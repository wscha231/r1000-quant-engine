#!/usr/bin/env python3
"""Smoke test for review-only daily crisis paper actions."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_daily_crisis_monitor import ALLOWED_PAPER_ACTION_TYPES, build_paper_action_candidates  # noqa: E402


def test_daily_crisis_paper_actions_are_whitelisted_review_only() -> None:
    holdings = pd.DataFrame(
        [
            {"ticker": "AAA", "current_weight": 0.22},
            {"ticker": "BBB", "current_weight": 0.17},
        ]
    )
    actions = build_paper_action_candidates(
        state="DEFENSE",
        raw_state="DEFENSE",
        reasons=["macro liquidity/credit confirmation"],
        holdings=holdings,
    )
    action_types = {item["action_type"] for item in actions}
    assert action_types <= set(ALLOWED_PAPER_ACTION_TYPES)
    assert "raise_cash" in action_types
    assert "trim_position" in action_types
    assert "block_new_buys" in action_types
    assert all("live_order" not in item for item in actions)


if __name__ == "__main__":
    test_daily_crisis_paper_actions_are_whitelisted_review_only()
    print("daily_crisis_paper_actions_smoke: PASS")
