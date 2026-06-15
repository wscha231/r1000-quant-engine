#!/usr/bin/env python3
"""Smoke test for repeated-leak self-correction router."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_self_correction_router import run  # noqa: E402


def row(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "portfolios": {
            "concentrated": {
                "leak_year_tags": {
                    "2021": "structural_underinvestment_bull",
                    "2023": "structural_underinvestment_bull",
                }
            },
            "main": {"leak_year_tags": {}},
        },
    }


def flat_alpha_row(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "portfolios": {
            "main": {
                "leak_year_tags": {
                    "2021": "flat_alpha_invested",
                    "2023": "flat_alpha_invested",
                }
            },
            "concentrated": {"leak_year_tags": {}},
        },
    }


def test_self_correction_router_queues_repeated_concentrated_bull_leak() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger_dir = root / "ledger"
        ledger_dir.mkdir()
        (ledger_dir / "ledger.jsonl").write_text(
            json.dumps(row("a")) + "\n" + json.dumps(row("b")) + "\n",
            encoding="utf-8",
        )
        (ledger_dir / "latest_verdict.json").write_text(
            json.dumps({"dominant_open_leak": "concentrated:structural_underinvestment_bull"}),
            encoding="utf-8",
        )
        out = root / "router"
        queue = run(Namespace(ledger_dir=str(ledger_dir), output_dir=str(out), min_repeat=2, ref="master", repo="wscha231/r1000-quant-engine"))
        assert queue["production_mutation_allowed"] is False
        assert queue["repeat_confirmed"] is True
        assert len(queue["queued_experiments"]) == 4
        assert all(item["requires_user_approval"] is True for item in queue["queued_experiments"])
        payloads = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert len(payloads) == 4
        first_inputs = payloads[0]["inputs"]
        assert first_inputs["backtest_years"] == "8"
        assert first_inputs["portfolio_policy"] == "alphaops_vnext_production"
        assert "experiment_env_json" in first_inputs
        assert "PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED" in first_inputs["experiment_env_json"]
        assert (out / "router_queue.md").exists()
        assert "gh workflow run" in (out / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")


def test_self_correction_router_routes_flat_alpha_to_era_challenger() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger_dir = root / "ledger"
        ledger_dir.mkdir()
        (ledger_dir / "ledger.jsonl").write_text(
            json.dumps(flat_alpha_row("a")) + "\n" + json.dumps(flat_alpha_row("b")) + "\n",
            encoding="utf-8",
        )
        (ledger_dir / "latest_verdict.json").write_text(
            json.dumps({"dominant_open_leak": "main:flat_alpha_invested"}),
            encoding="utf-8",
        )
        out = root / "router"
        queue = run(Namespace(ledger_dir=str(ledger_dir), output_dir=str(out), min_repeat=2, ref="master", repo="wscha231/r1000-quant-engine"))
        assert queue["repeat_confirmed"] is True
        assert len(queue["queued_experiments"]) == 1
        item = queue["queued_experiments"][0]
        assert item["experiment_id"] == "main_era_aware_scoring_challenger_review"
        assert item["production_mutation_allowed"] is False
        payloads = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        inputs = payloads[0]["inputs"]
        assert inputs["cache_key_suffix"] == "main_era_aware_scoring_challenger_review"
        assert "PHASE_ERA_AWARE_SCORING_CHALLENGER_REVIEW" in inputs["experiment_env_json"]
        assert "PHASE_ERA_AWARE_PORTFOLIO_KIND" in inputs["experiment_env_json"]


def test_self_correction_router_queues_oos_robustness_review_without_dispatch() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger_dir = root / "ledger"
        latest = root / "latest"
        ledger_dir.mkdir()
        (ledger_dir / "ledger.jsonl").write_text(json.dumps(row("a")) + "\n", encoding="utf-8")
        (ledger_dir / "latest_verdict.json").write_text(json.dumps({}), encoding="utf-8")
        (latest / "oos_lock").mkdir(parents=True)
        (latest / "oos_lock" / "summary.json").write_text(
            json.dumps(
                {
                    "status": "fail",
                    "lock_pass": False,
                    "failures": {"concentrated": ["oos_is_cagr_ratio_above_lock"]},
                    "portfolios": {
                        "concentrated": {
                            "status": "fail",
                            "cagr_is": 0.22,
                            "cagr_oos": 1.20,
                            "oos_is_cagr_ratio": 5.45,
                            "max_oos_is_cagr_ratio": 3.0,
                            "oos_trading_days": 480,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        out = root / "router"
        queue = run(Namespace(ledger_dir=str(ledger_dir), latest_run=str(latest), output_dir=str(out), min_repeat=2, ref="master", repo="wscha231/r1000-quant-engine"))
        assert queue["production_mutation_allowed"] is False
        assert queue["repeat_confirmed"] is False
        assert queue["queued_experiments"] == []
        assert queue["queued_review_task_count"] == 1
        task = queue["queued_review_tasks"][0]
        assert task["dispatch_mode"] == "manual_review_no_workflow_dispatch"
        assert task["production_mutation_allowed"] is False
        assert task["requires_user_approval"] is True
        assert task["portfolio"] == "concentrated"
        assert task["failure"] == "oos_is_cagr_ratio_above_lock"
        assert "era_leadership/summary.json" in task["review_artifacts"]
        assert task["metrics"]["oos_is_cagr_ratio"] == 5.45
        payloads = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert payloads == []
        report = (out / "router_queue.md").read_text(encoding="utf-8")
        assert "oos_lottery_era_name_review" in report


if __name__ == "__main__":
    test_self_correction_router_queues_repeated_concentrated_bull_leak()
    test_self_correction_router_routes_flat_alpha_to_era_challenger()
    test_self_correction_router_queues_oos_robustness_review_without_dispatch()
    print("self_correction_router_smoke: PASS")
