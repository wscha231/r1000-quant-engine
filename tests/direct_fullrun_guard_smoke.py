#!/usr/bin/env python3
"""The pipeline module must fail closed without two explicit fullrun opts."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_direct_module_execution_is_blocked_by_default() -> None:
    env = os.environ.copy()
    env.pop("R1000_ALLOW_DIRECT_FULLRUN", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "r1000_pipeline.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "direct full pipeline blocked" in result.stderr


if __name__ == "__main__":
    test_direct_module_execution_is_blocked_by_default()
    print("direct_fullrun_guard_smoke: PASS")
