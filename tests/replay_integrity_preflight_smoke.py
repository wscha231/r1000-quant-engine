#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_replay_integrity_preflight import build_report  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def write_price(cache: Path, ticker: str) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2026-01-02", periods=5)
    pd.DataFrame({"Adj Close": [100, 101, 102, 103, 104], "Close": [100, 101, 102, 103, 104]}, index=dates).to_parquet(cache / px_cache_name(ticker))


def test_preflight_blocks_latest_only_and_default_static_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        latest.mkdir()
        pd.DataFrame({"ticker": ["A"], "score": [1.0]}).to_csv(latest / "scored_latest.csv", index=False)
        broker = root / "broker"
        broker.mkdir()
        (broker / "metrics.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "metric_mode": "broker_ledger_next_close",
                    "target_book_filter_source": "default_static",
                    "end_date": "2026-05-22",
                }
            ),
            encoding="utf-8",
        )
        payload = build_report(
            latest_run=latest,
            output_dir=root / "out",
            baseline_lock=None,
            candidate_book_arg=None,
            target_book=None,
            broker_output_dir=broker,
            metrics_json=broker / "metrics.json",
            price_cache=None,
            portfolio_kind="concentrated",
            artifact_id="test",
            asof_date="2026-05-27",
        )
        assert "latest_only_source" in payload["blockers"]
        assert "default_static_concentrated_filter" in payload["blockers"]
        assert "TIER2_CACHE_REQUIRED" in payload["blockers"]
        assert "NO_BASELINE_LOCK" in payload["blockers"]
        assert payload["valid_for_research"] is False
        assert (root / "out" / "preflight_replay_gate.json").exists()


def test_preflight_accepts_historical_disabled_filter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest" / "reports"
        latest.mkdir(parents=True)
        pd.DataFrame({"rebalance_date": ["2026-01-31", "2026-02-28", "2026-03-31"], "ticker": ["A", "A", "A"]}).to_csv(
            latest / "candidate_replay_book.csv",
            index=False,
        )
        broker = root / "broker"
        broker.mkdir()
        (broker / "metrics.json").write_text(
            json.dumps(
                {
                    "status": "completed",
                    "metric_mode": "broker_ledger_next_close",
                    "target_book_filter_source": "disabled_explicit",
                    "end_date": "2026-05-26",
                }
            ),
            encoding="utf-8",
        )
        payload = build_report(
            latest_run=root / "latest",
            output_dir=root / "out",
            baseline_lock=None,
            candidate_book_arg=None,
            target_book=None,
            broker_output_dir=broker,
            metrics_json=broker / "metrics.json",
            price_cache=None,
            portfolio_kind="concentrated",
            artifact_id="test",
            asof_date="2026-05-27",
        )
        assert "default_static_concentrated_filter" not in payload["blockers"]
        assert payload["concentrated_filter_disabled"] is True
        assert payload["execution_tier"] == "NO_PRICE_CACHE"
        assert "NO_BASELINE_LOCK" in payload["blockers"]


def test_preflight_validates_registered_concentrated_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest" / "reports"
        latest.mkdir(parents=True)
        pd.DataFrame(
            {
                "rebalance_date": ["2026-01-31", "2026-02-28"],
                "ticker": ["A", "A"],
            }
        ).to_csv(latest / "candidate_replay_book.csv", index=False)
        broker = root / "broker"
        broker.mkdir()
        metrics_path = broker / "metrics.json"

        base_metrics = {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "target_book_filter_source": "registered_static_contract",
            "end_date": "2026-05-26",
        }
        metrics_path.write_text(
            json.dumps(
                {
                    **base_metrics,
                    "target_book_filter": {
                        "target_stock_names": 3,
                        "weighting_mode": "score_power",
                        "active_rebalance_interval_months": 1,
                    },
                }
            ),
            encoding="utf-8",
        )
        accepted = build_report(
            latest_run=root / "latest",
            output_dir=root / "accepted",
            baseline_lock=None,
            candidate_book_arg=None,
            target_book=None,
            broker_output_dir=broker,
            metrics_json=metrics_path,
            price_cache=None,
            portfolio_kind="concentrated",
            artifact_id="registered-valid",
            asof_date="2026-05-27",
        )
        assert accepted["registered_concentrated_filter_valid"] is True
        assert "registered_concentrated_contract_mismatch" not in accepted["blockers"]

        metrics_path.write_text(
            json.dumps(
                {
                    **base_metrics,
                    "target_book_filter": {
                        "target_stock_names": 1,
                        "weighting_mode": "conviction_curve",
                        "active_rebalance_interval_months": 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        rejected = build_report(
            latest_run=root / "latest",
            output_dir=root / "rejected",
            baseline_lock=None,
            candidate_book_arg=None,
            target_book=None,
            broker_output_dir=broker,
            metrics_json=metrics_path,
            price_cache=None,
            portfolio_kind="concentrated",
            artifact_id="registered-invalid",
            asof_date="2026-05-27",
        )
        assert rejected["registered_concentrated_filter_valid"] is False
        assert "registered_concentrated_contract_mismatch" in rejected["blockers"]


def test_preflight_blocks_incomplete_price_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest" / "reports"
        latest.mkdir(parents=True)
        pd.DataFrame({"rebalance_date": ["2026-01-31", "2026-02-28", "2026-03-31"], "ticker": ["A", "A", "A"]}).to_csv(
            latest / "candidate_replay_book.csv",
            index=False,
        )
        target = root / "target.csv"
        pd.DataFrame({"rebalance_date": ["2026-03-31"], "ticker": ["MISSING"], "weight": [1.0], "target_n": [1]}).to_csv(target, index=False)
        broker = root / "broker"
        broker.mkdir()
        (broker / "metrics.json").write_text(
            json.dumps({"status": "completed", "metric_mode": "broker_ledger_next_close", "target_book_filter_source": "disabled_explicit", "end_date": "2026-05-26"}),
            encoding="utf-8",
        )
        cache = root / "cache_prices"
        cache.mkdir()
        payload = build_report(
            latest_run=root / "latest",
            output_dir=root / "out",
            baseline_lock=None,
            candidate_book_arg=None,
            target_book=target,
            broker_output_dir=broker,
            metrics_json=broker / "metrics.json",
            price_cache=cache,
            portfolio_kind="main",
            artifact_id="test",
            asof_date="2026-05-27",
        )
        assert "PRICE_CACHE_INCOMPLETE" in payload["blockers"]
        assert "BENCHMARK_PRICE_MISSING" in payload["blockers"]
        assert "MACRO_FEATURE_MISSING" in payload["blockers"]
        assert payload["execution_tier"] != "TIER2_FULL_CACHE"


def test_preflight_uses_readable_benchmark_prices_and_long_crisis_inputs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        pd.DataFrame({"rebalance_date": ["2026-01-31"], "ticker": ["AAA"]}).to_csv(reports / "candidate_replay_book.csv", index=False)
        target = root / "target.csv"
        pd.DataFrame({"rebalance_date": ["2026-01-31"], "ticker": ["AAA"], "weight": [1.0], "target_n": [1]}).to_csv(target, index=False)
        broker = root / "broker"
        broker.mkdir()
        (broker / "metrics.json").write_text(
            json.dumps({"status": "completed", "metric_mode": "broker_ledger_next_close", "end_date": "2026-01-31"}),
            encoding="utf-8",
        )
        cache = root / "cache_prices"
        for ticker in ["AAA", "SPY", "QQQ"]:
            write_price(cache, ticker)
        feature_path = latest / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        threshold_path = latest / "long_crisis_learning" / "best_thresholds.json"
        feature_path.parent.mkdir(parents=True)
        threshold_path.parent.mkdir(parents=True)
        pd.DataFrame({"date": pd.bdate_range("2026-01-02", periods=5), "crisis_score": [0.1] * 5}).to_parquet(feature_path)
        threshold_path.write_text(json.dumps({"governor_thresholds": {"low": 0.3, "mid": 0.5, "high": 0.75}}), encoding="utf-8")
        baseline = root / "baseline.json"
        baseline.write_text(json.dumps({"run_id": "test", "official_metric_mode": "broker_ledger_next_close"}), encoding="utf-8")
        payload = build_report(
            latest_run=latest,
            output_dir=root / "out",
            baseline_lock=baseline,
            candidate_book_arg=None,
            target_book=target,
            broker_output_dir=broker,
            metrics_json=broker / "metrics.json",
            price_cache=cache,
            portfolio_kind="main",
            artifact_id="test",
            asof_date="2026-01-31",
        )
        assert payload["spy_price_readable"] is True
        assert payload["qqq_price_readable"] is True
        assert payload["benchmark_coverage_ratio"] == 1.0
        assert payload["long_crisis_features_available"] is True
        assert payload["long_crisis_thresholds_available"] is True
        assert "BENCHMARK_PRICE_MISSING" not in payload["blockers"]
        assert "LONG_CRISIS_FEATURE_MISSING" not in payload["blockers"]


def main() -> int:
    test_preflight_blocks_latest_only_and_default_static_filter()
    test_preflight_accepts_historical_disabled_filter()
    test_preflight_validates_registered_concentrated_contract()
    test_preflight_blocks_incomplete_price_cache()
    test_preflight_uses_readable_benchmark_prices_and_long_crisis_inputs()
    print("replay_integrity_preflight_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
