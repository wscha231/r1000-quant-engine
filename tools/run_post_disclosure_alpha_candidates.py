#!/usr/bin/env python3
"""Build research-only post-disclosure alpha candidates from SEC/ETF events.

This C6 sidecar turns current PIT 13F, Form 4, and ETF holding events plus
historical manager disclosure-alpha scores into a standalone watchlist. It does
not change production scores, target books, or broker-ledger defaults.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_13F_EVENTS = "data_pit/sec/13f_position_events.parquet"
DEFAULT_FORM4_EVENTS = "data_pit/sec/form4_transaction_events.parquet"
DEFAULT_ETF_EVENTS = "data_pit/etf_holdings/etf_holding_events.parquet"
DEFAULT_MANAGER_SCORES = "data_pit/sec/manager_disclosure_alpha_scores.parquet"
DEFAULT_METADATA = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"
DEFAULT_OUTPUT_DIR = "outputs/post_disclosure_alpha_candidates"

OUTPUT_COLUMNS = [
    "rank",
    "ticker",
    "post_disclosure_candidate_score",
    "event_strength_score",
    "manager_alpha_component",
    "source_convergence_score",
    "recency_score",
    "event_count_score",
    "negative_event_penalty",
    "evidence_confidence",
    "source_count",
    "event_count",
    "latest_available_from",
    "source_types",
    "event_types",
    "manager_names",
    "manager_ciks",
    "top_event_ids",
    "metadata_available",
    "tradable_candidate",
    "tradability_score",
    "engine_confirmation_score",
    "market_cap_usd",
    "dollar_volume_20d",
    "price",
    "universe_source",
    "ranking_eligible",
    "candidate_explanation",
    "research_only",
    "production_activation_allowed",
]


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def text_column(frame: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str)


def safe_pct(value: float) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return float(max(0.0, min(1.0, value)))


def first_existing(frame: pd.DataFrame, columns: list[str], default: str = "") -> pd.Series:
    out = pd.Series(default, index=frame.index, dtype=object)
    for col in columns:
        if col in frame.columns:
            values = frame[col].fillna("").astype(str)
            out = out.mask(out.astype(str).str.strip().eq(""), values)
    return out


def first_numeric(frame: pd.DataFrame, columns: list[str], default: float = 0.0) -> pd.Series:
    out = pd.Series(default, index=frame.index, dtype=float)
    used = pd.Series(False, index=frame.index)
    for col in columns:
        if col in frame.columns:
            values = pd.to_numeric(frame[col], errors="coerce")
            mask = ~used & values.notna()
            out.loc[mask] = values.loc[mask].astype(float)
            used.loc[mask] = True
    return out.fillna(default)


def first_boolish(frame: pd.DataFrame, columns: list[str], default: bool = True) -> pd.Series:
    out = pd.Series(default, index=frame.index, dtype=bool)
    used = pd.Series(False, index=frame.index)
    for col in columns:
        if col not in frame.columns:
            continue
        values = frame[col]
        parsed = values.map(
            lambda value: str(value).strip().lower()
            not in {"", "0", "0.0", "false", "nan", "none", "no"}
        )
        mask = ~used & values.notna()
        out.loc[mask] = parsed.loc[mask].astype(bool)
        used.loc[mask] = True
    return out.fillna(default).astype(bool)


def log_gate_score(value: float, floor: float, *, span: float = 2.0) -> float:
    try:
        value_f = float(value)
        floor_f = float(floor)
    except Exception:
        return 0.0
    if not math.isfinite(value_f) or not math.isfinite(floor_f) or floor_f <= 0:
        return 0.0
    if value_f <= 0:
        return 0.0
    return safe_pct(math.log10(max(value_f / floor_f, 1e-9)) / max(float(span), 1e-9))


def normalize_events(frame: pd.DataFrame, *, source_type: str, ticker_cols: list[str], score_cols: list[str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = first_existing(d, ticker_cols).str.upper().str.strip()
    if "available_from" not in d.columns and "accepted_at" in d.columns:
        d["available_from"] = d["accepted_at"]
    d["available_from_ts"] = pd.to_datetime(d.get("available_from"), errors="coerce", utc=True).dt.tz_convert(None)
    d["source_type"] = source_type
    d["event_id"] = first_existing(d, ["event_id", "accession_number"], default="")
    d["event_type"] = first_existing(d, ["event_type", "transaction_code"], default="")
    d["manager_cik"] = first_existing(d, ["manager_cik", "reporting_owner_cik", "owner_cik"], default="")
    d["manager_name"] = first_existing(d, ["manager_name", "reporting_owner_name", "owner_name", "etf_ticker"], default="")
    d["event_seed_score"] = first_numeric(d, score_cols, default=0.0).clip(-1.0, 1.0)
    d = d[d["ticker"].ne("") & d["ticker"].ne("NAN") & d["available_from_ts"].notna()].copy()
    return d[
        [
            "event_id",
            "source_type",
            "manager_cik",
            "manager_name",
            "ticker",
            "event_type",
            "event_seed_score",
            "available_from",
            "available_from_ts",
        ]
    ]


def normalize_manager_scores(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "manager_cik" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["manager_cik"] = text_column(d, "manager_cik").str.strip()
    d["manager_name"] = text_column(d, "manager_name")
    d["as_of_ts"] = pd.to_datetime(d.get("as_of_date"), errors="coerce")
    d["manager_disclosure_alpha_score"] = numeric(d, "manager_disclosure_alpha_score", 0.0).clip(0.0, 1.0)
    d["manager_confidence"] = numeric(d, "manager_confidence", 0.0).clip(0.0, 1.0)
    d = d[d["manager_cik"].ne("") & d["as_of_ts"].notna()].copy()
    return d.sort_values(["manager_cik", "as_of_ts"])


def attach_manager_alpha(events: pd.DataFrame, manager_scores: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return events
    d = events.copy()
    d["manager_disclosure_alpha_score"] = 0.0
    d["manager_confidence"] = 0.0
    if manager_scores.empty or "manager_cik" not in d.columns:
        return d
    score_groups = {str(k): g.sort_values("as_of_ts") for k, g in manager_scores.groupby("manager_cik")}
    scores: list[float] = []
    confidences: list[float] = []
    for _, row in d.iterrows():
        manager_cik = str(row.get("manager_cik", "")).strip()
        available = pd.Timestamp(row.get("available_from_ts"))
        group = score_groups.get(manager_cik)
        if group is None or group.empty or pd.isna(available):
            scores.append(0.0)
            confidences.append(0.0)
            continue
        eligible = group[group["as_of_ts"] <= available]
        if eligible.empty:
            scores.append(0.0)
            confidences.append(0.0)
            continue
        latest = eligible.iloc[-1]
        scores.append(float(latest.get("manager_disclosure_alpha_score", 0.0) or 0.0))
        confidences.append(float(latest.get("manager_confidence", 0.0) or 0.0))
    d["manager_disclosure_alpha_score"] = pd.Series(scores, index=d.index).clip(0.0, 1.0)
    d["manager_confidence"] = pd.Series(confidences, index=d.index).clip(0.0, 1.0)
    return d


def normalize_candidate_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = text_column(d, "ticker").str.upper().str.strip()
    d = d[d["ticker"].ne("") & d["ticker"].ne("NAN")].copy()
    if d.empty:
        return pd.DataFrame()
    d["market_cap_usd"] = first_numeric(d, ["market_cap_live", "mktcap", "mktcap_proxy"], 0.0)
    d["dollar_volume_20d"] = first_numeric(
        d,
        ["dollar_vol_20d", "dollar_volume_20d", "avg_dollar_vol_20d", "avg_dollar_volume_20d"],
        0.0,
    )
    d["price"] = first_numeric(d, ["current_price_live", "px", "close", "price"], 0.0)
    d["universe_source"] = first_existing(d, ["universe_source"], "")
    d["ranking_eligible"] = first_boolish(d, ["ranking_eligible"], True)
    d["future_winner_engine_score"] = first_numeric(d, ["portfolio_future_winner_engine_score"], 0.0).clip(0.0, 1.0)
    d["market_confirmation_score"] = first_numeric(
        d,
        ["selection_market_confirmation_score", "relative_strength_composite", "rs_market_composite"],
        0.0,
    ).clip(0.0, 1.0)
    d["engine_confirmation_score"] = (
        0.45 * d["future_winner_engine_score"]
        + 0.35 * d["market_confirmation_score"]
        + 0.20 * d["ranking_eligible"].astype(float)
    ).clip(0.0, 1.0)
    sort_cols = [c for c in ["score_total", "score", "market_cap_usd"] if c in d.columns]
    if sort_cols:
        for col in sort_cols:
            d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
        d = d.sort_values(sort_cols, ascending=False)
    keep = [
        "ticker",
        "market_cap_usd",
        "dollar_volume_20d",
        "price",
        "universe_source",
        "ranking_eligible",
        "future_winner_engine_score",
        "market_confirmation_score",
        "engine_confirmation_score",
    ]
    return d[keep].drop_duplicates("ticker", keep="first")


def attach_candidate_metadata(
    candidates: pd.DataFrame,
    metadata: pd.DataFrame,
    *,
    min_market_cap_usd: float,
    min_dollar_volume_usd: float,
    min_price: float,
) -> pd.DataFrame:
    d = candidates.copy()
    if metadata.empty:
        d["metadata_available"] = False
        d["market_cap_usd"] = 0.0
        d["dollar_volume_20d"] = 0.0
        d["price"] = 0.0
        d["universe_source"] = ""
        d["ranking_eligible"] = True
        d["engine_confirmation_score"] = 0.0
    else:
        d = d.merge(metadata, on="ticker", how="left")
        d["metadata_available"] = d["market_cap_usd"].notna()
        d["market_cap_usd"] = pd.to_numeric(d["market_cap_usd"], errors="coerce").fillna(0.0)
        d["dollar_volume_20d"] = pd.to_numeric(d["dollar_volume_20d"], errors="coerce").fillna(0.0)
        d["price"] = pd.to_numeric(d["price"], errors="coerce").fillna(0.0)
        d["universe_source"] = d["universe_source"].fillna("").astype(str)
        d["ranking_eligible"] = d["ranking_eligible"].map(
            lambda value: True
            if pd.isna(value)
            else str(value).strip().lower() not in {"", "0", "0.0", "false", "nan", "none", "no"}
        ).astype(bool)
        d["engine_confirmation_score"] = pd.to_numeric(
            d["engine_confirmation_score"], errors="coerce"
        ).fillna(0.0).clip(0.0, 1.0)
    d["tradability_score"] = [
        safe_pct(
            0.40 * log_gate_score(mcap, min_market_cap_usd, span=2.0)
            + 0.40 * log_gate_score(dvol, min_dollar_volume_usd, span=1.5)
            + 0.20 * safe_pct(price / max(float(min_price), 1e-9))
        )
        for mcap, dvol, price in zip(d["market_cap_usd"], d["dollar_volume_20d"], d["price"])
    ]
    d["tradable_candidate"] = (
        d["metadata_available"].astype(bool)
        & d["ranking_eligible"].astype(bool)
        & (d["market_cap_usd"] >= float(min_market_cap_usd))
        & (d["dollar_volume_20d"] >= float(min_dollar_volume_usd))
        & (d["price"] >= float(min_price))
    )
    d["post_disclosure_candidate_score"] = (
        0.85 * pd.to_numeric(d["post_disclosure_candidate_score"], errors="coerce").fillna(0.0)
        + 0.10 * d["engine_confirmation_score"]
        + 0.05 * pd.to_numeric(d["tradability_score"], errors="coerce").fillna(0.0)
    ).clip(0.0, 1.0)
    return d


def event_universe(events_13f: pd.DataFrame, events_form4: pd.DataFrame, events_etf: pd.DataFrame) -> pd.DataFrame:
    parts = [
        normalize_events(
            events_13f,
            source_type="13f",
            ticker_cols=["ticker"],
            score_cols=["post_disclosure_event_seed_score", "event_seed_score"],
        ),
        normalize_events(
            events_form4,
            source_type="form4",
            ticker_cols=["ticker", "issuer_ticker"],
            score_cols=["post_disclosure_event_seed_score", "event_seed_score"],
        ),
        normalize_events(
            events_etf,
            source_type="etf",
            ticker_cols=["ticker", "holding_ticker"],
            score_cols=["etf_event_seed_score", "post_disclosure_event_seed_score", "event_seed_score"],
        ),
    ]
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).sort_values(["available_from_ts", "source_type", "ticker"])


def filter_asof(events: pd.DataFrame, *, as_of_date: str, lookback_days: int) -> tuple[pd.DataFrame, pd.Timestamp | None]:
    if events.empty:
        return events, None
    as_of_ts = pd.to_datetime(as_of_date, errors="coerce") if str(as_of_date or "").strip() else events["available_from_ts"].max()
    if pd.isna(as_of_ts):
        return pd.DataFrame(), None
    as_of_ts = pd.Timestamp(as_of_ts).tz_localize(None) if pd.Timestamp(as_of_ts).tzinfo else pd.Timestamp(as_of_ts)
    start = as_of_ts - pd.Timedelta(days=int(lookback_days))
    d = events[(events["available_from_ts"] <= as_of_ts) & (events["available_from_ts"] >= start)].copy()
    return d, as_of_ts


def summarize_sources(values: pd.Series) -> str:
    items = sorted({str(x) for x in values.dropna().astype(str) if str(x).strip()})
    return ",".join(items)


def top_join(values: pd.Series, limit: int = 5) -> str:
    items: list[str] = []
    for value in values.dropna().astype(str):
        text = value.strip()
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return ",".join(items)


def explanation(row: pd.Series) -> str:
    parts: list[str] = []
    if int(row.get("source_count", 0)) > 0:
        parts.append(f"{int(row.get('source_count', 0))} evidence sources")
    if int(row.get("event_count", 0)) > 0:
        parts.append(f"{int(row.get('event_count', 0))} recent events")
    managers = str(row.get("manager_names", "") or "")
    if managers:
        parts.append(f"managers/owners: {managers}")
    event_types = str(row.get("event_types", "") or "")
    if event_types:
        parts.append(f"events: {event_types}")
    return "; ".join(parts)


def build_candidates(
    events: pd.DataFrame,
    manager_scores: pd.DataFrame,
    *,
    metadata: pd.DataFrame | None = None,
    as_of_date: str = "",
    lookback_days: int = 180,
    top_n: int = 30,
    tradable_only: bool = False,
    min_market_cap_usd: float = 300_000_000.0,
    min_dollar_volume_usd: float = 5_000_000.0,
    min_price: float = 2.0,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    scoped, as_of_ts = filter_asof(events, as_of_date=as_of_date, lookback_days=lookback_days)
    if scoped.empty or as_of_ts is None:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), {
            "status": "blocked",
            "reason": "missing recent post-disclosure events",
            "as_of_date": str(as_of_date or ""),
            "lookback_days": int(lookback_days),
        }
    scoped = attach_manager_alpha(scoped, manager_scores)
    scoped["positive_event_score"] = numeric(scoped, "event_seed_score", 0.0).clip(lower=0.0, upper=1.0)
    scoped["negative_event_score"] = (-numeric(scoped, "event_seed_score", 0.0).clip(upper=0.0)).clip(0.0, 1.0)
    scoped["age_days"] = (as_of_ts - scoped["available_from_ts"]).dt.total_seconds() / 86400.0
    scoped["recency_score"] = (1.0 - (scoped["age_days"] / max(float(lookback_days), 1.0))).clip(0.0, 1.0)

    rows: list[dict[str, Any]] = []
    for ticker, group in scoped.groupby("ticker", sort=True):
        source_count = int(group["source_type"].nunique())
        event_count = int(len(group))
        event_strength = safe_pct(float(group["positive_event_score"].sum()))
        negative = safe_pct(float(group["negative_event_score"].sum()))
        manager_component = safe_pct(float((group["manager_disclosure_alpha_score"] * group["manager_confidence"]).max()))
        convergence = safe_pct(source_count / 3.0)
        recency = safe_pct(float(group["recency_score"].max()))
        event_count_score = safe_pct(event_count / 5.0)
        confidence = safe_pct(0.34 * convergence + 0.33 * event_count_score + 0.33 * recency)
        score = safe_pct(
            0.30 * event_strength
            + 0.25 * manager_component
            + 0.15 * convergence
            + 0.10 * recency
            + 0.10 * event_count_score
            + 0.10 * confidence
            - 0.25 * negative
        )
        latest_available = group["available_from_ts"].max().isoformat()
        rows.append(
            {
                "ticker": ticker,
                "post_disclosure_candidate_score": score,
                "event_strength_score": event_strength,
                "manager_alpha_component": manager_component,
                "source_convergence_score": convergence,
                "recency_score": recency,
                "event_count_score": event_count_score,
                "negative_event_penalty": negative,
                "evidence_confidence": confidence,
                "source_count": source_count,
                "event_count": event_count,
                "latest_available_from": latest_available,
                "source_types": summarize_sources(group["source_type"]),
                "event_types": summarize_sources(group["event_type"]),
                "manager_names": top_join(group["manager_name"]),
                "manager_ciks": top_join(group["manager_cik"]),
                "top_event_ids": top_join(group["event_id"]),
                "research_only": True,
                "production_activation_allowed": False,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), {"status": "blocked", "reason": "no scored candidates"}
    out = attach_candidate_metadata(
        out,
        metadata if metadata is not None else pd.DataFrame(),
        min_market_cap_usd=float(min_market_cap_usd),
        min_dollar_volume_usd=float(min_dollar_volume_usd),
        min_price=float(min_price),
    )
    raw_candidate_rows = int(len(out))
    tradable_candidate_rows = int(out["tradable_candidate"].sum()) if "tradable_candidate" in out.columns else 0
    if bool(tradable_only):
        out = out[out["tradable_candidate"].astype(bool)].copy()
    if out.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS), {
            "status": "blocked",
            "reason": "no tradable candidates after metadata/liquidity filter" if bool(tradable_only) else "no scored candidates",
            "as_of_date": as_of_ts.isoformat(),
            "lookback_days": int(lookback_days),
            "raw_candidate_rows": raw_candidate_rows,
            "tradable_candidate_rows": tradable_candidate_rows,
            "metadata_ticker_count": int(len(metadata)) if metadata is not None else 0,
            "tradable_only": bool(tradable_only),
            "min_market_cap_usd": float(min_market_cap_usd),
            "min_dollar_volume_usd": float(min_dollar_volume_usd),
            "min_price": float(min_price),
            "research_only": True,
            "production_activation_allowed": False,
            "score_total_changed": False,
        }
    out = out.sort_values(
        [
            "post_disclosure_candidate_score",
            "engine_confirmation_score",
            "tradability_score",
            "evidence_confidence",
            "source_count",
            "event_count",
        ],
        ascending=False,
    ).reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    out["candidate_explanation"] = out.apply(explanation, axis=1)
    out = out[[col for col in OUTPUT_COLUMNS if col in out.columns]]
    if top_n > 0:
        out = out.head(int(top_n)).copy()
    summary = {
        "status": "completed",
        "schema_version": "post-disclosure-alpha-candidates-v1",
        "as_of_date": as_of_ts.isoformat(),
        "lookback_days": int(lookback_days),
        "event_rows": int(len(scoped)),
        "candidate_rows": int(len(out)),
        "raw_candidate_rows": raw_candidate_rows,
        "tradable_candidate_rows": tradable_candidate_rows,
        "metadata_ticker_count": int(len(metadata)) if metadata is not None else 0,
        "tradable_only": bool(tradable_only),
        "min_market_cap_usd": float(min_market_cap_usd),
        "min_dollar_volume_usd": float(min_dollar_volume_usd),
        "min_price": float(min_price),
        "unique_tickers": int(scoped["ticker"].nunique()),
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
    }
    return out, summary


def render_report(summary: dict[str, Any], candidates: pd.DataFrame) -> str:
    lines = [
        "# Post-Disclosure Alpha Candidates",
        "",
        "Research-only watchlist generated from current 13F/Form 4/ETF disclosure events and PIT manager-alpha scores.",
        "",
        f"- status: `{summary.get('status')}`",
        f"- as of: `{summary.get('as_of_date', '')}`",
        f"- event rows: {summary.get('event_rows', 0)}",
        f"- raw candidate rows: {summary.get('raw_candidate_rows', summary.get('candidate_rows', 0))}",
        f"- tradable candidate rows: {summary.get('tradable_candidate_rows', 0)}",
        f"- candidate rows: {summary.get('candidate_rows', 0)}",
        "",
        "| rank | ticker | score | tradable | market cap | dollar volume | sources | events | explanation |",
        "| ---: | --- | ---: | --- | ---: | ---: | --- | --- | --- |",
    ]
    if not candidates.empty:
        for _, row in candidates.head(20).iterrows():
            lines.append(
                "| {rank} | {ticker} | {score:.3f} | {tradable} | {mcap:.0f} | {dvol:.0f} | {sources} | {events} | {explain} |".format(
                    rank=int(row.get("rank", 0)),
                    ticker=row.get("ticker", ""),
                    score=float(row.get("post_disclosure_candidate_score", 0.0) or 0.0),
                    tradable=bool(row.get("tradable_candidate", False)),
                    mcap=float(row.get("market_cap_usd", 0.0) or 0.0),
                    dvol=float(row.get("dollar_volume_20d", 0.0) or 0.0),
                    sources=str(row.get("source_types", "")).replace("|", "/"),
                    events=str(row.get("event_types", "")).replace("|", "/"),
                    explain=str(row.get("candidate_explanation", "")).replace("|", "/"),
                )
            )
    lines.extend(["", "No production activation is allowed from this report alone.", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    events = event_universe(
        read_table(args.events_13f),
        read_table(args.events_form4),
        read_table(args.events_etf),
    )
    manager_scores = normalize_manager_scores(read_table(args.manager_scores))
    metadata = normalize_candidate_metadata(read_table(getattr(args, "metadata", DEFAULT_METADATA)))
    candidates, summary = build_candidates(
        events,
        manager_scores,
        metadata=metadata,
        as_of_date=args.as_of_date,
        lookback_days=int(args.lookback_days),
        top_n=int(args.top_n),
        tradable_only=bool(getattr(args, "tradable_only", False)),
        min_market_cap_usd=float(getattr(args, "min_market_cap_usd", 300_000_000.0)),
        min_dollar_volume_usd=float(getattr(args, "min_dollar_volume_usd", 5_000_000.0)),
        min_price=float(getattr(args, "min_price", 2.0)),
    )
    ranked_path = output_dir / "ranked_candidates.csv"
    latest_path = output_dir / "latest.csv"
    candidates.to_csv(ranked_path, index=False)
    candidates.to_csv(latest_path, index=False)
    summary.update(
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "events_13f": str(repo_path(args.events_13f)),
            "events_form4": str(repo_path(args.events_form4)),
            "events_etf": str(repo_path(args.events_etf)),
            "manager_scores": str(repo_path(args.manager_scores)),
            "metadata": str(repo_path(getattr(args, "metadata", DEFAULT_METADATA))),
            "outputs": {
                "ranked_candidates": str(ranked_path),
                "latest": str(latest_path),
                "summary": str(output_dir / "summary.json"),
                "report": str(output_dir / "report.md"),
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, candidates), encoding="utf-8")
    print(json.dumps({"status": summary.get("status"), "candidate_rows": int(len(candidates))}, sort_keys=True))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-13f", default=DEFAULT_13F_EVENTS)
    parser.add_argument("--events-form4", default=DEFAULT_FORM4_EVENTS)
    parser.add_argument("--events-etf", default=DEFAULT_ETF_EVENTS)
    parser.add_argument("--manager-scores", default=DEFAULT_MANAGER_SCORES)
    parser.add_argument("--metadata", default=DEFAULT_METADATA)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--top-n", type=int, default=30)
    parser.add_argument("--tradable-only", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--min-market-cap-usd", type=float, default=300_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=5_000_000.0)
    parser.add_argument("--min-price", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
