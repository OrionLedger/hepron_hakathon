from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import structlog

from cds_shared.database import get_db
from models.kpi import KPIDefinition as KPIDefModel
from cds_shared.schemas.canonical import KPIDefinition as KPIDefSchema

router = APIRouter(prefix="/v1/kpis", tags=["registry"])
logger = structlog.get_logger(__name__)

@router.post("/", response_model=KPIDefSchema, status_code=status.HTTP_201_CREATED)
def create_kpi(kpi: KPIDefSchema, db: Session = Depends(get_db)):
    """Register a new KPI in the system."""
    db_kpi = KPIDefModel(
        name=kpi.name,
        description=kpi.description,
        formula=kpi.formula,
        unit=kpi.unit,
        owner_dept_id=kpi.owner_dept_id,
        update_freq_minutes=kpi.update_frequency_seconds // 60,
        thresholds={"amber": kpi.warning_threshold, "red": kpi.critical_threshold},
        version=kpi.version
    )
    db.add(db_kpi)
    db.commit()
    db.refresh(db_kpi)
    
    # Return as schema
    return KPIDefSchema(
        kpi_id=str(db_kpi.id),
        name=db_kpi.name,
        description=db_kpi.description,
        formula=db_kpi.formula,
        source_datasets=[], # This needs to be parsed from formula in a real system
        unit=db_kpi.unit,
        owner_dept_id=db_kpi.owner_dept_id,
        update_frequency_seconds=db_kpi.update_freq_minutes * 60,
        version=db_kpi.version,
        warning_threshold=db_kpi.thresholds.get("amber"),
        critical_threshold=db_kpi.thresholds.get("red")
    )

@router.get("/", response_model=List[KPIDefSchema])
def list_kpis(dept_id: str = None, db: Session = Depends(get_db)):
    """List all registered KPIs, optionally filtered by department."""
    query = db.query(KPIDefModel)
    if dept_id:
        query = query.filter(KPIDefModel.owner_dept_id == dept_id)
    
    results = query.all()
    return [
        KPIDefSchema(
            kpi_id=str(k.id),
            name=k.name,
            description=k.description,
            formula=k.formula,
            source_datasets=[],
            unit=k.unit,
            owner_dept_id=k.owner_dept_id,
            update_frequency_seconds=k.update_freq_minutes * 60,
            version=k.version,
            warning_threshold=k.thresholds.get("amber"),
            critical_threshold=k.thresholds.get("red")
        ) for k in results
    ]

@router.get("/{kpi_id}", response_model=KPIDefSchema)
def get_kpi(kpi_id: int, db: Session = Depends(get_db)):
    """Get detailed definition for a specific KPI."""
    k = db.query(KPIDefModel).filter(KPIDefModel.id == kpi_id).first()
    if not k:
        raise HTTPException(status_code=404, detail="KPI not found")
        
    return KPIDefSchema(
        kpi_id=str(k.id),
        name=k.name,
        description=k.description,
        formula=k.formula,
        source_datasets=[],
        unit=k.unit,
        owner_dept_id=k.owner_dept_id,
        update_frequency_seconds=k.update_freq_minutes * 60,
        version=k.version,
        warning_threshold=k.thresholds.get("amber"),
        critical_threshold=k.thresholds.get("red")
    )
