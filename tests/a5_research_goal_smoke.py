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
        dates = ("2021-10-01", "2021-10-04", "2021-10-05")
        packet = {"manifest": dict(schema="a5-matched-spy-goal-v1", portfolio_kind="main", benchmark="SPY",
                      benchmark_policy="BUY_AND_HOLD_DIVIDENDS_REINVESTED", start_session=dates[0],
                      end_session=dates[-1]), "receipts": {}}
        manifest = packet["manifest"]
        for key in ("spy_total_return_receipt_sha256", "source_pit_receipt_sha256", "closed_loop_receipt_sha256"):
            packet["receipts"][key] = {"synthetic_test": key}
            manifest[key] = nav.digest(packet["receipts"][key])
        for name, points in (("portfolio", values), ("spy", spy_values)):
            rows = [dict(session=d, timestamp=d+"T20:00:00Z", nav=v) for d, v in zip(dates, points)]
            c = context(rows, anchor_nav=100000, anchor_time="2021-09-30T20:00:00Z")
            packet[name] = dict(context=c, rows=rows)
            manifest[name+"_context_sha256"] = nav.digest(c)
        book = packet["portfolio"]
        report = nav.calculate(book["rows"], book["context"])
        report.update(portfolio_kind="main", execution_status="completed", integer_shares=True, fill_mode="next_close",
                      cost_bps_per_side=25, cash_carry_mode="risk_free_rate", cash_rate_source="DGS3MO",
                      cash_rate_lag_days=1, cash_carry_haircut_bps=0, cash_carry_day_count=365,
                      cash_rate_future_use_count=0, execution_cost_mode="fixed_bps")
        packet["portfolio_report"] = report
        manifest["portfolio_report_sha256"] = nav.digest(report)
        return packet

    def assess(self, p, kind="main"):
        return goal.assess(p, portfolio_kind=kind, expected_manifest_sha256=nav.digest(p["manifest"]))

    def test_joint_target_without_rounding(self):
        spy = [100000, 90000, 100000]
        for values, expected in (([100000, 90000, 101000], "PASS"), ([100000, 89999.99999, 101000], "MISS"),
                                 ([100000, 90000, 100000], "MISS")):
            result = self.assess(self.packet(values, spy))
            self.assertEqual(result["status"], expected, result)
            self.assertAlmostEqual(result["total_return"], values[-1]/100000-1)
        self.assertEqual(self.assess(self.packet(spy, spy), "concentrated")["status"], "DATA_BLOCKED")

    def test_absent_original_mismatched_window_and_cost(self):
        packet = self.packet([100100, 100200, 101000], [100000, 99000, 100000])
        for change in ("raw", "spy", "session", "proxy", "cost"):
            p = copy.deepcopy(packet)
            if change == "raw":
                p["receipts"].clear()
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
