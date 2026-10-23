"""
Request/response models for the driver endpoints.

Shaped around what the driver screen sends and reads (see
frontend/src/pages/DriverDeliveries.js): it registers with
`{vehicle_type, license_number}`, updates the vehicle with the same shape, and
toggles availability with `is_available` as a *query parameter*.

The licence number goes in and never comes back out - the profile reports only
whether one is on file.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.geo import compass_point
from app.models.driver_orm import DriverRecord
from app.models.general import VehicleType, vehicle_eta_minutes
from app.schemas.order import OrderResponse

# Vehicles with nowhere built in to stand a cup. The enum says what a driver may
# travel on; this says what the ride can carry, so it belongs here rather than
# beside the enum.
VEHICLES_WITHOUT_CUP_HOLDER = frozenset(
    {
        VehicleType.MOTORCYCLE.value,
        VehicleType.E_BIKE.value,
        VehicleType.BIKE.value,
        VehicleType.SKATES.value,
        VehicleType.WALK.value,
    }
)


class DriverRegisterRequest(BaseModel):
    """What the driver registration form sends."""

    vehicle_type: VehicleType = VehicleType.CAR
    license_number: str = Field(default="", max_length=64)


class DriverVehicleUpdateRequest(BaseModel):
    """What the vehicle dialog sends. The licence is optional here."""

    vehicle_type: VehicleType
    license_number: Optional[str] = Field(default=None, max_length=64)


class DriverResponse(BaseModel):
    """A driver's own record. The licence number is never included."""

    model_config = ConfigDict(extra="allow")

    driver_id: str
    user_id: str
    # Sent as the stored string rather than the enum: input is validated against
    # VehicleType, but re-validating on the way out would turn a hand-edited row
    # into a 500 on the driver's own profile.
    vehicle_type: str
    is_available: bool
    has_license: bool = False
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record: DriverRecord) -> "DriverResponse":
        return cls(
            driver_id=record.driver_id,
            user_id=record.user_id,
            vehicle_type=record.vehicle_type,
            is_available=record.is_available,
            has_license=record.has_license,
            created_at=record.created_at,
        )


class DriverJobResponse(OrderResponse):
    """A job as the driver carrying it sees it: the order plus what it asks of
    the ride.

    The kitchen's and the customer's views of the same row stay unchanged; only
    the driver needs to know that two drinks are coming and that a bicycle has
    nowhere to stand them.
    """

    requires_cup_holder: bool = False
    # One line of plain text per thing to do differently. A list rather than a
    # single string so a second rule can be added without rewriting the screen.
    handling_notes: List[str] = Field(default_factory=list)

    # The trip, as far as it can be measured. None throughout when the order has
    # no location on file: an offer without a distance is still an offer.
    distance_km: Optional[float] = None
    eta_minutes: Optional[int] = None
    # Degrees clockwise from north, plus the eight-point name of the same thing,
    # so the screen can turn an arrow without doing trigonometry of its own.
    dropoff_bearing: Optional[float] = None
    dropoff_direction: Optional[str] = None
    # True when this driver passed on the job earlier and asked to see it again.
    was_rejected: bool = False

    def plan_trip(
        self,
        distance_km: Optional[float],
        bearing: Optional[float],
        vehicle_type: str,
    ) -> "DriverJobResponse":
        """Say how far the job is, how long it should take, and which way it lies.

        All three come from one measurement, so they are set together or not at
        all: a distance with no arrow would read as a bug rather than as missing
        data. The ETA is this vehicle's, since the same trip is a different job
        on foot than in a car.
        """
        if distance_km is None or bearing is None:
            return self

        self.distance_km = round(distance_km, 1)
        self.dropoff_bearing = round(bearing, 1)
        self.dropoff_direction = compass_point(bearing)
        self.eta_minutes = vehicle_eta_minutes(vehicle_type, distance_km)
        return self

    def plan_for(self, vehicle_type: str) -> "DriverJobResponse":
        """Record what this job asks of the driver's current vehicle.

        Only unsealed drinks are planned around: a sealed bottle or can travels
        like any other item, an open cup does not. Idempotent - called again
        after a vehicle change, it re-decides from scratch instead of
        accumulating notes.
        """
        self.requires_cup_holder = False
        self.handling_notes = []

        unsealed = self.unsealed_drink_count
        if not unsealed:
            return self

        pronoun = "it" if unsealed == 1 else "them"
        plural = "" if unsealed == 1 else "s"
        self.handling_notes.append(
            f"Carry {unsealed} unsealed drink{plural} and keep {pronoun} upright."
        )

        if vehicle_type in VEHICLES_WITHOUT_CUP_HOLDER:
            self.requires_cup_holder = True
            self.handling_notes.append(
                "Bring a cup holder or tray: this vehicle has nowhere to stand a cup."
            )

        return self


class EarningsPeriod(BaseModel):
    """One window of completed paid trips.

    `earnings` is the delivery fee plus the tip: what the trip was priced at,
    not a settled payout. Nothing in the app moves money yet (payments are not
    merged), so there is no commission to subtract and no transfer to point at.
    """

    deliveries: int = 0
    delivery_fees: float = 0.0
    tips: float = 0.0
    earnings: float = 0.0


class RecentDelivery(BaseModel):
    """One completed paid trip, for the earnings screen's list."""

    order_id: str
    delivered_at: Optional[datetime] = None
    delivery_fees: float = 0.0
    tips: float = 0.0
    earnings: float = 0.0


class DriverEarningsResponse(BaseModel):
    """A driver's lifetime totals, three rolling windows and recent trips.

    There is no rating field: reviews are not merged, and a made-up 5.0 would be
    the screen inventing a reputation. `surplus_runs` is separate from paid
    trips because volunteer rescues pay nothing and counting them as deliveries
    would overstate what the driver earned.
    """

    total_deliveries: int = 0
    total_earnings: float = 0.0
    today: EarningsPeriod = Field(default_factory=EarningsPeriod)
    week: EarningsPeriod = Field(default_factory=EarningsPeriod)
    month: EarningsPeriod = Field(default_factory=EarningsPeriod)
    surplus_runs: int = 0
    recent: List[RecentDelivery] = Field(default_factory=list)
