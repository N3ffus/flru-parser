from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic

from .config import CircuitBreakerConfig, RateLimitConfig
from .exceptions import CircuitOpenError


class AsyncRateLimiter:
    """Token bucket, concurrency cap, minimum interval, and shared cooldown."""

    def __init__(self, config: RateLimitConfig) -> None:
        self._rate = config.requests_per_second
        self._capacity = max(1, config.burst)
        self._tokens = float(self._capacity)
        self._updated_at = monotonic()
        self._min_interval = config.min_interval
        self._jitter = config.interval_jitter
        self._last_start = 0.0
        self._paused_until = 0.0
        self._lock = asyncio.Lock()
        self._concurrency = asyncio.Semaphore(config.max_concurrency)

    async def __aenter__(self) -> AsyncRateLimiter:
        await self._concurrency.acquire()
        try:
            await self.acquire()
        except BaseException:
            self._concurrency.release()
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        self._concurrency.release()

    async def pause_for(self, seconds: float) -> None:
        async with self._lock:
            self._paused_until = max(self._paused_until, monotonic() + max(0.0, seconds))

    async def acquire(self) -> None:
        while True:
            wait = 0.0
            async with self._lock:
                now = monotonic()
                pause_wait = self._paused_until - now
                if pause_wait > 0:
                    wait = pause_wait
                else:
                    elapsed = now - self._updated_at
                    self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                    self._updated_at = now
                    interval = self._min_interval + random.uniform(0, self._jitter)
                    interval_wait = max(0.0, self._last_start + interval - now)
                    token_wait = 0.0 if self._tokens >= 1 else (1 - self._tokens) / self._rate
                    wait = max(interval_wait, token_wait)
                    if wait <= 0:
                        self._tokens -= 1
                        self._last_start = now
                        return
            await asyncio.sleep(wait)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def before_call(self) -> None:
        if not self._config.enabled:
            return
        async with self._lock:
            if self._state is CircuitState.OPEN:
                if monotonic() - self._opened_at >= self._config.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                else:
                    raise CircuitOpenError("Circuit breaker is open")
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise CircuitOpenError("Circuit breaker is testing recovery")
                self._half_open_calls += 1

    async def record_success(self) -> None:
        if not self._config.enabled:
            return
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._half_open_calls = 0

    async def record_failure(self) -> None:
        if not self._config.enabled:
            return
        async with self._lock:
            self._failures += 1
            if (
                self._state is CircuitState.HALF_OPEN
                or self._failures >= self._config.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = monotonic()
                self._half_open_calls = 0


class CircuitBreakerRegistry:
    def __init__(self, config: CircuitBreakerConfig) -> None:
        self._config = config
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CircuitBreaker:
        async with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = CircuitBreaker(self._config)
                self._breakers[key] = breaker
            return breaker


@dataclass(slots=True)
class RetryBudget:
    total_timeout: float
    max_total_delay: float
    started_at: float = field(init=False)
    total_delay: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.started_at = monotonic()
        self.total_delay = 0.0

    @property
    def elapsed(self) -> float:
        return monotonic() - self.started_at

    @property
    def remaining(self) -> float:
        return max(0.0, self.total_timeout - self.elapsed)

    def allows(self, delay: float = 0.0) -> bool:
        return (
            self.elapsed + delay <= self.total_timeout
            and self.total_delay + delay <= self.max_total_delay
        )

    def consume_delay(self, delay: float) -> None:
        self.total_delay += delay
