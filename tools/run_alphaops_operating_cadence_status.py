#!/usr/bin/env python3
"""Summarize AlphaOps operating cadence state from existing run artifacts.

Read-only. This tool does not dispatch workflows, mutate policy, or promote
production. It converts the daily price audit + fullrun goal verifier into a
single machine-readable next-action summary.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_invalid_json": str(exc)}


def status_from_artifacts(latest_run: Path, *, material_change: bool = False) -> dict[str, Any]:
    price_audit = read_json(latest_run / "latest_price_date_audit.json")
    goal_verifier = read_json(latest_run / "goal_verifier" / "summary.json")
    account_eval = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    data_readiness = read_json(latest_run / "data_readiness" / "summary.json")

    price_status = str(price_audit.get("status") or "missing")
    goal_status = str(goal_verifier.get("status") or "missing")
    readiness_ready = bool(
        data_readiness.get("ready_for_policy_replay")
        or data_readiness.get("ready_for_fullrun")
        or data_readiness.get("status") == "ready"
    )
    pit_clean = bool(account_eval.get("pit_universe_label_clean") or account_eval.get("historical_universe_pit_clean"))
    production_allowed = bool(account_eval.get("production_promotion_allowed"))

    data_refresh_required = price_status not in {"ok"}
    verifier_missing = goal_status == "missing"
    goal_pass = goal_status == "pass"
    fullrun_ready = (not data_refresh_required) and (material_change or verifier_missing)
    weekly_sidecar_review_due = (not data_refresh_required) and (not material_change) and not verifier_missing

    if data_refresh_required:
        next_action = "run_free_data_daily_update"
    elif fullrun_ready:
        next_action = "run_full_rebuild_manual_with_integration_env"
    elif not goal_pass:
        next_action = "inspect_goal_verifier_and_fix_failed_gate"
    else:
        next_action = "hold_fullrun_run_weekly_sidecars_only"

    return {
        "schema_version": "alphaops-operating-cadence-status-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": str(latest_run),
        "material_change": bool(material_change),
        "price_audit": {
            "status": price_status,
            "latest_cached_bar_date": price_audit.get("latest_cached_bar_date"),
            "benchmark_anchor_date": price_audit.get("benchmark_anchor_date"),
            "stale_trading_days": price_audit.get("stale_trading_days"),
            "data_refresh_required": data_refresh_required,
        },
        "goal_verifier": {
            "status": goal_status,
            "goal_pass": goal_pass,
            "main_pass": ((goal_verifier.get("portfolios") or {}).get("main") or {}).get("pass"),
            "concentrated_pass": ((goal_verifier.get("portfolios") or {}).get("concentrated") or {}).get("pass"),
        },
        "data_readiness": {
            "status": data_readiness.get("status") or "missing",
            "ready_for_policy_replay_or_fullrun": readiness_ready,
        },
        "production": {
            "pit_universe_label_clean": pit_clean,
            "production_promotion_allowed": production_allowed,
            "production_blocked_by_pit": not pit_clean,
        },
        "recommendation": {
            "next_action": next_action,
            "fullrun_ready": fullrun_ready,
            "weekly_sidecar_review_due": weekly_sidecar_review_due,
            "production_interpretation": "research_only" if not pit_clean else "production_review_allowed_if_goal_and_contract_pass",
        },
        "non_mutating": True,
    }


def render_report(payload: dict[str, Any]) -> str:
    rec = payload["recommendation"]
    lines = ["# AlphaOps Operating Cadence Status", ""]
    lines.append(f"- next_action: `{rec['next_action']}`")
    lines.append(f"- fullrun_ready: `{str(rec['fullrun_ready']).lower()}`")
    lines.append(f"- weekly_sidecar_review_due: `{str(rec['weekly_sidecar_review_due']).lower()}`")
    lines.append(f"- production_interpretation: `{rec['production_interpretation']}`")
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    lines.append(f"- price_audit_status: `{payload['price_audit']['status']}`")
    lines.append(f"- benchmark_anchor_date: `{payload['price_audit'].get('benchmark_anchor_date')}`")
    lines.append(f"- stale_trading_days: `{payload['price_audit'].get('stale_trading_days')}`")
    lines.append(f"- goal_verifier_status: `{payload['goal_verifier']['status']}`")
    lines.append(f"- main_pass: `{payload['goal_verifier'].get('main_pass')}`")
    lines.append(f"- concentrated_pass: `{payload['goal_verifier'].get('concentrated_pass')}`")
    lines.append(f"- pit_universe_label_clean: `{payload['production']['pit_universe_label_clean']}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/operating_cadence_status")
    parser.add_argument("--material-change", action="store_true")
    args = parser.parse_args()

    latest_run = Path(args.latest_run)
    payload = status_from_artifacts(latest_run, material_change=args.material_change)
    report = render_report(payload)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
