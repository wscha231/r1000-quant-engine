#!/usr/bin/env python3
"""Block broker replay when the data/universe substrate is dirty.

This is a pre-broker safety gate. It does not fetch data, rewrite target books,
change strategy parameters, or promote results. It only reads the already
generated universe-health and data-readiness artifacts and decides whether the
run is clean enough to spend time on broker-ledger replay.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_first(paths: list[Path]) -> tuple[dict[str, Any], Path]:
    for path in paths:
        payload = read_json(path)
        if payload:
            return payload, path
    return {}, paths[0]


def blockers_from_data_readiness(payload: dict[str, Any]) -> list[str]:
    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        blockers = payload.get("policy_replay_blockers")
    return [str(item) for item in blockers] if isinstance(blockers, list) else []


def classify_pre_broker_substrate(latest_run: str | Path, *, universe_mode: str = "global_alpha_universe") -> dict[str, Any]:
    run_dir = repo_path(latest_run)
    universe, universe_path = load_first(
        [
            run_dir / "universe_health" / "universe_source_audit.json",
            run_dir / "universe_health" / "summary.json",
        ]
    )
    readiness, readiness_path = load_first(
        [
            run_dir / "data_readiness" / "summary.json",
            run_dir / "data_readiness" / "status.json",
        ]
    )

    blockers: list[str] = []
    warnings: list[str] = []

    if not universe:
        blockers.append("universe_health_missing")
    elif universe_mode != "adr":
        if universe.get("promotion_allowed") is not True:
            blockers.append("universe_health_promotion_not_allowed")
        if universe.get("hard_fail_before_expensive_rebuild") is True:
            blockers.append("universe_health_hard_fail_before_expensive_rebuild")
        r1000 = universe.get("r1000_base_count")
        floor = universe.get("min_r1000_base")
        if r1000 is not None and floor is not None:
            try:
                if int(r1000) < int(floor):
                    blockers.append(f"scored_r1000_base_below_floor:{r1000}<{floor}")
            except Exception:
                warnings.append("universe_health_count_parse_failed")

    if not readiness:
        blockers.append("data_readiness_missing")
    else:
        readiness_blockers = blockers_from_data_readiness(readiness)
        if readiness.get("ready_for_policy_replay") is not True:
            blockers.append("data_readiness_not_ready_for_policy_replay")
        if readiness_blockers:
            blockers.append("data_readiness_blockers_present")

    passed = not blockers
    recovery = {
        "fallback_available": universe.get("fallback_available"),
        "recommended_recovery_source": universe.get("recommended_recovery_source"),
        "recommended_recovery_reason": universe.get("recommended_recovery_reason"),
        "recovery_action": universe.get("recovery_action"),
    }
    return {
        "schema_version": "pre-broker-substrate-gate-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(run_dir),
        "universe_mode": universe_mode,
        "status": "pass" if passed else "blocked",
        "broker_replay_allowed": passed,
        "evidence_tier_when_blocked": "0_do_not_use",
        "production_mutation_allowed": False,
        "live_trading_allowed": False,
        "promotion_allowed": False,
        "blockers": blockers,
        "warnings": warnings,
        "recovery": recovery,
        "universe_health": {
            "path": str(universe_path),
            "exists": bool(universe),
            "status": universe.get("status"),
            "verdict_code": universe.get("verdict_code"),
            "promotion_allowed": universe.get("promotion_allowed"),
            "hard_fail_before_expensive_rebuild": universe.get("hard_fail_before_expensive_rebuild"),
            "r1000_base_count": universe.get("r1000_base_count"),
            "min_r1000_base": universe.get("min_r1000_base"),
            "primary_universe_source": universe.get("primary_universe_source"),
            "fallback_used": universe.get("fallback_used"),
            "fallback_available": universe.get("fallback_available"),
            "recommended_recovery_source": universe.get("recommended_recovery_source"),
            "recommended_recovery_reason": universe.get("recommended_recovery_reason"),
            "recovery_action": universe.get("recovery_action"),
            "monthly_universe_health_pass": universe.get("monthly_universe_health_pass"),
            "blockers": universe.get("blockers") if isinstance(universe.get("blockers"), list) else [],
        },
        "data_readiness": {
            "path": str(readiness_path),
            "exists": bool(readiness),
            "status": readiness.get("status"),
            "ready_for_policy_replay": readiness.get("ready_for_policy_replay"),
            "blockers": blockers_from_data_readiness(readiness),
            "warnings": readiness.get("warnings") if isinstance(readiness.get("warnings"), list) else [],
        },
        "rules": {
            "purpose": "prevent dirty universe/data substrates from reaching broker-ledger replay",
            "clean_7y_research_requires": [
                "universe_health.promotion_allowed=true",
                "data_readiness.ready_for_policy_replay=true",
                "data_readiness blockers empty",
            ],
            "blocked_use": "broker replay, Alpha Plane A/B, ready_for_human_review, promotion",
        },
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Pre-Broker Substrate Gate",
        "",
        f"- status: `{payload.get('status')}`",
        f"- broker_replay_allowed: `{str(payload.get('broker_replay_allowed')).lower()}`",
        f"- evidence_tier_when_blocked: `{payload.get('evidence_tier_when_blocked')}`",
        f"- production_mutation_allowed: `{str(payload.get('production_mutation_allowed')).lower()}`",
        f"- live_trading_allowed: `{str(payload.get('live_trading_allowed')).lower()}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend([f"- {item}" for item in blockers] if blockers else ["- none"])
    lines.extend(["", "## Universe Health", ""])
    universe = payload.get("universe_health") if isinstance(payload.get("universe_health"), dict) else {}
    for key in ("status", "promotion_allowed", "hard_fail_before_expensive_rebuild", "r1000_base_count", "min_r1000_base", "primary_universe_source"):
        lines.append(f"- {key}: `{universe.get(key)}`")
    lines.extend(["", "## Recovery", ""])
    recovery = payload.get("recovery") if isinstance(payload.get("recovery"), dict) else {}
    for key in ("fallback_available", "recommended_recovery_source", "recovery_action", "recommended_recovery_reason"):
        lines.append(f"- {key}: `{recovery.get(key)}`")
    lines.extend(["", "## Data Readiness", ""])
    readiness = payload.get("data_readiness") if isinstance(payload.get("data_readiness"), dict) else {}
    for key in ("status", "ready_for_policy_replay"):
        lines.append(f"- {key}: `{readiness.get(key)}`")
    readiness_blockers = readiness.get("blockers") if isinstance(readiness.get("blockers"), list) else []
    lines.append(f"- blocker_count: `{len(readiness_blockers)}`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload: dict[str, Any], output_dir: str | Path) -> None:
    out = repo_path(output_dir)
    write_json(out / "summary.json", payload)
    (out / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/pre_broker_substrate_gate")
    parser.add_argument("--universe-mode", default="global_alpha_universe")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero when broker replay should be blocked.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = classify_pre_broker_substrate(args.latest_run, universe_mode=args.universe_mode)
    write_outputs(payload, args.output_dir)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if args.strict and not payload.get("broker_replay_allowed"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
