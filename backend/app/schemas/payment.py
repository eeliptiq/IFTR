"""
Request and response models for the payment routes.

The client's side of the contract is small on purpose: checkout takes an order
id, and the success page polls a session id it did not choose. Everything that
decides money - the amount, the line items, whether the order may be paid at all
- is read server-side and never appears in a request.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.crypto import CryptoDiagnostics


class CheckoutRequest(BaseModel):
    """Start paying for an order the caller placed."""

    order_id: str = Field(min_length=1)

    # Where to send the customer back to. Checked against the API's allowed
    # origins before use; absent falls back to the dev frontend.
    origin_url: Optional[str] = None


class CheckoutResponse(BaseModel):
    """The hosted page to redirect to, and what it will charge."""

    order_id: str
    session_id: str
    url: str
    amount_total: int
    currency: str


class PaymentStatusResponse(BaseModel):
    """The answer the success page polls for.

    `payment_status` is the app's vocabulary (pending / paid / failed), while
    `status` is Stripe's session state (open / complete / expired). The page
    reads both: paid ends the wait, expired ends it the other way.
    """

    order_id: str
    session_id: str
    payment_status: str
    status: str
    amount_total: int
    currency: str


class WebhookResponse(BaseModel):
    received: bool = True
    # What, if anything, the event changed. Useful in the Stripe dashboard's
    # delivery log without leaking anything about the customer.
    handled: Optional[str] = None


class WebhookDeliverySummary(BaseModel):
    """The last notification Stripe sent, and how many arrived recently."""

    # The most recent delivery of any kind, refused ones included: the question
    # is whether this server is being reached, not whether it was happy.
    last_received_at: Optional[datetime] = None
    last_event_type: Optional[str] = None
    # settled | ignored | unmatched | unhandled | rejected | unconfigured
    last_outcome: Optional[str] = None
    # The most recent delivery whose signature checked out, and the most recent
    # one whose did not. A rejection with no verified delivery beside it is the
    # signature of a copied-that-secret-from-elsewhere mistake.
    last_verified_at: Optional[datetime] = None
    last_rejected_at: Optional[datetime] = None
    received_24h: int = 0
    rejected_24h: int = 0


class PaymentDiagnosticsResponse(BaseModel):
    """What this deployment's Stripe settings are, without the settings.

    Four states look identical from the customer's side - no key, a live key, a
    key with no signing secret, and a listener that is not forwarding - and
    this response tells them apart. No part of a key appears here, not even a
    masked tail: `key_mode` and `key_kind` are the parts of the key Stripe does
    not consider secret, and they are the parts that explain the failure.
    """

    checked_at: datetime

    # Is a key set at all, and therefore does the Pay button do anything?
    configured: bool
    checkout_available: bool
    # test | live | unset | unrecognised
    key_mode: str
    # secret | restricted | unset | unrecognised
    key_kind: str
    # A live key charges real cards. Called out separately from `key_mode`
    # because it is the one field nobody should have to interpret.
    live_mode: bool

    # Whether Stripe's events can be verified, and where they are sent.
    webhook_secret_configured: bool
    webhook_path: str
    # The event types the route acts on. Anything else is acknowledged and
    # ignored, which is what `last_outcome = unhandled` looks like later.
    handled_events: List[str] = Field(default_factory=list)

    currency: str
    min_charge_cents: int

    # Sentences for the misconfigurations that are visible from here, in the
    # order an operator should read them. Empty when nothing is wrong.
    warnings: List[str] = Field(default_factory=list)

    webhook: WebhookDeliverySummary

    # Bitcoin and Monero: what is configured, and how many invoices the watcher
    # is holding. No wallet is contacted - this endpoint has to answer when the
    # node is the thing that is broken.
    crypto: CryptoDiagnostics
