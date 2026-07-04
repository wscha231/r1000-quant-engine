#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_chameleon_policy_audit import run  # noqa: E402


def test_chameleon_policy_audit_is_review_only_and_labels_shocks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        summary = root / "r1_summary.json"
        summary.write_text(
            json.dumps(
                {
                    "current_state": "CORRECTION",
                    "bear_warning_score": 6,
                    "confidence": 0.75,
                }
            ),
            encoding="utf-8",
        )
        shock_panel = root / "shock.csv"
        pd.DataFrame(
            [
                {"ticker": "AAA", "one_day_return": -0.13, "current_position_weight": 0.10},
                {"ticker": "BBB", "one_day_return": -0.02, "current_position_weight": 0.31},
                {"ticker": "CCC", "ma50_failed": True, "ma200_failed": True, "rs_3m": -0.05},
            ]
        ).to_csv(shock_panel, index=False)
        payload = run(
            argparse.Namespace(
                regime_summary=str(summary),
                state_history=str(root / "missing.csv"),
                state="",
                shock_panel=str(shock_panel),
                output_dir=str(root / "out"),
            )
        )
        actions = pd.read_csv(root / "out" / "recommended_actions.csv")
        assert payload["status"] == "completed", payload
        assert payload["current_state"] == "CORRECTION", payload
        assert payload["all_actions_review_only"] is True, payload
        assert payload["executable_order_allowed"] is False, payload
        assert payload["production_policy_mutation_allowed"] is False, payload
        assert payload["live_trading_allowed"] is False, payload
        assert set(actions["review_status"].astype(str)) == {"REVIEW_ONLY"}
        assert not actions["executable_order_allowed"].astype(bool).any()
        assert "no_new_discretionary_entries" in set(actions["action_label"].astype(str))
        assert "SHOCK_REVIEW" in set(actions["shock_guard_label"].dropna().astype(str))
        assert "TRIM_TO_CAP_REVIEW" in set(actions["shock_guard_label"].dropna().astype(str))
        assert "EXIT_REVIEW" in set(actions["shock_guard_label"].dropna().astype(str))
        assert (root / "out" / "summary.json").exists()
        assert (root / "out" / "report.md").exists()


def main() -> int:
    test_chameleon_policy_audit_is_review_only_and_labels_shocks()
    print("chameleon_policy_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
