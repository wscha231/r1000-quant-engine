"""Run this checkout's G6 executor/producer with provider and broker mocks."""
from __future__ import annotations

import importlib.util
import ast
import hashlib
import io
import math
import os
import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from pathlib import Path
import socket
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT
EXECUTOR_PATH = ROOT / "r1000_paper_executor.py"
sys.path.insert(0, str(ROOT))
import pandas as pd
import pandas_market_calendars as mcal

# Frozen from the verified packet's exact 37046b7 master source, not the candidate.
BASELINE_AST = {
    "load_advisor_picks": "3d0bd542a7aa816d6f8795b77923090cd051c0a9770389cc392117dc2a93a62b",
    "normalize_picks": "5eaf8e9f4f90322dc6bb93a370801ff0fd3abfd75594dcba15e0fb1365bd0f5b",
    "planning_execution_tail": "e0cdca4731885b9200527e8ea9a9edd7e3ab6c74aa5af4b386c90773a5b6f244",
}


def source_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def FrameFixture():
    return pd.DataFrame([
        dict(ticker="AAA", weight=0.5, execution_reference_price=100.0),
        dict(ticker="HELD", weight=0.5, execution_reference_price=100.0),
    ])


class ExecutorMainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the real calendar's static holiday-rule cache; every clock still
        # runs its actual schedule. No synthetic calendar/close data is supplied.
        cls.nyse = mcal.get_calendar("NYSE")

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(mcal, "get_calendar", return_value=self.nyse))
        self.stack.enter_context(patch("socket.socket", side_effect=RuntimeError("NETWORK_FORBIDDEN")))
        self.stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=RuntimeError("NETWORK_FORBIDDEN")))
        self.stack.enter_context(patch("builtins.input", side_effect=RuntimeError("PROMPT_FORBIDDEN")))
        self.stack.enter_context(patch("sys.path", list(sys.path)))
        aggressive = ModuleType("aggressive")
        aggressive.__path__ = []
        broker = ModuleType("aggressive.executor")
        for name in ("_existing_positions", "_fetch_account_snapshot", "_get_trading_client",
                     "_place_limit_buy", "_place_market_sell"):
            setattr(broker, name, Mock(side_effect=RuntimeError("REAL_BROKER_FORBIDDEN")))
        alert = ModuleType("aggressive.telegram_alert")
        alert.send_alert = Mock(side_effect=RuntimeError("REAL_ALERT_FORBIDDEN"))
        self.stack.enter_context(patch.dict(sys.modules, {
            "aggressive": aggressive, "aggressive.executor": broker,
            "aggressive.telegram_alert": alert,
        }))
        self.risk = source_module("r1000_risk_sensing", BASE / "r1000_risk_sensing.py")
        self.regime = source_module("r1000_regime_data", BASE / "r1000_regime_data.py")
        self.executor = source_module("g6_candidate_executor", EXECUTOR_PATH)

    def snap(self, **changes):
        now = datetime.now(timezone.utc)
        session = self.regime._last_completed_us_session(now).isoformat()
        values = dict(timestamp="fixture", vix_level=20.0, vix_source="yfinance",
                      spy_session_date=session, vix_observation_date=session,
                      collected_at_utc=now.isoformat(),
                      spy_close=510.0, spy_ma200=490.0, spy_above_200ma=True,
                      spy_source="alpaca", warnings=[])
        values.update(changes)
        return self.regime.RegimeSnapshot(**values)

    def at_time(self, now):
        class DateTimeType(type):
            def __instancecheck__(cls, value):
                # Preserve real datetime/Timestamp recognition in source readers.
                return isinstance(value, datetime)

        class FrozenDateTime(datetime, metaclass=DateTimeType):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.astimezone().replace(tzinfo=None)

        stack = ExitStack()
        stack.enter_context(patch.object(self.regime, "datetime", FrozenDateTime))
        stack.enter_context(patch.object(self.regime.time, "time", return_value=now.timestamp()))
        return stack

    def snap_at(self, now, **changes):
        session = self.regime._last_completed_us_session(now).isoformat()
        values = dict(timestamp=now.astimezone().replace(tzinfo=None).isoformat(),
                      collected_at_utc=(now - timedelta(seconds=1)).isoformat(),
                      spy_session_date=session, vix_observation_date=session)
        values.update(changes)
        return self.snap(**values)

    def run_main(self, snap=None, actions=None, exception=None, execute=True,
                 skip=False, override=False, legacy=True, executor=None,
                 native_regime=False):
        pe = executor or self.executor
        snap = snap or self.snap()
        argv = ["fixture", "--advisor", "core", "--capital", "1000", "--confirm"]
        if execute:
            argv.append("--execute")
        if legacy:
            argv.append("--allow-legacy-execute")
        if skip:
            argv.append("--skip-regime-check")
        if override:
            argv.append("--override-regime-halt")
        load = Mock(return_value=FrameFixture())
        client = Mock(return_value=object())
        buy = Mock(return_value=("fixture_order_only", "accepted"))
        sell = Mock(side_effect=RuntimeError("SELL_FORBIDDEN"))
        send = Mock()
        audit = MagicMock()
        current = Mock(return_value=snap, side_effect=exception)
        if native_regime:
            current = Mock(side_effect=self.regime.current_regime)
        stdout, stderr = io.StringIO(), io.StringIO()
        with ExitStack() as ctx:
            ctx.enter_context(patch.object(pe, "load_advisor_picks", load))
            ctx.enter_context(patch.object(pe, "_get_trading_client", client))
            ctx.enter_context(patch.object(pe, "_fetch_account_snapshot",
                                          Mock(return_value={"cash": 1000, "equity": 1000})))
            ctx.enter_context(patch.object(pe, "_existing_positions", Mock(return_value={"HELD": 5})))
            ctx.enter_context(patch.object(pe, "_place_limit_buy", buy))
            ctx.enter_context(patch.object(pe, "_place_market_sell", sell))
            ctx.enter_context(patch.object(pe, "send_alert", send))
            ctx.enter_context(patch.object(pe, "Path", audit))
            ctx.enter_context(patch.object(self.regime, "current_regime", current))
            if actions is not None:
                ctx.enter_context(patch.object(self.regime, "layer3_actions_for_snapshot", Mock(return_value=actions)))
            ctx.enter_context(patch.object(sys, "argv", argv))
            ctx.enter_context(redirect_stdout(stdout))
            ctx.enter_context(redirect_stderr(stderr))
            result = pe.main()
        return dict(rc=result, load=load, client=client, buy=buy, sell=sell, send=send,
                    audit=audit, current=current, stdout=stdout.getvalue(), stderr=stderr.getvalue())

    def refused(self, result):
        self.assertEqual(result["rc"], 1)
        for name in ("load", "client", "buy", "sell", "send", "audit"):
            result[name].assert_not_called()
        self.assertIn("REFUSING --execute", result["stderr"])

    def test_legacy_ack_stays_required(self):
        self.refused(self.run_main(legacy=False))

    def test_fallback_rejected_even_with_override(self):
        for override in (False, True):
            with self.subTest(override=override):
                self.refused(self.run_main(self.snap(vix_source="fallback"), override=override))

    def test_missing_short_spy_rejected(self):
        for source in ("unavailable", "alpaca_empty", "alpaca_short", "", None):
            with self.subTest(source=source):
                self.refused(self.run_main(self.snap(spy_source=source), override=True))

    def test_nonfinite_or_missing_numeric_rejected(self):
        for change in ({"spy_close": 0.0}, {"spy_ma200": 0.0}, {"spy_close": None},
                       {"spy_close": float("nan")}, {"spy_ma200": float("inf")},
                       {"vix_level": float("nan")}, {"vix_level": 4.0}, {"vix_level": 101.0}):
            with self.subTest(change=change):
                self.refused(self.run_main(self.snap(**change)))

    def test_spy_flag_mismatch_rejected(self):
        self.refused(self.run_main(self.snap(spy_close=480.0, spy_above_200ma=True)))

    def test_preflight_exception_rejected(self):
        self.refused(self.run_main(exception=RuntimeError("fixture_preflight_failure"), override=True))

    def test_error_action_rejected(self):
        for actions in ([{"error": "fixture_import_error"}], [{"type": "UNKNOWN"}], [None], {}):
            with self.subTest(actions=actions):
                self.refused(self.run_main(actions=actions, override=True))

    def test_execute_skip_rejected(self):
        for override in (False, True):
            with self.subTest(override=override):
                result = self.run_main(skip=True, override=override)
                self.refused(result)
                result["current"].assert_not_called()

    def test_dry_run_skip_kept(self):
        result = self.run_main(execute=False, skip=True)
        self.assertEqual(result["rc"], 0)
        result["current"].assert_not_called()
        result["buy"].assert_not_called()
        result["audit"].assert_not_called()

    def test_dry_run_exception_keeps_preview(self):
        result = self.run_main(execute=False, exception=RuntimeError("fixture_preflight_failure"))
        self.assertEqual(result["rc"], 0)
        result["buy"].assert_not_called()
        result["audit"].assert_not_called()

    def test_valid_normal_plans_unchanged(self):
        result = self.run_main()
        self.assertEqual(result["rc"], 0)
        self.assertEqual(result["buy"].call_count, 1)
        args, kwargs = result["buy"].call_args
        self.assertEqual(args[1:], ("AAA", 5.0, 100.5))
        self.assertEqual(kwargs, {"fractional": True})
        result["sell"].assert_not_called()
        self.assertIn("SKIP (already held)", result["stdout"])

    def test_valid_fred_kept(self):
        self.assertEqual(self.run_main(self.snap(vix_source="fred"))["rc"], 0)

    def test_real_layer3_halt_and_override_kept(self):
        self.refused(self.run_main(self.snap(vix_level=30.0)))
        self.assertEqual(self.run_main(self.snap(vix_level=30.0), override=True)["rc"], 0)

    def test_valid_below_ma_cash_action_kept(self):
        result = self.run_main(self.snap(spy_close=470.0, spy_above_200ma=False))
        self.assertEqual(result["rc"], 0)
        self.assertIn("CASH_BUFFER", result["stdout"])
        self.assertIn("cash buffer suggested but not auto-applied", result["stdout"])

    def test_candidate_baseline_valid_preview_parity(self):
        tree = ast.parse(EXECUTOR_PATH.read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for name in ("load_advisor_picks", "normalize_picks"):
            self.assertEqual(hashlib.sha256(ast.dump(functions[name], include_attributes=False).encode()).hexdigest(),
                             BASELINE_AST[name])
        body = functions["main"].body
        start = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                     and node.value.func.id == "load_advisor_picks")
        tail = ast.Module(body=body[start:], type_ignores=[])
        self.assertEqual(hashlib.sha256(ast.dump(tail, include_attributes=False).encode()).hexdigest(),
                         BASELINE_AST["planning_execution_tail"])

    def test_error_member_on_typed_action_must_refuse(self):
        self.refused(self.run_main(actions=[{"type": "HALT_NEW", "priority": 7,
                                           "reason": "fixture", "error": "fixture_error"}],
                                  override=True))

    def test_boolean_prices_must_refuse(self):
        self.refused(self.run_main(self.snap(spy_close=True, spy_ma200=0.5,
                                            spy_above_200ma=True)))

    def native_provider(self, frame, cache_path, vix_date=None):
        provider = ModuleType("aggressive.data_alpaca")
        provider.fetch_spy_benchmark = Mock(return_value=frame)
        yf = ModuleType("yfinance")
        current_session = self.regime._last_completed_us_session(datetime.now(timezone.utc))
        vix_index = pd.DatetimeIndex([pd.Timestamp(vix_date or current_session, tz="America/New_York")])
        yf.Ticker = Mock(return_value=Mock(history=Mock(return_value=pd.DataFrame(
            {"Close": [20.0]}, index=vix_index))))
        self.stack.enter_context(patch.dict(sys.modules, {"aggressive.data_alpaca": provider, "yfinance": yf}))
        self.stack.enter_context(patch.object(self.regime, "_CACHE_PATH", cache_path))
        return provider.fetch_spy_benchmark

    def test_stale_spy_or_vix_date_refuses_execute_even_with_override(self):
        old = (self.regime._last_completed_us_session(datetime.now(timezone.utc))
               - timedelta(days=21)).isoformat()
        for key in ("spy_session_date", "vix_observation_date"):
            with self.subTest(key=key):
                self.refused(self.run_main(self.snap(**{key: old}), override=True))

    def test_stale_collection_time_refuses_execute(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.refused(self.run_main(self.snap(collected_at_utc=old), override=True))

    def test_native_producer_bad_history_cannot_authorize_orders(self):
        dates = pd.bdate_range(end="2026-10-07", periods=200, tz="UTC")
        frames = [
            pd.DataFrame({"close": [float("nan")] * 199 + [500.0]}, index=dates),
            pd.DataFrame({"close": [True] * 200}, index=dates),
            pd.DataFrame({"close": [500.0] * 200}, index=pd.DatetimeIndex([dates[-1]] * 200)),
        ]
        for frame in frames:
            with self.subTest(dtype=str(frame["close"].dtype)), tempfile.TemporaryDirectory() as tmp:
                fetch = self.native_provider(frame, Path(tmp) / "cache.json")
                self.refused(self.run_main(native_regime=True, override=True))
                fetch.assert_called_once_with(days=260)

    def test_native_future_cache_cannot_hide_failed_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            payload = dict(vars(self.snap(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))))
            payload.update(_cached_at=time.time() + 60, _source_validation_version=1)
            path.write_text(json.dumps(payload), encoding="utf-8")
            fetch = self.native_provider(pd.DataFrame(), path)
            self.refused(self.run_main(native_regime=True, override=True))
            fetch.assert_called_once_with(days=260)

    def test_native_valid_current_cache_preserves_mocked_order_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            self.stack.enter_context(patch.object(self.regime, "_CACHE_PATH", path))
            self.regime._save_cached_snapshot(self.snap(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            fetch = self.native_provider(pd.DataFrame(), path)
            result = self.run_main(native_regime=True)
            self.assertEqual(result["rc"], 0)
            fetch.assert_not_called()
            self.assertEqual(result["buy"].call_args.args[1:], ("AAA", 5.0, 100.5))

    def test_one_to_four_day_stale_spy_vix_or_both_refuse_before_any_target_or_order(self):
        now = datetime(2026, 10, 9, 21, 0, 10, tzinfo=timezone.utc)
        with self.at_time(now):
            for days in range(1, 5):
                old = (now.date() - timedelta(days=days)).isoformat()
                for fields in (("spy_session_date",), ("vix_observation_date",),
                               ("spy_session_date", "vix_observation_date")):
                    for override in (False, True):
                        with self.subTest(days=days, fields=fields, override=override):
                            snap = self.snap_at(now, **dict.fromkeys(fields, old))
                            self.refused(self.run_main(snap, override=override))

    def test_actual_nyse_session_boundaries_preserve_valid_order_contract(self):
        cases = (
            ("2026-10-08T19:59:59+00:00", "2026-10-07"),
            ("2026-10-08T20:00:01+00:00", "2026-10-08"),
            ("2026-10-08T20:15:00+00:00", "2026-10-08"),
            ("2026-10-10T21:00:00+00:00", "2026-10-09"),
            ("2026-11-02T21:00:01+00:00", "2026-11-02"),
            ("2026-11-26T22:00:00+00:00", "2026-11-25"),
            ("2026-11-27T17:59:59+00:00", "2026-11-25"),
            ("2026-11-27T18:00:01+00:00", "2026-11-27"),
            ("2026-12-25T22:00:00+00:00", "2026-12-24"),
        )
        for clock, session in cases:
            now = datetime.fromisoformat(clock)
            with self.subTest(clock=clock), self.at_time(now):
                snap = self.snap_at(now, spy_session_date=session, vix_observation_date=session)
                result = self.run_main(snap)
                self.assertEqual(result["rc"], 0)
                self.assertEqual(result["load"].call_count, 1)
                self.assertEqual(result["client"].call_count, 1)
                self.assertEqual(result["buy"].call_args.args[1:], ("AAA", 5.0, 100.5))
                result["sell"].assert_not_called()

    def test_holiday_pending_session_and_post_close_provider_lag_refuse(self):
        cases = (
            ("2026-10-08T20:00:01+00:00", "2026-10-07"),
            ("2026-11-26T22:00:00+00:00", "2026-11-26"),
            ("2026-11-27T17:59:59+00:00", "2026-11-27"),
            ("2026-11-27T18:00:01+00:00", "2026-11-25"),
            ("2026-12-25T22:00:00+00:00", "2026-12-25"),
        )
        for clock, invalid in cases:
            now = datetime.fromisoformat(clock)
            with self.subTest(clock=clock), self.at_time(now):
                for field in ("spy_session_date", "vix_observation_date"):
                    self.refused(self.run_main(self.snap_at(now, **{field: invalid}), override=True))

    def test_unavailable_calendar_refuses_even_valid_halt_override(self):
        snap = self.snap(vix_level=30.0)
        with patch.dict(sys.modules, {"pandas_market_calendars": None}):
            self.refused(self.run_main(snap, override=True))
        with patch("pandas_market_calendars.get_calendar", side_effect=RuntimeError("schedule_unavailable")):
            self.refused(self.run_main(snap, override=True))
        with patch("pandas_market_calendars.get_calendar") as calendar:
            calendar.return_value.schedule.return_value = pd.DataFrame({"market_close": []})
            self.refused(self.run_main(snap, override=True))

    def test_native_one_to_four_day_provider_lag_refuses_all_execution_boundaries(self):
        now = datetime(2026, 10, 9, 21, 0, 10, tzinfo=timezone.utc)
        current = "2026-10-09"
        with self.at_time(now):
            for days in range(1, 5):
                old = (now.date() - timedelta(days=days)).isoformat()
                for spy, vix in ((old, current), (current, old), (old, old)):
                    with self.subTest(days=days, spy=spy, vix=vix), tempfile.TemporaryDirectory() as tmp:
                        frame = pd.DataFrame({"close": [500.0] * 260},
                            index=pd.bdate_range(end=spy, periods=260, tz="UTC"))
                        fetch = self.native_provider(frame, Path(tmp) / "cache.json", vix_date=vix)
                        self.refused(self.run_main(native_regime=True, override=True))
                        fetch.assert_called_once_with(days=260)

    def test_native_stale_cache_with_fresh_clocks_and_future_mtime_refuses(self):
        now = datetime(2026, 10, 9, 21, 0, 10, tzinfo=timezone.utc)
        with self.at_time(now):
            for fields in (("spy_session_date",), ("vix_observation_date",),
                           ("spy_session_date", "vix_observation_date")):
                with self.subTest(fields=fields), tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "cache.json"
                    snap = self.snap_at(now, **dict.fromkeys(fields, "2026-10-08"))
                    payload = dict(vars(snap))
                    payload.update(_cached_at=now.timestamp(), _source_validation_version=1)
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    future = now.timestamp() + 86400
                    os.utime(path, (future, future))
                    fetch = self.native_provider(pd.DataFrame(), path, vix_date="2026-10-09")
                    self.refused(self.run_main(native_regime=True, override=True))
                    fetch.assert_called_once_with(days=260)

    def test_native_cache_crossing_actual_close_cannot_authorize_orders(self):
        for clock in ("2026-10-08T20:00:00+00:00", "2026-11-27T18:00:00+00:00"):
            close = datetime.fromisoformat(clock)
            with self.subTest(close=clock), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "cache.json"
                self.stack.enter_context(patch.object(self.regime, "_CACHE_PATH", path))
                with self.at_time(close - timedelta(seconds=10)):
                    self.regime._save_cached_snapshot(self.snap_at(close - timedelta(seconds=10)))
                    self.assertTrue(path.exists())
                with self.at_time(close):
                    fetch = self.native_provider(pd.DataFrame(), path, vix_date=close.date().isoformat())
                    self.refused(self.run_main(native_regime=True, override=True))
                    fetch.assert_called_once_with(days=260)


if __name__ == "__main__":
    unittest.main(verbosity=2)
