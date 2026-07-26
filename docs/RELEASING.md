# Releasing flru-parser

Production publishing is triggered only by a new annotated `vX.Y.Z` tag. Manual workflow
runs publish to TestPyPI only. Never move or force-update an existing release tag.

Before tagging, merge the release pull request, verify CI on the merge commit, and run:

```bash
uv run python scripts/check_release.py --tag vX.Y.Z
uv build
uvx twine check dist/*
uv run python scripts/check_dist_size.py dist
```

The repository owner must configure the GitHub `pypi` environment with required reviewers,
prevent self-review where available, and restrict deployments to release tags. Trusted
Publishing must be configured independently for the exact repository, workflow, and
environment.

After publication, install the exact version from `https://pypi.org/simple/` in a clean
environment and verify `flru.__version__`, public imports, and `flru-canary --help`.
