from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import structlog

from cds_shared.database import get_db
from models.alerts import AlertRule as AlertRuleModel
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/rules", tags=["alert_rules"])
logger = structlog.get_logger(__name__)

# Basic Pydantic schema for Rule
class AlertRuleSchema(BaseModel):
    name: str
    description: str
    kpi_id: int
    trigger_type: str
    condition: dict
    severity: str = "P3"
    cooldown_minutes: int = 15
    is_active: bool = True

@router.post("/", status_code=status.HTTP_201_CREATED)
def create_rule(rule: AlertRuleSchema, db: Session = Depends(get_db)):
    """Create a new alert rule."""
    db_rule = AlertRuleModel(**rule.model_dump())
    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return db_rule

@router.get("/", response_model=List[AlertRuleSchema])
def list_rules(kpi_id: int = None, db: Session = Depends(get_db)):
    """List all alert rules."""
    query = db.query(AlertRuleModel)
    if kpi_id:
        query = query.filter(AlertRuleModel.kpi_id == kpi_id)
    return query.all()

@router.get("/{rule_id}")
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    """Get a specific alert rule."""
    rule = db.query(AlertRuleModel).filter(AlertRuleModel.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule
