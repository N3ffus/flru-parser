"""Validate version and repository metadata before a release."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(message)


def python_minor_versions(data: dict[str, object]) -> list[str]:
    classifiers = data["project"]["classifiers"]  # type: ignore[index]
    prefix = "Programming Language :: Python :: "
    return [
        classifier.removeprefix(prefix)
        for classifier in classifiers  # type: ignore[union-attr]
        if re.fullmatch(rf"{re.escape(prefix)}3\.\d+", classifier)
    ]


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
        fail("src/flru/__init__.py has no literal __version__")
    if match.group(1) != project_version:
        fail(f"version mismatch: pyproject={project_version}, __version__={match.group(1)}")

    if args.tag and args.tag.removeprefix("v") != project_version:
        fail(f"tag/version mismatch: tag={args.tag}, package={project_version}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "OWNER" in pyproject_text + readme and not args.allow_placeholder:
        fail("replace OWNER first: uv run python scripts/configure_project.py YOUR_GITHUB_USERNAME")
    if f"## [{project_version}]" not in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"):
        fail(f"CHANGELOG.md has no [{project_version}] release section")

    supported_python = python_minor_versions(data)
    if not supported_python:
        fail("pyproject.toml has no Python minor-version classifiers")
    minimum_python = supported_python[0]
    maximum_python = supported_python[-1]
    next_minor = f"3.{int(maximum_python.split('.')[1]) + 1}"
    expected_constraint = f">={minimum_python},<{next_minor}"
    actual_constraint = data["project"]["requires-python"]
    if actual_constraint != expected_constraint:
        fail(
            "Python version mismatch: "
            f"requires-python={actual_constraint}, classifiers={supported_python}"
        )

    if data["tool"]["mypy"]["python_version"] != minimum_python:
        fail("Mypy version must match the oldest supported Python version")
    if data["tool"]["ruff"]["target-version"] != f"py{minimum_python.replace('.', '')}":
        fail("Ruff target version must match the oldest supported Python version")

    ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    matrix_match = re.search(r"python-version: \[([^\]]+)\]", ci_text)
    if not matrix_match:
        fail("CI has no Python version matrix")
    ci_python = re.findall(r'"(3\.\d+)"', matrix_match.group(1))
    if ci_python != supported_python:
        fail(f"Python version mismatch: classifiers={supported_python}, CI={ci_python}")

    supported_range = f"Supported Python versions: **{minimum_python}–{maximum_python}**."
    if supported_range not in readme:
        fail(f"README must contain: {supported_range}")

    license_expression = data["project"]["license"]
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if license_expression != "MIT" or not license_text.startswith("MIT License"):
        fail("license mismatch: pyproject.toml and LICENSE must both declare MIT")

    required_badges = [
        "img.shields.io/pypi/v/flru-parser.svg?label=package",
        "img.shields.io/pypi/pyversions/flru-parser.svg",
        "img.shields.io/badge/license-MIT-blue.svg",
        "actions/workflows/ci.yml/badge.svg?branch=main",
        "codecov.io/gh/N3ffus/flru-parser/branch/main/graph/badge.svg",
        "img.shields.io/badge/mypy-strict-blue.svg",
    ]
    missing_badges = [badge for badge in required_badges if badge not in readme]
    if missing_badges:
        fail(f"README badges are missing or inconsistent: {missing_badges}")

    print(f"Release metadata is consistent for {project_version}")


if __name__ == "__main__":
    main()
