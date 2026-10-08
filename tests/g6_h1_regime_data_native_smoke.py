"""Native SPY provider, VIX history, and cache regressions; no HTTP or broker IO."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import os
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import aggressive.data_alpaca as provider
import r1000_regime_data as regime


class NativeRegimeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(socket, "socket", side_effect=RuntimeError("NETWORK_FORBIDDEN")))
        self.stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=RuntimeError("HTTP_FORBIDDEN")))
        self.stack.enter_context(patch.dict("os.environ", {"FRED_API_KEY": ""}))
        self.tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.cache = Path(self.tmp) / "cache.json"
        self.stack.enter_context(patch.object(regime, "_CACHE_PATH", self.cache))

    def bars(self, count=200, values=None):
        index = pd.bdate_range(end=regime._last_completed_us_session(datetime.now(timezone.utc)), periods=count, tz="UTC")
        return pd.DataFrame({"close": values if values is not None else np.arange(count, dtype=float) + 300.0}, index=index)

    def fetch(self, frame):
        # Exercise the real fetch_spy_benchmark wrapper and its raw adjustment contract.
        with patch.object(provider, "fetch_daily_bars", return_value=frame) as raw:
            result = regime.fetch_spy_with_ma200()
        raw.assert_called_once_with("SPY", days=260, adjustment="raw")
        return result

    def refused(self, frame):
        close, ma, source, warnings = self.fetch(frame)
        self.assertEqual((close, ma, source), (0.0, 0.0, "alpaca_invalid"))
        self.assertTrue(warnings)

    def test_native_200_and_260_bar_math_unchanged(self):
        for count in (200, 260):
            with self.subTest(count=count):
                frame = self.bars(count)
                close, ma, source, warnings = self.fetch(frame)
                self.assertEqual(close, float(frame["close"].iloc[-1]))
                self.assertEqual(ma, float(frame["close"].tail(200).mean()))
                self.assertEqual(source, "alpaca")
                self.assertEqual(warnings, [])

    def test_199_nan_closes_do_not_become_one_observation_mean(self):
        self.refused(self.bars(values=[np.nan] * 199 + [500.0]))

    def test_python_and_numpy_boolean_raw_prices_refused(self):
        for value in (True, False, np.bool_(True)):
            with self.subTest(value=repr(value)):
                self.refused(self.bars(values=[value] * 200))
        frame = self.bars()
        frame["close"] = frame["close"].astype(object)
        frame.iloc[37, 0] = True
        self.refused(frame)

    def test_duplicate_timestamps_and_distinct_intraday_times_refused(self):
        for index in (pd.DatetimeIndex([pd.Timestamp("2026-10-07", tz="UTC")] * 200),
                      pd.date_range("2026-10-07", periods=200, freq="s", tz="UTC")):
            with self.subTest(unique=index.is_unique):
                frame = self.bars()
                frame.index = index
                self.refused(frame)

    def test_nonpositive_infinite_and_string_raw_prices_refused(self):
        for value in (0.0, -1.0, float("inf"), "500"):
            with self.subTest(value=value):
                frame = self.bars()
                frame["close"] = frame["close"].astype(object)
                frame.iloc[5, 0] = value
                self.refused(frame)

    def test_invalid_dates_refused(self):
        frame = self.bars()
        for index in (pd.RangeIndex(200), frame.index.tz_localize(None),
                      frame.index[::-1], frame.index[:-1].append(pd.DatetimeIndex([pd.NaT]))):
            with self.subTest(index=type(index).__name__):
                invalid = frame.copy()
                invalid.index = index
                self.refused(invalid)
        for date in (pd.Timestamp("2026-10-10", tz="UTC"), pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=7)):
            invalid = frame.copy()
            invalid.index = invalid.index[:-1].append(pd.DatetimeIndex([date]))
            self.refused(invalid)

    def test_invalid_older_unused_rows_do_not_change_200ma(self):
        frame = self.bars(260)
        frame.iloc[:60, 0] = np.nan
        self.assertEqual(self.fetch(frame)[2], "alpaca")

    def test_missing_close_short_and_empty_stay_unusable(self):
        self.refused(self.bars().rename(columns={"close": "wrong"}))
        self.assertEqual(self.fetch(self.bars(199))[2], "alpaca_short")
        self.assertEqual(self.fetch(pd.DataFrame())[2], "alpaca_empty")
        self.assertEqual(self.fetch(None)[2], "alpaca_empty")

    def test_provider_exception_returns_unavailable(self):
        with patch.object(provider, "fetch_spy_benchmark", side_effect=RuntimeError("fixture_failure")):
            result = regime.fetch_spy_with_ma200()
        self.assertEqual(result[:3], (0.0, 0.0, "unavailable"))

    def mock_yfinance(self, values, end=None):
        yf = ModuleType("yfinance")
        end = end or regime._last_completed_us_session(datetime.now(timezone.utc))
        index = pd.bdate_range(end=end, periods=len(values), tz="America/New_York")
        yf.Ticker = Mock(return_value=Mock(history=Mock(return_value=pd.DataFrame(
            {"Close": values}, index=index))))
        self.stack.enter_context(patch.dict(sys.modules, {"yfinance": yf}))
        return yf

    def test_yfinance_valid_fear_level_preserved(self):
        yf = self.mock_yfinance([20.0, 35.0])
        self.assertEqual(regime.fetch_vix()[:2], (35.0, "yfinance"))
        yf.Ticker.assert_called_once_with("^VIX")

    def test_bad_yfinance_observations_are_explicit_fallback(self):
        for value in (np.nan, np.inf, True, 4.0, 101.0):
            with self.subTest(value=value):
                self.mock_yfinance([value])
                self.assertEqual(regime.fetch_vix()[:2], (20.0, "fallback"))

    def test_fred_raw_boolean_nonfinite_and_bad_range_are_not_trusted(self):
        self.mock_yfinance([])
        self.stack.enter_context(patch.dict("os.environ", {"FRED_API_KEY": "fixture_not_a_secret"}))
        for value in (True, "nan", "inf", "4", "101", "."):
            with self.subTest(value=value):
                response = Mock()
                response.read.return_value = json.dumps({"observations": [{"value": value}]}).encode()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                with patch.object(urllib.request, "urlopen", return_value=response):
                    self.assertEqual(regime.fetch_vix()[:2], (20.0, "fallback"))

    def test_fred_valid_numeric_string_preserved(self):
        self.mock_yfinance([])
        self.stack.enter_context(patch.dict("os.environ", {"FRED_API_KEY": "fixture_not_a_secret"}))
        response = Mock()
        response.read.return_value = b'{"observations":[{"value":"31.5"}]}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(urllib.request, "urlopen", return_value=response):
            self.assertEqual(regime.fetch_vix()[:2], (31.5, "fred"))

    def snapshot(self, **changes):
        now = datetime.now(timezone.utc)
        session = regime._last_completed_us_session(now).isoformat()
        values = dict(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      spy_session_date=session, vix_observation_date=session,
                      collected_at_utc=now.isoformat(),
                      spy_close=500.0, spy_ma200=400.0, spy_above_200ma=True,
                      vix_level=20.0, vix_source="yfinance", spy_source="alpaca")
        values.update(changes)
        return regime.RegimeSnapshot(**values)

    def payload(self, **changes):
        result = asdict(self.snapshot())
        result.update(_cached_at=time.time(), _source_validation_version=1)
        result.update(changes)
        return result

    def write_cache(self, payload):
        self.cache.write_text(json.dumps(payload), encoding="utf-8")

    def test_current_valid_cache_roundtrip(self):
        snap = self.snapshot()
        regime._save_cached_snapshot(snap)
        self.assertEqual(regime._load_cached_snapshot(), snap)

    def test_future_expired_nonfinite_boolean_cache_clocks_refused(self):
        for clock in (time.time() + 60, time.time() - 3601, True, float("nan"), float("inf"), "123"):
            with self.subTest(clock=clock):
                self.write_cache(self.payload(_cached_at=clock))
                self.assertIsNone(regime._load_cached_snapshot())

    def test_future_old_and_invalid_observation_cache_clocks_refused(self):
        for timestamp in ((datetime.now() + timedelta(minutes=1)).isoformat(),
                          (datetime.now() - timedelta(hours=2)).isoformat(), "invalid"):
            with self.subTest(timestamp=timestamp):
                self.write_cache(self.payload(timestamp=timestamp))
                self.assertIsNone(regime._load_cached_snapshot())

    def test_pre_validation_and_boolean_version_cache_refused(self):
        for version in (None, True, 0, 2):
            payload = self.payload(_source_validation_version=version)
            if version is None:
                del payload["_source_validation_version"]
            self.write_cache(payload)
            self.assertIsNone(regime._load_cached_snapshot())

    def test_bad_cached_source_and_prices_refused(self):
        for changes in ({"spy_close": True}, {"spy_ma200": np.nan}, {"vix_source": "fallback"},
                        {"spy_source": "alpaca_short"}, {"spy_above_200ma": False}):
            self.write_cache(self.payload(**changes))
            self.assertIsNone(regime._load_cached_snapshot())

    def test_missing_source_produces_error_instead_of_benign_actions(self):
        with patch.object(regime, "fetch_spy_with_ma200", return_value=(0.0, 0.0, "unavailable", [])), \
             patch.object(regime, "fetch_vix", return_value=(20.0, "fallback", [])):
            snap = regime.current_regime(use_cache=False)
        self.assertIs(snap.spy_above_200ma, False)
        self.assertEqual(snap.regime_label, "unavailable")
        self.assertIn("error", regime.layer3_actions_for_snapshot(snap)[0])

    def test_stale_spy_session_blocks_native_snapshot(self):
        old = regime._last_completed_us_session(datetime.now(timezone.utc)) - timedelta(days=21)
        frame = pd.DataFrame({"close": [500.0] * 200},
                             index=pd.bdate_range(end=old, periods=200, tz="UTC"))
        self.mock_yfinance([20.0])
        with patch.object(provider, "fetch_daily_bars", return_value=frame):
            snap = regime.current_regime(use_cache=False)
        self.assertEqual(snap.spy_session_date, old.isoformat())
        self.assertEqual(snap.regime_label, "unavailable")
        self.assertIn("error", regime.layer3_actions_for_snapshot(snap)[0])
        self.assertIsNone(regime._load_cached_snapshot())

    def test_stale_vix_observation_blocks_native_snapshot(self):
        old = regime._last_completed_us_session(datetime.now(timezone.utc)) - timedelta(days=21)
        self.mock_yfinance([20.0], end=old)
        with patch.object(provider, "fetch_daily_bars", return_value=self.bars(260)):
            snap = regime.current_regime(use_cache=False)
        self.assertEqual(snap.vix_observation_date, old.isoformat())
        self.assertEqual(snap.regime_label, "unavailable")
        self.assertIn("error", regime.layer3_actions_for_snapshot(snap)[0])
        self.assertIsNone(regime._load_cached_snapshot())

    def test_future_file_mtime_cannot_revalidate_stale_observation(self):
        old = regime._last_completed_us_session(datetime.now(timezone.utc)) - timedelta(days=21)
        self.write_cache(self.payload(spy_session_date=old.isoformat()))
        future = time.time() + 86400
        os.utime(self.cache, (future, future))
        self.assertIsNone(regime._load_cached_snapshot())

    def test_collection_clock_freshness_and_cache_binding(self):
        now = datetime.now(timezone.utc)
        for collected in (now - timedelta(hours=2), now + timedelta(minutes=5),
                          now - timedelta(minutes=7)):
            with self.subTest(collected=collected):
                self.write_cache(self.payload(collected_at_utc=collected.isoformat()))
                self.assertIsNone(regime._load_cached_snapshot())

    def test_yfinance_or_fred_without_observation_date_is_not_admitted(self):
        yf = ModuleType("yfinance")
        yf.Ticker = Mock(return_value=Mock(history=Mock(return_value=pd.DataFrame({"Close": [20.0]}))))
        with patch.dict(sys.modules, {"yfinance": yf}):
            self.assertEqual(regime.fetch_vix(include_observation=True)[1], "fallback")
        self.mock_yfinance([])
        with patch.dict("os.environ", {"FRED_API_KEY": "fixture_not_a_secret"}):
            response = Mock()
            response.read.return_value = b'{"observations":[{"value":"20.0"}]}'
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            with patch.object(urllib.request, "urlopen", return_value=response):
                self.assertEqual(regime.fetch_vix(include_observation=True)[1], "fallback")

    def test_native_healthy_provider_to_snapshot_actions_and_cache(self):
        frame = self.bars(260)
        self.mock_yfinance([20.0])
        with patch.object(provider, "fetch_daily_bars", return_value=frame):
            snap = regime.current_regime(use_cache=False)
        self.assertEqual((snap.spy_source, snap.vix_source), ("alpaca", "yfinance"))
        self.assertEqual(snap.regime_label, "normal")
        self.assertEqual(regime.layer3_actions_for_snapshot(snap), [])
        self.assertEqual(regime._load_cached_snapshot(), snap)


if __name__ == "__main__":
    unittest.main(verbosity=2)
