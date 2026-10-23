"""
SQLAlchemy ORM model for organizations.

Maps to the 'organizations' table. One row per food bank, shelter or community
kitchen that signs up to receive surplus food; the account that registered it is
`user_id`, which also becomes the account's role (`organization_admin`).

Coordinates are stored encrypted (AES-256-GCM), matching the rest of the app.
The public view never returns them: a driver gets the delivery address only
after volunteering for a run, the same rule orders use for their dropoff.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.ids import generate_id


class OrganizationRecord(Base):
    __tablename__ = "organizations"

    org_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("org")
    )
    user_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # food_bank, shelter, community_kitchen, church, nonprofit.
    org_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Encrypted coordinates, plus the plaintext parts a courier can act on.
    lat_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    lng_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    address: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    delivery_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    # Verification is done by an admin. Nothing in the API can set this yet, so
    # a freshly registered organization can browse surplus but not reserve it.
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
