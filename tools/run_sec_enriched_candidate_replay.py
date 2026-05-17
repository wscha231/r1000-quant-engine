#!/usr/bin/env python3
"""Attach SEC Form 4 shadow evidence to candidate replay books.

This is a research-only sidecar. It does not modify production scores,
`score_total`, target books, or broker replay outputs. The enriched candidate
book can be passed to alpha-selector / broker-ledger challenger tools.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_ownership_signals import SIGNAL_COLUMNS, build_form4_signal  # noqa: E402

DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_FORM4 = "data_pit/sec/form4_transactions.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_enriched_candidate_replay"

SEC_SIGNAL_COLUMNS = [c for c in SIGNAL_COLUMNS if c not in {"ticker", "latest_available_from"}]
ENRICHED_SCORE_COLUMNS = [
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "sec_form4_sale_pressure_score",
    "early_evidence_score",
    "evidence_confidence_score",
    "leader_onset_sec_v2_score",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def rank_by_date(frame: pd.DataFrame, col: str) -> pd.Series:
    if frame.empty or col not in frame.columns:
        return pd.Series(0.5, index=frame.index, dtype=float)
    values = pd.to_numeric(frame[col], errors="coerce")
    return values.groupby(frame["rebalance_date"]).rank(pct=True).fillna(0.5).clip(0.0, 1.0)


def prepare_candidate_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns or "rebalance_date" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d = d[d["ticker"].ne("") & d["rebalance_date"].notna()].copy()
    return d


def as_of_timestamp(rebalance_date: pd.Timestamp) -> str:
    """Use end-of-calendar-day availability for monthly replay rows.

    This is conservative enough for date-level candidate books while still
    requiring `available_from` to be on or before the candidate date.
    """
    ts = pd.Timestamp(rebalance_date).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return ts.tz_localize("UTC").isoformat()


def build_form4_features_by_date(
    form4: pd.DataFrame,
    dates: list[pd.Timestamp],
    *,
    lookback_days: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for dt in sorted({pd.Timestamp(d).normalize() for d in dates}):
        signals = build_form4_signal(form4, as_of=as_of_timestamp(dt), lookback_days=lookback_days)
        if signals.empty:
            continue
        signals = signals.copy()
        signals["rebalance_date"] = dt
        frames.append(signals)
    if not frames:
        return pd.DataFrame(columns=["rebalance_date", *SIGNAL_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def add_leader_onset_sec_v2(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    future = rank_by_date(d, "portfolio_future_winner_engine_score")
    market = numeric(d, "selection_market_confirmation_score", 0.0).clip(0.0, 1.0)
    early = numeric(d, "early_evidence_score", 0.0).clip(0.0, 1.0)
    industry = rank_by_date(d, "industry_group_strength_score")
    rs = rank_by_date(d, "rs_acceleration_score")
    entry = numeric(d, "entry_quality_score", 0.0).clip(0.0, 1.0)
    d["leader_onset_sec_v2_score"] = (
        0.35 * future
        + 0.20 * market
        + 0.15 * early
        + 0.15 * industry
        + 0.10 * rs
        + 0.05 * entry
    ).fillna(0.0).clip(0.0, 1.0)
    return d


def enrich_candidate_book(
    candidates: pd.DataFrame,
    form4: pd.DataFrame,
    *,
    lookback_days: int = 90,
) -> pd.DataFrame:
    d = prepare_candidate_book(candidates)
    if d.empty:
        return pd.DataFrame()

    original_score_total = d["score_total"].copy() if "score_total" in d.columns else None
    dates = [pd.Timestamp(x) for x in d["rebalance_date"].dropna().unique()]
    signals = build_form4_features_by_date(form4, dates, lookback_days=lookback_days)
    if signals.empty:
        for col in SIGNAL_COLUMNS:
            if col not in {"ticker"}:
                d[col] = "" if col == "latest_available_from" else 0.0
    else:
        signals["ticker"] = signals["ticker"].astype(str).str.upper().str.strip()
        signals["rebalance_date"] = pd.to_datetime(signals["rebalance_date"], errors="coerce").dt.normalize()
        keep = ["rebalance_date", "ticker", *[c for c in SIGNAL_COLUMNS if c != "ticker"]]
        d = d.merge(signals[keep], on=["rebalance_date", "ticker"], how="left")
        for col in SEC_SIGNAL_COLUMNS:
            d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
        d["latest_available_from"] = d.get("latest_available_from", "").fillna("").astype(str)

    d = add_leader_onset_sec_v2(d)
    d["sec_evidence_research_only"] = True
    d["sec_evidence_production_activation_allowed"] = False
    d["sec_evidence_source"] = "form4_shadow"
    if original_score_total is not None:
        changed = pd.to_numeric(d["score_total"], errors="coerce").fillna(math.nan).reset_index(drop=True).equals(
            pd.to_numeric(original_score_total, errors="coerce").fillna(math.nan).reset_index(drop=True)
        )
        if not changed:
            raise RuntimeError("SEC enrichment changed score_total; refusing to continue")
    return d


def summary_payload(enriched: pd.DataFrame, candidate_path: Path, form4_path: Path, output_path: Path) -> dict[str, Any]:
    rows = int(len(enriched))
    with_evidence = int((numeric(enriched, "evidence_confidence_score", 0.0) > 0).sum()) if rows else 0
    by_date = (
        enriched.groupby("rebalance_date")["evidence_confidence_score"]
        .apply(lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0.0) > 0).sum()))
        .to_dict()
        if rows and "rebalance_date" in enriched.columns
        else {}
    )
    return {
        "status": "ok",
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "candidate_book": str(candidate_path),
        "form4_transactions": str(form4_path),
        "output_csv": str(output_path),
        "row_count": rows,
        "rows_with_sec_evidence": with_evidence,
        "coverage_ratio": float(with_evidence / rows) if rows else 0.0,
        "rows_with_sec_evidence_by_date": {str(k): v for k, v in by_date.items()},
        "columns_added": ENRICHED_SCORE_COLUMNS,
    }


def render_report(summary: dict[str, Any], enriched: pd.DataFrame) -> str:
    lines = [
        "# SEC Enriched Candidate Replay",
        "",
        "Research-only candidate replay enrichment. Production `score_total` and target books are not changed.",
        "",
        f"- rows: {summary.get('row_count', 0)}",
        f"- rows with SEC evidence: {summary.get('rows_with_sec_evidence', 0)}",
        f"- coverage ratio: {float(summary.get('coverage_ratio', 0.0)):.2%}",
        "",
        "## Top SEC Evidence Rows",
        "",
        "| date | ticker | early evidence | SEC confidence | leader_onset_sec_v2 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    if not enriched.empty:
        top = enriched.sort_values(["early_evidence_score", "leader_onset_sec_v2_score"], ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {date} | {ticker} | {early:.3f} | {conf:.3f} | {leader:.3f} |".format(
                    date=pd.Timestamp(row.get("rebalance_date")).date().isoformat()
                    if pd.notna(row.get("rebalance_date"))
                    else "",
                    ticker=row.get("ticker", ""),
                    early=float(row.get("early_evidence_score", 0.0) or 0.0),
                    conf=float(row.get("evidence_confidence_score", 0.0) or 0.0),
                    leader=float(row.get("leader_onset_sec_v2_score", 0.0) or 0.0),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = repo_path(args.candidate_book)
    form4_path = repo_path(args.form4)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = read_table(candidate_path)
    form4 = read_table(form4_path)
    enriched = enrich_candidate_book(candidates, form4, lookback_days=int(args.lookback_days))
    output_path = output_dir / "candidate_replay_book_sec_enriched.csv"
    enriched_out = enriched.copy()
    if "rebalance_date" in enriched_out.columns:
        enriched_out["rebalance_date"] = pd.to_datetime(enriched_out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    enriched_out.to_csv(output_path, index=False)
    summary = summary_payload(enriched_out, candidate_path, form4_path, output_path)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, enriched), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lookback-days", type=int, default=90)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
