#!/usr/bin/env python3
"""Broker-ledger replay correctness smoke tests.

This suite captures broker-ledger replay invariants and documents two
known biases that should be eliminated in a future commit. The tests
currently assert the OBSERVED behavior so the suite stays green; when
the underlying bug is fixed, the assertion in the corresponding test
must be flipped per the TODO comment.

Known biases documented here:
    1. Delisted positions whose price data ends mid-replay get marked
       at cost basis in account_equity (run_broker_ledger_replay.py:313).
       This understates max drawdown for bankrupt names.
    2. When a single signal date fans out into per-ticker fill dates
       that span multiple trading days, every trade is stamped with
       min(fill_dt_by_ticker.values()) rather than each ticker's own
       actual_dt (run_broker_ledger_replay.py:552-611). Cash can be
       debited earlier than the trade could have happened in reality.

Correctness invariants verified here:
    3. With fill_mode="next_close" every trade's actual fill date is
       strictly after the signal date.
    4. Long-horizon (1-year synthetic) equity curves are continuous:
       no duplicate dates, monotonic non-decreasing order, no NaN
       equity values, no gap greater than 7 calendar days between
       trading-day marks.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import replay  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2026-01-02") -> None:
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


def test_delisted_position_currently_marks_at_cost_basis() -> None:
    """Documents bug B1: delisted-to-no-data stock is marked at cost basis.

    Setup: BUY ZOMBIE on 2026-01-02 at $100. Its price data ends 2026-01-08.
    On 2026-02-02 the target book drops ZOMBIE (target_exit). The replay
    cannot fill the sell because ZOMBIE has no price on or after 2026-02-03.
    The position therefore remains in state.shares, and account_equity
    falls back to cost_basis (line 313-315) for marking.

    TODO: when the cost-basis fallback is replaced by zero-marking or
    explicit zombie handling, flip the assertion to expect that
    ending_capital_usd is lower (because the dead position is no longer
    contributing $100/share to equity).
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        # ALIVE trades from Jan through March; ZOMBIE only trades Jan 2-8 then disappears.
        _write_px(cache, "ALIVE", [100.0] * 60, start="2026-01-02")
        _write_px(cache, "ZOMBIE", [100.0, 100.0, 100.0, 100.0, 100.0], start="2026-01-02")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "ALIVE", "weight": 0.50},
                {"rebalance_date": "2026-01-02", "ticker": "ZOMBIE", "weight": 0.50},
                {"rebalance_date": "2026-02-02", "ticker": "ALIVE", "weight": 1.00},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=0.0,
            integer_shares=True,
            max_fill_lag_days=7,
        )

        assert metrics["status"] == "completed", metrics
        positions = pd.read_csv(out / "positions_latest.csv")
        zombie_rows = positions[positions["ticker"].astype(str).eq("ZOMBIE")]
        # Bug B1 observed: ZOMBIE remains as a position, marked at cost_basis ($100).
        # If the fix lands, ZOMBIE should be cleared from positions OR market_value_usd ~= 0.
        assert not zombie_rows.empty, "ZOMBIE should still be present under current cost-basis fallback bug"
        market_value = float(zombie_rows.iloc[0]["market_value_usd"])
        assert market_value > 100.0, (
            "current bug: dead ZOMBIE marked at >=100 (cost basis). "
            "When fixed, expect market_value_usd to be ~0 or row to be absent."
        )


def test_multi_day_fill_uses_min_fill_date_for_stamp() -> None:
    """Documents bug B2: trade.date uses min(fill_dt_by_ticker) for all trades.

    Setup: AAA trades from 2026-01-02 onward; LATE only starts trading
    on 2026-01-12. Both are in the same signal date 2026-01-02. AAA's
    fill_dt = 2026-01-05 (within max_fill_lag_days). LATE's fill_dt
    would be 2026-01-12, which is outside max_fill_lag_days=7.

    With max_fill_lag_days=15 to let LATE fill, both AAA and LATE
    trades are stamped at min(fill_dt) = AAA's earlier fill date,
    even though LATE could not have executed on that day in reality.

    TODO: when run_broker_ledger_replay.py:582+611 is changed to
    stamp each trade with its own ticker's actual_dt, flip this test
    to assert that LATE's trade date == LATE's actual fill date
    (NOT min).
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0] * 20, start="2026-01-02")
        _write_px(cache, "LATE", [50.0] * 20, start="2026-01-12")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.50},
                {"rebalance_date": "2026-01-02", "ticker": "LATE", "weight": 0.40},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=0.0,
            integer_shares=True,
            max_fill_lag_days=15,
        )

        assert metrics["status"] == "completed", metrics
        trades = pd.read_csv(out / "trades.csv")
        late_trades = trades[trades["ticker"].astype(str).eq("LATE")]
        aaa_trades = trades[trades["ticker"].astype(str).eq("AAA")]
        if late_trades.empty:
            # If max_fill_lag_days was insufficient, LATE never filled — test trivially passes.
            assert not aaa_trades.empty
            return
        # Bug B2 observed: LATE trade date == AAA trade date (the minimum fill date).
        # When fixed, LATE trade date should be its own actual fill date (2026-01-12 or later).
        late_date = str(late_trades.iloc[0]["date"])
        aaa_date = str(aaa_trades.iloc[0]["date"])
        assert late_date == aaa_date, (
            "current bug: LATE trade stamped with AAA's earlier fill date. "
            "When fixed, late_date should be >= 2026-01-12."
        )


def test_no_look_ahead_in_next_close_fills() -> None:
    """Correctness invariant: with fill_mode='next_close', every trade
    fills strictly AFTER its signal date.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        # 30 business days of synthetic data, two tickers, two rebalances.
        closes = [100.0 + i * 0.5 for i in range(30)]
        _write_px(cache, "AAA", closes, start="2026-01-02")
        _write_px(cache, "BBB", closes, start="2026-01-02")
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.60},
                {"rebalance_date": "2026-01-02", "ticker": "BBB", "weight": 0.30},
                {"rebalance_date": "2026-01-15", "ticker": "AAA", "weight": 0.40},
                {"rebalance_date": "2026-01-15", "ticker": "BBB", "weight": 0.50},
            ]
        ).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=0.0,
            integer_shares=True,
        )

        assert metrics["status"] == "completed", metrics
        trades = pd.read_csv(out / "trades.csv")
        for _, row in trades.iterrows():
            signal_date = pd.Timestamp(str(row["signal_date"]))
            fill_date = pd.Timestamp(str(row["date"]))
            assert fill_date > signal_date, (
                f"look-ahead detected: trade for {row['ticker']} stamped {fill_date} "
                f"is not strictly after signal_date {signal_date}"
            )


def test_long_horizon_equity_curve_continuous() -> None:
    """Correctness invariant: 1-year synthetic replay produces a
    continuous equity curve — no duplicate dates, monotonic
    non-decreasing date order, no NaN equity, no calendar gap > 7 days
    between consecutive marks (trading-day spacing tolerance includes
    weekends only).
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        # 252 business days of monotonic synthetic prices, two tickers.
        closes = [100.0 + i * 0.10 for i in range(252)]
        _write_px(cache, "AAA", closes, start="2025-05-12")
        _write_px(cache, "BBB", [50.0 + i * 0.05 for i in range(252)], start="2025-05-12")
        target = root / "targets.csv"
        rebalance_dates = ["2025-05-12", "2025-08-01", "2025-11-03", "2026-02-02", "2026-04-30"]
        rows = []
        for dt in rebalance_dates:
            rows.append({"rebalance_date": dt, "ticker": "AAA", "weight": 0.55})
            rows.append({"rebalance_date": dt, "ticker": "BBB", "weight": 0.40})
        pd.DataFrame(rows).to_csv(target, index=False)

        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            starting_capital=10_000.0,
            fill_mode="next_close",
            cost_bps=25.0,
            integer_shares=True,
        )

        assert metrics["status"] == "completed", metrics
        curve = pd.read_csv(out / "equity_curve.csv")
        assert not curve.empty
        # No duplicate dates.
        assert curve["date"].is_unique, "duplicate dates in equity curve"
        # Monotonic non-decreasing.
        dates = pd.to_datetime(curve["date"])
        assert (dates.diff().dropna() > pd.Timedelta(0)).all(), "equity dates not strictly increasing"
        # No NaN equity values.
        assert curve["equity_usd"].notna().all(), "NaN values in equity_usd"
        # No calendar gap greater than 7 days (allows for long weekends and short holiday breaks).
        gaps = dates.diff().dropna()
        assert gaps.max() <= pd.Timedelta(days=7), f"equity curve has gap of {gaps.max()} between marks"
        # Equity is positive throughout.
        assert (curve["equity_usd"] > 0).all(), "non-positive equity observed"


def main() -> int:
    test_delisted_position_currently_marks_at_cost_basis()
    test_multi_day_fill_uses_min_fill_date_for_stamp()
    test_no_look_ahead_in_next_close_fills()
    test_long_horizon_equity_curve_continuous()
    print("broker_ledger_correctness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
