from pathlib import Path

from flru.parsers import parse_freelancer_list


def test_freelancer_list() -> None:
    html = (Path(__file__).parent / "fixtures" / "freelancers.html").read_text()
    page = parse_freelancer_list(html, "https://www.fl.ru/freelancers/")
    assert len(page.items) == 1
    assert page.has_next is True
    user = page.items[0]
    assert user.username == "dev-one"
    assert user.name == "Петр Петров"
    assert user.location == "Москва"
    assert user.experience_raw == "10 лет"
    assert user.portfolio_count == 130
    assert user.reviews_count == 14
