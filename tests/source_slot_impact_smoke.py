#!/usr/bin/env python3
"""Offline post-PR702 clock/cache/request accounting regressions.

All price bytes are synthetic. A downloader double and socket guards prohibit
provider traffic; downloader invocations are not measured HTTP requests/costs.
"""
from __future__ import annotations

from argparse import Namespace
from collections import Counter
from datetime import timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_replay_price_cache as cache
from tools.alpaca_sip_managed_refresh import provider_endpoint_gate
from tools.run_daily_market_session_gate import evaluate_market_session


class SourceSlotImpactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.book = self.root / "book.csv"
        self.cache_dir = self.root / "cache"
        self.cache_dir.mkdir()
        for target in ("socket.socket.connect", "socket.create_connection"):
            guard = patch(target, side_effect=AssertionError("network forbidden"))
            self.addCleanup(guard.stop)
            guard.start()
        self.provider_guard = patch.object(
            cache, "download_yfinance", side_effect=AssertionError("provider forbidden")
        )
        self.provider_guard.start()
        self.addCleanup(self.provider_guard.stop)

    def book_for(self, count):
        names = [f"S{i:03d}" for i in range(count)]
        pd.DataFrame([
            dict(rebalance_date="2026-10-29", ticker=t, weight=1 / count)
            for t in names
        ]).to_csv(self.book, index=False)
        return names

    def frame(self, day):
        return pd.DataFrame(
            {"Open": [10.0], "Close": [10.0], "Adj Close": [10.0]},
            index=pd.DatetimeIndex([day]),
        )

    def write_prices(self, names, day):
        frame = self.frame(day)
        for ticker in names:
            frame.to_parquet(self.cache_dir / cache.px_cache_name(ticker))

    def at(self, clock, *, dry_run=False, downloader=None):
        class ClockTimestamp(pd.Timestamp):
            @classmethod
            def utcnow(cls):
                return pd.Timestamp(clock)

        class ClockPandas:
            Timestamp = ClockTimestamp

            def __getattr__(self, name):
                return getattr(pd, name)

        args = Namespace(
            books=[str(self.book)], scored="", max_scored=250,
            output_dir=str(self.cache_dir), start="2016-01-01", end="",
            batch_size=40, max_tickers=80, required_tickers=[],
            refresh_stale_days=2, refresh_through_date="", dry_run=dry_run,
        )
        with patch.object(cache, "pd", ClockPandas()):
            return cache.run(args, download_fn=downloader)

    def test_slots_preserve_session_across_dst_friday_and_early_close(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/free_data_daily_update.yml").read_text())
        trigger = workflow.get("on", workflow.get(True))
        self.assertEqual(trigger["schedule"], [dict(cron="30 0 * * 2-6")])
        for day, age in (("2026-10-26", 270), ("2026-10-30", 270),
                         ("2026-11-02", 210), ("2026-11-27", 390)):
            with self.subTest(day=day):
                new = pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=1, minutes=30)
                old = new - pd.Timedelta(hours=1)
                for now in (old, new):
                    market = evaluate_market_session(now_utc=now, min_close_age_minutes=120)
                    self.assertTrue(market["ready"])
                    self.assertEqual(market["session_date"], day)
                self.assertEqual(market["close_age_minutes"], age)
                self.assertIn(new.isoweekday(), range(2, 7))
                self.assertFalse(provider_endpoint_gate(day, old.to_pydatetime())["ready"])
                self.assertTrue(provider_endpoint_gate(day, new.to_pydatetime())["ready"])

    def test_exact_provider_boundary_and_stale_holiday_guard_remain(self):
        boundary = pd.Timestamp("2026-10-30T00:14:59Z").to_pydatetime()
        self.assertFalse(provider_endpoint_gate("2026-10-29", boundary - timedelta(seconds=1))["ready"])
        self.assertTrue(provider_endpoint_gate("2026-10-29", boundary)["ready"])
        for now in ("2026-07-04T00:30:00Z", "2026-11-27T00:30:00Z",
                    "2026-10-31T15:01:00Z"):
            with self.subTest(now=now):
                market = evaluate_market_session(now_utc=now, min_close_age_minutes=120)
                self.assertFalse(market["ready"])
                self.assertEqual(market["status"], "SKIP_STALE_SESSION")

    def test_age_two_to_three_is_the_only_new_age_threshold(self):
        names = self.book_for(5)
        for name, day in zip(names, ("2026-10-29", "2026-10-28", "2026-10-27", "2026-10-26")):
            self.write_prices([name], day)
        before = self.at("2026-10-29T23:30:00Z", dry_run=True)
        after = self.at("2026-10-30T00:30:00Z", dry_run=True)
        self.assertEqual((before["stale_before"], after["stale_before"]), (1, 2))
        self.assertEqual((before["download_target_count"], after["download_target_count"]), (2, 3))
        self.assertEqual((before["missing_before"], after["missing_before"]), (1, 1))
        self.assertEqual((before["requested_end"], after["requested_end"]), ("2026-10-31", "2026-11-01"))
        self.assertEqual(after["end"], "2026-10-29")
        self.assertEqual(after["manifest_end_source"], "actual_cached_bars")
        # A normal Monday's Friday bar is already age3 at the old slot.
        # Moving to Tuesday age4 adds no target solely for that weekend.
        self.write_prices(names, "2026-10-23")
        monday_before = self.at("2026-10-26T23:30:00Z", dry_run=True)
        monday_after = self.at("2026-10-27T00:30:00Z", dry_run=True)
        self.assertEqual(monday_before["download_target_count"], len(names))
        self.assertEqual(monday_after["download_target_count"], len(names))

    def test_age_two_cache_can_skip_the_completed_session(self):
        names = self.book_for(1)
        self.write_prices(names, "2026-10-28")
        result = self.at("2026-10-30T00:30:00Z")
        self.assertEqual(result["status"], "already_cached")
        self.assertEqual(result["download_target_count"], 0)
        self.assertEqual(result["common_coverage_end"], "2026-10-28")
        self.assertEqual(result["requested_end"], "2026-11-01")
        self.assertEqual(result["refresh_through_date"], "")
        self.assertIsNone(result["refresh_through_exact_coverage"])

    def test_eighty_new_targets_use_two_first_batches_and_reuse_new_bars(self):
        names = self.book_for(81)
        self.write_prices(names, "2026-10-27")
        before = self.at("2026-10-29T23:30:00Z")
        self.assertEqual(before["download_target_count"], 0)
        calls = []

        def downloader(batch, start, end):
            calls.append((list(batch), start, end))
            return {t: self.frame("2026-10-29") for t in batch}, {"provider": "synthetic"}

        result = self.at("2026-10-30T00:30:00Z", downloader=downloader)
        self.assertEqual(result["ticker_count"], 80)
        self.assertEqual(result["download_target_count"], 80)
        self.assertEqual(result["written"], 80)
        self.assertEqual([len(batch) for batch, _, _ in calls], [40, 40])
        self.assertEqual({t for batch, _, _ in calls for t in batch}, set(names[:80]))
        self.assertEqual({(start, end) for _, start, end in calls}, {("2016-01-01", "2026-11-01")})
        self.assertEqual(result["common_coverage_end"], "2026-10-29")
        repeated = self.at("2026-10-30T00:30:00Z")
        self.assertEqual(repeated["status"], "already_cached")

    def test_nonempty_old_response_repeats_without_advancing_coverage(self):
        names = self.book_for(1)
        self.write_prices(names, "2026-10-27")
        calls = []

        def downloader(batch, start, end):
            calls.append(list(batch))
            return {t: self.frame("2026-10-27") for t in batch}, {"provider": "synthetic"}

        for _ in range(2):
            result = self.at("2026-10-30T00:30:00Z", downloader=downloader)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["written"], 1)
            self.assertEqual(result["common_coverage_end"], "2026-10-27")
            self.assertEqual(result["download_attempt_count"], 1)
        self.assertEqual(calls, [names, names])

    def test_retry_accounting_bounds_are_not_two_http_requests(self):
        # No accepted frames: no cache transaction and no provider I/O.
        def failure_count(count):
            calls = []

            def downloader(batch, start, end):
                calls.append(list(batch))
                return {}, {"provider": "synthetic"}

            result = cache.download_prices(
                [f"S{i:03d}" for i in range(count)], "2016-01-01", "2026-11-01",
                self.cache_dir, 40, download_fn=downloader,
            )
            self.assertEqual(result["failed_count"], count)
            self.assertEqual(len(calls), (count + 39) // 40 + 2 * count)
            self.assertEqual(sum(map(len, calls)), 3 * count)
            self.assertEqual(set(Counter(t for batch in calls for t in batch).values()), {3} if count else set())
            self.assertTrue(all(len(batch) == 1 for batch in calls[(count + 39) // 40:]))
            return len(calls)

        counts = {n: failure_count(n) for n in (0, 1, 39, 40, 41, 79, 80)}
        self.assertEqual(counts[80], 162)
        self.assertEqual(counts[41] - counts[40], 3)

    def test_all_failed_refresh_keeps_bytes_but_is_not_current_coverage(self):
        names = self.book_for(1)
        self.write_prices(names, "2026-10-27")
        path = self.cache_dir / cache.px_cache_name(names[0])
        original = path.read_bytes()
        result = self.at("2026-10-30T00:30:00Z", downloader=lambda *args: ({}, {"provider": "synthetic"}))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["download_attempt_count"], 3)
        self.assertEqual(result["written"], 0)
        self.assertEqual(result["end"], "2026-10-27")
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
