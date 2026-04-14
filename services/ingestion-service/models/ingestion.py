from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class IngestionEvent(BaseModel):
    """A single data record being ingested."""
    entity_id: str = Field(..., description="Unique ID of the asset/sensor/record in the source system")
    timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp from source. If null, server time is used.")
    data: Dict[str, Any] = Field(..., description="The actual sensor readings or record fields")

class IngestionBatchRequest(BaseModel):
    """Request body for batched ingestion."""
    entity_type: str = Field(..., description="The type of entity, e.g. 'water_meter', 'traffic_counter'")
    events: List[IngestionEvent]
    metadata: Optional[Dict[str, Any]] = None
