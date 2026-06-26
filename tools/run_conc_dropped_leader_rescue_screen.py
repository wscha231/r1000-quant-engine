#!/usr/bin/env python3
"""Screen the Concentrated dropped-leader rescue hypothesis before A/B.

This is a research-only, measurement-only preflight.  It reads the
right-tail drop-counterfactual audit and determines whether a training-only
segment screen exists for the narrow Concentrated dropped-leader rescue work
order.  It never mutates target books, production gates, live trading, or
policy defaults.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_BASE_DIR = Path("outputs")
DEFAULT_OUTPUT_DIR = Path("outputs/conc_dropped_leader_rescue_screen")
DEFAULT_DROP_COUNTERFACTUAL = Path("right_tail_drop_counterfactual_audit/drop_counterfactuals.csv")

CLEAN7Y_START_DATE = pd.Timestamp("2019-06-03")
IS_END_DATE = pd.Timestamp("2024-06-02")
OOS_START_DATE = pd.Timestamp("2024-06-03")

SEGMENT_FIELDS = (
    "candidate_sector",
    "candidate_industry_group",
    "candidate_regime_state",
    "candidate_market_style_regime_label",
    "candidate_portfolio_sleeve_label",
)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")


def read_drop_counterfactuals(base_dir: Path) -> pd.DataFrame:
    path = base_dir / DEFAULT_DROP_COUNTERFACTUAL
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def high_signal_mask(frame: pd.DataFrame, *, min_rank: float, min_stack: int) -> pd.Series:
    rank = pd.to_numeric(frame.get("candidate_rank_percentile"), errors="coerce").fillna(0.0)
    stack = pd.to_numeric(frame.get("drop_signal_stack_count"), errors="coerce").fillna(0.0)
    rs_3m = pd.to_numeric(frame.get("rs_benchmark_3m"), errors="coerce").fillna(0.0)
    rs_6m = pd.to_numeric(frame.get("rs_benchmark_6m"), errors="coerce").fillna(0.0)
    flags = frame.get("drop_ex_ante_signal_flags", pd.Series("", index=frame.index)).astype(str)
    above_trend = flags.str.contains("above_ma200", case=False, regex=False)
    return (
        frame.get("portfolio", pd.Series("", index=frame.index)).astype(str).str.lower().eq("concentrated")
        & rank.ge(float(min_rank))
        & stack.ge(float(min_stack))
        & rs_3m.gt(0.0)
        & rs_6m.gt(0.0)
        & above_trend
    )


def completed_126d_excess(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    status = frame.get("fwd_126d_status", pd.Series("", index=frame.index)).astype(str).str.lower()
    values = pd.to_numeric(frame.get("fwd_126d_excess_spy"), errors="coerce")
    return values[status.eq("completed") & values.notna()]


def segment_row(
    *,
    group_field: str,
    group_value: str,
    train: pd.DataFrame,
    oos: pd.DataFrame,
    min_is_observations: int,
    min_is_completed_126d: int,
    min_oos_completed_126d: int,
    min_positive_rate: float,
) -> dict[str, Any]:
    train_completed = completed_126d_excess(train)
    oos_completed = completed_126d_excess(oos)
    train_positive_rate = float((train_completed > 0).mean()) if len(train_completed) else 0.0
    oos_positive_rate = float((oos_completed > 0).mean()) if len(oos_completed) else 0.0
    train_avg = float(train_completed.mean()) if len(train_completed) else 0.0
    oos_avg = float(oos_completed.mean()) if len(oos_completed) else 0.0
    is_candidate = (
        len(train) >= int(min_is_observations)
        and len(train_completed) >= int(min_is_completed_126d)
        and train_positive_rate >= float(min_positive_rate)
        and train_avg > 0.0
    )
    oos_interpretable = len(oos_completed) >= int(min_oos_completed_126d)
    oos_pass = bool(oos_interpretable and oos_positive_rate >= float(min_positive_rate) and oos_avg > 0.0)
    return {
        "group_field": group_field,
        "group_value": group_value,
        "is_observations": int(len(train)),
        "is_completed_126d_count": int(len(train_completed)),
        "is_avg_126d_excess_spy": train_avg,
        "is_positive_126d_rate": train_positive_rate,
        "is_segment_candidate": bool(is_candidate),
        "oos_observations": int(len(oos)),
        "oos_completed_126d_count": int(len(oos_completed)),
        "oos_avg_126d_excess_spy": oos_avg,
        "oos_positive_126d_rate": oos_positive_rate,
        "oos_interpretable": bool(oos_interpretable),
        "oos_pass": bool(oos_pass),
    }


def screen_segments(
    frame: pd.DataFrame,
    *,
    min_is_observations: int,
    min_is_completed_126d: int,
    min_oos_completed_126d: int,
    min_positive_rate: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return pd.DataFrame()
    for field in SEGMENT_FIELDS:
        if field not in frame.columns:
            continue
        for value, group in frame.dropna(subset=[field]).groupby(field, dropna=True):
            value_text = str(value).strip()
            if not value_text:
                continue
            train = group[group["drop_date"].le(IS_END_DATE)].copy()
            oos = group[group["drop_date"].ge(OOS_START_DATE)].copy()
            rows.append(
                segment_row(
                    group_field=field,
                    group_value=value_text,
                    train=train,
                    oos=oos,
                    min_is_observations=min_is_observations,
                    min_is_completed_126d=min_is_completed_126d,
                    min_oos_completed_126d=min_oos_completed_126d,
                    min_positive_rate=min_positive_rate,
                )
            )
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(
        ["is_segment_candidate", "oos_interpretable", "is_avg_126d_excess_spy", "is_completed_126d_count"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)


def choose_status(segments: pd.DataFrame) -> tuple[str, dict[str, Any] | None]:
    if segments.empty or not bool(segments.get("is_segment_candidate", pd.Series(dtype=bool)).any()):
        return "no_segment_candidate", None
    candidates = segments[segments["is_segment_candidate"].astype(bool)].copy()
    interpretable = candidates[candidates["oos_interpretable"].astype(bool)].copy()
    if interpretable.empty:
        return "inconclusive_oos_sample", candidates.iloc[0].to_dict()
    passing = interpretable[interpretable["oos_pass"].astype(bool)].copy()
    if passing.empty:
        return "oos_rejected", interpretable.iloc[0].to_dict()
    return "segment_candidate_ready_for_target_book_screen", passing.iloc[0].to_dict()


def render_report(summary: dict[str, Any], segments: pd.DataFrame) -> str:
    selected = summary.get("selected_segment") or {}
    lines = [
        "# Concentrated Dropped-Leader Rescue Screen",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Policy eligible: `{str(summary.get('policy_eligible')).lower()}`",
        f"- Used forward return in ranking: `{str(summary.get('used_forward_return_in_ranking')).lower()}`",
        f"- High-signal concentrated rows: `{summary.get('high_signal_concentrated_rows')}`",
        f"- IS window: `{summary.get('is_window', {}).get('start')}` to `{summary.get('is_window', {}).get('end')}`",
        f"- OOS window: `{summary.get('oos_window', {}).get('start')}` to `{summary.get('oos_window', {}).get('end')}`",
        "",
    ]
    if selected:
        lines.extend(
            [
                "## Selected / Blocking Segment",
                "",
                f"- group_field: `{selected.get('group_field')}`",
                f"- group_value: `{selected.get('group_value')}`",
                f"- IS completed 126d: `{selected.get('is_completed_126d_count')}`",
                f"- IS avg 126d excess SPY: `{safe_float(selected.get('is_avg_126d_excess_spy')):.4f}`",
                f"- OOS completed 126d: `{selected.get('oos_completed_126d_count')}`",
                f"- OOS avg 126d excess SPY: `{safe_float(selected.get('oos_avg_126d_excess_spy')):.4f}`",
                "",
            ]
        )
    if not segments.empty:
        top = segments.head(10).copy()
        cols = [
            "group_field",
            "group_value",
            "is_completed_126d_count",
            "is_avg_126d_excess_spy",
            "is_positive_126d_rate",
            "oos_completed_126d_count",
            "oos_avg_126d_excess_spy",
            "oos_positive_126d_rate",
            "is_segment_candidate",
            "oos_interpretable",
            "oos_pass",
        ]
        table = top[[c for c in cols if c in top.columns]].copy()
        lines.extend(["## Top Segments", ""])
        lines.append("| " + " | ".join(table.columns) + " |")
        lines.append("| " + " | ".join(["---"] * len(table.columns)) + " |")
        for _, row in table.iterrows():
            values = []
            for col in table.columns:
                value = row.get(col, "")
                if isinstance(value, float):
                    values.append(f"{value:.4f}")
                else:
                    values.append(str(value))
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    return "\n".join(lines)


def run(
    *,
    base_dir: Path,
    output_dir: Path,
    min_rank: float = 0.80,
    min_stack: int = 7,
    min_is_observations: int = 5,
    min_is_completed_126d: int = 5,
    min_oos_completed_126d: int = 3,
    min_positive_rate: float = 0.66,
) -> dict[str, Any]:
    raw = read_drop_counterfactuals(base_dir)
    if raw.empty:
        summary = {
            "schema_version": "conc-dropped-leader-rescue-screen-v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "missing_drop_counterfactuals",
            "policy_eligible": False,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
            "used_forward_return_in_ranking": False,
            "base_dir": str(base_dir),
        }
        write_json(output_dir / "summary.json", summary)
        (output_dir / "report.md").write_text(render_report(summary, pd.DataFrame()), encoding="utf-8")
        return summary
    frame = raw.copy()
    frame["drop_date"] = pd.to_datetime(frame.get("drop_date"), errors="coerce")
    frame = frame.dropna(subset=["drop_date"])
    mask = high_signal_mask(frame, min_rank=min_rank, min_stack=min_stack)
    high_signal = frame[mask].copy()
    segments = screen_segments(
        high_signal,
        min_is_observations=min_is_observations,
        min_is_completed_126d=min_is_completed_126d,
        min_oos_completed_126d=min_oos_completed_126d,
        min_positive_rate=min_positive_rate,
    )
    status, selected = choose_status(segments)
    is_candidates = (
        segments[segments["is_segment_candidate"].astype(bool)].copy()
        if not segments.empty and "is_segment_candidate" in segments.columns
        else pd.DataFrame()
    )
    summary = {
        "schema_version": "conc-dropped-leader-rescue-screen-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "policy_eligible": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "used_forward_return_in_ranking": False,
        "base_dir": str(base_dir),
        "drop_counterfactual_rows": int(len(frame)),
        "high_signal_concentrated_rows": int(len(high_signal)),
        "segment_rows": int(len(segments)),
        "is_segment_candidate_count": int(len(is_candidates)),
        "oos_interpretable_segment_count": int(is_candidates["oos_interpretable"].sum()) if not is_candidates.empty else 0,
        "oos_pass_segment_count": int(is_candidates["oos_pass"].sum()) if not is_candidates.empty else 0,
        "thresholds": {
            "min_rank": float(min_rank),
            "min_stack": int(min_stack),
            "min_is_observations": int(min_is_observations),
            "min_is_completed_126d": int(min_is_completed_126d),
            "min_oos_completed_126d": int(min_oos_completed_126d),
            "min_positive_rate": float(min_positive_rate),
        },
        "is_window": {"start": CLEAN7Y_START_DATE.date().isoformat(), "end": IS_END_DATE.date().isoformat()},
        "oos_window": {"start": OOS_START_DATE.date().isoformat(), "end": "latest_available"},
        "selected_segment": selected or {},
        "next_action": (
            "do_not_implement_policy; no training segment survived"
            if status == "no_segment_candidate"
            else "do_not_ship_policy; OOS sample is too sparse"
            if status == "inconclusive_oos_sample"
            else "discard_policy; selected segment failed OOS"
            if status == "oos_rejected"
            else "target_book_screen_allowed_before_broker_ab"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    high_signal.to_csv(output_dir / "high_signal_concentrated_drops.csv", index=False)
    segments.to_csv(output_dir / "segment_screen.csv", index=False)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, segments), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-rank", type=float, default=0.80)
    parser.add_argument("--min-stack", type=int, default=7)
    parser.add_argument("--min-is-observations", type=int, default=5)
    parser.add_argument("--min-is-completed-126d", type=int, default=5)
    parser.add_argument("--min-oos-completed-126d", type=int, default=3)
    parser.add_argument("--min-positive-rate", type=float, default=0.66)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(
        base_dir=Path(args.base_dir),
        output_dir=Path(args.output_dir),
        min_rank=args.min_rank,
        min_stack=args.min_stack,
        min_is_observations=args.min_is_observations,
        min_is_completed_126d=args.min_is_completed_126d,
        min_oos_completed_126d=args.min_oos_completed_126d,
        min_positive_rate=args.min_positive_rate,
    )
    print(json.dumps({k: summary.get(k) for k in ["status", "high_signal_concentrated_rows", "is_segment_candidate_count", "oos_interpretable_segment_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
