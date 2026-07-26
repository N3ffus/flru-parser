from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from time import monotonic

from .config import ProxyConfig
from .security import redact_url


@dataclass(slots=True)
class ProxyState:
    url: str | None
    failures: int = 0
    successes: int = 0
    cooldown_until: float = 0.0
    last_error: str | None = None

    @property
    def available(self) -> bool:
        return monotonic() >= self.cooldown_until

    @property
    def safe_url(self) -> str | None:
        return redact_url(self.url)


class ProxyPool:
    """Health-aware proxy selector. A ``None`` URL represents direct access."""

    def __init__(self, config: ProxyConfig) -> None:
        self._states = [ProxyState(url=url) for url in config.urls]
        self._direct = ProxyState(url=None)
        self._config = config
        self._index = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> ProxyState:
        while True:
            async with self._lock:
                available = [state for state in self._states if state.available]
                if available:
                    if self._config.strategy == "random":
                        return random.choice(available)
                    for _ in range(len(self._states)):
                        state = self._states[self._index % len(self._states)]
                        self._index += 1
                        if state.available:
                            return state
                    return available[0]
                if not self._states or self._config.direct_fallback:
                    return self._direct
                wait = max(
                    0.01,
                    min(state.cooldown_until for state in self._states) - monotonic(),
                )
            await asyncio.sleep(wait)

    async def success(self, state: ProxyState) -> None:
        async with self._lock:
            state.successes += 1
            state.failures = max(0, state.failures - 1)
            state.last_error = None

    async def failure(self, state: ProxyState, error: Exception) -> None:
        async with self._lock:
            state.last_error = type(error).__name__
            if state.url is None:
                return
            state.failures += 1
            if state.failures >= self._config.max_failures:
                state.cooldown_until = monotonic() + self._config.cooldown
                state.failures = 0

    async def snapshot(self) -> list[ProxyState]:
        async with self._lock:
            states = [*self._states]
            if self._config.direct_fallback or not states:
                states.append(self._direct)
            return [
                ProxyState(
                    url=state.safe_url,
                    failures=state.failures,
                    successes=state.successes,
                    cooldown_until=state.cooldown_until,
                    last_error=state.last_error,
                )
                for state in states
            ]
