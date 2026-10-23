"""
SQLAlchemy ORM model for UserRecord.

Maps to the 'users' table. Pydantic models in app/models/user.py
handle validation and serialization; this handles persistence.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.core.ids import generate_id


class UserRecord(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("user")
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="customer")
    phone: Mapped[str] = mapped_column(String(32), nullable=True)
    picture: Mapped[str] = mapped_column(Text, nullable=True)
    calendar_preference: Mapped[str] = mapped_column(String(32), nullable=True, default="gregorian")
    credits: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        """Serialize to dict for Pydantic model construction."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "phone": self.phone,
            "picture": self.picture,
            "calendar_preference": self.calendar_preference,
            "credits": self.credits,
            "is_approved": self.is_approved,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
