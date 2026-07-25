from collections import Counter

import httpx
import pytest

from flru import ClientConfig, FLClient, RateLimitConfig, RetryConfig

PROJECTS_HTML = """
<html><body><main id='projects-list'>
<article class='project-card'><h2><a href='/projects/1/test.html'>Test</a></h2>
<p class='project-description'>Description long enough for parsing.</p><div>Заказ 1 ответ</div></article>
</main></body></html>
"""


@pytest.mark.asyncio
async def test_client_get_projects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PROJECTS_HTML, request=request)

    config = ClientConfig(
        respect_robots_txt=False,
        rate_limit=RateLimitConfig(requests_per_second=1000, max_concurrency=10),
    )
    async with FLClient(config, transport=httpx.MockTransport(handler)) as client:
        projects = await client.get_projects()
        assert len(projects) == 1
        assert projects[0].id == 1


@pytest.mark.asyncio
async def test_retry_then_success() -> None:
    calls: Counter[str] = Counter()

    async def handler(request: httpx.Request) -> httpx.Response:
        calls[request.url.path] += 1
        if calls[request.url.path] < 3:
            return httpx.Response(503, text="temporary", request=request)
        return httpx.Response(200, text=PROJECTS_HTML, request=request)

    config = ClientConfig(
        respect_robots_txt=False,
        retry=RetryConfig(max_attempts=3, base_delay=0, max_delay=0, jitter=0),
        rate_limit=RateLimitConfig(requests_per_second=1000, max_concurrency=10),
    )
    async with FLClient(config, transport=httpx.MockTransport(handler)) as client:
        projects = await client.get_projects()
        metrics = await client.metrics()
        assert len(projects) == 1
        assert calls["/projects/"] == 3
        assert metrics.retries_total == 2
