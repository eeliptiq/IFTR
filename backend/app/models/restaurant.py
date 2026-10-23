from typing import List, Dict, Any

from app.core.ids import generate_id
from datetime import datetime, timezone
from typing import Optional
from pydantic import Field, ConfigDict, model_validator, validator
from app.models.encrypted_models import EncryptedLocation
from app.models.general import IFTRBaseModel, OrderStatus, FoodType, VehicleType
from app.models.user import UserRole
from app.models.menu_item import OptionType, MenuOption, MenuItem, MenuItemModifier
import logging

logger = logging.getLogger(__name__)

class MenuCategory(IFTRBaseModel):
    """Category for organizing menu items"""
    category_id: str = Field(default_factory=lambda: generate_id("cat"))
    name: str
    description: str = ""
    display_order: int = 0
    image_url: Optional[str] = None
    items: List[MenuItem] = Field(default_factory=list)

class RestaurantHours(IFTRBaseModel):
    """Operating hours for a single day"""
    day: str  # monday, tuesday, etc.
    open_time: str = ""  # HH:MM format, empty = closed
    close_time: str = ""  # HH:MM format, empty = closed
    is_closed: bool = False  # Explicitly closed for this day

    @model_validator(mode="after")
    def validate_times(self):
        # If explicitly closed, accept missing times
        if self.is_closed:
            return self

        # Both open and close should be provided or both empty
        if (bool(self.open_time) != bool(self.close_time)):
            raise ValueError("Both open_time and close_time must be set, or both empty when not closed")

        if self.open_time and self.close_time:
            try:
                ot = datetime.strptime(self.open_time, "%H:%M")
                ct = datetime.strptime(self.close_time, "%H:%M")
            except Exception:
                raise ValueError("open_time and close_time must be in HH:MM format")

            # Allow cross-midnight hours (e.g. 18:00 to 02:00)
            # if ot >= ct:
            #     raise ValueError("open_time must be before close_time")

        return self

class Restaurant(IFTRBaseModel):
    model_config = ConfigDict(extra="ignore")
    restaurant_id: str = Field(default_factory=lambda: generate_id("rest"))
    user_id: str  # Owner user ID
    name: str
    description: str = ""
    cuisine_type: str = ""
    image_url: Optional[str] = None
    location: EncryptedLocation
    is_active: bool = True
    is_online: bool = True  # Manual online/offline toggle
    manual_is_open: Optional[bool] = None # True=Force Open, False=Force Closed, None=Auto
    next_auto_close_at: Optional[datetime] = None # Failsafe time
    timezone: str = "UTC" # Default timezone
    operating_hours: List[RestaurantHours] = []  # Weekly schedule
    rating: float = 0.0
    total_reviews: int = 0
    menu: List[MenuItem] = []
    # Delivery settings can be customized per-restaurant:
    # {
    #   "per_km": 0.25,
    #   "base_fees": {"priority": 6.0, "standard": 6.0, "economy": 3.0},
    #   "company_fee_enabled": False,
    #   "company_fee_amount": 1.0,
    #   "free_over_total": 30.0
    # }
    delivery_settings: Dict[str, Any] = {}
    # Leaderboard and donation tracking
    show_in_leaderboard: bool = False
    total_meals_donated: int = 0
    surplus_deliveries_completed: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RestaurantCreate(IFTRBaseModel):
    name: str
    description: str = ""
    cuisine_type: str = ""
    image_url: Optional[str] = None
    lat: float
    lng: float
    address: str = ""
    city: str = ""
    zip_code: str = ""

class RestaurantSettingsUpdate(IFTRBaseModel):
    operating_hours: Optional[List[RestaurantHours]] = None
    manual_is_open: Optional[bool] = None
    timezone: Optional[str] = None
    show_in_leaderboard: Optional[bool] = None
    max_delivery_km: Optional[float] = None  # Drivers are not associated with restaurant
                                             # Main purpose is in case restaurant is concerned about order errors
                                             # Recommend opt-in for restaurants rather than default configuration
