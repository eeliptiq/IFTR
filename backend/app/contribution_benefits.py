# contribution_benefits.py
"""
contribution benefits and rewards system
"""

from typing import Dict, List, Optional, Any, Set
from pydantic import Field
from enum import Enum
from datetime import datetime, timedelta, timezone
from app.models.general import IFTRBaseModel, UserRole
from app.core.ids import generate_id
from app.contribution_scores import contributionScore, contributionTier

class contributionBenefitType(str, Enum):
    """Types of benefits users can unlock with contribution"""
    # Driver Benefits
    PRIORITY_ACCESS = "priority_access"  # First dibs on high-paying orders
    PROFILE_BADGE = "profile_badge"  # Visual recognition
    EXTENDED_OFFER_TIME = "extended_offer_time"  # More time to accept deliveries

    # Customer Benefits
    DELIVERY_DISCOUNT = "delivery_discount"
    FREE_DELIVERY = "free_delivery"
    PRIORITY_SUPPORT = "priority_support"
    EARLY_ACCESS = "early_access"  # Early access to new features
    DONATION_MATCH = "donation_match"  # Platform matches donations

    # Restaurant Benefits
    FEATURED_LISTING = "featured_listing"
    PROMOTIONAL_SPOT = "promotional_spot"  # Featured in promotions
    ANALYTICS_UPGRADE = "analytics_upgrade"  # Better analytics

    # Universal Benefits
    CUSTOM_THEME = "custom_theme"  # Custom app theme
    EXCLUSIVE_EVENTS = "exclusive_events"  # Invite-only events
    VERIFIED_STATUS = "verified_status"  # Verified badge


class contributionBenefit(IFTRBaseModel):
    """A specific benefit that can be unlocked with contribution"""
    benefit_id: str = Field(default_factory=lambda: generate_id("benefit"))
    benefit_type: contributionBenefitType
    name: str
    description: str

    # Requirements
    required_tier: contributionTier
    required_contribution: Optional[int] = None  # Alternative to tier
    cost_to_unlock: int = 0  # contribution cost to unlock (if any)

    # Activation
    is_active: bool = True
    max_uses: Optional[int] = None  # None = unlimited
    cooldown_days: Optional[int] = None  # Days between uses

    # Effects
    effect_data: Dict[str, Any] = Field(default_factory=dict)

    # Metadata
    icon: Optional[str] = None
    color: Optional[str] = None


class ActiveBenefit(IFTRBaseModel):
    """A benefit currently active for a user"""
    user_id: str
    benefit_id: str
    unlocked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Usage tracking
    times_used: int = 0
    last_used: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Current state
    is_active: bool = True
    remaining_uses: Optional[int] = None
    cooldown_days: Optional[int] = None

    @property
    def can_use(self) -> bool:
        """Check if benefit can be used now"""
        if not self.is_active:
            return False

        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False

        if self.remaining_uses is not None and self.remaining_uses <= 0:
            return False

        if self.cooldown_days and self.last_used:
            next_available = self.last_used + timedelta(days=self.cooldown_days)
            if datetime.now(timezone.utc) < next_available:
                return False

        return True

    def use(self) -> bool:
        """Use the benefit once"""
        if not self.can_use:
            return False

        self.times_used += 1
        self.last_used = datetime.now(timezone.utc)

        if self.remaining_uses is not None:
            self.remaining_uses -= 1
            if self.remaining_uses <= 0:
                self.is_active = False

        return True


class contributionRewardsManager:
    """Manage contribution benefits and rewards"""

    # Pre-defined benefits by tier
    TIER_BENEFITS = {
        contributionTier.CONTRIBUTOR: [
            {
                "type": contributionBenefitType.PROFILE_BADGE,
                "name": "Contributor Badge",
                "description": "Show your support with a contributor badge",
                "cost": 0,  # Automatically unlocked at tier
            }
        ],
        contributionTier.HELPER: [
            {
                "type": contributionBenefitType.PRIORITY_SUPPORT,
                "name": "Priority Support",
                "description": "Get faster responses from support team",
                "cost": 0,
            }
        ],
        contributionTier.CHAMPION: [
            {
                "type": contributionBenefitType.PRIORITY_ACCESS,
                "name": "Priority Delivery Access",
                "description": "Get first look at high-paying deliveries (drivers)",
                "cost": 0,
            },
            {
                "type": contributionBenefitType.DELIVERY_DISCOUNT,
                "name": "10% Delivery Discount",
                "description": "10% off delivery fees (customers)",
                "cost": 200,  # Can be purchased with contribution
            }
        ],
        contributionTier.HERO: [
            {
                "type": contributionBenefitType.FEATURED_LISTING,
                "name": "Featured Restaurant",
                "description": "Get featured in restaurant listings",
                "cost": 0,
            },
            {
                "type": contributionBenefitType.VERIFIED_STATUS,
                "name": "Verified Status",
                "description": "Get a verified checkmark on your profile",
                "cost": 0,
            }
        ],
        contributionTier.LEGEND: [
            {
                "type": contributionBenefitType.EXCLUSIVE_EVENTS,
                "name": "Exclusive Events Access",
                "description": "Access to platform exclusive events",
                "cost": 0,
            }
        ]
    }

    @classmethod
    def get_available_benefits(
            cls,
            user_contribution: contributionScore,
            user_role: UserRole
    ) -> List[contributionBenefit]:
        """Get benefits available to user based on tier and role"""
        available = []

        # Get benefits for current tier and all lower tiers
        tiers = list(contributionTier)
        user_tier_index = tiers.index(user_contribution.current_tier)

        for i in range(user_tier_index + 1):
            tier = tiers[i]
            tier_benefits = cls.TIER_BENEFITS.get(tier, [])

            for benefit_def in tier_benefits:
                # Check if benefit is relevant to user's role
                if cls._is_benefit_relevant(benefit_def["type"], user_role):
                    benefit = contributionBenefit(
                        benefit_type=benefit_def["type"],
                        name=benefit_def["name"],
                        description=benefit_def["description"],
                        required_tier=tier,
                        cost_to_unlock=benefit_def.get("cost", 0),
                    )
                    available.append(benefit)

        return available

    @classmethod
    def _is_benefit_relevant(cls, benefit_type: contributionBenefitType, user_role: UserRole) -> bool:
        """Check if a benefit is relevant to a user's role"""
        role_mapping = {
            contributionBenefitType.PRIORITY_ACCESS: [UserRole.DRIVER],

            contributionBenefitType.DELIVERY_DISCOUNT: [UserRole.CUSTOMER],
            contributionBenefitType.FREE_DELIVERY: [UserRole.CUSTOMER],
            contributionBenefitType.DONATION_MATCH: [UserRole.CUSTOMER],

            contributionBenefitType.FEATURED_LISTING: [UserRole.RESTAURANT_ADMIN],
            contributionBenefitType.PROMOTIONAL_SPOT: [UserRole.RESTAURANT_ADMIN],

            # Universal benefits for all roles
            contributionBenefitType.PROFILE_BADGE: [UserRole.CUSTOMER, UserRole.DRIVER,
                                             UserRole.RESTAURANT_ADMIN, UserRole.ORGANIZATION_ADMIN],
            contributionBenefitType.PRIORITY_SUPPORT: [UserRole.CUSTOMER, UserRole.DRIVER,
                                                UserRole.RESTAURANT_ADMIN],
            contributionBenefitType.VERIFIED_STATUS: [UserRole.CUSTOMER, UserRole.DRIVER,
                                               UserRole.RESTAURANT_ADMIN, UserRole.ORGANIZATION_ADMIN],
            contributionBenefitType.EXCLUSIVE_EVENTS: [UserRole.CUSTOMER, UserRole.DRIVER,
                                                UserRole.RESTAURANT_ADMIN],
            contributionBenefitType.CUSTOM_THEME: [UserRole.CUSTOMER, UserRole.DRIVER,
                                            UserRole.RESTAURANT_ADMIN],
            contributionBenefitType.EARLY_ACCESS: [UserRole.CUSTOMER, UserRole.DRIVER,
                                            UserRole.RESTAURANT_ADMIN],
        }

        relevant_roles = role_mapping.get(benefit_type, [])
        return user_role in relevant_roles if relevant_roles else True