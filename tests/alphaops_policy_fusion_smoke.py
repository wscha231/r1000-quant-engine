#!/usr/bin/env python3
"""Smoke test AlphaOps policy fusion artifact arbitration."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools.run_alphaops_policy_fusion import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class Args:
    def __init__(self, latest_run: Path, output_dir: Path) -> None:
        self.latest_run = str(latest_run)
        self.output_dir = str(output_dir)


def build_fixture(base: Path) -> None:
    write_json(
        base / "backtest_metrics.json",
        {"cagr": 0.23, "max_dd": -0.27, "sharpe": 1.10, "avg_cash_weight": 0.21},
    )
    write_json(
        base / "concentrated_backtest_metrics.json",
        {"cagr": 0.35, "max_dd": -0.23, "sharpe": 1.18},
    )
    write_json(
        base / "main_v2_backtest" / "metrics.json",
        {"cagr": 0.29, "max_dd": -0.20, "sharpe": 1.22, "avg_turnover_monthly": 0.18},
    )
    write_json(
        base / "concentrated_position_risk_replay" / "metrics.json",
        {"cagr": 0.51, "max_dd": -0.17, "sharpe": 1.75, "avg_turnover_monthly": 0.25},
    )
    write_json(
        base / "crisis_reentry_replay" / "metrics.json",
        {
            "best_by_cagr": {
                "policy_id": "fast_reentry",
                "cagr": 0.32,
                "max_dd": -0.11,
                "sharpe": 1.98,
                "avg_turnover_monthly": 0.20,
            }
        },
    )
    write_json(
        base / "main_cash_drag_replay" / "summary.json",
        {
            "best_by_cagr": {
                "model": "cash0.00_cap0.25",
                "cagr": 0.28,
                "max_dd": -0.24,
                "sharpe": 1.30,
            }
        },
    )
    write_rows(
        base / "historical_trade_journey" / "historical_decision_priorities.csv",
        [
            {"action": "current_position_stale_review", "ticker": "AAA", "priority": 110},
            {"action": "study_premature_exit_or_fast_capture", "ticker": "BBB", "priority": 85},
        ],
    )
    write_json(
        base / "macro_policy_engine" / "summary.json",
        {"latest": {"macro_risk_state": "green", "macro_style_state": "breakout_growth"}},
    )


def test_policy_fusion_smoke() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "out"
        build_fixture(latest)
        payload = run(Args(latest, out))
        assert payload["production_mutation_allowed"] is False
        policy_ids = {row["policy_id"] for row in payload["policy_candidates"]}
        assert "macro_crisis_cash_ladder" in policy_ids
        assert "position_hard_stop_distribution" in policy_ids
        assert "stale_leader_trim" in policy_ids
        assert (out / "policy_fusion_summary.json").exists()
        assert (out / "activation_plan.yaml").exists()
        matrix = (out / "conflict_matrix.csv").read_text(encoding="utf-8")
        assert "macro_crisis_cash_ladder" in matrix
        assert "idle_cash_redeploy" in matrix


def main() -> int:
    test_policy_fusion_smoke()
    print("alphaops policy fusion smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
