"""
The platform's impact numbers, as one read.

The community impact page is for everybody, not only administrators: the
figures are counts of food moved and people served, with no personal data in
them, so a customer seeing them is the point. They are assembled here rather
than in `app/api/admin.py` because they are not a moderation tool.

What each number means - and deliberately does not mean:

  * `meals_delivered` - item quantities on orders that reached `delivered`. A
    line of two portions is two meals, not one order.
  * `meals_donated` - portions organizations have actually received, read from
    their stored `total_received`. That counter is maintained by the delivery
    transaction, so this is a receipt rather than an estimate.
  * `surplus_saved` - portions reserved off a surplus listing, however far the
    run has got. Once a portion is spoken for it is no longer going to waste,
    and a run still in a volunteer's bag is not un-rescued.
  * `delivered_value` - the sum of delivered orders' `total_amount`. It is what
    those orders were worth, not money the platform has collected: the admin
    summary's `total_revenue` is the paid subset, and the two are deliberately
    different numbers.
  * `active_restaurants` / `active_drivers` - accounts currently switched on,
    not historical totals.
  * `organizations_helped` - organizations that have received at least one
    portion. A verified organization waiting for its first run is not "helped"
    yet.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_db
from app.models.driver_orm import DriverRecord
from app.models.general import OrderStatus
from app.models.organization_orm import OrganizationRecord
from app.models.order_orm import OrderRecord
from app.models.restaurant_orm import RestaurantRecord
from app.models.surplus_food_orm import SurplusDeliveryRecord
from app.models.user_orm import UserRecord
from app.schemas.impact import ImpactStatsResponse

router = APIRouter(prefix="/impact", tags=["impact"])


async def _count(db: AsyncSession, query) -> int:
    result = await db.execute(query)
    return int(result.scalar_one() or 0)


async def _sum(db: AsyncSession, column, *conditions) -> float:
    """Sum a column, with 0 rather than None for an empty table."""
    query = select(func.coalesce(func.sum(column), 0))
    if conditions:
        query = query.where(*conditions)
    result = await db.execute(query)
    return float(result.scalar_one() or 0)


async def collect_stats(db: AsyncSession) -> ImpactStatsResponse:
    """
    Counts of what the platform has moved.

    Four small aggregates plus one pass over delivered orders for the meal
    count: the item list is JSON, and SQLite and PostgreSQL do not agree on how
    to sum inside it, so the rows are read and summed in Python. The list is
    bounded by "delivered orders", which is the whole point of the number.

    Shared with the administrator dashboard (`GET /admin/stats`), which shows a
    subset of the same figures; computing them twice would eventually disagree.
    """
    total_orders = await _count(db, select(func.count()).select_from(OrderRecord))
    active_orders = await _count(
        db,
        select(func.count())
        .select_from(OrderRecord)
        .where(
            OrderRecord.status.notin_(
                [OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value]
            )
        ),
    )
    delivered_orders = await _count(
        db,
        select(func.count())
        .select_from(OrderRecord)
        .where(OrderRecord.status == OrderStatus.DELIVERED.value),
    )

    delivered_rows = await db.execute(
        select(OrderRecord.items).where(
            OrderRecord.status == OrderStatus.DELIVERED.value
        )
    )
    meals_delivered = 0
    for (items,) in delivered_rows.all():
        for line in items or []:
            if isinstance(line, dict):
                meals_delivered += int(line.get("quantity") or 0)

    delivered_value = await _sum(
        db,
        OrderRecord.total_amount,
        OrderRecord.status == OrderStatus.DELIVERED.value,
    )

    meals_donated = await _sum(db, OrganizationRecord.total_received)
    active_restaurants = await _count(
        db,
        select(func.count())
        .select_from(RestaurantRecord)
        .where(RestaurantRecord.is_active.is_(True)),
    )
    active_drivers = await _count(
        db,
        select(func.count())
        .select_from(DriverRecord)
        .where(DriverRecord.is_available.is_(True)),
    )
    organizations_helped = await _count(
        db,
        select(func.count())
        .select_from(OrganizationRecord)
        .where(OrganizationRecord.total_received > 0),
    )
    surplus_saved = await _sum(db, SurplusDeliveryRecord.quantity)

    return ImpactStatsResponse(
        total_orders=total_orders,
        active_orders=active_orders,
        delivered_orders=delivered_orders,
        delivered_value=round(delivered_value, 2),
        meals_delivered=meals_delivered,
        meals_donated=int(meals_donated),
        active_restaurants=active_restaurants,
        active_drivers=active_drivers,
        organizations_helped=organizations_helped,
        surplus_saved=int(surplus_saved),
    )


@router.get("/stats", response_model=ImpactStatsResponse)
async def impact_stats(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The impact page's feed, available to every signed-in account."""
    return await collect_stats(db)
