from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ..models import (
    Attachment,
    ParseDiagnostics,
    ProjectDetail,
    ProjectKind,
    ProjectPage,
    ProjectStatus,
    ProjectSummary,
    SourceInfo,
    UserSummary,
)
from .common import (
    PROJECT_URL_RE,
    absolute_url,
    clean_text,
    extract_images,
    extract_json_ld,
    extract_links,
    extract_meta,
    first_attr,
    first_text,
    multiline_text_of,
    page_fingerprint,
    parse_money,
    parse_ru_datetime,
    project_id_from_url,
    text_of,
    username_from_url,
    utc_now,
)

TITLE_SELECTORS = ("h1", '[itemprop="name"]', ".b-page__title", ".project-title")
DESCRIPTION_SELECTORS = (
    '[itemprop="description"]', ".b-layout__txt_padbot_20", ".b-post__txt.text-5",
    ".project-description", '[class*="description"]',
)


def _find_card(anchor: Tag) -> Tag:
    for parent in anchor.parents:
        if not isinstance(parent, Tag):
            continue
        classes = set(parent.get("class", []))
        if (
            parent.name == "article"
            or classes.intersection({"b-post", "project-card", "project", "catalog-item"})
            or str(parent.get("data-id", "")).startswith("qa-lenta-")
        ):
            return parent
        if parent.name in {"main", "body"}:
            break
    heading = anchor.find_parent(["h2", "h3"])
    if heading and isinstance(heading.parent, Tag) and heading.parent.name not in {"main", "body"}:
        return heading.parent
    return anchor.parent if isinstance(anchor.parent, Tag) else anchor


def _kind(text: str) -> ProjectKind:
    folded = text.casefold()
    if "вакансия" in folded:
        return ProjectKind.VACANCY
    if "конкурс" in folded:
        return ProjectKind.CONTEST
    if "заказ" in folded or "проект" in folded:
        return ProjectKind.ORDER
    return ProjectKind.UNKNOWN


def _status(text: str) -> ProjectStatus:
    folded = text.casefold()
    if "исполнитель определ" in folded or "исполнитель выбран" in folded:
        return ProjectStatus.EXECUTOR_SELECTED
    if any(value in folded for value in ("закрыт", "завершен", "завершён")):
        return ProjectStatus.CLOSED
    if "откликнуться" in folded:
        return ProjectStatus.OPEN
    return ProjectStatus.UNKNOWN


def _candidate_description(card: Tag, title: str) -> tuple[str | None, str]:
    value = first_text(card, DESCRIPTION_SELECTORS)
    if value and value != title:
        return value, "css"
    chunks = [
        text for node in card.find_all(["p", "div"], recursive=True)
        if (text := text_of(node)) and text != title and len(text) >= 20
        and not any(token in text.casefold() for token in ("откликнуться", "ответов", "больше 300"))
    ]
    return (max(chunks, key=len), "text_fallback") if chunks else (None, "missing")


def _budget_text(card: Tag) -> tuple[str | None, str]:
    value = first_text(card, ('[class*="price"]', '[class*="budget"]', ".b-post__price", '[itemprop="price"]'))
    if value:
        return value, "css"
    text = text_of(card) or ""
    for pattern in (
        r"(?:от\s+)?\d[\d\s\u00a0]*(?:\s*[₽$€]|\s*(?:руб(?:лей|ля|ль)?|USD|EUR))(?:\s*[–-]\s*\d[\d\s\u00a0]*(?:\s*[₽$€]|\s*(?:руб(?:лей|ля|ль)?|USD|EUR)))?",
        r"по договоренности", r"по результатам собеседования",
    ):
        if match := re.search(pattern, text, re.IGNORECASE):
            return clean_text(match.group()), "text_fallback"
    return None, "missing"


def _published_text(text: str) -> str | None:
    for pattern in (
        r"(?:сегодня|вчера)[^\n]{0,20}\d{1,2}:\d{2}",
        r"\d{1,2}\s+[А-Яа-яЁё]+(?:\s+\d{4})?[^\n]{0,20}\d{1,2}:\d{2}",
        r"\d+\s+(?:минут\w*|час\w*|дн\w*|недел\w*)\s+назад",
    ):
        if match := re.search(pattern, text, re.IGNORECASE):
            return clean_text(match.group())
    return None


def _next_page_url(soup: BeautifulSoup, url: str, page: int) -> str | None:
    explicit = soup.select_one('a[rel="next"], a[aria-label*="След" i], a[title*="След" i]')
    if explicit and explicit.get("href"):
        return absolute_url(url, str(explicit.get("href")))
    for anchor in soup.select("a[href]"):
        href = absolute_url(url, str(anchor.get("href")))
        if href and (
            parse_qs(urlsplit(href).query).get("page") == [str(page + 1)]
            or re.search(rf"/page-{page + 1}/?$", urlsplit(href).path)
        ):
            return href
    return None


def parse_project_list(
    html: str,
    url: str,
    *,
    page: int = 1,
    store_raw_html: bool = False,
    fetched_at: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> ProjectPage:
    fetched_at = fetched_at or utc_now()
    soup = BeautifulSoup(html, "lxml")
    root_selector = "#projects-list" if soup.select_one("#projects-list") else "main" if soup.select_one("main") else "body"
    root = soup.select_one(root_selector) or soup
    anchors = root.find_all("a", href=PROJECT_URL_RE)
    items: list[ProjectSummary] = []
    seen: set[int] = set()

    for anchor in anchors:
        href = absolute_url(url, str(anchor.get("href")))
        project_id = project_id_from_url(href or "")
        title = text_of(anchor)
        if project_id is None or not title or project_id in seen or not href:
            continue
        seen.add(project_id)
        card = _find_card(anchor)
        card_text = multiline_text_of(card) or ""
        user_anchor = card.find("a", href=re.compile(r"/users/[^/?#]+/?"))
        customer = None
        if user_anchor:
            user_url = absolute_url(url, str(user_anchor.get("href")))
            customer = UserSummary(username=username_from_url(user_url or ""), name=text_of(user_anchor), url=user_url)
        description, description_source = _candidate_description(card, title)
        budget_raw, budget_source = _budget_text(card)
        response_match = re.search(r"(\d+)\s+ответ", card_text, re.IGNORECASE)
        views_match = re.search(r"(?:больше\s+)?\d+\s+(?:просмотр|$)", card_text, re.IGNORECASE)
        location_match = re.search(r"(?:Вакансия|Заказ)\s*\(([^)]+)\)", card_text, re.IGNORECASE)
        image = card.select_one("img[src], img[data-src]")
        published_raw = _published_text(card_text)
        items.append(ProjectSummary(
            id=project_id, title=title, url=href, description=description,
            budget=parse_money(budget_raw), kind=_kind(card_text), status=_status(card_text),
            location=clean_text(location_match.group(1)) if location_match else None,
            published_at=parse_ru_datetime(published_raw, now=fetched_at, timezone_name=timezone_name),
            published_raw=published_raw,
            responses_count=int(response_match.group(1)) if response_match else None,
            views_raw=clean_text(views_match.group()) if views_match else None,
            customer=customer,
            image_url=absolute_url(url, str(image.get("src") or image.get("data-src"))) if image else None,
            source=SourceInfo(source_url=url, fetched_at=fetched_at),
            extra={"card_text": card_text, "field_sources": {"title": "url_anchor", "description": description_source, "budget": budget_source}},
        ))

    next_url = _next_page_url(soup, url, page)
    lower_text = (multiline_text_of(root) or "").casefold()
    warnings: list[str] = []
    if not items and not next_url and (page > 1 or any(marker in lower_text for marker in ("ничего не найдено", "нет проектов", "заказов не найдено"))):
        warnings.append("catalog_end")
    missing = [] if items else ["items"]
    confidence = 1.0 if items else 0.8 if "catalog_end" in warnings else 0.2
    diagnostics = ParseDiagnostics(
        cards_found=len({id(_find_card(anchor)) for anchor in anchors}),
        candidate_links_found=len(anchors),
        selectors_matched=[root_selector], missing_required=missing, warnings=warnings,
        field_sources={"items": "project_url_pattern"}, confidence=confidence,
        page_fingerprint=page_fingerprint(html),
    )
    return ProjectPage(
        page=page, url=url, items=items, has_next=next_url is not None, next_url=next_url,
        diagnostics=diagnostics, raw_html=html if store_raw_html else None,
    )


def _description_from_detail(root: Tag, title: str) -> tuple[str | None, str]:
    value = first_text(root, DESCRIPTION_SELECTORS)
    if value and value != title:
        return value, "css"
    candidates = [
        text for node in root.find_all(["p", "div"], recursive=True)
        if (text := multiline_text_of(node)) and text != title and len(text) >= 30
        and not any(token in text.casefold() for token in ("зарегистрирован:", "информация о заказчике", "посмотреть другие заказы", "выберите способ верификации"))
    ]
    return (max(candidates, key=len), "text_fallback") if candidates else (None, "missing")


def parse_project_detail(
    html: str,
    url: str,
    *,
    store_raw_html: bool = False,
    fetched_at: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> ProjectDetail:
    fetched_at = fetched_at or utc_now()
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("main") or soup.body or soup
    json_ld = extract_json_ld(soup)
    json_title = next((item.get("name") for item in json_ld if isinstance(item, dict) and item.get("name")), None)
    css_title = first_text(root, TITLE_SELECTORS)
    meta_title = clean_text(first_attr(soup, ['meta[property="og:title"]'], "content"))
    title = clean_text(str(json_title)) if json_title else css_title or meta_title
    project_id = project_id_from_url(url)
    if not title or project_id is None:
        raise ValueError(f"Could not identify FL.ru project page: {url}")

    text = multiline_text_of(root) or ""
    budget_match = re.search(r"Бюджет:\s*([^\n]+)", text, re.IGNORECASE)
    published_match = re.search(r"Опубликован(?:о)?\s+([^\n]+)", text, re.IGNORECASE)
    updated_match = re.search(r"Последнее изменение:\s*([^\n]+)", text, re.IGNORECASE)
    response_match = re.search(r"(\d+)\s+ответ", text, re.IGNORECASE)
    user_anchor = root.find("a", href=re.compile(r"/users/[^/?#]+/?"))
    customer = None
    if user_anchor:
        user_url = absolute_url(url, str(user_anchor.get("href")))
        customer = UserSummary(username=username_from_url(user_url or ""), name=text_of(user_anchor), url=user_url)
    executor = None
    if marker := root.find(string=re.compile(r"Заказчик выбрал исполнителя", re.IGNORECASE)):
        parent = marker.parent if isinstance(marker.parent, Tag) else root
        if executor_anchor := parent.find_next("a", href=re.compile(r"/users/[^/?#]+/?")):
            executor_url = absolute_url(url, str(executor_anchor.get("href")))
            executor = UserSummary(username=username_from_url(executor_url or ""), name=text_of(executor_anchor), url=executor_url)

    links, images = extract_links(root, url), extract_images(root, url)
    attachments = [Attachment(name=link.text, url=link.url) for link in links if re.search(r"\.(?:pdf|docx?|xlsx?|zip|rar|7z|png|jpe?g)(?:\?|$)", link.url, re.IGNORECASE)]
    breadcrumbs = [text_of(node) or "" for node in root.select('[class*="breadcrumb"] a, nav[aria-label*="breadcrumb" i] a') if text_of(node)]
    if not breadcrumbs:
        breadcrumbs = [text_of(node) or "" for node in root.select("a[href*='/projects/category/']")[:4] if text_of(node)]
    full_description, description_source = _description_from_detail(root, title)
    published_raw = clean_text(published_match.group(1)) if published_match else None
    updated_raw = clean_text(updated_match.group(1)) if updated_match else None
    return ProjectDetail(
        id=project_id, title=title, url=url, description=full_description, full_description=full_description,
        budget=parse_money(budget_match.group(1) if budget_match else None), kind=_kind(text), status=_status(text),
        category=breadcrumbs[-2] if len(breadcrumbs) >= 2 else None,
        subcategory=breadcrumbs[-1] if breadcrumbs else None,
        published_at=parse_ru_datetime(published_raw, now=fetched_at, timezone_name=timezone_name), published_raw=published_raw,
        updated_at=parse_ru_datetime(updated_raw, now=fetched_at, timezone_name=timezone_name), updated_raw=updated_raw,
        responses_count=int(response_match.group(1)) if response_match else None,
        customer=customer, executor=executor, breadcrumbs=breadcrumbs, attachments=attachments,
        links=links, images=images, metadata=extract_meta(soup), raw_text=text,
        raw_html=html if store_raw_html else None, source=SourceInfo(source_url=url, fetched_at=fetched_at),
        extra={"field_sources": {"title": "json_ld" if json_title else "css" if css_title else "open_graph", "description": description_source}},
    )


def with_page(url: str, page: int) -> str:
    parts = list(urlsplit(url))
    query = parse_qs(parts[3], keep_blank_values=True)
    query["page"] = [str(page)]
    parts[3] = urlencode(query, doseq=True)
    return urlunsplit(parts)
