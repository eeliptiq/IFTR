"""Response model for the admin audit trail.

An event names its actor by user id and by the role they held at the time - not
by email or token. The admin screen can join the id to a user if it needs a
face; the trail itself carries no contact details, so it stays safe to export.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas._time import as_utc


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    action: str
    subject_type: str
    subject_id: str
    actor_id: Optional[str] = None
    actor_role: str = ""
    # user | cli | system
    actor_kind: str = "user"
    from_value: Optional[str] = None
    to_value: Optional[str] = None
    detail: str = ""
    created_at: Optional[datetime] = None

    @classmethod
    def from_record(cls, record) -> "AuditEventResponse":
        return cls(
            event_id=record.event_id,
            action=record.action,
            subject_type=record.subject_type,
            subject_id=record.subject_id,
            actor_id=record.actor_id,
            actor_role=record.actor_role or "",
            actor_kind=record.actor_kind or "user",
            from_value=record.from_value,
            to_value=record.to_value,
            detail=record.detail or "",
            created_at=as_utc(record.created_at),
        )
