"""
Identity Service — Module M16
Provides authentication, RBAC/ABAC, user management, and audit persistence.
This service is the security foundation for the entire CDS platform.
All other services validate JWT tokens against /v1/auth/verify.
"""
import logging
import threading
from contextlib import asynccontextmanager
from typing import Optional

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

from routers import auth, users, roles
from routers import audit as audit_router
from workers.audit_consumer import AuditConsumerWorker

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
    """Initialize all resources on startup, clean up gracefully on shutdown."""
    logger.info("identity_service_starting", service=settings.SERVICE_NAME)

    # 1. Database
    init_db(settings.DATABASE_URL)

    # 2. Kafka producer + audit producer
    kafka_producer = CDSKafkaProducer(settings.KAFKA_BOOTSTRAP_SERVERS)
    audit_producer = AuditProducer(kafka_producer)
    app.state.kafka_producer = kafka_producer
    app.state.audit_producer = audit_producer

    # 3. Audit consumer worker (background thread)
    audit_worker = AuditConsumerWorker(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        database_url=settings.DATABASE_URL,
    )
    consumer_thread = threading.Thread(
        target=audit_worker.run,
        daemon=True,
        name="audit-consumer-thread",
    )
    consumer_thread.start()

    # 4. Observability
    setup_tracing(settings.SERVICE_NAME, settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    setup_metrics(settings.SERVICE_NAME)

    logger.info("identity_service_ready")
    yield

    # Shutdown
    logger.info("identity_service_stopping")
    audit_worker.stop()
    kafka_producer.close()
    logger.info("identity_service_stopped")


app = FastAPI(
    title="CDS Identity Service",
    description="Authentication, RBAC/ABAC, user management, and audit log persistence",
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

# Routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(audit_router.router)


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

    try:
        import redis as redis_lib
        r = redis_lib.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            socket_timeout=2,
        )
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"
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
