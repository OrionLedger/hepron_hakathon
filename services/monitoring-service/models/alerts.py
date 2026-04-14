from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Enum, Boolean
from datetime import datetime, timezone
import enum

from cds_shared.database import Base

class AlertSeverity(str, enum.Enum):
    P1 = "P1"  # Critical (SMS + Email + In-App)
    P2 = "P2"  # High (Email + In-App)
    P3 = "P3"  # Medium (In-App)
    P4 = "P4"  # Low (Logging only)

class AlertStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500))
    kpi_id = Column(Integer, nullable=False)
    trigger_type = Column(String(50), nullable=False, help_text="threshold, anomaly, absence")
    condition = Column(JSON, nullable=False, help_text='{"operator": ">", "value": 100}')
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.P3)
    cooldown_minutes = Column(Integer, default=15)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"))
    kpi_id = Column(Integer, nullable=False)
    severity = Column(Enum(AlertSeverity), nullable=False)
    status = Column(Enum(AlertStatus), default=AlertStatus.OPEN)
    message = Column(String(1000), nullable=False)
    triggered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)
    acknowledged_by = Column(String(100))
    metadata_json = Column(JSON, help_text="Current KPI value and other context at trigger time")
