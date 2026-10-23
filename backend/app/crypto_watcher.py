"""
Ask the wallets on a timer, so a payment is noticed even if the page is closed.

A crypto payment has no callback: nobody tells this server that money moved. The
page polls while it is open, which covers the customer who waits; this task
covers the one who closes the tab, which is the case the card flow handles with
a webhook and this one cannot.

Tuning, via environment:

    CRYPTO_WATCH_INTERVAL_SECONDS   seconds between sweeps (default 30); 0 or
                                    less disables the background sweep
    CRYPTO_BTC_CONFIRMATIONS        depth before a Bitcoin payment settles (1)
    CRYPTO_XMR_CONFIRMATIONS        depth before a Monero payment settles (2)

The sweep is skipped entirely when no wallet is configured, so a deployment that
takes no crypto does no work and logs nothing.

One watcher per process, like the uploads sweep: run uvicorn with one worker.
Two watchers would not double-settle anything - settlement is guarded - but they
would double the wallet traffic.
"""

import asyncio
import logging
import os
from typing import Optional

from app.crypto import wallets_from_env, watcher_interval_seconds
from app.crypto_flow import poll_open_invoices
from app.database import async_session_factory

logger = logging.getLogger(__name__)

INTERVAL_ENV_VAR = "CRYPTO_WATCH_INTERVAL_SECONDS"


async def run_poll_once() -> int:
    """One sweep. Returns how many invoices were checked.

    A failure is logged and swallowed: an unreachable wallet must not stop the
    schedule, because the next sweep is the retry.
    """
    wallets = wallets_from_env(os.environ)
    if wallets is None:
        return 0

    try:
        async with async_session_factory() as session:
            checked = await poll_open_invoices(session, wallets)
            await session.commit()
    except Exception:
        logger.exception("crypto sweep failed; the next interval will retry")
        return 0

    if checked:
        logger.debug("crypto sweep checked %d invoice(s)", checked)
    return checked


async def watch_forever(interval_seconds: Optional[int] = None) -> None:
    """Sweep now, then every interval, until the task is cancelled."""
    interval = (
        watcher_interval_seconds(os.environ)
        if interval_seconds is None
        else interval_seconds
    )

    if interval <= 0:
        logger.info("background crypto watcher is disabled (%s <= 0)", INTERVAL_ENV_VAR)
        return

    wallets = wallets_from_env(os.environ)
    if wallets is None:
        logger.info("background crypto watcher is idle: no wallet is configured")
        return

    logger.info(
        "background crypto watcher: every %s seconds for %s",
        interval,
        ", ".join(asset.name for asset in wallets.assets),
    )
    while True:
        try:
            await run_poll_once()
        except asyncio.CancelledError:
            logger.info("background crypto watcher stopped")
            raise
        except Exception:
            # run_poll_once reports its own failures; this keeps an unattended
            # schedule from dying for the rest of the process.
            logger.exception("crypto sweep iteration crashed; continuing")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("background crypto watcher stopped")
            raise
