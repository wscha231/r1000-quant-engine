#!/usr/bin/env python3
"""Research-only financial proxy screen for run287 candidate rows.

This is a cheap source screen. It uses candidate-book financial actual/proxy
columns as decision-time diagnostic signals and period_forward_return only as
an audit label. It does not mutate selection, sizing, production state, or
broker target books.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "run287-financial-proxy-screen-v1"
DEFAULT_CANDIDATE_BOOK = (
    "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe/reports/candidate_replay_book.csv"
)
DEFAULT_OUTPUT_DIR = "outputs/run287_financial_proxy_screen"
DEFAULT_OOS_START = "2024-07-01"

BASE_COLUMNS = ["rebalance_date", "ticker", "Name", "sector", "industry_group", "period_forward_return"]
SIGNAL_COLUMNS = [
    "actual_results_score",
    "eps_revision_score",
    "sales_growth_yoy",
    "eps_growth_yoy",
    "op_income_growth_yoy",
    "ocf_growth_yoy",
    "gross_margins",
    "operating_margins",
    "rev_growth_accel_4q",
    "capital_efficiency_score",
    "profitability_inflection_score",
    "selection_confirmation_score",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_candidate_book(path: Path) -> tuple[pd.DataFrame, list[str]]:
    if not path.exists():
        return pd.DataFrame(), []
    header = pd.read_csv(path, nrows=0)
    available = [col for col in SIGNAL_COLUMNS if col in header.columns]
    usecols = [col for col in BASE_COLUMNS + available if col in header.columns]
    frame = pd.read_csv(path, usecols=usecols, low_memory=False)
    return frame, available


def clean_frame(frame: pd.DataFrame, signals: list[str], oos_start: str) -> pd.DataFrame:
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out.get("rebalance_date"), errors="coerce").dt.normalize()
    out["ticker"] = out.get("ticker", pd.Series(index=out.index, dtype=str)).astype(str).str.upper().str.strip()
    out["forward_return_audit_only"] = pd.to_numeric(out.get("period_forward_return"), errors="coerce")
    out = out[out["rebalance_date"].notna() & out["forward_return_audit_only"].notna()].copy()
    oos_ts = pd.Timestamp(oos_start)
    out["split"] = out["rebalance_date"].map(lambda dt: "oos" if pd.Timestamp(dt) >= oos_ts else "is")
    for signal in signals:
        out[signal] = pd.to_numeric(out[signal], errors="coerce")
    return out


def quantile_stats(frame: pd.DataFrame, signal: str, min_rows: int) -> dict[str, Any]:
    d = frame[[signal, "forward_return_audit_only"]].dropna().copy()
    if len(d) < min_rows or d[signal].nunique() < 3:
        return {"status": "insufficient_rows", "row_count": int(len(d))}
    try:
        d["quantile"] = pd.qcut(d[signal], q=min(5, d[signal].nunique()), labels=False, duplicates="drop")
    except ValueError:
        return {"status": "insufficient_unique_values", "row_count": int(len(d))}
    if d["quantile"].nunique() < 2:
        return {"status": "insufficient_quantiles", "row_count": int(len(d))}
    grouped = d.groupby("quantile")["forward_return_audit_only"].agg(["count", "mean"]).reset_index()
    low = grouped.sort_values("quantile").iloc[0]
    high = grouped.sort_values("quantile").iloc[-1]
    high_rows = d[d["quantile"].eq(high["quantile"])]
    spearman = float(d[signal].rank(method="average").corr(d["forward_return_audit_only"].rank(method="average")))
    return {
        "status": "ok",
        "row_count": int(len(d)),
        "spearman": spearman,
        "low_quantile_count": int(low["count"]),
        "high_quantile_count": int(high["count"]),
        "low_quantile_mean": float(low["mean"]),
        "high_quantile_mean": float(high["mean"]),
        "high_minus_low": float(high["mean"] - low["mean"]),
        "high_quantile_positive_rate": float((high_rows["forward_return_audit_only"] > 0).mean()),
    }


def screen_signal(frame: pd.DataFrame, signal: str, min_rows: int, min_oos_high_count: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    split_stats: dict[str, dict[str, Any]] = {}
    for split, subset in [
        ("full", frame),
        ("is", frame[frame["split"].eq("is")]),
        ("oos", frame[frame["split"].eq("oos")]),
    ]:
        stats = quantile_stats(subset, signal, min_rows)
        split_stats[split] = stats
        row = {"signal": signal, "split": split, **stats}
        rows.append(row)
    full = split_stats.get("full", {})
    is_stats = split_stats.get("is", {})
    oos = split_stats.get("oos", {})
    candidate_positive = (
        full.get("status") == "ok"
        and is_stats.get("status") == "ok"
        and oos.get("status") == "ok"
        and safe_float(full.get("high_minus_low")) > 0
        and safe_float(is_stats.get("high_minus_low")) > 0
        and safe_float(oos.get("high_minus_low")) >= 0
        and safe_float(oos.get("high_quantile_count")) >= min_oos_high_count
    )
    summary = {
        "signal": signal,
        "candidate_positive": bool(candidate_positive),
        "full_high_minus_low": full.get("high_minus_low"),
        "is_high_minus_low": is_stats.get("high_minus_low"),
        "oos_high_minus_low": oos.get("high_minus_low"),
        "oos_high_quantile_count": oos.get("high_quantile_count"),
        "oos_high_quantile_positive_rate": oos.get("high_quantile_positive_rate"),
        "full_spearman": full.get("spearman"),
        "oos_spearman": oos.get("spearman"),
    }
    return summary, rows


def render_report(payload: dict[str, Any], signals: list[dict[str, Any]]) -> str:
    lines = [
        "# Run287 Financial Proxy Screen",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Candidate allowed: `{payload['candidate_allowed']}`",
        f"- Forward returns audit only: `{payload['forward_returns_audit_only']}`",
        f"- OOS start: `{payload['oos_start']}`",
        "",
        "| Signal | Candidate positive | Full high-low | IS high-low | OOS high-low | OOS high count | OOS hit rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in signals:
        lines.append(
            "| {signal} | {candidate_positive} | {full:.2%} | {is_:.2%} | {oos:.2%} | {count} | {hit:.2%} |".format(
                signal=item.get("signal"),
                candidate_positive=item.get("candidate_positive"),
                full=safe_float(item.get("full_high_minus_low")),
                is_=safe_float(item.get("is_high_minus_low")),
                oos=safe_float(item.get("oos_high_minus_low")),
                count=int(safe_float(item.get("oos_high_quantile_count"))),
                hit=safe_float(item.get("oos_high_quantile_positive_rate")),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This is not broker-ledger evidence.",
            "- Financial actual/proxy fields remain diagnostic until a true PIT revision/guidance feed is available.",
            "- A positive screen can only justify a default-off broker A/B design review, not a fullrun.",
            "- A negative or mixed screen blocks hook design from this source family.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = repo_path(args.input)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw, signals = read_candidate_book(input_path)
    if raw.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": "blocked",
            "reason": "missing_or_empty_candidate_book",
            "input": str(input_path),
            "research_only": True,
            "production_promotion_allowed": False,
            "fullrun_dispatched": False,
        }
        write_json(output_dir / "summary.json", payload)
        return payload
    frame = clean_frame(raw, signals, args.oos_start)
    signal_summaries: list[dict[str, Any]] = []
    stat_rows: list[dict[str, Any]] = []
    for signal in signals:
        summary, rows = screen_signal(frame, signal, args.min_rows, args.min_oos_high_count)
        signal_summaries.append(summary)
        stat_rows.extend(rows)
    positives = [item["signal"] for item in signal_summaries if item.get("candidate_positive")]
    decision_label = "diagnostic_positive_requires_broker_ab_review" if positives else "blocked_no_robust_financial_proxy_signal"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "input": str(input_path),
        "row_count": int(len(frame)),
        "ticker_count": int(frame["ticker"].nunique()),
        "signal_columns_checked": signals,
        "positive_signal_count": int(len(positives)),
        "positive_signals": positives,
        "decision_label": decision_label,
        "candidate_allowed": False,
        "next_action_allowed": "broker_ab_design_review_only" if positives else "do_not_design_hook_from_financial_proxy_family",
        "forward_returns_audit_only": True,
        "used_forward_return_in_ranking": False,
        "research_only": True,
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "oos_start": args.oos_start,
        "min_rows": int(args.min_rows),
        "min_oos_high_count": int(args.min_oos_high_count),
        "signal_summaries": signal_summaries,
        "artifacts": {
            "summary": str(output_dir / "summary.json"),
            "signal_stats": str(output_dir / "signal_stats.csv"),
            "report": str(output_dir / "report.md"),
        },
    }
    pd.DataFrame(stat_rows).to_csv(output_dir / "signal_stats.csv", index=False)
    (output_dir / "report.md").write_text(render_report(payload, signal_summaries), encoding="utf-8")
    write_json(output_dir / "summary.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--min-rows", type=int, default=50)
    parser.add_argument("--min-oos-high-count", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
