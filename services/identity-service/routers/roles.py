"""
RBAC management router — role assignment, revocation, permission queries.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cds_shared.audit import AuditProducer, AuditEvent
from cds_shared.auth.middleware import AuthContext, require_auth
from cds_shared.database import get_db
from cds_shared.config import settings
from models.abac_policy import ABACPolicyCreate, ABACPolicyResponse
from models.role import RoleAssignRequest, RoleRevokeRequest, RoleAssignmentResponse, RoleResponse
from services.rbac_service import RBACService
from services.abac_service import ABACService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/rbac", tags=["rbac"])


def _get_redis():
    return redis_lib.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )


def _meta(request: Request) -> dict:
    return {
        "request_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": settings.SERVICE_NAME,
    }


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else request.client.host or "unknown"


def _emit_audit(request: Request, auth: AuthContext, action: str, resource_id: str, metadata: dict = None):
    ap: Optional[AuditProducer] = getattr(request.app.state, "audit_producer", None)
    if ap:
        ap.emit(AuditEvent(
            actor_id=auth.user_id,
            actor_role=auth.role,
            actor_dept_id=auth.dept_id,
            action=action,
            resource_type="role",
            resource_id=resource_id,
            outcome="success",
            ip_address=_get_ip(request),
            trace_id=getattr(request.state, "trace_id", "unknown"),
            metadata=metadata or {},
        ))


@router.get("/roles", response_model=dict)
async def list_roles(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth()),
):
    """List all available roles."""
    svc = RBACService(db, _get_redis())
    roles = svc.get_all_roles()
    return {
        "data": [RoleResponse.model_validate(r).model_dump() for r in roles],
        "meta": _meta(request),
    }


@router.post("/roles/assign", response_model=dict, status_code=201)
async def assign_role(
    body: RoleAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["user:manage:own_dept"])),
):
    """Assign a role to a user."""
    # dept_admin can only assign up to dept_analyst in their own dept
    if auth.role == "dept_admin":
        if body.role_name in ("city_admin", "dept_admin"):
            raise HTTPException(status_code=403, detail="Cannot assign elevated roles")

    svc = RBACService(db, _get_redis())
    try:
        assignment = svc.assign_role(body.user_id, body.role_name, UUID(auth.user_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _emit_audit(
        request, auth, "role.assign", str(body.user_id),
        {"role_name": body.role_name},
    )
    return {
        "data": RoleAssignmentResponse.model_validate(assignment).model_dump(),
        "meta": _meta(request),
    }


@router.post("/roles/revoke", response_model=dict)
async def revoke_role(
    body: RoleRevokeRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["user:manage:own_dept"])),
):
    """Revoke a role from a user. Requires a reason."""
    svc = RBACService(db, _get_redis())
    try:
        svc.revoke_role(body.user_id, body.role_name, UUID(auth.user_id), body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _emit_audit(
        request, auth, "role.revoke", str(body.user_id),
        {"role_name": body.role_name, "reason": body.reason},
    )
    return {"data": {"message": "Role revoked"}, "meta": _meta(request)}


@router.get("/users/{user_id}/permissions", response_model=dict)
async def get_user_permissions(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth()),
):
    """Get effective permissions for a user. city_admin or self only."""
    if auth.role != "city_admin" and auth.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    svc = RBACService(db, _get_redis())
    permissions = svc.get_user_permissions(user_id)
    return {
        "data": {"user_id": user_id, "permissions": permissions},
        "meta": _meta(request),
    }


class CheckPermissionRequest(BaseModel):
    user_id: str
    permission: str


@router.post("/check-permission", response_model=dict)
async def check_permission(
    body: CheckPermissionRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["system:health:read"])),
):
    """Check if a user has a specific permission. Used by internal services."""
    svc = RBACService(db, _get_redis())
    has_perm = svc.check_permission(body.user_id, body.permission)
    return {"data": {"has_permission": has_perm}, "meta": _meta(request)}


@router.get("/policies", response_model=dict)
async def list_policies(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth()),
):
    """List all ABAC policies. city_admin only."""
    if auth.role != "city_admin":
        raise HTTPException(status_code=403, detail="city_admin role required")

    svc = ABACService(db, _get_redis())
    policies = svc.load_active_policies()
    return {
        "data": [ABACPolicyResponse.model_validate(p).model_dump() for p in policies],
        "meta": _meta(request),
    }


@router.post("/policies", response_model=dict, status_code=201)
async def create_policy(
    body: ABACPolicyCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth()),
):
    """Create a new ABAC policy. city_admin only."""
    if auth.role != "city_admin":
        raise HTTPException(status_code=403, detail="city_admin role required")

    svc = ABACService(db, _get_redis())
    policy = svc.create_policy(body, UUID(auth.user_id))

    _emit_audit(request, auth, "abac_policy.create", str(policy.id))
    return {
        "data": ABACPolicyResponse.model_validate(policy).model_dump(),
        "meta": _meta(request),
    }
