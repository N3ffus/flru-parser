from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from flru import (
    BatchResult,
    ClientConfig,
    FLClient,
    MemoryStateStore,
    ProjectFilters,
    ProjectSummary,
    ProjectType,
    RateLimitConfig,
    RetryConfig,
    SQLiteStateStore,
)
from flru.batch import BatchError
from flru.models import CrawlCheckpoint
from flru.state import project_content_hash, record_for

FIXTURES = Path(__file__).parent / "fixtures"
PROJECTS = (FIXTURES / "projects.html").read_text(encoding="utf-8")
PROJECT = (FIXTURES / "project.html").read_text(encoding="utf-8")
PROJECTS_WITH_CATEGORY = PROJECTS.replace(
    "<main id=", "<a href='/projects/category/programmirovanie/'>Программирование</a><main id="
)
USER = (FIXTURES / "user.html").read_text(encoding="utf-8")
FREELANCERS = (FIXTURES / "freelancers.html").read_text(encoding="utf-8")


def config(**kwargs):
    return ClientConfig(
        respect_robots_txt=False,
        retry=RetryConfig(max_attempts=1, base_delay=0, max_delay=0, jitter=0),
        rate_limit=RateLimitConfig(requests_per_second=1000, burst=20, max_concurrency=20),
        **kwargs,
    )


def router(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    page = request.url.params.get("page")
    if path == "/projects/" and page in {None, "1"}:
        return httpx.Response(
            200,
            text=PROJECTS_WITH_CATEGORY,
            request=request,
            headers={"Date": "Sat, 25 Jul 2026 12:00:00 GMT"},
        )
    if path == "/projects/" and page == "2":
        return httpx.Response(
            200, text="<html><main id='projects-list'>Нет проектов</main></html>", request=request
        )
    if path.startswith("/projects/5500001"):
        return httpx.Response(200, text=PROJECT, request=request)
    if path == "/freelancers/":
        return httpx.Response(200, text=FREELANCERS, request=request)
    if path == "/freelancers/page-2/":
        return httpx.Response(
            200, text="<html><main>Нет исполнителей</main></html>", request=request
        )
    if path.startswith("/users/customer-one"):
        return httpx.Response(200, text=USER, request=request)
    if path == "/generic/":
        return httpx.Response(
            200,
            text="<html><head><title>X</title></head><main><h1>Y</h1></main></html>",
            request=request,
        )
    return httpx.Response(404, request=request)


@pytest.mark.asyncio
async def test_batch_result_and_filters() -> None:
    result: BatchResult[int, str] = BatchResult(successful=["ok"])
    assert result.ok
    result.failed.append(BatchError(2, ValueError("bad")))
    assert not result.ok
    with pytest.raises(ValueError, match="bad"):
        result.raise_for_errors()

    filters = ProjectFilters(
        query="FastAPI",
        budget_from=1000,
        budget_to=5000,
        project_types=frozenset({ProjectType.ORDER, ProjectType.VACANCY}),
        only_with_budget=True,
        extra={"x": "y"},
    )
    params = filters.to_params()
    assert params["search"] == "FastAPI"
    assert params["budget_from"] == "1000"
    assert params["with_budget"] == 1
    assert sorted(params["kind"]) == ["1", "2"]


@pytest.mark.asyncio
async def test_client_extended_read_api() -> None:
    transport = httpx.MockTransport(router)
    async with FLClient(config(), transport=transport) as client:
        page = await client.get_page("/generic/")
        assert page.title == "X"

        batch = await client.get_projects_batch_result([1, 2], concurrency=2)
        assert batch.ok
        assert [item.page for item in batch.successful] == [1, 2]

        generator_batch = await client.get_projects_batch(
            (page for page in [1, 2]),
            concurrency=2,
        )
        assert [item.page for item in generator_batch if not isinstance(item, BaseException)] == [
            1,
            2,
        ]

        pages = [item async for item in client.iter_project_pages(max_pages=3, batch_size=2)]
        assert [item.page for item in pages] == [1, 2]
        assert pages[1].diagnostics.warnings == ["catalog_end"]

        projects = [item async for item in client.iter_projects(max_pages=2, batch_size=2)]
        assert {item.id for item in projects} == {5500001, 5500002}

        detail = await client.get_project(5500001)
        assert detail.id == 5500001
        details = await client.get_project_details_result([5500001, "/missing"])
        assert len(details.successful) == 1
        assert len(details.failed) == 1

        pipeline = [
            item
            async for item in client.iter_project_details(projects[:1], workers=2, queue_size=2)
        ]
        assert pipeline[0].id == 5500001

        freelancers = await client.get_freelancers()
        assert freelancers[0].username == "dev-one"
        freelancer_pages = await client.get_freelancers_batch_result([1, 2])
        assert len(freelancer_pages.successful) == 2
        walked = [item async for item in client.iter_freelancers(max_pages=2, batch_size=2)]
        assert [item.username for item in walked] == ["dev-one"]

        user = await client.get_user(
            "customer-one",
            include_projects=True,
            include_reviews=True,
            include_portfolio=True,
            pages=1,
        )
        assert user.user_id == 123456
        assert user.projects and user.reviews and user.portfolio

        categories = await client.get_categories()
        assert any(item.slug == "programmirovanie" for item in categories)
        assert (await client.metrics()).responses_total > 0
        assert (await client.proxy_health())[0]["url"] is None


@pytest.mark.asyncio
async def test_incremental_state_and_sqlite(tmp_path: Path) -> None:
    project = ProjectSummary(id=1, title="One", url="https://www.fl.ru/projects/1/one.html")
    assert project_content_hash(project) == project_content_hash(project.model_copy())

    memory = MemoryStateStore()
    first = record_for(project)
    await memory.save(first)
    assert await memory.contains(1)
    second = record_for(project, await memory.get(1))
    assert second.first_seen_at == first.first_seen_at
    checkpoint = CrawlCheckpoint(namespace="x", next_page=2, updated_at=datetime.now(UTC))
    await memory.save_checkpoint(checkpoint)
    assert (await memory.get_checkpoint("x")).next_page == 2

    sqlite = SQLiteStateStore(tmp_path / "state.db")
    await sqlite.save(second)
    assert (await sqlite.get(1)).content_hash == second.content_hash
    await sqlite.save_checkpoint(checkpoint)
    assert (await sqlite.get_checkpoint("x")).namespace == "x"
    await sqlite.close()


@pytest.mark.asyncio
async def test_iter_new_projects_persists_and_stops() -> None:
    transport = httpx.MockTransport(router)
    state = MemoryStateStore()
    async with FLClient(config(), transport=transport) as client:
        first = [item async for item in client.iter_new_projects(state, max_pages=2, batch_size=1)]
        assert len(first) == 2
        second = [
            item
            async for item in client.iter_new_projects(
                state,
                max_pages=2,
                batch_size=1,
                stop_after_known=1,
                resume=False,
            )
        ]
        assert second == []


def test_client_config_copies_and_freezes_mappings() -> None:
    from flru import ClientConfig

    headers = {"X-Test": "one"}
    cookies = {"session": "secret"}
    config = ClientConfig(headers=headers, cookies=cookies)

    headers["X-Test"] = "changed"
    cookies["session"] = "changed"

    assert config.headers["X-Test"] == "one"
    assert config.cookies["session"] == "secret"

    with pytest.raises(TypeError):
        config.headers["X-New"] = "value"  # type: ignore[index]


def test_with_cookies_keeps_original_config_unchanged() -> None:
    from flru import ClientConfig

    original = ClientConfig(cookies={"one": "1"})
    updated = original.with_cookies({"two": "2"})

    assert dict(original.cookies) == {"one": "1"}
    assert dict(updated.cookies) == {"one": "1", "two": "2"}


@pytest.mark.asyncio
async def test_update_cookies_before_first_request_is_applied() -> None:
    seen_cookie = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_cookie
        seen_cookie = request.headers.get("Cookie", "")
        return httpx.Response(200, request=request, text="ok")

    client_config = ClientConfig(
        respect_robots_txt=False,
        rate_limit=RateLimitConfig(requests_per_second=1000, max_concurrency=1),
    )
    async with FLClient(client_config, transport=httpx.MockTransport(handler)) as client:
        client.update_cookies({"session": "token"})
        await client.request("GET", "/projects/")

    assert "session=token" in seen_cookie
