"""
SQLAlchemy ORM model for orders.

Maps to the 'orders' table. Ordered items are stored as a JSON list (matching
the shape the React cart already sends) rather than a child table, the same
choice RestaurantRecord makes for its menu.

Scope note: this table carries what the restaurant queue needs to work an
order — who it is for, what is in it, what it costs and where it stands. The
status vocabulary is app.models.general.OrderStatus; the transitions the
restaurant itself may make live in app/order_flow.py; request validation and
response shaping live in app/schemas/order.py.

The driver columns are filled in by the driver slice: accepting an order stamps
the driver on it, and each later step stamps its own time. Payment state is not
here: it lives in the `order_payments` satellite (app/models/payment_orm.py),
for the same no-migrations reason as the location and delivery-detail rows, and
because a payment is its own record with its own provider ids and timestamps.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.ids import generate_id
from app.models.general import DeliveryInstructionType, OrderStatus


class OrderRecord(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("order")
    )
    restaurant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # List[dict] of ordered items (item_id, name, quantity, base_price, ...).
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    delivery_fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tip_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    status: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, default=OrderStatus.PENDING.value
    )
    is_donation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Set by the driver who claimed the order (the DriverRecord's id, not the
    # user's), so ownership is resolved from this row rather than the caller.
    driver_id: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    driver_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # Where the food goes. A kitchen needs this to hand the order over, so it is
    # stored in plaintext like RestaurantRecord.address. Exact coordinates are
    # not kept here at all, which is stronger than encrypting them.
    delivery_address: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    delivery_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    delivery_zip: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    delivery_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Stamped by each transition (see order_flow.TIMESTAMP_FIELDS).
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ready_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    picked_up_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OrderLocationRecord(Base):
    """Where an order's dropoff is, encrypted, kept apart from the order row.

    A table rather than two columns on `orders` for a mundane reason: there is no
    migration tool here, so `create_all` adds new tables to a database that
    already exists and silently does nothing about new columns. A column added to
    `orders` would work on a fresh database and break every order query on a
    running one.

    Encrypted like the restaurant's coordinates (AES-GCM, a value per field).
    The point of keeping it at all is that an offer can quote a distance and a
    direction without either side of the trip ever being able to read the
    customer's address off the wire.

    Absent for orders nobody has located yet - an unlocated order is offered
    without a distance rather than hidden, because missing data is not the same
    as an unrealistic trip.
    """

    __tablename__ = "order_locations"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lat_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lng_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class OrderDeliveryDetailsRecord(Base):
    """The choices the customer made at checkout.

    A satellite row for the same reason as the coordinates: `create_all` adds
    tables to a database that already exists but never columns to the tables in
    it. Both fields are read back - the courier's card shows the instruction and
    the speed the customer paid for - so neither is here for the record alone.

    Absent for an order that predates checkout or was written by a script; a
    missing row reads as the defaults (hand it over, standard speed).
    """

    __tablename__ = "order_delivery_details"

    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    instruction_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DeliveryInstructionType.HAND_TO_CUSTOMER.value
    )
    delivery_speed: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class OrderIssueRecord(Base):
    """A problem the customer reported with one order.

    Row per report rather than a flag on the order, because a customer may
    report twice and support needs to see both. Nothing resolves them yet -
    there is no support queue - so `status` is written once as pending and read
    by whoever builds that screen.
    """

    __tablename__ = "order_issues"

    issue_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("issue")
    )
    order_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
