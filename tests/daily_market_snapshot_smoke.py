#!/usr/bin/env python3
"""Smoke test for the daily market snapshot builder."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_price(cache: Path, ticker: str, prices: list[float]) -> None:
    dates = pd.date_range("2026-06-15", periods=len(prices), freq="B")
    frame = pd.DataFrame(
        {
            "Open": [p - 1.0 for p in prices],
            "High": [p + 2.0 for p in prices],
            "Low": [p - 2.0 for p in prices],
            "Close": prices,
            "Adj Close": [p * 0.99 for p in prices],
            "Volume": [1_000_000 + idx for idx, _ in enumerate(prices)],
        },
        index=dates,
    )
    cache.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache / px_cache_name(ticker))


def test_daily_market_snapshot_builder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        price_cache = root / "cache_prices"
        output_dir = root / "outputs" / "daily_market_snapshot"
        data_lake_dir = root / "data_pit" / "free" / "market_snapshot"
        info_cache = root / "data_raw" / "free" / "market_snapshot" / "yf_market_info_cache.csv"
        book = root / "outputs" / "portfolio_latest.csv"
        scored = root / "outputs" / "scored_latest.csv"

        write_price(price_cache, "AAA", [90.0, 100.0])
        write_price(price_cache, "BBB", [40.0, 50.0])
        write_price(price_cache, "SPY", [500.0, 510.0])
        book.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"ticker": ["AAA", "BBB", "CASH"], "weight": [0.5, 0.5, 0.0]}).to_csv(book, index=False)
        pd.DataFrame({"ticker": ["CCC"], "score_total": [99.0]}).to_csv(scored, index=False)
        info_cache.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "shares_outstanding": 10_000_000,
                    "implied_shares_outstanding": "",
                    "yfinance_market_cap": "",
                    "current_price": 100.0,
                    "currency": "USD",
                    "financial_currency": "USD",
                    "info_updated_at_utc": now,
                    "info_source": "fixture",
                },
                {
                    "ticker": "BBB",
                    "shares_outstanding": "",
                    "implied_shares_outstanding": 20_000_000,
                    "yfinance_market_cap": "",
                    "current_price": 50.0,
                    "currency": "USD",
                    "financial_currency": "USD",
                    "info_updated_at_utc": now,
                    "info_source": "fixture",
                },
            ]
        ).to_csv(info_cache, index=False)
        protected = [book, scored, info_cache]
        before = {path: file_hash(path) for path in protected}

        cmd = [
            sys.executable,
            str(ROOT / "tools" / "build_daily_market_snapshot.py"),
            "--price-cache",
            str(price_cache),
            "--book",
            str(book),
            "--scored",
            str(scored),
            "--max-scored",
            "1",
            "--required-tickers",
            "SPY",
            "--output-dir",
            str(output_dir),
            "--data-lake-dir",
            str(data_lake_dir),
            "--info-cache",
            str(info_cache),
            "--no-fetch-live-info",
            "--asof-date",
            "2026-06-17",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert {path: file_hash(path) for path in protected} == before

        snapshot = pd.read_csv(output_dir / "market_snapshot.csv")
        summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        aaa = snapshot[snapshot["ticker"].eq("AAA")].iloc[0]
        bbb = snapshot[snapshot["ticker"].eq("BBB")].iloc[0]
        spy = snapshot[snapshot["ticker"].eq("SPY")].iloc[0]
        ccc = snapshot[snapshot["ticker"].eq("CCC")].iloc[0]

        assert float(aaa["market_cap_close"]) == 1_000_000_000.0
        assert aaa["market_cap_source"] == "close_x_shares_outstanding"
        assert float(bbb["market_cap_close"]) == 1_000_000_000.0
        assert bbb["market_cap_source"] == "close_x_implied_shares_outstanding"
        assert bool(spy["selection_usable"]) is True
        assert bool(ccc["price_available"]) is False
        assert summary["schema_version"] == "daily-market-snapshot-v1"
        assert summary["production_mutation_allowed"] is False
        assert summary["live_trading_enabled"] is False
        assert summary["price_available_count"] == 3
        assert summary["market_cap_available_count"] == 2
        assert (data_lake_dir / "latest_market_snapshot.csv").exists()
        assert (data_lake_dir / "latest_manifest.json").exists()


def test_historical_asof_excludes_future_rows_and_strict_mode_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        price_cache = root / "cache_prices"
        price_cache.mkdir(parents=True)
        book = root / "book.csv"
        info_cache = root / "info.csv"
        pd.DataFrame({"ticker": ["AAA"]}).to_csv(book, index=False)
        pd.DataFrame(columns=["ticker"]).to_csv(info_cache, index=False)
        pd.DataFrame(
            {
                "Open": [99.0, 998.0],
                "High": [101.0, 1000.0],
                "Low": [98.0, 997.0],
                "Close": [100.0, 999.0],
                "Adj Close": [100.0, 999.0],
                "Volume": [1_000_000.0, 1_000_000.0],
            },
            index=pd.to_datetime(["2026-06-17", "2026-06-18"]),
        ).to_parquet(price_cache / px_cache_name("AAA"))

        def command(output: Path) -> list[str]:
            return [
                sys.executable,
                str(ROOT / "tools" / "build_daily_market_snapshot.py"),
                "--price-cache",
                str(price_cache),
                "--book",
                str(book),
                "--scored",
                str(root / "missing_scored.csv"),
                "--max-scored",
                "0",
                "--required-tickers",
                "AAA",
                "--output-dir",
                str(output),
                "--data-lake-dir",
                str(output / "data_lake"),
                "--info-cache",
                str(info_cache),
                "--no-fetch-live-info",
                "--asof-date",
                "2026-06-17",
                "--require-exact-asof-close",
            ]

        exact_output = root / "exact"
        result = subprocess.run(
            command(exact_output), cwd=ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
        snapshot = pd.read_csv(exact_output / "market_snapshot.csv")
        summary = json.loads(
            (exact_output / "summary.json").read_text(encoding="utf-8")
        )
        assert snapshot.loc[0, "latest_price_date"] == "2026-06-17"
        assert float(snapshot.loc[0, "previous_close"]) == 100.0
        assert summary["exact_asof_close_required"] is True
        assert summary["exact_asof_close_count"] == 1
        assert summary["exact_asof_close_missing_tickers"] == []

        pd.DataFrame({"ticker": ["AAA", "BBB"]}).to_csv(book, index=False)
        pd.DataFrame(
            {
                "Open": [49.0],
                "High": [51.0],
                "Low": [48.0],
                "Close": [50.0],
                "Adj Close": [50.0],
                "Volume": [1_000_000.0],
            },
            index=pd.to_datetime(["2026-06-16"]),
        ).to_parquet(price_cache / px_cache_name("BBB"))
        blocked_output = root / "blocked"
        result = subprocess.run(
            command(blocked_output), cwd=ROOT, capture_output=True, text=True
        )
        assert result.returncode == 2, result.stdout + result.stderr
        summary = json.loads(
            (blocked_output / "summary.json").read_text(encoding="utf-8")
        )
        assert summary["status"] == "blocked"
        assert summary["exact_asof_close_missing_tickers"] == ["BBB"]


def main() -> int:
    test_daily_market_snapshot_builder()
    test_historical_asof_excludes_future_rows_and_strict_mode_fails_closed()
    print("daily_market_snapshot_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
