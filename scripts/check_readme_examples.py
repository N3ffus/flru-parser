"""Compile documented Python examples without making network requests."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    examples = sorted((ROOT / "examples").glob("*.py"))
    if not examples:
        raise SystemExit("no Python examples found")
    for path in examples:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        print(f"checked {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
