"""Timestamp serialization shared by the surplus and organization views."""

from datetime import datetime, timezone
from typing import Optional


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Tag a stored timestamp as UTC.

    SQLite hands back naive datetimes even for `DateTime(timezone=True)`, and
    everything this app writes is UTC. Serializing one without an offset would
    make the browser read it as local time, so an expiry four hours away would
    count down from the wrong moment. Attaching UTC on the way out fixes the
    wire format without a migration.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
