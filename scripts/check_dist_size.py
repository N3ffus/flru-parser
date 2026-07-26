"""Reject unexpectedly large release archives."""

from __future__ import annotations

import argparse
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    args = parser.parse_args()
    files = sorted(path for path in args.dist.iterdir() if path.is_file())
    if not files:
        raise SystemExit("no distributions found")
    oversized = [path for path in files if path.stat().st_size > MAX_FILE_BYTES]
    total = sum(path.stat().st_size for path in files)
    for path in files:
        print(f"{path.name}: {path.stat().st_size} bytes")
    if oversized or total > MAX_TOTAL_BYTES:
        raise SystemExit("distribution size limit exceeded")


if __name__ == "__main__":
    main()
