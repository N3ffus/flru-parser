import asyncio

import pytest

from flru.config import CircuitBreakerConfig, ProxyConfig, RateLimitConfig
from flru.exceptions import CircuitOpenError
from flru.proxy import ProxyPool
from flru.resilience import AsyncRateLimiter, CircuitBreaker


@pytest.mark.asyncio
async def test_circuit_breaker() -> None:
    breaker = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60))
    await breaker.before_call()
    await breaker.record_failure()
    await breaker.before_call()
    await breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        await breaker.before_call()


@pytest.mark.asyncio
async def test_proxy_cooldown() -> None:
    pool = ProxyPool(
        ProxyConfig(
            urls=("http://proxy-1", "http://proxy-2"),
            max_failures=1,
            cooldown=60,
            direct_fallback=False,
        )
    )
    first = await pool.acquire()
    await pool.failure(first, RuntimeError("failed"))
    second = await pool.acquire()
    assert second.url != first.url


@pytest.mark.asyncio
async def test_rate_limiter_concurrency() -> None:
    limiter = AsyncRateLimiter(
        RateLimitConfig(requests_per_second=1000, burst=10, max_concurrency=2)
    )
    active = 0
    maximum = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal active, maximum
        async with limiter:
            async with lock:
                active += 1
                maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1

    await asyncio.gather(*(worker() for _ in range(8)))
    assert maximum <= 2


@pytest.mark.asyncio
async def test_disabled_circuit_breaker_never_opens() -> None:
    breaker = CircuitBreaker(
        CircuitBreakerConfig(enabled=False, failure_threshold=1, recovery_timeout=60)
    )
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.before_call()


@pytest.mark.asyncio
async def test_direct_connection_is_not_put_on_proxy_cooldown() -> None:
    pool = ProxyPool(ProxyConfig(max_failures=1, cooldown=60, direct_fallback=True))
    direct = await pool.acquire()
    assert direct.url is None

    await pool.failure(direct, RuntimeError("network failed"))
    acquired_again = await pool.acquire()

    assert acquired_again.url is None
    assert acquired_again.cooldown_until == 0


@pytest.mark.asyncio
async def test_proxy_snapshot_redacts_credentials() -> None:
    pool = ProxyPool(
        ProxyConfig(
            urls=("http://user:password@proxy.example:8080",),
            direct_fallback=False,
        )
    )

    snapshot = await pool.snapshot()

    assert snapshot[0].url == "http://***@proxy.example:8080"
    assert "password" not in (snapshot[0].url or "")


@pytest.mark.asyncio
async def test_direct_route_is_only_used_after_all_proxies_cool_down() -> None:
    pool = ProxyPool(
        ProxyConfig(
            urls=("http://proxy-1", "http://proxy-2"),
            max_failures=1,
            cooldown=60,
            direct_fallback=True,
        )
    )
    first = await pool.acquire()
    await pool.failure(first, RuntimeError("failed"))
    second = await pool.acquire()
    assert second.url not in {None, first.url}
    await pool.failure(second, RuntimeError("failed"))
    assert (await pool.acquire()).url is None


@pytest.mark.asyncio
async def test_failed_half_open_probe_reopens_and_releases_permit(monkeypatch) -> None:
    now = 0.0
    monkeypatch.setattr("flru.resilience.monotonic", lambda: now)
    breaker = CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=1, recovery_timeout=1, half_open_max_calls=1)
    )
    await breaker.record_failure()
    now = 2.0
    await breaker.before_call()
    await breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        await breaker.before_call()
    now = 4.0
    await breaker.before_call()
    await breaker.record_success()
    assert breaker.state.value == "closed"
