"""
IFTR Models Package
"""

# Import key models for easier access
from app.models.general import (
    IFTRBaseModel, OrderStatus, FoodType, VehicleType,
    DeliveryInstructionType, CalendarPreference, AddressTier
)

from app.models.user import (
    CalendarPreference as UserCalendarPreference, ThemePreference,
    UserBase, UserCreate, UserResponse, UserDB,
    UserSession, UserUpdate, create_user_response,
    mask_email, mask_phone
)

from app.models.payment import (
    PaymentStatus, PaymentMethod, Currency, FeeType,
    PaymentTransaction, Payout, PaymentIntentCreate,
    PaymentIntentResponse, RefundRequest, calculate_tax_amount,
    format_currency
)

# Note: Other models can be imported directly as needed
# from app.models.order import Order, OrderItem, OrderCreateRequest
# from app.models.delivery import Delivery, DeliveryStatus, DeliveryProof
# etc.
