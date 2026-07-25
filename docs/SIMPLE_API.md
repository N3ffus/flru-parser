# Simple API

`flru.Client` is the recommended entry point. It exposes common operations through flat arguments while inheriting every advanced method from `flru.FLClient`.

## Client construction

```python
from flru import Client

client = Client(
    concurrency=3,
    rps=1.0,
    retries=5,
    timeout=30,
    proxy=None,
    cookies=None,
    strict=True,
    respect_robots_txt=True,
)
```

| Argument | Meaning |
|---|---|
| `concurrency` | Maximum concurrent requests |
| `rps` | Average request starts per second |
| `retries` | Total attempts per logical request |
| `timeout` | Read timeout in seconds |
| `proxy` | One proxy URL or a sequence |
| `cookies` | Cookie mapping or `cookies.txt` path |
| `strict` | Detect unexpected empty pages and selector drift |
| `respect_robots_txt` | Enforce `robots.txt` decisions |

Use `async with Client() as client` so connections are always closed.

## `projects()`

```python
projects = await client.projects(
    pages=5,
    start_page=1,
    query="FastAPI",
    category="programmirovanie/python",
    min_budget=30_000,
    max_budget=200_000,
    types=["order", "vacancy"],
    with_budget=True,
    details=False,
    concurrency=3,
    fail_fast=True,
)
```

`pages` is a positive integer or `"all"`. A positive integer means the number of pages beginning at `start_page`.

With `details=False`, the method returns `list[ProjectSummary]`. With `details=True`, it returns `list[ProjectDetail]`.

## `stream_projects()`

```python
async for project in client.stream_projects(pages="all"):
    ...
```

Use this for large catalogs to avoid storing every summary in memory.

## `project()`

```python
project = await client.project(5500001)
project = await client.project("https://www.fl.ru/projects/5500001/example.html")
```

## `user()`

```python
profile = await client.user("username")
profile = await client.user("username", full=True, pages=3)
```

`full=True` loads projects, reviews and portfolio concurrently.

## `freelancers()`

```python
users = await client.freelancers(
    pages=5,
    category="programmirovanie",
)
```

## `new_projects()`

```python
items = await client.new_projects(
    "state.db",
    pages=30,
    stop_after_known=20,
)
```

A path creates an internal `SQLiteStateStore`. You may instead pass a `MemoryStateStore`, `PostgresStateStore`, `RedisStateStore` or custom implementation of `CrawlStateStore`.

## One-shot async functions

```python
from flru import fetch_freelancers, fetch_project, fetch_projects, fetch_user
```

Each helper creates and closes a temporary `Client`. For repeated operations, reuse one client instead.

## Sync API

```python
from flru.sync import Client

with Client() as client:
    projects = client.projects(pages=5)
```

The synchronous facade runs its async transport on a dedicated event-loop thread. It can therefore be used from ordinary synchronous applications without managing `asyncio` directly.

## Advanced escape hatch

Because `Client` subclasses `FLClient`, these remain available:

```python
page = await client.get_projects_page(1)
batch = await client.get_projects_batch_result(range(1, 10))
metrics = await client.metrics()
categories = await client.get_categories()
```
