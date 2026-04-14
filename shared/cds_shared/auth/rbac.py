"""
Role-Based Access Control engine.
Permission format: "resource:action:scope"
  resource: kpi, user, role, audit, dataset, threshold, report, alert, recommendation, system, governance, dashboard, ingestion, processing
  action:   read, create, update, delete, configure, manage, view, generate, approve, status
  scope:    own_dept (user's department only), all (unrestricted), system (infrastructure only)
"""
from typing import Dict, List, Optional

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    # Full access — city-level administrators
    "city_admin": ["*"],

    # Department administrators — full control over their department
    "dept_admin": [
        "kpi:read:own_dept",
        "kpi:configure:own_dept",
        "user:read:own_dept",
        "user:create:own_dept",
        "user:update:own_dept",
        "user:deactivate:own_dept",
        "threshold:read:own_dept",
        "threshold:configure:own_dept",
        "report:read:own_dept",
        "report:generate:own_dept",
        "alert:read:own_dept",
        "alert:configure:own_dept",
        "recommendation:read:own_dept",
        "recommendation:approve:own_dept",
        "dataset:read:own_dept",
        "dataset:register:own_dept",
        "governance:read:own_dept",
        "dashboard:view:own_dept",
    ],

    # Department analysts — read and analyse
    "dept_analyst": [
        "kpi:read:own_dept",
        "report:read:own_dept",
        "alert:read:own_dept",
        "recommendation:read:own_dept",
        "dataset:read:own_dept",
        "dashboard:view:own_dept",
    ],

    # Department viewers — read-only dashboard access
    "dept_viewer": [
        "kpi:read:own_dept",
        "dashboard:view:own_dept",
        "alert:read:own_dept",
    ],

    # Auditors — read all audit logs; no data access
    "auditor": [
        "audit:read:all",
        "user:read:all",
        "governance:read:all",
    ],

    # AI reviewers — review and approve AI recommendations
    "ai_reviewer": [
        "recommendation:read:own_dept",
        "recommendation:approve:own_dept",
        "kpi:read:own_dept",
    ],

    # System operators — infrastructure visibility only
    "system_operator": [
        "system:health:read",
        "system:metrics:read",
        "ingestion:status:read",
        "processing:status:read",
    ],
}


class RBACEngine:
    """Evaluates role-based permissions without external dependencies."""

    def has_permission(
        self,
        role: str,
        permission: str,
        context: Optional[Dict] = None,
    ) -> bool:
        """
        Returns True if the given role has the given permission.
        Wildcard "*" (city_admin) grants everything.
        Component-level wildcards supported: "kpi:*:own_dept" matches "kpi:read:own_dept".
        """
        role_perms = ROLE_PERMISSIONS.get(role, [])

        if "*" in role_perms:
            return True

        if permission in role_perms:
            return True

        # Component-level wildcard matching
        perm_parts = permission.split(":")
        for granted in role_perms:
            granted_parts = granted.split(":")
            if len(granted_parts) != len(perm_parts):
                continue
            if all(gp == "*" or gp == pp for gp, pp in zip(granted_parts, perm_parts)):
                return True

        return False

    def get_permissions(self, role: str) -> List[str]:
        return ROLE_PERMISSIONS.get(role, [])

    def get_all_roles(self) -> List[str]:
        return list(ROLE_PERMISSIONS.keys())
