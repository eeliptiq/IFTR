import sys
sys.path.insert(0, '.')

print("=== Testing Delivery Model ===")

try:
    from app.models.delivery import Delivery, DeliveryCreate, DeliveryStatus, DeliveryType
    from app.models.encrypted_models import EncryptedAddress
    
    print("✅ All imports work")
    
    # Test creating a delivery
    pickup = EncryptedAddress(
        tier="organization",
        address_line="123 Main St",
        city="Seattle",
        zip_code="98101"
    )
    
    dropoff = EncryptedAddress(
        tier="customer_home", 
        city="Seattle",
        zip_code="98102"
    )
    
    delivery = Delivery(
        pickups=[pickup],
        dropoff=dropoff,
        delivery_type=DeliveryType.SURPLUS,
        priority=2,
        food_weight_kg=5.5,
        food_category="produce"
    )
    
    print(f"✅ Delivery created: {delivery.delivery_id}")
    print(f"   Status: {delivery.status}")
    print(f"   Type: {delivery.delivery_type}")
    print(f"   Active: {delivery.is_active}")
    
    # Test status update
    delivery.add_status_update(DeliveryStatus.ASSIGNED, "Driver accepted")
    print(f"✅ Status updated: {delivery.status}")
    print(f"   History entries: {len(delivery.status_history)}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
