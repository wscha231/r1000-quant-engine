"""Repository-native G1 validation for the all-LEGACY adapter.

This file is validation-only.  It does not change strategy or broker behavior.
It executes the original G1 smoke in normal and optimized Python, rejects native
SKIPs, and compares the real existing broker replay caller against the adapter
on explicit synthetic target/price fixtures.
"""
from __future__ import annotations

from argparse import Namespace
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.legacy_control_adapter as adapter
import tools.run_alphaops_vnext_policy_replay as native
from tools.run_weekly_evaluation import px_cache_name


SUMMARY: dict[str, object] = {}


def strategy_spec(portfolio_kind: str) -> adapter.StrategySpec:
    return adapter.StrategySpec(
        portfolio_kind=portfolio_kind,
        target_n=15 if portfolio_kind == "main" else 5,
        candidate_source_ref="fixture:candidate-v1",
        regime_crisis_ref=("fixture:crisis-features-v1", "fixture:crisis-thresholds-v1"),
        discovery_module="LEGACY",
        entry_module="LEGACY",
        hold_exit_module="LEGACY",
        regime_module="LEGACY",
        allocation_module="LEGACY",
        version=adapter.LEGACY_STRATEGY_VERSION,
        parameters=(),
    )


def evaluation_spec(price_cache: Path) -> adapter.EvaluationSpec:
    return adapter.EvaluationSpec(
        universe_data_ref="fixture:universe-v1",
        calendar_ref="NYSE",
        price_cache_ref=str(price_cache),
        execution_mode="next_close",
        cost_bps=25.0,
        integer_shares=True,
        max_fill_lag_days=7,
        accounting_evaluator_ref="tools.run_broker_ledger_replay.replay",
        evaluation_window=(None, None),
        initial_capital=100000.0,
    )


def write_books(root: Path, *, missing_only: bool = False) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    if missing_only:
        main = pd.DataFrame(
            [{"rebalance_date": "2026-01-05", "ticker": "MISSING_MAIN", "weight": 0.90}]
        )
        concentrated = pd.DataFrame(
            [{"rebalance_date": "2026-01-05", "ticker": "MISSING_CONC", "weight": 0.90}]
        )
    else:
        main = pd.DataFrame(
            [
                {"rebalance_date": "2026-01-05", "ticker": "MAAA", "weight": 0.55},
                {"rebalance_date": "2026-01-05", "ticker": "MBBB", "weight": 0.35},
                {"rebalance_date": "2026-01-07", "ticker": "MAAA", "weight": 0.20},
                {"rebalance_date": "2026-01-07", "ticker": "MCCC", "weight": 0.70},
                {"rebalance_date": "2026-01-09", "ticker": "MCCC", "weight": 0.30},
                {"rebalance_date": "2026-01-09", "ticker": "MDDD", "weight": 0.60},
            ]
        )
        concentrated = pd.DataFrame(
            [
                {"rebalance_date": "2026-01-05", "ticker": "CEEE", "weight": 0.50},
                {"rebalance_date": "2026-01-05", "ticker": "CFFF", "weight": 0.40},
                {"rebalance_date": "2026-01-07", "ticker": "CEEE", "weight": 0.20},
                {"rebalance_date": "2026-01-07", "ticker": "CGGG", "weight": 0.70},
                {"rebalance_date": "2026-01-09", "ticker": "CGGG", "weight": 0.30},
                {"rebalance_date": "2026-01-09", "ticker": "CHHH", "weight": 0.60},
            ]
        )
        main["target_stock_names"] = 15
        main["weighting_mode"] = "alphaops_vnext_score_power"
        concentrated["target_stock_names"] = 5
        concentrated["weighting_mode"] = "alphaops_vnext_score_power"
    main.to_csv(reports / "operating_main_target_book.csv", index=False)
    concentrated.to_csv(reports / "operating_concentrated_target_book.csv", index=False)


def write_price_cache(price_cache: Path) -> None:
    price_cache.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(
        [
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
            "2026-01-12",
            "2026-01-13",
            "2026-01-14",
        ]
    )
    tickers = ["MAAA", "MBBB", "MCCC", "MDDD", "CEEE", "CFFF", "CGGG", "CHHH"]
    for offset, ticker in enumerate(tickers):
        close = np.asarray([100, 101, 103, 102, 105, 107, 106, 109], dtype=float) + offset * 3.0
        frame = pd.DataFrame(
            {
                "Open": close - 0.25,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Adj Close": close,
                "Volume": np.full(len(dates), 1_000_000 + offset * 10_000, dtype=float),
            },
            index=dates,
        )
        frame.to_parquet(price_cache / px_cache_name(ticker))


def normalize_paths(value: object, *roots: Path) -> object:
    if isinstance(value, dict):
        return {
            key: normalize_paths(item, *roots)
            for key, item in value.items()
            if key not in {"generated_at_utc", "generated_at"}
        }
    if isinstance(value, list):
        return [normalize_paths(item, *roots) for item in value]
    if isinstance(value, str):
        text = value
        for root in roots:
            text = text.replace(str(root), "<LATEST_RUN>")
        return text
    return value


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_csv_exact(case: unittest.TestCase, left: Path, right: Path) -> None:
    case.assertTrue(left.is_file(), str(left))
    case.assertTrue(right.is_file(), str(right))
    left_frame = pd.read_csv(left)
    right_frame = pd.read_csv(right)
    assert_frame_equal(left_frame, right_frame, check_exact=True, check_dtype=True)


def run_direct(latest_run: Path, price_cache: Path) -> dict[str, object]:
    args = Namespace(price_cache=str(price_cache), cost_bps=25.0, max_fill_lag_days=7)
    return native.run_broker_replays(args, latest_run)


def run_adapter(latest_run: Path, price_cache: Path) -> dict[str, object]:
    return adapter.run_broker_replays(
        strategy_spec("main"),
        strategy_spec("concentrated"),
        evaluation_spec(price_cache),
        latest_run=latest_run,
    )


class BrokerFixtureParityTests(unittest.TestCase):
    def test_positive_real_broker_fixture_parity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g1-native-positive-") as raw:
            root = Path(raw)
            price_cache = root / "prices"
            direct_root = root / "direct"
            adapter_root = root / "adapter"
            write_price_cache(price_cache)
            write_books(direct_root)
            write_books(adapter_root)

            direct = run_direct(direct_root, price_cache)
            adapted = run_adapter(adapter_root, price_cache)

            self.assertEqual(
                normalize_paths(direct, direct_root, adapter_root),
                normalize_paths(adapted, direct_root, adapter_root),
            )

            portfolio_summary: dict[str, object] = {}
            for portfolio in ("main", "concentrated"):
                self.assertEqual(direct[portfolio].get("status"), "completed")
                self.assertEqual(adapted[portfolio].get("status"), "completed")
                direct_output = direct_root / "broker_replay" / portfolio
                adapter_output = adapter_root / "broker_replay" / portfolio

                for name in (
                    "trades.csv",
                    "holdings_daily.csv",
                    "cash_ledger.csv",
                    "equity_curve.csv",
                    "positions_latest.csv",
                ):
                    assert_csv_exact(self, direct_output / name, adapter_output / name)

                direct_account = read_json(direct_output / "account_state_latest.json")
                adapter_account = read_json(adapter_output / "account_state_latest.json")
                self.assertEqual(
                    normalize_paths(direct_account, direct_root, adapter_root),
                    normalize_paths(adapter_account, direct_root, adapter_root),
                )

                trades = pd.read_csv(direct_output / "trades.csv")
                equity = pd.read_csv(direct_output / "equity_curve.csv")
                cash = pd.read_csv(direct_output / "cash_ledger.csv")
                holdings = pd.read_csv(direct_output / "holdings_daily.csv")
                positions = pd.read_csv(direct_output / "positions_latest.csv")
                self.assertFalse(trades.empty)
                self.assertFalse(equity.empty)
                self.assertFalse(cash.empty)
                self.assertFalse(holdings.empty)
                self.assertFalse(positions.empty)
                self.assertIn("BUY", set(trades["side"].astype(str)))
                self.assertIn("SELL", set(trades["side"].astype(str)))
                fees = float(pd.to_numeric(trades["fee_usd"], errors="raise").sum())
                self.assertGreater(fees, 0.0)
                self.assertTrue(pd.to_numeric(trades["fill_price"], errors="raise").gt(0.0).all())
                self.assertTrue(pd.to_datetime(trades["date"], errors="raise").notna().all())
                account = direct_account
                self.assertGreater(float(account["equity_usd"]), 0.0)
                self.assertGreaterEqual(float(account["cash_usd"]), 0.0)
                self.assertEqual(account["fill_mode"], "next_close")
                self.assertEqual(float(account["cost_bps_per_side"]), 25.0)
                self.assertIs(account["integer_shares"], True)
                self.assertEqual(float(account["starting_capital_usd"]), 100000.0)
                portfolio_summary[portfolio] = {
                    "trades": int(len(trades)),
                    "buys": int((trades["side"] == "BUY").sum()),
                    "sells": int((trades["side"] == "SELL").sum()),
                    "fees_usd": fees,
                    "ending_equity_usd": float(account["equity_usd"]),
                    "ending_cash_usd": float(account["cash_usd"]),
                    "positions": int(account["position_count"]),
                }
            SUMMARY["positive"] = portfolio_summary

    def test_missing_price_fail_closed_parity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g1-native-negative-") as raw:
            root = Path(raw)
            price_cache = root / "prices"
            price_cache.mkdir(parents=True, exist_ok=True)
            direct_root = root / "direct"
            adapter_root = root / "adapter"
            write_books(direct_root, missing_only=True)
            write_books(adapter_root, missing_only=True)

            direct = run_direct(direct_root, price_cache)
            adapted = run_adapter(adapter_root, price_cache)
            self.assertEqual(
                normalize_paths(direct, direct_root, adapter_root),
                normalize_paths(adapted, direct_root, adapter_root),
            )
            negative: dict[str, object] = {}
            for portfolio in ("main", "concentrated"):
                self.assertEqual(direct[portfolio].get("status"), "blocked")
                self.assertEqual(
                    direct[portfolio].get("reason"), "target_fill_coverage_incomplete"
                )
                negative[portfolio] = {
                    "status": direct[portfolio].get("status"),
                    "reason": direct[portfolio].get("reason"),
                }
            SUMMARY["missing_price"] = negative


def run_suite() -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BrokerFixtureParityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def run_original_smoke(*, optimized: bool) -> dict[str, int]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.append(str(ROOT / "tests" / "legacy_control_adapter_smoke.py"))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env={
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(ROOT)
            + (
                os.pathsep + os.environ["PYTHONPATH"]
                if os.environ.get("PYTHONPATH")
                else ""
            ),
        },
    )
    output = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(
            f"original smoke {'optimized' if optimized else 'normal'} failed:\n"
            + "\n".join(output.splitlines()[-30:])
        )
    skipped_match = re.search(r"skipped=(\d+)", output)
    skipped = int(skipped_match.group(1)) if skipped_match else 0
    ran_match = re.search(r"Ran (\d+) tests?", output)
    ran = int(ran_match.group(1)) if ran_match else -1
    if skipped:
        raise RuntimeError(
            f"original smoke {'optimized' if optimized else 'normal'} skipped {skipped} native tests"
        )
    if ran <= 0:
        raise RuntimeError("original smoke test count was not observed")
    return {"ran": ran, "skipped": skipped}


def main() -> int:
    if os.environ.get("G1_NATIVE_OPTIMIZED_CHILD") == "1":
        ok = run_suite()
        print("G1_OPT_SUMMARY=" + json.dumps(SUMMARY, sort_keys=True))
        return 0 if ok else 1

    if not run_suite():
        return 1
    smoke_normal = run_original_smoke(optimized=False)
    smoke_optimized = run_original_smoke(optimized=True)

    env = {**os.environ, "G1_NATIVE_OPTIMIZED_CHILD": "1"}
    optimized = subprocess.run(
        [sys.executable, "-O", str(Path(__file__).resolve())],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env=env,
    )
    if optimized.returncode != 0:
        print("\n".join((optimized.stdout or "").splitlines()[-40:]))
        return optimized.returncode
    opt_line = next(
        (line for line in (optimized.stdout or "").splitlines() if line.startswith("G1_OPT_SUMMARY=")),
        "",
    )
    if not opt_line:
        print("optimized broker fixture summary missing")
        return 1
    optimized_summary = json.loads(opt_line.split("=", 1)[1])
    final = {
        "broker_fixture_normal": SUMMARY,
        "broker_fixture_optimized": optimized_summary,
        "original_smoke_normal": smoke_normal,
        "original_smoke_optimized": smoke_optimized,
    }
    print("G1_NATIVE_VALIDATION_SUMMARY=" + json.dumps(final, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
