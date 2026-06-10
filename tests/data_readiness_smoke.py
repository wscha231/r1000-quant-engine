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
            {"start": "2019-01-01", "end": "2026-05-11", "ticker_count": 3, "failed_count": 0, "status": "completed"},
        )
        (free / "sec").mkdir(parents=True)
        (free / "sec" / "companyfacts.zip").write_bytes(b"zip")
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
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["AAA"], "weight": [1.0]}).to_csv(
            reports / "operating_main_target_book.csv", index=False
        )
        pd.DataFrame({"rebalance_date": ["2026-05-11"], "ticker": ["BBB"], "weight": [1.0]}).to_csv(
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
        assert payload["blockers"] == []


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
    test_data_readiness_reports_stale_operating_book()
    print("data_readiness_smoke: PASS")
