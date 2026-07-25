from flru.sync import Client

with Client() as fl:
    projects = fl.projects(pages=3, query="Python")

for project in projects:
    print(project.id, project.title, project.url)
