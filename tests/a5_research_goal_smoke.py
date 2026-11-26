from __future__ import annotations
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.nav_metrics_v2_smoke import context
from tools import evaluate_a5_research_goal as goal
from tools import nav_metrics_v2 as nav


class GoalTests(unittest.TestCase):
    def packet(self, values, spy_values, *, anchor_time="2021-09-30T20:00:00Z"):
        import pandas_market_calendars as mcal
        schedule = mcal.get_calendar("NYSE").schedule(start_date="2021-10-01", end_date="2026-11-06")
        dates = [value.date().isoformat() for value in schedule.index]
        packet = {"manifest": dict(schema="a5-matched-spy-goal-v1", portfolio_kind="main", benchmark="SPY",
                      benchmark_policy="BUY_AND_HOLD_DIVIDENDS_REINVESTED", start_session=dates[0],
                      end_session=dates[-1]), "receipts": {}}
        manifest = packet["manifest"]
        for name, points in (("portfolio", values), ("spy", spy_values)):
            values = [points[0]]*(len(dates)-2) + list(points[1:])
            rows = [dict(session=d, timestamp=t.isoformat(), nav=v)
                    for d, t, v in zip(dates, schedule["market_close"], values)]
            c = context(rows, anchor_nav=100000, anchor_time=anchor_time)
            packet[name] = dict(context=c, rows=rows)
            manifest[name+"_context_sha256"] = nav.digest(c)
        book = packet["portfolio"]
        report = nav.calculate(book["rows"], book["context"])
        report.update(portfolio_kind="main", execution_status="completed", integer_shares=True, fill_mode="next_close",
                      cost_bps_per_side=25, cash_carry_mode="risk_free_rate", cash_rate_source="DGS3MO",
                      cash_rate_lag_days=1, cash_carry_haircut_bps=0, cash_carry_day_count=365,
                      cash_rate_future_use_count=0,
                      target_fill_coverage=dict(execution_clock_contract="explicit_cutoff_exact_next_close_v1",
                                                coverage_complete=True, chronology_safe=True))
        packet["portfolio_report"] = report
        manifest["portfolio_report_sha256"] = nav.digest(report)
        packet["originals"] = dict(closed_loop=report,
            spy_total_return=dict(symbol="SPY", return_basis="TOTAL_RETURN", dividends_reinvested=True,
                                  status="VERIFIED", nav_rows_sha256=nav.digest(packet["spy"]["rows"])),
            source_pit=dict(status="VERIFIED", historical_pit_verified=True, corporate_actions_verified=True,
                            portfolio_context_sha256=manifest["portfolio_context_sha256"],
                            spy_context_sha256=manifest["spy_context_sha256"]))
        for role in ("source_pit", "spy_total_return"):
            packet["originals"][role].update(kind=role, start_session=dates[0], end_session=dates[-1])
        for role, fields in (
            ("closed_loop", dict(portfolio_kind="main", portfolio_context_sha256=manifest["portfolio_context_sha256"],
                 portfolio_report_sha256=nav.digest(report), producer="tools/run_broker_ledger_replay.py", own_fills_verified=True)),
            ("spy_total_return", dict(symbol="SPY", benchmark_policy=manifest["benchmark_policy"],
                 spy_context_sha256=manifest["spy_context_sha256"], dividends_reinvested=True)),
            ("source_pit", dict(portfolio_context_sha256=manifest["portfolio_context_sha256"],
                 spy_context_sha256=manifest["spy_context_sha256"], point_in_time_verified=True, corporate_actions_verified=True)),
        ):
            key = role+"_receipt_sha256"
            receipt = dict(kind=role, status="VERIFIED", start_session=dates[0], end_session=dates[-1],
                           original_sha256=nav.digest(packet["originals"][role]), **fields)
            packet["receipts"][key] = receipt
            manifest[key] = nav.digest(receipt)
        return packet

    def assess(self, p, kind="main"):
        return goal.assess(p, portfolio_kind=kind, expected_manifest_sha256=nav.digest(p["manifest"]),
                           end_session="2026-11-06")

    def test_joint_target_without_rounding(self):
        spy = [100000, 90000, 100000]
        for values, expected in (([100000, 90000, 700000], "PASS"), ([100000, 89999.99999, 700000], "MISS"),
                                 ([100000, 90000, 100000], "MISS")):
            result = self.assess(self.packet(values, spy))
            self.assertEqual(result["status"], expected, result)
            self.assertAlmostEqual(result["total_return"], values[-1]/100000-1)
        self.assertEqual(self.assess(self.packet(spy, spy), "concentrated")["status"], "DATA_BLOCKED")

    def test_relative_diagnostic_without_fixed_concentrated_cagr_target(self):
        spy = dict(cagr=.12, max_dd=-.20, ending_capital_usd=112000)
        for cagr, drawdown, base in (
            (.12, -.10, "MISS"), (.12000000001, -.20, "PASS"),
            (.39999999999, -.20, "PASS"), (.40, -.20, "PASS"),
            (.50, -.2000000001, "MISS"),
        ):
            book = dict(cagr=cagr, max_dd=drawdown, ending_capital_usd=100000+100000*cagr)
            self.assertEqual(goal.goal_outcome("main", book, spy)["status"], base)
            self.assertEqual(goal.goal_outcome("main", book, spy)["stretch_status"], "NOT_APPLICABLE")
            result = goal.goal_outcome("concentrated", book, spy)
            self.assertEqual((result["status"], result["stretch_status"]),
                             (base, "RETIRED_FIXED_CAGR_TARGET"))
        self.assertEqual(goal.goal_outcome("concentrated", dict(cagr=.43, max_dd=-.20, ending_capital_usd=143000),
                                          dict(cagr=.45, max_dd=-.30, ending_capital_usd=145000))["status"], "MISS")
        tiny = self.assess(self.packet([100000, 100000, math.nextafter(100000., math.inf)], [100000]*3))
        self.assertEqual(tiny["status"], "PASS")
        low = self.assess(self.packet([100000, 98000, 120000], [100000, 97000, 110000]))
        self.assertEqual((low["status"], low["stretch_status"], low["goal_policy"]),
                         ("PASS", "NOT_APPLICABLE", goal.GOAL_POLICY))
        self.assertEqual(low["project_mission"]["status"], "MISS")
        self.assertFalse(low["project_mission"]["cagr_met"])
        self.assertTrue(low["project_mission"]["drawdown_met"])
        self.assertEqual(low["project_mission"]["role"],
                         "LEGACY_FIXED_TARGET_DIAGNOSTIC_NOT_RESEARCH_ACCEPTANCE")
        self.assertIsNone(low["research_objective"]["fixed_cagr_target"])

    def test_compounding_objective_separates_benchmark_and_existing_risk_limit(self):
        spy = dict(cagr=.12, max_dd=-.40, ending_capital_usd=112000)
        for kind in ("main", "concentrated"):
            for cagr in (.13, .30, .35, .40, .50, .80):
                book = dict(cagr=cagr, max_dd=-.25, ending_capital_usd=100000*(1+cagr))
                result = goal.compounding_objective(kind, book, spy)
                self.assertEqual(result["status"], "MEASURED")
                self.assertIsNone(result["fixed_cagr_target"])
                self.assertEqual(result["drawdown_constraint"]["status"], "MET")
                self.assertEqual(result["drawdown_constraint"]["max_dd_min"], -.25)
                self.assertFalse(result["other_admission_gates_evaluated"])
                self.assertFalse(result["promotion_allowed"])
            book["max_dd"] = math.nextafter(-.25, -math.inf)
            # Beating SPY on return and MDD cannot relax the portfolio's own limit.
            self.assertEqual(goal.goal_outcome(kind, book, spy)["status"], "PASS")
            self.assertEqual(goal.compounding_objective(kind, book, spy)["drawdown_constraint"]["status"],
                             "BREACHED")
        measured = self.assess(self.packet([100000, 70000, 700000], [100000, 60000, 110000]))
        self.assertEqual(measured["status"], "PASS")
        self.assertEqual(measured["status_basis"], "MATCHED_SPY_COMPARISON_ONLY_NOT_ADMISSION")
        self.assertEqual(measured["research_objective"]["drawdown_constraint"]["status"], "BREACHED")
        self.assertFalse(measured["promotion_allowed"])

    def test_peak_to_recovery_longest_duration_and_equal_highs(self):
        anchor = dict(nav=100, timestamp="2026-01-01T21:00:00Z")
        rows = [dict(session="2026-01-"+day, nav=value) for day, value in
                (("02", 95), ("03", 98), ("05", 100), ("08", 100),
                 ("09", 70), ("10", 101), ("11", 80))]
        result = goal.drawdown_durations(rows, anchor)
        worst = result["max_drawdown_episode"]
        longest = result["longest_completed_episode"]
        self.assertEqual((worst["peak_session"], worst["trough_session"], worst["recovery_session"]),
                         ("2026-01-08", "2026-01-09", "2026-01-10"))
        self.assertEqual((worst["days"], worst["sessions"]), (2, 2))
        self.assertEqual((longest["days"], longest["sessions"]), (4, 3))
        self.assertEqual(result["completed_episode_count"], 2)
        self.assertEqual(result["ongoing_episode"]["observed_days"], 1)
        self.assertTrue(result["ongoing_episode"]["right_censored"])
        self.assertIsNone(result["ongoing_episode"]["days"])
        self.assertIsNone(result["ongoing_episode"]["sessions"])
        # The legacy trough measure retains its explicit, different meaning.
        self.assertEqual(goal._recovery(rows, anchor)["days"], 1)

    def test_recovery_from_anchor_and_unrecovered_window(self):
        anchor = dict(nav=100, timestamp="2026-01-01T21:00:00Z")
        rows = [dict(session="2026-01-02", nav=90), dict(session="2026-01-03", nav=80)]
        result = goal.drawdown_durations(rows, anchor)
        worst = result["max_drawdown_episode"]
        self.assertEqual(worst["status"], "UNRECOVERED_AT_END")
        self.assertEqual((worst["observed_days"], worst["observed_sessions"]), (2, 2))
        self.assertIsNone(worst["days"])
        self.assertIsNone(worst["recovery_session"])
        self.assertIsNone(result["longest_completed_episode"])
        rows = [dict(session=r["session"], nav=100) for r in rows]
        flat = goal.drawdown_durations(rows, anchor)
        self.assertEqual(flat["max_drawdown_episode"]["status"], "NO_DRAWDOWN")
        self.assertIsNone(flat["ongoing_episode"])

    def test_assess_recovery_anchor_uses_nyse_date_for_equivalent_timestamps(self):
        values = [90000, 100000, 102000]
        spy = [100000, 100000, 100000]
        utc = self.assess(self.packet(values, spy))
        offset = self.assess(self.packet(values, spy, anchor_time="2021-10-01T10:00:00+14:00"))
        self.assertNotEqual(utc["status"], "DATA_BLOCKED")
        self.assertEqual((offset["status"], offset["cagr"], offset["max_dd"]),
                         (utc["status"], utc["cagr"], utc["max_dd"]))
        expected = utc["drawdown_durations"]["max_drawdown_episode"]
        self.assertEqual((expected["peak_session"], expected["days"]), ("2021-09-30", 1862))
        self.assertEqual(offset["drawdown_durations"], utc["drawdown_durations"])

    def test_assess_recovery_counts_nyse_closes_between_anchor_and_first_nav(self):
        result = self.assess(self.packet([90000, 100000, 102000], [100000]*3,
                                         anchor_time="2021-09-28T20:00:00Z"))
        self.assertNotEqual(result["status"], "DATA_BLOCKED")
        episode = result["drawdown_durations"]["max_drawdown_episode"]
        self.assertEqual((episode["peak_session"], episode["trough_session"],
                          episode["recovery_session"]),
                         ("2021-09-28", "2021-10-01", "2026-11-05"))
        self.assertEqual((episode["days"], episode["sessions"], episode["observed_sessions"]),
                         (1864, 1282, 1282))

    def test_equal_depth_keeps_first_episode_and_reports_open_tie(self):
        rows = [dict(session="2026-01-"+day, nav=value) for day, value in
                (("02", 90), ("03", 100), ("04", 90))]
        result = goal.drawdown_durations(rows, dict(nav=100, timestamp="2026-01-01T21:00:00Z"))
        self.assertEqual(result["max_drawdown_episode"]["status"], "RECOVERED")
        self.assertEqual(result["max_drawdown_episode"]["trough_session"], "2026-01-02")
        self.assertEqual(result["ongoing_episode"]["status"], "UNRECOVERED_AT_END")
        self.assertEqual(result["max_drawdown_tie_policy"],
                         "FIRST_DEEPEST_EPISODE_ONGOING_REPORTED_SEPARATELY")

    def test_project_mission_thresholds_on_unrounded_measurements(self):
        for kind, threshold in (("main", .35), ("concentrated", .50)):
            for cagr, drawdown, cagr_met, drawdown_met in (
                (threshold, -.25, True, True),
                (math.nextafter(threshold, -math.inf), -.25, False, True),
                (threshold, math.nextafter(-.25, -math.inf), True, False),
            ):
                with self.subTest(kind=kind, cagr=cagr, drawdown=drawdown):
                    result = goal._project_mission(kind, {"cagr": cagr, "max_dd": drawdown})
                    self.assertEqual((result["cagr_min"], result["max_dd_min"]), (threshold, -.25))
                    self.assertEqual((result["cagr_met"], result["drawdown_met"]), (cagr_met, drawdown_met))
                    self.assertEqual(result["status"], "PASS" if cagr_met and drawdown_met else "MISS")

    def test_project_mission_is_independent_of_relative_base_and_packet_claims(self):
        p = self.packet([100000, 100000, 700000], [100000, 100000, 800000])
        p["project_mission"] = {"status": "MISS", "cagr_min": 100.}
        result = self.assess(p)
        self.assertEqual(result["status"], "MISS")
        mission = result["project_mission"]
        self.assertEqual((mission["status"], mission["cagr_min"], mission["max_dd_min"]), ("PASS", .35, -.25))
        self.assertEqual(mission["basis"], "MATCHED_RESEARCH_WINDOW_NET_NAV")
        identity = goal.mission_identity(goal.PORTFOLIO_MISSION_TARGETS)
        self.assertEqual(mission["mission_contract_sha256"], identity["mission_contract_sha256"])
        self.assertTrue(result["research_only"])
        self.assertFalse(result["promotion_allowed"])
        p["portfolio_report"]["cagr"] = 100.
        p["project_mission"] = {"status": "PASS"}
        blocked = self.assess(p)
        self.assertEqual(blocked["status"], "DATA_BLOCKED")
        self.assertIsNone(blocked["project_mission"])
        self.assertIsNone(blocked["research_objective"])

    def test_month_labels_calendar_cash_and_partial_period(self):
        # Daily grid validation happens before the diagnostic. Only month-end marks matter here.
        dates = ["2021-10-01","2021-10-29","2021-11-30","2021-12-31","2022-01-31","2022-02-04"]
        packet = dict(manifest={})
        for name, marks in (("portfolio", [100,95,100,90,90,70]), ("spy",[100,90,99,90,90,110])):
            packet[name] = dict(context=dict(anchor=dict(nav=100, timestamp="2021-09-30T20:00:00Z")),
                                rows=[dict(session=d, nav=v) for d,v in zip(dates, marks)])
        cash = [dict(date=d, equity_usd=r["nav"], cash_usd=19) for d,r in zip(dates, packet["portfolio"]["rows"])]
        packet["equity_curve"] = cash
        packet["manifest"]["equity_curve_sha256"] = nav.digest(cash)
        self.assertEqual(goal.monthly_diagnostics(packet)["cash_status"], "DATA_BLOCKED")
        packet["manifest"]["equity_curve_cash_basis"] = goal.CASH_BASIS
        diag = goal.monthly_diagnostics(packet)
        self.assertEqual(len(diag["months"]), 4)
        downs, rebounds = (diag["groups"][k] for k in ("spy_down", "immediate_rebound"))
        self.assertEqual((downs["count"], rebounds["count"]), (2, 1))
        self.assertAlmostEqual(downs["spy_return"], .9 * (90/99) - 1)
        self.assertAlmostEqual(rebounds["portfolio_return"], 100/95 - 1)
        self.assertAlmostEqual(rebounds["mean_prior_cash_weight"], 19/95)
        cash[1]["cash_usd"] = 0
        invalid = goal.monthly_diagnostics(packet)
        self.assertEqual(invalid["cash_status"], "DATA_BLOCKED")
        self.assertIsNone(invalid["groups"]["immediate_rebound"]["mean_prior_cash_weight"])
        for name in ("portfolio","spy"):
            packet[name]["rows"].pop(0)
        partial = goal.monthly_diagnostics(packet)
        self.assertEqual([row["month"] for row in partial["months"]], ["2021-11","2021-12","2022-01"])
        self.assertEqual(partial["groups"]["immediate_rebound"]["count"], 0)

    def test_recovery_gross_turnover_and_optional_qqq(self):
        p = self.packet([100000, 90000, 700000], [100000, 98000, 110000])
        blocked_optional = self.assess(p)
        self.assertEqual(blocked_optional["recovery_from_worst_trough"], dict(status="RECOVERED", days=1, sessions=1))
        self.assertEqual(blocked_optional["drawdown_durations"]["max_drawdown_episode"]["days"], 2)
        self.assertEqual(blocked_optional["turnover"]["status"], "DATA_BLOCKED")
        self.assertEqual(blocked_optional["qqq"]["status"], "DATA_BLOCKED")
        untouched = self.assess(self.packet([100000, 90000, 99000], [100000, 98000, 110000]))
        self.assertEqual(untouched["recovery_from_worst_trough"]["status"], "UNRECOVERED_AT_END")

        p["trades"] = [dict(date=p["manifest"]["start_session"], side="BUY", quantity=10, fill_price=9, gross_value=90)]
        p["manifest"]["trades_sha256"] = nav.digest(p["trades"])
        report = p["portfolio_report"]
        report["trade_count"] = 1
        key = "closed_loop_receipt_sha256"
        p["originals"]["closed_loop"] = report
        p["receipts"][key].update(original_sha256=nav.digest(report), portfolio_report_sha256=nav.digest(report))
        p["manifest"][key] = nav.digest(p["receipts"][key])
        p["manifest"]["portfolio_report_sha256"] = nav.digest(report)
        p["qqq"] = copy.deepcopy(p["spy"])
        original = dict(p["originals"]["spy_total_return"], symbol="QQQ", kind="qqq_total_return")
        p["originals"]["qqq_total_return"] = original
        p["manifest"]["qqq_total_return_original_sha256"] = nav.digest(original)
        p["manifest"]["qqq_context_sha256"] = nav.digest(p["qqq"]["context"])
        result = self.assess(p)
        self.assertEqual(result["qqq"]["status"], "MEASURED")
        self.assertEqual(result["qqq"]["cagr"], result["spy_cagr"])
        avg = sum(r["nav"] for r in p["portfolio"]["rows"])/len(p["portfolio"]["rows"])
        self.assertAlmostEqual(result["turnover"]["gross_over_mean_daily_nav"], 90/avg)
        p["qqq"]["rows"].pop()
        p["trades"][0]["side"] = "UNKNOWN"
        p["manifest"]["trades_sha256"] = nav.digest(p["trades"])
        invalid = self.assess(p)
        self.assertEqual(invalid["status"], result["status"])
        for field in ("turnover", "qqq"):
            self.assertEqual(invalid[field]["status"], "DATA_BLOCKED")

    def test_turnover_overflow_is_optional(self):
        fills = [dict(date="2021-10-01", side="BUY", quantity=1, fill_price=1e308, gross_value=1e308)]*2
        packet = dict(trades=fills, manifest={"trades_sha256": nav.digest(fills)},
                      portfolio_report={"trade_count": 2}, portfolio={"rows": [dict(session="2021-10-01", nav=100000)]})
        self.assertEqual(goal._turnover(packet, {"years": 5})["status"], "DATA_BLOCKED")

    def test_native_fixed_fee_omission_and_variable_fee_refusal(self):
        p = self.packet([100000, 99000, 700000], [100000, 99000, 110000])
        self.assertNotIn("execution_cost_mode", p["portfolio_report"])
        self.assertEqual(self.assess(p)["status"], "PASS")
        for fields in ({"execution_cost_mode": "variable"}, {"execution_cost_config": {"enabled": True}}):
            changed = copy.deepcopy(p)
            report = changed["portfolio_report"]
            report.update(fields)
            key = "closed_loop_receipt_sha256"
            hashed = nav.digest(report)
            changed["manifest"]["portfolio_report_sha256"] = hashed
            changed["originals"]["closed_loop"] = report
            changed["receipts"][key].update(original_sha256=hashed, portfolio_report_sha256=hashed)
            changed["manifest"][key] = nav.digest(changed["receipts"][key])
            self.assertEqual(self.assess(changed)["reason"], "GOAL_VARIABLE_COST")

    def test_absent_original_mismatched_window_and_cost(self):
        packet = self.packet([100100, 100200, 101000], [100000, 99000, 100000])
        for change in ("raw", "spy", "session", "proxy", "failed", "wrong_book", "original_end", "cost"):
            p = copy.deepcopy(packet)
            if change == "raw":
                p["receipts"].clear()
            elif change in ("failed", "wrong_book"):
                key = "closed_loop_receipt_sha256"
                p["receipts"][key].update({"status": "FAILED"} if change == "failed" else {"portfolio_kind": "concentrated"})
                p["manifest"][key] = nav.digest(p["receipts"][key])
            elif change == "original_end":
                role = "spy_total_return"
                key = role+"_receipt_sha256"
                p["originals"][role]["end_session"] = "2024-12-31"
                p["receipts"][key]["original_sha256"] = nav.digest(p["originals"][role])
                p["manifest"][key] = nav.digest(p["receipts"][key])
            elif change == "spy":
                p["spy"]["rows"].pop(1)
            elif change == "session":
                p["manifest"]["end_session"] = "2021-10-06"
            elif change == "proxy":
                p["manifest"]["benchmark_policy"] = "ADJUSTED_CLOSE_PROXY"
            else:
                p["portfolio_report"]["cost_bps_per_side"] = 50
                p["manifest"]["portfolio_report_sha256"] = nav.digest(p["portfolio_report"])
            blocked = self.assess(p)
            self.assertEqual(blocked["status"], "DATA_BLOCKED", change)
            self.assertIsNone(blocked["project_mission"], change)


if __name__ == "__main__":
    unittest.main()
