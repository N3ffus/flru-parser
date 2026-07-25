from decimal import Decimal
from pathlib import Path

from flru.models import ProjectKind, ProjectStatus
from flru.parsers import parse_project_detail, parse_project_list, parse_user_profile

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_project_list() -> None:
    page = parse_project_list(read("projects.html"), "https://www.fl.ru/projects/", page=1)
    assert len(page.items) == 2
    assert page.has_next is True
    assert page.next_url == "https://www.fl.ru/projects/?page=2"

    first = page.items[0]
    assert first.id == 5500001
    assert first.title == "Написать Python-парсер"
    assert first.kind is ProjectKind.ORDER
    assert first.status is ProjectStatus.UNKNOWN
    assert first.budget is not None
    assert first.budget.amount_min == Decimal("30000")
    assert first.customer is not None
    assert first.customer.username == "customer-one"
    assert first.responses_count == 12

    second = page.items[1]
    assert second.kind is ProjectKind.VACANCY
    assert second.location == "Россия, Москва"
    assert second.budget is not None
    assert second.budget.amount_max == Decimal("180000")


def test_project_detail() -> None:
    project = parse_project_detail(
        read("project.html"),
        "https://www.fl.ru/projects/5500001/python-parser.html",
    )
    assert project.id == 5500001
    assert project.title == "Написать Python-парсер"
    assert project.full_description is not None
    assert "пользователей" in project.full_description
    assert project.customer is not None
    assert project.customer.username == "customer-one"
    assert project.executor is not None
    assert project.executor.username == "dev-one"
    assert project.budget is not None
    assert project.budget.amount_min == Decimal("30000")
    assert len(project.attachments) == 1
    assert project.subcategory == "Python"


def test_user_profile() -> None:
    user = parse_user_profile(
        read("user.html"),
        "https://www.fl.ru/users/customer-one/",
    )
    assert user.username == "customer-one"
    assert user.user_id == 123456
    assert user.name == "Иван Иванов"
    assert user.role == "customer"
    assert user.location == "Россия, Москва"
    assert user.rating == Decimal("1543.25")
    assert user.reviews_positive == 12
    assert user.reviews_negative == 1
    assert user.safe_deals == 8
    assert user.projects_count == 2
    assert "Python" in user.skills
    assert len(user.projects) == 1
    assert len(user.reviews) >= 1
    assert len(user.portfolio) >= 1
