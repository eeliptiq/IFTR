# frontend_privacy_views.py
"""
Frontend views that respect location privacy
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from models.delivery import Delivery, DeliveryStatus
from models.order import OrderResponse
from models.driver import Driver
from models.general import IFTRBaseModel


class PrivacyRespectingDeliveryView(IFTRBaseModel):
    """Customer view of delivery without live tracking"""
    delivery_id: str
    status: str

    # Driver info (limited)
    driver_name: Optional[str] = None
    driver_rating: Optional[float] = None
    driver_vehicle: Optional[str] = None

    # Location info (protected)
    pickup_area: str  # Just city/neighborhood
    dropoff_area: str  # Just city/neighborhood

    # Timing info
    estimated_prep_time: Optional[int] = None  # minutes
    estimated_delivery_time: Optional[datetime] = None
    actual_delivery_time: Optional[datetime] = None

    # Progress info (without exact locations)
    current_step: str  # "searching", "preparing", "picking_up", "on_the_way", "arriving"
    progress_percentage: int = 0

    # Communication
    last_driver_message: Optional[str] = None
    last_driver_message_time: Optional[datetime] = None

    # Estimated times at each stage
    stage_estimates: Dict[str, Optional[datetime]] = {}

    @classmethod
    def from_delivery(
            cls,
            delivery: Delivery,
            order: Optional[OrderResponse] = None,
            driver: Optional[Driver] = None,
            messages: List[Dict] = []
    ) -> "PrivacyRespectingDeliveryView":
        """Create privacy-respecting view"""

        # Map to customer-friendly status
        status_map = {
            DeliveryStatus.PENDING: "searching_for_driver",
            DeliveryStatus.CONFIRMED: "restaurant_preparing",
            DeliveryStatus.OFFERED: "ready_for_pickup",
            DeliveryStatus.ASSIGNED: "driver_on_the_way_to_restaurant",
            DeliveryStatus.PICKED_UP: "driver_picked_up",
            DeliveryStatus.IN_TRANSIT: "on_the_way_to_you",
            DeliveryStatus.ARRIVED: "arrived_at_location",
            DeliveryStatus.DELIVERED: "delivered",
            DeliveryStatus.CANCELLED: "cancelled",
            DeliveryStatus.FAILED: "delivery_failed",
        }

        # Calculate progress percentage
        progress_map = {
            DeliveryStatus.PENDING: 10,
            DeliveryStatus.CONFIRMED: 25,
            DeliveryStatus.OFFERED: 40,
            DeliveryStatus.ASSIGNED: 55,
            DeliveryStatus.PICKED_UP: 70,
            DeliveryStatus.IN_TRANSIT: 85,
            DeliveryStatus.ARRIVED: 95,
            DeliveryStatus.DELIVERED: 100,
        }

        current_status = status_map.get(delivery.status, "unknown")
        progress = progress_map.get(delivery.status, 0)

        # Get areas (not exact addresses)
        pickup_area = cls._get_area_string(delivery.primary_pickup) if delivery.primary_pickup else "Pickup location"
        dropoff_area = cls._get_area_string(delivery.dropoff) if delivery.dropoff else "Delivery location"

        # Get latest driver message
        last_message = None
        last_message_time = None
        if messages:
            driver_messages = [m for m in messages if m.get("sender_role") == "driver"]
            if driver_messages:
                last_message = driver_messages[-1].get("content")
                last_message_time = driver_messages[-1].get("timestamp")

        # Create stage estimates
        stage_estimates = cls._calculate_stage_estimates(delivery)

        view = cls(
            delivery_id=delivery.delivery_id,
            status=current_status,
            pickup_area=pickup_area,
            dropoff_area=dropoff_area,
            estimated_delivery_time=delivery.delivery_window_end,
            actual_delivery_time=delivery.actual_delivery_time,
            current_step=current_status,
            progress_percentage=progress,
            last_driver_message=last_message,
            last_driver_message_time=last_message_time,
            stage_estimates=stage_estimates,
        )

        # Add limited driver info
        if driver:
            view.driver_name = cls._mask_name("Driver")  # Just "Driver" for privacy
            view.driver_rating = driver.rating
            view.driver_vehicle = driver.vehicle_type.value

        return view

    @staticmethod
    def _get_area_string(location) -> str:
        """Get area string without revealing exact address"""
        if location.city and location.zip_code:
            return f"{location.city}, {location.zip_code[:3]}XX"
        elif location.city:
            return location.city
        elif location.zip_code:
            return f"Area {location.zip_code[:3]}"
        else:
            return "Location protected"

    @staticmethod
    def _mask_name(name: str) -> str:
        """Always return 'Driver' for privacy"""
        return "Driver"

    @staticmethod
    def _calculate_stage_estimates(delivery: Delivery) -> Dict[str, Optional[datetime]]:
        """Calculate estimated times for each stage"""
        estimates = {}

        # Base estimates on created time
        base_time = delivery.created_at

        # Restaurant prep time (if known)
        if delivery.ready_by:
            estimates["ready_for_pickup"] = delivery.ready_by

        # Delivery window
        if delivery.delivery_window_end:
            estimates["estimated_delivery"] = delivery.delivery_window_end

        # If already in transit, provide arrival estimate
        if delivery.status == DeliveryStatus.IN_TRANSIT and delivery.actual_pickup_time:
            if delivery.estimated_duration_min:
                arrival_est = delivery.actual_pickup_time + timedelta(
                    minutes=delivery.estimated_duration_min
                )
                estimates["estimated_arrival"] = arrival_est

        return estimates


class DriverDeliveryCardPrivacy(IFTRBaseModel):
    """Delivery card for drivers with privacy protection"""
    delivery_id: str
    delivery_type: str

    # Pickup info (always shown)
    pickup_business: Optional[str] = None
    pickup_area: str
    pickup_distance_km: Optional[float] = None

    # Dropoff info (protected before acceptance)
    dropoff_area: str  # Just general area
    dropoff_direction: Optional[str] = None  # "north", "southeast", etc.
    total_distance_km: Optional[float] = None

    # Timing
    pickup_window: Optional[str] = None
    delivery_window: Optional[str] = None
    time_until_pickup: Optional[int] = None  # minutes

    # Earnings
    estimated_earnings: Optional[float] = None
    earnings_score: float = 0.0  # 0-100

    # Match scores
    total_score: float = 0.0  # 0-100
    distance_score: float = 0.0
    preference_score: float = 0.0

    # Urgency
    priority: int = 1
    is_urgent: bool = False

    # Food info
    food_weight_kg: Optional[float] = None
    food_category: Optional[str] = None

    # Accept button state
    can_accept: bool = True
    accept_expires_in: Optional[int] = None  # seconds

    @classmethod
    def from_delivery_with_scores(
            cls,
            delivery: Delivery,
            score_data: Dict[str, Any],
            include_dropoff_details: bool = False
    ) -> "DriverDeliveryCardPrivacy":
        """Create privacy-protected card with scores"""

        # Get pickup area
        pickup_area = ""
        if delivery.primary_pickup:
            if delivery.primary_pickup.city:
                pickup_area = delivery.primary_pickup.city
            elif delivery.primary_pickup.zip_code:
                pickup_area = f"Area {delivery.primary_pickup.zip_code[:3]}"

        # Get dropoff area (protected)
        dropoff_area = ""
        dropoff_direction = None
        if delivery.dropoff:
            if include_dropoff_details:
                # Driver accepted, show more info
                if delivery.dropoff.city:
                    dropoff_area = delivery.dropoff.city
                elif delivery.dropoff.zip_code:
                    dropoff_area = f"Area {delivery.dropoff.zip_code[:3]}"
            else:
                # Before acceptance, minimal info
                if delivery.dropoff.zip_code:
                    dropoff_area = f"Area {delivery.dropoff.zip_code[:3]}XX"
                else:
                    dropoff_area = "Delivery location"

            # Calculate approximate direction from pickup
            if delivery.primary_pickup and delivery.dropoff:
                # This would use hashed/encrypted coordinates
                dropoff_direction = cls._estimate_direction(
                    delivery.primary_pickup, delivery.dropoff
                )

        # Format time windows
        pickup_window = None
        if delivery.pickup_window_start and delivery.pickup_window_end:
            start = delivery.pickup_window_start.strftime('%I:%M %p').lstrip('0')
            end = delivery.pickup_window_end.strftime('%I:%M %p').lstrip('0')
            pickup_window = f"{start} - {end}"

        # Calculate time until pickup
        time_until_pickup = None
        if delivery.pickup_window_start:
            now = datetime.now(timezone.utc)
            if delivery.pickup_window_start > now:
                minutes = int((delivery.pickup_window_start - now).total_seconds() / 60)
                time_until_pickup = max(0, minutes)

        # Create card
        card = cls(
            delivery_id=delivery.delivery_id,
            delivery_type=delivery.delivery_type.value,
            pickup_business=delivery.food_source,
            pickup_area=pickup_area,
            pickup_distance_km=delivery.estimated_distance_km,
            dropoff_area=dropoff_area,
            dropoff_direction=dropoff_direction,
            total_distance_km=delivery.estimated_distance_km,
            pickup_window=pickup_window,
            delivery_window=delivery.delivery_window_end.strftime('%I:%M %p').lstrip(
                '0') if delivery.delivery_window_end else None,
            time_until_pickup=time_until_pickup,
            estimated_earnings=float(delivery.estimated_earnings) if delivery.estimated_earnings else None,
            earnings_score=score_data.get("components", {}).get("earnings_score", 0),
            total_score=score_data.get("total_score", 0),
            distance_score=score_data.get("components", {}).get("distance_score", 0),
            preference_score=score_data.get("components", {}).get("preference_score", 0),
            priority=delivery.priority,
            is_urgent=delivery.priority >= 8,
            food_weight_kg=delivery.food_weight_kg,
            food_category=delivery.food_category,
            can_accept=delivery.status == DeliveryStatus.OFFERED,
            accept_expires_in=cls._calculate_expiry(delivery),
        )

        return card

    @staticmethod
    def _estimate_direction(pickup, dropoff) -> Optional[str]:
        """Estimate direction without exact coordinates"""
        # Use hashed or encrypted coordinates to get approximate direction
        # For now, return None or implement with privacy-preserving geohashing
        return None

    @staticmethod
    def _calculate_expiry(delivery: Delivery) -> Optional[int]:
        """Calculate how long until offer expires"""
        if delivery.status != DeliveryStatus.OFFERED:
            return None

        # Offers expire 30 minutes after creation
        expiry_time = delivery.created_at + timedelta(minutes=30)
        now = datetime.now(timezone.utc)

        if expiry_time > now:
            return int((expiry_time - now).total_seconds())

        return 0  # Already expired