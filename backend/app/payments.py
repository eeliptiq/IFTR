"""
Stripe Checkout, behind one seam.

The endpoints do not call Stripe directly: this module is the only place that
knows the provider's SDK, and they depend on the `PaymentGateway` protocol below
rather than on `StripeGateway`. That is what lets the payment tests drive the
real routes - ownership checks, amount checks, idempotency, webhook replay -
with a fake gateway, and still leaves production talking to Stripe through the
official client.

Three rules the rest of the app relies on:

  * what is charged comes from the stored order, never from the client;
  * the status of a payment is whatever the provider says, not what the success
    page's query string says;
  * a session may only settle the order it names, and only for the amount that
    order was billed.

Nothing here reads the database. The routes own the rows; this module owns the
conversation with Stripe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Protocol

import stripe

logger = logging.getLogger(__name__)

# The app bills in US dollars only (see app/pricing.py); Stripe wants the
# smallest unit and a lower-case currency code.
CURRENCY = "usd"

# Stripe refuses charges below this in USD. Checking here turns a provider
# error into a sentence the customer can act on.
MIN_CHARGE_CENTS = 50


class PaymentsNotConfigured(Exception):
    """No Stripe key (or webhook secret) is configured on this deployment."""


class PaymentProviderError(Exception):
    """Stripe was asked and did not answer usefully."""


class InvalidWebhookSignature(Exception):
    """The webhook body does not match the signature Stripe sent with it."""


# A sentinel so `_field` can tell "the attribute is absent" from "the value is
# None", which matters for fields Stripe includes as JSON null.
_MISSING = object()


@dataclass(frozen=True)
class CheckoutLine:
    """One line on the hosted Checkout page, priced in cents."""

    label: str
    amount_cents: int


@dataclass(frozen=True)
class CheckoutSession:
    """A hosted Checkout page, ready to redirect to."""

    session_id: str
    url: str
    amount_cents: int
    currency: str


@dataclass(frozen=True)
class SessionState:
    """What Stripe currently says about a Checkout session."""

    session_id: str
    # Stripe's payment state: unpaid / paid / no_payment_required.
    payment_status: str
    # Stripe's session state: open / complete / expired.
    status: str
    amount_cents: int
    currency: str
    payment_intent_id: Optional[str]
    # The order this session was opened for, from client_reference_id and the
    # metadata written when it was created.
    order_id: str


class PaymentGateway(Protocol):
    """The slice of Stripe the checkout, status and webhook routes use."""

    async def create_checkout(
        self,
        *,
        order_id: str,
        customer_id: str,
        customer_email: str,
        lines: List[CheckoutLine],
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> CheckoutSession:
        ...

    async def retrieve(self, session_id: str) -> SessionState:
        ...

    def parse_webhook(self, payload: bytes, signature: str) -> Any:
        ...


def to_cents(amount: float) -> int:
    """Dollars as an integer number of cents, rounding half-up like a till.

    `round()` on a float would turn 2.675 into 2.67; Decimal on the string
    representation gives the number a person would write on the bill.
    """
    return int(
        (Decimal(str(amount or 0)) * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _field(value: Any, name: str, default: Any = None) -> Any:
    """Read one field from a Stripe object or a plain mapping.

    Stripe's models are *not* mappings in the v16 SDK - `StripeObject` raises on
    `.get` and exposes fields as attributes, including nested ones. The fake
    gateway in the tests returns dictionaries. One accessor keeps both readable.
    """
    if isinstance(value, Mapping):
        return value.get(name, default)

    # `getattr` with a default swallows the AttributeError StripeObject raises
    # for dict methods, so this branch is safe for both shapes.
    found = getattr(value, name, _MISSING)
    if found is not _MISSING:
        return found

    getter = getattr(value, "get", None)
    if callable(getter):
        try:
            return getter(name, default)
        except TypeError:
            pass

    return default


def state_from_session(session: Any) -> SessionState:
    """Normalise a Stripe session (or a test's stand-in) into `SessionState`."""
    metadata = _field(session, "metadata") or {}
    order_id = _field(metadata, "order_id") or _field(
        session, "client_reference_id", ""
    ) or ""

    payment_intent = _field(session, "payment_intent")
    if payment_intent is not None and not isinstance(payment_intent, str):
        payment_intent = _field(payment_intent, "id")

    return SessionState(
        session_id=str(_field(session, "id", "") or ""),
        payment_status=str(_field(session, "payment_status", "unpaid") or "unpaid"),
        status=str(_field(session, "status", "open") or "open"),
        amount_cents=int(_field(session, "amount_total", 0) or 0),
        currency=str(_field(session, "currency", CURRENCY) or CURRENCY),
        payment_intent_id=payment_intent,
        order_id=str(order_id),
    )


@lru_cache(maxsize=4)
def _client(secret_key: str) -> stripe.StripeClient:
    """One client per key, so connection pooling is not thrown away per request."""
    return stripe.StripeClient(secret_key, max_network_retries=2)


class StripeGateway:
    """The real gateway: Stripe Checkout over the official SDK."""

    def __init__(self, secret_key: str, webhook_secret: str = ""):
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret

    async def create_checkout(
        self,
        *,
        order_id: str,
        customer_id: str,
        customer_email: str,
        lines: List[CheckoutLine],
        amount_cents: int,
        currency: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> CheckoutSession:
        params: Dict[str, Any] = {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": currency,
                        "unit_amount": line.amount_cents,
                        "product_data": {"name": line.label},
                    },
                }
                for line in lines
            ],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": order_id,
            "metadata": {"order_id": order_id, "customer_id": customer_id},
            "payment_intent_data": {"metadata": {"order_id": order_id}},
        }
        if customer_email:
            params["customer_email"] = customer_email

        try:
            session = await _client(self._secret_key).v1.checkout.sessions.create_async(
                params, {"idempotency_key": idempotency_key}
            )
        except stripe.StripeError as exc:
            logger.warning("Stripe refused to create a checkout session: %s", exc)
            raise PaymentProviderError(str(exc)) from exc

        url = _field(session, "url")
        if not url:
            raise PaymentProviderError("Stripe returned a session without a URL")

        return CheckoutSession(
            session_id=str(_field(session, "id", "")),
            url=str(url),
            amount_cents=amount_cents,
            currency=currency,
        )

    async def retrieve(self, session_id: str) -> SessionState:
        try:
            session = await _client(self._secret_key).v1.checkout.sessions.retrieve_async(
                session_id
            )
        except stripe.StripeError as exc:
            logger.warning("Stripe could not retrieve session %s: %s", session_id, exc)
            raise PaymentProviderError(str(exc)) from exc
        return state_from_session(session)

    def parse_webhook(self, payload: bytes, signature: str) -> Any:
        if not self._webhook_secret:
            raise PaymentsNotConfigured("STRIPE_WEBHOOK_SECRET is not set")
        try:
            return stripe.Webhook.construct_event(
                payload, signature, self._webhook_secret
            )
        except (stripe.SignatureVerificationError, ValueError) as exc:
            raise InvalidWebhookSignature(str(exc)) from exc


def webhook_event_type(event: Any) -> str:
    """The event's `type`, from a Stripe Event or a test's mapping."""
    return str(_field(event, "type", "") or "")


def webhook_event_id(event: Any) -> str:
    """The event's `evt_...` id, or "" for a body that never parsed."""
    return str(_field(event, "id", "") or "")


def webhook_event_object(event: Any) -> Any:
    """The `data.object` a provider event carries.

    Stripe's Event is not a mapping, so `event["data"]` and `event.get(...)`
    both fail; the fields are attributes. This is the one place that knows it.
    """
    data = _field(event, "data")
    if data is None:
        return {}
    return _field(data, "object", {}) or {}


def gateway_from_env(environ: Mapping[str, str]) -> Optional[StripeGateway]:
    """The configured gateway, or None when this deployment takes no money.

    None is a real state, not an error: a local checkout with no Stripe account
    still places orders. The checkout route turns it into a `503` with a
    sentence rather than a `500` with a stack trace.
    """
    secret_key = (environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not secret_key:
        return None

    return StripeGateway(
        secret_key, (environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    )


# ---------------------------------------------------------------------------
# Reading the configuration without reading the secret
# ---------------------------------------------------------------------------

KEY_MODE_TEST = "test"
KEY_MODE_LIVE = "live"
# No key: checkout answers 503 and orders stay payable. A supported state.
KEY_MODE_UNSET = "unset"
# Something is set, but not in a shape Stripe issues. Checkout will try it and
# Stripe will refuse, which is worth saying out loud rather than discovering
# from a 502 at the first payment.
KEY_MODE_UNRECOGNISED = "unrecognised"

KEY_KIND_SECRET = "secret"
KEY_KIND_RESTRICTED = "restricted"


def _key_prefix(environ: Mapping[str, str]) -> str:
    """`sk_test`, `rk_live`, ... - the part of the key that is not a secret.

    Stripe puts the key's kind and mode in its first two segments, which is
    everything a support screen needs to know about it and nothing a credential
    is made of. The rest of the string never leaves this function.
    """
    secret_key = (environ.get("STRIPE_SECRET_KEY") or "").strip()
    if not secret_key:
        return ""
    parts = secret_key.split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else ""


def secret_key_mode(environ: Mapping[str, str]) -> str:
    """Whether the configured key charges test cards or real ones.

    This is the single most consequential fact about a payment configuration: a
    live key where a test key was expected is the difference between a sandbox
    and somebody's card. It is reported as one of four words, never as the key.
    """
    prefix = _key_prefix(environ)
    if not prefix:
        return KEY_MODE_UNSET
    if prefix in ("sk_live", "rk_live"):
        return KEY_MODE_LIVE
    if prefix in ("sk_test", "rk_test"):
        return KEY_MODE_TEST
    return KEY_MODE_UNRECOGNISED


def secret_key_kind(environ: Mapping[str, str]) -> str:
    """`secret` or `restricted`, because a restricted key can be missing a
    permission the Checkout call needs - a `403` from Stripe that otherwise
    looks like any other provider error."""
    prefix = _key_prefix(environ)
    if not prefix:
        return KEY_MODE_UNSET
    if prefix.startswith("sk_"):
        return KEY_KIND_SECRET
    if prefix.startswith("rk_"):
        return KEY_KIND_RESTRICTED
    return KEY_MODE_UNRECOGNISED
