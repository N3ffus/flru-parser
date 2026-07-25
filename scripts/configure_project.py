"""Replace the repository-owner placeholder in release metadata."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FILES = (
    Path("pyproject.toml"),
    Path("README.md"),
    Path("CONTRIBUTING.md"),
    Path(".github/ISSUE_TEMPLATE/config.yml"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("owner", help="GitHub account or organization name")
    args = parser.parse_args()
    owner = args.owner.strip()
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
        raise SystemExit("owner must be a valid GitHub account or organization name")
    changed = 0
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        updated = text.replace("OWNER", owner)
        if text != updated:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    print(f"Configured {changed} files for github.com/{owner}/flru-parser")


if __name__ == "__main__":
    main()
