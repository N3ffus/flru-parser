from __future__ import annotations

import asyncio

import httpx
import pytest

from flru import ClientConfig, FLClient, RateLimitConfig, RetryConfig
from flru.exceptions import AuthenticationRequired, BlockedError, HTTPStatusError, SecurityError
from flru.security import redact_url, validate_url


def config(**kwargs):
    return ClientConfig(
        respect_robots_txt=False,
        retry=RetryConfig(max_attempts=2, base_delay=0, max_delay=0, jitter=0, total_timeout=10, max_total_delay=1),
        rate_limit=RateLimitConfig(requests_per_second=1000, burst=10, max_concurrency=5),
        **kwargs,
    )


def test_url_security_and_redaction() -> None:
    assert redact_url("http://user:pass@proxy.local:8080/x?token=abc") == "http://user:***@proxy.local:8080/x?token=***"
    assert validate_url("https://st.fl.ru/x", frozenset({"fl.ru"}), True).endswith("/x")
    with pytest.raises(SecurityError):
        validate_url("ftp://www.fl.ru/x", frozenset({"fl.ru"}), True)
    with pytest.raises(SecurityError):
        validate_url("https://evil.test/x", frozenset({"fl.ru"}), True)


@pytest.mark.asyncio
async def test_safe_redirect_and_external_redirect_rejected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"}, request=request)
        if request.url.path == "/external":
            return httpx.Response(302, headers={"Location": "https://evil.test/x"}, request=request)
        return httpx.Response(200, text="ok", request=request)

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        assert await client.get_html("/start") == "ok"
        with pytest.raises(SecurityError):
            await client.get_html("/external")


@pytest.mark.asyncio
async def test_block_auth_status_and_event_handler_failure() -> None:
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/blocked":
            return httpx.Response(200, text="Подтвердите, что вы не робот", request=request)
        if request.url.path == "/auth":
            return httpx.Response(401, request=request)
        return httpx.Response(404, request=request)

    def broken_event(_event):
        raise RuntimeError("event failed")

    async with FLClient(config(), transport=httpx.MockTransport(handler), event_handler=broken_event) as client:
        with pytest.raises(BlockedError):
            await client.get_html("/blocked")
        with pytest.raises(AuthenticationRequired):
            await client.get_html("/auth")
        with pytest.raises(HTTPStatusError):
            await client.get_html("/not-found")
        assert (await client.metrics()).event_handler_failures_total > 0


@pytest.mark.asyncio
async def test_retry_after_and_stable_user_agent(monkeypatch) -> None:
    agents: list[str] = []
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        agents.append(request.headers["User-Agent"])
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, text="ok", request=request)

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        assert await client.get_html("/x") == "ok"
        assert agents[0] == agents[1]
        assert (await client.metrics()).rate_limited_total == 1


@pytest.mark.asyncio
async def test_shared_limiter_pause() -> None:
    from flru.config import RateLimitConfig
    from flru.resilience import AsyncRateLimiter

    limiter = AsyncRateLimiter(RateLimitConfig(requests_per_second=1000, max_concurrency=1))
    await limiter.pause_for(0.01)
    started = asyncio.get_running_loop().time()
    async with limiter:
        pass
    assert asyncio.get_running_loop().time() - started >= 0.005
