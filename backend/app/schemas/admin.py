"""Request/response models for the admin controls.

Changing a role is one field on purpose: the value before and after goes in the
audit row, and a role change must not be bundled with a profile edit that could
change the record it is attributed to.

`AdminOrganizationResponse` is the admin's view of an organization: unlike the
public one it includes contact details and the owner's email, because verifying
a food bank without being able to call it is not a decision anybody can make.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.general import UserRole
from app.schemas._time import as_utc
from app.schemas.auth import UserResponse
from app.schemas.impact import ImpactStatsResponse


class RoleChangeRequest(BaseModel):
    # Admin and support are assignable here, and only here: this is the
    # controlled path once at least one administrator exists.
    role: UserRole


class AccountStatusRequest(BaseModel):
    # One field, like a role change: suspension is a fact with a before and
    # after, not a profile edit bundled with other changes.
    is_active: bool


class AccountStatusResponse(UserResponse):
    """The account and what suspending it moved.

    `released_deliveries` counts the accepted jobs returned to the pool in the
    same request, so the console can say what happened to the driver's work
    instead of leaving it to an audit read. Zero on reactivation and on a
    suspension with nothing in hand.
    """

    released_deliveries: int = 0

    @classmethod
    def from_record(
        cls, user, released_deliveries: int = 0
    ) -> "AccountStatusResponse":
        return cls(
            **UserResponse.from_record(user).model_dump(),
            released_deliveries=released_deliveries,
        )


class AdminStatsResponse(ImpactStatsResponse):
    """The same platform totals the impact page reads, plus collected revenue.

    `total_revenue` is the sum of orders whose payment row says paid - money the
    provider confirmed, not money the app hopes for. `delivered_value` remains
    the value of what was delivered, paid or not; the two answer different
    questions and must not be substituted for each other.
    """

    total_revenue: float = 0.0


class AdminOrganizationResponse(BaseModel):
    """An organization as the admin console sees it.

    Includes what the public view deliberately withholds: how to reach the
    people behind the application. Coordinates stay encrypted and unreturned -
    the delivery address is what a volunteer needs, not a map pin.
    """

    model_config = ConfigDict(extra="allow")

    org_id: str
    user_id: str
    name: str
    description: str = ""
    org_type: str = ""
    address: str = ""
    city: str = ""
    delivery_address: Optional[str] = None
    contact_email: str = ""
    contact_phone: str = ""
    is_verified: bool = False
    total_received: int = 0
    owner_email: str = ""
    owner_name: str = ""
    created_at: Optional[datetime] = None

    @classmethod
    def from_records(cls, organization, owner=None) -> "AdminOrganizationResponse":
        return cls(
            org_id=organization.org_id,
            user_id=organization.user_id,
            name=organization.name,
            description=organization.description or "",
            org_type=organization.org_type or "",
            address=organization.address or "",
            city=organization.city or "",
            delivery_address=organization.delivery_address,
            contact_email=organization.contact_email or "",
            contact_phone=organization.contact_phone or "",
            is_verified=organization.is_verified,
            total_received=organization.total_received or 0,
            owner_email=owner.email if owner is not None else "",
            owner_name=owner.name if owner is not None else "",
            created_at=as_utc(organization.created_at),
        )
