"""
Authentication service — JWT creation, validation, token lifecycle management.
Uses python-jose for JWT, passlib[bcrypt] for password hashing, Redis for token store.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis as redis_lib
import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from cds_shared.config import settings
from models.user import User

logger = structlog.get_logger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

REFRESH_TOKEN_PREFIX = "refresh_token:"
BLACKLIST_PREFIX = "blacklist:"


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


class AuthService:
    def __init__(self, db: Session, redis_client: redis_lib.Redis) -> None:
        self._db = db
        self._redis = redis_client

    # ── Public methods ────────────────────────────────────────

    def login(self, username: str, password: str) -> TokenPair:
        """
        Authenticate user. Raises ValueError on invalid credentials.
        Raises PermissionError if user is inactive.
        """
        user = (
            self._db.query(User)
            .filter(User.username == username.lower().strip())
            .first()
        )

        if not user or not _pwd_context.verify(password, user.password_hash):
            logger.warning("login_failed_invalid_credentials", username=username)
            raise ValueError("Invalid username or password")

        if not user.is_active:
            logger.warning("login_failed_inactive_user", user_id=str(user.id))
            raise PermissionError("Account is deactivated")

        # Update last login timestamp
        user.last_login_at = datetime.now(timezone.utc)
        self._db.flush()

        token_pair = self._issue_token_pair(user)
        logger.info("login_success", user_id=str(user.id), role=user.role)
        return token_pair

    def refresh(self, refresh_token: str) -> TokenPair:
        """Issue a new token pair from a valid, non-revoked refresh token."""
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            raise ValueError(f"Invalid refresh token: {e}")

        if payload.get("type") != "refresh":
            raise ValueError("Token is not a refresh token")

        token_id = payload.get("token_id")
        user_id = payload.get("sub")

        # Verify token is in Redis (not revoked)
        stored = self._redis.get(f"{REFRESH_TOKEN_PREFIX}{token_id}")
        if not stored:
            raise ValueError("Refresh token has been revoked or expired")

        # Revoke the old token
        self._redis.delete(f"{REFRESH_TOKEN_PREFIX}{token_id}")

        user = self._db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise PermissionError("User not found or inactive")

        return self._issue_token_pair(user)

    def logout(self, token_id: str) -> None:
        """Revoke a refresh token by removing it from Redis."""
        self._redis.delete(f"{REFRESH_TOKEN_PREFIX}{token_id}")
        logger.info("logout_success", token_id=token_id)

    def verify_token(self, token: str) -> dict:
        """
        Validate a JWT access token and return AuthContext dict.
        Used by the /v1/auth/verify endpoint called by other services.
        """
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}")

        if payload.get("type") != "access":
            raise ValueError("Token is not an access token")

        # Check blacklist
        token_id = payload.get("token_id")
        if self._redis.exists(f"{BLACKLIST_PREFIX}{token_id}"):
            raise ValueError("Token has been revoked")

        user_id = payload.get("sub")
        user = self._db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise ValueError("User not found or inactive")

        return {
            "user_id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "dept_id": user.dept_id,
            "permissions": self._get_permissions_for_role(user.role),
            "token_id": token_id,
            "clearance_level": user.clearance_level,
        }

    def create_user_hash(self, password: str) -> str:
        return _pwd_context.hash(password)

    # ── Private helpers ───────────────────────────────────────

    def _issue_token_pair(self, user: User) -> TokenPair:
        access_token_id = str(uuid.uuid4())
        refresh_token_id = str(uuid.uuid4())

        access_token = self._create_access_token(user, access_token_id)
        refresh_token = self._create_refresh_token(user, refresh_token_id)

        self._store_refresh_token(
            refresh_token_id,
            str(user.id),
            settings.JWT_REFRESH_TOKEN_EXPIRE_HOURS,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def _create_access_token(self, user: User, token_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        payload = {
            "sub": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "dept_id": user.dept_id,
            "clearance_level": user.clearance_level,
            "token_id": token_id,
            "type": "access",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def _create_refresh_token(self, user: User, token_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(
            hours=settings.JWT_REFRESH_TOKEN_EXPIRE_HOURS
        )
        payload = {
            "sub": str(user.id),
            "token_id": token_id,
            "type": "refresh",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def _store_refresh_token(self, token_id: str, user_id: str, expires_hours: int) -> None:
        self._redis.setex(
            name=f"{REFRESH_TOKEN_PREFIX}{token_id}",
            time=expires_hours * 3600,
            value=user_id,
        )

    def _get_permissions_for_role(self, role: str) -> list:
        from cds_shared.auth.rbac import ROLE_PERMISSIONS
        return ROLE_PERMISSIONS.get(role, [])
