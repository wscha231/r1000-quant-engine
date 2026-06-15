#!/usr/bin/env python3
"""Smoke test for repeated-leak self-correction router."""
from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_self_correction_router import parse_args, run  # noqa: E402


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
        assert queue["schema_version"] == "self-correction-router-v1.1"
        assert queue["repeat_confirmed"] is True
        assert len(queue["queued_experiments"]) == 4
        assert all(item["requires_user_approval"] is True for item in queue["queued_experiments"])
        assert all(item["status"] == "queued" for item in queue["queued_experiments"])
        assert all(item["source_run_id"] == "b" for item in queue["queued_experiments"])
        assert all(item["payload_hash"] for item in queue["queued_experiments"])
        assert all(item["ledger_sha_at_queue"] for item in queue["queued_experiments"])
        payloads = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert len(payloads) == 4
        assert all(payload["depends_on_plan_ids"] == ["full_rebuild_8y_official_after_data_bootstrap"] for payload in payloads)
        assert all(payload["plan_id"] == payload["experiment_id"] for payload in payloads)
        assert all(payload["status"] == "queued" for payload in payloads)
        assert all(payload["payload_hash"] for payload in payloads)
        first_inputs = payloads[0]["inputs"]
        assert first_inputs["backtest_years"] == "8"
        assert first_inputs["portfolio_policy"] == "alphaops_vnext_production"
        assert "experiment_env_json" in first_inputs
        assert "PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED" in first_inputs["experiment_env_json"]
        assert (out / "router_queue.md").exists()
        assert (out / "queue_state.jsonl").exists()
        assert (out / "deduped_queue.json").exists()
        assert (out / "stale_payloads.json").exists()
        assert (out / "closure_report.md").exists()
        commands = (out / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")
        assert "blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap" in commands
        assert "# gh workflow run" in commands


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
        assert payloads[0]["depends_on_plan_ids"] == ["full_rebuild_8y_official_after_data_bootstrap"]
        inputs = payloads[0]["inputs"]
        assert inputs["cache_key_suffix"] == "main_era_aware_scoring_challenger_review"
        assert "PHASE_ERA_AWARE_SCORING_CHALLENGER_REVIEW" in inputs["experiment_env_json"]
        assert "PHASE_ERA_AWARE_PORTFOLIO_KIND" in inputs["experiment_env_json"]


def test_self_correction_router_allows_payload_after_official_8y_window() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger_dir = root / "ledger"
        latest = root / "latest"
        ledger_dir.mkdir()
        (ledger_dir / "ledger.jsonl").write_text(
            json.dumps(row("a")) + "\n" + json.dumps(row("b")) + "\n",
            encoding="utf-8",
        )
        (ledger_dir / "latest_verdict.json").write_text(
            json.dumps({"dominant_open_leak": "concentrated:structural_underinvestment_bull"}),
            encoding="utf-8",
        )
        (latest / "eight_year_backtest_readiness").mkdir(parents=True)
        (latest / "eight_year_backtest_readiness" / "summary.json").write_text(
            json.dumps({"status": "official_eight_year_ready", "official_window_ready": True}),
            encoding="utf-8",
        )
        out = root / "router"
        queue = run(Namespace(ledger_dir=str(ledger_dir), latest_run=str(latest), output_dir=str(out), min_repeat=2, ref="master", repo="wscha231/r1000-quant-engine"))
        assert queue["requires_completed_plan_ids"] == []
        payloads = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert all(payload["depends_on_plan_ids"] == [] for payload in payloads)
        assert all(payload["status"] == "queued" for payload in payloads)
        commands = (out / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")
        assert "blocked until completed_plan_id" not in commands
        assert "\ngh workflow run" in commands


def test_self_correction_router_suppresses_duplicate_active_payloads() -> None:
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
        first_out = root / "router_first"
        first_queue = run(Namespace(ledger_dir=str(ledger_dir), output_dir=str(first_out), min_repeat=2, ref="master", repo="wscha231/r1000-quant-engine"))
        assert len(first_queue["queued_experiments"]) == 4

        second_out = root / "router_second"
        second_queue = run(
            Namespace(
                ledger_dir=str(ledger_dir),
                output_dir=str(second_out),
                previous_queue=str(first_out / "router_queue.json"),
                min_repeat=2,
                ref="master",
                repo="wscha231/r1000-quant-engine",
            )
        )
        assert second_queue["queued_experiments"] == []
        assert second_queue["duplicate_suppressed_count"] == 4
        assert second_queue["stale_payload_count"] == 0
        payloads = json.loads((second_out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert payloads == []


def test_self_correction_router_marks_previous_payloads_stale_when_ledger_changes() -> None:
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
        first_out = root / "router_first"
        run(Namespace(ledger_dir=str(ledger_dir), output_dir=str(first_out), min_repeat=2, ref="master", repo="wscha231/r1000-quant-engine"))

        (ledger_dir / "ledger.jsonl").write_text(
            json.dumps(row("a")) + "\n" + json.dumps(row("c")) + "\n",
            encoding="utf-8",
        )
        second_out = root / "router_second"
        second_queue = run(
            Namespace(
                ledger_dir=str(ledger_dir),
                output_dir=str(second_out),
                previous_queue=str(first_out / "router_queue.json"),
                min_repeat=2,
                ref="master",
                repo="wscha231/r1000-quant-engine",
            )
        )
        assert len(second_queue["queued_experiments"]) == 4
        assert second_queue["duplicate_suppressed_count"] == 0
        assert second_queue["stale_payload_count"] == 4
        stale_payloads = json.loads((second_out / "stale_payloads.json").read_text(encoding="utf-8"))
        assert len(stale_payloads) == 4
        assert all(item["status"] == "stale" for item in stale_payloads)


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


def test_self_correction_router_defaults_to_github_context_ref_and_repo() -> None:
    old_ref = os.environ.get("GITHUB_REF_NAME")
    old_repo = os.environ.get("GITHUB_REPOSITORY")
    try:
        os.environ["GITHUB_REF_NAME"] = "codex/self-sustaining-loop-20260615"
        os.environ["GITHUB_REPOSITORY"] = "wscha231/r1000-quant-engine"
        args = parse_args([])
        assert args.ref == "codex/self-sustaining-loop-20260615"
        assert args.repo == "wscha231/r1000-quant-engine"
    finally:
        if old_ref is None:
            os.environ.pop("GITHUB_REF_NAME", None)
        else:
            os.environ["GITHUB_REF_NAME"] = old_ref
        if old_repo is None:
            os.environ.pop("GITHUB_REPOSITORY", None)
        else:
            os.environ["GITHUB_REPOSITORY"] = old_repo


if __name__ == "__main__":
    test_self_correction_router_queues_repeated_concentrated_bull_leak()
    test_self_correction_router_routes_flat_alpha_to_era_challenger()
    test_self_correction_router_allows_payload_after_official_8y_window()
    test_self_correction_router_suppresses_duplicate_active_payloads()
    test_self_correction_router_marks_previous_payloads_stale_when_ledger_changes()
    test_self_correction_router_queues_oos_robustness_review_without_dispatch()
    test_self_correction_router_defaults_to_github_context_ref_and_repo()
    print("self_correction_router_smoke: PASS")
