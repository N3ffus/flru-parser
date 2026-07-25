from __future__ import annotations

from ..observability import RequestEvent


class PrometheusEventHandler:
    """Export request events through prometheus-client.

    Install with ``flru-parser[observability]``.
    """

    def __init__(self, namespace: str = "flru") -> None:
        try:
            from prometheus_client import Counter, Histogram
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install flru-parser[observability]") from exc
        self.requests = Counter(
            f"{namespace}_requests_total",
            "FL.ru parser request events",
            ("phase", "endpoint", "status"),
        )
        self.latency = Histogram(
            f"{namespace}_request_duration_seconds",
            "FL.ru parser request latency",
            ("endpoint",),
        )

    def __call__(self, event: RequestEvent) -> None:
        self.requests.labels(
            phase=event.phase,
            endpoint=event.endpoint,
            status=str(event.status_code or "none"),
        ).inc()
        if event.elapsed is not None and event.phase == "success":
            self.latency.labels(endpoint=event.endpoint).observe(event.elapsed)
