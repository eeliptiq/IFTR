import numpy as np
from geopy.distance import geodesic
from datetime import datetime, timedelta
import random
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class Location:
    lat: float
    lng: float

    def distance_to(self, other: 'Location') -> float:
        """Calculate distance in kilometers"""
        return geodesic((self.lat, self.lng), (other.lat, other.lng)).km


@dataclass
class Restaurant:
    id: str
    name: str
    location: Location
    cuisine: str
    rating: float
    delivery_radius: float  # km
    menu: Dict[str, float]  # item: price
    prep_time: Tuple[float, float]  # min, max in minutes

    def can_deliver_to(self, location: Location) -> bool:
        return self.location.distance_to(location) <= self.delivery_radius

    def estimated_prep_time(self) -> float:
        """Random prep time within range"""
        return random.uniform(*self.prep_time)


@dataclass
class DeliverySimulator:
    """Simulates delivery logistics and pricing"""

    @staticmethod
    def calculate_delivery_fee(
            distance_km: float,
            order_value: float,
            surge_multiplier: float = 1.0
    ) -> float:
        """Calculate dynamic delivery fee"""
        base_fee = 2.99
        distance_charge = max(0, (distance_km - 3) * 0.5)  # Free first 3km
        small_order_surcharge = max(0, 15 - order_value) * 0.1 if order_value < 15 else 0

        total = (base_fee + distance_charge + small_order_surcharge) * surge_multiplier
        return round(total, 2)

    @staticmethod
    def estimate_delivery_time(
            prep_time: float,
            distance_km: float,
            traffic_factor: float = 1.0
    ) -> float:
        """Estimate total delivery time in minutes"""
        # Average speed: 20 km/h in city traffic
        travel_time = (distance_km / 20) * 60  # Convert to minutes

        # Traffic factor (1.0 = normal, 1.5 = heavy traffic)
        travel_time *= traffic_factor

        # Add buffer for pickup/dropoff
        buffer_time = 5

        total = prep_time + travel_time + buffer_time
        return round(total)

    @staticmethod
    def optimize_delivery_route(
            restaurants: List[Restaurant],
            delivery_locations: List[Location]
    ) -> List[Tuple[int, int]]:
        """Simple traveling salesman problem solver for route optimization"""
        # For now, use nearest neighbor algorithm
        # In production, you'd use OR-Tools or similar

        if not restaurants or not delivery_locations:
            return []

        # Combine all points
        all_points = [r.location for r in restaurants] + delivery_locations

        # Build distance matrix
        n = len(all_points)
        dist_matrix = np.zeros((n, n))

        for i in range(n):
            for j in range(n):
                if i != j:
                    dist_matrix[i][j] = all_points[i].distance_to(all_points[j])

        # Nearest neighbor algorithm
        visited = [False] * n
        route = [0]  # Start at first restaurant
        visited[0] = True

        for _ in range(n - 1):
            last = route[-1]
            # Find nearest unvisited point
            nearest = None
            min_dist = float('inf')

            for i in range(n):
                if not visited[i] and dist_matrix[last][i] < min_dist:
                    min_dist = dist_matrix[last][i]
                    nearest = i

            route.append(nearest)
            visited[nearest] = True

        return route