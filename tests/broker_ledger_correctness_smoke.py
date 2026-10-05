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

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CashCarryConfig,
    REPLAY_GENERATED_ARTIFACTS,
    fill_price,
    replay,
)
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402
from tools import run_broker_ledger_replay as broker  # noqa: E402


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


class OpeningClockAdmissionTests(unittest.TestCase):
    """Native parquet/replay checks whose assertions remain active under -O."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.target = self.root / "targets.csv"
        self.dates = pd.to_datetime([
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
        ])
        pd.DataFrame([
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 1.0},
            {"rebalance_date": "2026-01-05", "ticker": "AAA", "weight": 0.5},
            {"rebalance_date": "2026-01-05", "ticker": "BBB", "weight": 0.5},
        ]).to_csv(self.target, index=False)

    def write_prices(self, *, later_close=100.0, open_price=100.0,
                     missing_open=False, missing_fill_open=False) -> None:
        for ticker in ("AAA", "BBB"):
            closes = [100., 100., later_close if ticker == "AAA" else 100., 100., 100.]
            frame = pd.DataFrame({"Close": closes, "Adj Close": closes}, index=self.dates)
            if not missing_open:
                frame["Open"] = open_price
                if missing_fill_open:
                    frame.loc[pd.Timestamp("2026-01-05"), "Open"] = float("nan")
            frame.to_parquet(self.cache / px_cache_name(ticker))

    def run_replay(self, name, *, fill_mode="next_open"):
        output = self.root / name
        result = replay(target_book=self.target, price_cache=self.cache,
            output_dir=output, portfolio_kind="main", starting_capital=10000.,
            fill_mode=fill_mode, cost_bps=0., integer_shares=True)
        return result, output

    def check_no_performance(self, result, output):
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["metric_mode"], "DO_NOT_USE")
        self.assertFalse(result["valid_for_production"])
        for field in ("cagr", "max_dd", "sharpe", "ending_capital_usd"):
            self.assertNotIn(field, result)
        for artifact in ("trades.csv", "equity_curve.csv", "positions_latest.csv",
                         "account_state_latest.json"):
            self.assertFalse((output / artifact).exists(), artifact)

    def test_strict_loader_keeps_missing_open_and_legacy_fallback_separate(self):
        self.write_prices(missing_open=True)
        strict = load_price_series(self.cache, "AAA", require_observed_open=True)
        legacy = load_price_series(self.cache, "AAA")
        self.assertTrue(strict["open"].isna().all())
        self.assertTrue(legacy["open"].equals(legacy["close"]))
        self.assertEqual(fill_price({"AAA": strict}, "AAA", self.dates[0], "next_open", 7),
                         (None, None))

    def test_strict_loader_uses_observed_open_and_rejects_nan_on_eligible_session(self):
        self.write_prices(open_price=72.)
        prices = load_price_series(self.cache, "AAA", require_observed_open=True)
        self.assertEqual(fill_price({"AAA": prices}, "AAA", self.dates[0], "next_open", 7),
                         (self.dates[1], 72.))
        self.write_prices(missing_fill_open=True)
        prices = load_price_series(self.cache, "AAA", require_observed_open=True)
        self.assertEqual(fill_price({"AAA": prices}, "AAA", self.dates[0], "next_open", 7),
                         (None, None))

    def test_missing_or_nan_open_blocks_native_replay(self):
        for name, options in (("missing", {"missing_open": True}),
                              ("nan", {"missing_fill_open": True})):
            with self.subTest(name=name):
                self.write_prices(**options)
                result, output = self.run_replay(name)
                self.check_no_performance(result, output)
                self.assertEqual(result["reason"], "target_fill_coverage_incomplete")

    def test_future_close_cannot_produce_opening_intents_without_a_contract(self):
        for close in (80., 140.):
            with self.subTest(close=close):
                self.write_prices(later_close=close)
                result, output = self.run_replay(str(close))
                self.check_no_performance(result, output)
                self.assertEqual(result["reason"], "next_open_precommitted_order_intent_unavailable")
                self.assertTrue(result["target_fill_coverage"]["coverage_complete"])

    def test_realized_gap_price_cannot_backdate_missing_order_intent(self):
        for open_price in (60., 160.):
            with self.subTest(open_price=open_price):
                self.write_prices(open_price=open_price)
                result, output = self.run_replay(str(open_price))
                self.check_no_performance(result, output)
                self.assertEqual(result["reason"], "next_open_precommitted_order_intent_unavailable")

    def test_next_close_reference_and_blocked_rerun_cleanup(self):
        self.write_prices()
        result, output = self.run_replay("reuse", fill_mode="next_close")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["metric_mode"], "broker_ledger_next_close")
        self.assertEqual(result["ending_capital_usd"], 10000.)
        trades = pd.read_csv(output / "trades.csv")
        self.assertEqual(list(zip(trades["ticker"], trades["side"], trades["quantity"])),
                         [("AAA", "BUY", 100.), ("AAA", "SELL", 50.), ("BBB", "BUY", 50.)])
        blocked, same_output = self.run_replay("reuse")
        self.check_no_performance(blocked, same_output)


class GeneratedOutputLifecycleTests(unittest.TestCase):
    """Reused output directories cannot retain evidence from an older replay."""

    # Audited replay exports, including conditional reserve/partial-resize files.
    # This oracle is independent of the cleanup registry under test.
    generated = {
        "equity_curve.csv", "trades.csv", "holdings_daily.csv",
        "holdings_weekly.csv", "cash_ledger.csv", "target_vs_actual_weights.csv",
        "partial_resize_decisions.csv", "positions_latest.csv",
        "account_state_latest.json", "metrics.json", "replay_report.md",
        "target_fill_coverage.csv", "reserve_reason_audit.json",
    }
    blocked_diagnostics = {"metrics.json", "replay_report.md", "target_fill_coverage.csv"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.out = self.root / "replay"
        self.target = self.root / "targets.csv"
        self.dates = pd.to_datetime([
            "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
        ])
        pd.DataFrame([
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": .5},
        ]).to_csv(self.target, index=False)
        self.network_guard = patch("socket.socket", side_effect=RuntimeError("offline fixture"))
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def write_prices(self, opens):
        frame = pd.DataFrame({"Close": [100.] * 4, "Adj Close": [100.] * 4},
                             index=self.dates)
        if opens is not None:
            frame["Open"] = opens
        frame.to_parquet(self.cache / px_cache_name("AAA"))

    def run_replay(self, **kwargs):
        options = dict(target_book=self.target, price_cache=self.cache,
                       output_dir=self.out, portfolio_kind="main",
                       starting_capital=10000., fill_mode="next_close", cost_bps=25.,
                       integer_shares=True, cash_carry_config=CashCarryConfig(mode="none"),
                       reserve_mode="BROKER_CASH_OR_MMF")
        options.update(kwargs)
        return replay(**options)

    def seed_completed_outputs(self):
        self.write_prices([100.] * 4)
        result = self.run_replay(partial_resize_two_signal_confirmation=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual({p.name for p in self.out.iterdir()}
                         - {"caller_receipt.json", "notes.md", "caller_archive"}, self.generated)
        old_bytes = {name: (self.out / name).read_bytes() for name in self.generated}
        self.assertTrue(old_bytes["reserve_reason_audit.json"])
        # Caller-owned files and nested files are outside the replay export set.
        (self.out / "caller_receipt.json").write_bytes(b'{"caller":"preserve"}')
        (self.out / "notes.md").write_bytes(b"caller notes\n")
        nested = self.out / "caller_archive"
        nested.mkdir(exist_ok=True)
        (nested / "reserve_reason_audit.json").write_bytes(b"unrelated nested audit")
        return old_bytes

    def check_preserved_caller_files(self):
        self.assertEqual((self.out / "caller_receipt.json").read_bytes(),
                         b'{"caller":"preserve"}')
        self.assertEqual((self.out / "notes.md").read_bytes(), b"caller notes\n")
        self.assertEqual((self.out / "caller_archive" / "reserve_reason_audit.json").read_bytes(),
                         b"unrelated nested audit")

    def check_blocked_cleanup(self, result, old_bytes, expected_diagnostics):
        self.assertEqual(result["status"], "blocked")
        for name in self.generated - expected_diagnostics:
            self.assertFalse((self.out / name).exists(), name)
        for name in expected_diagnostics:
            self.assertTrue((self.out / name).is_file(), name)
            self.assertNotEqual((self.out / name).read_bytes(), old_bytes[name], name)
        actual = {p.name for p in self.out.iterdir() if p.is_file()}
        self.assertEqual(actual, expected_diagnostics | {"caller_receipt.json", "notes.md"})
        self.check_preserved_caller_files()

    def test_cleanup_registry_covers_observed_completed_exports(self):
        self.seed_completed_outputs()
        self.assertEqual(len(REPLAY_GENERATED_ARTIFACTS), len(set(REPLAY_GENERATED_ARTIFACTS)))
        self.assertEqual(set(REPLAY_GENERATED_ARTIFACTS), self.generated)

    def test_opening_blocks_remove_all_prior_generated_evidence(self):
        cases = (
            ("valid_open", [100.] * 4, "next_open_precommitted_order_intent_unavailable"),
            ("missing_open", None, "target_fill_coverage_incomplete"),
            ("nan_open", [100., float("nan"), 100., 100.], "target_fill_coverage_incomplete"),
            ("zero_open", [100., 0., 100., 100.], "target_fill_coverage_incomplete"),
            ("negative_open", [100., -1., 100., 100.], "target_fill_coverage_incomplete"),
            ("infinite_open", [100., float("inf"), 100., 100.], "target_fill_coverage_incomplete"),
        )
        for name, opens, reason in cases:
            with self.subTest(case=name):
                old_bytes = self.seed_completed_outputs()
                self.write_prices(opens)
                result = self.run_replay(fill_mode="next_open")
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["metric_mode"], "DO_NOT_USE")
                self.assertFalse(result["valid_for_production"])
                for field in ("cagr", "max_dd", "sharpe", "ending_capital_usd"):
                    self.assertNotIn(field, result)
                self.check_blocked_cleanup(result, old_bytes, self.blocked_diagnostics)

    def test_precoverage_blocks_remove_all_prior_generated_evidence(self):
        original_target = self.target.read_bytes()
        cases = (
            ("empty_target", "target book is empty or invalid"),
            ("invalid_weight", "target weight sum exceeds maximum reasonable exposure"),
            ("missing_cash_rate", "cash_rate_series_unavailable"),
        )
        for name, expected_reason in cases:
            with self.subTest(case=name):
                self.target.write_bytes(original_target)
                old_bytes = self.seed_completed_outputs()
                options = {}
                if name == "empty_target":
                    pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(
                        self.target, index=False)
                elif name == "invalid_weight":
                    pd.DataFrame([{"rebalance_date": "2026-01-02", "ticker": "AAA",
                                   "weight": 2.}]).to_csv(self.target, index=False)
                else:
                    options = dict(reserve_mode="DGS3MO_CARRY", cash_carry_config=CashCarryConfig(
                        mode="risk_free_rate", rate_path=self.root / "missing_rate.csv"))
                result = self.run_replay(**options)
                self.assertEqual(result["reason"], expected_reason)
                self.check_blocked_cleanup(result, old_bytes, {"metrics.json"})

    def test_completed_default_rerun_drops_optional_prior_evidence(self):
        self.seed_completed_outputs()
        result = self.run_replay(reserve_mode=None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["metric_mode"], "broker_ledger_next_close")
        self.assertFalse((self.out / "reserve_reason_audit.json").exists())
        self.assertFalse((self.out / "partial_resize_decisions.csv").exists())
        self.assertEqual({p.name for p in self.out.iterdir() if p.is_file()},
                         (self.generated - {"reserve_reason_audit.json", "partial_resize_decisions.csv"})
                         | {"caller_receipt.json", "notes.md"})
        self.check_preserved_caller_files()


class CallerInputCollisionTests(unittest.TestCase):
    """Known output cleanup must never consume declared caller input files."""

    generated = GeneratedOutputLifecycleTests.generated
    setUp = GeneratedOutputLifecycleTests.setUp
    write_prices = GeneratedOutputLifecycleTests.write_prices
    run_replay = GeneratedOutputLifecycleTests.run_replay
    seed_completed_outputs = GeneratedOutputLifecycleTests.seed_completed_outputs

    def check_protected(self, result, protected, original, *, cli=False):
        self.assertTrue(protected.exists(), "caller input was deleted")
        self.assertEqual(protected.read_bytes(), original)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "caller_input_collides_with_replay_output")
        self.assertEqual(result["metric_mode"], "DO_NOT_USE")
        self.assertFalse(result["valid_for_production"])
        for key in ("cagr", "max_dd", "sharpe", "ending_capital_usd"):
            self.assertIsNone(result.get(key))
        for name in self.generated - {"metrics.json", "replay_report.md"}:
            path = self.out / name
            if path.resolve() != protected.resolve():
                self.assertFalse(path.exists() or path.is_symlink(), name)
        self.assertEqual((self.out / "caller_receipt.json").read_bytes(), b'{"caller":"preserve"}')
        self.assertEqual((self.out / "notes.md").read_bytes(), b"caller notes\n")
        self.assertEqual((self.out / "caller_archive/reserve_reason_audit.json").read_bytes(), b"unrelated nested audit")

    def cli(self, target, *, mode, portfolio="main", extra=()):
        argv = ["broker", "--target-book", str(target), "--price-cache", str(self.cache),
                "--output-dir", str(self.out), "--portfolio-kind", portfolio,
                "--fill-mode", mode, "--cash-carry-mode", "none", *extra]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as output:
            code = broker.main()
        self.assertEqual(code, 2)
        return json.loads(output.getvalue())

    def test_all_thirteen_outputs_and_modes_protect_content_based_csv_inputs(self):
        source, original = self.target, self.target.read_bytes()
        for portfolio in ("main", "concentrated"):
            for mode in ("next_close", "same_close", "next_open"):
                for name in sorted(self.generated):
                    with self.subTest(portfolio=portfolio, mode=mode, name=name):
                        self.target = source
                        self.out = self.root / "outputs" / portfolio / (mode + "-" + name)
                        self.seed_completed_outputs()
                        self.target = self.out / name
                        self.target.write_bytes(original)
                        result = self.run_replay(fill_mode=mode, portfolio_kind=portfolio)
                        self.check_protected(result, self.target, original)
                        self.check_protected(self.cli(self.target, mode=mode, portfolio=portfolio), self.target, original)

    def test_declared_auxiliary_csv_paths_share_the_protected_set(self):
        source, original = self.target, self.target.read_bytes()
        for role in ("cash_rate", "paper_slippage"):
            for name in sorted(self.generated):
                with self.subTest(role=role, name=name):
                    self.target = source
                    self.out = self.root / (role + "-" + name)
                    self.seed_completed_outputs()
                    protected = self.out / name
                    protected.write_bytes(original)
                    options = ({"cash_carry_config": CashCarryConfig(mode="none", rate_path=protected)}
                               if role == "cash_rate" else
                               {"execution_cost_config": broker.ExecutionCostConfig(paper_slippage_path=protected)})
                    self.check_protected(self.run_replay(**options), protected, original)
                    flag = "--cash-rate-path" if role == "cash_rate" else "--paper-slippage-path"
                    self.check_protected(self.cli(source, mode="next_close", extra=(flag, str(protected))), protected, original)

    def test_actual_resolved_aliases_are_rejected_before_unlink(self):
        source, original = self.target, self.target.read_bytes()
        for name in ("reserve_reason_audit.json", "metrics.json", "replay_report.md"):
            for kind in ("parent", "case", "target_link", "output_link", "junction"):
                with self.subTest(name=name, kind=kind):
                    self.target = source
                    real_out = self.root / (kind + "-" + name)
                    self.out = real_out
                    self.seed_completed_outputs()
                    leaf = real_out / name
                    leaf.write_bytes(original)
                    protected_link = None
                    if kind == "parent":
                        self.target = real_out / "caller_archive" / ".." / name
                    elif kind == "case":
                        if os.name != "nt":
                            continue  # Separate actual Windows case behavior; no POSIX case claim.
                        self.target = Path(str(leaf).swapcase())
                    elif kind == "target_link":
                        self.target = self.root / ("caller-link-" + name)
                        try:
                            self.target.symlink_to(leaf)
                        except OSError as exc:
                            self.skipTest("native file symlink unavailable: " + type(exc).__name__)
                        protected_link = self.target
                    elif kind == "output_link":
                        leaf.unlink()
                        try:
                            leaf.symlink_to(source)
                        except OSError as exc:
                            self.skipTest("native file symlink unavailable: " + type(exc).__name__)
                        self.target = source
                        protected_link = leaf
                    else:
                        alias = self.root / ("junction-alias-" + name)
                        if os.name == "nt":
                            made = subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(real_out)],
                                                  capture_output=True)
                            self.assertEqual(made.returncode, 0, made.stderr)
                        else:
                            alias.symlink_to(real_out, target_is_directory=True)
                        self.out = alias
                        self.target = leaf
                    self.check_protected(self.run_replay(), self.target, original)
                    if protected_link is not None:
                        self.assertTrue(protected_link.is_symlink())
                    self.check_protected(self.cli(self.target, mode="next_close"), self.target, original)
                    if protected_link is not None:
                        self.assertTrue(protected_link.is_symlink())

    def test_collision_precedes_target_rate_price_and_order_reads(self):
        self.out.mkdir()
        self.target = self.out / "reserve_reason_audit.json"
        self.target.write_text("rebalance_date,ticker,weight\n2026-01-02,AAA,.5\n", encoding="utf-8")
        original = self.target.read_bytes()
        with patch.object(broker, "read_csv", side_effect=AssertionError("target reader reached")), \
             patch.object(broker, "load_price_series", side_effect=AssertionError("price reader reached")), \
             patch.object(broker, "load_cash_rate_series", side_effect=AssertionError("rate reader reached")), \
             patch.object(broker, "account_equity", side_effect=AssertionError("equity reached")), \
             patch.object(broker, "execute_order", side_effect=AssertionError("orders reached")):
            result = self.run_replay(reserve_mode="DGS3MO_CARRY")
        self.assertEqual(result["reason"], "caller_input_collides_with_replay_output")
        self.assertEqual(self.target.read_bytes(), original)

    def test_disjoint_inside_sibling_and_archive_inputs_preserve_closing_semantics(self):
        original = self.target.read_bytes()
        for mode in ("next_close", "same_close"):
            for placement in ("inside", "sibling", "nested"):
                with self.subTest(mode=mode, placement=placement):
                    self.out = self.root / (mode + placement)
                    self.out.mkdir()
                    self.target = ({"inside": self.out / "caller-target.csv",
                                    "sibling": self.root / "sibling" / "reserve_reason_audit.json",
                                    "nested": self.out / "archive" / "trades.csv"})[placement]
                    self.target.parent.mkdir(parents=True, exist_ok=True)
                    self.target.write_bytes(original)
                    self.write_prices([100.] * 4)
                    result = self.run_replay(fill_mode=mode)
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(self.target.read_bytes(), original)
                    self.assertTrue((self.out / "trades.csv").is_file())

    def test_cleanup_unlinks_disjoint_input_hardlinks_without_changing_original(self):
        original = self.target.read_bytes()
        for name in sorted(self.generated):
            with self.subTest(name=name):
                self.out = self.root / ("hardlink-" + name)
                self.out.mkdir()
                leaf = self.out / name
                os.link(self.target, leaf)
                self.write_prices([100.] * 4)
                result = self.run_replay(partial_resize_two_signal_confirmation=True)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(self.target.read_bytes(), original)
                self.assertNotEqual(leaf.stat().st_ino, self.target.stat().st_ino)


class ResearchNavCallerTests(unittest.TestCase):
    """Actual synthetic ledger + unchanged consumers; assertions active under -O."""
    setUp = GeneratedOutputLifecycleTests.setUp
    write_prices = GeneratedOutputLifecycleTests.write_prices
    run_replay = GeneratedOutputLifecycleTests.run_replay

    def measurement(self, value=9987.5):
        from nav_metrics_v2_smoke import rows, context, binding
        data = rows((value, value, value))
        return dict(full=context(data, anchor_nav=10000.), valuation_binding=binding(data))

    def test_raw_admission_precedes_coercion_sort_or_drop(self):
        from nav_metrics_v2_smoke import rows, context, frame
        from tools import nav_metrics_v2 as nav
        original = frame(rows()); c = context(rows())
        good = broker.calc_metrics(original, pd.DataFrame(), 100., measurement_context=c)
        self.assertEqual(good['status'], nav.COMPLETE)
        self.assertAlmostEqual(good['max_dd'], -.1)
        cases = [original.iloc[::-1], original.iloc[:2], pd.concat([original, original.iloc[:1]])]
        for value in ('95', None, True, 0., float('nan'), float('inf')):
            bad=original.copy();bad['equity_usd']=bad['equity_usd'].astype(object);bad.loc[1,'equity_usd']=value;cases.append(bad)
        for bad in cases:
            with self.subTest(rows=bad.to_dict('records')):
                before=bad.copy(deep=True)
                result=broker.calc_metrics(bad,pd.DataFrame(),100.,measurement_context=c)
                self.assertEqual(result['status'],nav.BLOCKED)
                self.assertIsNone(result['max_dd']); pd.testing.assert_frame_equal(before,bad)
        self.assertEqual(broker.calc_metrics(original,pd.DataFrame(),101.,measurement_context=c)['reason'],
                         'CALLER_PREFILL_CAPITAL_MISMATCH')
        self.assertEqual(broker.calc_metrics(original.drop(columns='valuation_time_utc'),pd.DataFrame(),100.,
                         measurement_context=c)['reason'],'VALUATION_TIME_UNBOUND')

    def test_bound_receipt_cannot_overwrite_actual_or_future_valuation_clock(self):
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import rows,frame,context,binding
        import copy
        data=rows();c=context(data);f=frame(data);b=binding(data)
        self.assertEqual(broker.calc_metrics(f,pd.DataFrame(),100.,measurement_context=c,valuation_binding=b)['status'],nav.COMPLETE)
        bad=f.copy();bad.loc[0,'valuation_time_utc']='2026-01-05T20:00:00Z'
        out=broker.calc_metrics(bad,pd.DataFrame(),100.,measurement_context=c,valuation_binding=b)
        self.assertEqual(out['reason'],'VALUATION_CLOCK_CONFLICT')
        future=copy.deepcopy(b);future['cutoff']='2026-01-08T21:00:00Z'
        out=broker.calc_metrics(f,pd.DataFrame(),100.,measurement_context=c,valuation_binding=future)
        self.assertEqual(out['reason'],'VALUATION_BINDING_FUTURE')

    def test_actual_net_fee_curve_is_research_and_never_official_filename(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        result=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(result['status'],nav.COMPLETE,result)
        self.assertEqual(result['execution_status'],'completed')
        self.assertEqual(result['metric_mode'],nav.MODE)
        self.assertAlmostEqual(result['max_dd'],-12.5/10000.)
        self.assertAlmostEqual(result['total_return'],-12.5/10000.)
        self.assertFalse(result['valid_for_production'])
        dest=self.out/nav.NAMESPACE
        curve=pd.read_csv(dest/nav.CURVE_FILE)
        self.assertEqual(curve['equity_usd'].tolist(),[9987.5]*3)
        self.assertEqual(pd.read_csv(dest/nav.artifact_name('trades.csv'))['fee_usd'].sum(),12.5)
        for name in REPLAY_GENERATED_ARTIFACTS:
            self.assertFalse((self.out/name).exists(),name)
            self.assertFalse((dest/name).exists(),name)
        self.assertTrue((dest/nav.METRICS_FILE).exists())
        self.assertIn('research_completed',(dest/nav.artifact_name('replay_report.md')).read_text())

    def test_bad_requested_measurement_clears_only_research_outputs(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)
        dest=self.out/nav.NAMESPACE
        (dest/'caller_note.txt').write_bytes(b'keep')
        (self.out/'equity_curve.csv').write_bytes(b'prior official evidence untouched')
        for bad in ({}, {'full':{}}, [], {'full':self.measurement()['full'],'windows':[]},
                    {'full':self.measurement()['full'],'windows':{'full':self.measurement()['full']}}):
            with self.subTest(context=bad):
                options=dict(measurement_context=bad)
                if type(bad) is dict and 'windows' in bad: options['oos_start']='2026-01-06'
                out=self.run_replay(**options)
                self.assertEqual(out['status'],nav.BLOCKED,out)
                self.assertIsNone(out['cagr'])
                self.assertFalse((dest/nav.CURVE_FILE).exists())
                self.assertFalse((dest/nav.artifact_name('account_state_latest.json')).exists())
                self.assertEqual((dest/'caller_note.txt').read_bytes(),b'keep')
                self.assertEqual((self.out/'equity_curve.csv').read_bytes(),b'prior official evidence untouched')

    def test_dynamic_cost_success_retains_execution_and_true_failure_redacts(self):
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context, binding
        from tools.execution_cost_model import ExecutionCostConfig
        idx=pd.bdate_range('2025-12-01','2026-01-07')
        pd.DataFrame({'Open':100.,'Close':100.,'Adj Close':100.,'High':100.,'Low':100.,
                      'Volume':1000000},index=idx).to_parquet(self.cache/px_cache_name('AAA'))
        cfg=ExecutionCostConfig(mode='spread_adv_impact_v1')
        # Genuine fixture execution determines net account rows; supplied receipt stays explicit.
        baseline=self.run_replay(execution_cost_config=cfg)
        self.assertEqual(baseline['status'],'completed',baseline)
        df=pd.read_csv(self.out/'equity_curve.csv')
        data=[dict(session=r.date,timestamp=r.date+'T21:00:00Z',nav=r.equity_usd) for r in df.itertuples()]
        c=dict(full=context(data,anchor_nav=10000.),valuation_binding=binding(data))
        result=self.run_replay(execution_cost_config=cfg,measurement_context=c)
        self.assertEqual(result['status'],nav.COMPLETE,result)
        self.assertTrue(result['execution_cost_coverage_complete'])
        self.assertEqual(result['metric_mode'],nav.MODE)
        self.assertTrue((self.out/nav.NAMESPACE/nav.CURVE_FILE).exists())
        self.assertEqual(result['ending_capital_usd'],baseline['ending_capital_usd'])
        self.write_prices([100.]*4)  # Actual missing OHLCV/history: E1 failure still redacts.
        failed=self.run_replay(execution_cost_config=cfg,measurement_context=self.measurement())
        self.assertEqual(failed['status'],'blocked')
        self.assertEqual(failed['metric_mode'],'DO_NOT_USE')
        self.assertNotIn('cagr',failed)
        self.assertFalse((self.out/nav.NAMESPACE/nav.CURVE_FILE).exists())

    def test_research_collision_rejects_before_cleanup_or_source_read(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        for name in REPLAY_GENERATED_ARTIFACTS:
            p=dest/nav.artifact_name(name);p.write_bytes(b'preserved destination')
        before={p.name:p.read_bytes() for p in dest.iterdir()}
        protected=dest/nav.METRICS_FILE
        with patch.object(broker,'read_csv',side_effect=AssertionError('must precede reads')):
            result=self.run_replay(measurement_context={},measurement_context_path=protected)
        self.assertEqual(result['reason'],'caller_input_collides_with_replay_output')
        self.assertEqual({p.name:p.read_bytes() for p in dest.iterdir()},before)
        cache_dest=self.cache/'out'/nav.NAMESPACE;cache_dest.mkdir(parents=True)
        sentinel=cache_dest/nav.CURVE_FILE;sentinel.write_bytes(b'input namespace')
        with patch.object(broker,'read_csv',side_effect=AssertionError('no source read')):
            result=self.run_replay(output_dir=self.cache/'out',measurement_context={})
        self.assertEqual(result['reason'],'CALLER_OUTPUT_INSIDE_PRICE_CACHE')
        self.assertEqual(sentinel.read_bytes(),b'input namespace')

    def test_partial_research_publication_cannot_leave_an_orphan_NAV(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        original=pd.DataFrame.to_csv
        def fail_after_curve(df,path,*args,**kwargs):
            if Path(path).name==nav.artifact_name('trades.csv'):
                raise OSError('synthetic disk failure')
            return original(df,path,*args,**kwargs)
        before=self.target.read_bytes()
        with patch.object(pd.DataFrame,'to_csv',fail_after_curve):
            out=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(out['status'],nav.BLOCKED)
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE')
        self.assertFalse((self.out/nav.NAMESPACE/nav.CURVE_FILE).exists())
        self.assertEqual(self.target.read_bytes(),before)

    def test_real_account_hygiene_mission_and_orphan_OOS_consumers_reject(self):
        from tools import nav_metrics_v2 as nav
        from tools.run_oos_lock_audit import audit_portfolio
        from tools.run_account_evaluation import summarize_portfolio
        from tools.run_metric_hygiene_report import official_portfolio
        from mission_contract import mission_binding_status,mission_identity,HISTORICAL_UNBOUND
        from r1000_config import PORTFOLIO_MISSION_TARGETS
        self.write_prices([100.]*4)
        latest=self.root/'consumer';self.out=latest/'broker_replay'/'main'
        result=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(result['status'],nav.COMPLETE)
        research=self.out/nav.NAMESPACE
        # Point old readers at the research directory itself; metadata absence must stay safe.
        rebased=latest/'rebased';(rebased/'broker_replay').mkdir(parents=True)
        for metadata in (None,{}, {'metric_mode':nav.MODE}, result):
            with self.subTest(metadata=metadata):
                target=research/nav.METRICS_FILE
                if metadata is None: target.unlink(missing_ok=True)
                else: target.write_text(json.dumps(metadata,allow_nan=False))
                # Original official root and an explicit rebased research-root alias both reject.
                import shutil
                copied=rebased/'broker_replay'/'main'
                if copied.exists(): shutil.rmtree(copied)
                shutil.copytree(research,copied)
                for root in (latest,rebased):
                    audit=audit_portfolio(root,'main',{'oos_start':'2026-01-06'})
                    self.assertFalse(audit['pass']);self.assertIn('equity_curve_missing_or_empty',audit['failures'])
                    account=summarize_portfolio(root,'main')
                    self.assertFalse(account['target_pass']);self.assertFalse(account['valid_for_production'])
                    hygiene=official_portfolio(root,'main')
                    self.assertFalse(hygiene['target_pass']);self.assertFalse(hygiene['production_valid'])
                self.assertEqual(mission_binding_status(metadata,mission_identity(PORTFOLIO_MISSION_TARGETS)),HISTORICAL_UNBOUND)

    def test_research_IO_every_native_export_stage_is_bounded(self):
        from tools import nav_metrics_v2 as nav
        from tools.execution_cost_model import ExecutionCostConfig
        self.write_prices([100.]*4);before=self.target.read_bytes()
        original_csv=pd.DataFrame.to_csv;original_text=Path.write_text
        scenes=("success","measurement_blocked","execution_blocked","empty_target")
        for scene in scenes:
            with self.subTest(scene=scene):
                self.target.write_bytes(before)
                options=dict(measurement_context=self.measurement())
                if scene=="measurement_blocked":options['measurement_context']={}
                if scene=="execution_blocked":options['execution_cost_config']=ExecutionCostConfig(mode='spread_adv_impact_v1')
                if scene=="empty_target":self.target.write_text('ticker,rebalance_date,weight\n')
                source=self.target.read_bytes();calls=[];fail_at=None;counter=0
                def observe(path):
                    nonlocal counter
                    if Path(path).parent==self.out/nav.NAMESPACE:
                        counter+=1;calls.append(Path(path).name)
                        if counter==fail_at:raise OSError("synthetic export failure")
                def csv(df,path,*a,**kw):observe(path);return original_csv(df,path,*a,**kw)
                def text(path,*a,**kw):observe(path);return original_text(path,*a,**kw)
                with patch.object(pd.DataFrame,'to_csv',csv),patch.object(Path,'write_text',text):
                    baseline=self.run_replay(**options)
                self.assertTrue(calls,scene)
                if scene=="success":self.assertEqual(baseline['status'],nav.COMPLETE)
                elif scene=="execution_blocked":
                    self.assertEqual(baseline['metric_mode'],'DO_NOT_USE')
                    self.assertTrue(baseline['performance_fields_redacted'])
                for index,name in enumerate(tuple(calls),1):
                    with self.subTest(scene=scene,write_index=index,name=name):
                        fail_at=index;counter=0;calls=[]
                        with patch.object(pd.DataFrame,'to_csv',csv),patch.object(Path,'write_text',text):
                            out=self.run_replay(**options)
                        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE',out)
                        self.assertEqual(out['status'],nav.BLOCKED)
                        self.assertFalse(out['current_publication_complete'])
                        self.assertTrue(out['cleanup_complete'])
                        for field in nav.METRIC_FIELDS:self.assertIsNone(out[field],field)
                        self.assertFalse(out['valid_for_production'])
                        self.assertEqual(self.target.read_bytes(),source)
                        self.assertFalse(any((self.out/nav.NAMESPACE/n).exists() for n in
                                             map(nav.artifact_name,broker.REPLAY_GENERATED_ARTIFACTS)))
        self.target.write_bytes(before)

    def test_research_startup_cleanup_failures_disclose_incomplete_output(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);dest=self.out/nav.NAMESPACE
        before=self.target.read_bytes();original_mkdir=Path.mkdir;original_unlink=Path.unlink
        original_resolve=Path.resolve
        def resolve(path,*a,**kw):
            if path==dest:raise PermissionError("resolve denied")
            return original_resolve(path,*a,**kw)
        with patch.object(Path,'resolve',resolve):out=self.run_replay(measurement_context={})
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['current_publication_complete'])
        def mkdir(path,*a,**kw):
            if path==dest:raise PermissionError("mkdir denied")
            return original_mkdir(path,*a,**kw)
        with patch.object(Path,'mkdir',mkdir):out=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['current_publication_complete'])
        self.assertEqual(self.target.read_bytes(),before)
        dest.mkdir(parents=True,exist_ok=True);keep=dest/'caller-notes';keep.write_bytes(b'preserve')
        for name in map(nav.artifact_name,broker.REPLAY_GENERATED_ARTIFACTS):
            with self.subTest(startup_unlink=name):
                leaf=dest/name;leaf.write_bytes(b'old generated')
                def unlink(path,*a,**kw):
                    if path==leaf:raise PermissionError("unlink denied")
                    return original_unlink(path,*a,**kw)
                with patch.object(Path,'unlink',unlink):out=self.run_replay(measurement_context={})
                self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE')
                self.assertFalse(out['cleanup_complete']);self.assertIn(name,out['uncleared_generated_outputs'])
                self.assertEqual(leaf.read_bytes(),b'old generated');leaf.unlink()
        original_text=Path.write_text
        def text(path,*a,**kw):
            if path.name==nav.artifact_name('replay_report.md'):raise OSError("late report failure")
            return original_text(path,*a,**kw)
        def unlink_metric(path,*a,**kw):
            if path==dest/nav.METRICS_FILE:raise PermissionError("cleanup denied")
            return original_unlink(path,*a,**kw)
        with patch.object(Path,'write_text',text),patch.object(Path,'unlink',unlink_metric):
            out=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['cleanup_complete'])
        self.assertIn(nav.METRICS_FILE,out['uncleared_generated_outputs'])
        self.assertTrue((dest/nav.METRICS_FILE).exists());self.assertFalse(out['current_publication_complete'])
        self.assertEqual(keep.read_bytes(),b'preserve');self.assertEqual(self.target.read_bytes(),before)
        # Predicate helpers can suppress denied stat; actual lstat must disclose uncertainty.
        original_lstat=nav.os.lstat;metric=dest/nav.METRICS_FILE
        def lstat(path,*a,**kw):
            if Path(path)==metric:raise PermissionError('stat denied')
            return original_lstat(path,*a,**kw)
        with patch.object(nav.os,'lstat',lstat):
            out=self.run_replay(measurement_context={})
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['cleanup_complete'])
        self.assertTrue(metric.exists());self.assertFalse(out['current_publication_complete'])
        metric.unlink()
        # Denial after successful publication must retain the uncertain leaf in telemetry.
        def after_write_lstat(path,*a,**kw):
            if Path(path)==metric:
                try:original_lstat(path,*a,**kw)
                except FileNotFoundError:pass
                else:raise PermissionError('cleanup stat denied')
            return original_lstat(path,*a,**kw)
        with patch.object(Path,'write_text',text),patch.object(nav.os,'lstat',after_write_lstat):
            out=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE');self.assertFalse(out['cleanup_complete'])
        self.assertIn(nav.METRICS_FILE,out['uncleared_generated_outputs']);self.assertTrue(metric.exists())

    def test_research_guard_preserves_legacy_and_programming_error_contracts(self):
        self.write_prices([100.]*4)
        with patch.object(broker,'read_csv',side_effect=ValueError('programming error')):
            with self.assertRaisesRegex(ValueError,'programming error'):
                self.run_replay(measurement_context={})
        original=Path.mkdir
        def mkdir(path,*a,**kw):
            if path==self.out:raise OSError('legacy IO')
            return original(path,*a,**kw)
        with patch.object(Path,'mkdir',mkdir):
            with self.assertRaisesRegex(OSError,'legacy IO'):self.run_replay()

    def test_actual_default_rate_and_reverse_price_aliases_preserve_sources(self):
        import os
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        names=list(map(nav.artifact_name,broker.REPLAY_GENERATED_ARTIFACTS))
        original_resolve=Path.resolve
        # Resolve-equivalence models the same physical alias on Windows without requiring symlink privilege.
        price=self.cache/px_cache_name('AAA');rate=self.root/'cache_macro'/'fred_dgs3mo_DGS3MO.csv'
        rate.parent.mkdir()
        rate.write_text('date,value\n2026-01-02,4.0\n')
        cfg=CashCarryConfig(mode=broker.CASH_CARRY_MODE_RISK_FREE)
        for source,options in ((price,{}),(rate,dict(cash_carry_config=cfg,reserve_mode='DGS3MO_CARRY'))):
            for name in names:
                with self.subTest(source=source.name,output=name):
                    leaf=dest/name;leaf.write_bytes(source.read_bytes());sentinel=dest/'caller-notes';sentinel.write_bytes(b'keep')
                    def resolve(path,*a,**kw):
                        return original_resolve(leaf,*a,**kw) if path==source else original_resolve(path,*a,**kw)
                    candidates=patch.object(broker,'REPO_ROOT',self.root)
                    with patch.object(Path,'resolve',resolve),candidates:
                        out=self.run_replay(measurement_context={},**options)
                    self.assertEqual(out['reason'],'caller_input_collides_with_replay_output',out)
                    self.assertEqual(leaf.read_bytes(),source.read_bytes());self.assertEqual(sentinel.read_bytes(),b'keep')
                    leaf.unlink()
        # A distinct hardlink can be unlinked as an output while the original price inode/bytes survive.
        leaf=dest/nav.CURVE_FILE;os.link(price,leaf);before=price.read_bytes()
        out=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(out['status'],nav.COMPLETE);self.assertEqual(price.read_bytes(),before)
        selected=rate.with_suffix('.parquet')
        pd.DataFrame([dict(date='2025-12-31',value=4.)]).to_parquet(selected)
        unused=rate
        def resolve_unused(path,*a,**kw):
            return original_resolve(dest/nav.METRICS_FILE,*a,**kw) if path==unused else original_resolve(path,*a,**kw)
        # Native selection stops at the first existing rate; an unselected alias is not a byte source.
        with patch.object(broker,'REPO_ROOT',self.root), \
             patch.object(Path,'resolve',resolve_unused):
            out=self.run_replay(measurement_context={},cash_carry_config=cfg,reserve_mode='DGS3MO_CARRY')
        self.assertNotEqual(out.get('reason'),'caller_input_collides_with_replay_output')
        if os.name!='nt':
            leaf=dest/nav.CURVE_FILE;leaf.unlink(missing_ok=True);original_price=price.read_bytes()
            leaf.write_bytes(original_price);price.unlink();price.symlink_to(leaf)
            try:
                out=self.run_replay(measurement_context={})
                self.assertEqual(out['reason'],'caller_input_collides_with_replay_output')
                self.assertEqual(leaf.read_bytes(),original_price)
            finally:price.unlink();price.write_bytes(original_price)


    def test_research_broker_preflight_refusal_discloses_retained_outputs(self):
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)
        dest=self.out/nav.NAMESPACE;names=[nav.artifact_name(n) for n in REPLAY_GENERATED_ARTIFACTS]
        for name in names:
            if not (dest/name).exists():(dest/name).write_bytes(b'prior generation')
        before={n:(dest/n).read_bytes() for n in names};real_resolve=Path.resolve
        for kind in ('target','directory','reverse_price'):
            with self.subTest(kind=kind):
                if kind=='directory':
                    original=nav.research_output_kind
                    def probe(p):return 'other' if p==dest/names[0] else original(p)
                    guard=patch.object(nav,'research_output_kind',probe)
                else:
                    source=self.target if kind=='target' else self.cache/px_cache_name('AAA')
                    def resolve(p,*a,**kw):return real_resolve(dest/names[0]) if p==source else real_resolve(p,*a,**kw)
                    guard=patch.object(Path,'resolve',resolve)
                with guard:out=self.run_replay(measurement_context=self.measurement())
                self.assertEqual(out['status'],nav.BLOCKED,out)
                self.assertFalse(out['current_publication_complete']);self.assertFalse(out['cleanup_complete'])
                self.assertEqual(set(out['uncleared_generated_outputs']),set(names))
                self.assertEqual(before,{n:(dest/n).read_bytes() for n in names})

    def test_research_broker_selected_shared_price_reader_fails_closed(self):
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);source=self.cache/px_cache_name('AAA');before=source.read_bytes()
        for stage in ('read','stat'):
            with self.subTest(stage=stage):
                self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)
                if stage=='read':
                    real_read=pd.read_parquet
                    def denied(p,*a,**kw):
                        if Path(p)==source:raise PermissionError('denied selected broker price')
                        return real_read(p,*a,**kw)
                    guard=patch.object(pd,'read_parquet',denied)
                else:
                    real_stat=Path.stat
                    def denied(p,*a,**kw):
                        if p==source:raise PermissionError('denied selected broker stat')
                        return real_stat(p,*a,**kw)
                    guard=patch.object(Path,'stat',denied)
                with guard:out=self.run_replay(measurement_context=self.measurement())
                self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE',out)
                self.assertFalse(out['current_publication_complete']);self.assertIsNone(out['cagr'])
                self.assertEqual(source.read_bytes(),before)
        with patch.object(pd,'read_parquet',side_effect=PermissionError('legacy read')):
            self.assertTrue(load_price_series(self.cache,'AAA').empty)

    def test_required_research_target_read_stat_and_absence_are_explicit(self):
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);raw=self.target.read_bytes()
        for stage in ('read','stat','missing'):
            with self.subTest(stage=stage):
                self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)
                if stage=='read':
                    original=pd.read_csv
                    def denied(p,*a,**kw):
                        if isinstance(p,(str,Path)) and Path(p)==self.target:raise PermissionError('denied target read')
                        return original(p,*a,**kw)
                    guard=patch.object(pd,'read_csv',denied)
                elif stage=='stat':
                    original=Path.stat
                    def denied(p,*a,**kw):
                        if p==self.target:raise PermissionError('denied target stat')
                        return original(p,*a,**kw)
                    guard=patch.object(Path,'stat',denied)
                else:
                    self.target.unlink();guard=__import__('contextlib').nullcontext()
                try:
                    with guard:out=self.run_replay(measurement_context=self.measurement())
                finally:
                    if stage=='missing':self.target.write_bytes(raw)
                self.assertEqual(out['reason'],'RESEARCH_IO_FAILURE',out)
                self.assertFalse(out['current_publication_complete']);self.assertIsNone(out['cagr'])
                self.assertEqual(out['io_error_type'],'FileNotFoundError' if stage=='missing' else 'PermissionError')
                self.assertEqual(self.target.read_bytes(),raw)
        with patch.object(pd,'read_csv',side_effect=PermissionError('legacy denied target')):
            self.assertTrue(broker.read_csv(self.target).empty)

    def test_selected_rate_and_slippage_IO_never_become_silent_optional_evidence(self):
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context,binding
        from tools.execution_cost_model import ExecutionCostConfig,load_paper_slippage
        idx=pd.bdate_range('2025-12-01','2026-01-07')
        px=pd.DataFrame({'Open':100.,'Close':100.,'Adj Close':100.,'High':100.,'Low':100.,'Volume':1000000},index=idx)
        for ticker in ('AAA','SPY','QQQ'):px.to_parquet(self.cache/px_cache_name(ticker))
        rate=self.root/'selected_rate.csv';rate.write_text('date,value\n2025-12-01,0\n',encoding='utf-8')
        slip=self.root/'selected_slippage.csv';slip.write_text('date,ticker,side,observed_slippage_bps\n2026-01-05,AAA,BUY,0\n',encoding='utf-8')
        for kind,source,options in (
            ('rate',rate,dict(cash_carry_config=CashCarryConfig(mode='risk_free_rate',rate_path=rate,rate_lag_days=0,haircut_bps=0.),reserve_mode='DGS3MO_CARRY')),
            ('slippage',slip,dict(execution_cost_config=ExecutionCostConfig(mode='spread_adv_impact_v1',paper_slippage_path=slip)))):
            with patch.object(broker,'ExecutionCostModel',wraps=broker.ExecutionCostModel) as ctor:
                baseline=self.run_replay(**options)
                if kind=='slippage':
                    self.assertEqual(len(ctor.call_args.args),2);self.assertEqual(ctor.call_args.kwargs,{})
                else:self.assertFalse(ctor.called)
            self.assertEqual(baseline['status'],'completed',baseline)
            df=pd.read_csv(self.out/'equity_curve.csv')
            data=[dict(session=r.date,timestamp=r.date+'T21:00:00Z',nav=r.equity_usd) for r in df.itertuples()]
            receipt=dict(full=context(data,anchor_nav=10000.),valuation_binding=binding(data));raw=source.read_bytes()
            for stage in ('read','stat','missing'):
                with self.subTest(kind=kind,stage=stage):
                    with patch.object(broker,'ExecutionCostModel',wraps=broker.ExecutionCostModel) as ctor:
                        self.assertEqual(self.run_replay(**options,measurement_context=receipt)['status'],nav.COMPLETE)
                        if kind=='slippage':self.assertEqual(ctor.call_args.kwargs,{'strict_io':True})
                    if stage=='read':
                        original=pd.read_csv
                        def denied(p,*a,**kw):
                            if isinstance(p,(str,Path)) and Path(p)==source:raise PermissionError('denied selected table read')
                            return original(p,*a,**kw)
                        guard=patch.object(pd,'read_csv',denied)
                    elif stage=='stat':
                        original=Path.stat
                        def denied(p,*a,**kw):
                            if p==source:raise PermissionError('denied selected table stat')
                            return original(p,*a,**kw)
                        guard=patch.object(Path,'stat',denied)
                    else:
                        source.unlink();guard=__import__('contextlib').nullcontext()
                    try:
                        with guard:out=self.run_replay(**options,measurement_context=receipt)
                    finally:
                        if stage=='missing':source.write_bytes(raw)
                    self.assertEqual(out.get('reason'),'RESEARCH_IO_FAILURE',out)
                    self.assertFalse(out['current_publication_complete']);self.assertIsNone(out['cagr'])
                    self.assertEqual(source.read_bytes(),raw)
        self.assertTrue(load_paper_slippage(None).empty)
        self.assertTrue(load_paper_slippage(self.root/'genuinely_missing_optional.csv').empty)
        self.assertFalse(load_paper_slippage(slip).empty)
        with patch.object(pd,'read_csv',side_effect=PermissionError('legacy optional read')):
            self.assertTrue(load_paper_slippage(slip).empty)

    def test_strict_optional_slippage_formats_absence_and_disabled_controls(self):
        from unittest.mock import patch
        from tools.execution_cost_model import ExecutionCostConfig,ExecutionCostModel,load_paper_slippage
        from tools import nav_metrics_v2 as nav
        supplied=pd.DataFrame([dict(date='2026-01-05',ticker='AAA',side='BUY',observed_slippage_bps=3.)])
        normalized=load_paper_slippage(None,strict_io=True)
        self.assertTrue(normalized.empty)
        for suffix in ('.csv','.parquet'):
            with self.subTest(format=suffix):
                path=self.root/('actual_optional'+suffix)
                if suffix=='.csv':supplied.to_csv(path,index=False)
                else:supplied.to_parquet(path,index=False)
                original=path.read_bytes()
                old=load_paper_slippage(path);strict=load_paper_slippage(path,strict_io=True)
                pd.testing.assert_frame_equal(old,strict)
                cfg=ExecutionCostConfig(mode='spread_adv_impact_v1',paper_slippage_path=path)
                pd.testing.assert_frame_equal(ExecutionCostModel({},cfg).paper_slippage,ExecutionCostModel({},cfg,strict_io=True).paper_slippage)
                reader='read_parquet' if suffix=='.parquet' else 'read_csv'
                with patch.object(pd,reader,side_effect=PermissionError('selected source denied')):
                    self.assertTrue(load_paper_slippage(path).empty)
                    with self.assertRaises(PermissionError):load_paper_slippage(path,strict_io=True)
                with patch.object(pd,reader,side_effect=ValueError('parser/programming boundary')):
                    with self.assertRaises(ValueError):load_paper_slippage(path,strict_io=True)
                self.assertEqual(path.read_bytes(),original)
        missing=self.root/'selected_missing.csv'
        self.assertTrue(load_paper_slippage(missing).empty)
        with self.assertRaises(FileNotFoundError):load_paper_slippage(missing,strict_io=True)
        self.write_prices([100.]*4)
        out=self.run_replay(execution_cost_config=ExecutionCostConfig(paper_slippage_path=missing),measurement_context=self.measurement())
        self.assertEqual(out['status'],nav.COMPLETE,out)  # Disabled optional source is not selected.

    def test_dynamic_cost_windows_keep_fixed_NAV_mode_and_failure_redaction(self):
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context,binding
        from tools.execution_cost_model import ExecutionCostConfig
        idx=pd.bdate_range('2025-12-01','2026-01-07')
        pd.DataFrame({'Open':100.,'Close':100.,'Adj Close':100.,'High':100.,'Low':100.,
                      'Volume':1000000},index=idx).to_parquet(self.cache/px_cache_name('AAA'))
        cfg=ExecutionCostConfig(mode='spread_adv_impact_v1');base=self.run_replay(execution_cost_config=cfg)
        self.assertEqual(base['status'],'completed',base)
        df=pd.read_csv(self.out/'equity_curve.csv')
        data=[dict(session=r.date,timestamp=r.date+'T21:00:00Z',nav=r.equity_usd) for r in df.itertuples()]
        first=context(data[:1],anchor_nav=10000.);first['cutoff']=data[-1]['timestamp']
        later=context(data[1:],anchor_nav=data[0]['nav'],anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        c=dict(full=context(data,anchor_nav=10000.),valuation_binding=binding(data),windows={'is':first,'oos':later})
        out=self.run_replay(execution_cost_config=cfg,measurement_context=c,oos_start='2026-01-06')
        self.assertEqual(out['status'],nav.COMPLETE,out)
        for label in ('full','is','oos'):
            metric=out if label=='full' else out['windows'][label]
            self.assertEqual(metric['metric_mode'],nav.MODE,metric)
            self.assertEqual(metric['execution_cost_mode'],cfg.mode)
        self.write_prices([100.]*4)
        failed=self.run_replay(execution_cost_config=cfg,measurement_context=c,oos_start='2026-01-06')
        self.assertEqual(failed['metric_mode'],'DO_NOT_USE',failed)
        self.assertNotIn('cagr',failed)


def main() -> int:
    test_missing_liquidation_fill_fails_closed_before_state_mutation()
    test_multi_day_transition_fails_closed_before_state_mutation()
    test_no_look_ahead_in_next_close_fills()
    test_latest_operating_close_is_audited_as_pending_next_close()
    test_non_appended_current_operating_close_is_pending()
    test_weekend_evidence_cutoff_uses_next_nyse_session()
    test_long_horizon_equity_curve_continuous()
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromTestCase(case)
        for case in (OpeningClockAdmissionTests, GeneratedOutputLifecycleTests, CallerInputCollisionTests, ResearchNavCallerTests)
    )
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        return 1
    print("broker_ledger_correctness_smoke: PASS")
    return 0




if __name__ == "__main__":
    raise SystemExit(main())
