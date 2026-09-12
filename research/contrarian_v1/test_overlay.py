"""Offline SYNTHETIC contract tests, not a profitability backtest."""
import copy
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from overlay import CONFIG, FLAGS, SENTIMENT, config_hash, digest, evaluate, historical_percentile

ROOT = Path(__file__).resolve().parent


def packet(score=50.0, session="2026-09-04", previous="2026-09-03"):
    p = json.loads((ROOT / "synthetic_input.json").read_text())
    p["session"], p["previous_session"] = session, previous
    p["decision_at"] = session + "T20:15:00Z"
    for key, obs in p["evidence"].items():
        obs["observed_at"] = session + "T20:00:00Z"
        obs["available_at"] = session + "T20:05:00Z"
        if key in SENTIMENT:
            obs["value"] = score
    return p


def change(p, **kwargs):
    for key, value in kwargs.items():
        p["evidence"][key]["value"] = value
    return p


def advance(p, result, session="2026-09-08", filled=True):
    q = copy.deepcopy(p)
    q["previous_session"], q["session"] = p["session"], session
    q["decision_at"] = session + "T20:15:00Z"
    for obs in q["evidence"].values():
        obs["observed_at"] = session + "T20:00:00Z"
        obs["available_at"] = session + "T20:05:00Z"
    if filled and result["proposed_equity"] is not None:
        q["current_equity"] = result["proposed_equity"]
    return q


def confirmed(p):
    first = evaluate(p)
    second = advance(p, first)
    return second, evaluate(second, first["state"])


class OverlayTests(unittest.TestCase):
    def test_neutral_no_cash_drag(self):
        p = packet(); p.update(baseline_equity=.95, current_equity=.95)
        r = evaluate(p)
        self.assertEqual(r["proposed_cash"], .05)
        self.assertEqual(r["state"]["tilt"], 0)

    def test_fear_requires_two_sessions(self):
        p = packet(10)
        self.assertEqual(evaluate(p)["proposed_equity"], .85)
        _, r = confirmed(p)
        self.assertEqual(r["proposed_equity"], .90)
        self.assertEqual(r["desired_equity"], .95)

    def test_fear_ladder_bounded_no_daily_additive_drift(self):
        p, r = confirmed(packet(10))
        for day in ("2026-09-09", "2026-09-10", "2026-09-11"):
            p = advance(p, r, day)
            r = evaluate(p, r["state"])
        self.assertEqual(r["proposed_equity"], .95)
        self.assertEqual(r["state"]["tilt"], .10)

    def test_prior_proposal_is_not_a_fill(self):
        p, r = confirmed(packet(10))
        p = advance(p, r, "2026-09-09", filled=False)
        r = evaluate(p, r["state"])
        self.assertEqual(r["proposed_equity"], .90)

    def test_healthy_greed_does_not_sell(self):
        _, r = confirmed(change(packet(95), valuation_attractive=False))
        self.assertEqual(r["proposed_equity"], .85)

    def test_stretched_greed_needs_second_confirmation(self):
        _, r = confirmed(change(packet(95), valuation_attractive=False, valuation_stretched=True))
        self.assertEqual(r["proposed_equity"], .85)

    def test_greed_ladder(self):
        p = change(packet(95), valuation_attractive=False, valuation_stretched=True,
                   breadth_improving=False, breadth_deteriorating=True)
        p, r = confirmed(p)
        self.assertEqual(r["proposed_equity"], .80)
        self.assertEqual(r["desired_equity"], .75)
        for day in ("2026-09-09", "2026-09-10", "2026-09-11"):
            p = advance(p, r, day); r = evaluate(p, r["state"])
        self.assertEqual(r["proposed_equity"], .75)

    def test_greed_reserve_released_without_permanent_cash_drag(self):
        p = change(packet(95), valuation_attractive=False, valuation_stretched=True,
                   breadth_improving=False, breadth_deteriorating=True)
        p, r = confirmed(p)
        p = advance(p, r, "2026-09-09")
        for key in SENTIMENT: p["evidence"][key]["value"] = 50
        change(p, valuation_stretched=False, breadth_deteriorating=False)
        r = evaluate(p, r["state"])
        self.assertEqual(r["state"]["tilt"], 0)
        self.assertEqual(r["proposed_equity"], .85)

    def test_panic_addition_not_sold_merely_on_sentiment_normalization(self):
        p, r = confirmed(packet(10)); p = advance(p, r, "2026-09-09")
        for k in SENTIMENT: p["evidence"][k]["value"] = 50
        r = evaluate(p, r["state"])
        self.assertEqual(r["state"]["tilt"], .10)
        self.assertGreaterEqual(r["proposed_equity"], p["current_equity"])

    def test_systemic_fear_no_buy(self):
        _, r = confirmed(change(packet(0), systemic_crisis=True))
        self.assertLessEqual(r["proposed_equity"], .85)
        self.assertEqual(r["state"]["tilt"], 0)

    def test_credit_and_liquidity_each_veto(self):
        for field in ("credit_deteriorating", "liquidity_deteriorating"):
            with self.subTest(field=field):
                _, r = confirmed(change(packet(0), **{field: True}))
                self.assertLessEqual(r["proposed_equity"], .85)

    def test_fundamental_break_veto(self):
        for flags in ({"fundamentals_intact": False}, {"earnings_deteriorating": True}):
            _, r = confirmed(change(packet(0), **flags))
            self.assertEqual(r["state"]["tilt"], 0)

    def test_fear_requires_value(self):
        _, r = confirmed(change(packet(0), valuation_attractive=False))
        self.assertEqual(r["state"]["tilt"], 0)

    def test_fear_requires_two_stabilizers(self):
        _, r = confirmed(change(packet(0), breadth_improving=False, volatility_easing=False))
        self.assertEqual(r["state"]["tilt"], 0)

    def test_no_200_day_trend_requirement(self):
        _, r = confirmed(packet(0))
        self.assertEqual(r["state"]["tilt"], .1)
        self.assertNotIn("ma200", json.dumps(packet()))

    def test_upstream_no_buy_veto(self):
        p = packet(0); p["new_buys_allowed"] = False
        _, r = confirmed(p)
        self.assertEqual(r["proposed_equity"], .85)

    def test_upstream_cap_dominates_ladder_and_buffer(self):
        p = packet(0); p["risk_cap"] = .40
        r = evaluate(p)
        self.assertEqual(r["proposed_equity"], .40)
        p["risk_cap"] = .845
        self.assertEqual(evaluate(p)["proposed_equity"], .845)

    def test_capacity_dominates(self):
        p = packet(0); p["eligible_equity_cap"] = .88
        _, r = confirmed(p)
        self.assertEqual(r["proposed_equity"], .88)

    def test_kill_switch_delegates_not_zero_weight_order(self):
        p = packet(); p["kill_switch"] = True; p["evidence"] = {}
        r = evaluate(p)
        self.assertEqual(r["status"], "DELEGATE_KILL_SWITCH")
        self.assertIsNone(r["proposed_equity"])
        self.assertFalse(r["orders_allowed"])

    def test_missing_never_becomes_neutral_or_cash_order(self):
        for field in SENTIMENT + FLAGS:
            p = packet(0); del p["evidence"][field]
            r = evaluate(p)
            self.assertEqual(r["status"], "BLOCKED_EVIDENCE")
            self.assertIsNone(r["proposed_equity"])

    def test_future_publication_blocked(self):
        p = packet(); p["evidence"][SENTIMENT[0]]["available_at"] = "2026-09-04T21:00:00Z"
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_old_observation_cannot_be_refreshed_by_new_download(self):
        p = packet(); p["evidence"][SENTIMENT[1]]["observed_at"] = "2026-08-20T20:00:00Z"
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_no_timezone_blocked(self):
        p = packet(); p["evidence"][SENTIMENT[0]]["available_at"] = "2026-09-04T20:05:00"
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_string_boolean_never_truthy(self):
        p = packet(0); p["new_buys_allowed"] = "false"
        with self.assertRaises(ValueError): evaluate(p)
        p = change(packet(0), systemic_crisis="false")
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_bad_numbers_and_hashes(self):
        for value in (True, float("nan"), float("inf"), -.1, 1.01):
            p = packet(); p["risk_cap"] = value
            with self.assertRaises(ValueError): evaluate(p)
        p = packet(); p["upstream_manifest_sha256"] = "not-a-hash"
        with self.assertRaises(ValueError): evaluate(p)

    def test_unknown_future_labels_rejected(self):
        p = packet(); p["evidence"]["future_return_1m"] = {}
        with self.assertRaises(ValueError): evaluate(p)

    def test_us_kr_cannot_mix(self):
        p = packet(); p["evidence"][SENTIMENT[0]]["market"] = "KR"
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")
        p = packet(); r = evaluate(p); p["market"] = "KR"
        with self.assertRaises(ValueError): evaluate(p, r["state"])

    def test_separate_kr_packet_supported_not_data_adapter_claim(self):
        p = packet(0); p["market"] = "KR"
        for obs in p["evidence"].values(): obs["market"] = "KR"
        _, r = confirmed(p)
        self.assertEqual(r["state"]["tilt"], .10)
        self.assertFalse(r["historical_pit_verified"])

    def test_duplicate_component_source_blocked(self):
        p = packet(); p["evidence"][SENTIMENT[1]] = copy.deepcopy(p["evidence"][SENTIMENT[0]])
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_contradictions_blocked(self):
        p = change(packet(), valuation_stretched=True)
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")
        p = change(packet(), breadth_deteriorating=True)
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_hysteresis(self):
        p, r = confirmed(packet(10)); p = advance(p, r, "2026-09-09")
        for k in SENTIMENT: p["evidence"][k]["value"] = 30
        r = evaluate(p, r["state"])
        self.assertEqual(r["state"]["zone"], "FEAR")
        p = advance(p, r, "2026-09-10")
        for k in SENTIMENT: p["evidence"][k]["value"] = 35
        self.assertEqual(evaluate(p, r["state"])["state"]["zone"], "NEUTRAL")

    def test_gap_resets_confirmation(self):
        p = packet(0); r = evaluate(p)
        p = advance(p, r, "2026-09-09"); p["previous_session"] = "2026-09-08"
        r = evaluate(p, r["state"])
        self.assertEqual(r["state"]["streak"], 1)
        self.assertEqual(r["state"]["tilt"], 0)

    def test_duplicate_and_conflicting_same_session(self):
        p = packet(0); r = evaluate(p)
        self.assertEqual(evaluate(p, r["state"])["status"], "DUPLICATE_SESSION")
        p["current_equity"] = .9
        with self.assertRaises(ValueError): evaluate(p, r["state"])

    def test_prior_tamper_and_future_blocked(self):
        p = packet(0); r = evaluate(p); state = copy.deepcopy(r["state"])
        state["tilt"] = .9
        with self.assertRaises(ValueError): evaluate(p, state)
        state = copy.deepcopy(r["state"]); state["session"] = "2026-09-10"
        del state["state_hash"]; state["state_hash"] = digest(state)
        with self.assertRaises(ValueError): evaluate(p, state)

    def test_no_input_mutation_deterministic(self):
        p = packet(0); before = copy.deepcopy(p)
        r1 = evaluate(p); r2 = evaluate(p)
        self.assertEqual(r1, r2); self.assertEqual(p, before)

    def test_percentile_helper_not_pit_attestation(self):
        self.assertEqual(historical_percentile(2, [1,2,3], higher_is_greed=True, min_observations=3), 50)
        self.assertEqual(historical_percentile(4, [1,2,3], higher_is_greed=False, min_observations=3), 0)
        with self.assertRaises(ValueError): historical_percentile(1, [1], higher_is_greed=True)
        self.assertEqual(historical_percentile(1, [1,1], higher_is_greed=True, min_observations=2), 50)

    def test_cli_smoke_and_duplicate_json_key(self):
        process = subprocess.run([sys.executable, str(ROOT / "overlay.py"), str(ROOT / "synthetic_input.json")],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0)
        self.assertFalse(json.loads(process.stdout)["orders_allowed"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp)/"bad.json"; bad.write_text('{"x":1,"x":2}')
            process = subprocess.run([sys.executable, str(ROOT / "overlay.py"), str(bad)],
                                     capture_output=True, text=True, check=False)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads(process.stdout)["status"], "INVALID_INPUT")

    def test_legacy_tilt_double_counting_blocked(self):
        p = packet(0); p["baseline_excludes_contrarian"] = False
        r = evaluate(p)
        self.assertEqual(r["status"], "BLOCKED_BASELINE")
        self.assertIsNone(r["proposed_equity"])

    def test_broken_fundamentals_block_baseline_increase_too(self):
        p = change(packet(0), fundamentals_intact=False)
        p.update(baseline_equity=.95, current_equity=.60)
        self.assertEqual(evaluate(p)["proposed_equity"], .60)

    def test_one_source_cannot_count_twice_with_different_hashes(self):
        p = packet()
        p["evidence"][SENTIMENT[1]]["source"] = p["evidence"][SENTIMENT[0]]["source"]
        self.assertEqual(evaluate(p)["status"], "BLOCKED_EVIDENCE")

    def test_randomized_safety_invariants(self):
        rng = random.Random(402)
        for _ in range(1000):
            p = packet(rng.uniform(0,100))
            p.update(baseline_equity=rng.random(), current_equity=rng.random(),
                     risk_cap=rng.random(), eligible_equity_cap=rng.random(),
                     new_buys_allowed=rng.choice([True,False]))
            r = evaluate(p); w = r["proposed_equity"]
            self.assertGreaterEqual(w, 0); self.assertLessEqual(w, min(p["risk_cap"], p["eligible_equity_cap"])+1e-8)
            self.assertAlmostEqual(w+r["proposed_cash"], 1)
            self.assertLessEqual(w-p["current_equity"], CONFIG["max_step"]+1e-8)
            if not p["new_buys_allowed"]: self.assertLessEqual(w, p["current_equity"]+1e-8)
            self.assertFalse(r["orders_allowed"]); self.assertFalse(r["production_activation_allowed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
