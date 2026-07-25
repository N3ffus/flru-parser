from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from flru import ClientConfig, FLClient, ProjectFilters, ProjectKind, ProjectSummary, ProjectType
from flru.easy import (
    Client,
    _normalize_cookies,
    _normalize_page_count,
    _normalize_project_types,
    _normalize_proxies,
    _project_filters,
    _state_store,
    _validate_start_page,
)
from flru.exceptions import EmptyPageError, SelectorDriftError
from flru.models import ParseDiagnostics, ProjectPage


def _page(
    *, page: int = 1, has_next: bool = False, items: list[ProjectSummary] | None = None
) -> ProjectPage:
    return ProjectPage(
        page=page,
        url="https://www.fl.ru/projects/",
        items=items or [],
        has_next=has_next,
        diagnostics=ParseDiagnostics(page_fingerprint="test"),
    )


def test_easy_normalizers_and_validation(tmp_path: Path) -> None:
    assert _normalize_proxies(None) == ()
    assert _normalize_proxies("http://proxy") == ("http://proxy",)
    assert _normalize_proxies(["a", "b"]) == ("a", "b")
    assert _normalize_cookies(None) == {}
    assert _normalize_cookies({"session": "value"}) == {"session": "value"}
    assert _normalize_page_count("all") is None
    assert _normalize_page_count(2) == 2
    for value in (0, True, "two"):
        with pytest.raises(ValueError):
            _normalize_page_count(value)  # type: ignore[arg-type]
    for value in (0, True):
        with pytest.raises(ValueError):
            _validate_start_page(value)
    assert _normalize_project_types(["order", "ВАКАНСИЯ"])
    default_filters = _project_filters(
        query=None,
        category=None,
        min_budget=None,
        max_budget=None,
        types=None,
        with_budget=None,
    )
    assert default_filters.to_params()["kind"] == ["1"]
    with pytest.raises(ValueError, match="unknown project type"):
        _normalize_project_types("other")
    store, owned = _state_store(tmp_path / "state.db")
    assert owned
    assert store is not None


def test_client_url_and_response_helpers() -> None:
    client = FLClient(ClientConfig())
    assert client._absolute("projects/") == "https://www.fl.ru/projects/"
    assert client._projects_url(None).endswith("/projects/")
    assert client._projects_url("projects/category/dev").endswith("/projects/category/dev/")
    assert client._projects_url("https://example.test/x") == "https://example.test/x"
    assert client._freelancers_url(None, 2).endswith("/freelancers/page-2/")
    assert client._freelancers_url("https://example.test/team", 2).endswith("/team/page-2/")
    assert client._project_url(12).endswith("/projects/12/")
    assert client._username("https://www.fl.ru/users/name/") == "name"
    with pytest.raises(ValueError):
        client._username("https://www.fl.ru/no-user/")
    assert client._page_number("https://x/?page=4") == 4
    assert client._page_number("https://x/page-3/") == 3
    assert client._page_number(None) is None
    assert client._endpoint("https://x/projects/1") == "projects"
    assert client._endpoint("https://x/") == "root"
    assert client._url_with_params("https://x", {"a": [1, 2]}) == "https://x?a=1&a=2"
    response = httpx.Response(200, headers={"Date": "invalid"})
    assert FLClient._response_datetime(response).tzinfo is not None
    dated = httpx.Response(200, headers={"Date": "Sat, 25 Jul 2026 12:00:00 GMT"})
    assert FLClient._response_datetime(dated) == datetime(2026, 7, 25, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_client_iteration_errors_and_validation() -> None:
    client = FLClient(ClientConfig(respect_robots_txt=False))
    with pytest.raises(ValueError, match="batch_size"):
        _ = [page async for page in client.iter_project_pages(batch_size=0)]

    client.get_projects_batch_result = AsyncMock(
        return_value=type("Batch", (), {"failed": [], "successful": []})()
    )  # type: ignore[method-assign]
    assert [page async for page in client.iter_project_pages(max_pages=1)] == []

    order = ProjectSummary(
        id=1,
        title="order",
        url="https://www.fl.ru/projects/1/",
        kind=ProjectKind.ORDER,
    )
    vacancy = ProjectSummary(
        id=2,
        title="vacancy",
        url="https://www.fl.ru/projects/2/",
        kind=ProjectKind.VACANCY,
    )
    client.iter_project_pages = lambda **_: _async_pages(_page(items=[order, vacancy]))  # type: ignore[method-assign]
    filtered = [
        item
        async for item in client.iter_projects(
            filters=ProjectFilters(project_types=frozenset({ProjectType.ORDER}))
        )
    ]
    assert filtered == [order]

    empty = _page()
    with pytest.raises(EmptyPageError):
        client._validate_project_page(empty)
    drift = _page()
    drift.diagnostics.candidate_links_found = 1
    with pytest.raises(SelectorDriftError):
        client._validate_project_page(drift)
    accepted = _page(items=[ProjectSummary(id=1, title="x", url="https://www.fl.ru/projects/1/")])
    client._validate_project_page(accepted)
    await client.close()


async def _async_pages(*pages: ProjectPage):  # type: ignore[no-untyped-def]
    for page in pages:
        yield page


@pytest.mark.asyncio
async def test_simple_client_delegates_single_page_and_details() -> None:
    api = Client(respect_robots_txt=False)
    item = ProjectSummary(id=1, title="x", url="https://www.fl.ru/projects/1/")
    api.get_projects = AsyncMock(return_value=[item])  # type: ignore[method-assign]
    api.get_project_details_result = AsyncMock(
        return_value=type(
            "Result", (), {"successful": [item], "raise_for_errors": lambda self: None}
        )()
    )  # type: ignore[method-assign]
    assert await api.projects() == [item]
    assert await api.projects(details=True) == [item]
    with pytest.raises(ValueError, match="pages"):
        await api.user("name", pages=0)
    await api.close()
