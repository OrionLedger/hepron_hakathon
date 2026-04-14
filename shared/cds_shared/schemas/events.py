"""
Kafka event envelope and topic name registry.
All inter-service Kafka messages must use EventEnvelope.
All topic names must be derived from the Topics class — never hardcoded strings.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """Standard wrapper for all Kafka inter-service messages."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = Field(..., description="e.g. 'raw_data_ingested', 'kpi_computed'")
    source_service: str
    payload: Dict[str, Any]
    schema_version: str = "v1"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: Optional[str] = None
    correlation_id: Optional[str] = None


class Topics:
    """
    Kafka topic name registry.
    Convention: {stage}.{source}.{entity}
    Never use raw strings for topic names in service code — use this class.
    """
    # Fixed topics
    AUDIT_EVENTS = "audit.events"
    THRESHOLD_BREACH = "monitoring.threshold_breach"
    FRESHNESS_BREACH = "governance.freshness_breach"
    NOTIFICATION_SEND = "notification.send"

    @staticmethod
    def raw(source: str, entity: str) -> str:
        """Raw ingested data before validation. Retention: 7 days."""
        return f"raw.{source}.{entity}"

    @staticmethod
    def validated(source: str, entity: str) -> str:
        """Schema-validated data. Retention: 30 days."""
        return f"validated.{source}.{entity}"

    @staticmethod
    def processed(source: str, entity: str) -> str:
        """ETL-processed canonical data. Retention: 30 days."""
        return f"processed.{source}.{entity}"

    @staticmethod
    def kpi_computed(kpi_id: str) -> str:
        """Computed KPI value event. Retention: 30 days."""
        return f"kpi.computed.{kpi_id}"

    @staticmethod
    def dlq(original_topic: str) -> str:
        """Dead letter queue. Retention: 30 days."""
        return f"dlq.{original_topic}"

    @staticmethod
    def ai_recommendations(dept_id: str) -> str:
        """AI recommendation events for a department. Retention: 7 days."""
        return f"ai.recommendations.{dept_id}"
