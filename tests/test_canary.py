from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from flru import (
    AuthenticationRequired,
    BlockedError,
    EmptyPageError,
    FreelancerPage,
    FreelancerSummary,
    ParseDiagnostics,
    ProjectDetail,
    ProjectPage,
    ProjectSummary,
    SelectorDriftError,
    UserProfile,
    canary,
)
from flru.parsers.common import (
    content_fingerprint,
    page_fingerprint,
    structural_fingerprint,
    structural_similarity,
    structural_tokens,
)


def diagnostics() -> ParseDiagnostics:
    return ParseDiagnostics(page_fingerprint="content", confidence=0.9)


class FakeClient:
    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_projects_page(self, _page: int) -> ProjectPage:
        return ProjectPage(
            page=1,
            url="https://www.fl.ru/projects/",
            items=[
                ProjectSummary(
                    id=1,
                    title="One",
                    url="https://www.fl.ru/projects/1/one.html",
                )
            ],
            diagnostics=diagnostics(),
        )

    async def get_project(self, _value: str) -> ProjectDetail:
        return ProjectDetail(
            id=1,
            title="One",
            url="https://www.fl.ru/projects/1/one.html",
            full_description="Description",
        )

    async def get_freelancers_page(self, _page: int) -> FreelancerPage:
        return FreelancerPage(
            page=1,
            url="https://www.fl.ru/freelancers/",
            items=[
                FreelancerSummary(
                    username="dev",
                    name="Developer",
                    url="https://www.fl.ru/users/dev/",
                )
            ],
            diagnostics=diagnostics(),
        )

    async def get_user(self, _username: str) -> UserProfile:
        return UserProfile(
            username="dev",
            name="Developer",
            url="https://www.fl.ru/users/dev/",
        )

    async def get_html(self, _url: str) -> str:
        return "<main class='catalog'><a href='/x'>Changed text 123</a></main>"


@pytest.mark.asyncio
async def test_multi_surface_canary_passes(monkeypatch) -> None:
    monkeypatch.setattr(canary, "FLClient", FakeClient)
    result = await canary.run_canary()
    assert result["ok"] is True
    assert result["warnings"] == ["baseline_unavailable"]
    assert [item["check_id"] for item in result["checks"]] == [
        "project_list",
        "project_detail",
        "freelancer_list",
        "freelancer_summary",
        "user_profile",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "category"),
    [
        (BlockedError("x"), "blocked"),
        (AuthenticationRequired("x"), "authentication_required"),
        (EmptyPageError("x"), "empty_page"),
        (SelectorDriftError("x"), "selector_drift"),
        (RuntimeError("x"), "unexpected_exception"),
    ],
)
async def test_canary_failure_categories(error: Exception, category: str) -> None:
    async def operation():
        raise error

    result = await canary._check("x", "/x", operation)
    assert result["failure_category"] == category


def test_structural_fingerprint_ignores_text_changes() -> None:
    left = "<main class='catalog'><a href='/1'>First 123</a></main>"
    right = "<main class='catalog'><a href='/99'>Completely different</a></main>"
    assert page_fingerprint(left) == content_fingerprint(left)
    assert content_fingerprint(left) != content_fingerprint(right)
    assert structural_fingerprint(left) == structural_fingerprint(right)
    assert structural_similarity(left, right) == 1
    assert "class:catalog" in structural_tokens(left)


def test_canary_main_reads_baseline_and_fails(monkeypatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"ok": True}), encoding="utf-8")

    async def failed_canary(**_kwargs):
        return {"ok": False, "checks": [], "warnings": []}

    monkeypatch.setattr(canary, "run_canary", failed_canary)
    monkeypatch.setattr(sys, "argv", ["flru-canary", "--baseline", str(baseline), "--pretty"])
    with pytest.raises(SystemExit):
        canary.main()
