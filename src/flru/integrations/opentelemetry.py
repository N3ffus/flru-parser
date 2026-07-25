from __future__ import annotations

from ..observability import RequestEvent


class OpenTelemetryEventHandler:
    """Emit lightweight events to the current OpenTelemetry span."""

    def __init__(self) -> None:
        try:
            from opentelemetry import trace
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install flru-parser[observability]") from exc
        self._trace = trace

    def __call__(self, event: RequestEvent) -> None:
        span = self._trace.get_current_span()
        span.add_event(
            f"flru.{event.phase}",
            {
                "http.request.method": event.method,
                "url.full": event.url,
                "flru.endpoint": event.endpoint,
                "flru.attempt": event.attempt,
                "http.response.status_code": event.status_code or 0,
                "flru.elapsed": event.elapsed or 0.0,
                "flru.error": event.error or "",
            },
        )
