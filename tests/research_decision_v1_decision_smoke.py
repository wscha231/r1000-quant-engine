"""Mechanical connection tests only; these fixtures provide no alpha evidence."""
import copy
import contextlib
import io
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
        self.assertEqual(incumbent["target_weight"], .2)
        self.assertIn("keep_incumbent_replacement_not_cost_justified", incumbent["reasons"])
        self.assertFalse(out["portfolio_proposal"]["constraints"]["violations"])

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
        self.assertEqual(result["portfolio_proposal"]["rows"][0]["target_weight"], 0.)
        held = book_context({"US:TEST": .1}); held["fx"] = ctx["fx"]
        self.assertEqual(evaluate(b, held)["portfolio_proposal"]["rows"][0]["action"], "HOLD")
        held["fx"]["scenario_rates"] = {s: 700. for s in ("Bear", "Base", "Bull")}
        below = evaluate(b, held)
        self.assertFalse(below["portfolio_proposal"]["ready"])
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
             mock.patch("tools.run_research_decision_v1.source_paths_match_commit", return_value=False), \
             mock.patch("tools.run_research_decision_v1.read_json") as read, \
             mock.patch("tools.run_research_decision_v1.immutable_json") as write, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 2)
            read.assert_not_called(); write.assert_not_called()
            self.assertIn("BLOCKED_SOURCE_MISMATCH", output.getvalue())

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
