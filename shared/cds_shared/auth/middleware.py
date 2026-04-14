"""
FastAPI authentication and authorization dependencies.
All services use require_auth() or get_current_user() as FastAPI Depends().
Token validation is delegated to the identity service.
"""
from __future__ import annotations

from typing import Callable, List, Optional

import httpx
import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from cds_shared.auth.rbac import RBACEngine
from cds_shared.config import settings

logger = structlog.get_logger(__name__)

_rbac = RBACEngine()
_bearer = HTTPBearer(auto_error=True)


class AuthContext(BaseModel):
    """Decoded user identity injected into route handlers via Depends(require_auth(...))."""
    user_id: str
    username: str
    email: str
    role: str
    dept_id: str
    permissions: List[str]
    token_id: str
    clearance_level: int = 2


async def _validate_token(token: str) -> AuthContext:
    """
    Validate a JWT Bearer token against the identity service /v1/auth/verify.
    Returns AuthContext on success.
    Raises HTTPException 401 for invalid/expired tokens.
    Raises HTTPException 503 if identity service is unavailable.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{settings.IDENTITY_SERVICE_URL}/v1/auth/verify",
                json={"token": token},
            )

        if response.status_code == 200:
            return AuthContext(**response.json()["data"])

        if response.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.error(
            "identity_service_unexpected_status",
            status_code=response.status_code,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service returned unexpected response",
        )

    except httpx.TimeoutException:
        logger.error("identity_service_timeout")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service timeout",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("token_validation_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token validation failed",
        )


def require_auth(
    required_permissions: Optional[List[str]] = None,
) -> Callable:
    """
    FastAPI dependency factory for authentication + RBAC authorization.

    Usage:
        @router.get("/kpis")
        async def list_kpis(auth: AuthContext = Depends(require_auth(["kpi:read:own_dept"]))):
            ...
    """
    async def _dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    ) -> AuthContext:
        auth_context = await _validate_token(credentials.credentials)

        if required_permissions:
            for permission in required_permissions:
                if not _rbac.has_permission(auth_context.role, permission):
                    logger.warning(
                        "rbac_permission_denied",
                        user_id=auth_context.user_id,
                        role=auth_context.role,
                        required=permission,
                        path=str(request.url.path),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Insufficient permissions. Required: {permission}",
                    )

        request.state.auth = auth_context
        return auth_context

    return _dependency


def get_current_user() -> Callable:
    """FastAPI dependency: validates token, returns AuthContext, no permission check."""
    return require_auth(required_permissions=None)
