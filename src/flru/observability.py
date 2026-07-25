from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from .models import EndpointMetrics, RequestMetrics
from .security import redact_url

logger = logging.getLogger("flru")


@dataclass(slots=True, frozen=True)
class RequestEvent:
    phase: Literal["start", "retry", "success", "failure", "blocked", "parse_failure"]
    method: str
    url: str
    attempt: int
    endpoint: str = "unknown"
    proxy: str | None = None
    status_code: int | None = None
    elapsed: float | None = None
    error: str | None = None

    def safe(self) -> RequestEvent:
        return RequestEvent(
            phase=self.phase,
            method=self.method,
            url=redact_url(self.url) or self.url,
            attempt=self.attempt,
            endpoint=self.endpoint,
            proxy=redact_url(self.proxy),
            status_code=self.status_code,
            elapsed=self.elapsed,
            error=self.error,
        )


EventHandler = Callable[[RequestEvent], None | Awaitable[None]]


class Metrics:
    def __init__(self, *, max_latency_samples: int = 1000) -> None:
        self._data = RequestMetrics()
        self._lock = asyncio.Lock()
        self._max_latency_samples = max_latency_samples

    async def mutate(self, *, endpoint: str | None = None, **changes: int | float) -> None:
        async with self._lock:
            for key, value in changes.items():
                current = getattr(self._data, key)
                setattr(self._data, key, current + value)
            if endpoint:
                item = self._data.endpoints.setdefault(endpoint, EndpointMetrics())
                if "requests_total" in changes:
                    item.requests += int(changes["requests_total"])
                if "failures_total" in changes:
                    item.failures += int(changes["failures_total"])
                if "retries_total" in changes:
                    item.retries += int(changes["retries_total"])
                if "latency_seconds_total" in changes:
                    latency = float(changes["latency_seconds_total"])
                    item.latency_seconds_total += latency
                    self._data.latency_samples.append(latency)
                    if len(self._data.latency_samples) > self._max_latency_samples:
                        del self._data.latency_samples[: len(self._data.latency_samples) // 2]

    async def snapshot(self) -> RequestMetrics:
        async with self._lock:
            return self._data.model_copy(deep=True)


class Timer:
    def __init__(self) -> None:
        self.started = monotonic()

    @property
    def elapsed(self) -> float:
        return monotonic() - self.started


async def emit(handler: EventHandler | None, event: RequestEvent) -> bool:
    """Run an event handler safely. Returns ``False`` when the handler failed."""
    if handler is None:
        return True
    try:
        result = handler(event.safe())
        if inspect.isawaitable(result):
            await result
        return True
    except Exception:
        logger.exception("FL.ru event handler failed")
        return False


class StructuredLogHandler:
    def __init__(self, log: logging.Logger | None = None) -> None:
        self.log = log or logger

    def __call__(self, event: RequestEvent) -> None:
        self.log.info(
            "flru_request",
            extra={
                "flru_phase": event.phase,
                "flru_method": event.method,
                "flru_url": event.url,
                "flru_endpoint": event.endpoint,
                "flru_attempt": event.attempt,
                "flru_proxy": event.proxy,
                "flru_status_code": event.status_code,
                "flru_elapsed": event.elapsed,
                "flru_error": event.error,
            },
        )
