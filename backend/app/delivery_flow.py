# delivery_flow.py - Refactored version with centralized validation

from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable
from decimal import Decimal
import logging
import re

from models.delivery import Delivery, DeliveryStatus, DeliveryType, DeliveryProof, ProofType
from models.order import Order, OrderStatus
from models.driver import Driver
from models.user import UserRole

logger = logging.getLogger(__name__)


class DeliveryTransitionError(Exception):
    """Raised when delivery state transition is invalid"""
    pass


class DeliveryValidation:
    """Centralized validation methods for delivery operations"""

    @staticmethod
    def validate_driver_id(driver_id: Optional[str]) -> bool:
        """Validate driver ID format"""
        if not driver_id or not isinstance(driver_id, str):
            return False

        driver_id = driver_id.strip()

        # Check it's not empty
        if not driver_id:
            return False

        # Optional: Validate format (starts with "driver_")
        if not driver_id.startswith("driver_"):
            logger.warning(f"Driver ID doesn't follow expected format: {driver_id}")
            # Don't fail here, as IDs might come from external systems
            # But you could enable this for strict validation

        return True

    @staticmethod
    def validate_pickup_time(delivery: Delivery) -> bool:
        """Validate pickup time is reasonable"""
        if not delivery.actual_pickup_time:
            return False

        # Pickup time shouldn't be in the future (with small buffer)
        if delivery.actual_pickup_time > datetime.now(timezone.utc) + timedelta(minutes=5):
            logger.warning(f"Pickup time is in the future: {delivery.actual_pickup_time}")
            return False

        # Pickup time shouldn't be before delivery was created
        if delivery.created_at and delivery.actual_pickup_time < delivery.created_at:
            logger.warning(f"Pickup time is before delivery creation: {delivery.actual_pickup_time}")
            return False

        return True

    @staticmethod
    def validate_delivery_time(delivery: Delivery) -> bool:
        """Validate delivery time is reasonable"""
        if not delivery.actual_delivery_time:
            return False

        # Delivery time shouldn't be in the future
        if delivery.actual_delivery_time > datetime.now(timezone.utc):
            logger.warning(f"Delivery time is in the future: {delivery.actual_delivery_time}")
            return False

        # Delivery must happen after pickup
        if delivery.actual_pickup_time and delivery.actual_delivery_time < delivery.actual_pickup_time:
            logger.warning(f"Delivery time is before pickup time: {delivery.actual_delivery_time}")
            return False

        return True

    @staticmethod
    def validate_proofs(delivery: Delivery, required_proof_types: List[ProofType]) -> bool:
        """Validate delivery has required proofs"""
        if not required_proof_types:
            return True

        existing_proof_types = {proof.proof_type for proof in delivery.proofs}

        # Check if we have at least one of each required proof type
        for proof_type in required_proof_types:
            if proof_type not in existing_proof_types:
                logger.warning(f"Missing required proof type: {proof_type}")
                return False

        # Additional validation for each proof
        for proof in delivery.proofs:
            if not DeliveryValidation.validate_proof_data(proof):
                logger.warning(f"Invalid proof data for proof: {proof.proof_id}")
                return False

        return True

    @staticmethod
    def validate_proof_data(proof: DeliveryProof) -> bool:
        """Validate individual proof data"""
        if not proof.data or not isinstance(proof.data, str):
            return False

        # GPS proof should contain coordinates
        if proof.proof_type == ProofType.GPS:
            # Check if it looks like coordinates (lat,lng)
            if not re.match(r'^-?\d+\.?\d*,-?\d+\.?\d*$', proof.data):
                logger.warning(f"GPS proof doesn't look like coordinates: {proof.data}")
                return False

        # Photo proof should have a URL or base64 data
        if proof.proof_type == ProofType.PHOTO:
            if not (proof.data.startswith('http') or
                    proof.data.startswith('data:image') or
                    len(proof.data) > 100):  # Assuming base64 would be long
                logger.warning(f"Photo proof doesn't look valid: {proof.data[:50]}...")
                return False

        return True


class DeliveryFlowManager:
    """
    Manages delivery state transitions and business logic
    """

    # Valid state transitions
    TRANSITION_RULES = {
        # Before restaurant accepts
        DeliveryStatus.PENDING: [
            DeliveryStatus.CONFIRMED,  # Restaurant accepts
            DeliveryStatus.CANCELLED,  # Customer cancels before acceptance
        ],

        # Restaurant has accepted, preparing food
        DeliveryStatus.CONFIRMED: [
            DeliveryStatus.OFFERED,  # Food ready, offered to drivers
            DeliveryStatus.CANCELLED,  # Restaurant cancels (kitchen issue)
        ],

        # Offered to drivers
        DeliveryStatus.OFFERED: [
            DeliveryStatus.ASSIGNED,  # Driver accepts
            DeliveryStatus.CANCELLED,  # No driver accepts in time
        ],

        # Driver assigned and on the way to restaurant
        DeliveryStatus.ASSIGNED: [
            DeliveryStatus.PICKED_UP,  # Driver has food
            DeliveryStatus.CANCELLED,  # Driver cancels before pickup
        ],

        # Driver has food, heading to customer
        DeliveryStatus.PICKED_UP: [
            DeliveryStatus.IN_TRANSIT,  # Started delivery journey
            DeliveryStatus.FAILED,  # Can't complete (accident, etc.)
        ],

        # Actively delivering
        DeliveryStatus.IN_TRANSIT: [
            DeliveryStatus.ARRIVED,  # At customer location
            DeliveryStatus.FAILED,  # Can't find customer, etc.
        ],

        # At customer location
        DeliveryStatus.ARRIVED: [
            DeliveryStatus.DELIVERED,  # Successfully delivered
            DeliveryStatus.FAILED,  # Customer not available
        ],

        # Terminal states
        DeliveryStatus.DELIVERED: [],
        DeliveryStatus.FAILED: [],
        DeliveryStatus.CANCELLED: [],
    }

    # State-specific validation rules
    STATE_VALIDATIONS: Dict[DeliveryStatus, List[Callable]] = {
        DeliveryStatus.ASSIGNED: [
            lambda d: DeliveryValidation.validate_driver_id(d.driver_id),
        ],
        DeliveryStatus.PICKED_UP: [
            lambda d: DeliveryValidation.validate_driver_id(d.driver_id),
            lambda d: DeliveryValidation.validate_pickup_time(d),
        ],
        DeliveryStatus.DELIVERED: [
            lambda d: DeliveryValidation.validate_driver_id(d.driver_id),
            lambda d: DeliveryValidation.validate_pickup_time(d),
            lambda d: DeliveryValidation.validate_delivery_time(d),
            lambda d: DeliveryValidation.validate_proofs(d, [ProofType.PHOTO, ProofType.GPS]),
        ],
    }

    @staticmethod
    def validate_transition(
            current_status: DeliveryStatus,
            new_status: DeliveryStatus,
            delivery: Optional[Delivery] = None
    ) -> bool:
        """Validate if state transition is allowed with all business rules"""

        # 1. Check if transition is allowed
        allowed_transitions = DeliveryFlowManager.TRANSITION_RULES.get(current_status, [])

        if new_status not in allowed_transitions:
            raise DeliveryTransitionError(
                f"Cannot transition from {current_status} to {new_status}. "
                f"Allowed: {allowed_transitions}"
            )

        # 2. If we have a delivery object, run state-specific validations
        if delivery:
            DeliveryFlowManager._validate_delivery_state(delivery, new_status)

        return True

    @staticmethod
    def _validate_delivery_state(delivery: Delivery, new_status: DeliveryStatus):
        """Run all validations for a specific state"""

        validations = DeliveryFlowManager.STATE_VALIDATIONS.get(new_status, [])

        for validation_func in validations:
            try:
                if not validation_func(delivery):
                    raise DeliveryTransitionError(
                        f"Validation failed for state {new_status}"
                    )
            except Exception as e:
                raise DeliveryTransitionError(
                    f"Validation error for state {new_status}: {str(e)}"
                )

        # Additional conditional validations
        if new_status == DeliveryStatus.PICKED_UP:
            # Auto-set pickup time if not set
            if not delivery.actual_pickup_time:
                delivery.actual_pickup_time = datetime.now(timezone.utc)
                logger.info(f"Auto-set pickup time for delivery {delivery.delivery_id}")

            # Ensure driver is assigned
            if not delivery.driver_id:
                raise DeliveryTransitionError("Cannot pick up without assigned driver")

        elif new_status == DeliveryStatus.DELIVERED:
            # Auto-set delivery time if not set
            if not delivery.actual_delivery_time:
                delivery.actual_delivery_time = datetime.now(timezone.utc)
                logger.info(f"Auto-set delivery time for delivery {delivery.delivery_id}")

    @staticmethod
    def transition_delivery(
            delivery: Delivery,
            new_status: DeliveryStatus,
            actor_id: str,
            actor_role: UserRole,
            notes: str = "",
            proof_data: Optional[Dict[str, Any]] = None
    ) -> Delivery:
        """
        Transition delivery to new state with validation
        """
        # Store current status for logging
        previous_status = delivery.status

        # Validate transition
        DeliveryFlowManager.validate_transition(
            current_status=delivery.status,
            new_status=new_status,
            delivery=delivery
        )

        # Check actor permissions
        if not DeliveryFlowManager.check_permissions(
                current_status=delivery.status,
                new_status=new_status,
                actor_role=actor_role,
                delivery=delivery,
                actor_id=actor_id
        ):
            raise DeliveryTransitionError(
                f"User {actor_id} with role {actor_role} not authorized for this transition"
            )

        # Add status update
        delivery.add_status_update(new_status, notes)

        # Handle specific state transitions
        if new_status == DeliveryStatus.ASSIGNED:
            delivery.assigned_at = datetime.now(timezone.utc)
            logger.info(f"Delivery {delivery.delivery_id} assigned to driver {delivery.driver_id}")

        elif new_status == DeliveryStatus.PICKED_UP:
            # Auto-add GPS proof if available
            if proof_data and 'location' in proof_data:
                delivery.add_proof(
                    proof_type=ProofType.GPS,
                    data=proof_data['location'],
                    metadata={"auto_generated": True, "actor_id": actor_id}
                )
                logger.info(f"Auto-added GPS proof for pickup of delivery {delivery.delivery_id}")

        elif new_status == DeliveryStatus.DELIVERED:
            # Log completion
            transit_time = None
            if delivery.actual_pickup_time and delivery.actual_delivery_time:
                transit_time = delivery.actual_delivery_time - delivery.actual_pickup_time
                logger.info(f"Delivery {delivery.delivery_id} completed in {transit_time}")

        logger.info(
            f"Delivery {delivery.delivery_id} transitioned from "
            f"{previous_status} to {new_status} by {actor_id}"
        )

        return delivery

    # Rest of the class remains similar but cleaner...

    @staticmethod
    def check_permissions(
            current_status: DeliveryStatus,
            new_status: DeliveryStatus,
            actor_role: UserRole,
            delivery: Delivery,
            actor_id: str
    ) -> bool:
        """Check if actor has permission for state transition"""

        # Admin can do anything
        if actor_role in [UserRole.ADMIN, UserRole.SUPPORT]:
            return True

        # Driver permissions
        if actor_role == UserRole.DRIVER:
            # Driver can only affect their own deliveries
            if not DeliveryValidation.validate_driver_id(delivery.driver_id):
                return False

            if delivery.driver_id != actor_id:
                return False

            driver_allowed_transitions = [
                DeliveryStatus.OFFERED,  # Can accept offered delivery
                DeliveryStatus.ASSIGNED,  # Can mark as assigned (when accepting)
                DeliveryStatus.PICKED_UP,
                DeliveryStatus.IN_TRANSIT,
                DeliveryStatus.ARRIVED,
                DeliveryStatus.DELIVERED,
                DeliveryStatus.FAILED,
            ]

            return new_status in driver_allowed_transitions

        # Restaurant permissions
        if actor_role == UserRole.RESTAURANT_ADMIN:
            # Restaurants can:
            # 1. Accept orders (PENDING → CONFIRMED/OFFERED)
            # 2. Mark as ready for pickup
            restaurant_allowed = [
                DeliveryStatus.CONFIRMED,  # Accept order
                DeliveryStatus.OFFERED,  # Ready for driver pickup
            ]

            # Check if this restaurant owns any orders in this delivery
            # TODO: Implement restaurant-order ownership check
            return new_status in restaurant_allowed

        # Customer permissions
        if actor_role == UserRole.CUSTOMER:
            # Customer can only cancel BEFORE restaurant accepts
            if new_status == DeliveryStatus.CANCELLED:
                # Allow cancellation only in PENDING state
                # Once restaurant accepts (CONFIRMED/OFFERED), customer must contact support
                return current_status == DeliveryStatus.PENDING

            # Customer can also mark as received (optional feature)
            if new_status == DeliveryStatus.DELIVERED:
                # Allow customer to confirm receipt after driver marks as arrived
                return current_status == DeliveryStatus.ARRIVED

            return False

        return False

    @staticmethod
    def is_on_time(delivery: Delivery, threshold_minutes: int = 15) -> bool:
        """Check if delivery was completed on time"""
        if not delivery.actual_delivery_time or not delivery.delivery_window_end:
            return False

        # Allow some grace period
        grace_period = timedelta(minutes=threshold_minutes)
        return delivery.actual_delivery_time <= delivery.delivery_window_end + grace_period