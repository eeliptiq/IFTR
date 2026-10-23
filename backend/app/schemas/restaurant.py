"""
Request/response schemas for restaurant & menu endpoints.

These mirror the shapes the React frontend already sends/expects (see
frontend/src/pages/Restaurants.js, RestaurantDetail.js, RestaurantMenu.js,
RegisterRestaurant.js) so the existing UI can be reused with minimal changes.
"""

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class MenuItemRequest(BaseModel):
    """
    A single menu item as sent by the restaurant menu manager.

    Every field the item keeps has to be declared here: pydantic ignores what a
    model does not know, so a flag missing from this list is silently dropped on
    the way to storage rather than rejected.
    """

    item_id: Optional[str] = None
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    price: float = 0.0
    category: str = ""
    image_url: Optional[str] = None
    is_available: bool = True
    is_drink: bool = False
    is_sealed: bool = False
    is_surplus: bool = False
    surplus_quantity: int = 0


class MenuItemResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_id: str
    name: str
    description: str = ""
    price: float = 0.0
    category: str = ""
    image_url: Optional[str] = None
    is_available: bool = True
    is_drink: bool = False
    is_sealed: bool = False
    is_surplus: bool = False
    surplus_quantity: int = 0


class RestaurantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str = ""
    cuisine_type: str = ""
    image_url: Optional[str] = None
    lat: float
    lng: float
    address: str = ""
    city: str = ""
    zip_code: str = ""


class RestaurantResponse(BaseModel):
    """Safe, client-facing view. Coordinates are never returned in full."""

    model_config = ConfigDict(extra="allow")

    restaurant_id: str
    user_id: str
    name: str
    description: str = ""
    cuisine_type: str = ""
    image_url: Optional[str] = None
    is_active: bool = True
    is_online: bool = True
    rating: float = 0.0
    total_reviews: int = 0
    city: str = ""
    zip_code: str = ""
    menu: List[MenuItemResponse] = Field(default_factory=list)
    distance_km: Optional[float] = None
    created_at: Optional[datetime] = None
