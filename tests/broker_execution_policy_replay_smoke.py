#!/usr/bin/env python3
from __future__ import annotations

import json
from contextlib import redirect_stdout
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_execution_policy_replay import replay
from tools import run_broker_execution_policy_replay as policy
from tools import run_broker_position_risk_replay as risk
from tools.run_weekly_evaluation import px_cache_name


def _write_price(cache: Path, ticker: str, prices: list[float]) -> None:
    dates = pd.bdate_range("2026-01-01", periods=len(prices))
    frame = pd.DataFrame({"Close": prices, "Adj Close": prices, "Open": prices}, index=dates)
    frame.to_parquet(cache / px_cache_name(ticker))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache_prices"
        cache.mkdir()
        _write_price(cache, "AAA", [100, 101, 102, 103, 104, 106, 108, 110, 111, 112, 113, 114, 115, 116, 117])
        target = root / "targets.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-01", "ticker": "AAA", "weight": 1.00},
                {"rebalance_date": "2026-01-08", "ticker": "AAA", "weight": 0.99},
            ]
        ).to_csv(target, index=False)
        out = root / "out"
        metrics = replay(
            target_book=target,
            price_cache=cache,
            output_dir=out,
            portfolio_kind="main",
            cost_bps=0.0,
            buy_band=0.05,
            sell_band=0.05,
            min_holding_days=63,
            new_entry_scale=1.0,
        )
        assert metrics["status"] == "completed"
        assert metrics["broker_ledger_valid"] is True
        assert metrics["valid_for_production"] is False
        assert metrics["research_only"] is True
        assert metrics["metric_mode"] == "broker_ledger_execution_policy_next_close"
        trades = pd.read_csv(out / "trades.csv")
        assert len(trades) == 1, trades
        assert trades.iloc[0]["side"] == "BUY"
        policy = pd.read_csv(out / "policy_decisions.csv")
        assert "skip_sell_inside_band" in set(policy["reason"]) or "skip_buy_inside_band" in set(policy["reason"])
        loaded = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        assert loaded["trade_count"] == 1
    print("broker_execution_policy_replay_smoke: PASS")
    return 0


class OpeningConsumerContract(unittest.TestCase):
    """Four-session synthetic admission tests, independent of economic performance."""

    engines = (policy, risk)
    shared_outputs = ("equity_curve.csv", "trades.csv", "holdings_daily.csv",
                      "cash_ledger.csv", "positions_latest.csv", "account_state_latest.json",
                      "metrics.json", "replay_report.md")

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.serial = 0

    def fixture(self, pattern: str = "valid", future_close: float = 100.0):
        self.serial += 1
        root = self.root / str(self.serial)
        cache = root / "cache"
        cache.mkdir(parents=True)
        dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
        fields = {"Close": [100.0, 100.0, future_close, 100.0],
                  "Adj Close": [100.0, 100.0, future_close, 100.0]}
        if pattern != "missing":
            opens = [50.0] * 4
            if pattern == "gap":
                opens[1] = None
            elif pattern in {"null", "nan", "infinite", "zero", "negative", "text"}:
                value = {"null": None, "nan": float("nan"), "infinite": float("inf"),
                         "zero": 0.0, "negative": -1.0, "text": "invalid"}[pattern]
                opens = [value] * 4
            fields["Open"] = opens
        pd.DataFrame(fields, index=dates).to_parquet(cache / px_cache_name("AAA"))
        benchmark = {"Close": [100.0] * 4, "Adj Close": [100.0] * 4}
        if pattern != "mixed":
            benchmark["Open"] = [100.0] * 4
        pd.DataFrame(benchmark, index=dates).to_parquet(cache / px_cache_name("SPY"))
        target = root / "targets.csv"
        pd.DataFrame([
            {"rebalance_date": "2026-01-02", "ticker": "AAA", "weight": 0.75},
            {"rebalance_date": "2026-01-05", "ticker": "AAA", "weight": 0.25},
        ]).to_csv(target, index=False)
        return target, cache, root / "out"

    def invoke(self, engine, target, cache, out, mode="next_open", **extra):
        options = dict(target_book=target, price_cache=cache, output_dir=out,
                       portfolio_kind="main", fill_mode=mode, cost_bps=0.0,
                       starting_capital=10000.0)
        if engine is risk:
            options.update(hard_stop=-1.0, trailing_stop=-1.0,
                           relative_trim_threshold=-10.0, relative_exit_threshold=-10.0,
                           enable_distribution_exit=False)
        options.update(extra)
        return engine.replay(**options)

    def closed(self, payload, out):
        self.assertEqual(payload.get("status"), "blocked")
        self.assertEqual(payload.get("metric_mode"), "DO_NOT_USE")
        self.assertTrue(payload.get("reason"))
        self.assertIs(payload.get("valid_for_production"), False)
        self.assertIs(payload.get("broker_ledger_valid"), False)
        for name in ("cagr", "sharpe", "max_dd", "ending_capital_usd", "total_return",
                     "avg_cash_weight", "trade_count"):
            self.assertIsNone(payload.get(name), name)
        self.assertEqual(json.loads((out / "metrics.json").read_text(encoding="utf-8")), payload)
        report = (out / "replay_report.md").read_text(encoding="utf-8")
        self.assertIn("DO_NOT_USE", report)
        self.assertIn("CAGR: N/A", report)
        self.assertNotIn("CAGR: 0.00%", report)

    def fail_input(self, kind, target, cache):
        if kind == "empty":
            pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(target, index=False)
        elif kind == "overweight":
            frame = pd.read_csv(target)
            frame["weight"] = 2.0
            frame.to_csv(target, index=False)
        elif kind == "missing_prices":
            for file in cache.iterdir():
                file.unlink()

    def test_all_observed_and_unavailable_open_families_block(self):
        for engine in self.engines:
            for pattern in ("valid", "missing", "gap", "null", "nan", "infinite",
                            "zero", "negative", "text", "mixed"):
                with self.subTest(engine=engine.__name__, pattern=pattern):
                    target, cache, out = self.fixture(pattern)
                    original = target.read_bytes()
                    self.closed(self.invoke(engine, target, cache, out), out)
                    self.assertEqual(target.read_bytes(), original)
                    self.assertFalse((out / "trades.csv").exists())

    def test_future_close_cannot_form_opening_orders(self):
        for engine in self.engines:
            for close in (50.0, 200.0):
                with self.subTest(engine=engine.__name__, future_close=close):
                    target, cache, out = self.fixture(future_close=close)
                    self.closed(self.invoke(engine, target, cache, out), out)

    def test_opening_admission_precedes_prices_equity_and_orders(self):
        for engine in self.engines:
            with self.subTest(engine=engine.__name__):
                target, cache, out = self.fixture()
                with patch.object(engine, "load_price_series", side_effect=AssertionError("price read")), \
                     patch.object(engine, "account_equity", side_effect=AssertionError("fill-day equity")), \
                     patch.object(engine, "execute_order", side_effect=AssertionError("opening quantity")):
                    self.closed(self.invoke(engine, target, cache, out), out)

    def test_completed_to_blocked_clears_only_each_engine_owned_files(self):
        for engine in self.engines:
            own_extra = "policy_decisions.csv" if engine is policy else "risk_actions.csv"
            other_extra = "risk_actions.csv" if engine is policy else "policy_decisions.csv"
            for failure in ("opening", "empty", "overweight", "missing_prices"):
                with self.subTest(engine=engine.__name__, failure=failure):
                    target, cache, out = self.fixture()
                    self.assertEqual(self.invoke(engine, target, cache, out, "next_close")["status"], "completed")
                    originals = {name: (out / name).read_bytes() for name in (*self.shared_outputs, own_extra)}
                    nested = out / "archive"
                    nested.mkdir()
                    for name, value in originals.items():
                        (nested / name).write_bytes(value)
                    (out / "caller.txt").write_bytes(b"caller")
                    (out / other_extra).write_bytes(b"other-engine-caller-owned")
                    self.fail_input(failure, target, cache)
                    input_bytes = target.read_bytes()
                    mode = "next_open" if failure == "opening" else "next_close"
                    self.closed(self.invoke(engine, target, cache, out, mode), out)
                    for name in originals:
                        if name not in {"metrics.json", "replay_report.md"}:
                            self.assertFalse((out / name).exists(), name)
                        self.assertEqual((nested / name).read_bytes(), originals[name])
                    self.assertEqual(target.read_bytes(), input_bytes)
                    self.assertEqual((out / "caller.txt").read_bytes(), b"caller")
                    self.assertEqual((out / other_extra).read_bytes(), b"other-engine-caller-owned")

    def test_cli_completion_and_all_blocked_statuses(self):
        for engine in self.engines:
            for case in ("complete", "opening", "empty", "overweight", "missing_prices"):
                with self.subTest(engine=engine.__name__, case=case):
                    target, cache, out = self.fixture()
                    self.fail_input(case, target, cache)
                    mode = "next_open" if case == "opening" else "next_close"
                    args = ["native", "--target-book", str(target), "--price-cache", str(cache),
                            "--output-dir", str(out), "--fill-mode", mode, "--cost-bps", "0"]
                    with patch.object(sys, "argv", args), redirect_stdout(io.StringIO()):
                        code = engine.main()
                    self.assertEqual(code, 0 if case == "complete" else 2)
                    payload = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
                    if case != "complete":
                        self.closed(payload, out)

    def test_blocked_metric_boundary_publishes_no_account_exports(self):
        for engine in self.engines:
            for status in ("blocked", "unknown", "failed", None):
                with self.subTest(engine=engine.__name__, metric_status=status):
                    target, cache, out = self.fixture()
                    value = {"status": status}
                    if status == "blocked":
                        value["reason"] = "unusable synthetic metric boundary"
                    with patch.object(engine, "calc_metrics", return_value=value):
                        self.closed(self.invoke(engine, target, cache, out, "next_close"), out)
                    self.assertFalse((out / "account_state_latest.json").exists())
                    self.assertFalse((out / "equity_curve.csv").exists())

    def test_completed_fill_mode_metadata_remains_truthful(self):
        for engine in self.engines:
            suffix = "execution_policy" if engine is policy else "position_risk"
            for mode in ("next_close", "same_close"):
                with self.subTest(engine=engine.__name__, mode=mode):
                    target, cache, out = self.fixture("missing")
                    result = self.invoke(engine, target, cache, out, mode)
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(result["fill_mode"], mode)
                    self.assertEqual(result["metric_mode"], f"broker_ledger_{suffix}_{mode}")
                    trades = pd.read_csv(out / "trades.csv")
                    self.assertTrue(trades["fill_mode"].eq(mode).all())

    def test_opening_preserves_target_even_if_it_has_an_export_name(self):
        for engine in self.engines:
            extra = "policy_decisions.csv" if engine is policy else "risk_actions.csv"
            for name in (*self.shared_outputs, extra):
                with self.subTest(engine=engine.__name__, input_name=name):
                    target, cache, out = self.fixture()
                    out.mkdir()
                    protected = out / name
                    protected.write_bytes(target.read_bytes())
                    original = protected.read_bytes()
                    result = self.invoke(engine, protected, cache, out)
                    self.assertEqual(result.get("status"), "blocked")
                    self.assertEqual(result.get("metric_mode"), "DO_NOT_USE")
                    self.assertIsNone(result.get("cagr"))
                    self.assertEqual(protected.read_bytes(), original)

    def test_next_close_target_exit_path_is_preserved(self):
        for engine in self.engines:
            with self.subTest(engine=engine.__name__):
                target, cache, out = self.fixture()
                frame = pd.read_csv(target)
                frame.loc[1, "ticker"] = "BBB"
                frame.loc[1, "weight"] = 1.0
                frame.to_csv(target, index=False)
                (cache / px_cache_name("BBB")).write_bytes((cache / px_cache_name("AAA")).read_bytes())
                options = {"min_holding_days": 0} if engine is policy else {}
                result = self.invoke(engine, target, cache, out, "next_close", **options)
                self.assertEqual(result["status"], "completed")
                trades = pd.read_csv(out / "trades.csv")
                self.assertIn("SELL", trades["side"].tolist())
                self.assertTrue(trades["fill_mode"].eq("next_close").all())

    def test_unknown_mode_and_unavailable_report_values(self):
        for engine in self.engines:
            with self.subTest(engine=engine.__name__):
                target, cache, out = self.fixture()
                self.closed(self.invoke(engine, target, cache, out, "unknown"), out)
                for value in (None, False, float("nan"), float("inf"), "invalid"):
                    self.assertEqual(engine.display_metric(value, ".2%"), "N/A")
                self.assertEqual(engine.display_metric(0.0, ".2%"), "0.00%")


if __name__ == "__main__":
    code = main()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OpeningConsumerContract)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(code if result.wasSuccessful() else 1)
