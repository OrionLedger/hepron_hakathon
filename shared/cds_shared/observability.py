"""
OpenTelemetry tracing and Prometheus metrics setup.
Call setup_tracing() and setup_metrics() once during service startup.
"""
from __future__ import annotations

import functools
import time
from typing import Callable, Optional

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)

http_requests_total = Counter(
    "cds_http_requests_total",
    "Total HTTP requests",
    ["service", "method", "endpoint", "status_code"],
)
http_request_duration_seconds = Histogram(
    "cds_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)


def setup_tracing(service_name: str, otlp_endpoint: str) -> None:
    """Configure OpenTelemetry with OTLP gRPC exporter."""
    resource = Resource.create({"service.name": service_name})
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("tracing_initialized", service=service_name)


def get_tracer(name: Optional[str] = None) -> trace.Tracer:
    return trace.get_tracer(name or __name__)


def setup_metrics(service_name: str) -> None:
    logger.info("metrics_initialized", service=service_name)


def instrument_fastapi(app) -> None:
    FastAPIInstrumentor.instrument_app(app)


def trace_function(span_name: Optional[str] = None) -> Callable:
    """Decorator that wraps a function in an OpenTelemetry span."""
    def decorator(func: Callable) -> Callable:
        name = span_name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            with tracer.start_as_current_span(name) as span:
                try:
                    result = func(*args, **kwargs)
                    span.set_attribute("outcome", "success")
                    return result
                except Exception as e:
                    span.set_attribute("outcome", "error")
                    span.record_exception(e)
                    raise
        return wrapper
    return decorator


class CDSTracingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware: creates a span per request, records metrics,
    and injects X-Trace-ID into the response.
    """

    def __init__(self, app, service_name: str) -> None:
        super().__init__(app)
        self._service_name = service_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        tracer = get_tracer()
        start_time = time.perf_counter()

        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("service.name", self._service_name)

            ctx = trace.get_current_span().get_span_context()
            trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else "unknown"
            request.state.trace_id = trace_id

            response = await call_next(request)

            duration = time.perf_counter() - start_time
            span.set_attribute("http.status_code", response.status_code)

            http_requests_total.labels(
                service=self._service_name,
                method=request.method,
                endpoint=request.url.path,
                status_code=str(response.status_code),
            ).inc()
            http_request_duration_seconds.labels(
                service=self._service_name,
                method=request.method,
                endpoint=request.url.path,
            ).observe(duration)

            response.headers["X-Trace-ID"] = trace_id
            return response
