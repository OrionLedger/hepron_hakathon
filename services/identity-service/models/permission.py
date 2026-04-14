from datetime import datetime
from typing import Optional
from uuid import UUID
import uuid
from sqlalchemy import String, DateTime, ForeignKey, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel
from cds_shared.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # "kpi:read:own_dept"
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)  # "own_dept"|"all"|"system"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    role_name: Mapped[str] = mapped_column(
        String(50), ForeignKey("roles.name"), nullable=False, index=True
    )
    permission_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("permissions.id"), nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    granted_by: Mapped[Optional[UUID]] = mapped_column(nullable=True)

    __table_args__ = (
        UniqueConstraint("role_name", "permission_id", name="uq_role_permission"),
    )


class PermissionResponse(BaseModel):
    id: str
    description: str
    resource_type: str
    action: str
    scope: str

    model_config = {"from_attributes": True}
