#!/usr/bin/env python3
"""Broker-ledger grid for simple leader-alpha selectors.

This research-only sidecar tests whether the strongest point-in-time
future/early/monster leader scores survive realistic account replay. It builds
monthly target books from `candidate_replay_book.csv`, then evaluates each
variant through the standard broker ledger:

- signal dated T is filled at next available close;
- integer shares, fees, cash, and daily account equity are preserved;
- selection uses only same-date candidate features;
- forward-return labels are never used for selection.
"""
from __future__ import annotations

import argparse
import inspect
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_broker_ledger_replay import replay as broker_replay, repo_path, safe_float  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402

BROKER_REPLAY_PARAMS = set(inspect.signature(broker_replay).parameters)


DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_OUT_DIR = "outputs/alpha_selector_broker_grid"

STYLE_WEIGHTS: dict[str, dict[str, float]] = {
    "future_heavy": {
        "portfolio_future_winner_engine_score": 0.35,
        "portfolio_early_scout_engine_score": 0.20,
        "portfolio_monster_early_score": 0.20,
        "h6_dynamic_leader_score": 0.10,
        "rs_acceleration_score": 0.08,
        "industry_group_strength_score": 0.05,
        "score": 0.02,
    },
    "future_heavy_post_disclosure_micro": {
        "portfolio_future_winner_engine_score": 0.32,
        "portfolio_early_scout_engine_score": 0.18,
        "portfolio_monster_early_score": 0.18,
        "h6_dynamic_leader_score": 0.09,
        "rs_acceleration_score": 0.07,
        "industry_group_strength_score": 0.04,
        "post_disclosure_discovery_score": 0.04,
        "post_disclosure_mega_confirmation_score": 0.03,
        "score": 0.02,
        "pda_13f_first_buy_surprise_score": 0.01,
        "pda_form4_open_market_buy_score": 0.01,
        "pda_etf_new_or_increase_score": 0.01,
    },
    "future_heavy_post_disclosure_confirmed": {
        "portfolio_future_winner_engine_score": 0.30,
        "portfolio_early_scout_engine_score": 0.17,
        "portfolio_monster_early_score": 0.17,
        "selection_market_confirmation_score": 0.10,
        "rs_acceleration_score": 0.08,
        "industry_group_strength_score": 0.05,
        "entry_quality_score": 0.04,
        "post_disclosure_price_confirmed_score": 0.04,
        "post_disclosure_discovery_score": 0.02,
        "pda_13f_first_buy_surprise_score": 0.01,
        "pda_form4_open_market_buy_score": 0.01,
        "pda_etf_new_or_increase_score": 0.01,
    },
    "future_heavy_post_disclosure_satellite": {
        "portfolio_future_winner_engine_score": 0.30,
        "portfolio_early_scout_engine_score": 0.17,
        "portfolio_monster_early_score": 0.17,
        "h6_dynamic_leader_score": 0.08,
        "selection_market_confirmation_score": 0.07,
        "rs_acceleration_score": 0.06,
        "industry_group_strength_score": 0.04,
        "entry_quality_score": 0.03,
        "post_disclosure_price_confirmed_score": 0.03,
        "post_disclosure_discovery_score": 0.02,
        "pda_13f_first_buy_surprise_score": 0.01,
        "pda_form4_open_market_buy_score": 0.01,
        "pda_etf_new_or_increase_score": 0.01,
    },
    "future_heavy_post_disclosure_optional_satellite": {
        "portfolio_future_winner_engine_score": 0.30,
        "portfolio_early_scout_engine_score": 0.17,
        "portfolio_monster_early_score": 0.17,
        "h6_dynamic_leader_score": 0.08,
        "selection_market_confirmation_score": 0.07,
        "rs_acceleration_score": 0.06,
        "industry_group_strength_score": 0.04,
        "entry_quality_score": 0.03,
        "post_disclosure_price_confirmed_score": 0.03,
        "post_disclosure_discovery_score": 0.02,
        "pda_13f_first_buy_surprise_score": 0.01,
        "pda_form4_open_market_buy_score": 0.01,
        "pda_etf_new_or_increase_score": 0.01,
    },
    "monster_heavy": {
        "portfolio_monster_early_score": 0.30,
        "portfolio_future_winner_engine_score": 0.25,
        "portfolio_early_scout_engine_score": 0.15,
        "h6_dynamic_leader_score": 0.12,
        "rs_acceleration_score": 0.10,
        "industry_group_strength_score": 0.05,
        "score": 0.03,
    },
    "rs_heavy": {
        "portfolio_future_winner_engine_score": 0.20,
        "portfolio_early_scout_engine_score": 0.15,
        "portfolio_monster_early_score": 0.15,
        "h6_dynamic_leader_score": 0.15,
        "rs_acceleration_score": 0.20,
        "industry_group_strength_score": 0.10,
        "score": 0.05,
    },
    "leader_onset_shadow": {
        "leader_onset_score": 0.35,
        "portfolio_monster_early_score": 0.18,
        "portfolio_future_winner_engine_score": 0.16,
        "portfolio_early_scout_engine_score": 0.12,
        "rs_acceleration_score": 0.10,
        "h6_dynamic_leader_score": 0.06,
        "industry_group_strength_score": 0.03,
    },
    "future_winner_smart_money": {
        "portfolio_future_winner_engine_score": 0.34,
        "selection_market_confirmation_score": 0.16,
        "rs_acceleration_score": 0.12,
        "industry_group_strength_score": 0.10,
        "portfolio_early_scout_engine_score": 0.08,
        "smart_money_shadow_score": 0.07,
        "sec_13f_score": 0.05,
        "evidence_fusion_score": 0.04,
        "sec_form4_score": 0.02,
        "entry_quality_score": 0.02,
    },
    "sec_evidence_shadow": {
        "evidence_fusion_score": 0.22,
        "leader_onset_sec_v3_score": 0.20,
        "portfolio_future_winner_engine_score": 0.15,
        "selection_market_confirmation_score": 0.10,
        "sec_combined_evidence_score": 0.10,
        "institutional_evidence_score": 0.05,
        "early_evidence_score": 0.05,
        "etf_holdings_score": 0.05,
        "rs_acceleration_score": 0.05,
        "entry_quality_score": 0.02,
        "industry_group_strength_score": 0.01,
    },
    "smart_money_shadow": {
        "smart_money_shadow_score": 0.30,
        "evidence_fusion_score": 0.22,
        "portfolio_future_winner_engine_score": 0.16,
        "selection_market_confirmation_score": 0.12,
        "leader_onset_sec_v3_score": 0.08,
        "sec_combined_evidence_score": 0.04,
        "etf_holdings_score": 0.03,
        "rs_acceleration_score": 0.03,
        "entry_quality_score": 0.02,
    },
    "post_disclosure_tiebreaker": {
        "portfolio_future_winner_engine_score": 0.32,
        "selection_market_confirmation_score": 0.18,
        "portfolio_early_scout_engine_score": 0.13,
        "portfolio_monster_early_score": 0.12,
        "rs_acceleration_score": 0.08,
        "industry_group_strength_score": 0.06,
        "entry_quality_score": 0.04,
        "post_disclosure_alpha_score": 0.04,
        "pda_13f_event_score": 0.01,
        "pda_form4_event_score": 0.01,
        "pda_etf_event_score": 0.01,
    },
    "post_disclosure_discovery": {
        "post_disclosure_discovery_score": 0.24,
        "portfolio_future_winner_engine_score": 0.18,
        "selection_market_confirmation_score": 0.14,
        "pda_13f_first_buy_surprise_score": 0.10,
        "pda_form4_open_market_buy_score": 0.10,
        "pda_etf_new_or_increase_score": 0.08,
        "pda_size_discovery_score": 0.06,
        "rs_acceleration_score": 0.04,
        "industry_group_strength_score": 0.03,
        "entry_quality_score": 0.03,
    },
    "post_disclosure_price_confirmed": {
        "post_disclosure_price_confirmed_score": 0.24,
        "selection_market_confirmation_score": 0.20,
        "portfolio_future_winner_engine_score": 0.18,
        "rs_acceleration_score": 0.12,
        "entry_quality_score": 0.08,
        "pda_13f_first_buy_surprise_score": 0.06,
        "pda_form4_open_market_buy_score": 0.05,
        "pda_etf_new_or_increase_score": 0.03,
        "industry_group_strength_score": 0.03,
        "pda_negative_event_score": -0.01,
    },
    "post_disclosure_mega_confirmation": {
        "portfolio_future_winner_engine_score": 0.28,
        "selection_market_confirmation_score": 0.18,
        "post_disclosure_mega_confirmation_score": 0.16,
        "post_disclosure_alpha_score": 0.10,
        "pda_13f_event_score": 0.07,
        "pda_form4_event_score": 0.06,
        "pda_etf_event_score": 0.05,
        "rs_acceleration_score": 0.04,
        "industry_group_strength_score": 0.04,
        "entry_quality_score": 0.02,
    },
    "post_disclosure_light": {
        "portfolio_future_winner_engine_score": 0.30,
        "selection_market_confirmation_score": 0.18,
        "post_disclosure_alpha_score": 0.12,
        "pda_13f_event_score": 0.05,
        "pda_form4_event_score": 0.05,
        "pda_etf_event_score": 0.04,
        "rs_acceleration_score": 0.10,
        "industry_group_strength_score": 0.10,
        "entry_quality_score": 0.06,
    },
    "post_disclosure_balanced": {
        "post_disclosure_alpha_score": 0.22,
        "portfolio_future_winner_engine_score": 0.22,
        "selection_market_confirmation_score": 0.16,
        "pda_13f_event_score": 0.10,
        "pda_form4_event_score": 0.10,
        "pda_etf_event_score": 0.06,
        "rs_acceleration_score": 0.07,
        "industry_group_strength_score": 0.05,
        "entry_quality_score": 0.02,
    },
}
RISK_COLUMNS = ("portfolio_risk_entry_block_score", "portfolio_stale_mega_leader_score")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def clean_label(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "na"


def parse_csv_ints(value: str, default: list[int]) -> list[int]:
    out: list[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(float(part)))
        except ValueError:
            continue
    return out or list(default)


def parse_csv_floats(value: str, default: list[float]) -> list[float]:
    out: list[float] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out or list(default)


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def rank_feature(frame: pd.DataFrame, col: str, *, lower_is_better: bool = False) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(0.5, index=frame.index, dtype=float)
    return (
        frame.groupby("rebalance_date")[col]
        .rank(pct=True, ascending=not lower_is_better)
        .fillna(0.5)
        .clip(0.0, 1.0)
    )


def add_leader_onset_score(frame: pd.DataFrame) -> pd.DataFrame:
    """Add a same-date, no-forward-label early-leader shadow score.

    This score intentionally uses only contemporaneous candidate features and
    liquidity/volume proxies. It is a selector diagnostic, not a production
    model feature, and never reads forward-return columns.
    """
    if frame.empty:
        return frame
    d = frame.copy()
    components = {
        "portfolio_monster_early_score": 0.22,
        "portfolio_future_winner_engine_score": 0.18,
        "portfolio_early_scout_engine_score": 0.14,
        "rs_acceleration_score": 0.14,
        "h6_dynamic_leader_score": 0.12,
        "industry_group_strength_score": 0.08,
        "relative_strength_composite": 0.05,
        "oneil_leadership_score": 0.04,
        "governance_catalyst_score": 0.03,
    }
    score = pd.Series(0.0, index=d.index, dtype=float)
    used_weight = 0.0
    for col, weight in components.items():
        if col in d.columns:
            values = pd.to_numeric(d[col], errors="coerce").fillna(0.0).clip(0.0, 1.0)
            score += float(weight) * values
            used_weight += float(weight)
    if "dollar_vol_20d" in d.columns:
        dollar_vol_rank = rank_feature(d, "dollar_vol_20d")
        score += 0.05 * dollar_vol_rank
        used_weight += 0.05
    if "px" in d.columns:
        # Price rank is only a coarse liquidity/attention proxy. It is kept at
        # tiny weight so small caps are not mechanically excluded.
        score += 0.02 * rank_feature(d, "px")
        used_weight += 0.02
    if used_weight <= 0:
        d["leader_onset_score"] = 0.0
    else:
        d["leader_onset_score"] = (score / used_weight).fillna(0.0).clip(0.0, 1.0)
    return d


def prepare_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d.dropna(subset=["rebalance_date"])
    d = d[d["ticker"].ne("")].copy()
    d = add_leader_onset_score(d)
    for col in sorted({c for weights in STYLE_WEIGHTS.values() for c in weights} | set(RISK_COLUMNS)):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    for col in sorted({c for weights in STYLE_WEIGHTS.values() for c in weights}):
        d[f"{col}_rank"] = rank_feature(d, col)
    for col in RISK_COLUMNS:
        d[f"{col}_safe_rank"] = rank_feature(d, col, lower_is_better=True)
    return d


def add_price_cache_tradeability(candidates: pd.DataFrame, price_cache: Path, max_fill_lag_days: int) -> pd.DataFrame:
    """Mark candidates that can actually be filled by the broker replay.

    The selector's liquidity fields can be populated even when the replay price
    cache lacks a next-close bar. If such names enter the target book, broker
    replay holds cash instead of the intended exposure, making the target book
    look invested while the account is not. This gate keeps the selector aligned
    with the official account-ledger evaluator.
    """
    if candidates.empty:
        return candidates
    out = candidates.copy()
    tickers = sorted(out["ticker"].astype(str).str.upper().unique())
    date_map: dict[str, np.ndarray] = {}
    for ticker in tickers:
        px = load_price_series(price_cache, ticker)
        if px.empty or "close" not in px.columns:
            continue
        close = pd.to_numeric(px["close"], errors="coerce").dropna()
        if close.empty:
            continue
        idx = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
        date_map[ticker] = np.array(sorted(idx.unique()), dtype="datetime64[ns]")
    max_lag = max(0, int(max_fill_lag_days))
    flags: list[bool] = []
    for row in out.itertuples(index=False):
        ticker = str(getattr(row, "ticker", "") or "").upper()
        signal_dt = pd.Timestamp(getattr(row, "rebalance_date")).normalize()
        dates = date_map.get(ticker)
        ok = False
        if dates is not None and len(dates):
            pos = int(np.searchsorted(dates, np.datetime64(signal_dt), side="right"))
            if pos < len(dates):
                fill_dt = pd.Timestamp(dates[pos]).normalize()
                ok = 0 <= (fill_dt - signal_dt).days <= max_lag
        flags.append(ok)
    out["price_cache_tradeable"] = flags
    return out


def liquidity_mask(frame: pd.DataFrame, *, min_mcap: float, min_dollar_vol: float, min_price: float) -> pd.Series:
    dollar_vol = numeric(frame, "dollar_vol_20d")
    price = pd.concat(
        [numeric(frame, "px", np.nan), numeric(frame, "current_price_live", np.nan)],
        axis=1,
    ).bfill(axis=1).iloc[:, 0].fillna(0.0)
    mcap = pd.concat(
        [numeric(frame, "market_cap_live", np.nan), numeric(frame, "mktcap", np.nan)],
        axis=1,
    ).max(axis=1).fillna(1e12)
    return (dollar_vol >= float(min_dollar_vol)) & (price >= float(min_price)) & (mcap >= float(min_mcap))


def gate_mask(frame: pd.DataFrame) -> pd.Series:
    sleeve = frame.get("portfolio_sleeve_label", pd.Series("", index=frame.index)).astype(str).str.lower()
    gate = frame.get("portfolio_candidate_gate_label", pd.Series("", index=frame.index)).astype(str).str.lower()
    leader_like = sleeve.str.contains("future|early|monster|leader|concentrated", regex=True, na=False)
    not_rejected = ~gate.str.contains("reject|block|fail", regex=True, na=False)
    risk_ok = numeric(frame, "portfolio_risk_entry_block_score") < 0.75
    stale_ok = numeric(frame, "portfolio_stale_mega_leader_score") < 0.75
    return risk_ok & stale_ok & (not_rejected | leader_like)


def score_candidates(frame: pd.DataFrame, style: str) -> pd.Series:
    weights = STYLE_WEIGHTS[style]
    score = pd.Series(0.0, index=frame.index, dtype=float)
    for col, weight in weights.items():
        score += float(weight) * frame.get(f"{col}_rank", pd.Series(0.5, index=frame.index))
    score += 0.05 * frame.get("portfolio_risk_entry_block_score_safe_rank", pd.Series(0.5, index=frame.index))
    score += 0.05 * frame.get("portfolio_stale_mega_leader_score_safe_rank", pd.Series(0.5, index=frame.index))
    return score.fillna(0.0).clip(0.0, 1.0)


def capped_score_weights(scores: pd.Series, cap: float) -> np.ndarray:
    values = np.maximum(pd.to_numeric(scores, errors="coerce").fillna(0.0).to_numpy(dtype=float), 0.01) ** 2
    weights = values / max(values.sum(), 1e-12)
    cap = max(0.01, min(1.0, float(cap)))
    weights = np.minimum(weights, cap)
    for _ in range(8):
        remaining = 1.0 - float(weights.sum())
        if remaining <= 1e-8:
            break
        room = cap - weights
        if float(room.max()) <= 1e-8:
            break
        weights = np.minimum(cap, weights + remaining * room / max(float(room.sum()), 1e-12))
    return weights


def select_satellite_targets(
    group: pd.DataFrame,
    target_n: int,
    single_name_cap: float,
    *,
    optional: bool = False,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Select a mostly future-heavy book with one capped post-disclosure satellite.

    Prior broker-grid runs showed post-disclosure evidence degrades results
    when it reorders the whole book. This selector keeps the future-heavy core
    intact and gives only one slot to a price-confirmed evidence candidate.
    """
    g = group.copy()
    g["core_score"] = score_candidates(g, "future_heavy")
    g["evidence_score"] = score_candidates(g, "post_disclosure_price_confirmed")
    evidence_signal = (
        (numeric(g, "post_disclosure_price_confirmed_score", 0.0) > 0.05)
        | (numeric(g, "pda_13f_first_buy_surprise_score", 0.0) > 0.05)
        | (numeric(g, "pda_form4_open_market_buy_score", 0.0) > 0.05)
        | (numeric(g, "pda_etf_new_or_increase_score", 0.0) > 0.05)
    )
    if optional:
        price_confirmed = numeric(g, "post_disclosure_price_confirmed_score", 0.0) >= 0.35
        price_confirmation = numeric(g, "post_disclosure_price_confirmation_score", 0.0) >= 0.35
        strong_disclosure = (
            (numeric(g, "pda_13f_first_buy_surprise_score", 0.0) >= 0.45)
            | (numeric(g, "pda_form4_open_market_buy_score", 0.0) >= 0.35)
            | (numeric(g, "pda_etf_new_or_increase_score", 0.0) >= 0.35)
        )
        core_floor = g["core_score"] >= float(g["core_score"].quantile(0.50))
        evidence_signal = evidence_signal & price_confirmed & price_confirmation & strong_disclosure & core_floor
    core_n = max(1, int(target_n) - 1)
    core = g.sort_values("core_score", ascending=False).head(core_n).copy()
    satellite_pool = g[~g["ticker"].isin(set(core["ticker"])) & evidence_signal].copy()
    satellite = satellite_pool.sort_values("evidence_score", ascending=False).head(1).copy()
    if satellite.empty:
        selected = g.sort_values("core_score", ascending=False).head(int(target_n)).copy()
        selected["alpha_selector_score"] = selected["core_score"]
        selected["post_disclosure_satellite_slot"] = False
        return selected, capped_score_weights(selected["alpha_selector_score"], single_name_cap)

    core["alpha_selector_score"] = core["core_score"]
    core["post_disclosure_satellite_slot"] = False
    satellite["alpha_selector_score"] = satellite["evidence_score"]
    satellite["post_disclosure_satellite_slot"] = True
    selected = pd.concat([core, satellite], ignore_index=True)
    cap = max(0.01, min(1.0, float(single_name_cap)))
    target_satellite_budget = max(0.10, 1.0 - (len(core) * cap))
    satellite_budget = min(cap, max(0.01, target_satellite_budget))
    core_budget = max(0.0, 1.0 - satellite_budget)
    core_weights = capped_score_weights(core["alpha_selector_score"], cap)
    core_sum = float(core_weights.sum())
    if core_sum > core_budget > 0:
        core_weights = core_weights * (core_budget / core_sum)
    weights = np.concatenate([core_weights, np.array([satellite_budget], dtype=float)])
    return selected, weights


def build_target_book(
    candidates: pd.DataFrame,
    *,
    style: str,
    target_n: int,
    single_name_cap: float,
    min_mcap: float,
    min_dollar_vol: float,
    min_price: float,
    require_price_cache: bool,
) -> pd.DataFrame:
    d = candidates.copy()
    d["alpha_selector_score"] = score_candidates(d, style)
    mask = liquidity_mask(d, min_mcap=min_mcap, min_dollar_vol=min_dollar_vol, min_price=min_price) & gate_mask(d)
    if require_price_cache:
        mask = mask & d.get("price_cache_tradeable", pd.Series(False, index=d.index)).astype(bool)
    rows: list[dict[str, Any]] = []
    for dt, group in d[mask].groupby("rebalance_date", sort=True):
        if style in {"future_heavy_post_disclosure_satellite", "future_heavy_post_disclosure_optional_satellite"}:
            selected, weights = select_satellite_targets(
                group,
                int(target_n),
                float(single_name_cap),
                optional=style == "future_heavy_post_disclosure_optional_satellite",
            )
        else:
            selected = group.sort_values("alpha_selector_score", ascending=False).head(int(target_n)).copy()
            weights = capped_score_weights(selected["alpha_selector_score"], single_name_cap) if not selected.empty else np.array([], dtype=float)
        if selected.empty:
            continue
        for (_, row), weight in zip(selected.iterrows(), weights):
            rows.append(
                {
                    "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                    "ticker": row.get("ticker"),
                    "Name": row.get("Name", ""),
                    "sector": row.get("sector", ""),
                    "weight": float(weight),
                    "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
                    "portfolio_candidate_gate_label": row.get("portfolio_candidate_gate_label", ""),
                    "leader_onset_score": safe_float(row.get("leader_onset_score")),
                    "leader_onset_sec_v2_score": safe_float(row.get("leader_onset_sec_v2_score")),
                    "leader_onset_sec_v3_score": safe_float(row.get("leader_onset_sec_v3_score")),
                    "early_evidence_score": safe_float(row.get("early_evidence_score")),
                    "institutional_evidence_score": safe_float(row.get("institutional_evidence_score")),
                    "sec_combined_evidence_score": safe_float(row.get("sec_combined_evidence_score")),
                    "etf_holdings_score": safe_float(row.get("etf_holdings_score")),
                    "smart_money_shadow_score": safe_float(row.get("smart_money_shadow_score")),
                    "smart_money_evidence_source_count": safe_float(row.get("smart_money_evidence_source_count")),
                    "evidence_fusion_score": safe_float(row.get("evidence_fusion_score")),
                    "post_disclosure_alpha_score": safe_float(row.get("post_disclosure_alpha_score")),
                    "post_disclosure_discovery_score": safe_float(row.get("post_disclosure_discovery_score")),
                    "post_disclosure_mega_confirmation_score": safe_float(row.get("post_disclosure_mega_confirmation_score")),
                    "post_disclosure_price_confirmation_score": safe_float(row.get("post_disclosure_price_confirmation_score")),
                    "post_disclosure_price_confirmed_score": safe_float(row.get("post_disclosure_price_confirmed_score")),
                    "post_disclosure_satellite_slot": bool(row.get("post_disclosure_satellite_slot", False)),
                    "pda_size_discovery_score": safe_float(row.get("pda_size_discovery_score")),
                    "pda_13f_event_score": safe_float(row.get("pda_13f_event_score")),
                    "pda_13f_new_or_add_score": safe_float(row.get("pda_13f_new_or_add_score")),
                    "pda_13f_new_or_add_count": safe_float(row.get("pda_13f_new_or_add_count")),
                    "pda_13f_first_buy_surprise_score": safe_float(row.get("pda_13f_first_buy_surprise_score")),
                    "pda_13f_first_buy_surprise_count": safe_float(row.get("pda_13f_first_buy_surprise_count")),
                    "pda_form4_event_score": safe_float(row.get("pda_form4_event_score")),
                    "pda_form4_open_market_buy_score": safe_float(row.get("pda_form4_open_market_buy_score")),
                    "pda_form4_open_market_buy_count": safe_float(row.get("pda_form4_open_market_buy_count")),
                    "pda_etf_event_score": safe_float(row.get("pda_etf_event_score")),
                    "pda_etf_new_or_increase_score": safe_float(row.get("pda_etf_new_or_increase_score")),
                    "pda_etf_new_or_increase_count": safe_float(row.get("pda_etf_new_or_increase_count")),
                    "pda_event_convergence_score": safe_float(row.get("pda_event_convergence_score")),
                    "pda_negative_event_score": safe_float(row.get("pda_negative_event_score")),
                    "sec_13f_manager_count": safe_float(row.get("sec_13f_manager_count")),
                    "sec_13f_buying_manager_count": safe_float(row.get("sec_13f_buying_manager_count")),
                    "sec_13f_value_delta_to_mcap": safe_float(row.get("sec_13f_value_delta_to_mcap")),
                    "evidence_confidence_score": safe_float(row.get("evidence_confidence_score")),
                    "alpha_selector_style": style,
                    "alpha_selector_score": safe_float(row.get("alpha_selector_score")),
                    "target_stock_names": int(target_n),
                    "weighting_mode": "alpha_selector",
                    "active_rebalance_interval_months": 1,
                    "research_only_backtest": True,
                    "production_activation_allowed": False,
                }
            )
    return pd.DataFrame(rows)


def target_distance(portfolio_kind: str, metrics: dict[str, Any]) -> float:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio_kind, PORTFOLIO_GOAL_TARGETS["main"])
    cagr = safe_float(metrics.get("cagr"), math.nan)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan)
    if not math.isfinite(cagr) or not math.isfinite(max_dd):
        return math.inf
    return max(0.0, target["cagr"] - cagr) + max(0.0, target["max_dd"] - max_dd)


def variant_id(style: str, n: int, cap: float) -> str:
    return f"{clean_label(style)}_N{int(n)}_cap{clean_label(cap)}"


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_book = repo_path(args.candidate_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = prepare_candidates(read_csv(candidate_book))
    require_price_cache = not bool(getattr(args, "allow_unfillable_targets", False))
    if require_price_cache:
        candidates = add_price_cache_tradeability(candidates, price_cache, int(args.max_fill_lag_days))
    if candidates.empty:
        payload = {
            "status": "blocked",
            "reason": "candidate replay book is missing or empty",
            "candidate_book": str(candidate_book),
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
        write_json(output_dir / "best_metrics.json", payload)
        return payload

    target_ns = parse_csv_ints(args.target_ns, [3, 5, 7])
    caps = parse_csv_floats(args.single_name_caps, [0.33, 0.50])
    styles = [s.strip() for s in str(args.styles or "").split(",") if s.strip() in STYLE_WEIGHTS] or list(STYLE_WEIGHTS)
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    variant_count = 0
    for style in styles:
        for n in target_ns:
            for cap in caps:
                if variant_count >= int(args.max_variants):
                    break
                variant_count += 1
                vid = variant_id(style, n, cap)
                variant_dir = output_dir / vid
                target = build_target_book(
                    candidates,
                    style=style,
                    target_n=n,
                    single_name_cap=cap,
                    min_mcap=float(args.min_market_cap_usd),
                    min_dollar_vol=float(args.min_dollar_volume_usd),
                    min_price=float(args.min_price),
                    require_price_cache=require_price_cache,
                )
                target_path = variant_dir / "target_book.csv"
                variant_dir.mkdir(parents=True, exist_ok=True)
                target.to_csv(target_path, index=False)
                champion_filters = (
                    {
                        "target_stock_names": str(int(n)),
                        "weighting_mode": "alpha_selector",
                        "active_rebalance_interval_months": "1",
                    }
                    if args.portfolio_kind == "concentrated"
                    else None
                )
                try:
                    replay_kwargs = {
                        "target_book": target_path,
                        "price_cache": price_cache,
                        "output_dir": variant_dir,
                        "portfolio_kind": args.portfolio_kind,
                        "starting_capital": float(args.starting_capital),
                        "fill_mode": args.fill_mode,
                        "cost_bps": float(args.cost_bps),
                        "integer_shares": not bool(args.no_integer_shares),
                        "max_fill_lag_days": int(args.max_fill_lag_days),
                    }
                    if champion_filters is not None and "concentrated_champion_filters" in BROKER_REPLAY_PARAMS:
                        replay_kwargs["concentrated_champion_filters"] = champion_filters
                    metrics = broker_replay(**replay_kwargs)
                except Exception as exc:
                    metrics = {
                        "status": "blocked",
                        "reason": f"broker replay failed: {type(exc).__name__}: {exc}",
                        "valid_for_production": False,
                    }
                metrics.update(
                    {
                        "candidate_id": f"{args.portfolio_kind}_alpha_selector_broker_grid_{vid}",
                        "metric_mode": "alpha_selector_broker_grid_next_close",
                        "portfolio_kind": args.portfolio_kind,
                        "alpha_selector_variant": vid,
                        "alpha_selector_style": style,
                        "target_stock_names": int(n),
                        "single_name_cap": float(cap),
                        "require_price_cache": require_price_cache,
                        "candidate_book": str(candidate_book),
                        "target_book": str(target_path),
                        "research_only": True,
                        "production_activation_allowed": False,
                    }
                )
                write_json(variant_dir / "metrics.json", metrics)
                rows.append(
                    {
                        "variant_id": vid,
                        "status": metrics.get("status"),
                        "style": style,
                        "target_stock_names": int(n),
                        "single_name_cap": float(cap),
                        "cagr": metrics.get("cagr"),
                        "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                        "sharpe": metrics.get("sharpe"),
                        "trade_count": metrics.get("trade_count"),
                        "avg_cash_weight": metrics.get("avg_cash_weight"),
                        "target_distance": target_distance(args.portfolio_kind, metrics),
                        "valid_for_production": bool(metrics.get("valid_for_production")),
                        "reason": metrics.get("reason", ""),
                    }
                )
                if metrics.get("status") == "completed" and metrics.get("valid_for_production"):
                    completed.append(metrics)
    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr", "max_dd"], ascending=[True, False, False])
    summary.to_csv(output_dir / "summary.csv", index=False)
    if completed:
        best_by_distance = sorted(completed, key=lambda m: (target_distance(args.portfolio_kind, m), -safe_float(m.get("cagr"), -1.0)))[0]
        best_distance_payload = dict(best_by_distance)
        best_distance_payload.update(
            {
                "status": "completed",
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_broker_grid_best_distance",
                "metric_mode": "alpha_selector_broker_grid_best_distance_next_close",
                "variant_count": variant_count,
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
        write_json(output_dir / "best_target_distance_metrics.json", best_distance_payload)
        best = sorted(
            completed,
            key=lambda m: (
                -safe_float(m.get("cagr"), -1.0),
                -safe_float(m.get("sharpe"), -1.0),
                safe_float(m.get("max_dd", m.get("max_drawdown")), -1.0),
            ),
        )[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "status": "completed",
                "candidate_id": f"{args.portfolio_kind}_alpha_selector_broker_grid_best",
                "metric_mode": "alpha_selector_broker_grid_best_next_close",
                "variant_count": variant_count,
                "selection_rule": "best_cagr_then_sharpe_then_max_dd",
                "best_target_distance_metrics": str(output_dir / "best_target_distance_metrics.json"),
                "research_only": True,
                "production_activation_allowed": False,
                "valid_for_production": True,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed alpha selector broker grid variants",
            "portfolio_kind": args.portfolio_kind,
            "variant_count": variant_count,
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        "# Alpha Selector Broker Grid",
        "",
        "Research-only account-ledger grid for concentrated leader-alpha target books.",
        "",
        f"- Portfolio: `{args.portfolio_kind}`",
        f"- Best CAGR: {safe_float(best_payload.get('cagr')):.2%}",
        f"- Best MaxDD: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown'))):.2%}",
        f"- Best Sharpe: {safe_float(best_payload.get('sharpe')):.3f}",
        f"- Selection rule: `{best_payload.get('selection_rule', 'n/a')}`",
        f"- Variants: {variant_count}",
        "",
        "Promotion requires target gates, stress windows, and human approval.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="main")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--styles", default="future_heavy,monster_heavy,rs_heavy,leader_onset_shadow")
    parser.add_argument("--target-ns", default="3,5,7")
    parser.add_argument("--single-name-caps", default="0.33,0.50")
    parser.add_argument("--max-variants", type=int, default=18)
    parser.add_argument("--min-market-cap-usd", type=float, default=1_000_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=20_000_000.0)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--allow-unfillable-targets", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload.get("status"), "cagr": payload.get("cagr"), "max_dd": payload.get("max_dd")}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
