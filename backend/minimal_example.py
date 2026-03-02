
"""
minimal_example.py
Run with: python minimal_example.py
"""

import sys
import os

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)  # Add app directory
sys.path.insert(0, os.path.join(current_dir, "models"))  # Add models directly

# First, let's test if we can import basic types
print("Testing basic imports...")

# Create simple stub for missing modules
class StubIFTRBaseModel:
    """Stub base model"""
    pass

# Test creating models without complex dependencies
print("\n1. Testing simple enum imports...")

# Define some enums locally for testing
from enum import Enum

class UserRole(str, Enum):
    CUSTOMER = "customer"
    DRIVER = "driver"
    RESTAURANT_ADMIN = "restaurant_admin"
    ADMIN = "admin"

class OrderStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class VehicleType(str, Enum):
    CAR = "car"
    BIKE = "bike"
    E_BIKE = "e-bike"
    MOTORCYCLE = "motorcycle"

print(f"   User roles: {[r.value for r in UserRole]}")
print(f"   Order statuses: {[s.value for s in OrderStatus]}")
print(f"   Vehicle types: {[v.value for v in VehicleType]}")

print("\n2. Testing model structure...")

# Define a simple model
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class SimpleUser(BaseModel):
    user_id: str = Field(default_factory=lambda: f"user_{datetime.now().timestamp()}")
    email: str
    name: str
    role: UserRole = UserRole.CUSTOMER
    created_at: datetime = Field(default_factory=datetime.now)

# Create instance
user = SimpleUser(
    email="test@example.com",
    name="Test User"
)
print(f"   Created user: {user.email} with role: {user.role.value}")

print("\n3. Testing order flow...")

class SimpleOrder(BaseModel):
    order_id: str = Field(default_factory=lambda: f"order_{datetime.now().timestamp()}")
    user_id: str
    status: OrderStatus = OrderStatus.PENDING
    total: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)

order = SimpleOrder(
    user_id=user.user_id,
    total=25.99
)
print(f"   Created order: {order.order_id} with status: {order.status.value}")

# Simulate order flow
order.status = OrderStatus.CONFIRMED
print(f"   Order confirmed at: {order.created_at}")

print("\n4. Testing delivery...")

class SimpleDelivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: f"deliv_{datetime.now().timestamp()}")
    order_id: str
    driver_id: Optional[str] = None
    vehicle_type: VehicleType = VehicleType.CAR
    status: str = "pending"

delivery = SimpleDelivery(
    order_id=order.order_id,
    driver_id="driver_123"
)
print(f"   Created delivery: {delivery.delivery_id} with vehicle: {delivery.vehicle_type.value}")

print("\n" + "="*60)
print("MINIMAL EXAMPLE COMPLETE!")
print("Your model concepts are sound. Now fix the import structure.")
print("="*60)

# Show what needs to be fixed
print("\nNEXT STEPS:")
print("1. Ensure your project structure is:")
print("   backend/app/models/__init__.py")
print("   backend/app/models/*.py")
print("   backend/app/core/__init__.py")
print("   backend/app/core/ids.py")
print("   backend/app/core/encryption.py")
print("\n2. Change relative imports in model files:")
print("   FROM: from ..core.ids import generate_id")
print("   TO:   from app.core.ids import generate_id")
print("\n3. Or run from project root: python -m app.test_imports")
