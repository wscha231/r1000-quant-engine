#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def test_required_ticker_reaches_price_cache_builder(tmp_path: Path) -> None:
    latest = tmp_path / "latest"
    reports = latest / "reports"
    reports.mkdir(parents=True)
    pd.DataFrame({"rebalance_date": ["2026-06-29"], "ticker": ["AAPL"], "weight": [1.0]}).to_csv(
        reports / "main_monthly_weights.csv", index=False
    )
    pd.DataFrame({"rebalance_date": ["2026-06-29"], "ticker": ["MSFT"], "weight": [1.0]}).to_csv(
        reports / "concentrated_strategy_holdings.csv", index=False
    )
    pd.DataFrame({"ticker": ["NVDA"], "score": [1.0]}).to_csv(latest / "scored_latest.csv", index=False)

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "run_free_data_lake_bootstrap.py"),
        "--latest-run",
        str(latest),
        "--data-root",
        str(tmp_path),
        "--output-dir",
        str(tmp_path / "outputs" / "free_data_lake_bootstrap"),
        "--manifest-dir",
        str(tmp_path / "manifests" / "free_data"),
        "--price-cache",
        str(tmp_path / "cache_prices"),
        "--price-mode",
        "dry_run",
        "--skip-macro-snapshot",
        "--max-price-tickers",
        "0",
        "--required-tickers",
        "SH",
    ]
    subprocess.run(cmd, cwd=ROOT, check=True, text=True, capture_output=True)
    manifest = json.loads((tmp_path / "cache_prices" / "replay_price_cache_manifest.json").read_text())
    assert set(manifest["required_tickers"]) >= {"SPY", "QQQ", "SH"}
    assert manifest["required_ticker_count"] >= 3


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_required_ticker_reaches_price_cache_builder(Path(tmp))
    print("free_data_lake_bootstrap_required_tickers_smoke: PASS")
