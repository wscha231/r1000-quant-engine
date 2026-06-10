#!/usr/bin/env python3
"""Generate research-only Main v2 shadow portfolio outputs."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_main_v2 import (  # noqa: E402
    MAIN_V2_BALANCED_POLICY,
    compose_main_sleeve_portfolio,
    result_to_rows,
    safe_float,
)


DEFAULT_SCORED = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_CURRENT_PORTFOLIO = "cloud_results/full_rebuild/latest_global_alpha_universe/portfolio_latest.csv"
DEFAULT_BASELINE_METRICS = "cloud_results/full_rebuild/latest_global_alpha_universe/backtest_metrics.json"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv_rows(path_like: str | Path) -> list[dict[str, str]]:
    path = repo_path(path_like)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


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


def read_json(path_like: str | Path) -> Any:
    path = repo_path(path_like)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def summarize_current_portfolio(path_like: str | Path) -> dict[str, Any]:
    path = repo_path(path_like)
    if not path.exists():
        return {"path": str(path), "available": False}
    rows = read_csv_rows(path)
    equity_rows = [row for row in rows if str(row.get("ticker", "")).upper() != "CASH"]
    cash = sum(safe_float(row.get("weight")) for row in rows if str(row.get("ticker", "")).upper() == "CASH")
    return {
        "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "available": True,
        "n_positions": len(equity_rows),
        "cash_weight": cash,
        "top_weights": [
            {
                "ticker": row.get("ticker"),
                "weight": safe_float(row.get("weight")),
                "sleeve": row.get("portfolio_sleeve_label"),
            }
            for row in equity_rows[:10]
        ],
    }


def render_report(result: dict[str, Any], current: dict[str, Any], baseline_metrics: dict[str, Any]) -> str:
    audit = result.get("audit", {})
    lines = [
        "# Main v2 Shadow Report",
        "",
        "This is a research-only shadow portfolio. It does not replace production main.",
        "",
        "## Main v2 Latest",
        "",
        f"- Regime: `{result.get('regime_state')}`",
        f"- Positions: {audit.get('n_positions')}",
        f"- Cash target: {safe_float(result.get('cash_target')):.2%}",
        f"- Single-name cap: {safe_float(audit.get('single_name_cap')):.2%}",
        f"- Conflicts: {audit.get('n_conflicts')}",
        f"- Cap excess to cash: {safe_float(audit.get('cap_excess_to_cash')):.2%}",
        "",
        "## Current Main Reference",
        "",
        f"- Positions: {current.get('n_positions')}",
        f"- Cash weight: {safe_float(current.get('cash_weight')):.2%}",
        f"- Baseline CAGR: {safe_float(baseline_metrics.get('cagr')):.2%}",
        f"- Baseline Sharpe: {baseline_metrics.get('sharpe')}",
        f"- Baseline MaxDD: {safe_float(baseline_metrics.get('max_dd')):.2%}",
        "",
        "## Sleeve Selection",
        "",
    ]
    for sleeve, rows in (result.get("selected_by_sleeve") or {}).items():
        tickers = ", ".join(str(row.get("ticker")) for row in rows)
        lines.append(f"- {sleeve}: {tickers}")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Main v2 concentrates the current broad main book into independent core/future/early books. "
            "The latest neutral policy targets 25% core, 55% future, 15% early, and 5% cash before caps.",
            "",
            "Promotion requires a historical backtest against legacy main; this latest snapshot is only the first wiring step.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", default=DEFAULT_SCORED)
    parser.add_argument("--current-portfolio", default=DEFAULT_CURRENT_PORTFOLIO)
    parser.add_argument("--baseline-metrics", default=DEFAULT_BASELINE_METRICS)
    parser.add_argument("--out-dir", default="outputs/main_v2")
    parser.add_argument("--regime", default=None)
    args = parser.parse_args()

    scored_path = repo_path(args.scored)
    if not scored_path.exists():
        print(f"[main-v2] missing scored input: {scored_path}")
        return 2
    rows = read_csv_rows(scored_path)
    result = compose_main_sleeve_portfolio(rows, regime_state=args.regime, policy=MAIN_V2_BALANCED_POLICY)

    out_dir = repo_path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "main_v2_latest.json", result)
    write_json(out_dir / "main_v2_audit_latest.json", result.get("audit", {}))
    out_rows = result_to_rows(result)
    write_csv_rows(
        out_dir / "main_v2_latest.csv",
        out_rows,
        ["rank", "ticker", "target_weight", "main_v2_sleeves", "main_v2_score", "regime_state", "row_type"],
    )
    selected_rows: list[dict[str, Any]] = []
    for sleeve, items in (result.get("selected_by_sleeve") or {}).items():
        for rank, item in enumerate(items, start=1):
            selected_rows.append({"sleeve": sleeve, "rank": rank, **item})
    write_csv_rows(out_dir / "main_v2_selected_by_sleeve.csv", selected_rows)

    current = summarize_current_portfolio(args.current_portfolio)
    baseline_metrics = read_json(args.baseline_metrics)
    comparison = {
        "research_only": True,
        "current_main": current,
        "baseline_metrics": baseline_metrics,
        "main_v2_audit": result.get("audit", {}),
        "production_activation_allowed": False,
    }
    write_json(out_dir / "main_v2_comparison_latest.json", comparison)
    (out_dir / "main_v2_report.md").write_text(
        render_report(result, current, baseline_metrics),
        encoding="utf-8",
    )
    print(f"[main-v2] wrote {out_dir / 'main_v2_latest.csv'}")
    print(f"[main-v2] wrote {out_dir / 'main_v2_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
