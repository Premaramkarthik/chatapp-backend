"""Minimal Prometheus-compatible metrics registry."""

from dataclasses import dataclass


@dataclass(slots=True)
class HttpMetric:
    """Aggregated HTTP metrics for one route label set."""

    count: int = 0
    duration_seconds_total: float = 0.0
