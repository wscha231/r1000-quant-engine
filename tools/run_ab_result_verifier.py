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
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from r1000_config import PORTFOLIO_GOAL_GATES, PORTFOLIO_GOAL_TARGETS
except Exception:  # pragma: no cover - smoke fallback
    PORTFOLIO_GOAL_TARGETS = {
        "main": {"cagr": 0.30, "max_dd": -0.25},
        "concentrated": {"cagr": 0.50, "max_dd": -0.28},
    }
    PORTFOLIO_GOAL_GATES = {
        "main": {"is_cagr_min": 0.25},
        "concentrated": {"is_cagr_min": 0.30},
    }

from tools.evidence_policy import TIER0, TIER1, TIER2, TIER3, TIER4, classify_evidence  # noqa: E402

OFFICIAL_METRIC_MODE = "broker_ledger_next_close"
MIN_BROKER_LEDGER_YEARS = 8.0
MIN_BROKER_LEDGER_TRADING_DAYS = 252 * 8
ATTRIBUTION_REQUIREMENT_ID = "attribution_package_year_mdd_name"
OOS_LOCK_REQUIREMENT_ID = "oos_holdout_lock"


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
        if value in (None, ""):
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
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio, {})
    return {
        "cagr": float(target.get("cagr", 0.30 if portfolio == "main" else 0.50)),
        "max_dd": float(target.get("max_dd", -0.25 if portfolio == "main" else -0.28)),
    }


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
    mode = str(row.get("official_metric_mode") or broker.get("metric_mode") or official.get("official_metric_mode") or "")
    evidence = classify_evidence(run_dir)
    years = safe_float(row.get("years"), safe_float(broker.get("years")))
    trading_days = safe_int(
        row.get("broker_ledger_actual_trading_days"),
        safe_int(row.get("broker_ledger_trading_days_estimate"), safe_int(window_gate.get("trading_days_estimate"), safe_int(broker.get("days")))),
    )
    target = target_for(portfolio)
    cagr = safe_float(row.get("cagr"), safe_float(broker.get("cagr")))
    max_dd = safe_float(row.get("max_dd"), safe_float(broker.get("max_dd")))
    is_cagr = safe_float(row.get("is_cagr"), safe_float(attr_row.get("is_cagr"), safe_float(is_window.get("cagr"))))
    oos_cagr = safe_float(row.get("oos_cagr"), safe_float(attr_row.get("oos_cagr"), safe_float(oos_window.get("cagr"))))
    target_pass = bool(row.get("target_pass"))
    if cagr is not None and max_dd is not None:
        target_pass = target_pass or (cagr >= target["cagr"] and max_dd >= target["max_dd"])

    return {
        "run_dir": str(run_dir),
        "run_label": run_label(run_dir),
        "portfolio": portfolio,
        "official_metrics_path": str(official_path),
        "official_metrics_exists": official_path.exists(),
        "broker_metrics_path": str(broker_path),
        "broker_metrics_exists": broker_path.exists(),
        "system_acceptance_path": str(system_path),
        "system_acceptance_exists": system_path.exists(),
        "is_attribution_path": str(is_attr_path),
        "is_attribution_exists": is_attr_path.exists(),
        "oos_lock_path": str(oos_lock_path),
        "oos_lock_exists": oos_lock_path.exists(),
        "official_metric_mode": mode,
        "evidence_tier": evidence.get("tier"),
        "evidence_label": evidence.get("evidence_label"),
        "evidence_allowed_uses": list(evidence.get("allowed_uses") or []),
        "evidence_blocked_uses": list(evidence.get("blocked_uses") or []),
        "evidence_reasons": list(evidence.get("reasons") or []),
        "evidence_tier0_blockers": list(evidence.get("tier0_blockers") or []),
        "research_ab_allowed": bool(evidence.get("research_ab_allowed")),
        "ready_for_human_review_allowed": bool(evidence.get("ready_for_human_review_allowed")),
        "evidence_promotion_allowed": bool(evidence.get("promotion_allowed")),
        "status": row.get("status") or broker.get("status") or "missing",
        "valid_for_production": bool(row.get("valid_for_production", broker.get("valid_for_production", False))),
        "target_pass": target_pass,
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
    if candidate.get("official_metric_mode") != OFFICIAL_METRIC_MODE:
        return "invalid_official_metrics", [f"official_metric_mode:{candidate.get('official_metric_mode') or 'missing'}"]
    if candidate.get("system_acceptance_production_activation_allowed") is True:
        return "reject_unsafe_production_activation", ["system_acceptance_production_activation_allowed_true"]
    evidence_tier = str(candidate.get("evidence_tier") or "")
    if evidence_tier == TIER0:
        return "do_not_use_evidence_tier", list(candidate.get("evidence_tier0_blockers") or ["tier0_do_not_use"])
    if evidence_tier not in {TIER1, TIER2, TIER3, TIER4} and not window_is_valid(candidate):
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

    if evidence_tier == TIER1:
        return "measured_research_7y", []
    if evidence_tier == TIER2:
        return "ready_for_human_review", []
    if evidence_tier == TIER3:
        return "robust_candidate_review_only", []

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

    return "promote_candidate_review_only" if evidence_tier == TIER4 else "robust_candidate_review_only", []


def verdict_rank(decision: str) -> int:
    if decision in {"promote_candidate_review_only", "robust_candidate_review_only", "ready_for_human_review"}:
        return 0
    if decision == "measured_research_7y":
        return 1
    if decision.startswith("blocked"):
        return 2
    return 3


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
        "ready_for_human_review": decision in {"ready_for_human_review", "robust_candidate_review_only", "promote_candidate_review_only"},
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
        "| Candidate | Tier | Decision | CAGR | MDD | IS-CAGR | OOS/IS | CAGR vs Base | IS vs Base | MDD vs Base | Issues |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in payload.get("candidates") or []:
        lines.append(
            "| {run} | `{tier}` | `{decision}` | {cagr} | {mdd} | {is_cagr} | {oos_ratio} | {dcagr}pp | {dis}pp | {dmdd}pp | {issues} |".format(
                run=row.get("run_label"),
                tier=row.get("evidence_tier") or "",
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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "experiment_id",
        "payload_hash",
        "workflow_run_id",
        "dispatch_run_id",
        "candidate_run",
        "run_label",
        "decision",
        "evidence_tier",
        "evidence_label",
        "review_valid_for_promotion",
        "ready_for_human_review",
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["issues"] = ";".join(str(item) for item in row.get("issues") or [])
            writer.writerow(out)


def run(args: argparse.Namespace) -> dict[str, Any]:
    portfolio = str(getattr(args, "portfolio", "concentrated"))
    baseline = collect_evidence(repo_path(args.baseline_run), portfolio)
    baseline_ok = baseline.get("official_metrics_exists") and baseline.get("official_metric_mode") == OFFICIAL_METRIC_MODE
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
    elif any(decision in {"ready_for_human_review", "robust_candidate_review_only"} for decision in decisions):
        status = "human_review_candidate_ready"
    elif any(decision == "measured_research_7y" for decision in decisions):
        status = "measured_research_7y"
    elif any(decision.startswith("blocked") for decision in decisions):
        status = "blocked"
    else:
        status = "rejected"

    payload = {
        "schema_version": "ab-result-verifier-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "portfolio": portfolio,
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

    output_dir = repo_path(getattr(args, "output_dir", "outputs/ab_result_verifier"))
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    write_csv(output_dir / "candidate_verdicts.csv", candidate_rows)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": status, "review_valid": payload["review_valid_candidate_count"], "candidates": len(candidate_rows)}, indent=2))
    return payload


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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
