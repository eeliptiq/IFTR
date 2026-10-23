"""
Keeping an invoice in step with the chain, and settling the order when it is paid.

The route that the payment page polls and the background watcher both come
through here, so "the wallet said X" is folded into the invoice in exactly one
place. Three decisions live in this module:

  * **monotonic totals.** A wallet that is rescanning can briefly report less
    than it did; the invoice never un-sees money.
  * **expiry releases the order, not the invoice.** An expired quote means the
    customer may pay another way, so the pending payment row is marked failed and
    the Stripe route stops being blocked. The invoice itself keeps being watched
    through its grace window, because a Bitcoin transaction can sit in the mempool
    for hours and money that arrived late is still money.
  * **settlement is once.** A confirmed invoice marks the order paid; a second
    confirmed invoice for an order that is already paid is logged as a duplicate
    rather than silently rewriting what happened.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._lookups import order_or_none
from app.crypto import (
    ASSETS,
    CryptoWallet,
    CryptoWalletError,
    CryptoWallets,
)
from app.models.crypto_orm import (
    CRYPTO_AWAITING,
    CRYPTO_CONFIRMED,
    CRYPTO_EXPIRED,
    CRYPTO_PARTIAL,
    OPEN_STATUSES,
    OrderCryptoInvoiceRecord,
)
from app.models.payment_orm import PAYMENT_FAILED, PAYMENT_PAID, OrderPaymentRecord
from app.payments import to_cents
from app.schemas._time import as_utc

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def payment_by_order(
    db: AsyncSession, order_id: str
) -> Optional[OrderPaymentRecord]:
    """The order's payment row, whichever provider wrote it."""
    return (
        await db.execute(
            select(OrderPaymentRecord).where(OrderPaymentRecord.order_id == order_id)
        )
    ).scalar_one_or_none()


async def open_invoice_for(
    db: AsyncSession, order_id: str
) -> Optional[OrderCryptoInvoiceRecord]:
    """The invoice still on offer for this order, if there is one.

    `expired` is deliberately not "open": an expired quote is no longer handed
    out, even though the address is still being watched.
    """
    return (
        await db.execute(
            select(OrderCryptoInvoiceRecord)
            .where(
                OrderCryptoInvoiceRecord.order_id == order_id,
                OrderCryptoInvoiceRecord.status.in_(
                    (CRYPTO_AWAITING, CRYPTO_PARTIAL)
                ),
            )
            .order_by(OrderCryptoInvoiceRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def settle_order(
    db: AsyncSession, invoice: OrderCryptoInvoiceRecord
) -> bool:
    """Mark the order paid from a confirmed invoice. Returns whether it changed.

    The row written is the same `order_payments` row a card payment writes, so
    every screen that already answers "has this been paid?" - the kitchen queue,
    the driver board, the admin revenue total - keeps answering correctly without
    knowing crypto exists.
    """
    order = await order_or_none(db, invoice.order_id)
    if order is None:
        logger.error(
            "invoice %s confirmed for order %s, which does not exist",
            invoice.invoice_id,
            invoice.order_id,
        )
        return False

    payment = await payment_by_order(db, invoice.order_id)
    if payment is not None and payment.payment_status == PAYMENT_PAID:
        # Paid by this invoice on an earlier poll, or by a card while the crypto
        # address was still in the customer's wallet. Say so and touch nothing.
        logger.warning(
            "invoice %s confirmed for order %s, which was already paid via %s",
            invoice.invoice_id,
            invoice.order_id,
            payment.session_id,
        )
        return False

    if payment is not None and payment.session_id != invoice.invoice_id:
        # The row belongs to a newer attempt: a card checkout the customer
        # opened after this quote expired, or a newer invoice. Late money at the
        # old address must not take over a payment that is still in flight - a
        # card charged afterwards would be a second charge, and Stripe's webhook
        # would find no row of its own. The invoice keeps the confirmation; this
        # is a duplicate payment for support to refund, not a settlement.
        logger.error(
            "invoice %s confirmed for order %s, but the payment row belongs to "
            "%s; refusing to overwrite it",
            invoice.invoice_id,
            invoice.order_id,
            payment.session_id,
        )
        return False

    if payment is None:
        payment = OrderPaymentRecord(
            order_id=order.order_id, session_id=invoice.invoice_id
        )
        db.add(payment)

    payment.session_id = invoice.invoice_id
    payment.checkout_url = ""
    payment.payment_status = PAYMENT_PAID
    payment.provider_status = CRYPTO_CONFIRMED
    payment.provider_payment_status = "paid"
    # The bill, not the quoted coin amount: revenue is reported in dollars, and
    # the invoice row keeps the exact atomic amount that was received.
    payment.amount_cents = to_cents(order.total_amount)
    payment.currency = "usd"
    payment.failure_reason = ""
    payment.paid_at = as_utc(invoice.confirmed_at) or _now()
    await db.flush()

    logger.info(
        "order %s paid with %s (invoice %s, %s confirmations)",
        order.order_id,
        invoice.asset,
        invoice.invoice_id,
        invoice.confirmations,
    )
    return True


async def _release_order_payment(
    db: AsyncSession, invoice: OrderCryptoInvoiceRecord
) -> None:
    """Let the order be paid another way once its crypto quote has expired."""
    payment = await payment_by_order(db, invoice.order_id)
    if payment is None or payment.payment_status == PAYMENT_PAID:
        return
    if payment.session_id != invoice.invoice_id:
        # A later attempt (a card, or a new invoice) owns the row now.
        return

    payment.provider_status = CRYPTO_EXPIRED
    payment.payment_status = PAYMENT_FAILED
    asset = ASSETS[invoice.asset]
    if invoice.received_atomic:
        payment.failure_reason = (
            "The crypto quote expired: "
            f"{asset.display(invoice.received_atomic)} of "
            f"{asset.display(invoice.amount_atomic)} {asset.unit} arrived. "
            "Contact support with the transaction id."
        )
    else:
        payment.failure_reason = "The crypto quote expired before it was paid."
    await db.flush()


async def _apply_expiry(
    db: AsyncSession, invoice: OrderCryptoInvoiceRecord, now: datetime
) -> bool:
    """Expire the quote when its time is up. Never touches a settled invoice."""
    if invoice.status in (CRYPTO_CONFIRMED, CRYPTO_EXPIRED):
        return False
    # SQLite hands back naive datetimes even for a timezone-aware column, so
    # every stored timestamp is read back through `as_utc` before it is compared
    # with a fresh `now`.
    if now <= as_utc(invoice.expires_at):
        return False

    invoice.status = CRYPTO_EXPIRED
    await _release_order_payment(db, invoice)
    logger.info("crypto invoice %s expired", invoice.invoice_id)
    return True


async def refresh_invoice(
    db: AsyncSession,
    invoice: OrderCryptoInvoiceRecord,
    wallet: CryptoWallet,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Ask the wallet about one invoice and fold the answer in.

    Returns whether the invoice changed. Raises `CryptoWalletError` when the
    wallet cannot be asked - the failure belongs to the caller, because a page
    poll and a background sweep want to report it differently - after the expiry
    above has been applied, so a dead node cannot keep a quote alive.
    """
    now = now or _now()
    changed = await _apply_expiry(db, invoice, now)

    if invoice.status == CRYPTO_CONFIRMED:
        return changed

    reading = await wallet.received(
        invoice.address, confirmations=invoice.confirmations_required
    )

    # Totals are cumulative, but a rescanning node can report less for a moment.
    # The invoice remembers the high-water mark instead of the latest answer.
    for field, value in (
        ("received_atomic", reading.received_atomic),
        ("confirmed_atomic", reading.confirmed_atomic),
        ("confirmations", reading.confirmations),
    ):
        if value > getattr(invoice, field):
            setattr(invoice, field, value)
            changed = True
    if reading.txid and reading.txid != invoice.txid:
        invoice.txid = reading.txid
        changed = True

    paid_in_full = (
        invoice.amount_atomic > 0
        and invoice.confirmed_atomic >= invoice.amount_atomic
    )

    if paid_in_full:
        invoice.status = CRYPTO_CONFIRMED
        invoice.confirmed_at = as_utc(invoice.confirmed_at) or now
        changed = True
        if await settle_order(db, invoice):
            changed = True
    elif now > as_utc(invoice.expires_at):
        invoice.status = CRYPTO_EXPIRED
    elif invoice.received_atomic > 0:
        invoice.status = CRYPTO_PARTIAL
    else:
        invoice.status = CRYPTO_AWAITING

    return changed


async def poll_open_invoices(
    db: AsyncSession,
    wallets: CryptoWallets,
    *,
    now: Optional[datetime] = None,
    limit: int = 50,
) -> int:
    """Refresh every invoice that could still be paid, or still be too late.

    Invoices past their grace window are dropped from the sweep: the money is
    not coming, and polling a wallet about them forever is a slow leak of
    requests. Their rows stay, with whatever was received, for support to read.
    """
    now = now or _now()
    invoices = (
        (
            await db.execute(
                select(OrderCryptoInvoiceRecord)
                .where(
                    OrderCryptoInvoiceRecord.status.in_(OPEN_STATUSES),
                    # SQLite drops the offset on the way in, so UTC is
                    # compared as naive UTC - the same shape it was stored in.
                    OrderCryptoInvoiceRecord.grace_until
                    > now.replace(tzinfo=None),
                )
                .order_by(OrderCryptoInvoiceRecord.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    checked = 0
    for invoice in invoices:
        wallet = wallets.for_asset(invoice.asset)
        if wallet is None:
            continue
        try:
            await refresh_invoice(db, invoice, wallet, now=now)
        except CryptoWalletError as exc:
            # One unreachable wallet must not stop the sweep for the other asset.
            logger.warning("invoice %s: %s", invoice.invoice_id, exc)
            continue
        checked += 1

    return checked
