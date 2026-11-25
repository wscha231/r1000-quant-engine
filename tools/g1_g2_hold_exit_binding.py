"""Narrow G1/G2 hold-exit binding prepared from PR #582 + PR #581.

This module adds no hold/exit formula and no broker/evaluator behavior.  It
keeps LEGACY as the default and only loads the G2 module when the StrategySpec
selects the exact G2 hold_exit module ID.  G2 is a post-Control treatment
layer: current G1 builds the Control target book first, then the existing G2
``build_leadership_persistence_book`` may transform that target before any
broker replay.
"""
from __future__ import annotations

from dataclasses import replace
import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from tools import legacy_control_adapter as g1


BINDING_SCHEMA_VERSION = "g1-g2-hold-exit-binding-v1"
G2_HOLD_EXIT_MODULE_ID = "run287_hold_exit_replacement_policy"
G2_PARAMETER_KEYS = (
    "hold_exit_module_version",
    "hold_exit_policy_id",
    "hold_exit_policy_config",
    "hold_exit_policy_identity",
)


def _load_g2() -> Any:
    return importlib.import_module("tools.run287_hold_exit_policy")


def _legacy_shadow(spec: g1.StrategySpec) -> g1.StrategySpec:
    return replace(
        spec,
        hold_exit_module=g1.LEGACY_MODULE_ID,
        parameters=(),
    )


def _parameter_map(spec: g1.StrategySpec) -> dict[str, Any]:
    if not isinstance(spec.parameters, tuple):
        raise ValueError("hold_exit parameters must be an immutable tuple")
    out: dict[str, Any] = {}
    for item in spec.parameters:
        if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str):
            raise ValueError("invalid hold_exit parameter entry")
        key, value = item
        if key in out:
            raise ValueError(f"duplicate hold_exit parameter:{key}")
        out[key] = value
    if set(out) != set(G2_PARAMETER_KEYS):
        missing = sorted(set(G2_PARAMETER_KEYS) - set(out))
        unknown = sorted(set(out) - set(G2_PARAMETER_KEYS))
        raise ValueError(
            "invalid G2 hold_exit parameter set:missing="
            + ",".join(missing)
            + ";unknown="
            + ",".join(unknown)
        )
    return out


def _resolve_g2_policy(spec: g1.StrategySpec) -> tuple[Any, Any]:
    if spec.hold_exit_module != G2_HOLD_EXIT_MODULE_ID:
        raise ValueError(f"unknown hold_exit_module:{spec.hold_exit_module!r}")

    # Reuse G1 validation for every non-hold module and all base identities.
    g1.validate_strategy_spec(_legacy_shadow(spec))
    params = _parameter_map(spec)
    g2 = _load_g2()

    if g2.MODULE_ID != G2_HOLD_EXIT_MODULE_ID:
        raise ValueError("G2 module ID drift")
    if str(params["hold_exit_module_version"]) != str(g2.MODULE_VERSION):
        raise ValueError("unsupported G2 hold_exit module version")
    if params["hold_exit_policy_id"] != g2.POLICY_ID:
        raise ValueError("unsupported G2 hold_exit policy_id")

    supplied_config = params["hold_exit_policy_config"]
    supplied_identity = params["hold_exit_policy_identity"]
    if not isinstance(supplied_config, str) or not supplied_config:
        raise ValueError("missing G2 policy config identity")
    if not isinstance(supplied_identity, str) or not supplied_identity:
        raise ValueError("missing G2 policy audit identity")
    try:
        payload = json.loads(supplied_config)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid G2 policy config JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("parameters"), dict):
        raise ValueError("invalid G2 policy config shape")
    if "minimum_score_gap" not in payload["parameters"]:
        raise ValueError("missing G2 minimum_score_gap")

    # The only admitted candidate axis is the existing G2 minimum_score_gap
    # helper.  Re-serialization must match exactly, so changing cost, RS/risk,
    # incumbent protection, or any other G2 parameter fails closed.
    policy = g2.minimum_score_gap_candidate(
        minimum_score_gap=payload["parameters"]["minimum_score_gap"]
    )
    expected_config = g2.serialize_policy_config(policy)
    if supplied_config != expected_config:
        raise ValueError("G2 policy config is not the bounded minimum_score_gap candidate")
    expected_identity = g2.policy_audit_identity(policy)
    if supplied_identity != expected_identity:
        raise ValueError("invalid G2 policy config identity")
    return g2, policy


def make_g2_parameters(*, minimum_score_gap: float | None = None) -> tuple[tuple[str, Any], ...]:
    """Build the exact existing G2 module/config identity for a StrategySpec."""

    g2 = _load_g2()
    if g2.MODULE_ID != G2_HOLD_EXIT_MODULE_ID:
        raise ValueError("G2 module ID drift")
    policy = g2.minimum_score_gap_candidate(minimum_score_gap=minimum_score_gap)
    return (
        ("hold_exit_module_version", g2.MODULE_VERSION),
        ("hold_exit_policy_id", g2.POLICY_ID),
        ("hold_exit_policy_config", g2.serialize_policy_config(policy)),
        ("hold_exit_policy_identity", g2.policy_audit_identity(policy)),
    )


def validate_strategy_spec(spec: g1.StrategySpec) -> None:
    """Validate LEGACY exactly or the one admitted G2 post-Control overlay."""

    if spec.hold_exit_module == g1.LEGACY_MODULE_ID:
        # Critical invariant: the LEGACY path never imports/calls G2.
        g1.validate_strategy_spec(spec)
        return
    if spec.hold_exit_module != G2_HOLD_EXIT_MODULE_ID:
        raise ValueError(f"unknown hold_exit_module:{spec.hold_exit_module!r}")
    _resolve_g2_policy(spec)


def build_control_variant_book(
    spec: g1.StrategySpec,
    *,
    candidate: pd.DataFrame,
    crisis_states: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build the unchanged G1 Control book before any optional G2 treatment."""

    if spec.hold_exit_module == g1.LEGACY_MODULE_ID:
        # Exact direct delegate: no G2 load, no spec rewrite.
        return g1.build_variant_book(
            spec,
            candidate=candidate,
            crisis_states=crisis_states,
            prices=prices,
        )
    validate_strategy_spec(spec)
    return g1.build_variant_book(
        _legacy_shadow(spec),
        candidate=candidate,
        crisis_states=crisis_states,
        prices=prices,
    )


def assign_weights(
    spec: g1.StrategySpec,
    *,
    selected: list[dict[str, Any]],
    cash_target: float,
) -> list[dict[str, Any]]:
    """Keep allocation on the existing G1/Control implementation."""

    if spec.hold_exit_module == g1.LEGACY_MODULE_ID:
        return g1.assign_weights(spec, selected=selected, cash_target=cash_target)
    validate_strategy_spec(spec)
    return g1.assign_weights(
        _legacy_shadow(spec), selected=selected, cash_target=cash_target
    )


def apply_hold_exit_module(
    spec: g1.StrategySpec,
    control_target_book: pd.DataFrame,
    *,
    scored_candidate_cache_path: str | Path | None = None,
    lifecycle_path: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Apply the selected post-Control hold/exit treatment before broker replay.

    LEGACY returns the exact supplied target-book object and never loads G2.
    G2 requires explicit PIT scored-cache and lifecycle identities, loads the
    cache through the existing G2 loader, then delegates exactly to the existing
    G2 ``build_leadership_persistence_book``.
    """

    if not isinstance(control_target_book, pd.DataFrame):
        raise TypeError("control_target_book must be a DataFrame")
    if spec.hold_exit_module == g1.LEGACY_MODULE_ID:
        g1.validate_strategy_spec(spec)
        return (
            control_target_book,
            pd.DataFrame(),
            pd.DataFrame(),
            {
                "schema_version": BINDING_SCHEMA_VERSION,
                "hold_exit_module": g1.LEGACY_MODULE_ID,
                "status": "LEGACY_BYPASS",
                "g2_called": False,
            },
        )

    g2, policy = _resolve_g2_policy(spec)
    if scored_candidate_cache_path is None:
        raise ValueError("missing G2 PIT scored-candidate cache identity")
    if lifecycle_path is None:
        raise ValueError("missing G2 lifecycle identity")
    cache_path = Path(scored_candidate_cache_path)
    lifecycle = Path(lifecycle_path)
    if not cache_path.is_file():
        raise FileNotFoundError(cache_path)
    if not lifecycle.is_file():
        raise FileNotFoundError(lifecycle)

    scored = g2.load_scored_candidate_cache(cache_path)
    # Reuse G1's input-isolation primitive; do not add another mutation model.
    control_input = g1._isolated_frame(control_target_book)
    scored_input = g1._isolated_frame(scored)
    return g2.build_leadership_persistence_book(
        control_input,
        scored_input,
        portfolio=spec.portfolio_kind,
        lifecycle_path=lifecycle,
        policy=policy,
    )


def broker_specs_after_treatment(
    main_spec: g1.StrategySpec,
    concentrated_spec: g1.StrategySpec,
) -> tuple[g1.StrategySpec, g1.StrategySpec]:
    """Return G1-acceptable specs after treatment books are materialized.

    This performs no broker call and no file write.  A future R0 integration
    must first bind/materialize the returned treatment target books, then call
    the existing G1 ``run_broker_replays`` with these shadow specs.
    """

    validate_strategy_spec(main_spec)
    validate_strategy_spec(concentrated_spec)
    return (
        main_spec if main_spec.hold_exit_module == g1.LEGACY_MODULE_ID else _legacy_shadow(main_spec),
        concentrated_spec
        if concentrated_spec.hold_exit_module == g1.LEGACY_MODULE_ID
        else _legacy_shadow(concentrated_spec),
    )


def run_control(
    main_spec: g1.StrategySpec,
    concentrated_spec: g1.StrategySpec,
    evaluation: g1.EvaluationSpec,
    *,
    args: Any,
) -> dict[str, Any]:
    """Exact G1 delegate for the all-LEGACY Control arm only."""

    if (
        main_spec.hold_exit_module != g1.LEGACY_MODULE_ID
        or concentrated_spec.hold_exit_module != g1.LEGACY_MODULE_ID
    ):
        raise ValueError(
            "G2 is post-Control/pre-broker treatment; full run_control G2 routing is not admitted"
        )
    # No G2 validation or load on the all-LEGACY arm.
    return g1.run_control(main_spec, concentrated_spec, evaluation, args=args)


def run_broker_replays(
    main_spec: g1.StrategySpec,
    concentrated_spec: g1.StrategySpec,
    evaluation: g1.EvaluationSpec,
    *,
    latest_run: str | Path,
) -> dict[str, Any]:
    """Exact G1 broker delegate for LEGACY books only.

    G2 candidate books must first be materialized by the future R0 wiring; this
    preparation deliberately refuses to infer that state from a path/boolean.
    """

    if (
        main_spec.hold_exit_module != g1.LEGACY_MODULE_ID
        or concentrated_spec.hold_exit_module != g1.LEGACY_MODULE_ID
    ):
        raise ValueError(
            "G2 treatment-book materialization is required before broker replay"
        )
    return g1.run_broker_replays(
        main_spec,
        concentrated_spec,
        evaluation,
        latest_run=latest_run,
    )
