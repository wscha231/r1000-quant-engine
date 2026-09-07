"""Mechanical connection tests only; these fixtures provide no alpha evidence."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_decision_v1_fixture import rehash
from research_decision_v1_decision_fixture import with_scenario, config, context
from tools.research_decision_v1.data import export_market
from tools.research_decision_v1.engine import run_decisions


def evaluate(b=None, ctx=None, previous=None):
    b = b or with_scenario()
    return run_decisions([export_market(b, b["market"])], ctx or context(), config(), previous)


class DecisionTests(unittest.TestCase):
    def test_ev_scenario_arithmetic_reverse_and_horizons(self):
        r = evaluate()["ranking"][0]
        self.assertEqual([s["target_price"] for s in r["scenarios"]], [74., 189., 291.])
        self.assertAlmostEqual(r["expected_total_return"], .8575)
        self.assertAlmostEqual(r["reverse_valuation"]["required_revenue"], 10900/1.8)
        self.assertIsNone(r["statistical_loss_probability"])
        self.assertTrue(all(v["return"] is None for v in r["short_horizons"].values()))
        self.assertEqual(set(r["four_questions"]), {"good_company", "good_stock", "buy_price_now", "portfolio_value"})

    def test_pe_does_not_subtract_net_debt_twice(self):
        b = with_scenario(); sc = b["securities"][0]["blocks"]["scenario"]
        sc["payload"]["method"] = "PE"; rehash(sc)
        self.assertEqual(evaluate(b)["ranking"][0]["scenarios"][1]["target_price"], 198.)

    def test_probability_horizon_and_duplicate_buyback_block(self):
        for mutation in (lambda p: p["scenarios"][0].update(probability=.9),
                         lambda p: p.update(horizon_months=6),
                         lambda p: p["scenarios"][1].update(buyback_yield=.1),
                         lambda p: p.update(method="UNSUPPORTED_DCF")):
            b = with_scenario(); sc = b["securities"][0]["blocks"]["scenario"]
            mutation(sc["payload"]); rehash(sc)
            r = evaluate(b)
            self.assertFalse(r["ranking"][0]["valuation_ready"])
            self.assertEqual(r["portfolio_proposal"]["cash_weight"], 1.)

    def test_dividend_does_not_invert_bear_base_bull_order(self):
        b = with_scenario(); sc = b["securities"][0]["blocks"]["scenario"]
        sc["payload"]["scenarios"][0]["dividend"] = 200.; rehash(sc)
        r = evaluate(b)
        self.assertFalse(r["ranking"][0]["valuation_ready"])
        self.assertIn("valuation:scenario_return_order_invalid", r["ranking"][0]["blockers"])

    def test_fx_conversion_and_invalid_fx_preserves_local_rank(self):
        ctx = context(); ctx["fx"]["scenario_rates"] = {s: 1540. for s in ("Bear", "Base", "Bull")}
        r = evaluate(ctx=ctx)["ranking"][0]
        self.assertAlmostEqual(r["expected_total_return_krw"], (1+.8575)*1.1-1)
        ctx["fx"]["status"] = "missing"
        out = evaluate(ctx=ctx)
        self.assertEqual(out["ranking"][0]["investment_rank_local"], 1)
        self.assertIsNone(out["ranking"][0]["investment_rank"])
        self.assertFalse(out["portfolio_proposal"]["ready"])

    def test_ties_determinism_and_immutable_previous_change_reasons(self):
        b = with_scenario(ticker="BBB"); b["securities"] += with_scenario(ticker="AAA")["securities"]
        first = evaluate(b)
        self.assertEqual(first, evaluate(copy.deepcopy(b)))
        self.assertEqual(first["ranking"][0]["security_id"], "US:AAA")
        self.assertEqual(first["ranking"][0]["investment_rank"], 1)
        sc = b["securities"][0]["blocks"]["scenario"]
        sc["payload"]["scenarios"][1]["revenue"] *= 1.05; rehash(sc)
        second = evaluate(b, previous=first)
        changed = next(r for r in second["ranking"] if r["security_id"] == "US:BBB")
        self.assertIn("estimates", changed["rank_change_reasons"])
        self.assertNotEqual(first["decision_hash"], second["decision_hash"])
        self.assertEqual(second["previous_decision_hash"], first["decision_hash"])

    def test_small_us_two_kr_one_connection(self):
        us = with_scenario(ticker="AAA"); us["securities"] += with_scenario(ticker="BBB")["securities"]
        us["securities"][1]["blocks"]["risk"]["payload"]["exposures"]["industry:other"] = 1.
        rehash(us["securities"][1]["blocks"]["risk"])
        kr = with_scenario("KR")
        out = run_decisions([export_market(us, "US"), export_market(kr, "KR")], context(), config())
        self.assertTrue(out["readiness"]["portfolio_proposal_ready"])
        self.assertFalse(out["readiness"]["target_5_plus_2_complete"])
        p = out["portfolio_proposal"]
        self.assertAlmostEqual(sum(r["target_weight"] for r in p["rows"])+p["cash_weight"], 1.)
        self.assertFalse(p["constraints"]["violations"])
        self.assertFalse(out["readiness"]["oos_validated"])

    def test_export_tampering_and_mixed_data_kind(self):
        ex = export_market(with_scenario(), "US"); ex["securities"][0]["discovery"]["price"] = 1.
        with self.assertRaisesRegex(ValueError, "market_export_replay_mismatch"): run_decisions([ex], context(), config())
        kr = {"schema_version": "research-input-v1", "market": "KR", "data_kind": "REAL",
              "decision_cutoff": context()["decision_cutoff"], "securities": [
                  {"security_id": "KR:000660", "ticker": "000660", "market": "KR", "currency": "KRW", "blocks": {}}]}
        with self.assertRaisesRegex(ValueError, "synthetic_and_real_must_not_mix"):
            run_decisions([export_market(with_scenario(), "US"), export_market(kr, "KR")], context(), config())

    def test_incumbent_not_exited_on_short_rs_or_entry_failure(self):
        b = with_scenario(); s = b["securities"][0]; p = s["blocks"]["price"]
        p["payload"]["bars"] = copy.deepcopy(p["payload"]["bars"])
        for i, bar in enumerate(p["payload"]["bars"][-20:]): bar["close"] = 100 - i
        rehash(p)
        ctx = context(); ctx["mode"] = "EXISTING_BOOK_PROPOSAL"
        ctx["book"] = {"source": "https://example.org/synthetic-book", "decision_cutoff": ctx["decision_cutoff"],
                       "verified_at": "2026-09-07T11:00:00Z", "currency": "KRW", "pending_orders": [],
                       "positions": {"US:TEST": .1}, "cash_weight": .9}
        out = evaluate(b, ctx)
        row = out["portfolio_proposal"]["rows"][0]
        self.assertEqual(row["action"], "HOLD")
        self.assertEqual(row["target_weight"], .1)
        s["blocks"]["financials"]["status"] = "provider_error"
        out = evaluate(b, ctx)
        self.assertEqual(out["portfolio_proposal"]["rows"][0]["target_weight"], .1)
        self.assertFalse(out["portfolio_proposal"]["ready"])

    def test_concentration_liquidity_and_stress_caps(self):
        b = with_scenario(); s = b["securities"][0]
        s["blocks"]["risk"]["payload"]["stress_loss"] = 1.; rehash(s["blocks"]["risk"])
        ctx = context(); ctx["capital_krw"] = 1e14
        out = evaluate(b, ctx); p = out["portfolio_proposal"]
        self.assertLessEqual(p["constraints"]["scenario_stress_loss"], .25)
        self.assertFalse(p["constraints"]["violations"])
        self.assertGreater(p["cash_weight"], .9)

    def test_future_regime_and_pending_orders_block(self):
        ctx = context(); ctx["regime"]["observed_at"] = "2026-09-08T00:00:00Z"
        self.assertFalse(evaluate(ctx=ctx)["portfolio_proposal"]["ready"])

    def test_entry_threshold_failure_is_not_incumbent_exit(self):
        b = with_scenario(); s = b["securities"][0]; p = s["blocks"]["price"]
        for bar in p["payload"]["bars"]: bar["close"] = 250.
        rehash(p)
        ctx = context(); ctx["mode"] = "EXISTING_BOOK_PROPOSAL"
        ctx["book"] = {"source": "https://example.org/synthetic-book", "decision_cutoff": ctx["decision_cutoff"],
                       "verified_at": "2026-09-07T11:00:00Z", "currency": "KRW", "pending_orders": [],
                       "positions": {"US:TEST": .1}, "cash_weight": .9}
        out = evaluate(b, ctx)
        self.assertEqual(out["portfolio_proposal"]["rows"][0]["action"], "HOLD")
        self.assertTrue(out["portfolio_proposal"]["ready"])
        ctx["book"]["pending_orders"] = [{"security_id": "US:TEST", "side": "BUY"}]
        out = evaluate(b, ctx)
        self.assertFalse(out["portfolio_proposal"]["ready"])
        self.assertIsNone(out["portfolio_proposal"]["rows"][0]["target_weight"])

    def test_all_cash_can_be_a_valid_research_decision(self):
        b = with_scenario(); p = b["securities"][0]["blocks"]["price"]
        for bar in p["payload"]["bars"]: bar["close"] = 250.
        rehash(p)
        out = evaluate(b)
        self.assertTrue(out["portfolio_proposal"]["ready"])
        self.assertEqual(out["portfolio_proposal"]["cash_weight"], 1.)
        self.assertFalse(out["portfolio_proposal"]["cash_is_unallocated_fallback"])

    def test_small_rank_advantage_does_not_replace_incumbent(self):
        b = with_scenario(ticker="INCUMBENT")
        for ticker in ("AAA", "BBB", "CCC", "DDD"):
            b["securities"] += with_scenario(ticker=ticker)["securities"]
        ctx = context(); ctx["mode"] = "EXISTING_BOOK_PROPOSAL"
        ctx["book"] = {"source": "https://example.org/synthetic-book", "decision_cutoff": ctx["decision_cutoff"],
                       "verified_at": "2026-09-07T11:00:00Z", "currency": "KRW", "pending_orders": [],
                       "positions": {"US:INCUMBENT": .2}, "cash_weight": .8}
        out = evaluate(b, ctx)
        incumbent = next(r for r in out["portfolio_proposal"]["rows"] if r["security_id"] == "US:INCUMBENT")
        self.assertEqual(incumbent["target_weight"], .2)
        self.assertIn("keep_incumbent_replacement_not_cost_justified", incumbent["reasons"])
        self.assertFalse(out["portfolio_proposal"]["constraints"]["violations"])


if __name__ == "__main__": unittest.main()
