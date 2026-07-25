#!/usr/bin/env python3
"""Smoke checks for daily theme leadership tape."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_theme_leadership_tape import apply_state_confirmation, run  # noqa: E402
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
        _write_px(cache, "XOM", [100.0 - i * 0.04 for i in range(150)], [2_000_000] * 150)
        _write_px(cache, "CVX", [95.0 - i * 0.03 for i in range(150)], [2_000_000] * 150)
        _write_px(cache, "LLY", [100.0 + i * 0.02 for i in range(150)], [2_000_000] * 150)
        _write_px(cache, "UNH", [100.0 + i * 0.01 for i in range(150)], [2_000_000] * 150)
        _write_px(cache, "SPY", [100.0 + i * 0.01 for i in range(150)], [20_000_000] * 150)
        _write_px(cache, "QQQ", [100.0 + i * 0.015 for i in range(150)], [20_000_000] * 150)
        _write_px(cache, "DRAM", [20.0] * 145 + [22.0, 25.0, 29.0, 34.0, 40.0], [100_000] * 145 + [5_000_000] * 5)
        scored = root / "scored_latest.csv"
        pd.DataFrame(
            [
                {"ticker": "MU", "Name": "Micron Technology", "sector": "Technology", "industry": "Semiconductors", "mktcap": 100_000_000_000, "rs_acceleration_score": 1.0},
                {"ticker": "WDC", "Name": "Western Digital", "sector": "Technology", "industry": "Storage", "mktcap": 30_000_000_000, "rs_acceleration_score": 0.9},
                {"ticker": "SNDK", "Name": "Sandisk", "sector": "Technology", "industry": "Flash Memory", "mktcap": 20_000_000_000, "rs_acceleration_score": 0.8},
                {"ticker": "AAPL", "Name": "Apple", "sector": "Technology", "industry": "Consumer Electronics", "mktcap": 2_000_000_000_000, "rs_acceleration_score": 0.1},
                {"ticker": "XOM", "Name": "Exxon Mobil", "sector": "Energy", "industry": "Oil & Gas Integrated", "mktcap": 500_000_000_000},
                {"ticker": "CVX", "Name": "Chevron", "sector": "Energy", "industry": "Oil & Gas Integrated", "mktcap": 300_000_000_000},
                {"ticker": "LLY", "Name": "Eli Lilly", "sector": "Healthcare", "industry": "Drug Manufacturers", "mktcap": 700_000_000_000},
                {"ticker": "UNH", "Name": "UnitedHealth", "sector": "Healthcare", "industry": "Health Care Plans", "mktcap": 400_000_000_000},
            ]
        ).to_csv(scored, index=False)

        payload = run(
            scored,
            cache,
            out,
            min_mcap=1_000_000_000,
            min_dollar_vol=1_000_000,
            allow_network=False,
        )

        assert payload["status"] == "completed"
        assert payload["data_status"] == "READY_REPORT_ONLY"
        assert payload["top_theme"] == "memory_semiconductors"
        assert payload["top_sector"] == "Information Technology"
        theme = pd.read_csv(out / "theme_leadership.csv")
        sectors = pd.read_csv(out / "sector_leadership.csv")
        subsectors = pd.read_csv(out / "subsector_leadership.csv")
        ticker = pd.read_csv(out / "ticker_leadership.csv")
        watchlist = pd.read_csv(out / "leader_watchlist.csv")
        assert "memory_semiconductors" in set(theme["leadership_theme"])
        assert {"Information Technology", "Energy", "Health Care"}.issubset(
            set(sectors["sector_normalized"])
        )
        assert "Semiconductors" in set(subsectors["subindustry_normalized"])
        assert {"MU", "WDC", "SNDK"}.issubset(set(ticker["ticker"]))
        assert ticker["price_date"].nunique() == 1
        assert ticker.loc[ticker["ticker"].eq("MU"), "rs_spy_21d"].iloc[0] > 0
        assert {"LEADER_REVIEW", "EMERGING_REVIEW"}.intersection(
            set(watchlist["suggested_action"])
        )
        assert not watchlist["production_activation_allowed"].astype(bool).any()
        etf = pd.read_csv(out / "etf_attention.csv")
        lookthrough = pd.read_csv(out / "etf_lookthrough_watchlist.csv")
        assert "DRAM" in set(etf["etf"])
        assert {"MU", "WDC", "SNDK"}.intersection(set(lookthrough["ticker"]))
        assert (out / "report.md").exists()


def test_theme_leadership_truncates_future_rows_and_confirmation_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "theme_tape"
        cache.mkdir()
        steady = [100.0 + i * 0.1 for i in range(150)]
        _write_px(cache, "SPY", steady, [10_000_000] * 150)
        _write_px(cache, "QQQ", steady, [10_000_000] * 150)
        _write_px(cache, "AAA", steady + [10_000.0], [2_000_000] * 151)
        _write_px(cache, "BBB", steady[:-1], [2_000_000] * 149)
        scored = root / "scored_latest.csv"
        pd.DataFrame(
            [
                {"ticker": "AAA", "sector": "Industrials", "industry": "Machinery", "mktcap": 5_000_000_000},
                {"ticker": "BBB", "sector": "Industrials", "industry": "Machinery", "mktcap": 5_000_000_000},
            ]
        ).to_csv(scored, index=False)

        payload = run(
            scored,
            cache,
            out,
            min_mcap=1_000_000_000,
            min_dollar_vol=1_000_000,
            allow_network=False,
        )

        assert payload["status"] == "completed"
        ticker = pd.read_csv(out / "ticker_leadership.csv")
        aaa = ticker.loc[ticker["ticker"].eq("AAA")].iloc[0]
        bbb = ticker.loc[ticker["ticker"].eq("BBB")].iloc[0]
        assert aaa["ret_1d"] < 0.01
        assert aaa["price_date"] == payload["common_close_date"]
        assert bbb["price_status"] == "stale_close"
        assert not bool(bbb["exact_close"])

        current = pd.DataFrame(
            [
                {
                    "as_of_date": "2026-07-24",
                    "level": "sector",
                    "group_key": "Industrials",
                    "group_label": "Industrials",
                    "raw_leadership_state": "EMERGING",
                    "leadership_state": "EMERGING",
                    "leadership_rank": 1,
                    "top_tickers": "AAA",
                    "research_only": True,
                    "production_activation_allowed": False,
                }
            ]
        )
        first, _ = apply_state_confirmation(
            current,
            pd.DataFrame(),
            as_of=pd.Timestamp("2026-07-24"),
        )
        same_day, _ = apply_state_confirmation(
            current,
            first,
            as_of=pd.Timestamp("2026-07-24"),
        )
        next_day = current.copy()
        next_day["as_of_date"] = "2026-07-27"
        confirmed, _ = apply_state_confirmation(
            next_day,
            same_day,
            as_of=pd.Timestamp("2026-07-27"),
        )
        assert first.iloc[0]["leadership_state"] == "EMERGING_WATCH"
        assert same_day.iloc[0]["state_confirmation_count"] == 1
        assert confirmed.iloc[0]["leadership_state"] == "EMERGING_CONFIRMED"
        assert confirmed.iloc[0]["state_confirmation_count"] == 2


def test_after_close_refreshes_prices_before_leadership_scan() -> None:
    workflow = (ROOT / ".github" / "workflows" / "after_close_daily.yml").read_text(
        encoding="utf-8"
    )
    refresh = workflow.index("Refresh balanced leadership price cache")
    scan = workflow.index("Hierarchical sector and stock leadership tape")
    assert refresh < scan
    assert "--max-scored-per-sector 12" in workflow
    assert "--no-network" in workflow


def main() -> int:
    test_theme_leadership_detects_memory_cluster()
    test_theme_leadership_truncates_future_rows_and_confirmation_is_idempotent()
    test_after_close_refreshes_prices_before_leadership_scan()
    print("theme_leadership_tape_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
