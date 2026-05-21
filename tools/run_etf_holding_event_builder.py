#!/usr/bin/env python3
"""Build PIT ETF holding events for post-disclosure alpha studies.

This C5 tool converts ETF holdings snapshots into event rows that can be
labeled by `run_post_disclosure_alpha_labeler.py`. It is research-only and
does not change ETF refresh, production scores, target books, or broker replay.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_HOLDINGS = "data_pit/etf_holdings/etf_holdings.parquet"
DEFAULT_OUTPUT_DIR = "outputs/etf_holding_events"
DEFAULT_PIT_OUTPUT = "data_pit/etf_holdings/etf_holding_events.parquet"

EVENT_COLUMNS = [
    "event_id",
    "source_type",
    "ticker",
    "holding_ticker",
    "holding_name",
    "etf_ticker",
    "etf_label",
    "theme",
    "available_from",
    "as_of_date",
    "event_type",
    "history_boundary",
    "holding_weight",
    "previous_holding_weight",
    "holding_weight_delta",
    "holding_rank",
    "previous_holding_rank",
    "etf_consensus_count",
    "theme_consensus_count",
    "source",
    "etf_event_seed_score",
    "research_only",
    "production_activation_allowed",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def text(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def num(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def safe_pct(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def normalize_holdings(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty:
        return pd.DataFrame()
    d = holdings.copy()
    d["etf_ticker"] = text(d, "etf_ticker").str.upper().str.strip()
    d["holding_ticker"] = text(d, "holding_ticker").str.upper().str.strip()
    d["ticker"] = d["holding_ticker"]
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True)
    d["holding_weight"] = num(d, "holding_weight").clip(lower=0.0)
    d["etf_label"] = text(d, "etf_label")
    d["holding_name"] = text(d, "holding_name")
    d["theme"] = text(d, "theme", "unknown").replace("", "unknown")
    d["source"] = text(d, "source")
    d["as_of_date"] = text(d, "as_of_date").where(text(d, "as_of_date").str.strip().ne(""), text(d, "available_from"))
    d = d[d["etf_ticker"].ne("") & d["holding_ticker"].ne("") & d["available_from_ts"].notna()].copy()
    if d.empty:
        return pd.DataFrame()
    d = d.sort_values(["etf_ticker", "available_from_ts", "holding_weight"], ascending=[True, True, False])
    d = d.drop_duplicates(["etf_ticker", "holding_ticker", "available_from_ts"], keep="last")
    d["holding_rank"] = d.groupby(["etf_ticker", "available_from_ts"])["holding_weight"].rank(method="first", ascending=False).astype(int)
    return d.reset_index(drop=True)


def event_type_for(current_weight: float, previous_weight: float, *, initial_snapshot: bool, change_threshold: float) -> str:
    if initial_snapshot and current_weight > 0 and previous_weight <= 0:
        return "initial"
    if current_weight > 0 and previous_weight <= 0:
        return "inclusion"
    if current_weight <= 0 and previous_weight > 0:
        return "removal"
    delta = current_weight - previous_weight
    if delta > change_threshold:
        return "weight_increase"
    if delta < -change_threshold:
        return "weight_decrease"
    return "unchanged"


def seed_score(event_type: str, weight: float, delta: float, consensus: int) -> float:
    if event_type == "initial":
        return 0.02
    if event_type == "inclusion":
        return safe_pct(0.30 + 0.35 * safe_pct(weight / 0.05) + 0.20 * safe_pct(consensus / 3.0))
    if event_type == "weight_increase":
        return safe_pct(0.12 + 0.45 * safe_pct(delta / 0.03) + 0.18 * safe_pct(weight / 0.05) + 0.15 * safe_pct(consensus / 3.0))
    if event_type == "weight_decrease":
        return float(max(-1.0, min(0.0, -0.10 - 0.35 * safe_pct(abs(delta) / 0.03))))
    if event_type == "removal":
        return -0.30
    return 0.0


def consensus_maps(current: pd.DataFrame) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    if current.empty:
        return {}, {}
    ticker_counts = current.groupby("holding_ticker")["etf_ticker"].nunique().astype(int).to_dict()
    theme_counts = current.groupby(["holding_ticker", "theme"])["etf_ticker"].nunique().astype(int).to_dict()
    return {str(k): int(v) for k, v in ticker_counts.items()}, {(str(k[0]), str(k[1])): int(v) for k, v in theme_counts.items()}


def build_etf_holding_events(holdings: pd.DataFrame, *, change_threshold: float = 0.0025) -> pd.DataFrame:
    d = normalize_holdings(holdings)
    if d.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    rows: list[dict[str, Any]] = []
    for etf_ticker, etf_frame in d.groupby("etf_ticker", sort=True):
        snapshots = sorted(etf_frame["available_from_ts"].dropna().unique())
        previous = pd.DataFrame()
        for index, available_ts in enumerate(snapshots):
            current = etf_frame[etf_frame["available_from_ts"].eq(available_ts)].copy()
            current_by_ticker = current.set_index("holding_ticker", drop=False)
            previous_by_ticker = previous.set_index("holding_ticker", drop=False) if not previous.empty else pd.DataFrame()
            all_tickers = sorted(set(current_by_ticker.index.astype(str)) | (set(previous_by_ticker.index.astype(str)) if not previous_by_ticker.empty else set()))
            consensus, theme_consensus = consensus_maps(d[d["available_from_ts"].eq(available_ts)])
            for holding_ticker in all_tickers:
                cur = current_by_ticker.loc[holding_ticker] if holding_ticker in current_by_ticker.index else pd.Series(dtype=object)
                prev = previous_by_ticker.loc[holding_ticker] if not previous_by_ticker.empty and holding_ticker in previous_by_ticker.index else pd.Series(dtype=object)
                weight = float(cur.get("holding_weight", 0.0) or 0.0)
                prev_weight = float(prev.get("holding_weight", 0.0) or 0.0)
                delta = weight - prev_weight
                event_type = event_type_for(weight, prev_weight, initial_snapshot=(index == 0), change_threshold=float(change_threshold))
                theme = str(cur.get("theme") or prev.get("theme") or "unknown")
                row = {
                    "event_id": f"etf:{etf_ticker}:{pd.Timestamp(available_ts).date().isoformat()}:{holding_ticker}",
                    "source_type": "etf_holding",
                    "ticker": str(holding_ticker).upper().strip(),
                    "holding_ticker": str(holding_ticker).upper().strip(),
                    "holding_name": str(cur.get("holding_name") or prev.get("holding_name") or ""),
                    "etf_ticker": str(etf_ticker).upper().strip(),
                    "etf_label": str(cur.get("etf_label") or prev.get("etf_label") or etf_ticker),
                    "theme": theme,
                    "available_from": str(cur.get("available_from") or pd.Timestamp(available_ts).isoformat()),
                    "as_of_date": str(cur.get("as_of_date") or pd.Timestamp(available_ts).date().isoformat()),
                    "event_type": event_type,
                    "history_boundary": bool(index == 0),
                    "holding_weight": weight,
                    "previous_holding_weight": prev_weight,
                    "holding_weight_delta": delta,
                    "holding_rank": int(cur.get("holding_rank", 0) or 0),
                    "previous_holding_rank": int(prev.get("holding_rank", 0) or 0),
                    "etf_consensus_count": int(consensus.get(str(holding_ticker).upper().strip(), 0)),
                    "theme_consensus_count": int(theme_consensus.get((str(holding_ticker).upper().strip(), theme), 0)),
                    "source": str(cur.get("source") or prev.get("source") or ""),
                    "research_only": True,
                    "production_activation_allowed": False,
                }
                row["etf_event_seed_score"] = seed_score(event_type, weight, delta, int(row["etf_consensus_count"]))
                rows.append(row)
            previous = current
    events = pd.DataFrame(rows)
    for col in EVENT_COLUMNS:
        if col not in events.columns:
            events[col] = False if col in {"history_boundary", "research_only", "production_activation_allowed"} else ""
    return events[EVENT_COLUMNS].sort_values(["available_from", "etf_ticker", "ticker"]).reset_index(drop=True)


def render_report(summary: dict[str, Any], events: pd.DataFrame) -> str:
    lines = [
        "# ETF Holding Events",
        "",
        "Research-only ETF holdings event table for post-disclosure alpha studies.",
        "",
        f"- event rows: {summary.get('event_rows', 0)}",
        f"- ticker count: {summary.get('ticker_count', 0)}",
        f"- ETF count: {summary.get('etf_count', 0)}",
        "",
        "## Event Counts",
        "",
        "| event_type | rows |",
        "| --- | ---: |",
    ]
    counts = events["event_type"].value_counts().to_dict() if "event_type" in events else {}
    for key, value in sorted(counts.items()):
        lines.append(f"| {key} | {int(value)} |")
    lines.extend(
        [
            "",
            "## Top Positive Events",
            "",
            "| available_from | ETF | ticker | type | weight | delta | seed | theme |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    if not events.empty:
        top = events.sort_values("etf_event_seed_score", ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {available} | {etf} | {ticker} | {event} | {weight:.3f} | {delta:.3f} | {seed:.3f} | {theme} |".format(
                    available=row.get("available_from", ""),
                    etf=row.get("etf_ticker", ""),
                    ticker=row.get("ticker", ""),
                    event=row.get("event_type", ""),
                    weight=float(row.get("holding_weight", 0.0)),
                    delta=float(row.get("holding_weight_delta", 0.0)),
                    seed=float(row.get("etf_event_seed_score", 0.0)),
                    theme=row.get("theme", ""),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    holdings_path = repo_path(args.holdings)
    pit_output = repo_path(args.pit_output)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    holdings = read_table(holdings_path)
    events = build_etf_holding_events(holdings, change_threshold=float(args.change_threshold))
    write_table(events, pit_output)
    write_table(events, output_dir / "etf_holding_events.csv")
    latest = events.copy()
    if not latest.empty and "available_from" in latest.columns:
        latest_ts = pd.to_datetime(latest["available_from"], errors="coerce", utc=True)
        latest = latest[latest_ts.eq(latest_ts.max())].copy() if latest_ts.notna().any() else latest.head(0)
    write_table(latest, output_dir / "latest.csv")
    available = pd.to_datetime(events.get("available_from"), errors="coerce", utc=True) if not events.empty else pd.Series(dtype="datetime64[ns, UTC]")
    summary = {
        "status": "completed" if not events.empty else "blocked",
        "reason": "" if not events.empty else "missing ETF holdings snapshots with holding_ticker and available_from",
        "schema_version": "etf-holding-events-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "holdings": str(holdings_path),
        "pit_output": str(pit_output),
        "event_rows": int(len(events)),
        "latest_rows": int(len(latest)),
        "ticker_count": int(events["ticker"].nunique()) if not events.empty else 0,
        "etf_count": int(events["etf_ticker"].nunique()) if not events.empty else 0,
        "latest_available_from": available.max().isoformat() if not events.empty and available.notna().any() else "",
        "missing_available_from": int(available.isna().sum()) if not events.empty else 0,
        "event_counts": events["event_type"].value_counts().to_dict() if not events.empty else {},
        "outputs": {
            "pit_output": str(pit_output),
            "events_csv": str(output_dir / "etf_holding_events.csv"),
            "latest_csv": str(output_dir / "latest.csv"),
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, events), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "event_rows": summary["event_rows"]}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_HOLDINGS)
    parser.add_argument("--pit-output", default=DEFAULT_PIT_OUTPUT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--change-threshold", type=float, default=0.0025)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
