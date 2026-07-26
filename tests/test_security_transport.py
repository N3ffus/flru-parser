from __future__ import annotations

import asyncio

import httpx
import pytest

from flru import ClientConfig, FLClient, RateLimitConfig, RetryConfig
from flru.client import _gather_batch_or_stop_on_block
from flru.exceptions import AuthenticationRequired, BlockedError, HTTPStatusError, SecurityError
from flru.security import redact_url, validate_url


def config(**kwargs):
    return ClientConfig(
        respect_robots_txt=False,
        retry=RetryConfig(
            max_attempts=2, base_delay=0, max_delay=0, jitter=0, total_timeout=10, max_total_delay=1
        ),
        rate_limit=RateLimitConfig(requests_per_second=1000, burst=10, max_concurrency=5),
        **kwargs,
    )


def test_url_security_and_redaction() -> None:
    assert (
        redact_url("http://user:pass@proxy.local:8080/x?token=abc")
        == "http://***@proxy.local:8080/x?token=***"
    )
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
async def test_block_auth_status_and_event_handler_failure(tmp_path, monkeypatch) -> None:
    paths: list[str] = []
    monkeypatch.chdir(tmp_path)

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/blocked":
            return httpx.Response(
                403,
                text="<html><title>Access denied</title><div class='g-recaptcha'></div></html>",
                headers={"Set-Cookie": "session=secret", "X-Debug": "safe"},
                request=request,
            )
        if request.url.path == "/auth":
            return httpx.Response(401, request=request)
        return httpx.Response(404, request=request)

    def broken_event(_event):
        raise RuntimeError("event failed")

    async with FLClient(
        config(blocked_dump_directory=".flru-debug"),
        transport=httpx.MockTransport(handler),
        event_handler=broken_event,
    ) as client:
        with pytest.raises(BlockedError) as blocked:
            await client.get_html("/blocked")
        with pytest.raises(AuthenticationRequired):
            await client.get_html("/auth")
        with pytest.raises(HTTPStatusError):
            await client.get_html("/not-found")
        assert (await client.metrics()).event_handler_failures_total > 0

    assert blocked.value.status_code == 403
    assert blocked.value.debug_path is not None
    assert (blocked.value.debug_path / "response.html").read_text() == (
        "<html><title>Access denied</title><div class='g-recaptcha'></div></html>"
    )
    metadata = (blocked.value.debug_path / "metadata.json").read_text(encoding="utf-8")
    assert '"x-debug": "safe"' in metadata
    assert "Set-Cookie" not in metadata
    assert "secret" not in metadata
    assert paths.count("/blocked") == 1


@pytest.mark.asyncio
async def test_captcha_word_in_normal_script_is_not_a_block() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><script>analytics.track('captcha_seen')</script><main>ok</main></html>",
            request=request,
        )

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        assert "captcha_seen" in await client.get_html("/normal")


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
async def test_server_cookies_persist_for_following_requests() -> None:
    received_cookies: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        received_cookies.append(request.headers.get("Cookie", ""))
        if len(received_cookies) == 1:
            return httpx.Response(
                200, headers={"Set-Cookie": "session=token; Path=/"}, request=request
            )
        return httpx.Response(200, text="ok", request=request)

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.get_html("/first")
        await client.get_html("/second")

    assert "session=token" in received_cookies[1]


@pytest.mark.asyncio
async def test_batch_work_is_cancelled_when_a_block_is_detected() -> None:
    cancellation_observed = asyncio.Event()

    async def blocked() -> None:
        raise BlockedError("blocked")

    async def pending() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancellation_observed.set()

    with pytest.raises(BlockedError, match="blocked"):
        await _gather_batch_or_stop_on_block([blocked(), pending()])

    assert cancellation_observed.is_set()


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


@pytest.mark.asyncio
async def test_cross_origin_redirect_strips_explicit_credentials() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.fl.ru":
            return httpx.Response(
                302, headers={"Location": "https://st.fl.ru/final"}, request=request
            )
        seen.update(request.headers)
        return httpx.Response(200, text="ok", request=request)

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.request(
            "GET",
            "/start",
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "Proxy-Authorization": "Basic secret",
                "X-Safe": "yes",
            },
        )

    assert "authorization" not in seen
    assert "proxy-authorization" not in seen
    assert seen["x-safe"] == "yes"


@pytest.mark.asyncio
async def test_cross_origin_redirect_strips_default_credentials_and_cookie_jar() -> None:
    seen: httpx.Headers | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        if request.url.host == "www.fl.ru":
            return httpx.Response(
                302,
                headers={
                    "Location": "https://st.fl.ru/final",
                    "Set-Cookie": "server=secret; Domain=.fl.ru; Path=/",
                },
                request=request,
            )
        seen = request.headers
        return httpx.Response(200, text="ok", request=request)

    async with FLClient(
        config(
            headers={"Authorization": "Bearer default"},
            cookies={"configured": "secret"},
        ),
        transport=httpx.MockTransport(handler),
    ) as client:
        await client.get_html("/start")

    assert seen is not None
    assert "authorization" not in seen
    assert "cookie" not in seen
    assert "proxy-authorization" not in seen


@pytest.mark.asyncio
async def test_https_to_http_redirect_is_rejected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"Location": "http://www.fl.ru/final"}, request=request
        )

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SecurityError, match="HTTPS to HTTP"):
            await client.get_html("/start")


@pytest.mark.asyncio
async def test_same_origin_redirect_keeps_explicit_credentials() -> None:
    seen = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/final"}, request=request)
        seen = request.headers.get("Authorization", "")
        return httpx.Response(200, text="ok", request=request)

    async with FLClient(config(), transport=httpx.MockTransport(handler)) as client:
        await client.request("GET", "/start", headers={"Authorization": "Bearer safe"})

    assert seen == "Bearer safe"
