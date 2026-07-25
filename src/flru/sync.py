from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine, Mapping
from pathlib import Path
from typing import Any, TypeVar

import httpx

from .config import ClientConfig
from .easy import Client as AsyncClient
from .easy import CookiesInput, ProxyInput
from .filters import ProjectFilters
from .models import FreelancerSummary, PageData, ProjectDetail, ProjectSummary, RequestMetrics, UserProfile
from .observability import EventHandler
from .state import CrawlStateStore

T = TypeVar("T")


class _LoopThread:
    """Own one event loop in a dedicated thread for the sync facade."""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._main, name="flru-sync", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def run(self, coroutine: Coroutine[Any, Any, T]) -> T:
        if self._loop is None:
            raise RuntimeError("Sync client loop is not available")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def close(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop = None


class Client:
    """Synchronous facade with the same simple API as :class:`flru.Client`."""

    def __init__(
        self,
        *,
        concurrency: int | None = None,
        rps: float | None = None,
        retries: int | None = None,
        timeout: float | None = None,
        proxy: ProxyInput = None,
        cookies: CookiesInput = None,
        strict: bool | None = None,
        respect_robots_txt: bool | None = None,
        http2: bool | None = None,
        verify_ssl: bool | None = None,
        config: ClientConfig | None = None,
        event_handler: EventHandler | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._loop_thread = _LoopThread()
        try:
            self._client = AsyncClient(
                concurrency=concurrency,
                rps=rps,
                retries=retries,
                timeout=timeout,
                proxy=proxy,
                cookies=cookies,
                strict=strict,
                respect_robots_txt=respect_robots_txt,
                http2=http2,
                verify_ssl=verify_ssl,
                config=config,
                event_handler=event_handler,
                transport=transport,
            )
        except BaseException:
            self._loop_thread.close()
            raise
        self._closed = False

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def projects(self, **kwargs: Any) -> list[ProjectSummary] | list[ProjectDetail]:
        return self._loop_thread.run(self._client.projects(**kwargs))

    def project(self, project: int | str) -> ProjectDetail:
        return self._loop_thread.run(self._client.project(project))

    def freelancers(self, **kwargs: Any) -> list[FreelancerSummary]:
        return self._loop_thread.run(self._client.freelancers(**kwargs))

    def user(self, username: str, **kwargs: Any) -> UserProfile:
        return self._loop_thread.run(self._client.user(username, **kwargs))

    def new_projects(
        self,
        state: CrawlStateStore | str | Path = ".flru-state.db",
        **kwargs: Any,
    ) -> list[ProjectSummary]:
        return self._loop_thread.run(self._client.new_projects(state, **kwargs))

    def page(self, url: str) -> PageData:
        return self._loop_thread.run(self._client.page(url))

    def stats(self) -> RequestMetrics:
        return self._loop_thread.run(self._client.stats())

    # Compatibility methods from 0.2.x.
    def get_projects(
        self,
        page: int = 1,
        *,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> list[ProjectSummary]:
        return self._loop_thread.run(
            self._client.get_projects(
                page,
                category=category,
                filters=filters,
                params=params,
            )
        )

    def crawl_projects(self, **kwargs: Any) -> list[ProjectSummary]:
        return self._loop_thread.run(self._client.crawl_projects(**kwargs))

    def get_project(self, project: int | str) -> ProjectDetail:
        return self.project(project)

    def get_user(self, user: str, **kwargs: Any) -> UserProfile:
        return self._loop_thread.run(self._client.get_user(user, **kwargs))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop_thread.run(self._client.close())
        finally:
            self._loop_thread.close()


FLClient = Client


def projects(
    *, client_options: dict[str, Any] | None = None, **kwargs: Any
) -> list[ProjectSummary] | list[ProjectDetail]:
    """One-shot synchronous project lookup."""
    with Client(**(client_options or {})) as client:
        return client.projects(**kwargs)


def project(
    project_id_or_url: int | str,
    *,
    client_options: dict[str, Any] | None = None,
) -> ProjectDetail:
    """One-shot synchronous project lookup by ID or URL."""
    with Client(**(client_options or {})) as client:
        return client.project(project_id_or_url)


def freelancers(
    *, client_options: dict[str, Any] | None = None, **kwargs: Any
) -> list[FreelancerSummary]:
    """One-shot synchronous freelancer lookup."""
    with Client(**(client_options or {})) as client:
        return client.freelancers(**kwargs)


def user(
    username: str,
    *,
    client_options: dict[str, Any] | None = None,
    **kwargs: Any,
) -> UserProfile:
    """One-shot synchronous user lookup."""
    with Client(**(client_options or {})) as client:
        return client.user(username, **kwargs)


__all__ = [
    "Client",
    "FLClient",
    "freelancers",
    "project",
    "projects",
    "user",
]
