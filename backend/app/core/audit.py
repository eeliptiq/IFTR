"""
Phase 2: Privacy-preserving audit logging for sensitive data access.
"""

import os
import hashlib
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

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