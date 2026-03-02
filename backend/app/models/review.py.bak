from pydantic import BaseModel, Field, ConfigDict
from ..core.ids import generate_id
from typing import Optional
from datetime import datetime, timezone

# Review Models
class Review(BaseModel):
    model_config = ConfigDict(extra="ignore")
    review_id: str = Field(default_factory=lambda: generate_id("rev"))
    order_id: str
    customer_id: str
    customer_name: str = ""
    restaurant_id: Optional[str] = None
    driver_id: Optional[str] = None
    rating: int  # 1-5
    comment: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewCreate(BaseModel):
    order_id: str
    restaurant_rating: Optional[int] = None
    comment: str = ""
