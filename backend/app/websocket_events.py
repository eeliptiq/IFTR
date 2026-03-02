# websocket_privacy_events.py
"""
Privacy-focused WebSocket events
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from pydantic import Field
from models.delivery import Delivery, DeliveryStatus
from models.general import IFTRBaseModel


class PrivacyWebSocketEvent(IFTRBaseModel):
    """WebSocket event with privacy protection"""
    event_type: str
    delivery_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Location info (protected)
    driver_proximity: Optional[str] = None  # "near_restaurant", "in_transit", "near_dropoff"
    estimated_minutes_away: Optional[int] = None

    # Status updates
    new_status: Optional[str] = None
    previous_status: Optional[str] = None

    # Messages
    message: Optional[str] = None
    message_type: Optional[str] = None  # "driver_update", "system", "delay_notice"

    @classmethod
    def from_delivery_update(
            cls,
            delivery: Delivery,
            previous_status: DeliveryStatus,
            message: Optional[str] = None
    ) -> "PrivacyWebSocketEvent":
        """Create privacy-protected event from delivery update"""

        # Map to customer-friendly status
        status_map = {
            DeliveryStatus.ASSIGNED: "driver_assigned",
            DeliveryStatus.PICKED_UP: "order_picked_up",
            DeliveryStatus.IN_TRANSIT: "on_the_way",
            DeliveryStatus.ARRIVED: "arrived",
            DeliveryStatus.DELIVERED: "delivered",
        }

        # Calculate proximity hint
        proximity = None
        estimated_minutes = None

        if delivery.status == DeliveryStatus.ASSIGNED:
            proximity = "heading_to_restaurant"
            estimated_minutes = 5  # Default estimate
        elif delivery.status == DeliveryStatus.PICKED_UP:
            proximity = "leaving_restaurant"
        elif delivery.status == DeliveryStatus.IN_TRANSIT:
            proximity = "in_transit"
            if delivery.estimated_duration_min:
                estimated_minutes = delivery.estimated_duration_min
        elif delivery.status == DeliveryStatus.ARRIVED:
            proximity = "arrived_at_location"

        event = cls(
            event_type="delivery_update",
            delivery_id=delivery.delivery_id,
            driver_proximity=proximity,
            estimated_minutes_away=estimated_minutes,
            new_status=status_map.get(delivery.status),
            previous_status=status_map.get(previous_status),
            message=message,
            message_type="system" if not message else "status_update",
        )

        return event

    @classmethod
    def create_driver_message(
            cls,
            delivery_id: str,
            message: str,
            driver_name: str = "Your driver"
    ) -> "PrivacyWebSocketEvent":
        """Create event for driver message"""
        return cls(
            event_type="driver_message",
            delivery_id=delivery_id,
            message=f"{driver_name}: {message}",
            message_type="driver_update",
        )

    @classmethod
    def create_delay_notice(
            cls,
            delivery_id: str,
            delay_minutes: int,
            reason: str = "traffic"
    ) -> "PrivacyWebSocketEvent":
        """Create event for delivery delay"""
        reason_map = {
            "traffic": "Heavy traffic",
            "weather": "Weather conditions",
            "restaurant": "Restaurant delay",
            "other": "Unexpected delay",
        }

        return cls(
            event_type="delay_notice",
            delivery_id=delivery_id,
            message=f"Delivery delayed by {delay_minutes} minutes due to {reason_map.get(reason, 'unexpected circumstances')}",
            message_type="delay_notice",
        )