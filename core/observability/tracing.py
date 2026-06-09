"""OpenTelemetry tracing setup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.config.settings import settings
from core.logging.logger import get_logger, log_info

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = get_logger(__name__)


def setup_tracing(app: FastAPI) -> None:
    """Configure OTLP tracing and auto-instrumentation for FastAPI, httpx, asyncpg."""
    if not settings.observability.enabled:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

    resource = Resource.create(
        {
            "service.name": settings.observability.service_name,
            "deployment.environment": settings.app.environment,
        }
    )
    sampler = TraceIdRatioBased(settings.observability.traces_sample_rate)
    provider = TracerProvider(resource=resource, sampler=sampler)
    exporter = OTLPSpanExporter(
        endpoint=settings.observability.otlp_endpoint,
        insecure=settings.observability.otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/metrics,/health/live,/health/ready",
    )
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()
    LoggingInstrumentor().instrument(set_logging_format=False)

    log_info(
        logger,
        "OpenTelemetry tracing initialized",
        endpoint=settings.observability.otlp_endpoint,
        sample_rate=settings.observability.traces_sample_rate,
    )
