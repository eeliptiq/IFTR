"""
Restaurant-side order state machine.

Mirrors the shape of app/delivery_flow.py: one table of allowed edges, a
validate step that raises a domain error, and a single place that stamps the
audit timestamps. Keeping it out of the API layer means the rules can be read
and tested without an HTTP client, and the API maps the domain error to a
status code.

Three actors share the lifecycle: the restaurant works an order from pending to
ready, a driver takes it from ready to delivered, and the customer may back out
while it is still pending. The graph below is what is reachable at all;
ROLE_TRANSITIONS is who may take which edge. Keeping them apart is what lets one
endpoint serve all three screens while refusing an owner who tries to mark food
delivered, a driver who tries to accept an order for someone else, or a customer
who tries to cancel an order already being cooked.

The one edge in no role's set is ready -> assigned: claiming an order also has
to stamp the driver onto it, so it is taken by the accept endpoint rather than
by a bare status change.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from app.models.general import OrderStatus

# Who is acting on the order, as a relationship rather than an account role.
RESTAURANT = "restaurant"
DRIVER = "driver"
CUSTOMER = "customer"


class OrderTransitionError(Exception):
    """Raised when an order state transition is invalid."""


class OrderTransitionNotPermitted(OrderTransitionError):
    """Raised when the edge exists but this actor may not take it."""


class OrderFlowManager:
    """Allowed order transitions and the side effects of taking them."""

    # Every edge an order may take, whoever takes it.
    TRANSITION_RULES: Dict[OrderStatus, List[OrderStatus]] = {
        # Charge taken; the restaurant accepts or declines.
        OrderStatus.PENDING: [
            OrderStatus.CONFIRMED,  # Restaurant accepts
            OrderStatus.CANCELLED,  # Restaurant declines
        ],
        # Accepted; a kitchen problem can still stop it before food is made.
        OrderStatus.CONFIRMED: [
            OrderStatus.PREPARING,
            OrderStatus.CANCELLED,
        ],
        # Cooking: no way back. Once food is being made, an order is not the
        # restaurant's to cancel any more - that goes through support.
        OrderStatus.PREPARING: [
            OrderStatus.READY,
        ],
        # Food is ready: a driver claims it (accept endpoint only).
        OrderStatus.READY: [
            OrderStatus.ASSIGNED,
        ],
        # Driver has the job and is on the way to the restaurant.
        OrderStatus.ASSIGNED: [
            OrderStatus.PICKED_UP,
        ],
        # Food is in hand.
        OrderStatus.PICKED_UP: [
            OrderStatus.IN_TRANSIT,
        ],
        # On the way to the customer.
        OrderStatus.IN_TRANSIT: [
            OrderStatus.DELIVERED,
        ],
        # Terminal states.
        OrderStatus.DELIVERED: [],
        OrderStatus.CANCELLED: [],
    }

    # Which of those edges each actor is allowed to take.
    ROLE_TRANSITIONS: Dict[str, Dict[OrderStatus, Set[OrderStatus]]] = {
        RESTAURANT: {
            OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
            OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
            OrderStatus.PREPARING: {OrderStatus.READY},
        },
        DRIVER: {
            OrderStatus.ASSIGNED: {OrderStatus.PICKED_UP},
            OrderStatus.PICKED_UP: {OrderStatus.IN_TRANSIT},
            OrderStatus.IN_TRANSIT: {OrderStatus.DELIVERED},
        },
        CUSTOMER: {
            # Changing their mind before the kitchen starts. Once food is being
            # made the decision is the restaurant's, and after pickup it belongs
            # to support: an order in transit cannot be un-cooked.
            OrderStatus.PENDING: {OrderStatus.CANCELLED},
        },
    }

    # Which timestamp records that a status was reached.
    TIMESTAMP_FIELDS: Dict[OrderStatus, str] = {
        OrderStatus.CONFIRMED: "confirmed_at",
        OrderStatus.READY: "ready_at",
        OrderStatus.ASSIGNED: "assigned_at",
        OrderStatus.PICKED_UP: "picked_up_at",
        OrderStatus.DELIVERED: "delivered_at",
        OrderStatus.CANCELLED: "cancelled_at",
    }

    @staticmethod
    def allowed_transitions(current: OrderStatus) -> List[OrderStatus]:
        """The statuses reachable from `current`."""
        return list(OrderFlowManager.TRANSITION_RULES.get(current, []))

    @staticmethod
    def coerce(status: Any) -> OrderStatus:
        """
        Read a stored status back into the enum.

        A row written by an older or hand-edited database can hold a value the
        enum no longer has; that is a refused transition rather than a crash.
        """
        try:
            return OrderStatus(status)
        except ValueError:
            raise OrderTransitionError(f"Unknown order status stored: {status!r}")

    @staticmethod
    def validate_transition(current: OrderStatus, new_status: OrderStatus) -> bool:
        """Raise OrderTransitionError unless current -> new_status is allowed."""
        allowed = OrderFlowManager.allowed_transitions(current)

        if new_status not in allowed:
            reachable = ", ".join(status.value for status in allowed) or "nothing"
            raise OrderTransitionError(
                f"Cannot move an order from {current.value} to {new_status.value}. "
                f"From {current.value} an order may only become: {reachable}"
            )

        return True

    @staticmethod
    def allows(actor: str, current: OrderStatus, new_status: OrderStatus) -> bool:
        """Whether this actor may take this edge, which must also be reachable."""
        return new_status in OrderFlowManager.ROLE_TRANSITIONS.get(actor, {}).get(
            current, set()
        )

    @staticmethod
    def validate_permission(actor: str, current: OrderStatus, new_status: OrderStatus) -> bool:
        """Raise OrderTransitionNotPermitted unless this actor owns this edge."""
        if not OrderFlowManager.allows(actor, current, new_status):
            raise OrderTransitionNotPermitted(
                f"A {actor} may not move an order from {current.value} to "
                f"{new_status.value}"
            )

        return True

    @staticmethod
    def apply_transition(
        order: Any, new_status: OrderStatus, now: Optional[datetime] = None
    ) -> Any:
        """
        Write a validated transition onto an order record.

        Duck-typed on purpose (`order` is an ORM row): the rules above stay
        usable without a database. Assigns rather than mutates so SQLAlchemy
        always sees the change.
        """
        now = now or datetime.now(timezone.utc)

        order.status = new_status.value
        order.updated_at = now

        field = OrderFlowManager.TIMESTAMP_FIELDS.get(new_status)
        if field:
            setattr(order, field, now)

        return order
