#!/usr/bin/env python3
"""Smoke test crisis re-entry policy avoids future-month drawdown leakage."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_crisis_reentry_replay import POLICIES, target_cash_for_month  # noqa: E402


def main() -> int:
    target, action = target_cash_for_month(
        state="green",
        policy=POLICIES["fast_reentry"],
        prev_target_cash=0.50,
        drawdown_before=0.0,
        drawdown_after=-0.50,
    )
    assert action == "green_redeploy_step", (target, action)
    assert target < 0.50, (target, action)
    print("crisis_reentry_policy_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
