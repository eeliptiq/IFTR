"""
The client's side of the crypto contract.

Two shapes matter. The invoice is what a customer needs in order to pay: an
address, an amount they can type, the same pair as a wallet URI for a QR code,
and when the quote stops being valid. The status is what the page polls: how
much has arrived, how deep it is, and whether the order is settled.

Amounts appear twice on purpose - `amount` as a decimal string for humans and
`amount_atomic` as the integer the server actually compares against the chain.
The browser never sends either one back.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CryptoAssetOption(BaseModel):
    """One coin this deployment can invoice, with the policy applied to it."""

    code: str
    name: str
    unit: str
    # How deep a payment must be before the order is treated as paid.
    confirmations_required: int
    # Smallest invoice worth the network fee, as a decimal string.
    minimum: str


class CryptoMethods(BaseModel):
    enabled: bool = False
    assets: List[CryptoAssetOption] = Field(default_factory=list)


class PaymentMethodsResponse(BaseModel):
    """What the Pay buttons may offer.

    Public: it says which payment methods exist, not how they are configured. A
    customer needs it to choose; nobody needs it to be a secret.
    """

    card_available: bool
    crypto: CryptoMethods


class CryptoInvoiceRequest(BaseModel):
    order_id: str = Field(min_length=1)
    # `btc` or `xmr`; validated against the configured assets, not a free string.
    asset: str = Field(min_length=1)


class CryptoInvoiceResponse(BaseModel):
    order_id: str
    invoice_id: str
    asset: str
    asset_name: str
    unit: str

    address: str
    # What to send: the decimal the wallet shows, and the integer it is compared
    # against. `uri` is the same thing as a `bitcoin:`/`monero:` link for a QR.
    amount: str
    amount_atomic: int
    uri: str

    # The quote itself, kept beside the amount so the price can be replayed.
    fiat_total_cents: int
    currency: str
    rate_cents_per_coin: int
    confirmations_required: int

    status: str
    expires_at: datetime
    grace_until: datetime


class CryptoStatusResponse(BaseModel):
    order_id: str
    invoice_id: str
    asset: str

    address: str
    amount: str
    amount_atomic: int

    # `awaiting` / `partial` / `confirmed` / `expired`, plus the depth that
    # decides the difference between "seen" and "settled".
    status: str
    received: str
    received_atomic: int
    confirmed_atomic: int
    confirmations: int
    confirmations_required: int
    txid: str = ""

    expires_at: datetime
    grace_until: datetime

    # The order's own payment state, which is what the kitchen reads.
    payment_status: str
    # False when the wallet could not be asked on this poll: the page keeps its
    # countdown and keeps asking rather than reporting a failure to pay.
    wallet_ok: bool = True


class CryptoDiagnostics(BaseModel):
    """What an operator needs to know, without a node being asked."""

    enabled: bool
    assets: List[str] = Field(default_factory=list)
    quote_minutes: int
    grace_hours: int
    minimum_charge_cents: int
    watcher_interval_seconds: int
    open_invoices: int = 0
    confirmed_invoices: int = 0
    last_confirmed_at: Optional[datetime] = None
    warnings: List[str] = Field(default_factory=list)
