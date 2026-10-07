"""Thin all-LEGACY routing boundary for the existing AlphaOps Control.

G1 is structural parity only.  This module does not implement scoring,
selection, hold/exit, regime, allocation, execution, accounting, or evaluation
logic.  It validates an explicit all-LEGACY recipe and delegates to the current
native Control functions lazily so import/validation alone does not start the
legacy pipeline or perform IO.
"""
from __future__ import annotations

from argparse import Namespace
from copy import deepcopy
from dataclasses import dataclass
import importlib
import math
from pathlib import Path
from typing import Any

import pandas as pd

LEGACY_MODULE_ID = "LEGACY"
LEGACY_STRATEGY_VERSION = "alphaops_vnext_production@legacy-v1"
LEGACY_ACCOUNTING_EVALUATOR_REF = "tools.run_broker_ledger_replay.replay"
LEGACY_EXECUTION_MODE = "next_close"
LEGACY_NATIVE_STARTING_CAPITAL = 100000.0
LEGACY_TARGET_N = {"main": 15, "concentrated": 5}
_NATIVE_CONTROL_MODULE = "tools.run_alphaops_vnext_policy_replay"


@dataclass(frozen=True)
class StrategySpec:
    """Immutable identity/routing metadata for one current Control portfolio."""

    portfolio_kind: str
    target_n: int
    candidate_source_ref: str
    regime_crisis_ref: tuple[str, str]
    discovery_module: str
    entry_module: str
    hold_exit_module: str
    regime_module: str
    allocation_module: str
    version: str
    parameters: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class EvaluationSpec:
    """Immutable identity for the existing broker-ledger evaluation path.

    The native AlphaOps ``run_broker_replays`` helper currently fixes starting
    capital at the broker replay default and does not accept an evaluation
    window argument.  G1 therefore fails closed on any value that would require
    adapter-side economic behavior instead of silently pretending it was used.
    """

    universe_data_ref: str
    calendar_ref: str
    price_cache_ref: str
    execution_mode: str
    cost_bps: float | None
    integer_shares: bool | None
    max_fill_lag_days: int | None
    accounting_evaluator_ref: str
    evaluation_window: tuple[str | None, str | None]
    initial_capital: float | None


def _nonempty_ref(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {name} identity")


def validate_strategy_spec(spec: StrategySpec) -> None:
    if not isinstance(spec, StrategySpec):
        raise TypeError("StrategySpec required")
    if spec.portfolio_kind not in LEGACY_TARGET_N:
        raise ValueError("unsupported portfolio_kind")
    expected_n = LEGACY_TARGET_N[spec.portfolio_kind]
    if type(spec.target_n) is not int or spec.target_n != expected_n:
        raise ValueError(
            f"legacy target_n mismatch:{spec.portfolio_kind}:{spec.target_n!r}"
        )
    _nonempty_ref("candidate_source_ref", spec.candidate_source_ref)
    if (
        not isinstance(spec.regime_crisis_ref, tuple)
        or len(spec.regime_crisis_ref) != 2
    ):
        raise ValueError("regime_crisis_ref must contain features and thresholds refs")
    _nonempty_ref("crisis_features_ref", spec.regime_crisis_ref[0])
    _nonempty_ref("crisis_thresholds_ref", spec.regime_crisis_ref[1])
    for field_name in (
        "discovery_module",
        "entry_module",
        "hold_exit_module",
        "regime_module",
        "allocation_module",
    ):
        if getattr(spec, field_name) != LEGACY_MODULE_ID:
            raise ValueError(f"unknown {field_name}:{getattr(spec, field_name)!r}")
    if spec.version != LEGACY_STRATEGY_VERSION:
        raise ValueError(f"unsupported strategy version:{spec.version!r}")
    if not isinstance(spec.parameters, tuple) or spec.parameters:
        raise ValueError("unexpected legacy strategy parameters")


def validate_evaluation_spec(spec: EvaluationSpec) -> None:
    if not isinstance(spec, EvaluationSpec):
        raise TypeError("EvaluationSpec required")
    _nonempty_ref("universe_data_ref", spec.universe_data_ref)
    _nonempty_ref("calendar_ref", spec.calendar_ref)
    _nonempty_ref("price_cache_ref", spec.price_cache_ref)
    if spec.execution_mode != LEGACY_EXECUTION_MODE:
        raise ValueError(f"unsupported execution_mode:{spec.execution_mode!r}")
    if spec.cost_bps is None or isinstance(spec.cost_bps, bool):
        raise ValueError("missing cost configuration")
    try:
        cost = float(spec.cost_bps)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid cost configuration") from exc
    if not math.isfinite(cost) or cost < 0.0:
        raise ValueError("invalid cost configuration")
    if spec.integer_shares is not True:
        raise ValueError("legacy broker replay requires integer_shares=true")
    if (
        type(spec.max_fill_lag_days) is not int
        or spec.max_fill_lag_days is None
        or spec.max_fill_lag_days < 0
    ):
        raise ValueError("missing or invalid max_fill_lag_days")
    if spec.accounting_evaluator_ref != LEGACY_ACCOUNTING_EVALUATOR_REF:
        raise ValueError("unsupported accounting/evaluator reference")
    if (
        not isinstance(spec.evaluation_window, tuple)
        or len(spec.evaluation_window) != 2
        or spec.evaluation_window != (None, None)
    ):
        raise ValueError(
            "native run_broker_replays has no evaluation-window input; only explicit full window is supported"
        )
    if spec.initial_capital is None or isinstance(spec.initial_capital, bool):
        raise ValueError("missing initial capital")
    try:
        capital = float(spec.initial_capital)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid initial capital") from exc
    if not math.isfinite(capital) or capital != LEGACY_NATIVE_STARTING_CAPITAL:
        raise ValueError(
            "native run_broker_replays fixes starting capital at 100000; adapter will not override it"
        )


def _load_native() -> Any:
    return importlib.import_module(_NATIVE_CONTROL_MODULE)


def _isolated_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("DataFrame input required")
    result = frame.copy(deep=True)
    for index, dtype in enumerate(frame.dtypes):
        if pd.api.types.is_object_dtype(dtype):
            result.isetitem(
                index,
                pd.Series(
                    [deepcopy(value) for value in frame.iloc[:, index]],
                    index=frame.index,
                    dtype=object,
                ),
            )
    result.attrs = deepcopy(frame.attrs)
    return result


def build_variant_book(
    spec: StrategySpec,
    *,
    candidate: pd.DataFrame,
    crisis_states: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Delegate one Main15/Concentrated5 target-book build to current Control."""

    validate_strategy_spec(spec)
    if not isinstance(prices, dict) or not all(
        isinstance(key, str) and isinstance(value, pd.DataFrame)
        for key, value in prices.items()
    ):
        raise TypeError("prices must be dict[str, DataFrame]")
    native = _load_native()
    return native.build_variant_book(
        _isolated_frame(candidate),
        portfolio_kind=spec.portfolio_kind,
        target_n=spec.target_n,
        crisis_states=_isolated_frame(crisis_states),
        prices={key: _isolated_frame(value) for key, value in prices.items()},
    )


def assign_weights(
    spec: StrategySpec,
    *,
    selected: list[dict[str, Any]],
    cash_target: float,
) -> list[dict[str, Any]]:
    """Delegate allocation exactly; no adapter-side sizing formula exists."""

    validate_strategy_spec(spec)
    if not isinstance(selected, list) or not all(isinstance(row, dict) for row in selected):
        raise TypeError("selected must be list[dict]")
    native = _load_native()
    return native.assign_weights(deepcopy(selected), spec.portfolio_kind, cash_target)



def run_control(
    main_spec: StrategySpec,
    concentrated_spec: StrategySpec,
    evaluation: EvaluationSpec,
    *,
    args: Namespace,
) -> dict[str, Any]:
    """Validate the all-LEGACY recipe and delegate the full existing runner.

    No argument is rewritten.  This is the authoritative G1 routing boundary
    for the first all-LEGACY recipe; the native ``build`` function retains all
    existing post-book overlays, artifact writes, and optional broker replay.
    """

    validate_strategy_spec(main_spec)
    validate_strategy_spec(concentrated_spec)
    validate_evaluation_spec(evaluation)
    if main_spec.portfolio_kind != "main" or concentrated_spec.portfolio_kind != "concentrated":
        raise ValueError("run_control requires Main15 and Concentrated5 legacy specs")
    required = (
        "candidate_book",
        "price_cache",
        "portfolio_kind",
        "main_target_n",
        "concentrated_target_n",
        "cost_bps",
        "max_fill_lag_days",
        "long_crisis_features",
        "long_crisis_thresholds",
    )
    missing = [name for name in required if not hasattr(args, name)]
    if missing:
        raise ValueError("missing native Control arguments:" + ",".join(missing))
    if args.portfolio_kind != "both":
        raise ValueError("first all-LEGACY recipe requires portfolio_kind=both")
    if args.main_target_n != main_spec.target_n or args.concentrated_target_n != concentrated_spec.target_n:
        raise ValueError("native target_n does not match all-LEGACY recipe")
    if not isinstance(args.candidate_book, str) or not args.candidate_book.strip():
        raise ValueError("explicit candidate source identity required")
    if args.candidate_book != main_spec.candidate_source_ref or args.candidate_book != concentrated_spec.candidate_source_ref:
        raise ValueError("native candidate source does not match all-LEGACY recipe")
    expected_crisis = (str(args.long_crisis_features), str(args.long_crisis_thresholds))
    if expected_crisis != main_spec.regime_crisis_ref or expected_crisis != concentrated_spec.regime_crisis_ref:
        raise ValueError("native crisis references do not match all-LEGACY recipe")
    if str(args.price_cache) != evaluation.price_cache_ref:
        raise ValueError("native price-cache reference does not match EvaluationSpec")
    if float(args.cost_bps) != float(evaluation.cost_bps):
        raise ValueError("native cost configuration does not match EvaluationSpec")
    if int(args.max_fill_lag_days) != evaluation.max_fill_lag_days:
        raise ValueError("native max-fill-lag does not match EvaluationSpec")
    native = _load_native()
    return native.build(args)

def run_broker_replays(
    main_spec: StrategySpec,
    concentrated_spec: StrategySpec,
    evaluation: EvaluationSpec,
    *,
    latest_run: str | Path,
) -> dict[str, Any]:
    """Delegate the existing two-book broker replay caller without new accounting."""

    validate_strategy_spec(main_spec)
    validate_strategy_spec(concentrated_spec)
    if main_spec.portfolio_kind != "main" or concentrated_spec.portfolio_kind != "concentrated":
        raise ValueError("run_broker_replays requires Main15 and Concentrated5 legacy specs")
    validate_evaluation_spec(evaluation)
    native = _load_native()
    args = Namespace(
        price_cache=evaluation.price_cache_ref,
        cost_bps=evaluation.cost_bps,
        max_fill_lag_days=evaluation.max_fill_lag_days,
    )
    return native.run_broker_replays(args, Path(latest_run))