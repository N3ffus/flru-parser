from __future__ import annotations

import asyncio
import email.utils
import random
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .config import ClientConfig
from .exceptions import (
    AuthenticationRequired,
    BlockedError,
    HTTPStatusError,
    RateLimitedError,
    TransportError,
)
from .observability import EventHandler, Metrics, RequestEvent, Timer, emit
from .proxy import ProxyPool, ProxyState
from .resilience import AsyncRateLimiter, CircuitBreakerRegistry, RetryBudget
from .security import validate_url

_BLOCK_MARKERS = (
    "captcha",
    "подтвердите, что вы не робот",
    "доступ временно ограничен",
    "cloudflare",
)
_AUTH_MARKERS = (
    "необходимо авторизоваться",
    "войдите в аккаунт",
)
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class ResilientTransport:
    def __init__(
        self,
        config: ClientConfig,
        *,
        event_handler: EventHandler | None = None,
        client_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.metrics = Metrics()
        self._event_handler = event_handler
        self._rate_limiter = AsyncRateLimiter(config.rate_limit)
        self._circuits = CircuitBreakerRegistry(config.circuit_breaker)
        self._proxy_pool = ProxyPool(config.proxies)
        self._clients: dict[str | None, httpx.AsyncClient] = {}
        self._client_transport = client_transport
        self._cookies = dict(config.cookies)
        self._closed = False

    @property
    def proxy_pool(self) -> ProxyPool:
        return self._proxy_pool

    def _make_client(self, proxy: str | None) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=self.config.timeout.connect,
            read=self.config.timeout.read,
            write=self.config.timeout.write,
            pool=self.config.timeout.pool,
        )
        limits = httpx.Limits(
            max_connections=self.config.max_connections,
            max_keepalive_connections=self.config.max_keepalive_connections,
            keepalive_expiry=self.config.keepalive_expiry,
        )
        user_agent = (
            random.choice(self.config.user_agents)
            if self.config.rotate_user_agents
            else self.config.user_agents[0]
        )
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "User-Agent": user_agent,
            **self.config.headers,
        }
        return httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            headers=headers,
            cookies=self._cookies,
            proxy=proxy,
            verify=self.config.verify_ssl,
            follow_redirects=False,
            http2=self.config.http2,
            transport=self._client_transport,
        )

    def _client(self, proxy: str | None) -> httpx.AsyncClient:
        if proxy not in self._clients:
            self._clients[proxy] = self._make_client(proxy)
        return self._clients[proxy]

    def _endpoint(self, url: str) -> str:
        path = urlsplit(url).path.strip("/")
        return path.split("/", 1)[0] or "root"

    def _circuit_key(self, endpoint: str, proxy: str | None) -> str:
        scope = self.config.circuit_breaker.scope
        if scope == "global":
            return "global"
        if scope == "endpoint":
            return endpoint
        return f"{endpoint}|{proxy or 'direct'}"

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._closed:
            raise RuntimeError("Transport is closed")
        validate_url(url, self.config.allowed_hosts, self.config.allow_subdomains)

        endpoint = self._endpoint(url)
        last_error: Exception | None = None
        request_headers = dict(kwargs.pop("headers", {}) or {})
        budget = RetryBudget(
            total_timeout=self.config.retry.total_timeout,
            max_total_delay=self.config.retry.max_total_delay,
        )

        for attempt in range(1, self.config.retry.max_attempts + 1):
            response: httpx.Response | None = None
            proxy_state = await self._proxy_pool.acquire()
            circuit = await self._circuits.get(self._circuit_key(endpoint, proxy_state.url))
            await circuit.before_call()
            timer = Timer()
            await self.metrics.mutate(endpoint=endpoint, requests_total=1)
            await self._emit(RequestEvent("start", method, url, attempt, endpoint, proxy_state.safe_url))

            try:
                async with self._rate_limiter:
                    response = await self._request_following_safe_redirects(
                        self._client(proxy_state.url), method, url, headers=request_headers, **kwargs
                    )
                elapsed = timer.elapsed
                await self.metrics.mutate(
                    endpoint=endpoint,
                    responses_total=1,
                    bytes_received=len(response.content),
                    latency_seconds_total=elapsed,
                )
                self._detect_block(response)

                if response.status_code in self.config.retry.retry_statuses:
                    if response.status_code == 429:
                        await self.metrics.mutate(rate_limited_total=1)
                        retry_after = self._retry_after(response)
                        if retry_after is not None:
                            await self._rate_limiter.pause_for(retry_after)
                        raise RateLimitedError(429, str(response.url))
                    raise HTTPStatusError(response.status_code, str(response.url))

                if response.status_code in {401, 403}:
                    raise AuthenticationRequired(
                        f"FL.ru returned HTTP {response.status_code} for {response.url}"
                    )
                if response.is_error:
                    raise HTTPStatusError(response.status_code, str(response.url))

                await self._proxy_pool.success(proxy_state)
                await circuit.record_success()
                await self._emit(
                    RequestEvent(
                        "success",
                        method,
                        str(response.url),
                        attempt,
                        endpoint,
                        proxy_state.safe_url,
                        response.status_code,
                        elapsed,
                    )
                )
                return response

            except AuthenticationRequired as exc:
                await self.metrics.mutate(endpoint=endpoint, failures_total=1)
                await self._emit_failure(method, url, attempt, endpoint, proxy_state, timer, exc)
                raise
            except HTTPStatusError as exc:
                last_error = exc
                await self.metrics.mutate(endpoint=endpoint, failures_total=1)
                if exc.status_code not in self.config.retry.retry_statuses:
                    await self._emit_failure(method, url, attempt, endpoint, proxy_state, timer, exc)
                    raise
                await self._proxy_pool.failure(proxy_state, exc)
            except BlockedError as exc:
                last_error = exc
                await self.metrics.mutate(endpoint=endpoint, blocked_total=1, failures_total=1)
                await self._proxy_pool.failure(proxy_state, exc)
                await self._emit(
                    RequestEvent(
                        "blocked",
                        method,
                        url,
                        attempt,
                        endpoint,
                        proxy_state.safe_url,
                        elapsed=timer.elapsed,
                        error=type(exc).__name__,
                    )
                )
            except httpx.TransportError as exc:
                last_error = exc
                await self.metrics.mutate(endpoint=endpoint, failures_total=1)
                await self._proxy_pool.failure(proxy_state, exc)

            if attempt >= self.config.retry.max_attempts:
                await circuit.record_failure()
                break

            delay = self._retry_delay(attempt, response)
            if not budget.allows(delay):
                await circuit.record_failure()
                break
            budget.consume_delay(delay)
            await self.metrics.mutate(endpoint=endpoint, retries_total=1)
            await self._emit(
                RequestEvent(
                    "retry",
                    method,
                    url,
                    attempt,
                    endpoint,
                    proxy_state.safe_url,
                    elapsed=timer.elapsed,
                    error=type(last_error).__name__ if last_error else None,
                )
            )
            await asyncio.sleep(delay)

        await self._emit(
            RequestEvent(
                "failure",
                method,
                url,
                min(self.config.retry.max_attempts, attempt),
                endpoint,
                error=type(last_error).__name__ if last_error else None,
            )
        )
        if isinstance(last_error, TransportError):
            raise last_error
        raise TransportError(f"Request failed: {method} {url}: {last_error}") from last_error

    async def _request_following_safe_redirects(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> httpx.Response:
        current_method = method
        current_url = url
        body_kwargs = dict(kwargs)
        for _ in range(10):
            response = await client.request(current_method, current_url, headers=headers, **body_kwargs)
            if not self.config.follow_redirects or response.status_code not in _REDIRECT_CODES:
                return response
            location = response.headers.get("Location")
            if not location:
                return response
            current_url = urljoin(str(response.url), location)
            validate_url(current_url, self.config.allowed_hosts, self.config.allow_subdomains)
            if response.status_code == 303 or (
                response.status_code in {301, 302} and current_method.upper() == "POST"
            ):
                current_method = "GET"
                body_kwargs.pop("content", None)
                body_kwargs.pop("data", None)
                body_kwargs.pop("json", None)
        raise TransportError(f"Too many redirects for {url}")

    async def emit_event(self, event: RequestEvent) -> None:
        """Emit a sanitized event without allowing handler failures to break requests."""
        if not await emit(self._event_handler, event):
            await self.metrics.mutate(event_handler_failures_total=1)

    async def _emit(self, event: RequestEvent) -> None:
        await self.emit_event(event)

    async def _emit_failure(
        self,
        method: str,
        url: str,
        attempt: int,
        endpoint: str,
        proxy_state: ProxyState,
        timer: Timer,
        error: Exception,
    ) -> None:
        await self._emit(
            RequestEvent(
                "failure",
                method,
                url,
                attempt,
                endpoint,
                proxy_state.safe_url,
                getattr(error, "status_code", None),
                timer.elapsed,
                type(error).__name__,
            )
        )

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and self.config.retry.respect_retry_after:
            parsed = self._retry_after(response)
            if parsed is not None:
                return min(parsed, self.config.retry.max_delay)
        exponential = min(
            self.config.retry.max_delay,
            self.config.retry.base_delay * (2 ** (attempt - 1)),
        )
        return exponential + random.uniform(0, self.config.retry.jitter)

    def _retry_after(self, response: httpx.Response) -> float | None:
        return self._parse_retry_after(response.headers.get("Retry-After"))

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                return None

    def _detect_block(self, response: httpx.Response) -> None:
        if not self.config.detect_blocks:
            return
        sample = response.text[:200_000].casefold()
        if any(marker in sample for marker in _BLOCK_MARKERS):
            raise BlockedError(f"Anti-bot or CAPTCHA page detected at {response.url}")
        if any(marker in sample for marker in _AUTH_MARKERS):
            raise AuthenticationRequired(f"Authentication is required for {response.url}")

    def update_cookies(self, cookies: dict[str, str]) -> None:
        self._cookies.update(cookies)
        for client in self._clients.values():
            client.cookies.update(cookies)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.gather(*(client.aclose() for client in self._clients.values()))
        self._clients.clear()
