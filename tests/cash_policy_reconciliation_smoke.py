#!/usr/bin/env python3
"""Smoke test for latest cash-policy reconciliation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_cash_policy_reconciliation import run  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cash_policy_reconciliation_flags_unconfirmed_mechanical_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        _write_json(
            latest / "macro_policy_engine" / "summary.json",
            {
                "status": "completed",
                "latest": {
                    "macro_risk_state": "green",
                    "macro_style_state": "breakout_growth",
                    "recommended_cash_floor": 0.03,
                    "cash_raise_gate": "none",
                    "cash_raise_confirmation_count": 0,
                    "confirmed_cash_raise": False,
                },
            },
        )
        _write_json(
            latest / "orchestrator" / "unified_target_latest.json",
            {
                "cash_target": 0.3044,
                "regime_state": "neutral",
                "by_mandate_capacity": {"main": 0.65, "concentrated": 0.10, "tactical": 0.0},
                "audit": {
                    "policy_capacity": {
                        "expected_total_invested": 0.75,
                        "actual_total_invested_after_merge": 0.6956,
                        "merged_below_expected_due_to_conflicts": 0.0544,
                    }
                },
            },
        )
        pd.DataFrame(
            [
                {"ticker": "AAA", "target_weight": 0.50},
                {"ticker": "CASH", "target_weight": 0.3044},
            ]
        ).to_csv(latest / "orchestrator" / "unified_target_latest.csv", index=False)
        _write_json(
            latest / "operating_snapshot" / "operating_snapshot_latest.json",
            {
                "current_cash_weight": 0.003,
                "target_cash_weight": 0.3044,
                "cash_policy_flag": "target_cash_above_macro_floor_without_confirmation",
                "cash_policy_review_action": "CASH_POLICY_REVIEW",
            },
        )
        for portfolio, target_cash in [("main", 0.0), ("concentrated", 0.0)]:
            _write_json(
                latest / "account_ledger_preview" / portfolio / "preview_metrics.json",
                {
                    "target_cash_weight": target_cash,
                    "cash_weight": 0.002,
                    "projected_cash_weight": 0.002,
                    "order_count": 0,
                    "blocked_order_count": 0,
                },
            )
        payload = run(latest, root / "out")
        assert payload["status"] == "completed", payload
        assert payload["review_required"] is True, payload
        assert payload["decision_point"] == "target_cash_exceeds_macro_floor_without_confirmation", payload
        assert round(float(payload["target_cash_above_macro_floor"]), 4) == 0.2744
        by_source = pd.read_csv(root / "out" / "cash_target_by_source.csv")
        assert "orchestrator_conflict_merge_cash" in set(by_source["source"])
        assert (root / "out" / "cash_policy_reconciliation_report.md").exists()


def main() -> int:
    test_cash_policy_reconciliation_flags_unconfirmed_mechanical_cash()
    print("cash_policy_reconciliation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
