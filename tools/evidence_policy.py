#!/usr/bin/env python3
"""Classify broker-ledger evidence into explicit operating tiers.

The policy separates clean 7-year research evidence from official promotion
evidence. A short but clean broker-ledger run can support Alpha Plane audit and
A/B work; dirty inputs remain DO_NOT_USE regardless of length.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


OFFICIAL_METRIC_MODE = "broker_ledger_next_close"
MIN_RESEARCH_YEARS = 7.0
MIN_ROBUST_YEARS = 8.0
MIN_R1000_BASE = 400

TIER0 = "0_do_not_use"
TIER1 = "1_research_7y"
TIER2 = "2_operating_candidate"
TIER3 = "3_robust_candidate"
TIER4 = "4_official_promotion"

LABELS = {
    TIER0: "do_not_use",
    TIER1: "research_7y",
    TIER2: "operating_candidate",
    TIER3: "robust_candidate",
    TIER4: "official_promotion",
}

ALLOWED_BY_TIER = {
    TIER0: ["diagnostics"],
    TIER1: ["audit", "ab_research", "daily_preview_diagnostics"],
    TIER2: ["audit", "ab_research", "daily_operating_preview", "ready_for_human_review"],
    TIER3: ["audit", "ab_research", "daily_operating_preview", "ready_for_human_review", "robust_human_review"],
    TIER4: ["audit", "ab_research", "daily_operating_preview", "ready_for_human_review", "promotion_review"],
}

BLOCKED_BY_TIER = {
    TIER0: ["audit", "ab_research", "daily_operating_preview", "ready_for_human_review", "promotion", "live_trading"],
    TIER1: ["official_promotion", "automatic_production_mutation", "live_trading"],
    TIER2: ["official_promotion", "automatic_production_mutation", "live_trading"],
    TIER3: ["automatic_promotion", "automatic_production_mutation", "live_trading"],
    TIER4: ["automatic_promotion", "automatic_production_mutation", "live_trading_without_user_approval"],
}

PASS_STATUSES = {"ok", "pass", "passed", "ready", "completed", "production_evidence_ready"}
FAIL_STATUSES = {"blocked", "failed", "fail", "invalid", "invalid_window", "not_ready", "do_not_use"}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


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
    out = safe_float(value)
    return default if out is None else int(out)


def status_text(value: Any) -> str:
    return str(value or "").strip().lower()


def status_failed(value: Any) -> bool:
    text = status_text(value)
    return bool(text) and (text in FAIL_STATUSES or text.startswith("invalid"))


def csv_row_count(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            rows = sum(1 for _ in reader)
        return max(0, rows - 1)
    except Exception:
        return None


def load_universe_health(run_dir: Path) -> dict[str, Any]:
    for path in (
        run_dir / "universe_health" / "universe_source_audit.json",
        run_dir / "universe_health" / "summary.json",
    ):
        payload = read_json(path)
        if payload:
            payload["_source_path"] = str(path)
            return payload
    return {}


def load_proxy_robustness(run_dir: Path) -> dict[str, Any]:
    for path in (
        run_dir / "evidence_policy" / "proxy_10y_robustness.json",
        run_dir / "proxy_10y_robustness" / "summary.json",
        run_dir / "ten_year_backtest_readiness" / "summary.json",
    ):
        payload = read_json(path)
        if payload:
            payload["_source_path"] = str(path)
            return payload
    return {}


def load_pre_broker_substrate_gate(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "pre_broker_substrate_gate" / "summary.json"
    payload = read_json(path)
    if payload:
        payload["_source_path"] = str(path)
    return payload


def portfolio_items(official: dict[str, Any], run_dir: Path) -> dict[str, dict[str, Any]]:
    nested = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    names = sorted(set(nested.keys()) | {"main", "concentrated"})
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        row = nested.get(name) if isinstance(nested.get(name), dict) else {}
        broker = read_json(run_dir / "broker_replay" / name / "metrics.json")
        merged = {**broker, **row}
        if merged:
            out[name] = merged
    return out


def official_mode_for(official: dict[str, Any], portfolios: dict[str, dict[str, Any]]) -> str:
    mode = str(official.get("official_metric_mode") or official.get("metric_mode") or "")
    if mode:
        return mode
    for row in portfolios.values():
        mode = str(row.get("official_metric_mode") or row.get("metric_mode") or "")
        if mode:
            return mode
    return ""


def portfolio_years(row: dict[str, Any]) -> float | None:
    years = safe_float(row.get("years"))
    if years is not None:
        return years
    gate = row.get("broker_ledger_window_gate") if isinstance(row.get("broker_ledger_window_gate"), dict) else {}
    return safe_float(gate.get("years"))


def portfolio_trading_days(row: dict[str, Any]) -> int | None:
    for key in ("broker_ledger_actual_trading_days", "broker_ledger_trading_days_estimate", "days", "trading_days"):
        value = safe_int(row.get(key))
        if value is not None:
            return value
    gate = row.get("broker_ledger_window_gate") if isinstance(row.get("broker_ledger_window_gate"), dict) else {}
    return safe_int(gate.get("actual_trading_days"), safe_int(gate.get("trading_days_estimate")))


def data_readiness_pass(readiness: dict[str, Any], reasons: list[str]) -> bool:
    if not readiness:
        reasons.append("data_readiness_missing")
        return False
    if readiness.get("ready_for_policy_replay") is not True:
        reasons.append("data_readiness_not_ready_for_policy_replay")
        return False
    if status_failed(readiness.get("status")):
        reasons.append(f"data_readiness_status={readiness.get('status')}")
        return False
    known_gaps = ((readiness.get("free_data_coverage") or {}).get("known_gaps") or [])
    if known_gaps:
        reasons.append("free_data_coverage_known_gaps")
        return False
    return True


def universe_pass(universe: dict[str, Any], reasons: list[str]) -> bool:
    if not universe:
        reasons.append("universe_health_missing")
        return False
    count = safe_int(universe.get("r1000_base_count"), safe_int(universe.get("scored_r1000_base")))
    floor = safe_int(universe.get("min_r1000_base"), MIN_R1000_BASE) or MIN_R1000_BASE
    if count is not None and count < floor:
        reasons.append(f"universe_starved:{count}<{floor}")
        return False
    if universe.get("promotion_allowed") is False:
        reasons.append("universe_health_promotion_allowed=false")
        return False
    if status_failed(universe.get("status")):
        reasons.append(f"universe_health_status={universe.get('status')}")
        return False
    return True


def cash_trap_state(run_dir: Path) -> tuple[bool | None, list[str]]:
    payload = read_json(run_dir / "cash_reentry_quality" / "summary.json")
    if not payload:
        return None, ["cash_trap_evidence_missing"]
    flags: list[str] = []
    if payload.get("cash_trap_flag") is True:
        flags.append("cash_trap_flag=true")
    rows = safe_int(payload.get("cash_trap_rows"), 0) or 0
    if rows > 0:
        flags.append(f"cash_trap_rows={rows}")
    portfolio_payload = payload.get("portfolios") if isinstance(payload.get("portfolios"), dict) else {}
    for portfolio, item in portfolio_payload.items():
        if isinstance(item, dict) and item.get("cash_trap_flag") is True:
            flags.append(f"{portfolio}.cash_trap_flag=true")
    return (not flags), flags


def daily_output_state(user_current_dir: Path | None) -> tuple[bool | None, list[str]]:
    if user_current_dir is None:
        return None, ["daily_output_not_present"]
    if not user_current_dir.exists():
        return None, ["daily_output_not_present"]
    reasons: list[str] = []
    summary = read_json(user_current_dir / "summary.json")
    decision = read_json(user_current_dir / "08_rebalance_decision.json")
    contract = read_json(user_current_dir / "09_daily_output_contract_summary.json")
    current_rows = csv_row_count(user_current_dir / "01_current_holdings.csv")
    target_rows = csv_row_count(user_current_dir / "02_target_weights.csv")
    order_rows = csv_row_count(user_current_dir / "03_order_preview.csv")

    if current_rows is not None and current_rows <= 0:
        reasons.append("current_holdings_empty")
    if target_rows is not None and target_rows <= 0:
        reasons.append("target_weights_empty")
    if order_rows is not None and order_rows < 0:
        reasons.append("order_preview_invalid")
    if summary:
        if summary.get("current_holdings_missing") is True:
            reasons.append("current_holdings_missing")
        if summary.get("valid_for_production") is True and summary.get("production_promotion_allowed") is not True:
            reasons.append("user_current_valid_for_production_inconsistent")
    for source_name, source in (("rebalance_decision", decision), ("daily_contract", contract)):
        if not source:
            continue
        if source.get("live_trading_enabled") is True:
            reasons.append(f"{source_name}.live_trading_enabled=true")
        if source.get("production_mutation_allowed") is True:
            reasons.append(f"{source_name}.production_mutation_allowed=true")
        if source.get("canonical_production_sync") is True:
            reasons.append(f"{source_name}.canonical_production_sync=true")
        if source.get("human_approval_required") is False:
            reasons.append(f"{source_name}.human_approval_required=false")
        if source_name == "daily_contract" and source.get("current_snapshot_used_for_order_preview") is False:
            reasons.append("daily_contract.current_snapshot_used_for_order_preview=false")
    return (not reasons), reasons


def proxy_10y_pass(payload: dict[str, Any], reasons: list[str]) -> bool:
    if not payload:
        reasons.append("proxy_10y_robustness_missing")
        return False
    if payload.get("proxy_10y_robustness_pass") is True:
        return True
    if payload.get("official_10y_ready") is True and payload.get("proxy_10y_price_ready") is True:
        return True
    reasons.append("proxy_10y_robustness_not_passed")
    return False


def pre_broker_gate_pass(payload: dict[str, Any], reasons: list[str]) -> bool | None:
    if not payload:
        return None
    blockers = payload.get("blockers") if isinstance(payload.get("blockers"), list) else []
    if payload.get("broker_replay_allowed") is False or status_failed(payload.get("status")) or blockers:
        reasons.append("pre_broker_substrate_gate_blocked")
        reasons.extend(f"pre_broker:{item}" for item in blockers)
        return False
    return True


def classify_evidence(
    run_dir: str | Path,
    *,
    user_current_dir: str | Path | None = None,
    official_metrics_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_path = repo_path(run_dir)
    user_current_path = repo_path(user_current_dir) if user_current_dir is not None else (
        run_path / "user_current" if (run_path / "user_current").exists() else None
    )
    official_path = run_path / "account_evaluation" / "official_metrics.json"
    official = official_metrics_override if isinstance(official_metrics_override, dict) and official_metrics_override else read_json(official_path)
    portfolios = portfolio_items(official, run_path)
    readiness = read_json(run_path / "data_readiness" / "summary.json")
    universe = load_universe_health(run_path)
    proxy = load_proxy_robustness(run_path)
    pre_broker_gate = load_pre_broker_substrate_gate(run_path)
    tier0: list[str] = []
    reasons: list[str] = []

    if not official:
        tier0.append("official_broker_metric_missing")
    mode = official_mode_for(official, portfolios)
    if mode != OFFICIAL_METRIC_MODE:
        tier0.append(f"official_metric_mode_not_broker_ledger_next_close:{mode or 'missing'}")
    if not portfolios:
        tier0.append("broker_portfolio_metrics_missing")
    for name, row in portfolios.items():
        if status_text(row.get("status") or "missing") != "completed":
            tier0.append(f"{name}.broker_replay_status={row.get('status') or 'missing'}")
        row_mode = str(row.get("official_metric_mode") or row.get("metric_mode") or mode or "")
        if row_mode != OFFICIAL_METRIC_MODE:
            tier0.append(f"{name}.metric_mode={row_mode or 'missing'}")

    if not data_readiness_pass(readiness, tier0):
        pass
    if not universe_pass(universe, tier0):
        pass

    pre_broker_reasons: list[str] = []
    pre_broker_ok = pre_broker_gate_pass(pre_broker_gate, pre_broker_reasons)
    if pre_broker_ok is False:
        tier0.extend(pre_broker_reasons)

    daily_valid, daily_reasons = daily_output_state(user_current_path)
    if daily_valid is False:
        tier0.extend(daily_reasons)

    years_values = [portfolio_years(row) for row in portfolios.values()]
    years_values = [value for value in years_values if value is not None]
    min_years = min(years_values) if years_values else 0.0
    trading_values = [portfolio_trading_days(row) for row in portfolios.values()]
    trading_values = [value for value in trading_values if value is not None]
    min_trading_days = min(trading_values) if trading_values else None

    cash_ok, cash_reasons = cash_trap_state(run_path)
    has_clean_research_window = min_years >= MIN_RESEARCH_YEARS
    has_robust_window = min_years >= MIN_ROBUST_YEARS
    proxy_reasons: list[str] = []
    has_proxy_robustness = proxy_10y_pass(proxy, proxy_reasons)

    all_target_pass = bool(official.get("production_target_pass")) and all(bool(row.get("target_pass")) for row in portfolios.values())
    all_strengthened = bool(official.get("strengthened_pass")) and all(bool(row.get("strengthened_pass")) for row in portfolios.values())
    all_valid_for_production = bool(portfolios) and all(bool(row.get("valid_for_production")) for row in portfolios.values())
    alternative_contract = bool(official.get("alternative_evidence_contract_approved"))
    official_window_pass = has_robust_window and all_valid_for_production
    cash_false_for_promotion = cash_ok is True

    if tier0 or not has_clean_research_window:
        tier = TIER0
        if not has_clean_research_window:
            tier0.append(f"broker_ledger_years_below_7:{min_years:.2f}")
    elif (official_window_pass or alternative_contract) and all_target_pass and all_strengthened and cash_false_for_promotion:
        tier = TIER4
        reasons.append("official_promotion_evidence_pass")
    elif has_robust_window or has_proxy_robustness:
        tier = TIER3
        reasons.append("robust_window_or_proxy_10y_pass")
    elif daily_valid is True and cash_ok is True:
        tier = TIER2
        reasons.append("clean_7y_daily_preview_and_cash_trap_false")
    else:
        tier = TIER1
        reasons.append("clean_7y_research_evidence")
        if daily_valid is not True:
            reasons.extend(daily_reasons)
        if cash_ok is not True:
            reasons.extend(cash_reasons)

    promotion_allowed = tier == TIER4
    payload = {
        "schema_version": "evidence-tier-policy-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(run_path),
        "tier": tier,
        "evidence_label": LABELS[tier],
        "allowed_uses": ALLOWED_BY_TIER[tier],
        "blocked_uses": BLOCKED_BY_TIER[tier],
        "reasons": sorted(set(reasons)),
        "tier0_blockers": sorted(set(tier0)),
        "requires_human_approval": True,
        "production_activation_allowed": False,
        "live_trading_allowed": False,
        "promotion_allowed": promotion_allowed,
        "research_ab_allowed": tier in {TIER1, TIER2, TIER3, TIER4},
        "daily_operating_preview_allowed": tier in {TIER2, TIER3, TIER4},
        "ready_for_human_review_allowed": tier in {TIER2, TIER3, TIER4},
        "official_metric_mode": mode,
        "min_broker_ledger_years": min_years,
        "min_broker_ledger_trading_days": min_trading_days,
        "data_readiness_pass": not any(reason.startswith("data_readiness") or "known_gaps" in reason for reason in tier0),
        "universe_health_pass": not any(reason.startswith("universe") for reason in tier0),
        "cash_trap_false": cash_ok,
        "cash_trap_reasons": cash_reasons,
        "daily_output_valid": daily_valid,
        "daily_output_reasons": daily_reasons,
        "proxy_10y_robustness_pass": has_proxy_robustness,
        "proxy_10y_reasons": proxy_reasons,
        "pre_broker_substrate_gate_pass": pre_broker_ok,
        "pre_broker_substrate_gate_reasons": pre_broker_reasons,
        "valid_for_production_semantics": "promotion_only; false does not invalidate clean Tier 1 research evidence",
        "source_files": {
            "official_metrics": str(official_path),
            "data_readiness": str(run_path / "data_readiness" / "summary.json"),
            "universe_health": str(universe.get("_source_path") or run_path / "universe_health" / "universe_source_audit.json"),
            "user_current": str(user_current_path) if user_current_path is not None else "",
            "cash_reentry_quality": str(run_path / "cash_reentry_quality" / "summary.json"),
            "proxy_10y": str(proxy.get("_source_path") or ""),
            "pre_broker_substrate_gate": str(pre_broker_gate.get("_source_path") or ""),
        },
        "portfolios": {
            name: {
                "status": row.get("status"),
                "metric_mode": row.get("official_metric_mode") or row.get("metric_mode") or mode,
                "valid_for_production": bool(row.get("valid_for_production")),
                "target_pass": bool(row.get("target_pass")),
                "strengthened_pass": bool(row.get("strengthened_pass")),
                "years": portfolio_years(row),
                "trading_days": portfolio_trading_days(row),
                "cagr": safe_float(row.get("cagr")),
                "max_dd": safe_float(row.get("max_dd")),
            }
            for name, row in portfolios.items()
        },
    }
    return payload


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Evidence Policy",
        "",
        f"- tier: `{payload.get('tier')}`",
        f"- evidence_label: `{payload.get('evidence_label')}`",
        f"- research_ab_allowed: `{str(payload.get('research_ab_allowed')).lower()}`",
        f"- daily_operating_preview_allowed: `{str(payload.get('daily_operating_preview_allowed')).lower()}`",
        f"- ready_for_human_review_allowed: `{str(payload.get('ready_for_human_review_allowed')).lower()}`",
        f"- promotion_allowed: `{str(payload.get('promotion_allowed')).lower()}`",
        f"- requires_human_approval: `{str(payload.get('requires_human_approval')).lower()}`",
        "",
        "## Uses",
        "",
        f"- allowed: `{', '.join(payload.get('allowed_uses') or [])}`",
        f"- blocked: `{', '.join(payload.get('blocked_uses') or [])}`",
        "",
        "## Reasons",
        "",
    ]
    reasons = payload.get("reasons") or []
    lines.extend([f"- {item}" for item in reasons] if reasons else ["- none"])
    blockers = payload.get("tier0_blockers") or []
    lines.extend(["", "## Tier 0 Blockers", ""])
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.extend(["", "## Portfolio Evidence", ""])
    lines.append("| Portfolio | Years | Trading Days | Valid For Production | Target Pass | Strengthened Pass | CAGR | MaxDD |")
    lines.append("| --- | ---: | ---: | :---: | :---: | :---: | ---: | ---: |")
    for name, row in (payload.get("portfolios") or {}).items():
        cagr = row.get("cagr")
        max_dd = row.get("max_dd")
        lines.append(
            "| {name} | {years:.2f} | {days} | {vfp} | {target} | {strong} | {cagr} | {mdd} |".format(
                name=name,
                years=safe_float(row.get("years"), 0.0) or 0.0,
                days=row.get("trading_days") or "",
                vfp=str(bool(row.get("valid_for_production"))).lower(),
                target=str(bool(row.get("target_pass"))).lower(),
                strong=str(bool(row.get("strengthened_pass"))).lower(),
                cagr="" if cagr is None else f"{cagr:.2%}",
                mdd="" if max_dd is None else f"{max_dd:.2%}",
            )
        )
    lines.extend(
        [
            "",
            "## Policy Notes",
            "",
            "- Clean 7-year broker-ledger evidence is valid research evidence for Alpha Plane audit and A/B.",
            "- Dirty evidence remains Tier 0 DO_NOT_USE regardless of length.",
            "- `valid_for_production=false` blocks Tier 4 promotion, but does not by itself invalidate clean Tier 1 research evidence.",
            "- proxy 10-year evidence must remain labelled proxy and cannot be called official Russell 1000 evidence.",
            "- Live trading and automatic production mutation remain forbidden without explicit user approval.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    write_json(output_dir / "evidence_status.json", payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--user-current-dir", default="")
    parser.add_argument("--output-dir", default="outputs/evidence_policy")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = classify_evidence(args.latest_run, user_current_dir=args.user_current_dir or None)
    write_outputs(payload, repo_path(args.output_dir))
    print(json.dumps({"tier": payload["tier"], "evidence_label": payload["evidence_label"], "promotion_allowed": payload["promotion_allowed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
