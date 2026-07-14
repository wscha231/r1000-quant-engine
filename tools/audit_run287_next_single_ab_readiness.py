#!/usr/bin/env python3
"""Fail-closed readiness audit for the next single Run287 portfolio A/B.

The audit proves local generated-book artifact availability, preserves terminal
source-screen failures, and separates a forward mechanism-review gate from a
historical fixed/generated-book A/B gate.  It never runs a backtest or mutates
books, weights, cash, orders, production, or live-trading state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-next-single-ab-readiness-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_if_file(path: Path | None) -> str:
    return sha256_file(path) if path is not None and path.is_file() else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_substrate(contract: dict[str, Any], freeze: dict[str, Any]) -> dict[str, Any]:
    rules = contract.get("generated_substrate", {})
    gates = freeze.get("gates", {}) if isinstance(freeze.get("gates"), dict) else {}
    core = gates.get("core_substrate", {}) if isinstance(gates.get("core_substrate"), dict) else {}
    parity = gates.get("parity", {}) if isinstance(gates.get("parity"), dict) else {}
    generated = gates.get("generated_book_substrate", {}) if isinstance(gates.get("generated_book_substrate"), dict) else {}
    blockers: list[str] = []

    if not freeze:
        blockers.append("evidence_freeze_missing_or_invalid")
    if rules.get("require_core_ready", True) and not core.get("ready"):
        blockers.append("core_substrate_not_ready")
    if rules.get("require_parity_ready", True) and not parity.get("ready"):
        blockers.append("control_parity_not_ready")
    if rules.get("require_generated_book_ready", True) and not generated.get("ready"):
        blockers.append("generated_book_substrate_not_ready")
    expected_run = str(rules.get("official_source_run_id", ""))
    observed_run = str(generated.get("official_source_run_id", ""))
    if expected_run and observed_run != expected_run:
        blockers.append(f"official_source_run_mismatch:{observed_run or 'missing'}!={expected_run}")

    artifacts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in rules.get("local_artifacts", []):
        if not isinstance(item, dict):
            blockers.append("invalid_artifact_contract_row")
            continue
        artifact_id = str(item.get("id", "")).strip()
        configured = repo_path(str(item.get("path", "")))
        expected = str(item.get("expected_sha256", "")).strip().lower()
        row: dict[str, Any] = {
            "id": artifact_id,
            "path": str(configured),
            "expected_sha256": expected,
            "exists": configured.is_file(),
            "observed_sha256": "",
            "hash_match": False,
        }
        if not artifact_id or artifact_id in seen_ids:
            blockers.append(f"invalid_or_duplicate_artifact_id:{artifact_id or 'missing'}")
        seen_ids.add(artifact_id)
        if not expected or len(expected) != 64:
            blockers.append(f"invalid_expected_sha256:{artifact_id or 'missing'}")
        if not configured.is_file():
            blockers.append(f"local_artifact_missing:{artifact_id or configured.name}")
        else:
            observed = sha256_file(configured)
            row["observed_sha256"] = observed
            row["hash_match"] = observed == expected
            row["bytes"] = configured.stat().st_size
            if observed != expected:
                blockers.append(f"local_artifact_hash_mismatch:{artifact_id}")
        artifacts.append(row)

    manifest_checks = generated.get("hash_checks", {}) if isinstance(generated.get("hash_checks"), dict) else {}
    for artifact_id in seen_ids:
        if manifest_checks.get(artifact_id) is not True:
            blockers.append(f"freeze_manifest_hash_check_not_true:{artifact_id}")

    return {
        "ready": not blockers,
        "status": "READY" if not blockers else "BLOCKED_SUBSTRATE",
        "official_source_run_id": observed_run,
        "artifacts": artifacts,
        "blockers": sorted(set(blockers)),
    }


def terminal_lane_checks(
    contract: dict[str, Any],
    sec_filing: dict[str, Any],
    sec_guidance: dict[str, Any],
) -> dict[str, Any]:
    rules = contract.get("terminal_source_lanes", {})
    expected_filing = str(rules.get("sec_filing_quality_event", {}).get("required_verdict", ""))
    expected_guidance = str(rules.get("sec_management_guidance_scout", {}).get("required_status", ""))
    observed_filing = str(sec_filing.get("verdict") or sec_filing.get("source_screen_verdict") or "MISSING")
    observed_guidance = str(sec_guidance.get("status") or "MISSING")
    blockers: list[str] = []
    if observed_filing != expected_filing:
        blockers.append(f"sec_filing_terminal_verdict_mismatch:{observed_filing}")
    if observed_guidance != expected_guidance:
        blockers.append(f"sec_guidance_terminal_status_mismatch:{observed_guidance}")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "lanes": {
            "sec_filing_quality_event": {
                "status": observed_filing,
                "terminal": observed_filing == expected_filing,
                "portfolio_ab_allowed": False,
            },
            "sec_management_guidance_scout": {
                "status": observed_guidance,
                "terminal": observed_guidance == expected_guidance,
                "portfolio_ab_allowed": False,
            },
        },
    }


def candidate_repeat_matches(candidate: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    fields = tuple(registry.get("match_fields", ["signal", "mechanism", "book", "window"]))
    matches: list[str] = []
    for entry in registry.get("entries", []):
        if not isinstance(entry, dict) or not entry.get("blocked_reuse"):
            continue
        if all(str(candidate.get(field, "")) == str(entry.get(field, "")) for field in fields):
            matches.append(str(entry.get("id", "unknown")))
    return matches


def evaluate_historical_lane(
    contract: dict[str, Any],
    substrate: dict[str, Any],
    terminal_lanes: dict[str, Any],
    source_gate: dict[str, Any],
    source_screen: dict[str, Any],
    fixed_book: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    rules = contract.get("external_pit_lane", {})
    data_ready = str(source_gate.get("status", "MISSING")) == str(rules.get("source_data_ready_status"))
    screen_pass = str(source_screen.get("verdict", "MISSING")) == str(rules.get("source_screen_pass_verdict"))
    fixed_pass = str(fixed_book.get("verdict", "MISSING")) == str(rules.get("fixed_book_pass_verdict"))
    candidate_field = str(rules.get("candidate_arms_field", "candidate_arms"))
    candidates_raw = source_screen.get(candidate_field, []) if screen_pass else []
    candidates = [item for item in candidates_raw if isinstance(item, dict)] if isinstance(candidates_raw, list) else []
    required = [str(value) for value in rules.get("candidate_arm_required_fields", [])]
    blockers: list[str] = []

    if not substrate.get("ready"):
        blockers.append("generated_substrate_not_ready")
    if not terminal_lanes.get("ready"):
        blockers.append("terminal_source_lane_evidence_not_frozen")
    if not data_ready:
        blockers.append("external_pit_source_gate_not_ready")
    if not screen_pass:
        blockers.append("external_pit_source_screen_not_passed")
    if screen_pass and len(candidates) != len(candidates_raw):
        blockers.append("candidate_arm_row_not_object")
    max_arms = int(rules.get("maximum_eligible_arms", 1))
    if screen_pass and len(candidates) == 0:
        blockers.append("source_screen_passed_without_candidate_arm")
    if len(candidates) > max_arms:
        blockers.append(f"multiple_eligible_arms:{len(candidates)}>{max_arms}")

    eligible: list[dict[str, Any]] = []
    for candidate in candidates:
        arm_id = str(candidate.get("arm_id", "missing"))
        missing = [
            field
            for field in required
            if field not in candidate or candidate.get(field) is None or candidate.get(field) == ""
        ]
        if missing:
            blockers.append(f"candidate_arm_missing_fields:{arm_id}:{','.join(missing)}")
            continue
        if candidate.get("preregistered") is not True:
            blockers.append(f"candidate_arm_not_preregistered:{arm_id}")
            continue
        repeated = candidate_repeat_matches(candidate, registry)
        if repeated:
            blockers.append(f"candidate_arm_do_not_repeat:{arm_id}:{','.join(repeated)}")
            continue
        eligible.append(candidate)

    selected: dict[str, Any] | None = eligible[0] if len(eligible) == 1 else None
    fixed_arm_id = str(fixed_book.get("arm_id", ""))
    if fixed_pass and selected and fixed_arm_id != str(selected.get("arm_id")):
        blockers.append(f"fixed_book_arm_mismatch:{fixed_arm_id or 'missing'}")

    fixed_book_ab_open = bool(data_ready and screen_pass and selected and not fixed_pass and not blockers)
    generated_book_ab_open = bool(data_ready and screen_pass and selected and fixed_pass and not blockers)
    next_gate_open = fixed_book_ab_open or generated_book_ab_open
    stage = "NONE"
    if fixed_book_ab_open:
        stage = "FIXED_BOOK_AB"
    elif generated_book_ab_open:
        stage = "GENERATED_BOOK_AB"

    return {
        "source_data_gate_status": str(source_gate.get("status", "MISSING")),
        "source_screen_verdict": str(source_screen.get("verdict", "MISSING")),
        "fixed_book_verdict": str(fixed_book.get("verdict", "MISSING")),
        "eligible_arm_count": len(eligible),
        "eligible_arms": eligible,
        "selected_arm": selected,
        "next_single_ab_stage": stage,
        "next_single_ab_gate_open": next_gate_open,
        "fixed_book_ab_gate_open": fixed_book_ab_open,
        "generated_book_ab_gate_open": generated_book_ab_open,
        "blockers": sorted(set(blockers)),
    }


def write_report(output_dir: Path, summary: dict[str, Any]) -> None:
    historical = summary["historical_lane"]
    forward = summary["forward_lane"]
    lines = [
        "# Run287 next single A/B readiness",
        "",
        f"- Status: `{summary['status']}`",
        f"- Generated substrate: `{summary['generated_substrate']['status']}`",
        f"- Next historical A/B gate open: `{historical['next_single_ab_gate_open']}`",
        f"- Next historical A/B stage: `{historical['next_single_ab_stage']}`",
        f"- Forward mechanism review ready: `{forward['mechanism_review_ready']}`",
        "- Forward mechanism review is not historical CAGR/MDD evidence and cannot open a portfolio A/B.",
        "- No book, weight, cash, order, fullrun, production, or live-trading state was changed.",
    ]
    blockers = historical.get("blockers", []) + summary["generated_substrate"].get("blockers", [])
    if blockers:
        lines.extend(["", "## Blockers", ""] + [f"- `{item}`" for item in sorted(set(blockers))])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit(
    *,
    contract_path: Path,
    freeze_path: Path,
    sec_filing_path: Path,
    sec_guidance_path: Path,
    source_gate_path: Path | None,
    source_screen_path: Path | None,
    fixed_book_path: Path | None,
    risk_outcome_path: Path | None,
    do_not_repeat_path: Path,
    output_dir: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    contract = read_json(contract_path)
    if contract.get("schema_version") != "run287-next-single-ab-readiness-contract-v1":
        raise ValueError("invalid readiness contract schema")
    substrate = verify_substrate(contract, read_json(freeze_path))
    terminal = terminal_lane_checks(contract, read_json(sec_filing_path), read_json(sec_guidance_path))
    historical = evaluate_historical_lane(
        contract,
        substrate,
        terminal,
        read_json(source_gate_path) if source_gate_path else {},
        read_json(source_screen_path) if source_screen_path else {},
        read_json(fixed_book_path) if fixed_book_path else {},
        read_json(do_not_repeat_path),
    )
    risk = read_json(risk_outcome_path) if risk_outcome_path else {}
    forward_ready_field = str(contract.get("forward_risk_lane", {}).get("mechanism_review_ready_field", "mechanism_review_ready"))
    forward_ready = risk.get(forward_ready_field) is True

    if historical["next_single_ab_gate_open"]:
        status = "READY_SINGLE_FIXED_BOOK_AB" if historical["fixed_book_ab_gate_open"] else "READY_SINGLE_GENERATED_BOOK_AB"
    elif forward_ready and substrate["ready"] and terminal["ready"]:
        status = "READY_FORWARD_MECHANISM_REVIEW_ONLY"
    else:
        status = "BLOCKED_NO_ELIGIBLE_SINGLE_AB"

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at or utc_now(),
        "status": status,
        "generated_substrate": substrate,
        "terminal_source_lanes": terminal,
        "historical_lane": historical,
        "forward_lane": {
            "mechanism_review_ready": forward_ready,
            "mechanism_review_gate_open": forward_ready,
            "review_only": True,
            "historical_ab_evidence": False,
            "portfolio_ab_allowed": False,
        },
        "next_single_ab_gate_open": historical["next_single_ab_gate_open"],
        "selected_arm": historical["selected_arm"],
        "input_hashes": {
            "contract_sha256": hash_if_file(contract_path),
            "evidence_freeze_sha256": hash_if_file(freeze_path),
            "sec_filing_source_screen_sha256": hash_if_file(sec_filing_path),
            "sec_guidance_review_sha256": hash_if_file(sec_guidance_path),
            "external_source_gate_sha256": hash_if_file(source_gate_path),
            "external_source_screen_sha256": hash_if_file(source_screen_path),
            "fixed_book_summary_sha256": hash_if_file(fixed_book_path),
            "risk_outcome_summary_sha256": hash_if_file(risk_outcome_path),
            "do_not_repeat_registry_sha256": hash_if_file(do_not_repeat_path),
        },
        "safety": contract["safety"],
        "backtest_executed": False,
        "fullrun_executed": False,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", summary)
    write_report(output_dir, summary)
    return summary


def optional_path(value: str) -> Path | None:
    return repo_path(value) if value else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/run287_next_single_ab_readiness_contract.json")
    parser.add_argument("--freeze-manifest", default="outputs/run287_research_evidence_freeze/manifest.json")
    parser.add_argument("--sec-filing-source-screen", default="outputs/sec_filing_quality_event/source_screen_summary.json")
    parser.add_argument("--sec-guidance-review", default="outputs/run287_sec_guidance_goldset_review_gate_20260714/summary.json")
    parser.add_argument("--external-source-gate", default="")
    parser.add_argument("--external-source-screen", default="")
    parser.add_argument("--fixed-book-summary", default="")
    parser.add_argument("--risk-outcome-summary", default="outputs/run287_risk_outcome_archive_20260714_local/summary.json")
    parser.add_argument("--do-not-repeat", default="docs/run287_do_not_repeat_registry.json")
    parser.add_argument("--output-dir", default="outputs/run287_next_single_ab_readiness_20260715")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = audit(
        contract_path=repo_path(args.contract),
        freeze_path=repo_path(args.freeze_manifest),
        sec_filing_path=repo_path(args.sec_filing_source_screen),
        sec_guidance_path=repo_path(args.sec_guidance_review),
        source_gate_path=optional_path(args.external_source_gate),
        source_screen_path=optional_path(args.external_source_screen),
        fixed_book_path=optional_path(args.fixed_book_summary),
        risk_outcome_path=optional_path(args.risk_outcome_summary),
        do_not_repeat_path=repo_path(args.do_not_repeat),
        output_dir=repo_path(args.output_dir),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["next_single_ab_gate_open"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
