
"""
User models for IFTR platform.

Clean separation:
- Public models (API responses, client-facing)
- Private models (database/internal, with sensitive data)
- Authentication models (sessions, tokens)
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, EmailStr, SecretStr, field_validator
import re

from app.models.general import IFTRBaseModel, generate_id, UserRole
from app.models.encrypted_models import EncryptedLocation
from app.contribution_scores import contributionScore, contributionTier
from app.contribution_benefits import ActiveBenefit

from decimal import Decimal

# ===== ENUMS =====
class CalendarPreference(str, Enum):
    """Calendar preferences for cultural/religious needs"""
    GREGORIAN = "gregorian"  # Default Western calendar
    HIJRI = "hijri"  # Islamic calendar
    HEBREW = "hebrew"  # Hebrew calendar
    CHINESE = "chinese" # Chinese lunar calendar
    BUDDHIST = "buddhist"  # Buddhist calendar


class ThemePreference(str, Enum):
    """UI theme preferences"""
    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"  # Follow system preference


# ===== PUBLIC MODELS (Client-facing) =====
class UserBase(IFTRBaseModel):
    """Base fields shared by all user models"""
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    role: UserRole = UserRole.CUSTOMER
    phone: Optional[str] = Field(None, pattern=r'^\+?[1-9]\d{1,14}$')  # E.164 format
    picture: Optional[str] = None  # URL to profile picture
    preferred_calendar: CalendarPreference = CalendarPreference.GREGORIAN
    credits: Decimal = 0.0 # Can be used for delivery orders instead of cash
                           # Given as remuneration for errors
                           # Before cashing out, earnings can be used as credits instead
                           # This decreases credit card processing fees if earning user intends to order anyway
    # =============== ADD LANGUAGE OPTIONS ===============

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is properly formatted"""
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class UserCreate(IFTRBaseModel):
    """
    Input for user registration.
    Used when creating new users via API.
    """
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: Optional[SecretStr] = None  # For traditional signup
    role: UserRole = UserRole.CUSTOMER
    phone: Optional[str] = Field(None, pattern=r'^\+?[1-9]\d{1,14}$')
    picture: Optional[str] = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: Optional[SecretStr]) -> Optional[SecretStr]:
        """Validate password strength if provided"""
        if v is not None:
            password = v.get_secret_value()
            if len(password) < 8:
                raise ValueError("Password must be at least 8 characters")
            # Add more password rules as needed
        return v


class UserResponse(UserBase):
    """
    What gets returned to clients.
    Contains no sensitive information.
    """
    user_id: str = Field(default_factory=lambda: generate_id("user"))
    is_active: bool = True
    is_approved: bool = False  # For drivers/organizations needing approval
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    theme_preference: ThemePreference = ThemePreference.AUTO

    # Statistics (public)
    total_orders: int = 0
    total_deliveries: int = 0  # For drivers
    member_since_days: Optional[int] = None

    @property
    def is_driver(self) -> bool:
        """Check if user is a driver"""
        return self.role == UserRole.DRIVER

    @property
    def is_admin(self) -> bool:
        """Check if user has admin privileges"""
        return self.role in [UserRole.ADMIN, UserRole.SUPPORT]


# ===== PRIVATE MODELS (Database/Internal) =====
class UserDB(UserResponse):
    """
    Database version with private fields.
    Named UserDB to distinguish from public models.
    """
    model_config = ConfigDict(extra="ignore")

    # Authentication & Security
    password_hash: Optional[str] = None  # Hashed password (bcrypt/scrypt)
    mfa_secret: Optional[str] = None  # For 2FA
    two_factor_enabled: bool = False
    login_attempts: int = 0
    account_locked_until: Optional[datetime] = None
    last_login: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None

    # Privacy-sensitive data (encrypted at rest)
    location: Optional[EncryptedLocation] = None  # Current/last known location
    date_of_birth: Optional[str] = None  # Encrypted if stored
    government_id_hash: Optional[str] = None  # For driver verification

    # Preferences (private)
    notification_preferences: Dict[str, bool] = Field(default_factory=lambda: {
        "email": True,
        "push": True,
        "sms": False
    })
    email_verified: bool = False
    phone_verified: bool = False

    # Metadata
    signup_source: Optional[str] = None  # "web", "mobile", "invite"
    referral_code: Optional[str] = None
    referred_by: Optional[str] = None

    def is_account_locked(self) -> bool:
        """Check if account is currently locked"""
        if self.account_locked_until is None:
            return False
        return datetime.now(timezone.utc) < self.account_locked_until

    def increment_login_attempts(self, max_attempts: int = 5, lock_minutes: int = 15):
        """Increment failed login attempts and lock if exceeded"""
        self.login_attempts += 1
        if self.login_attempts >= max_attempts:
            self.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=lock_minutes)


class UserSession(IFTRBaseModel):
    """
    User session for authentication.
    Tokens are hashed before storage.
    """
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(default_factory=lambda: generate_id("sess"))
    user_id: str
    session_token_hash: str  # Hash of the actual JWT/session token
    expires_at: datetime
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Security context
    device_info: Optional[str] = None  # "iPhone 14, iOS 17"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    location_approx: Optional[str] = None  # City/region, not exact coordinates

    # Session metadata
    is_mobile: bool = False
    last_activity: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        """Check if session has expired"""
        return datetime.now(timezone.utc) > self.expires_at

    def is_active(self) -> bool:
        """Check if session is still active (not expired)"""
        return not self.is_expired()


class UserUpdate(IFTRBaseModel):
    """
    Input for updating user profile.
    Partial updates allowed.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, pattern=r'^\+?[1-9]\d{1,14}$')
    picture: Optional[str] = None
    preferred_calendar: Optional[CalendarPreference] = None
    theme_preference: Optional[ThemePreference] = None
    notification_preferences: Optional[Dict[str, bool]] = None

class UserWithContribution(UserDB):

    """
    User model extended with contribution functionality
    """
    contribution: Optional[contributionScore] = None

    @property
    def contribution_score(self) -> int:
        """Get user's contribution score, default to 0 if not set"""
        return self.contribution.total_contribution if self.contribution else 0

    @property
    def contribution_tier(self) -> contributionTier:
        """Get user's contribution tier"""
        return self.contribution.current_tier if self.contribution else contributionTier.NEWCOMER

    @property
    def active_benefits(self) -> List[ActiveBenefit]:
        """Get user's active benefits (would come from database)"""
        # This would typically be a relationship
        return []

    def can_access_priority_deliveries(self) -> bool:
        """Check if user can access priority deliveries (for drivers)"""
        if self.role != UserRole.DRIVER:
            return False

        return self.contribution_tier in [
            contributionTier.CHAMPION,
            contributionTier.HERO,
            contributionTier.LEGEND
        ]

    def get_delivery_priority_boost(self) -> float:
        """Get priority boost for delivery access based on contribution"""
        if not self.contribution:
            return 1.0

        # Higher contribution = higher boost
        boost_map = {
            contributionTier.NEWCOMER: 1.0,
            contributionTier.CONTRIBUTOR: 1.1,
            contributionTier.HELPER: 1.2,
            contributionTier.CHAMPION: 1.4,
            contributionTier.HERO: 1.6,
            contributionTier.LEGEND: 2.0,
        }

        return boost_map.get(self.contribution_tier, 1.0)


# ===== HELPER FUNCTIONS =====
def create_user_response(user_db: UserDB) -> UserResponse:
    """
    Convert UserDB to UserResponse (strip private fields).
    Used before sending user data to clients.
    """
    # Get public fields from UserDB
    public_data = user_db.model_dump(exclude={
        # Exclude all sensitive/internal fields
        'password_hash', 'mfa_secret', 'two_factor_enabled',
        'login_attempts', 'account_locked_until', 'last_login',
        'password_changed_at', 'location', 'date_of_birth',
        'government_id_hash', 'notification_preferences',
        'email_verified', 'phone_verified', 'signup_source',
        'referral_code', 'referred_by'
    })

    return UserResponse(**public_data)


def mask_email(email: str) -> str:
    """Mask email for privacy in logs"""
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = '*' * len(local)
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_phone(phone: str) -> str:
    """Mask phone number for privacy"""
    if len(phone) <= 4:
        return '***'
    return phone[:-4] + '****'
