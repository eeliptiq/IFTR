"""
What a checkout costs, worked out in one place.

Two callers need these numbers - the checkout screen quotes them before the
order exists, and the create endpoint charges them - and the screen mirrors them
in JavaScript (frontend/src/pages/RestaurantDetail.js). Where the two disagree,
what is charged is what this module says: the client's arithmetic is a preview,
never the bill.

Nothing here reads the database or the request, so the rules can be exercised
without either.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

# Under this subtotal the courier is paid a flat fee; above it the restaurant's
# order is worth carrying for free.
FREE_DELIVERY_THRESHOLD = 30.0
BASE_DELIVERY_FEE = 2.99

# The three speeds the checkout dialog offers. Priority is priced up because it
# is the one that cannot be batched with anything else.
DEFAULT_SPEED = "standard"
SPEED_FEE_MULTIPLIER: Dict[str, float] = {
    "priority": 1.5,
    "standard": 1.0,
    "economy": 0.5,
}

# What the kitchen would charge for a line the menu no longer lists, so the code
# cannot quietly price an unknown item from the client's number.
class UnknownMenuItem(Exception):
    """Raised when a cart line names an item the menu does not have."""


class ItemUnavailable(Exception):
    """Raised when a cart line names an item the restaurant has switched off."""


@dataclass(frozen=True)
class Quote:
    """A priced order: the lines to store, and the money to charge for them."""

    lines: List[dict]
    subtotal: float
    delivery_fee: float
    tip_amount: float
    total_amount: float


def quote(
    menu: Iterable[dict],
    cart: Iterable[Tuple[str, int]],
    speed: str = DEFAULT_SPEED,
    tip_amount: float = 0.0,
) -> Quote:
    """
    Price a cart against the menu.

    `cart` is (item_id, quantity) pairs; `menu` is the restaurant's stored menu,
    the same list the menu screen writes. Prices, names and the drink flags all
    come from the menu, so a doctored request can change what is ordered but not
    what it costs.

    Tax is deliberately absent: nothing charges it yet, and a rate invented here
    would be a number on an invoice nobody agreed to.
    """
    by_id = {
        item.get("item_id"): item
        for item in menu or []
        if isinstance(item, dict) and item.get("item_id")
    }

    lines: List[dict] = []
    subtotal = 0.0
    for item_id, quantity in cart:
        item = by_id.get(item_id)
        if item is None:
            raise UnknownMenuItem(item_id)
        if item.get("is_available", True) is False:
            raise ItemUnavailable(item.get("name") or item_id)

        price = float(item.get("price") or 0.0)
        subtotal += price * quantity

        lines.append(
            {
                "item_id": item_id,
                "name": item.get("name") or "",
                "quantity": quantity,
                # Stored as base_price; the customer's view renames it to the
                # `price` the tracking screen reads (see schemas/order.py).
                "base_price": price,
                # Carried over from the menu so the courier's planning works on
                # a real order: until checkout existed, nothing could set these.
                "is_drink": bool(item.get("is_drink")),
                "is_sealed": bool(item.get("is_sealed")),
                "is_surplus": bool(item.get("is_surplus")),
            }
        )

    subtotal = round(subtotal, 2)
    base_fee = BASE_DELIVERY_FEE if subtotal < FREE_DELIVERY_THRESHOLD else 0.0
    multiplier = SPEED_FEE_MULTIPLIER.get(speed, SPEED_FEE_MULTIPLIER[DEFAULT_SPEED])
    delivery_fee = round(base_fee * multiplier, 2)
    tip = round(max(0.0, tip_amount), 2)

    return Quote(
        lines=lines,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tip_amount=tip,
        total_amount=round(subtotal + delivery_fee + tip, 2),
    )
