"""G1 all-LEGACY routing/parity smoke tests.

The test uses unittest assertions so validation remains active under ``python -O``.
Native parity tests use the current repository Control when importable; contract
and fail-closed tests do not need native IO or data collection.
"""
from __future__ import annotations

from argparse import Namespace
import ast
from copy import deepcopy
from dataclasses import replace
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import tools.legacy_control_adapter as adapter


BASE_SHA = "6a2fa606896a2f263fffa07b9273d60f2d011626"


def strategy_spec(portfolio_kind: str = "main") -> adapter.StrategySpec:
    return adapter.StrategySpec(
        portfolio_kind=portfolio_kind,
        target_n=15 if portfolio_kind == "main" else 5,
        candidate_source_ref="fixture:candidate-v1",
        regime_crisis_ref=(
            "fixture:long-crisis-features-v1",
            "fixture:long-crisis-thresholds-v1",
        ),
        discovery_module="LEGACY",
        entry_module="LEGACY",
        hold_exit_module="LEGACY",
        regime_module="LEGACY",
        allocation_module="LEGACY",
        version=adapter.LEGACY_STRATEGY_VERSION,
        parameters=(),
    )


def evaluation_spec(price_cache_ref: str = "fixture:price-cache-v1") -> adapter.EvaluationSpec:
    return adapter.EvaluationSpec(
        universe_data_ref="fixture:universe-data-v1",
        calendar_ref="fixture:calendar-v1",
        price_cache_ref=price_cache_ref,
        execution_mode="next_close",
        cost_bps=25.0,
        integer_shares=True,
        max_fill_lag_days=7,
        accounting_evaluator_ref="tools.run_broker_ledger_replay.replay",
        evaluation_window=(None, None),
        initial_capital=100000.0,
    )


def synthetic_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    rows: list[dict] = []
    tickers = [f"SYN{i:02d}" for i in range(20)]
    for date in pd.to_datetime(["2026-01-30", "2026-02-27"]):
        for rank, ticker in enumerate(tickers):
            rows.append(
                {
                    "rebalance_date": date,
                    "ticker": ticker,
                    "Name": ticker,
                    "sector": ("Technology", "Industrials", "Health Care", "Utilities")[rank % 4],
                    "industry_group": f"SyntheticGroup{rank % 8}",
                    "rs_spy_3m": 0.20 - rank * 0.001,
                    "rs_qqq_3m": 0.18 - rank * 0.001,
                    "rs_spy_6m": 0.30 - rank * 0.001,
                    "rs_qqq_6m": 0.28 - rank * 0.001,
                    "rs_benchmark_1w": 0.02,
                    "rs_benchmark_3m": 0.20 - rank * 0.001,
                    "rs_benchmark_6m": 0.30 - rank * 0.001,
                    "relative_strength_composite": 95.0 - rank * 0.1,
                    "industry_group_strength_score": 1.0,
                    "portfolio_future_winner_engine_score": 1.0 - rank * 0.01,
                    "theme_phase_multiplier_primary": 1.0,
                    "dollar_vol_20d": 50_000_000.0,
                    "market_cap_live": 10_000_000_000.0,
                    "data_confidence": 1.0,
                    "price_above_ma200": 1.0,
                    "price_above_ma50": 1.0,
                    "fcf_ttm": 1_000_000_000.0,
                    "fcf_margin": 0.15,
                    "forward_pe": 22.0,
                    "peg_ratio": 1.1,
                    "fcf_yield": 0.04,
                    "regime_state": "neutral",
                }
            )
    candidate = pd.DataFrame(rows)
    candidate.attrs = {"scope": "SYNTHETIC", "provider_verified": False}
    crisis = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-30", "2026-02-27"]),
            "crisis_state": ["GREEN", "GREEN"],
        }
    )
    dates = pd.bdate_range("2025-01-02", "2026-03-13")
    prices: dict[str, pd.DataFrame] = {}
    for ticker in [*tickers, "SPY", "QQQ", "SMH", "SOXX"]:
        close = np.linspace(100.0, 160.0, len(dates))
        prices[ticker] = pd.DataFrame(
            {"Open": close, "Close": close, "Adj Close": close}, index=dates
        )
    return candidate, crisis, prices


class LegacyAdapterContractTests(unittest.TestCase):
    def test_all_legacy_specs_validate_without_loading_native(self) -> None:
        with patch.object(adapter, "_load_native", side_effect=AssertionError("must not load")) as loader:
            adapter.validate_strategy_spec(strategy_spec("main"))
            adapter.validate_strategy_spec(strategy_spec("concentrated"))
            adapter.validate_evaluation_spec(evaluation_spec())
        loader.assert_not_called()

    def test_unknown_modules_fail_closed(self) -> None:
        cases = {
            "discovery_module": "NEW_DISCOVERY",
            "entry_module": "NEW_ENTRY",
            "hold_exit_module": "NEW_HOLD_EXIT",
            "regime_module": "NEW_REGIME",
            "allocation_module": "NEW_ALLOCATION",
        }
        base = strategy_spec()
        for field_name, value in cases.items():
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    adapter.validate_strategy_spec(replace(base, **{field_name: value}))

    def test_unsupported_version_and_parameters_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported strategy version"):
            adapter.validate_strategy_spec(replace(strategy_spec(), version="v2"))
        with self.assertRaisesRegex(ValueError, "unexpected legacy strategy parameters"):
            adapter.validate_strategy_spec(
                replace(strategy_spec(), parameters=(("threshold", 0.0),))
            )

    def test_missing_execution_or_cost_identity_fails_closed(self) -> None:
        base = evaluation_spec()
        for changed in (
            {"execution_mode": ""},
            {"cost_bps": None},
            {"accounting_evaluator_ref": ""},
            {"price_cache_ref": ""},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    adapter.validate_evaluation_spec(replace(base, **changed))

    def test_native_only_capital_and_full_window_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "starting capital"):
            adapter.validate_evaluation_spec(
                replace(evaluation_spec(), initial_capital=250000.0)
            )
        with self.assertRaisesRegex(ValueError, "evaluation-window"):
            adapter.validate_evaluation_spec(
                replace(evaluation_spec(), evaluation_window=("2024-01-01", None))
            )

    def test_adapter_protects_supplied_inputs_from_mutating_native(self) -> None:
        candidate = pd.DataFrame(
            {"ticker": ["A"], "payload": [{"nested": [1]}], "value": [0.0]}
        )
        candidate.attrs = {"source": {"available_at": None}}
        crisis = pd.DataFrame({"date": ["2026-01-30"], "crisis_state": ["GREEN"]})
        prices = {"A": pd.DataFrame({"Close": [10.0]})}
        before_candidate = deepcopy(candidate.to_dict("records"))
        before_attrs = deepcopy(candidate.attrs)
        before_crisis = crisis.copy(deep=True)
        before_prices = prices["A"].copy(deep=True)

        class Native:
            @staticmethod
            def build_variant_book(c, *, portfolio_kind, target_n, crisis_states, prices):
                c.at[0, "payload"]["nested"].append(99)
                c.attrs["source"]["available_at"] = "invented"
                crisis_states.at[0, "crisis_state"] = "RED"
                prices["A"].iloc[0, 0] = 999.0
                return (pd.DataFrame({"ticker": ["A"]}), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

        with patch.object(adapter, "_load_native", return_value=Native):
            adapter.build_variant_book(
                strategy_spec(), candidate=candidate, crisis_states=crisis, prices=prices
            )
        self.assertEqual(candidate.to_dict("records"), before_candidate)
        self.assertEqual(candidate.attrs, before_attrs)
        assert_frame_equal(crisis, before_crisis, check_exact=True)
        assert_frame_equal(prices["A"], before_prices, check_exact=True)

    def test_validation_source_contains_no_io_or_network_writer(self) -> None:
        source = Path(adapter.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_import_roots = {"requests", "urllib", "socket", "http", "subprocess"}
        forbidden_calls = {
            "write_text",
            "write_bytes",
            "to_csv",
            "to_parquet",
            "mkdir",
            "unlink",
            "rename",
            "replace",
        }
        imports: set[str] = set()
        called_attrs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called_attrs.add(node.func.attr)
        self.assertTrue(imports.isdisjoint(forbidden_import_roots), imports)
        self.assertTrue(called_attrs.isdisjoint(forbidden_calls), called_attrs)

    def test_feature_env_is_not_overridden(self) -> None:
        seen: list[tuple[str | None, str | None]] = []

        class Native:
            @staticmethod
            def assign_weights(selected, portfolio_kind, cash_target):
                seen.append(
                    (os.environ.get("PHASE_LEADERSHIP_PERSISTENCE_HOLD_ENABLED"), os.environ.get("R1000_CONC_SCORE_SIZING_SIGNAL"))
                )
                return selected

        selected = [{"ticker": "A", "weight": 1.0}]
        with patch.dict(
            os.environ,
            {
                "PHASE_LEADERSHIP_PERSISTENCE_HOLD_ENABLED": "custom-phase-value",
                "R1000_CONC_SCORE_SIZING_SIGNAL": "custom-signal-value",
            },
            clear=False,
        ):
            before = dict(os.environ)
            with patch.object(adapter, "_load_native", return_value=Native):
                result = adapter.assign_weights(
                    strategy_spec(), selected=selected, cash_target=0.0
                )
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(
            seen,
            [("custom-phase-value", "custom-signal-value")],
        )
        self.assertEqual(result, selected)

    def test_full_control_runner_is_exact_delegate_without_rewriting_args(self) -> None:
        payload = {"status": "fixture", "marker": object()}
        calls: list[Namespace] = []

        class Native:
            @staticmethod
            def build(args):
                calls.append(args)
                return payload

        args = Namespace(
            latest_run="fixture:latest-run",
            candidate_book="fixture:candidate-v1",
            price_cache="fixture:price-cache-v1",
            output_dir="fixture:output",
            portfolio_kind="both",
            main_target_n=15,
            concentrated_target_n=5,
            production_output_mode="shadow_only",
            skip_broker_replay=True,
            run_current_report=False,
            cost_bps=25.0,
            max_fill_lag_days=7,
            long_crisis_features="fixture:long-crisis-features-v1",
            long_crisis_thresholds="fixture:long-crisis-thresholds-v1",
        )
        with patch.object(adapter, "_load_native", return_value=Native):
            result = adapter.run_control(
                strategy_spec("main"),
                strategy_spec("concentrated"),
                evaluation_spec(),
                args=args,
            )
        self.assertIs(result, payload)
        self.assertEqual(calls, [args])
        self.assertIs(calls[0], args)

    def test_full_control_runner_rejects_identity_mismatch(self) -> None:
        args = Namespace(
            candidate_book="fixture:wrong-candidate",
            price_cache="fixture:price-cache-v1",
            portfolio_kind="both",
            main_target_n=15,
            concentrated_target_n=5,
            cost_bps=25.0,
            max_fill_lag_days=7,
            long_crisis_features="fixture:long-crisis-features-v1",
            long_crisis_thresholds="fixture:long-crisis-thresholds-v1",
        )
        with self.assertRaisesRegex(ValueError, "candidate source"):
            adapter.run_control(
                strategy_spec("main"),
                strategy_spec("concentrated"),
                evaluation_spec(),
                args=args,
            )

    def test_broker_binding_passes_only_existing_native_inputs(self) -> None:
        calls: list[tuple[Namespace, Path]] = []

        class Native:
            @staticmethod
            def run_broker_replays(args, latest_run):
                calls.append((args, latest_run))
                return {"main": {"status": "blocked"}, "concentrated": {"status": "blocked"}}

        with patch.object(adapter, "_load_native", return_value=Native):
            result = adapter.run_broker_replays(
                strategy_spec("main"),
                strategy_spec("concentrated"),
                evaluation_spec("/tmp/example-price-cache"),
                latest_run="/tmp/example-latest-run",
            )
        self.assertEqual(result["main"]["status"], "blocked")
        self.assertEqual(len(calls), 1)
        args, latest = calls[0]
        self.assertEqual(args.price_cache, "/tmp/example-price-cache")
        self.assertEqual(args.cost_bps, 25.0)
        self.assertEqual(args.max_fill_lag_days, 7)
        self.assertEqual(latest, Path("/tmp/example-latest-run"))
        self.assertEqual(set(vars(args)), {"price_cache", "cost_bps", "max_fill_lag_days"})


class NativeLegacyParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.native = importlib.import_module("tools.run_alphaops_vnext_policy_replay")
            cls.native_error = None
        except Exception as exc:  # local prepared slice may not have the full repo dependency graph
            cls.native = None
            cls.native_error = f"{type(exc).__name__}:{exc}"

    def require_native(self) -> None:
        if self.native is None:
            self.skipTest(f"native Control import unavailable:{self.native_error}")

    def test_direct_build_variant_book_equals_all_legacy_adapter(self) -> None:
        self.require_native()
        phase_keys = [
            key for key in os.environ if key.startswith("PHASE_") or key.startswith("R1000_")
        ]
        saved = {key: os.environ.get(key) for key in phase_keys}
        for key in phase_keys:
            os.environ[key] = ""
        try:
            for kind in ("main", "concentrated"):
                with self.subTest(portfolio_kind=kind):
                    spec = strategy_spec(kind)
                    candidate, crisis, prices = synthetic_inputs()
                    direct = self.native.build_variant_book(
                        candidate.copy(deep=True),
                        portfolio_kind=kind,
                        target_n=spec.target_n,
                        crisis_states=crisis.copy(deep=True),
                        prices={key: value.copy(deep=True) for key, value in prices.items()},
                    )
                    adapted = adapter.build_variant_book(
                        spec,
                        candidate=candidate,
                        crisis_states=crisis,
                        prices=prices,
                    )
                    self.assertFalse(direct[0].empty, "parity must not be vacuous")
                    for expected, actual in zip(direct, adapted):
                        assert_frame_equal(expected, actual, check_exact=True)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_direct_allocation_equals_all_legacy_adapter(self) -> None:
        self.require_native()
        selected = [
            {
                "ticker": "AAA",
                "alphaops_vnext_score": 3.0,
                "sector": "Technology",
                "industry_group": "Software",
            },
            {
                "ticker": "BBB",
                "alphaops_vnext_score": 2.0,
                "sector": "Industrials",
                "industry_group": "Machinery",
            },
            {
                "ticker": "CCC",
                "alphaops_vnext_score": 1.0,
                "sector": "Health Care",
                "industry_group": "Biotech",
            },
        ]
        direct = self.native.assign_weights(deepcopy(selected), "main", 0.10)
        adapted = adapter.assign_weights(
            strategy_spec("main"), selected=selected, cash_target=0.10
        )
        self.assertEqual(direct, adapted)
        self.assertEqual(selected[0].get("weight"), None)

    def test_existing_broker_caller_direct_and_adapter_bind_identically(self) -> None:
        self.require_native()
        payload = {
            "status": "fixture",
            "orders": [{"ticker": "AAA", "side": "BUY", "quantity": 7.0}],
            "fills": [{"ticker": "AAA", "date": "2026-01-30", "price": 101.25}],
            "cash_usd": 29288.75,
            "total_fees_usd": 17.72,
            "nav": 100123.45,
            "account_state": {"equity_usd": 100123.45, "cash_usd": 29288.75},
            "reason_codes": ["fixture_reason"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            direct_root = root / "direct"
            adapter_root = root / "adapter"
            direct_root.mkdir()
            adapter_root.mkdir()
            price_cache = root / "prices"
            evaluation = evaluation_spec(str(price_cache))
            direct_args = Namespace(
                price_cache=str(price_cache), cost_bps=25.0, max_fill_lag_days=7
            )
            direct_calls: list[dict] = []
            adapter_calls: list[dict] = []

            def direct_replay(**kwargs):
                direct_calls.append(dict(kwargs))
                return deepcopy(payload)

            def adapted_replay(**kwargs):
                adapter_calls.append(dict(kwargs))
                return deepcopy(payload)

            with patch.object(self.native, "broker_replay", side_effect=direct_replay):
                direct = self.native.run_broker_replays(direct_args, direct_root)
            with patch.object(self.native, "broker_replay", side_effect=adapted_replay):
                wrapped = adapter.run_broker_replays(
                    strategy_spec("main"),
                    strategy_spec("concentrated"),
                    evaluation,
                    latest_run=adapter_root,
                )
            self.assertEqual(direct, wrapped)
            self.assertEqual(len(direct_calls), 2)
            self.assertEqual(len(adapter_calls), 2)
            for direct_call, adapted_call in zip(direct_calls, adapter_calls):
                for key in (
                    "portfolio_kind",
                    "fill_mode",
                    "cost_bps",
                    "integer_shares",
                    "max_fill_lag_days",
                    "concentrated_champion_filters",
                ):
                    self.assertEqual(direct_call[key], adapted_call[key])
                self.assertEqual(direct_call["price_cache"], adapted_call["price_cache"])
                self.assertEqual(direct_call["target_book"].name, adapted_call["target_book"].name)
                self.assertEqual(direct_call["output_dir"].name, adapted_call["output_dir"].name)
            self.assertEqual(list(direct_root.iterdir()), [])
            self.assertEqual(list(adapter_root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
