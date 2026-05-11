#!/usr/bin/env python3
"""Smoke test for cash-policy attribution diagnostics."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_cash_policy_attribution import run  # noqa: E402


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        reports = latest / "reports"
        _write_csv(
            reports / "main_monthly_weights.csv",
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.80},
                {"rebalance_date": "2026-01-31", "ticker": "CASH", "weight": 0.20},
                {"rebalance_date": "2026-02-28", "ticker": "AAA", "weight": 0.70},
                {"rebalance_date": "2026-02-28", "ticker": "CASH", "weight": 0.30},
                {"rebalance_date": "2026-03-31", "ticker": "AAA", "weight": 0.40},
                {"rebalance_date": "2026-03-31", "ticker": "BBB", "weight": 0.28},
                {"rebalance_date": "2026-03-31", "ticker": "CCC", "weight": 0.20},
                {"rebalance_date": "2026-03-31", "ticker": "CASH", "weight": 0.12},
            ],
        )
        _write_csv(
            reports / "regime_by_month.csv",
            [
                {
                    "rebalance_date": "2026-01-31",
                    "regime_label": "war_shock_alert",
                    "cash_weight_start": 0.20,
                    "cash_weight": 0.20,
                    "cash_weight_end": 0.20,
                    "cash_target_used": 0.15,
                    "drawdown_before_month": -0.03,
                    "drawdown_after_month": -0.04,
                },
                {
                    "rebalance_date": "2026-02-28",
                    "regime_label": "risk_off_alert",
                    "cash_weight_start": 0.30,
                    "cash_weight": 0.30,
                    "cash_weight_end": 0.30,
                    "cash_target_used": 0.28,
                    "drawdown_before_month": -0.12,
                    "drawdown_after_month": -0.16,
                },
                {
                    "rebalance_date": "2026-03-31",
                    "regime_label": "balanced",
                    "cash_weight_start": 0.12,
                    "cash_weight": 0.80,
                    "cash_weight_end": 0.80,
                    "cash_target_used": 0.00,
                    "drawdown_before_month": -0.01,
                    "drawdown_after_month": -0.01,
                },
            ],
        )
        out_dir = root / "out"
        summary = run(latest, out_dir)
        assert summary["status"] == "completed", summary
        reasons = summary["reason_counts"]
        assert reasons.get("event_shock_cash_to_review", 0) == 1, summary
        assert reasons.get("confirmed_macro_defense_cash", 0) == 1, summary
        assert reasons.get("idle_cash_candidate", 0) == 1, summary
        assert summary["months_cash_export_mismatch_gt_2pct"] == 0, summary
        assert round(summary["avg_period_end_cash_weight"], 2) == 0.43, summary
        rows = (out_dir / "cash_drag_attribution.csv").read_text(encoding="utf-8")
        assert "confirmed_macro_defense" in rows
        assert "event_shock_without_confirmation" in rows
    print("cash policy attribution smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
