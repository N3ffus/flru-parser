from __future__ import annotations

import sys
from types import ModuleType

from flru.observability import RequestEvent


def test_prometheus_adapter(monkeypatch) -> None:
    observed: list[tuple[str, float]] = []

    class Metric:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def labels(self, **_kwargs):
            return self

        def inc(self) -> None:
            observed.append(("inc", 1))

        def observe(self, value: float) -> None:
            observed.append(("observe", value))

    prometheus_client = ModuleType("prometheus_client")
    prometheus_client.Counter = Metric  # type: ignore[attr-defined]
    prometheus_client.Histogram = Metric  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "prometheus_client", prometheus_client)
    from flru.integrations.prometheus import PrometheusEventHandler

    handler = PrometheusEventHandler("test")
    handler(RequestEvent("success", "GET", "https://www.fl.ru", 1, "root", elapsed=0.2))
    assert observed == [("inc", 1), ("observe", 0.2)]


def test_opentelemetry_adapter(monkeypatch) -> None:
    events: list[str] = []

    class Span:
        def add_event(self, name: str, _attributes) -> None:
            events.append(name)

    opentelemetry = ModuleType("opentelemetry")
    trace = ModuleType("opentelemetry.trace")
    trace.get_current_span = lambda: Span()  # type: ignore[attr-defined]
    opentelemetry.trace = trace  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", opentelemetry)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace)
    from flru.integrations.opentelemetry import OpenTelemetryEventHandler

    handler = OpenTelemetryEventHandler()
    handler(RequestEvent("start", "GET", "https://www.fl.ru", 1, "root"))
    assert events == ["flru.start"]
