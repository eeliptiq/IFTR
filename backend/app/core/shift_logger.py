"""
Shift-based driver activity logging with fresh anonymous IDs per shift.
"""

import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class DriverShiftLogger:
    """Log driver activity with shift-based anonymity"""

    def __init__(self):
        self.active_shifts: Dict[str, str] = {}  # driver_id -> shift_id
        self.shift_logs: Dict[str, dict] = {}  # shift_id -> anonymous data

    def start_shift(self, driver_id: str) -> str:
        """Begin a new shift with fresh anonymous ID"""
        shift_id = self._generate_shift_id()
        self.active_shifts[driver_id] = shift_id

        # Initialize anonymous log
        self.shift_logs[shift_id] = {
            "start_time": datetime.now(timezone.utc).isoformat(),
            "deliveries_completed": 0,
            "volunteer_deliveries": 0,
            "earnings": 0.0,
            "region": "",  # Will be set on first location update
            "vehicle_type": "",
            "community_impact": 0
        }

        return shift_id

    def log_delivery_completion(self, driver_id: str, is_volunteer: bool = False, earnings: float = 0.0):
        """Log delivery completion"""
        shift_id = self.active_shifts.get(driver_id)
        if shift_id:
            self.shift_logs[shift_id]["deliveries_completed"] += 1
            self.shift_logs[shift_id]["earnings"] += earnings
            if is_volunteer:
                self.shift_logs[shift_id]["volunteer_deliveries"] += 1
                self.shift_logs[shift_id]["community_impact"] += 1

    def update_shift_region(self, driver_id: str, zip_prefix: str):
        """Update shift region based on ZIP prefix"""
        shift_id = self.active_shifts.get(driver_id)
        if shift_id:
            self.shift_logs[shift_id]["region"] = zip_prefix

    def end_shift(self, driver_id: str) -> Optional[str]:
        """End shift and return anonymous shift reference"""
        shift_id = self.active_shifts.pop(driver_id, None)
        if shift_id:
            self.shift_logs[shift_id]["end_time"] = datetime.now(timezone.utc).isoformat()

            # Generate a new reference ID that doesn't link to driver
            reference_id = self._generate_reference_id(shift_id)

            return reference_id  # Give to driver for verification claims
        return None

    def get_community_metrics(self, region: str) -> dict:
        """Get positive metrics for the community dashboard"""
        relevant_shifts = [
            s for s in self.shift_logs.values()
            if s.get("region") == region
        ]

        if not relevant_shifts:
            return {"total_deliveries": 0, "volunteer_deliveries": 0, "active_drivers": 0}

        return {
            "total_deliveries": sum(s["deliveries_completed"] for s in relevant_shifts),
            "volunteer_deliveries": sum(s["volunteer_deliveries"] for s in relevant_shifts),
            "active_drivers": len(relevant_shifts),
            "estimated_meals_delivered": sum(s["deliveries_completed"] for s in relevant_shifts) * 3,
        }

    def _generate_shift_id(self) -> str:
        """Generate unique shift ID unlinkable to driver"""
        timestamp = int(datetime.now(timezone.utc).timestamp())
        random_bytes = os.urandom(8)
        return hashlib.sha256(f"{timestamp}:{random_bytes.hex()}").hexdigest()[:16]

    def _generate_reference_id(self, shift_id: str) -> str:
        """Generate a different ID for driver reference"""
        return hashlib.sha256(f"ref:{shift_id}:{os.urandom(4).hex()}").hexdigest()[:12]

# Global instance
shift_logger = DriverShiftLogger()