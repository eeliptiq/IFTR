"""
Pydantic models for IFTR food delivery platforms
"""

"""
Location models for IFTR food delivery system.

Design Note: Coordinates are encrypted separately (lat, lng) for simplicity.
For deployments expecting >1,000,000 active locations (major metropolitan areas),
consider combining coordinates into a single encrypted JSON object to:
1. Reduce storage by ~30% (one IV/tag instead of two)
2. Ensure atomic updates (lat/lng can't get mismatched)
3. Slightly faster encryption/decryption (one operation instead of two)

Current separate encryption supports moderate-scale deployments effectively.

See documes/snippets_for_different_builds.txt for major metropolitan support and enhanced encryption options.
"""


# app/models/general.py - CLEAN VERSION
from enum import Enum
from datetime import datetime, timezone
from typing import Optional
from pydantic import Field, ConfigDict, EmailStr, SecretStr, BaseModel
import logging
from ..core.ids import generate_id

logger = logging.getLogger(__name__)
logger = logging.getLogger(__name__)

class OrderStatus(str, Enum):
    PENDING = "pending"        # Charge customer but allow refund if restaurant declines
    CONFIRMED = "confirmed"    # Restaurant has accepted the order, no more refund unless issue
    PREPARING = "preparing"
    READY = "ready"            # Order is waiting for driver
    ASSIGNED = "assigned"      # Driver accepted, on the way to restaurant
    PICKED_UP = "picked_up"    # Driver has the food
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"    # Default cancellation policy is not allowing customer to cancel after confirmed
                               # If order has issue, customer can receive credits or refund after contacting support
                               # Feel free to change this, but remember cancellation can be a major platform issue

class FoodType(str, Enum):
    REGULAR = "regular"
    SURPLUS = "surplus"
    DONATION = "donation"

class VehicleType(str, Enum):
    MOTORCYCLE = "motorcycle"
    CAR = "car"
    TRUCK = "truck"
    E_BIKE = "e-bike"
    BIKE = "bike"
    SKATES = "rollerskates/skateboard"

class DeliveryInstructionType(str, Enum):
    """Types of delivery instructions"""
    LEAVE_AT_DOOR = "leave_at_door"
    HAND_TO_CUSTOMER = "hand_to_customer"
    MEET_AT_DOOR = "meet_at_door"
    CALL_ON_ARRIVAL = "call_on_arrival"
    NO_CONTACT = "no_contact"
    RING_BELL = "ring_bell"
    USE_SIDE_DOOR = "use_side_door"
    OTHER = "other"

class CalendarPreference(str, Enum):
    """Calendar preferences for users"""
    GREGORIAN = "gregorian"
    JALALI = "jalali"
    HIJRI = "hijri"
    HEBREW = "hebrew"
    CHINESE = "chinese"

# Base Models
# Base model for inheritance if needed
class IFTRBaseModel(BaseModel):
    """Base model with common configurations"""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

class DecryptedLocation(IFTRBaseModel):
    lat: float = 0.0
    lng: float = 0.0
    # NOTE: For high-volume applications (>1M locations), consider
    # combined encryption (lat+lng as single encrypted JSON) to reduce
    # storage overhead and ensure atomicity. Current separate encryption
    # is simpler for moderate-scale deployments.
    address: str = ""
    city: str = ""
    zip_code: str = ""

class AddressTier(str, Enum):
    CUSTOMER_HOME = "customer_home"  # Full encryption
    CUSTOMER_WORK = "customer_work"  # Full encryption
    ORGANIZATION = "organization"  # Partial encryption (coordinates only)
    PUBLIC_PLACE = "public_place"  # No encryption