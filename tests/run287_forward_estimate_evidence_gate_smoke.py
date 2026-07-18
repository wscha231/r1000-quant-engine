#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_forward_estimate_evidence_gate import (  # noqa: E402
    STATUS_BLOCKED,
    STATUS_READY,
    STATUS_UNDERPOWERED,
    run,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_rows(tickers: list[str], date: str, *, exact: bool = False) -> pd.DataFrame:
    available = f"{date}T12:00:00Z" if exact else date
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "as_of_date": date,
                "available_from": available,
                "fetch_source": "fmp",
                "eps_estimate_access": True,
                "revenue_estimate_access": True,
                "vendor_estimate_access": True,
                "has_forward_estimate": 1,
                "est_eps_fy1": float(index + 1),
                "est_eps_fy2": float(index + 2),
                "est_rev_fy1": float(index + 3),
            }
            for index, ticker in enumerate(tickers)
        ]
        + [
            {
                "ticker": "MISSING",
                "as_of_date": date,
                "available_from": available,
                "fetch_source": "finnhub",
                "eps_estimate_access": False,
                "revenue_estimate_access": False,
                "vendor_estimate_access": False,
                "has_forward_estimate": 0,
                "est_eps_fy1": 0.0,
                "est_eps_fy2": 0.0,
                "est_rev_fy1": 0.0,
            }
        ]
    )


def build_fixture(
    root: Path,
    *,
    true_count: int,
    observed_count: int,
    resolved_count: int,
    blocks_21d: int,
    blocks_63d: int,
    review_ready: bool,
    exact: bool = False,
) -> dict[str, Path]:
    archive = root / "data_pit" / "events" / "earnings_estimates"
    ledger_dir = root / "outputs" / "free_data_forward_paper_ledger"
    archive.mkdir(parents=True)
    ledger_dir.mkdir(parents=True)
    snapshot = archive / "estimates_20260718.parquet"
    snapshot_rows([f"T{index:03d}" for index in range(true_count)], "2026-07-18", exact=exact).to_parquet(
        snapshot, index=False
    )
    index_row = {
        "fetch_date": "2026-07-18",
        "snapshot_sha256": sha256(snapshot),
        "collector_status": "blocked_partial_coverage",
        "entitlement_circuit_tripped_vendors": ["finnhub"],
        "estimated_estimate_http_requests_avoided": 92,
    }
    (archive / "archive_index.jsonl").write_text(json.dumps(index_row) + "\n", encoding="utf-8")
    checkpoint = {
        "forward_only": True,
        "universe": {
            "ticker_count": 993,
            "eligible_ticker_count": 992,
            "source": {"pit_universe_label_clean": False},
        },
    }
    (archive / "collection_checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    ledger = {
        "schema_version": "free-data-forward-paper-ledger-v2",
        "as_of_date": "2026-07-17",
        "status": "forward_paper_tracking_active",
        "historical_backtest_acceptance_allowed": False,
        "live_trading_enabled": False,
        "production_promotion_allowed": False,
        "target_books_mutated": False,
        "valid_for_backtest": False,
        "valid_for_production": False,
        "fullrun_dispatched": False,
        "coverage": {"decision_date_count": 6, "observation_count": 348, "unique_ticker_count": 82},
        "capture_audit": {"source_observed_at_utc": "2026-07-18T03:49:19Z", "source_receipt_lag_days": 0},
        "review_readiness": {
            "status": "REVIEW_READY_PAPER_ONLY" if review_ready else "UNDERPOWERED",
            "review_ready": review_ready,
            "paper_only": True,
            "valid_for_historical_backtest_acceptance": False,
            "distinct_true_forward_ticker_count": observed_count,
            "resolved_outcome_count": resolved_count,
            "sample_checks": {
                "decision_week_blocks_21d": {"actual": blocks_21d},
                "decision_week_blocks_63d": {"actual": blocks_63d},
            },
        },
    }
    (ledger_dir / "summary.json").write_text(json.dumps(ledger), encoding="utf-8")
    return {
        "snapshot_dir": archive,
        "archive_index": archive / "archive_index.jsonl",
        "checkpoint": archive / "collection_checkpoint.json",
        "ledger": ledger_dir / "summary.json",
        "output": root / "outputs" / "gate",
    }


def execute(paths: dict[str, Path], **kwargs: object) -> dict[str, object]:
    return run(
        snapshot_dir=str(paths["snapshot_dir"]),
        archive_index=str(paths["archive_index"]),
        collection_checkpoint=str(paths["checkpoint"]),
        paper_ledger_summary=str(paths["ledger"]),
        output_dir=str(paths["output"]),
        **kwargs,
    )


def test_underpowered_forward_archive_stays_out_of_historical_research() -> None:
    with tempfile.TemporaryDirectory() as temp:
        paths = build_fixture(
            Path(temp),
            true_count=35,
            observed_count=22,
            resolved_count=0,
            blocks_21d=0,
            blocks_63d=0,
            review_ready=False,
        )
        payload = execute(paths)
        assert payload["status"] == STATUS_UNDERPOWERED, payload
        assert payload["archive"]["true_estimate_distinct_ticker_count"] == 35
        assert payload["archive"]["false_estimate_rows_with_numeric_placeholders"] == 1
        assert payload["archive"]["exact_timezone_available_from_ratio"] == 0.0
        assert payload["paper_gate"]["distinct_true_forward_ticker_count"] == 22
        assert payload["archive_to_ledger_true_ticker_utilization"] == 22 / 35
        assert payload["coverage_repeat_gate"]["coverage_increase_ticker_count"] == 22
        assert not payload["coverage_repeat_gate"]["threshold_met"]
        assert not payload["historical_source_screen_allowed"]
        assert not payload["same_arm_historical_retest_allowed"]
        assert payload["next_action"].startswith("continue_bounded")
        assert (paths["output"] / "summary.json").is_file()
        assert (paths["output"] / "snapshot_daily.csv").is_file()
        assert (paths["output"] / "report.md").is_file()


def test_paper_ready_never_becomes_historical_acceptance() -> None:
    with tempfile.TemporaryDirectory() as temp:
        paths = build_fixture(
            Path(temp),
            true_count=60,
            observed_count=50,
            resolved_count=200,
            blocks_21d=12,
            blocks_63d=8,
            review_ready=True,
            exact=True,
        )
        payload = execute(paths)
        assert payload["status"] == STATUS_READY, payload
        assert payload["forward_paper_review_ready"]
        assert not payload["historical_source_screen_allowed"]
        assert not payload["historical_generated_book_experiment_allowed"]
        assert not payload["historical_cagr_mdd_evidence_changed"]
        assert not payload["target_books_mutated"]


def test_hash_mismatch_and_future_availability_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as temp:
        paths = build_fixture(
            Path(temp),
            true_count=2,
            observed_count=2,
            resolved_count=0,
            blocks_21d=0,
            blocks_63d=0,
            review_ready=False,
        )
        snapshot = paths["snapshot_dir"] / "estimates_20260718.parquet"
        frame = pd.read_parquet(snapshot)
        frame.loc[0, "available_from"] = "2026-07-19T00:00:00Z"
        frame.to_parquet(snapshot, index=False)
        payload = execute(paths)
        assert payload["status"] == STATUS_BLOCKED, payload
        assert any("sha256_mismatch" in item for item in payload["contract_failures"])
        assert any("future_availability_rows" in item for item in payload["contract_failures"])


if __name__ == "__main__":
    test_underpowered_forward_archive_stays_out_of_historical_research()
    test_paper_ready_never_becomes_historical_acceptance()
    test_hash_mismatch_and_future_availability_fail_closed()
    print("run287_forward_estimate_evidence_gate_smoke: PASS")
