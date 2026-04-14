"""
Notification Service — Module M14
Handles multi-channel alert delivery (Email, SMS, In-App).
Connects to the alert rule engine and manages escalation.
"""
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from cds_shared.config import settings
from cds_shared.database import init_db
from cds_shared.kafka_client import CDSKafkaProducer
from cds_shared.audit import AuditProducer
from cds_shared.observability import setup_tracing, setup_metrics, CDSTracingMiddleware

# ── Logging setup ─────────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup."""
    logger.info("notification_service_starting", service=settings.SERVICE_NAME)

    # 1. Database
    init_db(settings.DATABASE_URL)

    # 2. Kafka producer
    kafka_producer = CDSKafkaProducer(settings.KAFKA_BOOTSTRAP_SERVERS)
    audit_producer = AuditProducer(kafka_producer)
    app.state.kafka_producer = kafka_producer
    app.state.audit_producer = audit_producer

    # 3. Observability
    setup_tracing(settings.SERVICE_NAME, settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    setup_metrics(settings.SERVICE_NAME)

    logger.info("notification_service_ready")
    yield

    # Shutdown
    logger.info("notification_service_stopping")
    kafka_producer.close()
    logger.info("notification_service_stopped")


app = FastAPI(
    title="CDS Notification Service",
    description="Multi-channel delivery for city-wide alerts",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tracing
app.add_middleware(CDSTracingMiddleware, service_name=settings.SERVICE_NAME)

# Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health/live", tags=["health"])
async def liveness():
    return {"status": "alive", "service": settings.SERVICE_NAME}


@app.get("/health/ready", tags=["health"])
async def readiness():
    checks = {}
    overall = "ready"

    try:
        from cds_shared.database import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        overall = "degraded"

    return JSONResponse(
        status_code=200 if overall == "ready" else 503,
        content={"status": overall, "checks": checks, "service": settings.SERVICE_NAME},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=str(request.url.path),
        trace_id=trace_id,
    )
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "trace_id": trace_id},
    )
