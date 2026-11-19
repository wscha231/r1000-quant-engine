from __future__ import annotations
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.nav_metrics_v2_smoke import context
from tools import evaluate_a5_research_goal as goal
from tools import nav_metrics_v2 as nav


class GoalTests(unittest.TestCase):
    def packet(self, values, spy_values):
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
            c = context(rows, anchor_nav=100000, anchor_time="2021-09-30T20:00:00Z")
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
            self.assertEqual(self.assess(p)["status"], "DATA_BLOCKED", change)


if __name__ == "__main__":
    unittest.main()
