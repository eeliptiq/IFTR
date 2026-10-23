"""
Response models for orders.

Shaped around what the merged React screens actually read. Note the field is
called `status`, not `order_status` as in app/models/order.py: the ported
restaurant screen renders `order.status` (see
frontend/src/pages/RestaurantOrders.js), so the wire name follows the client.
The richer internal order model predates this and is not yet wired to a route.

`extra="allow"` on these models follows the convention in
app/schemas/restaurant.py: stored JSON may carry fields this layer does not know
about, and round-tripping them is better than silently dropping them.

Three views of one row, because three different people look at it:

  * `from_record` - the kitchen's. It needs the customer's name, address and
    instructions to pack and hand over the order.
  * `for_job_offer` - a job on the board. A driver deciding whether to take work
    gets the shape of the work: what is in the bag and what it pays. Not who the
    customer is, where they live, or the code to their front door.
  * `for_active_job` - a job in hand. Now the driver must actually go, so both
    ends of the trip are included. Still not the customer's name: a courier
    delivers to an address, not to a person's identity.

A customer's view also carries `reassignments`: the times their delivery came
back to the courier pool, projected from the `delivery.reassigned` audit rows.
The audit row keeps the administrator and the suspension reason where they
belong; the customer gets the fact that the courier changed, and no more.

Locations are one shape everywhere (`LocationSummary`): an address, no
coordinates. Coordinates stay encrypted on the restaurant and are never stored
on an order at all.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.general import DeliveryInstructionType
from app.models.order_orm import OrderRecord


class LocationSummary(BaseModel):
    """Where to go, without coordinates."""

    model_config = ConfigDict(extra="allow")

    address: str = ""
    city: str = ""
    zip_code: str = ""


class OrderReassignmentResponse(BaseModel):
    """One return-to-pool, as the customer's tracker tells it.

    The audit row behind this names the administrator who moved the delivery and
    why. The customer gets the neutral fact and when it happened: who decided it
    and that the previous courier was suspended are not theirs to read, and
    exposing them would turn an operational decision into a status judgment
    about a person.
    """

    model_config = ConfigDict(extra="allow")

    returned_at: Optional[datetime] = None


class OrderItemResponse(BaseModel):
    """One line of an order, as the kitchen or the courier sees it."""

    model_config = ConfigDict(extra="allow")

    item_id: str = ""
    name: str = ""
    quantity: int = 1
    base_price: float = 0.0
    # The same stored number under the name the tracking screen reads. See
    # OrderResponse.item_view: one value, two labels, no second copy to drift.
    price: float = 0.0
    is_drink: bool = False
    # Only meaningful on a drink. Absent means unsealed - an open cup from the
    # fountain - because that is the case that needs planning around; a sealed
    # bottle can ride in a bag.
    is_sealed: bool = False
    is_surplus: bool = False
    special_instructions: str = ""


class OrderResponse(BaseModel):
    """An order, from one of the three points of view above."""

    model_config = ConfigDict(extra="allow")

    order_id: str
    restaurant_id: str
    # Named rather than looked up by the client: an offer has to say which
    # kitchen the food is waiting in, and the courier screen would otherwise
    # need one request per card to find out.
    restaurant_name: str = ""
    customer_id: str
    customer_name: str = ""

    status: str
    items: List[OrderItemResponse] = Field(default_factory=list)
    # Units rather than lines: a courier counts portions, and two lines of three
    # are six items to carry, not two.
    item_count: int = 0
    # Derived, not stored: a drink is a fact about the item, and the driver's
    # card asks whether this order contains one.
    has_drinks: bool = False
    # Units, not lines, for the same reason as item_count: two Cokes are two
    # cups to stand upright, and that is what the courier plans around.
    drink_count: int = 0
    # The subset of drink_count that cannot simply be bagged: the number the
    # courier screen asks about, because it decides whether the ride needs a
    # cup holder.
    unsealed_drink_count: int = 0

    # What the customer asked for at checkout. Empty on an order that predates
    # checkout or was written by a script, which the screens read as their own
    # defaults rather than as a choice.
    delivery_instruction_type: str = ""
    delivery_speed: str = ""
    # pending / paid / failed, read from the order's payment row (see
    # app/models/payment_orm.py). An order that predates payments, or has never
    # been through checkout, reads as pending - which is true: nothing charged.
    payment_status: str = "pending"
    # Minutes, quoted for the customer's tracking screen. None when the order's
    # location is unknown.
    estimated_delivery_time: Optional[int] = None

    # The driver, once one has claimed the order.
    driver_id: Optional[str] = None
    driver_name: str = ""
    # Deliveries that came back to the pool, oldest first. Empty on an order
    # that has always belonged to whoever holds it now.
    reassignments: List[OrderReassignmentResponse] = Field(default_factory=list)

    subtotal: float = 0.0
    tax_amount: float = 0.0
    delivery_fee: float = 0.0
    tip_amount: float = 0.0
    total_amount: float = 0.0
    # What the courier is paid: the delivery fee plus the tip. Derived, so the
    # two parts can never disagree with the sum on the screen.
    pay_amount: float = 0.0
    is_donation: bool = False

    delivery_address: str = ""
    delivery_city: str = ""
    delivery_zip: str = ""
    delivery_instructions: str = ""

    # Filled in only for the driver holding the job.
    pickup_location: Optional[LocationSummary] = None
    delivery_location: Optional[LocationSummary] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    @classmethod
    def item_count_of(cls, items: List[dict]) -> int:
        """Total units ordered, tolerating a hand-written quantity."""
        total = 0
        for item in items or []:
            try:
                total += int(item.get("quantity") or 1)
            except (AttributeError, TypeError, ValueError):
                total += 1
        return total

    @classmethod
    def has_drinks_of(cls, items: List[dict]) -> bool:
        """Whether any line is a drink, from the item's own is_drink flag."""
        return any(
            isinstance(item, dict) and bool(item.get("is_drink")) for item in items or []
        )

    @classmethod
    def drink_count_of(cls, items: List[dict]) -> int:
        """Drink units ordered, tolerating a hand-written quantity."""
        total = 0
        for item in items or []:
            if not isinstance(item, dict) or not item.get("is_drink"):
                continue
            try:
                total += int(item.get("quantity") or 1)
            except (TypeError, ValueError):
                total += 1
        return total

    @classmethod
    def unsealed_drink_count_of(cls, items: List[dict]) -> int:
        """Drink units that are not sealed: the ones a cup holder is for.

        A drink with no is_sealed flag counts as unsealed. Assuming the harder
        case is what the kitchen not filing packaging should get you - the
        alternative is a fountain cup carried as if it were a can.
        """
        total = 0
        for item in items or []:
            if not isinstance(item, dict) or not item.get("is_drink"):
                continue
            if item.get("is_sealed"):
                continue
            try:
                total += int(item.get("quantity") or 1)
            except (TypeError, ValueError):
                total += 1
        return total

    @classmethod
    def item_view(cls, item: dict) -> OrderItemResponse:
        """One line as a client reads it.

        The stored dict carries the price once, as `base_price`. The kitchen
        screen was written against that name and the tracking screen against
        `price`, so the view answers to both instead of storing the number
        twice and letting the copies drift.
        """
        if not isinstance(item, dict):
            return OrderItemResponse()

        return OrderItemResponse(
            **{**item, "price": item.get("price", item.get("base_price", 0.0))}
        )

    @classmethod
    def from_record(
        cls, record: OrderRecord, restaurant_name: str = ""
    ) -> "OrderResponse":
        """The kitchen's view: everything needed to make and hand over the order."""
        return cls(
            order_id=record.order_id,
            restaurant_id=record.restaurant_id,
            restaurant_name=restaurant_name,
            customer_id=record.customer_id,
            customer_name=record.customer_name or "",
            status=record.status,
            items=[cls.item_view(item) for item in (record.items or [])],
            item_count=cls.item_count_of(record.items or []),
            has_drinks=cls.has_drinks_of(record.items or []),
            drink_count=cls.drink_count_of(record.items or []),
            unsealed_drink_count=cls.unsealed_drink_count_of(record.items or []),
            driver_id=record.driver_id,
            driver_name=record.driver_name or "",
            subtotal=record.subtotal or 0.0,
            tax_amount=record.tax_amount or 0.0,
            delivery_fee=record.delivery_fee or 0.0,
            tip_amount=record.tip_amount or 0.0,
            total_amount=record.total_amount or 0.0,
            pay_amount=(record.delivery_fee or 0.0) + (record.tip_amount or 0.0),
            is_donation=record.is_donation,
            delivery_address=record.delivery_address or "",
            delivery_city=record.delivery_city or "",
            delivery_zip=record.delivery_zip or "",
            delivery_instructions=record.delivery_instructions or "",
            created_at=record.created_at,
            updated_at=record.updated_at,
            confirmed_at=record.confirmed_at,
            ready_at=record.ready_at,
            assigned_at=record.assigned_at,
            picked_up_at=record.picked_up_at,
            delivered_at=record.delivered_at,
            cancelled_at=record.cancelled_at,
        )

    @classmethod
    def for_job_offer(
        cls, record: OrderRecord, restaurant_name: str = ""
    ) -> "OrderResponse":
        """
        A job on the board.

        Deliberately stripped of the customer: their name, where they live and
        any door code are none of the business of a driver who has not taken the
        work. The screen renders its own fallbacks ("See instructions") for the
        fields left empty.
        """
        view = cls.from_record(record, restaurant_name=restaurant_name)
        view.customer_id = ""
        view.customer_name = ""
        view.delivery_address = ""
        view.delivery_city = ""
        view.delivery_zip = ""
        view.delivery_instructions = ""
        return view

    @classmethod
    def for_active_job(
        cls,
        record: OrderRecord,
        pickup: Optional[LocationSummary] = None,
        restaurant_name: str = "",
    ) -> "OrderResponse":
        """A job in hand, with both ends of the trip so the driver can go."""
        view = cls.from_record(record, restaurant_name=restaurant_name)
        view.customer_id = ""
        view.customer_name = ""
        view.delivery_location = LocationSummary(
            address=record.delivery_address or "",
            city=record.delivery_city or "",
            zip_code=record.delivery_zip or "",
        )
        view.pickup_location = pickup
        return view

    @classmethod
    def for_customer(
        cls,
        record: OrderRecord,
        restaurant_name: str = "",
        pickup: Optional[LocationSummary] = None,
        estimated_delivery_time: Optional[int] = None,
    ) -> "OrderResponse":
        """The customer's own order: nothing is withheld from the person who
        placed it, and the trip is theirs to see.

        Includes the address they gave and the driver once one is on the
        order - the privacy rules that strip an *offer* are about not telling a
        driver who has not taken the work, not about the customer.
        """
        view = cls.from_record(record, restaurant_name=restaurant_name)
        view.estimated_delivery_time = estimated_delivery_time
        view.delivery_location = LocationSummary(
            address=record.delivery_address or "",
            city=record.delivery_city or "",
            zip_code=record.delivery_zip or "",
        )
        view.pickup_location = pickup
        return view

    def with_delivery(
        self,
        instruction_type: Optional[str],
        delivery_speed: Optional[str],
    ) -> "OrderResponse":
        """Attach the choices the customer made at checkout, when they exist."""
        self.delivery_instruction_type = instruction_type or ""
        self.delivery_speed = delivery_speed or ""
        return self

    def with_payment(self, payment_status: Optional[str]) -> "OrderResponse":
        """Attach the stored payment state, defaulting to "not paid".

        The state lives in a satellite table because there is no migration
        tool; the response is the one place its three values meet the screens.
        """
        self.payment_status = payment_status or "pending"
        return self


class CartItemRequest(BaseModel):
    """One cart line as the checkout screen sends it.

    Only the identity and the count are trusted. `price` is accepted so an
    older client does not fail validation, then ignored: the menu is the only
    authority on what something costs (see app/pricing.py).
    """

    item_id: str = Field(min_length=1)
    name: str = ""
    quantity: int = Field(default=1, ge=1, le=50)
    price: float = 0.0
    is_surplus: bool = False


class OrderCreateRequest(BaseModel):
    """Checkout: what the customer wants, and where it goes."""

    restaurant_id: str = Field(min_length=1)
    items: List[CartItemRequest] = Field(min_length=1)

    # Optional because a client need not know where the door is; the order is
    # then created without a location and offered without a distance.
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    delivery_address: str = Field(default="", max_length=256)

    delivery_instruction_type: str = DeliveryInstructionType.HAND_TO_CUSTOMER.value
    delivery_instructions: str = Field(default="", max_length=1000)
    delivery_speed: str = "standard"
    tip_amount: float = Field(default=0.0, ge=0.0)
    is_donation: bool = False
    # Accepted and refused with an explanation: scheduling an order is a feature
    # (the kitchen would have to hold it), and silently cooking a "7pm" order
    # now would be a lie told to the customer.
    scheduled_for: Optional[str] = None


class AddTipRequest(BaseModel):
    """A tip added after the fact. Only ever an increase."""

    amount: float = Field(gt=0.0)


class AddTipResponse(BaseModel):
    message: str
    additional_tip: float
    total_tip: float


class ReportIssueRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)


class ReportIssueResponse(BaseModel):
    message: str
    issue_id: str
