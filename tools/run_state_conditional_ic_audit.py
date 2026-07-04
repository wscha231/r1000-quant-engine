#!/usr/bin/env python3
"""Research-only R2 state-conditional feature-family IC audit."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.research_audit_utils import first_existing, read_csv, repo_path, safe_float, spearman, write_json  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/state_conditional_ic_audit"
FORWARD_LABELS = ["forward_126d_excess", "forward_63d_excess", "period_forward_return"]
FEATURE_FAMILIES = {
    "momentum": [
        "rs_spy_3m",
        "rs_spy_6m",
        "rs_spy_12m",
        "rs_qqq_3m",
        "rs_theme_3m",
        "near_52w_high_pct",
        "relative_strength_composite",
    ],
    "turnaround_quality": [
        "value_inflection_score",
        "cashflow_inflection_under_loss_score",
        "fundamental_turnaround_acceleration_score",
        "h1_oversold_value_score",
        "profitability_inflection_score",
    ],
}


def load_inputs(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        frame = read_csv(path)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["source_file"] = str(path)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def attach_state(frame: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    date_col = "rebalance_date" if "rebalance_date" in out.columns else "date"
    out["rebalance_date"] = pd.to_datetime(out[date_col], errors="coerce").dt.normalize()
    states = states.copy()
    states["date"] = pd.to_datetime(states["date"], errors="coerce").dt.normalize()
    states = states.dropna(subset=["date"]).sort_values("date")
    if states.empty:
        out["state"] = "UNKNOWN"
        return out
    joined = pd.merge_asof(out.sort_values("rebalance_date"), states[["date", "state"]], left_on="rebalance_date", right_on="date", direction="backward")
    joined["state"] = joined["state"].fillna("UNKNOWN")
    return joined


def family_score(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    present = [col for col in cols if col in frame.columns]
    if not present:
        return pd.Series(index=frame.index, dtype=float)
    ranked = []
    for col in present:
        values = pd.to_numeric(frame[col], errors="coerce")
        if values.notna().any():
            ranked.append(values.rank(pct=True))
    if not ranked:
        return pd.Series(index=frame.index, dtype=float)
    return pd.concat(ranked, axis=1).mean(axis=1)


def era_count(dates: pd.Series) -> int:
    parsed = pd.to_datetime(dates, errors="coerce")
    return int(parsed.dropna().dt.year.nunique())


def month_count(dates: pd.Series) -> int:
    parsed = pd.to_datetime(dates, errors="coerce")
    return int(parsed.dropna().dt.to_period("M").nunique())


def fold_ic_metrics(d: pd.DataFrame, score_col: str, label_col: str, oos_start: str) -> dict[str, Any]:
    if not oos_start:
        return {"is_ic": None, "oos_ic": None, "oos_noncollapse": False, "ic_sign_stable_across_folds": False}
    split = pd.Timestamp(oos_start)
    dated = d.copy()
    dated["_date"] = pd.to_datetime(dated["rebalance_date"], errors="coerce")
    is_part = dated[dated["_date"] < split]
    oos_part = dated[dated["_date"] >= split]
    is_ic = spearman(is_part[score_col], is_part[label_col]) if len(is_part) >= 3 else None
    oos_ic = spearman(oos_part[score_col], oos_part[label_col]) if len(oos_part) >= 3 else None
    if is_ic is None or oos_ic is None:
        stable = False
        noncollapse = False
    else:
        stable = (is_ic >= 0 and oos_ic >= 0) or (is_ic <= 0 and oos_ic <= 0)
        noncollapse = bool(oos_ic >= -0.02)
    return {
        "is_ic": is_ic,
        "oos_ic": oos_ic,
        "oos_noncollapse": bool(noncollapse),
        "ic_sign_stable_across_folds": bool(stable),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    r3_min_samples = int(getattr(args, "r3_min_samples", 60))
    r3_min_eras = int(getattr(args, "r3_min_eras", 2))
    r3_min_state_months = int(getattr(args, "r3_min_state_months", 6))
    oos_start = str(getattr(args, "oos_start", "") or "")
    inputs = [repo_path(path) for path in args.inputs]
    frame = load_inputs(inputs)
    states = read_csv(repo_path(args.state_history))
    label_col = first_existing(frame, FORWARD_LABELS)
    rows: list[dict[str, Any]] = []
    if not frame.empty and not states.empty and label_col:
        frame = attach_state(frame, states)
        for family, cols in FEATURE_FAMILIES.items():
            frame[f"{family}_score"] = family_score(frame, cols)
        for state, group in frame.groupby("state", dropna=False):
            for family in FEATURE_FAMILIES:
                score_col = f"{family}_score"
                d = group[[score_col, label_col]].dropna()
                if "rebalance_date" in group.columns:
                    dated = group[[score_col, label_col, "rebalance_date"]].dropna(subset=[score_col, label_col])
                else:
                    dated = d.copy()
                    dated["rebalance_date"] = pd.NaT
                fold_metrics = fold_ic_metrics(dated, score_col, label_col, oos_start)
                e_count = era_count(dated["rebalance_date"])
                m_count = month_count(dated["rebalance_date"])
                completed = len(d) >= int(args.min_samples)
                r3_row_eligible = (
                    len(d) >= r3_min_samples
                    and e_count >= r3_min_eras
                    and m_count >= r3_min_state_months
                    and bool(fold_metrics["oos_noncollapse"])
                    and bool(fold_metrics["ic_sign_stable_across_folds"])
                )
                rows.append(
                    {
                        "state": state,
                        "feature_family": family,
                        "status": "completed" if completed else "insufficient_sample",
                        "sample_count": int(len(d)),
                        "era_count": e_count,
                        "state_month_count": m_count,
                        "ic": spearman(d[score_col], d[label_col]),
                        **fold_metrics,
                        "r3_row_eligible": bool(r3_row_eligible),
                        "forward_label": label_col,
                        "forward_return_is_audit_label_only": True,
                    }
                )
    table = pd.DataFrame(rows)
    table.to_csv(output_dir / "ic_by_state_and_feature_family.csv", index=False)
    proceed = False
    if not table.empty:
        eligible = table[table["r3_row_eligible"].eq(True)].copy()
        pivot = eligible.pivot_table(index="state", columns="feature_family", values="ic", aggfunc="mean")
        for state in ["CORRECTION", "BEAR", "RECOVERY"]:
            if state in pivot.index:
                turn = safe_float(pivot.loc[state].get("turnaround_quality"), default=-999.0)
                mom = safe_float(pivot.loc[state].get("momentum"), default=999.0)
                if turn - mom >= float(args.material_ic_gap):
                    proceed = True
    payload = {
        "schema_version": "state-conditional-ic-audit-v1",
        "status": "completed" if rows else "blocked",
        "reason": "" if rows else "missing_state_history_or_forward_labels",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(path) for path in inputs],
        "state_history": str(repo_path(args.state_history)),
        "forward_label": label_col,
        "proceed_to_r3_gate_pass": bool(proceed),
        "r3_authorized": bool(proceed),
        "r3_min_samples": r3_min_samples,
        "r3_min_eras": r3_min_eras,
        "r3_min_state_months": r3_min_state_months,
        "oos_start": oos_start,
        "forward_return_is_audit_label_only": True,
        "forward_labels_used_for_ranking": False,
        "research_only": True,
        "production_activation_allowed": False,
        "policy_hook_allowed": False,
    }
    write_json(output_dir / "summary.json", payload)
    lines = [
        "# State Conditional IC Audit",
        "",
        f"- status: `{payload['status']}`",
        f"- proceed to R3 gate pass: `{str(proceed).lower()}`",
        "- policy hook allowed: `false`",
        "",
        "| state | family | n | IC | status |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        lines.append(f"| {row.get('state')} | {row.get('feature_family')} | {row.get('sample_count')} | {row.get('ic')} | {row.get('status')} |")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--state-history", required=True)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--material-ic-gap", type=float, default=0.05)
    parser.add_argument("--r3-min-samples", type=int, default=60)
    parser.add_argument("--r3-min-eras", type=int, default=2)
    parser.add_argument("--r3-min-state-months", type=int, default=6)
    parser.add_argument("--oos-start", default="")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
