# health_check.py - Quick daily test
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("🧪 IFTR Health Check")
print("=" * 40)

# Critical path test
try:
    from app.models.order import Order
    from app.models.driver import Driver
    from app.models.delivery import Delivery
    from app.core.encryption import encrypt_data

    print("✅ Critical imports: OK")

    # Quick smoke test
    test = encrypt_data("test")
    print("✅ Encryption: OK")

    from app.models.general import VehicleType

    print(f"✅ Enums: {VehicleType.CAR}")

    print("\n🎉 System Healthy!")

except Exception as e:
    print(f"❌ Health check failed: {e}")
    import traceback

    traceback.print_exc()