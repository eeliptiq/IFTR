"""
Request/response models for organizations.

Shaped around what the ported screens read (frontend/src/pages/
RegisterOrganization.js and OrganizationPages.js): they look up their own record
by `user_id` and read `is_verified`, `name` and `org_id`.

Coordinates go in and never come out. An organization's address is not secret,
but its exact coordinates are only useful to a driver already carrying a run to
it, and that driver gets the address from the delivery, not from this list.
Contact details are not returned either: the list is readable by every signed-in
account, and publishing a food bank's phone number to anyone who asks is how it
gets scraped.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._time import as_utc


class OrganizationCreateRequest(BaseModel):
    """What the registration form sends."""

    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2000)
    org_type: str = Field(default="", max_length=64)
    lat: float
    lng: float
    address: str = Field(default="", max_length=256)
    city: str = Field(default="", max_length=128)
    contact_email: str = Field(default="", max_length=255)
    contact_phone: str = Field(default="", max_length=32)
    delivery_address: Optional[str] = Field(default=None, max_length=500)


class OrganizationResponse(BaseModel):
    """The public view of an organization."""

    model_config = ConfigDict(extra="allow")

    org_id: str
    user_id: str
    name: str
    description: str = ""
    org_type: str = ""
    address: str = ""
    city: str = ""
    is_verified: bool = False
    total_received: int = 0
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> "OrganizationResponse":
        return cls(
            org_id=record.org_id,
            user_id=record.user_id,
            name=record.name,
            description=record.description or "",
            org_type=record.org_type or "",
            address=record.address or "",
            city=record.city or "",
            is_verified=record.is_verified,
            total_received=record.total_received or 0,
            created_at=as_utc(record.created_at),
        )
