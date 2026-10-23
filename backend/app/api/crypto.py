"""
Paying an order in Bitcoin or Monero, from the customer's side.

The card flow is a redirect and a webhook. This one is a page that stays open:

  1. `POST /payments/crypto/invoice` quotes a fiat bill in coin at a recorded
     rate, reserves a fresh address for it, and hands both back with an expiry.
  2. The customer pays from their own wallet. There is nobody to call us back,
     so the page polls `GET /payments/crypto/status/{order_id}` and the background
     watcher polls the wallet; both fold what they learn into the same invoice.
  3. When enough has arrived with enough confirmations, the order's payment row
     is marked paid - the same row a card payment writes, so every screen that
     asks "has this been paid?" keeps working unchanged.

Money-safety rules, in one place:

  * the amount comes from the stored order, never from the request;
  * a stale or missing rate means no invoice, never a guessed one;
  * one invoice on offer per order, and an open one blocks a card checkout, so a
    customer cannot pay twice by accident;
  * a paid order cannot be invoiced again, and a confirmed invoice cannot be
    un-confirmed.

When no wallet is configured this answers `503` with a sentence. That is a
supported state, like a missing Stripe key: the order exists and stays payable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._lookups import order_or_none
from app.api.payments import get_gateway  # same seam the card routes use
from app.core.auth import get_current_user
from app.crypto import (
    ASSETS,
    CRYPTO_SESSION_PREFIX,
    CryptoAsset,
    CryptoWalletError,
    CryptoWallets,
    RateUnavailable,
    confirmations_for,
    grace_hours,
    minimum_charge_cents,
    quote_minutes,
    quoted_amount,
    wallets_from_env,
)
from app.crypto_flow import OPEN_STATUSES, open_invoice_for, payment_by_order, refresh_invoice
from app.crypto_rates import fetch_rate_cents
from app.database import get_db
from app.models.crypto_orm import OrderCryptoInvoiceRecord
from app.models.general import OrderStatus, UserRole
from app.models.payment_orm import PAYMENT_PAID, PAYMENT_PENDING, OrderPaymentRecord
from app.payments import to_cents
from app.schemas._time import as_utc
from app.schemas.crypto import (
    CryptoAssetOption,
    CryptoInvoiceRequest,
    CryptoInvoiceResponse,
    CryptoMethods,
    CryptoStatusResponse,
    PaymentMethodsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


class RateFeed(Protocol):
    """Where a fiat price comes from, as a dependency the tests can replace."""

    async def cents(self, asset: CryptoAsset) -> int:
        ...


class CoinGeckoRateFeed:
    """The live feed. See app/crypto_rates.py for the cache and the checks."""

    async def cents(self, asset: CryptoAsset) -> int:
        return await fetch_rate_cents(asset, os.environ)


def get_wallets() -> Optional[CryptoWallets]:
    """The configured wallets, or None when this deployment takes no crypto."""
    return wallets_from_env(os.environ)


def get_rate_feed() -> RateFeed:
    return CoinGeckoRateFeed()


def _require_wallets(wallets: Optional[CryptoWallets]) -> CryptoWallets:
    if wallets is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Crypto payments are not configured on this server. The order "
                "was placed and stays payable; no address can be issued until a "
                "wallet is configured."
            ),
        )
    return wallets


def _asset_or_400(code: str) -> CryptoAsset:
    asset = ASSETS.get((code or "").strip().lower())
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported asset. Use one of: {', '.join(ASSETS)}.",
        )
    return asset


def _asset_option(asset: CryptoAsset) -> CryptoAssetOption:
    return CryptoAssetOption(
        code=asset.code,
        name=asset.name,
        unit=asset.unit,
        confirmations_required=confirmations_for(asset, os.environ),
        minimum=asset.display(asset.minimum_atomic),
    )


def _invoice_response(
    invoice: OrderCryptoInvoiceRecord,
) -> CryptoInvoiceResponse:
    asset = ASSETS[invoice.asset]
    return CryptoInvoiceResponse(
        order_id=invoice.order_id,
        invoice_id=invoice.invoice_id,
        asset=asset.code,
        asset_name=asset.name,
        unit=asset.unit,
        address=invoice.address,
        amount=asset.display(invoice.amount_atomic),
        amount_atomic=invoice.amount_atomic,
        uri=asset.uri(invoice.address, invoice.amount_atomic),
        fiat_total_cents=invoice.fiat_cents,
        currency="usd",
        rate_cents_per_coin=invoice.rate_cents,
        confirmations_required=invoice.confirmations_required,
        status=invoice.status,
        # Stored naive by SQLite; tagged UTC so the browser counts down from the
        # right instant instead of from its own timezone.
        expires_at=as_utc(invoice.expires_at),
        grace_until=as_utc(invoice.grace_until),
    )


def _payable_or_error(order) -> None:
    """Guards shared by both ways of paying: the bill has to still exist."""
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


@router.get("/methods", response_model=PaymentMethodsResponse)
async def payment_methods(
    wallets: Optional[CryptoWallets] = Depends(get_wallets),
):
    """Which ways this deployment can be paid, for the buttons that offer them.

    Public on purpose: it says that Bitcoin exists, not how it is configured.
    The cards' own availability is the same "is a Stripe key set" question the
    checkout route answers with a `503`.
    """
    crypto_assets: List[CryptoAssetOption] = [
        _asset_option(asset) for asset in (wallets.assets if wallets else [])
    ]
    return PaymentMethodsResponse(
        card_available=get_gateway() is not None,
        crypto=CryptoMethods(
            enabled=bool(crypto_assets),
            assets=crypto_assets,
        ),
    )


@router.post(
    "/crypto/invoice",
    response_model=CryptoInvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crypto_invoice(
    body: CryptoInvoiceRequest,
    current_user=Depends(get_current_user),
    wallets: Optional[CryptoWallets] = Depends(get_wallets),
    feed: RateFeed = Depends(get_rate_feed),
    db: AsyncSession = Depends(get_db),
):
    """Quote one order in coin and reserve an address for it.

    Idempotent in the way that matters: asking again for the same asset while
    the invoice is still open hands back the address already given out. Asking
    for a different asset while one is open is refused - two live addresses for
    one bill is how a customer pays twice.
    """
    configured = _require_wallets(wallets)
    asset = _asset_or_400(body.asset)

    wallet = configured.for_asset(asset.code)
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"{asset.name} is not configured on this server. "
                "Choose another payment method; the order stays payable."
            ),
        )

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
    _payable_or_error(order)

    payment = await payment_by_order(db, order.order_id)
    if payment is not None and payment.payment_status == PAYMENT_PAID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This order is already paid"
        )

    # Checked before the "something is already in flight" guard: an open invoice
    # *is* that something, and the answer to asking again is the address already
    # handed out, not a refusal.
    existing = await open_invoice_for(db, order.order_id)
    if existing is not None:
        if existing.asset == asset.code:
            # The same answer as last time, and no second address.
            return _invoice_response(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A {ASSETS[existing.asset].name} invoice is already open for this "
                "order. Pay that one, or wait for its quote to expire."
            ),
        )

    if payment is not None and payment.provider_status == "open":
        # One payment in flight per order. A card checkout is a redirect the
        # customer may still be looking at; a crypto invoice is an address that
        # stays valid for minutes. Either one plus a second method is a double
        # payment waiting to happen.
        other = (
            "a crypto invoice"
            if payment.session_id.startswith(CRYPTO_SESSION_PREFIX)
            else "a card checkout"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This order already has {other} in progress. Finish it, or wait "
                "for it to expire, before starting another payment."
            ),
        )

    fiat_cents = to_cents(order.total_amount)
    if fiat_cents < minimum_charge_cents(os.environ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This order is too small to pay in crypto: the network fee would "
                "be a meaningful share of the bill."
            ),
        )

    try:
        rate_cents = await feed.cents(asset)
    except RateUnavailable as exc:
        logger.warning("no %s quote: %s", asset.code, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "An exchange rate for this coin is unavailable right now, so no "
                "amount can be quoted. Try again in a minute, or pay by card."
            ),
        ) from exc

    amount_atomic = quoted_amount(asset, fiat_cents, rate_cents)
    if amount_atomic < asset.minimum_atomic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This order is below the smallest {asset.name} invoice "
                f"({asset.display(asset.minimum_atomic)} {asset.unit})."
            ),
        )

    # A fresh address per invoice. The label is the order id so an operator
    # looking at the wallet can tell what a payment was for without the app.
    try:
        address = await wallet.new_address(order.order_id)
    except CryptoWalletError as exc:
        logger.error("could not reserve a %s address: %s", asset.code, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The wallet could not issue an address. Nothing was charged; "
                "try again shortly or pay by card."
            ),
        ) from exc

    attempt = int(
        await db.scalar(
            select(func.count())
            .select_from(OrderCryptoInvoiceRecord)
            .where(OrderCryptoInvoiceRecord.order_id == order.order_id)
        )
        or 0
    ) + 1

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=quote_minutes(os.environ))
    grace_until = expires_at + timedelta(hours=grace_hours(os.environ))

    invoice = OrderCryptoInvoiceRecord(
        invoice_id=f"{CRYPTO_SESSION_PREFIX}{asset.code}_{order.order_id}_{attempt}",
        order_id=order.order_id,
        asset=asset.code,
        attempt=attempt,
        address=address,
        amount_atomic=amount_atomic,
        rate_cents=rate_cents,
        fiat_cents=fiat_cents,
        confirmations_required=confirmations_for(asset, os.environ),
        status="awaiting",
        expires_at=expires_at,
        grace_until=grace_until,
    )
    db.add(invoice)

    # The order's payment row says "in progress", whichever provider is doing
    # it: the kitchen, the tip guard and the card route all read this one row.
    if payment is None:
        payment = OrderPaymentRecord(
            order_id=order.order_id, session_id=invoice.invoice_id
        )
        db.add(payment)

    payment.session_id = invoice.invoice_id
    payment.checkout_url = ""
    payment.payment_status = PAYMENT_PENDING
    payment.provider_status = "open"
    payment.provider_payment_status = "unpaid"
    payment.amount_cents = fiat_cents
    payment.currency = "usd"
    payment.failure_reason = ""
    payment.paid_at = None
    await db.flush()

    logger.info(
        "invoice %s: %s %s for order %s at %s cents/coin",
        invoice.invoice_id,
        asset.display(amount_atomic),
        asset.unit,
        order.order_id,
        rate_cents,
    )
    return _invoice_response(invoice)


@router.get(
    "/crypto/status/{order_id}",
    response_model=CryptoStatusResponse,
)
async def crypto_status(
    order_id: str,
    current_user=Depends(get_current_user),
    wallets: Optional[CryptoWallets] = Depends(get_wallets),
    db: AsyncSession = Depends(get_db),
):
    """What the page polls: how much has arrived, and whether it is settled.

    The wallet is asked on each poll, so the answer does not wait for the
    background sweep. When the wallet cannot be reached the stored answer is
    returned with `wallet_ok: false` rather than an error: a node being down is
    not news about the payment, and the page should keep its countdown.
    """
    invoice = (
        await db.execute(
            select(OrderCryptoInvoiceRecord)
            .where(OrderCryptoInvoiceRecord.order_id == order_id)
            .order_by(OrderCryptoInvoiceRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    order = await order_or_none(db, order_id)
    # A missing invoice and somebody else's order get the same answer, so the
    # route cannot be used to probe for order ids.
    if invoice is None or order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No crypto invoice found for this order",
        )
    if (
        order.customer_id != current_user.user_id
        and current_user.role != UserRole.ADMIN.value
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No crypto invoice found for this order",
        )

    wallet_ok = True
    if (
        wallets is not None
        and invoice.status in OPEN_STATUSES
    ):
        wallet = wallets.for_asset(invoice.asset)
        if wallet is not None:
            try:
                await refresh_invoice(db, invoice, wallet)
                await db.flush()
            except CryptoWalletError as exc:
                logger.warning("status poll for %s: %s", invoice.invoice_id, exc)
                wallet_ok = False

    payment = await payment_by_order(db, order_id)
    asset = ASSETS[invoice.asset]
    return CryptoStatusResponse(
        order_id=invoice.order_id,
        invoice_id=invoice.invoice_id,
        asset=asset.code,
        address=invoice.address,
        amount=asset.display(invoice.amount_atomic),
        amount_atomic=invoice.amount_atomic,
        status=invoice.status,
        received=asset.display(invoice.received_atomic),
        received_atomic=invoice.received_atomic,
        confirmed_atomic=invoice.confirmed_atomic,
        confirmations=invoice.confirmations,
        confirmations_required=invoice.confirmations_required,
        txid=invoice.txid,
        expires_at=as_utc(invoice.expires_at),
        grace_until=as_utc(invoice.grace_until),
        payment_status=payment.payment_status if payment else PAYMENT_PENDING,
        wallet_ok=wallet_ok,
    )
