#!/usr/bin/env python3
"""Decide whether a clean 7-year broker-ledger run can be used for research.

This is deliberately not a promotion gate. It converts the evidence-tier
policy plus daily snapshot/cash audit checks into a machine-readable
``clean_7y_research_ready`` artifact that can unblock Alpha Plane audit and
A/B research without pretending that 7Y evidence is official production proof.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_policy import (  # noqa: E402
    OFFICIAL_METRIC_MODE,
    TIER0,
    TIER1,
    TIER2,
    TIER3,
    TIER4,
    classify_evidence,
    read_json,
    repo_path,
    safe_float,
    write_json,
)

READY = "clean_7y_research_ready"
NOT_READY = "not_ready"
ALLOWED_RESEARCH_USES = ["alpha_plane_audit", "alpha_plane_ab_research", "daily_operating_preview"]
ALWAYS_BLOCKED_USES = ["official_promotion", "live_trading", "production_mutation"]


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes", "pass", "passed", "ready", "ok"}


def _load_first(paths: list[Path]) -> tuple[dict[str, Any], Path | None]:
    for path in paths:
        payload = read_json(path)
        if payload:
            return payload, path
    return {}, None


def _official_metric_mode(evidence: dict[str, Any], official: dict[str, Any]) -> str:
    return str(evidence.get("official_metric_mode") or official.get("official_metric_mode") or official.get("metric_mode") or "")


def _portfolio_years(evidence: dict[str, Any], official: dict[str, Any]) -> float:
    value = safe_float(evidence.get("min_broker_ledger_years"), 0.0) or 0.0
    if value:
        return value
    portfolios = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    years = []
    for row in portfolios.values():
        if not isinstance(row, dict):
            continue
        candidate = safe_float(row.get("years"))
        if candidate is None:
            gate = row.get("broker_ledger_window_gate") if isinstance(row.get("broker_ledger_window_gate"), dict) else {}
            candidate = safe_float(gate.get("years"))
        if candidate is not None:
            years.append(candidate)
    return min(years) if years else 0.0


def _data_readiness_ready(run_dir: Path, evidence: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    payload = read_json(run_dir / "data_readiness" / "summary.json")
    ready = payload.get("ready_for_policy_replay") is True and str(payload.get("status", "")).lower() not in {"blocked", "failed", "invalid"}
    if "data_readiness_pass" in evidence:
        ready = ready and evidence.get("data_readiness_pass") is True
    return ready, payload, str(run_dir / "data_readiness" / "summary.json")


def _universe_healthy(run_dir: Path, evidence: dict[str, Any]) -> tuple[bool, dict[str, Any], str]:
    payload, path = _load_first([
        run_dir / "universe_health" / "universe_source_audit.json",
        run_dir / "universe_health" / "summary.json",
    ])
    healthy = bool(payload)
    if payload.get("promotion_allowed") is False:
        healthy = False
    status = str(payload.get("status", "")).lower()
    if status in {"invalid_universe", "blocked", "failed", "invalid", "do_not_use"}:
        healthy = False
    count = payload.get("r1000_base_count", payload.get("scored_r1000_base"))
    floor = payload.get("min_r1000_base", 400)
    try:
        if count is not None and int(float(count)) < int(float(floor)):
            healthy = False
    except (TypeError, ValueError):
        pass
    if "universe_health_pass" in evidence:
        healthy = healthy and evidence.get("universe_health_pass") is True
    return healthy, payload, str(path or run_dir / "universe_health" / "universe_source_audit.json")


def _daily_snapshot_pass(run_dir: Path, user_current_dir: str | Path | None = None) -> tuple[bool, dict[str, Any], str]:
    user_current_path = repo_path(user_current_dir) if user_current_dir is not None else run_dir / "user_current"
    payload, path = _load_first([
        user_current_path / "09_daily_output_contract_summary.json",
        user_current_path / "summary.json",
        run_dir / "daily_operating_selection_refresh" / "summary.json",
    ])
    if not payload:
        return False, payload, str(user_current_path / "09_daily_output_contract_summary.json")
    explicit = payload.get("snapshot_contract_pass")
    if explicit is None:
        explicit = payload.get("current_snapshot_used_for_order_preview")
    review_only_safe = (
        payload.get("review_only") is True
        and payload.get("live_trading_enabled") is False
        and payload.get("production_mutation_allowed") is False
        and payload.get("canonical_production_sync") is False
        and payload.get("human_approval_required") is True
    )
    return _bool(explicit) and review_only_safe, payload, str(path)


def _cash_trap_clear(run_dir: Path, evidence: dict[str, Any]) -> tuple[bool, bool, dict[str, Any], str]:
    payload = read_json(run_dir / "cash_reentry_quality" / "summary.json")
    available = bool(payload)
    if not available:
        return False, False, payload, str(run_dir / "cash_reentry_quality" / "summary.json")
    flag = payload.get("cash_trap_flag")
    rows = payload.get("cash_trap_rows")
    cash_trap_false = flag is False or (flag is None and rows in (0, "0", 0.0))
    portfolios = payload.get("by_portfolio") if isinstance(payload.get("by_portfolio"), dict) else {}
    for item in portfolios.values():
        if isinstance(item, dict) and item.get("cash_trap_flag") is True:
            cash_trap_false = False
    if evidence.get("cash_trap_false") is False:
        cash_trap_false = False
    return True, bool(cash_trap_false), payload, str(run_dir / "cash_reentry_quality" / "summary.json")


def classify_clean_7y_readiness(latest_run: str | Path, *, user_current_dir: str | Path | None = None) -> dict[str, Any]:
    run_dir = repo_path(latest_run)
    evidence = classify_evidence(run_dir, user_current_dir=user_current_dir)
    official = read_json(run_dir / "account_evaluation" / "official_metrics.json")

    mode = _official_metric_mode(evidence, official)
    years = _portfolio_years(evidence, official)
    data_ready, data_payload, data_path = _data_readiness_ready(run_dir, evidence)
    universe_ok, universe_payload, universe_path = _universe_healthy(run_dir, evidence)
    daily_ok, daily_payload, daily_path = _daily_snapshot_pass(run_dir, user_current_dir=user_current_dir)
    cash_available, cash_false, cash_payload, cash_path = _cash_trap_clear(run_dir, evidence)

    checks = {
        "broker_ledger_next_close": mode == OFFICIAL_METRIC_MODE,
        "broker_window_years_min_7": years >= 7.0,
        "data_readiness_policy_replay_ready": data_ready,
        "universe_health_pass": universe_ok,
        "daily_snapshot_contract_pass": daily_ok,
        "cash_trap_audit_available": cash_available,
        "cash_trap_false": cash_false,
        "evidence_tier_research_eligible": evidence.get("tier") in {TIER1, TIER2, TIER3, TIER4},
        "tier0_absent": evidence.get("tier") != TIER0,
    }

    blockers: list[str] = []
    for key, passed in checks.items():
        if not passed:
            blockers.append(key)
    blockers.extend(str(item) for item in evidence.get("tier0_blockers", []) if item)
    blockers = sorted(set(blockers))

    ready = not blockers
    blocked_uses = list(ALWAYS_BLOCKED_USES)
    if not ready:
        blocked_uses = ["alpha_plane_audit", "alpha_plane_ab_research", "daily_operating_preview", *blocked_uses]

    payload = {
        "schema_version": "clean-7y-research-readiness-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(run_dir),
        "status": READY if ready else NOT_READY,
        "evidence_tier": evidence.get("tier"),
        "evidence_label": evidence.get("evidence_label"),
        "evidence_recovery": evidence.get("pre_broker_substrate_gate_recovery"),
        "pre_broker_substrate_gate_pass": evidence.get("pre_broker_substrate_gate_pass"),
        "pre_broker_substrate_gate_reasons": evidence.get("pre_broker_substrate_gate_reasons"),
        "metric_mode": mode,
        "broker_window_years": years,
        "allowed_uses": ALLOWED_RESEARCH_USES if ready else ["diagnostics"],
        "blocked_uses": blocked_uses,
        "promotion_allowed": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "human_approval_required": True,
        "ready_for_alpha_plane_audit": ready,
        "ready_for_alpha_plane_ab_research": ready,
        "ready_for_human_review_allowed": False,
        "valid_for_production_semantics": "promotion_only; clean 7Y research readiness never implies official promotion",
        "checks": checks,
        "blockers": blockers,
        "warnings": [
            "clean_7y_research_ready is not official promotion evidence",
            "proxy_10y or official evidence is still required before promotion review",
        ],
        "next_actions": [
            "run Alpha Plane audits before any T3/recovery A/B" if ready else "fix blockers before Alpha Plane A/B research",
            "validate any successful 7Y candidate on proxy_10y or official evidence before promotion",
        ],
        "source_files": {
            "official_metrics": str(run_dir / "account_evaluation" / "official_metrics.json"),
            "evidence_policy": str(run_dir / "evidence_policy" / "evidence_status.json"),
            "data_readiness": data_path,
            "universe_health": universe_path,
            "daily_snapshot_contract": daily_path,
            "cash_reentry_quality": cash_path,
        },
        "source_summaries": {
            "data_readiness_status": data_payload.get("status"),
            "universe_status": universe_payload.get("status"),
            "universe_count": universe_payload.get("r1000_base_count", universe_payload.get("scored_r1000_base")),
            "daily_snapshot_status": daily_payload.get("status"),
            "cash_trap_rows": cash_payload.get("cash_trap_rows"),
            "recommended_recovery_source": (
                evidence.get("pre_broker_substrate_gate_recovery") or {}
            ).get("recommended_recovery_source"),
            "recovery_action": (
                evidence.get("pre_broker_substrate_gate_recovery") or {}
            ).get("recovery_action"),
        },
    }
    return payload


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Clean 7Y Research Readiness",
        "",
        f"- status: `{payload.get('status')}`",
        f"- evidence tier: `{payload.get('evidence_tier')}`",
        f"- evidence label: `{payload.get('evidence_label')}`",
        f"- broker window years: `{payload.get('broker_window_years')}`",
        f"- metric mode: `{payload.get('metric_mode')}`",
        f"- promotion allowed: `{payload.get('promotion_allowed')}`",
        f"- live trading enabled: `{payload.get('live_trading_enabled')}`",
        "",
        "## Checks",
        "",
        "| Check | Pass |",
        "| --- | --- |",
    ]
    for key, value in payload.get("checks", {}).items():
        lines.append(f"| `{key}` | `{bool(value)}` |")
    lines.extend(["", "## Blockers", ""])
    blockers = payload.get("blockers") or []
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- none")
    recovery = payload.get("evidence_recovery") if isinstance(payload.get("evidence_recovery"), dict) else {}
    if recovery:
        lines.extend(["", "## Recovery", ""])
        for key in ("fallback_available", "recommended_recovery_source", "recovery_action", "recommended_recovery_reason"):
            lines.append(f"- {key}: `{recovery.get(key)}`")
    lines.extend(["", "## Allowed Uses", ""])
    lines.extend(f"- `{item}`" for item in payload.get("allowed_uses", []))
    lines.extend(["", "## Blocked Uses", ""])
    lines.extend(f"- `{item}`" for item in payload.get("blocked_uses", []))
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {item}" for item in payload.get("warnings", []))
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check clean 7Y broker-ledger research readiness")
    parser.add_argument("--latest-run", default="outputs", help="Run output directory")
    parser.add_argument("--user-current-dir", default="", help="Optional user_current directory override")
    parser.add_argument("--output-dir", default="outputs/clean_7y_research_readiness")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = classify_clean_7y_readiness(
        args.latest_run,
        user_current_dir=args.user_current_dir or None,
    )
    write_outputs(payload, repo_path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
