"""
User management router. All write operations emit audit events.
dept_admin can only manage users within their own department.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from cds_shared.audit import AuditProducer, AuditEvent
from cds_shared.auth.middleware import AuthContext, require_auth
from cds_shared.database import get_db
from cds_shared.config import settings
from models.user import User, UserCreate, UserUpdate, UserResponse, UserListResponse
from services.auth_service import AuthService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/users", tags=["users"])


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


def _emit_audit(request: Request, auth: AuthContext, action: str, resource_id: str, outcome: str = "success"):
    ap: Optional[AuditProducer] = getattr(request.app.state, "audit_producer", None)
    if ap:
        ap.emit(AuditEvent(
            actor_id=auth.user_id,
            actor_role=auth.role,
            actor_dept_id=auth.dept_id,
            action=action,
            resource_type="user",
            resource_id=resource_id,
            outcome=outcome,
            ip_address=_get_ip(request),
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ))


@router.get("", response_model=dict)
async def list_users(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    dept_id: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["user:read:own_dept"])),
):
    """List users. dept_admin only sees their own department."""
    query = db.query(User)

    # dept_admin can only see their own dept
    if auth.role == "dept_admin":
        query = query.filter(User.dept_id == auth.dept_id)
    elif dept_id:
        query = query.filter(User.dept_id == dept_id)

    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    total = query.count()
    users = query.offset((page - 1) * page_size).limit(page_size).all()

    _emit_audit(request, auth, "user.list", f"dept={auth.dept_id}")
    return {
        "data": UserListResponse(
            items=[UserResponse.model_validate(u) for u in users],
            total=total,
            page=page,
            page_size=page_size,
        ).model_dump(),
        "meta": _meta(request),
    }


@router.post("", response_model=dict, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["user:create:own_dept"])),
):
    """Create a new user."""
    # dept_admin can only create users for their own dept
    if auth.role == "dept_admin":
        if body.dept_id != auth.dept_id:
            raise HTTPException(status_code=403, detail="Cannot create users for other departments")
        if body.role in ("city_admin", "dept_admin"):
            raise HTTPException(status_code=403, detail="dept_admin cannot assign city_admin or dept_admin role")

    # Check uniqueness
    if db.query(User).filter(User.username == body.username.lower()).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    if db.query(User).filter(User.email == body.email.lower()).first():
        raise HTTPException(status_code=409, detail="Email already exists")

    redis_client = _get_redis()
    svc = AuthService(db, redis_client)
    user = User(
        username=body.username.lower().strip(),
        email=body.email.lower().strip(),
        password_hash=svc.create_user_hash(body.password),
        full_name=body.full_name,
        dept_id=body.dept_id,
        role=body.role,
        clearance_level=body.clearance_level,
        created_by=uuid.UUID(auth.user_id),
    )
    db.add(user)
    db.flush()

    _emit_audit(request, auth, "user.create", str(user.id))
    return {"data": UserResponse.model_validate(user).model_dump(), "meta": _meta(request)}


@router.get("/{user_id}", response_model=dict)
async def get_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth()),
):
    """Get a user by ID. city_admin sees all; dept_admin sees own dept; users see themselves."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Authorization check
    if auth.role not in ("city_admin", "auditor"):
        if auth.user_id != user_id and (auth.role != "dept_admin" or user.dept_id != auth.dept_id):
            raise HTTPException(status_code=403, detail="Access denied")

    _emit_audit(request, auth, "user.read", user_id)
    return {"data": UserResponse.model_validate(user).model_dump(), "meta": _meta(request)}


@router.put("/{user_id}", response_model=dict)
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["user:update:own_dept"])),
):
    """Update user fields."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if auth.role == "dept_admin" and user.dept_id != auth.dept_id:
        raise HTTPException(status_code=403, detail="Cannot update users from other departments")

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        if auth.role == "dept_admin" and body.role in ("city_admin", "dept_admin"):
            raise HTTPException(status_code=403, detail="Cannot assign elevated roles")
        user.role = body.role
        # Invalidate permission cache
        redis_client = _get_redis()
        redis_client.delete(f"perms:{user_id}")
    if body.clearance_level is not None:
        user.clearance_level = body.clearance_level
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.is_mfa_enabled is not None:
        user.is_mfa_enabled = body.is_mfa_enabled

    db.flush()
    _emit_audit(request, auth, "user.update", user_id)
    return {"data": UserResponse.model_validate(user).model_dump(), "meta": _meta(request)}


@router.delete("/{user_id}", response_model=dict)
async def deactivate_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["user:deactivate:own_dept"])),
):
    """Soft-delete a user (sets is_active=False). city_admin only."""
    if auth.role != "city_admin":
        raise HTTPException(status_code=403, detail="Only city_admin can deactivate users")

    if auth.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.flush()

    _emit_audit(request, auth, "user.deactivate", user_id)
    return {"data": {"message": "User deactivated"}, "meta": _meta(request)}


@router.post("/{user_id}/reset-password", response_model=dict)
async def reset_password(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth()),
):
    """Reset user password. city_admin, dept_admin (own dept), or self."""
    from pydantic import BaseModel

    class ResetPasswordRequest(BaseModel):
        new_password: str

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Authorization
    if auth.user_id != user_id:
        if auth.role == "dept_admin" and user.dept_id != auth.dept_id:
            raise HTTPException(status_code=403, detail="Access denied")
        elif auth.role not in ("city_admin", "dept_admin"):
            raise HTTPException(status_code=403, detail="Access denied")

    # Parse body manually to avoid circular import
    import json
    body_bytes = await request.body()
    body_data = json.loads(body_bytes)
    new_password = body_data.get("new_password", "")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    redis_client = _get_redis()
    svc = AuthService(db, redis_client)
    user.password_hash = svc.create_user_hash(new_password)
    db.flush()

    # Invalidate all refresh tokens for this user
    pattern = f"refresh_token:*"
    for key in redis_client.scan_iter(pattern):
        if redis_client.get(key) == user_id:
            redis_client.delete(key)

    _emit_audit(request, auth, "user.password_reset", user_id)
    return {"data": {"message": "Password updated"}, "meta": _meta(request)}
