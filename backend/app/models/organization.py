from core.ids import generate_id
from datetime import datetime, timezone
from typing import Optional
from pydantic import Field, ConfigDict
import logging
from models.encrypted_models import EncryptedLocation
from models.general import IFTRBaseModel

logger = logging.getLogger(__name__)

# Organization Models (for food distribution)
class Organization(IFTRBaseModel):
    model_config = ConfigDict(extra="ignore")
    org_id: str = Field(default_factory=lambda: generate_id("org"))
    user_id: str
    name: str
    description: str = ""
    org_type: str = ""  # food_bank, shelter, community_kitchen
    location: EncryptedLocation
    contact_email: str = ""
    contact_phone: str = ""
    delivery_address: Optional[str] = None # Optional delivery address
    is_verified: bool = False
    total_received: int = 0  # Total meals received
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class OrganizationCreate(IFTRBaseModel):
    name: str
    description: str = ""
    org_type: str = ""
    lat: float
    lng: float
    address: str = ""
    city: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    delivery_address: Optional[str] = None

class OrganizationSettingsUpdate(IFTRBaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    org_type: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    delivery_address: Optional[str] = None