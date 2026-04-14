from datetime import datetime
from typing import Optional, Any, Dict
from sqlalchemy import String, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pydantic import BaseModel
from cds_shared.database import Base


class AuditLog(Base):
    """
    Immutable audit log records consumed from the audit.events Kafka topic.
    NO UPDATE or DELETE is ever performed on this table.
    """
    __tablename__ = "audit_logs"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # prevents duplicates
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_dept_id: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)  # success|denied|error
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_audit_actor_ts", "actor_id", "timestamp"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
        Index("ix_audit_action_ts", "action", "timestamp"),
        Index("ix_audit_trace", "trace_id"),
    )


class AuditLogResponse(BaseModel):
    event_id: str
    timestamp: datetime
    actor_id: str
    actor_role: str
    actor_dept_id: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    ip_address: str
    trace_id: str
    metadata: Optional[Dict[str, Any]]

    model_config = {"from_attributes": True}
