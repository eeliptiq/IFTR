#!/usr/bin/env python
"""
Delete uploaded images that no record references any more.

Dry run by default - it reports what would go and removes nothing:

    python cleanup_uploads.py                     # report only
    python cleanup_uploads.py --delete            # remove the orphans
    python cleanup_uploads.py --delete --min-age-minutes 0

Each run is appended to backend/logs/uploads_cleanup.log, so the result is still
readable afterwards instead of scrolling off the terminal. Use --log-file to
write somewhere else, or --no-log to skip it.

Run it from the backend directory (or via `./run.sh cleanup-uploads --delete`)
so the app package and its DATABASE_URL resolve the same way the server's do.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

from app.database import async_session_factory
from app.uploads_gc import (
    DEFAULT_MIN_AGE_MINUTES,
    LOG_PATH,
    EmptyDatabaseError,
    cleanup_uploads,
    human_size,
)


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cleanup_uploads.py",
        description="Delete uploaded images that no record references any more.",
        epilog="Without --delete this is a dry run: it removes nothing.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove the orphaned files (default: report only)",
    )
    parser.add_argument(
        "--min-age-minutes",
        type=int,
        default=DEFAULT_MIN_AGE_MINUTES,
        metavar="N",
        help=(
            "never touch a file modified in the last N minutes "
            f"(default {DEFAULT_MIN_AGE_MINUTES}; 0 disables the guard)"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete even when the database looks empty",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=str(LOG_PATH),
        metavar="PATH",
        help=f"where to append this run's result (default {LOG_PATH})",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="do not write a log entry for this run",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    log_path = None if args.no_log else Path(args.log_file)
    refusal: Optional[str] = None

    async with async_session_factory() as session:
        try:
            report = await cleanup_uploads(
                session,
                delete=args.delete,
                min_age_minutes=args.min_age_minutes,
                force=args.force,
                log_path=log_path,
            )
        except EmptyDatabaseError as exc:
            refusal = str(exc)

    if refusal is not None:
        print(f"refusing to delete: {refusal}", file=sys.stderr)
        if log_path:
            print(f"logged the refusal to {log_path}", file=sys.stderr)
        return 2

    print(f"files on disk:      {report.files_on_disk} ({human_size(report.total_bytes)})")
    print(f"referenced in db:   {report.referenced_names} ({report.referenced_present} present)")
    print(f"orphaned:           {len(report.orphans)} ({human_size(report.orphan_bytes)})")
    print(f"too new to touch:   {len(report.too_new)} (within {args.min_age_minutes} min)")
    if report.unmanaged:
        print(f"unmanaged (left):   {len(report.unmanaged)}  {', '.join(report.unmanaged)}")

    if report.dry_run:
        if report.orphans:
            print("\ndry run - nothing deleted. Would remove:")
            for path in report.orphans:
                print(f"  - {path.name} ({human_size(report.size_of(path))})")
            print("\nre-run with --delete to remove them")
        else:
            print("\nnothing to clean up")
    elif report.deleted:
        print(f"\ndeleted {len(report.deleted)} file(s), reclaimed {human_size(report.deleted_bytes)}")
    else:
        print("\nnothing to clean up")

    if report.log_error:
        print(f"WARNING: could not write the log: {report.log_error}", file=sys.stderr)
    elif report.log_path:
        print(f"\nlogged this run to {report.log_path}")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
