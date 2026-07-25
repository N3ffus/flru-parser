# flru-parser — документация на русском

`flru-parser` — неофициальный типизированный клиент для чтения публичных страниц FL.ru. Основной API сделан коротким, при этом production-настройки и low-level методы сохранены.

## Установка

```bash
uv add flru-parser
```

## Минимальный async-пример

```python
import asyncio

from flru import Client


async def main() -> None:
    async with Client() as fl:
        projects = await fl.projects(pages=5)

        for project in projects:
            print(project.title, project.budget_min, project.url)


asyncio.run(main())
```

## Синхронный пример

```python
from flru.sync import Client

with Client() as fl:
    projects = fl.projects(pages=5, query="FastAPI")
```

## Основные методы

```python
await fl.projects(pages=5)
await fl.projects(pages="all", query="Python", min_budget=30_000)
await fl.projects(details=True)
await fl.project(5500001)
await fl.user("username", full=True, pages=3)
await fl.freelancers(pages=5)
await fl.new_projects("flru-state.db", pages=30)
```

`projects()` принимает простые аргументы без обязательного создания `ProjectFilters`:

```python
projects = await fl.projects(
    pages=10,
    query="FastAPI",
    category="programmirovanie/python",
    min_budget=30_000,
    max_budget=200_000,
    types=["заказ", "вакансия"],
    with_budget=True,
    concurrency=3,
)
```

Для полного каталога без хранения всех объектов в памяти:

```python
async for project in fl.stream_projects(pages="all"):
    print(project.title)
```

## Инкрементальный сбор

SQLite создаётся автоматически:

```python
new_projects = await fl.new_projects(
    "flru-state.db",
    pages=30,
    stop_after_known=20,
)
```

Состояние хранит `first_seen_at`, `last_seen_at`, hash содержимого и checkpoint. Также доступны Memory, PostgreSQL и Redis.

## Прокси и cookies

```python
async with Client(
    concurrency=3,
    rps=0.8,
    retries=6,
    proxy="http://user:password@proxy.example:8080",
    cookies="cookies.txt",
) as fl:
    projects = await fl.projects(pages=10)
```

## Advanced API

`Client` наследует полный `FLClient`, поэтому старый и low-level API остаётся доступен:

```python
page = await fl.get_projects_page(1)
batch = await fl.get_projects_batch_result(range(1, 10))
categories = await fl.get_categories()
```

Production-слой поддерживает retries, jitter, `Retry-After`, общий cooldown после 429, rate limiting, circuit breaker, proxy pool, allowlist доменов, безопасные redirects, `robots.txt`, диагностику селекторов, Prometheus и OpenTelemetry.

Полное описание: [основной README](../../README.md) и [Simple API](../SIMPLE_API.md).
