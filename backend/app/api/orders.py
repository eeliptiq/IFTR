"""
Order endpoints addressed by order id.

Mounted under /api (see app/main.py). The restaurant screen works its queue with
these: it lists its own orders from /restaurants/{id}/orders (see
app/api/restaurants.py) and advances them here.

The new status arrives as a query parameter named `status` because that is what
the merged React screens send — `PUT /orders/{id}/status?status=preparing` with
an empty body. The Python argument is named `order_status` so it does not shadow
`fastapi.status`, with the wire name pinned via the alias.

Three screens call this one endpoint - the restaurant's queue, the driver's
delivery, and the customer cancelling from their tracking page - and the halves
of an order's life belong to different people. Who is acting is therefore
resolved from the order and the caller's records - owner of the restaurant, the
driver the order is assigned to, or the customer who placed it - and then
checked against that actor's edges in app/order_flow.py.

Order creation lives here too (`POST /orders`, see app/pricing.py for what it
costs): checkout is what makes the two queues and the tracking screen show real
data rather than seeded rows.
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.audit import DELIVERY_REASSIGNED
from app.core.auth import get_current_user
from app.core.encryption import encrypt_data
from app.core.geo import straight_line_km
from app.models.audit_orm import AuditEventRecord
from app.models.driver_orm import DriverRecord
from app.models.general import OrderStatus, VehicleType, vehicle_eta_minutes
from app.models.order_orm import (
    OrderDeliveryDetailsRecord,
    OrderIssueRecord,
    OrderLocationRecord,
    OrderRecord,
)
from app.models.payment_orm import PAYMENT_PAID
from app.models.restaurant_orm import RestaurantRecord
from app.models.user_orm import UserRecord
from app.order_flow import (
    CUSTOMER,
    DRIVER,
    RESTAURANT,
    OrderFlowManager,
    OrderTransitionError,
    OrderTransitionNotPermitted,
)
from app.pricing import ItemUnavailable, UnknownMenuItem, quote
from app.schemas.order import (
    AddTipRequest,
    AddTipResponse,
    OrderCreateRequest,
    OrderReassignmentResponse,
    OrderResponse,
    ReportIssueRequest,
    ReportIssueResponse,
)
from app.schemas._time import as_utc
from app.api._lookups import (
    delivery_details_by_order,
    dropoffs_by_order,
    order_or_none,
    payments_by_order,
    pickup_summary,
    restaurant_or_none,
    restaurant_point,
    restaurants_by_id,
)

router = APIRouter(prefix="/orders", tags=["orders"])

# The customer's orders page asks for at most this many; nobody pages yet.
CUSTOMER_ORDER_LIMIT = 50

# The restaurant's own half of the lifecycle is enforced by the flow manager; a
# refused move is a conflict with the order's current state, not a bad request.
_TRANSITION_REFUSED = status.HTTP_409_CONFLICT


def _estimated_minutes(
    restaurant: Optional[RestaurantRecord], dropoff
) -> Optional[int]:
    """How long the trip should take, for the customer's tracking screen.

    Quoted on a car: until a driver claims the order there is no vehicle to
    quote on, and a customer-facing estimate that assumed a bicycle would be
    wrong in the other direction. None when either end of the trip is unknown.
    """
    origin = restaurant_point(restaurant)
    if origin is None or dropoff is None:
        return None

    distance = straight_line_km(origin[0], origin[1], dropoff[0], dropoff[1])
    return vehicle_eta_minutes(VehicleType.CAR.value, distance)


async def _reassignments_by_order(
    db: AsyncSession, order_ids: List[str]
) -> Dict[str, List[OrderReassignmentResponse]]:
    """Returns to the pool per order, oldest first.

    Read from the same `delivery.reassigned` audit rows the admin trail uses
    rather than a second copy on the order: the audit row is the transition,
    and a customer-visible projection of it cannot disagree with the
    administrator's. Only the timestamp is projected - the actor and the
    suspension reason stay in the admin trail.

    Batched by order ids so the customer's order list costs one query rather
    than one per row.
    """
    if not order_ids:
        return {}

    result = await db.execute(
        select(AuditEventRecord)
        .where(AuditEventRecord.action == DELIVERY_REASSIGNED)
        .where(AuditEventRecord.subject_type == "order")
        .where(AuditEventRecord.subject_id.in_(order_ids))
        .order_by(AuditEventRecord.created_at.asc())
    )

    grouped: Dict[str, List[OrderReassignmentResponse]] = {}
    for row in result.scalars().all():
        grouped.setdefault(row.subject_id, []).append(
            OrderReassignmentResponse(returned_at=as_utc(row.created_at))
        )
    return grouped


async def _customer_view(
    db: AsyncSession,
    order: OrderRecord,
    reassignments: Optional[List[OrderReassignmentResponse]] = None,
) -> OrderResponse:
    """One order as its customer sees it, trip and choices included."""
    restaurant = await restaurant_or_none(db, order.restaurant_id)
    details = (await delivery_details_by_order(db, [order.order_id])).get(order.order_id)
    dropoff = (await dropoffs_by_order(db, [order.order_id])).get(order.order_id)

    payment = (await payments_by_order(db, [order.order_id])).get(order.order_id)
    view = OrderResponse.for_customer(
        order,
        restaurant_name=restaurant.name if restaurant else "",
        pickup=pickup_summary(restaurant),
        estimated_delivery_time=_estimated_minutes(restaurant, dropoff),
    )
    view.reassignments = reassignments or []
    return view.with_delivery(
        details.instruction_type if details else None,
        details.delivery_speed if details else None,
    ).with_payment(payment.payment_status if payment else None)


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreateRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Place an order.

    What is ordered is the customer's to choose and what it costs is not: every
    line is priced from the restaurant's stored menu, and an item the menu does
    not list - or has switched off - is refused rather than priced from the
    request. The menu also supplies each line's drink flags, which is how a
    courier's copy of the order knows there are two unsealed drinks in the bag.

    Scheduling is refused with a reason instead of accepted and ignored: an
    order the kitchen would have to hold is a feature, and quietly cooking it
    now would tell the customer something untrue about their dinner.
    """
    if body.scheduled_for:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Scheduled orders are not supported yet - choose ASAP and "
                "place the order when you want it."
            ),
        )

    restaurant = await restaurant_or_none(db, body.restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    if not restaurant.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This restaurant is not taking orders",
        )

    try:
        priced = quote(
            restaurant.menu or [],
            [(item.item_id, item.quantity) for item in body.items],
            speed=body.delivery_speed,
            tip_amount=body.tip_amount,
        )
    except UnknownMenuItem as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{exc}' is not on this restaurant's menu",
        ) from exc
    except ItemUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{exc} is no longer available",
        ) from exc

    order = OrderRecord(
        restaurant_id=restaurant.restaurant_id,
        customer_id=current_user.user_id,
        customer_name=current_user.name or "",
        items=priced.lines,
        subtotal=priced.subtotal,
        delivery_fee=priced.delivery_fee,
        tip_amount=priced.tip_amount,
        total_amount=priced.total_amount,
        status=OrderStatus.PENDING.value,
        is_donation=body.is_donation,
        delivery_address=body.delivery_address,
        delivery_instructions=body.delivery_instructions,
    )
    db.add(order)
    # Flushed before its satellite rows are written: the order's id is generated
    # on insert, and both rows below are keyed by it.
    await db.flush()

    # The dropoff coordinates are optional and encrypted on the way in: an order
    # without them is offered without a distance later rather than hidden.
    if body.delivery_lat is not None and body.delivery_lng is not None:
        db.add(
            OrderLocationRecord(
                order_id=order.order_id,
                lat_encrypted=encrypt_data(str(body.delivery_lat)),
                lng_encrypted=encrypt_data(str(body.delivery_lng)),
            )
        )

    db.add(
        OrderDeliveryDetailsRecord(
            order_id=order.order_id,
            instruction_type=body.delivery_instruction_type,
            delivery_speed=body.delivery_speed,
        )
    )

    await db.flush()
    return await _customer_view(db, order)


@router.get("", response_model=List[OrderResponse])
async def list_my_orders(
    order_status: Optional[OrderStatus] = Query(
        None,
        alias="status",
        description="Only orders in this status, which is what the tabs send.",
    ),
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own orders, newest first.

    Always filtered by the caller's id, so this cannot be turned into a list of
    somebody else's orders by a query parameter.
    """
    query = select(OrderRecord).where(OrderRecord.customer_id == current_user.user_id)
    if order_status is not None:
        query = query.where(OrderRecord.status == order_status.value)

    result = await db.execute(
        query.order_by(OrderRecord.created_at.desc()).limit(CUSTOMER_ORDER_LIMIT)
    )
    records = list(result.scalars().all())

    kitchens = await restaurants_by_id(db, {r.restaurant_id for r in records})
    details = await delivery_details_by_order(db, [r.order_id for r in records])
    reassignments = await _reassignments_by_order(
        db, [r.order_id for r in records]
    )
    payments = await payments_by_order(db, [r.order_id for r in records])

    orders: List[OrderResponse] = []
    for record in records:
        restaurant = kitchens.get(record.restaurant_id)
        dropoff = (await dropoffs_by_order(db, [record.order_id])).get(record.order_id)
        view = OrderResponse.for_customer(
            record,
            restaurant_name=restaurant.name if restaurant else "",
            pickup=pickup_summary(restaurant),
            estimated_delivery_time=_estimated_minutes(restaurant, dropoff),
        )
        view.reassignments = reassignments.get(record.order_id, [])
        chosen = details.get(record.order_id)
        payment = payments.get(record.order_id)
        orders.append(
            view.with_delivery(
                chosen.instruction_type if chosen else None,
                chosen.delivery_speed if chosen else None,
            ).with_payment(payment.payment_status if payment else None)
        )

    return orders


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One order, if the caller has a claim on it.

    Three people may read an order: the customer who placed it, the owner of the
    restaurant making it, and the driver carrying it. Being *a* restaurant or *a*
    driver is not enough - the merged app used to hand any restaurant account
    every order on the platform, which is a leak, not a convenience.
    """
    order = await order_or_none(db, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    restaurant = await restaurant_or_none(db, order.restaurant_id)
    driver = await db.execute(
        select(DriverRecord).where(DriverRecord.user_id == current_user.user_id)
    )
    my_driver = driver.scalar_one_or_none()

    is_customer = order.customer_id == current_user.user_id
    is_owner = restaurant is not None and restaurant.user_id == current_user.user_id
    is_courier = my_driver is not None and order.driver_id == my_driver.driver_id

    if not (is_customer or is_owner or is_courier):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
        )

    reassignments = await _reassignments_by_order(db, [order.order_id])
    return await _customer_view(
        db, order, reassignments.get(order.order_id, [])
    )


@router.post("/{order_id}/add-tip", response_model=AddTipResponse)
async def add_tip(
    order_id: str,
    body: AddTipRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tip the driver after the fact.

    Only increases, and only on the customer's own order: the tip is folded into
    the stored tip rather than kept in a second field, so the courier's pay is
    one number that cannot disagree with itself. A cancelled order is the one
    refusal, because there is no delivery left to tip for.
    """
    order = await order_or_none(db, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    if order.customer_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the customer can tip"
        )
    if order.status == OrderStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cancelled order cannot be tipped",
        )

    # The bill cannot change under a Checkout page: Stripe charges the amount it
    # was opened with, and a tip added afterwards would either go uncollected or
    # make the paid amount disagree with the total. Tipping before paying works;
    # after payment there is no second charge to put it on yet.
    payment = (await payments_by_order(db, [order.order_id])).get(order.order_id)
    if payment is not None and (
        payment.payment_status == PAYMENT_PAID or payment.provider_status == "open"
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This order already has a payment in progress - add the tip "
                "before starting checkout."
            ),
        )

    order.tip_amount = round((order.tip_amount or 0.0) + body.amount, 2)
    order.total_amount = round(
        (order.subtotal or 0.0)
        + (order.delivery_fee or 0.0)
        + (order.tax_amount or 0.0)
        + order.tip_amount,
        2,
    )
    await db.flush()

    return AddTipResponse(
        message="Tip added successfully",
        additional_tip=body.amount,
        total_tip=order.tip_amount,
    )


@router.post(
    "/{order_id}/report-issue",
    response_model=ReportIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_issue(
    order_id: str,
    body: ReportIssueRequest,
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a problem with an order, for whoever reads support.

    Stored rather than notified: there is no support queue yet, so the report is
    written down and nothing promises a reply. Only the customer may file one -
    a restaurant or courier reporting their own problem is a different feature.
    """
    order = await order_or_none(db, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    if order.customer_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not your order"
        )

    issue = OrderIssueRecord(
        order_id=order.order_id,
        customer_id=current_user.user_id,
        description=body.description,
    )
    db.add(issue)
    await db.flush()

    return ReportIssueResponse(
        message="Issue reported successfully", issue_id=issue.issue_id
    )


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    order_status: OrderStatus = Query(
        ...,
        alias="status",
        description="The status to move the order to.",
    ),
    current_user: UserRecord = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Move one order along its lifecycle, as the restaurant or as its driver.

    Only two people may move an order: the owner of the restaurant it belongs to
    (its half) and the driver it is assigned to (the rest). Both the edge and
    the right to take it are checked, so a kitchen cannot mark food delivered
    and a driver cannot accept somebody else's job.
    """
    result = await db.execute(
        select(OrderRecord).where(OrderRecord.order_id == order_id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    # Who the caller is, resolved from stored rows rather than from anything
    # they sent. A missing restaurant row means the caller's authority cannot be
    # established, which is a refusal too.
    owner = await db.execute(
        select(RestaurantRecord).where(
            RestaurantRecord.restaurant_id == order.restaurant_id
        )
    )
    restaurant = owner.scalar_one_or_none()

    driver = await db.execute(
        select(DriverRecord).where(DriverRecord.user_id == current_user.user_id)
    )
    my_driver = driver.scalar_one_or_none()

    if restaurant is not None and restaurant.user_id == current_user.user_id:
        actor = RESTAURANT
    elif my_driver is not None and order.driver_id == my_driver.driver_id:
        actor = DRIVER
    elif order.customer_id == current_user.user_id:
        # The customer's own edge is narrow - changing their mind before the
        # kitchen starts - but it is theirs, and the tracking screen offers it.
        actor = CUSTOMER
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this order",
        )

    try:
        current_status = OrderFlowManager.coerce(order.status)
        OrderFlowManager.validate_transition(current_status, order_status)
    except OrderTransitionError as exc:
        raise HTTPException(
            status_code=_TRANSITION_REFUSED, detail=str(exc)
        ) from exc

    # The edge exists and the caller has a claim on the order - but the edge may
    # still belong to the other party.
    try:
        OrderFlowManager.validate_permission(actor, current_status, order_status)
    except OrderTransitionNotPermitted as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    OrderFlowManager.apply_transition(order, order_status)
    await db.flush()

    return OrderResponse.from_record(order)
