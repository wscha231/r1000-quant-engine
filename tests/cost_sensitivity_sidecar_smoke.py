#!/usr/bin/env python3
"""Smoke tests for the cost-sensitivity sidecar.

Verifies that the sidecar:
  * runs 4 cost levels and emits one row per level
  * computes baseline-relative deltas
  * shows higher costs erode CAGR / ending capital monotonically
  * publishes the schema fields the auto policy challenger looks for
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_cost_sensitivity_sidecar import run  # noqa: E402
from tools import run_cost_sensitivity_sidecar as sidecar  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


def _write_px(cache_dir: Path, ticker: str, closes: list[float], start: str = "2024-01-02") -> None:
    idx = pd.bdate_range(start=start, periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )
    df.to_parquet(cache_dir / px_cache_name(ticker))


def test_cost_sensitivity_sweep_emits_four_levels_and_monotonic_cost_drag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "cost_sensitivity"
        cache.mkdir()
        # 60 business days of steadily-rising synthetic prices with weekly
        # rotation so trades happen at every rebalance regardless of cost.
        rising = [100.0 + i * 0.30 for i in range(60)]
        slow = [50.0 + i * 0.05 for i in range(60)]
        _write_px(cache, "AAA", rising, start="2024-01-02")
        _write_px(cache, "BBB", slow, start="2024-01-02")

        target = root / "targets.csv"
        rows = []
        # Alternate weighting every week to force turnover so cost drag is visible.
        rebalance_dates = [
            "2024-01-02", "2024-01-09", "2024-01-16", "2024-01-23",
            "2024-01-30", "2024-02-06", "2024-02-13", "2024-02-20",
        ]
        for i, dt in enumerate(rebalance_dates):
            if i % 2 == 0:
                rows.append({"rebalance_date": dt, "ticker": "AAA", "weight": 0.70})
                rows.append({"rebalance_date": dt, "ticker": "BBB", "weight": 0.20})
            else:
                rows.append({"rebalance_date": dt, "ticker": "AAA", "weight": 0.20})
                rows.append({"rebalance_date": dt, "ticker": "BBB", "weight": 0.70})
        pd.DataFrame(rows).to_csv(target, index=False)

        payload = run(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            cost_bps_list=[25.0, 50.0, 75.0, 100.0],
            starting_capital=10_000.0,
            fill_mode="next_close",
            max_fill_lag_days=7,
            baseline_cost_bps=25.0,
        )

        assert payload["schema_version"] == "cost-sensitivity-sidecar-v1"
        assert payload["portfolio_kind"] == "main"
        assert payload["research_only"] is True
        assert payload["production_activation_allowed"] is False
        levels = payload["levels"]
        assert len(levels) == 4
        # Levels sorted ascending by cost.
        assert [lv["cost_bps"] for lv in levels] == [25.0, 50.0, 75.0, 100.0]
        # Higher cost should not produce higher ending capital, given the
        # same target book and a non-zero-turnover policy.
        endings = [lv["ending_capital_usd"] for lv in levels]
        assert endings[0] >= endings[1] >= endings[2] >= endings[3], endings
        # Baseline row reports zero delta against itself; later levels are non-positive.
        assert levels[0]["cagr_delta_pp_vs_baseline"] == 0.0
        for lv in levels[1:]:
            assert lv["cagr_delta_pp_vs_baseline"] <= 0.0 + 1e-6, lv
            assert lv["total_fees_usd"] >= levels[0]["total_fees_usd"]
        # Output files exist and are valid JSON / non-empty markdown.
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["portfolio_kind"] == "main"
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "Cost Sensitivity Sidecar" in report
        assert "Cost bps" in report


def test_cost_sensitivity_handles_single_level() -> None:
    """Edge case: a single cost level produces one row and no monotonicity claim."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        out = root / "cost_sensitivity"
        cache.mkdir()
        _write_px(cache, "AAA", [100.0] * 20, start="2024-01-02")
        target = root / "targets.csv"
        pd.DataFrame([{"rebalance_date": "2024-01-02", "ticker": "AAA", "weight": 1.0}]).to_csv(target, index=False)

        payload = run(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            cost_bps_list=[50.0],
            starting_capital=10_000.0,
            fill_mode="next_close",
            max_fill_lag_days=7,
            baseline_cost_bps=50.0,
        )
        assert payload["status"] == "completed"
        assert len(payload["levels"]) == 1
        assert payload["levels"][0]["cost_bps"] == 50.0
        assert payload["levels"][0]["cagr_delta_pp_vs_baseline"] == 0.0


class BlockedCostResultChecks(unittest.TestCase):
    fields = ("cagr", "sharpe", "max_dd", "ending_capital_usd", "total_fees_usd",
              "trade_count", "avg_cash_weight", "gross_traded_usd")
    deltas = ("cagr_delta_pp_vs_baseline", "sharpe_delta_vs_baseline",
              "maxdd_delta_pp_vs_baseline", "ending_delta_usd_vs_baseline")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache, self.out = self.root / "cache", self.root / "out"
        self.cache.mkdir()
        _write_px(self.cache, "AAA", [100.0 + i for i in range(20)])
        self.target = self.root / "target.csv"
        pd.DataFrame([{"rebalance_date": "2024-01-02", "ticker": "AAA", "weight": 1.0}]).to_csv(self.target, index=False)

    def invoke(self, **changes):
        args = dict(target_book=self.target, price_cache=self.cache, output_dir=self.out,
                    portfolio_kind="main", cost_bps_list=[25.0, 50.0], starting_capital=10000.0,
                    fill_mode="next_close", max_fill_lag_days=7, baseline_cost_bps=25.0)
        args.update(changes)
        return sidecar.run(**args)

    @staticmethod
    def completed(cost=25.0):
        return {"status": "completed", "metric_mode": "broker_ledger_next_close", "cost_bps_per_side": cost,
                "cagr": .1, "sharpe": 1.2, "max_dd": -.05, "ending_capital_usd": 11000.,
                "total_fees_usd": 25., "trade_count": 2, "avg_cash_weight": .1, "gross_traded_usd": 10000.}

    def check_blocked_row(self, row):
        self.assertNotEqual(row["status"], "completed")
        for field in self.fields + self.deltas:
            self.assertIsNone(row.get(field), field)

    def test_real_next_open_blocks_all_levels_and_cli_without_zero_performance(self):
        payload = self.invoke(fill_mode="next_open")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["metric_mode"], "DO_NOT_USE")
        self.assertEqual([r["cost_bps"] for r in payload["levels"]], [25., 50.])
        self.assertIsNone(payload["breakeven_cost_bps"])
        for row in payload["levels"]:
            self.check_blocked_row(row)
            self.assertEqual(row["reason"], "next_open_precommitted_order_intent_unavailable")
        report = (self.out / "report.md").read_text(encoding="utf-8")
        self.assertIn("blocked", report)
        self.assertIn("N/A", report)
        self.assertNotIn("0.00%", report)

    def test_cli_reports_blocked_next_open_and_successful_next_close(self):
        for fill_mode, expected in (("next_open", 2), ("next_close", 0)):
            with self.subTest(fill_mode=fill_mode):
                self.check_cli(fill_mode, expected)

    def check_cli(self, fill_mode, expected):
        cli = subprocess.run([sys.executable, *(["-O"] if not __debug__ else []),
            str(REPO_ROOT / "tools/run_cost_sensitivity_sidecar.py"), "--target-book", str(self.target),
            "--price-cache", str(self.cache), "--output-dir", str(self.out), "--fill-mode", fill_mode,
            "--cost-bps-list", "25", "50"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(cli.returncode, expected, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["status"], "blocked" if expected else "completed")

    def test_completed_then_blocked_reused_output_preserves_caller_files(self):
        old = self.invoke()
        self.assertEqual(old["status"], "completed")
        self.assertTrue(all(r["status"] == "completed" for r in old["levels"]))
        caller = self.out / "caller.json"
        nested = self.out / "archive" / "summary.json"
        nested.parent.mkdir()
        caller.write_bytes(b"caller-owned")
        nested.write_bytes(b"archive-owned")
        for open_column in ("missing", "invalid"):
            with self.subTest(open_column=open_column):
                prices = pd.read_parquet(self.cache / px_cache_name("AAA"))
                if open_column == "missing": prices = prices.drop(columns=["Open"], errors="ignore")
                else: prices["Open"] = 0.
                prices.to_parquet(self.cache / px_cache_name("AAA"))
                result = self.invoke(fill_mode="next_open")
                self.assertEqual(result["status"], "blocked")
                for row in result["levels"]: self.check_blocked_row(row)
                saved = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual(saved, result)
                self.assertEqual(caller.read_bytes(), b"caller-owned")
                self.assertEqual(nested.read_bytes(), b"archive-owned")

    def test_blocked_unknown_or_unusable_completed_metrics_are_redacted(self):
        cases = [("status_" + str(s), {**self.completed(), "status": s})
                 for s in ("blocked", "BLOCKED_SHORT_HISTORY", "unknown", "skipped", None)]
        for field in self.fields:
            for value in (None, float("nan"), float("inf"), float("-inf"), True):
                cases.append((f"{field}_{value!r}", {**self.completed(), field: value}))
        for key in ("metric_mode", "performance_fields_redacted"):
            cases.append((key, {**self.completed(), key: "DO_NOT_USE" if key == "metric_mode" else True}))
        for name, metrics in cases:
            with self.subTest(name=name):
                row = sidecar.summarize(metrics, self.completed())
                self.check_blocked_row(row)
        positive = sidecar.summarize({**self.completed(), "cagr": 0.}, {**self.completed(), "cagr": 0.})
        self.assertEqual(positive["status"], "completed")
        self.assertEqual(positive["cagr"], 0.)
        self.assertEqual(positive["cagr_delta_pp_vs_baseline"], 0.)

    def test_blocked_baseline_or_late_level_never_admits_whole_sweep(self):
        for blocked_cost in (25., 50.):
            with self.subTest(blocked_cost=blocked_cost):
                def result(**args):
                    cost = args["cost_bps"]
                    return ({"status": "blocked", "reason": "synthetic_prerequisite", "cagr": 9.99}
                            if cost == blocked_cost else self.completed(cost))
                with patch.object(sidecar, "run_level", side_effect=result): payload = self.invoke()
                self.assertEqual(payload["status"], "blocked")
                self.assertIsNone(payload["breakeven_cost_bps"])
                for row in payload["levels"]:
                    if row["cost_bps"] == blocked_cost: self.check_blocked_row(row)
                    elif blocked_cost == 25.:
                        self.assertEqual(row["cagr"], .1)
                        for field in self.deltas: self.assertIsNone(row.get(field))

    def test_completed_baseline_later_in_sorted_sweep_binds_all_deltas(self):
        with patch.object(sidecar, "run_level", side_effect=lambda **a: self.completed(a["cost_bps"])):
            payload = self.invoke(baseline_cost_bps=50.)
        self.assertEqual(payload["status"], "completed")
        for row in payload["levels"]:
            self.assertEqual(row["cagr_delta_pp_vs_baseline"], 0.)

    def test_direct_deltas_require_usable_baseline_metadata(self):
        cases = [{**self.completed(), "status": status} for status in ("blocked", "unknown", None)]
        cases += [{**self.completed(), "metric_mode": "DO_NOT_USE"},
                  {**self.completed(), "performance_fields_redacted": True}]
        cases += [{**self.completed(), field: value}
                  for field in ("cagr", "sharpe", "max_dd", "ending_capital_usd")
                  for value in (None, True, float("nan"), float("inf"))]
        for baseline in cases:
            with self.subTest(baseline=baseline):
                row = sidecar.summarize(self.completed(), baseline)
                self.assertEqual(row["status"], "completed")
                for field in self.deltas: self.assertIsNone(row.get(field))

    def test_root_broker_cli_already_propagates_blocked_mode_without_numeric_metrics(self):
        for mode, expected in (("next_open", 2), ("next_close", 0)):
            with self.subTest(mode=mode):
                command = [sys.executable, *(["-O"] if not __debug__ else []),
                    str(REPO_ROOT / "tools/run_broker_ledger_replay.py"), "--target-book", str(self.target),
                    "--price-cache", str(self.cache), "--output-dir", str(self.root / "broker-cli"),
                    "--fill-mode", mode, "--cost-bps", "25"]
                process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(process.returncode, expected, process.stderr)
                payload = json.loads(process.stdout)
                self.assertEqual(payload["status"], "blocked" if expected else "completed")
                if expected:
                    self.assertEqual(payload["metric_mode"], "DO_NOT_USE")
                    for field in ("cagr", "sharpe", "max_dd"): self.assertIsNone(payload.get(field))

    def test_empty_invalid_sweep_or_baseline_blocks_before_replay(self):
        cases = [{"cost_bps_list": []}]
        for value in (None, True, -1., float("nan"), float("inf")):
            cases.extend([{"cost_bps_list": [25., value]}, {"baseline_cost_bps": value}])
        for case in cases:
            with self.subTest(case=case), patch.object(sidecar, "run_level") as replay:
                payload = self.invoke(**case)
                self.assertEqual(payload["status"], "blocked")
                self.assertIsNone(payload["breakeven_cost_bps"])
                replay.assert_not_called()
                json.dumps(payload, allow_nan=False)

    def test_level_exception_replaces_old_summaries_without_private_error_text(self):
        with patch.object(sidecar, "run_level", side_effect=lambda **a: self.completed(a["cost_bps"])):
            self.invoke()
        with patch.object(sidecar, "run_level", side_effect=ValueError("private-error-marker")):
            payload = self.invoke()
        self.assertEqual(payload["status"], "blocked")
        for row in payload["levels"]: self.check_blocked_row(row)
        self.assertNotIn("private-error-marker", (self.out / "summary.json").read_text(encoding="utf-8"))
        self.assertNotIn("private-error-marker", (self.out / "report.md").read_text(encoding="utf-8"))

    def test_absent_and_near_unrequested_baselines_block_before_replay(self):
        cases = [([25., 50.], 0.), ([25., 50.], 75.), ([25.], 25.00000001),
                 ([25.00000001], 25.), (["25", 50.], "25.00000001")]
        for costs, baseline in cases:
            with self.subTest(costs=costs, baseline=baseline), \
                 patch.object(sidecar, "run_level", side_effect=lambda **a: self.completed(a["cost_bps"])) as level:
                payload = self.invoke(cost_bps_list=costs, baseline_cost_bps=baseline)
                self.assertEqual(payload["status"], "blocked")
                self.assertEqual(payload["metric_mode"], "DO_NOT_USE")
                self.assertEqual(payload["baseline_status"], "not_in_sweep")
                self.assertEqual(payload["reason"], "cost_baseline_not_in_sweep")
                self.assertIsNone(payload["breakeven_cost_bps"])
                self.assertEqual(payload["levels"], [])
                level.assert_not_called()

    def test_exact_normalized_baseline_cannot_borrow_an_earlier_near_cost(self):
        baseline = 25.00000001
        def replayed(**args):
            return {**self.completed(args["cost_bps"]),
                    "ending_capital_usd": 12000. if args["cost_bps"] == baseline else 10000.}
        with patch.object(sidecar, "run_level", side_effect=replayed):
            payload = self.invoke(cost_bps_list=["25", baseline, 50., "25"], baseline_cost_bps=str(baseline))
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(len(payload["levels"]), 3)
        exact = next(row for row in payload["levels"] if row["cost_bps"] == baseline)
        self.assertEqual(exact["ending_delta_usd_vs_baseline"], 0.)
        first = payload["levels"][0]
        self.assertEqual(first["ending_delta_usd_vs_baseline"], -2000.)

    def test_unusable_baseline_never_completes_or_supplies_comparisons(self):
        cases = [None, []]
        cases += [{**self.completed(), "status": value} for value in (None, "blocked", "unknown", "skipped")]
        cases += [{**self.completed(), "metric_mode": "DO_NOT_USE"},
                  {**self.completed(), "performance_fields_redacted": True}]
        cases += [{**self.completed(), field: value} for field in self.fields
                  for value in (None, True, float("nan"), float("inf"), float("-inf"))]
        for baseline in cases:
            with self.subTest(baseline=baseline):
                def level(**args):
                    return baseline if args["cost_bps"] == 25. else self.completed(args["cost_bps"])
                with patch.object(sidecar, "run_level", side_effect=level):
                    payload = self.invoke()
                self.assertEqual(payload["status"], "blocked")
                self.assertEqual(payload["baseline_status"], "blocked")
                self.assertIsNone(payload["breakeven_cost_bps"])
                for row in payload["levels"]:
                    for field in self.deltas:
                        self.assertIsNone(row[field])

    def test_real_single_and_later_baselines_remain_usable(self):
        for costs, baseline in (([50.], 50.), ([50., 25., 50.], 50.), (["25", 50.], "25")):
            with self.subTest(costs=costs, baseline=baseline):
                payload = self.invoke(cost_bps_list=costs, baseline_cost_bps=baseline)
                self.assertEqual(payload["status"], "completed")
                self.assertEqual(payload["baseline_status"], "completed")
                row = next(r for r in payload["levels"] if r["cost_bps"] == float(baseline))
                for field in self.deltas:
                    self.assertEqual(row[field], 0.)

    def test_missing_baseline_reused_directory_and_native_main_fail_closed(self):
        self.assertEqual(self.invoke()["status"], "completed")
        caller, nested = self.out / "caller.csv", self.out / "archive" / "summary.json"
        nested.parent.mkdir()
        caller.write_bytes(b"caller")
        nested.write_bytes(b"archive")
        argv = ["sidecar", "--target-book", str(self.target), "--price-cache", str(self.cache),
                "--output-dir", str(self.out), "--cost-bps-list", "50", "--baseline-cost-bps", "25"]
        with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()) as printed:
            code = sidecar.main()
        self.assertEqual(code, 2)
        payload = json.loads(printed.getvalue())
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["baseline_status"], "not_in_sweep")
        self.assertEqual(json.loads((self.out / "summary.json").read_bytes()), payload)
        self.assertIn("blocked", (self.out / "report.md").read_text(encoding="utf-8"))
        self.assertEqual(caller.read_bytes(), b"caller")
        self.assertEqual(nested.read_bytes(), b"archive")

    def test_sidecar_preserves_both_owned_names_before_all_validation_paths(self):
        source, original = self.target, self.target.read_bytes()
        for name in ("summary.json", "report.md"):
            for case in ("valid", "absent_baseline", "invalid_inputs", "opening"):
                with self.subTest(name=name, case=case):
                    self.out = self.root / (name + case)
                    self.out.mkdir()
                    self.target = self.out / name
                    self.target.write_bytes(original)
                    other = self.out / ("report.md" if name == "summary.json" else "summary.json")
                    other.write_bytes(b"old summary")
                    options = ({"cost_bps_list": [50.]} if case == "absent_baseline" else
                               {"cost_bps_list": []} if case == "invalid_inputs" else
                               {"fill_mode": "next_open"} if case == "opening" else {})
                    with patch.object(sidecar, "run_level", side_effect=AssertionError("collision reached replay")) as level:
                        result = self.invoke(**options)
                    self.assertTrue(self.target.exists(), "caller target deleted")
                    self.assertEqual(self.target.read_bytes(), original)
                    self.assertEqual(result["status"], "blocked")
                    self.assertEqual(result["reason"], "caller_input_collides_with_replay_output")
                    self.assertEqual(result["metric_mode"], "DO_NOT_USE")
                    self.assertIsNone(result["breakeven_cost_bps"])
                    level.assert_not_called()
                    self.assertNotEqual(other.read_bytes(), b"old summary")
        self.target = source


def main() -> int:
    test_cost_sensitivity_sweep_emits_four_levels_and_monotonic_cost_drag()
    test_cost_sensitivity_handles_single_level()
    if not unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(BlockedCostResultChecks)).wasSuccessful():
        return 1
    print("cost_sensitivity_sidecar_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
