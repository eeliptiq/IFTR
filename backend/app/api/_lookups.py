"""
Lookups shared by the two order-facing routers.

The restaurant queue (app/api/restaurants.py), the customer's side
(app/api/orders.py) and the driver's board (app/api/drivers.py) all need the
same few things about an order: which kitchen is making it, where its dropoff
is, and what the customer asked for. Reading them here keeps one query shape and
one decryption rule instead of three copies that drift.

Every one of these is a read. Nothing here decides anything.
"""

from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_data
from app.models.order_orm import (
    OrderDeliveryDetailsRecord,
    OrderLocationRecord,
    OrderRecord,
)
from app.models.payment_orm import OrderPaymentRecord
from app.models.restaurant_orm import RestaurantRecord
from app.schemas.order import LocationSummary

Point = Tuple[float, float]


async def restaurant_or_none(
    db: AsyncSession, restaurant_id: str
) -> Optional[RestaurantRecord]:
    """The restaurant an order belongs to, or None if the row has gone."""
    result = await db.execute(
        select(RestaurantRecord).where(RestaurantRecord.restaurant_id == restaurant_id)
    )
    return result.scalar_one_or_none()


def point_of(lat_encrypted: str, lng_encrypted: str) -> Optional[Point]:
    """Coordinates from a pair of encrypted columns.

    A row that cannot be decrypted or parsed counts as unlocated rather than as
    an error: an order without a distance is still an order.
    """
    try:
        return float(decrypt_data(lat_encrypted)), float(decrypt_data(lng_encrypted))
    except (TypeError, ValueError):
        return None


def restaurant_point(restaurant: Optional[RestaurantRecord]) -> Optional[Point]:
    """Where the food is cooked, from the restaurant's encrypted columns."""
    if restaurant is None:
        return None
    return point_of(restaurant.lat_encrypted, restaurant.lng_encrypted)


def pickup_summary(restaurant: Optional[RestaurantRecord]) -> Optional[LocationSummary]:
    """Where a driver collects the food.

    Read from the restaurant rather than copied onto the order, so a restaurant
    that moves is still found.
    """
    if restaurant is None:
        return None

    return LocationSummary(
        address=restaurant.address or "",
        city=restaurant.city or "",
        zip_code=restaurant.zip_code or "",
    )


async def restaurants_by_id(
    db: AsyncSession, restaurant_ids: Set[str]
) -> Dict[str, RestaurantRecord]:
    """Every restaurant on a page of orders, in one query."""
    if not restaurant_ids:
        return {}

    result = await db.execute(
        select(RestaurantRecord).where(
            RestaurantRecord.restaurant_id.in_(restaurant_ids)
        )
    )
    return {record.restaurant_id: record for record in result.scalars().all()}


async def dropoffs_by_order(
    db: AsyncSession, order_ids: List[str]
) -> Dict[str, Point]:
    """Decrypted dropoff coordinates, for the orders that have any."""
    if not order_ids:
        return {}

    result = await db.execute(
        select(OrderLocationRecord).where(OrderLocationRecord.order_id.in_(order_ids))
    )
    points: Dict[str, Point] = {}
    for record in result.scalars().all():
        point = point_of(record.lat_encrypted, record.lng_encrypted)
        if point is not None:
            points[record.order_id] = point
    return points


async def delivery_details_by_order(
    db: AsyncSession, order_ids: List[str]
) -> Dict[str, OrderDeliveryDetailsRecord]:
    """What each customer asked for at checkout, for the orders that said."""
    if not order_ids:
        return {}

    result = await db.execute(
        select(OrderDeliveryDetailsRecord).where(
            OrderDeliveryDetailsRecord.order_id.in_(order_ids)
        )
    )
    return {record.order_id: record for record in result.scalars().all()}


async def payments_by_order(
    db: AsyncSession, order_ids: List[str]
) -> Dict[str, OrderPaymentRecord]:
    """The payment row behind each order, for the orders that have one.

    Batched for the order lists: a customer's page asks "paid or not" of every
    row, and a query per row would turn one screen into fifty. Orders that
    predate payments simply have no entry, which the caller reads as pending.
    """
    if not order_ids:
        return {}

    result = await db.execute(
        select(OrderPaymentRecord).where(
            OrderPaymentRecord.order_id.in_(order_ids)
        )
    )
    return {record.order_id: record for record in result.scalars().all()}


async def order_or_none(db: AsyncSession, order_id: str) -> Optional[OrderRecord]:
    """One order row, or None."""
    result = await db.execute(
        select(OrderRecord).where(OrderRecord.order_id == order_id)
    )
    return result.scalar_one_or_none()
