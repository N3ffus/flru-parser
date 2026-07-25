"""Conservative production configuration with structured logs."""

import asyncio
import logging

from flru import (
    CircuitBreakerConfig,
    ClientConfig,
    FLClient,
    RateLimitConfig,
    RetryConfig,
    StructuredLogHandler,
)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = ClientConfig(
        retry=RetryConfig(max_attempts=6, total_timeout=120, max_total_delay=60),
        rate_limit=RateLimitConfig(
            requests_per_second=0.8,
            burst=2,
            max_concurrency=4,
            min_interval=0.4,
        ),
        circuit_breaker=CircuitBreakerConfig(scope="endpoint_proxy"),
        store_failed_html=True,
        failed_html_directory="failed-html",
    )
    async with FLClient(config, event_handler=StructuredLogHandler()) as client:
        async for project in client.iter_projects(max_pages=5, batch_size=2):
            print(project.title)


if __name__ == "__main__":
    asyncio.run(main())
