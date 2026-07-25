from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from flru.cookies import load_netscape_cookies
from flru.robots import RobotsPolicy


def test_load_netscape_cookies(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".fl.ru\tTRUE\t/\tFALSE\t2147483647\tsession\tsecret\n"
        ".example.com\tTRUE\t/\tFALSE\t2147483647\tother\tignored\n",
        encoding="utf-8",
    )
    assert load_netscape_cookies(path) == {"session": "secret"}


@pytest.mark.asyncio
async def test_robots_policy_success_and_cache(monkeypatch) -> None:
    calls = 0

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            nonlocal calls
            calls += 1
            request = httpx.Request("GET", url, headers=headers)
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/", request=request)

    monkeypatch.setattr("flru.robots.httpx.AsyncClient", FakeClient)
    policy = RobotsPolicy(
        base_url="https://www.fl.ru",
        user_agent="test",
        timeout=httpx.Timeout(1),
        verify=True,
        cache_ttl=60,
        fail_closed=False,
    )
    assert await policy.allowed("https://www.fl.ru/projects/")
    assert not await policy.allowed("https://www.fl.ru/private/x")
    assert calls == 1


@pytest.mark.asyncio
async def test_robots_policy_failure_modes(monkeypatch) -> None:
    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, headers):
            _ = headers
            raise httpx.ConnectError("offline")

    monkeypatch.setattr("flru.robots.httpx.AsyncClient", FailingClient)
    open_policy = RobotsPolicy(
        base_url="https://www.fl.ru", user_agent="test", timeout=httpx.Timeout(1),
        verify=True, cache_ttl=60, fail_closed=False,
    )
    closed_policy = RobotsPolicy(
        base_url="https://www.fl.ru", user_agent="test", timeout=httpx.Timeout(1),
        verify=True, cache_ttl=60, fail_closed=True,
    )
    assert await open_policy.allowed("https://www.fl.ru/x")
    assert not await closed_policy.allowed("https://www.fl.ru/x")
