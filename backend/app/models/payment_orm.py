"""
The payment state of one order.

A satellite table rather than columns on `orders`, for the same reason
`order_locations` and `order_delivery_details` are: there is no migration tool
here, so `create_all` adds new tables to a database that already exists and
silently does nothing about new columns on the ones already in it. A column
added to `orders` would work on a fresh database and break every order query on
a running one.

One row per order, not one per attempt. A customer who cancels Checkout and
tries again is paying the same bill, and two rows would leave the order with
two payment states and no answer to "has this been paid?". The row is therefore
updated in place: a new Stripe session replaces the old one until one of them is
paid, after which the paid session is final.

Nothing here talks to Stripe. This table is what we remember about the session;
app/payments.py is what asks Stripe what actually happened, and the status
endpoint refreshes this row from the provider rather than trusting it.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The vocabulary the customer-facing order view and the React screens read.
# Deliberately not Stripe's: `unpaid` is not a state a customer should have to
# interpret, and the provider's own words are kept beside it in
# `provider_payment_status` for whoever debugs this.
PAYMENT_PENDING = "pending"
PAYMENT_PAID = "paid"
PAYMENT_FAILED = "failed"


class OrderPaymentRecord(Base):
    __tablename__ = "order_payments"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Stripe's session id (`cs_test_...` / `cs_live_...`). Unique because it is
    # the only handle the success page has when it comes back from Checkout.
    session_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    # The hosted page to send the customer to. Stored rather than re-created:
    # a page reload in the middle of paying must not open a second session.
    checkout_url: Mapped[str] = mapped_column(Text, nullable=False, default="")

    payment_status: Mapped[str] = mapped_column(
        String(16), index=True, nullable=False, default=PAYMENT_PENDING
    )
    # Stripe's own session state: open / complete / expired, and its payment
    # state: unpaid / paid / no_payment_required. Kept verbatim so a support
    # question ("Stripe says paid, the app says pending") can be answered from
    # the row instead of from a dashboard.
    provider_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open"
    )
    provider_payment_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unpaid"
    )

    # What Stripe was asked to charge, in the smallest currency unit. The status
    # endpoint compares it with the order before it marks anything paid, so a
    # session for the wrong amount cannot settle a bill.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    # Why a payment failed, in one sentence, when we know: an amount mismatch,
    # an expired session, a refused card. Empty on a pending or paid row.
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Which attempt this session is. The checkout endpoint increments it only
    # after Stripe accepts a session, and uses the next value as the idempotency
    # key, so a request retried after a crash gets the session it already made
    # instead of paying for a second one.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
