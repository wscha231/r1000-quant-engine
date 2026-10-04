#!/usr/bin/env python3
"""Review-only verifier for completed full-rebuild A/B candidates.

The system acceptance audit can queue Concentrated recovery experiments, and
the review dispatcher can launch them with explicit approval. This tool closes
the next governance step: after those A/B runs finish, compare each candidate
against the baseline run and decide whether the result is review-promotable,
blocked by missing evidence, invalid, or rejected.

It never mutates production config, target books, or live orders.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from r1000_config import PORTFOLIO_MISSION_TARGETS
from mission_contract import mission_identity, mission_binding_status, OFFICIAL_METRIC_MODE
from research import evaluation_v2_admission as comparison_admission

try:
    from r1000_config import PORTFOLIO_GOAL_GATES
except Exception:  # pragma: no cover - smoke fallback
    PORTFOLIO_GOAL_GATES = {
        "main": {"is_cagr_min": 0.25},
        "concentrated": {"is_cagr_min": 0.30},
    }


MIN_BROKER_LEDGER_YEARS = 8.0
MIN_BROKER_LEDGER_TRADING_DAYS = 252 * 8
ATTRIBUTION_REQUIREMENT_ID = "attribution_package_year_mdd_name"
OOS_LOCK_REQUIREMENT_ID = "oos_holdout_lock"
COMPARISON_OPTIONS = ("comparison_admission_root", "comparison_control_arm",
                      "comparison_challenger_arm", "expected_context_sha256")
COMPARISON_AUTHORITY_FIELDS = ("unverified_domains", "g0_certified", "economic_comparison_ready",
                              "champion_promotion_allowed", "public_publication_allowed",
                              "fullrun_allowed", "target_paper_broker_mutation_allowed")


def blocked_comparison(reason: str) -> dict[str, Any]:
    return {
        "schema": comparison_admission.SCHEMA, "status": "BLOCKED", "reason": reason,
        "unverified_domains": list(comparison_admission.UNVERIFIED),
        **{name: False for name in COMPARISON_AUTHORITY_FIELDS if name != "unverified_domains"},
    }


def physical_path_chain(path: Path) -> tuple[tuple[int, int] | None, set[tuple[int, int]]]:
    """Bind existing endpoints/ancestors without reading artifact contents."""
    endpoint = None
    identities = set()
    for component in (path, *path.parents):
        try:
            observed = component.stat()
        except FileNotFoundError:
            continue  # Include the nearest existing ancestor of missing output.
        comparison_admission.require(observed.st_ino != 0, "OUTPUT_ADMISSION_PATH_INVALID")
        identity = (observed.st_dev, observed.st_ino)
        identities.add(identity)
        if component == path:
            endpoint = identity
    return endpoint, identities


def comparison_output_error(args: argparse.Namespace) -> str | None:
    """Check physical output geometry before artifact/legacy reads or writes."""
    root = getattr(args, "comparison_admission_root", None)
    if root is None:
        return None
    try:
        comparison_admission.require((type(root) is str or isinstance(root, Path)) and bool(str(root)),
                                     "OUTPUT_ADMISSION_PATH_INVALID")
        # Keep lexical checks for missing paths, and bind existing components
        # physically: case-insensitive POSIX volumes need not normalize spelling.
        resolved_root = Path(root).resolve(strict=False)
        root_key = os.path.normcase(str(resolved_root))
        root_identity, root_chain = physical_path_chain(resolved_root)
        output = repo_path(getattr(args, "output_dir", "outputs/ab_result_verifier"))
        for path in (output, *(output / name for name in PUBLICATION_LEAVES)):
            if path != output and path.exists():
                # A multiply linked report file can mutate a pinned input even
                # when its directory is outside the bundle. Reject ambiguous
                # physical aliases without scanning or reading input artifacts.
                comparison_admission.require(path.stat().st_nlink <= 1, "OUTPUT_ADMISSION_PATH_OVERLAP")
            resolved_output = path.resolve(strict=False)
            output_identity, output_chain = physical_path_chain(resolved_output)
            comparison_admission.require(
                (root_identity is None or root_identity not in output_chain)
                and (output_identity is None or output_identity not in root_chain),
                "OUTPUT_ADMISSION_PATH_OVERLAP",
            )
            output_key = os.path.normcase(str(resolved_output))
            try:
                common = os.path.commonpath((root_key, output_key))
            except ValueError:  # Different volumes cannot overlap.
                continue
            comparison_admission.require(common not in (root_key, output_key),
                                         "OUTPUT_ADMISSION_PATH_OVERLAP")
    except comparison_admission.AdmissionError as exc:
        return str(exc)
    except (OSError, TypeError, ValueError, RuntimeError):
        return "OUTPUT_ADMISSION_PATH_INVALID"
    return None


def comparison_precheck(args: argparse.Namespace) -> dict[str, Any] | None:
    """Optional byte identity admission; its caller pin is never derived from arms."""
    # Keep the actual native read boundary across later legacy result collection.
    # A surviving parent or a new directory at the same spelling is not that root.
    args._comparison_admitted_root = None
    values = [getattr(args, name, None) for name in COMPARISON_OPTIONS]
    if all(value is None for value in values):
        return None
    try:
        output_error = comparison_output_error(args)
        comparison_admission.require(output_error is None, output_error or "OUTPUT_ADMISSION_PATH_INVALID")
        comparison_admission.require(all(value is not None for value in values),
                                     "ADMISSION_OPTIONS_INCOMPLETE")
        candidates = getattr(args, "candidate_run", None)
        comparison_admission.require(type(candidates) in (list, tuple) and len(candidates) == 1,
                                     "COMPARISON_SINGLE_CANDIDATE_REQUIRED")
        root, control_id, challenger_id, pin = values
        comparison_admission.require(type(pin) is str and comparison_admission.HEX64.fullmatch(pin) is not None,
                                     "EXPECTED_CONTEXT_HASH_REQUIRED")
        comparison_admission.validate_artifact_id(control_id)
        comparison_admission.validate_artifact_id(challenger_id)
        resolver = comparison_admission.BoundedArtifactResolver(root)
        args._comparison_admitted_root = (resolver.root, resolver.root_identity)
        control = comparison_admission.strict_json(resolver(control_id))
        challenger = comparison_admission.strict_json(resolver(challenger_id))
        return comparison_admission.compare_environment(control, challenger,
                    expected_context_sha256=pin, artifact_resolver=resolver)
    except comparison_admission.AdmissionError as exc:
        return blocked_comparison(str(exc))


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if isinstance(value, bool) or value in (None, ""):
            return default
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def target_for(portfolio: str) -> dict[str, float]:
    target = PORTFOLIO_MISSION_TARGETS[portfolio]
    return {"cagr": float(target["cagr"]), "max_dd": float(target["max_dd"])}


def gate_for(portfolio: str) -> dict[str, float]:
    gate = PORTFOLIO_GOAL_GATES.get(portfolio, {})
    return {
        "is_cagr_min": float(gate.get("is_cagr_min", 0.25 if portfolio == "main" else 0.30)),
    }


def nested_metric(payload: dict[str, Any], *keys: str) -> float | None:
    cur: Any = payload
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return safe_float(cur)


def requirement_status(system: dict[str, Any], requirement_id: str) -> str:
    for row in system.get("requirements") or []:
        if isinstance(row, dict) and row.get("requirement_id") == requirement_id:
            return str(row.get("status") or "")
    return ""


def requirement_row(system: dict[str, Any], requirement_id: str) -> dict[str, Any]:
    for row in system.get("requirements") or []:
        if isinstance(row, dict) and row.get("requirement_id") == requirement_id:
            return row
    return {}


def run_label(path: Path) -> str:
    parts = [part for part in path.parts if part]
    return parts[-1] if parts else str(path)


def collect_evidence(run_dir: Path, portfolio: str) -> dict[str, Any]:
    official_path = run_dir / "account_evaluation" / "official_metrics.json"
    official = read_json(official_path)
    contract_status = mission_binding_status(official, mission_identity(PORTFOLIO_MISSION_TARGETS))
    portfolios = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    row = portfolios.get(portfolio) if isinstance(portfolios.get(portfolio), dict) else {}

    broker_path = run_dir / "broker_replay" / portfolio / "metrics.json"
    broker = read_json(broker_path)
    system_path = run_dir / "system_acceptance_audit" / "summary.json"
    system = read_json(system_path)
    is_attr_path = run_dir / "is_attribution" / "summary.json"
    is_attr = read_json(is_attr_path)
    attr_row = is_attr.get(portfolio) if isinstance(is_attr.get(portfolio), dict) else {}
    oos_lock_path = run_dir / "oos_lock" / "summary.json"
    oos_lock = read_json(oos_lock_path)
    oos_portfolios = oos_lock.get("portfolios") if isinstance(oos_lock.get("portfolios"), dict) else {}
    oos_row = oos_portfolios.get(portfolio) if isinstance(oos_portfolios.get(portfolio), dict) else {}
    oos_requirement = requirement_row(system, OOS_LOCK_REQUIREMENT_ID)

    windows = broker.get("windows") if isinstance(broker.get("windows"), dict) else {}
    is_window = windows.get("is") if isinstance(windows.get("is"), dict) else {}
    oos_window = windows.get("oos") if isinstance(windows.get("oos"), dict) else {}
    window_gate = row.get("broker_ledger_window_gate") if isinstance(row.get("broker_ledger_window_gate"), dict) else {}
    mode = str(broker.get("metric_mode") or "")
    years = safe_float(row.get("years"), safe_float(broker.get("years")))
    trading_days = safe_int(
        row.get("broker_ledger_actual_trading_days"),
        safe_int(row.get("broker_ledger_trading_days_estimate"), safe_int(window_gate.get("trading_days_estimate"), safe_int(broker.get("days")))),
    )
    target = target_for(portfolio)
    cagr = safe_float(broker.get("cagr"))
    max_dd = safe_float(broker.get("max_dd"))
    is_cagr = safe_float(row.get("is_cagr"), safe_float(attr_row.get("is_cagr"), safe_float(is_window.get("cagr"))))
    oos_cagr = safe_float(row.get("oos_cagr"), safe_float(attr_row.get("oos_cagr"), safe_float(oos_window.get("cagr"))))
    status = broker.get("status") or "missing"
    source_target_pass = bool(row.get("target_pass"))
    mission_evidence_valid = bool(
        broker_path.is_file() and status == "completed" and mode == OFFICIAL_METRIC_MODE
        and cagr is not None and max_dd is not None
    )
    reevaluated_target_pass = bool(
        mission_evidence_valid
        and cagr >= target["cagr"]
        and max_dd >= target["max_dd"]
    )
    target_pass = bool(reevaluated_target_pass and contract_status == "current_mission_contract")

    return {
        "run_dir": str(run_dir),
        **mission_identity(PORTFOLIO_MISSION_TARGETS),
        "source_target_contract_status": contract_status,
        "run_label": run_label(run_dir),
        "portfolio": portfolio,
        "official_metrics_path": str(official_path),
        "official_metrics_exists": official_path.exists(),
        "broker_metrics_path": str(broker_path),
        "broker_metrics_exists": broker_path.is_file(),
        "mission_evidence_valid": mission_evidence_valid,
        "system_acceptance_path": str(system_path),
        "system_acceptance_exists": system_path.exists(),
        "is_attribution_path": str(is_attr_path),
        "is_attribution_exists": is_attr_path.exists(),
        "oos_lock_path": str(oos_lock_path),
        "oos_lock_exists": oos_lock_path.exists(),
        "official_metric_mode": mode,
        "status": status,
        "valid_for_production": bool(
            mission_evidence_valid and broker.get("valid_for_production", False)
            and contract_status == "current_mission_contract"
        ),
        "target_type": "canonical_mission",
        "target_pass": target_pass,
        "reevaluated_target_pass": reevaluated_target_pass,
        "source_target_pass": source_target_pass,
        "source_cagr_target": safe_float(row.get("cagr_target")),
        "source_max_dd_target": safe_float(row.get("max_dd_target")),
        "strengthened_pass": bool(row.get("strengthened_pass")),
        "tier2_failing": list(row.get("tier2_failing") or []),
        "cagr": cagr,
        "cagr_target": target["cagr"],
        "max_dd": max_dd,
        "max_dd_target": target["max_dd"],
        "is_cagr": is_cagr,
        "is_cagr_target": gate_for(portfolio)["is_cagr_min"],
        "oos_cagr": oos_cagr,
        "oos_lock_status": oos_lock.get("status") or "",
        "oos_lock_pass": oos_lock.get("lock_pass"),
        "oos_lock_hard_blocker_count": safe_int(oos_lock.get("hard_blocker_count"), 0 if oos_lock else None),
        "oos_lock_portfolio_status": oos_row.get("status") or "",
        "oos_is_cagr_ratio": safe_float(oos_row.get("oos_is_cagr_ratio")),
        "oos_lock_failures": list(oos_row.get("failures") or []),
        "oos_lock_requirement_status": str(oos_requirement.get("status") or ""),
        "oos_lock_requirement_hard_blocker": oos_requirement.get("hard_blocker") if oos_requirement else None,
        "sharpe": safe_float(row.get("sharpe"), safe_float(broker.get("sharpe"))),
        "avg_cash_weight": safe_float(row.get("avg_cash_weight"), safe_float(broker.get("avg_cash_weight"))),
        "years": years,
        "min_years": MIN_BROKER_LEDGER_YEARS,
        "trading_days": trading_days,
        "min_trading_days": MIN_BROKER_LEDGER_TRADING_DAYS,
        "start_date": row.get("start_date") or broker.get("start_date"),
        "end_date": row.get("end_date") or broker.get("end_date"),
        "window_gate_status": window_gate.get("status") or "",
        "window_gate_valid": window_gate.get("valid"),
        "window_gate_reasons": list(window_gate.get("reasons") or []),
        "system_acceptance_status": system.get("status") or "",
        "system_acceptance_hard_blocker_count": safe_int(system.get("hard_blocker_count"), 0 if system else None),
        "system_acceptance_production_activation_allowed": system.get("production_activation_allowed") if system else None,
        "attribution_requirement_status": requirement_status(system, ATTRIBUTION_REQUIREMENT_ID),
    }


def pct(value: Any) -> str:
    number = safe_float(value)
    return "n/a" if number is None else f"{number:.2%}"


def pp(value: Any) -> float | None:
    number = safe_float(value)
    return None if number is None else round(number * 100.0, 4)


def window_is_valid(candidate: dict[str, Any]) -> bool:
    years = safe_float(candidate.get("years"), 0.0) or 0.0
    trading_days = safe_int(candidate.get("trading_days"))
    gate_valid = candidate.get("window_gate_valid")
    if gate_valid is True:
        return True
    if candidate.get("valid_for_production") and years >= MIN_BROKER_LEDGER_YEARS:
        return trading_days is None or trading_days >= MIN_BROKER_LEDGER_TRADING_DAYS
    return False


def classify_candidate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    min_cagr_delta: float,
    min_is_cagr_delta: float,
    max_mdd_regression: float,
    require_evidence: bool,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not candidate.get("official_metrics_exists"):
        return "invalid_official_metrics", ["official_metrics_missing"]
    if candidate.get("source_target_contract_status") != "current_mission_contract":
        return "blocked_target_contract", ["historical_or_unbound_target_contract"]
    if candidate.get("official_metric_mode") != OFFICIAL_METRIC_MODE:
        return "invalid_official_metrics", [f"official_metric_mode:{candidate.get('official_metric_mode') or 'missing'}"]
    if candidate.get("system_acceptance_production_activation_allowed") is True:
        return "reject_unsafe_production_activation", ["system_acceptance_production_activation_allowed_true"]
    if not window_is_valid(candidate):
        issues.append("eight_year_window_not_valid")
        if (safe_float(candidate.get("years"), 0.0) or 0.0) < MIN_BROKER_LEDGER_YEARS:
            issues.append("broker_ledger_years_below_8")
        trading_days = safe_int(candidate.get("trading_days"))
        if trading_days is not None and trading_days < MIN_BROKER_LEDGER_TRADING_DAYS:
            issues.append("broker_ledger_trading_days_below_8y")
        issues.extend(str(item) for item in candidate.get("window_gate_reasons") or [])
        return "invalid_window", sorted(set(issues))

    cagr = safe_float(candidate.get("cagr"))
    max_dd = safe_float(candidate.get("max_dd"))
    if cagr is None or max_dd is None:
        return "invalid_official_metrics", ["candidate_cagr_or_mdd_missing"]
    if not candidate.get("target_pass") or cagr < candidate["cagr_target"] or max_dd < candidate["max_dd_target"]:
        return "reject_target_shortfall", [
            f"cagr:{pct(cagr)}_target:{pct(candidate['cagr_target'])}",
            f"max_dd:{pct(max_dd)}_target:{pct(candidate['max_dd_target'])}",
        ]

    is_cagr = safe_float(candidate.get("is_cagr"))
    if is_cagr is None:
        return "reject_strengthened_gate", ["is_cagr_missing"]
    if is_cagr < (safe_float(candidate.get("is_cagr_target"), 0.0) or 0.0):
        issues.append(f"is_cagr_below_target:{pct(is_cagr)}<{pct(candidate.get('is_cagr_target'))}")
    if not candidate.get("strengthened_pass"):
        issues.append("strengthened_pass_false")
    issues.extend(str(item) for item in candidate.get("tier2_failing") or [])
    if issues:
        return "reject_strengthened_gate", sorted(set(issues))

    regression_issues: list[str] = []
    base_cagr = safe_float(baseline.get("cagr"))
    if base_cagr is not None and (cagr - base_cagr) < min_cagr_delta:
        regression_issues.append(f"cagr_delta_below_min:{pp(cagr - base_cagr)}pp")
    base_is = safe_float(baseline.get("is_cagr"))
    if base_is is not None and (is_cagr - base_is) < min_is_cagr_delta:
        regression_issues.append(f"is_cagr_delta_below_min:{pp(is_cagr - base_is)}pp")
    base_mdd = safe_float(baseline.get("max_dd"))
    if base_mdd is not None and (max_dd - base_mdd) < -max_mdd_regression:
        regression_issues.append(f"max_dd_regression_too_large:{pp(max_dd - base_mdd)}pp")
    if regression_issues:
        return "reject_regression", regression_issues

    if require_evidence:
        missing = []
        if not candidate.get("system_acceptance_exists"):
            missing.append("system_acceptance_audit_missing")
        if not candidate.get("is_attribution_exists"):
            missing.append("is_attribution_summary_missing")
        if not candidate.get("oos_lock_exists"):
            missing.append("oos_lock_summary_missing")
        if candidate.get("attribution_requirement_status") != "pass":
            missing.append(f"{ATTRIBUTION_REQUIREMENT_ID}:{candidate.get('attribution_requirement_status') or 'missing'}")
        if not candidate.get("oos_lock_requirement_status"):
            missing.append(f"{OOS_LOCK_REQUIREMENT_ID}:{candidate.get('oos_lock_requirement_status') or 'missing'}")
        if candidate.get("system_acceptance_production_activation_allowed") is not False:
            missing.append("system_acceptance_production_activation_allowed_not_false")
        if missing:
            return "blocked_missing_evidence", missing
        oos_lock_blockers = safe_int(candidate.get("oos_lock_hard_blocker_count"), 0) or 0
        if (
            candidate.get("oos_lock_status") != "pass"
            or candidate.get("oos_lock_pass") is not True
            or candidate.get("oos_lock_portfolio_status") != "pass"
            or candidate.get("oos_lock_requirement_status") != "pass"
            or oos_lock_blockers > 0
            or candidate.get("oos_lock_failures")
        ):
            issues = [
                f"status:{candidate.get('oos_lock_status') or 'missing'}",
                f"portfolio_status:{candidate.get('oos_lock_portfolio_status') or 'missing'}",
                f"system_acceptance_requirement:{candidate.get('oos_lock_requirement_status') or 'missing'}",
                f"hard_blocker_count:{oos_lock_blockers}",
            ]
            issues.extend(str(item) for item in candidate.get("oos_lock_failures") or [])
            return "blocked_oos_lock", sorted(set(issues))
        hard_blockers = safe_int(candidate.get("system_acceptance_hard_blocker_count"), 0) or 0
        if hard_blockers > 0 or candidate.get("system_acceptance_status") != "production_evidence_ready":
            return "blocked_system_acceptance", [
                f"status:{candidate.get('system_acceptance_status') or 'missing'}",
                f"hard_blocker_count:{hard_blockers}",
            ]

    return "promote_candidate_review_only", []


def verdict_rank(decision: str) -> int:
    if decision == "promote_candidate_review_only":
        return 0
    if decision.startswith("blocked"):
        return 1
    return 2


def build_candidate_row(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    min_cagr_delta: float,
    min_is_cagr_delta: float,
    max_mdd_regression: float,
    require_evidence: bool,
) -> dict[str, Any]:
    decision, issues = classify_candidate(
        baseline,
        candidate,
        min_cagr_delta=min_cagr_delta,
        min_is_cagr_delta=min_is_cagr_delta,
        max_mdd_regression=max_mdd_regression,
        require_evidence=require_evidence,
    )
    cagr = safe_float(candidate.get("cagr"))
    is_cagr = safe_float(candidate.get("is_cagr"))
    max_dd = safe_float(candidate.get("max_dd"))
    base_cagr = safe_float(baseline.get("cagr"))
    base_is = safe_float(baseline.get("is_cagr"))
    base_mdd = safe_float(baseline.get("max_dd"))
    return {
        **candidate,
        "decision": decision,
        "issues": issues,
        "review_valid_for_promotion": decision == "promote_candidate_review_only",
        "requires_user_approval": True,
        "production_activation_allowed": False,
        "baseline_run_label": baseline.get("run_label"),
        "cagr_delta_vs_baseline_pp": pp(cagr - base_cagr) if cagr is not None and base_cagr is not None else None,
        "is_cagr_delta_vs_baseline_pp": pp(is_cagr - base_is) if is_cagr is not None and base_is is not None else None,
        "max_dd_delta_vs_baseline_pp": pp(max_dd - base_mdd) if max_dd is not None and base_mdd is not None else None,
    }


def render_report(payload: dict[str, Any]) -> str:
    baseline = payload.get("baseline") or {}
    lines = [
        "# A/B Result Verifier",
        "",
        f"- status: `{payload.get('status')}`",
        f"- portfolio: `{payload.get('portfolio')}`",
        f"- production_activation_allowed: `{str(payload.get('production_activation_allowed')).lower()}`",
        f"- requires_user_approval: `{str(payload.get('requires_user_approval')).lower()}`",
        f"- baseline: `{baseline.get('run_label')}` ({pct(baseline.get('cagr'))} / {pct(baseline.get('max_dd'))}, IS {pct(baseline.get('is_cagr'))})",
        "",
        "| Candidate | Decision | CAGR | MDD | IS-CAGR | OOS/IS | CAGR vs Base | IS vs Base | MDD vs Base | Issues |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    admission = payload.get("comparison_admission")
    if admission is not None:
        lines[8:8] = [
            f"- comparison byte admission: `{admission['status']}`",
            f"- comparison blocked reason: `{admission.get('reason', 'none')}`",
            "- Byte identity leaves provider, PIT, execution and economic domains unverified; all authority remains false.",
            "",
        ]
    for row in payload.get("candidates") or []:
        lines.append(
            "| {run} | `{decision}` | {cagr} | {mdd} | {is_cagr} | {oos_ratio} | {dcagr}pp | {dis}pp | {dmdd}pp | {issues} |".format(
                run=row.get("run_label"),
                decision=row.get("decision"),
                cagr=pct(row.get("cagr")),
                mdd=pct(row.get("max_dd")),
                is_cagr=pct(row.get("is_cagr")),
                oos_ratio="n/a" if row.get("oos_is_cagr_ratio") is None else f"{float(row.get('oos_is_cagr_ratio')):.2f}x",
                dcagr=row.get("cagr_delta_vs_baseline_pp"),
                dis=row.get("is_cagr_delta_vs_baseline_pp"),
                dmdd=row.get("max_dd_delta_vs_baseline_pp"),
                issues=", ".join(row.get("issues") or []),
            )
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- Review-only: this verifier never edits production config or submits orders.",
            "- A promotable candidate must pass the target contract, strengthened IS gates, 8-year broker-ledger window, OOS lock, attribution evidence, and system acceptance evidence.",
            "- `promote_candidate_review_only` still requires human review and a separate PR before any production change.",
            "",
        ]
    )
    return "\n".join(lines)


def write_csv_rows(handle: Any, rows: list[dict[str, Any]]) -> None:
    fields = [
        "experiment_id",
        "payload_hash",
        "workflow_run_id",
        "dispatch_run_id",
        "candidate_run",
        "run_label",
        "decision",
        "review_valid_for_promotion",
        "cagr",
        "max_dd",
        "is_cagr",
        "cagr_delta_vs_baseline_pp",
        "is_cagr_delta_vs_baseline_pp",
        "max_dd_delta_vs_baseline_pp",
        "years",
        "trading_days",
        "oos_lock_status",
        "oos_lock_portfolio_status",
        "oos_is_cagr_ratio",
        "system_acceptance_status",
        "system_acceptance_hard_blocker_count",
        "issues",
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        out = dict(row)
        out["issues"] = ";".join(str(item) for item in row.get("issues") or [])
        writer.writerow(out)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        write_csv_rows(handle, rows)


REPORT_LEAVES = ("summary.json", "candidate_verdicts.csv", "report.md")
COMPLETION_LEAF = "comparison_publication_complete.json"
PUBLICATION_LEAVES = (*REPORT_LEAVES, COMPLETION_LEAF)
PUBLICATION_SCHEMA = "r1000-ab-comparison-publication-v1"
COMPARISON_SUMMARY_SCHEMA = "ab-result-verifier-publication-v2"
MAX_REPORT_BYTES = 1024 * 1024


class PublicationCommitUncertain(comparison_admission.AdmissionError):
    """The final commit operation was attempted; its delivery is uncertain."""


def completed_comparison_summary(path: Path, raw: bytes) -> dict[str, Any]:
    """Validate a new file receipt; parse the same summary bytes bound by it."""
    resolver = comparison_admission.BoundedArtifactResolver(path.parent)
    for name in PUBLICATION_LEAVES:
        observed = (path.parent / name).lstat()
        comparison_admission.require(observed.st_nlink == 1, 'PUBLICATION_REPORT_LINK')
    comparison_admission.require(resolver(path.name) == raw, 'PUBLICATION_SUMMARY_CHANGED')
    summary = comparison_admission.strict_json(raw)
    comparison_admission.require(summary.get('schema_version') == COMPARISON_SUMMARY_SCHEMA
        and summary.get('current_receipt') is True, 'PUBLICATION_PROTOCOL_REQUIRED')
    protocol = summary.get('comparison_publication')
    comparison_admission.require(type(protocol) is dict and set(protocol) == {'schema', 'generation'}
        and protocol['schema'] == PUBLICATION_SCHEMA, 'PUBLICATION_PROTOCOL_REQUIRED')
    generation = protocol['generation']
    comparison_admission.require(type(generation) is str and len(generation) == 32
        and all(value in '0123456789abcdef' for value in generation), 'PUBLICATION_GENERATION')
    witness = comparison_admission.strict_json(resolver(COMPLETION_LEAF))
    comparison_admission.require(set(witness) == {'schema', 'generation', 'reports'}
        and witness['schema'] == PUBLICATION_SCHEMA and witness['generation'] == generation,
        'PUBLICATION_WITNESS')
    reports = witness['reports']
    comparison_admission.require(type(reports) is dict and set(reports) == set(REPORT_LEAVES),
        'PUBLICATION_WITNESS')
    for name in REPORT_LEAVES:
        ref = reports[name]
        comparison_admission.require(type(ref) is dict and set(ref) == {'bytes', 'sha256'}
            and type(ref['bytes']) is int and 0 <= ref['bytes'] <= MAX_REPORT_BYTES
            and type(ref['sha256']) is str and comparison_admission.HEX64.fullmatch(ref['sha256']) is not None,
            'PUBLICATION_WITNESS')
        report = raw if name == 'summary.json' else resolver(name)
        comparison_admission.require(len(report) == ref['bytes']
            and hashlib.sha256(report).hexdigest() == ref['sha256'], 'PUBLICATION_REPORT_MISMATCH')
    for name in resolver.cache:
        resolver.validate_cached(name)
        comparison_admission.require((path.parent / name).lstat().st_nlink == 1, 'PUBLICATION_REPORT_LINK')
    return summary


def publication_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


class ReportDirectory:
    """Anchor each component; never write through a checked pathname alone.

    POSIX operations use directory-relative descriptors. On Windows, listing/
    traversal handles deny write/delete sharing for every path component;
    attribute-only handles do not prevent directory replacement. Unsupported
    backends fail closed before publication.
    """
    def __init__(self, path: Path, *, create: bool = False, allow_missing: bool = False):
        self.path = Path(os.path.abspath(path))
        self.entries: list[tuple[Path, int, tuple[int, int]]] = []
        self.owned_descriptors: dict[str, int] = {}
        self.expected_leaves: dict[str, tuple[int, int] | None] = {}
        self.teardown_warning = False
        self.windows = os.name == 'nt'
        self.kernel = None
        if self.windows:
            import ctypes
            from ctypes import wintypes
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            self.kernel.CreateFileW.restype = wintypes.HANDLE
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle.restype = wintypes.BOOL
            self.kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                               ctypes.c_void_p, wintypes.DWORD]
            self.kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        else:
            comparison_admission.require(os.name == 'posix' and hasattr(os, 'O_DIRECTORY')
                and hasattr(os, 'O_NOFOLLOW') and os.open in os.supports_dir_fd
                and os.mkdir in os.supports_dir_fd and os.rename in os.supports_dir_fd
                and os.unlink in os.supports_dir_fd, 'OUTPUT_PUBLICATION_ANCHOR_UNAVAILABLE')
        completed = False
        try:
            current = Path(self.path.anchor)
            for part in ('', *self.path.parts[1:]):
                if part: current = current / part
                parent = self.entries[-1][1] if self.entries else None
                try:
                    observed = current.lstat()
                except FileNotFoundError:
                    if allow_missing: break
                    comparison_admission.require(create, 'OUTPUT_PUBLICATION_PATH_CHANGED')
                    if self.windows: os.mkdir(current)
                    else: os.mkdir(part, dir_fd=parent)
                    observed = current.lstat()
                comparison_admission.require(stat.S_ISDIR(observed.st_mode)
                    and not comparison_admission._is_link(observed), 'OUTPUT_PUBLICATION_PATH_CHANGED')
                if self.windows:
                    handle = self._win_open(current, 0xA1, 1, 3, 0x02000000 | 0x00200000)
                else:
                    handle = os.open(part if parent is not None else str(current),
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                self.entries.append((current, handle, publication_identity(observed)))
                self.guard()
            comparison_admission.require(bool(self.entries), 'OUTPUT_PUBLICATION_PATH_CHANGED')
            completed = True
        finally:
            if not completed: self.close()

    def _win_open(self, path: Path, access: int, sharing: int, disposition: int, flags: int) -> int:
        import ctypes
        handle = self.kernel.CreateFileW(str(path), access, sharing, None, disposition, flags, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError('output handle unavailable')
        return handle

    def guard(self) -> None:
        for path, handle, identity in self.entries:
            observed = path.lstat()
            comparison_admission.require(stat.S_ISDIR(observed.st_mode)
                and not comparison_admission._is_link(observed)
                and publication_identity(observed) == identity, 'OUTPUT_PUBLICATION_PATH_CHANGED')
            if not self.windows:
                comparison_admission.require(publication_identity(os.fstat(handle)) == identity,
                    'OUTPUT_PUBLICATION_PATH_CHANGED')

    def leaf_stat(self, name: str) -> os.stat_result | None:
        try:
            return (self.path / name).lstat() if self.windows else os.stat(name,
                dir_fd=self.entries[-1][1], follow_symlinks=False)
        except FileNotFoundError:
            return None

    def safe_leaf(self, name: str) -> os.stat_result | None:
        value = self.leaf_stat(name)
        comparison_admission.require(value is None or (stat.S_ISREG(value.st_mode)
            and not comparison_admission._is_link(value) and value.st_nlink == 1),
            'OUTPUT_PUBLICATION_PATH_CHANGED')
        if name in self.expected_leaves:
            comparison_admission.require((publication_identity(value) if value else None)
                == self.expected_leaves[name], 'OUTPUT_PUBLICATION_PATH_CHANGED')
        return value

    def register_descriptor(self, name: str, descriptor: int) -> int:
        value = os.fstat(descriptor)
        comparison_admission.require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1
            and not comparison_admission._is_link(value), 'OUTPUT_PUBLICATION_PATH_CHANGED')
        self.owned_descriptors[name] = descriptor
        self.expected_leaves[name] = publication_identity(value)
        return descriptor

    def capture_owned_leaves(self) -> None:
        for name in PUBLICATION_LEAVES:
            observed = self.safe_leaf(name)
            self.expected_leaves[name] = publication_identity(observed) if observed else None
            if observed is None: continue
            if self.windows:
                descriptor = self.existing_leaf_descriptor(name)
            else:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                     dir_fd=self.entries[-1][1])
            registered = False
            try:
                comparison_admission.require(publication_identity(os.fstat(descriptor)) == publication_identity(observed),
                    'OUTPUT_PUBLICATION_PATH_CHANGED')
                self.register_descriptor(name, descriptor); registered = True
            finally:
                if not registered: os.close(descriptor)

    def existing_leaf_descriptor(self, name: str) -> int:
        import msvcrt
        handle = self._win_open(self.path / name, 0x10080, 0, 3, 0x00200000)
        transferred = False
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            transferred = True
            return descriptor
        finally:
            if not transferred: self.kernel.CloseHandle(handle)

    def create_temp(self, name: str) -> int:
        if self.windows:
            descriptor = self.create_exclusive_leaf(name)
        else:
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=self.entries[-1][1])
        registered = False
        try:
            self.register_descriptor(name, descriptor)
            registered = True
            return descriptor
        finally:
            if not registered: os.close(descriptor)

    def create_exclusive_leaf(self, name: str) -> int:
        comparison_admission.require(self.windows, 'OUTPUT_PUBLICATION_ANCHOR_UNAVAILABLE')
        import msvcrt
        handle = self._win_open(self.path / name, 0xC0010000, 0, 1, 0x80 | 0x00200000)
        transferred = False
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
            transferred = True
            return descriptor
        finally:
            if not transferred: self.kernel.CloseHandle(handle)

    def replace(self, source: str, destination: str) -> tuple[int, int]:
        if self.windows:
            # Strong parent locks deny path rename on this Windows backend.
            # Never relax them: unlink the owned name, then CREATE_NEW. Writes
            # target only a new exclusive handle, never an existing leaf inode.
            self.guard(); self.safe_leaf(destination)
            comparison_admission.require(self.unlink_owned(destination), 'OUTPUT_PUBLICATION_PATH_CHANGED')
            target = self.create_exclusive_leaf(destination)
            registered = False
            try:
                self.register_descriptor(destination, target)
                registered = True
            finally:
                if not registered: os.close(target)
            # Hold the new final inode through group completion/cleanup.
            identity = publication_identity(os.fstat(target))
            original = self.owned_descriptors[source]
            os.lseek(original, 0, os.SEEK_SET)
            while True:
                raw = os.read(original, 65536)
                if not raw: break
                offset = 0
                while offset < len(raw):
                    written = os.write(target, raw[offset:])
                    comparison_admission.require(type(written) is int and 0 < written <= len(raw) - offset,
                        'OUTPUT_PUBLICATION_FAILED')
                    offset += written
            os.fsync(target)
            comparison_admission.require(self.unlink_owned(source), 'OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE')
            return identity
        identity = publication_identity(self.safe_leaf(source))
        os.replace(source, destination, src_dir_fd=self.entries[-1][1], dst_dir_fd=self.entries[-1][1])
        if destination in self.owned_descriptors:
            try: os.close(self.owned_descriptors.pop(destination))
            except OSError: pass
        self.owned_descriptors[destination] = self.owned_descriptors.pop(source)
        self.expected_leaves[destination] = self.expected_leaves.pop(source)
        return identity

    def close_owned_descriptors(self) -> None:
        for name, descriptor in list(self.owned_descriptors.items()):
            del self.owned_descriptors[name]
            try: os.close(descriptor)
            except OSError: self.teardown_warning = True

    def verify_installed(self, name: str, size: int, digest: str) -> None:
        """Verify the installed anchored name, not only the original stage fd."""
        self.guard()
        observed = self.safe_leaf(name)
        comparison_admission.require(observed is not None, 'OUTPUT_PUBLICATION_PATH_CHANGED')
        if self.windows:
            # The exclusive new handle denies write/delete access. The held
            # directory components and observed name bind this exact inode.
            descriptor = self.owned_descriptors[name]
        else:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=self.entries[-1][1])
        try:
            before = os.fstat(descriptor)
            comparison_admission.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and not comparison_admission._is_link(before)
                and publication_identity(before) == publication_identity(observed)
                and before.st_size == size, 'OUTPUT_PUBLICATION_PATH_CHANGED')
            os.lseek(descriptor, 0, os.SEEK_SET)
            actual = hashlib.sha256(); remaining = size
            while remaining:
                raw = os.read(descriptor, min(65536, remaining))
                comparison_admission.require(isinstance(raw, bytes) and 0 < len(raw) <= remaining,
                    'OUTPUT_PUBLICATION_FAILED')
                actual.update(raw); remaining -= len(raw)
            after = os.fstat(descriptor)
            final = self.safe_leaf(name)
            comparison_admission.require(final is not None
                and publication_identity(after) == publication_identity(final) == publication_identity(before)
                and after.st_size == size and actual.hexdigest() == digest,
                'OUTPUT_PUBLICATION_PATH_CHANGED')
            self.guard()
        finally:
            if not self.windows:
                try: os.close(descriptor)
                except OSError: self.teardown_warning = True

    def close(self) -> None:
        self.close_owned_descriptors()
        for _, handle, _ in reversed(self.entries):
            if self.windows:
                if not self.kernel.CloseHandle(handle): self.teardown_warning = True
            else:
                try: os.close(handle)
                except OSError: self.teardown_warning = True
        self.entries.clear()

    def unlink_owned(self, name: str) -> bool:
        value = self.leaf_stat(name)
        descriptor = self.owned_descriptors.get(name)
        if value is None:
            if descriptor is not None: os.close(self.owned_descriptors.pop(name))
            self.expected_leaves[name] = None
            return True
        if descriptor is None: return False
        if not stat.S_ISREG(value.st_mode) or comparison_admission._is_link(value) or value.st_nlink != 1:
            return False
        if (publication_identity(value) != self.expected_leaves.get(name)
                or publication_identity(os.fstat(descriptor)) != publication_identity(value)):
            return False
        if self.windows:
            import ctypes
            import msvcrt
            disposition = ctypes.c_byte(1)
            if not self.kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(descriptor), 4,
                    ctypes.byref(disposition), ctypes.sizeof(disposition)):
                raise OSError('owned output deletion unavailable')
        else:
            # POSIX has no portable inode-conditional unlink. After an error,
            # retaining a name is safer than deleting a raced new occupant.
            # The direct API/CLI reports incomplete publication in this case.
            return False
        os.close(self.owned_descriptors.pop(name))
        self.expected_leaves[name] = None
        return True


def publish_anchored(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    """Write exclusive new inodes; old leaves are opened only for ownership."""
    root = output = None
    temporary: dict[str, tuple[int, int]] = {}
    commit_attempted = False
    commit_verified = False
    try:
        admitted_root = getattr(args, '_comparison_admitted_root', None)
        if getattr(args, 'comparison_admission_root', None) is not None:
            root = ReportDirectory(Path(args.comparison_admission_root), allow_missing=admitted_root is None)
        if admitted_root is not None:
            comparison_admission.require(root.path == admitted_root[0]
                and root.entries[-1][2] == admitted_root[1], 'ARTIFACT_ROOT_CHANGED')
        output = ReportDirectory(repo_path(args.output_dir), create=True)
        if root is not None: root.guard()
        output.guard()
        error = comparison_output_error(args)
        comparison_admission.require(error is None, error or 'OUTPUT_PUBLICATION_PATH_CHANGED')
        output.capture_owned_leaves()
        text = io.StringIO(newline=''); write_csv_rows(text, payload['candidates'])
        contents = (json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False) + '\n',
                    text.getvalue(), render_report(payload))
        staged = []
        for leaf, content in zip(REPORT_LEAVES, contents):
            if root is not None: root.guard()
            output.guard()
            for target in PUBLICATION_LEAVES: output.safe_leaf(target)
            name = '.ab-report-' + uuid.uuid4().hex + '.tmp'
            descriptor = output.create_temp(name)
            value = os.fstat(descriptor)
            comparison_admission.require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1,
                'OUTPUT_PUBLICATION_PATH_CHANGED')
            temporary[name] = publication_identity(value)
            raw = content.encode('utf-8'); offset = 0
            comparison_admission.require(len(raw) <= MAX_REPORT_BYTES,
                                         'OUTPUT_REPORT_BYTE_BUDGET')
            while offset < len(raw):
                written = os.write(descriptor, raw[offset:])
                comparison_admission.require(type(written) is int and 0 < written <= len(raw) - offset,
                    'OUTPUT_PUBLICATION_FAILED')
                offset += written
            os.fsync(descriptor)
            staged.append((name, leaf, temporary[name], len(raw), hashlib.sha256(raw).hexdigest()))
        # Install summary last, but verify its installed identity and bytes too.
        # A partial or unverified group is never this invocation's receipt.
        staged.sort(key=lambda item: item[1] == 'summary.json')
        for name, leaf, identity, size, digest in staged:
            if root is not None: root.guard()
            output.guard(); output.safe_leaf(leaf)
            error = comparison_output_error(args)
            comparison_admission.require(error is None, error or 'OUTPUT_PUBLICATION_PATH_CHANGED')
            value = output.safe_leaf(name)
            comparison_admission.require(value is not None and publication_identity(value) == identity,
                'OUTPUT_PUBLICATION_PATH_CHANGED')
            installed_identity = output.replace(name, leaf)
            temporary.pop(name)
            value = output.safe_leaf(leaf)
            comparison_admission.require(value is not None and publication_identity(value) == installed_identity,
                'OUTPUT_PUBLICATION_PATH_CHANGED')
            output.verify_installed(leaf, size, digest)
        # These positive reports remain uncommitted until a matching witness.
        # Complete all source/output/report validation before attempting commit.
        if root is not None: root.guard()
        output.guard()
        error = comparison_output_error(args)
        comparison_admission.require(error is None, error or 'OUTPUT_PUBLICATION_PATH_CHANGED')
        witness = {'schema': PUBLICATION_SCHEMA,
                   'generation': payload['comparison_publication']['generation'],
                   'reports': {leaf: {'bytes': size, 'sha256': digest}
                               for _, leaf, _, size, digest in staged}}
        raw = (json.dumps(witness, indent=2, sort_keys=True) + '\n').encode('utf-8')
        name = '.ab-report-' + uuid.uuid4().hex + '.tmp'
        descriptor = output.create_temp(name)
        temporary[name] = publication_identity(os.fstat(descriptor))
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            comparison_admission.require(type(written) is int and 0 < written <= len(raw) - offset,
                                         'OUTPUT_PUBLICATION_FAILED')
            offset += written
        os.fsync(descriptor)
        output.verify_installed(name, len(raw), hashlib.sha256(raw).hexdigest())
        if root is not None: root.guard()
        output.guard(); output.safe_leaf(COMPLETION_LEAF)
        error = comparison_output_error(args)
        comparison_admission.require(error is None, error or 'OUTPUT_PUBLICATION_PATH_CHANGED')
        # Final commit/delivery step. Any error from this point is uncertain
        # delivery, never a later source rejection or revocation of its files.
        commit_attempted = True
        installed_identity = output.replace(name, COMPLETION_LEAF)
        temporary.pop(name)
        value = output.safe_leaf(COMPLETION_LEAF)
        comparison_admission.require(value is not None and publication_identity(value) == installed_identity,
                                     'OUTPUT_PUBLICATION_PATH_CHANGED')
        output.verify_installed(COMPLETION_LEAF, len(raw), hashlib.sha256(raw).hexdigest())
        commit_verified = True
    except (comparison_admission.AdmissionError, OSError, ValueError, TypeError, RuntimeError) as exc:
        incomplete = False
        if output is not None:
            for name in list(output.owned_descriptors):
                if commit_attempted and not name.startswith('.ab-report-'): continue
                try: incomplete = not output.unlink_owned(name) or incomplete
                except OSError: incomplete = True
        if commit_attempted:
            # The commit may already be readable. Do not revoke its files or
            # report an explicit data rejection/current_receipt=false.
            raise PublicationCommitUncertain('OUTPUT_PUBLICATION_COMMIT_UNCERTAIN') from None
        reason = str(exc) if isinstance(exc, comparison_admission.AdmissionError) else 'OUTPUT_PUBLICATION_FAILED'
        if incomplete: reason = 'OUTPUT_PUBLICATION_CLEANUP_INCOMPLETE'
        raise comparison_admission.AdmissionError(reason) from None
    finally:
        for directory in (output, root):
            if directory is not None:
                try: directory.close()
                except OSError: directory.teardown_warning = True
        if any(directory is not None and directory.teardown_warning for directory in (output, root)):
            emit_status({'status': 'publication_resource_cleanup_warning',
                         'current_receipt': True if commit_verified else None if commit_attempted else False})


def blocked_comparison_payload(admission: dict[str, Any], portfolio: str) -> dict[str, Any]:
    return {
        "schema_version": "ab-result-verifier-v1", **mission_identity(PORTFOLIO_MISSION_TARGETS),
        "status": "blocked_comparison_admission", "portfolio": portfolio,
        "current_receipt": False,
        "comparison_admission": admission, "baseline": {}, "candidate_count": 0,
        "candidates": [], "review_valid_candidate_count": 0,
        "production_activation_allowed": False, "live_trading_allowed": False,
        "requires_user_approval": True,
        **{name: admission[name] for name in COMPARISON_AUTHORITY_FIELDS},
    }


def publish_or_block(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {**payload, 'current_receipt': True, 'schema_version': COMPARISON_SUMMARY_SCHEMA,
               'comparison_publication': {'schema': PUBLICATION_SCHEMA, 'generation': uuid.uuid4().hex}}
    try:
        publish_report(args, payload)
    except PublicationCommitUncertain as exc:
        payload = blocked_comparison_payload(blocked_comparison(str(exc)), payload['portfolio'])
        payload.update(status='comparison_publication_uncertain', current_receipt=None)
        emit_status({'status': payload['status'], 'reason': str(exc), 'current_receipt': None})
    except comparison_admission.AdmissionError as exc:
        # Final geometry failure is an in-memory blocked result for direct API
        # callers too. Do not retry publication into the unsafe destination.
        payload = blocked_comparison_payload(blocked_comparison(str(exc)), payload["portfolio"])
        emit_status({"status": payload["status"], "reason": str(exc), "current_receipt": False})
    return payload


def emit_status(payload: dict[str, Any]) -> None:
    """Telemetry failure does not change installed evidence or API outcome."""
    message = json.dumps(payload, indent=2)
    if getattr(sys.stdout, 'closed', False): return
    try:
        print(message, flush=True)
    except OSError:
        # Flush now so a closed native pipe cannot override main's outcome at
        # interpreter shutdown. Never close a caller's redirected/custom stream.
        if sys.stdout is sys.__stdout__:
            try: sys.stdout.close()
            except OSError: pass


def run(args: argparse.Namespace) -> dict[str, Any]:
    portfolio = str(getattr(args, "portfolio", "concentrated"))
    output_error = comparison_output_error(args)
    admission = blocked_comparison(output_error) if output_error else comparison_precheck(args)
    if admission is not None and admission["status"] == "BLOCKED":
        payload = blocked_comparison_payload(admission, portfolio)
        if output_error is None:
            return publish_or_block(args, payload)
        else:
            # An unsafe report destination must never receive even a blocked
            # summary. Return the bounded result in memory/CLI only.
            emit_status({"status": payload["status"], "reason": output_error})
        return payload
    baseline = collect_evidence(repo_path(args.baseline_run), portfolio)
    baseline_ok = bool(
        baseline.get("official_metrics_exists")
        and baseline.get("mission_evidence_valid")
        and baseline.get("source_target_contract_status") == "current_mission_contract"
    )
    require_evidence = not bool(getattr(args, "allow_missing_evidence", False))
    min_cagr_delta = float(getattr(args, "min_cagr_delta_pp", 0.0)) / 100.0
    min_is_delta = float(getattr(args, "min_is_cagr_delta_pp", 0.5)) / 100.0
    max_mdd_regression = float(getattr(args, "max_mdd_regression_pp", 1.0)) / 100.0
    dispatch_context = {
        "experiment_id": str(getattr(args, "experiment_id", "") or ""),
        "payload_hash": str(getattr(args, "payload_hash", "") or ""),
        "workflow_run_id": str(getattr(args, "workflow_run_id", "") or ""),
        "dispatch_run_id": str(getattr(args, "dispatch_run_id", "") or ""),
    }

    candidate_rows: list[dict[str, Any]] = []
    for candidate_arg in getattr(args, "candidate_run", None) or []:
        candidate = collect_evidence(repo_path(candidate_arg), portfolio)
        if not baseline_ok:
            row = {
                **candidate,
                "decision": "blocked_missing_baseline",
                "issues": ["baseline_official_metrics_missing_or_invalid"],
                "review_valid_for_promotion": False,
                "requires_user_approval": True,
                "production_activation_allowed": False,
                "baseline_run_label": baseline.get("run_label"),
            }
        else:
            row = build_candidate_row(
                baseline,
                candidate,
                min_cagr_delta=min_cagr_delta,
                min_is_cagr_delta=min_is_delta,
                max_mdd_regression=max_mdd_regression,
                require_evidence=require_evidence,
            )
        row["candidate_run"] = row.get("run_label")
        for key, value in dispatch_context.items():
            if value:
                row[key] = value
        candidate_rows.append(row)

    candidate_rows.sort(
        key=lambda row: (
            verdict_rank(str(row.get("decision"))),
            -(safe_float(row.get("is_cagr"), -1.0) or -1.0),
            -(safe_float(row.get("cagr"), -1.0) or -1.0),
        )
    )
    decisions = [str(row.get("decision")) for row in candidate_rows]
    if not baseline_ok:
        status = "blocked_missing_baseline"
    elif any(decision == "promote_candidate_review_only" for decision in decisions):
        status = "review_candidate_ready"
    elif any(decision.startswith("blocked") for decision in decisions):
        status = "blocked"
    else:
        status = "rejected"

    payload = {
        "schema_version": "ab-result-verifier-v1",
        **mission_identity(PORTFOLIO_MISSION_TARGETS),
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "portfolio": portfolio,
        "target_type": "canonical_mission",
        "baseline": baseline,
        "candidate_count": len(candidate_rows),
        "review_valid_candidate_count": sum(1 for row in candidate_rows if row.get("review_valid_for_promotion")),
        "production_activation_allowed": False,
        "live_trading_allowed": False,
        "requires_user_approval": True,
        "dispatch_context": dispatch_context,
        "thresholds": {
            "min_cagr_delta_pp": float(getattr(args, "min_cagr_delta_pp", 0.0)),
            "min_is_cagr_delta_pp": float(getattr(args, "min_is_cagr_delta_pp", 0.5)),
            "max_mdd_regression_pp": float(getattr(args, "max_mdd_regression_pp", 1.0)),
            "require_evidence": require_evidence,
        },
        "candidates": candidate_rows,
    }
    if admission is not None:
        payload["comparison_admission"] = admission
        payload.update({name: admission[name] for name in COMPARISON_AUTHORITY_FIELDS})

    return publish_or_block(args, payload)


def publish_report(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    output_error = comparison_output_error(args)
    comparison_admission.require(output_error is None, output_error or "OUTPUT_ADMISSION_PATH_INVALID")
    if 'comparison_publication' not in payload:
        payload = {**payload, 'current_receipt': True, 'schema_version': COMPARISON_SUMMARY_SCHEMA,
                   'comparison_publication': {'schema': PUBLICATION_SCHEMA, 'generation': uuid.uuid4().hex}}
    publish_anchored(args, payload)
    emit_status({"status": payload["status"], "review_valid": payload["review_valid_candidate_count"],
                 "candidates": len(payload["candidates"])})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--candidate-run", action="append", required=True)
    parser.add_argument("--output-dir", default="outputs/ab_result_verifier")
    parser.add_argument("--portfolio", default="concentrated", choices=["main", "concentrated"])
    parser.add_argument("--min-cagr-delta-pp", type=float, default=0.0)
    parser.add_argument("--min-is-cagr-delta-pp", type=float, default=0.5)
    parser.add_argument("--max-mdd-regression-pp", type=float, default=1.0)
    parser.add_argument("--allow-missing-evidence", action="store_true")
    parser.add_argument("--experiment-id", default="", help="Optional self-correction experiment id that produced the candidate run.")
    parser.add_argument("--payload-hash", default="", help="Optional self-correction workflow payload hash for queue closure.")
    parser.add_argument("--workflow-run-id", default="", help="Optional completed GitHub Actions workflow run id.")
    parser.add_argument("--dispatch-run-id", default="", help="Optional review dispatcher run id.")
    parser.add_argument("--comparison-admission-root", default=None, help="Opt-in immutable flat artifact bundle directory.")
    parser.add_argument("--comparison-control-arm", default=None, help="Flat artifact ID of the control arm JSON declaration.")
    parser.add_argument("--comparison-challenger-arm", default=None, help="Flat artifact ID of the single challenger arm JSON declaration.")
    parser.add_argument("--expected-context-sha256", default=None, help="Independently pinned caller context hash; never derived from either arm.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        payload = run(parse_args(argv))
    except comparison_admission.AdmissionError as exc:
        emit_status({"status": "blocked_comparison_admission", "reason": str(exc)})
        return 2
    return 2 if payload["status"] in ("blocked_comparison_admission", "comparison_publication_uncertain") else 0


if __name__ == "__main__":
    raise SystemExit(main())
