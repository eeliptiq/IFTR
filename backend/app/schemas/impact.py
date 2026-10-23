"""The community impact page's read model.

One flat shape: the page shows every figure at once, so there is no reason to
nest them. `delivered_value` is documented in app/api/impact.py as the value of
delivered orders rather than settled revenue, because nothing settles payments
yet.
"""

from pydantic import BaseModel


class ImpactStatsResponse(BaseModel):
    total_orders: int = 0
    active_orders: int = 0
    delivered_orders: int = 0
    delivered_value: float = 0.0
    meals_delivered: int = 0
    meals_donated: int = 0
    active_restaurants: int = 0
    active_drivers: int = 0
    organizations_helped: int = 0
    surplus_saved: int = 0
