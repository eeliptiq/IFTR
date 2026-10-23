"""
One crypto invoice: a quoted amount, an address, and what the chain says about it.

A new table rather than columns on `order_payments` for the same no-migrations
reason as the other satellites: `create_all` adds tables to a database that
already exists and does nothing about new columns on the ones already in it.

An invoice is kept after it is paid or expires. A Bitcoin transaction can surface
hours after the address was handed out, and "which address was that?" has to
have an answer then too - which is also why an expired invoice keeps being polled
until its grace window ends.

`amount_atomic` and `rate_cents` are the arithmetic the quote used: integer
satoshi (or piconero) against integer US cents per whole coin. Both are kept so a
dispute about the price can be settled by replaying it, not by re-fetching a rate
that has since moved.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The invoice's own state. `partial` is money seen but not enough; `expired`
# means the quote is no longer offered (the invoice is still watched until its
# grace window ends, because late money is still money).
CRYPTO_AWAITING = "awaiting"
CRYPTO_PARTIAL = "partial"
CRYPTO_CONFIRMED = "confirmed"
CRYPTO_EXPIRED = "expired"

OPEN_STATUSES = (CRYPTO_AWAITING, CRYPTO_PARTIAL, CRYPTO_EXPIRED)


class OrderCryptoInvoiceRecord(Base):
    __tablename__ = "order_crypto_invoices"

    # `crypto_<asset>_<order>_<attempt>`: unique, and legible in a log line.
    # It is also what the order's payment row stores as its session id, which is
    # how the rest of the app sees "this order is being paid in crypto".
    invoice_id: Mapped[str] = mapped_column(String(96), primary_key=True)

    order_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    asset: Mapped[str] = mapped_column(String(8), index=True, nullable=False)

    # Which attempt at paying this order this invoice is. Restarting an invoice
    # gets a new address; the old one is kept and keeps being watched.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    address: Mapped[str] = mapped_column(String(128), nullable=False)

    # What was asked for, in atomic units, at the rate below.
    amount_atomic: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # The dollar bill the quote was made from. Stored rather than re-read from
    # the order, so the invoice keeps saying what it asked for even if the order
    # is edited later.
    fiat_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # How deep the payment must be before the order is treated as paid. Stored
    # per invoice: changing the setting later must not re-open a settled order.
    confirmations_required: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    # What the wallet last said. `received` counts zero-confirmation funds,
    # `confirmed` only those at the required depth.
    received_atomic: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    confirmed_atomic: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    confirmations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    txid: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    status: Mapped[str] = mapped_column(
        String(16), index=True, nullable=False, default=CRYPTO_AWAITING
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # The quote's lifetime, and how long we keep watching after it.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    grace_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
