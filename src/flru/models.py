from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

PARSER_VERSION = "0.5.0"
SCHEMA_VERSION = "1"


class FLModel(BaseModel):
    model_config = ConfigDict(extra="allow", validate_assignment=True)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary."""
        return self.model_dump(mode="json")


class ProjectKind(StrEnum):
    ORDER = "order"
    VACANCY = "vacancy"
    CONTEST = "contest"
    UNKNOWN = "unknown"


class ProjectStatus(StrEnum):
    OPEN = "open"
    EXECUTOR_SELECTED = "executor_selected"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class ParseDiagnostics(FLModel):
    cards_found: int = 0
    candidate_links_found: int = 0
    parsed_count: int = 0
    filtered_count: int = 0
    unknown_kind_count: int = 0
    selectors_matched: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)
    confidence: float = 1.0
    page_fingerprint: str


class SourceInfo(FLModel):
    source_url: str
    fetched_at: datetime
    parser_version: str = PARSER_VERSION
    schema_version: str = SCHEMA_VERSION


class Money(FLModel):
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    currency: str | None = None
    negotiable: bool = False
    interview_based: bool = False
    raw: str | None = None

    @property
    def amount(self) -> Decimal | None:
        """Return the most representative single amount when available."""
        if self.amount_min == self.amount_max:
            return self.amount_min
        return self.amount_min or self.amount_max


class Link(FLModel):
    text: str | None = None
    url: str
    rel: str | None = None


class Image(FLModel):
    url: str
    alt: str | None = None
    title: str | None = None


class Attachment(FLModel):
    name: str | None = None
    url: str
    media_type: str | None = None


class UserSummary(FLModel):
    username: str | None = None
    user_id: int | None = None
    name: str | None = None
    url: str | None = None
    avatar_url: str | None = None
    role: str | None = None
    location: str | None = None
    rating: Decimal | None = None
    reviews_positive: int | None = None
    reviews_negative: int | None = None
    safe_deals: int | None = None
    verified: bool | None = None
    online: bool | None = None


class FreelancerSummary(UserSummary):
    specialization: str | None = None
    experience_raw: str | None = None
    portfolio_count: int | None = None
    reviews_count: int | None = None
    description: str | None = None
    portfolio_links: list[Link] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ProjectSummary(FLModel):
    id: int
    title: str
    url: str
    description: str | None = None
    budget: Money | None = None
    kind: ProjectKind = ProjectKind.UNKNOWN
    status: ProjectStatus = ProjectStatus.UNKNOWN
    category: str | None = None
    subcategory: str | None = None
    location: str | None = None
    published_at: datetime | None = None
    published_raw: str | None = None
    responses_count: int | None = None
    views_raw: str | None = None
    customer: UserSummary | None = None
    image_url: str | None = None
    source: SourceInfo | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def budget_min(self) -> Decimal | None:
        return self.budget.amount_min if self.budget else None

    @property
    def budget_max(self) -> Decimal | None:
        return self.budget.amount_max if self.budget else None

    @property
    def currency(self) -> str | None:
        return self.budget.currency if self.budget else None

    @property
    def customer_username(self) -> str | None:
        return self.customer.username if self.customer else None


class ProjectDetail(ProjectSummary):
    full_description: str | None = None
    updated_at: datetime | None = None
    updated_raw: str | None = None
    executor: UserSummary | None = None
    breadcrumbs: list[str] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    raw_text: str | None = None
    raw_html: str | None = None


class ProjectRecord(FLModel):
    project: ProjectSummary
    first_seen_at: datetime
    last_seen_at: datetime
    content_hash: str
    source_updated_at: datetime | None = None


class CrawlCheckpoint(FLModel):
    namespace: str = "projects"
    next_url: str | None = None
    next_page: int | None = None
    updated_at: datetime
    consecutive_known: int = 0


class Review(FLModel):
    author: UserSummary | None = None
    text: str | None = None
    rating: int | None = None
    sentiment: str | None = None
    created_at: datetime | None = None
    created_raw: str | None = None
    project_url: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PortfolioItem(FLModel):
    title: str | None = None
    url: str | None = None
    description: str | None = None
    image_url: str | None = None
    category: str | None = None
    price: Money | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class UserProfile(UserSummary):
    registered_raw: str | None = None
    last_seen_raw: str | None = None
    about: str | None = None
    skills: list[str] = Field(default_factory=list)
    specializations: list[str] = Field(default_factory=list)
    projects_count: int | None = None
    vacancies_count: int | None = None
    contests_count: int | None = None
    reviews: list[Review] = Field(default_factory=list)
    projects: list[ProjectSummary] = Field(default_factory=list)
    portfolio: list[PortfolioItem] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    raw_text: str | None = None
    raw_html: str | None = None
    source: SourceInfo | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Heading(FLModel):
    level: int
    text: str


class TableData(FLModel):
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class PageData(FLModel):
    url: str
    title: str | None = None
    canonical_url: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    headings: list[Heading] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    lists: list[list[str]] = Field(default_factory=list)
    tables: list[TableData] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    json_ld: list[Any] = Field(default_factory=list)
    text: str | None = None
    raw_html: str | None = None
    source: SourceInfo | None = None


class FreelancerPage(FLModel):
    page: int
    url: str
    items: list[FreelancerSummary] = Field(default_factory=list)
    has_next: bool = False
    next_url: str | None = None
    diagnostics: ParseDiagnostics
    raw_html: str | None = None


class ProjectPage(FLModel):
    page: int
    url: str
    items: list[ProjectSummary] = Field(default_factory=list)
    has_next: bool = False
    next_url: str | None = None
    diagnostics: ParseDiagnostics
    raw_html: str | None = None


class Category(FLModel):
    name: str
    url: str
    slug: str | None = None
    parent: str | None = None


class EndpointMetrics(FLModel):
    requests: int = 0
    failures: int = 0
    retries: int = 0
    latency_seconds_total: float = 0.0


class RequestMetrics(FLModel):
    requests_total: int = 0
    responses_total: int = 0
    retries_total: int = 0
    failures_total: int = 0
    blocked_total: int = 0
    rate_limited_total: int = 0
    parse_failures_total: int = 0
    selector_drift_total: int = 0
    event_handler_failures_total: int = 0
    bytes_received: int = 0
    latency_seconds_total: float = 0.0
    latency_samples: list[float] = Field(default_factory=list)
    endpoints: dict[str, EndpointMetrics] = Field(default_factory=dict)
