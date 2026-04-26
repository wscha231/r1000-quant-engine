"""Alpaca historical bar data fetcher for Aggressive engine.

Provides daily OHLCV data for technical signal computation.

Usage:
    from aggressive.data_alpaca import fetch_daily_bars, fetch_latest_bars
    df = fetch_daily_bars("NVDA", days=260)     # ~1Y of daily bars
    bars = fetch_latest_bars(["NVDA", "AMD"], days=60)  # dict[str, DataFrame]

Caching:
    Bars are cached to aggressive/cache/bars/{TICKER}_{PERIOD}.parquet
    with a 24h freshness check. Call fetch_daily_bars(..., force_refresh=True)
    to bypass.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from aggressive.agg_config import get_alpaca_credentials, load_agg_config


_CACHE_TTL_HOURS = 12   # re-fetch if cache is > 12h old
_CACHE_SUBDIR = "bars"


def _cache_path(ticker: str, days: int) -> Path:
    cfg = load_agg_config()
    cache_dir = cfg.cache_dir / _CACHE_SUBDIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{ticker.upper()}_{days}d.parquet"


# Module-level "warned once" flags to suppress per-ticker spam when alpaca-py
# is missing or credentials are unset. Without these, fetching N tickers in a
# loop prints the same FAIL message N times.
_ONCE_FLAGS: dict[str, bool] = {}


def _cache_is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age_hours = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
    return age_hours < _CACHE_TTL_HOURS


def fetch_daily_bars(
    ticker: str,
    days: int = 260,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fetch daily OHLCV bars for a single ticker.

    Returns DataFrame with columns: open, high, low, close, volume, vwap, trade_count
    Indexed by UTC timestamp (tz-aware).

    Returns empty DataFrame if fetch fails.
    """
    cache = _cache_path(ticker, days)
    if not force_refresh and _cache_is_fresh(cache):
        try:
            return pd.read_parquet(cache)
        except Exception:
            pass  # fall through to refetch

    try:
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        if not _ONCE_FLAGS.get("import"):
            print("FAIL: alpaca-py not installed. Run: py -3 -m pip install alpaca-py")
            _ONCE_FLAGS["import"] = True
        return pd.DataFrame()

    try:
        key, secret = get_alpaca_credentials()
    except RuntimeError as exc:
        if not _ONCE_FLAGS.get("creds"):
            print(f"FAIL: {exc}")
            _ONCE_FLAGS["creds"] = True
        return pd.DataFrame()

    client = StockHistoricalDataClient(key, secret)
    # Add buffer for weekends/holidays (roughly 1.5x calendar days needed)
    lookback_cal_days = int(days * 1.5) + 10
    end = datetime.now(timezone.utc) - timedelta(minutes=16)   # Alpaca free-tier 15min lag
    start = end - timedelta(days=lookback_cal_days)

    req = StockBarsRequest(
        symbol_or_symbols=ticker.upper(),
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    try:
        bars = client.get_stock_bars(req)
    except Exception as exc:
        print(f"FAIL fetching {ticker}: {exc}")
        return pd.DataFrame()

    df = bars.df
    if df.empty:
        return df

    # Alpaca returns MultiIndex (symbol, timestamp); drop symbol level
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index(level=0, drop=True)

    df = df.tail(days).copy()

    # Cache
    try:
        df.to_parquet(cache)
    except Exception as exc:
        print(f"WARN: could not cache {ticker}: {exc}")

    return df


def fetch_latest_bars(
    tickers: list[str],
    days: int = 60,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Batch fetch. Returns dict[ticker, DataFrame]."""
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch_daily_bars(t, days=days, force_refresh=force_refresh)
        if not df.empty:
            out[t] = df
    return out


def fetch_spy_benchmark(days: int = 260) -> pd.DataFrame:
    """Fetch SPY daily bars for relative-strength comparisons."""
    return fetch_daily_bars("SPY", days=days)


if __name__ == "__main__":
    print("=" * 60)
    print("Alpaca Data Fetcher Smoke Test")
    print("=" * 60)

    df = fetch_daily_bars("NVDA", days=60, force_refresh=True)
    if df.empty:
        print("FAIL: empty result")
        sys.exit(1)

    print(f"NVDA bars fetched: {len(df)} rows")
    print(f"  date range: {df.index.min()} to {df.index.max()}")
    print(f"  latest close: ${df['close'].iloc[-1]:.2f}")
    print(f"  20d avg volume: {df['volume'].tail(20).mean():,.0f}")
    print()

    # Batch + SPY
    batch = fetch_latest_bars(["NVDA", "AMD", "AVGO"], days=60)
    print(f"Batch fetched: {len(batch)} tickers")
    for t, b in batch.items():
        print(f"  {t}: {len(b)} bars, latest close ${b['close'].iloc[-1]:.2f}")

    spy = fetch_spy_benchmark(days=60)
    print(f"\nSPY: {len(spy)} bars, latest close ${spy['close'].iloc[-1]:.2f}")
    print("\nPASS")
