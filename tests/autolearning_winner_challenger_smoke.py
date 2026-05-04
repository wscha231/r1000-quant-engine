#!/usr/bin/env python3
"""Smoke test for AutoLearning winner challenger harness."""
from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_autolearning_winner_challenger import run  # noqa: E402


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        latest = root / "latest"
        auto = root / "auto"
        lifecycle = root / "lifecycle"
        onset = root / "onset"
        shakeout = root / "shakeout"
        cash_drag = root / "cash_drag"
        out = root / "out"
        latest.mkdir(parents=True)
        auto.mkdir(parents=True)
        lifecycle.mkdir(parents=True)
        onset.mkdir(parents=True)
        shakeout.mkdir(parents=True)
        cash_drag.mkdir(parents=True)

        write_json(latest / "backtest_metrics.json", {
            "strategy_cagr": 0.24,
            "sharpe": 1.2,
            "max_dd": -0.22,
            "avg_cash_weight": 0.09,
            "months": 84,
        })
        write_json(latest / "concentrated_backtest_metrics.json", {
            "strategy_cagr": 0.35,
            "sharpe": 1.1,
            "max_dd": -0.24,
            "selected_names": 5,
        })
        write_json(auto / "hypotheses_latest.json", [{"id": "h1"}, {"id": "h2"}])
        (latest / "reports").mkdir(parents=True)
        pd.DataFrame([
            {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.86},
            {"rebalance_date": "2024-01-31", "ticker": "CASH", "weight": 0.14},
        ]).to_csv(latest / "reports" / "main_monthly_weights.csv", index=False)
        pd.DataFrame([{"hypothesis_id": "h1", "status": "needs_full_challenger_backtest"}]).to_csv(
            auto / "counterfactual_results.csv", index=False
        )
        pd.DataFrame([{"ticker": "AAA"}, {"ticker": "BBB"}]).to_csv(lifecycle / "missed_winner_report.csv", index=False)
        pd.DataFrame([{"ticker": "OLD"}]).to_csv(lifecycle / "stale_winner_report.csv", index=False)
        pd.DataFrame([{"held_ticker": "OLD", "challenger_ticker": "AAA"}]).to_csv(
            lifecycle / "leadership_rotation_report.csv", index=False
        )
        write_json(onset / "pattern_summary.json", {"event_count": 2, "production_activation_allowed": False})
        pd.DataFrame([
            {
                "ticker": "AAA",
                "hold_3m_return": 0.2,
                "hold_6m_return": 0.8,
                "hold_12m_return": 1.5,
                "trail20_after_50pct_return": 1.1,
            },
            {
                "ticker": "BBB",
                "hold_3m_return": -0.1,
                "hold_6m_return": 0.4,
                "hold_12m_return": 0.9,
                "trail20_after_50pct_return": 0.7,
            },
        ]).to_csv(onset / "hold_diagnostics.csv", index=False)
        pd.DataFrame([{"ticker": "AAA"}, {"ticker": "BBB"}]).to_csv(onset / "events.csv", index=False)
        write_json(shakeout / "pattern_summary.json", {
            "event_count": 2,
            "production_activation_allowed": False,
            "label_counts": {"SHAKEOUT": 1, "TRUE_BREAKDOWN": 1},
        })
        pd.DataFrame([{"ticker": "AAA"}, {"ticker": "BBB"}]).to_csv(shakeout / "events.csv", index=False)
        pd.DataFrame([
            {
                "label": "SHAKEOUT",
                "horizon": "6m",
                "action": "add25",
                "n": 1,
                "avg_return": 0.5,
                "median_return": 0.5,
                "hit_rate": 1.0,
                "worst_return": 0.5,
                "best_return": 0.5,
            }
        ]).to_csv(shakeout / "action_summary.csv", index=False)
        write_json(cash_drag / "summary.json", {
            "production_activation_allowed": False,
            "best_by_cagr": {"model": "cash0.00_cap0.22", "cash_cap": 0.0, "single_name_cap": 0.22},
            "base_metrics": {"avg_cash_weight": 0.14},
        })

        decision = run(Namespace(
            latest_run=str(latest),
            autolearning_dir=str(auto),
            lifecycle_dir=str(lifecycle),
            onset_dir=str(onset),
            shakeout_dir=str(shakeout),
            cash_drag_dir=str(cash_drag),
            output_dir=str(out),
        ))
        assert decision["production_activation_allowed"] is False
        assert decision["autolearning"]["hypothesis_count"] == 2
        assert decision["winner_lifecycle"]["missed_count"] == 2
        assert decision["winner_onset"]["event_count"] == 2
        assert decision["shakeout_breakdown"]["event_count"] == 2
        assert decision["event_level_backtest"]["status"] == "available"
        assert decision["shakeout_action_backtest"]["status"] == "available"
        assert decision["baseline"]["main"]["latest_cash_weight"] == 0.14
        assert decision["policy_value_replay"]["status"] == "CAGR_FIRST_REPLAY_REQUIRED"
        assert decision["main_cash_drag_replay"]["status"] == "available"
        assert decision["winner_lifecycle"]["top_rotations"] == ["OLD->AAA"]
        assert decision["verdict"] == "EVENT_LEVEL_ONLY_WAIT_FOR_MONTHLY_BOOKS"
        assert (out / "summary.json").exists()
        assert (out / "candidate_experiment.yaml").exists()
        assert "production_activation_allowed: false" in (out / "candidate_experiment.yaml").read_text(encoding="utf-8")
        assert "cash_drag_reduction_grid" in (out / "candidate_experiment.yaml").read_text(encoding="utf-8")
        assert "current_best_cash_cap: 0.0" in (out / "candidate_experiment.yaml").read_text(encoding="utf-8")

    print("autolearning_winner_challenger_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
