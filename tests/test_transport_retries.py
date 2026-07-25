import httpx
import pytest

from flru import CircuitBreakerConfig, ClientConfig, FLClient, RateLimitConfig, RetryConfig
from flru.exceptions import HTTPStatusError


@pytest.mark.asyncio
async def test_retries_count_as_one_circuit_failure() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    config = ClientConfig(
        retry=RetryConfig(max_attempts=3, base_delay=0, max_delay=0, jitter=0),
        rate_limit=RateLimitConfig(requests_per_second=1000, burst=10, max_concurrency=5),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=2, recovery_timeout=60),
        respect_robots_txt=False,
    )
    transport = httpx.MockTransport(handler)

    async with FLClient(config, transport=transport) as client:
        with pytest.raises(HTTPStatusError):
            await client.get_html("/projects/")

        # The first logical request exhausted all three retries but must count as
        # only one breaker failure, so the next logical request is still admitted.
        with pytest.raises(HTTPStatusError):
            await client.get_html("/projects/")

    assert attempts == 6

@pytest.mark.asyncio
async def test_retry_metrics_are_incremented_once_per_retry() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = 503 if attempts < 3 else 200
        return httpx.Response(status, request=request, text="ok")

    config = ClientConfig(
        retry=RetryConfig(max_attempts=3, base_delay=0, max_delay=0, jitter=0),
        rate_limit=RateLimitConfig(requests_per_second=1000, burst=10, max_concurrency=1),
        circuit_breaker=CircuitBreakerConfig(enabled=False),
        respect_robots_txt=False,
    )

    async with FLClient(config, transport=httpx.MockTransport(handler)) as client:
        response = await client.request("GET", "/projects/")
        metrics = await client.metrics()

    assert response.status_code == 200
    assert attempts == 3
    assert metrics.retries_total == 2
    assert metrics.endpoints["projects"].retries == 2
