from __future__ import annotations

from urllib.parse import quote

from hypothesis import given
from hypothesis import strategies as st

from flru import ProjectSummary
from flru.security import redact_url
from flru.state import project_content_hash


@given(
    project_id=st.integers(min_value=1, max_value=10**12),
    title=st.text(min_size=1, max_size=80).filter(lambda value: not value.isspace()),
)
def test_content_hash_is_deterministic(project_id: int, title: str) -> None:
    project = ProjectSummary(
        id=project_id,
        title=title,
        url=f"https://www.fl.ru/projects/{project_id}/project.html",
    )
    assert project_content_hash(project) == project_content_hash(project.model_copy(deep=True))


@given(
    username=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=30,
    ),
    password=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=30,
    ),
)
def test_redact_url_never_exposes_proxy_credentials(username: str, password: str) -> None:
    username = f"user_{username}"
    password = f"pass_{password}"
    url = f"http://{quote(username)}:{quote(password)}@proxy.example:8080/path"
    redacted = redact_url(url)
    assert redacted is not None
    assert username not in redacted
    assert password not in redacted
    assert "***" in redacted
