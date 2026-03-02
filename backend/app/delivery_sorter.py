# delivery_sorter.py
"""
Sort deliveries from a driver's perspective to help them choose
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal
import math

from models.delivery import Delivery, DeliveryType, DeliveryStatus
from models.driver import Driver, RoutePreferences


class DeliverySorter:
    """
    Sorts available deliveries based on driver preferences and circumstances
    """

    @staticmethod
    def calculate_driver_score(
            delivery: Delivery,
            driver: Driver,
            current_location: Optional[Tuple[float, float]] = None
    ) -> Dict[str, Any]:
        """
        Calculate multiple scores for a delivery from driver's perspective
        Returns: {
            "total_score": 0-100,
            "components": {
                "earnings_score": 0-100,
                "distance_score": 0-100,
                "preference_score": 0-100,
                "urgency_score": 0-100,
                "experience_score": 0-100
            },
            "reasons": List[str]  # Why this score
        }
        """
        components = {}
        reasons = []

        # 1. Earnings potential (30% weight)
        earnings_score = DeliverySorter._calculate_earnings_score(delivery, driver)
        components["earnings_score"] = earnings_score

        if earnings_score > 70:
            reasons.append("Good earning potential")
        elif earnings_score < 30:
            reasons.append("Lower than average pay")

        # 2. Distance from current location (25% weight)
        distance_score = DeliverySorter._calculate_distance_score(
            delivery, driver, current_location
        )
        components["distance_score"] = distance_score

        if distance_score > 70:
            reasons.append("Close to your location")
        elif distance_score < 30 and current_location:
            reasons.append("Far from current location")

        # 3. Match with driver preferences (20% weight)
        preference_score = DeliverySorter._calculate_preference_score(delivery, driver)
        components["preference_score"] = preference_score

        if preference_score > 70:
            reasons.append("Matches your preferences well")
        elif preference_score < 30:
            reasons.append("Doesn't match your preferences")

        # 4. Urgency/time sensitivity (15% weight)
        urgency_score = DeliverySorter._calculate_urgency_score(delivery)
        components["urgency_score"] = urgency_score

        if urgency_score > 70:
            reasons.append("Time-sensitive delivery")

        # 5. Driver experience/suitability (10% weight)
        experience_score = DeliverySorter._calculate_experience_score(delivery, driver)
        components["experience_score"] = experience_score

        if experience_score > 70:
            reasons.append("Good match for your experience")

        # Calculate weighted total score
        weights = {
            "earnings_score": 0.30,
            "distance_score": 0.25,
            "preference_score": 0.20,
            "urgency_score": 0.15,
            "experience_score": 0.10,
        }

        total_score = sum(
            components[key] * weight
            for key, weight in weights.items()
            if key in components
        )

        return {
            "total_score": round(total_score, 1),
            "components": components,
            "reasons": reasons[:3]  # Top 3 reasons
        }

    @staticmethod
    def _calculate_earnings_score(delivery: Delivery, driver: Driver) -> float:
        """Score based on earnings potential"""
        if not delivery.estimated_earnings:
            return 50.0  # Neutral score if earnings unknown

        # Normalize earnings
        # Assuming $5-$30 range for most deliveries
        min_earnings = Decimal("5.00")
        max_earnings = Decimal("30.00")

        if delivery.estimated_earnings < min_earnings:
            normalized = 0.0
        elif delivery.estimated_earnings > max_earnings:
            normalized = 100.0
        else:
            normalized = float(
                (delivery.estimated_earnings - min_earnings) /
                (max_earnings - min_earnings) * 100
            )

        # Adjust based on driver's earning preference
        if hasattr(driver, 'route_preferences'):
            earn_preference = driver.route_preferences.earn_vs_volunteer / 100.0
            # Scale score based on preference (0.5 = neutral)
            normalized = normalized * (0.5 + earn_preference * 0.5)

        return max(0.0, min(100.0, normalized))

    @staticmethod
    def _calculate_distance_score(
            delivery: Delivery,
            driver: Driver,
            current_location: Optional[Tuple[float, float]]
    ) -> float:
        """Score based on distance from driver"""
        if not current_location or not delivery.estimated_distance_km:
            return 50.0  # Neutral if distance unknown

        # Calculate score (closer = higher)
        distance = delivery.estimated_distance_km

        # Drivers generally prefer under 5km
        if distance <= 2:
            return 100.0
        elif distance <= 5:
            return 80.0
        elif distance <= 10:
            return 60.0
        elif distance <= 20:
            return 40.0
        else:
            return 20.0

    @staticmethod
    def _calculate_preference_score(delivery: Delivery, driver: Driver) -> float:
        """Score based on driver's route preferences"""
        if not hasattr(driver, 'route_preferences'):
            return 50.0

        pref = driver.route_preferences
        score = 50.0

        # Check delivery type preference
        if delivery.delivery_type == DeliveryType.SURPLUS:
            # Volunteer-focused drivers prefer surplus
            score += (100 - pref.earn_vs_volunteer) * 0.5
        else:
            # Paid delivery
            score += pref.earn_vs_volunteer * 0.5

        # Check max distance preference
        if delivery.estimated_distance_km and pref.max_distance:
            if delivery.estimated_distance_km <= pref.max_distance:
                score += 20.0
            else:
                score -= 30.0

        # Adventure mode bonus for high-priority deliveries
        if pref.adventure_mode and delivery.priority >= 7:
            score += 15.0

        return max(0.0, min(100.0, score))

    @staticmethod
    def _calculate_urgency_score(delivery: Delivery) -> float:
        """Score based on delivery urgency"""
        # Higher priority = more urgent
        priority_score = delivery.priority * 10.0  # 1-10 → 10-100

        # Time window urgency
        time_bonus = 0.0
        if delivery.delivery_window_start and delivery.delivery_window_end:
            window_hours = (delivery.delivery_window_end - delivery.delivery_window_start).total_seconds() / 3600
            # Shorter window = more urgent
            if window_hours < 1:
                time_bonus = 20.0
            elif window_hours < 2:
                time_bonus = 10.0

        return min(100.0, priority_score + time_bonus)

    @staticmethod
    def _calculate_experience_score(delivery: Delivery, driver: Driver) -> float:
        """Score based on driver's experience with similar deliveries"""
        score = 50.0

        # Experience with delivery type
        if delivery.delivery_type == DeliveryType.SURPLUS:
            if driver.surplus_deliveries > 10:
                score += 30.0
            elif driver.surplus_deliveries > 0:
                score += 15.0

        # Heavy deliveries need more experience
        if delivery.food_weight_kg and delivery.food_weight_kg > 10:
            if driver.total_deliveries > 50:
                score += 20.0
            else:
                score -= 10.0

        # High-priority deliveries for experienced drivers
        if delivery.priority >= 8:
            if driver.total_deliveries > 100:
                score += 15.0
            elif driver.total_deliveries < 20:
                score -= 10.0

        return max(0.0, min(100.0, score))

    @staticmethod
    def sort_deliveries_for_driver(
            deliveries: List[Delivery],
            driver: Driver,
            current_location: Optional[Tuple[float, float]] = None,
            sort_by: str = "total_score"  # or "earnings", "distance", "urgency"
    ) -> List[Dict[str, Any]]:
        """
        Sort deliveries from best to worst for a specific driver
        """
        scored_deliveries = []

        for delivery in deliveries:
            # Skip if not available
            if delivery.status != DeliveryStatus.OFFERED:
                continue

            score_data = DeliverySorter.calculate_driver_score(
                delivery, driver, current_location
            )

            # Get sort key based on preference
            if sort_by == "earnings":
                sort_value = score_data["components"]["earnings_score"]
            elif sort_by == "distance":
                sort_value = score_data["components"]["distance_score"]
            elif sort_by == "urgency":
                sort_value = score_data["components"]["urgency_score"]
            else:  # total_score
                sort_value = score_data["total_score"]

            scored_deliveries.append({
                "delivery": delivery,
                "score_data": score_data,
                "sort_value": sort_value,
            })

        # Sort descending (higher score = better)
        scored_deliveries.sort(key=lambda x: x["sort_value"], reverse=True)

        return scored_deliveries

    @staticmethod
    def get_delivery_summary_for_driver(
            delivery: Delivery,
            driver: Driver,
            include_address: bool = False
    ) -> Dict[str, Any]:
        """
        Create a summary of delivery for driver to view
        Respects privacy by not showing exact address until accepted
        """
        summary = {
            "delivery_id": delivery.delivery_id,
            "delivery_type": delivery.delivery_type,
            "status": delivery.status,
            "priority": delivery.priority,
        }

        # Pickup info (always shown)
        if delivery.primary_pickup:
            summary["pickup_info"] = {
                "business_name": delivery.food_source or "Restaurant",
                "area": delivery.primary_pickup.city or delivery.primary_pickup.zip_code,
                "distance_km": delivery.estimated_distance_km,
            }

        # Dropoff info (privacy-protected)
        if delivery.dropoff:
            if include_address:
                # Driver accepted, show full address
                summary["dropoff_info"] = {
                    "full_address": delivery.dropoff.display_address,
                    "city": delivery.dropoff.city,
                    "zip_code": delivery.dropoff.zip_code,
                    "distance_from_pickup_km": delivery.estimated_distance_km,
                }
            else:
                # Before acceptance, show only proximity info
                summary["dropoff_info"] = {
                    "general_area": delivery.dropoff.city or delivery.dropoff.zip_prefix + "XX",
                    "distance_from_pickup_km": delivery.estimated_distance_km,
                    "direction_from_pickup": DeliverySorter._get_direction_hint(
                        delivery.primary_pickup, delivery.dropoff
                    ) if delivery.primary_pickup else None,
                }

        # Timing info
        if delivery.pickup_window_start and delivery.pickup_window_end:
            summary["pickup_window"] = {
                "start": delivery.pickup_window_start.isoformat(),
                "end": delivery.pickup_window_end.isoformat(),
                "urgency": delivery.priority,
            }

        # Earnings (if available)
        if delivery.estimated_earnings:
            summary["estimated_earnings"] = float(delivery.estimated_earnings)

        # Food info (for surplus)
        if delivery.food_weight_kg:
            summary["food_info"] = {
                "weight_kg": delivery.food_weight_kg,
                "category": delivery.food_category,
            }

        return summary

    @staticmethod
    def _get_direction_hint(pickup, dropoff) -> Optional[str]:
        """Get approximate direction without revealing exact location"""
        # This would require decrypted coordinates
        # For now, return a placeholder or implement with hashed coordinates
        return "northeast"  # Placeholder