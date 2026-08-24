#!/usr/bin/env python3
"""Materialize the exact v0.3 reference source and test suite from reviewable parts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ARTIFACTS = {
    "peer_wake_v03.py": (
        [
            "source_parts/peer_wake_v03.part01.pyfrag",
            "source_parts/peer_wake_v03.part02.pyfrag",
            "source_parts/peer_wake_v03.part03.pyfrag",
            "source_parts/peer_wake_v03.part04.pyfrag",
        ],
        "3733f63d06946d93c6a6872482c6978ccfd51f963e10261f9a7dbf3eea63c619",
    ),
    "test_peer_wake_v03.py": (
        [
            "source_parts/test_peer_wake_v03.part01.pyfrag",
            "source_parts/test_peer_wake_v03.part02.pyfrag",
            "source_parts/test_peer_wake_v03.part03.pyfrag",
        ],
        "7ef116990981ef6236b8ca04cde6fd234a970e65e1dd3f6f89f4d3cd804cee28",
    ),
}


def main() -> int:
    for target_name, (part_names, expected_digest) in ARTIFACTS.items():
        data = b"".join((ROOT / part_name).read_bytes() for part_name in part_names)
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != expected_digest:
            raise SystemExit(
                f"refusing to materialize {target_name}: digest {actual_digest} "
                f"!= expected {expected_digest}"
            )
        target = ROOT / target_name
        target.write_bytes(data)
        os.chmod(target, 0o755)
        print(f"materialized {target_name} sha256={actual_digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
