from __future__ import annotations

import re
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .exceptions import SecurityError

_SECRET_QUERY_RE = re.compile(r"(?i)(token|key|password|secret|signature)=([^&]+)")


def is_allowed_host(host: str | None, allowed_hosts: frozenset[str], allow_subdomains: bool) -> bool:
    if not host:
        return False
    host = host.casefold().rstrip(".")
    return any(
        host == allowed or (allow_subdomains and host.endswith(f".{allowed}"))
        for allowed in allowed_hosts
    )


def validate_url(url: str, allowed_hosts: frozenset[str], allow_subdomains: bool) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise SecurityError(f"Unsupported URL scheme: {parts.scheme!r}")
    if not is_allowed_host(parts.hostname, allowed_hosts, allow_subdomains):
        raise SecurityError(f"Host is not allowed: {parts.hostname!r}")
    return url


def redact_url(url: str | None) -> str | None:
    if url is None:
        return None
    parts = urlsplit(url)
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    userinfo = ""
    if parts.username:
        userinfo = f"{parts.username}:***@"
    netloc = f"{userinfo}{hostname}{port}"
    query = _SECRET_QUERY_RE.sub(lambda match: f"{match.group(1)}=***", parts.query)
    return urlunsplit(SplitResult(parts.scheme, netloc, parts.path, query, parts.fragment))
