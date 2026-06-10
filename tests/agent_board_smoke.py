#!/usr/bin/env python3
"""Smoke checks for the artifact-only multi-agent board."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_agent_board import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_agent_board_blocks_regression_and_writes_packets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "agent_board"
        write_json(
            root / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "production_target_pass": False,
                "portfolios": {
                    "main": {
                        "portfolio": "main",
                        "status": "completed",
                        "valid_for_production": True,
                        "official_metric_mode": "broker_ledger_next_close",
                        "cagr": 0.1286,
                        "max_dd": -0.2707,
                        "sharpe": 0.8,
                        "broker_trade_count": 100,
                    },
                    "concentrated": {
                        "portfolio": "concentrated",
                        "status": "completed",
                        "valid_for_production": True,
                        "official_metric_mode": "broker_ledger_next_close",
                        "cagr": 0.1689,
                        "max_dd": -0.3380,
                        "sharpe": 0.7,
                        "broker_trade_count": 80,
                    },
                },
            },
        )
        write_json(
            root / "sec_enriched_candidate_replay" / "summary.json",
            {
                "status": "ok",
                "research_only": True,
                "production_activation_allowed": False,
                "coverage_ratio": 0.05,
            },
        )

        result = run(
            argparse.Namespace(
                latest_run=str(root),
                output_dir=str(out),
                run_url="https://github.com/wscha231/r1000-quant-engine/actions/runs/example",
                max_tasks=0,
            )
        )
        assert result["status"] == "ok"
        summary = json.loads((out / "board_summary.json").read_text(encoding="utf-8"))
        tasks = json.loads((out / "agent_task_queue.json").read_text(encoding="utf-8"))
        gate = json.loads((out / "promotion_gate_review.json").read_text(encoding="utf-8"))

        assert summary["production_activation_allowed"] is False
        assert gate["automatic_promotion_allowed"] is False
        assert gate["human_promotion_review_candidate"] is False
        assert any(item["agent"] == "A4" for item in tasks), tasks
        assert any(item["agent"] == "A5" for item in tasks), tasks
        assert any(item["agent"] == "A7" for item in tasks), tasks
        assert (out / "pro_packets" / "a4.md").exists()
        assert "latest 20260516 is a regression case" in (out / "pro_packets" / "a4.md").read_text(encoding="utf-8")
        assert (out / "report.md").exists()


def test_agent_board_rejects_proxy_without_official_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out = root / "agent_board"
        write_json(root / "backtest_metrics.json", {"cagr": 0.99, "max_dd": -0.01, "sharpe": 9.0})

        run(
            argparse.Namespace(
                latest_run=str(root),
                output_dir=str(out),
                run_url="",
                max_tasks=0,
            )
        )
        summary = json.loads((out / "board_summary.json").read_text(encoding="utf-8"))
        tasks = json.loads((out / "agent_task_queue.json").read_text(encoding="utf-8"))

        assert all(not row["official_evidence"] for row in summary["portfolios"])
        assert all(row["governance_action"] == "rerun_broker_ledger_missing_official" for row in summary["portfolios"])
        assert any(item["agent"] == "A6" and item["priority"] == "P0" for item in tasks)


if __name__ == "__main__":
    test_agent_board_blocks_regression_and_writes_packets()
    test_agent_board_rejects_proxy_without_official_metrics()
    print("agent_board_smoke: PASS")
