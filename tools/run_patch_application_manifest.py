#!/usr/bin/env python3
"""Write a manifest explaining which AlphaOps patches ran.

The manifest separates research sidecars from production mutations.  AlphaOps
vNext production is the explicit mode that can replace operating target books
before broker replay.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


EXPECTED_PATCHES = {
    "baseline_lock": "baseline_lock/active_baseline.json",
    "market_leader_challenger": "market_leader_challenger/summary.json",
    "integrated_theme_leader_crisis_replay": "integrated_theme_leader_crisis_replay/summary.json",
    "strategy_logic_ledger": "strategy_logic_ledger/summary.json",
    "position_cleanup_review": "operator_review/dust_positions_report.csv",
    "user_current_research_only_notice": "user_current/07_research_sidecar_context.json",
    "sidecar_promotion_bridge": "promotion_review/sidecar_promotion_bridge_status.json",
    "sidecar_promotion_check": "promotion_review/integrated_target_promotion_check.json",
    "decision_cadence_review": "decision_cadence/decision_cadence_summary.json",
    "alphaops_vnext_policy_replay": "alphaops_vnext/summary.json",
}


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


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def sidecar_record(latest_run: Path, name: str, rel_path: str, sidecar_profile: str) -> dict[str, Any]:
    path = latest_run / rel_path
    ran = path.exists()
    if ran:
        reason = ""
    elif sidecar_profile == "operating_minimal" and name in {
        "baseline_lock",
        "market_leader_challenger",
        "integrated_theme_leader_crisis_replay",
        "strategy_logic_ledger",
        "position_cleanup_review",
    }:
        reason = "skipped_by_operating_minimal_profile"
    elif sidecar_profile == "phase_g_only":
        reason = "skipped_by_phase_g_only_profile"
    else:
        reason = "not_found_or_failed"
    return {
        "name": name,
        "expected": True,
        "executed": bool(ran),
        "path": str(path),
        "skip_reason": reason,
    }


def current_holdings_source(latest_run: Path) -> str:
    activation = read_json(latest_run / "alphaops_vnext" / "production_activation.json")
    if str(activation.get("status") or "").lower() == "applied":
        return str(activation.get("current_holdings_source") or "alphaops_vnext_policy_target_book")
    if (latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv").exists():
        return "production_operating_snapshot_broker_ledger"
    if (latest_run / "broker_replay" / "main" / "positions_latest.csv").exists():
        return "production_broker_replay_positions_latest"
    return "production_operating_target_book"


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_path = repo_path(args.output)
    sidecar_profile = args.sidecar_profile or env_first("SIDECAR_PROFILE", default="unknown")
    artifact_profile = args.artifact_profile or env_first("ARTIFACT_PROFILE", default="unknown")
    gdrive_sync_mode = args.gdrive_sync_mode or env_first("GDRIVE_SYNC_MODE", default="unknown")
    portfolio_policy = getattr(args, "portfolio_policy", "") or env_first("PORTFOLIO_POLICY", default="production_baseline")
    approved_target_policy_path = getattr(args, "approved_target_policy_path", "") or env_first(
        "APPROVED_TARGET_POLICY_PATH",
        default="outputs/promotion_review/approved_target_policy.json",
    )
    run_id = args.run_id or env_first("GITHUB_RUN_ID", default="local")
    branch = args.branch or env_first("GITHUB_HEAD_REF", "GITHUB_REF_NAME", default="")
    head_sha = args.head_sha or env_first("GITHUB_SHA", default="")
    run_attempt = args.run_attempt or env_first("GITHUB_RUN_ATTEMPT", default="")
    artifact_id = args.artifact_id or run_id

    executed = [sidecar_record(latest_run, name, rel, sidecar_profile) for name, rel in EXPECTED_PATCHES.items()]
    skipped = [row for row in executed if not row["executed"]]
    integrated = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "summary.json")
    replay_gate = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "replay_gate_status.json")
    promotion_gate = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "promotion_gate_status.json")
    mutation = read_json(latest_run / "integrated_theme_leader_crisis_replay" / "production_mutation_check.json")
    promotion_check = read_json(latest_run / "promotion_review" / "integrated_target_promotion_check.json")
    promotion_audit = read_json(latest_run / "promotion_review" / "production_mutation_audit.json")
    promotion_bridge = read_json(latest_run / "promotion_review" / "sidecar_promotion_bridge_status.json")
    decision_cadence = read_json(latest_run / "decision_cadence" / "decision_cadence_summary.json")
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    alphaops_activation = read_json(latest_run / "alphaops_vnext" / "production_activation.json")

    alphaops_applied = str(alphaops_activation.get("status") or "").lower() == "applied"
    production_mutated = str(promotion_audit.get("status") or "").lower() == "applied" or alphaops_applied
    if alphaops_applied:
        reason = "alphaops_vnext_production_replaced_operating_books"
    elif not integrated:
        reason = "integrated_replay_not_executed"
    elif production_mutated:
        reason = "approved_sidecar_target_applied_to_operating_book"
    elif str(promotion_gate.get("status") or "").lower() != "passed":
        reason = "research_only_sidecar_promotion_gate_not_passed"
    else:
        reason = "production_activation_forbidden_until_manual_promotion"

    payload = {
        "schema_version": "alphaops-patch-application-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "commit_sha": head_sha,
        "head_sha": head_sha,
        "branch": branch,
        "artifact_id": artifact_id,
        "latest_run": str(latest_run),
        "sidecar_profile": sidecar_profile,
        "artifact_profile": artifact_profile,
        "gdrive_sync_mode": gdrive_sync_mode,
        "portfolio_policy": portfolio_policy,
        "approved_target_policy_path": approved_target_policy_path,
        "expected_patches": {name: True for name in EXPECTED_PATCHES},
        "executed_sidecars": executed,
        "skipped_sidecars": skipped,
        "production_mutation_allowed": bool(portfolio_policy in {"approved_integrated", "alphaops_vnext_production"}),
        "production_mutated": bool(production_mutated),
        "production_mutation_check_status": alphaops_activation.get("status") or promotion_audit.get("status") or mutation.get("status", "missing"),
        "production_applied": bool(production_mutated),
        "sidecar_only": not bool(production_mutated),
        "current_holdings_source": current_holdings_source(latest_run),
        "reason_not_applied_to_current_holdings": reason,
        "sidecar_applied_to_production": bool(production_mutated),
        "promotion_status": promotion_check.get("status") or promotion_gate.get("status", "missing"),
        "promotion_bridge_status": alphaops_activation.get("status") or promotion_bridge.get("status", "missing"),
        "alphaops_vnext_activation_status": alphaops_activation.get("status", "missing"),
        "alphaops_vnext_summary_path": str(latest_run / "alphaops_vnext" / "summary.json") if alphaops_activation else "",
        "decision_cadence_status": decision_cadence.get("schema_version", "missing"),
        "mid_month_reentry_allowed": bool(decision_cadence.get("mid_month_reentry_allowed", False)),
        "shadow_available": bool((latest_run / "shadow_operating").exists()),
        "projected_holdings_path": (
            str(latest_run / "operator_review" / "projected_holdings_after_market_leader_target.csv")
            if portfolio_policy == "market_leader_shadow"
            and (latest_run / "operator_review" / "projected_holdings_after_market_leader_target.csv").exists()
            else (
                str(latest_run / "operator_review" / "projected_holdings_after_integrated_target.csv")
                if (latest_run / "operator_review" / "projected_holdings_after_integrated_target.csv").exists()
                else ""
            )
        ),
        "projected_integrated_holdings_path": str(latest_run / "operator_review" / "projected_holdings_after_integrated_target.csv")
        if (latest_run / "operator_review" / "projected_holdings_after_integrated_target.csv").exists()
        else "",
        "projected_market_leader_holdings_path": str(latest_run / "operator_review" / "projected_holdings_after_market_leader_target.csv")
        if (latest_run / "operator_review" / "projected_holdings_after_market_leader_target.csv").exists()
        else "",
        "official_metric_mode": official.get("official_metric_mode") or official.get("metric_mode") or "",
        "valid_for_production": official.get("valid_for_production"),
        "candidate_replay_book_present": bool((latest_run / "reports" / "candidate_replay_book.csv").exists()),
        "replay_gate_status": replay_gate.get("status", "missing"),
        "promotion_gate_status": promotion_gate.get("status", "missing"),
        "promotion_activation_allowed": bool(promotion_gate.get("production_activation_allowed", False)),
        "integrated_replay_status": integrated.get("status", "missing"),
        "integrated_case_failure_count": integrated.get("case_failure_count", ""),
        "notes": [
            "Current holdings come from broker-ledger operating books.",
            "Market Leader, Multi-Lane, Crisis, and Integrated Replay outputs are research-only unless approved_integrated promotion is applied.",
            "approved_integrated or alphaops_vnext_production may replace operating target books before broker replay.",
        ],
    }
    write_json(output_path, payload)
    replay_copy = latest_run / "replay_integrity" / "patch_application_manifest.json"
    if output_path.resolve() != replay_copy.resolve():
        write_json(replay_copy, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output", default="outputs/patch_application_manifest.json")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-attempt", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--branch", default="")
    parser.add_argument("--artifact-id", default="")
    parser.add_argument("--sidecar-profile", default="")
    parser.add_argument("--artifact-profile", default="")
    parser.add_argument("--gdrive-sync-mode", default="")
    parser.add_argument("--portfolio-policy", default="")
    parser.add_argument("--approved-target-policy-path", default="")
    return parser.parse_args()


def main() -> int:
    payload = build_manifest(parse_args())
    print(json.dumps({"status": "completed", "executed_count": sum(1 for x in payload["executed_sidecars"] if x["executed"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
