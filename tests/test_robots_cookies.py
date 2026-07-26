from __future__ import annotations

from pathlib import Path

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
async def test_robots_policy_success_and_cache() -> None:
    calls = 0

    async def fetch_text(_url: str) -> str:
        nonlocal calls
        calls += 1
        return "User-agent: *\nDisallow: /private/"

    policy = RobotsPolicy(
        base_url="https://www.fl.ru",
        user_agent="test",
        fetch_text=fetch_text,
        cache_ttl=60,
        fail_closed=False,
    )
    assert await policy.allowed("https://www.fl.ru/projects/")
    assert not await policy.allowed("https://www.fl.ru/private/x")
    assert calls == 1


@pytest.mark.asyncio
async def test_robots_policy_failure_modes() -> None:
    calls = 0

    async def fail(_url: str) -> str:
        nonlocal calls
        calls += 1
        raise OSError("offline")

    open_policy = RobotsPolicy(
        base_url="https://www.fl.ru",
        user_agent="test",
        fetch_text=fail,
        cache_ttl=60,
        fail_closed=False,
    )
    closed_policy = RobotsPolicy(
        base_url="https://www.fl.ru",
        user_agent="test",
        fetch_text=fail,
        cache_ttl=60,
        fail_closed=True,
    )
    assert await open_policy.allowed("https://www.fl.ru/x")
    assert await open_policy.allowed("https://www.fl.ru/x")
    assert not await closed_policy.allowed("https://www.fl.ru/x")
    assert calls == 2
