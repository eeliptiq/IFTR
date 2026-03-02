# app/models/payment.py - WITH COMPUTED amount_net
"""
Payment models for IFTR platform.

Supports multiple payment methods, refunds, and financial reporting.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator, computed_field

from .general import IFTRBaseModel, generate_id


# ===== ENUMS =====
class PaymentStatus(str, Enum):
    """Status of a payment transaction"""
    PENDING = "pending"  # Created, not yet processed
    PROCESSING = "processing"  # Being processed by payment gateway
    SUCCEEDED = "succeeded"  # Successfully completed
    FAILED = "failed"  # Failed (insufficient funds, declined, etc.)
    REFUNDED = "refunded"  # Fully refunded
    PARTIALLY_REFUNDED = "partially_refunded"  # Partially refunded
    DISPUTED = "disputed"  # Customer dispute initiated
    CANCELED = "canceled"  # Canceled before completion


class PaymentMethod(str, Enum):
    """Supported payment methods"""
    CARD = "card"  # Credit/debit card
    APPLE_PAY = "apple_pay"  # Apple Pay
    GOOGLE_PAY = "google_pay"  # Google Pay
    PAYPAL = "paypal"  # PayPal
    CASH = "cash"  # Cash on delivery
    CREDIT = "credit"  # Platform credit/balance
    BANK_TRANSFER = "bank_transfer"  # Bank transfer


class Currency(str, Enum):
    """Supported currencies"""
    USD = "usd"  # US Dollar
    CAD = "cad"  # Canadian Dollar
    EUR = "eur"  # Euro
    GBP = "gbp"  # British Pound
    # Add more as needed


class FeeType(str, Enum):
    """Types of fees in the payment"""
    PLATFORM_FEE = "platform_fee"  # IFTR service fee
    PROCESSING_FEE = "processing_fee"  # Payment processor fee
    DELIVERY_FEE = "delivery_fee"  # Driver delivery fee
    TAX = "tax"  # Sales tax
    TIP = "tip"  # Driver tip
    DONATION = "donation"  # Optional charity donation


# ===== MODELS =====
class PaymentFee(IFTRBaseModel):
    """Individual fee component within a payment"""
    fee_type: FeeType
    amount: Decimal = Field(ge=Decimal("0.00"))
    description: str = ""
    tax_inclusive: bool = False  # Whether tax is included in this amount

    @field_validator('amount')
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        """Ensure amount has proper precision"""
        return v.quantize(Decimal('0.01'))  # Round to 2 decimal places


class PaymentCardDetails(IFTRBaseModel):
    """Secure storage of card details (PCI compliant)"""
    model_config = ConfigDict(extra="ignore")

    # Store only what's necessary and PCI compliant
    last4: str = Field(min_length=4, max_length=4)
    brand: str  # "visa", "mastercard", "amex", etc.
    exp_month: int = Field(ge=1, le=12)
    exp_year: int = Field(ge=datetime.now(timezone.utc).year)
    funding: str = "credit"  # "credit", "debit", "prepaid"

    # Never store full PAN, CVV, or track data!

    @property
    def masked_number(self) -> str:
        """Display-safe card number"""
        return f"**** **** **** {self.last4}"

    @property
    def is_expired(self) -> bool:
        """Check if card is expired"""
        now = datetime.now(timezone.utc)
        return (self.exp_year < now.year or
                (self.exp_year == now.year and self.exp_month < now.month))


class PaymentTransaction(IFTRBaseModel):
    """
    Main payment transaction model.
    Tracks all money movements in the system.
    """
    model_config = ConfigDict(extra="ignore")

    # Identifiers
    transaction_id: str = Field(default_factory=lambda: generate_id("txn"))
    external_id: Optional[str] = None  # ID from payment processor (Stripe, etc.)
    order_id: str
    user_id: str
    driver_id: Optional[str] = None  # For driver payouts

    # Amounts (amount_net is now computed - see below)
    amount_total: Decimal = Field(ge=Decimal("0.00"))  # Total charged to customer
    amount_subtotal: Decimal = Field(ge=Decimal("0.00"))  # Before fees/taxes
    amount_tax: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    amount_tip: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    amount_donation: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    # amount_net REMOVED as a field - now computed property

    # Fee breakdown
    fees: List[PaymentFee] = Field(default_factory=list)

    # Payment details
    currency: Currency = Currency.USD
    payment_method: PaymentMethod
    payment_status: PaymentStatus = PaymentStatus.PENDING
    card_details: Optional[PaymentCardDetails] = None  # Only for card payments

    # Metadata
    description: str = ""
    statement_descriptor: Optional[str] = Field(None, max_length=22)  # Appears on statements
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Processor data
    stripe_session_id: Optional[str] = None
    stripe_payment_intent_id: Optional[str] = None
    processor_response: Optional[Dict[str, Any]] = None  # Raw response from processor

    # Timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None

    # Refund information
    refund_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    refund_reason: Optional[str] = None
    refund_external_id: Optional[str] = None

    # Fraud/security
    risk_score: Optional[float] = Field(None, ge=0.0, le=1.0)  # 0=low risk, 1=high risk
    flagged_for_review: bool = False

    # ===== VALIDATORS =====
    @field_validator('amount_total')
    @classmethod
    def validate_total_amount(cls, v: Decimal, info) -> Decimal:
        """Validate total amount matches sum of components"""
        if 'amount_subtotal' in info.data:
            subtotal = info.data['amount_subtotal']
            tax = info.data.get('amount_tax', Decimal('0.00'))
            tip = info.data.get('amount_tip', Decimal('0.00'))
            donation = info.data.get('amount_donation', Decimal('0.00'))

            calculated = subtotal + tax + tip + donation
            if abs(v - calculated) > Decimal('0.01'):  # Allow small rounding differences
                raise ValueError(f"Total amount {v} doesn't match sum of components {calculated}")

        return v.quantize(Decimal('0.01'))

    @field_validator('refund_amount')
    @classmethod
    def validate_refund_amount(cls, v: Decimal, info) -> Decimal:
        """Validate refund doesn't exceed original amount"""
        if 'amount_total' in info.data and v > info.data['amount_total']:
            raise ValueError(f"Refund amount {v} exceeds original amount {info.data['amount_total']}")
        return v

    # ===== COMPUTED FIELDS =====
    @computed_field
    @property
    def amount_net(self) -> Decimal:
        """
        Net amount after platform and processing fees.
        This is what the restaurant/driver actually receives.

        Calculation: total - platform_fee - processing_fee
        (Tax, tip, donation, and delivery fees are not subtracted)
        """
        # Sum platform and processing fees
        deductible_fees = Decimal('0.00')
        for fee in self.fees:
            if fee.fee_type in [FeeType.PLATFORM_FEE, FeeType.PROCESSING_FEE]:
                deductible_fees += fee.amount

        net = self.amount_total - deductible_fees

        # Ensure net is not negative (though fees shouldn't exceed total)
        return max(net, Decimal('0.00')).quantize(Decimal('0.01'))

    @computed_field
    @property
    def amount_driver_payout(self) -> Decimal:
        """
        Amount that goes to the driver.
        Includes: delivery fee + tip (if any)
        """
        driver_amount = Decimal('0.00')

        # Add delivery fees
        for fee in self.fees:
            if fee.fee_type == FeeType.DELIVERY_FEE:
                driver_amount += fee.amount

        # Add tip
        driver_amount += self.amount_tip

        return driver_amount.quantize(Decimal('0.01'))

    @computed_field
    @property
    def amount_restaurant_payout(self) -> Decimal:
        """
        Amount that goes to the restaurant.
        Subtotal minus any restaurant-specific fees.
        """
        # Start with subtotal
        restaurant_amount = self.amount_subtotal

        # Subtract any restaurant commission/fees
        # (You might add restaurant-specific fees later)

        return restaurant_amount.quantize(Decimal('0.01'))

    @computed_field
    @property
    def fee_summary(self) -> Dict[str, Decimal]:
        """Summary of all fees by type"""
        summary = {fee_type.value: Decimal('0.00') for fee_type in FeeType}

        for fee in self.fees:
            summary[fee.fee_type.value] = summary.get(fee.fee_type.value, Decimal('0.00')) + fee.amount

        # Add tax, tip, donation from main fields
        summary[FeeType.TAX.value] = self.amount_tax
        summary[FeeType.TIP.value] = self.amount_tip
        summary[FeeType.DONATION.value] = self.amount_donation

        return summary

    # ===== PROPERTIES =====
    @property
    def is_successful(self) -> bool:
        """Check if payment was successful"""
        return self.payment_status in [PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED,
                                       PaymentStatus.PARTIALLY_REFUNDED]

    @property
    def is_refunded(self) -> bool:
        """Check if payment was refunded (fully or partially)"""
        return self.payment_status in [PaymentStatus.REFUNDED, PaymentStatus.PARTIALLY_REFUNDED]

    @property
    def can_refund(self) -> bool:
        """Check if payment can be refunded"""
        return (self.is_successful and
                not self.is_refunded and
                self.refund_amount < self.amount_total)

    @property
    def remaining_refund_amount(self) -> Decimal:
        """Amount available for refund"""
        if not self.is_successful:
            return Decimal('0.00')
        return self.amount_total - self.refund_amount

    @property
    def formatted_amount(self) -> str:
        """Formatted amount with currency symbol"""
        symbols = {
            Currency.USD: '$',
            Currency.CAD: 'CA$',
            Currency.EUR: '€',
            Currency.GBP: '£'
        }
        symbol = symbols.get(self.currency, self.currency.value.upper())
        return f"{symbol}{self.amount_total:.2f}"

    # ===== METHODS =====
    def add_fee(self, fee_type: FeeType, amount: Decimal, description: str = ""):
        """Add a fee to the payment"""
        fee = PaymentFee(
            fee_type=fee_type,
            amount=amount,
            description=description
        )
        self.fees.append(fee)
        self.updated_at = datetime.now(timezone.utc)

    def mark_refunded(self, amount: Decimal, reason: str = "", external_id: Optional[str] = None):
        """Mark payment as refunded"""
        if amount > self.remaining_refund_amount:
            raise ValueError(f"Cannot refund {amount}, only {self.remaining_refund_amount} available")

        self.refund_amount += amount
        self.refund_reason = reason
        self.refund_external_id = external_id
        self.refunded_at = datetime.now(timezone.utc)

        if self.refund_amount == self.amount_total:
            self.payment_status = PaymentStatus.REFUNDED
        elif self.refund_amount > Decimal('0.00'):
            self.payment_status = PaymentStatus.PARTIALLY_REFUNDED

        self.updated_at = datetime.now(timezone.utc)

class Payout(IFTRBaseModel):
    """Driver/restaurant payout from platform earnings"""
    model_config = ConfigDict(extra="ignore")

    payout_id: str = Field(default_factory=lambda: generate_id("payout"))
    recipient_id: str  # driver_id or restaurant_id
    recipient_type: str  # "driver" or "restaurant"

    amount: Decimal = Field(ge=Decimal("0.01"))
    currency: Currency = Currency.USD
    status: PaymentStatus = PaymentStatus.PENDING

    # What this payout covers
    transaction_ids: List[str] = Field(default_factory=list)  # Payments being paid out
    period_start: datetime
    period_end: datetime

    # Payout method
    payout_method: str  # "bank_transfer", "paypal", "cash"
    destination_details: Dict[str, Any] = Field(default_factory=dict)

    # Timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: Optional[datetime] = None
    estimated_arrival: Optional[datetime] = None

    # Metadata
    description: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ===== REQUEST/RESPONSE MODELS =====
class PaymentIntentCreate(IFTRBaseModel):
    """Request to create a payment intent"""
    order_id: str
    amount_total: Decimal = Field(ge=Decimal("0.01"))
    currency: Currency = Currency.USD
    payment_method: PaymentMethod = PaymentMethod.CARD
    save_payment_method: bool = False  # For future payments
    tip_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    donation_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))


class PaymentIntentResponse(IFTRBaseModel):
    """Response after creating payment intent"""
    client_secret: Optional[str] = None  # For Stripe/etc.
    payment_intent_id: str
    amount_total: Decimal
    currency: Currency
    requires_action: bool = False  # For 3D Secure
    next_action: Optional[Dict[str, Any]] = None


class RefundRequest(IFTRBaseModel):
    """Request to refund a payment"""
    transaction_id: str
    amount: Optional[Decimal] = None  # None = full refund
    reason: str = ""

# ===== HELPER FUNCTIONS =====
def calculate_tax_amount(subtotal: Decimal, tax_rate: Decimal = Decimal("0.08")) -> Decimal:
    """Calculate tax amount with proper rounding"""
    tax = subtotal * tax_rate
    return tax.quantize(Decimal('0.01'))

def format_currency(amount: Decimal, currency: Currency) -> str:
    """Format amount with currency symbol"""
    symbols = {
        Currency.USD: '$',
        Currency.CAD: 'CA$',
        Currency.EUR: '€',
        Currency.GBP: '£'
    }
    symbol = symbols.get(currency, currency.value.upper())
    return f"{symbol}{amount:.2f}"

