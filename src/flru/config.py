from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit

from .exceptions import ConfigurationError

DEFAULT_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
)


@dataclass(slots=True, frozen=True)
class RetryConfig:
    max_attempts: int = 5
    base_delay: float = 0.75
    max_delay: float = 30.0
    jitter: float = 0.35
    retry_statuses: frozenset[int] = frozenset({408, 425, 429, 500, 502, 503, 504})
    respect_retry_after: bool = True
    total_timeout: float = 90.0
    max_total_delay: float = 45.0


@dataclass(slots=True, frozen=True)
class RateLimitConfig:
    requests_per_second: float = 1.0
    burst: int = 2
    max_concurrency: int = 5
    min_interval: float = 0.5
    interval_jitter: float = 0.15


@dataclass(slots=True, frozen=True)
class CircuitBreakerConfig:
    enabled: bool = True
    failure_threshold: int = 8
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 1
    scope: Literal["global", "endpoint", "endpoint_proxy"] = "endpoint_proxy"


@dataclass(slots=True, frozen=True)
class ProxyConfig:
    urls: tuple[str, ...] = ()
    strategy: Literal["round_robin", "random"] = "round_robin"
    max_failures: int = 3
    cooldown: float = 120.0
    direct_fallback: bool = True


@dataclass(slots=True, frozen=True)
class TimeoutConfig:
    connect: float = 10.0
    read: float = 30.0
    write: float = 15.0
    pool: float = 10.0


@dataclass(slots=True, frozen=True)
class ClientConfig:
    base_url: str = "https://www.fl.ru"
    retry: RetryConfig = field(default_factory=RetryConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    proxies: ProxyConfig = field(default_factory=ProxyConfig)
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)
    headers: Mapping[str, str] = field(default_factory=dict)
    cookies: Mapping[str, str] = field(default_factory=dict)
    user_agents: tuple[str, ...] = DEFAULT_USER_AGENTS
    rotate_user_agents: bool = True
    follow_redirects: bool = True
    verify_ssl: bool = True
    http2: bool = True
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_expiry: float = 30.0
    respect_robots_txt: bool = True
    robots_fail_closed: bool = False
    robots_cache_ttl: float = 3600.0
    store_raw_html: bool = False
    store_failed_html: bool = False
    failed_html_directory: str | None = None
    detect_blocks: bool = True
    allowed_hosts: frozenset[str] = frozenset({"fl.ru", "www.fl.ru"})
    allow_subdomains: bool = True
    parser_timezone: str = "Europe/Moscow"
    strict_parsing: bool = True

    def __post_init__(self) -> None:
        host = (urlsplit(self.base_url).hostname or "").casefold()
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "cookies", MappingProxyType(dict(self.cookies)))
        if self.rate_limit.requests_per_second <= 0:
            raise ConfigurationError("requests_per_second must be positive")
        if self.rate_limit.max_concurrency <= 0:
            raise ConfigurationError("max_concurrency must be positive")
        if self.rate_limit.min_interval < 0:
            raise ConfigurationError("min_interval must not be negative")
        if self.retry.max_attempts <= 0:
            raise ConfigurationError("max_attempts must be positive")
        if self.retry.total_timeout <= 0:
            raise ConfigurationError("total_timeout must be positive")
        if not self.user_agents:
            raise ConfigurationError("at least one user agent is required")
        if not host or not any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts):
            raise ConfigurationError("base_url host must be present in allowed_hosts")

    def with_cookies(self, cookies: Mapping[str, str]) -> ClientConfig:
        return replace(self, cookies={**self.cookies, **cookies})
