# Contributing

Thank you for improving `flru-parser`.

## Setup

```bash
git clone https://github.com/N3ffus/flru-parser.git
cd flru-parser
uv sync --group dev
uv run pre-commit install
```

## Quality gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/flru
uv run pytest --cov=flru --cov-report=term-missing
uv build
uvx twine check dist/*
```

Coverage must stay at or above 85% with branch coverage enabled.

## Selector changes

When fixing a selector:

1. Add or update an anonymized HTML fixture.
2. Add a regression test that fails before the fix.
3. Prefer JSON-LD, meta tags, semantic attributes, and URL patterns over fragile class names.
4. Preserve diagnostics and field provenance.
5. Never commit authenticated HTML, cookies, tokens, personal messages, or unnecessary personal data.

## Pull requests

Keep changes focused, document public API changes, update `CHANGELOG.md`, and add tests. Breaking changes require a major version bump.
