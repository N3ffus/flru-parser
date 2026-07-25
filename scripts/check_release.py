"""Validate version and repository metadata before a release."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-placeholder", action="store_true")
    parser.add_argument("--tag", help="Release tag, for example v0.3.0")
    args = parser.parse_args()

    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(pyproject_text)
    project_version = data["project"]["version"]
    init_text = (ROOT / "src/flru/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init_text, re.MULTILINE)
    if not match:
        raise SystemExit("src/flru/__init__.py has no literal __version__")
    if match.group(1) != project_version:
        raise SystemExit(
            f"version mismatch: pyproject={project_version}, __version__={match.group(1)}"
        )

    if args.tag and args.tag.removeprefix("v") != project_version:
        raise SystemExit(f"tag/version mismatch: tag={args.tag}, package={project_version}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "OWNER" in pyproject_text + readme and not args.allow_placeholder:
        raise SystemExit(
            "replace OWNER first: uv run python scripts/configure_project.py YOUR_GITHUB_USERNAME"
        )
    if f"## [{project_version}]" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"):
        raise SystemExit(f"CHANGELOG.md has no [{project_version}] release section")
    print(f"Release metadata is consistent for {project_version}")


if __name__ == "__main__":
    main()
