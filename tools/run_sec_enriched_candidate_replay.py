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
from tools.run_etf_holdings_refresh import build_signals as build_etf_signals  # noqa: E402
from tools.run_sec_ownership_signals import SIGNAL_COLUMNS, build_form4_signal  # noqa: E402

DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_FORM4 = "data_pit/sec/form4_transactions.parquet"
DEFAULT_13F = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_ETF_HOLDINGS = "data_pit/etf_holdings/etf_holdings.parquet"
DEFAULT_TOP_MANAGER_SIGNALS = "data_pit/sec/top_manager_discovery_signals.parquet"
DEFAULT_OUTPUT_DIR = "outputs/sec_enriched_candidate_replay"

# Walk-forward Top-7 manager discovery signals (built by
# tools/build_top_manager_discovery_signals.py). These feed the
# TOP7_MANAGER_DISCOVERY lane in r1000_candidate_lanes.py; merging them here is
# what turns top7_manager_discovery_lane_score on downstream in vNext.
TOP_MANAGER_FEATURE_COLUMNS = [
    "top3_manager_count",
    "top7_manager_count",
    "top10_manager_count",
    "top7_discovery_score",
    "top_manager_discovery_score",
]

SEC_SIGNAL_COLUMNS = [c for c in SIGNAL_COLUMNS if c not in {"ticker", "latest_available_from"}]
INSTITUTIONAL_FEATURE_COLUMNS = [c for c in INSTITUTIONAL_SIGNAL_COLUMNS if c not in {"ticker", "latest_available_from"}]
ETF_FEATURE_COLUMNS = [
    "etf_consensus_count",
    "etf_weight_sum",
    "etf_recent_add_score",
    "etf_theme_leadership_score",
    "etf_crowding_score",
    "etf_holdings_score",
    "etf_evidence_confidence",
    "etf_themes",
    "etf_sources",
]
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
    "etf_consensus_count",
    "etf_weight_sum",
    "etf_recent_add_score",
    "etf_theme_leadership_score",
    "etf_crowding_score",
    "etf_holdings_score",
    "etf_evidence_confidence",
    "sec_form4_score",
    "sec_13f_score",
    "etf_holdings_score_shadow",
    "smart_money_shadow_score",
    "smart_money_evidence_source_count",
    "smart_money_convergence_bonus",
    "smart_money_risk_penalty",
    "evidence_fusion_score",
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
        "AIRLS": "AIRLINES",
        "AMER": "AMERICA",
        "BK": "BANK",
        "CENTY": "CENTURY",
        "FINL": "FINANCIAL",
        "INDS": "INDUSTRIES",
        "INTL": "INTERNATIONAL",
        "MACHS": "MACHINES",
        "MTRS": "MOTORS",
        "PETE": "PETROLEUM",
        "SVCS": "SERVICES",
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
        "AND",
        "DEL",
        "DELAWARE",
        "N",
        "OF",
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


def _etf_available_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "available_from" not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    return pd.to_datetime(frame["available_from"], errors="coerce", utc=True).dt.tz_convert(None)


def _etf_snapshot_asof(holdings: pd.DataFrame, dt: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    if holdings.empty or "available_from" not in holdings.columns:
        return pd.DataFrame(), pd.DataFrame()
    d = holdings.copy()
    d["_available_ts"] = _etf_available_series(d)
    as_of = pd.Timestamp(dt).normalize() + pd.Timedelta(hours=23, minutes=59, seconds=59)
    eligible = d[d["_available_ts"].notna() & (d["_available_ts"] <= as_of)].copy()
    if eligible.empty:
        return pd.DataFrame(), pd.DataFrame()

    current_parts: list[pd.DataFrame] = []
    previous_parts: list[pd.DataFrame] = []
    for _, group in eligible.groupby("etf_ticker", sort=False):
        available_dates = sorted(group["_available_ts"].dropna().unique())
        if not available_dates:
            continue
        latest = available_dates[-1]
        current_parts.append(group[group["_available_ts"].eq(latest)].drop(columns=["_available_ts"]))
        if len(available_dates) >= 2:
            prev = available_dates[-2]
            previous_parts.append(group[group["_available_ts"].eq(prev)].drop(columns=["_available_ts"]))
    current = pd.concat(current_parts, ignore_index=True, sort=False) if current_parts else pd.DataFrame()
    previous = pd.concat(previous_parts, ignore_index=True, sort=False) if previous_parts else pd.DataFrame()
    return current, previous


def build_etf_features_by_date(etf_holdings: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for dt in sorted({pd.Timestamp(d).normalize() for d in dates}):
        current, previous = _etf_snapshot_asof(etf_holdings, dt)
        signals = build_etf_signals(current, previous)
        if signals.empty:
            continue
        signals = signals.copy()
        signals["rebalance_date"] = dt
        frames.append(signals)
    if not frames:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "latest_available_from", *ETF_FEATURE_COLUMNS])
    return pd.concat(frames, ignore_index=True, sort=False)


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


def add_smart_money_shadow_scores(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    inst_score = numeric(d, "institutional_evidence_score", 0.0).clip(0.0, 1.0)
    inst_conf = numeric(d, "institutional_evidence_confidence_score", 0.0).clip(0.0, 1.0)
    insider_score = numeric(d, "early_evidence_score", 0.0).clip(0.0, 1.0)
    insider_conf = numeric(d, "evidence_confidence_score", 0.0).clip(0.0, 1.0)
    etf_score = numeric(d, "etf_holdings_score", 0.0).clip(0.0, 1.0)
    etf_conf = numeric(d, "etf_evidence_confidence", 0.0).clip(0.0, 1.0)
    d["sec_13f_score"] = (inst_score * inst_conf).fillna(0.0)
    d["sec_form4_score"] = (insider_score * insider_conf).fillna(0.0)
    d["etf_holdings_score_shadow"] = (etf_score * etf_conf).fillna(0.0)
    has_inst = d["sec_13f_score"] > 0.0
    has_insider = d["sec_form4_score"] > 0.0
    has_etf = d["etf_holdings_score_shadow"] > 0.0
    d["smart_money_evidence_source_count"] = has_inst.astype(int) + has_insider.astype(int) + has_etf.astype(int)
    d["smart_money_convergence_bonus"] = (d["smart_money_evidence_source_count"].clip(0, 3) - 1).clip(lower=0) * 0.06
    d["smart_money_risk_penalty"] = (
        0.05 * numeric(d, "sec_13f_crowding_score", 0.0).clip(0.0, 1.0)
        + 0.03 * numeric(d, "sec_13f_stale_penalty", 0.0).clip(0.0, 1.0)
        + 0.04 * numeric(d, "sec_form4_sale_pressure_score", 0.0).clip(0.0, 1.0)
        + 0.03 * numeric(d, "etf_crowding_score", 0.0).clip(0.0, 1.0)
    ).fillna(0.0)
    d["smart_money_shadow_score"] = (
        0.45 * d["sec_13f_score"]
        + 0.35 * d["sec_form4_score"]
        + 0.20 * d["etf_holdings_score_shadow"]
        + d["smart_money_convergence_bonus"]
        - d["smart_money_risk_penalty"]
    ).fillna(0.0).clip(0.0, 1.0)
    d["evidence_fusion_score"] = (
        0.28 * d["smart_money_shadow_score"]
        + 0.20 * numeric(d, "sec_combined_evidence_score", 0.0).clip(0.0, 1.0)
        + 0.18 * numeric(d, "leader_onset_sec_v3_score", 0.0).clip(0.0, 1.0)
        + 0.16 * numeric(d, "selection_market_confirmation_score", 0.0).clip(0.0, 1.0)
        + 0.10 * rank_by_date(d, "industry_group_strength_score")
        + 0.08 * rank_by_date(d, "rs_acceleration_score")
    ).fillna(0.0).clip(0.0, 1.0)
    return d


def enrich_candidate_book(
    candidates: pd.DataFrame,
    form4: pd.DataFrame,
    holdings_13f: pd.DataFrame | None = None,
    etf_holdings: pd.DataFrame | None = None,
    top_manager_signals: pd.DataFrame | None = None,
    *,
    lookback_days: int = 90,
    institutional_lookback_days: int = 210,
) -> pd.DataFrame:
    d = prepare_candidate_book(candidates)
    if d.empty:
        return pd.DataFrame()

    original_score_total = d["score_total"].copy() if "score_total" in d.columns else None
    refresh_cols = set(SEC_SIGNAL_COLUMNS) | set(INSTITUTIONAL_FEATURE_COLUMNS) | set(ETF_FEATURE_COLUMNS) | set(ENRICHED_SCORE_COLUMNS) | set(TOP_MANAGER_FEATURE_COLUMNS)
    refresh_cols.update(
        {
            "latest_available_from",
            "latest_13f_available_from",
            "latest_etf_available_from",
            "latest_top_manager_available_from",
            "sec_evidence_research_only",
            "sec_evidence_production_activation_allowed",
            "sec_evidence_source",
        }
    )
    d = d.drop(columns=[c for c in refresh_cols if c in d.columns], errors="ignore")
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

    etf_holdings = etf_holdings if etf_holdings is not None else pd.DataFrame()
    etf_signals = build_etf_features_by_date(etf_holdings, dates)
    if etf_signals.empty:
        for col in ETF_FEATURE_COLUMNS:
            d[col] = "" if col in {"etf_themes", "etf_sources"} else 0.0
        d["latest_etf_available_from"] = ""
    else:
        etf_signals["ticker"] = etf_signals["ticker"].astype(str).str.upper().str.strip()
        etf_signals["rebalance_date"] = pd.to_datetime(etf_signals["rebalance_date"], errors="coerce").dt.normalize()
        etf = etf_signals.rename(columns={"latest_available_from": "latest_etf_available_from"})
        keep = ["rebalance_date", "ticker", *[c for c in etf.columns if c in ETF_FEATURE_COLUMNS], "latest_etf_available_from"]
        d = d.merge(etf[keep], on=["rebalance_date", "ticker"], how="left")
        for col in ETF_FEATURE_COLUMNS:
            if col in {"etf_themes", "etf_sources"}:
                d[col] = d.get(col, "").fillna("").astype(str)
            else:
                d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
        d["latest_etf_available_from"] = d.get("latest_etf_available_from", "").fillna("").astype(str)

    top_manager_signals = top_manager_signals if top_manager_signals is not None else pd.DataFrame()
    if top_manager_signals.empty or "ticker" not in top_manager_signals.columns:
        for col in TOP_MANAGER_FEATURE_COLUMNS:
            d[col] = 0.0
        d["latest_top_manager_available_from"] = ""
    else:
        tm = top_manager_signals.copy()
        tm["ticker"] = tm["ticker"].astype(str).str.upper().str.strip()
        tm["rebalance_date"] = pd.to_datetime(tm["rebalance_date"], errors="coerce").dt.normalize()
        avail_col = ["latest_top_manager_available_from"] if "latest_top_manager_available_from" in tm.columns else []
        keep = ["rebalance_date", "ticker", *[c for c in TOP_MANAGER_FEATURE_COLUMNS if c in tm.columns], *avail_col]
        d = d.merge(tm[keep], on=["rebalance_date", "ticker"], how="left")
        for col in TOP_MANAGER_FEATURE_COLUMNS:
            d[col] = pd.to_numeric(d.get(col), errors="coerce").fillna(0.0)
        d["latest_top_manager_available_from"] = d.get("latest_top_manager_available_from", "").fillna("").astype(str)

    d = add_combined_sec_scores(d)
    d = add_leader_onset_sec_v2(d)
    d = add_smart_money_shadow_scores(d)
    d["sec_evidence_research_only"] = True
    d["sec_evidence_production_activation_allowed"] = False
    d["sec_evidence_source"] = "form4_13f_etf_shadow"
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
    etf_holdings_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    rows = int(len(enriched))
    with_evidence = int((numeric(enriched, "evidence_confidence_score", 0.0) > 0).sum()) if rows else 0
    with_13f = int((numeric(enriched, "institutional_evidence_confidence_score", 0.0) > 0).sum()) if rows else 0
    with_etf = int((numeric(enriched, "etf_evidence_confidence", 0.0) > 0).sum()) if rows else 0
    with_smart_money = int((numeric(enriched, "smart_money_shadow_score", 0.0) > 0).sum()) if rows else 0
    with_top_manager = int((numeric(enriched, "top_manager_discovery_score", 0.0) > 0).sum()) if rows else 0
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
        "etf_holdings": str(etf_holdings_path),
        "output_csv": str(output_path),
        "row_count": rows,
        "rows_with_sec_evidence": with_evidence,
        "rows_with_13f_evidence": with_13f,
        "rows_with_etf_evidence": with_etf,
        "rows_with_smart_money_evidence": with_smart_money,
        "coverage_ratio": float(with_evidence / rows) if rows else 0.0,
        "coverage_13f_ratio": float(with_13f / rows) if rows else 0.0,
        "coverage_etf_ratio": float(with_etf / rows) if rows else 0.0,
        "coverage_smart_money_ratio": float(with_smart_money / rows) if rows else 0.0,
        "rows_with_top_manager_evidence": with_top_manager,
        "coverage_top_manager_ratio": float(with_top_manager / rows) if rows else 0.0,
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
        f"- rows with ETF evidence: {summary.get('rows_with_etf_evidence', 0)}",
        f"- rows with smart-money evidence: {summary.get('rows_with_smart_money_evidence', 0)}",
        f"- coverage ratio: {float(summary.get('coverage_ratio', 0.0)):.2%}",
        f"- 13F coverage ratio: {float(summary.get('coverage_13f_ratio', 0.0)):.2%}",
        "",
        "## Top SEC Evidence Rows",
        "",
        "| date | ticker | form4 | 13F | ETF | smart money | fusion | leader_onset_sec_v3 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not enriched.empty:
        top = enriched.sort_values(["evidence_fusion_score", "smart_money_shadow_score"], ascending=False).head(20)
        for _, row in top.iterrows():
            lines.append(
                "| {date} | {ticker} | {form4:.3f} | {inst:.3f} | {etf:.3f} | {smart:.3f} | {fusion:.3f} | {leader:.3f} |".format(
                    date=pd.Timestamp(row.get("rebalance_date")).date().isoformat()
                    if pd.notna(row.get("rebalance_date"))
                    else "",
                    ticker=row.get("ticker", ""),
                    form4=float(row.get("early_evidence_score", 0.0) or 0.0),
                    inst=float(row.get("institutional_evidence_score", 0.0) or 0.0),
                    etf=float(row.get("etf_holdings_score", 0.0) or 0.0),
                    smart=float(row.get("smart_money_shadow_score", 0.0) or 0.0),
                    fusion=float(row.get("evidence_fusion_score", 0.0) or 0.0),
                    leader=float(row.get("leader_onset_sec_v3_score", 0.0) or 0.0),
                )
            )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_path = repo_path(args.candidate_book)
    form4_path = repo_path(args.form4)
    institutional_13f_path = repo_path(args.institutional_13f)
    etf_holdings_path = repo_path(args.etf_holdings)
    top_manager_signals_path = repo_path(getattr(args, "top_manager_signals", DEFAULT_TOP_MANAGER_SIGNALS))
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = read_table(candidate_path)
    form4 = read_table(form4_path)
    holdings_13f = read_table(institutional_13f_path)
    etf_holdings = read_table(etf_holdings_path)
    top_manager_signals = read_table(top_manager_signals_path) if top_manager_signals_path.exists() else pd.DataFrame()
    enriched = enrich_candidate_book(
        candidates,
        form4,
        holdings_13f,
        etf_holdings,
        top_manager_signals,
        lookback_days=int(args.lookback_days),
        institutional_lookback_days=int(args.institutional_lookback_days),
    )
    output_path = output_dir / "candidate_replay_book_sec_enriched.csv"
    enriched_out = enriched.copy()
    if "rebalance_date" in enriched_out.columns:
        enriched_out["rebalance_date"] = pd.to_datetime(enriched_out["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    enriched_out.to_csv(output_path, index=False)
    summary = summary_payload(enriched_out, candidate_path, form4_path, institutional_13f_path, etf_holdings_path, output_path)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, enriched), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--form4", default=DEFAULT_FORM4)
    parser.add_argument("--institutional-13f", default=DEFAULT_13F)
    parser.add_argument("--etf-holdings", default=DEFAULT_ETF_HOLDINGS)
    parser.add_argument("--top-manager-signals", default=DEFAULT_TOP_MANAGER_SIGNALS)
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
