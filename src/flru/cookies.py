from __future__ import annotations

from http.cookiejar import MozillaCookieJar
from pathlib import Path


def load_netscape_cookies(path: str | Path, *, domain_suffix: str = "fl.ru") -> dict[str, str]:
    """Load cookies exported in Netscape/cookies.txt format."""
    jar = MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return {
        cookie.name: cookie.value
        for cookie in jar
        if cookie.value is not None and cookie.domain.lstrip(".").endswith(domain_suffix)
    }
