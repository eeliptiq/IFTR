"""
Taking Bitcoin and Monero directly, without a payment processor.

There is no hosted page and no webhook in this world: a crypto payment is a
*quote* and a *watcher*.

  1. The customer picks an asset for an order. We quote a fiat-to-coin amount at
     a recorded exchange rate, valid for a few minutes, and hand out a fresh
     receiving address for that one invoice.
  2. A background watcher asks the wallet, on a timer, what has arrived at that
     address, and settles the order once enough has arrived with enough
     confirmations.

Three rules this module exists to keep:

  * money is counted in integer atomic units - satoshi for BTC, piconero for XMR
    - and never in floats. 0.1 BTC is not a number a float can hold, and an
    invoice that is off by one atomic unit can never be paid in full.
  * the amount comes from the stored order and the recorded rate, never from the
    browser. The quote keeps the rate it used, so a later argument about the
    price has an answer.
  * one fresh address per invoice. Reusing an address would leak every
    customer's history to every other customer and make "which order paid this?"
    unanswerable.

Nothing here opens a socket: `CryptoWallet` is the seam the HTTP adapters
implement, which is what lets the routes be driven with a wallet that has a
memory instead of a blockchain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Dict, List, Mapping, Optional, Protocol

ASSET_BTC = "btc"
ASSET_XMR = "xmr"

# A crypto invoice is stored in `order_payments.session_id` with this prefix.
# Both payment routes use it to tell "a Stripe session" from "an address we are
# watching", which is the difference between asking Stripe and asking nothing.
CRYPTO_SESSION_PREFIX = "crypto_"


class CryptoNotConfigured(Exception):
    """No wallet is configured on this deployment."""


class CryptoWalletError(Exception):
    """A wallet was asked and did not answer usefully."""


class RateUnavailable(Exception):
    """A fiat rate could not be established, so no quote can be made."""


@dataclass(frozen=True)
class CryptoAsset:
    """One coin, and the arithmetic that belongs to it alone."""

    code: str
    name: str
    unit: str
    decimals: int
    atomic_units: int
    uri_scheme: str
    default_confirmations: int
    # Below this, the network fee is a meaningful share of the bill.
    minimum_atomic: int

    def display(self, amount_atomic: int) -> str:
        """Atomic units as the amount a person types into their wallet."""
        whole, fraction = divmod(int(amount_atomic), self.atomic_units)
        if not fraction:
            return str(whole)
        return f"{whole}.{str(fraction).rjust(self.decimals, '0').rstrip('0')}"

    def uri(self, address: str, amount_atomic: int) -> str:
        """A wallet URI, so a QR code can carry the amount as well as the address.

        Bitcoin and Monero do not agree on the parameter name; both agree the
        amount is in whole coins, which is why `display` is the one formatter.
        """
        parameter = "amount" if self.code == ASSET_BTC else "tx_amount"
        return f"{self.uri_scheme}:{address}?{parameter}={self.display(amount_atomic)}"


BTC = CryptoAsset(
    code=ASSET_BTC,
    name="Bitcoin",
    unit="BTC",
    decimals=8,
    atomic_units=100_000_000,
    uri_scheme="bitcoin",
    # One block: the retail default. A reorg deeper than that at food-order
    # values is rare, and six confirmations is an hour of cold food.
    default_confirmations=1,
    minimum_atomic=1_000,
)

XMR = CryptoAsset(
    code=ASSET_XMR,
    name="Monero",
    unit="XMR",
    decimals=12,
    atomic_units=1_000_000_000_000,
    uri_scheme="monero",
    # Monero's own guidance is that funds are not spendable until ten
    # confirmations, but waiting twenty minutes for a delivery order defeats the
    # order. Two blocks is the deliberate compromise, and the risk is the same
    # one a card chargeback-free payment carries anyway: nothing after delivery.
    default_confirmations=2,
    # 0.01 XMR is the floor most XMR services accept.
    minimum_atomic=10_000_000_000,
)

ASSETS: Dict[str, CryptoAsset] = {BTC.code: BTC, XMR.code: XMR}


@dataclass(frozen=True)
class WalletReading:
    """What a wallet says about one address right now.

    `received_atomic` counts everything seen, including zero-confirmation
    transactions; `confirmed_atomic` counts only what has reached the required
    depth. The difference is the sentence "we can see it, it is not final yet".
    """

    received_atomic: int = 0
    confirmed_atomic: int = 0
    confirmations: int = 0
    txid: str = ""


class CryptoWallet(Protocol):
    """The slice of a wallet the invoice and watcher routes use."""

    asset_code: str

    async def new_address(self, label: str) -> str:
        """A fresh receiving address, labelled so an operator can find it."""

    async def received(self, address: str, *, confirmations: int) -> WalletReading:
        """What has arrived at `address`, and how deep the deepest payment is."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Long enough to open a wallet and scan a QR code, short enough that a sudden
# move in the price cannot be exploited by paying an old quote.
DEFAULT_QUOTE_MINUTES = 15

# After the timer ends an invoice is no longer offered, but it keeps being
# watched: a Bitcoin transaction can sit in the mempool for hours, and money
# that arrived late is still money. This is how long we keep looking.
DEFAULT_GRACE_HOURS = 24

# Below this, no crypto invoice is offered at all: the network fee would be a
# meaningful share of the bill.
DEFAULT_MIN_CHARGE_CENTS = 100


def _int_setting(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = (environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def confirmations_for(asset: CryptoAsset, environ: Mapping[str, str]) -> int:
    """How deep a payment must be before the order is treated as paid.

    A setting per asset rather than one number: a Monero block is two minutes
    and a Bitcoin block is ten, so the same count is a very different wait.
    """
    name = f"CRYPTO_{asset.code.upper()}_CONFIRMATIONS"
    value = _int_setting(environ, name, asset.default_confirmations)
    return max(0, value)


def quote_minutes(environ: Mapping[str, str]) -> int:
    return _int_setting(environ, "CRYPTO_QUOTE_MINUTES", DEFAULT_QUOTE_MINUTES)


def grace_hours(environ: Mapping[str, str]) -> int:
    return _int_setting(environ, "CRYPTO_GRACE_HOURS", DEFAULT_GRACE_HOURS)


def minimum_charge_cents(environ: Mapping[str, str]) -> int:
    return _int_setting(
        environ, "CRYPTO_MIN_CHARGE_CENTS", DEFAULT_MIN_CHARGE_CENTS
    )


# ---------------------------------------------------------------------------
# Quoting
# ---------------------------------------------------------------------------


def quoted_amount(
    asset: CryptoAsset, fiat_cents: int, rate_cents_per_coin: int
) -> int:
    """Atomic units for a fiat amount at a recorded rate.

    Rounded **up**, not to nearest: rounding down would systematically
    under-charge, and an invoice one atomic unit short is one that can never be
    settled by the amount it asks for.
    """
    if fiat_cents <= 0:
        raise ValueError("a quote needs a positive fiat amount")
    if rate_cents_per_coin <= 0:
        raise RateUnavailable("the exchange rate is not a usable number")

    units = Decimal(fiat_cents) * asset.atomic_units / Decimal(rate_cents_per_coin)
    return int(units.to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# Which wallets this deployment has
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CryptoWallets:
    """The wallets that are configured, keyed by asset code."""

    wallets: Dict[str, CryptoWallet]

    def for_asset(self, code: str) -> Optional[CryptoWallet]:
        return self.wallets.get(code)

    @property
    def assets(self) -> List[CryptoAsset]:
        return [ASSETS[code] for code in ASSETS if code in self.wallets]


def wallets_from_env(environ: Mapping[str, str]) -> Optional[CryptoWallets]:
    """The configured wallets, or None when this deployment accepts no crypto.

    None is a real state, like a missing Stripe key: orders still work, and the
    invoice route answers `503` with a sentence instead of crashing. The imports
    are local so this module stays free of HTTP clients.
    """
    from app.crypto_wallets import BitcoinCoreWallet, MoneroWalletRpc

    configured: Dict[str, CryptoWallet] = {}

    bitcoin_url = (environ.get("BITCOIN_RPC_URL") or "").strip()
    if bitcoin_url:
        configured[ASSET_BTC] = BitcoinCoreWallet(
            bitcoin_url,
            user=(environ.get("BITCOIN_RPC_USER") or "").strip(),
            password=(environ.get("BITCOIN_RPC_PASSWORD") or ""),
            wallet=(environ.get("BITCOIN_WALLET") or "").strip(),
        )

    monero_url = (environ.get("MONERO_WALLET_RPC_URL") or "").strip()
    if monero_url:
        configured[ASSET_XMR] = MoneroWalletRpc(
            monero_url,
            user=(environ.get("MONERO_WALLET_RPC_USER") or "").strip(),
            password=(environ.get("MONERO_WALLET_RPC_PASSWORD") or ""),
        )

    if not configured:
        return None

    return CryptoWallets(configured)


def rate_url(environ: Mapping[str, str]) -> str:
    """Where fiat rates come from. One URL, so a stub can stand in for the feed."""
    return (
        (environ.get("CRYPTO_RATE_URL") or "").strip()
        or "https://api.coingecko.com/api/v3/simple/price"
    )


def watcher_interval_seconds(environ: Mapping[str, str]) -> int:
    return _int_setting(environ, "CRYPTO_WATCH_INTERVAL_SECONDS", 30)
