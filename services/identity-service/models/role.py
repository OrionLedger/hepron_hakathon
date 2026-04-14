from datetime import datetime
from typing import Optional
from uuid import UUID
import uuid
from sqlalchemy import String, DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel
from cds_shared.database import Base


class Role(Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    parent_role: Mapped[Optional[str]] = mapped_column(
        String(50), ForeignKey("roles.name"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(nullable=True)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    role_name: Mapped[str] = mapped_column(
        String(50), ForeignKey("roles.name"), nullable=False
    )
    assigned_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    revocation_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    __table_args__ = (
        Index("ix_role_assignments_user_active", "user_id", "revoked_at"),
    )


# ── Pydantic schemas ──────────────────────────────────────────

class RoleResponse(BaseModel):
    name: str
    description: str
    parent_role: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RoleAssignRequest(BaseModel):
    user_id: UUID
    role_name: str


class RoleRevokeRequest(BaseModel):
    user_id: UUID
    role_name: str
    reason: str


class RoleAssignmentResponse(BaseModel):
    id: UUID
    user_id: UUID
    role_name: str
    assigned_by: UUID
    assigned_at: datetime
    revoked_at: Optional[datetime]

    model_config = {"from_attributes": True}
