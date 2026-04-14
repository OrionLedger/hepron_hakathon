from fastapi import APIRouter, Request, HTTPException, Depends, status
from typing import List
import structlog

from cds_shared.schemas.events import EventEnvelope, Topics
from cds_shared.config import settings
from models.ingestion import IngestionBatchRequest

router = APIRouter(prefix="/v1/ingest", tags=["ingestion"])
logger = structlog.get_logger(__name__)

@router.post("/{dept_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_department_events(
    dept_id: str,
    request: IngestionBatchRequest,
    fastapi_request: Request
):
    """
    Ingest a batch of events for a specific department.
    Validated events are wrapped in an EventEnvelope and published to Kafka.
    """
    kafka_producer = fastapi_request.app.state.kafka_producer
    audit_producer = fastapi_request.app.state.audit_producer
    
    success_count = 0
    errors = []
    
    topic = Topics.raw(dept_id, request.entity_type)
    
    for event in request.events:
        try:
            # Wrap in envelope
            envelope = EventEnvelope(
                event_type=f"raw_{request.entity_type}_ingested",
                source_service=settings.SERVICE_NAME,
                payload={
                    "dept_id": dept_id,
                    "entity_type": request.entity_type,
                    "entity_id": event.entity_id,
                    "source_timestamp": event.timestamp,
                    "data": event.data,
                    "batch_metadata": request.metadata
                }
            )
            
            # Publish to Kafka
            kafka_producer.produce(topic, envelope.model_dump())
            success_count += 1
            
        except Exception as e:
            logger.error("ingestion_failed", error=str(e), dept_id=dept_id, entity_id=event.entity_id)
            errors.append({"entity_id": event.entity_id, "error": str(e)})

    # Audit the ingestion action
    await audit_producer.produce_audit_event(
        action="DATA_INGESTION",
        resource_type="department_data",
        resource_id=dept_id,
        user_id="system_ingestor", # In production, this would come from Auth JWT
        result="success" if not errors else "partial_success",
        payload={
            "dept_id": dept_id,
            "entity_type": request.entity_type,
            "record_count": len(request.events),
            "success_count": success_count,
            "error_count": len(errors)
        }
    )

    if success_count == 0 and request.events:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "All ingestion attempts failed", "errors": errors}
        )

    return {
        "status": "accepted",
        "dept_id": dept_id,
        "topic": topic,
        "processed_count": success_count,
        "failed_count": len(errors),
        "errors": errors if errors else None
    }
