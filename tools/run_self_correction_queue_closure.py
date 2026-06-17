#!/usr/bin/env python3
"""Close self-correction queue items from review-only A/B verifier summaries.

The router creates workflow dispatch payloads, and the A/B verifier classifies
completed candidate runs. This tool joins those two artifacts without mutating
production config, target books, or live orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

QUEUE_STATUSES = [
    "queued",
    "dispatched",
    "measured",
    "rejected",
    "ready_for_human_review",
    "stale",
    "closed",
]
HUMAN_REVIEW_DECISIONS = {
    "promote_candidate_review_only",
    "ready_for_human_review",
    "robust_candidate_review_only",
}


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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def str_value(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def load_verifier_summaries(summary_paths: list[str], verifier_dirs: list[str]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for item in summary_paths:
        if item:
            paths.append(repo_path(item))
    for item in verifier_dirs:
        if item:
            paths.append(repo_path(item) / "summary.json")
    if not paths:
        paths.append(repo_path("outputs/ab_result_verifier/summary.json"))

    summaries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        payload = read_json(path)
        if payload:
            payload["_summary_path"] = str(path)
            summaries.append(payload)
    return summaries


def verifier_candidates(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in summaries:
        context = summary.get("dispatch_context") if isinstance(summary.get("dispatch_context"), dict) else {}
        for candidate in summary.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            row = dict(candidate)
            for key in ("experiment_id", "payload_hash", "workflow_run_id", "dispatch_run_id"):
                row[key] = str_value(row.get(key) or context.get(key))
            row["candidate_run"] = str_value(row.get("candidate_run") or row.get("run_label"))
            row["verifier_status"] = summary.get("status")
            row["verifier_summary_path"] = summary.get("_summary_path")
            rows.append(row)
    return rows


def decision_rank(decision: str) -> int:
    if decision in HUMAN_REVIEW_DECISIONS:
        return 0
    if decision.startswith("blocked"):
        return 1
    if decision.startswith("reject") or decision.startswith("invalid"):
        return 2
    return 3


def match_candidate(item: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    item_payload_hash = str_value(item.get("payload_hash"))
    item_experiment = str_value(item.get("experiment_id"))
    item_dispatch_run = str_value(item.get("dispatch_run_id"))

    best: tuple[int, int, dict[str, Any], str] | None = None
    for candidate in candidates:
        score = 0
        reason = ""
        if item_payload_hash and item_payload_hash == str_value(candidate.get("payload_hash")):
            score = 100
            reason = "payload_hash"
        elif item_dispatch_run and item_dispatch_run == str_value(candidate.get("dispatch_run_id")):
            score = 90
            reason = "dispatch_run_id"
        elif item_experiment and item_experiment == str_value(candidate.get("experiment_id")):
            score = 70
            reason = "experiment_id"
        if score <= 0:
            continue
        rank = decision_rank(str_value(candidate.get("decision")))
        current = (score, -rank, candidate, reason)
        if best is None or current[:2] > best[:2]:
            best = current
    if best is None:
        return None, ""
    return best[2], best[3]


def status_from_decision(decision: str) -> str:
    if decision in HUMAN_REVIEW_DECISIONS:
        return "ready_for_human_review"
    if decision.startswith("reject") or decision.startswith("invalid"):
        return "rejected"
    if decision.startswith("blocked"):
        return "measured"
    return "measured"


def close_item(item: dict[str, Any], candidates: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    out = dict(item)
    current_status = str_value(out.get("status") or "queued")
    if current_status == "stale":
        out["closure_match_status"] = "skipped_stale"
        return out

    candidate, match_key = match_candidate(item, candidates)
    if candidate is None:
        out["closure_match_status"] = "unmatched"
        out.setdefault("status", current_status or "queued")
        return out

    decision = str_value(candidate.get("decision") or "measured")
    next_status = status_from_decision(decision)
    out["status"] = next_status
    out["status_reason"] = decision
    out["closure_match_status"] = "matched"
    out["closure_match_key"] = match_key
    out["closure_decision"] = decision
    out["closure_issues"] = list(candidate.get("issues") or [])
    out["review_valid_for_promotion"] = bool(candidate.get("review_valid_for_promotion"))
    out["candidate_run"] = candidate.get("candidate_run") or candidate.get("run_label")
    out["workflow_run_id"] = candidate.get("workflow_run_id") or out.get("workflow_run_id")
    out["dispatch_run_id"] = candidate.get("dispatch_run_id") or out.get("dispatch_run_id")
    out["verifier_summary_path"] = candidate.get("verifier_summary_path")
    out["verifier_status"] = candidate.get("verifier_status")
    out["measured_at_utc"] = generated_at
    out["measured_ledger_run_id"] = candidate.get("candidate_run") or candidate.get("run_label")
    out["production_mutation_allowed"] = False
    out["live_trading_allowed"] = False
    out["requires_user_approval"] = True
    out["requires_followup"] = next_status == "measured"
    if next_status == "ready_for_human_review":
        out["ready_for_human_review_at_utc"] = generated_at
    if next_status == "rejected":
        out["rejected_at_utc"] = generated_at
    out["candidate_metrics"] = {
        "cagr": candidate.get("cagr"),
        "max_dd": candidate.get("max_dd"),
        "is_cagr": candidate.get("is_cagr"),
        "oos_is_cagr_ratio": candidate.get("oos_is_cagr_ratio"),
        "cagr_delta_vs_baseline_pp": candidate.get("cagr_delta_vs_baseline_pp"),
        "is_cagr_delta_vs_baseline_pp": candidate.get("is_cagr_delta_vs_baseline_pp"),
        "max_dd_delta_vs_baseline_pp": candidate.get("max_dd_delta_vs_baseline_pp"),
    }
    return out


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Self-Correction Queue Closure",
        "",
        f"- schema_version: `{payload.get('schema_version')}`",
        f"- production_mutation_allowed: `{str(payload.get('production_mutation_allowed')).lower()}`",
        f"- live_trading_allowed: `{str(payload.get('live_trading_allowed')).lower()}`",
        f"- queue_items: `{payload.get('queue_item_count')}`",
        f"- matched_items: `{payload.get('matched_item_count')}`",
        f"- ready_for_human_review: `{payload.get('ready_for_human_review_count')}`",
        f"- rejected: `{payload.get('rejected_count')}`",
        f"- measured_needs_followup: `{payload.get('measured_count')}`",
        "",
        "| Experiment | Status | Decision | Match | Candidate Run | Issues |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("queue_state") or []:
        lines.append(
            "| {experiment} | `{status}` | `{decision}` | {match} | {run} | {issues} |".format(
                experiment=item.get("experiment_id"),
                status=item.get("status"),
                decision=item.get("closure_decision") or item.get("status_reason") or "",
                match=item.get("closure_match_status") or "",
                run=item.get("candidate_run") or "",
                issues=", ".join(str(issue) for issue in item.get("closure_issues") or []),
            )
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- This closure is review-only and cannot place orders or mutate production.",
            "- `ready_for_human_review` means a verifier candidate passed all gates, but still needs user approval and a separate PR.",
            "- `measured` means evidence exists but is blocked and needs follow-up rather than automatic rejection.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = utc_now()
    output_dir = repo_path(getattr(args, "output_dir", "outputs/self_correction_queue"))
    queue_path = repo_path(getattr(args, "queue_path", "outputs/self_correction_router/router_queue.json"))
    queue = read_json(queue_path)
    summaries = load_verifier_summaries(
        list(getattr(args, "verifier_summary", None) or []),
        list(getattr(args, "verifier_dir", None) or []),
    )
    candidates = verifier_candidates(summaries)
    items = [item for item in (queue.get("queued_experiments") or []) if isinstance(item, dict)]
    closed_items = [close_item(item, candidates, generated_at) for item in items]
    status_counts: dict[str, int] = {}
    for item in closed_items:
        status = str_value(item.get("status") or "queued")
        status_counts[status] = status_counts.get(status, 0) + 1
    stale_payloads = list(queue.get("stale_payloads") or [])
    for item in closed_items:
        if item.get("status") == "stale":
            stale_payloads.append(item)

    payload = {
        "schema_version": "self-correction-queue-closure-v1",
        "generated_at_utc": generated_at,
        "production_mutation_allowed": False,
        "live_trading_allowed": False,
        "requires_user_approval": True,
        "queue_path": str(queue_path),
        "verifier_summary_count": len(summaries),
        "verifier_candidate_count": len(candidates),
        "queue_statuses": QUEUE_STATUSES,
        "status_counts": status_counts,
        "queue_item_count": len(closed_items),
        "matched_item_count": sum(1 for item in closed_items if item.get("closure_match_status") == "matched"),
        "ready_for_human_review_count": status_counts.get("ready_for_human_review", 0),
        "rejected_count": status_counts.get("rejected", 0),
        "measured_count": status_counts.get("measured", 0),
        "unmatched_count": sum(1 for item in closed_items if item.get("closure_match_status") == "unmatched"),
        "queue_state": closed_items,
        "duplicate_suppressed": queue.get("duplicate_suppressed") or [],
        "duplicate_suppressed_count": queue.get("duplicate_suppressed_count") or 0,
        "stale_payloads": stale_payloads,
        "stale_payload_count": len(stale_payloads),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "queue_state.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True, default=str) + "\n" for item in closed_items),
        encoding="utf-8",
    )
    write_json(
        output_dir / "deduped_queue.json",
        {
            "queue_state": closed_items,
            "duplicate_suppressed": payload["duplicate_suppressed"],
            "duplicate_suppressed_count": payload["duplicate_suppressed_count"],
        },
    )
    write_json(output_dir / "stale_payloads.json", stale_payloads)
    (output_dir / "closure_report.md").write_text(render_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "status_counts": status_counts,
                "matched": payload["matched_item_count"],
                "ready_for_human_review": payload["ready_for_human_review_count"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-path", default="outputs/self_correction_router/router_queue.json")
    parser.add_argument("--verifier-summary", action="append", default=[])
    parser.add_argument("--verifier-dir", action="append", default=[])
    parser.add_argument("--output-dir", default="outputs/self_correction_queue")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
