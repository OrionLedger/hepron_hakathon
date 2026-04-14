from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pydantic import BaseModel
from cds_shared.database import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    parent_dept_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("departments.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


# ── Pydantic schemas ──────────────────────────────────────────

class DepartmentCreate(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parent_dept_id: Optional[str] = None


class DepartmentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    parent_dept_id: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
