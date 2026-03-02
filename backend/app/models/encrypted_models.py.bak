from .general import IFTRBaseModel
from .general import AddressTier
from typing import Optional, TYPE_CHECKING
from datetime import datetime, timezone
from ..core.ids import generate_id

from pydantic import ConfigDict, Field

class EncryptedLocation(IFTRBaseModel):
    lat: str = ""  # Encrypted latitude
    lng: str = ""  # Encrypted longitude
    # NOTE: For high-volume applications (>1M locations), consider
    # combined encryption (lat+lng as single encrypted JSON) to reduce
    # storage overhead and ensure atomicity. Current separate encryption
    # is simpler for moderate-scale deployments.
    address: str = ""
    city: str = ""
    zip_code: str = ""

class EncryptedAddress(IFTRBaseModel):
    """Address with ZIP-based localization"""
    tier: AddressTier
    encrypted_lat: str = ""
    encrypted_lng: str = ""

    # Text fields
    _address_line_encrypted: str = ""
    address_line: str = ""
    city: str = ""
    zip_code: str = ""
    zip_prefix: str = ""
    neighborhood: str = ""  # Optional community self-identification

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-calculate ZIP prefix
        if self.zip_code and len(self.zip_code) >= 3:
            self.zip_prefix = self.zip_code[:3]

    @property
    def display_address(self) -> str:
        """Safe display based on sensitivity"""
        if self.tier in [AddressTier.CUSTOMER_HOME, AddressTier.CUSTOMER_WORK]:
            # Privacy-focused display
            if self.city and self.zip_code:
                return f"{self.city}, {self.zip_code}"
            elif self.zip_code:
                return f"ZIP: {self.zip_code}"
            else:
                return "Location protected"
        else:
            # Public/organization: Full address
            return f"{self.address_line}, {self.city}, {self.zip_code}"

    @property
    def region(self) -> str:
        """Get region for routing/analytics"""
        return self.zip_prefix or "unknown"
