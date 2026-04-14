from datetime import datetime
from typing import Optional, List
from uuid import UUID
import uuid
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel, EmailStr, field_validator
from cds_shared.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    dept_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("departments.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="dept_viewer")
    clearance_level: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("ix_users_dept_role", "dept_id", "role"),
    )


# ── Pydantic schemas ──────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str
    dept_id: str
    role: str = "dept_viewer"
    clearance_level: int = 2

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        allowed = {"city_admin", "dept_admin", "dept_analyst", "dept_viewer",
                   "auditor", "ai_reviewer", "system_operator"}
        if v not in allowed:
            raise ValueError(f"Role must be one of {allowed}")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    clearance_level: Optional[int] = None
    is_active: Optional[bool] = None
    is_mfa_enabled: Optional[bool] = None


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    full_name: str
    dept_id: str
    role: str
    clearance_level: int
    is_active: bool
    is_mfa_enabled: bool
    last_login_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int
    page: int
    page_size: int
