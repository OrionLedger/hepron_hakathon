"""
Kafka producer and consumer wrappers for CDS services.
All inter-service communication passes through these wrappers.
Enforces DLQ routing, structured logging, and no silent failures.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog
from confluent_kafka import Consumer, KafkaError, KafkaException, Producer

logger = structlog.get_logger(__name__)


class DLQException(Exception):
    """
    Raise inside a Kafka consumer handler to send the message to the dead-letter queue
    instead of retrying indefinitely.
    """
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CDSKafkaProducer:
    """Thread-safe Kafka producer with JSON serialization and delivery tracking."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._producer = Producer({
            "bootstrap.servers": bootstrap_servers,
            "acks": "all",
            "retries": 5,
            "retry.backoff.ms": 500,
            "enable.idempotence": True,
            "compression.type": "lz4",
            "linger.ms": 5,
            "batch.size": 32768,
        })

    def _on_delivery(self, err, msg) -> None:
        if err:
            logger.error(
                "kafka_delivery_failed",
                topic=msg.topic(),
                error=str(err),
            )
        else:
            logger.debug(
                "kafka_delivery_success",
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
            )

    def publish(
        self,
        topic: str,
        key: str,
        value: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Publish a JSON-serialized message to a Kafka topic. Non-blocking."""
        try:
            encoded_value = json.dumps(value, default=str).encode("utf-8")
            encoded_key = key.encode("utf-8") if key else None
            kafka_headers = (
                [(k, v.encode("utf-8")) for k, v in headers.items()]
                if headers else None
            )
            self._producer.produce(
                topic=topic,
                key=encoded_key,
                value=encoded_value,
                headers=kafka_headers,
                on_delivery=self._on_delivery,
            )
            self._producer.poll(0)
        except BufferError:
            logger.error("kafka_producer_buffer_full", topic=topic)
            raise
        except KafkaException as e:
            logger.error("kafka_produce_failed", topic=topic, error=str(e))
            raise

    def publish_event(
        self,
        topic: str,
        event_type: str,
        payload: Dict[str, Any],
        source: str,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish a message wrapped in the standard EventEnvelope. Returns event_id."""
        event_id = str(uuid.uuid4())
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "source_service": source,
            "payload": payload,
            "schema_version": "v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trace_id": trace_id,
            "correlation_id": correlation_id,
        }
        self.publish(
            topic=topic,
            key=event_id,
            value=envelope,
            headers={"event_type": event_type, "source": source},
        )
        return event_id

    def flush(self, timeout: float = 10.0) -> None:
        remaining = self._producer.flush(timeout=timeout)
        if remaining > 0:
            logger.warning("kafka_flush_incomplete", messages_remaining=remaining)

    def close(self) -> None:
        self.flush()
        logger.info("kafka_producer_closed")


class CDSKafkaConsumer:
    """
    Kafka consumer with graceful shutdown, DLQ routing, and structured error handling.
    Call consume() in a dedicated background thread.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._consumer = Consumer({
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": auto_offset_reset,
            "enable.auto.commit": False,
            "max.poll.interval.ms": 300000,
            "session.timeout.ms": 30000,
            "heartbeat.interval.ms": 10000,
        })
        self._dlq_producer: Optional[CDSKafkaProducer] = None
        self._running = False
        self._shutdown_event = threading.Event()

    def set_dlq_producer(self, producer: CDSKafkaProducer) -> None:
        self._dlq_producer = producer

    def consume(
        self,
        topics: List[str],
        handler: Callable[[Dict[str, Any], Dict[str, str]], None],
        max_poll_records: int = 100,
        poll_timeout_seconds: float = 1.0,
    ) -> None:
        """
        Subscribe and process messages until shutdown() is called.
        handler(value: dict, headers: dict) — raise DLQException to route to DLQ.
        """
        self._consumer.subscribe(topics)
        self._running = True
        logger.info(
            "kafka_consumer_started",
            topics=topics,
            group_id=self._consumer.memberid() or "unknown",
        )

        try:
            while self._running and not self._shutdown_event.is_set():
                messages = self._consumer.consume(
                    num_messages=max_poll_records,
                    timeout=poll_timeout_seconds,
                )
                for msg in messages:
                    if msg is None:
                        continue
                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        logger.error("kafka_consumer_error", error=str(msg.error()))
                        continue
                    try:
                        value = json.loads(msg.value().decode("utf-8"))
                        headers = {
                            k: v.decode("utf-8") if isinstance(v, bytes) else v
                            for k, v in (msg.headers() or [])
                        }
                        handler(value, headers)
                        self._consumer.commit(message=msg, asynchronous=False)
                    except DLQException as dlq_err:
                        self._send_to_dlq(msg, dlq_err.reason)
                        self._consumer.commit(message=msg, asynchronous=False)
                    except Exception as e:
                        # No silent failures
                        logger.error(
                            "kafka_handler_failed",
                            topic=msg.topic(),
                            partition=msg.partition(),
                            offset=msg.offset(),
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        self._consumer.commit(message=msg, asynchronous=False)
        except KafkaException as e:
            logger.error("kafka_consumer_fatal_error", error=str(e))
            raise
        finally:
            self._consumer.close()
            logger.info("kafka_consumer_closed")

    def _send_to_dlq(self, original_msg, reason: str) -> None:
        if not self._dlq_producer:
            logger.error(
                "dlq_producer_not_set",
                topic=original_msg.topic(),
                reason=reason,
            )
            return
        dlq_topic = f"dlq.{original_msg.topic()}"
        try:
            raw_value = json.loads(original_msg.value().decode("utf-8"))
            self._dlq_producer.publish(
                topic=dlq_topic,
                key=original_msg.key().decode("utf-8") if original_msg.key() else "unknown",
                value={
                    "original_topic": original_msg.topic(),
                    "original_partition": original_msg.partition(),
                    "original_offset": original_msg.offset(),
                    "original_value": raw_value,
                    "failure_reason": reason,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            logger.warning(
                "message_sent_to_dlq",
                original_topic=original_msg.topic(),
                dlq_topic=dlq_topic,
                reason=reason,
            )
        except Exception as e:
            logger.error("dlq_publish_failed", error=str(e))

    def shutdown(self) -> None:
        self._running = False
        self._shutdown_event.set()
        logger.info("kafka_consumer_shutdown_requested")
