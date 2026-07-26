from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from ..models import Heading, Image, Link, Money, PageData, SourceInfo, TableData

SPACE_RE = re.compile(r"[\s\u00a0]+")
PROJECT_URL_RE = re.compile(r"/projects/(?P<id>\d+)(?:(?:/[^?#]*)?\.html|/)?(?:[?#].*)?$")
USER_URL_RE = re.compile(r"/users/(?P<username>[^/?#]+)/?(?:[^?#]*)?$")
NUMBER_RE = re.compile(r"\d[\d\s\u00a0]*")
MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def page_fingerprint(html: str) -> str:
    """Return a content fingerprint (legacy public name)."""
    return content_fingerprint(html)


def content_fingerprint(html: str) -> str:
    """Hash normalized page content, including reader-visible text."""
    normalized = SPACE_RE.sub(" ", html).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def structural_tokens(html: str) -> frozenset[str]:
    """Extract stable markup signals while ignoring text and volatile identifiers."""
    soup = BeautifulSoup(html, "lxml")
    tokens: set[str] = set()
    for node in soup.find_all(True):
        tokens.add(f"tag:{node.name}")
        for class_name in node.get("class", []):
            normalized = str(class_name).casefold()
            if len(normalized) <= 40 and not re.search(r"\d{4,}|[a-f0-9]{10,}", normalized):
                tokens.add(f"class:{normalized}")
    link_count = len(soup.find_all("a", href=True))
    bucket = min(link_count // 10, 10)
    tokens.add(f"link_bucket:{bucket}")
    return frozenset(tokens)


def structural_fingerprint(html: str) -> str:
    payload = "\n".join(sorted(structural_tokens(html)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def structural_similarity(left: str, right: str) -> float:
    left_tokens = structural_tokens(left)
    right_tokens = structural_tokens(right)
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 1.0


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = SPACE_RE.sub(" ", value).strip()
    return text or None


def text_of(node: Tag | None, separator: str = " ") -> str | None:
    return clean_text(node.get_text(separator, strip=True)) if node else None


def multiline_text_of(node: Tag | BeautifulSoup | None) -> str | None:
    if node is None:
        return None
    lines = [clean_text(str(value)) for value in node.stripped_strings]
    return "\n".join(line for line in lines if line) or None


def absolute_url(base_url: str, value: str | None) -> str | None:
    return urljoin(base_url, value) if value else None


def project_id_from_url(url: str) -> int | None:
    match = PROJECT_URL_RE.search(urlsplit(url).path)
    return int(match.group("id")) if match else None


def username_from_url(url: str) -> str | None:
    match = USER_URL_RE.search(urlsplit(url).path)
    return match.group("username") if match else None


def first_text(root: Tag | BeautifulSoup, selectors: Iterable[str]) -> str | None:
    for selector in selectors:
        value = text_of(root.select_one(selector))
        if value:
            return value
    return None


def first_attr(root: Tag | BeautifulSoup, selectors: Iterable[str], attribute: str) -> str | None:
    for selector in selectors:
        node = root.select_one(selector)
        if node and node.get(attribute):
            return str(node.get(attribute))
    return None


def parse_int(value: str | None) -> int | None:
    match = NUMBER_RE.search(value or "")
    return int(re.sub(r"\D", "", match.group())) if match else None


def parse_decimal(value: str | None) -> Decimal | None:
    match = re.search(r"-?\d[\d\s\u00a0]*(?:[.,]\d+)?", value or "")
    if not match:
        return None
    normalized = re.sub(r"[\s\u00a0]", "", match.group()).replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_money(value: str | None) -> Money | None:
    raw = clean_text(value)
    if not raw:
        return None
    folded = raw.casefold()
    currency = (
        "RUB"
        if "₽" in raw or "руб" in folded
        else "USD"
        if "$" in raw or "usd" in folded
        else "EUR"
        if "€" in raw or "eur" in folded
        else None
    )
    # Project cards often append counters and durations after the budget
    # (for example, a price followed by a two-day duration). Only numbers through the
    # final currency marker belong to the monetary range.
    currency_matches = list(re.finditer(r"₽|руб(?:\.|лей|ля)?|\$|usd|€|eur", raw, re.IGNORECASE))
    amount_text = raw[: currency_matches[-1].end()] if currency_matches else raw
    amounts = [
        parse_decimal(part)
        for part in re.findall(r"\d[\d\s\u00a0]*(?:[.,]\d+)?", amount_text)
    ]
    numbers = [item for item in amounts if item is not None]
    return Money(
        amount_min=numbers[0] if numbers else None,
        amount_max=numbers[1] if len(numbers) > 1 else (numbers[0] if numbers else None),
        currency=currency,
        negotiable="договор" in folded,
        interview_based="собеседован" in folded,
        raw=raw,
    )


def parse_ru_datetime(
    value: str | None,
    *,
    now: datetime | None = None,
    timezone_name: str = "Europe/Moscow",
) -> datetime | None:
    if not (text := clean_text(value)):
        return None
    zone = ZoneInfo(timezone_name)
    now = now or datetime.now(zone)
    now = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    folded = text.casefold()
    if folded.startswith("сегодня"):
        time_match = re.search(r"(\d{1,2}):(\d{2})", folded)
        return now.replace(
            hour=int(time_match.group(1)) if time_match else 0,
            minute=int(time_match.group(2)) if time_match else 0,
            second=0,
            microsecond=0,
        )
    if folded.startswith("вчера"):
        time_match = re.search(r"(\d{1,2}):(\d{2})", folded)
        value_dt = now - timedelta(days=1)
        return value_dt.replace(
            hour=int(time_match.group(1)) if time_match else 0,
            minute=int(time_match.group(2)) if time_match else 0,
            second=0,
            microsecond=0,
        )
    absolute = re.search(
        r"(?P<day>\d{1,2})\s+(?P<month>[а-яё]+)(?:\s+(?P<year>\d{4}))?(?:[^\d]+(?P<hour>\d{1,2}):(?P<minute>\d{2}))?",
        folded,
    )
    if absolute and absolute.group("month") in MONTHS_RU:
        try:
            candidate = datetime(
                int(absolute.group("year") or now.year),
                MONTHS_RU[absolute.group("month")],
                int(absolute.group("day")),
                int(absolute.group("hour") or 0),
                int(absolute.group("minute") or 0),
                tzinfo=zone,
            )
            if absolute.group("year") is None and candidate - now > timedelta(days=31):
                candidate = candidate.replace(year=candidate.year - 1)
            return candidate
        except ValueError:
            return None
    relative = re.search(
        r"(?P<count>\d+)\s+(?P<unit>минут\w*|час\w*|дн\w*|день|дня|недел\w*|месяц\w*)\s+назад",
        folded,
    )
    if relative:
        count, unit = int(relative.group("count")), relative.group("unit")
        delta = (
            timedelta(minutes=count)
            if unit.startswith("минут")
            else timedelta(hours=count)
            if unit.startswith("час")
            else timedelta(days=count)
            if unit.startswith(("дн", "день", "дня"))
            else timedelta(weeks=count)
            if unit.startswith("недел")
            else timedelta(days=count * 30)
        )
        return now - delta
    return None


def extract_meta(soup: BeautifulSoup) -> dict[str, str]:
    return {
        str(node.get("name") or node.get("property")): str(node.get("content"))
        for node in soup.select("meta[name], meta[property]")
        if (node.get("name") or node.get("property")) and node.get("content")
    }


def extract_json_ld(soup: BeautifulSoup) -> list[Any]:
    result: list[Any] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            result.append(json.loads(node.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def extract_links(root: Tag | BeautifulSoup, base_url: str) -> list[Link]:
    result: list[Link] = []
    seen: set[str] = set()
    for node in root.select("a[href]"):
        url = absolute_url(base_url, str(node.get("href")))
        if not url or url in seen or url.startswith(("javascript:", "mailto:")):
            continue
        seen.add(url)
        rel_value = node.get("rel")
        rel = (
            " ".join(rel_value) if isinstance(rel_value, list) else clean_text(str(rel_value or ""))
        )
        result.append(Link(text=text_of(node), url=url, rel=rel))
    return result


def extract_images(root: Tag | BeautifulSoup, base_url: str) -> list[Image]:
    result: list[Image] = []
    seen: set[str] = set()
    for node in root.select("img[src], img[data-src]"):
        url = absolute_url(base_url, str(node.get("src") or node.get("data-src")))
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(
            Image(
                url=url,
                alt=clean_text(str(node.get("alt") or "")),
                title=clean_text(str(node.get("title") or "")),
            )
        )
    return result


def parse_generic_page(
    html: str, url: str, *, store_raw_html: bool = False, fetched_at: datetime | None = None
) -> PageData:
    soup = BeautifulSoup(html, "lxml")
    main = soup.select_one("main") or soup.body or soup
    tables: list[TableData] = []
    for table in main.select("table"):
        rows: list[list[str]] = []
        headers: list[str] = []
        for row in table.select("tr"):
            cells = [text_of(cell) or "" for cell in row.select("th,td")]
            if not cells:
                continue
            if row.select("th") and not headers:
                headers = cells
            else:
                rows.append(cells)
        tables.append(TableData(headers=headers, rows=rows))
    canonical = first_attr(soup, ['link[rel="canonical"]'], "href")
    return PageData(
        url=url,
        title=clean_text(soup.title.string if soup.title else None),
        canonical_url=absolute_url(url, canonical),
        metadata=extract_meta(soup),
        headings=[
            Heading(level=int(node.name[1]), text=text_of(node) or "")
            for node in main.select("h1,h2,h3,h4,h5,h6")
            if text_of(node)
        ],
        paragraphs=[text for node in main.select("p") if (text := text_of(node))],
        lists=[
            items
            for node in main.select("ul,ol")
            if (
                items := [
                    text for li in node.find_all("li", recursive=False) if (text := text_of(li))
                ]
            )
        ],
        tables=tables,
        links=extract_links(main, url),
        images=extract_images(main, url),
        json_ld=extract_json_ld(soup),
        text=multiline_text_of(main),
        raw_html=html if store_raw_html else None,
        source=SourceInfo(source_url=url, fetched_at=fetched_at or utc_now()),
    )
