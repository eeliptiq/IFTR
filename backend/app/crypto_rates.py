"""
What one coin is worth in dollars, for long enough to write a quote.

A fiat-priced bill has to be converted to a coin amount at some instant, and
that instant becomes part of the invoice: the rate, its source and its age are
stored with the quote, so "why did it ask for 0.0041 BTC?" has an answer weeks
later.

Two rules:

  * **fail closed.** No rate, an old rate or a nonsense rate means no invoice.
    Guessing here charges the customer the wrong amount, and crypto has no
    chargeback to undo it.
  * **short cache, short quote.** The feed is cached for a minute so a page
    refresh does not hammer it, and the quote it produces expires in fifteen.
    A quote that outlives its rate is a free option on the price.

The source is one URL (`CRYPTO_RATE_URL`) rather than a hard-coded vendor, which
is what lets a stub stand in during development and lets you point it at a
different feed without touching code. Two independent sources compared against
each other would be better still; that is listed as a follow-up rather than
pretended here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Mapping, Optional, Tuple

import httpx

from app.crypto import ASSETS, CryptoAsset, RateUnavailable, rate_url

REQUEST_TIMEOUT_SECONDS = 8.0

# Long enough to cover a page refresh, short enough that a moving market is
# noticed. The quote window below is the number that actually protects money.
CACHE_SECONDS = 60

# The identifiers the feed speaks. CoinGecko uses slugs, not tickers, and asking
# for "xmr" instead of "monero" is a silent empty answer.
FEED_IDS: Dict[str, str] = {asset.code: slug for asset, slug in (
    (ASSETS["btc"], "bitcoin"),
    (ASSETS["xmr"], "monero"),
)}

_cache: Dict[str, Tuple[int, float]] = {}


def _cached(asset_code: str) -> Optional[int]:
    entry = _cache.get(asset_code)
    if entry is None:
        return None
    cents, fetched_at = entry
    if time.monotonic() - fetched_at > CACHE_SECONDS:
        return None
    return cents


def clear_cache() -> None:
    """Forget what was fetched; the tests use this between fakes."""
    _cache.clear()


def _to_cents(value: object) -> int:
    """A feed's dollar price as integer cents, refusing anything unfittable."""
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RateUnavailable(f"the rate feed sent a price we cannot read: {value!r}") from exc

    if not price.is_finite() or price <= 0:
        raise RateUnavailable(f"the rate feed sent an unusable price: {value!r}")

    cents = int((price * 100).to_integral_value())
    if cents <= 0:
        raise RateUnavailable("the rate feed sent a price below one cent")
    return cents


async def fetch_rate_cents(
    asset: CryptoAsset, environ: Mapping[str, str]
) -> int:
    """USD cents for one whole coin, from the cache or the feed.

    Raises `RateUnavailable` rather than returning a default: a wrong rate is
    worse than no quote, because a wrong rate is a wrong charge.
    """
    cached = _cached(asset.code)
    if cached is not None:
        return cached

    slug = FEED_IDS.get(asset.code)
    if slug is None:
        raise RateUnavailable(f"no rate feed is known for {asset.code}")

    params = {"ids": slug, "vs_currencies": "usd"}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(rate_url(environ), params=params)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPError as exc:
        raise RateUnavailable(f"the rate feed could not be reached: {exc}") from exc
    except ValueError as exc:
        raise RateUnavailable("the rate feed answered with something else") from exc

    if not isinstance(body, dict):
        raise RateUnavailable("the rate feed answered with something else")

    entry = body.get(slug)
    if not isinstance(entry, dict) or "usd" not in entry:
        raise RateUnavailable(f"the rate feed has no dollar price for {slug}")

    cents = _to_cents(entry["usd"])
    _cache[asset.code] = (cents, time.monotonic())
    return cents
