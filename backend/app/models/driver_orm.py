"""
SQLAlchemy ORM model for drivers.

Maps to the 'drivers' table. One row per user who signs up to deliver; the
order's `driver_id` points at `driver_id` here, never at a user id, so the
relationship that grants delivery rights is a stored fact rather than something
a request can claim.

Kept deliberately small: identity and the vehicle the driver moves food with.
Stats (deliveries completed, rating), earnings, route preferences and location
belong to slices that do not exist yet - a column nothing can write would
misrepresent what is implemented.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.ids import generate_id
from app.models.general import VehicleType

# The enum owns the vocabulary; the column stores its value. Written this way
# round so a new option (walk) reaches the default without a second literal.
DEFAULT_VEHICLE_TYPE = VehicleType.CAR.value


class DriverRecord(Base):
    __tablename__ = "drivers"

    driver_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("driver")
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True, unique=True, nullable=False)

    # Stored as the VehicleType value, validated on write in
    # app/schemas/driver.py. A string column rather than a SQL enum keeps the
    # vocabulary in one place (app/models/general.py).
    vehicle_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_VEHICLE_TYPE
    )

    # A licence number identifies a person, so it is stored encrypted (AES-GCM)
    # as app/models/driver.py does, and never returned - not even to its owner.
    license_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")

    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def has_license(self) -> bool:
        """Whether a licence number is on file, without revealing it."""
        return bool(self.license_number_encrypted)


class OrderDeclineRecord(Base):
    """A job this driver has turned down.

    Kept rather than handled in the browser because the board is polled every
    30 seconds: without a stored "no" a rejected job would be offered again
    before the driver had put the phone down.

    Keyed by the pair, so declining the same job twice is one fact rather than
    two. A new row per order rather than a list on the driver, which keeps the
    board's exclusion a join instead of a JSON scan. The reason is not recorded:
    nothing reads it yet, and the reason a driver passed is visible in what the
    job asked for.
    """

    __tablename__ = "order_declines"

    driver_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    declined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
