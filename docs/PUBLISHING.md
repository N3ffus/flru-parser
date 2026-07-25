# Publishing to PyPI

The project is prepared for GitHub Actions Trusted Publishing, so the release workflow does not require a long-lived PyPI API token.

## One-time repository setup

1. Run `uv run python scripts/configure_project.py YOUR_GITHUB_USERNAME`.
2. Push the project to `https://github.com/YOUR_GITHUB_USERNAME/flru-parser`.
3. Create GitHub environments named `testpypi` and `pypi`.
4. On TestPyPI and PyPI, add a Trusted Publisher for:
   - owner: your GitHub username;
   - repository: `flru-parser`;
   - workflow: `release.yml`;
   - environment: `testpypi` or `pypi`.
5. Protect the `pypi` environment with manual approval if desired.

## Validate locally

```bash
uv sync --group dev
make check
make release-check
```

The commands run formatting/lint checks, strict type checking, branch coverage, wheel/sdist builds, metadata validation, and release metadata consistency checks.

## TestPyPI

Run the **Release** workflow manually and choose `testpypi`. Verify installation in an isolated environment:

```bash
uv venv /tmp/flru-test
uv pip install \
  --python /tmp/flru-test/bin/python \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  flru-parser==0.3.0
```

On Windows, use `/tmp/flru-test/Scripts/python.exe` instead.

## Production release

1. Update the version in `pyproject.toml` and `src/flru/__init__.py`.
2. Move changes from `Unreleased` into a versioned `CHANGELOG.md` section.
3. Run `make check` and `make release-check`.
4. Commit, create an annotated tag, and push it:

```bash
git tag -a v0.3.0 -m "flru-parser 0.3.0"
git push origin main v0.3.0
```

The workflow builds distributions once, validates them, and publishes the exact same artifacts through PyPI Trusted Publishing.

## Manual fallback

```bash
uv build
uvx twine check dist/*
uv publish --token "$UV_PUBLISH_TOKEN"
```

Prefer Trusted Publishing for normal releases.
