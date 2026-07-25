from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast, overload

import httpx

from .client import FLClient
from .config import ClientConfig
from .cookies import load_netscape_cookies
from .filters import ProjectFilters, ProjectType
from .models import (
    FreelancerSummary,
    PageData,
    ProjectDetail,
    ProjectSummary,
    RequestMetrics,
    UserProfile,
)
from .observability import EventHandler
from .state import CrawlStateStore, SQLiteStateStore

Pages = int | Literal["all"]
ProjectTypeInput = ProjectType | str | Sequence[ProjectType | str] | None
CookiesInput = Mapping[str, str] | str | Path | None
ProxyInput = str | Sequence[str] | None


class Client(FLClient):
    """Simple high-level API.

    ``Client`` covers common use cases with flat arguments. The lower-level
    :class:`flru.FLClient` and configuration dataclasses remain available for
    applications that need complete control.
    """

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
        """Create a client using sensible production defaults.

        Args:
            concurrency: Maximum simultaneous requests.
            rps: Maximum average requests per second.
            retries: Attempts per logical request, including the first attempt.
            timeout: Read timeout in seconds.
            proxy: One proxy URL or a sequence of proxy URLs.
            cookies: Cookie mapping or a Netscape ``cookies.txt`` path.
            strict: Raise when page structure appears to have changed.
            respect_robots_txt: Respect FL.ru robots.txt directives.
            http2: Enable HTTP/2 support.
            verify_ssl: Verify TLS certificates.
            config: Optional advanced configuration used as the base.
        """
        base = config or ClientConfig()
        concurrency_value = (
            (3 if config is None else base.rate_limit.max_concurrency)
            if concurrency is None
            else concurrency
        )
        rps_value = (
            (1.0 if config is None else base.rate_limit.requests_per_second) if rps is None else rps
        )
        retries_value = (
            (5 if config is None else base.retry.max_attempts) if retries is None else retries
        )
        timeout_value = (
            (30.0 if config is None else base.timeout.read) if timeout is None else timeout
        )
        strict_value = base.strict_parsing if strict is None else strict
        robots_value = base.respect_robots_txt if respect_robots_txt is None else respect_robots_txt
        http2_value = base.http2 if http2 is None else http2
        verify_ssl_value = base.verify_ssl if verify_ssl is None else verify_ssl

        if concurrency_value <= 0:
            raise ValueError("concurrency must be positive")
        if rps_value <= 0:
            raise ValueError("rps must be positive")
        if retries_value <= 0:
            raise ValueError("retries must be positive")
        if timeout_value <= 0:
            raise ValueError("timeout must be positive")

        proxy_urls = _normalize_proxies(proxy)
        cookie_values = _normalize_cookies(cookies)

        simple_config = replace(
            base,
            retry=replace(base.retry, max_attempts=retries_value),
            rate_limit=replace(
                base.rate_limit,
                requests_per_second=rps_value,
                max_concurrency=concurrency_value,
            ),
            proxies=replace(base.proxies, urls=proxy_urls) if proxy is not None else base.proxies,
            timeout=replace(
                base.timeout,
                connect=min(timeout_value, base.timeout.connect),
                read=timeout_value,
                write=min(timeout_value, base.timeout.write),
                pool=min(timeout_value, base.timeout.pool),
            ),
            cookies={**base.cookies, **cookie_values},
            strict_parsing=strict_value,
            respect_robots_txt=robots_value,
            http2=http2_value,
            verify_ssl=verify_ssl_value,
        )
        super().__init__(
            simple_config,
            event_handler=event_handler,
            transport=transport,
        )

    @overload
    async def projects(
        self,
        *,
        details: Literal[False] = False,
        pages: Pages = 1,
        start_page: int = 1,
        query: str | None = None,
        category: str | None = None,
        min_budget: Decimal | int | None = None,
        max_budget: Decimal | int | None = None,
        types: ProjectTypeInput = None,
        with_budget: bool | None = None,
        concurrency: int | None = None,
        fail_fast: bool = True,
    ) -> list[ProjectSummary]: ...

    @overload
    async def projects(
        self,
        *,
        details: Literal[True],
        pages: Pages = 1,
        start_page: int = 1,
        query: str | None = None,
        category: str | None = None,
        min_budget: Decimal | int | None = None,
        max_budget: Decimal | int | None = None,
        types: ProjectTypeInput = None,
        with_budget: bool | None = None,
        concurrency: int | None = None,
        fail_fast: bool = True,
    ) -> list[ProjectDetail]: ...

    async def projects(
        self,
        *,
        pages: Pages = 1,
        start_page: int = 1,
        query: str | None = None,
        category: str | None = None,
        min_budget: Decimal | int | None = None,
        max_budget: Decimal | int | None = None,
        types: ProjectTypeInput = None,
        with_budget: bool | None = None,
        details: bool = False,
        concurrency: int | None = None,
        fail_fast: bool = True,
    ) -> list[ProjectSummary] | list[ProjectDetail]:
        """Return projects from one or more catalog pages.

        Examples:
            ``await client.projects()`` — first page.
            ``await client.projects(pages=5)`` — first five pages.
            ``await client.projects(pages="all")`` — the complete catalog.
            ``await client.projects(details=True)`` — full project cards.
        """
        _validate_start_page(start_page)
        max_pages = _normalize_page_count(pages)
        filters = _project_filters(
            query=query,
            category=category,
            min_budget=min_budget,
            max_budget=max_budget,
            types=types,
            with_budget=with_budget,
        )

        if max_pages == 1:
            summaries = await self.get_projects(start_page, filters=filters)
        else:
            summaries = await self.crawl_projects(
                start_page=start_page,
                max_pages=max_pages,
                batch_size=concurrency or self.config.rate_limit.max_concurrency,
                filters=filters,
                fail_fast=fail_fast,
            )

        if not details:
            return summaries

        result = await self.get_project_details_result(summaries, concurrency=concurrency)
        if fail_fast:
            result.raise_for_errors()
        return result.successful

    async def stream_projects(
        self,
        *,
        pages: Pages = "all",
        start_page: int = 1,
        query: str | None = None,
        category: str | None = None,
        min_budget: Decimal | int | None = None,
        max_budget: Decimal | int | None = None,
        types: ProjectTypeInput = None,
        with_budget: bool | None = None,
        concurrency: int | None = None,
        fail_fast: bool = True,
    ) -> AsyncIterator[ProjectSummary]:
        """Stream projects without retaining the complete catalog in memory."""
        _validate_start_page(start_page)
        filters = _project_filters(
            query=query,
            category=category,
            min_budget=min_budget,
            max_budget=max_budget,
            types=types,
            with_budget=with_budget,
        )
        async for project in self.iter_projects(
            start_page=start_page,
            max_pages=_normalize_page_count(pages),
            batch_size=concurrency or self.config.rate_limit.max_concurrency,
            filters=filters,
            fail_fast=fail_fast,
        ):
            yield project

    async def project(self, project: int | str) -> ProjectDetail:
        """Return one complete project by ID or URL."""
        return await self.get_project(project)

    async def freelancers(
        self,
        *,
        pages: Pages = 1,
        start_page: int = 1,
        category: str | None = None,
        concurrency: int | None = None,
        fail_fast: bool = True,
    ) -> list[FreelancerSummary]:
        """Return freelancers from one or more catalog pages."""
        _validate_start_page(start_page)
        max_pages = _normalize_page_count(pages)
        if max_pages == 1:
            return await self.get_freelancers(start_page, category=category)

        return [
            item
            async for item in self.iter_freelancers(
                start_page=start_page,
                max_pages=max_pages,
                batch_size=concurrency or self.config.rate_limit.max_concurrency,
                category=category,
                fail_fast=fail_fast,
            )
        ]

    async def user(
        self,
        username: str,
        *,
        full: bool = False,
        pages: int = 1,
    ) -> UserProfile:
        """Return a user profile; ``full=True`` also loads related sections."""
        if pages <= 0:
            raise ValueError("pages must be positive")
        return await self.get_user(
            username,
            include_projects=full,
            include_reviews=full,
            include_portfolio=full,
            pages=pages,
        )

    async def new_projects(
        self,
        state: CrawlStateStore | str | Path = ".flru-state.db",
        *,
        pages: Pages = 30,
        start_page: int | None = None,
        stop_after_known: int = 20,
        query: str | None = None,
        category: str | None = None,
        min_budget: Decimal | int | None = None,
        max_budget: Decimal | int | None = None,
        types: ProjectTypeInput = None,
        with_budget: bool | None = None,
        concurrency: int | None = None,
    ) -> list[ProjectSummary]:
        """Return only new or changed projects using durable crawl state.

        Passing a filesystem path automatically creates and closes a SQLite
        state store. Advanced applications can pass any ``CrawlStateStore``.
        """
        if start_page is not None:
            _validate_start_page(start_page)
        if stop_after_known <= 0:
            raise ValueError("stop_after_known must be positive")
        store, owned = _state_store(state)
        filters = _project_filters(
            query=query,
            category=category,
            min_budget=min_budget,
            max_budget=max_budget,
            types=types,
            with_budget=with_budget,
        )
        try:
            crawl_options: dict[str, Any] = {
                "max_pages": _normalize_page_count(pages),
                "batch_size": concurrency or self.config.rate_limit.max_concurrency,
                "filters": filters,
                "stop_after_known": stop_after_known,
            }
            if start_page is not None:
                crawl_options["start_page"] = start_page
            return [
                project
                async for project in self.iter_new_projects(
                    store,
                    **crawl_options,
                )
            ]
        finally:
            if owned:
                await store.close()

    async def page(self, url: str) -> PageData:
        """Parse an arbitrary allowed FL.ru page."""
        return await self.get_page(url)

    async def stats(self) -> RequestMetrics:
        """Return request and parser metrics."""
        return await self.metrics()


def _normalize_proxies(proxy: ProxyInput) -> tuple[str, ...]:
    if proxy is None:
        return ()
    if isinstance(proxy, str):
        return (proxy,)
    return tuple(proxy)


def _normalize_cookies(cookies: CookiesInput) -> dict[str, str]:
    if cookies is None:
        return {}
    if isinstance(cookies, Mapping):
        return dict(cookies)
    return load_netscape_cookies(cookies)


def _normalize_page_count(pages: Pages) -> int | None:
    if pages == "all":
        return None
    if not isinstance(pages, int) or isinstance(pages, bool) or pages <= 0:
        raise ValueError('pages must be a positive integer or "all"')
    return pages


def _validate_start_page(page: int) -> None:
    if isinstance(page, bool) or page <= 0:
        raise ValueError("start_page must be positive")


def _normalize_project_types(types: ProjectTypeInput) -> frozenset[ProjectType]:
    if types is None:
        return frozenset()
    values: Sequence[ProjectType | str]
    values = (types,) if isinstance(types, (ProjectType, str)) else types

    aliases = {
        "order": ProjectType.ORDER,
        "orders": ProjectType.ORDER,
        "vacancy": ProjectType.VACANCY,
        "vacancies": ProjectType.VACANCY,
        "contest": ProjectType.CONTEST,
        "contests": ProjectType.CONTEST,
        "заказ": ProjectType.ORDER,
        "заказы": ProjectType.ORDER,
        "вакансия": ProjectType.VACANCY,
        "вакансии": ProjectType.VACANCY,
        "конкурс": ProjectType.CONTEST,
        "конкурсы": ProjectType.CONTEST,
    }
    result: set[ProjectType] = set()
    for value in values:
        if isinstance(value, ProjectType):
            result.add(value)
            continue
        normalized = value.strip().casefold()
        try:
            result.add(aliases[normalized] if normalized in aliases else ProjectType(normalized))
        except ValueError as exc:
            choices = ", ".join(item.name.lower() for item in ProjectType)
            raise ValueError(f"unknown project type {value!r}; expected one of: {choices}") from exc
    return frozenset(result)


def _project_filters(
    *,
    query: str | None,
    category: str | None,
    min_budget: Decimal | int | None,
    max_budget: Decimal | int | None,
    types: ProjectTypeInput,
    with_budget: bool | None,
) -> ProjectFilters:
    # The public "projects" API represents FL.ru orders.  FL.ru's unfiltered
    # catalog also contains vacancies and contests, so request orders unless
    # callers explicitly select one or more kinds.
    project_types = _normalize_project_types(types)
    if types is None:
        project_types = frozenset({ProjectType.ORDER})
    return ProjectFilters(
        query=query,
        category=category,
        budget_from=min_budget,
        budget_to=max_budget,
        project_types=project_types,
        only_with_budget=with_budget,
    )


def _state_store(state: CrawlStateStore | str | Path) -> tuple[CrawlStateStore, bool]:
    if isinstance(state, (str, Path)):
        return SQLiteStateStore(state), True
    return state, False


async def fetch_projects(
    *,
    client_options: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> list[ProjectSummary] | list[ProjectDetail]:
    """Fetch projects in one call and close the temporary client."""
    async with Client(**dict(client_options or {})) as client:
        return cast(list[ProjectSummary] | list[ProjectDetail], await client.projects(**kwargs))


async def fetch_project(
    project_id_or_url: int | str,
    *,
    client_options: Mapping[str, Any] | None = None,
) -> ProjectDetail:
    """Fetch one project in one call."""
    async with Client(**dict(client_options or {})) as client:
        return await client.project(project_id_or_url)


async def fetch_freelancers(
    *,
    client_options: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> list[FreelancerSummary]:
    """Fetch freelancers in one call."""
    async with Client(**dict(client_options or {})) as client:
        return await client.freelancers(**kwargs)


async def fetch_user(
    username: str,
    *,
    client_options: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> UserProfile:
    """Fetch one user profile in one call."""
    async with Client(**dict(client_options or {})) as client:
        return await client.user(username, **kwargs)


__all__ = [
    "Client",
    "CookiesInput",
    "Pages",
    "ProjectTypeInput",
    "ProxyInput",
    "fetch_freelancers",
    "fetch_project",
    "fetch_projects",
    "fetch_user",
]
