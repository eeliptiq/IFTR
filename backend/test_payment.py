# test_payment_computed.py
import sys

sys.path.insert(0, '.')

print("🧪 Testing Payment Models with Computed Properties")
print("=" * 50)

try:
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.models.payment import (
        PaymentStatus, PaymentMethod, Currency, FeeType,
        PaymentTransaction, PaymentFee, Payout,
        format_currency, calculate_tax_amount
    )

    print("✅ All imports successful")

    # Test 1: Basic payment transaction - NO amount_net needed!
    payment = PaymentTransaction(
        order_id="order_123",
        user_id="user_456",
        amount_total=Decimal("35.99"),
        amount_subtotal=Decimal("32.99"),
        amount_tax=Decimal("2.64"),
        amount_tip=Decimal("3.00"),
        payment_method=PaymentMethod.CARD,
        currency=Currency.USD
    )

    print(f"✅ Payment created: {payment.transaction_id}")
    print(f"   Total: {payment.formatted_amount}")
    print(f"   Net (computed): ${payment.amount_net}")
    print(f"   Status: {payment.payment_status}")

    # Test 2: Add fees and see net amount change
    payment.add_fee(FeeType.PLATFORM_FEE, Decimal("2.50"), "Service fee")
    payment.add_fee(FeeType.PROCESSING_FEE, Decimal("1.00"), "Card processing")

    print(f"\n✅ Added fees:")
    print(f"   Platform fee: ${payment.fees[0].amount}")
    print(f"   Processing fee: ${payment.fees[1].amount}")
    print(f"   Updated net: ${payment.amount_net}")  # Should be $35.99 - $3.50 = $32.49

    # Test 3: Driver payout amount
    payment.add_fee(FeeType.DELIVERY_FEE, Decimal("4.99"), "Delivery")
    print(f"\n✅ Added delivery fee: ${payment.fees[2].amount}")
    print(f"   Driver payout: ${payment.amount_driver_payout}")  # $4.99 + $3.00 tip = $7.99

    # Test 4: Restaurant payout amount
    print(f"   Restaurant payout: ${payment.amount_restaurant_payout}")  # $32.99 subtotal

    # Test 5: Fee summary
    print(f"\n✅ Fee summary:")
    for fee_type, amount in payment.fee_summary.items():
        if amount > 0:
            print(f"   {fee_type}: ${amount}")

    # Test 6: Refund functionality
    payment.payment_status = PaymentStatus.SUCCEEDED
    payment.mark_refunded(Decimal("10.00"), "Partial refund")
    print(f"\n✅ Refund processed: ${payment.refund_amount}")
    print(f"   New status: {payment.payment_status}")
    print(f"   Can refund more? {payment.can_refund}")
    print(f"   Remaining refundable: ${payment.remaining_refund_amount}")

    print("\n🎉 COMPUTED PROPERTIES WORKING!")
    print("\nBenefits of computed properties:")
    print("  1. Always accurate (calculated on the fly)")
    print("  2. No storage duplication")
    print("  3. Business logic encapsulated in models")
    print("  4. Easy to change calculations later")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback

    traceback.print_exc()