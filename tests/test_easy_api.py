from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from flru import (
    Client,
    ClientConfig,
    CrawlCheckpoint,
    MemoryStateStore,
    Money,
    ProjectSummary,
    RateLimitConfig,
    RetryConfig,
    fetch_projects,
)
from flru.sync import Client as SyncClient

FIXTURES = Path(__file__).parent / "fixtures"
PROJECTS = (FIXTURES / "projects.html").read_text(encoding="utf-8")
PROJECT = (FIXTURES / "project.html").read_text(encoding="utf-8")
USER = (FIXTURES / "user.html").read_text(encoding="utf-8")
FREELANCERS = (FIXTURES / "freelancers.html").read_text(encoding="utf-8")


def router(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    page = request.url.params.get("page")
    if path == "/projects/" and page in {None, "1"}:
        return httpx.Response(200, text=PROJECTS, request=request)
    if path == "/projects/" and page == "2":
        return httpx.Response(
            200,
            text="<html><main id='projects-list'>Нет проектов</main></html>",
            request=request,
        )
    if path.startswith("/projects/5500001") or path.startswith("/projects/5500002"):
        return httpx.Response(200, text=PROJECT, request=request)
    if path == "/freelancers/":
        return httpx.Response(200, text=FREELANCERS, request=request)
    if path.startswith("/users/customer-one"):
        return httpx.Response(200, text=USER, request=request)
    return httpx.Response(404, request=request)


def client() -> Client:
    return Client(
        concurrency=4,
        rps=1000,
        retries=1,
        respect_robots_txt=False,
        transport=httpx.MockTransport(router),
    )


@pytest.mark.asyncio
async def test_simple_client_configuration_and_projects() -> None:
    async with client() as api:
        assert api.config.rate_limit.max_concurrency == 4
        assert api.config.retry.max_attempts == 1

        projects = await api.projects(
            pages=2,
            query="FastAPI",
            min_budget=1000,
            types=["заказ", "вакансия"],
            with_budget=True,
        )

    assert {project.id for project in projects} == {5500001, 5500002}


@pytest.mark.asyncio
async def test_simple_details_stream_user_and_freelancers() -> None:
    async with client() as api:
        details = await api.projects(details=True)
        streamed = [project async for project in api.stream_projects(pages=1)]
        project = await api.project(5500001)
        user = await api.user("customer-one", full=True)
        freelancers = await api.freelancers()

    assert details and details[0].full_description
    assert len(streamed) == 1
    assert project.id == 5500001
    assert user.projects and user.reviews and user.portfolio
    assert freelancers[0].username == "dev-one"


@pytest.mark.asyncio
async def test_simple_incremental_and_one_shot() -> None:
    state = MemoryStateStore()
    async with client() as api:
        first = await api.new_projects(state, pages=2)
        second = await api.new_projects(state, pages=2, stop_after_known=1)

    assert len(first) == 1
    assert second == []

    projects = await fetch_projects(
        client_options={
            "rps": 1000,
            "retries": 1,
            "respect_robots_txt": False,
            "transport": httpx.MockTransport(router),
        }
    )
    assert len(projects) == 1



@pytest.mark.asyncio
async def test_simple_incremental_resumes_checkpoint() -> None:
    state = MemoryStateStore()
    await state.save_checkpoint(
        CrawlCheckpoint(
            namespace="projects",
            next_page=2,
            updated_at=datetime.now(timezone.utc),
        )
    )

    async with client() as api:
        projects = await api.new_projects(state, pages=1)

    assert projects == []


def test_model_convenience_properties() -> None:
    project = ProjectSummary(
        id=1,
        title="Test",
        url="https://www.fl.ru/projects/1/test.html",
        budget=Money(amount_min=Decimal("1000"), amount_max=Decimal("1000"), currency="RUB"),
    )

    assert project.budget.amount == Decimal("1000")
    assert project.budget_min == Decimal("1000")
    assert project.budget_max == Decimal("1000")
    assert project.currency == "RUB"
    assert project.to_dict()["id"] == 1


def test_sync_simple_api() -> None:
    with SyncClient(
        rps=1000,
        retries=1,
        respect_robots_txt=False,
        transport=httpx.MockTransport(router),
    ) as api:
        projects = api.projects()
        project = api.project(5500001)

    assert len(projects) == 1
    assert project.id == 5500001




def test_simple_client_preserves_advanced_config_defaults() -> None:
    config = ClientConfig(
        retry=RetryConfig(max_attempts=2),
        rate_limit=RateLimitConfig(requests_per_second=0.5, max_concurrency=9),
        respect_robots_txt=False,
    )
    api = Client(config=config)

    assert api.config.retry.max_attempts == 2
    assert api.config.rate_limit.requests_per_second == 0.5
    assert api.config.rate_limit.max_concurrency == 9
    assert api.config.respect_robots_txt is False


def test_simple_client_from_cookie_file(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".fl.ru\tTRUE\t/\tFALSE\t2147483647\tsession\ttoken\n",
        encoding="utf-8",
    )

    api = Client.from_cookie_file(
        cookie_file,
        rps=1000,
        retries=1,
        respect_robots_txt=False,
        transport=httpx.MockTransport(router),
    )
    assert api.config.cookies["session"] == "token"


@pytest.mark.asyncio
async def test_simple_validation() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        Client(concurrency=0)

    with pytest.raises(ValueError, match="timeout"):
        SyncClient(timeout=0)

    async with client() as api:
        with pytest.raises(ValueError, match="pages"):
            await api.projects(pages=0)

        with pytest.raises(ValueError, match="unknown project type"):
            await api.projects(types="unknown")
