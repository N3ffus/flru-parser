import asyncio

from flru import Client


async def main() -> None:
    async with Client() as fl:
        projects = await fl.projects(
            pages=5,
            query="FastAPI",
            min_budget=30_000,
            with_budget=True,
        )

        for project in projects:
            print(project.title, project.budget_min, project.currency, project.url)


if __name__ == "__main__":
    asyncio.run(main())
