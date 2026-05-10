#!/usr/bin/env python3
"""Smoke checks for daily theme leadership tape."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_theme_leadership_tape import run  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], volumes: list[int]) -> None:
    idx = pd.bdate_range(start="2026-01-02", periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": volumes,
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_theme_leadership_detects_memory_cluster() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "theme_tape"
        cache.mkdir()
        base = [30.0] * 145
        _write_px(cache, "MU", base + [34.0, 38.0, 44.0, 51.0, 60.0], [1_000_000] * 145 + [5_000_000] * 5)
        _write_px(cache, "WDC", base + [33.0, 37.0, 42.0, 47.0, 55.0], [1_000_000] * 145 + [4_000_000] * 5)
        _write_px(cache, "SNDK", base + [32.0, 35.0, 39.0, 44.0, 50.0], [1_000_000] * 145 + [4_000_000] * 5)
        _write_px(cache, "AAPL", [100.0 + i * 0.1 for i in range(150)], [2_000_000] * 150)
        _write_px(cache, "DRAM", [20.0] * 145 + [22.0, 25.0, 29.0, 34.0, 40.0], [100_000] * 145 + [5_000_000] * 5)
        scored = root / "scored_latest.csv"
        pd.DataFrame(
            [
                {"ticker": "MU", "Name": "Micron Technology", "sector": "Technology", "industry": "Semiconductors", "mktcap": 100_000_000_000, "rs_acceleration_score": 1.0},
                {"ticker": "WDC", "Name": "Western Digital", "sector": "Technology", "industry": "Storage", "mktcap": 30_000_000_000, "rs_acceleration_score": 0.9},
                {"ticker": "SNDK", "Name": "Sandisk", "sector": "Technology", "industry": "Flash Memory", "mktcap": 20_000_000_000, "rs_acceleration_score": 0.8},
                {"ticker": "AAPL", "Name": "Apple", "sector": "Technology", "industry": "Consumer Electronics", "mktcap": 2_000_000_000_000, "rs_acceleration_score": 0.1},
            ]
        ).to_csv(scored, index=False)

        payload = run(scored, cache, out, min_mcap=1_000_000_000, min_dollar_vol=1_000_000)

        assert payload["status"] == "completed"
        assert payload["top_theme"] == "memory_semiconductors"
        theme = pd.read_csv(out / "theme_leadership.csv")
        ticker = pd.read_csv(out / "ticker_leadership.csv")
        assert "memory_semiconductors" in set(theme["leadership_theme"])
        assert {"MU", "WDC", "SNDK"}.issubset(set(ticker["ticker"]))
        etf = pd.read_csv(out / "etf_attention.csv")
        lookthrough = pd.read_csv(out / "etf_lookthrough_watchlist.csv")
        assert "DRAM" in set(etf["etf"])
        assert {"MU", "WDC", "SNDK"}.intersection(set(lookthrough["ticker"]))
        assert (out / "report.md").exists()


def main() -> int:
    test_theme_leadership_detects_memory_cluster()
    print("theme_leadership_tape_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
