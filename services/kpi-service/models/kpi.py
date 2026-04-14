from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, ForeignKey, Enum, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from cds_shared.database import Base

class KPIStatus(str, enum.Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"
    STALE = "STALE"

class KPIDefinition(Base):
    __tablename__ = "kpi_definitions"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500))
    formula = Column(String(1000), nullable=False, help_text="Expression string for computation")
    unit = Column(String(50), nullable=False)
    owner_dept_id = Column(String(100), nullable=False)
    update_freq_minutes = Column(Integer, default=60)
    thresholds = Column(JSON, nullable=False, help_text='{"amber": 50, "red": 80}')
    version = Column(Integer, default=1)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class KPIValue(Base):
    """
    Stored in TimescaleDB hypertable.
    Tracks computed values over time.
    """
    __tablename__ = "kpi_values"

    id = Column(Integer, primary_key=True)
    kpi_id = Column(Integer, ForeignKey("kpi_definitions.id"), nullable=False)
    value = Column(Float, nullable=False)
    status = Column(Enum(KPIStatus), nullable=False)
    computed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    formula_version = Column(Integer, nullable=False)
    source_record_ids = Column(JSON, help_text="List of source Kafka message IDs used for this computation")

    # Composite index for time-series queries
    __table_args__ = (
        Index("idx_kpi_time", "kpi_id", "computed_at"),
    )

class KPIBaseline(Base):
    """EPIC-13: Value realization baseline."""
    __tablename__ = "kpi_baselines"

    id = Column(Integer, primary_key=True)
    kpi_id = Column(Integer, ForeignKey("kpi_definitions.id"), nullable=False)
    baseline_value = Column(Float, nullable=False)
    set_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(String(500))
