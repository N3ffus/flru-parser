from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from ..models import PortfolioItem, Review, SourceInfo, UserProfile, UserSummary
from .common import (
    absolute_url,
    clean_text,
    extract_images,
    extract_links,
    extract_meta,
    first_attr,
    first_text,
    multiline_text_of,
    parse_decimal,
    parse_money,
    text_of,
    username_from_url,
    utc_now,
)
from .projects import parse_project_list


def _title_fields(soup: BeautifulSoup) -> tuple[str | None, int | None, str | None, str | None]:
    title = clean_text(soup.title.string if soup.title else None) or ""
    name_match = re.search(r"(?:Заказчик|Фрилансер)\s+(.+?)\s+ID:\s*(\d+)", title, re.IGNORECASE)
    user_id = int(name_match.group(2)) if name_match else None
    name = clean_text(name_match.group(1)) if name_match else None
    role = None
    if title.casefold().startswith("заказчик"):
        role = "customer"
    elif title.casefold().startswith("фрилансер"):
        role = "freelancer"

    location = None
    location_match = re.search(r"FL\.ru,\s*(.+?)(?:\s*\(|$)", title, re.IGNORECASE)
    if location_match:
        location = clean_text(location_match.group(1))
    return name, user_id, role, location


def _extract_counts(text: str) -> tuple[int | None, int | None, int | None]:
    all_match = re.search(r"Все\s*\((\d+)\)", text, re.IGNORECASE)
    vacancies = re.search(r"Вакансии\s*\((\d+)\)", text, re.IGNORECASE)
    contests = re.search(r"Конкурсы\s*\((\d+)\)", text, re.IGNORECASE)
    return (
        int(all_match.group(1)) if all_match else None,
        int(vacancies.group(1)) if vacancies else None,
        int(contests.group(1)) if contests else None,
    )


def _extract_reviews(root: Tag, url: str) -> list[Review]:
    reviews: list[Review] = []
    candidates = root.select('[class*="opinion"], [class*="review"]')
    for node in candidates:
        text = multiline_text_of(node)
        if not text or len(text) < 15:
            continue
        author_anchor = node.find("a", href=re.compile(r"/users/[^/?#]+/?"))
        author = None
        if isinstance(author_anchor, Tag):
            author_url = absolute_url(url, str(author_anchor.get("href")))
            author = UserSummary(
                username=username_from_url(author_url or ""),
                name=text_of(author_anchor),
                url=author_url,
            )
        sentiment = "negative" if re.search(r"отрицат|минус", text, re.IGNORECASE) else None
        if sentiment is None and re.search(r"положит|плюс", text, re.IGNORECASE):
            sentiment = "positive"
        reviews.append(Review(author=author, text=text, sentiment=sentiment))
    return reviews


def _extract_portfolio(root: Tag, url: str) -> list[PortfolioItem]:
    items: list[PortfolioItem] = []
    seen: set[str] = set()
    for node in root.select('[class*="portfolio"] a[href], a[href*="/portfolio/"]'):
        href = absolute_url(url, str(node.get("href")))
        if not href or href in seen:
            continue
        seen.add(href)
        card = node.find_parent(["article", "li", "div"]) or node
        image = card.select_one("img[src], img[data-src]") if isinstance(card, Tag) else None
        image_url = (
            absolute_url(url, str(image.get("src") or image.get("data-src"))) if image else None
        )
        card_text = multiline_text_of(card) if isinstance(card, Tag) else text_of(node)
        items.append(
            PortfolioItem(
                title=text_of(node),
                url=href,
                description=card_text,
                image_url=image_url,
                price=parse_money(card_text),
            )
        )
    return items


def parse_user_profile(
    html: str,
    url: str,
    *,
    store_raw_html: bool = False,
    fetched_at: datetime | None = None,
) -> UserProfile:
    fetched_at = fetched_at or utc_now()
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("main") or soup.body or soup
    raw_text = multiline_text_of(root) or ""
    name_from_title, user_id, role, location = _title_fields(soup)
    name = (
        first_text(
            root,
            (
                "h1",
                '[itemprop="name"]',
                ".user-name",
                '[class*="profile"] h2',
            ),
        )
        or name_from_title
    )
    username = username_from_url(url)

    registered_match = re.search(r"На сайте\s+([^\n(]+)", raw_text, re.IGNORECASE)
    last_seen_match = re.search(r"\((?:заходил|заходила)\s+([^)]+)\)", raw_text, re.IGNORECASE)
    rating_match = re.search(r"Рейтинг\s+([\d\s.,]+)", raw_text, re.IGNORECASE)
    deals_match = re.search(r"Безопасные сделки\s+(\d+)", raw_text, re.IGNORECASE)
    reviews_match = re.search(r"Отзывы\s*\+?\s*(\d+)\s*-\s*(\d+)", raw_text, re.IGNORECASE)
    if not reviews_match:
        reviews_match = re.search(r"\+\s*(\d+)\s*-\s*(\d+)", raw_text)
    projects_count, vacancies_count, contests_count = _extract_counts(raw_text)

    avatar = first_attr(
        root,
        (
            '[itemprop="image"]',
            'img[class*="avatar"]',
            'img[class*="userpic"]',
        ),
        "src",
    )
    about = first_text(
        root,
        (
            '[itemprop="description"]',
            '[class*="about"]',
            '[class*="user-info"]',
        ),
    )
    skill_nodes = root.select(
        '[class*="skill"] a, [class*="specialization"] a, a[href*="/freelancers/"]'
    )
    skills = list(dict.fromkeys(text for node in skill_nodes if (text := text_of(node))))

    project_page = parse_project_list(html, url, page=1, store_raw_html=False)
    links = extract_links(root, url)
    images = extract_images(root, url)
    verified = bool(
        root.select_one('[class*="verified"], [title*="верифиц" i]')
        or re.search(r"верифицирован", raw_text, re.IGNORECASE)
    )

    return UserProfile(
        username=username,
        user_id=user_id,
        name=name,
        url=url,
        avatar_url=absolute_url(url, avatar),
        role=role,
        location=location,
        rating=parse_decimal(rating_match.group(1)) if rating_match else None,
        reviews_positive=int(reviews_match.group(1)) if reviews_match else None,
        reviews_negative=int(reviews_match.group(2)) if reviews_match else None,
        safe_deals=int(deals_match.group(1)) if deals_match else None,
        verified=verified,
        registered_raw=clean_text(registered_match.group(1)) if registered_match else None,
        last_seen_raw=clean_text(last_seen_match.group(1)) if last_seen_match else None,
        about=about,
        skills=skills,
        specializations=skills,
        projects_count=projects_count,
        vacancies_count=vacancies_count,
        contests_count=contests_count,
        reviews=_extract_reviews(root, url),
        projects=project_page.items,
        portfolio=_extract_portfolio(root, url),
        links=links,
        images=images,
        metadata=extract_meta(soup),
        raw_text=raw_text,
        raw_html=html if store_raw_html else None,
        source=SourceInfo(source_url=url, fetched_at=fetched_at),
        extra={"field_sources": {"name": "css_or_title", "profile": "user_url_pattern"}},
    )
