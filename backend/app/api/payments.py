"""
Paying for an order: Stripe Checkout, the success page's poll, and the webhook.

The customer's path is three steps, and each one can fail without losing money:

  1. `POST /payments/checkout` mints a hosted Checkout session for an order the
     caller owns and returns its URL. The amount comes from the stored order;
     the request carries no money at all.
  2. Checkout sends the browser back to `/payment/success?session_id=...`, and
     the page polls `GET /payments/status/{session_id}`. The answer is read from
     Stripe, not from the query string, so a hand-edited URL cannot mark an
     order paid.
  3. `POST /payments/webhook` is Stripe's own notification. It is the half that
     works when the customer closes the tab after paying, and it is verified
     against `STRIPE_WEBHOOK_SECRET` before it can change anything.

Who may ask about a session: only the customer whose order it is. Session ids
are unguessable, but an id in a success URL is not a credential - the token on
the request is what decides, and a session that belongs to somebody else is
answered exactly like one that does not exist.

When no Stripe key is configured, checkout answers `503` with a sentence. That
is a supported state: the order has already been placed, the checkout screen
says no charge was made, and the kitchen still sees the order. `payment_status`
stays `pending`, which is the truth.

`GET /payments/diagnostics` is the view from the operator's side: which of those
settings are active, whether the key is a test one or a live one, and when
Stripe last managed to reach this server. It reads the environment and the
delivery table and never calls Stripe, so it still answers when the thing it is
describing is broken. No part of a key appears in it.
"""

import logging
import os
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._lookups import order_or_none, restaurant_or_none
from app.core.auth import get_current_user, require_role
from app.cors import allowed_origin_regex, allowed_origins
from app.crypto import (
    CRYPTO_SESSION_PREFIX,
    confirmations_for,
    grace_hours,
    minimum_charge_cents as crypto_minimum_charge_cents,
    quote_minutes,
    wallets_from_env,
    watcher_interval_seconds,
)
from app.database import async_session_factory, get_db
from app.models.general import OrderStatus, UserRole
from app.models.crypto_orm import (
    CRYPTO_CONFIRMED,
    OPEN_STATUSES,
    OrderCryptoInvoiceRecord,
)
from app.models.order_orm import OrderRecord
from app.models.payment_orm import (
    PAYMENT_FAILED,
    PAYMENT_PAID,
    PAYMENT_PENDING,
    OrderPaymentRecord,
)
from app.models.user_orm import UserRecord
from app.models.webhook_orm import (
    OUTCOME_IGNORED,
    OUTCOME_REJECTED,
    OUTCOME_SETTLED,
    OUTCOME_UNCONFIGURED,
    OUTCOME_UNHANDLED,
    OUTCOME_UNMATCHED,
    PaymentWebhookDeliveryRecord,
)
from app.payments import (
    CURRENCY,
    KEY_KIND_RESTRICTED,
    KEY_MODE_LIVE,
    KEY_MODE_TEST,
    KEY_MODE_UNRECOGNISED,
    KEY_MODE_UNSET,
    MIN_CHARGE_CENTS,
    CheckoutLine,
    InvalidWebhookSignature,
    PaymentGateway,
    PaymentProviderError,
    PaymentsNotConfigured,
    SessionState,
    gateway_from_env,
    secret_key_kind,
    secret_key_mode,
    state_from_session,
    to_cents,
    webhook_event_id,
    webhook_event_object,
    webhook_event_type,
)
from app.schemas._time import as_utc
from app.schemas.crypto import CryptoDiagnostics
from app.schemas.payment import (
    CheckoutRequest,
    CheckoutResponse,
    PaymentDiagnosticsResponse,
    PaymentStatusResponse,
    WebhookDeliverySummary,
    WebhookResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

# The events that can change a payment. Everything else Stripe sends is
# acknowledged and ignored: returning an error for an event we do not handle
# would make Stripe retry it forever.
CHECKOUT_COMPLETED = "checkout.session.completed"
CHECKOUT_ASYNC_SUCCEEDED = "checkout.session.async_payment_succeeded"
CHECKOUT_ASYNC_FAILED = "checkout.session.async_payment_failed"
CHECKOUT_EXPIRED = "checkout.session.expired"

HANDLED_EVENTS = {
    CHECKOUT_COMPLETED,
    CHECKOUT_ASYNC_SUCCEEDED,
    CHECKOUT_ASYNC_FAILED,
    CHECKOUT_EXPIRED,
}

# The status page polls for about twenty seconds before giving up; that is a
# display decision, not a payment one. The webhook settles the order regardless.
_PAID_STATES = {"paid", "no_payment_required"}


def get_gateway() -> Optional[PaymentGateway]:
    """The configured gateway, or None when this deployment takes no money."""
    return gateway_from_env(os.environ)


def require_gateway(
    gateway: Optional[PaymentGateway] = Depends(get_gateway),
) -> PaymentGateway:
    """The gateway, or a `503` that says what is missing.

    Separate from `get_gateway` so the status route can answer a *paid* row from
    storage even if the key has since been removed. A missing key is not an
    error about a payment that already happened.
    """
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Payments are not configured on this server. The order was "
                "placed, but no charge can be made until STRIPE_SECRET_KEY is set."
            ),
        )
    return gateway


async def _payment_by_order(
    db: AsyncSession, order_id: str
) -> Optional[OrderPaymentRecord]:
    result = await db.execute(
        select(OrderPaymentRecord).where(OrderPaymentRecord.order_id == order_id)
    )
    return result.scalar_one_or_none()


async def _payment_by_session(
    db: AsyncSession, session_id: str
) -> Optional[OrderPaymentRecord]:
    result = await db.execute(
        select(OrderPaymentRecord).where(
            OrderPaymentRecord.session_id == session_id
        )
    )
    return result.scalar_one_or_none()


def _checkout_origin(requested: Optional[str]) -> str:
    """The origin Checkout sends the customer back to.

    A browser may only come back to somewhere this API already trusts - the same
    list CORS uses. Otherwise a caller could have the payer redirected to a site
    of their choosing after a real charge. A request with no origin falls back
    to the dev frontend's port.
    """
    candidate = (requested or "").strip().rstrip("/")
    if not candidate:
        return "http://localhost:3000"

    allowed = allowed_origins(os.environ)
    pattern = allowed_origin_regex(os.environ)
    if candidate in allowed or (pattern and re.match(pattern, candidate)):
        return candidate

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="origin_url is not an origin this API serves",
    )


def _order_name(order: OrderRecord, restaurant_name: str) -> str:
    """What the hosted page calls the order, short enough for a line item."""
    kitchen = (restaurant_name or "the restaurant").strip()
    label = f"Order from {kitchen}"
    return label[:250]


def _lines_for(order: OrderRecord, restaurant_name: str) -> List[CheckoutLine]:
    """Break the bill into the lines the customer saw at checkout.

    The parts are read from the order and added back up. If they do not equal
    the stored total - an older row written before pricing was centralised, a
    tax nobody charges - the fallback is one line for the whole bill rather than
    a page whose lines visibly do not add up.
    """
    subtotal = to_cents(order.subtotal)
    tax = to_cents(order.tax_amount)
    fee = to_cents(order.delivery_fee)
    tip = to_cents(order.tip_amount)

    lines = [CheckoutLine(_order_name(order, restaurant_name), subtotal)]
    if tax:
        lines.append(CheckoutLine("Tax", tax))
    if fee:
        lines.append(CheckoutLine("Delivery", fee))
    if tip:
        lines.append(CheckoutLine("Driver tip", tip))

    if subtotal <= 0 or sum(line.amount_cents for line in lines) != to_cents(
        order.total_amount
    ):
        return [CheckoutLine(_order_name(order, restaurant_name), to_cents(order.total_amount))]

    return lines


def _checkout_response(
    order: OrderRecord, payment: OrderPaymentRecord
) -> CheckoutResponse:
    return CheckoutResponse(
        order_id=order.order_id,
        session_id=payment.session_id,
        url=payment.checkout_url,
        amount_total=payment.amount_cents,
        currency=payment.currency,
    )


def _status_response(
    order: OrderRecord, payment: OrderPaymentRecord
) -> PaymentStatusResponse:
    return PaymentStatusResponse(
        order_id=order.order_id,
        session_id=payment.session_id,
        payment_status=payment.payment_status,
        status=payment.provider_status,
        amount_total=payment.amount_cents,
        currency=payment.currency,
    )


async def _apply_state(
    db: AsyncSession,
    payment: OrderPaymentRecord,
    order: OrderRecord,
    state: SessionState,
    *,
    source: str,
) -> bool:
    """Fold what the provider says into the stored payment row.

    Returns whether the row was allowed to change. Two guards matter:

      * the session must name the order it is stored against, so a session for
        another order cannot settle this bill;
      * a paid session must have charged the bill exactly. A mismatch is
        recorded as failed rather than paid, because "money arrived" and "this
        order is settled" are different statements when the amount is wrong.

    A row already marked paid is never downgraded: a later `open` or `expired`
    event from an older session must not un-pay an order.
    """
    if state.order_id and state.order_id != order.order_id:
        logger.error(
            "Payment session %s names order %s but is stored against %s (%s); ignoring",
            state.session_id,
            state.order_id,
            order.order_id,
            source,
        )
        return False

    # A superseded session may still complete (the customer had two tabs open).
    # Money is money: its paid state is accepted, but an unpaid state from an
    # older session must not overwrite the current attempt's.
    superseded = state.session_id and state.session_id != payment.session_id
    if superseded and state.payment_status not in _PAID_STATES:
        logger.info(
            "Ignoring %s state for superseded session %s of order %s",
            state.status,
            state.session_id,
            order.order_id,
        )
        return False

    expected = to_cents(order.total_amount)
    payment.provider_status = state.status or payment.provider_status
    payment.provider_payment_status = (
        state.payment_status or payment.provider_payment_status
    )
    if state.payment_intent_id:
        payment.payment_intent_id = state.payment_intent_id
    if state.currency:
        payment.currency = state.currency
    if state.amount_cents:
        payment.amount_cents = state.amount_cents

    if state.payment_status in _PAID_STATES:
        if state.amount_cents != expected:
            logger.error(
                "Session %s paid %s cents for order %s, which was billed %s; "
                "not marking it paid",
                state.session_id,
                state.amount_cents,
                order.order_id,
                expected,
            )
            if payment.payment_status != PAYMENT_PAID:
                payment.payment_status = PAYMENT_FAILED
                payment.failure_reason = (
                    f"Charged {state.amount_cents} cents, but the order total is "
                    f"{expected} cents."
                )
        else:
            payment.payment_status = PAYMENT_PAID
            payment.paid_at = payment.paid_at or datetime.now(timezone.utc)
            payment.failure_reason = ""
    elif state.status == "expired":
        if payment.payment_status != PAYMENT_PAID:
            payment.payment_status = PAYMENT_FAILED
            payment.failure_reason = "The checkout session expired before it was paid."
    elif payment.payment_status != PAYMENT_PAID:
        payment.payment_status = PAYMENT_PENDING

    await db.flush()
    return True


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_checkout(
    body: CheckoutRequest,
    current_user: UserRecord = Depends(get_current_user),
    gateway: PaymentGateway = Depends(require_gateway),
    db: AsyncSession = Depends(get_db),
):
    """Open a hosted Checkout page for one of the caller's orders.

    Idempotent in the way that matters: an unpaid session that is still open is
    handed back rather than replaced, so a double-click or a page refresh cannot
    leave the customer with two tabs that both charge them.
    """
    order = await order_or_none(db, body.order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    if order.customer_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the customer who placed the order can pay for it",
        )
    if order.status == OrderStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cancelled order cannot be paid",
        )
    if order.status == OrderStatus.DELIVERED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This order has already been delivered",
        )

    amount = to_cents(order.total_amount)
    if amount < MIN_CHARGE_CENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stripe cannot charge less than {MIN_CHARGE_CENTS} cents; "
                "this order is too small to check out online."
            ),
        )

    payment = await _payment_by_order(db, order.order_id)
    if payment is not None and payment.payment_status == PAYMENT_PAID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This order is already paid"
        )

    # An order can also be waiting on a Bitcoin or Monero invoice, which is not
    # a Stripe session: there is nothing for Stripe to answer about it, and an
    # address the customer may already be typing into their wallet must not be
    # joined by a second payable page. An *expired* invoice does not block the
    # card - its row is simply reused for this attempt.
    crypto_invoice = payment is not None and payment.session_id.startswith(
        CRYPTO_SESSION_PREFIX
    )
    if crypto_invoice and payment.provider_status == "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This order is waiting on a crypto payment. Finish that payment, "
                "or wait for its quote to expire, before paying by card."
            ),
        )

    if payment is not None and not crypto_invoice:
        # Ask Stripe about the session we already have before making another.
        try:
            state = await gateway.retrieve(payment.session_id)
        except PaymentProviderError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Could not reach the payment provider; please try again.",
            ) from exc

        await _apply_state(db, payment, order, state, source="checkout")
        if payment.payment_status == PAYMENT_PAID:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This order is already paid",
            )
        if payment.provider_status == "open" and payment.checkout_url:
            return _checkout_response(order, payment)

    restaurant = await restaurant_or_none(db, order.restaurant_id)
    restaurant_name = restaurant.name if restaurant else ""

    origin = _checkout_origin(body.origin_url)
    attempt = (payment.attempt if payment else 0) + 1

    try:
        session = await gateway.create_checkout(
            order_id=order.order_id,
            customer_id=current_user.user_id,
            customer_email=current_user.email or "",
            lines=_lines_for(order, restaurant_name),
            amount_cents=amount,
            currency="usd",
            success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/payment/cancel?order_id={order.order_id}",
            # Stable per attempt: a request retried after this process died
            # gets the session it already made instead of a second one.
            idempotency_key=f"checkout-{order.order_id}-{attempt}",
        )
    except PaymentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The payment provider refused to start a checkout; please try again.",
        ) from exc

    if payment is None:
        payment = OrderPaymentRecord(
            order_id=order.order_id, session_id=session.session_id
        )
        db.add(payment)

    payment.session_id = session.session_id
    payment.checkout_url = session.url
    payment.payment_status = PAYMENT_PENDING
    payment.provider_status = "open"
    payment.provider_payment_status = "unpaid"
    payment.amount_cents = session.amount_cents
    payment.currency = session.currency
    payment.payment_intent_id = None
    payment.failure_reason = ""
    payment.paid_at = None
    payment.attempt = attempt
    await db.flush()

    return _checkout_response(order, payment)


@router.get("/status/{session_id}", response_model=PaymentStatusResponse)
async def payment_status(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
    gateway: Optional[PaymentGateway] = Depends(get_gateway),
    db: AsyncSession = Depends(get_db),
):
    """Whether the session behind a success page has been paid.

    The answer is refreshed from Stripe unless the row already says paid, in
    which case the stored answer is returned: once money is recorded, a provider
    outage must not turn a confirmed payment into "something went wrong".
    """
    payment = await _payment_by_session(db, session_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )

    order = await order_or_none(db, payment.order_id)
    # A session that does not exist and one that belongs to somebody else get
    # the same answer, so the route cannot be used to probe for order ids.
    if order is None or order.customer_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found"
        )

    if payment.payment_status == PAYMENT_PAID:
        return _status_response(order, payment)

    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are not configured on this server.",
        )

    try:
        state = await gateway.retrieve(session_id)
    except PaymentProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the payment provider; please try again.",
        ) from exc

    await _apply_state(db, payment, order, state, source="status")
    return _status_response(order, payment)


# ---------------------------------------------------------------------------
# What the webhook did, and what it refused
# ---------------------------------------------------------------------------

# The path Stripe is told to call, and the address to copy into `stripe listen`
# or the Dashboard. One constant so the diagnostics response cannot drift from
# the route it describes.
WEBHOOK_PATH = "/api/payments/webhook"

# Enough history to answer "is the listener reaching us" and "what did the last
# few deliveries do", without turning a table that every delivery writes into an
# archive. Stripe retries a failing endpoint for days; an unbounded log of those
# retries is a slow disk leak.
WEBHOOK_HISTORY_LIMIT = 500


def _remember_delivery(
    db: AsyncSession,
    *,
    verified: bool,
    outcome: str,
    event_id: str = "",
    event_type: str = "",
    session_id: str = "",
) -> None:
    """Add one delivery row to the caller's transaction."""
    db.add(
        PaymentWebhookDeliveryRecord(
            event_id=event_id,
            event_type=event_type,
            session_id=session_id,
            verified=verified,
            outcome=outcome,
        )
    )


async def _prune_deliveries(db: AsyncSession) -> None:
    """Keep the newest `WEBHOOK_HISTORY_LIMIT` deliveries, drop the rest."""
    await db.execute(
        delete(PaymentWebhookDeliveryRecord).where(
            PaymentWebhookDeliveryRecord.id.notin_(
                select(PaymentWebhookDeliveryRecord.id)
                .order_by(PaymentWebhookDeliveryRecord.id.desc())
                .limit(WEBHOOK_HISTORY_LIMIT)
                .scalar_subquery()
            )
        )
    )


async def _remember_refused(
    *, outcome: str, event_type: str = "", session_id: str = ""
) -> None:
    """Record a delivery that was not believed, on a session of its own.

    The request's session is rolled back when the route raises, which is exactly
    the path a refused delivery takes: written there, the record of the failure
    would be discarded by the error it describes. This one commits independently,
    so "Stripe says delivered, the app says it never arrived" leaves something
    behind to read.

    Only the arrival is recorded - no payload, no signature, and no event id,
    because nothing in a body that failed verification can be trusted.
    """
    async with async_session_factory() as session:
        _remember_delivery(
            session,
            verified=False,
            outcome=outcome,
            event_type=event_type,
            session_id=session_id,
        )
        await _prune_deliveries(session)
        await session.commit()


async def _latest_delivery(
    db: AsyncSession, *conditions
) -> Optional[PaymentWebhookDeliveryRecord]:
    """The newest delivery matching `conditions`, if there is one."""
    result = await db.execute(
        select(PaymentWebhookDeliveryRecord)
        .where(*conditions)
        .order_by(
            PaymentWebhookDeliveryRecord.received_at.desc(),
            PaymentWebhookDeliveryRecord.id.desc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/webhook", response_model=WebhookResponse)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
    gateway: Optional[PaymentGateway] = Depends(get_gateway),
    db: AsyncSession = Depends(get_db),
):
    """Stripe's notification that a payment happened, verified before it counts.

    The body is read raw: the signature covers those exact bytes, so parsing
    first and re-serialising would make every signature fail. Unknown events are
    acknowledged with `200` so Stripe stops retrying them; a bad signature is
    `400` and changes nothing.

    Every attempt is written to `payment_webhook_deliveries`, refusals included:
    "the app never heard about the payment" and "the app refused to believe it"
    are different problems with the same symptom. `GET /payments/diagnostics`
    reads that record back.
    """
    if gateway is None:
        await _remember_refused(outcome=OUTCOME_UNCONFIGURED)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments are not configured on this server.",
        )

    if not stripe_signature:
        await _remember_refused(outcome=OUTCOME_REJECTED)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe-Signature header",
        )

    payload = await request.body()
    try:
        event = gateway.parse_webhook(payload, stripe_signature)
    except PaymentsNotConfigured as exc:
        await _remember_refused(outcome=OUTCOME_UNCONFIGURED)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STRIPE_WEBHOOK_SECRET is not configured on this server.",
        ) from exc
    except InvalidWebhookSignature as exc:
        await _remember_refused(outcome=OUTCOME_REJECTED)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        ) from exc

    event_type = webhook_event_type(event)
    if event_type not in HANDLED_EVENTS:
        _remember_delivery(
            db,
            verified=True,
            outcome=OUTCOME_UNHANDLED,
            event_id=webhook_event_id(event),
            event_type=event_type,
        )
        await _prune_deliveries(db)
        return WebhookResponse(received=True)

    event_object = webhook_event_object(event)
    state = state_from_session(event_object)
    if not state.session_id:
        logger.warning("Stripe sent a %s with no session id; ignoring", event_type)
        _remember_delivery(
            db,
            verified=True,
            outcome=OUTCOME_IGNORED,
            event_id=webhook_event_id(event),
            event_type=event_type,
        )
        await _prune_deliveries(db)
        return WebhookResponse(received=True)

    payment = await _payment_by_session(db, state.session_id)
    if payment is not None:
        order = await order_or_none(db, payment.order_id)
    elif state.order_id:
        # The checkout request may have died after Stripe made the session and
        # before the row was written. The metadata is enough to recover.
        order = await order_or_none(db, state.order_id)
        if order is not None:
            payment = OrderPaymentRecord(
                order_id=order.order_id,
                session_id=state.session_id,
                amount_cents=state.amount_cents,
                currency=state.currency,
            )
            db.add(payment)
    else:
        order = None

    if order is None:
        logger.warning(
            "Stripe event %s for session %s names no order we know; acknowledging",
            event_type,
            state.session_id,
        )
        _remember_delivery(
            db,
            verified=True,
            outcome=OUTCOME_UNMATCHED,
            event_id=webhook_event_id(event),
            event_type=event_type,
            session_id=state.session_id,
        )
        await _prune_deliveries(db)
        return WebhookResponse(received=True)

    # An async failure has a complete session with an unpaid status. Translate
    # it into the state the row understands before folding it in.
    if event_type == CHECKOUT_ASYNC_FAILED:
        state = replace(state, status="expired")

    changed = await _apply_state(db, payment, order, state, source="webhook")
    if (
        changed
        and event_type == CHECKOUT_ASYNC_FAILED
        and payment.payment_status != PAYMENT_PAID
    ):
        payment.payment_status = PAYMENT_FAILED
        payment.failure_reason = "Stripe reported the payment failed."

    _remember_delivery(
        db,
        verified=True,
        outcome=OUTCOME_SETTLED if changed else OUTCOME_IGNORED,
        event_id=webhook_event_id(event),
        event_type=event_type,
        session_id=state.session_id,
    )
    await _prune_deliveries(db)

    return WebhookResponse(
        received=True,
        handled=payment.payment_status if changed else None,
    )


@router.get("/diagnostics", response_model=PaymentDiagnosticsResponse)
async def payment_diagnostics(
    current_user=Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Which Stripe settings this deployment is running with, and whether events arrive.

    Deliberately offline: it answers from the environment and the delivery table
    without calling Stripe, so it still works on the deployment that is broken -
    which is the only time anybody reads it. An unreachable Stripe would turn a
    diagnostic into a second failure to diagnose.

    No part of a key appears here, not even a masked tail. What it does say is
    the part of a key that is not a secret: whether one is set at all, whether it
    is a test key or a live one, and whether it is a full secret key or a
    restricted one. Those three facts explain most of the ways a checkout can be
    configured wrongly, and none of them is a credential.

    Administrator-only: it is a map of the deployment's payment configuration,
    and the delivery history names sessions a support conversation might be
    about.
    """
    environ = os.environ
    mode = secret_key_mode(environ)
    kind = secret_key_kind(environ)
    configured = mode != KEY_MODE_UNSET
    hook_secret = bool((environ.get("STRIPE_WEBHOOK_SECRET") or "").strip())

    latest = await _latest_delivery(db)
    latest_verified = await _latest_delivery(
        db, PaymentWebhookDeliveryRecord.verified.is_(True)
    )
    latest_refused = await _latest_delivery(
        db, PaymentWebhookDeliveryRecord.verified.is_(False)
    )

    # A rolling day rather than "today": this answers "is the listener still
    # forwarding", which needs no timezone and no midnight.
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    received_24h = int(
        await db.scalar(
            select(func.count())
            .select_from(PaymentWebhookDeliveryRecord)
            .where(PaymentWebhookDeliveryRecord.received_at >= since)
        )
        or 0
    )
    refused_24h = int(
        await db.scalar(
            select(func.count())
            .select_from(PaymentWebhookDeliveryRecord)
            .where(
                PaymentWebhookDeliveryRecord.received_at >= since,
                PaymentWebhookDeliveryRecord.verified.is_(False),
            )
        )
        or 0
    )

    warnings: List[str] = []
    if mode == KEY_MODE_UNSET:
        warnings.append(
            "STRIPE_SECRET_KEY is not set: checkout answers 503 and orders stay payable."
        )
    if mode == KEY_MODE_LIVE:
        warnings.append(
            "A live key is configured: checkout charges real cards, and Stripe's "
            "test card numbers will be declined."
        )
    if mode == KEY_MODE_UNRECOGNISED:
        warnings.append(
            "STRIPE_SECRET_KEY is set but is not a Stripe key shape (sk_test_, "
            "sk_live_ or a restricted rk_ key); Stripe will refuse it."
        )
    if kind == KEY_KIND_RESTRICTED:
        warnings.append(
            "The key is restricted: it needs write access to Checkout sessions "
            "before it can start a payment."
        )
    if configured and not hook_secret:
        warnings.append(
            "STRIPE_WEBHOOK_SECRET is empty: signed events are refused with 503, "
            "so a payment is only confirmed while the success page is open. "
            "dev_payments.sh fills this in for you."
        )
    if configured and latest is None:
        warnings.append(
            "No webhook delivery has arrived yet. Locally that is "
            f"`stripe listen --forward-to localhost:8000{WEBHOOK_PATH}`."
        )

    # Crypto has no webhook and no card network: what matters is whether a
    # wallet is configured and how much the watcher is holding. Counting rows
    # never contacts a node, so this block answers with the node down too.
    crypto_now = datetime.now(timezone.utc)
    crypto_wallets = wallets_from_env(environ)
    crypto_open = int(
        await db.scalar(
            select(func.count())
            .select_from(OrderCryptoInvoiceRecord)
            .where(
                OrderCryptoInvoiceRecord.status.in_(OPEN_STATUSES),
                OrderCryptoInvoiceRecord.grace_until > crypto_now,
            )
        )
        or 0
    )
    crypto_confirmed = int(
        await db.scalar(
            select(func.count())
            .select_from(OrderCryptoInvoiceRecord)
            .where(OrderCryptoInvoiceRecord.status == CRYPTO_CONFIRMED)
        )
        or 0
    )
    crypto_last = await db.scalar(
        select(func.max(OrderCryptoInvoiceRecord.confirmed_at))
    )

    crypto_warnings: List[str] = []
    if crypto_wallets is None:
        crypto_warnings.append(
            "No crypto wallet is configured: Bitcoin and Monero invoices are "
            "unavailable and this deployment takes card payments only."
        )
    else:
        if watcher_interval_seconds(environ) <= 0:
            crypto_warnings.append(
                "The crypto watcher is disabled (CRYPTO_WATCH_INTERVAL_SECONDS <= 0): "
                "a payment is only noticed while the customer's page is open."
            )
        for option in crypto_wallets.assets:
            if confirmations_for(option, environ) == 0:
                crypto_warnings.append(
                    f"{option.name} payments settle with no confirmations "
                    f"(CRYPTO_{option.code.upper()}_CONFIRMATIONS=0): a transaction "
                    "that is replaced before it confirms takes the order with it."
                )

    webhook = WebhookDeliverySummary(
        received_24h=received_24h, rejected_24h=refused_24h
    )
    if latest is not None:
        webhook.last_received_at = as_utc(latest.received_at)
        webhook.last_event_type = latest.event_type or None
        webhook.last_outcome = latest.outcome or None
    if latest_verified is not None:
        webhook.last_verified_at = as_utc(latest_verified.received_at)
    if latest_refused is not None:
        webhook.last_rejected_at = as_utc(latest_refused.received_at)

    return PaymentDiagnosticsResponse(
        checked_at=datetime.now(timezone.utc),
        # With no key, the Pay button is answered with a sentence rather than a
        # charge. That is a supported state, not an outage. A key Stripe will
        # not recognise is not "available" either: checkout would reach Stripe
        # and be refused, so the honest answer is the same.
        configured=configured,
        checkout_available=mode in (KEY_MODE_TEST, KEY_MODE_LIVE),
        key_mode=mode,
        key_kind=kind,
        live_mode=mode == KEY_MODE_LIVE,
        webhook_secret_configured=hook_secret,
        webhook_path=WEBHOOK_PATH,
        handled_events=sorted(HANDLED_EVENTS),
        currency=CURRENCY,
        min_charge_cents=MIN_CHARGE_CENTS,
        warnings=warnings,
        webhook=webhook,
        crypto=CryptoDiagnostics(
            enabled=crypto_wallets is not None,
            assets=[
                asset.code for asset in (crypto_wallets.assets if crypto_wallets else [])
            ],
            quote_minutes=quote_minutes(environ),
            grace_hours=grace_hours(environ),
            minimum_charge_cents=crypto_minimum_charge_cents(environ),
            watcher_interval_seconds=watcher_interval_seconds(environ),
            open_invoices=crypto_open,
            confirmed_invoices=crypto_confirmed,
            last_confirmed_at=as_utc(crypto_last),
            warnings=crypto_warnings,
        ),
    )
