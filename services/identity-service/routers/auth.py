"""
Authentication router — login, refresh, logout, token verification.
All endpoints are versioned at /v1/auth.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cds_shared.audit import AuditProducer, AuditEvent
from cds_shared.auth.middleware import AuthContext, require_auth
from cds_shared.database import get_db
from cds_shared.config import settings
from services.auth_service import AuthService, TokenPair

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["authentication"])


def _get_redis():
    r = redis_lib.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )
    return r


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else request.client.host or "unknown"


def _meta(request: Request) -> dict:
    return {
        "request_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": settings.SERVICE_NAME,
    }


# ── Request / Response schemas ────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VerifyRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Routes ────────────────────────────────────────────────────

@router.post("/login", response_model=dict, status_code=200)
async def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate with username + password. Returns access + refresh token pair."""
    redis_client = _get_redis()
    svc = AuthService(db, redis_client)

    # Rate limiting: 10 attempts per IP per minute via Redis counter
    ip = _get_ip(request)
    rate_key = f"rate_login:{ip}"
    count = redis_client.incr(rate_key)
    if count == 1:
        redis_client.expire(rate_key, 60)
    if count > 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a minute.",
        )

    trace_id = getattr(request.state, "trace_id", "unknown")
    audit_producer: Optional[AuditProducer] = getattr(request.app.state, "audit_producer", None)

    try:
        token_pair = svc.login(body.username, body.password)

        if audit_producer:
            audit_producer.emit(AuditEvent(
                actor_id=body.username,
                actor_role="unknown",
                actor_dept_id="unknown",
                action="user.login",
                resource_type="user",
                resource_id=body.username,
                outcome="success",
                ip_address=ip,
                trace_id=trace_id,
            ))

        return {
            "data": TokenResponse(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                expires_in=token_pair.expires_in,
            ).model_dump(),
            "meta": _meta(request),
        }

    except ValueError:
        if audit_producer:
            audit_producer.emit(AuditEvent(
                actor_id=body.username,
                actor_role="unknown",
                actor_dept_id="unknown",
                action="user.login",
                resource_type="user",
                resource_id=body.username,
                outcome="denied",
                ip_address=ip,
                trace_id=trace_id,
            ))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )


@router.post("/refresh", response_model=dict, status_code=200)
async def refresh_token(
    body: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Issue a new token pair from a valid refresh token."""
    redis_client = _get_redis()
    svc = AuthService(db, redis_client)

    try:
        token_pair = svc.refresh(body.refresh_token)
        return {
            "data": TokenResponse(
                access_token=token_pair.access_token,
                refresh_token=token_pair.refresh_token,
                expires_in=token_pair.expires_in,
            ).model_dump(),
            "meta": _meta(request),
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


@router.post("/logout", response_model=dict, status_code=200)
async def logout(
    request: Request,
    auth: AuthContext = Depends(require_auth()),
    db: Session = Depends(get_db),
):
    """Revoke the current user's refresh token."""
    redis_client = _get_redis()
    svc = AuthService(db, redis_client)
    svc.logout(auth.token_id)

    audit_producer: Optional[AuditProducer] = getattr(request.app.state, "audit_producer", None)
    if audit_producer:
        audit_producer.emit(AuditEvent(
            actor_id=auth.user_id,
            actor_role=auth.role,
            actor_dept_id=auth.dept_id,
            action="user.logout",
            resource_type="user",
            resource_id=auth.user_id,
            outcome="success",
            ip_address=_get_ip(request),
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ))

    return {"data": {"message": "Logged out successfully"}, "meta": _meta(request)}


@router.post("/verify", response_model=dict, status_code=200)
async def verify_token(
    body: VerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Validate a JWT token and return AuthContext.
    Used internally by other services via cds_shared auth middleware.
    """
    redis_client = _get_redis()
    svc = AuthService(db, redis_client)

    try:
        auth_context = svc.verify_token(body.token)
        return {"data": auth_context, "meta": _meta(request)}
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.get("/context", response_model=dict, status_code=200)
async def get_auth_context(
    request: Request,
    auth: AuthContext = Depends(require_auth()),
):
    """Return the current user's auth context. Used by frontend to initialize session."""
    audit_producer: Optional[AuditProducer] = getattr(request.app.state, "audit_producer", None)
    if audit_producer:
        audit_producer.emit(AuditEvent(
            actor_id=auth.user_id,
            actor_role=auth.role,
            actor_dept_id=auth.dept_id,
            action="auth.context_read",
            resource_type="auth_context",
            resource_id=auth.user_id,
            outcome="success",
            ip_address=_get_ip(request),
            trace_id=getattr(request.state, "trace_id", "unknown"),
        ))
    return {"data": auth.model_dump(), "meta": _meta(request)}
