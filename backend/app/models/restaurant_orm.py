"""
SQLAlchemy ORM model for RestaurantRecord.

Maps to the 'restaurants' table. The menu is stored as a JSON list of menu-item
dicts (matching the shape the React menu manager sends/reads) rather than a
separate table, which keeps the first slice small. Coordinates are stored
encrypted (AES-256-GCM) as text, mirroring the model-layer convention in
app/models/restaurant.py.

Pydantic models in app/schemas/restaurant.py handle request validation and
response shaping; this handles persistence.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.ids import generate_id


class RestaurantRecord(Base):
    __tablename__ = "restaurants"

    restaurant_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("rest")
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cuisine_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Encrypted coordinates (AES-GCM). Only city / zip_code are stored plaintext
    # so we can show a rough area without revealing the exact location.
    lat_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lng_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    address: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    zip_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    manual_is_open: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    operating_hours: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    rating: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_reviews: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # List[dict] of menu items.
    menu: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    delivery_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    show_in_leaderboard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_meals_donated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    surplus_deliveries_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
