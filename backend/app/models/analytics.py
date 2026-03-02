from pydantic import BaseModel

# Analytics Models
class DashboardStats(BaseModel):
    total_orders: int = 0
    active_orders: int = 0
    total_revenue: float = 0.0
    meals_donated: int = 0
    active_drivers: int = 0
    active_restaurants: int = 0
    surplus_saved: int = 0