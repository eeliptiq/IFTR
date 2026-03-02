from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, timezone
from enum import Enum
from app.core.ids import generate_id
from ..models.encrypted_models import EncryptedLocation

# Surplus Food Models
class SurplusFood(BaseModel):
    model_config = ConfigDict(extra="ignore")
    surplus_id: str = Field(default_factory=lambda: generate_id("surplus"))
    user_id: str  # Owner user ID (Restaurant or Free Kitchen)
    restaurant_id: Optional[str] = None  # Optional, for backward compatibility or specific restaurant linkage
    restaurant_name: str = ""
    description: str
    quantity: int
    original_price: float
    discounted_price: float = 0.0  # 0 means free
    expiry_time: datetime
    pickup_location: EncryptedLocation
    is_available: bool = True
    reserved_by_org_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SurplusFoodCreate(BaseModel):
    description: str
    quantity: int
    original_price: float
    discounted_price: float = 0.0
    expiry_hours: int = 4  # Hours until expiry


# Surplus Delivery Model - Driver volunteers to deliver surplus to organizations
class SurplusDeliveryStatus(str, Enum):
    PENDING = "pending"  # Waiting for driver pickup
    PICKED_UP = "picked_up"  # Driver has the food
    IN_TRANSIT = "in_transit"  # On the way to organization
    DELIVERED = "delivered"  # Completed
    CANCELLED = "cancelled"


class SurplusDelivery(BaseModel):
    model_config = ConfigDict(extra="ignore")
    delivery_id: str = Field(default_factory=lambda: generate_id("sdel"))
    surplus_id: str
    restaurant_id: str
    restaurant_name: str = ""
    org_id: str
    org_name: str = ""
    driver_id: Optional[str] = None
    driver_name: str = ""
    status: SurplusDeliveryStatus = SurplusDeliveryStatus.PENDING
    pickup_location: Optional[EncryptedLocation] = None
    delivery_location: Optional[EncryptedLocation] = None
    estimated_time: Optional[int] = None  # minutes
    quantity: int = 1
    description: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
