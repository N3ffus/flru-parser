from __future__ import annotations

import argparse
import asyncio
import json

from .client import FLClient


async def run_canary() -> dict[str, object]:
    async with FLClient() as client:
        page = await client.get_projects_page(1)
        first = page.items[0]
        return {
            "ok": True,
            "items": len(page.items),
            "first_id": first.id,
            "first_title": first.title,
            "fingerprint": page.diagnostics.page_fingerprint,
            "confidence": page.diagnostics.confidence,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a read-only FL.ru parser canary")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_canary())
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
