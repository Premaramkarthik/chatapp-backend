"""Minimal Prometheus-compatible metrics registry."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

from core.observability.metric import HttpMetric


class MetricsRegistry:
    """In-process metrics registry exposed in Prometheus text format."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._http_requests: dict[tuple[str, str, str], HttpMetric] = defaultdict(HttpMetric)
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._totals: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)

    def record_http_request(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record an HTTP request observation."""
        status_class = f"{status_code // 100}xx"
        key = (method, path, status_class)
        with self._lock:
            metric = self._http_requests[key]
            metric.count += 1
            metric.duration_seconds_total += duration_seconds

    def render_prometheus(self) -> str:
        """Render metrics using the Prometheus text exposition format."""
        lines = [
            "# HELP chatapp_http_requests_total Total HTTP requests.",
            "# TYPE chatapp_http_requests_total counter",
        ]
        with self._lock:
            snapshot = dict(self._http_requests)

        for (method, path, status_class), metric in sorted(snapshot.items()):
            labels = _labels(method=method, path=path, status_class=status_class)
            lines.append(f"chatapp_http_requests_total{{{labels}}} {metric.count}")

        lines.extend(
            [
                "# HELP chatapp_http_request_duration_seconds_total "
                "Total HTTP request duration in seconds.",
                "# TYPE chatapp_http_request_duration_seconds_total counter",
            ]
        )
        for (method, path, status_class), metric in sorted(snapshot.items()):
            labels = _labels(method=method, path=path, status_class=status_class)
            lines.append(
                "chatapp_http_request_duration_seconds_total"
                f"{{{labels}}} {metric.duration_seconds_total:.6f}"
            )

        with self._lock:
            counters = dict(self._counters)
        for (name, labels_tuple), count in sorted(counters.items()):
            lines.extend(
                [
                    f"# HELP chatapp_{name} Application counter.",
                    f"# TYPE chatapp_{name} counter",
                ]
            )
            labels = ",".join(
                f'{_escape_label(key)}="{_escape_label(value)}"' for key, value in labels_tuple
            )
            suffix = f"{{{labels}}}" if labels else ""
            lines.append(f"chatapp_{name}{suffix} {count}")

        with self._lock:
            totals = dict(self._totals)
        for (name, labels_tuple), value in sorted(totals.items()):
            lines.extend(
                [
                    f"# HELP chatapp_{name} Application observed total.",
                    f"# TYPE chatapp_{name} counter",
                ]
            )
            labels = ",".join(
                f'{_escape_label(key)}="{_escape_label(value)}"' for key, value in labels_tuple
            )
            suffix = f"{{{labels}}}" if labels else ""
            lines.append(f"chatapp_{name}{suffix} {value:.6f}")

        return "\n".join(lines) + "\n"

    def increment(self, name: str, **labels: str) -> None:
        """Increment a named counter with optional labels."""
        labels_tuple = tuple(sorted((key, str(value)) for key, value in labels.items()))
        with self._lock:
            self._counters[(name, labels_tuple)] += 1

    def observe_total(self, name: str, *, duration_seconds: float, **labels: str) -> None:
        """Add one duration observation to a cumulative total."""
        labels_tuple = tuple(sorted((key, str(value)) for key, value in labels.items()))
        with self._lock:
            self._totals[(name, labels_tuple)] += duration_seconds


def _labels(*, method: str, path: str, status_class: str) -> str:
    return (
        f'method="{_escape_label(method)}",'
        f'path="{_escape_label(path)}",'
        f'status_class="{_escape_label(status_class)}"'
    )


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


metrics_registry = MetricsRegistry()
