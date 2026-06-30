#!/usr/bin/env python3
"""Smoke checks for free data lake bootstrap without network downloads."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_free_data_lake_bootstrap import run  # noqa: E402


def test_free_data_lake_bootstrap_dry_run_outputs_manifest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest = root / "latest"
        reports = latest / "reports"
        reports.mkdir(parents=True)

        pd.DataFrame(
            [
                {"ticker": "NVDA", "rebalance_date": "2026-03-31", "weight": 0.05},
                {"ticker": "MSFT", "rebalance_date": "2026-03-31", "weight": 0.04},
            ]
        ).to_csv(reports / "main_monthly_weights.csv", index=False)
        pd.DataFrame(
            [
                {"ticker": "NVDA", "rebalance_date": "2026-03-31", "weight": 0.45},
            ]
        ).to_csv(reports / "concentrated_strategy_holdings.csv", index=False)
        pd.DataFrame(
            [
                {"ticker": "NVDA", "score": 10.0},
                {"ticker": "MSFT", "score": 9.0},
            ]
        ).to_csv(latest / "scored_latest.csv", index=False)
        (latest / "backtest_metrics.json").write_text('{"cagr":0.2,"sharpe":1.0,"max_drawdown":-0.2}\n', encoding="utf-8")
        (latest / "concentrated_backtest_metrics.json").write_text('{"cagr":0.3,"sharpe":1.1,"max_drawdown":-0.3}\n', encoding="utf-8")

        args = argparse.Namespace(
            latest_run=str(latest),
            data_root=str(root),
            output_dir=str(root / "outputs" / "free_data_lake_bootstrap"),
            manifest_dir=str(root / "manifests" / "free_data"),
            price_cache=str(root / "cache_prices"),
            pit_label="pit_proxy_universe",
            sec_companyfacts=False,
            sec_max_age_days=7.0,
            skip_macro_snapshot=True,
            price_mode="dry_run",
            price_start="2020-01-01",
            max_price_tickers=10,
            max_scored=5,
            batch_size=2,
            required_downloads=False,
        )
        payload = run(args)
        assert payload["coverage"]["pit_label"] == "pit_proxy_universe"
        assert payload["coverage"]["sources"]["universe"]["status"] == "available"
        assert payload["manifest"]["requested"]["required_benchmark_price_tickers"] == ["SPY", "QQQ"]
        assert (root / "manifests" / "free_data" / "latest_manifest.json").exists()
        assert (root / "data_pit" / "free" / "coverage_audit.json").exists()
        price_manifest = root / "data_raw" / "free" / "prices" / "replay_price_cache_manifest.json"
        assert price_manifest.exists()
        price_payload = json.loads(price_manifest.read_text(encoding="utf-8"))
        assert price_payload["status"] == "dry_run"
        assert price_payload["required_tickers"] == ["QQQ", "SPY"]
        assert price_payload["required_ticker_count"] == 2


def main() -> int:
    test_free_data_lake_bootstrap_dry_run_outputs_manifest()
    print("free data lake bootstrap smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
