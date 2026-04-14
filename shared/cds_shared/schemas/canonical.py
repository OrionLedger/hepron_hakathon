"""
Canonical data schemas shared across all CDS services.
Business logic must ONLY consume canonical records — never raw data.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class CanonicalRecord(BaseModel):
    """
    Standardized data record produced by the processing service after ETL.
    The only data format that should be consumed by business logic layers.
    """
    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str = Field(..., description="Adapter identifier, e.g. 'water_dept_api'")
    entity_type: str = Field(..., description="e.g. 'meter_reading', 'sensor_data'")
    dept_id: str = Field(..., description="Owning department ID")
    data: Dict[str, Any] = Field(..., description="Normalized, standardized data fields")
    raw_hash: str = Field(..., description="SHA-256 of original raw payload for deduplication")
    schema_version: str = Field(default="v1")
    ingested_at: datetime
    processed_at: Optional[datetime] = None
    quality_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @classmethod
    def compute_hash(cls, raw_data: Dict[str, Any]) -> str:
        """Compute a deterministic deduplication hash from raw data."""
        return hashlib.sha256(
            json.dumps(raw_data, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    model_config = {"frozen": False}


class KPIDefinition(BaseModel):
    """
    KPI definition stored in the KPI registry.
    Business rules for computation live in the formula field — never hardcoded in service logic.
    """
    kpi_id: str
    name: str
    description: str
    formula: str = Field(
        ...,
        description="Formula evaluated by the formula engine, e.g. 'sum(records.volume_m3)'",
    )
    source_datasets: List[str] = Field(..., description="entity_type values required for computation")
    unit: str = Field(..., description="Unit of measurement, e.g. 'm3', 'ILS', 'count', 'percent'")
    owner_dept_id: str
    update_frequency_seconds: int = Field(default=300, ge=60)
    version: int = Field(default=1, ge=1)
    is_active: bool = True
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    threshold_operator: str = Field(
        default="gt",
        description="Threshold comparison operator: gt, lt, gte, lte, eq",
    )

    @field_validator("formula")
    @classmethod
    def formula_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Formula cannot be empty")
        return v


class KPIValue(BaseModel):
    """A single computed KPI value written to the KPI store."""
    kpi_id: str
    dept_id: str
    value: float
    unit: str
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_record_ids: List[str] = Field(default_factory=list)
    schema_version: str = "v1"
    computation_metadata: Dict[str, Any] = Field(default_factory=dict)
