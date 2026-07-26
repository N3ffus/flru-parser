from __future__ import annotations

import asyncio

import pytest

from flru import BlockedError, FLClient, ProjectDetail, ProjectSummary


def summary(project_id: int) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        title=f"Project {project_id}",
        url=f"https://www.fl.ru/projects/{project_id}/project.html",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("workers", "queue_size"), [(0, 1), (-1, 1), (1, 0), (1, -1)])
async def test_streaming_rejects_invalid_sizes(workers: int, queue_size: int) -> None:
    client = FLClient()
    with pytest.raises(ValueError):
        await anext(client.iter_project_details_result([], workers=workers, queue_size=queue_size))
    await client.close()


@pytest.mark.asyncio
async def test_result_stream_exposes_independent_errors(monkeypatch) -> None:
    client = FLClient()

    async def get_project(value: str) -> ProjectDetail:
        project_id = int(value.split("/projects/")[1].split("/")[0])
        if project_id == 2:
            raise RuntimeError("broken")
        return ProjectDetail(**summary(project_id).model_dump())

    monkeypatch.setattr(client, "get_project", get_project)
    results = [
        item
        async for item in client.iter_project_details_result(
            [summary(1), summary(2), summary(3)], workers=2, queue_size=1
        )
    ]
    assert {item.key for item in results if item.ok} == {1, 3}
    assert [item.key for item in results if not item.ok] == [2]
    await client.close()


@pytest.mark.asyncio
async def test_blocked_error_is_never_hidden(monkeypatch) -> None:
    client = FLClient()

    async def get_project(_value: str) -> ProjectDetail:
        raise BlockedError("blocked")

    monkeypatch.setattr(client, "get_project", get_project)
    with pytest.raises(BlockedError):
        async for _ in client.iter_project_details(
            [summary(1)], workers=1, queue_size=1, fail_fast=False
        ):
            pass
    await client.close()


@pytest.mark.asyncio
async def test_producer_error_propagates_without_hanging(monkeypatch) -> None:
    client = FLClient()

    async def projects():
        yield summary(1)
        raise RuntimeError("producer failed")

    async def get_project(value: str) -> ProjectDetail:
        await asyncio.sleep(0)
        return ProjectDetail(**summary(1).model_dump())

    monkeypatch.setattr(client, "get_project", get_project)
    with pytest.raises(RuntimeError, match="producer failed"):
        async with asyncio.timeout(1):
            async for _ in client.iter_project_details_result(projects(), workers=2, queue_size=1):
                pass
    await client.close()


@pytest.mark.asyncio
async def test_early_consumer_exit_closes_pipeline(monkeypatch) -> None:
    client = FLClient()
    cancelled = asyncio.Event()

    async def projects():
        try:
            for project_id in range(100):
                yield summary(project_id)
        finally:
            cancelled.set()

    async def get_project(value: str) -> ProjectDetail:
        project_id = int(value.split("/projects/")[1].split("/")[0])
        return ProjectDetail(**summary(project_id).model_dump())

    monkeypatch.setattr(client, "get_project", get_project)
    stream = client.iter_project_details_result(projects(), workers=2, queue_size=1)
    await anext(stream)
    await stream.aclose()
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    await client.close()
