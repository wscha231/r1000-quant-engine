#!/usr/bin/env python3
"""Smoke entrypoint for H2 13F manager-skill policy tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = (
    ROOT / "tests" / "test_sec_13f_manager_policy.py",
    ROOT / "tests" / "test_sec_13f_manager_review.py",
)


def main() -> int:
    for optimize in (False, True):
        for test in TESTS:
            command = [sys.executable]
            if optimize:
                command.append("-O")
            command.append(str(test))
            completed = subprocess.run(command, cwd=ROOT)
            if completed.returncode != 0:
                return completed.returncode
    print("sec_13f_manager_skill_h2_smoke: PASS (64 unique tests; normal and -O)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
