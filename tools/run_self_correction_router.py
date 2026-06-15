#!/usr/bin/env python3
"""Route repeated ledger leaks into review-only A/B queue artifacts."""
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
        queued.append(
            {
                **template,
                "workflow": ".github/workflows/full_rebuild_manual.yml",
                "dispatch_mode": "workflow_dispatch_payload_only",
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
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger_dir = repo_path(args.ledger_dir)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_ledger(ledger_dir / "ledger.jsonl")
    latest_verdict = read_json(ledger_dir / "latest_verdict.json")
    queue = build_queue(rows, latest_verdict, int(args.min_repeat))
    (output_dir / "router_queue.json").write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "router_queue.md").write_text(render_markdown(queue), encoding="utf-8")
    print(json.dumps({"latest_focus": queue.get("latest_focus"), "queued": len(queue.get("queued_experiments") or [])}, indent=2))
    return queue


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", default="cloud_results/performance_ledger")
    parser.add_argument("--output-dir", default="outputs/self_correction_router")
    parser.add_argument("--min-repeat", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
