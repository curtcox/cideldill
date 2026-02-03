"""Verify duplicated files remain identical across client/server packages."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

DUPLICATES = [
    (
        Path("client/src/cideldill_client/serialization.py"),
        Path("server/src/cideldill_server/serialization.py"),
    ),
    (
        Path("client/src/cideldill_client/exceptions.py"),
        Path("server/src/cideldill_server/exceptions.py"),
    ),
    (
        Path("client/src/cideldill_client/py.typed"),
        Path("server/src/cideldill_server/py.typed"),
    ),
]


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    mismatches = []
    for left, right in DUPLICATES:
        if not left.exists() or not right.exists():
            mismatches.append(f"Missing duplicate: {left} or {right}")
            continue
        if _hash_file(left) != _hash_file(right):
            mismatches.append(f"Mismatch: {left} != {right}")

    if mismatches:
        print("Duplicate file check failed:")
        for msg in mismatches:
            print(f"- {msg}")
        return 1

    print("Duplicate file check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
