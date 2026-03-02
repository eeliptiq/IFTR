# contribution.py
"""
Contribution scoring system for IFTR platform
Rewards users for positive contributions across all roles
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Set
from enum import Enum
from decimal import Decimal
import logging
from pydantic import Field, validator

from app.models.general import IFTRBaseModel, UserRole
from app.core.ids import generate_id

logger = logging.getLogger(__name__)


class contributionActionType(str, Enum):
    """Types of contribution-earning actions"""
    # Delivery Actions
    COMPLETE_DELIVERY = "complete_delivery"
    COMPLETE_SURPLUS_DELIVERY = "complete_surplus_delivery"
    ON_TIME_DELIVERY = "on_time_delivery"
    APPRECIATED_DELIVERY = "APPRECIATED_DELIVERY"
    URGENT_DELIVERY = "urgent_delivery"

    # Customer Actions
    PLACE_ORDER = "place_order"
    LEAVE_REVIEW = "leave_review"
    REFER_USER = "refer_user"
    COMPLETE_PROFILE_CUSTOMER = "complete_profile_customer"

    # Organization Actions
    DONATE_FOOD = "donate_food"
    COMPLETE_PROFILE_ORG = "complete_profile_org"

    # Restaurant Actions
    ACCEPT_ORDER_QUICKLY = "accept_order_quickly"
    PROVIDE_SURPLUS = "provide_surplus"
    COMPLETE_MANY_ORDERS = "complete_many_orders"
    FEW_ISSUES = "few_issues"

    # Community Actions
    HELP_SUPPORT = "help_support"  # Answer questions in forums
    VOLUNTEER_EVENT = "volunteer_event"
    COMMUNITY_MODERATION = "community_moderation"

    # Platform Growth
    INVITE_DRIVER = "invite_driver"
    INVITE_RESTAURANT = "invite_restaurant"
    BUG_REPORT = "bug_report"
    FEATURE_SUGGESTION = "feature_suggestion"


class contributionTier(str, Enum):
    """contribution achievement tiers"""
    NEWCOMER = "newcomer"  # 0-99
    CONTRIBUTOR = "contributor"  # 100-499
    HELPER = "helper"  # 500-999
    CHAMPION = "champion"  # 1000-1999
    HERO = "hero"  # 2000-4999
    LEGEND = "legend"  # 5000+


class contributionScore(IFTRBaseModel):
    """Main contribution score model for a user"""
    user_id: str
    total_contribution: int = 0
    available_contribution: int = 0  # Can be spent on rewards
    lifetime_contribution: int = 0  # Total ever earned (never decreases)

    # Tier information
    current_tier: contributionTier = contributionTier.NEWCOMER
    tier_progress: float = 0.0  # 0-100% to next tier

    # Role-specific contribution (for tracking, not spending)
    driver_contribution: int = 0
    customer_contribution: int = 0
    restaurant_contribution: int = 0
    organization_contribution: int = 0
    community_contribution: int = 0

    # Streaks and metrics
    current_streak: int = 0  # Consecutive days with contribution-earning activity
    longest_streak: int = 0
    last_activity_date: Optional[datetime] = None

    # Recent activity
    recent_actions: List[Dict[str, Any]] = Field(default_factory=list)

    # Benefits unlocked
    unlocked_benefits: Set[str] = Field(default_factory=set)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def next_tier(self) -> Optional[contributionTier]:
        """Get the next tier the user can achieve"""
        tiers = list(contributionTier)
        current_index = tiers.index(self.current_tier)
        if current_index < len(tiers) - 1:
            return tiers[current_index + 1]
        return None

    @property
    def next_tier_threshold(self) -> int:
        """Get contribution needed for next tier"""
        thresholds = {
            contributionTier.NEWCOMER: 100,
            contributionTier.CONTRIBUTOR: 500,
            contributionTier.HELPER: 1000,
            contributionTier.CHAMPION: 2000,
            contributionTier.HERO: 5000,
            contributionTier.LEGEND: 10000,  # Legend has no upper bound
        }
        next_tier = self.next_tier
        return thresholds.get(next_tier, 0) if next_tier else 0

    @property
    def can_spend(self, amount: int) -> bool:
        """Check if user can spend contribution"""
        return self.available_contribution >= amount

    def add_contribution(self, amount: int, action_type: contributionActionType, metadata: Dict[str, Any] = None):
        """Add contribution to user's score"""
        self.total_contribution += amount
        self.available_contribution += amount
        self.lifetime_contribution += amount

        # Update role-specific contribution based on action type
        if "delivery" in action_type.value:
            self.driver_contribution += amount
        elif action_type in [contributionActionType.PLACE_ORDER, contributionActionType.LEAVE_REVIEW, contributionActionType.COMPLETE_PROFILE]:
            self.customer_contribution += amount
        elif action_type in [contributionActionType.DONATE_FOOD]:
            self.organization_contribution += amount
        elif "restaurant" in action_type.value or "surplus" in action_type.value:
            self.restaurant_contribution += amount
        else:
            self.community_contribution += amount

        # Update tier
        self._update_tier()

        # Update streak
        self._update_streak()

        # Record recent action
        self.recent_actions.insert(0, {
            "action_type": action_type.value,
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
            "total_after": self.total_contribution
        })

        # Keep only last 50 actions
        if len(self.recent_actions) > 50:
            self.recent_actions = self.recent_actions[:50]

        self.updated_at = datetime.now(timezone.utc)

        logger.info(f"Added {amount} contribution to user {self.user_id} for {action_type}")

    def spend_contribution(self, amount: int, reason: str) -> bool:
        """Spend available contribution"""
        if not self.can_spend(amount):
            return False

        self.available_contribution -= amount
        self.updated_at = datetime.now(timezone.utc)

        logger.info(f"User {self.user_id} spent {amount} contribution for: {reason}")
        return True

    def _update_tier(self):
        """Update user's contribution tier based on total contribution"""
        thresholds = {
            contributionTier.NEWCOMER: 0,
            contributionTier.CONTRIBUTOR: 100,
            contributionTier.HELPER: 500,
            contributionTier.CHAMPION: 1000,
            contributionTier.HERO: 2000,
            contributionTier.LEGEND: 5000,
        }

        # Find current tier
        new_tier = contributionTier.NEWCOMER
        for tier, threshold in sorted(thresholds.items(), key=lambda x: x[1], reverse=True):
            if self.total_contribution >= threshold:
                new_tier = tier
                break

        # Update if changed
        if new_tier != self.current_tier:
            old_tier = self.current_tier
            self.current_tier = new_tier
            logger.info(f"User {self.user_id} promoted from {old_tier} to {new_tier}")

        # Calculate progress to next tier
        next_threshold = self.next_tier_threshold
        if next_threshold > 0:
            current_threshold = thresholds.get(self.current_tier, 0)
            range_size = next_threshold - current_threshold
            progress = (self.total_contribution - current_threshold) / range_size * 100
            self.tier_progress = min(100.0, max(0.0, progress))
        else:
            self.tier_progress = 100.0

    def _update_streak(self):
        """Update activity streak"""
        today = datetime.now(timezone.utc).date()

        if not self.last_activity_date:
            self.current_streak = 1
        else:
            last_date = self.last_activity_date.date()
            if last_date == today:
                # Already updated today
                return
            elif last_date == today - timedelta(days=1):
                # Consecutive day
                self.current_streak += 1
            else:
                # Streak broken
                self.current_streak = 1

        # Update longest streak
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak

        self.last_activity_date = datetime.now(timezone.utc)


class contributionCalculator:
    """Calculate contribution points for various actions"""

    # Base points for different actions
    ACTION_POINTS = {
        # Delivery Actions
        contributionActionType.COMPLETE_DELIVERY: 10,
        contributionActionType.COMPLETE_SURPLUS_DELIVERY: 25,  # Extra for surplus
        contributionActionType.ON_TIME_DELIVERY: 5,
        contributionActionType.APPRECIATED_DELIVERY: 15,
        contributionActionType.URGENT_DELIVERY: 20,

        # Customer Actions
        contributionActionType.PLACE_ORDER: 5,
        contributionActionType.LEAVE_REVIEW: 3,
        contributionActionType.REFER_USER: 50,  # When referred user completes first order
        contributionActionType.COMPLETE_PROFILE_CUSTOMER: 10,

        # Organization Actions
        contributionActionType.DONATE_FOOD: 30,
        contributionActionType.COMPLETE_PROFILE_ORG: 20,

        # Restaurant Actions
        contributionActionType.ACCEPT_ORDER_QUICKLY: 5,
        contributionActionType.PROVIDE_SURPLUS: 40,  # High reward for surplus food
        contributionActionType.FEW_ISSUES: 20,  # Monthly bonus
        contributionActionType.COMPLETE_MANY_ORDERS: {
            "per_10_orders": 25,
            "per_50_orders": 150,  # Bonus for volume
        },

        # Community Actions
        contributionActionType.HELP_SUPPORT: 15,
        contributionActionType.VOLUNTEER_EVENT: 100,
        contributionActionType.COMMUNITY_MODERATION: 30,

        # Platform Growth
        contributionActionType.INVITE_DRIVER: 75,  # When invited driver completes 5 deliveries
        contributionActionType.INVITE_RESTAURANT: 100,  # When restaurant joins and activates
        contributionActionType.BUG_REPORT: 10,
        contributionActionType.FEATURE_SUGGESTION: 20,
    }

    @classmethod
    def calculate_contribution(
            cls,
            action_type: contributionActionType,
            metadata: Optional[Dict[str, Any]] = None,
            user_role: Optional[UserRole] = None
    ) -> int:
        """Calculate contribution points for an action"""
        base_points = cls.ACTION_POINTS.get(action_type, 0)

        if isinstance(base_points, dict):
            # Handle dynamic point calculations

            if action_type == contributionActionType.COMPLETE_MANY_ORDERS:
                order_count = metadata.get('order_count', 0) if metadata else 0
                if order_count >= 50:
                    return base_points.get("per_50_orders", 0)
                elif order_count >= 10:
                    return base_points.get("per_10_orders", 0)
                return 0

        # Apply role multiplier (optional)
        multiplier = 1.0
        if user_role:
            # Could give extra points for cross-role contributions
            if user_role == UserRole.DRIVER and "surplus" in action_type.value:
                multiplier = 1.5  # Extra for drivers doing surplus

        return int(base_points * multiplier)

    @classmethod
    def calculate_delivery_contribution(
            cls,
            delivery_type: str,
            was_on_time: bool,
            was_urgent: bool = False,
            food_weight_kg: Optional[float] = None
    ) -> Dict[str, int]:
        """Calculate contribution breakdown for a delivery"""
        contribution_breakdown = {}
        total = 0

        # Base delivery contribution
        if delivery_type == "surplus":
            base_points = cls.ACTION_POINTS[contributionActionType.COMPLETE_SURPLUS_DELIVERY]
            contribution_breakdown["surplus_delivery"] = base_points
            total += base_points
        else:
            base_points = cls.ACTION_POINTS[contributionActionType.COMPLETE_DELIVERY]
            contribution_breakdown["regular_delivery"] = base_points
            total += base_points

        # On-time bonus
        if was_on_time:
            on_time_points = cls.ACTION_POINTS[contributionActionType.ON_TIME_DELIVERY]
            contribution_breakdown["on_time"] = on_time_points
            total += on_time_points

        # Urgent delivery bonus
        if was_urgent:
            urgent_points = cls.ACTION_POINTS[contributionActionType.URGENT_DELIVERY]
            contribution_breakdown["urgent"] = urgent_points
            total += urgent_points

        # Heavy delivery bonus (extra for heavy surplus)
        if food_weight_kg and food_weight_kg > 15:
            heavy_bonus = int(food_weight_kg * 0.5)  # 0.5 points per kg over 15kg
            contribution_breakdown["heavy_load"] = heavy_bonus
            total += heavy_bonus

        contribution_breakdown["total"] = total
        return contribution_breakdown