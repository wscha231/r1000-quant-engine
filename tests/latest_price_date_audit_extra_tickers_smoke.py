#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_latest_price_date_audit import run_audit  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, end: str = "2026-06-29") -> None:
    idx = pd.bdate_range(end=end, periods=5)
    df = pd.DataFrame(
        {
            "Open": [100.0] * len(idx),
            "Close": [100.0] * len(idx),
            "Adj Close": [100.0] * len(idx),
            "Volume": [1_000_000] * len(idx),
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_extra_ticker_is_audited() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        latest = root / "outputs"
        cache.mkdir()
        latest.mkdir()
        for ticker in ["SPY", "QQQ", "SH"]:
            _write_px(cache, ticker)

        payload = run_audit(
            price_cache=cache,
            latest_run=latest,
            audit_date=pd.Timestamp("2026-06-29"),
            stale_threshold=2,
            max_book_tickers=0,
            extra_tickers=["SH"],
        )

        assert payload["status"] == "ok"
        assert payload["extra_tickers"] == ["SH"]
        assert "SH" in payload["per_ticker"]
        assert payload["missing_tickers"] == []


def test_missing_extra_ticker_is_reported() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        latest = root / "outputs"
        cache.mkdir()
        latest.mkdir()
        for ticker in ["SPY", "QQQ"]:
            _write_px(cache, ticker)

        payload = run_audit(
            price_cache=cache,
            latest_run=latest,
            audit_date=pd.Timestamp("2026-06-29"),
            stale_threshold=2,
            max_book_tickers=0,
            extra_tickers=["SH"],
        )

        assert payload["status"] == "ok"
        assert payload["extra_tickers"] == ["SH"]
        assert "SH" not in payload["per_ticker"]
        assert payload["missing_tickers"] == ["SH"]


if __name__ == "__main__":
    test_extra_ticker_is_audited()
    test_missing_extra_ticker_is_reported()
    print("latest_price_date_audit_extra_tickers_smoke: PASS")
