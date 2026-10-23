"""
One row per attempt Stripe made to tell us something.

The payment tables answer "what happened to this bill". This one answers a
different question that cannot be answered from them: did the notification ever
arrive? A paid order still sitting at `pending` looks identical whether Stripe
never called, called and was rejected for its signature, or called about an
event this app deliberately ignores. Without a record of the delivery itself,
all three look like silence.

Refused deliveries are recorded too. A forged body is worth knowing about, and
far more often the cause is mundane: a `whsec_...` copied from the Dashboard
does not verify the events `stripe listen` signs, so the API answers `400` to
every one of them. That failure is invisible in the logs a developer thinks to
read and obvious here.

Nothing holds the payload, the signature or the key - an event id, its type,
the session it named, whether the signature checked out, and what the route did
with it. The table is bounded by `WEBHOOK_HISTORY_LIMIT` in app/api/payments.py:
every delivery writes a row and Stripe retries, so this is a recent-history
record, not an archive.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# What the route did with a delivery. Named for the outcome rather than for the
# event, because two deliveries of the same event type can end differently (a
# replayed event settles nothing the second time) and that difference is the
# whole point of keeping the row.
OUTCOME_SETTLED = "settled"
OUTCOME_IGNORED = "ignored"
OUTCOME_UNMATCHED = "unmatched"
OUTCOME_UNHANDLED = "unhandled"
OUTCOME_REJECTED = "rejected"
OUTCOME_UNCONFIGURED = "unconfigured"


class PaymentWebhookDeliveryRecord(Base):
    __tablename__ = "payment_webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Stripe's `evt_...`. Empty when the body never got far enough to be parsed,
    # which is exactly the case for a rejected signature: nothing in those bytes
    # can be trusted, including the id.
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # e.g. `checkout.session.completed`. Empty when the body was not parsed.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # The Checkout session the event named, when it named one. An id, not a
    # secret: it is the same handle the success page polls with.
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # Whether the signature checked out before anything was believed. The
    # security fact, kept separately from the outcome so "how many deliveries
    # have we refused" is one indexed read.
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # One of the OUTCOME_* values above.
    outcome: Mapped[str] = mapped_column(String(24), nullable=False, default="")

    # When the request arrived, not when Stripe sent it: the question this
    # answers is whether this server is being reached.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
