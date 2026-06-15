#!/usr/bin/env python3
"""Route repeated ledger leaks into review-only A/B queue artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LEAK_EXPERIMENTS = {
    "concentrated:structural_underinvestment_bull": [
        {
            "experiment_id": "conc_bull_floor_stock_min",
            "description": "Measure bull/strong_bull stock floor against concentrated underinvestment.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {"PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED": "1"},
        },
        {
            "experiment_id": "conc_continuation_winner_relaxation",
            "description": "Relax continuation winner filters only in bull/strong_bull regimes.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {"PHASE_CONCENTRATED_CONTINUATION_RELAX_ENABLED": "1"},
        },
        {
            "experiment_id": "conc_theme_leadership_boost",
            "description": "Boost theme leadership confirmation for bull-era leaders.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {"PHASE_THEME_LEADERSHIP_BOOST_ENABLED": "1"},
        },
        {
            "experiment_id": "conc_concentration_cap_relaxation",
            "description": "Relax concentrated cap for confirmed continuation winners.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {"PHASE_CONCENTRATED_CAP_RELAX_ENABLED": "1"},
        },
    ],
    "main:structural_underinvestment_bull": [
        {
            "experiment_id": "main_bull_floor_stock_min",
            "description": "Measure stock floor for main book in bull/strong_bull regimes.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {"PHASE_REGIME_CAPACITY_BULL_FLOOR_ENABLED": "1"},
        }
    ],
    "main:flat_alpha_invested": [
        {
            "experiment_id": "main_era_aware_scoring_challenger_review",
            "description": "Route main selection-IC decay into the era-aware scoring challenger review.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {
                "PHASE_ERA_AWARE_SCORING_CHALLENGER_REVIEW": "1",
                "PHASE_ERA_AWARE_PORTFOLIO_KIND": "main",
            },
        }
    ],
    "concentrated:flat_alpha_invested": [
        {
            "experiment_id": "conc_era_aware_scoring_challenger_review",
            "description": "Route concentrated selection-IC decay into the era-aware scoring challenger review.",
            "workflow_inputs": {"portfolio_policy": "alphaops_vnext_production", "artifact_profile": "minimal"},
            "env": {
                "PHASE_ERA_AWARE_SCORING_CHALLENGER_REVIEW": "1",
                "PHASE_ERA_AWARE_PORTFOLIO_KIND": "concentrated",
            },
        }
    ],
}

OOS_ROBUSTNESS_ACTIONS = {
    "oos_is_cagr_ratio_above_lock": {
        "task_id": "oos_lottery_era_name_review",
        "description": "OOS CAGR is too high relative to locked IS CAGR; inspect whether the result is a narrow era/name lottery before any SHIP retry.",
        "review_artifacts": [
            "oos_lock/report.md",
            "is_attribution/summary.json",
            "era_leadership/summary.json",
            "era_aware_scoring_challenger/summary.json",
            "trade_attribution/<portfolio>/findings.json",
        ],
        "next_action": "Compare IS/OOS top-name contribution and era buckets; require a new 8-year rebuild plus A/B verifier before promotion.",
    },
    "oos_cagr_degradation_above_lock": {
        "task_id": "oos_degradation_defense_review",
        "description": "Locked OOS CAGR degraded more than allowed; inspect crisis defense, cash overlay, and drawdown attribution before more exposure experiments.",
        "review_artifacts": [
            "oos_lock/report.md",
            "daily_crisis_monitor/summary.json",
            "crisis_paper_order_bridge/summary.json",
            "mdd_cash_overlay_research/<portfolio>/metrics.json",
            "trade_attribution/<portfolio>/findings.json",
        ],
        "next_action": "Do not increase concentration; review defensive sidecars and rerun only after the broker-ledger OOS lock passes.",
    },
    "oos_trading_days_below_min": {
        "task_id": "oos_window_data_extension_review",
        "description": "Locked OOS window does not have enough trading days; fix data/window coverage before interpreting robustness.",
        "review_artifacts": [
            "oos_lock/report.md",
            "eight_year_backtest_readiness/summary.json",
            "data_readiness/summary.json",
        ],
        "next_action": "Run the 8-year data bootstrap/rebuild dispatch plan; treat the current robustness verdict as invalid-window evidence.",
    },
}

EIGHT_YEAR_OFFICIAL_PLAN_ID = "full_rebuild_8y_official_after_data_bootstrap"
ACTIVE_QUEUE_STATUSES = {"queued", "dispatched"}
QUEUE_STATUSES = [
    "queued",
    "dispatched",
    "measured",
    "rejected",
    "ready_for_human_review",
    "stale",
    "closed",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(canonical)


def has_official_eight_year_window(latest_run: Path) -> bool:
    summary = read_json(latest_run / "eight_year_backtest_readiness" / "summary.json")
    if not summary:
        return False
    status = str(summary.get("status") or "")
    return bool(summary.get("official_window_ready") is True or status == "official_eight_year_ready")


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def dominant_for_row(row: dict[str, Any]) -> str | None:
    counts: dict[str, int] = {}
    portfolios = row.get("portfolios") if isinstance(row.get("portfolios"), dict) else {}
    for portfolio, payload in portfolios.items():
        if not isinstance(payload, dict):
            continue
        tags = payload.get("leak_year_tags") if isinstance(payload.get("leak_year_tags"), dict) else {}
        for tag in tags.values():
            if tag in {"structural_underinvestment_bull", "flat_alpha_invested"}:
                key = f"{portfolio}:{tag}"
                counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def oos_review_action(failure: str) -> dict[str, Any]:
    return OOS_ROBUSTNESS_ACTIONS.get(
        failure,
        {
            "task_id": "oos_lock_failure_review",
            "description": "OOS lock failed; inspect the lock report before running another promotion attempt.",
            "review_artifacts": ["oos_lock/report.md"],
            "next_action": "Keep the run non-promotable until the OOS lock artifact passes.",
        },
    )


def build_oos_robustness_tasks(latest_run: Path) -> dict[str, Any]:
    lock_path = latest_run / "oos_lock" / "summary.json"
    lock = read_json(lock_path)
    if not lock:
        return {
            "status": "missing",
            "lock_pass": False,
            "summary_path": str(lock_path),
            "queued_review_tasks": [],
        }
    tasks: list[dict[str, Any]] = []
    failures = lock.get("failures") if isinstance(lock.get("failures"), dict) else {}
    portfolios = lock.get("portfolios") if isinstance(lock.get("portfolios"), dict) else {}
    for portfolio, failure_list in sorted(failures.items()):
        if not isinstance(failure_list, list):
            continue
        row = portfolios.get(portfolio) if isinstance(portfolios.get(portfolio), dict) else {}
        for failure in failure_list:
            failure_text = str(failure)
            action = oos_review_action(failure_text)
            artifacts = [
                str(item).replace("<portfolio>", str(portfolio))
                for item in action.get("review_artifacts", [])
            ]
            tasks.append(
                {
                    "task_id": f"{portfolio}_{action['task_id']}",
                    "source": "oos_lock",
                    "portfolio": str(portfolio),
                    "failure": failure_text,
                    "description": action["description"],
                    "next_action": action["next_action"],
                    "review_artifacts": artifacts,
                    "dispatch_mode": "manual_review_no_workflow_dispatch",
                    "production_mutation_allowed": False,
                    "requires_user_approval": True,
                    "metrics": {
                        "cagr_is": row.get("cagr_is"),
                        "cagr_oos": row.get("cagr_oos"),
                        "oos_is_cagr_ratio": row.get("oos_is_cagr_ratio"),
                        "oos_degradation_pp": row.get("oos_degradation_pp"),
                        "max_allowed_degradation_pp": row.get("max_allowed_degradation_pp"),
                        "max_oos_is_cagr_ratio": row.get("max_oos_is_cagr_ratio"),
                        "oos_trading_days": row.get("oos_trading_days"),
                    },
                }
            )
    return {
        "status": lock.get("status") or "unknown",
        "lock_pass": lock.get("lock_pass"),
        "summary_path": str(lock_path),
        "failure_count": sum(len(v) for v in failures.values() if isinstance(v, list)),
        "queued_review_task_count": len(tasks),
        "queued_review_tasks": tasks,
    }


def build_queue(
    ledger_rows: list[dict[str, Any]],
    latest_verdict: dict[str, Any],
    min_repeat: int,
    *,
    latest_run: Path | None = None,
    ledger_sha: str = "",
    previous_queue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    dependency_ids = [] if latest_run is not None and has_official_eight_year_window(latest_run) else [EIGHT_YEAR_OFFICIAL_PLAN_ID]
    latest_focus = latest_verdict.get("dominant_open_leak") or (dominant_for_row(ledger_rows[-1]) if ledger_rows else None)
    recent_focuses = [dominant_for_row(row) for row in ledger_rows[-min_repeat:]]
    repeated = bool(latest_focus and len(recent_focuses) >= min_repeat and all(item == latest_focus for item in recent_focuses))
    templates = LEAK_EXPERIMENTS.get(str(latest_focus), []) if repeated else []
    previous_items = []
    if isinstance(previous_queue, dict):
        previous_items = [item for item in (previous_queue.get("queued_experiments") or []) if isinstance(item, dict)]
    previous_active: dict[str, dict[str, Any]] = {}
    stale_payloads: list[dict[str, Any]] = []
    for item in previous_items:
        payload_hash = str(item.get("payload_hash") or "")
        if not payload_hash or str(item.get("status") or "queued") not in ACTIVE_QUEUE_STATUSES:
            continue
        previous_active[payload_hash] = item
        queued_ledger_sha = str(item.get("ledger_sha_at_queue") or "")
        if ledger_sha and queued_ledger_sha and queued_ledger_sha != ledger_sha:
            stale_payloads.append(
                {
                    "experiment_id": item.get("experiment_id"),
                    "payload_hash": payload_hash,
                    "previous_status": item.get("status") or "queued",
                    "previous_ledger_sha_at_queue": queued_ledger_sha,
                    "current_ledger_sha": ledger_sha,
                    "status": "stale",
                }
            )
    queued = []
    seen_hashes: set[str] = set()
    duplicate_suppressed: list[dict[str, Any]] = []
    latest_run_id = str(ledger_rows[-1].get("run_id") or "") if ledger_rows else ""
    for template in templates:
        env_payload = dict(template.get("env") or {})
        workflow_inputs = {
            "universe_mode": "global_alpha_universe",
            "backtest_years": "8",
            "skip_collector": "true",
            "fast_mode": "true",
            "sidecar_profile": "operating_minimal",
            "artifact_profile": "minimal",
            "gdrive_sync_mode": "minimal",
            "portfolio_policy": "alphaops_vnext_production",
            "cache_key_suffix": str(template.get("experiment_id") or "self_correction"),
            "experiment_env_json": json.dumps(env_payload, sort_keys=True),
        }
        workflow_inputs.update({str(k): str(v).lower() if isinstance(v, bool) else str(v) for k, v in (template.get("workflow_inputs") or {}).items()})
        hash_material = {
            "experiment_id": template.get("experiment_id"),
            "source_leak": latest_focus,
            "workflow": "full_rebuild_manual.yml",
            "workflow_dispatch_inputs": workflow_inputs,
            "depends_on_plan_ids": dependency_ids,
        }
        payload_hash = stable_payload_hash(hash_material)
        previous_item = previous_active.get(payload_hash)
        previous_same_ledger = bool(previous_item and previous_item.get("ledger_sha_at_queue") == ledger_sha)
        if payload_hash in seen_hashes or previous_same_ledger:
            duplicate_suppressed.append(
                {
                    "experiment_id": template.get("experiment_id"),
                    "payload_hash": payload_hash,
                    "reason": "duplicate_active_payload",
                    "source_leak": latest_focus,
                }
            )
            continue
        seen_hashes.add(payload_hash)
        queued.append(
            {
                **template,
                "workflow": "full_rebuild_manual.yml",
                "dispatch_mode": "workflow_dispatch_payload_only",
                "workflow_dispatch_inputs": workflow_inputs,
                "production_mutation_allowed": False,
                "requires_user_approval": True,
                "depends_on_plan_ids": dependency_ids,
                "source_leak": latest_focus,
                "source_run_id": latest_run_id,
                "status": "queued",
                "status_reason": "dependency_blocked" if dependency_ids else "ready_for_dispatch_review",
                "queued_at_utc": generated_at,
                "payload_hash": payload_hash,
                "ledger_sha_at_queue": ledger_sha,
                "dispatch_run_id": None,
                "dispatched_at_utc": None,
                "measured_ledger_run_id": None,
                "measured_at_utc": None,
                "rejected_at_utc": None,
                "ready_for_human_review_at_utc": None,
            }
        )
    oos_robustness = build_oos_robustness_tasks(latest_run) if latest_run is not None else {
        "status": "not_checked",
        "queued_review_tasks": [],
    }
    return {
        "schema_version": "self-correction-router-v1.1",
        "generated_at_utc": generated_at,
        "production_mutation_allowed": False,
        "queue_statuses": QUEUE_STATUSES,
        "ledger_sha_at_queue": ledger_sha,
        "latest_focus": latest_focus,
        "recent_focuses": recent_focuses,
        "min_repeat": min_repeat,
        "repeat_confirmed": repeated,
        "requires_completed_plan_ids": dependency_ids,
        "queued_experiments": queued,
        "duplicate_suppressed_count": len(duplicate_suppressed),
        "duplicate_suppressed": duplicate_suppressed,
        "stale_payload_count": len(stale_payloads),
        "stale_payloads": stale_payloads,
        "oos_robustness": {
            key: value
            for key, value in oos_robustness.items()
            if key != "queued_review_tasks"
        },
        "queued_review_tasks": oos_robustness.get("queued_review_tasks") or [],
    }


def build_dispatch_payloads(queue: dict[str, Any], ref: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in queue.get("queued_experiments") or []:
        if item.get("status") != "queued":
            continue
        payloads.append(
            {
                "plan_id": item.get("experiment_id"),
                "experiment_id": item.get("experiment_id"),
                "source_leak": item.get("source_leak"),
                "source_run_id": item.get("source_run_id"),
                "workflow_id": item.get("workflow") or "full_rebuild_manual.yml",
                "ref": ref,
                "inputs": item.get("workflow_dispatch_inputs") or {},
                "requires_user_approval": True,
                "production_mutation_allowed": False,
                "depends_on_plan_ids": item.get("depends_on_plan_ids") or [],
                "status": item.get("status") or "queued",
                "payload_hash": item.get("payload_hash"),
                "ledger_sha_at_queue": item.get("ledger_sha_at_queue"),
            }
        )
    return payloads


def render_dispatch_script(payloads: list[dict[str, Any]], repo: str) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# Review-only generated commands. Inspect before running.",
        "",
    ]
    for payload in payloads:
        payload_name = str(payload.get("plan_id") or payload.get("experiment_id") or "payload")
        dependencies = [str(item) for item in payload.get("depends_on_plan_ids") or []]
        workflow_id = shlex.quote(str(payload.get("workflow_id") or "full_rebuild_manual.yml"))
        ref = shlex.quote(str(payload.get("ref") or "master"))
        parts = ["gh", "workflow", "run", workflow_id, "--repo", shlex.quote(repo), "--ref", ref]
        for key, value in sorted((payload.get("inputs") or {}).items()):
            parts.extend(["-f", shlex.quote(f"{key}={value}")])
        command = " ".join(parts)
        lines.append("# " + payload_name)
        if dependencies:
            lines.append("# blocked until completed_plan_id: " + ",".join(dependencies))
            lines.append("# " + command)
        else:
            lines.append(command)
        lines.append("")
    return "\n".join(lines)


def render_markdown(queue: dict[str, Any]) -> str:
    oos = queue.get("oos_robustness") if isinstance(queue.get("oos_robustness"), dict) else {}
    lines = [
        "# Self-Correction Router Queue",
        "",
        "- production_mutation_allowed: `false`",
        f"- latest_focus: `{queue.get('latest_focus') or 'none'}`",
        f"- repeat_confirmed: `{str(queue.get('repeat_confirmed')).lower()}`",
        f"- requires_completed_plan_ids: `{','.join(queue.get('requires_completed_plan_ids') or []) or 'none'}`",
        f"- duplicate_suppressed_count: `{queue.get('duplicate_suppressed_count') or 0}`",
        f"- stale_payload_count: `{queue.get('stale_payload_count') or 0}`",
        f"- oos_lock_status: `{oos.get('status') or 'not_checked'}`",
        "",
        "| Experiment | Status | Source Leak | Source Run | Env | Requires Approval |",
        "| --- | --- | --- | --- | --- | :---: |",
    ]
    for item in queue.get("queued_experiments") or []:
        env = ", ".join(f"{k}={v}" for k, v in (item.get("env") or {}).items())
        lines.append(
            f"| {item.get('experiment_id')} | {item.get('status')} | {item.get('source_leak')} | "
            f"{item.get('source_run_id') or ''} | {env} | yes |"
        )
    lines.extend(
        [
            "",
            "## Dispatch Artifacts",
            "",
            "- `workflow_dispatch_payloads.json`: REST/GraphQL-ready workflow dispatch payloads.",
            "- `workflow_dispatch_commands.sh`: equivalent `gh workflow run` commands for manual review.",
            "- These files are generated only; this router never dispatches workflows itself.",
        ]
    )
    tasks = queue.get("queued_review_tasks") or []
    lines.extend(["", "## Review Tasks", ""])
    if tasks:
        lines.extend(
            [
                "| Task | Portfolio | Failure | Dispatch Mode | Next Action |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for task in tasks:
            lines.append(
                "| {task} | {portfolio} | {failure} | {mode} | {next_action} |".format(
                    task=task.get("task_id"),
                    portfolio=task.get("portfolio"),
                    failure=task.get("failure"),
                    mode=task.get("dispatch_mode"),
                    next_action=task.get("next_action"),
                )
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = repo_path(args.ledger_dir)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "ledger.jsonl"
    rows = read_ledger(ledger_path)
    ledger_sha = sha256_file(ledger_path)
    latest_verdict = read_json(ledger_dir / "latest_verdict.json")
    latest_run_arg = getattr(args, "latest_run", None)
    latest_run = repo_path(latest_run_arg) if latest_run_arg else ledger_dir.parent / "outputs"
    previous_queue_arg = getattr(args, "previous_queue", "")
    previous_queue_path = repo_path(previous_queue_arg) if previous_queue_arg else output_dir / "router_queue.json"
    previous_queue = read_json(previous_queue_path) if previous_queue_path.exists() else {}
    queue = build_queue(
        rows,
        latest_verdict,
        int(args.min_repeat),
        latest_run=latest_run,
        ledger_sha=ledger_sha,
        previous_queue=previous_queue,
    )
    dispatch_payloads = build_dispatch_payloads(queue, args.ref)
    queue["dispatch_payload_count"] = len(dispatch_payloads)
    queue["queued_review_task_count"] = len(queue.get("queued_review_tasks") or [])
    (output_dir / "router_queue.json").write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "workflow_dispatch_payloads.json").write_text(json.dumps(dispatch_payloads, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "workflow_dispatch_commands.sh").write_text(render_dispatch_script(dispatch_payloads, args.repo) + "\n", encoding="utf-8")
    (output_dir / "router_queue.md").write_text(render_markdown(queue), encoding="utf-8")
    (output_dir / "queue_state.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True, default=str) + "\n" for item in queue.get("queued_experiments") or []),
        encoding="utf-8",
    )
    (output_dir / "deduped_queue.json").write_text(
        json.dumps(
            {
                "queued_experiments": queue.get("queued_experiments") or [],
                "duplicate_suppressed_count": queue.get("duplicate_suppressed_count") or 0,
                "duplicate_suppressed": queue.get("duplicate_suppressed") or [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "stale_payloads.json").write_text(json.dumps(queue.get("stale_payloads") or [], indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "closure_report.md").write_text(render_markdown(queue), encoding="utf-8")
    print(json.dumps({"latest_focus": queue.get("latest_focus"), "queued": len(queue.get("queued_experiments") or [])}, indent=2))
    return queue


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", default="cloud_results/performance_ledger")
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/self_correction_router")
    parser.add_argument("--min-repeat", type=int, default=2)
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", "master"))
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "wscha231/r1000-quant-engine"))
    parser.add_argument("--previous-queue", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
