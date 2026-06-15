#!/usr/bin/env python3
"""Route repeated ledger leaks into review-only A/B queue artifacts."""
from __future__ import annotations

import argparse
import json
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
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


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


def build_queue(ledger_rows: list[dict[str, Any]], latest_verdict: dict[str, Any], min_repeat: int) -> dict[str, Any]:
    latest_focus = latest_verdict.get("dominant_open_leak") or (dominant_for_row(ledger_rows[-1]) if ledger_rows else None)
    recent_focuses = [dominant_for_row(row) for row in ledger_rows[-min_repeat:]]
    repeated = bool(latest_focus and len(recent_focuses) >= min_repeat and all(item == latest_focus for item in recent_focuses))
    templates = LEAK_EXPERIMENTS.get(str(latest_focus), []) if repeated else []
    queued = []
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
        queued.append(
            {
                **template,
                "workflow": "full_rebuild_manual.yml",
                "dispatch_mode": "workflow_dispatch_payload_only",
                "workflow_dispatch_inputs": workflow_inputs,
                "production_mutation_allowed": False,
                "requires_user_approval": True,
                "source_leak": latest_focus,
            }
        )
    return {
        "schema_version": "self-correction-router-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "production_mutation_allowed": False,
        "latest_focus": latest_focus,
        "recent_focuses": recent_focuses,
        "min_repeat": min_repeat,
        "repeat_confirmed": repeated,
        "queued_experiments": queued,
    }


def build_dispatch_payloads(queue: dict[str, Any], ref: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in queue.get("queued_experiments") or []:
        payloads.append(
            {
                "experiment_id": item.get("experiment_id"),
                "source_leak": item.get("source_leak"),
                "workflow_id": item.get("workflow") or "full_rebuild_manual.yml",
                "ref": ref,
                "inputs": item.get("workflow_dispatch_inputs") or {},
                "requires_user_approval": True,
                "production_mutation_allowed": False,
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
        workflow_id = shlex.quote(str(payload.get("workflow_id") or "full_rebuild_manual.yml"))
        ref = shlex.quote(str(payload.get("ref") or "master"))
        parts = ["gh", "workflow", "run", workflow_id, "--repo", shlex.quote(repo), "--ref", ref]
        for key, value in sorted((payload.get("inputs") or {}).items()):
            parts.extend(["-f", shlex.quote(f"{key}={value}")])
        lines.append("# " + str(payload.get("experiment_id")))
        lines.append(" ".join(parts))
        lines.append("")
    return "\n".join(lines)


def render_markdown(queue: dict[str, Any]) -> str:
    lines = [
        "# Self-Correction Router Queue",
        "",
        "- production_mutation_allowed: `false`",
        f"- latest_focus: `{queue.get('latest_focus') or 'none'}`",
        f"- repeat_confirmed: `{str(queue.get('repeat_confirmed')).lower()}`",
        "",
        "| Experiment | Source Leak | Env | Requires Approval |",
        "| --- | --- | --- | :---: |",
    ]
    for item in queue.get("queued_experiments") or []:
        env = ", ".join(f"{k}={v}" for k, v in (item.get("env") or {}).items())
        lines.append(f"| {item.get('experiment_id')} | {item.get('source_leak')} | {env} | yes |")
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
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = repo_path(args.ledger_dir)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_ledger(ledger_dir / "ledger.jsonl")
    latest_verdict = read_json(ledger_dir / "latest_verdict.json")
    queue = build_queue(rows, latest_verdict, int(args.min_repeat))
    dispatch_payloads = build_dispatch_payloads(queue, args.ref)
    queue["dispatch_payload_count"] = len(dispatch_payloads)
    (output_dir / "router_queue.json").write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "workflow_dispatch_payloads.json").write_text(json.dumps(dispatch_payloads, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "workflow_dispatch_commands.sh").write_text(render_dispatch_script(dispatch_payloads, args.repo) + "\n", encoding="utf-8")
    (output_dir / "router_queue.md").write_text(render_markdown(queue), encoding="utf-8")
    print(json.dumps({"latest_focus": queue.get("latest_focus"), "queued": len(queue.get("queued_experiments") or [])}, indent=2))
    return queue


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", default="cloud_results/performance_ledger")
    parser.add_argument("--output-dir", default="outputs/self_correction_router")
    parser.add_argument("--min-repeat", type=int, default=2)
    parser.add_argument("--ref", default="master")
    parser.add_argument("--repo", default="wscha231/r1000-quant-engine")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
