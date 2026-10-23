"""
Request/response schemas for authentication endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, SecretStr, field_validator

from app.models.general import UserRole

# The roles an account may ask for when it signs itself up. Each one is an
# onboarding intent rather than an authority: what a restaurant owner or a
# driver may actually do is decided by the records they own (a restaurant row, a
# driver row), never by this string. `admin` and `support` are deliberately
# absent - an administrator is created from the server's shell with
# `./run.sh create-admin`, so no HTTP request can grant that role.
SELF_SERVICE_ROLES = frozenset(
    {
        UserRole.CUSTOMER,
        UserRole.DRIVER,
        UserRole.RESTAURANT_ADMIN,
        UserRole.ORGANIZATION_ADMIN,
    }
)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8)
    name: str = Field(min_length=1, max_length=128)
    role: UserRole = UserRole.CUSTOMER
    phone: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _must_be_self_serviceable(cls, value: UserRole) -> UserRole:
        if value not in SELF_SERVICE_ROLES:
            raise ValueError(
                f"role '{value.value}' cannot be granted at registration; "
                "an administrator is created with ./run.sh create-admin"
            )
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Safe user response — no sensitive fields."""
    user_id: str
    email: str
    name: str
    role: str
    phone: Optional[str] = None
    picture: Optional[str] = None
    calendar_preference: Optional[str] = None
    credits: float = 0.0
    is_approved: bool = False
    # Readable by the account itself and by an administrator; never writable
    # through the profile endpoint.
    is_active: bool = True
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_record(cls, user) -> "UserResponse":
        """The safe view of a stored account - no password material, ever."""
        return cls(
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            role=user.role,
            phone=user.phone,
            picture=user.picture,
            calendar_preference=user.calendar_preference,
            credits=user.credits,
            is_approved=user.is_approved,
            is_active=user.is_active,
            created_at=user.created_at,
        )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    phone: Optional[str] = None
    picture: Optional[str] = None
    calendar_preference: Optional[str] = None
