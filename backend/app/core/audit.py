"""
Phase 2: Privacy-preserving audit logging for sensitive data access.

Two trails live here, for two different questions:

  * `PrivacyAuditLogger` answers "was sensitive data looked at?" with tiered log
    lines, so a suspicious pattern can be spotted without storing who looked.
  * `record_event` / `change_role` answer "who changed this, and from what?"
    with rows in `audit_events`. A role, an account's activity or a verification
    is durable state, so its history has to outlive log rotation and be
    queryable by subject.
"""

import os
import hashlib
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_orm import AuditEventRecord
from app.models.user_orm import UserRecord

logger = logging.getLogger(__name__)


class AccessLevel(Enum):
    ADMIN = "admin"
    SUPPORT = "support"
    SYSTEM = "system"
    DRIVER_SELF = "driver_self"
    CUSTOMER = "customer"


class PrivacyAuditLogger:
    """
    Tiered audit logging:
    - Level 1: Anonymous pattern detection (always on)
    - Level 2: Identifiable logs for security incidents (triggered)
    - Level 3: Full traceability for investigations (admin-enabled)
    """

    def __init__(self):
        self.investigation_mode = False
        self.security_incident = False

    def log_access(self, user_id: str, resource_type: str, fields: list[str], reason: str):
        """Main logging entry point with privacy tiers"""

        # Always log anonymous patterns
        anonymous_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resource_type": resource_type,
            "fields_accessed": fields,
            "reason": reason,
            "access_pattern": self._hash_pattern(user_id, resource_type),
            "tier": "anonymous"
        }
        logger.info(f"AUDIT_ANON: {anonymous_entry}")

        # Level 2: Log identifiable info if suspicious
        suspicious = self._is_suspicious(fields, reason)
        if suspicious or self.security_incident:
            identifiable_entry = anonymous_entry.copy()
            identifiable_entry.update({
                "user_id_hash": self._one_way_hash(user_id),
                "tier": "identifiable"
            })
            logger.warning(f"AUDIT_IDENT: {identifiable_entry}")

        # Level 3: Full traceability for investigations
        if self.investigation_mode:
            full_entry = anonymous_entry.copy()
            full_entry.update({
                "user_id": user_id,
                "tier": "full_trace"
            })
            self._store_secure_log(full_entry)

    def _hash_pattern(self, user_id: str, resource_type: str) -> str:
        """Create reversible hash for pattern analysis"""
        day_salt = datetime.utcnow().strftime("%Y-%m-%d")
        pattern = f"{user_id}:{resource_type}:{day_salt}"
        return hashlib.sha256(pattern.encode()).hexdigest()[:16]

    def _one_way_hash(self, user_id: str) -> str:
        """One-way hash for semi-anonymous tracking"""
        salt = os.getenv("AUDIT_HASH_SALT", "audit_salt")
        return hashlib.sha256(f"{user_id}:{salt}".encode()).hexdigest()[:24]

    def _is_suspicious(self, fields: list[str], reason: str) -> bool:
        """Detect potentially suspicious access patterns"""
        sensitive_fields = {"license_number", "home_address", "coordinates"}
        suspicious_reasons = {"manual_override", "bulk_export", "debug"}

        if set(fields) & sensitive_fields:
            return True
        if reason in suspicious_reasons:
            return True
        return False

    def enable_investigation(self, case_id: str, admin_id: str):
        """Enable full tracing for a specific investigation"""
        self.investigation_mode = True
        logger.critical(f"INVESTIGATION_START: case={case_id}, admin={admin_id}")

    def disable_investigation(self, case_id: str):
        """Disable investigation mode"""
        self.investigation_mode = False
        logger.critical(f"INVESTIGATION_END: case={case_id}")


# Global instance
audit_logger = PrivacyAuditLogger()


# --------------------------------------------------------------------------
# Persisted trail of privileged changes
# --------------------------------------------------------------------------

ROLE_CHANGED = "user.role_changed"
USER_SUSPENDED = "user.suspended"
USER_REACTIVATED = "user.reactivated"
# A driver's accepted delivery returned to the pool when the driver was
# suspended. Subject is the order or the volunteer run, not the account: the
# question this answers is "what happened to this delivery".
DELIVERY_REASSIGNED = "delivery.reassigned"
ORGANIZATION_VERIFIED = "organization.verified"
ORGANIZATION_UNVERIFIED = "organization.unverified"

# "the caller themself" - the common case for onboarding. A sentinel rather than
# None, because None is a real actor: the server's shell, which has no account.
_SELF = object()


def record_event(
    db: AsyncSession,
    *,
    action: str,
    subject_type: str,
    subject_id: str,
    from_value: Optional[str] = None,
    to_value: Optional[str] = None,
    actor: Optional[UserRecord] = None,
    actor_role: Optional[str] = None,
    actor_kind: str = "user",
    detail: str = "",
) -> AuditEventRecord:
    """Add one audit row to the caller's transaction.

    Written through the request's session on purpose: the change and the record
    of it commit together. A failed request can then leave neither a role change
    with no trail, nor a trail describing a change that never happened.
    """
    if actor_role is None:
        actor_role = getattr(actor, "role", "") or ""

    event = AuditEventRecord(
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        actor_id=actor.user_id if actor is not None else None,
        actor_role=actor_role,
        actor_kind="user" if actor is not None else actor_kind,
        from_value=from_value,
        to_value=to_value,
        detail=detail,
    )
    db.add(event)
    return event


def change_role(
    db: AsyncSession,
    user: UserRecord,
    new_role: str,
    *,
    detail: str = "",
    actor=_SELF,
    actor_role: Optional[str] = None,
    actor_kind: str = "user",
) -> bool:
    """Move an account to `new_role`, recording the transition once.

    Returns whether anything changed. A promotion to the role the account
    already holds is not an event - saying so in the trail would turn a retried
    onboarding tap into history that never happened.

    `actor` defaults to the account itself (onboarding). Pass `actor=None,
    actor_kind="cli"` for a command run from the server's shell.
    """
    previous = user.role or ""
    if previous == new_role:
        return False

    if actor is _SELF:
        actor = user

    if actor_role is None:
        # An account acting on itself held `previous` at that moment. An
        # administrator acting on somebody else holds their own role, which is
        # not the subject's. A command run from the shell holds no role.
        if actor is None:
            actor_role = ""
        elif actor is user:
            actor_role = previous
        else:
            actor_role = actor.role or ""

    record_event(
        db,
        action=ROLE_CHANGED,
        subject_type="user",
        subject_id=user.user_id,
        from_value=previous,
        to_value=new_role,
        actor=actor,
        actor_role=actor_role,
        actor_kind=actor_kind,
        detail=detail,
    )
    user.role = new_role
    return True