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


def main() -> int:
    test_preflight_blocks_latest_only_and_default_static_filter()
    test_preflight_accepts_historical_disabled_filter()
    test_preflight_blocks_incomplete_price_cache()
    print("replay_integrity_preflight_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
