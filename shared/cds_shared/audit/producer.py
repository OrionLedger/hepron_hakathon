"""
Audit event producer.
Emits immutable audit records to the audit.events Kafka topic.
NEVER raises exceptions — audit failures are logged but must not break service operations.
All critical actions MUST emit an audit event.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict

import structlog

if TYPE_CHECKING:
    from cds_shared.kafka_client import CDSKafkaProducer

logger = structlog.get_logger(__name__)


@dataclass
class AuditEvent:
    """
    Represents one auditable action.
    action format: "resource_type.verb"  e.g. "kpi.read", "user.create", "role.assign"
    outcome:       "success" | "denied" | "error"
    """
    actor_id: str
    actor_role: str
    actor_dept_id: str
    action: str
    resource_type: str
    resource_id: str
    outcome: str
    ip_address: str
    trace_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AuditProducer:
    """Publishes AuditEvent objects to the audit.events Kafka topic."""

    TOPIC = "audit.events"

    def __init__(self, kafka_producer: "CDSKafkaProducer") -> None:
        self._producer = kafka_producer

    def emit(self, event: AuditEvent) -> None:
        """
        Emit audit event. Thread-safe, non-blocking.
        Logs error on failure but NEVER raises.
        """
        try:
            self._producer.publish(
                topic=self.TOPIC,
                key=event.actor_id,
                value={
                    "event_id": event.event_id,
                    "timestamp": event.timestamp,
                    "actor_id": event.actor_id,
                    "actor_role": event.actor_role,
                    "actor_dept_id": event.actor_dept_id,
                    "action": event.action,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "outcome": event.outcome,
                    "ip_address": event.ip_address,
                    "trace_id": event.trace_id,
                    "metadata": event.metadata,
                },
                headers={
                    "event_type": "audit_event",
                    "resource_type": event.resource_type,
                },
            )
        except Exception as e:
            # CRITICAL: audit failures must NEVER be silent
            logger.error(
                "audit_emit_failed",
                error=str(e),
                action=event.action,
                actor_id=event.actor_id,
                resource_id=event.resource_id,
            )
