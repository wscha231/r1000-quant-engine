#!/usr/bin/env python3
"""Smoke test for the research-only macro policy sidecar."""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from tools.run_macro_policy_engine import run  # noqa: E402


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
            reports / "regime_by_month.csv",
            [
                {
                    "rebalance_date": "2022-01-31",
                    "regime_label": "balanced",
                    "cash_target_used": 0.0,
                    "cash_weight": 0.05,
                    "drawdown_before_month": -0.04,
                    "drawdown_after_month": -0.07,
                },
                {
                    "rebalance_date": "2022-02-28",
                    "regime_label": "risk_off_alert",
                    "cash_target_used": 0.28,
                    "cash_weight": 0.35,
                    "drawdown_before_month": -0.07,
                    "drawdown_after_month": -0.10,
                },
                {
                    "rebalance_date": "2022-03-31",
                    "regime_label": "growth_reentry_alert",
                    "cash_target_used": 0.0,
                    "cash_weight": 0.12,
                    "drawdown_before_month": -0.10,
                    "drawdown_after_month": -0.06,
                },
                {
                    "rebalance_date": "2022-04-29",
                    "regime_label": "balanced",
                    "cash_target_used": 0.0,
                    "cash_weight": 0.02,
                    "drawdown_before_month": -0.02,
                    "drawdown_after_month": 0.0,
                },
            ],
        )
        _write_csv(
            reports / "main_monthly_weights.csv",
            [
                {"rebalance_date": "2022-01-31", "ticker": "AAA", "regime_state": "neutral"},
                {"rebalance_date": "2022-02-28", "ticker": "AAA", "regime_state": "bear"},
                {"rebalance_date": "2022-03-31", "ticker": "AAA", "regime_state": "bear"},
                {"rebalance_date": "2022-04-29", "ticker": "AAA", "regime_state": "bull"},
            ],
        )
        _write_csv(
            reports / "candidate_replay_book.csv",
            [
                {
                    "rebalance_date": "2022-01-31",
                    "ticker": "AAA",
                    "style_breakout_preference": 0.6,
                    "style_turnaround_preference": 0.2,
                    "style_quality_compounder_preference": 0.3,
                    "style_cash_defense_preference": 0.1,
                    "market_style_regime_label": "breakout_growth",
                },
                {
                    "rebalance_date": "2022-02-28",
                    "ticker": "AAA",
                    "style_breakout_preference": 0.1,
                    "style_turnaround_preference": 0.1,
                    "style_quality_compounder_preference": 0.2,
                    "style_cash_defense_preference": 0.8,
                    "market_style_regime_label": "cash_defense",
                },
            ],
        )
        out_dir = root / "out"
        summary = run(latest, out_dir)
        assert summary["status"] == "completed", summary
        assert summary["months"] == 4, summary
        assert summary["risk_state_counts"].get("red", 0) >= 1, summary
        assert (out_dir / "macro_policy_by_month.csv").exists()
        assert (out_dir / "regime_speed_audit.csv").exists()
        diagnostics = (out_dir / "regime_speed_audit.csv").read_text(encoding="utf-8")
        assert "late_risk_alert" in diagnostics
        assert "premature_growth_reentry" in diagnostics
    print("macro policy engine smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

