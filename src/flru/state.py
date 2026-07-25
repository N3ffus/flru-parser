from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .models import CrawlCheckpoint, ProjectRecord, ProjectSummary


def project_content_hash(project: ProjectSummary) -> str:
    payload = project.model_dump(mode="json", exclude={"source"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def record_for(project: ProjectSummary, previous: ProjectRecord | None = None) -> ProjectRecord:
    now = datetime.now(UTC)
    return ProjectRecord(
        project=project,
        first_seen_at=previous.first_seen_at if previous else now,
        last_seen_at=now,
        content_hash=project_content_hash(project),
        source_updated_at=getattr(project, "updated_at", None),
    )


@runtime_checkable
class CrawlStateStore(Protocol):
    async def get(self, project_id: int) -> ProjectRecord | None: ...

    async def contains(self, project_id: int) -> bool: ...

    async def save(self, record: ProjectRecord) -> None: ...

    async def save_many(self, records: Iterable[ProjectRecord]) -> None: ...

    async def get_checkpoint(self, namespace: str) -> CrawlCheckpoint | None: ...

    async def save_checkpoint(self, checkpoint: CrawlCheckpoint) -> None: ...

    async def close(self) -> None: ...


class MemoryStateStore:
    def __init__(self) -> None:
        self.records: dict[int, ProjectRecord] = {}
        self.checkpoints: dict[str, CrawlCheckpoint] = {}
        self._lock = asyncio.Lock()

    async def get(self, project_id: int) -> ProjectRecord | None:
        async with self._lock:
            return self.records.get(project_id)

    async def contains(self, project_id: int) -> bool:
        async with self._lock:
            return project_id in self.records

    async def save(self, record: ProjectRecord) -> None:
        async with self._lock:
            self.records[record.project.id] = record

    async def save_many(self, records: Iterable[ProjectRecord]) -> None:
        async with self._lock:
            self.records.update({record.project.id: record for record in records})

    async def get_checkpoint(self, namespace: str) -> CrawlCheckpoint | None:
        async with self._lock:
            return self.checkpoints.get(namespace)

    async def save_checkpoint(self, checkpoint: CrawlCheckpoint) -> None:
        async with self._lock:
            self.checkpoints[checkpoint.namespace] = checkpoint

    async def close(self) -> None:
        return None


class SQLiteStateStore:
    """Durable state store using only the Python standard library."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = asyncio.Lock()
        self._initialized = False

    async def _ensure_schema(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize_sync(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    namespace TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                """
            )

    async def get(self, project_id: int) -> ProjectRecord | None:
        await self._ensure_schema()
        return await asyncio.to_thread(self._get_sync, project_id)

    def _get_sync(self, project_id: int) -> ProjectRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return ProjectRecord.model_validate_json(row[0]) if row else None

    async def contains(self, project_id: int) -> bool:
        return await self.get(project_id) is not None

    async def save(self, record: ProjectRecord) -> None:
        await self.save_many([record])

    async def save_many(self, records: Iterable[ProjectRecord]) -> None:
        await self._ensure_schema()
        values = [(record.project.id, record.model_dump_json()) for record in records]
        if values:
            await asyncio.to_thread(self._save_many_sync, values)

    def _save_many_sync(self, values: list[tuple[int, str]]) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                "INSERT INTO projects(project_id, payload) VALUES(?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET payload = excluded.payload",
                values,
            )

    async def get_checkpoint(self, namespace: str) -> CrawlCheckpoint | None:
        await self._ensure_schema()
        return await asyncio.to_thread(self._get_checkpoint_sync, namespace)

    def _get_checkpoint_sync(self, namespace: str) -> CrawlCheckpoint | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM checkpoints WHERE namespace = ?", (namespace,)
            ).fetchone()
        return CrawlCheckpoint.model_validate_json(row[0]) if row else None

    async def save_checkpoint(self, checkpoint: CrawlCheckpoint) -> None:
        await self._ensure_schema()
        await asyncio.to_thread(self._save_checkpoint_sync, checkpoint)

    def _save_checkpoint_sync(self, checkpoint: CrawlCheckpoint) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO checkpoints(namespace, payload) VALUES(?, ?) "
                "ON CONFLICT(namespace) DO UPDATE SET payload = excluded.payload",
                (checkpoint.namespace, checkpoint.model_dump_json()),
            )

    async def close(self) -> None:
        return None


class PostgresStateStore:
    """Optional asyncpg-backed store. Install ``flru-parser[postgres]``."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: Any | None = None
        self._lock = asyncio.Lock()

    async def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is None:
                try:
                    import asyncpg
                except ImportError as exc:  # pragma: no cover - optional dependency
                    raise RuntimeError("Install flru-parser[postgres]") from exc
                self._pool = await asyncpg.create_pool(self.dsn)
                async with self._pool.acquire() as connection:
                    await connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS flru_projects (
                            project_id BIGINT PRIMARY KEY,
                            payload JSONB NOT NULL
                        );
                        CREATE TABLE IF NOT EXISTS flru_checkpoints (
                            namespace TEXT PRIMARY KEY,
                            payload JSONB NOT NULL
                        );
                        """
                    )
        return self._pool

    async def get(self, project_id: int) -> ProjectRecord | None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT payload FROM flru_projects WHERE project_id=$1", project_id
            )
        if not value:
            return None
        return (
            ProjectRecord.model_validate_json(value)
            if isinstance(value, str)
            else ProjectRecord.model_validate(value)
        )

    async def contains(self, project_id: int) -> bool:
        return await self.get(project_id) is not None

    async def save(self, record: ProjectRecord) -> None:
        await self.save_many([record])

    async def save_many(self, records: Iterable[ProjectRecord]) -> None:
        values = [(record.project.id, record.model_dump_json()) for record in records]
        if not values:
            return
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.executemany(
                "INSERT INTO flru_projects(project_id,payload) VALUES($1,$2::jsonb) "
                "ON CONFLICT(project_id) DO UPDATE SET payload=excluded.payload",
                values,
            )

    async def get_checkpoint(self, namespace: str) -> CrawlCheckpoint | None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT payload FROM flru_checkpoints WHERE namespace=$1", namespace
            )
        if not value:
            return None
        return (
            CrawlCheckpoint.model_validate_json(value)
            if isinstance(value, str)
            else CrawlCheckpoint.model_validate(value)
        )

    async def save_checkpoint(self, checkpoint: CrawlCheckpoint) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO flru_checkpoints(namespace,payload) VALUES($1,$2::jsonb) "
                "ON CONFLICT(namespace) DO UPDATE SET payload=excluded.payload",
                checkpoint.namespace,
                checkpoint.model_dump_json(),
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


class RedisStateStore:
    """Optional Redis-backed store. Install ``flru-parser[redis]``."""

    def __init__(self, url: str, *, prefix: str = "flru") -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install flru-parser[redis]") from exc
        self._redis = Redis.from_url(url, decode_responses=True)
        self.prefix = prefix

    def _project_key(self, project_id: int) -> str:
        return f"{self.prefix}:project:{project_id}"

    def _checkpoint_key(self, namespace: str) -> str:
        return f"{self.prefix}:checkpoint:{namespace}"

    async def get(self, project_id: int) -> ProjectRecord | None:
        value = await self._redis.get(self._project_key(project_id))
        return ProjectRecord.model_validate_json(value) if value else None

    async def contains(self, project_id: int) -> bool:
        return bool(await self._redis.exists(self._project_key(project_id)))

    async def save(self, record: ProjectRecord) -> None:
        await self._redis.set(self._project_key(record.project.id), record.model_dump_json())

    async def save_many(self, records: Iterable[ProjectRecord]) -> None:
        pipeline = self._redis.pipeline()
        count = 0
        for record in records:
            pipeline.set(self._project_key(record.project.id), record.model_dump_json())
            count += 1
        if count:
            await pipeline.execute()

    async def get_checkpoint(self, namespace: str) -> CrawlCheckpoint | None:
        value = await self._redis.get(self._checkpoint_key(namespace))
        return CrawlCheckpoint.model_validate_json(value) if value else None

    async def save_checkpoint(self, checkpoint: CrawlCheckpoint) -> None:
        await self._redis.set(
            self._checkpoint_key(checkpoint.namespace), checkpoint.model_dump_json()
        )

    async def close(self) -> None:
        await self._redis.aclose()
