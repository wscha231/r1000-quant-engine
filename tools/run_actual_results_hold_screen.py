#!/usr/bin/env python3
"""Actual-results-confirmed hold-extension screen.

This diagnostic narrows the rejected broad "hold leaders longer" idea to a
PIT-observable subset: dropped prior holdings that were still leaders and had
positive actual-results evidence at the prior decision date.

Forward 126d excess remains an audit label only. This tool does not mutate
selection, scoring, target books, production gates, or live trading.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_hold_duration_leak_screen import (  # noqa: E402
    drop_rows_for_portfolio,
    load_premature_audit,
    load_target_book,
    repo_path,
    safe_float,
    target_book_path,
    write_csv,
    write_json,
)

SCHEMA_VERSION = "actual-results-hold-screen-v1"
DEFAULT_OUTPUT_DIR = "outputs/actual_results_hold_screen"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_date(value: Any) -> pd.Timestamp | None:
    out = pd.to_datetime(value, errors="coerce")
    if pd.isna(out):
        return None
    return pd.Timestamp(out).normalize()


def predicate_flags(row: dict[str, Any]) -> dict[str, bool]:
    base = bool(row.get("pit_leader_hold_candidate"))
    actual = safe_float(row.get("prior_actual_results_score")) > 0.0
    eps = safe_float(row.get("prior_eps_revision_score")) > 0.0 or safe_float(row.get("prior_revision_score")) > 0.0
    event = safe_float(row.get("prior_event_reaction_score")) > 0.0
    confirmations = int(actual) + int(eps) + int(event)
    return {
        "actual_results_positive_pit_hold": bool(base and actual),
        "actual_and_event_positive_pit_hold": bool(base and actual and event),
        "two_plus_confirmations_pit_hold": bool(base and confirmations >= 2),
        "eps_revision_positive_pit_hold": bool(base and eps),
    }


def split_name(drop_date: Any, oos_start: pd.Timestamp) -> str:
    dt = clean_date(drop_date)
    if dt is None:
        return "unknown"
    return "oos" if dt >= oos_start else "is"


def summarize_predicate(frame: pd.DataFrame, label: str, split: str) -> dict[str, Any]:
    if frame.empty:
        return {
            "label": label,
            "split": split,
            "rows": 0,
            "positive_rows": 0,
            "positive_rate": None,
            "mean_excess_126d": None,
            "median_excess_126d": None,
            "min_excess_126d": None,
            "max_excess_126d": None,
        }
    values = pd.to_numeric(frame["premature_sell_excess_126d"], errors="coerce")
    valid = values.dropna()
    positive = int((valid > 0).sum())
    rows = int(len(valid))
    return {
        "label": label,
        "split": split,
        "rows": rows,
        "positive_rows": positive,
        "positive_rate": float(positive / rows) if rows else None,
        "mean_excess_126d": float(valid.mean()) if rows else None,
        "median_excess_126d": float(valid.median()) if rows else None,
        "min_excess_126d": float(valid.min()) if rows else None,
        "max_excess_126d": float(valid.max()) if rows else None,
    }


def evaluate_primary(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    full = summaries.get("full", {})
    is_ = summaries.get("is", {})
    oos = summaries.get("oos", {})
    gates = {
        "full_rows_ge_30": int(full.get("rows") or 0) >= 30,
        "is_rows_ge_30": int(is_.get("rows") or 0) >= 30,
        "oos_rows_ge_8": int(oos.get("rows") or 0) >= 8,
        "full_mean_positive": safe_float(full.get("mean_excess_126d"), -999.0) > 0.0,
        "is_mean_positive": safe_float(is_.get("mean_excess_126d"), -999.0) > 0.0,
        "oos_mean_positive": safe_float(oos.get("mean_excess_126d"), -999.0) > 0.0,
        "oos_positive_rate_ge_50": safe_float(oos.get("positive_rate"), -999.0) >= 0.50,
    }
    screen_pass = all(gates.values())
    return {
        "gates": gates,
        "screen_pass": bool(screen_pass),
        "next_action": "design_default_off_hook_candidate" if screen_pass else "discard_or_collect_more_evidence",
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Actual-Results Hold Screen",
        "",
        "Research-only screen for a narrow hold-extension candidate.",
        "",
        f"- generated_at_utc: `{payload['generated_at_utc']}`",
        f"- portfolio: `{payload['portfolio']}`",
        f"- target_book: `{payload['target_book']}`",
        f"- production_mutation_allowed: `{str(payload['production_mutation_allowed']).lower()}`",
        f"- live_trading_enabled: `{str(payload['live_trading_enabled']).lower()}`",
        "",
        "## Evidence Availability",
        "",
        f"- actual_results_score column present: `{str(payload['evidence_availability']['actual_results_score_column_present']).lower()}`",
        f"- actual_results_score nonzero rows: `{payload['evidence_availability']['actual_results_score_positive_rows']}`",
        "",
        "## Predicate Results",
        "",
        "| predicate | split | rows | positive rate | mean 126d excess | median 126d excess |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in payload.get("predicate_summaries", []):
        rate = row.get("positive_rate")
        mean = row.get("mean_excess_126d")
        median = row.get("median_excess_126d")
        lines.append(
            "| {label} | {split} | {rows} | {rate} | {mean} | {median} |".format(
                label=row.get("label"),
                split=row.get("split"),
                rows=row.get("rows", 0),
                rate="" if rate is None else f"{float(rate):.2%}",
                mean="" if mean is None else f"{float(mean):.2%}",
                median="" if median is None else f"{float(median):.2%}",
            )
        )
    primary = payload.get("primary_candidate", {})
    lines.extend(
        [
            "",
            "## Primary Candidate",
            "",
            f"- label: `{primary.get('label')}`",
            f"- screen_pass: `{str(primary.get('evaluation', {}).get('screen_pass')).lower()}`",
            f"- next_action: `{primary.get('evaluation', {}).get('next_action')}`",
            "",
            "Forward returns are audit labels only and must not be used in live ranking.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(
    *,
    latest_run: Path,
    output_dir: Path,
    portfolio: str,
    target_book: Path | None,
    oos_start: str,
) -> dict[str, Any]:
    latest_run = repo_path(latest_run)
    output_dir = repo_path(output_dir)
    portfolio = str(portfolio).lower().strip()
    book_path = target_book if target_book is not None else target_book_path(latest_run, portfolio)
    book_path = repo_path(book_path)
    book = load_target_book(book_path)
    audit = load_premature_audit(latest_run)
    rows = drop_rows_for_portfolio(book, audit, portfolio)
    enriched: list[dict[str, Any]] = []
    oos_dt = pd.Timestamp(oos_start).normalize()
    for row in rows:
        out = dict(row)
        out.update(predicate_flags(row))
        out["split"] = split_name(row.get("drop_rebalance_date"), oos_dt)
        enriched.append(out)

    all_rows = pd.DataFrame(enriched)
    if all_rows.empty:
        all_rows = pd.DataFrame(
            columns=[
                "portfolio",
                "ticker",
                "drop_rebalance_date",
                "premature_sell_excess_126d",
                "actual_results_positive_pit_hold",
                "split",
            ]
        )
    write_csv(output_dir / "candidate_rows.csv", all_rows)

    predicate_summaries: list[dict[str, Any]] = []
    summary_by_label: dict[str, dict[str, dict[str, Any]]] = {}
    labels = [
        "actual_results_positive_pit_hold",
        "actual_and_event_positive_pit_hold",
        "two_plus_confirmations_pit_hold",
        "eps_revision_positive_pit_hold",
    ]
    for label in labels:
        label_frame = all_rows[all_rows.get(label, pd.Series(dtype=bool)).astype(bool)].copy()
        summary_by_label[label] = {}
        for split in ["full", "is", "oos"]:
            split_frame = label_frame if split == "full" else label_frame[label_frame["split"].eq(split)]
            item = summarize_predicate(split_frame, label, split)
            predicate_summaries.append(item)
            summary_by_label[label][split] = item

    primary_label = "actual_results_positive_pit_hold"
    evaluation = evaluate_primary(summary_by_label.get(primary_label, {}))
    actual_col_present = "actual_results_score" in set(book.columns)
    actual_positive_rows = int((pd.to_numeric(book.get("actual_results_score", pd.Series(dtype=float)), errors="coerce").fillna(0.0) > 0).sum()) if not book.empty else 0
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "latest_run": str(latest_run),
        "target_book": str(book_path),
        "portfolio": portfolio,
        "is_oos_split": {
            "is_end_exclusive": oos_dt.date().isoformat(),
            "oos_start": oos_dt.date().isoformat(),
        },
        "joined_rows": int(len(all_rows)),
        "drop_rows": str(output_dir / "candidate_rows.csv"),
        "evidence_availability": {
            "actual_results_score_column_present": bool(actual_col_present),
            "actual_results_score_positive_rows": int(actual_positive_rows),
        },
        "predicate_summaries": predicate_summaries,
        "primary_candidate": {
            "label": primary_label,
            "summaries": summary_by_label.get(primary_label, {}),
            "evaluation": evaluation,
        },
        "research_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "target": {
            "cagr": 0.50 if portfolio == "concentrated" else 0.35,
            "max_dd_risk_cap": -0.28,
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio", default="concentrated", choices=["main", "concentrated"])
    parser.add_argument("--target-book", default="")
    parser.add_argument("--oos-start", default="2024-06-03")
    args = parser.parse_args()
    payload = run(
        latest_run=Path(args.latest_run),
        output_dir=Path(args.output_dir),
        portfolio=args.portfolio,
        target_book=Path(args.target_book) if args.target_book else None,
        oos_start=args.oos_start,
    )
    print(json.dumps({"summary": str(repo_path(args.output_dir) / "summary.json"), "primary": payload["primary_candidate"]["evaluation"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
