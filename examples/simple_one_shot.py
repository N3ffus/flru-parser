import asyncio

from flru import fetch_projects

projects = asyncio.run(
    fetch_projects(
        pages=3,
        query="FastAPI",
        min_budget=30_000,
    )
)

for project in projects:
    print(project.title, project.url)
