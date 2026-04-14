"""
Audit consumer worker — persists audit events from Kafka to PostgreSQL.
Deduplicates via event_id (ON CONFLICT DO NOTHING).
Batch inserts every 100 messages or 5 seconds, whichever comes first.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from cds_shared.kafka_client import CDSKafkaConsumer, CDSKafkaProducer

logger = structlog.get_logger(__name__)


class AuditConsumerWorker:
    """
    Consumes from audit.events Kafka topic and persists to audit_logs table.
    Deduplicates by event_id — INSERT ... ON CONFLICT DO NOTHING.
    """
    TOPIC = "audit.events"
    GROUP_ID = "identity-service-audit-consumer"
    BATCH_SIZE = 100
    BATCH_TIMEOUT_SECONDS = 5

    def __init__(self, bootstrap_servers: str, database_url: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._database_url = database_url
        self._consumer: CDSKafkaConsumer = None
        self._running = False
        self._batch: List[Dict[str, Any]] = []
        self._last_flush = time.monotonic()

    def run(self) -> None:
        """Main consumer loop. Call in a background thread."""
        # Create dedicated DB engine for the consumer thread
        engine = create_engine(
            self._database_url,
            pool_size=2,
            max_overflow=5,
            pool_pre_ping=True,
        )
        SessionLocal = sessionmaker(bind=engine)

        self._consumer = CDSKafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            group_id=self.GROUP_ID,
            auto_offset_reset="earliest",
        )
        self._running = True

        def handle_message(value: Dict[str, Any], headers: Dict[str, str]) -> None:
            self._batch.append(value)

            now = time.monotonic()
            should_flush = (
                len(self._batch) >= self.BATCH_SIZE
                or (now - self._last_flush) >= self.BATCH_TIMEOUT_SECONDS
            )
            if should_flush:
                with SessionLocal() as session:
                    self._flush_batch(session)
                self._last_flush = time.monotonic()

        try:
            self._consumer.consume(
                topics=[self.TOPIC],
                handler=handle_message,
                max_poll_records=self.BATCH_SIZE,
            )
        except Exception as e:
            logger.error("audit_consumer_crashed", error=str(e))
        finally:
            # Flush remaining messages
            if self._batch:
                try:
                    with SessionLocal() as session:
                        self._flush_batch(session)
                except Exception as e:
                    logger.error("audit_final_flush_failed", error=str(e))
            engine.dispose()

    def stop(self) -> None:
        """Signal graceful shutdown."""
        self._running = False
        if self._consumer:
            self._consumer.shutdown()

    def _flush_batch(self, session) -> None:
        """Batch insert audit events. ON CONFLICT DO NOTHING for idempotency."""
        if not self._batch:
            return

        rows = []
        for event in self._batch:
            try:
                rows.append({
                    "event_id": event["event_id"],
                    "timestamp": datetime.fromisoformat(event["timestamp"]),
                    "actor_id": event.get("actor_id", "unknown"),
                    "actor_role": event.get("actor_role", "unknown"),
                    "actor_dept_id": event.get("actor_dept_id", "unknown"),
                    "action": event.get("action", "unknown"),
                    "resource_type": event.get("resource_type", "unknown"),
                    "resource_id": event.get("resource_id", "unknown"),
                    "outcome": event.get("outcome", "unknown"),
                    "ip_address": event.get("ip_address", "0.0.0.0"),
                    "trace_id": event.get("trace_id", ""),
                    "metadata": event.get("metadata"),
                })
            except Exception as e:
                logger.error("audit_row_parse_failed", error=str(e), event=event)

        if not rows:
            self._batch.clear()
            return

        try:
            stmt = pg_insert(text("audit_logs")).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
            session.execute(stmt)
            session.commit()
            logger.info("audit_batch_flushed", count=len(rows))
        except Exception as e:
            session.rollback()
            logger.error(
                "audit_batch_insert_failed",
                error=str(e),
                count=len(rows),
            )
        finally:
            self._batch.clear()
