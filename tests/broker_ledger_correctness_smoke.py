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


    def test_actual_full_OOS_flow_and_RF_receipts_preserve_inputs_and_block_exports(self):
        import copy
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import rows,context,binding,ref
        self.write_prices([100.]*4);self.assertEqual(self.run_replay()['status'],'completed')
        official={p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        sources={p:p.read_bytes() for p in [self.target,*self.cache.iterdir()] if p.is_file()}
        data=rows((9987.5,9987.5,9987.5));first=context(data[:1],anchor_nav=10000.);first['cutoff']=data[-1]['timestamp']
        later=context(data[1:],anchor_nav=data[0]['nav'],anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        good=dict(full=context(data,anchor_nav=10000.),valuation_binding=binding(data),windows={'is':first,'oos':later})
        dest=self.out/nav.NAMESPACE
        for label in ('full','oos'):
            for kind in ('flow_empty','flow_zero','RF'):
                for valid in (False,True):
                    with self.subTest(label=label,kind=kind,valid=valid):
                        c=copy.deepcopy(good);m=c['full'] if label=='full' else c['windows'][label]
                        if kind.startswith('flow'):
                            f=m['external_flows']
                            if kind=='flow_zero':f['events']=[dict(timestamp=f['end'],amount=0.)]
                            f['ref']=ref({k:v for k,v in f.items() if k!='ref'},'actual-ledger-zero-flow',f['end'] if valid else f['start'])
                        else:m['risk_free']['ref']['available_at']=data[-1]['timestamp'] if valid else m['anchor']['timestamp']
                        before=nav.encoded(c)
                        self.assertEqual(self.run_replay(measurement_context=good,oos_start='2026-01-06')['status'],nav.COMPLETE)
                        (dest/'caller_note.txt').write_bytes(b'preserve unrelated note')
                        result=self.run_replay(measurement_context=c,oos_start='2026-01-06');selected=result if label=='full' else result['windows'][label]
                        if not valid:
                            self.assertEqual(result['status'],nav.BLOCKED,result);self.assertEqual(selected['status'],nav.BLOCKED,selected)
                            self.assertIsNone(selected['cagr']);self.assertFalse(selected['metric_admission_complete'])
                            self.assertFalse((dest/nav.CURVE_FILE).exists());self.assertFalse((dest/nav.artifact_name('account_state_latest.json')).exists())
                        else:self.assertEqual(result['status'],nav.COMPLETE,result);self.assertEqual(selected['status'],nav.COMPLETE,selected)
                        self.assertFalse(result['fullrun_allowed']);self.assertFalse(result['valid_for_production'])
                        self.assertEqual(nav.encoded(c),before);self.assertEqual({p:p.read_bytes() for p in sources},sources)
                        self.assertEqual({p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()},official)
                        self.assertEqual((dest/'caller_note.txt').read_bytes(),b'preserve unrelated note')

    def test_r4_requested_windows_are_one_atomic_measurement_admission(self):
        import copy
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import rows,context,binding
        data=rows((9987.5,)*3);self.write_prices([100.]*4)
        full=context(data,anchor_nav=10000.)
        is_c=context(data[:2],anchor_nav=10000.);is_c['cutoff']=full['cutoff']
        oos=context(data[2:],anchor_nav=data[1]['nav'],anchor_time=data[1]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        oos2=context(data[1:2],anchor_nav=data[0]['nav'],anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR');oos2['cutoff']=full['cutoff']
        package=dict(full=full,valuation_binding=binding(data),windows={'is':is_c,'oos':oos,'oos2':oos2})
        options=dict(oos_start='2026-01-07',oos2_start='2026-01-06',oos2_end='2026-01-06')
        good=self.run_replay(measurement_context=package,**options)
        self.assertEqual(good['status'],nav.COMPLETE,good)
        for label in ('full','is','oos','oos2'):self.assertEqual(good['windows'][label]['status'],nav.COMPLETE,label)
        diagnostic_only=('interval_returns','first_interval_return','starting_capital_usd','start_date','end_date',
            'anchor_timestamp','ending_timestamp','days','frequency','measurement_context_sha256','input_rows_sha256',
            'valuation_binding_sha256','valuation_binding_provenance','statistic_reasons','annualization','standard_deviation_ddof')
        for label in ('full','is','oos','oos2'):
            for kind in ('missing','shape','NAV','RF','flow','anchor'):
                with self.subTest(label=label,kind=kind):
                    bad=copy.deepcopy(package);entry=bad if label=='full' else bad['windows'];key='full' if label=='full' else label
                    if kind=='missing':entry.pop(key)
                    elif kind=='shape':entry[key]={}
                    elif kind=='NAV':entry[key]['nav_ref']['sha256']='0'*64
                    elif kind=='RF':entry[key].pop('risk_free')
                    elif kind=='flow':entry[key]['external_flows']['ref']['available_at']=entry[key]['anchor']['timestamp']
                    else:entry[key]['anchor']['ref']['sha256']='0'*64
                    result=self.run_replay(measurement_context=bad,**options)
                    self.assertEqual(result['status'],nav.BLOCKED,result)
                    self.assertEqual(result['execution_status'],'completed')
                    self.assertFalse(result['metric_admission_complete'])
                    for metric in (result,*(result['windows'][name] for name in ('full','is','oos','oos2'))):
                        self.assertEqual(metric['status'],nav.BLOCKED)
                        for field in nav.METRIC_FIELDS:self.assertIsNone(metric[field],field)
                        for field in diagnostic_only:self.assertNotIn(field,metric,field)
                        for field,value in nav.AUTHORITY.items():self.assertEqual(metric[field],value,field)
                    dest=self.out/nav.NAMESPACE
                    self.assertEqual(json.loads((dest/nav.METRICS_FILE).read_text()),result)
                    self.assertFalse((dest/nav.CURVE_FILE).exists())
                    self.assertFalse((dest/nav.artifact_name('account_state_latest.json')).exists())
                    json.dumps(result,allow_nan=False)
        invalid=self.run_replay(measurement_context=package,oos_start='not-a-date')
        self.assertEqual(invalid['status'],nav.BLOCKED)
        for metric in (invalid,*[v for v in invalid['windows'].values() if type(v) is dict]):
            self.assertEqual(metric['status'],nav.BLOCKED);self.assertIsNone(metric['cagr'])
        self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)

    def test_r4_context_cli_failure_preserves_observed_generation_before_cleanup(self):
        import io,contextlib,sys
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        path=self.root/'measurement.json';dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        originals={nav.CURVE_FILE:b'prior research curve',nav.METRICS_FILE:b'{"prior":true}','foreign-note':b'untouched'}
        argv=['broker','--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),
              '--starting-capital','10000','--nav-metrics-context',str(path),'--cash-carry-mode','none','--reserve-mode','BROKER_CASH_OR_MMF']
        original_lstat=nav.os.lstat;original_open=nav.os.open;original_read=nav.os.read
        for kind,code in (('stat','CONTEXT_INPUT_IO'),('open','CONTEXT_INPUT_IO'),('short_read','CONTEXT_FILE_CHANGED'),
                          ('missing','CONTEXT_INPUT_IO'),('malformed','CONTEXT_JSON'),('duplicate','JSON_DUPLICATE')):
            with self.subTest(kind=kind):
                path.write_text(json.dumps(self.measurement()));before=path.read_bytes()
                if kind=='malformed':path.write_bytes(b'{');before=path.read_bytes()
                elif kind=='duplicate':path.write_bytes(b'{"full":{},"full":{}}');before=path.read_bytes()
                elif kind=='missing':path.unlink();before=None
                for name,value in originals.items():(dest/name).write_bytes(value)
                descriptors=set()
                def lstat(p,*a,**kw):
                    if kind=='stat' and Path(p)==path:raise PermissionError('context stat denied')
                    return original_lstat(p,*a,**kw)
                def opening(p,*a,**kw):
                    if Path(p)==path and kind=='open':raise PermissionError('context open denied')
                    fd=original_open(p,*a,**kw)
                    if Path(p)==path:descriptors.add(fd)
                    return fd
                def read(fd,*a,**kw):
                    if kind=='short_read' and fd in descriptors:return b''
                    return original_read(fd,*a,**kw)
                output=io.StringIO()
                with patch.object(sys,'argv',argv),patch.object(nav.os,'lstat',lstat),patch.object(nav.os,'open',opening),patch.object(nav.os,'read',read),contextlib.redirect_stdout(output):
                    exit_code=broker.main()
                result=json.loads(output.getvalue(),parse_constant=lambda value: self.fail('nonfinite stdout '+value))
                self.assertEqual(exit_code,2);self.assertEqual(result['status'],nav.BLOCKED)
                self.assertEqual(result.get('context_input_reason',result['reason']),code,result)
                self.assertFalse(result['current_publication_complete']);self.assertFalse(result['cleanup_complete'])
                self.assertIn(nav.CURVE_FILE,result['uncleared_generated_outputs'])
                self.assertEqual({name:(dest/name).read_bytes() for name in originals},originals)
                for field in nav.METRIC_FIELDS:self.assertIsNone(result[field])
                if before is not None:self.assertEqual(path.read_bytes(),before)
        path.write_text(json.dumps(self.measurement()))
        with patch.object(nav,'load_context',side_effect=AssertionError('explicit direct context must not reload')):
            self.assertEqual(self.run_replay(measurement_context=self.measurement(),measurement_context_path=path)['status'],nav.COMPLETE)
        with patch.object(nav,'load_context',side_effect=RuntimeError('programming error')),patch.object(sys,'argv',argv):
            with self.assertRaisesRegex(RuntimeError,'programming error'):broker.main()

    def test_r4_dynamic_and_early_research_diagnostics_are_strict_finite(self):
        import io,contextlib,sys
        from tools import nav_metrics_v2 as nav
        from tools.execution_cost_model import ExecutionCostConfig
        idx=pd.bdate_range('2025-12-01','2026-01-07')
        pd.DataFrame({'Open':100.,'Close':100.,'Adj Close':100.,'High':100.,'Low':100.,'Volume':1000000},index=idx).to_parquet(self.cache/px_cache_name('AAA'))
        cfg=ExecutionCostConfig(mode='spread_adv_impact_v1')
        baseline=self.run_replay(execution_cost_config=cfg)
        self.assertEqual(baseline['status'],'completed')
        for value in (float('nan'),float('inf'),float('-inf')):
            for mode in ('fixed_bps','spread_adv_impact_v1'):
                with self.subTest(cost=value,mode=mode):
                    result=self.run_replay(cost_bps=value,execution_cost_config=ExecutionCostConfig(mode=mode),measurement_context=self.measurement())
                    json.dumps(result,allow_nan=False)
                    self.assertNotEqual(result['status'],nav.COMPLETE)
                    self.assertFalse(result.get('valid_for_production'))
                    if mode=='spread_adv_impact_v1':
                        self.assertEqual(result['metric_mode'],'DO_NOT_USE')
                        self.assertIsNone(result.get('maximum_modeled_total_cost_bps'))
                    dest=self.out/nav.NAMESPACE
                    if (dest/nav.METRICS_FILE).exists():json.loads((dest/nav.METRICS_FILE).read_text(),parse_constant=lambda v:self.fail(v))
                    self.assertFalse((dest/nav.CURVE_FILE).exists())
        # Research-only early branch diagnostics must be finite too; default payload semantics remain.
        original=self.target.read_bytes();self.target.write_text('ticker,rebalance_date,weight\n')
        result=self.run_replay(measurement_context=self.measurement(),cost_bps=float('nan'))
        json.dumps(result,allow_nan=False);self.assertNotEqual(result['status'],nav.COMPLETE)
        self.target.write_bytes(original)
        argv=['broker','--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),
              '--starting-capital','10000','--cost-bps','nan','--execution-cost-mode','spread_adv_impact_v1',
              '--nav-metrics-context',str(self.root/'context.json')]
        (self.root/'context.json').write_text(json.dumps(self.measurement()));output=io.StringIO()
        with patch.object(sys,'argv',argv),contextlib.redirect_stdout(output):code=broker.main()
        self.assertEqual(code,2);json.loads(output.getvalue(),parse_constant=lambda v:self.fail(v))
        # Nonfinite terminal audits are not zero-cost calibration and must not
        # erase a real E1 rejection. Keep valid execution distinct from measurement.
        from nav_metrics_v2_smoke import context,binding
        curve=pd.read_csv(self.out/'equity_curve.csv')
        data=[dict(session=r.date,timestamp=r.date+'T21:00:00Z',nav=r.equity_usd) for r in curve.itertuples()]
        package=dict(full=context(data,anchor_nav=10000.),valuation_binding=binding(data))
        original_summary=broker.summarize_execution_costs
        for coverage in (False,True):
            with self.subTest(nonfinite_terminal_audit=True,coverage=coverage):
                def summary(*a,**kw):
                    value=original_summary(*a,**kw);value['coverage_complete']=coverage
                    value['unavailable_audit_value']=float('inf');return value
                with patch.object(broker,'summarize_execution_costs',summary):
                    result=self.run_replay(execution_cost_config=cfg,measurement_context=package)
                json.dumps(result,allow_nan=False)
                self.assertFalse((self.out/nav.NAMESPACE/nav.CURVE_FILE).exists())
                if coverage:
                    self.assertEqual(result['status'],nav.BLOCKED);self.assertIsNone(result['cagr'])
                else:
                    self.assertEqual(result['status'],'blocked');self.assertEqual(result['metric_mode'],'DO_NOT_USE')
                    self.assertTrue(result['performance_fields_redacted']);self.assertNotIn('cagr',result)


    def test_r5_first_selected_caller_row_requires_actual_PREFILL_for_all_ranges(self):
        import copy
        from nav_metrics_v2_smoke import context, frame, binding
        from tools import nav_metrics_v2 as nav
        data=[dict(session=d,timestamp=d+'T21:00:00Z',nav=v) for d,v in
              zip(('2026-01-02','2026-01-05','2026-01-06','2026-01-07'),(90.,95.,96.,97.))]
        ranges=(None,(None,None),(None,'2026-01-05'),('2026-01-02','2026-01-05'),
                ('2026-01-01','2026-01-05'),('2026-01-02',None),('2026-01-01',None),(None,'2026-01-02'))
        for representation in ('string','native_date'):
            f=frame(data)
            if representation=='native_date':f['date']=pd.to_datetime(f['date']).dt.date
            original=f.copy(deep=True)
            for label in ('full','is'):
                for interval in ranges:
                    selected=[r for r in data if interval is None or
                              ((not interval[0] or r['session']>=interval[0]) and
                               (not interval[1] or r['session']<=interval[1]))]
                    for variant,capital,kind in (('valid',100.,'PREFILL'),('low',50.,'PREFILL'),
                                                ('high',200.,'PREFILL'),('first_NAV',90.,'PREFILL'),('kind',100.,'OOS_PREDECESSOR')):
                        with self.subTest(representation=representation,label=label,interval=interval,variant=variant):
                            c=context(selected,anchor_nav=capital,anchor_time='2025-12-31T21:00:00Z',anchor_kind=kind)
                            c['cutoff']=data[-1]['timestamp'];before=copy.deepcopy(c)
                            # Every negative is fully rehashed and otherwise admitted by pure measurement.
                            admitted=nav.calculate_frame(f,c,valuation_binding=binding(data),date_range=interval,label=label)
                            self.assertEqual(admitted['status'],nav.COMPLETE,admitted)
                            result=broker.calc_metrics(f,pd.DataFrame(),100.,measurement_context=c,
                                valuation_binding=binding(data),date_range=interval,label=label)
                            if variant=='valid':
                                self.assertEqual(result['status'],nav.COMPLETE,result)
                                self.assertEqual(result['starting_capital_usd'],100.)
                                self.assertAlmostEqual(result['first_interval_return'],-.1)
                            else:
                                self.assertEqual(result['status'],nav.BLOCKED,result)
                                self.assertEqual(result['reason'],'CALLER_PREFILL_ANCHOR_KIND' if variant=='kind'
                                                 else 'CALLER_PREFILL_CAPITAL_MISMATCH')
                                self.assertFalse(result['metric_admission_complete'])
                                for field in nav.METRIC_FIELDS:self.assertIsNone(result[field],field)
                            for field,value in nav.AUTHORITY.items():self.assertEqual(result[field],value,field)
                            json.dumps(result,allow_nan=False);self.assertEqual(c,before)
                            pd.testing.assert_frame_equal(f,original)

    def test_r5_interior_predecessor_and_empty_OOS_boundaries_remain_distinct(self):
        from nav_metrics_v2_smoke import context,frame,binding
        from tools import nav_metrics_v2 as nav
        data=[dict(session=d,timestamp=d+'T21:00:00Z',nav=v) for d,v in
              zip(('2026-01-02','2026-01-05','2026-01-06','2026-01-07'),(90.,95.,96.,97.))]
        f=frame(data);b=binding(data)
        for lo in ('2026-01-03','2026-01-05'):
            for label in ('full','is','oos','oos2'):
                for variant,capital,time,kind in (('valid',90.,data[0]['timestamp'],'OOS_PREDECESSOR'),
                     ('NAV',100.,data[0]['timestamp'],'OOS_PREDECESSOR'),
                     ('time',90.,'2025-12-31T21:00:00Z','OOS_PREDECESSOR'),
                     ('kind',90.,data[0]['timestamp'],'PREFILL')):
                    with self.subTest(lo=lo,label=label,variant=variant):
                        c=context(data[1:],anchor_nav=capital,anchor_time=time,anchor_kind=kind)
                        result=broker.calc_metrics(f,pd.DataFrame(),100.,measurement_context=c,
                            valuation_binding=b,date_range=(lo,None),label=label)
                        if variant=='valid':
                            self.assertEqual(result['status'],nav.COMPLETE,result)
                            self.assertEqual(result['starting_capital_usd'],90.)
                        else:
                            self.assertEqual(result['status'],nav.BLOCKED,result)
                            self.assertEqual(result['reason'],'OOS_PREDECESSOR_MISMATCH')
        c=context(data,anchor_nav=100.,anchor_time='2025-12-31T21:00:00Z')
        for label in ('oos','oos2'):
            for interval in (None,(None,None),(None,'2026-01-05'),('2026-01-02',None),('2026-01-01',None)):
                with self.subTest(label=label,interval=interval):
                    result=broker.calc_metrics(f,pd.DataFrame(),100.,measurement_context=c,
                                              valuation_binding=b,date_range=interval,label=label)
                    self.assertEqual(result['reason'],'OOS_PREDECESSOR_MISSING')
                    self.assertEqual(result['status'],nav.BLOCKED)
        for interval,reason in (((None,'2026-01-01'),'WINDOW_EMPTY'),(('2026-01-08',None),'WINDOW_EMPTY'),
                                (('2026-01-07','2026-01-02'),'WINDOW_EMPTY'),(('invalid',None),'CALLER_CONTEXT_OR_ROW_SHAPE')):
            with self.subTest(interval=interval):
                result=broker.calc_metrics(f,pd.DataFrame(),100.,measurement_context=c,
                                          valuation_binding=b,date_range=interval,label='is')
                self.assertEqual(result['status'],nav.BLOCKED);self.assertEqual(result['reason'],reason)
        empty=broker.calc_metrics(f.iloc[:0],pd.DataFrame(),100.,measurement_context=c,label='is')
        self.assertEqual(empty['status'],nav.BLOCKED)
        # The unmodified default branch still uses its legacy subwindow anchoring.
        legacy=broker.calc_metrics(f,pd.DataFrame(),100.,date_range=('2026-01-03',None),label='is')
        self.assertEqual(legacy['status'],'completed');self.assertEqual(legacy['starting_capital_usd'],95.)

    def test_r5_hash_consistent_bad_IS_atomically_blocks_actual_replay_exports(self):
        import copy,hashlib
        from nav_metrics_v2_smoke import rows,context,binding
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);data=rows((9987.5,)*3)
        source_hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in [self.target,*self.cache.iterdir()]}
        full=context(data,anchor_nav=10000.)
        first=context(data[:2],anchor_nav=10000.);first['cutoff']=full['cutoff']
        oos=context(data[2:],anchor_nav=data[1]['nav'],anchor_time=data[1]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        oos2=context(data[1:2],anchor_nav=data[0]['nav'],anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        oos2['cutoff']=full['cutoff']
        package=dict(full=full,valuation_binding=binding(data),windows={'is':first,'oos':oos,'oos2':oos2})
        for include_oos2 in (False,True):
            options=dict(oos_start='2026-01-07')
            if include_oos2:options.update(oos2_start='2026-01-06',oos2_end='2026-01-06')
            good=self.run_replay(measurement_context=package,**options)
            self.assertEqual(good['status'],nav.COMPLETE,good)
            dest=self.out/nav.NAMESPACE;foreign=dest/'foreign.txt';foreign.write_bytes(b'preserve foreign')
            for variant,capital,kind in (('low',5000.,'PREFILL'),('high',20000.,'PREFILL'),
                                         ('first_postfee_NAV',9987.5,'PREFILL'),('kind',10000.,'OOS_PREDECESSOR')):
                with self.subTest(include_oos2=include_oos2,variant=variant):
                    bad=copy.deepcopy(package)
                    bad['windows']['is']=context(data[:2],anchor_nav=capital,anchor_kind=kind)
                    bad['windows']['is']['cutoff']=full['cutoff'];before=copy.deepcopy(bad)
                    result=self.run_replay(measurement_context=bad,**options)
                    self.assertEqual(result['status'],nav.BLOCKED,result)
                    self.assertEqual(result['execution_status'],'completed');self.assertEqual(result['trade_count'],1)
                    labels=('full','is','oos','oos2') if include_oos2 else ('full','is','oos')
                    for metric in (result,*(result['windows'][label] for label in labels)):
                        self.assertEqual(metric['status'],nav.BLOCKED);self.assertFalse(metric['metric_admission_complete'])
                        for field in nav.METRIC_FIELDS:self.assertIsNone(metric[field],field)
                        for field in ('start_date','end_date','interval_returns','first_interval_return',
                                      'measurement_context_sha256','input_rows_sha256','valuation_binding_provenance'):
                            self.assertNotIn(field,metric,field)
                        for field,value in nav.AUTHORITY.items():self.assertEqual(metric[field],value,field)
                    self.assertEqual(result['windows']['is']['reason'],'CALLER_PREFILL_ANCHOR_KIND' if variant=='kind'
                                     else 'CALLER_PREFILL_CAPITAL_MISMATCH')
                    self.assertFalse((dest/nav.CURVE_FILE).exists())
                    self.assertFalse((dest/nav.artifact_name('account_state_latest.json')).exists())
                    self.assertEqual(json.loads((dest/nav.METRICS_FILE).read_text()),result)
                    self.assertEqual(foreign.read_bytes(),b'preserve foreign');self.assertEqual(bad,before)
                    self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in source_hashes},source_hashes)
                    json.dumps(result,allow_nan=False)
            self.assertEqual(self.run_replay(measurement_context=package,**options)['status'],nav.COMPLETE)
        self.assertEqual(self.run_replay()['status'],'completed')
        from tools.execution_cost_model import ExecutionCostConfig
        failed=self.run_replay(measurement_context=bad,execution_cost_config=ExecutionCostConfig(mode='spread_adv_impact_v1'),**options)
        self.assertEqual(failed['metric_mode'],'DO_NOT_USE');self.assertTrue(failed['performance_fields_redacted'])
        self.assertNotIn('cagr',failed);json.dumps(failed,allow_nan=False)
        self.assertFalse((dest/nav.CURVE_FILE).exists())
        self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in source_hashes},source_hashes)


    def test_r6_actual_selected_decode_phases_preserve_inputs_and_foreign_outputs(self):
        import pyarrow as pa,pyarrow.parquet as pq
        from tools import nav_metrics_v2 as nav
        from tools.execution_cost_model import ExecutionCostConfig
        self.write_prices([100.]*4);original_target=self.target.read_bytes();price=self.cache/px_cache_name('AAA');original_price=price.read_bytes()
        dest=self.out/nav.NAMESPACE
        for role in ('target','rate','price','slippage','slippage_date'):
            for kind in (('utf8','parse','empty') if role in ('target','rate','slippage') else ('bad_magic','attrs') if role=='price' else ('date',)):
                with self.subTest(role=role,kind=kind):
                    self.target.write_bytes(original_target);price.write_bytes(original_price)
                    self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)
                    foreign=dest/'foreign.txt';foreign.write_bytes(b'keep');archive=dest/'archive';archive.mkdir(exist_ok=True);(archive/nav.CURVE_FILE).write_bytes(b'nested keep')
                    prior=(dest/nav.CURVE_FILE).read_bytes();options={};source=self.target if role=='target' else price if role=='price' else self.root/(role+'.csv')
                    if role in ('rate','slippage','slippage_date'):
                        if role=='rate':options.update(cash_carry_config=CashCarryConfig(mode='risk_free_rate',rate_path=source),reserve_mode='DGS3MO_CARRY')
                        else:options['execution_cost_config']=ExecutionCostConfig(mode='spread_adv_impact_v1',paper_slippage_path=source)
                    if kind=='attrs':
                        table=pa.Table.from_pandas(pd.read_parquet(price));meta=dict(table.schema.metadata or {});meta[b'PANDAS_ATTRS']=b'{' ;pq.write_table(table.replace_schema_metadata(meta),source)
                    elif kind=='date':source.write_bytes(b'date,ticker,side,observed_slippage_bps\n2026-99-99,AAA,BUY,1\n')
                    else:source.write_bytes({'utf8':b'a,b\n\xff,1\n','parse':b'a,b\n"unfinished','empty':b'','bad_magic':b'bad parquet'}[kind])
                    before={p:p.read_bytes() for p in [self.target,*self.cache.iterdir(),source]}
                    try:result=self.run_replay(measurement_context=self.measurement(),**options)
                    except Exception as exc:self.fail('Actual replay decoder escaped: '+type(exc).__name__)
                    self.assertEqual(result['status'],nav.BLOCKED,result);self.assertEqual(result['reason'],'RESEARCH_IO_FAILURE')
                    self.assertFalse(result['metric_admission_complete']);self.assertFalse(result['current_publication_complete'])
                    for field in nav.METRIC_FIELDS:self.assertIsNone(result[field])
                    for field,value in nav.AUTHORITY.items():self.assertEqual(result[field],value)
                    if role=='target':self.assertFalse(result['cleanup_complete']);self.assertEqual((dest/nav.CURVE_FILE).read_bytes(),prior)
                    else:self.assertTrue(result['cleanup_complete']);self.assertFalse((dest/nav.CURVE_FILE).exists())
                    self.assertEqual(foreign.read_bytes(),b'keep');self.assertEqual((archive/nav.CURVE_FILE).read_bytes(),b'nested keep')
                    self.assertEqual({p:p.read_bytes() for p in before},before);json.dumps(result,allow_nan=False)
        self.target.write_bytes(original_target);price.write_bytes(original_price)
        self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)

    def test_r6_actual_broker_cli_decoder_failure_has_finite_incomplete_disclosure(self):
        import subprocess
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);context_path=self.root/'context.json';context_path.write_text(json.dumps(self.measurement()))
        self.target.write_bytes(b'a\n\xff\n');before=self.target.read_bytes();dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        leaf=dest/nav.CURVE_FILE;leaf.write_bytes(b'prior');foreign=dest/'foreign';foreign.write_bytes(b'keep')
        cmd=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(ROOT/'tools/run_broker_ledger_replay.py'),
             '--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),
             '--cash-carry-mode','none','--nav-metrics-context',str(context_path)]
        child=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(child.returncode,2,child.stderr);self.assertNotIn('Traceback',child.stderr)
        result=json.loads(child.stdout,parse_constant=lambda x:self.fail(x));self.assertEqual(result['status'],nav.BLOCKED)
        self.assertEqual(result['selected_input_cause'],'UnicodeDecodeError');self.assertFalse(result['current_publication_complete'])
        self.assertFalse(result['cleanup_complete']);self.assertEqual(leaf.read_bytes(),b'prior');self.assertEqual(foreign.read_bytes(),b'keep')
        self.assertEqual(self.target.read_bytes(),before);self.assertFalse(result['fullrun_allowed'])



    def test_attrs_actual_replay_and_cli_preserve_null_incomplete_input_and_aliases(self):
        import subprocess,pyarrow as pa,pyarrow.parquet as pq
        from tools import nav_metrics_v2 as nav
        from tools.execution_cost_model import ExecutionCostConfig
        self.write_prices([100.]*4);price=self.cache/px_cache_name('AAA');pristine=price.read_bytes();table=pa.Table.from_pandas(pd.read_parquet(price))
        dest=self.out/nav.NAMESPACE
        for role in ('price','rate','slippage'):
            for raw in (b'[1]',b'null',b'1',b'"x"',b'[[1]]'):
                with self.subTest(role=role,raw=raw):
                    price.write_bytes(pristine);self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)
                    foreign=dest/'foreign';foreign.write_bytes(b'keep');archive=dest/'archive';archive.mkdir(exist_ok=True);(archive/'note').write_bytes(b'nested keep')
                    source=price if role=='price' else self.root/(role+'.parquet')
                    evidence=table if role=='price' else pa.Table.from_pandas(pd.DataFrame(dict(date=['2026-01-02'],ticker=['AAA'],side=['BUY'],observed_slippage_bps=[1.],value=[4.])))
                    pq.write_table(evidence.replace_schema_metadata({**(evidence.schema.metadata or {}),b'PANDAS_ATTRS':raw}),source)
                    options=dict(cash_carry_config=CashCarryConfig(mode='risk_free_rate',rate_path=source),reserve_mode='DGS3MO_CARRY') if role=='rate' else dict(execution_cost_config=ExecutionCostConfig(mode='spread_adv_impact_v1',paper_slippage_path=source)) if role=='slippage' else {}
                    before={p:p.read_bytes() for p in [self.target,*self.cache.iterdir(),source]}
                    result=self.run_replay(measurement_context=self.measurement(),**options)
                    self.assertEqual(result['status'],nav.BLOCKED,result);self.assertEqual(result['selected_input_cause'],'PandasAttrsShape')
                    self.assertEqual(result['selected_input_reason'],'SELECTED_INPUT_PARQUET_ATTRS');self.assertFalse(result['current_publication_complete'])
                    self.assertTrue(result['cleanup_complete']);self.assertFalse(result['metric_admission_complete'])
                    for field in nav.METRIC_FIELDS:self.assertIsNone(result[field])
                    for field,value in nav.AUTHORITY.items():self.assertEqual(result[field],value)
                    self.assertFalse((dest/nav.CURVE_FILE).exists());self.assertEqual({p:p.read_bytes() for p in before},before)
                    self.assertEqual(foreign.read_bytes(),b'keep');self.assertEqual((archive/'note').read_bytes(),b'nested keep');json.dumps(result,allow_nan=False)
        context=self.root/'attrs-context.json';context.write_text(json.dumps(self.measurement()))
        cmd=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(ROOT/'tools/run_broker_ledger_replay.py'),'--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),'--cash-carry-mode','none','--nav-metrics-context',str(context)]
        pq.write_table(table.replace_schema_metadata({**(table.schema.metadata or {}),b'PANDAS_ATTRS':b'[[1]]'}),price)
        # Child must hit the actual malformed selected price reader.
        child=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(child.returncode,2,child.stderr);self.assertNotIn('Traceback',child.stderr)
        result=json.loads(child.stdout);self.assertEqual(result['selected_input_cause'],'PandasAttrsShape');self.assertFalse(result['current_publication_complete'])
        self.assertFalse(result['metric_admission_complete']);self.assertFalse((dest/nav.CURVE_FILE).exists())
        # A reverse cache/output hard alias is refused before deletion or parsing.
        price.write_bytes(pristine);leaf=dest/nav.CURVE_FILE;leaf.write_bytes(pristine);price.unlink();__import__('os').link(leaf,price)
        before=price.read_bytes();result=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(result['status'],nav.COMPLETE);self.assertEqual(price.read_bytes(),before)
        self.assertEqual(foreign.read_bytes(),b'keep');self.assertTrue(leaf.exists())
        # Removing one generated hard-link name preserves the still-linked input.
        with __import__('unittest').mock.patch.object(self,'out',self.cache):
            refused=self.run_replay(measurement_context=self.measurement())
        self.assertEqual(refused['status'],nav.BLOCKED);self.assertFalse(refused['cleanup_complete'])
        self.assertEqual(price.read_bytes(),before)
        price.unlink();price.write_bytes(pristine);self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)

    def test_API_path_flag_admits_selected_file_missing_formats_and_precedence(self):
        import json,copy
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav, run_weekly_evaluation as weekly
        is_broker = True
        if is_broker:self.write_prices([100.]*4)
        call = self.run_replay if is_broker else lambda **k: weekly.run(self.latest,self.out,self.cache,**k)
        key = 'measurement_context' if is_broker else 'measurement_contexts'
        path=self.root/'API-context.json';good=self.measurement()
        cases=[('none',None,'CONTEXT_PATH_REQUIRED'),('missing',path,'CONTEXT_INPUT_IO'),
               ('json',path,'CONTEXT_JSON'),('utf8',path,'CONTEXT_JSON'),
               ('shape',path,'CONTEXT_TYPE'),('duplicate',path,'JSON_DUPLICATE'),
               ('nonfinite',path,'NUMBER_NONFINITE'),('deep',path,'RESOURCE_TREE')]
        for kind,selected,reason in cases:
            for supplied in (None,{},good):
                with self.subTest(kind=kind,object_is_none=supplied is None,object_is_empty=supplied=={}):
                    path.unlink(missing_ok=True)
                    raw={'json':b'{','utf8':b'\xff','shape':b'[]','duplicate':b'{"x":1,"x":2}',
                         'nonfinite':b'{"x":NaN}','deep':b'['*20+b'0'+b']'*20}.get(kind)
                    if raw is not None:path.write_bytes(raw)
                    self.out=self.root/('API-format-'+kind+str(supplied is None)+str(supplied=={}))
                    dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
                    leaf=dest/(nav.METRICS_FILE if is_broker else 'weekly_metrics.research_v2.json')
                    leaf.write_bytes(b'prior');foreign=dest/'foreign';foreign.write_bytes(b'keep')
                    inputs={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and not p.is_relative_to(self.out)}
                    observed=[];original=nav.observe_research_publication
                    def observe(*a,**k):observed.append(nav.research_io_active());return original(*a,**k)
                    with patch.object(nav,'observe_research_publication',side_effect=observe),patch.object(nav,'load_context',wraps=nav.load_context) as loader:
                        result=call(**{key:supplied},measurement_context_path=selected,load_measurement_context_from_path=True)
                    self.assertTrue(observed);self.assertTrue(all(observed));self.assertEqual(loader.call_count,0 if kind=='none' else 1)
                    self.assertEqual(result['status'],nav.BLOCKED);self.assertEqual(result['context_input_reason'],reason)
                    self.assertEqual(result['metric_mode'],nav.MODE);self.assertFalse(result['metric_admission_complete'])
                    self.assertFalse(result['current_publication_complete']);self.assertFalse(result['cleanup_complete'])
                    for field in nav.METRIC_FIELDS:self.assertIsNone(result[field])
                    for field,value in nav.AUTHORITY.items():self.assertEqual(result[field],value)
                    self.assertEqual(leaf.read_bytes(),b'prior');self.assertEqual(foreign.read_bytes(),b'keep')
                    self.assertEqual({p:p.read_bytes() for p in inputs},inputs);json.dumps(result,allow_nan=False)
                    self.assertEqual({p.name for p in self.out.iterdir()},{nav.NAMESPACE})
        for kind in ('directory','oversize'):
            with self.subTest(kind=kind):
                selected=self.root/('API-'+kind)
                if kind=='directory':selected.mkdir()
                else:
                    with selected.open('wb') as handle:handle.truncate(nav.MAX_BYTES+1)
                self.out=self.root/('API-resource-'+kind)
                result=call(measurement_context_path=selected,load_measurement_context_from_path=True)
                self.assertEqual(result['status'],nav.BLOCKED)
                self.assertEqual(result['context_input_reason'],'CONTEXT_NOT_REGULAR' if kind=='directory' else 'RESOURCE_BYTES')
                self.assertFalse(result['current_publication_complete']);self.assertFalse(self.out.exists())
                self.assertEqual(selected.stat().st_size,nav.MAX_BYTES+1) if kind=='oversize' else self.assertTrue(selected.is_dir())
        path.write_text(json.dumps(good));before=path.read_bytes()
        for supplied in (None,{}, {'deliberately_invalid_object':'selected file takes precedence'}):
            self.out=self.root/('API-valid-'+str(supplied is None)+str(supplied=={}))
            with patch.object(nav,'load_context',wraps=nav.load_context) as loader:
                result=call(**{key:supplied},measurement_context_path=path,load_measurement_context_from_path=True)
            self.assertEqual(result['status'],nav.COMPLETE,result);self.assertEqual(loader.call_count,1)
            self.assertFalse(result['valid_for_production']);self.assertTrue(result['metric_admission_complete'])
            self.assertEqual(path.read_bytes(),before);self.assertEqual({p.name for p in self.out.iterdir()},{nav.NAMESPACE})

    def test_API_path_flag_guard_IO_strict_read_cost_cleanup_and_programming(self):
        import json,errno,os
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav, run_weekly_evaluation as weekly, run_broker_ledger_replay as broker
        from tools.execution_cost_model import ExecutionCostConfig
        is_broker = True
        if is_broker:self.write_prices([100.]*4)
        call=self.run_replay if is_broker else lambda **k: weekly.run(self.latest,self.out,self.cache,**k)
        path=self.root/'API-IO-context.json';path.write_text(json.dumps(self.measurement()))
        options=dict(measurement_context_path=path,load_measurement_context_from_path=True)
        for fault in ('open','changed'):
            self.out=self.root/('API-IO-'+fault);dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
            leaf=dest/nav.CURVE_FILE if is_broker else dest/'weekly_equity_curve.research_v2.csv';leaf.write_bytes(b'prior')
            foreign=dest/'foreign';foreign.write_bytes(b'keep');original_open=nav.os.open;original_fstat=nav.os.fstat;fds=set();observed=[]
            def opened(p,*a,**k):
                if Path(p)==path:
                    self.assertTrue(nav.research_io_active());observed.append('open')
                    if fault=='open':raise PermissionError(errno.EACCES,'controlled boundary injection')
                fd=original_open(p,*a,**k)
                if Path(p)==path:fds.add(fd)
                return fd
            def fstat(fd):
                value=original_fstat(fd)
                if fd in fds and fault=='changed':return SimpleNamespace(st_mode=value.st_mode,st_dev=value.st_dev,st_ino=value.st_ino,st_size=value.st_size,st_mtime_ns=value.st_mtime_ns+1)
                return value
            before=path.read_bytes()
            with patch.object(nav.os,'open',side_effect=opened),patch.object(nav.os,'fstat',side_effect=fstat):result=call(**options)
            self.assertTrue(observed);self.assertEqual(result['reason'],'RESEARCH_IO_FAILURE')
            self.assertEqual(result['context_input_reason'],'CONTEXT_INPUT_IO' if fault=='open' else 'CONTEXT_FILE_CHANGED')
            self.assertFalse(result['current_publication_complete']);self.assertFalse(result['cleanup_complete'])
            self.assertEqual(leaf.read_bytes(),b'prior');self.assertEqual(foreign.read_bytes(),b'keep');self.assertEqual(path.read_bytes(),before)
        source=self.target if is_broker else self.reports/'main_monthly_weights.csv'
        price=self.cache/weekly.px_cache_name('AAA')
        for role in ('beforecleanup','aftercleanup','unlink'):
            with self.subTest(role=role):
                self.out=self.root/('API-stage-'+role);dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
                leaf=dest/(nav.CURVE_FILE if is_broker else 'weekly_equity_curve.research_v2.csv');leaf.write_bytes(b'prior')
                foreign=dest/'foreign';foreign.write_bytes(b'keep');original=source.read_bytes();price_original=price.read_bytes()
                if role=='beforecleanup':source.write_bytes(b'a\n\xff\n')
                if role=='aftercleanup':price.write_bytes(b'corrupt parquet')
                original_unlink=Path.unlink
                def unlink(p,*a,**k):
                    if p==leaf:raise PermissionError(errno.EACCES,'controlled cleanup injection')
                    return original_unlink(p,*a,**k)
                try:
                    before_source=source.read_bytes();before_price=price.read_bytes()
                    if role=='unlink':
                        with patch.object(Path,'unlink',unlink):result=call(**options)
                    else:result=call(**options)
                    self.assertEqual(result['status'],nav.BLOCKED);self.assertEqual(result['reason'],'RESEARCH_IO_FAILURE')
                    self.assertFalse(result['current_publication_complete']);self.assertFalse(result['metric_admission_complete'])
                    self.assertEqual(foreign.read_bytes(),b'keep');self.assertEqual(source.read_bytes(),before_source);self.assertEqual(price.read_bytes(),before_price)
                    if role=='aftercleanup':self.assertTrue(result['cleanup_complete']);self.assertFalse(leaf.exists())
                    else:self.assertFalse(result['cleanup_complete']);self.assertEqual(leaf.read_bytes(),b'prior')
                    for name in nav.METRIC_FIELDS:self.assertIsNone(result[name])
                    json.dumps(result,allow_nan=False)
                finally:source.write_bytes(original);price.write_bytes(price_original)
        self.out=self.root/'API-strict-state';states=[]
        original_reader=weekly.load_price_series
        def read(*a,**k):states.append((nav.research_io_active(),k.get('strict_io',False)));return original_reader(*a,**k)
        target_module=broker if is_broker else weekly
        with patch.object(target_module,'load_price_series',side_effect=read):result=call(**options)
        self.assertEqual(result['status'],nav.COMPLETE,result);self.assertTrue(states);self.assertTrue(all(x[0] for x in states))
        if not is_broker:self.assertTrue(all(x[1] for x in states))
        if is_broker:
            self.out=self.root/'API-strict-cost';seen=[];original_model=broker.ExecutionCostModel
            def model(*a,**k):seen.append(k.get('strict_io'));return original_model(*a,**k)
            cfg=ExecutionCostConfig(mode='spread_adv_impact_v1',paper_slippage_path=self.root/'selected-missing-slippage.csv')
            with patch.object(broker,'ExecutionCostModel',side_effect=model):result=call(**options,execution_cost_config=cfg)
            self.assertEqual(result['status'],nav.BLOCKED);self.assertEqual(result['reason'],'RESEARCH_IO_FAILURE');self.assertEqual(seen,[True])
        for cls in (RuntimeError,TypeError,ValueError):
            exc=cls('unchanged programmer failure');self.out=self.root/('API-program-'+cls.__name__)
            with patch.object(nav,'load_context',side_effect=exc):
                with self.assertRaises(cls) as got:call(**options)
            self.assertIs(got.exception,exc)

    def test_API_path_flag_preserves_defaults_signature_bindings_and_collisions(self):
        import json,inspect,os
        from unittest.mock import patch
        from tools import nav_metrics_v2 as nav, run_weekly_evaluation as weekly, run_broker_ledger_replay as broker
        is_broker = True
        if is_broker:self.write_prices([100.]*4)
        call=self.run_replay if is_broker else lambda **k: weekly.run(self.latest,self.out,self.cache,**k)
        key='measurement_context' if is_broker else 'measurement_contexts';path=self.root/'API-protection-only.json';path.write_bytes(b'{')
        self.out=self.root/'API-legacy-default';baseline=call()
        curve=self.out/('equity_curve.csv' if is_broker else 'weekly_equity_curve.csv');curve_before=curve.read_bytes()
        with patch.object(nav,'load_context',side_effect=AssertionError('unselected file must not load')):
            legacy=call(measurement_context_path=path,load_measurement_context_from_path=False)
        self.assertEqual(legacy,baseline);self.assertEqual(curve.read_bytes(),curve_before);self.assertFalse((self.out/nav.NAMESPACE).exists())
        self.assertEqual(path.read_bytes(),b'{');self.out=self.root/'API-object-no-reload'
        with patch.object(nav,'load_context',side_effect=AssertionError('protection path must not reload')):
            result=call(**{key:self.measurement()},measurement_context_path=path,load_measurement_context_from_path=False)
        self.assertEqual(result['status'],nav.COMPLETE,result);self.assertEqual(path.read_bytes(),b'{')
        path.write_text(json.dumps(self.measurement()))
        if not is_broker:
            for keyword in (False,True):
                self.out=self.root/('API-binding-'+str(keyword))
                opts=dict(measurement_context_path=path,load_measurement_context_from_path=True)
                if keyword:result=weekly.run(latest_run=self.latest,output_dir=self.out,price_cache=self.cache,**opts)
                else:result=weekly.run(self.latest,self.out,self.cache,**opts)
                self.assertEqual(result['status'],nav.COMPLETE)
                bound=inspect.signature(weekly.run).bind(self.latest,self.out,self.cache,**opts)
                self.assertEqual(bound.arguments['measurement_context_path'],path)
        else:
            self.assertTrue(all(p.kind==inspect.Parameter.KEYWORD_ONLY for p in inspect.signature(broker.replay).parameters.values()))
            with self.assertRaises(TypeError):broker.replay(self.target,self.cache,self.out)
        self.out=self.root/'API-selected-collision';dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        selected=dest/(nav.METRICS_FILE if is_broker else 'weekly_metrics.research_v2.json');selected.write_bytes(path.read_bytes());before=selected.read_bytes()
        with patch.object(nav,'load_context',side_effect=AssertionError('collision must refuse before load')):
            result=call(measurement_context_path=selected,load_measurement_context_from_path=True)
        self.assertEqual(result['status'],nav.BLOCKED);self.assertFalse(result['current_publication_complete']);self.assertEqual(selected.read_bytes(),before)
        self.out=self.cache/'API-refused';dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        leaf=dest/(nav.CURVE_FILE if is_broker else 'weekly_equity_curve.research_v2.csv');leaf.write_bytes(b'cache input')
        with patch.object(nav,'load_context',side_effect=AssertionError('cache output must refuse before load')):
            result=call(measurement_context_path=path,load_measurement_context_from_path=True)
        self.assertEqual(result['status'],nav.BLOCKED);self.assertEqual(leaf.read_bytes(),b'cache input');self.assertFalse(result['cleanup_complete'])
        self.out=self.root/'API-reverse-resolved-alias';dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        leaf=dest/(nav.CURVE_FILE if is_broker else 'weekly_equity_curve.research_v2.csv')
        price=self.cache/weekly.px_cache_name('AAA');pristine=price.read_bytes();leaf.write_bytes(pristine)
        original_resolve=Path.resolve
        def resolve(p,*a,**k):
            return original_resolve(leaf,*a,**k) if p==price else original_resolve(p,*a,**k)
        # Controlled resolved reverse-link boundary, not a privileged Windows file symlink.
        with patch.object(Path,'resolve',resolve):result=call(measurement_context_path=path,load_measurement_context_from_path=True)
        self.assertEqual(result['status'],nav.BLOCKED);self.assertFalse(result['cleanup_complete'])
        self.assertEqual(leaf.read_bytes(),pristine);self.assertEqual(price.read_bytes(),pristine)
        self.out=self.root/'API-safe-hardlink';dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
        leaf=dest/(nav.CURVE_FILE if is_broker else 'weekly_equity_curve.research_v2.csv');os.link(price,leaf)
        result=call(measurement_context_path=path,load_measurement_context_from_path=True)
        self.assertEqual(result['status'],nav.COMPLETE,result);self.assertEqual(price.read_bytes(),pristine)

    def test_API_path_flag_keeps_actual_CLI_selected_file_compatibility(self):
        import json,subprocess
        from tools import nav_metrics_v2 as nav
        is_broker = True
        if is_broker:self.write_prices([100.]*4)
        path=self.root/'API-CLI-context.json';path.write_text(json.dumps(self.measurement()));before=path.read_bytes()
        for valid in (True,False):
            self.out=self.root/('API-CLI-'+str(valid))
            selected=path if valid else self.root/'API-CLI-missing.json'
            cmd=[sys.executable]+(['-O'] if sys.flags.optimize else [])
            if is_broker:
                cmd += [str(ROOT/'tools/run_broker_ledger_replay.py'),'--target-book',str(self.target),'--price-cache',str(self.cache),
                        '--output-dir',str(self.out),'--starting-capital','10000','--fill-mode','next_close','--cash-carry-mode','none',
                        '--oos-start','','--oos2-start','']
            else:
                cmd += [str(ROOT/'tools/run_weekly_evaluation.py'),'--latest-run',str(self.latest),'--output-dir',str(self.out),'--price-cache',str(self.cache)]
            cmd += ['--nav-metrics-context',str(selected)]
            child=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(child.returncode,0 if valid else 2,child.stderr+child.stdout);self.assertNotIn('Traceback',child.stderr)
            result=json.loads(child.stdout,parse_constant=lambda x:self.fail(x));self.assertEqual(result['status'],nav.COMPLETE if valid else nav.BLOCKED)
            self.assertFalse(result['valid_for_production']);self.assertEqual(path.read_bytes(),before)
            self.assertEqual({p.name for p in self.out.iterdir()},{nav.NAMESPACE}) if valid else self.assertFalse(self.out.exists())




    def test_atomic_top_refusal_masks_every_requested_window_and_actual_CLI_defaults(self):
        import copy,subprocess,pandas_market_calendars as mcal
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context,binding
        schedule=mcal.get_calendar('NYSE').schedule(start_date='2022-12-29',end_date='2024-07-02')
        pd.DataFrame({'Close':100.,'Adj Close':100.,'Open':100.},index=schedule.index).to_parquet(self.cache/broker.px_cache_name('AAA'))
        pd.DataFrame([dict(rebalance_date='2022-12-29',ticker='AAA',weight=.5)]).to_csv(self.target,index=False)
        data=[dict(session=str(d.date()),timestamp=t.isoformat(),nav=9987.5) for d,t in schedule['market_close'].iloc[1:].items()]
        prefill=schedule['market_close'].iloc[0].isoformat();full=context(data,anchor_nav=10000.,anchor_time=prefill)
        def interval(lo,hi=None):
            chosen=[r for r in data if (lo is None or r['session']>=lo) and (hi is None or r['session']<=hi)]
            position=data.index(chosen[0]);previous=data[position-1] if position else None
            value=context(chosen,anchor_nav=previous['nav'] if previous else 10000.,anchor_time=previous['timestamp'] if previous else prefill,anchor_kind='OOS_PREDECESSOR' if previous else 'PREFILL')
            value['cutoff']=full['cutoff'];return value
        good=dict(full=full,valuation_binding=binding(data),windows={'is':interval(None,'2024-06-30'),'oos':interval(broker.DEFAULT_OOS_START),'oos2':interval(broker.DEFAULT_OOS2_START,'2024-06-30')})
        target_before=self.target.read_bytes();cache_before={p.name:p.read_bytes() for p in self.cache.iterdir()}
        for kind in ('healthy','unknown_root','full_RF','binding_hash'):
            for route in ('API','CLI'):
                with self.subTest(kind=kind,route=route):
                    package=copy.deepcopy(good)
                    if kind=='unknown_root':package['misspelled']='unknown'
                    elif kind=='full_RF':package['full']['risk_free']['ref']['sha256']='0'*64
                    elif kind=='binding_hash':package['valuation_binding']['ref']['sha256']='0'*64
                    self.out=self.root/('atomic-'+kind+route);dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
                    foreign=dest/'foreign';foreign.write_bytes(b'keep');nested=dest/'archive';nested.mkdir();(nested/'keep').write_bytes(b'nested')
                    selected=self.root/('atomic-context-'+kind+route+'.json');selected.write_text(json.dumps(package),encoding='utf-8');before=selected.read_bytes()
                    if route=='API':result=self.run_replay(measurement_context=package,oos_start=broker.DEFAULT_OOS_START,oos2_start=broker.DEFAULT_OOS2_START)
                    else:
                        cmd=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(ROOT/'tools/run_broker_ledger_replay.py'),'--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),'--starting-capital','10000','--fill-mode','next_close','--cost-bps','25','--cash-carry-mode','none','--nav-metrics-context',str(selected)]
                        child=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=90)
                        self.assertEqual(child.returncode,0 if kind=='healthy' else 2,child.stderr+child.stdout);self.assertNotIn('Traceback',child.stderr)
                        result=json.loads(child.stdout,parse_constant=lambda x:self.fail(x))
                    self.assertTrue({'status','full','is','oos','oos2'}<=set(result['windows']))
                    if kind=='healthy':self.assertEqual({result['windows'][k]['status'] for k in ('full','is','oos','oos2')},{nav.COMPLETE})
                    else:
                        self.assertEqual(result['status'],nav.BLOCKED,result);self.assertFalse(result['metric_admission_complete'])
                        if kind=='unknown_root':self.assertEqual(result['reason'],'MEASUREMENT_PACKAGE_FIELDS')
                        for metric in (result,*(result['windows'][k] for k in ('full','is','oos','oos2'))):
                            self.assertEqual(metric['status'],nav.BLOCKED);self.assertEqual(metric['reason'],result['reason'])
                            for field in nav.METRIC_FIELDS:self.assertIsNone(metric[field])
                            for field in ('interval_returns','start_date','end_date','measurement_context_sha256','input_rows_sha256','valuation_binding_provenance','ending_timestamp','anchor_timestamp'):self.assertNotIn(field,metric)
                        self.assertFalse((dest/nav.CURVE_FILE).exists());self.assertFalse((dest/nav.artifact_name('account_state_latest.json')).exists())
                    self.assertEqual(json.loads((dest/nav.METRICS_FILE).read_text()),result)
                    self.assertEqual(foreign.read_bytes(),b'keep');self.assertEqual((nested/'keep').read_bytes(),b'nested')
                    self.assertEqual(selected.read_bytes(),before);self.assertEqual(self.target.read_bytes(),target_before)
                    self.assertEqual({p.name:p.read_bytes() for p in self.cache.iterdir()},cache_before)
                    json.dumps(result,allow_nan=False)

    def test_recursive_research_geometry_and_prepare_helper_keep_legacy_semantics(self):
        import errno,os
        from unittest.mock import patch
        from contextlib import nullcontext
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);path=self.root/'atomic-geometry-context.json';path.write_text(json.dumps(self.measurement()));before=path.read_bytes()
        for location in ('selected','output','generated'):
            with self.subTest(location=location):
                self.out=self.root/('geometry-'+location);dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True)
                leaf=dest/nav.CURVE_FILE;leaf.write_bytes(b'prior');foreign=dest/'foreign';foreign.write_bytes(b'foreign')
                selected=path
                if location=='selected':
                    selected=self.root/'selected-self-loop'
                    try:os.symlink(selected,selected)
                    except OSError as error:
                        self.assertIn(getattr(error,'winerror',None),(5,1314));continue
                original=Path.resolve
                def denied(p,*a,**k):
                    if location=='output' and p==dest or location=='generated' and p==leaf:raise OSError(errno.ELOOP,'controlled native OS boundary')
                    return original(p,*a,**k)
                with (nullcontext() if location=='selected' else patch.object(Path,'resolve',denied)):result=self.run_replay(measurement_context_path=selected,load_measurement_context_from_path=True)
                self.assertEqual(result['status'],nav.BLOCKED,result);self.assertFalse(result['current_publication_complete'])
                self.assertFalse(result['cleanup_complete']);self.assertIn(nav.CURVE_FILE,result['uncleared_generated_outputs'])
                self.assertEqual(leaf.read_bytes(),b'prior');self.assertEqual(foreign.read_bytes(),b'foreign');self.assertEqual(path.read_bytes(),before)
                if location=='selected':
                    import subprocess
                    cmd=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(ROOT/'tools/run_broker_ledger_replay.py'),'--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),'--starting-capital','10000','--fill-mode','next_close','--cash-carry-mode','none','--oos-start','','--oos2-start','','--nav-metrics-context',str(selected)]
                    child=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=60)
                    self.assertEqual(child.returncode,2,child.stderr+child.stdout);self.assertNotIn('Traceback',child.stderr)
                    self.assertEqual(json.loads(child.stdout)['status'],nav.BLOCKED);self.assertEqual(leaf.read_bytes(),b'prior')
        for strict in (False,True):
            for phase in ('safe','collision','resolve_failure'):
                with self.subTest(strict=strict,phase=phase):
                    out=self.root/('prepare-'+str(strict)+phase);out.mkdir();generated=out/'generated';generated.write_bytes(b'prior');protected=self.root/'input';protected.write_bytes(b'input')
                    original=Path.resolve;seen=[];declared=generated if phase=='collision' else protected
                    def selected(p):seen.append(p);return original(p)
                    if phase=='resolve_failure':
                        error=OSError(errno.ELOOP,'controlled prepare geometry failure')
                        target='resolve_research_path' if strict else 'resolve';owner=nav if strict else Path
                        with patch.object(owner,target,side_effect=error),self.assertRaises(OSError) as caught:broker.prepare_generated_outputs(out,('generated',),input_paths=(protected,),strict_io=strict)
                        self.assertIs(caught.exception,error);self.assertEqual(generated.read_bytes(),b'prior')
                    elif strict:
                        with patch.object(nav,'resolve_research_path',side_effect=selected):_,collision=broker.prepare_generated_outputs(out,('generated',),input_paths=(declared,),strict_io=True)
                        self.assertIn(declared,seen);self.assertGreaterEqual(seen.count(generated),2);self.assertEqual(collision,phase=='collision')
                    else:
                        with patch.object(nav,'resolve_research_path',side_effect=AssertionError('legacy must not route through research helper')):_,collision=broker.prepare_generated_outputs(out,('generated',),input_paths=(declared,))
                        self.assertEqual(collision,phase=='collision')
                    if phase=='safe':self.assertFalse(generated.exists())
                    else:self.assertEqual(generated.read_bytes(),b'prior')
                    self.assertEqual(protected.read_bytes(),b'input')
        error=RuntimeError('unrelated program')
        with patch.object(nav,'resolve_research_path',side_effect=error),self.assertRaises(RuntimeError) as caught:self.run_replay(measurement_context=self.measurement())
        self.assertIs(caught.exception,error)


    def test_strict_nonempty_slippage_required_groups_preserve_aliases_empty_and_program_errors(self):
        from itertools import combinations
        from tools.execution_cost_model import load_paper_slippage
        groups=('date','ticker','side','observed_slippage_bps')
        good=dict(date=['2026-01-05'],ticker=['aaa'],side=['buy'],observed_slippage_bps=[0.])
        for suffix in ('.csv','.parquet'):
            path=self.root/('schema'+suffix)
            for size in range(1,5):
                for missing in combinations(groups,size):
                    with self.subTest(format=suffix,missing=missing):
                        raw=pd.DataFrame({k:v for k,v in good.items() if k not in missing} or {'other':[1]})
                        if suffix=='.csv':raw.to_csv(path,index=False)
                        else:raw.to_parquet(path,index=False)
                        before=path.read_bytes()
                        with self.assertRaises(OSError) as caught:load_paper_slippage(path,strict_io=True)
                        self.assertEqual(caught.exception.selected_input_reason,'SELECTED_INPUT_SLIPPAGE_SCHEMA')
                        self.assertEqual(caught.exception.selected_input_cause,'SlippageRequiredColumns')
                        self.assertTrue(load_paper_slippage(path).empty);self.assertEqual(path.read_bytes(),before)
            for date_col in ('date','fill_date','executed_at'):
                for value_col in ('observed_slippage_bps','implementation_shortfall_bps','slippage_bps'):
                    with self.subTest(format=suffix,date=date_col,value=value_col):
                        raw=pd.DataFrame({date_col:['2026-01-05'], 'ticker':['aaa'], 'side':['buy'],value_col:['0'],'unused':['x']})
                        if suffix=='.csv':raw.to_csv(path,index=False)
                        else:raw.to_parquet(path,index=False)
                        strict=load_paper_slippage(path,strict_io=True);old=load_paper_slippage(path)
                        pd.testing.assert_frame_equal(strict,old);self.assertEqual(len(strict),1)
            empty=pd.DataFrame(columns=['other'])
            if suffix=='.csv':empty.to_csv(path,index=False)
            else:empty.to_parquet(path,index=False)
            self.assertTrue(load_paper_slippage(path,strict_io=True).empty)
            reader='read_csv' if suffix=='.csv' else 'read_parquet'
            for error in (AttributeError('program'),ValueError('SELECTED_INPUT_SLIPPAGE_SCHEMA'),TypeError('backend')):
                with patch.object(pd,reader,side_effect=error),self.assertRaises(type(error)) as caught:
                    load_paper_slippage(path,strict_io=True)
                self.assertIs(caught.exception,error)
        self.assertTrue(load_paper_slippage(None,strict_io=True).empty)
        self.assertTrue(load_paper_slippage(self.root/'absent-optional.csv').empty)
        with self.assertRaises(FileNotFoundError):load_paper_slippage(self.root/'absent-selected.csv',strict_io=True)

    def test_strict_slippage_schema_reaches_atomic_replay_refusal_and_real_CLI(self):
        import json,subprocess,sys
        from tools import nav_metrics_v2 as nav
        from nav_metrics_v2_smoke import context,binding
        from tools.execution_cost_model import ExecutionCostConfig
        idx=pd.bdate_range('2025-12-01','2026-01-07')
        px=pd.DataFrame({'Open':100.,'Close':100.,'Adj Close':100.,'High':100.,'Low':100.,'Volume':1000000},index=idx)
        for ticker in ('AAA','SPY','QQQ'):px.to_parquet(self.cache/px_cache_name(ticker))
        baseline=self.run_replay(execution_cost_config=ExecutionCostConfig(mode='spread_adv_impact_v1'))
        self.assertEqual(baseline['status'],'completed',baseline)
        df=pd.read_csv(self.out/'equity_curve.csv')
        data=[dict(session=r.date,timestamp=r.date+'T21:00:00Z',nav=r.equity_usd) for r in df.itertuples()]
        receipt=dict(full=context(data,anchor_nav=10000.),valuation_binding=binding(data))
        source_before={p:p.read_bytes() for p in self.cache.iterdir() if p.is_file()};target_before=self.target.read_bytes()
        for suffix in ('.csv','.parquet'):
            with self.subTest(format=suffix):
                path=self.root/('selected-schema'+suffix)
                good=pd.DataFrame([dict(date='2026-01-05',ticker='AAA',side='BUY',observed_slippage_bps=0.)])
                if suffix=='.csv':good.to_csv(path,index=False)
                else:good.to_parquet(path,index=False)
                cfg=ExecutionCostConfig(mode='spread_adv_impact_v1',paper_slippage_path=path)
                self.assertEqual(self.run_replay(execution_cost_config=cfg,measurement_context=receipt)['status'],nav.COMPLETE)
                dest=self.out/nav.NAMESPACE;foreign=dest/'foreign';foreign.write_bytes(b'foreign')
                malformed=good.drop(columns=['observed_slippage_bps'])
                if suffix=='.csv':malformed.to_csv(path,index=False)
                else:malformed.to_parquet(path,index=False)
                raw=path.read_bytes()
                result=self.run_replay(execution_cost_config=cfg,measurement_context=receipt)
                self.assertEqual(result.get('reason'),'RESEARCH_IO_FAILURE',result)
                self.assertEqual(result.get('selected_input_reason'),'SELECTED_INPUT_SLIPPAGE_SCHEMA')
                self.assertEqual(result['selected_input_cause'],'SlippageRequiredColumns')
                self.assertFalse(result['current_publication_complete'])
                for field in nav.METRIC_FIELDS:self.assertIsNone(result[field])
                for field,value in nav.AUTHORITY.items():self.assertEqual(result[field],value)
                self.assertFalse((dest/nav.CURVE_FILE).exists());self.assertEqual(foreign.read_bytes(),b'foreign')
                self.assertEqual(path.read_bytes(),raw)
        context_path=self.root/'schema-context.json';context_path.write_text(json.dumps(receipt))
        cmd=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(ROOT/'tools/run_broker_ledger_replay.py'),
            '--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),
            '--starting-capital','10000','--execution-cost-mode','spread_adv_impact_v1',
            '--paper-slippage-path',str(path),'--nav-metrics-context',str(context_path)]
        child=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
        self.assertEqual(child.returncode,2,child.stderr);self.assertNotIn('Traceback',child.stderr)
        self.assertEqual(json.loads(child.stdout).get('selected_input_reason'),'SELECTED_INPUT_SLIPPAGE_SCHEMA')
        self.assertEqual(self.target.read_bytes(),target_before)
        for p,b in source_before.items():self.assertEqual(p.read_bytes(),b)
        # Disabled cost mode does not select the malformed table or fabricate its normalization.
        with patch('tools.execution_cost_model.load_paper_slippage',side_effect=AssertionError('disabled source read')):
            self.assertEqual(self.run_replay(execution_cost_config=ExecutionCostConfig(paper_slippage_path=path),
                measurement_context=self.measurement())['status'],nav.COMPLETE)


    def test_nonexecution_early_refusal_has_canonical_requested_measurement_package(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);target=self.target.read_bytes()
        for kind in ('empty','weight'):
            with self.subTest(kind=kind):
                self.target.write_bytes(target)
                if kind=='empty':pd.DataFrame(columns=['rebalance_date','ticker','weight']).to_csv(self.target,index=False)
                dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True,exist_ok=True)
                foreign=dest/'foreign.keep';foreign.write_bytes(b'foreign')
                raw={p:p.read_bytes() for p in [self.target,*self.cache.iterdir()]}
                options=dict(measurement_context=self.measurement(),oos_start='2026-01-07',oos2_start='2026-01-06')
                if kind=='weight':options['max_reasonable_weight_sum']=.45
                result=self.run_replay(**options)
                expected='target book is empty or invalid' if kind=='empty' else 'target weight sum exceeds maximum reasonable exposure'
                self.assertEqual(result['reason'],expected);self.assertEqual(result['status'],nav.BLOCKED)
                self.assertEqual(result['requested_window_labels'],['full','is','oos','oos2'])
                self.assertEqual(set(result['windows']),{'full','is','oos','oos2'})
                for metric in (result,*result['windows'].values()):
                    self.assertEqual(metric['status'],nav.BLOCKED);self.assertEqual(metric['metric_mode'],nav.MODE)
                    self.assertFalse(metric['metric_admission_complete'])
                    for field in nav.METRIC_FIELDS:self.assertIsNone(metric[field])
                    for field,value in nav.AUTHORITY.items():self.assertEqual(metric[field],value)
                    for field in ('start_date','end_date','interval_returns','input_rows_sha256','valuation_binding_provenance'):
                        self.assertNotIn(field,metric)
                self.assertNotIn('measurement_admission',result)
                self.assertEqual(json.loads((dest/nav.METRICS_FILE).read_text()),result)
                self.assertFalse((dest/nav.CURVE_FILE).exists());self.assertEqual(foreign.read_bytes(),b'foreign')
                for p,b in raw.items():self.assertEqual(p.read_bytes(),b)
                legacy=self.run_replay(**({'max_reasonable_weight_sum':.45} if kind=='weight' else {}))
                self.assertEqual(legacy['status'],'blocked');self.assertNotIn('measurement_admission',legacy)
                self.assertNotEqual(legacy.get('metric_mode'),nav.MODE)
        self.target.write_bytes(target)
        self.assertEqual(self.run_replay(measurement_context=self.measurement())['status'],nav.COMPLETE)

    def test_E1_fill_refusal_preserves_outer_redaction_with_separate_measurement_envelope(self):
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4)
        dest=self.out/nav.NAMESPACE;dest.mkdir(parents=True);foreign=dest/'foreign.keep';foreign.write_bytes(b'foreign')
        raw={p:p.read_bytes() for p in [self.target,*self.cache.iterdir()]}
        result=self.run_replay(measurement_context=self.measurement(),max_fill_lag_days=1,
                              oos_start='2026-01-07',oos2_start='2026-01-06')
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['reason'],'target_fill_coverage_incomplete')
        self.assertEqual(result['metric_mode'],'DO_NOT_USE');self.assertTrue(result['performance_fields_redacted'])
        self.assertNotIn('cagr',result);self.assertFalse(result['target_fill_coverage']['coverage_complete'])
        admitted=result['measurement_admission']
        self.assertEqual(admitted['requested_window_labels'],['full','is','oos','oos2'])
        for metric in (admitted,*admitted['windows'].values()):
            self.assertEqual(metric['status'],nav.BLOCKED);self.assertEqual(metric['metric_mode'],nav.MODE)
            self.assertEqual(metric['reason'],result['reason']);self.assertFalse(metric['metric_admission_complete'])
            for field in nav.METRIC_FIELDS:self.assertIsNone(metric[field])
            for field,value in nav.AUTHORITY.items():self.assertEqual(metric[field],value)
            for field in ('start_date','end_date','interval_returns','input_rows_sha256','valuation_binding_provenance'):
                self.assertNotIn(field,metric)
        self.assertEqual(json.loads((dest/nav.METRICS_FILE).read_text()),result)
        report=(dest/nav.artifact_name('replay_report.md')).read_text()
        self.assertIn(result['reason'],report);self.assertIn('Performance metrics: unavailable',report)
        self.assertFalse((dest/nav.CURVE_FILE).exists());self.assertEqual(foreign.read_bytes(),b'foreign')
        for p,b in raw.items():self.assertEqual(p.read_bytes(),b)
        legacy=self.run_replay(max_fill_lag_days=1)
        self.assertEqual(legacy['metric_mode'],'DO_NOT_USE');self.assertNotIn('cagr',legacy)
        self.assertNotIn('measurement_admission',legacy)

    def test_exact_empty_OOS2_end_is_None_and_other_falsey_types_refuse_actual_windows(self):
        import copy,subprocess,sys
        from nav_metrics_v2_smoke import rows,context,frame,binding
        from tools import nav_metrics_v2 as nav
        self.write_prices([100.]*4);data=rows((9987.5,)*3)
        full=context(data,anchor_nav=10000.);first=context(data[:2],anchor_nav=10000.);first['cutoff']=full['cutoff']
        oos=context(data[2:],anchor_nav=data[1]['nav'],anchor_time=data[1]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        second=context(data[1:2],anchor_nav=data[0]['nav'],anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        second['cutoff']=full['cutoff']
        contexts={'full':full,'is':first,'oos':oos,'oos2':second}
        package=dict(full=full,valuation_binding=binding(data),windows={k:v for k,v in contexts.items() if k!='full'})
        curve=frame(data);original=copy.deepcopy(package);raw={p:p.read_bytes() for p in [self.target,*self.cache.iterdir()]}
        for end in (None,'','2026-01-06',False,0,' ','\t','not-date','2026-01-05','2026-01-07'):
            with self.subTest(end=repr(end),type=type(end).__name__):
                result=broker.calc_metrics_with_oos(curve,pd.DataFrame(),10000.,oos_start='2026-01-07',
                    oos2_start='2026-01-06',oos2_end=end,measurement_contexts=contexts,valuation_binding=binding(data))
                actual=self.run_replay(measurement_context=package,oos_start='2026-01-07',oos2_start='2026-01-06',oos2_end=end)
                if end is None or (type(end) is str and end in ('','2026-01-06')):
                    self.assertEqual(result['status'],nav.COMPLETE,result);self.assertEqual(actual['status'],nav.COMPLETE,actual)
                    self.assertEqual(result['oos2_end'],'2026-01-06');self.assertEqual(actual['windows']['oos2']['end_date'],'2026-01-06')
                else:
                    self.assertEqual(result['status'],nav.BLOCKED);self.assertEqual(result['full']['reason'],'INVALID_REQUESTED_WINDOW')
                    self.assertEqual(actual['status'],nav.BLOCKED)
                    for metric in (actual,*(actual['windows'][k] for k in ('full','is','oos','oos2'))):
                        self.assertEqual(metric['status'],nav.BLOCKED)
                        for field in nav.METRIC_FIELDS:self.assertIsNone(metric[field])
                        self.assertNotIn('start_date',metric);self.assertNotIn('valuation_binding_provenance',metric)
                    self.assertFalse((self.out/nav.NAMESPACE/nav.CURVE_FILE).exists())
                self.assertEqual(package,original)
                for p,b in raw.items():self.assertEqual(p.read_bytes(),b)
        # A secondary-only open boundary is supported, with its real immediate predecessor.
        tail=context(data[1:],anchor_nav=data[0]['nav'],anchor_time=data[0]['timestamp'],anchor_kind='OOS_PREDECESSOR')
        for end in (None,''):
            result=broker.calc_metrics_with_oos(curve,pd.DataFrame(),10000.,oos2_start='2026-01-06',oos2_end=end,
                measurement_contexts={'full':full,'oos2':tail},valuation_binding=binding(data))
            self.assertEqual(result['status'],nav.COMPLETE,result);self.assertIsNone(result['oos2_end'])
            self.assertEqual(result['oos2']['end_date'],'2026-01-07')
        primary=broker.calc_metrics_with_oos(curve,pd.DataFrame(),10000.,oos_start='2026-01-07',
            measurement_contexts=contexts,valuation_binding=binding(data))
        self.assertEqual(primary['status'],nav.COMPLETE)
        path=self.root/'OOS-empty-context.json';path.write_text(json.dumps(package))
        command=[sys.executable]+(['-O'] if sys.flags.optimize else [])+[str(ROOT/'tools/run_broker_ledger_replay.py'),
            '--target-book',str(self.target),'--price-cache',str(self.cache),'--output-dir',str(self.out),
            '--starting-capital','10000','--fill-mode','next_close','--cash-carry-mode','none',
            '--reserve-mode','BROKER_CASH_OR_MMF','--oos-start','2026-01-07','--oos2-start','2026-01-06',
            '--oos2-end','','--nav-metrics-context',str(path)]
        child=subprocess.run(command,capture_output=True,text=True,timeout=90)
        self.assertEqual(child.returncode,0,child.stderr);self.assertNotIn('Traceback',child.stderr)
        self.assertEqual(json.loads(child.stdout)['windows']['oos2']['end_date'],'2026-01-06')


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
