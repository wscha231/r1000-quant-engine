#!/usr/bin/env python3
"""Broker-ledger replay correctness smoke tests.

Correctness invariants verified here:
    1. A transition with a missing liquidation fill fails closed before
       any account state or performance artifact is produced.
    2. A synchronous target transition that would fill on multiple dates
       fails closed before any account state is mutated.
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


def test_missing_liquidation_fill_fails_closed_before_state_mutation() -> None:
    """A missing target-exit fill must block the complete replay.

    Setup: BUY ZOMBIE on 2026-01-02 at $100. Its price data ends 2026-01-08.
    On 2026-02-02 the target book drops ZOMBIE (target_exit). The replay
    cannot fill the sell because ZOMBIE has no price on or after 2026-02-03,
    so the preflight must reject the replay without publishing performance.
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

        assert metrics["status"] == "blocked", metrics
        assert metrics["reason"] == "target_fill_coverage_incomplete"
        coverage = pd.read_csv(out / "target_fill_coverage.csv")
        exit_row = coverage[
            coverage["ticker"].eq("ZOMBIE")
            & coverage["transition_action"].eq("target_exit")
        ].iloc[0]
        assert exit_row["fillable"] in {False, 0, "False", "false"}
        assert exit_row["reason"] == "no_fill_within_lag"
        for artifact in (
            "trades.csv",
            "equity_curve.csv",
            "positions_latest.csv",
            "account_state_latest.json",
        ):
            assert not (out / artifact).exists()


def test_multi_day_transition_fails_closed_before_state_mutation() -> None:
    """A synchronous transition cannot use multiple observable fill dates.

    Setup: AAA trades from 2026-01-02 onward; LATE only starts trading
    on 2026-01-12. Both are in the same signal date 2026-01-02. AAA's
    fill_dt = 2026-01-05 (within max_fill_lag_days). LATE's fill_dt
    would be 2026-01-12, which is outside max_fill_lag_days=7.

    With max_fill_lag_days=15 both names are individually fillable, but their
    different actual dates make the synchronous portfolio transition invalid.
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

        assert metrics["status"] == "blocked", metrics
        assert metrics["reason"] == "target_fill_coverage_incomplete"
        assert metrics["target_fill_coverage"]["chronology_safe"] is False
        coverage = pd.read_csv(out / "target_fill_coverage.csv")
        first_signal = coverage[coverage["signal_date"].eq("2026-01-02")]
        assert set(first_signal["actual_fill_date"]) == {
            "2026-01-05",
            "2026-01-12",
        }
        assert not first_signal["chronology_safe"].astype(bool).all()
        assert not (out / "trades.csv").exists()
        assert not (out / "equity_curve.csv").exists()


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


def test_latest_operating_close_is_audited_as_pending_next_close() -> None:
    """An appended close-date decision cannot require an unobserved next bar."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(
            cache,
            "AAA",
            [100.0, 101.0, 102.0, 103.0, 104.0],
            start="2026-01-02",
        )
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "operating_latest_price_date": "",
                    "operating_appended": False,
                },
                {
                    "rebalance_date": "2026-01-08",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "operating_latest_price_date": "2026-01-08",
                    "operating_appended": True,
                },
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
        assert metrics["stock_evidence_end_date"] == "2026-01-08"
        assert (
            metrics["stock_evidence_end_source"]
            == "target_book_operating_latest_price_date"
        )
        summary = metrics["target_fill_coverage"]
        assert summary["required_transition_fill_count"] == 1
        assert summary["pending_transition_fill_count"] == 1
        assert summary["coverage_complete"] is True
        coverage = pd.read_csv(out / "target_fill_coverage.csv")
        latest = coverage.loc[coverage["signal_date"].eq("2026-01-08")].iloc[0]
        assert latest["required_for_replay"] in {False, 0, "False", "false"}
        assert latest["reason"] == "fill_after_evidence_end"
        assert pd.to_datetime(
            pd.read_csv(out / "equity_curve.csv")["date"]
        ).max() <= pd.Timestamp("2026-01-08")


def test_non_appended_current_operating_close_is_pending() -> None:
    """A builder-authorized current historical row also supplies the cutoff."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "broker"
        cache.mkdir()
        _write_px(
            cache,
            "AAA",
            [100.0, 101.0, 102.0, 103.0, 104.0],
            start="2026-01-02",
        )
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "operating_latest_price_date": "",
                    "operating_appended": False,
                    "operating_evidence_end_eligible": False,
                },
                {
                    "rebalance_date": "2026-01-08",
                    "ticker": "AAA",
                    "weight": 1.0,
                    "operating_latest_price_date": "2026-01-08",
                    "operating_appended": False,
                    "operating_evidence_end_eligible": True,
                },
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
        assert metrics["stock_evidence_end_date"] == "2026-01-08"
        assert (
            metrics["target_fill_coverage"]["pending_transition_fill_count"]
            == 1
        )


def test_weekend_evidence_cutoff_uses_next_nyse_session() -> None:
    """Friday next-close is pending through Sunday with or without Monday data."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2025-12-30",
                    "ticker": "AAA",
                    "weight": 1.0,
                },
                {
                    "rebalance_date": "2026-01-02",
                    "ticker": "AAA",
                    "weight": 1.0,
                },
            ]
        ).to_csv(target, index=False)
        summaries = []
        for label, include_monday in (
            ("without_monday", False),
            ("with_monday", True),
        ):
            cache = root / f"cache_{label}"
            out = root / f"broker_{label}"
            cache.mkdir()
            dates = [
                "2025-12-29",
                "2025-12-30",
                "2025-12-31",
                "2026-01-02",
            ]
            if include_monday:
                dates.append("2026-01-05")
            closes = [100.0 + index for index in range(len(dates))]
            pd.DataFrame(
                {
                    "Open": closes,
                    "Close": closes,
                    "Adj Close": closes,
                    "Volume": [1_000_000] * len(dates),
                },
                index=pd.to_datetime(dates),
            ).to_parquet(cache / px_cache_name("AAA"))

            metrics = replay(
                target_book=target,
                price_cache=cache,
                output_dir=out,
                portfolio_kind="main",
                starting_capital=10_000.0,
                fill_mode="next_close",
                cost_bps=0.0,
                integer_shares=True,
                evidence_end_date="2026-01-04",
            )
            assert metrics["status"] == "completed", metrics
            summaries.append(metrics["target_fill_coverage"])
            coverage = pd.read_csv(out / "target_fill_coverage.csv")
            friday = coverage.loc[
                coverage["signal_date"].eq("2026-01-02")
            ].iloc[0]
            assert friday["earliest_possible_fill_date"] == "2026-01-05"
            assert friday["required_for_replay"] in {
                False,
                0,
                "False",
                "false",
            }
            assert friday["reason"] == "fill_after_evidence_end"

        assert {
            (
                summary["required_transition_fill_count"],
                summary["pending_transition_fill_count"],
            )
            for summary in summaries
        } == {(1, 1)}


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
        rebalance_dates = [
            "2025-05-12",
            "2025-08-01",
            "2025-11-03",
            "2026-02-02",
            "2026-04-27",
        ]
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
    test_missing_liquidation_fill_fails_closed_before_state_mutation()
    test_multi_day_transition_fails_closed_before_state_mutation()
    test_no_look_ahead_in_next_close_fills()
    test_latest_operating_close_is_audited_as_pending_next_close()
    test_non_appended_current_operating_close_is_pending()
    test_weekend_evidence_cutoff_uses_next_nyse_session()
    test_long_horizon_equity_curve_continuous()
    print("broker_ledger_correctness_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
