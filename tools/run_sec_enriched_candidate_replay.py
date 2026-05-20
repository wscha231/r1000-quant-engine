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
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_institutional_signals import (  # noqa: E402
    INSTITUTIONAL_SIGNAL_COLUMNS,
    build_13f_signal,
)
from tools.run_sec_ownership_signals import SIGNAL_COLUMNS, build_form4_signal  # noqa: E402

DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_FORM4 = "data_pit/sec/form4_transactions.parquet"
DEFAULT_13F = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_enriched_candidate_replay"

SEC_SIGNAL_COLUMNS = [c for c in SIGNAL_COLUMNS if c not in {"ticker", "latest_available_from"}]
INSTITUTIONAL_FEATURE_COLUMNS = [c for c in INSTITUTIONAL_SIGNAL_COLUMNS if c not in {"ticker", "latest_available_from"}]
ENRICHED_SCORE_COLUMNS = [
    "sec_form4_open_market_buy_score",
    "sec_form4_cluster_buy_score",
    "sec_form4_ceo_cfo_buy_score",
    "sec_form4_sale_pressure_score",
    "sec_13f_manager_count",
    "sec_13f_buying_manager_count",
    "sec_13f_new_position_manager_count",
    "sec_13f_value_delta_usd",
    "sec_13f_value_delta_to_mcap",
    "sec_13f_consensus_buy_score",
    "sec_13f_accumulation_score",
    "sec_13f_smart_money_score",
    "institutional_evidence_score",
    "early_evidence_score",
    "evidence_confidence_score",
    "sec_combined_evidence_score",
    "leader_onset_sec_v2_score",
    "leader_onset_sec_v3_score",
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


def issuer_name_key(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9 ]+", " ", str(value or "").upper().replace("&", " AND "))
    aliases = {
        "FINL": "FINANCIAL",
        "TECH": "TECHNOLOGY",
        "COMMUNICATIONS": "COMMUNICATION",
    }
    stop = {
        "THE",
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LTD",
        "LIMITED",
        "PLC",
        "SA",
        "NV",
        "COM",
        "COMMON",
        "STOCK",
        "CLASS",
        "CL",
        "NEW",
        "ORD",
        "SHS",
    }
    tokens = [aliases.get(tok, tok) for tok in text.split() if tok and tok not in stop]
    return " ".join(tokens)


def candidate_issuer_map(candidates: pd.DataFrame) -> dict[str, str]:
    if candidates.empty or "ticker" not in candidates.columns:
        return {}
    name_col = "Name" if "Name" in candidates.columns else "name" if "name" in candidates.columns else ""
    if not name_col:
        return {}
    pairs = candidates[["ticker", name_col]].dropna().copy()
    pairs["ticker"] = pairs["ticker"].astype(str).str.upper().str.strip()
    pairs["issuer_key"] = pairs[name_col].map(issuer_name_key)
    pairs = pairs[pairs["ticker"].ne("") & pairs["issuer_key"].ne("")]
    counts = pairs.groupby("issuer_key")["ticker"].nunique()
    unique_keys = set(counts[counts.eq(1)].index)
    return pairs[pairs["issuer_key"].isin(unique_keys)].drop_duplicates("issuer_key").set_index("issuer_key")["ticker"].to_dict()


def map_13f_tickers_from_candidates(holdings_13f: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    if holdings_13f.empty or "issuer_name" not in holdings_13f.columns:
        return holdings_13f
    mapping = candidate_issuer_map(candidates)
    if not mapping:
        return holdings_13f
    d = holdings_13f.copy()
    if "ticker_mapped" not in d.columns:
        d["ticker_mapped"] = ""
    blank = d["ticker_mapped"].astype(str).str.strip().eq("")
    d.loc[blank, "ticker_mapped"] = d.loc[blank, "issuer_name"].map(lambda value: mapping.get(issuer_name_key(value), ""))
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


def build_13f_features_by_date(
    holdings_13f: pd.DataFrame,
    dates: list[pd.Timestamp],
    *,
    lookback_days: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for dt in sorted({pd.Timestamp(d).normalize() for d in dates}):
        signals = build_13f_signal(holdings_13f, as_of=as_of_timestamp(dt), lookback_days=lookback_days)
        if signals.empty:
            continue
        signals = signals.copy()
        signals["rebalance_date"] = dt
        frames.append(signals)
    if not frames:
        return pd.DataFrame(columns=["rebalance_date", *INSTITUTIONAL_SIGNAL_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def market_cap_series(frame: pd.DataFrame) -> pd.Series:
    candidates: list[pd.Series] = []
    for col in ["market_cap_live", "mktcap", "market_cap", "current_market_cap"]:
        if col in frame.columns:
            candidates.append(pd.to_numeric(frame[col], errors="coerce"))
    if not candidates:
        return pd.Series(0.0, index=frame.index, dtype=float)
    return pd.concat(candidates, axis=1).max(axis=1).fillna(0.0).clip(lower=0.0)


def add_combined_sec_scores(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    form4 = numeric(d, "early_evidence_score", 0.0).clip(0.0, 1.0)
    inst = numeric(d, "institutional_evidence_score", 0.0).clip(0.0, 1.0)
    confidence = numeric(d, "evidence_confidence_score", 0.0).clip(0.0, 1.0)
    inst_conf = numeric(d, "institutional_evidence_confidence_score", 0.0).clip(0.0, 1.0)
    mcap = market_cap_series(d)
    delta = numeric(d, "sec_13f_value_delta_usd", 0.0).clip(lower=0.0)
    ratio = pd.Series(0.0, index=d.index, dtype=float)
    valid_mcap = mcap > 0.0
    ratio.loc[valid_mcap] = (delta.loc[valid_mcap] / mcap.loc[valid_mcap]).clip(0.0, 1.0)
    d["sec_13f_value_delta_to_mcap"] = ratio
    ratio_score = (ratio / 0.01).clip(0.0, 1.0)
    d["sec_combined_evidence_score"] = (
        0.45 * form4
        + 0.35 * inst
        + 0.10 * ratio_score
        + 0.10 * (0.5 * confidence + 0.5 * inst_conf)
    ).fillna(0.0).clip(0.0, 1.0)
    return d


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
    combined = numeric(d, "sec_combined_evidence_score", 0.0).clip(0.0, 1.0)
    institutional = numeric(d, "institutional_evidence_score", 0.0).clip(0.0, 1.0)
    d["leader_onset_sec_v3_score"] = (
        0.30 * future
        + 0.18 * market
        + 0.17 * combined
        + 0.10 * institutional
        + 0.12 * industry
        + 0.08 * rs
        + 0.05 * entry
    ).fillna(0.0).clip(0.0, 1.0)
    return d


def enrich_candidate_book(
    candidates: pd.DataFrame,
    form4: pd.DataFrame,
    holdings_13f: pd.DataFrame | None = None,
    *,
    lookback_days: int = 90,
    institutional_lookback_days: int = 210,
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

    holdings_13f = holdings_13f if holdings_13f is not None else pd.DataFrame()
    holdings_13f = map_13f_tickers_from_candidates(holdings_13f, d)
    inst_signals = build_13f_features_by_date(holdings_13f, dates, lookback_days=institutional_lookback_days)
    if inst_signals.empty:
        for col in INSTITUTIONAL_FEATURE_COLUMNS:
            d[col] = 0.0
        d["latest_13f_available_from"] = ""
    else:
        inst_signals["ticker"] = inst_signals["ticker"].astype(str).str.upper().str.strip()
        inst_signals["rebalance_date"] = pd.to_datetime(inst_signals["rebalance_date"], errors="coerce").dt.normalize()
        inst = inst_signals.rename(columns={"latest_available_from": "latest_13f_available_from"})
        keep = ["rebalance_date", "ticker", *[c for c in inst.columns if c in INSTITUTIONAL_FEATURE_COLUMNS], "latest_13f_available_from"]
        d = d.merge(inst[keep], on=["rebalance_date", "ticker"], how="left")
        for col in INSTITUTIONAL_FEATURE_COLUMNS:
            d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
        d["latest_13f_available_from"] = d.get("latest_13f_available_from", "").fillna("").astype(str)

    d = add_combined_sec_scores(d)
    d = add_leader_onset_sec_v2(d)
    d["sec_evidence_research_only"] = True
    d["sec_evidence_production_activation_allowed"] = False
    d["sec_evidence_source"] = "form4_13f_shadow"
    if original_score_total is not None:
        changed = pd.to_numeric(d["score_total"], errors="coerce").fillna(math.nan).reset_index(drop=True).equals(
            pd.to_numeric(original_score_total, errors="coerce").fillna(math.nan).reset_index(drop=True)
        )
        if not changed:
            raise RuntimeError("SEC enrichment changed score_total; refusing to continue")
    return d


def summary_payload(
    enriched: pd.DataFrame,
    candidate_path: Path,
    form4_path: Path,
    institutional_13f_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    rows = int(len(enriched))
    with_evidence = int((numeric(enriched, "evidence_confidence_score", 0.0) > 0).sum()) if rows else 0
    with_13f = int((numeric(enriched, "institutional_evidence_confidence_score", 0.0) > 0).sum()) if rows else 0
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
        "institutional_13f_holdings": str(institutional_13f_path),
        "output_csv": str(output_path),
        "row_count": rows,
        "rows_with_sec_evidence": with_evidence,
        "rows_with_13f_evidence": with_13f,
        "coverage_ratio": float(with_evidence / rows) if rows else 0.0,
        "coverage_13f_ratio": float(with_13f / rows) if rows else 0.0,
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
        f"- rows with 13F evidence: {summary.get('rows_with_13f_evidence', 0)}",
        f"- coverage ratio: {float(summary.get('coverage_ratio', 0.0)):.2%}",
        f"- 13F coverage ratio: {float(summary.get('coverage_13f_ratio', 0.0)):.2%}",
        "",
        "## Top SEC Evidence Rows",
        "",
        "| date | ticker | form4 evidence | 13F evidence | combined | leader_onset_sec_v3 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    if not enriched.empty:
        top = enriched.sort_values(["sec_combined_evidence_score", "leader_onset_sec_v3_score"], ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {date} | {ticker} | {form4:.3f} | {inst:.3f} | {combined:.3f} | {leader:.3f} |".format(
                    date=pd.Timestamp(row.get("rebalance_date")).date().isoformat()
                    if pd.notna(row.get("rebalance_date"))
                    else "",
                    ticker=row.get("ticker", ""),
                    form4=float(row.get("early_evidence_score", 0.0) or 0.0),
                    inst=float(row.get("institutional_evidence_score", 0.0) or 0.0),
                    combined=float(row.get("sec_combined_evidence_score", 0.0) or 0.0),
                    leader=float(row.get("leader_onset_sec_v3_score", 0.0) or 0.0),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = repo_path(args.candidate_book)
    form4_path = repo_path(args.form4)
    institutional_13f_path = repo_path(args.institutional_13f)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = read_table(candidate_path)
    form4 = read_table(form4_path)
    holdings_13f = read_table(institutional_13f_path)
    enriched = enrich_candidate_book(
        candidates,
        form4,
        holdings_13f,
        lookback_days=int(args.lookback_days),
        institutional_lookback_days=int(args.institutional_lookback_days),
    )
    output_path = output_dir / "candidate_replay_book_sec_enriched.csv"
    enriched_out = enriched.copy()
    if "rebalance_date" in enriched_out.columns:
        enriched_out["rebalance_date"] = pd.to_datetime(enriched_out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    enriched_out.to_csv(output_path, index=False)
    summary = summary_payload(enriched_out, candidate_path, form4_path, institutional_13f_path, output_path)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, enriched), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--institutional-13f", default=DEFAULT_13F)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--institutional-lookback-days", type=int, default=210)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
