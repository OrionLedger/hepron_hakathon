"""
ABAC service — policy management and attribute-based access evaluation.
Policies cached in Redis with 5-minute TTL.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

import redis as redis_lib
import structlog
from sqlalchemy.orm import Session

from cds_shared.auth.abac import ABACEngine, ABACContext
from models.abac_policy import ABACPolicy, ABACPolicyCreate
from models.user import User

logger = structlog.get_logger(__name__)

POLICY_CACHE_KEY = "abac:policies"
POLICY_CACHE_TTL = 300  # 5 minutes


class ABACService:
    def __init__(self, db: Session, redis_client: redis_lib.Redis) -> None:
        self._db = db
        self._redis = redis_client
        self._engine = ABACEngine()

    def evaluate(
        self,
        user: User,
        resource_dept_id: str,
        resource_sensitivity: str,
        action: str,
        environment: Optional[dict] = None,
    ) -> bool:
        """Evaluate ABAC policies for an access request."""
        ctx = ABACContext(
            user_id=str(user.id),
            user_dept_id=user.dept_id,
            user_role=user.role,
            user_clearance_level=user.clearance_level,
            resource_dept_id=resource_dept_id,
            resource_sensitivity=resource_sensitivity,
            action=action,
            environment=environment or {},
        )
        return self._engine.evaluate(ctx)

    def load_active_policies(self) -> List[ABACPolicy]:
        """Load active policies from DB. Cached in Redis."""
        cached = self._redis.get(POLICY_CACHE_KEY)
        if cached:
            # Return DB objects refreshed from cache data
            policy_ids = json.loads(cached)
            return (
                self._db.query(ABACPolicy)
                .filter(ABACPolicy.id.in_(policy_ids))
                .all()
            )
        policies = (
            self._db.query(ABACPolicy)
            .filter(ABACPolicy.is_active == True)
            .order_by(ABACPolicy.priority.desc())
            .all()
        )
        self._redis.setex(
            POLICY_CACHE_KEY,
            POLICY_CACHE_TTL,
            json.dumps([str(p.id) for p in policies]),
        )
        return policies

    def create_policy(self, policy_data: ABACPolicyCreate, created_by: UUID) -> ABACPolicy:
        """Create a new ABAC policy. Invalidates policy cache."""
        policy = ABACPolicy(
            name=policy_data.name,
            description=policy_data.description,
            condition_yaml=policy_data.condition_yaml,
            applies_to=policy_data.applies_to,
            action=policy_data.action,
            priority=policy_data.priority,
            created_by=created_by,
        )
        self._db.add(policy)
        self._db.flush()
        self._redis.delete(POLICY_CACHE_KEY)
        logger.info("abac_policy_created", policy_name=policy_data.name)
        return policy

    def invalidate_policy_cache(self) -> None:
        self._redis.delete(POLICY_CACHE_KEY)
