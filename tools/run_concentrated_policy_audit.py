#!/usr/bin/env python3
"""Generate research-only concentrated sleeve policy audit outputs."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_concentrated_policy import (  # noqa: E402
    CONCENTRATED_CAPACITY_MAPS,
    CONCENTRATED_POLICY_BY_REGIME,
    audit_concentrated_portfolio,
    safe_float,
)


DEFAULT_SCORED = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_CONCENTRATED = "cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_portfolio_latest.csv"
DEFAULT_METRICS = "cloud_results/full_rebuild/latest_global_alpha_universe/concentrated_backtest_metrics.json"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv_rows(path_like: str | Path) -> list[dict[str, str]]:
    path = repo_path(path_like)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def read_json(path_like: str | Path) -> Any:
    path = repo_path(path_like)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def render_report(audit: dict[str, Any], metrics: dict[str, Any]) -> str:
    cap_violations = audit.get("cap_violations") or []
    entry_blocked = audit.get("entry_blocked") or []
    risk_blocked = audit.get("risk_blocked") or []
    rows = audit.get("rows") or []
    cagr = metrics.get("cagr", metrics.get("strategy_cagr"))
    lines = [
        "# Concentrated Policy Audit",
        "",
        "This is a research-only policy audit. It does not change concentrated selection, weighting, or execution.",
        "",
        "## Latest Sleeve",
        "",
        f"- Regime: `{audit.get('regime_state')}`",
        f"- Current positions: {audit.get('current_n')}",
        f"- Current concentrated weight sum: {safe_float(audit.get('current_weight_sum')):.2%}",
        f"- Balanced recommended capacity: {safe_float(audit.get('recommended_capacity')):.2%}",
        f"- Balanced recommended target N: {audit.get('recommended_target_n')}",
        f"- Cap violations: {len(cap_violations)}",
        f"- Entry-gate blocked current holdings: {len(entry_blocked)}",
        f"- Risk-gate blocked current holdings: {len(risk_blocked)}",
        "",
        "## Historical Reference",
        "",
        f"- CAGR: {safe_float(cagr):.2%}",
        f"- Sharpe: {metrics.get('sharpe')}",
        f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
        "",
        "## Current Holdings Audit",
        "",
    ]
    for row in rows:
        lines.append(
            "- {ticker}: weight {weight:.2%}, conviction {conviction:.3f}, entry {entry}, risk {risk}".format(
                ticker=row.get("ticker"),
                weight=safe_float(row.get("weight")),
                conviction=safe_float(row.get("concentrated_conviction_score")),
                entry="pass" if row.get("entry_gate_pass") else f"blocked({row.get('entry_failed')})",
                risk="pass" if row.get("risk_gate_pass") else f"blocked({row.get('risk_failed')})",
            )
        )
    lines.extend(
        [
            "",
            "## Policy Maps",
            "",
            "- Conservative, balanced, and aggressive capacity maps are exported in `policy_maps_latest.json`.",
            "- Promotion path remains: cap audit -> timing backtest -> orchestrator backtest -> approval.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--concentrated", default=DEFAULT_CONCENTRATED)
    parser.add_argument("--metrics", default=DEFAULT_METRICS)
    parser.add_argument("--out-dir", default="outputs/concentrated_policy")
    parser.add_argument("--regime", default=None)
    args = parser.parse_args()

    concentrated_path = repo_path(args.concentrated)
    scored_path = repo_path(args.scored)
    if not concentrated_path.exists():
        print(f"[concentrated-policy] missing concentrated input: {concentrated_path}")
        return 2
    if not scored_path.exists():
        print(f"[concentrated-policy] missing scored input: {scored_path}")
        return 2

    holdings = read_csv_rows(concentrated_path)
    scored_rows = read_csv_rows(scored_path)
    audit = audit_concentrated_portfolio(
        holdings,
        scored_rows=scored_rows,
        regime_state=args.regime,
        policy=CONCENTRATED_POLICY_BY_REGIME,
    )
    metrics = read_json(args.metrics)

    out_dir = repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "policy_audit_latest.json", audit)
    write_json(
        out_dir / "policy_maps_latest.json",
        {
            "capacity_maps": CONCENTRATED_CAPACITY_MAPS,
            "balanced_policy": CONCENTRATED_POLICY_BY_REGIME,
            "research_only": True,
            "production_activation_allowed": False,
        },
    )
    write_csv_rows(
        out_dir / "policy_audit_latest.csv",
        audit.get("rows") or [],
        [
            "ticker",
            "name",
            "sector",
            "weight",
            "concentrated_score",
            "concentrated_conviction_score",
            "entry_gate_pass",
            "risk_gate_pass",
            "entry_failed",
            "risk_failed",
        ],
    )
    (out_dir / "policy_report.md").write_text(render_report(audit, metrics), encoding="utf-8")
    print(f"[concentrated-policy] wrote {out_dir / 'policy_audit_latest.json'}")
    print(f"[concentrated-policy] wrote {out_dir / 'policy_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
