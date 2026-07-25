from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from ..models import FreelancerPage, FreelancerSummary, Link, ParseDiagnostics
from .common import (
    absolute_url,
    clean_text,
    multiline_text_of,
    page_fingerprint,
    parse_decimal,
    parse_int,
    text_of,
    username_from_url,
    utc_now,
)

USER_HREF_RE = re.compile(r"^/users/[^/?#]+/?$")


def _find_card(anchor: Tag) -> Tag:
    for parent in anchor.parents:
        if not isinstance(parent, Tag):
            continue
        classes = " ".join(parent.get("class", []))
        if parent.name in {"article", "li"} or re.search(
            r"(?:freelancer|user-card|b-user|catalog-item)", classes, re.IGNORECASE
        ):
            return parent
        if parent.name in {"main", "body"}:
            break
    return anchor.find_parent("div") or anchor


def _next_url(soup: BeautifulSoup, url: str, page: int) -> str | None:
    explicit = soup.select_one('a[rel="next"], a[aria-label*="След" i], a[title*="След" i]')
    if explicit and explicit.get("href"):
        return absolute_url(url, str(explicit.get("href")))
    wanted = f"page-{page + 1}"
    return next(
        (
            absolute_url(url, str(anchor.get("href")))
            for anchor in soup.select("a[href]")
            if wanted in str(anchor.get("href"))
        ),
        None,
    )


def parse_freelancer_list(
    html: str,
    url: str,
    *,
    page: int = 1,
    store_raw_html: bool = False,
    fetched_at: datetime | None = None,
) -> FreelancerPage:
    _ = fetched_at or utc_now()
    soup = BeautifulSoup(html, "lxml")
    root_selector = "main" if soup.select_one("main") else "body"
    root = soup.select_one(root_selector) or soup
    candidates = root.find_all("a", href=USER_HREF_RE)
    items: list[FreelancerSummary] = []
    seen: set[str] = set()
    for anchor in candidates:
        profile_url = absolute_url(url, str(anchor.get("href")))
        username, name = username_from_url(profile_url or ""), text_of(anchor)
        if not profile_url or not username or not name or username in seen:
            continue
        card = _find_card(anchor)
        card_text = multiline_text_of(card) or ""
        if not any(
            marker in card_text.casefold()
            for marker in ("опыт:", "портфолио:", "отзыв", "предложить заказ", "сроки и цены")
        ):
            continue
        seen.add(username)
        avatar = card.select_one("img[src], img[data-src]")
        experience = re.search(r"Опыт:\s*([^\n]+)", card_text, re.IGNORECASE)
        portfolio = re.search(r"Портфолио:\s*(\d+)\s+работ", card_text, re.IGNORECASE)
        reviews = re.search(r"(\d+)\s+отзыв", card_text, re.IGNORECASE)
        rating = re.search(r"Рейтинг\s*[:]?\s*([\d\s.,]+)", card_text, re.IGNORECASE)
        specialization = next(
            (
                clean_text(line)
                for line in card_text.splitlines()
                if ":" in line and not line.casefold().startswith(("опыт:", "портфолио:"))
            ),
            None,
        )
        location = None
        if "," in name:
            name, location = [clean_text(part) for part in name.split(",", 1)]
        portfolio_links = [
            Link(text=text_of(item_anchor), url=href)
            for item_anchor in card.select("a[href]")
            if (href := absolute_url(url, str(item_anchor.get("href"))))
            and href != profile_url
            and "/portfolio/" in urlsplit(href).path
        ]
        items.append(
            FreelancerSummary(
                username=username,
                name=name,
                url=profile_url,
                avatar_url=absolute_url(url, str(avatar.get("src") or avatar.get("data-src")))
                if avatar
                else None,
                role="freelancer",
                location=location,
                rating=parse_decimal(rating.group(1)) if rating else None,
                specialization=specialization,
                experience_raw=clean_text(experience.group(1)) if experience else None,
                portfolio_count=parse_int(portfolio.group(1)) if portfolio else None,
                reviews_count=parse_int(reviews.group(1)) if reviews else None,
                description=card_text,
                portfolio_links=portfolio_links,
                extra={"card_text": card_text, "field_sources": {"profile": "user_url_pattern"}},
            )
        )
    next_url = _next_url(soup, url, page)
    warnings = ["catalog_end"] if not items and not next_url and page > 1 else []
    return FreelancerPage(
        page=page,
        url=url,
        items=items,
        has_next=next_url is not None,
        next_url=next_url,
        diagnostics=ParseDiagnostics(
            cards_found=len({id(_find_card(anchor)) for anchor in candidates}),
            candidate_links_found=len(candidates),
            selectors_matched=[root_selector],
            missing_required=[] if items else ["items"],
            warnings=warnings,
            field_sources={"items": "user_url_pattern"},
            confidence=1.0 if items else 0.8 if warnings else 0.2,
            page_fingerprint=page_fingerprint(html),
        ),
        raw_html=html if store_raw_html else None,
    )
