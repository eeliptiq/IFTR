"""
Reclaim disk space from uploaded images that nothing references any more.

Uploaded images land in backend/uploads/ (see app/api/uploads.py). When an owner
replaces or clears a photo, or drops a menu item that had one, the old file stays
on disk: nothing points at it, but nothing removes it either. This module finds
those orphans and, when asked, deletes them.

What counts as a reference: every text/JSON column of every mapped table is
searched for a "/uploads/<name>" value. That means a photo kept only by a menu
item inside the restaurant's JSON menu is kept, and a table added later is
covered as soon as its ORM module exists - no list of fields to keep in sync.

Every run records what it found and what it reclaimed in a log file
(backend/logs/uploads_cleanup.log) and through the logging module, so the result
is readable after the fact instead of scrolling off a terminal.

Safety, in order of importance:
  * dry run by default - the caller has to opt in to deletion;
  * a file modified within `min_age_minutes` is never touched, because the UI
    uploads a file the moment it is picked while the record pointing at it is
    saved later, so a file that looks unreferenced may simply be mid-flow;
  * if no mapped table holds a single row, we refuse to delete (unless forced),
    so running against the wrong DATABASE_URL cannot empty the uploads folder.
"""

import importlib
import json
import logging
import os
import pkgutil
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from sqlalchemy import JSON, String, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.uploads import UPLOAD_DIR
from app.database import Base

logger = logging.getLogger(__name__)

# app/api/uploads.py names its files "<32 hex>.<ext>". Anything else sitting in
# the directory was put there by hand, so we leave it alone.
MANAGED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|gif|webp)$")

# Any "/uploads/<name>" inside a stored value counts as a reference to <name>.
UPLOAD_REFERENCE_RE = re.compile(r"/uploads/([^/?#\s\"'\\]+)")

DEFAULT_MIN_AGE_MINUTES = 60

# Run history, kept outside uploads/ so the sweep never has to skip its own log.
# app/uploads_gc.py -> parents[1] is backend/, alongside uploads/ and iftr.db.
# UPLOADS_GC_LOG overrides the destination (tests write to a temporary file).
LOG_PATH = Path(
    os.getenv("UPLOADS_GC_LOG") or Path(__file__).resolve().parents[1] / "logs" / "uploads_cleanup.log"
)


class EmptyDatabaseError(RuntimeError):
    """Raised when deletion is requested against a database with no rows."""


def human_size(size: int) -> str:
    """Render a byte count the way the log and the CLI report it."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@dataclass
class CleanupReport:
    """What the sweep found, and what it did about it."""

    dry_run: bool = True
    files_on_disk: int = 0
    total_bytes: int = 0
    referenced_names: int = 0
    referenced_present: int = 0
    unmanaged: List[str] = field(default_factory=list)
    missing_tables: List[str] = field(default_factory=list)
    orphans: List[Path] = field(default_factory=list)
    # name -> size, captured while scanning: a deleted file can no longer be stat'ed.
    orphan_sizes: Dict[str, int] = field(default_factory=dict)
    orphan_bytes: int = 0
    too_new: List[Path] = field(default_factory=list)
    deleted: List[Path] = field(default_factory=list)
    deleted_bytes: int = 0
    note: Optional[str] = None
    log_path: Optional[Path] = None
    log_error: Optional[str] = None

    def size_of(self, path: Path) -> int:
        return self.orphan_sizes.get(path.name, 0)

    def is_idle(self) -> bool:
        """True when there was nothing to act on: no orphans, no deletions, no refusal."""
        return not self.orphans and not self.deleted and not self.note

    def summary(self) -> str:
        """One line describing the run, for the log file, the console and logging."""
        if self.dry_run:
            outcome = f"{len(self.orphans)} orphan(s) found, {human_size(self.orphan_bytes)}"
        else:
            outcome = f"{len(self.deleted)} file(s) deleted, {human_size(self.deleted_bytes)} reclaimed"
        line = (
            f"{'dry run' if self.dry_run else 'delete'}: {outcome} | "
            f"on disk {self.files_on_disk} ({human_size(self.total_bytes)}), "
            f"referenced {self.referenced_names}, "
            f"too new {len(self.too_new)}, "
            f"unmanaged {len(self.unmanaged)}"
        )
        return f"{line} | {self.note}" if self.note else line

    def log_lines(self, timestamp: Optional[str] = None) -> List[str]:
        """The readable block this run appends to the log file."""
        stamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = [f"{stamp}  {self.summary()}"]
        # Label each file by what actually happened to it: a refusal run must not
        # read later as if the files had been deleted.
        for path in self.orphans:
            if path in self.deleted:
                label = "deleted"
            elif self.dry_run:
                label = "would delete"
            else:
                label = "not deleted"
            lines.append(f"  {label}: {path.name} ({human_size(self.size_of(path))})")
        if self.unmanaged:
            lines.append(f"  left alone (not ours): {', '.join(self.unmanaged)}")
        if self.missing_tables:
            lines.append(f"  no table yet, skipped: {', '.join(self.missing_tables)}")
        return lines


def load_orm_models() -> int:
    """
    Import every app.models.*_orm module so its tables join Base.metadata.

    Importing app.database alone leaves the registry empty, which would make the
    sweep report every file as unreferenced. Discovering the modules by their
    naming convention means a table added later is covered without an edit here.
    """
    import app.models as models_package

    loaded = 0
    for module in pkgutil.iter_modules(models_package.__path__):
        if module.name.endswith("_orm"):
            importlib.import_module(f"app.models.{module.name}")
            loaded += 1
    return loaded


def write_log(
    report: CleanupReport, path: Optional[Union[Path, str]] = None
) -> Optional[Path]:
    """
    Append this run to the cleanup log, creating the directory if needed.

    `path` may be a Path or a string (argparse hands over strings); omit it for
    the module default. A log that cannot be written must not undo a sweep that
    already happened, so the reason is recorded on the report and logged rather
    than raised.
    """
    target = Path(LOG_PATH if path is None else path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(report.log_lines()) + "\n\n")
    except OSError as exc:
        report.log_error = f"{exc.__class__.__name__}: {exc}"
        logger.warning("could not write the uploads cleanup log to %s: %s", target, exc)
        return None

    report.log_path = target
    return target


def _names_in(value: Any) -> Set[str]:
    """Upload filenames referenced by a single stored value."""
    if value is None:
        return set()
    if not isinstance(value, str):
        # A JSON column comes back as a list/dict; flatten it back to text.
        value = json.dumps(value, default=str)
    return {os.path.basename(name) for name in UPLOAD_REFERENCE_RE.findall(value)}


def _reference_candidates(table) -> List[Any]:
    """Columns that can hold a URL: strings and JSON (menu, settings, ...)."""
    return [column for column in table.columns if isinstance(column.type, (String, JSON))]


async def _table_names(session: AsyncSession) -> Set[str]:
    """Tables that actually exist in the connected database."""

    def _inspect(sync_session) -> Set[str]:
        return set(inspect(sync_session.get_bind()).get_table_names())

    return await session.run_sync(_inspect)


async def _referenced_names(
    session: AsyncSession, tables: Set[str]
) -> Tuple[Set[str], List[str]]:
    """Return the referenced upload filenames, plus models whose table is absent."""
    referenced: Set[str] = set()
    missing: List[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            missing.append(table.name)
            continue
        for column in _reference_candidates(table):
            # Cast so a JSON/JSONB column can be searched the same way as text.
            stmt = select(column).where(func.cast(column, String).like("%/uploads/%"))
            for (value,) in (await session.execute(stmt)).all():
                referenced.update(_names_in(value))

    return referenced, missing


async def _database_is_empty(session: AsyncSession, tables: Set[str]) -> bool:
    """True when no existing mapped table holds a row."""
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        if await session.scalar(select(func.count()).select_from(table)):
            return False
    return True


async def cleanup_uploads(
    session: AsyncSession,
    *,
    delete: bool = False,
    min_age_minutes: int = DEFAULT_MIN_AGE_MINUTES,
    force: bool = False,
    log_path: Optional[Union[Path, str]] = LOG_PATH,
    log_idle: bool = True,
    now: Optional[datetime] = None,
) -> CleanupReport:
    """
    Sweep UPLOAD_DIR and report unreferenced files, deleting them only if asked.

    Every run is appended to `log_path` (pass None to skip) and emitted through
    the logging module. Pass log_idle=False to leave idle runs out of the log,
    which keeps a frequent background sweep from burying real events.

    Raises EmptyDatabaseError if deletion is requested while no mapped table has
    any rows, unless `force` is set; the refusal itself is logged first.
    """
    report = CleanupReport(dry_run=not delete)

    load_orm_models()
    tables = await _table_names(session)
    referenced, missing = await _referenced_names(session, tables)
    report.referenced_names = len(referenced)
    report.missing_tables = missing

    if UPLOAD_DIR.is_dir():
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=min_age_minutes)

        for path in sorted(UPLOAD_DIR.iterdir()):
            if not path.is_file():
                continue
            if not MANAGED_NAME_RE.match(path.name):
                report.unmanaged.append(path.name)
                continue

            size = path.stat().st_size
            report.files_on_disk += 1
            report.total_bytes += size

            if path.name in referenced:
                report.referenced_present += 1
                continue

            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified > cutoff:
                report.too_new.append(path)
                continue

            report.orphans.append(path)
            report.orphan_sizes[path.name] = size
            report.orphan_bytes += size

    if delete and report.orphans:
        if not force and await _database_is_empty(session, tables):
            report.note = (
                f"refused: {len(report.orphans)} file(s) look unreferenced but no table "
                "holds a row - check DATABASE_URL"
            )
        else:
            for path in report.orphans:
                size = report.size_of(path)
                try:
                    path.unlink()
                except FileNotFoundError:
                    # Another sweep or an operator removed it first.
                    logger.debug("uploads sweep: %s was already gone", path.name)
                    continue
                report.deleted.append(path)
                report.deleted_bytes += size

    if log_path is not None and (log_idle or not report.is_idle()):
        write_log(report, log_path)

    if report.is_idle():
        logger.debug("uploads sweep - nothing to reclaim")
    else:
        logger.info("uploads cleanup - %s", report.summary())

    if report.note:
        raise EmptyDatabaseError(
            f"{report.note}. Pass --force to delete anyway."
        )

    return report
