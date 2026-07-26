from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser


class RobotsPolicy:
    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        fetch_text: Callable[[str], Awaitable[str]],
        cache_ttl: float,
        fail_closed: bool,
    ) -> None:
        parts = urlsplit(base_url)
        self._robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        self._user_agent = user_agent
        self._fetch_text = fetch_text
        self._cache_ttl = cache_ttl
        self._fail_closed = fail_closed
        self._parser: RobotFileParser | None = None
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def allowed(self, url: str) -> bool:
        parser = await self._get_parser()
        return (
            not self._fail_closed
            if parser is None
            else parser.can_fetch(self._user_agent, urljoin(self._robots_url, url))
        )

    async def _get_parser(self) -> RobotFileParser | None:
        if self._loaded_at and monotonic() - self._loaded_at < self._cache_ttl:
            return self._parser
        async with self._lock:
            if self._loaded_at and monotonic() - self._loaded_at < self._cache_ttl:
                return self._parser
            try:
                text = await self._fetch_text(self._robots_url)
                parser = RobotFileParser()
                parser.set_url(self._robots_url)
                parser.parse(text.splitlines())
                self._parser, self._loaded_at = parser, monotonic()
                return parser
            except Exception:
                self._loaded_at = monotonic()
                return None
