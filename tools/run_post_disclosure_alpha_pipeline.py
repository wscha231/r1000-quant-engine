#!/usr/bin/env python3
"""Run the research-only post-disclosure alpha pipeline end to end.

The pipeline builds disclosure events, combines them, labels post-disclosure
returns, learns signal/manager alpha summaries, and emits current candidates.
It is a sidecar orchestration tool only; it never changes production scores or
target books.
"""
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

from tools.run_13f_position_event_builder import run as run_13f_events  # noqa: E402
from tools.run_etf_holding_event_builder import run as run_etf_events  # noqa: E402
from tools.run_form4_transaction_event_builder import run as run_form4_events  # noqa: E402
from tools.run_post_disclosure_alpha_candidates import event_universe, run as run_candidates  # noqa: E402
from tools.run_post_disclosure_alpha_labeler import run as run_labeler  # noqa: E402
from tools.run_post_disclosure_overlay_challenger import run as run_overlay  # noqa: E402
from tools.run_post_disclosure_signal_learning import run as run_learning  # noqa: E402

DEFAULT_OUTPUT_DIR = "outputs/post_disclosure_alpha_pipeline"
DEFAULT_COMBINED_EVENTS = "data_pit/sec/post_disclosure_events_all.parquet"
DEFAULT_LABELS = "data_pit/sec/post_disclosure_alpha_labels.parquet"
DEFAULT_MANAGER_SCORES = "data_pit/sec/manager_disclosure_alpha_scores.parquet"
DEFAULT_METADATA = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_CANDIDATE_BOOK = "cloud_results/full_rebuild/latest_global_alpha_universe/reports/candidate_replay_book.csv"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: str | Path) -> pd.DataFrame:
    p = repo_path(path)
    if not p.exists():
        return pd.DataFrame()
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p, low_memory=False)


def write_table(frame: pd.DataFrame, path: str | Path) -> None:
    p = repo_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() == ".parquet":
        frame.to_parquet(p, index=False)
    else:
        frame.to_csv(p, index=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def call_step(name: str, fn: Any, namespace: argparse.Namespace) -> dict[str, Any]:
    try:
        payload = fn(namespace)
        if not isinstance(payload, dict):
            payload = {"status": "unknown", "payload": payload}
    except Exception as exc:  # pragma: no cover - defensive reporting
        payload = {"status": "failed", "error": str(exc)}
    payload = dict(payload)
    payload.setdefault("status", "unknown")
    payload["step"] = name
    return payload


def combine_events(events_13f: str, events_form4: str, events_etf: str, combined_events: str) -> dict[str, Any]:
    events = event_universe(read_table(events_13f), read_table(events_form4), read_table(events_etf))
    write_table(events, combined_events)
    source_counts = events["source_type"].value_counts().to_dict() if not events.empty and "source_type" in events.columns else {}
    return {
        "status": "completed" if not events.empty else "blocked",
        "reason": "" if not events.empty else "missing disclosure event rows",
        "step": "combine_events",
        "combined_events": str(repo_path(combined_events)),
        "event_rows": int(len(events)),
        "ticker_count": int(events["ticker"].nunique()) if not events.empty and "ticker" in events.columns else 0,
        "source_counts": source_counts,
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Post-Disclosure Alpha Pipeline",
        "",
        "Research-only end-to-end pipeline for disclosure event learning and candidate generation.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- combined event rows: {summary.get('combined_event_rows', 0)}",
        f"- label rows: {summary.get('label_rows', 0)}",
        f"- candidate rows: {summary.get('candidate_rows', 0)}",
        "",
        "## Steps",
        "",
        "| step | status | reason |",
        "| --- | --- | --- |",
    ]
    for name, payload in (summary.get("steps") or {}).items():
        lines.append(f"| {name} | {payload.get('status', '')} | {payload.get('reason', payload.get('error', ''))} |")
    lines.extend(["", "Production activation remains disabled; outputs are research-only.", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    steps: dict[str, dict[str, Any]] = {}

    if not bool(args.skip_event_builders):
        steps["13f_events"] = call_step(
            "13f_events",
            run_13f_events,
            argparse.Namespace(
                holdings=args.holdings_13f,
                metadata=args.metadata,
                pit_output=args.events_13f,
                output_dir=str(output_dir / "13f_position_events"),
            ),
        )
        steps["form4_events"] = call_step(
            "form4_events",
            run_form4_events,
            argparse.Namespace(
                form4=args.form4_transactions,
                metadata=args.metadata,
                pit_output=args.events_form4,
                output_dir=str(output_dir / "form4_transaction_events"),
            ),
        )
        steps["etf_events"] = call_step(
            "etf_events",
            run_etf_events,
            argparse.Namespace(
                holdings=args.etf_holdings,
                pit_output=args.events_etf,
                output_dir=str(output_dir / "etf_holding_events"),
                change_threshold=float(args.etf_change_threshold),
            ),
        )

    steps["combine_events"] = combine_events(args.events_13f, args.events_form4, args.events_etf, args.combined_events)
    combined_rows = int(steps["combine_events"].get("event_rows", 0) or 0)

    steps["label_events"] = call_step(
        "label_events",
        run_labeler,
        argparse.Namespace(
            events=args.combined_events,
            price_cache=args.price_cache,
            pit_output=args.labels,
            output_dir=str(output_dir / "post_disclosure_alpha"),
            benchmark_ticker=args.benchmark_ticker,
            horizons=args.horizons,
        ),
    )
    steps["signal_learning"] = call_step(
        "signal_learning",
        run_learning,
        argparse.Namespace(
            labels=args.labels,
            output_dir=str(output_dir / "post_disclosure_signal_learning"),
            manager_output=args.manager_scores,
            horizons=args.learning_horizons,
        ),
    )
    steps["candidates"] = call_step(
        "candidates",
        run_candidates,
        argparse.Namespace(
            events_13f=args.events_13f,
            events_form4=args.events_form4,
            events_etf=args.events_etf,
            manager_scores=args.manager_scores,
            metadata=args.metadata,
            output_dir=str(output_dir / "post_disclosure_alpha_candidates"),
            as_of_date=args.as_of_date,
            lookback_days=int(args.lookback_days),
            top_n=int(args.top_n),
            tradable_only=bool(args.tradable_only),
            min_market_cap_usd=float(args.min_market_cap_usd),
            min_dollar_volume_usd=float(args.min_dollar_volume_usd),
            min_price=float(args.min_price),
        ),
    )
    if bool(args.run_overlay_challenger):
        steps["overlay_challenger"] = call_step(
            "overlay_challenger",
            run_overlay,
            argparse.Namespace(
                candidate_book=args.candidate_book,
                events_13f=args.events_13f,
                events_form4=args.events_form4,
                events_etf=args.events_etf,
                output_dir=str(output_dir / "post_disclosure_overlay_challenger"),
                lookback_days=int(args.lookback_days),
                run_broker_grid=bool(args.run_broker_grid),
                price_cache=args.price_cache,
                portfolio_kinds=args.portfolio_kinds,
                starting_capital=float(args.starting_capital),
                fill_mode=args.fill_mode,
                cost_bps=float(args.cost_bps),
                max_fill_lag_days=int(args.max_fill_lag_days),
                styles=args.styles,
                target_ns=args.target_ns,
                single_name_caps=args.single_name_caps,
                main_target_ns=args.main_target_ns,
                concentrated_target_ns=args.concentrated_target_ns,
                main_single_name_caps=args.main_single_name_caps,
                concentrated_single_name_caps=args.concentrated_single_name_caps,
                max_variants=int(args.max_variants),
                min_market_cap_usd=float(args.min_market_cap_usd),
                min_dollar_volume_usd=float(args.min_dollar_volume_usd),
                min_price=float(args.min_price),
                allow_unfillable_targets=bool(args.allow_unfillable_targets),
            ),
        )

    label_rows = int(steps["label_events"].get("label_rows", 0) or 0)
    candidate_rows = int(steps["candidates"].get("candidate_rows", 0) or 0)
    completed_core = combined_rows > 0 and label_rows > 0 and steps["signal_learning"].get("status") == "completed"
    summary = {
        "status": "completed" if completed_core else "blocked",
        "reason": "" if completed_core else "one or more core post-disclosure steps are blocked",
        "schema_version": "post-disclosure-alpha-pipeline-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "combined_event_rows": combined_rows,
        "label_rows": label_rows,
        "candidate_rows": candidate_rows,
        "steps": steps,
        "outputs": {
            "combined_events": str(repo_path(args.combined_events)),
            "labels": str(repo_path(args.labels)),
            "manager_scores": str(repo_path(args.manager_scores)),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "combined_event_rows": combined_rows, "label_rows": label_rows, "candidate_rows": candidate_rows}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-event-builders", action="store_true")
    parser.add_argument("--holdings-13f", default="data_pit/sec/institutional_13f_holdings.parquet")
    parser.add_argument("--form4-transactions", default="data_pit/sec/form4_transactions.parquet")
    parser.add_argument("--etf-holdings", default="data_pit/etf_holdings/etf_holdings.parquet")
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--events-13f", default="data_pit/sec/13f_position_events.parquet")
    parser.add_argument("--events-form4", default="data_pit/sec/form4_transaction_events.parquet")
    parser.add_argument("--events-etf", default="data_pit/etf_holdings/etf_holding_events.parquet")
    parser.add_argument("--combined-events", default=DEFAULT_COMBINED_EVENTS)
    parser.add_argument("--labels", default=DEFAULT_LABELS)
    parser.add_argument("--manager-scores", default=DEFAULT_MANAGER_SCORES)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--horizons", default="1,5,21,42,63,126")
    parser.add_argument("--learning-horizons", default="21,63,126")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--tradable-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--etf-change-threshold", type=float, default=0.0025)
    parser.add_argument("--run-overlay-challenger", action="store_true")
    parser.add_argument("--run-broker-grid", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--portfolio-kinds", default="main,concentrated")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--styles", default="post_disclosure_light,post_disclosure_balanced")
    parser.add_argument("--target-ns", default="")
    parser.add_argument("--single-name-caps", default="")
    parser.add_argument("--main-target-ns", default="12,15,18")
    parser.add_argument("--concentrated-target-ns", default="3,5")
    parser.add_argument("--main-single-name-caps", default="0.08,0.12,0.18")
    parser.add_argument("--concentrated-single-name-caps", default="0.33,0.50")
    parser.add_argument("--max-variants", type=int, default=24)
    parser.add_argument("--min-market-cap-usd", type=float, default=300_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=5_000_000.0)
    parser.add_argument("--min-price", type=float, default=2.0)
    parser.add_argument("--allow-unfillable-targets", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
