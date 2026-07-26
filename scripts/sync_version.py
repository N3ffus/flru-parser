"""Synchronize derived version declarations with pyproject.toml."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_one(text: str, pattern: str, replacement: str, source: Path) -> str:
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise SystemExit(f"expected one version marker in {source}, found {count}")
    return updated


def synchronized_files() -> dict[Path, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(pyproject["project"]["version"])

    init_path = ROOT / "src/flru/__init__.py"
    init_text = replace_one(
        init_path.read_text(encoding="utf-8"),
        r'^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        init_path,
    )

    models_path = ROOT / "src/flru/models.py"
    models_text = replace_one(
        models_path.read_text(encoding="utf-8"),
        r'^PARSER_VERSION = "[^"]+"$',
        f'PARSER_VERSION = "{version}"',
        models_path,
    )

    readme_path = ROOT / "README.md"
    readme_source = readme_path.read_text(encoding="utf-8")
    readme_source = replace_one(
        readme_source,
        r"img\.shields\.io/badge/version-[0-9]+\.[0-9]+\.[0-9]+-blue\.svg",
        f"img.shields.io/badge/version-{version}-blue.svg",
        readme_path,
    )
    release_block = (
        "<!-- release-version:start -->\n"
        "```bash\n"
        f'git tag -a v{version} -m "flru-parser {version}"\n'
        f"git push origin main v{version}\n"
        "```\n"
        "<!-- release-version:end -->"
    )
    readme_text = replace_one(
        readme_source,
        r"<!-- release-version:start -->.*?<!-- release-version:end -->",
        release_block,
        readme_path,
    )
    return {
        init_path: init_text,
        models_path: models_text,
        readme_path: readme_text,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of updating files when synchronized content differs.",
    )
    args = parser.parse_args()
    changed = []
    for path, expected in synchronized_files().items():
        current = path.read_text(encoding="utf-8")
        if current == expected:
            continue
        changed.append(path.relative_to(ROOT))
        if not args.check:
            path.write_text(expected, encoding="utf-8")
    if args.check and changed:
        rendered = ", ".join(str(path) for path in changed)
        raise SystemExit(f"version-derived files are stale: {rendered}")
    action = "checked" if args.check else "synchronized"
    print(f"{action} version-derived files")


if __name__ == "__main__":
    main()
