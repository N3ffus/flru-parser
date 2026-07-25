from __future__ import annotations

from pathlib import Path


class FLRUError(Exception):
    """Base package exception."""


class ConfigurationError(FLRUError):
    """Invalid client configuration."""


class TransportError(FLRUError):
    """Request failed after all retry attempts."""


class HTTPStatusError(TransportError):
    def __init__(self, status_code: int, url: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"FL.ru returned HTTP {status_code} for {url}")


class RateLimitedError(HTTPStatusError):
    """Remote server returned HTTP 429."""


class BlockedError(TransportError):
    """A CAPTCHA, anti-bot page, or access block was detected."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        debug_path: Path | None = None,
    ) -> None:
        self.status_code = status_code
        self.debug_path = debug_path
        super().__init__(message)


class AuthenticationRequired(TransportError):
    """The requested page requires a valid authenticated session."""


class CircuitOpenError(TransportError):
    """Circuit breaker is open and temporarily rejects requests."""


class RobotsDeniedError(FLRUError):
    """robots.txt denies access for the configured user agent."""


class SecurityError(FLRUError):
    """A URL violates the configured host or redirect policy."""


class ParseError(FLRUError):
    """Page could not be parsed into the requested model."""


class EmptyPageError(ParseError):
    """A page had no parsed records and could not be identified as catalog end."""


class SelectorDriftError(ParseError):
    """Candidate records were present, but selectors could not parse them."""


class UnexpectedPageError(ParseError):
    """The response is valid HTML but not the expected page type."""
