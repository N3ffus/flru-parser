import asyncio

from flru import Client


async def main() -> None:
    async with Client() as fl:
        projects = await fl.new_projects(
            "flru-state.db",
            pages=30,
            stop_after_known=20,
        )

        for project in projects:
            print("NEW OR CHANGED:", project.title)


if __name__ == "__main__":
    asyncio.run(main())
