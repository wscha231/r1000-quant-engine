#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from argparse import Namespace
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.run_baseline_replay_repro_audit as audit  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_repro_audit_reports_drift_and_target_book_hash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        ab_dir = root / "ab"
        official_metrics = {
            "official_metric_mode": "broker_ledger_next_close",
            "portfolios": {
                "concentrated": {
                    "official_metric_mode": "broker_ledger_next_close",
                    "cagr": 0.4624,
                    "max_dd": -0.2582,
                    "sharpe": 1.42,
                    "years": 7.055,
                    "start_date": "2019-06-03",
                    "end_date": "2026-06-23",
                    "avg_cash_weight": 0.42,
                    "pit_universe_label_clean": False,
                    "production_promotion_allowed": False,
                }
            },
        }
        baseline_metrics = {
            "metric_mode": "broker_ledger_next_close",
            "cagr": 0.4719,
            "max_dd": -0.2581,
            "sharpe": 1.44,
            "years": 7.061,
            "start_date": "2019-06-03",
            "end_date": "2026-06-25",
            "avg_cash_weight": 0.421,
            "trade_count": 602,
        }
        target_book = "rebalance_date,ticker,target_weight\n2019-05-31,CASH,0.4\n2019-05-31,NVDA,0.3\n2026-06-25,CASH,0.1\n"
        write_json(latest / "account_evaluation" / "official_metrics.json", official_metrics)
        write_json(ab_dir / "baseline" / "broker" / "metrics.json", baseline_metrics)
        write_csv(ab_dir / "baseline" / "target_book.csv", target_book)
        write_json(
            ab_dir / "summary.json",
            {
                "arms": [
                    {
                        "arm": "baseline",
                        "broker_metrics_path": str(ab_dir / "baseline" / "broker" / "metrics.json"),
                        "target_book_path": str(ab_dir / "baseline" / "target_book.csv"),
                    },
                    {"arm": "cap30", "cap_breach_count": 0, "ab_verdict": "reject_no_cagr_edge"},
                ],
                "policy_candidates": [],
            },
        )
        write_json(
            root / "cache_prices" / "replay_price_cache_manifest.json",
            {"status": "completed", "start": "2019-05-09", "end": "2026-06-25", "ticker_count": 3},
        )

        payload = audit.run(
            Namespace(
                latest_run=str(latest),
                ab_dir=str(ab_dir),
                output_dir=str(root / "audit"),
                portfolio="concentrated",
                official_metrics="",
                ab_summary="",
                price_cache_manifest="",
            )
        )

        assert payload["conclusion"] == "explained_drift_end_date_mismatch"
        assert payload["blockers"]["window_mismatch_gt_0_03y"] is False
        assert payload["blockers"]["metric_mode_not_next_close"] is False
        assert payload["target_book"]["sha256"]
        assert payload["target_book"]["date_count"] == 2
        assert payload["warnings"]["end_date_mismatch"] is True
        assert payload["drift_changes_score_sizing_decision"] is False
        assert (root / "audit" / "summary.json").exists()
        assert (root / "audit" / "report.md").exists()


def test_repro_audit_blocks_bad_metric_mode_and_window_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        ab_dir = root / "ab"
        write_json(
            latest / "account_evaluation" / "official_metrics.json",
            {
                "official_metric_mode": "broker_ledger_next_close",
                "portfolios": {
                    "concentrated": {
                        "official_metric_mode": "broker_ledger_next_close",
                        "cagr": 0.46,
                        "max_dd": -0.25,
                        "years": 7.05,
                    }
                },
            },
        )
        write_json(
            ab_dir / "baseline" / "broker" / "metrics.json",
            {"metric_mode": "weight_level_research_comparison", "cagr": 0.50, "max_dd": -0.20, "years": 6.80},
        )
        write_csv(ab_dir / "baseline" / "target_book.csv", "rebalance_date,ticker,target_weight\n2019-05-31,CASH,1\n")
        write_json(
            ab_dir / "summary.json",
            {
                "arms": [
                    {
                        "arm": "baseline",
                        "broker_metrics_path": str(ab_dir / "baseline" / "broker" / "metrics.json"),
                        "target_book_path": str(ab_dir / "baseline" / "target_book.csv"),
                    }
                ],
                "policy_candidates": [],
            },
        )

        payload = audit.run(
            Namespace(
                latest_run=str(latest),
                ab_dir=str(ab_dir),
                output_dir=str(root / "audit"),
                portfolio="concentrated",
                official_metrics="",
                ab_summary="",
                price_cache_manifest="",
            )
        )

        assert payload["conclusion"] == "blocked_reproducibility_mismatch"
        assert payload["blockers"]["window_mismatch_gt_0_03y"] is True
        assert payload["blockers"]["metric_mode_not_next_close"] is True


if __name__ == "__main__":
    test_repro_audit_reports_drift_and_target_book_hash()
    test_repro_audit_blocks_bad_metric_mode_and_window_mismatch()
    print("baseline_replay_repro_audit_smoke: PASS")
