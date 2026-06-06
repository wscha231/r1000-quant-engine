#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_data_readiness import build_payload  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_pit_evidence_store(root: Path) -> None:
    sec = root / "data_pit" / "sec"
    etf = root / "data_pit" / "etf_holdings"
    sec.mkdir(parents=True, exist_ok=True)
    etf.mkdir(parents=True, exist_ok=True)
    (sec / "form4_transactions.parquet").write_bytes(b"pit")
    (sec / "institutional_13f_holdings.parquet").write_bytes(b"pit")
    (etf / "etf_holdings.parquet").write_bytes(b"pit")


def test_data_readiness_detects_fresh_operating_books_and_snapshots() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        free = root / "data_raw" / "free"
        pit = root / "data_pit" / "free"
        manifests = root / "manifests" / "free_data"
        cache.mkdir(parents=True)
        reports.mkdir(parents=True)
        for idx in range(3):
            (cache / f"{idx}.parquet").write_bytes(b"placeholder")
        write_json(
            free / "prices" / "replay_price_cache_manifest.json",
            {"start": "2019-01-01", "end": "2026-05-15", "ticker_count": 3, "failed_count": 0, "status": "completed"},
        )
        (free / "sec").mkdir(parents=True)
        (free / "sec" / "companyfacts.zip").write_bytes(b"zip")
        (root / "data_pit" / "macro").mkdir(parents=True)
        (root / "data_pit" / "macro" / "long_crisis_daily_features.parquet").write_bytes(b"macro")
        write_pit_evidence_store(root)
        write_json(pit / "coverage_audit.json", {"readiness": "ready_for_proxy_replay", "pit_label": "pit_proxy_universe", "known_gaps": []})
        write_json(manifests / "latest_manifest.json", {"status": "completed", "generated_at_utc": "2026-05-12T00:00:00Z"})
        pd.DataFrame({"ticker": ["AAA", "BBB"], "feature_date": ["2026-05-11", "2026-05-11"], "score": [1, 2]}).to_csv(
            latest / "scored_latest.csv", index=False
        )
        pd.DataFrame({"ticker": ["AAA"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame({"ticker": ["BBB"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(
            latest / "concentrated_portfolio_latest.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["AAA"], "weight": [1.0]}).to_csv(
            reports / "main_monthly_weights.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["BBB"], "weight": [1.0]}).to_csv(
            reports / "concentrated_strategy_holdings.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["AAA"], "weight": [1.0], "smart_money_score": [0.0]}).to_csv(
            reports / "operating_main_target_book.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["BBB"], "weight": [1.0], "smart_money_score": [0.0]}).to_csv(
            reports / "operating_concentrated_target_book.csv", index=False
        )
        write_json(latest / "target_snapshots" / "latest_manifest.json", {"snapshot_date": "2026-05-11"})

        args = Namespace(
            latest_run=str(latest),
            price_cache=str(cache),
            free_data_root=str(free),
            coverage=str(pit / "coverage_audit.json"),
            manifest=str(manifests / "latest_manifest.json"),
            output_dir=str(root / "audit"),
            max_stale_days=999,
            min_price_files=3,
            min_scored_rows=2,
            strict=False,
        )
        payload = build_payload(args)
        assert payload["status"] == "ready"
        assert payload["ready_for_skip_collector_replay"] is True
        assert payload["ready_for_policy_replay"] is True
        assert payload["blockers"] == []


def test_data_readiness_reports_feature_source_coverage_and_pit_dates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        free = root / "data_raw" / "free"
        pit = root / "data_pit" / "free"
        manifests = root / "manifests" / "free_data"
        cache.mkdir(parents=True)
        reports.mkdir(parents=True)
        for idx in range(3):
            (cache / f"{idx}.parquet").write_bytes(b"placeholder")
        write_json(
            free / "prices" / "replay_price_cache_manifest.json",
            {"start": "2019-01-01", "end": "2026-05-31", "ticker_count": 3, "failed_count": 0, "status": "completed"},
        )
        (free / "sec").mkdir(parents=True)
        (free / "sec" / "companyfacts.zip").write_bytes(b"zip")
        (root / "data_pit" / "macro").mkdir(parents=True)
        (root / "data_pit" / "macro" / "long_crisis_daily_features.parquet").write_bytes(b"macro")
        write_pit_evidence_store(root)
        write_json(pit / "coverage_audit.json", {"readiness": "ready_for_proxy_replay", "pit_label": "pit_proxy_universe", "known_gaps": []})
        write_json(manifests / "latest_manifest.json", {"status": "completed", "generated_at_utc": "2026-05-31T00:00:00Z"})
        pd.DataFrame({"ticker": ["AAA", "BBB"], "feature_date": ["2026-05-31", "2026-05-31"], "score": [1, 2]}).to_csv(
            latest / "scored_latest.csv", index=False
        )
        pd.DataFrame({"ticker": ["AAA"], "weight": [1.0], "feature_date": ["2026-05-31"]}).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame({"ticker": ["BBB"], "weight": [1.0], "feature_date": ["2026-05-31"]}).to_csv(
            latest / "concentrated_portfolio_latest.csv", index=False
        )
        target_rows = [
            {
                "rebalance_date": "2026-05-31",
                "ticker": "AAA",
                "weight": 0.6,
                "ticker_ret_1m": 0.08,
                "rs_benchmark_1m": 0.03,
                "spy_1m_return": 0.02,
                "qqq_1m_return": 0.01,
                "market_style_regime_label": "balanced",
                "leadership_theme": "ai_compute",
                "smart_money_score": 0.4,
                "selection_confirmation_score": 0.7,
                "target_n": 15,
                "action": "NEW",
                "latest_available_from": "2026-06-02",
            },
            {
                "rebalance_date": "2026-05-31",
                "ticker": "BBB",
                "weight": 0.4,
                "ticker_ret_1m": 0.02,
                "rs_benchmark_1m": -0.01,
                "spy_1m_return": 0.02,
                "qqq_1m_return": 0.01,
                "market_style_regime_label": "balanced",
                "leadership_theme": "industrial_rebuild",
                "smart_money_score": 0.1,
                "selection_confirmation_score": 0.4,
                "target_n": 15,
                "action": "HOLD",
                "latest_available_from": "2026-05-30",
            },
        ]
        pd.DataFrame(target_rows).to_csv(reports / "operating_main_target_book.csv", index=False)
        pd.DataFrame([{**row, "target_n": 5} for row in target_rows]).to_csv(reports / "operating_concentrated_target_book.csv", index=False)
        write_json(latest / "target_snapshots" / "latest_manifest.json", {"snapshot_date": "2026-05-31"})

        args = Namespace(
            latest_run=str(latest),
            price_cache=str(cache),
            free_data_root=str(free),
            coverage=str(pit / "coverage_audit.json"),
            manifest=str(manifests / "latest_manifest.json"),
            output_dir=str(root / "audit"),
            max_stale_days=999,
            min_price_files=3,
            min_scored_rows=2,
            strict=False,
        )
        payload = build_payload(args)
        coverage = payload["feature_source_coverage"]
        main = coverage["books"]["main"]
        assert main["categories"]["price_momentum"]["present_count"] >= 2
        assert main["categories"]["macro_regime"]["present_count"] >= 3
        assert main["categories"]["theme_leadership"]["present_columns"] == ["leadership_theme"]
        assert coverage["overall"]["pit_future_available_from_rows"] == 2
        assert main["pit_available_from_check"]["rows_with_any_future_available_from"] == 1
        assert any("available_from after rebalance_date" in item for item in payload["warnings"])


def test_data_readiness_caps_target_freshness_to_observable_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        free = root / "data_raw" / "free"
        pit = root / "data_pit" / "free"
        manifests = root / "manifests" / "free_data"
        cache.mkdir(parents=True)
        reports.mkdir(parents=True)
        for idx in range(3):
            (cache / f"{idx}.parquet").write_bytes(b"placeholder")
        write_json(
            free / "prices" / "replay_price_cache_manifest.json",
            {"start": "2019-01-01", "end": "2026-05-15", "ticker_count": 3, "failed_count": 0, "status": "completed"},
        )
        (free / "sec").mkdir(parents=True)
        (free / "sec" / "companyfacts.zip").write_bytes(b"zip")
        (root / "data_pit" / "macro").mkdir(parents=True)
        (root / "data_pit" / "macro" / "long_crisis_daily_features.parquet").write_bytes(b"macro")
        write_pit_evidence_store(root)
        write_json(pit / "coverage_audit.json", {"readiness": "ready_for_proxy_replay", "pit_label": "pit_proxy_universe", "known_gaps": []})
        write_json(manifests / "latest_manifest.json", {"status": "completed", "generated_at_utc": "2026-05-12T00:00:00Z"})
        pd.DataFrame({"ticker": ["AAA", "BBB"], "feature_date": ["2026-05-12", "2026-05-12"], "score": [1, 2]}).to_csv(
            latest / "scored_latest.csv", index=False
        )
        pd.DataFrame({"ticker": ["AAA"], "weight": [1.0], "feature_date": ["2026-05-12"]}).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame({"ticker": ["BBB"], "weight": [1.0], "feature_date": ["2026-05-12"]}).to_csv(
            latest / "concentrated_portfolio_latest.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["AAA"], "weight": [1.0], "smart_money_score": [0.0]}).to_csv(
            reports / "operating_main_target_book.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["BBB"], "weight": [1.0], "smart_money_score": [0.0]}).to_csv(
            reports / "operating_concentrated_target_book.csv", index=False
        )
        write_json(
            reports / "operating_target_books_summary.json",
            {
                "books": [
                    {"portfolio": "main", "latest_price_close_date": "2026-05-11", "output_max_rebalance_date": "2026-05-11"},
                    {"portfolio": "concentrated", "latest_price_close_date": "2026-05-11", "output_max_rebalance_date": "2026-05-11"},
                ]
            },
        )
        write_json(latest / "target_snapshots" / "latest_manifest.json", {"snapshot_date": "2026-05-11"})

        args = Namespace(
            latest_run=str(latest),
            price_cache=str(cache),
            free_data_root=str(free),
            coverage=str(pit / "coverage_audit.json"),
            manifest=str(manifests / "latest_manifest.json"),
            output_dir=str(root / "audit"),
            max_stale_days=999,
            min_price_files=3,
            min_scored_rows=2,
            strict=False,
        )
        payload = build_payload(args)
        assert payload["latest_target_date"] == "2026-05-12"
        assert payload["latest_observable_close_date"] == "2026-05-11"
        assert payload["effective_latest_target_date"] == "2026-05-11"
        assert payload["ready_for_fullrun"] is True
        assert payload["ready_for_policy_replay"] is True
        assert payload["blockers"] == []
        assert any("freshness gate uses observable close" in item for item in payload["warnings"])


def test_data_readiness_allows_policy_replay_with_pit_stores_without_companyfacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        cache = root / "cache_prices"
        free = root / "data_raw" / "free"
        pit = root / "data_pit"
        manifests = root / "manifests" / "free_data"
        cache.mkdir(parents=True)
        reports.mkdir(parents=True)
        for idx in range(3):
            (cache / f"{idx}.parquet").write_bytes(b"placeholder")
        write_json(
            free / "prices" / "replay_price_cache_manifest.json",
            {"start": "2019-01-01", "end": "2026-05-11", "ticker_count": 3, "failed_count": 0, "status": "completed"},
        )
        (pit / "sec").mkdir(parents=True)
        (pit / "sec" / "form4_transactions.parquet").write_bytes(b"pit")
        (pit / "sec" / "institutional_13f_holdings.parquet").write_bytes(b"pit")
        (pit / "macro").mkdir(parents=True)
        (pit / "macro" / "long_crisis_daily_features.parquet").write_bytes(b"macro")
        write_pit_evidence_store(root)
        write_json(root / "data_pit" / "free" / "coverage_audit.json", {"readiness": "ready_for_proxy_replay", "known_gaps": []})
        write_json(manifests / "latest_manifest.json", {"status": "completed", "generated_at_utc": "2026-05-12T00:00:00Z"})
        pd.DataFrame({"ticker": ["AAA", "BBB"], "feature_date": ["2026-05-11", "2026-05-11"], "score": [1, 2]}).to_csv(
            latest / "scored_latest.csv", index=False
        )
        pd.DataFrame({"ticker": ["AAA"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame({"ticker": ["BBB"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(
            latest / "concentrated_portfolio_latest.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["AAA"], "weight": [1.0], "smart_money_score": [0.0]}).to_csv(
            reports / "operating_main_target_book.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["BBB"], "weight": [1.0], "smart_money_score": [0.0]}).to_csv(
            reports / "operating_concentrated_target_book.csv", index=False
        )
        write_json(latest / "target_snapshots" / "latest_manifest.json", {"snapshot_date": "2026-05-11"})

        args = Namespace(
            latest_run=str(latest),
            price_cache=str(cache),
            free_data_root=str(free),
            coverage=str(root / "data_pit" / "free" / "coverage_audit.json"),
            manifest=str(manifests / "latest_manifest.json"),
            output_dir=str(root / "audit"),
            max_stale_days=999,
            min_price_files=3,
            min_scored_rows=2,
            strict=False,
        )
        payload = build_payload(args)
        assert payload["ready_for_fullrun"] is False
        assert payload["ready_for_skip_collector_replay"] is False
        assert payload["ready_for_policy_replay"] is True
        assert payload["policy_replay_blockers"] == []
        assert any("companyfacts" in item for item in payload["blockers"])


def test_data_readiness_reports_stale_operating_book() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "outputs"
        reports = latest / "reports"
        reports.mkdir(parents=True)
        pd.DataFrame({"ticker": ["AAA", "BBB"], "feature_date": ["2026-05-11", "2026-05-11"]}).to_csv(latest / "scored_latest.csv", index=False)
        pd.DataFrame({"ticker": ["AAA"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(latest / "portfolio_latest.csv", index=False)
        pd.DataFrame({"ticker": ["BBB"], "weight": [1.0], "feature_date": ["2026-05-11"]}).to_csv(
            latest / "concentrated_portfolio_latest.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-03-02"], "ticker": ["AAA"], "weight": [1.0]}).to_csv(
            reports / "operating_main_target_book.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-03-02"], "ticker": ["BBB"], "weight": [1.0]}).to_csv(
            reports / "operating_concentrated_target_book.csv", index=False
        )
        args = Namespace(
            latest_run=str(latest),
            price_cache=str(root / "missing_cache"),
            free_data_root=str(root / "missing_free"),
            coverage=str(root / "missing_coverage.json"),
            manifest=str(root / "missing_manifest.json"),
            output_dir=str(root / "audit"),
            max_stale_days=3,
            min_price_files=1,
            min_scored_rows=2,
            strict=False,
        )
        payload = build_payload(args)
        assert payload["status"] == "blocked"
        assert any("operating target book max date" in item for item in payload["blockers"])


if __name__ == "__main__":
    test_data_readiness_detects_fresh_operating_books_and_snapshots()
    test_data_readiness_reports_feature_source_coverage_and_pit_dates()
    test_data_readiness_caps_target_freshness_to_observable_close()
    test_data_readiness_allows_policy_replay_with_pit_stores_without_companyfacts()
    test_data_readiness_reports_stale_operating_book()
    print("data_readiness_smoke: PASS")
