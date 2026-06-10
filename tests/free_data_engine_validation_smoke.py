#!/usr/bin/env python3
"""Smoke checks for free data engine validation reports."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_free_data_engine_validation import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_free_data_engine_validation_reports_metrics_and_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        proxy = root / "proxy"
        coverage = root / "data_pit" / "free" / "coverage_audit.json"
        out = root / "validation"
        base_metrics = {
            "status": "completed",
            "start_date": "2020-01-02",
            "end_date": "2026-05-08",
            "cagr": 0.2,
            "sharpe": 1.0,
            "max_dd": -0.3,
            "trade_count": 100,
            "metric_mode": "broker_ledger_next_close",
        }
        for base in [latest / "broker_replay", proxy]:
            write_json(base / "main" / "metrics.json", base_metrics)
            write_json(base / "concentrated" / "metrics.json", {**base_metrics, "cagr": 0.3, "max_dd": -0.4})
        write_json(coverage, {"pit_label": "pit_proxy_universe", "readiness": "ready_for_proxy_replay", "known_gaps": []})
        write_json(latest / "auto_learning_v2" / "promotion_decision.json", {"status": "blocked"})
        write_json(
            latest / "policy_fusion" / "policy_fusion_summary.json",
            {"activation_queue": [{"policy_id": "long_winner_hold_template", "portfolio": "main", "priority": "watch"}]},
        )
        payload = run(
            argparse.Namespace(
                latest_run=str(latest),
                proxy_backtest_dir=str(proxy),
                coverage=str(coverage),
                output_dir=str(out),
            )
        )
        assert payload["validation_status"] == "ready_for_learning_review"
        assert len(payload["metrics"]) == 4
        assert any(row["cagr"] == 0.3 for row in payload["metrics"])
        assert (out / "summary.json").exists()
        assert "MaxDD" in (out / "report.md").read_text(encoding="utf-8")


def main() -> int:
    test_free_data_engine_validation_reports_metrics_and_gate()
    print("free data engine validation smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
