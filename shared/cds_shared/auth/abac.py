"""
Attribute-Based Access Control engine.
Enforces department-level data isolation, clearance levels, and time-based restrictions.
ABAC runs AFTER RBAC — both must pass for access to be granted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import structlog

logger = structlog.get_logger(__name__)

SENSITIVITY_LEVELS: Dict[str, int] = {
    "public": 1,
    "internal": 2,
    "confidential": 3,
    "restricted": 4,
}

# Roles that can read across all departments
CROSS_DEPT_ROLES = frozenset({"city_admin", "auditor", "system_operator"})

BUSINESS_HOURS_START = 8   # UTC
BUSINESS_HOURS_END = 18    # UTC


@dataclass
class ABACContext:
    """All attributes needed to evaluate ABAC policies for one access request."""
    user_id: str
    user_dept_id: str
    user_role: str
    user_clearance_level: int    # 1=public, 2=internal, 3=confidential, 4=restricted
    resource_dept_id: str
    resource_sensitivity: str    # "public" | "internal" | "confidential" | "restricted"
    action: str
    environment: Dict = field(default_factory=dict)  # hour, ip_address, etc.


class ABACEngine:
    """Evaluates attribute-based access control policies."""

    def evaluate(self, context: ABACContext) -> bool:
        """
        Run all policy checks. Returns True only if every check passes.
        Logs denial details — never silent.
        """
        checks = {
            "dept_isolation": self._dept_isolation_check(context),
            "clearance_level": self._clearance_level_check(context),
            "time_restriction": self._time_restriction_check(context),
        }

        if all(checks.values()):
            return True

        failed = [name for name, result in checks.items() if not result]
        logger.info(
            "abac_access_denied",
            user_id=context.user_id,
            user_role=context.user_role,
            user_dept=context.user_dept_id,
            resource_dept=context.resource_dept_id,
            action=context.action,
            failed_checks=failed,
        )
        return False

    def _dept_isolation_check(self, ctx: ABACContext) -> bool:
        """Users can only access their own department's resources unless cross-dept role."""
        if ctx.user_role in CROSS_DEPT_ROLES:
            return True
        return ctx.user_dept_id == ctx.resource_dept_id

    def _clearance_level_check(self, ctx: ABACContext) -> bool:
        """User clearance level must be >= resource sensitivity level."""
        required = SENSITIVITY_LEVELS.get(ctx.resource_sensitivity, 1)
        return ctx.user_clearance_level >= required

    def _time_restriction_check(self, ctx: ABACContext) -> bool:
        """Confidential/restricted data is only accessible during business hours (UTC 8–18)."""
        if ctx.resource_sensitivity not in ("confidential", "restricted"):
            return True
        hour = ctx.environment.get("hour")
        if hour is None:
            return True  # system calls without time context: permissive
        return BUSINESS_HOURS_START <= hour <= BUSINESS_HOURS_END
