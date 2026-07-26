from __future__ import annotations

import asyncio
import email.utils
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self, TypeVar, cast
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .batch import BatchError, BatchResult, StreamItemResult
from .config import ClientConfig
from .cookies import load_netscape_cookies
from .exceptions import (
    BlockedError,
    EmptyPageError,
    ParseError,
    RobotsDeniedError,
    SelectorDriftError,
)
from .filters import ProjectFilters, ProjectType
from .models import (
    Category,
    CrawlCheckpoint,
    FreelancerPage,
    FreelancerSummary,
    PageData,
    PortfolioItem,
    ProjectDetail,
    ProjectKind,
    ProjectPage,
    ProjectSummary,
    RequestMetrics,
    Review,
    UserProfile,
)
from .observability import EventHandler, RequestEvent
from .parsers import (
    parse_freelancer_list,
    parse_generic_page,
    parse_project_detail,
    parse_project_list,
    parse_user_profile,
    with_page,
)
from .robots import RobotsPolicy
from .state import CrawlStateStore, record_for
from .transport import ResilientTransport

T = TypeVar("T")


async def _gather_batch_or_stop_on_block(
    awaitables: Iterable[Awaitable[T]],
) -> list[T | BaseException]:
    """Cancel outstanding work when a block makes further scraping inappropriate."""
    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    for task in done:
        error = task.exception()
        if isinstance(error, BlockedError):
            for pending_task in pending:
                pending_task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise error
    return list(await asyncio.gather(*tasks, return_exceptions=True))


class FLClient:
    """Asynchronous, read-only client/parser for public FL.ru pages."""

    def __init__(
        self,
        config: ClientConfig | None = None,
        *,
        event_handler: EventHandler | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or ClientConfig()
        self._event_handler = event_handler
        self._transport = ResilientTransport(
            self.config,
            event_handler=event_handler,
            client_transport=transport,
        )
        timeout = httpx.Timeout(
            connect=self.config.timeout.connect,
            read=self.config.timeout.read,
            write=self.config.timeout.write,
            pool=self.config.timeout.pool,
        )
        self._robots = RobotsPolicy(
            base_url=self.config.base_url,
            user_agent=self.config.user_agents[0],
            timeout=timeout,
            verify=self.config.verify_ssl,
            cache_ttl=self.config.robots_cache_ttl,
            fail_closed=self.config.robots_fail_closed,
        )
        self._closed = False

    @classmethod
    def from_cookie_file(
        cls,
        path: str | Path,
        config: ClientConfig | None = None,
        **kwargs: Any,
    ) -> Self:
        base = config or ClientConfig()
        return cls(config=base.with_cookies(load_netscape_cookies(path)), **kwargs)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._transport.close()

    async def metrics(self) -> RequestMetrics:
        return await self._transport.metrics.snapshot()

    async def proxy_health(self) -> list[dict[str, Any]]:
        states = await self._transport.proxy_pool.snapshot()
        return [
            {
                "url": state.safe_url,
                "failures": state.failures,
                "successes": state.successes,
                "cooldown_until": state.cooldown_until,
                "last_error": state.last_error,
            }
            for state in states
        ]

    def update_cookies(self, cookies: Mapping[str, str]) -> None:
        self._transport.update_cookies(dict(cookies))

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        absolute = self._absolute(url)
        if self.config.respect_robots_txt and not await self._robots.allowed(absolute):
            raise RobotsDeniedError(f"robots.txt denies access to {absolute}")
        return await self._transport.request(method, absolute, **kwargs)

    async def _get_document(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> tuple[str, str, datetime]:
        response = await self.request("GET", url, params=params)
        fetched_at = self._response_datetime(response)
        return response.text, str(response.url), fetched_at

    async def get_html(self, url: str, *, params: Mapping[str, Any] | None = None) -> str:
        html, _, _ = await self._get_document(url, params=params)
        return html

    async def get_page(self, url: str) -> PageData:
        absolute = self._absolute(url)
        html, effective_url, fetched_at = await self._get_document(absolute)
        return parse_generic_page(
            html,
            effective_url,
            store_raw_html=self.config.store_raw_html,
            fetched_at=fetched_at,
        )

    async def get_projects_page(
        self,
        page: int = 1,
        *,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
        url: str | None = None,
    ) -> ProjectPage:
        request_url = url or self._projects_url(category or (filters.category if filters else None))
        query = {**(filters.to_params() if filters else {}), **dict(params or {})}
        if page != 1 and not url:
            query["page"] = page
        html, effective_url, fetched_at = await self._get_document(request_url, params=query)
        try:
            result = parse_project_list(
                html,
                effective_url,
                page=page,
                store_raw_html=self.config.store_raw_html,
                fetched_at=fetched_at,
                timezone_name=self.config.parser_timezone,
            )
            self._validate_project_page(result)
            if filters and filters.project_types:
                kind_map = {
                    ProjectType.ORDER: ProjectKind.ORDER,
                    ProjectType.VACANCY: ProjectKind.VACANCY,
                    ProjectType.CONTEST: ProjectKind.CONTEST,
                }
                requested = {kind_map[item] for item in filters.project_types}
                result.items = [item for item in result.items if item.kind in requested]
            return result
        except ParseError as exc:
            await self._record_parse_failure(effective_url, html, exc)
            raise

    async def get_projects(
        self,
        page: int = 1,
        *,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> list[ProjectSummary]:
        return (
            await self.get_projects_page(
                page,
                category=category,
                filters=filters,
                params=params,
            )
        ).items

    async def get_projects_batch_result(
        self,
        pages: Iterable[int],
        *,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
        concurrency: int | None = None,
    ) -> BatchResult[int, ProjectPage]:
        page_numbers = list(pages)
        semaphore = asyncio.Semaphore(concurrency or self.config.rate_limit.max_concurrency)

        async def load(page: int) -> ProjectPage:
            async with semaphore:
                return await self.get_projects_page(
                    page,
                    category=category,
                    filters=filters,
                    params=params,
                )

        values = await _gather_batch_or_stop_on_block(load(page) for page in page_numbers)
        result: BatchResult[int, ProjectPage] = BatchResult()
        for page, value in zip(page_numbers, values, strict=True):
            if isinstance(value, asyncio.CancelledError):
                raise value
            if isinstance(value, BlockedError):
                raise value
            if isinstance(value, Exception):
                result.failed.append(BatchError(page, value))
            else:
                result.successful.append(cast(ProjectPage, value))
        return result

    async def get_projects_batch(
        self,
        pages: Iterable[int],
        *,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
        concurrency: int | None = None,
        return_exceptions: bool = False,
    ) -> list[ProjectPage | Exception]:
        """Compatibility API; prefer :meth:`get_projects_batch_result`."""
        page_numbers = list(pages)
        result = await self.get_projects_batch_result(
            page_numbers,
            category=category,
            filters=filters,
            params=params,
            concurrency=concurrency,
        )
        if result.failed and not return_exceptions:
            raise result.failed[0].error
        by_page: dict[int, ProjectPage | Exception] = {
            item.page: item for item in result.successful
        }
        by_page.update({item.key: item.error for item in result.failed})
        return [by_page[page] for page in page_numbers]

    async def iter_project_pages(
        self,
        *,
        start_page: int = 1,
        max_pages: int | None = None,
        batch_size: int = 3,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
        fail_fast: bool = True,
    ) -> AsyncIterator[ProjectPage]:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        current, emitted = start_page, 0
        while max_pages is None or emitted < max_pages:
            size = batch_size if max_pages is None else min(batch_size, max_pages - emitted)
            page_numbers = list(range(current, current + size))
            batch = await self.get_projects_batch_result(
                page_numbers,
                category=category,
                filters=filters,
                params=params,
                concurrency=batch_size,
            )
            if batch.failed and fail_fast:
                raise batch.failed[0].error
            pages = sorted(batch.successful, key=lambda item: item.page)
            if not pages:
                break
            stop = False
            for page in pages:
                yield page
                emitted += 1
                if not page.has_next:
                    stop = True
                    break
            if stop or (batch.failed and not fail_fast):
                break
            current = self._page_number(pages[-1].next_url) or pages[-1].page + 1

    async def iter_projects(
        self,
        *,
        start_page: int = 1,
        max_pages: int | None = None,
        batch_size: int = 3,
        category: str | None = None,
        filters: ProjectFilters | None = None,
        params: Mapping[str, Any] | None = None,
        deduplicate: bool = True,
        fail_fast: bool = True,
    ) -> AsyncIterator[ProjectSummary]:
        seen: set[int] = set()
        allowed_kinds = {
            ProjectType.ORDER: ProjectKind.ORDER,
            ProjectType.VACANCY: ProjectKind.VACANCY,
            ProjectType.CONTEST: ProjectKind.CONTEST,
        }
        requested_kinds = (
            {allowed_kinds[item] for item in filters.project_types}
            if filters and filters.project_types
            else set()
        )
        async for page in self.iter_project_pages(
            start_page=start_page,
            max_pages=max_pages,
            batch_size=batch_size,
            category=category,
            filters=filters,
            params=params,
            fail_fast=fail_fast,
        ):
            for item in page.items:
                # FL.ru can include pinned cards of another kind even when a
                # `kind` filter is present, so enforce the requested kinds
                # locally as well.
                if requested_kinds and item.kind not in requested_kinds:
                    continue
                if deduplicate and item.id in seen:
                    continue
                seen.add(item.id)
                yield item

    async def iter_new_projects(
        self,
        state: CrawlStateStore,
        *,
        namespace: str = "projects",
        stop_after_known: int = 20,
        resume: bool = True,
        **kwargs: Any,
    ) -> AsyncIterator[ProjectSummary]:
        checkpoint = await state.get_checkpoint(namespace) if resume else None
        if checkpoint and checkpoint.next_page and "start_page" not in kwargs:
            kwargs["start_page"] = checkpoint.next_page
        resumed_from_checkpoint = bool(
            checkpoint and (checkpoint.next_page is not None or checkpoint.next_url is not None)
        )
        consecutive_known = (
            checkpoint.consecutive_known if checkpoint and resumed_from_checkpoint else 0
        )
        async for page in self.iter_project_pages(**kwargs):
            records = []
            for project in page.items:
                previous = await state.get(project.id)
                record = record_for(project, previous)
                records.append(record)
                if previous is not None and previous.content_hash == record.content_hash:
                    consecutive_known += 1
                else:
                    consecutive_known = 0
                    yield project
                if consecutive_known >= stop_after_known:
                    await state.save_many(records)
                    await state.save_checkpoint(
                        CrawlCheckpoint(
                            namespace=namespace,
                            next_url=page.next_url,
                            next_page=self._page_number(page.next_url),
                            updated_at=datetime.now(UTC),
                            consecutive_known=consecutive_known,
                        )
                    )
                    return
            await state.save_many(records)
            await state.save_checkpoint(
                CrawlCheckpoint(
                    namespace=namespace,
                    next_url=page.next_url,
                    next_page=self._page_number(page.next_url),
                    updated_at=datetime.now(UTC),
                    consecutive_known=consecutive_known,
                )
            )

    async def crawl_projects(self, **kwargs: Any) -> list[ProjectSummary]:
        return [project async for project in self.iter_projects(**kwargs)]

    async def iter_project_details(
        self,
        projects: AsyncIterator[ProjectSummary] | Iterable[ProjectSummary],
        *,
        workers: int = 4,
        queue_size: int = 50,
        fail_fast: bool = True,
    ) -> AsyncIterator[ProjectDetail]:
        """Yield successful details from the result stream."""
        async for result in self.iter_project_details_result(
            projects,
            workers=workers,
            queue_size=queue_size,
        ):
            if result.error is None:
                assert result.value is not None
                yield result.value
            elif isinstance(result.error, BlockedError) or fail_fast:
                raise result.error

    async def iter_project_details_result(
        self,
        projects: AsyncIterator[ProjectSummary] | Iterable[ProjectSummary],
        *,
        workers: int = 4,
        queue_size: int = 50,
    ) -> AsyncIterator[StreamItemResult[int, ProjectDetail]]:
        """Bounded structured pipeline that exposes per-item failures."""
        if workers <= 0:
            raise ValueError("workers must be greater than zero")
        if queue_size <= 0:
            raise ValueError("queue_size must be greater than zero")

        input_queue: asyncio.Queue[ProjectSummary | None] = asyncio.Queue(queue_size)
        output_queue: asyncio.Queue[StreamItemResult[int, ProjectDetail] | BaseException | None] = (
            asyncio.Queue(queue_size)
        )

        async def producer() -> None:
            try:
                if isinstance(projects, AsyncIterable):
                    async for item in projects:
                        await input_queue.put(item)
                else:
                    for item in projects:
                        await input_queue.put(item)
            except Exception as exc:
                await output_queue.put(exc)
            finally:
                task = asyncio.current_task()
                if isinstance(projects, AsyncIterable):
                    close = getattr(projects, "aclose", None)
                    if close is not None:
                        await close()
                if task is None or not task.cancelling():
                    for _ in range(workers):
                        await input_queue.put(None)

        async def worker() -> None:
            while (item := await input_queue.get()) is not None:
                try:
                    value = await self.get_project(item.url)
                    await output_queue.put(StreamItemResult(key=item.id, value=value))
                except BlockedError as exc:
                    await output_queue.put(exc)
                    return
                except Exception as exc:
                    await output_queue.put(StreamItemResult(key=item.id, error=exc))
                finally:
                    input_queue.task_done()
            input_queue.task_done()
            await output_queue.put(None)

        tasks = [asyncio.create_task(producer(), name="flru-project-producer")]
        tasks.extend(
            asyncio.create_task(worker(), name=f"flru-project-worker-{index}")
            for index in range(workers)
        )
        finished = 0
        try:
            while finished < workers:
                value = await output_queue.get()
                if value is None:
                    finished += 1
                elif isinstance(value, BaseException):
                    raise value
                else:
                    yield value
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def get_freelancers_page(
        self, page: int = 1, *, category: str | None = None
    ) -> FreelancerPage:
        url = self._freelancers_url(category, page)
        html, effective_url, fetched_at = await self._get_document(url)
        try:
            result = parse_freelancer_list(
                html,
                effective_url,
                page=page,
                store_raw_html=self.config.store_raw_html,
                fetched_at=fetched_at,
            )
            if (
                self.config.strict_parsing
                and not result.items
                and "catalog_end" not in result.diagnostics.warnings
            ):
                if result.diagnostics.candidate_links_found:
                    raise SelectorDriftError(f"Freelancer selectors drifted at {effective_url}")
                raise EmptyPageError(f"Unexpected empty freelancer page: {effective_url}")
            return result
        except ParseError as exc:
            await self._record_parse_failure(effective_url, html, exc)
            raise

    async def get_freelancers(
        self, page: int = 1, *, category: str | None = None
    ) -> list[FreelancerSummary]:
        return (await self.get_freelancers_page(page, category=category)).items

    async def get_freelancers_batch_result(
        self,
        pages: Iterable[int],
        *,
        category: str | None = None,
        concurrency: int | None = None,
    ) -> BatchResult[int, FreelancerPage]:
        page_numbers = list(pages)
        semaphore = asyncio.Semaphore(concurrency or self.config.rate_limit.max_concurrency)

        async def load(page: int) -> FreelancerPage:
            async with semaphore:
                return await self.get_freelancers_page(page, category=category)

        values = await _gather_batch_or_stop_on_block(load(page) for page in page_numbers)
        result: BatchResult[int, FreelancerPage] = BatchResult()
        for page, value in zip(page_numbers, values, strict=True):
            if isinstance(value, asyncio.CancelledError):
                raise value
            if isinstance(value, BlockedError):
                raise value
            if isinstance(value, Exception):
                result.failed.append(BatchError(page, value))
            else:
                result.successful.append(cast(FreelancerPage, value))
        return result

    async def get_freelancers_batch(
        self,
        pages: Iterable[int],
        *,
        category: str | None = None,
        concurrency: int | None = None,
        return_exceptions: bool = False,
    ) -> list[FreelancerPage | Exception]:
        page_numbers = list(pages)
        result = await self.get_freelancers_batch_result(
            page_numbers, category=category, concurrency=concurrency
        )
        if result.failed and not return_exceptions:
            raise result.failed[0].error
        mapping: dict[int, FreelancerPage | Exception] = {
            item.page: item for item in result.successful
        }
        mapping.update({error.key: error.error for error in result.failed})
        return [mapping[page] for page in page_numbers]

    async def iter_freelancers(
        self,
        *,
        start_page: int = 1,
        max_pages: int | None = None,
        batch_size: int = 3,
        category: str | None = None,
        deduplicate: bool = True,
        fail_fast: bool = True,
    ) -> AsyncIterator[FreelancerSummary]:
        seen: set[str] = set()
        current, emitted = start_page, 0
        while max_pages is None or emitted < max_pages:
            size = batch_size if max_pages is None else min(batch_size, max_pages - emitted)
            batch = await self.get_freelancers_batch_result(
                range(current, current + size), category=category, concurrency=batch_size
            )
            if batch.failed and fail_fast:
                raise batch.failed[0].error
            pages = sorted(batch.successful, key=lambda item: item.page)
            if not pages:
                break
            stop = False
            for page in pages:
                emitted += 1
                for item in page.items:
                    key = item.username or item.url or item.name or ""
                    if deduplicate and key in seen:
                        continue
                    seen.add(key)
                    yield item
                if not page.has_next:
                    stop = True
                    break
            if stop or (batch.failed and not fail_fast):
                break
            current = self._page_number(pages[-1].next_url) or pages[-1].page + 1

    async def get_project(self, project: int | str) -> ProjectDetail:
        url = self._project_url(project)
        html, effective_url, fetched_at = await self._get_document(url)
        try:
            return parse_project_detail(
                html,
                effective_url,
                store_raw_html=self.config.store_raw_html,
                fetched_at=fetched_at,
                timezone_name=self.config.parser_timezone,
            )
        except ValueError as exc:
            error = ParseError(str(exc))
            await self._record_parse_failure(effective_url, html, error)
            raise error from exc

    async def get_project_details_result(
        self,
        projects: Sequence[ProjectSummary | int | str],
        *,
        concurrency: int | None = None,
    ) -> BatchResult[int | str, ProjectDetail]:
        semaphore = asyncio.Semaphore(concurrency or self.config.rate_limit.max_concurrency)

        async def load(project: ProjectSummary | int | str) -> ProjectDetail:
            value: int | str = project.url if isinstance(project, ProjectSummary) else project
            async with semaphore:
                return await self.get_project(value)

        values = await _gather_batch_or_stop_on_block(load(project) for project in projects)
        result: BatchResult[int | str, ProjectDetail] = BatchResult()
        for project, value in zip(projects, values, strict=True):
            key: int | str = project.id if isinstance(project, ProjectSummary) else project
            if isinstance(value, asyncio.CancelledError):
                raise value
            if isinstance(value, BlockedError):
                raise value
            if isinstance(value, Exception):
                result.failed.append(BatchError(key, value))
            else:
                result.successful.append(cast(ProjectDetail, value))
        return result

    async def get_project_details(
        self,
        projects: Sequence[ProjectSummary | int | str],
        *,
        concurrency: int | None = None,
        return_exceptions: bool = False,
    ) -> list[ProjectDetail | Exception]:
        result = await self.get_project_details_result(projects, concurrency=concurrency)
        if result.failed and not return_exceptions:
            raise result.failed[0].error
        success = iter(result.successful)
        errors = {item.key: item.error for item in result.failed}
        output: list[ProjectDetail | Exception] = []
        for project in projects:
            key: int | str = project.id if isinstance(project, ProjectSummary) else project
            output.append(errors[key] if key in errors else next(success))
        return output

    async def get_user(
        self,
        user: str,
        *,
        include_projects: bool = False,
        include_reviews: bool = False,
        include_portfolio: bool = False,
        pages: int = 1,
    ) -> UserProfile:
        url = self._user_url(user)
        html, effective_url, fetched_at = await self._get_document(url)
        profile = parse_user_profile(
            html,
            effective_url,
            store_raw_html=self.config.store_raw_html,
            fetched_at=fetched_at,
        )
        tasks: list[tuple[str, Any]] = []
        if include_projects:
            tasks.append(("projects", self.get_user_projects(user, pages=pages)))
        if include_reviews:
            tasks.append(("reviews", self.get_user_reviews(user, pages=pages)))
        if include_portfolio:
            tasks.append(("portfolio", self.get_user_portfolio(user, pages=pages)))
        if tasks:
            values = await asyncio.gather(*(task for _, task in tasks))
            for (field, _), value in zip(tasks, values, strict=True):
                setattr(profile, field, value)
        return profile

    async def get_user_projects(self, user: str, *, pages: int = 1) -> list[ProjectSummary]:
        base = self._user_url(user)
        urls = [with_page(base, page) if page > 1 else base for page in range(1, pages + 1)]
        documents = await asyncio.gather(*(self._get_document(url) for url in urls))
        result: dict[int, ProjectSummary] = {}
        for page, (html, effective_url, fetched_at) in enumerate(documents, 1):
            parsed = parse_project_list(html, effective_url, page=page, fetched_at=fetched_at)
            result.update({project.id: project for project in parsed.items})
        return list(result.values())

    async def get_user_reviews(self, user: str, *, pages: int = 1) -> list[Review]:
        values = await self._collect_user_section(user, "opinions", "reviews", pages)
        return [cast(Review, value) for value in values]

    async def get_user_portfolio(self, user: str, *, pages: int = 1) -> list[PortfolioItem]:
        values = await self._collect_user_section(user, "portfolio", "portfolio", pages)
        return [cast(PortfolioItem, value) for value in values]

    async def _collect_user_section(
        self, user: str, section: str, field: str, pages: int
    ) -> list[Any]:
        username = self._username(user)
        base = self._absolute(f"/users/{username}/{section}/")
        urls = [with_page(base, page) if page > 1 else base for page in range(1, pages + 1)]
        documents = await asyncio.gather(*(self._get_document(url) for url in urls))
        result: list[Any] = []
        seen: set[str] = set()
        for html, effective_url, fetched_at in documents:
            profile = parse_user_profile(html, effective_url, fetched_at=fetched_at)
            for value in getattr(profile, field):
                key = value.model_dump_json()
                if key not in seen:
                    seen.add(key)
                    result.append(value)
        return result

    async def get_categories(self) -> list[Category]:
        url = self._absolute("/projects/")
        html = await self.get_html(url)
        soup = BeautifulSoup(html, "lxml")
        result: list[Category] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href*='/projects/category/']"):
            href = self._absolute(str(anchor.get("href")))
            name = " ".join(anchor.get_text(" ", strip=True).split())
            if not name or href in seen:
                continue
            seen.add(href)
            match = re.search(r"/projects/category/(.+?)/?$", urlsplit(href).path)
            slug = match.group(1) if match else None
            result.append(
                Category(
                    name=name,
                    url=href,
                    slug=slug,
                    parent=slug.split("/", 1)[0] if slug and "/" in slug else None,
                )
            )
        return result

    def _validate_project_page(self, page: ProjectPage) -> None:
        if not self.config.strict_parsing or page.items:
            return
        diagnostics = page.diagnostics
        if diagnostics.candidate_links_found > 0:
            raise SelectorDriftError(
                f"Found {diagnostics.candidate_links_found} project links but parsed no items at {page.url}"
            )
        if "catalog_end" not in diagnostics.warnings:
            raise EmptyPageError(f"Unexpected empty project page: {page.url}")

    async def _record_parse_failure(
        self,
        url: str,
        html: str,
        error: ParseError | None = None,
    ) -> None:
        if isinstance(error, SelectorDriftError):
            await self._transport.metrics.mutate(parse_failures_total=1, selector_drift_total=1)
        else:
            await self._transport.metrics.mutate(parse_failures_total=1)
        await self._transport.emit_event(
            RequestEvent("parse_failure", "GET", url, 1, self._endpoint(url))
        )
        if not self.config.store_failed_html or not self.config.failed_html_directory:
            return
        directory = Path(self.config.failed_html_directory)
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", url)[:160]
        await asyncio.to_thread(
            (directory / f"{safe_name}.html").write_text, html, encoding="utf-8"
        )

    def _absolute(self, url: str) -> str:
        return urljoin(self.config.base_url.rstrip("/") + "/", url)

    def _projects_url(self, category: str | None) -> str:
        if not category:
            return self._absolute("/projects/")
        if category.startswith(("http://", "https://")):
            return category
        category = category.strip("/")
        if category.startswith("projects/category/"):
            return self._absolute(f"/{category}/")
        return self._absolute(f"/projects/category/{category}/")

    def _freelancers_url(self, category: str | None, page: int) -> str:
        if category and category.startswith(("http://", "https://")):
            base = category.rstrip("/") + "/"
        elif category:
            base = self._absolute(f"/freelancers/{category.strip('/')}/")
        else:
            base = self._absolute("/freelancers/")
        return base if page == 1 else urljoin(base, f"page-{page}/")

    def _project_url(self, project: int | str) -> str:
        if isinstance(project, int) or str(project).isdigit():
            return self._absolute(f"/projects/{project}/")
        return self._absolute(str(project))

    def _username(self, user: str) -> str:
        if user.startswith(("http://", "https://")) or "/users/" in user:
            match = re.search(r"/users/([^/?#]+)/?", urlsplit(self._absolute(user)).path)
            if not match:
                raise ValueError(f"Could not extract username from {user!r}")
            return match.group(1)
        return user.strip("/")

    def _user_url(self, user: str) -> str:
        return self._absolute(f"/users/{self._username(user)}/")

    @staticmethod
    def _page_number(url: str | None) -> int | None:
        if not url:
            return None
        query = parse_qs(urlsplit(url).query)
        if query.get("page") and query["page"][0].isdigit():
            return int(query["page"][0])
        if match := re.search(r"/page-(\d+)/?", urlsplit(url).path):
            return int(match.group(1))
        return None

    @staticmethod
    def _response_datetime(response: httpx.Response) -> datetime:
        if value := response.headers.get("Date"):
            try:
                parsed = email.utils.parsedate_to_datetime(value)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                pass
        return datetime.now(UTC)

    @staticmethod
    def _endpoint(url: str) -> str:
        path = urlsplit(url).path.strip("/")
        return path.split("/", 1)[0] or "root"

    @staticmethod
    def _url_with_params(url: str, params: Mapping[str, Any]) -> str:
        return f"{url}?{urlencode(params, doseq=True)}" if params else url
