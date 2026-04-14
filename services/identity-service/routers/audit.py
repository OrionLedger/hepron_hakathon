"""
Audit log query router. Requires auditor role.
Cursor-based pagination — never offset-based.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session

from cds_shared.auth.middleware import AuthContext, require_auth
from cds_shared.database import get_db
from cds_shared.config import settings
from models.audit_log import AuditLog, AuditLogResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/audit", tags=["audit"])


def _meta(request: Request) -> dict:
    return {
        "request_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": settings.SERVICE_NAME,
    }


def _encode_cursor(event_id: str, timestamp: str) -> str:
    payload = json.dumps({"event_id": event_id, "timestamp": timestamp})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        return json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@router.get("/events", response_model=dict)
async def list_audit_events(
    request: Request,
    actor_id: Optional[str] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    outcome: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    cursor: Optional[str] = None,
    limit: int = Query(default=50, le=200, ge=1),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["audit:read:all"])),
):
    """
    Query audit events with optional filters and cursor-based pagination.
    Requires auditor role.
    """
    filters = []

    if actor_id:
        filters.append(AuditLog.actor_id == actor_id)
    if action:
        filters.append(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        filters.append(AuditLog.resource_type == resource_type)
    if resource_id:
        filters.append(AuditLog.resource_id == resource_id)
    if outcome:
        filters.append(AuditLog.outcome == outcome)
    if from_date:
        filters.append(AuditLog.timestamp >= from_date)
    if to_date:
        filters.append(AuditLog.timestamp <= to_date)

    # Cursor-based pagination
    if cursor:
        cursor_data = _decode_cursor(cursor)
        filters.append(AuditLog.timestamp <= cursor_data["timestamp"])
        filters.append(AuditLog.event_id != cursor_data["event_id"])

    query = db.query(AuditLog)
    if filters:
        query = query.filter(and_(*filters))

    query = query.order_by(AuditLog.timestamp.desc())
    events = query.limit(limit + 1).all()

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    next_cursor = None
    if has_more and events:
        last = events[-1]
        next_cursor = _encode_cursor(last.event_id, last.timestamp.isoformat())

    return {
        "data": [AuditLogResponse.model_validate(e).model_dump() for e in events],
        "meta": {
            **_meta(request),
            "next_cursor": next_cursor,
            "has_more": has_more,
            "count": len(events),
        },
    }


@router.get("/events/{event_id}", response_model=dict)
async def get_audit_event(
    event_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth(["audit:read:all"])),
):
    """Get a single audit event by ID. Requires auditor role."""
    event = db.query(AuditLog).filter(AuditLog.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return {"data": AuditLogResponse.model_validate(event).model_dump(), "meta": _meta(request)}
