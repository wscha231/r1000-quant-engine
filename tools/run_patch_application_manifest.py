#!/usr/bin/env python3
"""Write a manifest explaining which AlphaOps patches ran.

The manifest is diagnostic only. It makes explicit that integrated
leader/lane/crisis sidecars are research-only and do not mutate current
production holdings.
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
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")

    production_mutated = str(mutation.get("status") or "").lower() == "failed"
    if not integrated:
        reason = "integrated_replay_not_executed"
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
        "expected_patches": {name: True for name in EXPECTED_PATCHES},
        "executed_sidecars": executed,
        "skipped_sidecars": skipped,
        "production_mutation_allowed": False,
        "production_mutated": bool(production_mutated),
        "production_mutation_check_status": mutation.get("status", "missing"),
        "production_applied": False,
        "sidecar_only": True,
        "current_holdings_source": current_holdings_source(latest_run),
        "reason_not_applied_to_current_holdings": reason,
        "official_metric_mode": official.get("official_metric_mode") or official.get("metric_mode") or "",
        "valid_for_production": official.get("valid_for_production"),
        "candidate_replay_book_present": bool((latest_run / "reports" / "candidate_replay_book.csv").exists()),
        "replay_gate_status": replay_gate.get("status", "missing"),
        "promotion_gate_status": promotion_gate.get("status", "missing"),
        "promotion_activation_allowed": bool(promotion_gate.get("production_activation_allowed", False)),
        "integrated_replay_status": integrated.get("status", "missing"),
        "integrated_case_failure_count": integrated.get("case_failure_count", ""),
        "notes": [
            "Current holdings come from production broker-ledger operating books.",
            "Market Leader, Multi-Lane, Crisis, and Integrated Replay outputs are research-only.",
            "This manifest does not promote or mutate production targets.",
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
    return parser.parse_args()


def main() -> int:
    payload = build_manifest(parse_args())
    print(json.dumps({"status": "completed", "executed_count": sum(1 for x in payload["executed_sidecars"] if x["executed"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
