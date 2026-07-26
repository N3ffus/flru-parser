# flru-parser

[![Package version](https://img.shields.io/pypi/v/flru-parser.svg?label=package)](https://pypi.org/project/flru-parser/)
[![Python: 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://pypi.org/project/flru-parser/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Typing](https://img.shields.io/badge/typing-PEP%20561-blue)](src/flru/py.typed)
[![Tests](https://github.com/N3ffus/flru-parser/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/N3ffus/flru-parser/actions/workflows/ci.yml?query=branch%3Amain)
[![Coverage: 87.9%](https://img.shields.io/badge/coverage-87.9%25-brightgreen.svg)](https://github.com/N3ffus/flru-parser/actions/workflows/ci.yml?query=branch%3Amain)
[![Mypy: strict](https://img.shields.io/badge/mypy-strict-blue.svg)](https://github.com/N3ffus/flru-parser/actions/workflows/ci.yml?query=branch%3Amain)

A typed, resilient, read-only Python client for public pages on [FL.ru](https://www.fl.ru/).
The default API is intentionally small; production controls remain available when needed.

> **Unofficial project.** This package is not affiliated with or endorsed by FL.ru. FL.ru does not expose a stable public API for all supported data. HTML selectors may require maintenance after a site redesign. The parser detects likely selector drift instead of silently returning an empty catalog.

[Русская документация](docs/ru/README.md) · [Simple API](docs/SIMPLE_API.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

## Features

- Simple async API: `projects()`, `project()`, `user()`, `freelancers()`, `new_projects()`.
- Matching synchronous API in `flru.sync`.
- Projects, details, categories, freelancers, profiles, reviews and portfolios.
- Typed Pydantic models with PEP 561 support.
- Retries, jitter, `Retry-After`, shared HTTP 429 cooldown and retry budgets.
- RPS and concurrency limits, endpoint/proxy circuit breakers and proxy health tracking.
- HTTP, HTTPS and SOCKS proxy pools with credential redaction.
- Safe redirects, allowed-host enforcement, `robots.txt` support and block-page detection.
- Incremental crawling with Memory, SQLite, PostgreSQL or Redis state.
- Parse diagnostics, confidence, field provenance and page fingerprints.
- Prometheus, OpenTelemetry and structured event integrations.
- CI, branch-coverage gate, dependency audit, live canary and PyPI Trusted Publishing.

## Installation

```bash
uv add flru-parser
```

Optional integrations:

```bash
uv add "flru-parser[postgres]"
uv add "flru-parser[redis]"
uv add "flru-parser[observability]"
```

Supported Python versions: **3.11–3.13**.

## Five-minute API

### Async

```python
import asyncio

from flru import Client


async def main() -> None:
    async with Client() as fl:
        projects = await fl.projects(pages=5)

        for project in projects:
            print(project.title, project.budget_min, project.currency, project.url)


asyncio.run(main())
```

### Sync

```python
from flru.sync import Client

with Client() as fl:
    projects = fl.projects(pages=5)

for project in projects:
    print(project.title, project.budget_min, project.url)
```

### One-shot helpers

```python
import asyncio

from flru import fetch_project, fetch_projects

projects = asyncio.run(fetch_projects(pages=3, query="FastAPI"))
project = asyncio.run(fetch_project(projects[0].id))
```

For synchronous scripts:

```python
from flru.sync import project, projects

items = projects(pages=3, query="FastAPI")
detail = project(items[0].id)
```

## Common operations

### Search and filter projects

No separate filter object is needed for the common path:

```python
projects = await fl.projects(
    pages=10,
    query="Python FastAPI",
    category="programmirovanie/python",
    min_budget=30_000,
    max_budget=200_000,
    types="order",  # order, vacancy, contest
    with_budget=True,
    concurrency=3,
)
```

`types` accepts one value or a sequence. English and Russian aliases are supported:

```python
projects = await fl.projects(types=["заказ", "вакансия"])
```

### Parse the complete catalog

```python
projects = await fl.projects(pages="all")
```

For a large catalog, stream results instead of retaining everything in memory:

```python
async for project in fl.stream_projects(pages="all", concurrency=3):
    print(project.id, project.title)
```

### Load full project cards

```python
details = await fl.projects(pages=3, details=True)

for project in details:
    print(project.full_description, project.attachments)
```

Or retrieve one project by ID or URL:

```python
project = await fl.project(5500001)
project = await fl.project("https://www.fl.ru/projects/5500001/example.html")
```

### Profiles and freelancers

```python
profile = await fl.user("username")
full_profile = await fl.user("username", full=True, pages=3)
freelancers = await fl.freelancers(pages=5, category="programmirovanie")
```

`full=True` concurrently loads projects, reviews and portfolio sections.

### Incremental crawling

The simplest durable mode uses a local SQLite file automatically:

```python
new_or_changed = await fl.new_projects(
    "flru-state.db",
    pages=30,
    stop_after_known=20,
)
```

The state tracks content hashes, `first_seen_at`, `last_seen_at` and crawl checkpoints. Repeated runs stop after enough already-known records.

Advanced stores remain available:

```python
from flru import PostgresStateStore

state = PostgresStateStore("postgresql://user:pass@localhost/app")
projects = await fl.new_projects(state, pages="all")
await state.close()
```

### Proxies, cookies and request limits

Common production options are flat constructor arguments:

```python
async with Client(
    concurrency=3,
    rps=0.8,
    retries=6,
    timeout=45,
    proxy=[
        "http://user:password@proxy-1.example:8080",
        "socks5://user:password@proxy-2.example:1080",
    ],
    cookies="cookies.txt",
) as fl:
    projects = await fl.projects(pages=10)
```

`cookies` can be a mapping or a Netscape-format browser export path.
Proxy credentials are redacted from metrics and events.
When `direct_fallback=True`, direct access is used only while every configured proxy is
unavailable. This can change the apparent client IP and should be enabled only when that
privacy trade-off is acceptable.

### Models

Models are regular Pydantic models:

```python
project = projects[0]

print(project.budget_min)
print(project.budget_max)
print(project.currency)
print(project.customer_username)
print(project.to_dict())
print(project.model_dump_json(indent=2))
```

## Advanced API

The simple `Client` subclasses the full `FLClient`, so low-level methods remain directly available:

```python
from flru import FLClient, ProjectFilters

async with FLClient() as client:
    page = await client.get_projects_page(page=1)
    batch = await client.get_projects_batch_result(range(1, 11), concurrency=4)
    categories = await client.get_categories()
```

Use `FLClient` and the immutable configuration dataclasses when every transport setting must be controlled:

```python
from flru import (
    CircuitBreakerConfig,
    ClientConfig,
    FLClient,
    ProxyConfig,
    RateLimitConfig,
    RetryConfig,
)

config = ClientConfig(
    retry=RetryConfig(
        max_attempts=6,
        base_delay=1,
        max_delay=45,
        total_timeout=120,
        max_total_delay=60,
    ),
    rate_limit=RateLimitConfig(
        requests_per_second=0.8,
        max_concurrency=4,
        min_interval=0.4,
    ),
    circuit_breaker=CircuitBreakerConfig(
        failure_threshold=8,
        recovery_timeout=90,
        scope="endpoint_proxy",
    ),
    proxies=ProxyConfig(
        urls=("http://user:password@proxy.example:8080",),
        direct_fallback=True,
    ),
)

client = FLClient(config)
```

See [docs/SIMPLE_API.md](docs/SIMPLE_API.md) for the complete high-level API and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for internals.

## Reliability behavior

- Empty output is not automatically treated as the end of the catalog.
- Candidate links with no parsed cards raise `SelectorDriftError`.
- Unclassified empty pages raise `EmptyPageError`.
- A recognized end page contains the `catalog_end` diagnostic warning.
- HTTP 429 can pause all concurrent workers through a shared cooldown.
- HTTP 429 and 503 honor `Retry-After` when the server supplies it.
- Circuit breakers are scoped by endpoint and proxy by default.
- CAPTCHA and block pages are detected, not bypassed or retried. Their HTML and sanitized response
  metadata are saved to `.flru-debug/blocked-.../`; this directory is ignored by Git.
- Requests are restricted to allowed FL.ru hosts and safe redirects.

## Observability

```python
metrics = await fl.stats()
print(metrics.requests_total, metrics.retries_total, metrics.endpoints)
```

Structured logging:

```python
from flru import Client, StructuredLogHandler

fl = Client(event_handler=StructuredLogHandler())
```

Optional adapters:

```python
from flru.integrations.opentelemetry import OpenTelemetryEventHandler
from flru.integrations.prometheus import PrometheusEventHandler
```

Install `flru-parser[observability]` before using these adapters.

## Exceptions

| Exception | Meaning |
|---|---|
| `BlockedError` | CAPTCHA, anti-bot or access-block page detected; exposes `status_code` and `debug_path` |
| `AuthenticationRequired` | Authenticated cookies are required |
| `RateLimitedError` | HTTP 429 after retry policy exhaustion |
| `CircuitOpenError` | A scoped circuit breaker is open |
| `SecurityError` | Host, scheme or redirect violates policy |
| `RobotsDeniedError` | `robots.txt` denies access |
| `SelectorDriftError` | Candidate records exist but current selectors parsed none |
| `EmptyPageError` | Empty page cannot be classified as catalog end |
| `ParseError` | HTML cannot be converted into the requested model |

## Quality

The CI badge shows the current `main` result. CI enforces at least 85% branch coverage and
publishes the XML and HTML reports as a workflow artifact.

Run the complete local checks:

```bash
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/flru
uv run pytest --cov=flru --cov-branch --cov-report=term-missing --cov-report=html
uv build
uvx twine check dist/*
```

The repository also contains:

- Python 3.11–3.13 CI matrix;
- scheduled dependency vulnerability audit;
- read-only live selector canary;
- pre-commit configuration;
- Trusted Publishing workflows for TestPyPI and PyPI.

## Publishing

The release workflow uses PyPI Trusted Publishing and checks that the Git tag matches both package version declarations.

```bash
uv run python scripts/configure_project.py YOUR_GITHUB_USERNAME
uv run python scripts/sync_version.py --check
```

<!-- release-version:start -->
```bash
git tag -a v0.4.0 -m "flru-parser 0.4.0"
git push origin main v0.4.0
```
<!-- release-version:end -->

See [docs/PUBLISHING.md](docs/PUBLISHING.md) for the one-time PyPI and GitHub setup.

## Responsible use

- Respect FL.ru terms, `robots.txt`, applicable law and personal-data requirements.
- Prefer incremental crawling and reasonable request rates.
- Do not use proxies or this package to bypass access controls or CAPTCHA.
- Do not automate account actions through undocumented endpoints.
- Public indexability does not automatically grant unlimited collection or redistribution rights.

## License

MIT. See [LICENSE](LICENSE).
