from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from flru import ClientConfig, ConfigurationError
from flru.parsers import parse_project_list
from flru.parsers.common import (
    clean_text,
    parse_decimal,
    parse_int,
    parse_money,
    parse_ru_datetime,
    project_id_from_url,
    username_from_url,
)


def test_common_edge_cases() -> None:
    assert clean_text(None) is None
    assert parse_int("abc") is None
    assert parse_decimal("abc") is None
    assert parse_money("по договоренности").negotiable
    assert project_id_from_url("https://www.fl.ru/projects/nope") is None
    assert username_from_url("https://www.fl.ru/nope") is None
    now = datetime(2026, 7, 25, 12, tzinfo=ZoneInfo("Europe/Moscow"))
    assert parse_ru_datetime("сегодня 10:30", now=now).hour == 10
    assert parse_ru_datetime("вчера 09:00", now=now).day == 24
    assert parse_ru_datetime("2 часа назад", now=now).hour == 10
    assert parse_ru_datetime("31 февраля 2026", now=now) is None


def test_project_diagnostics() -> None:
    html = (Path(__file__).parent / "fixtures" / "projects.html").read_text(encoding="utf-8")
    page = parse_project_list(html, "https://www.fl.ru/projects/")
    assert page.diagnostics.confidence == 1
    assert page.diagnostics.candidate_links_found == 2
    assert page.items[0].source is not None
    assert page.items[0].published_at.tzinfo is not None

    end = parse_project_list("<html><main>Нет проектов</main></html>", "https://www.fl.ru/projects/?page=2", page=2)
    assert "catalog_end" in end.diagnostics.warnings


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate_limit": __import__("flru").RateLimitConfig(requests_per_second=0)},
        {"rate_limit": __import__("flru").RateLimitConfig(max_concurrency=0)},
        {"retry": __import__("flru").RetryConfig(max_attempts=0)},
        {"retry": __import__("flru").RetryConfig(total_timeout=0)},
        {"user_agents": ()},
        {"base_url": "https://evil.test"},
    ],
)
def test_config_validation(kwargs) -> None:
    with pytest.raises(ConfigurationError):
        ClientConfig(**kwargs)
