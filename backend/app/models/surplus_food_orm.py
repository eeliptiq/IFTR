"""
SQLAlchemy ORM models for surplus food.

Two tables, because a listing and a rescue are different things:

  * `surplus_food` - what a restaurant has going spare, with how many portions
    are still available and when the food stops being safe to hand on.
  * `surplus_deliveries` - one organization's reservation of some of those
    portions, and the volunteer run that should move them. This row *is* the
    reservation: the quantity is what that organization booked, so the
    organization's "received" list stays truthful even when a listing is split
    between two organizations.

Coordinates are encrypted (AES-256-GCM) as everywhere else. The listing keeps a
snapshot of the pickup point because a surplus listing is about food that exists
right now; the delivery copies the pickup from the restaurant at reservation
time, so the volunteer is sent to where the restaurant actually is.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.ids import generate_id
from app.models.surplus_food import SurplusDeliveryStatus


class SurplusFoodRecord(Base):
    __tablename__ = "surplus_food"

    surplus_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("surplus")
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    restaurant_id: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    restaurant_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Portions still available, not portions originally listed. The screens
    # read this as "how many can I reserve", so it has to fall as reservations
    # are made.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    discounted_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    expiry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )

    pickup_lat_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pickup_lng_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pickup_address: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    pickup_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    pickup_zip_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set when the last portion of a listing is reserved, which is what the
    # restaurant's own page reads to show "Reserved" instead of a countdown.
    reserved_by_org_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SurplusDeliveryRecord(Base):
    """One reservation, and the volunteer run that carries it out.

    The status is the delivery's, not the listing's: two organizations can
    reserve different portions of one listing, and one of them may already have
    been delivered while the other is still waiting for a driver.
    """

    __tablename__ = "surplus_deliveries"

    delivery_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("sdel")
    )
    surplus_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    restaurant_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    restaurant_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    org_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    driver_id: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    driver_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    # A string column rather than a SQL enum: the vocabulary lives in
    # app/models/surplus_food.py, as it does for orders.
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SurplusDeliveryStatus.PENDING.value
    )

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    pickup_lat_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pickup_lng_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pickup_address: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    pickup_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    pickup_zip_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    dropoff_lat_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dropoff_lng_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dropoff_address: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    dropoff_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    dropoff_zip_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    # Straight-line trip length, and the quote for a car. The board re-quotes
    # the time on the volunteer's own vehicle.
    distance_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    estimated_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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
