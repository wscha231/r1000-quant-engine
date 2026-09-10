"""Mechanical connection tests only; these fixtures provide no alpha evidence."""
import copy
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from research_decision_v1_fixture import rehash
from research_decision_v1_decision_fixture import with_scenario, config, context
from tools.research_decision_v1.data import export_market
from tools.research_decision_v1.engine import run_decisions
from tools.run_research_decision_v1 import main, render_report, source_paths_match_commit


def evaluate(b=None, ctx=None, previous=None):
    b = b or with_scenario()
    return run_decisions([export_market(b, b["market"])], ctx or context(), config(), previous)


def book_context(positions):
    ctx = context(); ctx["mode"] = "EXISTING_BOOK_PROPOSAL"
    ctx["book"] = {"source": "https://example.org/synthetic-book", "decision_cutoff": ctx["decision_cutoff"],
                   "verified_at": "2026-09-07T11:00:00Z", "currency": "KRW", "pending_orders": [],
                   "positions": positions, "cash_weight": 1-sum(positions.values())}
    return ctx


def set_targets(security, targets):
    sc = security["blocks"]["scenario"]
    for scenario, target in zip(sc["payload"]["scenarios"], targets):
        scenario["revenue"] = (target*scenario["diluted_shares"]+scenario["net_debt"])/(scenario["margin"]*scenario["multiple"])
    rehash(sc)


class DecisionTests(unittest.TestCase):
    def assert_hold_accounting(self, proposal, security_id, prior_weight, cfg=None, *, expected_ready=True):
        """HOLD preserves notional; funded weights use the smaller post-cost NAV."""
        cfg = config() if cfg is None else cfg
        self.assertEqual(proposal["ready"], expected_ready, proposal["blockers"])
        self.assertEqual(proposal["target_weight_basis"], "POST_COST_NAV")
        self.assertFalse(proposal["orders_allowed"])
        self.assertEqual(bool(proposal["constraints"]["violations"]), not expected_ready)
        funding = proposal["funding"]
        initial, nav = funding["initial_nav_krw"], funding["post_cost_nav_krw"]
        # Numerical tolerance is at most 1e-12 of NAV, not a trading buffer.
        tolerance = max(1e-8, initial * 1e-12)
        self.assertGreater(nav, 0.)
        self.assertLessEqual(nav, initial)
        self.assertGreaterEqual(funding["cash_krw"], 0.)
        held = next(r for r in proposal["rows"] if r["security_id"] == security_id)
        self.assertEqual(held["action"], "HOLD")
        self.assertEqual(funding["trade_fraction_initial_nav"][security_id], 0.)
        self.assertEqual(funding["position_fraction_initial_nav"][security_id], prior_weight)
        self.assertAlmostEqual(funding["position_values_krw"][security_id], initial * prior_weight,
                               delta=tolerance)
        self.assertAlmostEqual(held["target_weight"] * nav, initial * prior_weight, delta=tolerance)
        expected_fee = initial * sum(abs(trade) * cfg["one_way_cost_bps"][sid.split(":")[0]] / 10000
                                     for sid, trade in funding["trade_fraction_initial_nav"].items())
        self.assertAlmostEqual(funding["transaction_cost_krw"], expected_fee, delta=tolerance)
        self.assertAlmostEqual(nav + expected_fee, initial, delta=tolerance)
        self.assertAlmostEqual(sum(funding["position_values_krw"].values()) + funding["cash_krw"],
                               nav, delta=tolerance)
        self.assertAlmostEqual(proposal["cash_weight"] * nav, funding["cash_krw"], delta=tolerance)
        for row in proposal["rows"]:
            self.assertAlmostEqual(row["target_weight"] * nav,
                                   funding["position_values_krw"].get(row["security_id"], 0.),
                                   delta=tolerance)
        self.assertAlmostEqual(sum(r["target_weight"] for r in proposal["rows"]) + proposal["cash_weight"],
                               1., places=12)

    def funded_hold_fixture(self, new_weight=.3, zero_cost=False):
        from tools.research_decision_v1.portfolio import fund_targets
        cfg = config()
        if zero_cost:
            cfg["one_way_cost_bps"] = {"US": 0., "KR": 0.}
        funding = fund_targets({"US:OLD": .2, "US:NEW": new_weight}, {"US:OLD": .2},
                               {sid: {"market": "US"} for sid in ("US:OLD", "US:NEW")}, context(), cfg)
        proposal = {"ready": True, "blockers": [], "orders_allowed": False,
                    "target_weight_basis": "POST_COST_NAV", "funding": funding,
                    "constraints": {"violations": []}, "cash_weight": funding["cash_weight"],
                    "rows": [{"security_id": sid, "action": "HOLD" if sid == "US:OLD" else "ENTER",
                              "target_weight": weight} for sid, weight in funding["target_weights"].items()]}
        return proposal, cfg

    def test_hold_accounting_has_analytic_post_cost_weight(self):
        for new_weight in (.2, .3):
            proposal, cfg = self.funded_hold_fixture(new_weight)
            self.assert_hold_accounting(proposal, "US:OLD", .2, cfg)
            rate = cfg["one_way_cost_bps"]["US"] / 10000
            self.assertAlmostEqual(proposal["funding"]["target_weights"]["US:OLD"],
                                   .2 * (1 + rate * new_weight), places=12)
            self.assertGreater(proposal["funding"]["transaction_cost_krw"], 0.)

    def test_hold_accounting_zero_fee_is_exact_no_trade(self):
        proposal, cfg = self.funded_hold_fixture(zero_cost=True)
        self.assert_hold_accounting(proposal, "US:OLD", .2, cfg)
        self.assertEqual(proposal["funding"]["target_weights"]["US:OLD"], .2)
        self.assertEqual(proposal["funding"]["transaction_cost_krw"], 0.)

    def test_hold_accounting_rejects_hidden_trade_stale_weight_and_funding_errors(self):
        proposal, cfg = self.funded_hold_fixture()
        for mistake in ("trade", "weight", "cash", "fee", "action", "risk"):
            with self.subTest(mistake=mistake):
                broken = copy.deepcopy(proposal)
                row = next(r for r in broken["rows"] if r["security_id"] == "US:OLD")
                if mistake == "trade": broken["funding"]["trade_fraction_initial_nav"]["US:OLD"] = .0001
                if mistake == "weight": row["target_weight"] = .2
                if mistake == "cash": broken["funding"]["cash_krw"] += 1.
                if mistake == "fee": broken["funding"]["transaction_cost_krw"] = 0.
                if mistake == "action": row["action"] = "ADD"
                if mistake == "risk": broken["constraints"]["violations"] = ["single_cap"]
                with self.assertRaises(AssertionError):
                    self.assert_hold_accounting(broken, "US:OLD", .2, cfg)

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

    def test_equal_economic_targets_allow_only_roundoff_not_reversed_scenarios(self):
        b = with_scenario(); set_targets(b["securities"][0], (110., 110., 110.))
        row = evaluate(b)["ranking"][0]
        self.assertTrue(row["valuation_ready"])
        self.assertGreaterEqual(row["scenario_range"], 0.)
        set_targets(b["securities"][0], (111., 110., 110.))
        self.assertFalse(evaluate(b)["ranking"][0]["valuation_ready"])

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

    def test_ingestion_refresh_is_not_a_fundamental_revision(self):
        b = with_scenario(); first = evaluate(b)
        for block in b["securities"][0]["blocks"].values(): block["ingested_at"] = "2026-09-07T11:30:00Z"
        second = evaluate(b, previous=first)
        self.assertEqual(second["ranking"][0]["rank_change_reasons"], ["evidence_provenance"])
        self.assertEqual(first["ranking"][0]["investment_rank"], second["ranking"][0]["investment_rank"])

    def test_sensitivity_domain_does_not_invalidate_base_valuation(self):
        b = with_scenario(); sc = b["securities"][0]["blocks"]["scenario"]
        for row in sc["payload"]["scenarios"]: row["margin"] = .95
        rehash(sc); result = evaluate(b)
        self.assertTrue(result["ranking"][0]["valuation_ready"])
        self.assertIsNone(result["ranking"][0]["sensitivity"]["margin"][1]["target_price"])

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
        b = with_scenario(); set_targets(b["securities"][0], (109., 110., 111.))
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
        self.assert_hold_accounting(out["portfolio_proposal"], "US:INCUMBENT", .2, expected_ready=False)
        self.assertIn("keep_incumbent_replacement_not_cost_justified", incumbent["reasons"])
        self.assertGreater(incumbent["target_weight"], .2)
        self.assertFalse(out["portfolio_proposal"]["ready"])
        self.assertTrue(out["portfolio_proposal"]["constraints"]["violations"])

    def test_nonpositive_metric_blocks_each_supported_valuation_method(self):
        for method, field in (("PE", "net_income"), ("EV_EBITDA", "ebitda")):
            b = with_scenario(); security = b["securities"][0]
            financials, scenario = security["blocks"]["financials"], security["blocks"]["scenario"]
            financials["payload"]["ttm"][field] = -1.; scenario["payload"]["method"] = method
            rehash(financials); rehash(scenario)
            result = evaluate(b)
            self.assertIn("valuation:valuation_metric_nonpositive", result["ranking"][0]["blockers"])
            self.assertEqual(result["portfolio_proposal"]["rows"][0]["target_weight"], 0.)

    def test_zero_book_rows_are_new_entry_candidates(self):
        ctx = context(); ctx["mode"] = "EXISTING_BOOK_PROPOSAL"
        ctx["book"] = {"source": "https://example.org/synthetic-book", "decision_cutoff": ctx["decision_cutoff"],
                       "verified_at": "2026-09-07T11:00:00Z", "currency": "KRW", "pending_orders": [],
                       "positions": {"US:TEST": 0.}, "cash_weight": 1.}
        self.assertEqual(evaluate(ctx=ctx)["portfolio_proposal"]["rows"][0]["action"], "ENTER")

    def test_liquidation_must_fit_trade_liquidity_not_only_target_holdings(self):
        b = with_scenario(); security = b["securities"][0]
        for bar in security["blocks"]["price"]["payload"]["bars"]: bar["volume"] = 100.
        security["blocks"]["thesis"]["payload"]["intact"] = False
        rehash(security["blocks"]["price"]); rehash(security["blocks"]["thesis"])
        ctx = context(); ctx["mode"] = "EXISTING_BOOK_PROPOSAL"
        ctx["book"] = {"source": "https://example.org/synthetic-book", "decision_cutoff": ctx["decision_cutoff"],
                       "verified_at": "2026-09-07T11:00:00Z", "currency": "KRW", "pending_orders": [],
                       "positions": {"US:TEST": .2}, "cash_weight": .8}
        result = evaluate(b, ctx)
        self.assertFalse(result["portfolio_proposal"]["ready"])
        self.assertIn("US:TEST:trade_liquidity", result["portfolio_proposal"]["constraints"]["violations"])
        self.assertIn("US:TEST:trade_liquidity", render_report(result))
        self.assertIn("Constraint audit", render_report(result))
        security["blocks"]["risk"]["payload"]["liquidity_restriction"] = True; rehash(security["blocks"]["risk"])
        result = evaluate(b, ctx)
        self.assertIn("US:TEST:trade_liquidity_restriction", result["portfolio_proposal"]["constraints"]["violations"])

    def test_industry_equal_weight_and_verified_cap_weight_are_separate(self):
        b = with_scenario(ticker="AAA")
        b["securities"] += with_scenario(ticker="BBB")["securities"] + with_scenario(ticker="CCC")["securities"]
        for i, security in enumerate(b["securities"]):
            price = security["blocks"]["price"]
            price["payload"]["bars"] = copy.deepcopy(price["payload"]["bars"])
            price["payload"]["bars"][-1]["close"] = (110., 100., 90.)[i]; rehash(price)
            risk = security["blocks"]["risk"]; risk["payload"]["exposures"]["industry:test"] = (1., .5, .25)[i]; rehash(risk)
        row = next(g for g in evaluate(b)["industry_discovery"] if g["group"] == "US/industry:test")["horizons"]["20"]
        self.assertAlmostEqual(row["equal_weight_return"], 0.)
        self.assertIsNone(row["current_cap_weight_return"])
        for i, security in enumerate(b["securities"]):
            cap = copy.deepcopy(security["blocks"]["price"]); cap["unit"] = "currency"
            cap["payload"] = {"as_of": "2026-09-04", "value": (i+1)*1e9}; rehash(cap)
            security["optional"]["market_cap"] = cap
        row = next(g for g in evaluate(b)["industry_discovery"] if g["group"] == "US/industry:test")["horizons"]["20"]
        self.assertAlmostEqual(row["current_cap_weight_return"], -1/30)
        self.assertEqual(row["market_cap_coverage"], 3)

    def test_fx_adjusted_net_return_controls_entry_and_hold_hurdles(self):
        b = with_scenario(); set_targets(b["securities"][0], (145., 156., 167.))
        ctx = context(); ctx["fx"]["scenario_rates"] = {s: 980. for s in ("Bear", "Base", "Bull")}
        result = evaluate(b, ctx); row = result["ranking"][0]
        self.assertGreater(row["expected_net_return"], .15)
        self.assertGreater(row["investment_utility_krw"], 0.)
        self.assertAlmostEqual(row["expected_net_return_krw"], .089)
        self.assertEqual(row["four_questions"]["buy_price_now"], "wait")
        self.assertEqual(row["four_questions_local"]["buy_price_now"], "pass")
        self.assertEqual(result["portfolio_proposal"]["rows"][0]["target_weight"], 0.)
        held = book_context({"US:TEST": .1}); held["fx"] = ctx["fx"]
        self.assertEqual(evaluate(b, held)["portfolio_proposal"]["rows"][0]["action"], "HOLD")
        held["fx"]["scenario_rates"] = {s: 700. for s in ("Bear", "Base", "Bull")}
        below = evaluate(b, held)
        self.assertFalse(below["portfolio_proposal"]["ready"])
        self.assertEqual(below["ranking"][0]["four_questions"]["good_stock"], "fail")
        self.assertEqual(below["portfolio_proposal"]["rows"][0]["target_weight"], .1)
        self.assertIn("US:TEST:held_below_hold_hurdle_requires_review", below["portfolio_proposal"]["blockers"])

    def test_zero_clipped_replacement_does_not_sell_incumbent(self):
        b = with_scenario(ticker="OLD"); set_targets(b["securities"][0], (125., 125., 125.))
        b["securities"] += with_scenario(ticker="NEW")["securities"]
        price = b["securities"][1]["blocks"]["price"]
        for bar in price["payload"]["bars"]: bar["volume"] = 1.
        rehash(price)
        result = evaluate(b, book_context({"US:OLD": .2}))["portfolio_proposal"]
        weights = {r["security_id"]: r["target_weight"] for r in result["rows"]}
        self.assertEqual(weights, {"US:NEW": 0., "US:OLD": .2})

    def test_replacement_capacity_cannot_be_reused_for_multiple_incumbents(self):
        b = with_scenario(ticker="OLD_A"); b["securities"] += with_scenario(ticker="OLD_B")["securities"]
        for s in b["securities"]: set_targets(s, (125., 125., 125.))
        b["securities"] += with_scenario(ticker="NEW")["securities"]
        price = b["securities"][-1]["blocks"]["price"]
        for bar in price["payload"]["bars"]: bar["volume"] = 5000.
        rehash(price)
        result = evaluate(b, book_context({"US:OLD_A": .2, "US:OLD_B": .2}))["portfolio_proposal"]
        weights = {r["security_id"]: r["target_weight"] for r in result["rows"]}
        self.assertLessEqual(.4-weights["US:OLD_A"]-weights["US:OLD_B"], weights["US:NEW"]+1e-9)
        self.assertGreater(weights["US:OLD_A"]+weights["US:OLD_B"], 0.)

    def test_retained_incumbents_consume_final_country_count(self):
        b = with_scenario(ticker="OLD")
        b["securities"][0]["blocks"]["risk"]["payload"]["liquidity_restriction"] = True
        rehash(b["securities"][0]["blocks"]["risk"])
        for ticker in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            b["securities"] += with_scenario(ticker=ticker)["securities"]
        result = evaluate(b, book_context({"US:OLD": .1}))["portfolio_proposal"]
        self.assertLessEqual(sum(r["target_weight"]>0 for r in result["rows"]), 5)
        self.assertEqual(result["constraints"]["country_counts"]["US"], 5)
        self.assertEqual(next(r for r in result["rows"] if r["security_id"] == "US:EEE")["target_weight"], 0.)
        # An already oversized book is preserved and explicitly blocked.
        held = book_context({s["security_id"]: .05 for s in b["securities"]})
        result = evaluate(b, held)["portfolio_proposal"]
        self.assertFalse(result["ready"])
        self.assertIn("US:country_count_cap", result["constraints"]["violations"])

    def test_removed_candidates_remain_in_change_ledger(self):
        b = with_scenario(ticker="AAA"); b["securities"] += with_scenario(ticker="BBB")["securities"]
        first = evaluate(b); b["securities"] = b["securities"][:1]
        second = evaluate(b, previous=first)
        removed = next(r for r in second["decision_ledger"] if r["security_id"] == "US:BBB")
        self.assertEqual(removed["previous_investment_rank"], 2)
        self.assertIsNone(removed["investment_rank"])
        self.assertIn("removed_from_research_universe", removed["changes"])
        self.assertIsNone(removed["portfolio_action"])

    def test_report_names_return_currencies_ranks_and_four_questions(self):
        ctx = context(); ctx["fx"]["scenario_rates"] = {s: 1540. for s in ("Bear", "Base", "Bull")}
        report = render_report(evaluate(ctx=ctx))
        for expected in ("Local total return (currency)", "KRW total return", "KRW return rank", "KRW investment rank",
                         "85.75% (USD)", "104.33%", "Good company?", "Good stock?", "Buy price now?", "Portfolio value?"):
            self.assertIn(expected, report)

    def test_secret_or_legacy_fields_in_custom_config_cannot_be_persisted(self):
        for key, value in (("api_key", "private-value"), ("source", "https://example.org/api?token=private"), ("NONRANKING", 12)):
            cfg = config(); cfg[key] = value
            with self.assertRaises(ValueError): run_decisions([export_market(with_scenario(), "US")], context(), cfg)

    def test_dirty_source_blocks_cli_before_input_or_artifact_access(self):
        with mock.patch("sys.argv", ["research", "--market-export", "unused", "--context", "unused"]), \
             mock.patch("tools.run_research_decision_v1.verified_source_snapshot", return_value=None), \
             mock.patch("tools.run_research_decision_v1.load_verified_runtime") as runtime, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 2)
            runtime.assert_not_called()
            self.assertIn("BLOCKED_SOURCE_MISMATCH", output.getvalue())

    def test_renderer_changes_get_distinct_executions_and_dirty_engine_never_imports(self):
        original = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [p.relative_to(original) for p in (original/"tools/research_decision_v1").rglob("*.py")]
            paths += [Path("tools/run_research_decision_v1.py"), Path("tools/export_research_decision_market.py"), Path("docs/research_decision_v1_config.json")]
            if (original/"tools/__init__.py").exists(): paths.append(Path("tools/__init__.py"))
            for path in paths:
                (root/path).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(original/path, root/path)
            def git(*args): return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)
            def commit():
                git("add", "tools", "docs")
                git("-c", "user.name=Research test", "-c", "user.email=research-test@example.org", "commit", "-m", "fixture")
            git("init"); commit()
            (root/"input.json").write_text(json.dumps(export_market(with_scenario(), "US")))
            (root/"context.json").write_text(json.dumps(context()))
            cmd = [sys.executable, "-I", "tools/run_research_decision_v1.py", "--market-export", "input.json", "--context", "context.json"]
            def launch(): return subprocess.run(cmd, cwd=root, text=True, capture_output=True, timeout=60)
            first = launch(); self.assertEqual(first.returncode, 0, first.stderr)
            a = json.loads(first.stdout); before = (Path(a["directory"])/"report.md").read_bytes()
            before_files = {p.name:p.read_bytes() for p in Path(a["directory"]).iterdir() if p.is_file()}
            for path in paths: (root/path).write_bytes((root/path).read_bytes().replace(b"\r\n",b"\n").replace(b"\n",b"\r\n"))
            crlf = launch(); self.assertEqual(crlf.returncode, 0, crlf.stderr)
            self.assertEqual(json.loads(crlf.stdout)["directory"], a["directory"])
            self.assertEqual({p.name:p.read_bytes() for p in Path(a["directory"]).iterdir() if p.is_file()}, before_files)
            for path in paths: (root/path).write_bytes((root/path).read_bytes().replace(b"\r\n",b"\n"))
            cli = root/"tools/run_research_decision_v1.py"; code = cli.read_text()
            marker = 'return "\\n".join(lines)'
            self.assertIn(marker, code)
            cli.write_text(code.replace(marker, marker+' + "\\nRenderer version two.\\n"', 1)); commit()
            second = launch(); self.assertEqual(second.returncode, 0, second.stderr)
            b = json.loads(second.stdout)
            self.assertEqual(a["decision_hash"], b["decision_hash"])
            self.assertNotEqual(a["directory"], b["directory"])
            self.assertEqual((Path(a["directory"])/"report.md").read_bytes(), before)
            self.assertIn("Renderer version two", (Path(b["directory"])/"report.md").read_text())
            side_effect = root/"should_never_exist.txt"
            injected = root/"injected"; injected.mkdir()
            poison = "from pathlib import Path\nPath("+repr(str(side_effect))+").write_text('bad')\nraise RuntimeError('unchecked import')\n"
            (root/"tools/pandas.py").write_text(poison)
            (injected/"pandas.py").write_text(poison)
            env = dict(os.environ, PYTHONPATH=str(injected))
            isolated = subprocess.run(cmd, cwd=root, env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(isolated.returncode, 0, isolated.stderr)
            self.assertEqual(json.loads(isolated.stdout)["directory"], b["directory"])
            unchecked = subprocess.run([cmd[0], *cmd[2:]], cwd=root, env=env, text=True, capture_output=True, timeout=60)
            self.assertEqual(unchecked.returncode, 2, unchecked.stderr)
            self.assertIn("BLOCKED_RUNTIME", unchecked.stderr)
            # Even an extra path inserted after interpreter isolation is removed
            # before the verified package imports third-party dependencies.
            wrapper = "import sys,runpy;sys.path.insert(0,"+repr(str(injected))+");sys.argv="+repr(cmd[2:])+";runpy.run_path(sys.argv[0],run_name='__main__')"
            extra_path = subprocess.run([sys.executable, "-I", "-c", wrapper], cwd=root, text=True, capture_output=True, timeout=60)
            self.assertEqual(extra_path.returncode, 0, extra_path.stderr)
            self.assertFalse(side_effect.exists())
            for dirty in ("def invalid(:\n", "from pathlib import Path\nPath("+repr(str(side_effect))+").write_text('bad')\n"):
                (root/"tools/research_decision_v1/engine.py").write_text(dirty)
                blocked = launch()
                self.assertEqual(blocked.returncode, 2, blocked.stderr)
                self.assertEqual(json.loads(blocked.stdout)["status"], "BLOCKED_SOURCE_MISMATCH")
                self.assertFalse(side_effect.exists())

    def test_new_capital_requires_typed_explicit_assumption(self):
        for value in (None, False, 1, "true"):
            ctx = context()
            if value is None: ctx.pop("capital_is_assumption")
            else: ctx["capital_is_assumption"] = value
            with self.subTest(value=value):
                proposal = evaluate(ctx=ctx)["portfolio_proposal"]
                self.assertFalse(proposal["ready"])
                self.assertIn("new_capital_requires_explicit_assumption", proposal["blockers"])
                self.assertIs(proposal["capital_is_assumption"], True)
                self.assertEqual(proposal["cash_weight"], 1.)

    def test_connection_receipt_gates_survive_python_optimization(self):
        script = Path(__file__).resolve().parents[1]/"research/decision_v1/reproduce_checks.py"
        code = '''import copy,runpy,sys
verify=runpy.run_path(sys.argv[1])['verify_case']
first={'result':{'decision_hash':'one'}}
files={'report.json':'one'}
report={'portfolio_proposal':{'rows':[{'target_weight':0.2}],'cash_weight':0.8},'data_kind':'SYNTHETIC',
        'readiness':{'orders_allowed':False,'oos_validated':False,'portfolio_proposal_ready':True,'target_5_plus_2_complete':True}}
verify('SYNTHETIC_7',first,first,files,files,report)
for change in ('hash','files','weight','sum','kind','orders','oos','complete','real_ready'):
    second=copy.deepcopy(first); after=copy.deepcopy(files); out=copy.deepcopy(report); label='SYNTHETIC_7'
    if change=='hash': second['result']['decision_hash']='two'
    if change=='files': after['report.json']='two'
    if change=='weight': out['portfolio_proposal']['cash_weight']=float('nan')
    if change=='sum': out['portfolio_proposal']['cash_weight']=0.7
    if change=='kind': out['data_kind']='REAL'
    if change in ('orders','oos'): out['readiness']['orders_allowed' if change=='orders' else 'oos_validated']=True
    if change=='complete': out['readiness']['target_5_plus_2_complete']=False
    if change=='real_ready': label='REAL_PILOT';out['data_kind']='REAL'
    try: verify(label,first,second,files,after,out)
    except ValueError: continue
    raise RuntimeError('accepted invalid case: '+change)
print('guarded 9 invalid cases under optimization')
'''
        result = subprocess.run([sys.executable, "-I", "-O", "-c", code, str(script)], text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("guarded 9", result.stdout)

    def test_infeasible_top_names_do_not_consume_final_country_slots(self):
        b = with_scenario(ticker="AAA0"); b["securities"] = []
        for i in range(5):
            security = with_scenario(ticker="AAA"+str(i))["securities"][0]
            set_targets(security, (170., 180., 190.))
            for bar in security["blocks"]["price"]["payload"]["bars"]: bar["volume"] = 1.
            rehash(security["blocks"]["price"]); b["securities"].append(security)
        b["securities"] += with_scenario(ticker="ZZZ")["securities"]
        result = evaluate(b)
        self.assertEqual(next(r for r in result["ranking"] if r["security_id"] == "US:ZZZ")["investment_rank"], 6)
        selected = [r for r in result["portfolio_proposal"]["rows"] if r["target_weight"] > 0]
        self.assertEqual([r["security_id"] for r in selected], ["US:ZZZ"])
        self.assertTrue(result["portfolio_proposal"]["ready"])

    def test_missing_universe_holding_preserves_valid_book_and_renders_blocker(self):
        result = evaluate(ctx=book_context({"US:HELD": .2}))
        proposal = result["portfolio_proposal"]
        self.assertFalse(proposal["ready"])
        self.assertEqual({r["security_id"]: r["target_weight"] for r in proposal["rows"]}, {"US:TEST": 0., "US:HELD": .2})
        self.assertEqual(proposal["cash_weight"], .8)
        report = render_report(result)
        self.assertIn("US:HELD", report)
        self.assertIn("book_holdings_missing_from_risk_universe", report)
        self.assertIn("blocked_missing_evidence", report)

    def test_optional_provenance_and_cap_changes_are_attributed(self):
        b = with_scenario(); cap = copy.deepcopy(b["securities"][0]["blocks"]["price"])
        cap["unit"] = "currency"; cap["payload"] = {"as_of": "2026-09-04", "value": 1e9}; rehash(cap)
        b["securities"][0]["optional"]["market_cap"] = cap
        first = evaluate(b)
        cap["ingested_at"] = "2026-09-07T11:30:00Z"
        second = evaluate(b, previous=first)
        self.assertEqual(second["ranking"][0]["rank_change_reasons"], ["evidence_provenance"])
        cap["payload"]["value"] = 2e9; rehash(cap)
        third = evaluate(b, previous=second)
        self.assertIn("optional_evidence", third["ranking"][0]["rank_change_reasons"])

    def test_strengthened_incumbent_adds_share_remaining_budget(self):
        us = with_scenario(ticker="ADD0"); us["securities"] = []
        for i in range(4):
            security = with_scenario(ticker="ADD"+str(i))["securities"][0]
            security["blocks"]["thesis"]["payload"]["strengthened"] = True; rehash(security["blocks"]["thesis"])
            us["securities"].append(security)
        us["securities"] += with_scenario(ticker="LOW")["securities"]
        kr = with_scenario("KR", "990000"); kr["securities"] += with_scenario("KR", "990001")["securities"]
        for i, security in enumerate(kr["securities"]):
            security.update(ticker=str(990000+i), security_id="KR:"+str(990000+i))
            for block in security["blocks"].values(): block["security_id"] = security["security_id"]
        for security in [us["securities"][-1], *kr["securities"]]: set_targets(security, (109., 110., 111.))
        all_securities = [*us["securities"], *kr["securities"]]
        for i, security in enumerate(all_securities):
            risk = security["blocks"]["risk"]; risk["payload"]["stress_loss"] = .3
            risk["payload"]["exposures"] = {"industry:g"+str(i): 1., "theme:g"+str(i): 1., "customer:g"+str(i): .2}; rehash(risk)
        positions = {s["security_id"]: (.01 if i < 4 else .2) for i, s in enumerate(all_securities)}
        result = run_decisions([export_market(us, "US"), export_market(kr, "KR")], book_context(positions), config())
        proposal = result["portfolio_proposal"]
        self.assertGreaterEqual(proposal["cash_weight"], 0.)
        self.assertLessEqual(proposal["constraints"]["gross_exposure"], .7+1e-10)
        self.assertTrue(proposal["ready"], proposal["blockers"])

    def test_incremental_add_requires_entry_hurdle_even_when_strengthened(self):
        b = with_scenario(); security = b["securities"][0]; set_targets(security, (109., 110., 111.))
        security["blocks"]["thesis"]["payload"]["strengthened"] = True; rehash(security["blocks"]["thesis"])
        out = evaluate(b, book_context({"US:TEST": .01}))
        self.assertEqual(out["ranking"][0]["four_questions"]["buy_price_now"], "wait")
        self.assertEqual(out["portfolio_proposal"]["rows"][0]["action"], "HOLD")
        self.assertEqual(out["portfolio_proposal"]["rows"][0]["target_weight"], .01)

    def test_cross_country_replacement_pays_each_trade_leg(self):
        us = with_scenario(ticker="OLD1"); us["securities"] += with_scenario(ticker="OLD2")["securities"]
        kr = with_scenario("KR")
        for security in us["securities"]: set_targets(security, (120., 120., 120.))
        set_targets(kr["securities"][0], (123.55, 123.55, 123.55))
        for security in [*us["securities"], *kr["securities"]]:
            risk = security["blocks"]["risk"]
            risk["payload"]["exposures"] = {"industry:fee_case": 1., "theme:"+security["ticker"]: 1., "customer:"+security["ticker"]: .2}; rehash(risk)
        price = kr["securities"][0]["blocks"]["price"]
        for bar in price["payload"]["bars"]: bar["volume"] = 100000000.
        rehash(price)
        out = run_decisions([export_market(us,"US"), export_market(kr,"KR")], book_context({"US:OLD1":.2,"US:OLD2":.2}), config())
        lookup = {r["security_id"]:r for r in out["ranking"]}
        self.assertAlmostEqual(lookup["KR:999999"]["investment_utility_krw"]-lookup["US:OLD1"]["investment_utility_krw"], .0335)
        targets = {r["security_id"]:r["target_weight"] for r in out["portfolio_proposal"]["rows"]}
        self.assertEqual(targets["US:OLD1"], .2); self.assertEqual(targets["US:OLD2"], .2)
        self.assertEqual(targets["KR:999999"], 0.)

    def test_final_incumbent_capacity_refills_independent_lower_ranked_names(self):
        b = with_scenario(ticker="OLD1"); b["securities"] += with_scenario(ticker="OLD2")["securities"]
        for security in b["securities"]: set_targets(security, (190., 200., 210.))
        for ticker in ("AAA", "BBB", "CCC", "DDD", "EEE"):
            security = with_scenario(ticker=ticker)["securities"][0]; set_targets(security, (170.,180.,190.)); b["securities"].append(security)
        for security in b["securities"]:
            risk = security["blocks"]["risk"]; ticker=security["ticker"]
            risk["payload"]["stress_loss"] = .3
            risk["payload"]["exposures"] = {"industry:"+("blocked" if ticker in {"OLD1","OLD2","AAA","BBB","CCC"} else ticker):1., "theme:"+ticker:1., "customer:"+ticker:.2}; rehash(risk)
        ctx=book_context({"US:OLD1":.2,"US:OLD2":.2})
        out = evaluate(b, ctx)["portfolio_proposal"]
        targets={r["security_id"]:r["target_weight"] for r in out["rows"]}
        for sid in ("US:OLD1", "US:OLD2"):
            self.assert_hold_accounting(out, sid, .2, expected_ready=False)
        self.assertGreater(targets["US:DDD"], 0.); self.assertGreater(targets["US:EEE"], 0.)
        self.assertFalse(out["ready"])
        self.assertTrue(out["constraints"]["violations"])

    def test_git_replace_cannot_attest_different_source_bytes(self):
        # Keep this source-integrity regression in the already mandatory H2
        # suite as well as the focused source suite.
        from research_workflow_source_smoke import SourceSeamTests
        SourceSeamTests().test_replace_ref_cannot_attest_different_commit_bytes()

    def test_previous_metadata_is_sanitized_and_component_schema_is_closed(self):
        from tools.research_decision_v1.data import digest
        b=with_scenario(ticker="OLD"); previous=evaluate(b)
        for key, value in (("api_key","dummy"),("extension","https://example.org/a?token=dummy"),("price","not-a-sha256"),("rank",1)):
            changed=copy.deepcopy(previous); changed["ranking"][0]["component_hashes"][key]=value
            changed["decision_hash"]=digest({k:v for k,v in changed.items() if k!="decision_hash"})
            with self.assertRaises(ValueError): evaluate(with_scenario(ticker="NEW"), previous=changed)
        self.assertEqual(evaluate(b, previous=previous)["ranking"][0]["rank_change_reasons"], ["unchanged"])

    def test_missing_book_completion_requires_admitted_current_holdings(self):
        positions={"US:HELD"+str(i):.05 for i in range(5)}; positions.update({"KR:"+str(990000+i):.05 for i in range(2)})
        out=evaluate(ctx=book_context(positions))
        self.assertFalse(out["readiness"]["portfolio_proposal_ready"])
        self.assertFalse(out["readiness"]["target_5_plus_2_complete"])
        self.assertFalse(out["readiness"]["research_universe_fully_covered"])

    def test_source_byte_check_ignores_index_flags_and_includes_parent_initializer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = {"tools/research_decision_v1/__init__.py": "# package\n", "tools/research_decision_v1/data.py": "# data\n",
                     "tools/run_research_decision_v1.py": "# consumer\n", "tools/export_research_decision_market.py": "# exporter\n",
                     "docs/research_decision_v1_config.json": "{}\n"}
            for path, value in files.items():
                (root/path).parent.mkdir(parents=True, exist_ok=True); (root/path).write_text(value)
            def git(*args): return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL)
            git("init"); git("add", "tools", "docs")
            git("-c", "user.name=Research test", "-c", "user.email=research-test@example.org", "commit", "-m", "fixture")
            self.assertTrue(source_paths_match_commit(root))
            git("update-index", "--assume-unchanged", "tools/research_decision_v1/data.py")
            (root/"tools/research_decision_v1/data.py").write_text("# dirty\n")
            self.assertFalse(source_paths_match_commit(root))
            (root/"tools/research_decision_v1/data.py").write_text(files["tools/research_decision_v1/data.py"])
            (root/"tools/__init__.py").write_text("# injected parent\n")
            self.assertFalse(source_paths_match_commit(root))


if __name__ == "__main__": unittest.main()
