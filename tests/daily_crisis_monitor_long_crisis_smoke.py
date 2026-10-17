#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import io
import sys
import tempfile
import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_daily_crisis_monitor import build_monitor  # noqa: E402
from tools import run_daily_crisis_monitor as monitor
from tools import daily_crisis_report_clock as clock
from tools.run287_crisis_policy import availability_records, component_availability


def test_daily_crisis_monitor_uses_learned_long_crisis_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest_run = root / "outputs"
        feature_path = root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        thresholds_path = root / "outputs" / "long_crisis_learning" / "best_thresholds.json"
        feature_path.parent.mkdir(parents=True)
        thresholds_path.parent.mkdir(parents=True)

        idx = pd.bdate_range("2026-01-02", periods=3)
        features = pd.DataFrame(
            {
                "crisis_score": [0.10, 0.25, 0.80],
                "liquidity_confirmation_score": [0.05, 0.10, 0.60],
                "market_trend_damage_score": [0.05, 0.10, 0.58],
                "credit_stress_score": [0.02, 0.10, 0.20],
                "qqq_below_ma200": [0.0, 0.0, 1.0],
                "volatility_stress_score": [0.10, 0.20, 0.70],
                "future_63d_drawdown": [0.0, -0.10, -0.30],
                "future_63d_drawdown_le_15pct": [0, 0, 1],
            },
            index=idx,
        )
        features.to_parquet(feature_path)
        thresholds_path.write_text(
            json.dumps(
                {
                    "governor_thresholds": {"low": 0.30, "mid": 0.50, "high": 0.75},
                    "cash_hard_gate": {"liquidity_gate": 0.35, "trend_gate": 0.35, "credit_gate": 0.55},
                }
            ),
            encoding="utf-8",
        )

        payload = build_monitor(
            SimpleNamespace(
                latest_run=str(latest_run),
                output_dir=str(root / "monitor"),
                history=str(root / "monitor" / "state_history.json"),
                update_history=False,
                long_crisis_features=str(feature_path),
                long_crisis_thresholds=str(thresholds_path),
            )
        )
        assert payload["raw_state"] == "DEFENSE", payload
        assert payload["long_crisis"]["available"] is True
        assert payload["long_crisis"]["future_labels_excluded"] is True
        assert payload["long_crisis"]["cash_gate_reason"] == "systemic_confirmation_pass"
        assert "future_63d_drawdown" not in (root / "monitor" / "summary.json").read_text(encoding="utf-8")


def test_daily_crisis_monitor_blocks_unconfirmed_vix_only_cash_raise() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        latest_run = root / "outputs"
        feature_path = root / "data_pit" / "macro" / "long_crisis_daily_features.parquet"
        thresholds_path = root / "outputs" / "long_crisis_learning" / "best_thresholds.json"
        feature_path.parent.mkdir(parents=True)
        thresholds_path.parent.mkdir(parents=True)

        idx = pd.bdate_range("2026-01-02", periods=2)
        pd.DataFrame(
            {
                "crisis_score": [0.20, 0.70],
                "liquidity_confirmation_score": [0.02, 0.05],
                "market_trend_damage_score": [0.04, 0.10],
                "credit_stress_score": [0.01, 0.05],
                "volatility_stress_score": [0.20, 0.95],
                "qqq_below_ma200": [0.0, 0.0],
            },
            index=idx,
        ).to_parquet(feature_path)
        thresholds_path.write_text(
            json.dumps({"governor_thresholds": {"low": 0.30, "mid": 0.50, "high": 0.75}}),
            encoding="utf-8",
        )

        payload = build_monitor(
            SimpleNamespace(
                latest_run=str(latest_run),
                output_dir=str(root / "monitor"),
                history=str(root / "monitor" / "state_history.json"),
                update_history=False,
                long_crisis_features=str(feature_path),
                long_crisis_thresholds=str(thresholds_path),
            )
        )
        assert payload["raw_state"] == "WATCH", payload
        assert payload["long_crisis"]["cash_gate_reason"] == "blocked_no_liquidity_or_trend_confirmation"


class LegacyCurrentnessTests(unittest.TestCase):
    """Clock fixtures only; no current Source/PIT or economic admission."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_case(self, session="2026-10-16", now="2026-10-17T00:45:00+00:00", *, mutate=None, update=True, report_now=None, history_mutate=None, inference_error=None):
        observed = datetime.fromisoformat(now)
        values = dict(market_trend_damage_score=0.1, qqq_below_ma200=0.0, qqq_ma200=100.0,
                      hy_oas_zscore_252d=0.1, vix_zscore_252d=0.1, liquidity_confirmation_score=0.1,
                      rate_shock_score=0.1)
        try:
            times = clock.session_times(session)
            available = (times["close"]+timedelta(minutes=15)).isoformat() if times else now
        except (clock.Blocked, ValueError, TypeError):
            available = now
        meta = dict(available=True, latest_date=session, canonical_state_inputs=values,
                    component_availability=availability_records(component_availability(
                        values, decision_time=available, available_from=available)),
                    missing_critical_components=[], future_labels_excluded=True)
        meta["source_clocks"] = {name:dict(observation_date=session, value_observation_date=session,
            available_from=available, collected_at=available, expiry=(observed+timedelta(days=1)).isoformat(),
            source_sha256="a"*64) for name in
            ("market", "qqq", "vix", "hy_oas", "dgs10", "dxy", "m2", "fed_assets", "reverse_repo", "tga")}
        config = self.root/"thresholds.json"
        config.write_text(json.dumps(dict(governor_thresholds=dict(low=.35, mid=.55, high=.75),
            cash_hard_gate=dict(liquidity_gate=.35, trend_gate=.35, credit_gate=.55))))
        config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
        meta["thresholds_sha256"] = config_sha
        snapshot_root = self.root/"inputs/operating_snapshot"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        raw = b"ticker,weight\nCASH,1.0\n"
        (snapshot_root/"current_operating_holdings_latest.csv").write_bytes(raw)
        snapshot = dict(report_session=session, book_session=session,
            holdings_sha256=hashlib.sha256(raw).hexdigest())
        snapshot_raw = json.dumps(snapshot).encode()
        (snapshot_root/"current_portfolio_snapshot_summary.json").write_bytes(snapshot_raw)
        snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()
        meta["portfolio_snapshot_binding"] = dict(snapshot, summary_sha256=snapshot_sha)
        meta["raw_state_sidecar_clocks"] = {name:dict(report_session=session, available_from=available,
                                                     generated_at_utc=available)
            for name in ("risk_controls", "safety_audit", "macro_policy", "portfolio_snapshot")}
        if mutate:
            mutate(meta)
        context = clock.completed_session_clock(now)
        prior_session = context["previous_session"]
        prior = dict(schema="legacy-crisis-diagnostic-history-v1", risk_as_of_session=prior_session,
                     state="GREEN", raw_state="GREEN", raw_state_streak=3,
                     updated_at_utc=clock.session_times(prior_session)["AFTER_CLOSE"].isoformat())
        if history_mutate:
            history_mutate(prior)
        history_path = self.root/"history.json"
        before = json.dumps(prior, indent=2).encode()
        history_path.write_bytes(before)
        args = SimpleNamespace(latest_run=str(self.root/"inputs"), output_dir=str(self.root/"report"),
            history=str(history_path), update_history=update, long_crisis_features="not-read.parquet",
            long_crisis_thresholds=str(config), expected_thresholds_sha256=config_sha,
            expected_snapshot_sha256=snapshot_sha, report_now=report_now)
        with patch.object(clock, "trusted_now", return_value=observed), \
             patch.object(monitor, "infer_raw_state", side_effect=inference_error, return_value=("GREEN", ["fixture source diagnostic"], copy.deepcopy(meta))), \
             patch.object(monitor, "apply_hysteresis", wraps=monitor.apply_hysteresis) as hysteresis:
            out = build_monitor(args)
        stored = json.loads((self.root/"report/summary.json").read_text(encoding="utf-8"))
        self.assertEqual(stored, out)
        return out, before, history_path.read_bytes(), hysteresis.call_count

    def assert_current_blocked(self, result, code=None):
        out, before, after, calls = result
        self.assertIsNone(out["state"])
        self.assertEqual(out["current_report_status"], "BLOCKED")
        self.assertEqual(out["data_health"], "DATA_BLOCKED")
        self.assertEqual(out["paper_action_candidates"], [])
        self.assertEqual(before, after)
        self.assertEqual(calls, 0)
        self.assertFalse(out["history_update_allowed"])
        self.assertEqual(out["raw_state"], "GREEN")
        self.assertEqual(out["raw_state_scope"], "UNVERIFIED_LEGACY_INPUT_DIAGNOSTIC")
        if code:
            self.assertIn(code, out["blockers"])

    def test_stale_source_cannot_be_current_green_or_advance_history(self):
        result = self.run_case(session="2026-03-20")
        self.assert_current_blocked(result, "STALE_SUCCESS_NOT_CURRENT_REPORT")
        self.assertEqual(result[0]["expected_session"], "2026-10-16")
        self.assertTrue(all(not r["fresh"] for r in result[0]["component_availability"]))

    def test_current_source_keeps_review_behavior_without_promotion(self):
        out, before, after, calls = self.run_case()
        self.assertEqual(out["state"], "GREEN")
        self.assertEqual(out["current_report_status"], "CURRENT_LEGACY_DIAGNOSTIC")
        self.assertEqual([a["action_type"] for a in out["paper_action_candidates"]], ["no_op"])
        self.assertEqual(calls, 1)
        self.assertNotEqual(before, after)
        for name in ("auto_trade_allowed", "source_clock_authenticated", "canonical_regime_authorized",
                     "source_promotion_allowed", "pit_promotion_allowed"):
            self.assertIs(out[name], False)

    def test_missing_or_malformed_source_date_is_not_execution_date(self):
        for session in (None, "", "2026-99-99", "2026-10-16T00:00:00Z"):
            with self.subTest(session=session):
                self.assert_current_blocked(self.run_case(session=session))

    def test_future_source_session_is_not_clamped(self):
        self.assert_current_blocked(self.run_case(session="2026-10-19"), "FUTURE_SOURCE_SESSION")

    def test_future_or_malformed_original_availability_blocks(self):
        for available in ("2026-10-18T00:00:00Z", "2026-10-16T22:00:00Z", "2026-10-16"):
            with self.subTest(available=available):
                def change(meta):meta["component_availability"][0]["available_from"] = available
                self.assert_current_blocked(self.run_case(mutate=change))

    def test_weekend_and_holiday_resolve_last_completed_xnys_session(self):
        for session, now in (("2026-10-16", "2026-10-18T15:00:00+00:00"),
                             ("2026-07-02", "2026-07-03T15:00:00+00:00")):
            with self.subTest(now=now):
                result = self.run_case(session=session, now=now)
                out = result[0]
                self.assertEqual(out["expected_session"], session)
                self.assert_current_blocked(result, "LATE_SESSION_NOT_RETROACTIVE")

    def test_early_close_uses_existing_one_hour_report_cutoff(self):
        self.assert_current_blocked(self.run_case(session="2026-11-27", now="2026-11-27T18:30:00+00:00"), "SLOT_NOT_DUE")
        out, _, _, _ = self.run_case(session="2026-11-27", now="2026-11-27T19:05:00+00:00")
        self.assertEqual(out["expected_session"], "2026-11-27")
        self.assertEqual(out["session_close_utc"], "2026-11-27T18:00:00+00:00")
        self.assertEqual(out["state"], "GREEN")

    def test_caller_time_cannot_backdate_legacy_current_report(self):
        self.assert_current_blocked(self.run_case(session="2026-03-20", report_now="2026-03-20T23:00:00Z"),
                                    "STALE_SUCCESS_NOT_CURRENT_REPORT")

    def test_missing_critical_inputs_are_data_health_not_market_risk(self):
        def change(meta):meta["missing_critical_components"] = ["hy_oas"]
        self.assert_current_blocked(self.run_case(mutate=change), "MISSING_CRITICAL_COMPONENTS")

    def test_missing_or_invalid_component_clock_records_refuse(self):
        for records in (None, [], 3, [None], [{}]):
            with self.subTest(records=records):
                self.assert_current_blocked(self.run_case(mutate=lambda meta:meta.update(component_availability=records)))

    def test_component_records_require_unique_complete_known_names_and_booleans(self):
        def duplicate(meta):meta["component_availability"].append(copy.deepcopy(meta["component_availability"][0]))
        def incomplete(meta):meta["component_availability"].pop()
        def unknown(meta):meta["component_availability"][0]["component"] = "unknown"
        def invalid_bool(meta):meta["component_availability"][0]["fresh"] = "true"
        def absent_clock(meta):meta["component_availability"][0].pop("available_from")
        for change in (duplicate, incomplete, unknown, invalid_bool, absent_clock):
            with self.subTest(change=change.__name__):
                self.assert_current_blocked(self.run_case(mutate=change))

    def test_critical_metadata_cannot_hide_missing_or_stale_values(self):
        def missing(meta):meta["canonical_state_inputs"].pop("hy_oas_zscore_252d")
        def stale(meta):meta["component_availability"][0]["fresh"] = False
        def unavailable(meta):meta["component_availability"][0]["available"] = False
        def hidden_stale(meta):meta["canonical_state_inputs"]["hy_oas_stale"] = True
        for change in (missing, stale, unavailable, hidden_stale):
            with self.subTest(change=change.__name__):
                self.assert_current_blocked(self.run_case(mutate=change))

    def test_available_noncritical_state_inputs_cannot_be_stale(self):
        for name in ("liquidity", "rate_shock"):
            with self.subTest(name=name):
                def change(meta):
                    next(r for r in meta["component_availability"] if r["component"] == name)["fresh"] = False
                self.assert_current_blocked(self.run_case(mutate=change), "STALE_STATE_INPUT")
                self.assert_current_blocked(self.run_case(mutate=lambda m:m["canonical_state_inputs"].update({name+"_stale":True})),
                                            "STALE_STATE_INPUT")

    def test_malformed_availability_still_writes_blocked_summary(self):
        for value in ({"bad":"clock"}, ["2026-10-16"], 3, True):
            with self.subTest(value=value):
                self.assert_current_blocked(self.run_case(mutate=lambda m:m["component_availability"][0].update(available_from=value)))
                self.assert_current_blocked(self.run_case(mutate=lambda m:m["canonical_state_inputs"].update(hy_oas_available_from=value)))

    def test_history_clock_is_bound_to_prior_new_york_report_window(self):
        for value in ("2026-10-16T21:30:00Z", "2026-10-16T04:00:00Z", "2026-10-15T20:59:59Z"):
            with self.subTest(value=value):
                self.assert_current_blocked(self.run_case(history_mutate=lambda h:h.update(updated_at_utc=value)),
                                            "HISTORY_CLOCK_INVALID")
        out = self.run_case(history_mutate=lambda h:h.update(updated_at_utc="2026-10-16T03:59:59Z"))[0]
        self.assertEqual(out["current_report_status"], "CURRENT_LEGACY_DIAGNOSTIC")

    def test_inference_failure_replaces_current_summary_with_blocked(self):
        out, before, after, calls = self.run_case(inference_error=ValueError("PRIVATE_INPUT_SENTINEL"))
        self.assertIsNone(out["state"])
        self.assertIsNone(out["raw_state"])
        self.assertEqual(out["current_report_status"], "BLOCKED")
        self.assertEqual(out["data_health"], "DATA_BLOCKED")
        self.assertEqual(out["paper_action_candidates"], [])
        self.assertEqual(before, after)
        self.assertEqual(calls, 0)
        self.assertNotIn("PRIVATE_INPUT_SENTINEL", json.dumps(out))

    def test_missing_stale_duplicate_or_malformed_history_requires_recovery(self):
        def absent(h):h.clear()
        def old(h):h.update(risk_as_of_session="2026-03-20", updated_at_utc="2026-03-20T22:00:00Z")
        def duplicate(h):h.update(risk_as_of_session="2026-10-16")
        def future(h):h.update(updated_at_utc="2026-10-19T00:00:00Z")
        def streak(h):h.update(raw_state_streak=True)
        def state(h):h.update(state="nonsense")
        for change in (absent, old, duplicate, future, streak, state):
            with self.subTest(change=change.__name__):
                self.assert_current_blocked(self.run_case(history_mutate=change))

    def test_all_raw_state_sidecar_clocks_are_required(self):
        for name in ("risk_controls", "safety_audit", "macro_policy", "portfolio_snapshot"):
            for field, value in (("report_session", "2026-03-20"), ("available_from", None),
                                 ("generated_at_utc", "2026-10-18T00:00:00Z")):
                with self.subTest(name=name, field=field):
                    def change(meta):meta["raw_state_sidecar_clocks"][name][field] = value
                    self.assert_current_blocked(self.run_case(mutate=change))
        self.assert_current_blocked(self.run_case(mutate=lambda m:m.pop("raw_state_sidecar_clocks")))

    def test_history_streak_bound_never_writes_an_unreadable_counter(self):
        out, _, _, _ = self.run_case(history_mutate=lambda h:h.update(raw_state_streak=clock.MAX_COMPLETED_SESSIONS-1))
        self.assertEqual(out["hysteresis"]["raw_state_streak"], clock.MAX_COMPLETED_SESSIONS)
        self.assert_current_blocked(self.run_case(history_mutate=lambda h:h.update(raw_state_streak=clock.MAX_COMPLETED_SESSIONS)),
                                    "HISTORY_STREAK_LIMIT")
        out, _, _, _ = self.run_case(history_mutate=lambda h:h.update(raw_state="DEFENSE", raw_state_streak=clock.MAX_COMPLETED_SESSIONS))
        self.assertEqual(out["current_report_status"], "CURRENT_LEGACY_DIAGNOSTIC")
        self.assertEqual(out["hysteresis"]["raw_state_streak"], 1)

    def test_native_inference_captures_clocks_from_all_consumed_sidecars(self):
        names = ("live_trading_risk_controls/risk_controls_summary.json", "live_trading_safety/safety_audit_summary.json",
                 "macro_policy_engine/summary.json", "operating_snapshot/current_portfolio_snapshot_summary.json")
        for path in names:
            target = self.root/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(dict(report_session="2026-03-20", available_from="2026-03-20T21:00:00Z",
                                              generated_at_utc="2026-03-20T21:00:00Z")))
        with patch.object(monitor, "infer_latest_long_crisis_state", return_value=("GREEN", [], {})):
            raw, _, meta = monitor.infer_raw_state(self.root, self.root/"unused", self.root/"unused")
        self.assertEqual(raw, "GREEN")
        self.assertEqual(set(meta["raw_state_sidecar_clocks"]), {"risk_controls", "safety_audit", "macro_policy", "portfolio_snapshot"})
        self.assertTrue(all(v["report_session"] == "2026-03-20" for v in meta["raw_state_sidecar_clocks"].values()))

    def test_blocked_monitor_cannot_feed_cadence_raw_or_integrated_fallback(self):
        from tools import run_decision_cadence_review as cadence
        payload = self.run_case(session="2026-03-20")[0]
        latest = self.root/"cadence_inputs"
        monitor_dir = latest/"daily_crisis_monitor"
        monitor_dir.mkdir(parents=True)
        integrated = latest/"integrated_theme_leader_crisis_replay"
        integrated.mkdir()
        (integrated/"daily_crisis_state.csv").write_text("crisis_state,reentry_stage\nGREEN,REENTRY_STAGE_1\n")
        for raw in ("GREEN", "DEFENSE", "CRISIS", "REENTRY_STAGE_1"):
            with self.subTest(raw=raw):
                payload["raw_state"] = raw
                (monitor_dir/"summary.json").write_text(json.dumps(payload))
                context = cadence.crisis_context(latest)
                self.assertIsNone(context["daily_monitor_state"])
                self.assertIsNone(context["daily_monitor_raw_state"])
                self.assertIsNone(context["daily_crisis_state_latest"])
                self.assertEqual(context["reentry_stage"], "")
                args = SimpleNamespace(latest_run=str(latest), price_cache=str(self.root/"unused"),
                                       output_dir=str(self.root/"cadence_output"), max_watchlist_candidates=1)
                old_output = Path(args.output_dir)
                old_output.mkdir(exist_ok=True)
                names = ("daily_holdings_review.csv", "weekly_watchlist_refresh.csv", "monthly_event_rerank_plan.json",
                         "decision_cadence_summary.json", "abcd_cadence_preregistration.json", "decision_cadence_report.md")
                for name in names:
                    (old_output/name).write_text("STALE_BUY_REENTRY")
                with patch.object(cadence, "current_holdings", side_effect=AssertionError("decision computation reached")):
                    with self.assertRaisesRegex(ValueError, "CURRENT_CRISIS_REPORT_BLOCKED"):
                        cadence.build_review(args)
                for name in names:
                    self.assertNotIn("STALE_BUY_REENTRY", (old_output/name).read_text())
                summary = json.loads((old_output/"decision_cadence_summary.json").read_text())
                self.assertEqual(summary["current_report_status"], "BLOCKED")
                self.assertFalse(summary["available"])
                self.assertFalse(summary["new_buy_allowed"])
                self.assertFalse(summary["mid_month_reentry_allowed"])
                self.assertEqual(summary["event_triggers_active"], [])
                self.assertTrue(pd.read_csv(old_output/"daily_holdings_review.csv").empty)
                self.assertTrue(pd.read_csv(old_output/"weekly_watchlist_refresh.csv").empty)

    def test_cadence_requires_current_monitor_without_missing_or_old_fallback(self):
        from tools import run_decision_cadence_review as cadence
        valid = self.run_case()[0]
        latest = self.root/"current_cadence"
        monitor_dir = latest/"daily_crisis_monitor"
        monitor_dir.mkdir(parents=True)
        integrated = latest/"integrated_theme_leader_crisis_replay"
        integrated.mkdir()
        (integrated/"daily_crisis_state.csv").write_text("crisis_state,reentry_stage\nGREEN,REENTRY_STAGE_1\n")
        cases = (None, {"state":"GREEN", "raw_state":"GREEN"},
                 dict(valid, generated_at_utc="2026-03-20T22:00:00Z"),
                 dict(valid, risk_as_of_session="2026-03-20"),
                 dict(valid, generated_at_utc="2026-10-18T00:00:00Z"))
        with patch.object(clock, "trusted_now", return_value=datetime.fromisoformat("2026-10-17T00:45:00+00:00")):
            for payload in cases:
                with self.subTest(payload=payload):
                    path = monitor_dir/"summary.json"
                    if payload is None:path.unlink(missing_ok=True)
                    else:path.write_text(json.dumps(payload))
                    context = cadence.crisis_context(latest)
                    self.assertEqual(context["current_report_status"], "BLOCKED")
                    self.assertIsNone(context["daily_monitor_state"])
                    self.assertIsNone(context["daily_crisis_state_latest"])
                    self.assertEqual(context["reentry_stage"], "")
            (monitor_dir/"summary.json").write_text(json.dumps(valid))
            self.assertEqual(cadence.crisis_context(latest)["daily_monitor_state"], "GREEN")

    def test_cadence_requires_canonical_states_and_uses_current_reentry_only(self):
        from tools import run_decision_cadence_review as cadence
        valid = self.run_case()[0]
        latest = self.root/"typed_cadence"
        monitor_dir = latest/"daily_crisis_monitor"
        monitor_dir.mkdir(parents=True)
        integrated = latest/"integrated_theme_leader_crisis_replay"
        integrated.mkdir()
        (integrated/"daily_crisis_state.csv").write_text("crisis_state,reentry_stage\nGREEN,REENTRY_STAGE_3\n")
        with patch.object(clock, "trusted_now", return_value=datetime.fromisoformat("2026-10-17T00:45:00+00:00")):
            for key in ("state", "raw_state"):
                for value in (None, "", "NORMAL", "REENTRY_READY", "GREEN ", True, {}, []):
                    with self.subTest(key=key, value=value):
                        (monitor_dir/"summary.json").write_text(json.dumps(dict(valid, **{key:value})))
                        context = cadence.crisis_context(latest)
                        self.assertEqual(context["current_report_status"], "BLOCKED")
                        self.assertIsNone(context["daily_monitor_state"])
                        self.assertEqual(context["reentry_stage"], "")
            for state, stage in (("GREEN", ""), ("REENTRY_STAGE_1", "REENTRY_STAGE_1")):
                (monitor_dir/"summary.json").write_text(json.dumps(dict(valid, state=state)))
                context = cadence.crisis_context(latest)
                self.assertEqual(context["daily_monitor_state"], state)
                self.assertEqual(context["daily_monitor_raw_state"], "GREEN")
                self.assertEqual(context["reentry_stage"], stage)

    def test_explicit_historical_report_route_remains_separate(self):
        marker = {"current_report_status":"READY_DRY_RUN", "input_kind":"FIXTURE"}
        with patch.object(monitor, "build_clock_report", return_value=marker) as route:
            self.assertIs(build_monitor(SimpleNamespace(report_slot="AFTER_CLOSE", report_session="2025-01-02")), marker)
        route.assert_called_once()

    def test_original_source_clocks_missing_expired_and_mismatched_refuse(self):
        def missing(meta):meta.pop("source_clocks")
        def expired(meta):meta["source_clocks"]["hy_oas"]["expiry"] = "2026-03-21T00:00:00Z"
        def mismatch(meta):meta["source_clocks"]["vix"]["observation_date"] = "2026-03-20"
        def future(meta):meta["source_clocks"]["dgs10"]["collected_at"] = "2026-10-18T00:00:00Z"
        for change in (missing, expired, mismatch, future):
            with self.subTest(change=change.__name__):
                self.assert_current_blocked(self.run_case(mutate=change))

    def test_current_thresholds_require_complete_pinned_exact_values(self):
        from tools.crisis_state_engine import load_long_crisis_thresholds
        path = self.root/"strict.json"
        valid = dict(governor_thresholds=dict(low=.35, mid=.55, high=.75),
                     cash_hard_gate=dict(liquidity_gate=.35, trend_gate=.35, credit_gate=.55))
        for invalid in ({}, dict(governor_thresholds=valid["governor_thresholds"]),
                        dict(valid, governor_thresholds=dict(low=True, mid=.55, high=.75)),
                        dict(valid, cash_hard_gate=dict(liquidity_gate=".35", trend_gate=.35, credit_gate=.55))):
            path.write_text(json.dumps(invalid))
            with self.assertRaises((ValueError, KeyError, TypeError)):
                load_long_crisis_thresholds(path, require_complete=True,
                    expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        path.write_text(json.dumps(valid))
        with self.assertRaises(ValueError):
            load_long_crisis_thresholds(path, require_complete=True, expected_sha256="b"*64)
        result = load_long_crisis_thresholds(path, require_complete=True,
                    expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual([result[k] for k in ("low", "mid", "high", "liquidity_gate", "trend_gate", "credit_gate")],
                         [.35, .55, .75, .35, .35, .55])
        self.assert_current_blocked(self.run_case(mutate=lambda m:m.update(thresholds_sha256="b"*64)),
                                    "CURRENT_CONFIG_PROOF_REQUIRED")

    def test_unbound_holdings_never_produce_action_candidates(self):
        for field, value in (("summary_sha256", "b"*64), ("holdings_sha256", "c"*64),
                             ("book_session", "2026-10-15"), ("report_session", None)):
            with self.subTest(field=field):
                out, _, _, _ = self.run_case(mutate=lambda m:m["portfolio_snapshot_binding"].update({field:value}))
                self.assertEqual(out["holdings_binding"]["status"], "BLOCKED_HOLDINGS_PROOF")
                self.assertEqual(out["paper_action_candidates"], [])

    def test_producer_preserves_clocks_through_ffill_and_current_inference(self):
        from r1000_long_crisis_liquidity import source_clock_panel
        from tools.crisis_state_engine import infer_long_crisis_state_from_row, load_long_crisis_thresholds
        dates = pd.DatetimeIndex(["2026-03-20", "2026-10-16"])
        series = pd.Series([18.0], index=dates[:1])
        series.attrs["observation_clocks"] = {"2026-03-20":dict(available_from="2026-03-20T20:15:00Z",
            collected_at="2026-03-20T20:20:00Z", expiry="2026-03-21T00:00:00Z", source_sha256="a"*64)}
        panel = source_clock_panel(series, dates)
        self.assertEqual(json.loads(panel.iloc[-1])["observation_date"], "2026-03-20")
        self.assertEqual(json.loads(panel.iloc[-1])["available_from"], "2026-03-20T20:15:00Z")
        row = pd.Series(dict(crisis_score=.1, vix_zscore_252d=.1,
            source_clocks_json=json.dumps(dict(vix=json.loads(panel.iloc[-1])))))
        _, _, meta = infer_long_crisis_state_from_row(row, load_long_crisis_thresholds(self.root/"absent"),
            asof_date=dates[-1], source_clock_required=True)
        vix = next(item for item in meta["component_availability"] if item["component"] == "vix")
        self.assertEqual(vix["available_from"], "2026-03-20T20:15:00+00:00")
        self.assertNotIn("2026-10-16", vix["available_from"])

    def test_fred_snapshot_preserves_observation_realtime_and_fetch_clock(self):
        from tools import macro_daily_snapshot as daily
        raw = json.dumps(dict(realtime_start="2026-10-17", realtime_end="2026-10-17",
            observations=[dict(date="2026-10-14", value="4.25", realtime_start="2026-10-17",
                               realtime_end="2026-10-17")])).encode()
        with patch.object(daily.urllib.request, "urlopen", return_value=io.BytesIO(raw)):
            record = daily.fetch_fred_observation("DGS10", "fixture-not-real")
        self.assertEqual(record["value"], 4.25)
        self.assertEqual(record["observation_date"], "2026-10-14")
        self.assertEqual(record["realtime_start"], "2026-10-17")
        self.assertIsNotNone(record["collected_at_utc"])
        self.assertIsNone(record["published_at_utc"])
        self.assertEqual(record["availability_status"], "UNKNOWN")
        self.assertNotIn("fixture-not-real", json.dumps(record))
        with patch.object(daily.urllib.request, "urlopen", return_value=io.BytesIO(raw)):
            self.assertEqual(daily.fetch_fred_series("DGS10", "fixture-not-real"), 4.25)

    def test_feature_numeric_panel_preserved_with_lagged_clock_provenance(self):
        from r1000_long_crisis_liquidity import build_long_crisis_features
        dates = pd.bdate_range("2025-01-02", "2026-10-16")
        market = pd.Series(range(100, 100+len(dates)), index=dates, dtype=float)
        macros = {name:market.copy() for name in
                  ("vix", "hy_oas", "dgs10", "dxy", "fed_assets", "reverse_repo", "tga")}
        monthly = pd.date_range("2024-01-01", "2026-10-01", freq="MS")
        macros["m2"] = pd.Series(range(1000,1000+len(monthly)), index=monthly, dtype=float)
        before = build_long_crisis_features(market, macros, qqq_close=market, start="2025-01-02")
        macros["m2"].attrs["observation_clocks"] = {d.date().isoformat():dict(
            available_from=(d+pd.Timedelta(days=15)).tz_localize("UTC").isoformat()) for d in monthly}
        after = build_long_crisis_features(market, macros, qqq_close=market, start="2025-01-02")
        pd.testing.assert_frame_equal(before.drop(columns="source_clocks_json"), after.drop(columns="source_clocks_json"))
        m2 = json.loads(after.iloc[-1]["source_clocks_json"])["m2"]
        self.assertEqual(m2["observation_date"], "2026-09-01")
        self.assertEqual(m2["available_from"], "2026-09-16T00:00:00+00:00")


def run_currentness_tests():
    result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(LegacyCurrentnessTests))
    if not result.wasSuccessful():
        raise RuntimeError("LEGACY_CURRENT_REPORT_CLOCK_FAILED")


if __name__ == "__main__":
    test_daily_crisis_monitor_uses_learned_long_crisis_gate()
    test_daily_crisis_monitor_blocks_unconfirmed_vix_only_cash_raise()
    run_currentness_tests()
    from daily_crisis_report_clock_smoke import run_tests
    run_tests()
    print("daily_crisis_monitor_long_crisis_smoke: PASS")
