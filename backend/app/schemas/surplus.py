"""
Request/response models for surplus food and volunteer runs.

Three audiences, three shapes, because each needs a different amount of truth:

  * The marketplace (`SurplusFoodResponse`) is what a restaurant lists and an
    organization browses: portions left, when the food expires, whether the
    whole listing has been claimed. No address.
  * The organization's own reservations (`ReservedSurplusResponse`) say how many
    portions *that organization* booked, even when a listing was split with
    somebody else, plus where the run stands.
  * A volunteer's board (`SurplusDeliveryResponse`) describes the trip - where
    from, where to, how far - but only includes the addresses once the driver is
    the one carrying it, the same rule orders follow.

Timestamps are tagged UTC on the way out; see app/schemas/_time.py.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.surplus_food import SurplusDeliveryStatus
from app.models.surplus_food_orm import SurplusDeliveryRecord, SurplusFoodRecord
from app.schemas._time import as_utc
from app.schemas.order import LocationSummary


class SurplusCreateRequest(BaseModel):
    """What the restaurant's "list surplus" dialog sends."""

    description: str = Field(min_length=1, max_length=500)
    quantity: int = Field(default=1, ge=1, le=500)
    original_price: float = Field(default=0.0, ge=0.0)
    discounted_price: float = Field(default=0.0, ge=0.0)
    expiry_hours: int = Field(default=4, ge=1, le=72)

    @model_validator(mode="after")
    def _asking_price_is_not_above_value(self) -> "SurplusCreateRequest":
        # A "discount" above the stated value is a typo, not a price. Refusing it
        # here keeps the browsing page from advertising $12 of food for $15.
        if self.discounted_price > self.original_price:
            raise ValueError("discounted_price cannot exceed original_price")
        return self


class SurplusReserveRequest(BaseModel):
    """How much of a listing an organization wants.

    Optional so a caller can reserve whatever is left, which is what the API did
    before the quantity dialog existed and still the sane default.
    """

    quantity: Optional[int] = Field(default=None, ge=1, le=500)


class SurplusFoodResponse(BaseModel):
    """A listing on the marketplace."""

    model_config = ConfigDict(extra="allow")

    surplus_id: str
    restaurant_id: Optional[str] = None
    restaurant_name: str = ""
    description: str
    # Portions still available.
    quantity: int
    original_price: float = 0.0
    discounted_price: float = 0.0
    expiry_time: Optional[datetime] = None
    is_available: bool = True
    reserved_by_org_id: Optional[str] = None
    pickup_city: str = ""
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record: SurplusFoodRecord) -> "SurplusFoodResponse":
        return cls(
            surplus_id=record.surplus_id,
            restaurant_id=record.restaurant_id,
            restaurant_name=record.restaurant_name or "",
            description=record.description,
            quantity=record.quantity,
            original_price=record.original_price or 0.0,
            discounted_price=record.discounted_price or 0.0,
            expiry_time=as_utc(record.expiry_time),
            is_available=record.is_available,
            reserved_by_org_id=record.reserved_by_org_id,
            pickup_city=record.pickup_city or "",
            created_at=as_utc(record.created_at),
        )


class ReservedSurplusResponse(BaseModel):
    """One of the caller organization's reservations.

    `quantity` is what this organization booked, not what is left on the shelf:
    a listing of ten portions split six/four appears as six here to one
    organization and four to the other, which is the only reading that makes the
    received page add up.
    """

    model_config = ConfigDict(extra="allow")

    surplus_id: str
    restaurant_id: Optional[str] = None
    restaurant_name: str = ""
    description: str
    quantity: int
    original_price: float = 0.0
    discounted_price: float = 0.0
    expiry_time: Optional[datetime] = None
    delivery_id: str
    delivery_status: str
    created_at: Optional[datetime] = None

    @classmethod
    def from_records(
        cls,
        delivery: SurplusDeliveryRecord,
        listing: SurplusFoodRecord,
    ) -> "ReservedSurplusResponse":
        return cls(
            surplus_id=listing.surplus_id,
            restaurant_id=listing.restaurant_id,
            restaurant_name=listing.restaurant_name or "",
            description=listing.description,
            quantity=delivery.quantity,
            original_price=listing.original_price or 0.0,
            discounted_price=listing.discounted_price or 0.0,
            expiry_time=as_utc(listing.expiry_time),
            delivery_id=delivery.delivery_id,
            delivery_status=delivery.status,
            created_at=as_utc(delivery.created_at),
        )


class SurplusReservationResponse(BaseModel):
    """What the reserve endpoint answers, and what its toast quotes."""

    message: str
    surplus_id: str
    delivery_id: str
    quantity_reserved: int
    quantity_remaining: int


class SurplusDeliveryResponse(BaseModel):
    """A volunteer run, as the driver's board shows it."""

    model_config = ConfigDict(extra="allow")

    delivery_id: str
    surplus_id: str
    restaurant_id: Optional[str] = None
    restaurant_name: str = ""
    org_id: str
    org_name: str = ""
    quantity: int = 1
    description: str = ""
    status: str = SurplusDeliveryStatus.PENDING.value
    distance_km: Optional[float] = None
    estimated_time: Optional[int] = None
    # Only filled in for the driver carrying the run.
    pickup: Optional[LocationSummary] = None
    dropoff: Optional[LocationSummary] = None

    @classmethod
    def from_record(
        cls,
        record: SurplusDeliveryRecord,
        distance_km: Optional[float] = None,
        estimated_time: Optional[int] = None,
        include_places: bool = False,
    ) -> "SurplusDeliveryResponse":
        view = cls(
            delivery_id=record.delivery_id,
            surplus_id=record.surplus_id,
            restaurant_id=record.restaurant_id,
            restaurant_name=record.restaurant_name or "",
            org_id=record.org_id,
            org_name=record.org_name or "",
            quantity=record.quantity,
            description=record.description or "",
            status=record.status,
            distance_km=(
                round(distance_km, 1)
                if distance_km is not None
                else (round(record.distance_km, 1) if record.distance_km is not None else None)
            ),
            estimated_time=estimated_time,
        )
        if include_places:
            view.pickup = LocationSummary(
                address=record.pickup_address or "",
                city=record.pickup_city or "",
                zip_code=record.pickup_zip_code or "",
            )
            view.dropoff = LocationSummary(
                address=record.dropoff_address or "",
                city=record.dropoff_city or "",
                zip_code=record.dropoff_zip_code or "",
            )
        return view
