from datetime import datetime
from typing import Optional
from uuid import UUID
import uuid
from sqlalchemy import String, Boolean, Integer, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel
from cds_shared.database import Base


class ABACPolicy(Base):
    __tablename__ = "abac_policies"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    condition_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    applies_to: Mapped[str] = mapped_column(String(512), nullable=False)  # comma-separated resource types
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(nullable=True)


class ABACPolicyCreate(BaseModel):
    name: str
    description: str
    condition_yaml: str
    applies_to: str
    action: str
    priority: int = 100


class ABACPolicyResponse(BaseModel):
    id: UUID
    name: str
    description: str
    condition_yaml: str
    applies_to: str
    action: str
    priority: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
