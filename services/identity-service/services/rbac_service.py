"""
RBAC service — role assignment, revocation, and permission management.
Permission cache stored in Redis with 60-second TTL.
"""
from __future__ import annotations

import json
from typing import List, Optional
from uuid import UUID

import redis as redis_lib
import structlog
from sqlalchemy.orm import Session

from cds_shared.auth.rbac import RBACEngine, ROLE_PERMISSIONS
from models.role import Role, RoleAssignment
from models.user import User

logger = structlog.get_logger(__name__)

PERMISSION_CACHE_TTL = 60  # seconds
PERMISSION_CACHE_PREFIX = "perms:"


class RBACService:
    def __init__(self, db: Session, redis_client: redis_lib.Redis) -> None:
        self._db = db
        self._redis = redis_client
        self._engine = RBACEngine()

    def get_user_permissions(self, user_id: str) -> List[str]:
        """Return permissions for a user. Cached in Redis."""
        cache_key = f"{PERMISSION_CACHE_PREFIX}{user_id}"
        cached = self._redis.get(cache_key)
        if cached:
            return json.loads(cached)

        user = self._db.query(User).filter(User.id == user_id).first()
        if not user:
            return []

        permissions = self._engine.get_permissions(user.role)
        self._redis.setex(cache_key, PERMISSION_CACHE_TTL, json.dumps(permissions))
        return permissions

    def check_permission(self, user_id: str, permission: str) -> bool:
        """Check if a user has a specific permission."""
        user = self._db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            return False
        return self._engine.has_permission(user.role, permission)

    def assign_role(
        self,
        user_id: UUID,
        role_name: str,
        assigned_by_id: UUID,
    ) -> RoleAssignment:
        """Assign a role to a user. Creates RoleAssignment record and updates user.role."""
        # Validate role exists
        role = self._db.query(Role).filter(Role.name == role_name).first()
        if not role:
            raise ValueError(f"Role '{role_name}' does not exist")

        user = self._db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User not found")

        assignment = RoleAssignment(
            user_id=user_id,
            role_name=role_name,
            assigned_by=assigned_by_id,
        )
        self._db.add(assignment)

        user.role = role_name
        self._db.flush()

        self.invalidate_permission_cache(str(user_id))
        logger.info("role_assigned", user_id=str(user_id), role=role_name)
        return assignment

    def revoke_role(
        self,
        user_id: UUID,
        role_name: str,
        revoked_by_id: UUID,
        reason: str,
    ) -> RoleAssignment:
        """Revoke an active role assignment. Reverts user to dept_viewer."""
        from datetime import datetime, timezone

        assignment = (
            self._db.query(RoleAssignment)
            .filter(
                RoleAssignment.user_id == user_id,
                RoleAssignment.role_name == role_name,
                RoleAssignment.revoked_at.is_(None),
            )
            .first()
        )
        if not assignment:
            raise ValueError("Active role assignment not found")

        assignment.revoked_at = datetime.now(timezone.utc)
        assignment.revoked_by = revoked_by_id
        assignment.revocation_reason = reason

        user = self._db.query(User).filter(User.id == user_id).first()
        if user:
            user.role = "dept_viewer"

        self._db.flush()
        self.invalidate_permission_cache(str(user_id))
        logger.info("role_revoked", user_id=str(user_id), role=role_name, reason=reason)
        return assignment

    def invalidate_permission_cache(self, user_id: str) -> None:
        """Remove cached permissions for a user."""
        self._redis.delete(f"{PERMISSION_CACHE_PREFIX}{user_id}")

    def get_all_roles(self) -> List[Role]:
        return self._db.query(Role).all()
