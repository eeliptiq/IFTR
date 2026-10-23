"""
Keep the uploads directory tidy without anyone remembering to run the sweep.

app/uploads_gc.py does the actual work; this module runs it on a timer from the
FastAPI lifespan, so an orphan left behind by a replaced photo or a deleted menu
item is reclaimed on its own.

Tuning, via environment:
    UPLOADS_GC_INTERVAL_MINUTES   minutes between sweeps (default 60); 0 or
                                  less disables the background sweep entirely

The first sweep runs as soon as the app starts, then every interval after that.
The age guard in uploads_gc still applies, so a file uploaded moments before
someone restarts the server is not at risk.

One sweeper per process: start uvicorn with a single worker (the default, and
what run.sh does) so two processes do not sweep at the same time.
"""

import asyncio
import logging
import os
from typing import Optional

from app.database import async_session_factory
from app.uploads_gc import EmptyDatabaseError, cleanup_uploads, human_size

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_MINUTES = 60

INTERVAL_ENV_VAR = "UPLOADS_GC_INTERVAL_MINUTES"


def configured_interval_minutes() -> float:
    """Interval in minutes, falling back to the default when the value is unusable."""
    raw = os.getenv(INTERVAL_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_INTERVAL_MINUTES

    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "%s=%r is not a number; using %s minutes",
            INTERVAL_ENV_VAR,
            raw,
            DEFAULT_INTERVAL_MINUTES,
        )
        return DEFAULT_INTERVAL_MINUTES


async def run_sweep_once() -> None:
    """
    Run one sweep, reporting the outcome through the logger.

    A scheduled sweep must never bring the app down or stop the schedule, so
    failures are logged with their traceback and the next interval still runs.
    """
    try:
        async with async_session_factory() as session:
            report = await cleanup_uploads(session, delete=True, log_idle=False)
    except EmptyDatabaseError as exc:
        logger.error("uploads sweep refused to delete anything: %s", exc)
        return
    except Exception:
        logger.exception("uploads sweep failed; the next interval will retry")
        return

    if report.deleted:
        logger.info(
            "uploads sweep reclaimed %s from %d file(s)",
            human_size(report.deleted_bytes),
            len(report.deleted),
        )


async def sweep_forever(interval_minutes: Optional[float] = None) -> None:
    """Sweep now, then every interval, until the task is cancelled."""
    interval = configured_interval_minutes() if interval_minutes is None else interval_minutes

    if interval <= 0:
        logger.info("background uploads sweep is disabled (%s <= 0)", INTERVAL_ENV_VAR)
        return

    logger.info("background uploads sweep: every %s minutes", interval)
    while True:
        try:
            await run_sweep_once()
        except asyncio.CancelledError:
            logger.info("background uploads sweep stopped")
            raise
        except Exception:
            # run_sweep_once reports its own failures; this is the safety net that
            # keeps an unattended schedule from dying for the rest of the process.
            logger.exception("uploads sweep iteration crashed; continuing")

        try:
            await asyncio.sleep(interval * 60)
        except asyncio.CancelledError:
            logger.info("background uploads sweep stopped")
            raise
