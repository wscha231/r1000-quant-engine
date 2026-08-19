#!/usr/bin/env python3
"""Build a hash-bound, research-only Run287 macro sleeve proposal.

The router consumes one READY current macro sidecar and can change only the
aggregate risk/stability/cash budget.  It never reads stock scores or holdings
and cannot write a selector, target book, order, accepted ledger, or account.
The current mapping is a preregistered policy shadow, not a fitted allocation
model or historical performance claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "run287-macro-risk-budget-shadow-v1"
DEFAULT_CONTRACT = REPO_ROOT / "docs/run287_macro_risk_budget_shadow_contract.json"
DEFAULT_OUTPUT = REPO_ROOT / "outputs/run287_macro_risk_budget_shadow"
READY_STATUS = "READY_SHADOW_MACRO_RISK_BUDGET"
BLOCKED_STATUS = "BLOCKED_MACRO_RISK_BUDGET_INPUT"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return loaded


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return str(value)


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def utc_timestamp(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid UTC timestamp: {value!r}")
    return pd.Timestamp(parsed)


def finite_value(row: pd.Series, column: str) -> float:
    value = float(pd.to_numeric(row.get(column), errors="coerce"))
    if not math.isfinite(value):
        raise ValueError(f"macro column is not finite: {column}")
    return value


def bounded_z(value: float) -> float:
    """Map a robust z-like macro score monotonically into [-1, 1]."""
    return float(np.tanh(float(value) / 1.5))


def macro_family_scores(row: pd.Series) -> dict[str, float]:
    market = float(
        np.mean(
            [
                bounded_z(finite_value(row, "macro_risk_off_score")),
                bounded_z(-finite_value(row, "market_regime_score")),
            ]
        )
    )
    liquidity_balance = float(
        np.clip(
            finite_value(row, "liquidity_drain_score")
            - finite_value(row, "liquidity_impulse_score"),
            -1.0,
            1.0,
        )
    )
    liquidity = float(
        np.mean(
            [
                liquidity_balance,
                bounded_z(-finite_value(row, "liquidity_regime_score")),
            ]
        )
    )
    inflation = float(
        np.mean(
            [
                bounded_z(finite_value(row, "inflation_pressure_score")),
                bounded_z(finite_value(row, "inflation_reacceleration_score")),
                bounded_z(finite_value(row, "upstream_cost_pressure_score")),
            ]
        )
    )
    labor = bounded_z(finite_value(row, "labor_softening_score"))
    return {
        "market_stress": market,
        "liquidity_stress": liquidity,
        "inflation_stress": inflation,
        "labor_stress": labor,
    }


def sleeve_allocation(
    base: Mapping[str, Any],
    *,
    effective_macro_stress: float,
    max_tilt: float,
) -> dict[str, float]:
    stress = float(np.clip(effective_macro_stress, -1.0, 1.0))
    risk = float(base["risk_assets"]) - max_tilt * stress
    stability = float(base["stability_assets"]) + (max_tilt * 2.0 / 3.0) * stress
    cash = float(base["cash_or_broker_mmf"]) + (max_tilt / 3.0) * stress
    weights = {
        "risk_assets": risk,
        "stability_assets": stability,
        "cash_or_broker_mmf": cash,
    }
    if any(not math.isfinite(value) or value < -1e-12 for value in weights.values()):
        raise ValueError(f"invalid sleeve allocation: {weights}")
    residual = 1.0 - float(sum(weights.values()))
    weights["cash_or_broker_mmf"] += residual
    if not np.isclose(sum(weights.values()), 1.0, atol=1e-12):
        raise ValueError("sleeve weights do not sum to one")
    return weights


def blocked_payload(
    *,
    blockers: list[str],
    contract_path: Path,
    manifest_path: Path,
    macro_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "blockers": blockers,
        "research_only": True,
        "proposal_only": True,
        "historical_performance_validated": False,
        "source_inputs": {
            "contract": fingerprint(contract_path),
            "macro_manifest": fingerprint(manifest_path),
            "macro_current": fingerprint(macro_path),
        },
        "stock_ranking_executed": False,
        "selector_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "operating_ledger_mutated": False,
        "portfolio_mutation_allowed": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
        "fullrun_executed": False,
    }


def render_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Run287 Macro Risk-Budget Shadow",
        "",
        f"- status: `{payload.get('status')}`",
        f"- valuation close: `{payload.get('valuation_close_date', '')}`",
        f"- profile: `{payload.get('profile', '')}`",
        f"- historical performance validated: `{str(payload.get('historical_performance_validated', False)).lower()}`",
        "",
    ]
    if payload.get("blockers"):
        lines.extend(["## Blockers", "", *[f"- `{item}`" for item in payload["blockers"]], ""])
        return "\n".join(lines)
    allocation = payload["allocation"]
    stability_detail = payload["stability_asset_detail"]
    lines.extend(
        [
            "## Shadow Sleeve Proposal",
            "",
            f"- risk assets: `{100.0 * allocation['risk_assets']:.2f}%`",
            f"- stability assets: `{100.0 * allocation['stability_assets']:.2f}%`",
            f"  - short Treasury category: `{100.0 * stability_detail['short_treasury']:.2f}%`",
            f"  - intermediate Treasury category: `{100.0 * stability_detail['intermediate_treasury']:.2f}%`",
            f"- cash or broker MMF: `{100.0 * allocation['cash_or_broker_mmf']:.2f}%`",
            "",
            "## Boundary",
            "",
            "This is a current-decision shadow proposal. It does not select securities,",
            "write targets, generate orders, mutate the accepted ledger, or prove historical",
            "performance. The current broker cash/MMF Reserve default is unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    contract_path = Path(args.contract).resolve()
    manifest_path = Path(args.macro_manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")

    input_hashes_before = {
        "contract": sha256_file(contract_path) if contract_path.is_file() else "",
        "macro_manifest": sha256_file(manifest_path) if manifest_path.is_file() else "",
        "macro_current": "",
    }
    blockers: list[str] = []
    contract: dict[str, Any] = {}
    manifest: dict[str, Any] = {}
    try:
        contract = read_json(contract_path)
    except Exception as exc:
        blockers.append(f"contract_unreadable:{type(exc).__name__}")
    try:
        manifest = read_json(manifest_path)
    except Exception as exc:
        blockers.append(f"macro_manifest_unreadable:{type(exc).__name__}")

    manifest_macro = ((manifest.get("outputs") or {}).get("macro_current") or {})
    macro_path = Path(args.macro_current or str(manifest_macro.get("path") or "missing")).resolve()
    expected_macro_sha = str(manifest_macro.get("sha256") or "").lower()
    actual_macro_sha = sha256_file(macro_path) if macro_path.is_file() else ""
    input_hashes_before["macro_current"] = actual_macro_sha

    required_status = str(
        ((contract.get("input_contract") or {}).get("required_manifest_status"))
        or "READY_CONSERVATIVE_MACRO_SIDECAR"
    )
    if manifest.get("status") != required_status:
        blockers.append(f"macro_manifest_status:{manifest.get('status')}!={required_status}")
    if manifest.get("blockers"):
        blockers.append("macro_manifest_has_blockers")
    if manifest.get("current_decision_only") is not True:
        blockers.append("current_decision_only_not_true")
    if manifest.get("macro_merge_allowed") is not True:
        blockers.append("macro_merge_allowed_not_true")
    if manifest.get("historical_backtest_acceptance_allowed") is not False:
        blockers.append("historical_backtest_acceptance_boundary_invalid")
    if not macro_path.is_file():
        blockers.append("macro_current_missing")
    elif not expected_macro_sha:
        blockers.append("macro_current_manifest_sha_missing")
    elif actual_macro_sha.lower() != expected_macro_sha:
        blockers.append("macro_current_sha256_mismatch")

    frame = pd.DataFrame()
    if macro_path.is_file():
        try:
            frame = pd.read_csv(macro_path)
        except Exception as exc:
            blockers.append(f"macro_current_unreadable:{type(exc).__name__}")
    if len(frame) != 1:
        blockers.append(f"macro_current_row_count:{len(frame)}!=1")

    row = frame.iloc[0] if len(frame) == 1 else pd.Series(dtype=object)
    required_columns = list((contract.get("input_contract") or {}).get("required_columns") or [])
    missing_columns = [column for column in required_columns if column not in frame.columns]
    blockers.extend(f"macro_column_missing:{column}" for column in missing_columns)
    for column in required_columns:
        if column in frame.columns:
            value = pd.to_numeric(row.get(column), errors="coerce")
            if not math.isfinite(float(value)):
                blockers.append(f"macro_column_not_finite:{column}")

    valuation_close = str(manifest.get("valuation_close_date") or "")
    if len(frame) == 1 and str(row.get("valuation_close_date") or "") != valuation_close:
        blockers.append("valuation_close_date_mismatch")
    try:
        decision_time = utc_timestamp(manifest.get("decision_time_utc"))
        macro_available = utc_timestamp(manifest.get("macro_available_from"))
        if decision_time < macro_available:
            blockers.append("decision_time_before_macro_available_from")
    except ValueError:
        blockers.append("macro_availability_timestamp_invalid")

    profile = str(args.profile).lower().strip()
    profiles = contract.get("profiles") or {}
    if profile not in profiles:
        blockers.append(f"unsupported_profile:{profile}")

    output_dir.mkdir(parents=True)
    if blockers:
        payload = blocked_payload(
            blockers=sorted(set(blockers)),
            contract_path=contract_path,
            manifest_path=manifest_path,
            macro_path=macro_path,
        )
        write_json(output_dir / "manifest.json", payload)
        (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
        return payload

    family_scores = macro_family_scores(row)
    raw_stress = float(np.clip(np.mean(list(family_scores.values())), -1.0, 1.0))
    observed_inflation = max(
        finite_value(row, "cpi_yoy"),
        finite_value(row, "core_cpi_yoy"),
    )
    inflation_guard_triggered = observed_inflation > 0.025
    effective_stress = max(raw_stress, 0.0) if inflation_guard_triggered else raw_stress
    max_tilt = float((contract.get("tilt_policy") or {}).get("maximum_risk_asset_tilt"))
    sleeve = sleeve_allocation(
        profiles[profile],
        effective_macro_stress=effective_stress,
        max_tilt=max_tilt,
    )
    stability_split = (contract.get("tilt_policy") or {}).get("stability_split") or {}
    short_treasury = sleeve["stability_assets"] * float(stability_split["short_treasury"])
    intermediate_treasury = sleeve["stability_assets"] - short_treasury
    stability_detail = {
        "short_treasury": short_treasury,
        "intermediate_treasury": intermediate_treasury,
    }
    if not np.isclose(
        sleeve["risk_assets"]
        + stability_detail["short_treasury"]
        + stability_detail["intermediate_treasury"]
        + sleeve["cash_or_broker_mmf"],
        1.0,
        atol=1e-12,
    ):
        raise ValueError("expanded allocation does not sum to one")

    family_path = output_dir / "family_scores.csv"
    pd.DataFrame(
        [{"family": name, "stress_score": value} for name, value in family_scores.items()]
    ).to_csv(family_path, index=False)

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "blockers": [],
        "valuation_close_date": valuation_close,
        "decision_time_utc": str(manifest.get("decision_time_utc")),
        "macro_available_from": str(manifest.get("macro_available_from")),
        "profile": profile,
        "family_scores": family_scores,
        "raw_macro_stress": raw_stress,
        "effective_macro_stress": effective_stress,
        "inflation_guard": {
            "triggered": inflation_guard_triggered,
            "observed_max_cpi_yoy": observed_inflation,
            "threshold": 0.025,
            "risk_on_tilt_suppressed": bool(inflation_guard_triggered and raw_stress < 0.0),
        },
        "allocation": sleeve,
        "stability_asset_detail": stability_detail,
        "reserve_execution_policy_changed": False,
        "current_reserve_default": "BROKER_CASH_OR_MMF",
        "research_only": True,
        "proposal_only": True,
        "historical_performance_validated": False,
        "performance_status": "NOT_RUN_BLOCKED_BY_PIT_SCIENTIFIC_WEIGHTING_READINESS",
        "stock_ranking_executed": False,
        "selector_executed": False,
        "target_books_written": False,
        "orders_generated": False,
        "operating_ledger_mutated": False,
        "portfolio_mutation_allowed": False,
        "automatic_promotion_allowed": False,
        "production_or_live_trading_enabled": False,
        "fullrun_executed": False,
        "source_inputs": {
            "contract": fingerprint(contract_path),
            "macro_manifest": fingerprint(manifest_path),
            "macro_current": fingerprint(macro_path),
        },
        "code": {
            "builder": fingerprint(Path(__file__).resolve()),
            "git_head": git_head(),
        },
    }
    proposal_path = output_dir / "proposal.json"
    write_json(proposal_path, payload)
    report_path = output_dir / "report.md"
    report_path.write_text(render_report(payload), encoding="utf-8")
    input_hashes_after = {
        "contract": sha256_file(contract_path),
        "macro_manifest": sha256_file(manifest_path),
        "macro_current": sha256_file(macro_path),
    }
    if input_hashes_after != input_hashes_before:
        raise RuntimeError("source input changed during macro risk-budget build")
    payload["source_inputs_mutated"] = False
    payload["outputs"] = {
        "proposal": fingerprint(proposal_path),
        "family_scores": fingerprint(family_path),
        "report": fingerprint(report_path),
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--macro-manifest", required=True)
    parser.add_argument("--macro-current", default="")
    parser.add_argument("--profile", choices=["conservative", "balanced", "growth"], default="balanced")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
