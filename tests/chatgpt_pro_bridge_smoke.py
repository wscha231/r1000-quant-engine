#!/usr/bin/env python3
"""Smoke checks for manual ChatGPT Pro bridge packet generation."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_chatgpt_pro_bridge_generates_question_and_response_templates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        out = root / "bridge"
        write_json(
            latest / "broker_replay" / "main" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.22,
                "max_dd": -0.29,
                "sharpe": 1.1,
                "trade_count": 100,
                "avg_cash_weight": 0.05,
            },
        )
        write_json(
            latest / "broker_replay" / "concentrated" / "metrics.json",
            {
                "status": "completed",
                "metric_mode": "broker_ledger_next_close",
                "valid_for_production": True,
                "cagr": 0.35,
                "max_dd": -0.23,
                "sharpe": 1.3,
            },
        )
        extra = root / "selection_quality_summary.json"
        write_json(extra, {"top_factor": "portfolio_future_winner_engine_score", "research_only": True})

        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "run_chatgpt_pro_bridge.py"),
                "--agent",
                "A10",
                "--latest-run",
                str(latest),
                "--run-url",
                "https://github.com/example/run/1",
                "--input-file",
                str(extra),
                "--output-dir",
                str(out),
            ],
            cwd=REPO_ROOT,
            check=True,
        )

        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["api_used"] is False
        assert "A10" in manifest["agents"]
        question = (out / "pro_question_a10.md").read_text(encoding="utf-8")
        response = (out / "pro_response_template_a10.md").read_text(encoding="utf-8")
        assert "[PRO_QUESTION]" in question
        assert "A10 AutoLearning/Test Engine" in question
        assert "broker_ledger_next_close" in question
        assert "codex/broker-ledger-replay-foundation" in question
        assert "latest 20260516 is a regression case" in question
        assert "https://github.com/example/run/1" in question
        assert "selection_quality_summary.json" in question
        assert "[PRO_RESPONSE]" in response
        assert "Verify this response against repo artifacts" in response


def test_chatgpt_pro_bridge_generates_all_agent_packets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "bridge"
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "tools" / "run_chatgpt_pro_bridge.py"),
                "--agent",
                "all",
                "--latest-run",
                str(Path(tmp) / "missing_latest"),
                "--output-dir",
                str(out),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert set(manifest["agents"]) == {"A0", "A2", "A3", "A4", "A5", "A7", "A10"}
        for agent in manifest["agents"]:
            assert (out / f"pro_question_{agent.lower()}.md").exists()
            assert (out / f"pro_response_template_{agent.lower()}.md").exists()


if __name__ == "__main__":
    test_chatgpt_pro_bridge_generates_question_and_response_templates()
    test_chatgpt_pro_bridge_generates_all_agent_packets()
    print("chatgpt_pro_bridge_smoke: PASS")
