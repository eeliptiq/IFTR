"""
Driver endpoints: registration, the vehicle, availability, and the jobs on
offer.

Mounted under /api (see app/main.py). The driver screen works its side of the
order lifecycle with these plus `PUT /orders/{id}/status` (app/api/orders.py),
which is the same endpoint the restaurant screen uses - who may take which step
is decided there from the caller's relationship to the order.

Two behaviours are dictated by the merged screen and are easy to break:

  * `GET /drivers/profile` answers 404 with exactly "Driver not found" when the
    caller has no driver record. The screen treats that string as "show the
    registration form", so it is a contract, not a message (see
    DRIVER_NOT_FOUND).
  * `GET /drivers/active-delivery` answers 200 with `null` when the driver has
    no job in hand. The screen awaits it without catching, so a 404 here would
    reject the whole page load and hide the orders on offer.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.audit import change_role
from app.core.auth import get_current_user
from app.core.encryption import encrypt_data
from app.core.geo import bearing_degrees, straight_line_km
from app.api._lookups import (
    Point,
    delivery_details_by_order,
    dropoffs_by_order,
    pickup_summary,
    restaurant_or_none,
    restaurant_point,
    restaurants_by_id,
)
from app.models.driver_orm import DriverRecord, OrderDeclineRecord
from app.models.general import OrderStatus, UserRole, vehicle_eta_minutes
from app.models.order_orm import OrderDeliveryDetailsRecord, OrderRecord
from app.models.organization_orm import OrganizationRecord
from app.models.restaurant_orm import RestaurantRecord
from app.models.surplus_food import SurplusDeliveryStatus
from app.models.surplus_food_orm import SurplusDeliveryRecord
from app.models.user_orm import UserRecord
from app.order_flow import OrderFlowManager
from app.schemas.driver import (
    DriverEarningsResponse,
    DriverJobResponse,
    DriverRegisterRequest,
    DriverResponse,
    DriverVehicleUpdateRequest,
    EarningsPeriod,
    RecentDelivery,
)
from app.schemas.order import LocationSummary
from app.schemas.surplus import SurplusDeliveryResponse

router = APIRouter(prefix="/drivers", tags=["drivers"])

# The screen matches this exact detail to decide it should offer registration.
DRIVER_NOT_FOUND = "Driver not found"

# An order a driver is carrying or on the way to collect.
ACTIVE_STATUSES = (
    OrderStatus.ASSIGNED.value,
    OrderStatus.PICKED_UP.value,
    OrderStatus.IN_TRANSIT.value,
)

# The longest trip worth offering. Quoted on the driver's own vehicle, so this
# is a real filter rather than a distance in disguise: twelve kilometres is a
# long haul by car and an hour and a half on foot, and only one of those is work
# anybody wants.
MAX_JOB_ETA_MINUTES = 60


def _with_trip(
    view: DriverJobResponse,
    origin: Optional[Point],
    dropoff: Optional[Point],
    vehicle_type: str,
) -> DriverJobResponse:
    """Attach the trip to a job view, when both ends of it are known."""
    if origin is None or dropoff is None:
        return view

    view.plan_trip(
        straight_line_km(origin[0], origin[1], dropoff[0], dropoff[1]),
        bearing_degrees(origin[0], origin[1], dropoff[0], dropoff[1]),
        vehicle_type,
    )
    return view


def _with_delivery(
    view: DriverJobResponse,
    details: Optional[OrderDeliveryDetailsRecord],
) -> DriverJobResponse:
    """Attach what the customer asked for at checkout, when the order has it.

    An order placed by a script or before checkout existed has no row here; the
    screen then falls back to its own default rather than being told a choice
    nobody made.
    """
    view.with_delivery(
        details.instruction_type if details else None,
        details.delivery_speed if details else None,
    )
    return view


async def _current_driver(user: UserRecord, db: AsyncSession) -> DriverRecord:
    """The caller's driver record, or a 404 the screen understands."""
    result = await db.execute(
        select(DriverRecord).where(DriverRecord.user_id == user.user_id)
    )
    driver = result.scalar_one_or_none()
    if driver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=DRIVER_NOT_FOUND
        )
    return driver


@router.post(
    "/register", response_model=DriverResponse, status_code=status.HTTP_201_CREATED
)
async def register_driver(
    body: DriverRegisterRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sign the current user up as a driver."""
    existing = await db.execute(
        select(DriverRecord).where(DriverRecord.user_id == current_user.user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already registered as driver",
        )

    driver = DriverRecord(
        user_id=current_user.user_id,
        vehicle_type=body.vehicle_type.value,
        license_number_encrypted=(
            encrypt_data(body.license_number.strip()) if body.license_number else ""
        ),
    )
    db.add(driver)

    # Promote the account so driver-specific UI unlocks, as registering a
    # restaurant does for its owner. Recorded with the role they held before.
    change_role(
        db,
        current_user,
        UserRole.DRIVER.value,
        detail="registered as a driver",
    )

    await db.flush()
    return DriverResponse.from_record(driver)


@router.get("/profile", response_model=DriverResponse)
async def get_driver_profile(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's driver record. 404s when they have not registered."""
    return DriverResponse.from_record(await _current_driver(current_user, db))


@router.put("/vehicle", response_model=DriverResponse)
async def update_driver_vehicle(
    body: DriverVehicleUpdateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the vehicle, and the licence if one was sent."""
    driver = await _current_driver(current_user, db)

    driver.vehicle_type = body.vehicle_type.value
    if body.license_number:
        driver.license_number_encrypted = encrypt_data(body.license_number.strip())

    await db.flush()
    return DriverResponse.from_record(driver)


@router.put("/availability", response_model=DriverResponse)
async def set_driver_availability(
    is_available: bool = Query(
        ...,
        description="Whether the driver is online and wants new jobs.",
    ),
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Go online or offline.

    Availability gates the list of jobs on offer, so going offline does what the
    screen says it does. It is not required to finish a job already in hand: the
    orders a driver has accepted stay reachable through the active job.
    """
    driver = await _current_driver(current_user, db)

    driver.is_available = is_available
    await db.flush()
    return DriverResponse.from_record(driver)


@router.get("/available-orders", response_model=List[DriverJobResponse])
async def get_available_orders(
    include_rejected: bool = Query(
        False,
        description=(
            "Also offer the jobs this driver passed on earlier, flagged as "
            "rejected. Used by the screen's 'show rejected orders' button."
        ),
    ),
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Orders a driver can claim: cooked, claimed by nobody, and worth the trip.

    Ready only - not the orders still being prepared. Offering food that is not
    cooked yet would let a driver claim an order the kitchen had not finished,
    and a claimed order is one the kitchen can no longer cancel or move on.

    Realistic only: an order whose ETA on this driver's vehicle exceeds
    MAX_JOB_ETA_MINUTES is left off the board, because offering work nobody can
    finish is not a choice, it is noise. An order with no location on file is
    still offered - it cannot be judged, and hiding it would look like the
    order does not exist.

    Shortest trip first, so the board reads as a ranking of what is quickest to
    do rather than as a queue by age. Ties keep the oldest-first order the query
    came back in.
    """
    driver = await _current_driver(current_user, db)

    if not driver.is_available:
        return []

    # A job this driver already passed on stays off their board unless they ask
    # for it back. The exclusion is a subquery rather than filtering in Python
    # so the database does the work the poll repeats.
    declined = select(OrderDeclineRecord.order_id).where(
        OrderDeclineRecord.driver_id == driver.driver_id
    )

    query = (
        select(OrderRecord)
        .where(OrderRecord.status == OrderStatus.READY.value)
        .where(OrderRecord.driver_id.is_(None))
    )
    if not include_rejected:
        query = query.where(~OrderRecord.order_id.in_(declined))

    result = await db.execute(query.order_by(OrderRecord.created_at.asc()))
    records = list(result.scalars().all())

    rejected_ids: Set[str] = set()
    if include_rejected and records:
        previously = await db.execute(
            select(OrderDeclineRecord.order_id).where(
                OrderDeclineRecord.driver_id == driver.driver_id,
                OrderDeclineRecord.order_id.in_([r.order_id for r in records]),
            )
        )
        rejected_ids = {row[0] for row in previously.all()}

    kitchens = await restaurants_by_id(db, {r.restaurant_id for r in records})
    dropoffs = await dropoffs_by_order(db, [r.order_id for r in records])
    chosen = await delivery_details_by_order(db, [r.order_id for r in records])

    # A job offer carries neither the customer's details nor the addresses: what
    # is on offer is the shape of the work, and the places to go come with the
    # job once it is claimed. What it does carry is the trip and the handling
    # plan, so a driver can decide whether to take the work before taking it.
    offers: List[DriverJobResponse] = []
    for record in records:
        restaurant = kitchens.get(record.restaurant_id)
        view = DriverJobResponse.for_job_offer(
            record, restaurant_name=restaurant.name if restaurant else ""
        ).plan_for(driver.vehicle_type)
        view.was_rejected = record.order_id in rejected_ids
        view = _with_delivery(view, chosen.get(record.order_id))
        view = _with_trip(
            view,
            restaurant_point(restaurant),
            dropoffs.get(record.order_id),
            driver.vehicle_type,
        )

        if view.eta_minutes is not None and view.eta_minutes > MAX_JOB_ETA_MINUTES:
            continue
        offers.append(view)

    offers.sort(key=lambda offer: (offer.eta_minutes is None, offer.eta_minutes or 0))
    return offers


@router.post("/accept-order/{order_id}", response_model=DriverJobResponse)
async def accept_order(
    order_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Claim a ready order.

    The claim is a single conditional UPDATE rather than a read followed by a
    write, because two drivers tapping at the same moment is exactly its failure
    mode: whoever's statement matches no row loses, and is told so.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(OrderRecord).where(OrderRecord.order_id == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    # Someone else's order is reported as taken, not as "not ready yet": an
    # order stops being ready precisely because a driver took it, and saying
    # otherwise would send the next driver looking for a kitchen that finished.
    if order.driver_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Order already taken"
        )

    if order.status != OrderStatus.READY.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only a ready order can be accepted; this one is "
                f"{order.status}"
            ),
        )

    now = datetime.now(timezone.utc)
    claimed = await db.execute(
        update(OrderRecord)
        .where(OrderRecord.order_id == order_id)
        .where(OrderRecord.status == OrderStatus.READY.value)
        .where(OrderRecord.driver_id.is_(None))
        .values(
            driver_id=driver.driver_id,
            driver_name=current_user.name or "",
            status=OrderStatus.ASSIGNED.value,
            # The same field the flow table declares for this status, so the
            # claim cannot drift from every other transition.
            **{OrderFlowManager.TIMESTAMP_FIELDS[OrderStatus.ASSIGNED]: now},
            updated_at=now,
        )
    )

    if claimed.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order already taken by another driver",
        )

    refreshed = await db.execute(
        select(OrderRecord).where(OrderRecord.order_id == order_id)
    )

    # The job is theirs now, so the reply includes where to collect it: the next
    # thing the driver does is drive there.
    restaurant = await restaurant_or_none(db, order.restaurant_id)
    claimed_view = DriverJobResponse.for_active_job(
        refreshed.scalar_one(),
        pickup=pickup_summary(restaurant),
        restaurant_name=restaurant.name if restaurant else "",
    )
    claimed_view.plan_for(driver.vehicle_type)
    _with_delivery(
        claimed_view,
        (await delivery_details_by_order(db, [order_id])).get(order_id),
    )
    return _with_trip(
        claimed_view,
        restaurant_point(restaurant),
        (await dropoffs_by_order(db, [order_id])).get(order_id),
        driver.vehicle_type,
    )


@router.post("/decline-order/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def decline_order(
    order_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Pass on a job, without taking it away from anyone else.

    A decline is personal: the order stays on other drivers' boards and stays
    claimable by this one (the accept path does not consult declines - a driver
    who changes their mind at the pickup is not a state worth modelling).

    Idempotent: declining twice is one fact, and the second call succeeds, so a
    double-tap or a retried request is not an error the screen has to explain.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(OrderRecord).where(OrderRecord.order_id == order_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    # Someone already carrying the order has nothing to reject; reporting that
    # keeps a stale card from claiming a decline was recorded against live work.
    existing = await db.execute(
        select(OrderRecord.driver_id).where(OrderRecord.order_id == order_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Order already taken"
        )

    already = await db.execute(
        select(OrderDeclineRecord).where(
            OrderDeclineRecord.driver_id == driver.driver_id,
            OrderDeclineRecord.order_id == order_id,
        )
    )
    if already.scalar_one_or_none() is None:
        db.add(OrderDeclineRecord(driver_id=driver.driver_id, order_id=order_id))
        await db.flush()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/active-delivery", response_model=Optional[DriverJobResponse])
async def get_active_delivery(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The order the driver is on, or null when they are not on one.

    Null rather than 404: the screen asks for this on every poll and treats the
    answer as "what am I carrying", so "nothing" is a normal reply.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(OrderRecord)
        .where(OrderRecord.driver_id == driver.driver_id)
        .where(OrderRecord.status.in_(ACTIVE_STATUSES))
        .order_by(OrderRecord.assigned_at.desc())
    )
    order = result.scalars().first()
    if order is None:
        return None

    # Planned against the vehicle as it is now: a driver who switched to a
    # bicycle after claiming a drink order is told to bring a cup holder.
    restaurant = await restaurant_or_none(db, order.restaurant_id)
    active_view = DriverJobResponse.for_active_job(
        order,
        pickup=pickup_summary(restaurant),
        restaurant_name=restaurant.name if restaurant else "",
    )
    active_view.plan_for(driver.vehicle_type)
    _with_delivery(
        active_view,
        (await delivery_details_by_order(db, [order.order_id])).get(order.order_id),
    )
    return _with_trip(
        active_view,
        restaurant_point(restaurant),
        (await dropoffs_by_order(db, [order.order_id])).get(order.order_id),
        driver.vehicle_type,
    )


# --------------------------------------------------------------------------
# Volunteer surplus runs
# --------------------------------------------------------------------------

# What a run is quoted at when neither end of it is located. The screen renders
# its own 20 too, so the card never has to invent a number.
DEFAULT_SURPLUS_MINUTES = 20

# A claimed run moves one way only: collect the food, drive it, hand it over.
# The table is the whole vocabulary the endpoint accepts, so a stale screen
# cannot skip from `assigned` to `delivered` and book a delivery that never
# happened.
SURPLUS_TRANSITIONS = {
    SurplusDeliveryStatus.ASSIGNED.value: SurplusDeliveryStatus.PICKED_UP.value,
    SurplusDeliveryStatus.PICKED_UP.value: SurplusDeliveryStatus.IN_TRANSIT.value,
    SurplusDeliveryStatus.IN_TRANSIT.value: SurplusDeliveryStatus.DELIVERED.value,
}

# The stages that are still somebody's job in hand. Delivered and cancelled are
# terminal, so they leave the driver's active list.
SURPLUS_ACTIVE_STATUSES = (
    SurplusDeliveryStatus.ASSIGNED.value,
    SurplusDeliveryStatus.PICKED_UP.value,
    SurplusDeliveryStatus.IN_TRANSIT.value,
)


def _surplus_view(
    record: SurplusDeliveryRecord,
    vehicle_type: str,
    include_places: bool = False,
) -> SurplusDeliveryResponse:
    """A volunteer run quoted on this driver's vehicle.

    The stored estimate is for a car, because that is what the reservation was
    quoted at. Re-quoting here is the same choice the order board makes: a trip
    offered to somebody on foot is a different trip.
    """
    distance = record.distance_km
    estimated = (
        vehicle_eta_minutes(vehicle_type, distance)
        if distance is not None
        else (record.estimated_time or DEFAULT_SURPLUS_MINUTES)
    )
    return SurplusDeliveryResponse.from_record(
        record,
        distance_km=distance,
        estimated_time=estimated,
        include_places=include_places,
    )


@router.get("/surplus-deliveries", response_model=List[SurplusDeliveryResponse])
async def get_surplus_deliveries(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Surplus runs nobody has volunteered for, oldest first.

    Gated on availability like the paid board: going offline means "no work",
    and a volunteer run is work even though it pays nothing. The card shows the
    restaurant and the organization, not the addresses - a driver who has not
    taken the run has no business with either door.
    """
    driver = await _current_driver(current_user, db)
    if not driver.is_available:
        return []

    result = await db.execute(
        select(SurplusDeliveryRecord)
        .where(SurplusDeliveryRecord.status == SurplusDeliveryStatus.PENDING.value)
        .where(SurplusDeliveryRecord.driver_id.is_(None))
        .order_by(SurplusDeliveryRecord.created_at.asc())
        .limit(50)
    )
    return [
        _surplus_view(record, driver.vehicle_type)
        for record in result.scalars().all()
    ]


@router.post(
    "/volunteer-surplus/{delivery_id}", response_model=SurplusDeliveryResponse
)
async def volunteer_for_surplus_delivery(
    delivery_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Take a surplus run.

    The claim is a single conditional UPDATE, so two drivers tapping at once
    resolve to one volunteer and one "already taken". The run is marked
    `assigned`, not `picked_up`: saying a driver has the food before they have
    been to the restaurant would be a fact the database cannot know. The reply
    carries both addresses, because collecting it is the next thing they do.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(SurplusDeliveryRecord).where(
            SurplusDeliveryRecord.delivery_id == delivery_id
        )
    )
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Surplus delivery not found",
        )
    if delivery.driver_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delivery already taken by another volunteer",
        )
    if delivery.status != SurplusDeliveryStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This run is already {delivery.status}",
        )

    now = datetime.now(timezone.utc)
    estimated = _surplus_view(delivery, driver.vehicle_type).estimated_time

    claimed = await db.execute(
        update(SurplusDeliveryRecord)
        .where(SurplusDeliveryRecord.delivery_id == delivery_id)
        .where(SurplusDeliveryRecord.driver_id.is_(None))
        .where(
            SurplusDeliveryRecord.status == SurplusDeliveryStatus.PENDING.value
        )
        .values(
            driver_id=driver.driver_id,
            driver_name=current_user.name or "",
            status=SurplusDeliveryStatus.ASSIGNED.value,
            assigned_at=now,
            estimated_time=estimated,
        )
    )
    if claimed.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delivery already taken by another volunteer",
        )

    await db.refresh(delivery)
    return _surplus_view(
        delivery, driver.vehicle_type, include_places=True
    )


@router.post(
    "/surplus-deliveries/{delivery_id}/abandon",
    response_model=SurplusDeliveryResponse,
)
async def abandon_surplus_delivery(
    delivery_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Hand a claimed run back before collecting the food.

    Going back on a claim is a real thing: a volunteer's afternoon changes, or
    they realise the trip is longer than the board quoted. Before pickup the
    run is still at the restaurant, so returning it to `pending` puts it back on
    every volunteer's board with no physical consequence.

    After pickup it cannot be returned: the food is in the volunteer's hands,
    and offering it to somebody else would send them to a counter that no longer
    has it. That case is a `409` asking them to finish the delivery instead.

    The release is conditional on the run still being the `assigned` row this
    volunteer read, so a tap that races a pickup cannot reopen a run already
    under way.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(SurplusDeliveryRecord).where(
            SurplusDeliveryRecord.delivery_id == delivery_id
        )
    )
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Surplus delivery not found",
        )
    if delivery.driver_id != driver.driver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your delivery",
        )
    if delivery.status != SurplusDeliveryStatus.ASSIGNED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cannot abandon a run after the food has been collected; "
                "complete the delivery instead"
            ),
        )

    released = await db.execute(
        update(SurplusDeliveryRecord)
        .where(SurplusDeliveryRecord.delivery_id == delivery_id)
        .where(SurplusDeliveryRecord.driver_id == driver.driver_id)
        .where(
            SurplusDeliveryRecord.status == SurplusDeliveryStatus.ASSIGNED.value
        )
        .values(
            status=SurplusDeliveryStatus.PENDING.value,
            driver_id=None,
            driver_name="",
            assigned_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    if released.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delivery changed while updating; refresh and try again",
        )

    await db.refresh(delivery)
    # No addresses on the way out: the caller is no longer carrying the run, and
    # the people who can take it next will be shown them when they claim it.
    return _surplus_view(delivery, driver.vehicle_type, include_places=False)


@router.get("/active-surplus", response_model=List[SurplusDeliveryResponse])
async def get_active_surplus(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Volunteer runs this driver has claimed and not yet finished.

    The board only lists runs nobody has taken, so this is the other half: a
    claimed run needs somewhere to live after a reload. A list rather than one
    row because nothing stops a volunteer from taking a second run while the
    first is still waiting at the restaurant; the screen shows every one.

    Addresses are included - the driver is the one carrying these.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(SurplusDeliveryRecord)
        .where(SurplusDeliveryRecord.driver_id == driver.driver_id)
        .where(SurplusDeliveryRecord.status.in_(SURPLUS_ACTIVE_STATUSES))
        .order_by(SurplusDeliveryRecord.assigned_at.asc())
    )
    return [
        _surplus_view(record, driver.vehicle_type, include_places=True)
        for record in result.scalars().all()
    ]


@router.put(
    "/surplus-deliveries/{delivery_id}/status",
    response_model=SurplusDeliveryResponse,
)
async def update_surplus_status(
    delivery_id: str,
    new_status: SurplusDeliveryStatus = Query(
        ...,
        alias="status",
        description="The next stage of the run.",
    ),
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Move a claimed volunteer run along: picked up, in transit, delivered.

    Only the volunteer carrying it may advance it, and only one step at a time.
    The write is conditional on the status that was read, so two taps on
    "Complete" cannot deliver the same food twice - the loser is told the run
    changed instead of incrementing the counters again.

    Delivering is also the moment the rescue becomes a receipt: the portions
    are added to the organization's `total_received` and the restaurant's
    `total_meals_donated`, in the same transaction as the status change. Doing
    it on `assigned` would count food that might never arrive; doing it in a
    second request would leave a delivered run that no counter knows about.
    """
    driver = await _current_driver(current_user, db)

    result = await db.execute(
        select(SurplusDeliveryRecord).where(
            SurplusDeliveryRecord.delivery_id == delivery_id
        )
    )
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Surplus delivery not found",
        )
    if delivery.driver_id != driver.driver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your delivery",
        )

    current_status = delivery.status
    expected = SURPLUS_TRANSITIONS.get(current_status)
    if expected != new_status.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot move a surplus delivery from {current_status} to "
                f"{new_status.value}"
                + (f"; the next step is {expected}" if expected else "")
            ),
        )

    now = datetime.now(timezone.utc)
    values = {"status": new_status.value}
    if new_status is SurplusDeliveryStatus.PICKED_UP:
        values["picked_up_at"] = now
    elif new_status is SurplusDeliveryStatus.DELIVERED:
        values["delivered_at"] = now

    moved = await db.execute(
        update(SurplusDeliveryRecord)
        .where(SurplusDeliveryRecord.delivery_id == delivery_id)
        .where(SurplusDeliveryRecord.driver_id == driver.driver_id)
        .where(SurplusDeliveryRecord.status == current_status)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if moved.rowcount != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delivery changed while updating; refresh and try again",
        )

    if new_status is SurplusDeliveryStatus.DELIVERED:
        # One portion count, added to both sides of the rescue: what the
        # organization received and what the restaurant gave away.
        await db.execute(
            update(OrganizationRecord)
            .where(OrganizationRecord.org_id == delivery.org_id)
            .values(
                total_received=OrganizationRecord.total_received
                + delivery.quantity
            )
        )
        if delivery.restaurant_id:
            await db.execute(
                update(RestaurantRecord)
                .where(
                    RestaurantRecord.restaurant_id == delivery.restaurant_id
                )
                .values(
                    total_meals_donated=RestaurantRecord.total_meals_donated
                    + delivery.quantity
                )
            )

    await db.refresh(delivery)
    return _surplus_view(delivery, driver.vehicle_type, include_places=True)


@router.get("/earnings", response_model=DriverEarningsResponse)
async def driver_earnings(
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    What this driver's completed trips were worth.

    A trip is worth its delivery fee plus its tip. That is what the customer's
    payment covered for the trip, not a settled payout: there is no commission
    to subtract yet and no transfer to the driver's account has happened.
    Volunteer surplus runs are counted separately (`surplus_runs`) and never as
    paid deliveries, because they pay nothing.

    The windows are rolling - since UTC midnight, the last 7 days, the last 30
    days - rather than calendar weeks and months, which need a timezone the
    platform does not have. Trips with no `delivered_at` stamp (seeded rows from
    before the driver slice) still count in the lifetime total but in no window,
    because there is no date to put them in.
    """
    driver = await _current_driver(current_user, db)

    async def totals(since: Optional[datetime] = None) -> EarningsPeriod:
        query = select(
            func.count(OrderRecord.order_id),
            func.coalesce(func.sum(OrderRecord.delivery_fee), 0.0),
            func.coalesce(func.sum(OrderRecord.tip_amount), 0.0),
        ).where(
            OrderRecord.driver_id == driver.driver_id,
            OrderRecord.status == OrderStatus.DELIVERED.value,
        )
        if since is not None:
            query = query.where(OrderRecord.delivered_at >= since)

        deliveries, fees, tips = (await db.execute(query)).one()
        fees = round(float(fees or 0.0), 2)
        tips = round(float(tips or 0.0), 2)
        return EarningsPeriod(
            deliveries=int(deliveries or 0),
            delivery_fees=fees,
            tips=tips,
            earnings=round(fees + tips, 2),
        )

    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lifetime = await totals()

    completed_runs = await db.execute(
        select(func.count())
        .select_from(SurplusDeliveryRecord)
        .where(
            SurplusDeliveryRecord.driver_id == driver.driver_id,
            SurplusDeliveryRecord.status == SurplusDeliveryStatus.DELIVERED.value,
        )
    )

    recent_rows = await db.execute(
        select(OrderRecord)
        .where(
            OrderRecord.driver_id == driver.driver_id,
            OrderRecord.status == OrderStatus.DELIVERED.value,
            OrderRecord.delivered_at.isnot(None),
        )
        .order_by(OrderRecord.delivered_at.desc())
        .limit(5)
    )
    recent = []
    for order in recent_rows.scalars().all():
        fees = round(float(order.delivery_fee or 0.0), 2)
        tips = round(float(order.tip_amount or 0.0), 2)
        recent.append(
            RecentDelivery(
                order_id=order.order_id,
                delivered_at=order.delivered_at,
                delivery_fees=fees,
                tips=tips,
                earnings=round(fees + tips, 2),
            )
        )

    return DriverEarningsResponse(
        total_deliveries=lifetime.deliveries,
        total_earnings=lifetime.earnings,
        today=await totals(midnight),
        week=await totals(now - timedelta(days=7)),
        month=await totals(now - timedelta(days=30)),
        surplus_runs=int(completed_runs.scalar_one() or 0),
        recent=recent,
    )
