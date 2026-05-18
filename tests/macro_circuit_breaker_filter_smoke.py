#!/usr/bin/env python3
"""Smoke tests for the SPY 200-day MA macro circuit breaker filter."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_macro_circuit_breaker_filter import (  # noqa: E402
    apply_filter,
    compute_crisis_series,
    crisis_at,
    run,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_spy(cache_dir: Path, ticker: str, closes: list[float], start: str = "2023-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_crisis_state_machine_requires_confirm_days_to_flip() -> None:
    closes = [100 + i * 0.1 for i in range(220)]
    closes.extend([110.0, 90.0, 90.0, 90.0, 90.0, 90.0])
    closes.extend([130.0, 130.0, 130.0, 130.0])
    idx = pd.bdate_range(start="2023-01-02", periods=len(closes))
    spy = pd.DataFrame({"close": closes, "open": closes}, index=idx)
    crisis = compute_crisis_series(spy, ma_window=200, confirm_days=3)
    on_days = [d for d, c in crisis.items() if c]
    assert on_days, "expected at least one crisis day"
    off_days_after = crisis.iloc[226:].sum()
    assert off_days_after < 4, "crisis should clear after 3 days above MA"


def test_single_day_dip_does_not_trigger() -> None:
    closes = [100 + i * 0.1 for i in range(220)]
    closes.extend([90.0])
    closes.extend([130.0] * 10)
    idx = pd.bdate_range(start="2023-01-02", periods=len(closes))
    spy = pd.DataFrame({"close": closes, "open": closes}, index=idx)
    crisis = compute_crisis_series(spy, ma_window=200, confirm_days=3)
    assert not crisis.any(), "single-day dip must not flip the state machine"


def test_apply_filter_halves_only_crisis_dates() -> None:
    crisis = pd.Series(
        {
            pd.Timestamp("2023-01-01"): False,
            pd.Timestamp("2023-06-01"): True,
            pd.Timestamp("2023-09-01"): False,
        }
    )
    book = pd.DataFrame(
        [
            {"rebalance_date": "2023-03-31", "ticker": "AAA", "weight": 0.60},
            {"rebalance_date": "2023-06-30", "ticker": "AAA", "weight": 0.60},
            {"rebalance_date": "2023-06-30", "ticker": "CASH", "weight": 0.40},
            {"rebalance_date": "2023-10-31", "ticker": "AAA", "weight": 0.60},
        ]
    )
    out, decisions = apply_filter(book, crisis, halve_factor=0.5)
    out = out.set_index(["rebalance_date", "ticker"])
    assert float(out.loc[(pd.Timestamp("2023-03-31"), "AAA"), "weight"]) == 0.60
    assert float(out.loc[(pd.Timestamp("2023-06-30"), "AAA"), "weight"]) == 0.30
    assert float(out.loc[(pd.Timestamp("2023-06-30"), "CASH"), "weight"]) == 0.40
    assert float(out.loc[(pd.Timestamp("2023-10-31"), "AAA"), "weight"]) == 0.60


def test_crisis_at_returns_false_before_series_start() -> None:
    crisis = pd.Series({pd.Timestamp("2024-01-01"): True})
    assert crisis_at(crisis, pd.Timestamp("2023-01-01")) is False
    assert crisis_at(crisis, pd.Timestamp("2024-01-01")) is True
    assert crisis_at(crisis, pd.Timestamp("2024-06-01")) is True


def test_run_writes_csv_and_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        closes = [100 + i * 0.1 for i in range(220)]
        closes.extend([95.0, 90.0, 85.0, 80.0, 75.0])
        _write_spy(cache, "SPY", closes, start="2023-01-02")
        book = pd.DataFrame(
            [
                {"rebalance_date": "2023-06-30", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2023-09-29", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2023-12-29", "ticker": "AAA", "weight": 0.50},
            ]
        )
        input_book = root / "in.csv"
        book.to_csv(input_book, index=False)
        output_book = root / "out.csv"
        diag = root / "diag.json"
        payload = run(
            input_book=input_book,
            output_book=output_book,
            diagnostics_path=diag,
            price_cache=cache,
            ma_window=200,
            confirm_days=3,
            halve_factor=0.5,
        )
        assert payload["status"] == "completed", payload
        assert payload["schema_version"] == "macro-circuit-breaker-filter-v1"
        assert payload["spy_ticker_used"] == "SPY"
        assert output_book.exists()
        assert diag.exists()
        loaded = json.loads(diag.read_text(encoding="utf-8"))
        assert loaded["status"] == "completed"


def test_run_blocks_when_spy_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        book = pd.DataFrame(
            [{"rebalance_date": "2023-06-30", "ticker": "AAA", "weight": 0.50}]
        )
        input_book = root / "in.csv"
        book.to_csv(input_book, index=False)
        payload = run(
            input_book=input_book,
            output_book=root / "out.csv",
            diagnostics_path=root / "diag.json",
            price_cache=cache,
        )
        assert payload["status"] == "blocked"
        assert "SPY price series not found" in payload["reason"]


def main() -> int:
    test_crisis_state_machine_requires_confirm_days_to_flip()
    test_single_day_dip_does_not_trigger()
    test_apply_filter_halves_only_crisis_dates()
    test_crisis_at_returns_false_before_series_start()
    test_run_writes_csv_and_diagnostics()
    test_run_blocks_when_spy_missing()
    print("macro_circuit_breaker_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
