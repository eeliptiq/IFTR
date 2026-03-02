"""
MealsMiles - Public Business Logic

This module contains the default business logic for the MealsMiles platform.
It is designed to be a transparent and functional baseline that allows
the application to run out-of-the-box.

**For Independent Developers & Forks:**
You can create your own proprietary logic by creating a 'math_logic_private.py'
file in this same directory. The application will automatically use your
private file if it exists, otherwise it will fall back to this public one.

This allows you to develop and test your own unique algorithms for pricing,
driver eligibility, and optimization without needing to alter the core
application code.
"""

from typing import Tuple, Dict, Any
# The Pydantic models are used for type hinting to ensure data consistency.
from ..models.order import Order
from ..models.driver import Driver
from fastkml import kml

def get_minimum_driver_fee(order_data: Dict[str, Any]) -> float:
    """
    Calculate the minimum fee offered to a driver for a given order.
    This is a basic calculation and can be customized.

    Args:
        order_data: A dictionary representing the order.

    Returns:
        The minimum fee for the driver as a float.
    """
    # Basic flat fee: $5 per delivery.
    # This is a simple starting point. You could develop a more complex
    # model based on distance, estimated time, order value, etc.
    base_fee = 5.00
    
    # Example of a distance-based component (optional, commented out):
    # distance_km = order_data.get("delivery_distance_km", 0)
    # fee_per_km = 0.50  # 50 cents per kilometer
    # distance_fee = distance_km * fee_per_km
    # distance_fee = distance_km * fee_per_km
    
    return base_fee

def calculate_order_costs(order_details: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculate the full breakdown of costs for an order.
    
    Args:
        order_details: A dictionary containing subtotal, tip_amount, etc.
        
    Returns:
        A dictionary with subtotal, tax, restaurant_fee, driver_fee, total, etc.
    """
    subtotal = order_details.get("subtotal", 0.0)
    tip_amount = order_details.get("tip_amount", 0.0)
    
    # Basic tax calculation (e.g., 8%)
    tax_rate = 0.08
    tax = round(subtotal * tax_rate, 2)
    
    # Calculate driver fee
    driver_fee = get_minimum_driver_fee(order_details)
    
    # Restaurant fee (e.g., platform fee charged to restaurant or customer)
    # For now, let's assume a small platform fee charged to customer
    restaurant_fee = 2.00
    
    total = subtotal + tax + driver_fee + restaurant_fee + tip_amount
    
    return {
        "subtotal": subtotal,
        "tax": tax,
        "restaurant_fee": restaurant_fee,
        "driver_fee": driver_fee,
        "total": round(total, 2),
        "estimated_delivery_time": datetime.now(timezone.utc) + timedelta(minutes=45) # Placeholder
    }

def check_driver_eligibility(driver: Driver, order: Order) -> Tuple[bool, str]:
    """
    Check if a driver is eligible to accept a specific order.
    This is a basic check and can be customized.

    Args:
        driver: The Driver object.
        order: The Order object.

    Returns:
        A tuple containing a boolean (True if eligible) and a reason string.
    """
    # Basic eligibility: any available driver is eligible.
    # You could implement more complex rules here, such as:
    # - Vehicle type restrictions (e.g., no bikes for large orders)
    # - Driver rating requirements
    # - Proximity to the restaurant
    
    # Maximum distance placeholder (in kilometers)
    MAX_DELIVERY_DISTANCE_KM = 10.0

    # Check if the order distance exceeds the maximum allowed distance
    if order.distance_km and order.distance_km > MAX_DELIVERY_DISTANCE_KM:
        return (False, f"Order exceeds the maximum delivery distance of {MAX_DELIVERY_DISTANCE_KM} km.")
        
    if driver.is_available:
        return (True, "Driver is available.")
    else:
        return (False, "Driver is not currently available.")
