#!/usr/bin/env python3
"""Aggregate AlphaOps pre-fullrun gates into one read-only verdict.

This is stricter than the daily price freshness check. It answers whether the
current branch has enough evidence to justify asking a human to dispatch one
integration fullrun. The tool never dispatches workflows and never mutates
production state.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


W1_MAX_WEIGHT_DELTA = 1e-9
MAIN_CAGR_TARGET = 0.35
CONCENTRATED_CAGR_TARGET = 0.50
MAX_DD_TARGET = -0.25


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_invalid_json": str(exc), "_path": str(path)}


def read_policy_combo_dir(path: Path | None) -> dict[str, Any]:
    if path is None or not str(path):
        return {"_missing": True, "_path": ""}
    if not path.exists():
        return {"_missing": True, "_path": str(path)}
    if path.is_file():
        return read_json(path)
    return {
        "status": "loaded_from_broker_metric_dir",
        "path": str(path),
        "main": read_json(path / "broker_main_cash_carry" / "metrics.json"),
        "concentrated": read_json(path / "broker_concentrated_cash_carry" / "metrics.json"),
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "pass", "ready", "ok"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _dict_values(raw: Any) -> list[Any]:
    if isinstance(raw, dict):
        return list(raw.values())
    if isinstance(raw, list):
        return raw
    return [raw]


def _all_zero(raw: Any) -> bool:
    return all(_number(v, default=999999.0) == 0.0 for v in _dict_values(raw))


def _max_abs_value(raw: Any) -> float:
    values = [_number(v, default=999999.0) for v in _dict_values(raw)]
    return max((abs(v) for v in values), default=999999.0)


def _missing_or_invalid(payload: dict[str, Any]) -> str:
    if payload.get("_missing"):
        return "missing"
    if payload.get("_invalid_json"):
        return "invalid_json"
    return ""


def evaluate_price_gate(price_readiness: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problem = _missing_or_invalid(price_readiness)
    if problem:
        return {"status": problem, "fullrun_ready": False}, [f"price_readiness_{problem}"]
    ready = bool(price_readiness.get("fullrun_ready"))
    blockers = [] if ready else ["price_readiness_not_ready"]
    blockers.extend([f"price_{b}" for b in price_readiness.get("blockers") or []])
    return {
        "status": price_readiness.get("status"),
        "fullrun_ready": ready,
        "blockers": price_readiness.get("blockers") or [],
        "required_price_tickers": price_readiness.get("required_price_tickers") or [],
        "required_experiment_env": price_readiness.get("required_experiment_env") or {},
    }, blockers


def evaluate_w1_gate(control_repro: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problem = _missing_or_invalid(control_repro)
    if problem:
        return {"status": problem, "passes_required_gate": False}, [f"target_book_control_repro_{problem}"]
    acceptance = control_repro.get("acceptance") or {}
    explicit_pass = bool(acceptance.get("passes_required_gate"))
    exact_counts = (
        _all_zero(acceptance.get("official_only_date_count"))
        and _all_zero(acceptance.get("generated_only_date_count"))
        and _all_zero(acceptance.get("ticker_mismatch_date_count"))
        and _max_abs_value(acceptance.get("max_weight_delta_abs")) <= W1_MAX_WEIGHT_DELTA
    )
    passed = explicit_pass or exact_counts
    summary = {
        "status": control_repro.get("status"),
        "passes_required_gate": passed,
        "official_only_date_count": acceptance.get("official_only_date_count"),
        "generated_only_date_count": acceptance.get("generated_only_date_count"),
        "ticker_mismatch_date_count": acceptance.get("ticker_mismatch_date_count"),
        "max_weight_delta_abs": acceptance.get("max_weight_delta_abs"),
        "threshold_max_weight_delta_abs": W1_MAX_WEIGHT_DELTA,
        "reason": acceptance.get("reason") or control_repro.get("root_cause_assessment", {}).get("primary_cause"),
    }
    return summary, ([] if passed else ["target_book_control_repro_not_exact"])


def same_machine_control_exact(control_repro: dict[str, Any]) -> bool:
    same_machine = control_repro.get("same_machine_double_reproduction") or {}
    main = same_machine.get("main") or {}
    concentrated = same_machine.get("concentrated") or {}
    return bool(main.get("exact_control_reproduced") and concentrated.get("exact_control_reproduced"))


def evaluate_policy_combo_gate(policy_combo: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problem = _missing_or_invalid(policy_combo)
    if problem:
        return {"status": problem, "research_pass": False}, []

    main = policy_combo.get("main") or {}
    concentrated = policy_combo.get("concentrated") or {}
    if main.get("_missing") or concentrated.get("_missing"):
        return {
            "status": "missing_metrics",
            "research_pass": False,
            "main_status": _missing_or_invalid(main),
            "concentrated_status": _missing_or_invalid(concentrated),
        }, ["policy_path_combo_metrics_missing"]

    def metric_summary(metrics: dict[str, Any], cagr_target: float) -> dict[str, Any]:
        cagr = _number(metrics.get("cagr"), default=-999.0)
        max_dd = _number(metrics.get("max_dd"), default=-999.0)
        return {
            "metric_mode": str(metrics.get("metric_mode") or ""),
            "cagr": cagr,
            "max_dd": max_dd,
            "sharpe": metrics.get("sharpe"),
            "years": metrics.get("years"),
            "end_date": metrics.get("end_date"),
            "end_date_matches_official": bool(metrics.get("end_date_matches_official")),
            "production_activation_allowed": bool(metrics.get("production_activation_allowed")),
            "target_pass": cagr >= cagr_target and max_dd >= MAX_DD_TARGET,
        }

    main_summary = metric_summary(main, MAIN_CAGR_TARGET)
    concentrated_summary = metric_summary(concentrated, CONCENTRATED_CAGR_TARGET)
    blockers: list[str] = []
    for label, summary in (("main", main_summary), ("concentrated", concentrated_summary)):
        if summary["metric_mode"] != "broker_ledger_next_close_cash_carry":
            blockers.append(f"policy_combo_{label}_invalid_metric_mode")
        if _number(summary.get("years"), default=0.0) < 7.0:
            blockers.append(f"policy_combo_{label}_invalid_window")
        if not summary["end_date_matches_official"]:
            blockers.append(f"policy_combo_{label}_end_date_mismatch")
        if summary["production_activation_allowed"]:
            blockers.append(f"policy_combo_{label}_production_activation_allowed")
        if not summary["target_pass"]:
            blockers.append(f"policy_combo_{label}_target_not_met")

    research_pass = not blockers
    return {
        "status": "research_pass_policy_path_combo" if research_pass else "blocked",
        "research_pass": research_pass,
        "path": policy_combo.get("path"),
        "main": main_summary,
        "concentrated": concentrated_summary,
        "blockers": blockers,
    }, [f"policy_path_{b}" for b in blockers]


def evaluate_replacement_gate(replacement_readiness: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problem = _missing_or_invalid(replacement_readiness)
    if problem:
        return {"status": problem, "fullrun_allowed": False}, [f"replacement_quality_readiness_{problem}"]
    blockers = list(replacement_readiness.get("blockers") or [])
    fullrun_allowed = bool(replacement_readiness.get("fullrun_allowed")) and not blockers
    summary = {
        "status": replacement_readiness.get("status"),
        "fullrun_allowed": fullrun_allowed,
        "blockers": blockers,
        "verdict": replacement_readiness.get("verdict"),
        "control_reproduced": (replacement_readiness.get("control_reproduction") or {}).get("control_reproduced"),
        "hook_is_subset_of_fixed": (replacement_readiness.get("swap_diff") or {}).get("hook_is_subset_of_fixed"),
    }
    return summary, ([] if fullrun_allowed else ["replacement_quality_not_fullrun_ready", *[f"replacement_{b}" for b in blockers]])


def evaluate_main_gate(main_hedge_off: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    problem = _missing_or_invalid(main_hedge_off)
    if problem:
        return {"status": problem, "quote_long_only_allowed": False}, [f"main_hedge_off_baseline_{problem}"]
    quote_allowed = bool(main_hedge_off.get("quote_long_only_allowed"))
    target_pass = bool(main_hedge_off.get("main_cash_carry_target_pass"))
    summary = {
        "status": main_hedge_off.get("status"),
        "quote_long_only_allowed": quote_allowed,
        "main_cash_carry_target_pass": target_pass,
        "hedge_off_cash_carry_cagr": main_hedge_off.get("hedge_off_cash_carry_cagr"),
        "hedge_off_cash_carry_max_dd": main_hedge_off.get("hedge_off_cash_carry_max_dd"),
        "main_cash_carry_cagr_shortfall_pp": main_hedge_off.get("main_cash_carry_cagr_shortfall_pp"),
        "main_cash_carry_mdd_margin_pp": main_hedge_off.get("main_cash_carry_mdd_margin_pp"),
        "end_date_matches_official": main_hedge_off.get("end_date_matches_official"),
    }
    blockers: list[str] = []
    if not quote_allowed:
        blockers.append("main_long_only_quote_not_allowed")
    if not target_pass:
        blockers.append("main_long_only_cash_carry_target_not_met")
    return summary, blockers


def evaluate_earnings_gate(earnings_coverage: dict[str, Any], *, required: bool) -> tuple[dict[str, Any], list[str]]:
    problem = _missing_or_invalid(earnings_coverage)
    if problem:
        return {"status": problem, "research_ready": False, "required": required}, [f"earnings_guidance_coverage_{problem}"] if required else []
    research_ready = bool(earnings_coverage.get("research_ready"))
    summary = {
        "status": earnings_coverage.get("status"),
        "required": required,
        "research_ready": research_ready,
        "plumbing_ready": earnings_coverage.get("plumbing_ready"),
        "service_ready": earnings_coverage.get("service_ready"),
        "policy_ready": earnings_coverage.get("policy_ready"),
        "coverage_eligible_rows": earnings_coverage.get("coverage_eligible_rows"),
        "coverage_eligible_tickers": earnings_coverage.get("coverage_eligible_tickers"),
        "actuals_context_available": earnings_coverage.get("actuals_context_available"),
        "proxy_context_available": earnings_coverage.get("proxy_context_available"),
    }
    return summary, ([] if (research_ready or not required) else ["earnings_guidance_not_research_ready"])


def evaluate_universe_gate(universe_status: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    problem = _missing_or_invalid(universe_status)
    if problem:
        return {"status": problem, "pit_universe_label_clean": False}, [f"universe_health_{problem}"], ["pit_universe_label_clean_false"]
    status = str(universe_status.get("status") or "").lower()
    pit_clean = bool(universe_status.get("pit_universe_label_clean") or universe_status.get("historical_universe_pit_clean"))
    health_ok = status in {"ok", "pass", "passed", "ready", "valid", "completed"} and not universe_status.get("blockers")
    summary = {
        "status": universe_status.get("status"),
        "health_ok": health_ok,
        "pit_universe_label_clean": pit_clean,
        "blockers": universe_status.get("blockers") or [],
        "primary_universe_source": universe_status.get("primary_universe_source"),
        "r1000_base_count": universe_status.get("r1000_base_count"),
        "candidate_count": universe_status.get("candidate_count"),
    }
    blockers = [] if health_ok else ["universe_health_not_ready"]
    production_blockers = [] if pit_clean else ["pit_universe_label_clean_false"]
    return summary, blockers, production_blockers


def evaluate(
    *,
    price_readiness: dict[str, Any],
    control_repro: dict[str, Any],
    replacement_readiness: dict[str, Any],
    main_hedge_off: dict[str, Any],
    policy_combo: dict[str, Any] | None,
    earnings_coverage: dict[str, Any],
    universe_status: dict[str, Any],
    require_earnings_research_ready: bool = True,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    blockers: list[str] = []
    production_blockers: list[str] = []

    checks["price_readiness"], new_blockers = evaluate_price_gate(price_readiness)
    blockers.extend(new_blockers)
    checks["target_book_control_repro"], new_blockers = evaluate_w1_gate(control_repro)
    w1_blockers = new_blockers
    checks["policy_path_combo"], policy_combo_blockers = evaluate_policy_combo_gate(policy_combo or {"_missing": True})
    policy_combo_pass = bool(checks["policy_path_combo"].get("research_pass"))
    if policy_combo_pass and same_machine_control_exact(control_repro):
        checks["target_book_control_repro"]["official_dirty_mismatch_non_blocking"] = True
        checks["target_book_control_repro"]["non_blocking_reason"] = (
            "current clean-code same-machine reproduction is exact and the frozen "
            "policy-path combo candidate passed broker replay; old dirty official "
            "mismatch is retained as provenance context, not a fullrun blocker"
        )
    else:
        blockers.extend(w1_blockers)
    blockers.extend(policy_combo_blockers)
    checks["replacement_quality"], new_blockers = evaluate_replacement_gate(replacement_readiness)
    if policy_combo_pass:
        checks["replacement_quality"]["superseded_by_policy_path_combo"] = True
    else:
        blockers.extend(new_blockers)
    checks["main_long_only"], new_blockers = evaluate_main_gate(main_hedge_off)
    if policy_combo_pass:
        checks["main_long_only"]["superseded_by_policy_path_combo"] = True
    else:
        blockers.extend(new_blockers)
    checks["earnings_guidance"], new_blockers = evaluate_earnings_gate(
        earnings_coverage,
        required=require_earnings_research_ready,
    )
    blockers.extend(new_blockers)
    checks["universe_health"], new_blockers, new_prod_blockers = evaluate_universe_gate(universe_status)
    blockers.extend(new_blockers)
    production_blockers.extend(new_prod_blockers)

    unique_blockers = sorted(dict.fromkeys(blockers))
    unique_production_blockers = sorted(dict.fromkeys(production_blockers))
    preconditions_ready = not unique_blockers
    return {
        "schema_version": "alphaops-prefullrun-gate-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ready_for_user_approval" if preconditions_ready else "blocked",
        "research_fullrun_preconditions_ready": preconditions_ready,
        "fullrun_dispatch_allowed": False,
        "dispatch_requires_explicit_user_approval": True,
        "blockers": unique_blockers,
        "production_promotion_allowed": False,
        "production_blockers": unique_production_blockers,
        "checks": checks,
        "next_action": "request_user_approval_for_one_fullrun" if preconditions_ready else "finish_prefullrun_blockers",
        "claude_question_required": False,
        "claude_question": "",
        "non_mutating": True,
        "live_trading_enabled": False,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = ["# AlphaOps Pre-Fullrun Gate", ""]
    lines.append(f"- status: `{payload.get('status')}`")
    lines.append(f"- research_fullrun_preconditions_ready: `{str(payload.get('research_fullrun_preconditions_ready')).lower()}`")
    lines.append(f"- fullrun_dispatch_allowed: `{str(payload.get('fullrun_dispatch_allowed')).lower()}`")
    lines.append(f"- next_action: `{payload.get('next_action')}`")
    lines.append(f"- blockers: `{', '.join(payload.get('blockers') or []) or 'none'}`")
    lines.append(f"- production_blockers: `{', '.join(payload.get('production_blockers') or []) or 'none'}`")
    lines.append("")
    lines.append("## Check Summary")
    lines.append("")
    for name, check in (payload.get("checks") or {}).items():
        lines.append(f"### {name}")
        if isinstance(check, dict):
            for key, value in check.items():
                lines.append(f"- {key}: `{value}`")
        lines.append("")
    lines.append("## Claude Question")
    lines.append("")
    if payload.get("claude_question_required"):
        lines.append(str(payload.get("claude_question") or ""))
    else:
        lines.append("No new Claude question is required. The current blockers are mechanical and should be fixed before another review round.")
    lines.append("")
    lines.append("No workflow dispatch, live trading, or production promotion is performed by this gate.")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-readiness", default="outputs/fullrun_readiness/summary.json")
    parser.add_argument("--control-repro", default="outputs/target_book_control_repro_root_cause/summary.json")
    parser.add_argument(
        "--replacement-readiness",
        default="outputs/replacement_quality_readiness_audit_28616190134_allowlist_v2/summary.json",
    )
    parser.add_argument("--main-hedge-off", default="outputs/main_hedge_off_baseline/metrics.json")
    parser.add_argument("--policy-combo-dir", default="")
    parser.add_argument("--earnings-coverage", default="outputs/earnings_guidance_coverage/summary.json")
    parser.add_argument("--universe-status", default="outputs/p2_pit_membership_status_28616190134/summary.json")
    parser.add_argument("--output-dir", default="outputs/prefullrun_gate")
    parser.add_argument("--skip-earnings-research-gate", action="store_true")
    args = parser.parse_args()

    payload = evaluate(
        price_readiness=read_json(Path(args.price_readiness)),
        control_repro=read_json(Path(args.control_repro)),
        replacement_readiness=read_json(Path(args.replacement_readiness)),
        main_hedge_off=read_json(Path(args.main_hedge_off)),
        policy_combo=read_policy_combo_dir(Path(args.policy_combo_dir)) if args.policy_combo_dir else None,
        earnings_coverage=read_json(Path(args.earnings_coverage)),
        universe_status=read_json(Path(args.universe_status)),
        require_earnings_research_ready=not args.skip_earnings_research_gate,
    )
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(render_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
