from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import monotonic
from typing import Any

from .client import FLClient
from .exceptions import (
    AuthenticationRequired,
    BlockedError,
    EmptyPageError,
    SelectorDriftError,
)
from .parsers.common import structural_fingerprint


def _category(error: Exception) -> str:
    if isinstance(error, BlockedError):
        return "blocked"
    if isinstance(error, AuthenticationRequired):
        return "authentication_required"
    if isinstance(error, EmptyPageError):
        return "empty_page"
    if isinstance(error, SelectorDriftError):
        return "selector_drift"
    return "unexpected_exception"


async def _check(
    check_id: str,
    url: str,
    operation: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    started = monotonic()
    try:
        values = await operation()
        return {
            "check_id": check_id,
            "status": "passed",
            "duration_seconds": monotonic() - started,
            "url": url,
            "failure_category": None,
            **values,
        }
    except Exception as exc:
        return {
            "check_id": check_id,
            "status": "failed",
            "duration_seconds": monotonic() - started,
            "url": url,
            "failure_category": _category(exc),
            "error": type(exc).__name__,
        }


async def run_canary(
    *,
    baseline: dict[str, Any] | None = None,
    confidence_threshold: float = 0.75,
) -> dict[str, object]:
    checks: list[dict[str, Any]] = []
    warnings = [] if baseline is not None else ["baseline_unavailable"]
    async with FLClient() as client:
        project_page = None
        freelancer_page = None

        async def project_list() -> dict[str, Any]:
            nonlocal project_page
            project_page = await client.get_projects_page(1)
            first = project_page.items[0]
            missing = [field for field in ("id", "title", "url") if not getattr(first, field, None)]
            confidence = project_page.diagnostics.confidence
            if missing:
                raise SelectorDriftError(f"Missing required fields: {missing}")
            if confidence < confidence_threshold:
                raise SelectorDriftError(f"Low confidence: {confidence}")
            html = await client.get_html("/projects/")
            return {
                "required_fields": ["id", "title", "url"],
                "missing_fields": missing,
                "confidence": confidence,
                "content_fingerprint": project_page.diagnostics.page_fingerprint,
                "structural_fingerprint": structural_fingerprint(html),
                "warnings": project_page.diagnostics.warnings,
            }

        checks.append(await _check("project_list", "/projects/", project_list))

        async def project_detail() -> dict[str, Any]:
            if project_page is None or not project_page.items:
                raise EmptyPageError("Project list has no item for detail canary")
            detail = await client.get_project(project_page.items[0].url)
            missing = [
                field for field in ("id", "title", "url") if not getattr(detail, field, None)
            ]
            if missing or not detail.full_description:
                raise SelectorDriftError(f"Missing project detail fields: {missing}")
            html = await client.get_html(detail.url)
            return {
                "required_fields": ["id", "title", "url", "full_description"],
                "missing_fields": missing,
                "confidence": None,
                "content_fingerprint": None,
                "structural_fingerprint": structural_fingerprint(html),
                "warnings": [],
            }

        detail_url = project_page.items[0].url if project_page and project_page.items else ""
        checks.append(await _check("project_detail", detail_url, project_detail))

        async def freelancer_list() -> dict[str, Any]:
            nonlocal freelancer_page
            freelancer_page = await client.get_freelancers_page(1)
            first = freelancer_page.items[0]
            missing = [
                field for field in ("username", "name", "url") if not getattr(first, field, None)
            ]
            if missing:
                raise SelectorDriftError(f"Missing freelancer fields: {missing}")
            return {
                "required_fields": ["username", "name", "url"],
                "missing_fields": missing,
                "confidence": freelancer_page.diagnostics.confidence,
                "content_fingerprint": freelancer_page.diagnostics.page_fingerprint,
                "structural_fingerprint": None,
                "warnings": freelancer_page.diagnostics.warnings,
            }

        checks.append(await _check("freelancer_list", "/freelancers/", freelancer_list))

        async def freelancer_summary() -> dict[str, Any]:
            if freelancer_page is None or not freelancer_page.items:
                raise EmptyPageError("Freelancer list has no summary")
            return {
                "required_fields": ["username", "name", "url"],
                "missing_fields": [],
                "confidence": freelancer_page.diagnostics.confidence,
                "content_fingerprint": freelancer_page.diagnostics.page_fingerprint,
                "structural_fingerprint": None,
                "warnings": [],
            }

        summary_url = (
            freelancer_page.items[0].url or "" if freelancer_page and freelancer_page.items else ""
        )
        checks.append(await _check("freelancer_summary", summary_url, freelancer_summary))

        async def user_profile() -> dict[str, Any]:
            if freelancer_page is None or not freelancer_page.items:
                raise EmptyPageError("Freelancer list has no user for profile canary")
            username = freelancer_page.items[0].username
            if not username:
                raise SelectorDriftError("Freelancer summary has no username")
            profile = await client.get_user(username)
            missing = [field for field in ("username", "url") if not getattr(profile, field, None)]
            if not profile.name:
                missing.append("name")
            if missing:
                raise SelectorDriftError(f"Missing profile fields: {missing}")
            html = await client.get_html(profile.url or "")
            return {
                "required_fields": ["username", "name", "url"],
                "missing_fields": missing,
                "confidence": None,
                "content_fingerprint": None,
                "structural_fingerprint": structural_fingerprint(html),
                "warnings": [],
            }

        checks.append(await _check("user_profile", summary_url, user_profile))

    return {
        "ok": all(check["status"] == "passed" for check in checks),
        "warnings": warnings,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a read-only FL.ru parser canary")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--confidence-threshold", type=float, default=0.75)
    args = parser.parse_args()
    baseline = None
    if args.baseline and args.baseline.exists():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    result = asyncio.run(
        run_canary(
            baseline=baseline,
            confidence_threshold=args.confidence_threshold,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
