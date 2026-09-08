"""Synthetic regression: retaining filled exposure is not a fresh buy approval."""
import copy
import random
import unittest
from overlay import FLAGS, SENTIMENT, evaluate


def fixture(score=10, session="2026-09-03", previous="2026-09-02"):
    values = dict.fromkeys(FLAGS, False)
    values.update(fundamentals_intact=True, valuation_attractive=True,
                  breadth_improving=True, volatility_easing=True, price_stabilizing=True)
    values.update(dict.fromkeys(SENTIMENT, score))
    return {
        "schema": "contrarian-input-v1", "market": "US", "session": session,
        "previous_session": previous, "decision_at": session + "T20:15:00Z",
        "baseline_equity": .85, "current_equity": .85, "risk_cap": 1.,
        "eligible_equity_cap": 1., "new_buys_allowed": True, "kill_switch": False,
        "baseline_excludes_contrarian": True, "upstream_manifest_sha256": "0" * 64,
        "evidence": {k: {"value": v, "observed_at": session + "T20:00:00Z",
                         "available_at": session + "T20:05:00Z",
                         "source": "SYNTHETIC:" + k, "sha256": "1" * 64,
                         "market": "US"} for k, v in values.items()},
    }


def prior_fear():
    first = evaluate(fixture())
    second = fixture(session="2026-09-04", previous="2026-09-03")
    return evaluate(second, first["state"])["state"]


def next_packet(score=50, current=.85):
    p = fixture(score, session="2026-09-08", previous="2026-09-04")
    p["current_equity"] = current
    return p


class EntryReauthorizationTests(unittest.TestCase):
    def test_unfilled_fear_not_executed_after_normalization(self):
        p = next_packet()
        self.assertEqual(evaluate(p, prior_fear())["proposed_equity"], .85)

    def test_no_stale_fear_buy_after_gap(self):
        p = fixture(50, session="2026-09-09", previous="2026-09-08")
        p["evidence"]["valuation_attractive"]["value"] = False
        r = evaluate(p, prior_fear())
        self.assertEqual(r["state"]["streak"], 1)
        self.assertEqual(r["proposed_equity"], .85)

    def test_fear_continuation_requires_current_value(self):
        p = next_packet(10)
        p["evidence"]["valuation_attractive"]["value"] = False
        self.assertEqual(evaluate(p, prior_fear())["proposed_equity"], .85)

    def test_fear_continuation_requires_current_stability(self):
        p = next_packet(10)
        for name in ("breadth_improving", "volatility_easing", "price_stabilizing"):
            p["evidence"][name]["value"] = False
        self.assertEqual(evaluate(p, prior_fear())["proposed_equity"], .85)

    def test_partially_filled_addition_is_held_not_completed(self):
        r = evaluate(next_packet(current=.90), prior_fear())
        self.assertEqual(r["proposed_equity"], .90)
        self.assertEqual(r["state"]["tilt"], .10)

    def test_fully_filled_addition_not_sold_for_normalization(self):
        self.assertEqual(evaluate(next_packet(current=.95), prior_fear())["proposed_equity"], .95)

    def test_upstream_baseline_increase_remains_separate(self):
        p = next_packet(current=.80)
        self.assertEqual(evaluate(p, prior_fear())["proposed_equity"], .85)

    def test_upstream_cap_still_overrides_hold(self):
        p = next_packet(current=.95); p["risk_cap"] = .88
        self.assertEqual(evaluate(p, prior_fear())["proposed_equity"], .88)

    def test_no_buy_still_overrides_every_increase(self):
        p = next_packet(10); p["new_buys_allowed"] = False
        self.assertEqual(evaluate(p, prior_fear())["proposed_equity"], .85)

    def test_current_qualified_fear_still_deploys(self):
        self.assertEqual(evaluate(next_packet(10), prior_fear())["proposed_equity"], .90)

    def test_gap_requires_reconfirmation_before_new_fear_add(self):
        p = fixture(10, session="2026-09-09", previous="2026-09-08")
        first = evaluate(p, prior_fear())
        self.assertEqual(first["proposed_equity"], .85)
        p = fixture(10, session="2026-09-10", previous="2026-09-09")
        self.assertEqual(evaluate(p, first["state"])["proposed_equity"], .90)

    def test_greed_trim_unchanged(self):
        p = fixture(90)
        for name, value in {"valuation_attractive": False, "valuation_stretched": True,
                            "breadth_improving": False, "breadth_deteriorating": True}.items():
            p["evidence"][name]["value"] = value
        first = evaluate(p)
        q = copy.deepcopy(p)
        q.update(session="2026-09-04", previous_session="2026-09-03", decision_at="2026-09-04T20:15:00Z")
        for obs in q["evidence"].values():
            obs.update(observed_at="2026-09-04T20:00:00Z", available_at="2026-09-04T20:05:00Z")
        self.assertEqual(evaluate(q, first["state"])["proposed_equity"], .80)

    def test_randomized_hold_only_boundaries(self):
        rng = random.Random(20260908)
        prior = prior_fear()
        for _ in range(1000):
            p = next_packet(score=50, current=rng.uniform(0, 1))
            p.update(baseline_equity=rng.uniform(0, 1), risk_cap=rng.uniform(0, 1),
                     eligible_equity_cap=rng.uniform(0, 1))
            r = evaluate(p, prior)
            ceiling = min(p["risk_cap"], p["eligible_equity_cap"])
            self.assertLessEqual(r["proposed_equity"], ceiling + 1e-8)
            self.assertLessEqual(r["proposed_equity"], max(p["current_equity"], p["baseline_equity"]) + 1e-8)
            self.assertGreaterEqual(r["proposed_equity"], 0)
            self.assertFalse(r["orders_allowed"])
            self.assertAlmostEqual(r["proposed_equity"] + r["proposed_cash"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
