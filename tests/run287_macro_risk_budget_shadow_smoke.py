#!/usr/bin/env python3
"""Smoke tests for the proposal-only Run287 macro risk-budget router."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_macro_risk_budget_shadow import (  # noqa: E402
    BLOCKED_STATUS,
    READY_STATUS,
    build,
)


CONTRACT = ROOT / "docs/run287_macro_risk_budget_shadow_contract.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def macro_row(*, stressed: bool = False) -> dict[str, object]:
    if stressed:
        return {
            "macro_risk_off_score": 2.0,
            "market_regime_score": -2.0,
            "liquidity_drain_score": 0.9,
            "liquidity_impulse_score": 0.0,
            "liquidity_regime_score": -2.0,
            "inflation_pressure_score": 1.5,
            "inflation_reacceleration_score": 1.5,
            "upstream_cost_pressure_score": 1.5,
            "labor_softening_score": 1.5,
            "cpi_yoy": 0.04,
            "core_cpi_yoy": 0.035,
            "valuation_close_date": "2026-08-18",
        }
    return {
        "macro_risk_off_score": -0.46,
        "market_regime_score": 0.38,
        "liquidity_drain_score": 0.31,
        "liquidity_impulse_score": 0.0,
        "liquidity_regime_score": -0.14,
        "inflation_pressure_score": -0.02,
        "inflation_reacceleration_score": 0.02,
        "upstream_cost_pressure_score": -0.06,
        "labor_softening_score": -0.02,
        "cpi_yoy": 0.041,
        "core_cpi_yoy": 0.028,
        "valuation_close_date": "2026-08-18",
    }


def fixture(
    root: Path,
    *,
    stressed: bool = False,
    stale: bool = False,
    profile: str = "balanced",
) -> tuple[argparse.Namespace, Path, Path]:
    macro = root / "macro_current.csv"
    pd.DataFrame([macro_row(stressed=stressed)]).to_csv(macro, index=False)
    manifest = root / "macro_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "READY_CONSERVATIVE_MACRO_SIDECAR",
                "blockers": [],
                "valuation_close_date": "2026-08-18",
                "decision_time_utc": "2026-08-18T21:00:00Z",
                "macro_available_from": (
                    "2026-08-18T22:00:00Z" if stale else "2026-08-18T20:15:00Z"
                ),
                "current_decision_only": True,
                "macro_merge_allowed": True,
                "historical_backtest_acceptance_allowed": False,
                "outputs": {
                    "macro_current": {
                        "path": str(macro),
                        "sha256": sha(macro),
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        contract=str(CONTRACT),
        macro_manifest=str(manifest),
        macro_current="",
        profile=profile,
        output_dir=str(root / "output"),
    )
    return args, manifest, macro


def test_balanced_inflation_guard_suppresses_unvalidated_risk_on_tilt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args, manifest, macro = fixture(Path(tmp))
        before = {"manifest": sha(manifest), "macro": sha(macro)}
        payload = build(args)
        assert payload["status"] == READY_STATUS
        assert payload["raw_macro_stress"] < 0.0
        assert payload["effective_macro_stress"] == 0.0
        assert payload["inflation_guard"]["triggered"] is True
        assert payload["inflation_guard"]["risk_on_tilt_suppressed"] is True
        allocation = payload["allocation"]
        stability_detail = payload["stability_asset_detail"]
        assert np.isclose(allocation["risk_assets"], 0.60)
        assert np.isclose(allocation["stability_assets"], 0.25)
        assert np.isclose(stability_detail["short_treasury"], 0.20)
        assert np.isclose(stability_detail["intermediate_treasury"], 0.05)
        assert np.isclose(allocation["cash_or_broker_mmf"], 0.15)
        assert np.isclose(
            allocation["risk_assets"]
            + stability_detail["short_treasury"]
            + stability_detail["intermediate_treasury"]
            + allocation["cash_or_broker_mmf"],
            1.0,
        )
        assert payload["historical_performance_validated"] is False
        assert payload["stock_ranking_executed"] is False
        assert payload["target_books_written"] is False
        assert payload["orders_generated"] is False
        assert payload["operating_ledger_mutated"] is False
        assert payload["source_inputs_mutated"] is False
        assert before == {"manifest": sha(manifest), "macro": sha(macro)}
        output = Path(args.output_dir)
        assert not any("target" in path.name.lower() for path in output.iterdir())
        assert not any("order" in path.name.lower() for path in output.iterdir())
        assert not any("ledger" in path.name.lower() for path in output.iterdir())


def test_stress_monotonically_reduces_risk_and_raises_stability_and_cash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args, _, _ = fixture(Path(tmp), stressed=True)
        payload = build(args)
        assert payload["status"] == READY_STATUS
        assert 0.0 < payload["effective_macro_stress"] <= 1.0
        allocation = payload["allocation"]
        assert allocation["risk_assets"] < 0.60
        assert allocation["stability_assets"] > 0.25
        assert allocation["cash_or_broker_mmf"] > 0.15


def test_profile_is_explicit_and_not_inferred_from_macro() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args, _, _ = fixture(Path(tmp), profile="growth")
        payload = build(args)
        assert payload["status"] == READY_STATUS
        assert payload["profile"] == "growth"
        assert np.isclose(payload["allocation"]["risk_assets"], 0.75)


def test_hash_mismatch_fails_closed_without_proposal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args, _, macro = fixture(Path(tmp))
        macro.write_text(macro.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        payload = build(args)
        assert payload["status"] == BLOCKED_STATUS
        assert "macro_current_sha256_mismatch" in payload["blockers"]
        assert payload["portfolio_mutation_allowed"] is False
        assert not (Path(args.output_dir) / "proposal.json").exists()


def test_future_macro_availability_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        args, _, _ = fixture(Path(tmp), stale=True)
        payload = build(args)
        assert payload["status"] == BLOCKED_STATUS
        assert "decision_time_before_macro_available_from" in payload["blockers"]
        assert payload["target_books_written"] is False


def main() -> int:
    test_balanced_inflation_guard_suppresses_unvalidated_risk_on_tilt()
    test_stress_monotonically_reduces_risk_and_raises_stability_and_cash()
    test_profile_is_explicit_and_not_inferred_from_macro()
    test_hash_mismatch_fails_closed_without_proposal()
    test_future_macro_availability_fails_closed()
    print("run287_macro_risk_budget_shadow_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
