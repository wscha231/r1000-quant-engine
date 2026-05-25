#!/usr/bin/env python3
"""Search conservative crisis/liquidity cash-gate thresholds.

The search optimizes validation split behavior and reports holdout outcomes.
It emits threshold candidates for Phase G; it does not activate production.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_long_crisis_liquidity import evaluate_thresholds  # noqa: E402


DEFAULT_FEATURES = "data_pit/macro/long_crisis_daily_features.parquet"
DEFAULT_OUTPUT_DIR = "outputs/long_crisis_learning"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_features(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def parse_float_grid(text: str) -> list[float]:
    return [float(x.strip()) for x in str(text).split(",") if x.strip()]


def render_report(summary: dict[str, Any], grid: pd.DataFrame) -> str:
    lines = [
        "# Long Crisis Threshold Search",
        "",
        f"- status: `{summary.get('status')}`",
        f"- selected: `{summary.get('selected_reason', '')}`",
        "",
        "## Top Validation Candidates",
        "",
        "| crisis | liquidity | trend | validation score | holdout recall | holdout false positive | holdout signal rate |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not grid.empty:
        val = grid[grid["split"].eq("validation")].sort_values("score", ascending=False).head(10)
        for _, row in val.iterrows():
            key = (row["crisis_gate"], row["liquidity_gate"], row["trend_gate"])
            h = grid[
                grid["split"].eq("holdout")
                & grid["crisis_gate"].eq(key[0])
                & grid["liquidity_gate"].eq(key[1])
                & grid["trend_gate"].eq(key[2])
            ]
            holdout = h.iloc[0] if not h.empty else {}
            lines.append(
                "| "
                f"{row['crisis_gate']:.2f} | {row['liquidity_gate']:.2f} | {row['trend_gate']:.2f} | "
                f"{row['score']:.3f} | {float(holdout.get('recall', 0.0)):.3f} | "
                f"{float(holdout.get('false_positive_rate', 0.0)):.3f} | "
                f"{float(holdout.get('signal_rate', 0.0)):.3f} |"
            )
    lines.extend(["", "Research-only threshold candidates. Phase G broker replay is required before promotion.", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    features_path = repo_path(args.features)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    features = read_features(features_path)
    if features.empty:
        summary = {
            "status": "blocked",
            "reason": "missing long crisis features",
            "features": str(features_path),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "threshold_search_summary.json", summary)
        (output_dir / "threshold_search_report.md").write_text(render_report(summary, pd.DataFrame()), encoding="utf-8")
        print(json.dumps({"status": "blocked", "reason": summary["reason"]}, sort_keys=True))
        return summary

    crisis_grid = parse_float_grid(args.crisis_gates)
    liquidity_grid = parse_float_grid(args.liquidity_gates)
    trend_grid = parse_float_grid(args.trend_gates)
    rows: list[dict[str, Any]] = []
    for crisis_gate, liquidity_gate, trend_gate in product(crisis_grid, liquidity_grid, trend_grid):
        for split in ("train", "validation", "test", "holdout"):
            rows.append(
                evaluate_thresholds(
                    features,
                    crisis_gate=crisis_gate,
                    liquidity_gate=liquidity_gate,
                    trend_gate=trend_gate,
                    split=split,
                    drawdown_col=args.label,
                )
            )
    grid = pd.DataFrame(rows)
    grid_path = output_dir / "threshold_grid.csv"
    grid.to_csv(grid_path, index=False)

    ok = grid[grid["status"].eq("ok")].copy()
    selected: dict[str, Any] = {}
    selected_reason = "no_valid_candidate"
    if not ok.empty:
        validation = ok[ok["split"].eq("validation")].copy()
        # CAGR-preserving preference: disallow threshold sets with too many
        # signals or excessive false positives before choosing by score.
        safe = validation[
            validation["signal_rate"].le(float(args.max_signal_rate))
            & validation["false_positive_rate"].le(float(args.max_false_positive_rate))
        ].copy()
        if safe.empty:
            safe = validation.copy()
            selected_reason = "fallback_best_validation_score"
        else:
            selected_reason = "safe_validation_candidate"
        if not safe.empty:
            best = safe.sort_values(["score", "recall", "false_positive_rate"], ascending=[False, False, True]).iloc[0]
            selected = {
                "crisis_gate": float(best["crisis_gate"]),
                "liquidity_gate": float(best["liquidity_gate"]),
                "trend_gate": float(best["trend_gate"]),
                "governor_thresholds": {
                    "low": max(0.20, float(best["crisis_gate"]) - 0.15),
                    "mid": float(best["crisis_gate"]),
                    "high": min(0.90, float(best["crisis_gate"]) + 0.20),
                },
                "cash_hard_gate": {
                    "liquidity_gate": float(best["liquidity_gate"]),
                    "trend_gate": float(best["trend_gate"]),
                    "credit_gate": 0.55,
                },
                "validation": best.to_dict(),
            }
    if selected:
        write_json(output_dir / "best_thresholds.json", selected)
    summary = {
        "status": "completed" if selected else "blocked",
        "reason": "" if selected else "no threshold candidate selected",
        "schema_version": "long-crisis-threshold-search-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "features": str(features_path),
        "threshold_grid": str(grid_path),
        "best_thresholds": str(output_dir / "best_thresholds.json") if selected else "",
        "selected_reason": selected_reason,
        "selected": selected,
    }
    write_json(output_dir / "threshold_search_summary.json", summary)
    (output_dir / "threshold_search_report.md").write_text(render_report(summary, grid), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "grid_rows": int(len(grid)), "selected": selected}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", default=DEFAULT_FEATURES)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", default="future_63d_drawdown_le_15pct")
    parser.add_argument("--crisis-gates", default="0.35,0.45,0.55,0.65")
    parser.add_argument("--liquidity-gates", default="0.20,0.35,0.50,0.65")
    parser.add_argument("--trend-gates", default="0.20,0.35,0.50")
    parser.add_argument("--max-signal-rate", type=float, default=0.35)
    parser.add_argument("--max-false-positive-rate", type=float, default=0.45)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())

