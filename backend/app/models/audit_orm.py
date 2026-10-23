"""
Persisted trail of privileged changes.

One row per thing that happened, rather than a log line: a role change or a
verification is a fact about an account or an organization, and it has to still
be there when the process that made it is long gone and the logs have rotated.

Nothing here holds secret material. An actor is recorded by user id (and the
role they held at the time), never by email, password or token - the user row is
the place to look those up, and the trail stays safe to hand to an auditor.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import generate_id
from app.database import Base


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: generate_id("audit")
    )

    # Dotted and stable, e.g. `user.role_changed`, `organization.verified`.
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # Who acted. Null for a command run from the server's shell, which has no
    # signed-in account behind it; `actor_kind` then says so.
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    # The role the actor held when they acted, not the role they ended up with.
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    actor_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user"
    )  # user | cli | system

    from_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    to_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
