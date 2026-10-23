"""
Surplus food endpoints: what a restaurant has going spare, and what an
organization reserves.

Mounted under /api (see app/main.py). The volunteer half of the flow - a driver
picking a run up - lives with the rest of the driver endpoints in
app/api/drivers.py.

The rules that matter:

  * Only the owner of a registered restaurant may list surplus, and the pickup
    point comes from the restaurant record rather than the request, so a listing
    cannot point a volunteer at an arbitrary address.
  * Only a *verified* organization may reserve. Verification is an admin
    decision (a later slice); until then a new organization can browse.
  * Stock is claimed with one conditional UPDATE. Two organizations tapping
    "reserve the last 3" at the same time resolve to one winner and one "only N
    left", never to a negative shelf.
  * A reservation is stored as a volunteer delivery row, so splitting one
    listing between two organizations keeps each organization's amount and
    status separate.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._lookups import point_of
from app.api.organizations import current_organization
from app.core.auth import get_current_user
from app.core.geo import straight_line_km
from app.database import get_db
from app.models.general import VehicleType, vehicle_eta_minutes
from app.models.restaurant_orm import RestaurantRecord
from app.models.surplus_food import SurplusDeliveryStatus
from app.models.surplus_food_orm import SurplusDeliveryRecord, SurplusFoodRecord
from app.models.user_orm import UserRecord
from app.schemas.surplus import (
    ReservedSurplusResponse,
    SurplusCreateRequest,
    SurplusFoodResponse,
    SurplusReservationResponse,
    SurplusReserveRequest,
)

router = APIRouter(prefix="/surplus", tags=["surplus"])

# What a volunteer run is quoted at before anybody has claimed it: a car, since
# that is the default vehicle and the board re-quotes for whoever takes it.
DEFAULT_VOLUNTEER_MINUTES = 20


def _active_filter():
    """The conditions under which a listing can still be reserved."""
    return (
        SurplusFoodRecord.is_available.is_(True),
        SurplusFoodRecord.quantity > 0,
        SurplusFoodRecord.expiry_time > datetime.now(timezone.utc),
    )


def _pickup_from_restaurant(record: RestaurantRecord) -> dict:
    return {
        "pickup_lat_encrypted": record.lat_encrypted or "",
        "pickup_lng_encrypted": record.lng_encrypted or "",
        "pickup_address": record.address or "",
        "pickup_city": record.city or "",
        "pickup_zip_code": record.zip_code or "",
    }


def _pickup_from_listing(record: SurplusFoodRecord) -> dict:
    return {
        "pickup_lat_encrypted": record.pickup_lat_encrypted or "",
        "pickup_lng_encrypted": record.pickup_lng_encrypted or "",
        "pickup_address": record.pickup_address or "",
        "pickup_city": record.pickup_city or "",
        "pickup_zip_code": record.pickup_zip_code or "",
    }


@router.get("", response_model=List[SurplusFoodResponse])
async def list_surplus(
    available_only: bool = True,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Browse surplus food.

    By default only what can still be reserved: available, not expired, and with
    portions left. Soonest expiry first, because rescuing the food that spoils
    next is the point.
    """
    query = select(SurplusFoodRecord)
    if available_only:
        query = query.where(*_active_filter())

    result = await db.execute(
        query.order_by(SurplusFoodRecord.expiry_time.asc())
    )
    return [
        SurplusFoodResponse.from_record(record)
        for record in result.scalars().all()
    ]


@router.post(
    "",
    response_model=SurplusFoodResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_surplus(
    body: SurplusCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List surplus food from the caller's restaurant."""
    result = await db.execute(
        select(RestaurantRecord).where(
            RestaurantRecord.user_id == current_user.user_id
        )
    )
    restaurant = result.scalar_one_or_none()
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be a restaurant owner",
        )

    listing = SurplusFoodRecord(
        user_id=current_user.user_id,
        restaurant_id=restaurant.restaurant_id,
        restaurant_name=restaurant.name,
        description=body.description.strip(),
        quantity=body.quantity,
        original_price=body.original_price,
        discounted_price=body.discounted_price,
        expiry_time=datetime.now(timezone.utc) + timedelta(hours=body.expiry_hours),
        **_pickup_from_restaurant(restaurant),
    )
    db.add(listing)
    await db.flush()
    return SurplusFoodResponse.from_record(listing)


@router.get("/reservations", response_model=List[ReservedSurplusResponse])
async def my_reservations(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The caller organization's reservations, newest first.

    Each row is one reservation, with the number of portions that organization
    booked and the state of its volunteer run. That is what the received page
    reads; the public listing's `quantity` is the shelf, not the booking.
    """
    organization = await current_organization(db, current_user)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an organization",
        )

    result = await db.execute(
        select(SurplusDeliveryRecord, SurplusFoodRecord)
        .join(
            SurplusFoodRecord,
            SurplusFoodRecord.surplus_id == SurplusDeliveryRecord.surplus_id,
        )
        .where(SurplusDeliveryRecord.org_id == organization.org_id)
        .order_by(SurplusDeliveryRecord.created_at.desc())
    )
    return [
        ReservedSurplusResponse.from_records(delivery, listing)
        for delivery, listing in result.all()
    ]


@router.post(
    "/{surplus_id}/reserve",
    response_model=SurplusReservationResponse,
)
async def reserve_surplus(
    surplus_id: str,
    body: Optional[SurplusReserveRequest] = None,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reserve some (or all) of a listing, and ask a volunteer to move it.

    The decrement is the concurrency guard: the UPDATE only matches while the
    shelf still holds that many portions and the listing is still live, so the
    loser of a race is told how much is left instead of overbooking the food.
    """
    organization = await current_organization(db, current_user)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an organization",
        )
    if not organization.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization must be verified by admin",
        )

    result = await db.execute(
        select(SurplusFoodRecord).where(
            SurplusFoodRecord.surplus_id == surplus_id
        )
    )
    listing = result.scalar_one_or_none()
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Surplus food not found",
        )

    now = datetime.now(timezone.utc)
    expiry = listing.expiry_time
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry is not None and expiry <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Surplus listing has expired",
        )

    requested = body.quantity if body and body.quantity is not None else listing.quantity
    if listing.quantity <= 0 or not listing.is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Surplus listing is no longer available",
        )
    if requested > listing.quantity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only {listing.quantity} portion(s) available",
        )

    remaining = SurplusFoodRecord.quantity - requested
    claimed = await db.execute(
        update(SurplusFoodRecord)
        .where(
            SurplusFoodRecord.surplus_id == surplus_id,
            SurplusFoodRecord.is_available.is_(True),
            SurplusFoodRecord.quantity >= requested,
            SurplusFoodRecord.expiry_time > now,
        )
        .values(
            quantity=remaining,
            # The last portion closes the listing; a partial reservation leaves
            # the rest on the shelf for somebody else.
            is_available=case((remaining <= 0, False), else_=True),
            reserved_by_org_id=case(
                (remaining <= 0, organization.org_id),
                else_=SurplusFoodRecord.reserved_by_org_id,
            ),
            updated_at=now,
        )
        # The session object is refreshed below. Letting SQLAlchemy evaluate
        # the SET against it would compare the aware `now` bound above with the
        # naive datetime SQLite loads, which raises instead of updating.
        .execution_options(synchronize_session=False)
    )

    if claimed.rowcount != 1:
        fresh = await db.execute(
            select(SurplusFoodRecord.quantity).where(
                SurplusFoodRecord.surplus_id == surplus_id
            )
        )
        left = fresh.scalar_one_or_none() or 0
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only {left} portion(s) left"
                if left > 0
                else "Surplus listing is no longer available"
            ),
        )

    await db.refresh(listing)

    # Where the food is: the restaurant's current address rather than the
    # listing's snapshot, so a kitchen that has moved is still found.
    restaurant = None
    if listing.restaurant_id:
        found = await db.execute(
            select(RestaurantRecord).where(
                RestaurantRecord.restaurant_id == listing.restaurant_id
            )
        )
        restaurant = found.scalar_one_or_none()
    pickup = (
        _pickup_from_restaurant(restaurant)
        if restaurant is not None
        else _pickup_from_listing(listing)
    )

    pickup_point = point_of(
        pickup["pickup_lat_encrypted"], pickup["pickup_lng_encrypted"]
    )
    dropoff_point = point_of(organization.lat_encrypted, organization.lng_encrypted)

    distance_km = None
    if pickup_point is not None and dropoff_point is not None:
        distance_km = straight_line_km(
            pickup_point[0],
            pickup_point[1],
            dropoff_point[0],
            dropoff_point[1],
        )

    delivery = SurplusDeliveryRecord(
        surplus_id=listing.surplus_id,
        restaurant_id=listing.restaurant_id,
        restaurant_name=listing.restaurant_name or "",
        org_id=organization.org_id,
        org_name=organization.name,
        status=SurplusDeliveryStatus.PENDING.value,
        quantity=requested,
        # The card already prints the portion count beside this; repeating it
        # here read as "4x 10 portions of lasagna".
        description=listing.description,
        **pickup,
        dropoff_lat_encrypted=organization.lat_encrypted or "",
        dropoff_lng_encrypted=organization.lng_encrypted or "",
        dropoff_address=organization.delivery_address
        or organization.address
        or "",
        dropoff_city=organization.city or "",
        distance_km=distance_km,
        estimated_time=(
            vehicle_eta_minutes(VehicleType.CAR.value, distance_km)
            if distance_km is not None
            else DEFAULT_VOLUNTEER_MINUTES
        ),
    )
    db.add(delivery)
    await db.flush()

    return SurplusReservationResponse(
        message=(
            f"Reserved {requested} portion(s)! "
            "A volunteer driver will pick it up."
        ),
        surplus_id=listing.surplus_id,
        delivery_id=delivery.delivery_id,
        quantity_reserved=requested,
        quantity_remaining=listing.quantity,
    )
