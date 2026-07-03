#!/usr/bin/env python3
"""Research-only fixed-book broker counterfactual for missed Concentrated leaders.

The challenger swaps a PIT-filtered cap/replacement missed leader into an
existing non-cash Concentrated slot at the donor slot's weight. Cash weight and
total exposure are therefore preserved; forward returns are copied only into the
audit table and never used for ranking or target-book construction.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_TICKERS,
    replay,
    resolve_cash_carry_config,
)

DEFAULT_OUTPUT_DIR = "outputs/concentrated_cap_replacement_broker_counterfactual"
DEFAULT_ARMS = (
    "rank_top15,"
    "rs3_ge20,"
    "rs3_ge30,"
    "rank_top15_or_rs3_ge20,"
    "rank_top15_and_revenue_ge10,"
    "rs3_ge20_and_revenue_ge10,"
    "rs3_ge30_and_revenue_ge10"
)
PIT_RULE_COLUMNS = ("leader_rank_ex_ante", "rs_spy_3m", "revenue_growth")
FORWARD_LABEL_COLUMNS = ("forward_21d_excess", "forward_63d_excess", "forward_126d_excess")


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def metrics_cash_carry_mode(metrics: dict[str, Any]) -> str:
    mode = str(metrics.get("cash_carry_mode") or CASH_CARRY_MODE_NONE).strip().lower()
    return mode or CASH_CARRY_MODE_NONE


def truthy_series(frame: pd.DataFrame, col: str, default: bool) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index)
    return frame[col].astype(str).str.lower().isin({"true", "1", "yes", "y"})


def falsy_series(frame: pd.DataFrame, col: str, default: bool) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index)
    return ~frame[col].astype(str).str.lower().isin({"true", "1", "yes", "y"})


def normalize_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def arm_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_").lower()


def era_for_date(value: Any) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return "unknown"
    year = int(pd.Timestamp(dt).year)
    if year <= 2020:
        return "2019-2020"
    if year <= 2022:
        return "2021-2022"
    if year <= 2024:
        return "2023-2024"
    return "2025-2026"


def parse_arms(text: str) -> list[str]:
    out: list[str] = []
    for token in str(text or "").split(","):
        name = token.strip()
        if name and name not in out:
            out.append(name)
    return out


def prepare_missed(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    out = frame.copy()
    for col in (*PIT_RULE_COLUMNS, *FORWARD_LABEL_COLUMNS, "liquidity_score"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("portfolio", "rejection_reason", "ticker", "rebalance_date", "theme", "sector", "subindustry", "lane"):
        if col not in out.columns:
            out[col] = ""
    out["ticker"] = out["ticker"].map(normalize_ticker)
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    valid = (
        out["portfolio"].astype(str).eq("concentrated")
        & out["rejection_reason"].astype(str).eq("cap_or_replacement")
        & out["ticker"].ne("")
        & falsy_series(out, "used_forward_return_in_ranking", True)
        & truthy_series(out, "historical_valid", True)
        & truthy_series(out, "ex_ante_source_valid", True)
        & truthy_series(out, "missed_leader_historical_audit_allowed", True)
    )
    return out[valid].copy()


def rule_mask(frame: pd.DataFrame, rule: str) -> pd.Series:
    rank = pd.to_numeric(frame.get("leader_rank_ex_ante"), errors="coerce")
    rs3 = pd.to_numeric(frame.get("rs_spy_3m"), errors="coerce")
    rev = pd.to_numeric(frame.get("revenue_growth"), errors="coerce")
    rules: dict[str, pd.Series] = {
        "rank_top15": rank <= 15,
        "rs3_ge20": rs3 >= 0.20,
        "rs3_ge30": rs3 >= 0.30,
        "rank_top15_or_rs3_ge20": (rank <= 15) | (rs3 >= 0.20),
        "rank_top15_or_rs3_ge30": (rank <= 15) | (rs3 >= 0.30),
        "rank_top15_and_rs3_ge20": (rank <= 15) & (rs3 >= 0.20),
        "rank_top15_and_rs3_ge30": (rank <= 15) & (rs3 >= 0.30),
        "rank_top15_and_revenue_ge10": (rank <= 15) & (rev >= 0.10),
        "rs3_ge20_and_revenue_ge10": (rs3 >= 0.20) & (rev >= 0.10),
        "rs3_ge30_and_revenue_ge10": (rs3 >= 0.30) & (rev >= 0.10),
    }
    if rule not in rules:
        raise ValueError(f"unknown arm rule: {rule}")
    return rules[rule].fillna(False)


def sort_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    rank = out["leader_rank_ex_ante"] if "leader_rank_ex_ante" in out.columns else pd.Series(index=out.index, dtype=float)
    rs3 = out["rs_spy_3m"] if "rs_spy_3m" in out.columns else pd.Series(index=out.index, dtype=float)
    rev = out["revenue_growth"] if "revenue_growth" in out.columns else pd.Series(index=out.index, dtype=float)
    liq = out["liquidity_score"] if "liquidity_score" in out.columns else pd.Series(index=out.index, dtype=float)
    out["_rank_sort"] = pd.to_numeric(rank, errors="coerce").fillna(999999.0)
    out["_rs3_sort"] = pd.to_numeric(rs3, errors="coerce").fillna(-999999.0)
    out["_rev_sort"] = pd.to_numeric(rev, errors="coerce").fillna(-999999.0)
    out["_liq_sort"] = pd.to_numeric(liq, errors="coerce").fillna(-999999.0)
    return out.sort_values(
        ["_rank_sort", "_rs3_sort", "_rev_sort", "_liq_sort", "ticker"],
        ascending=[True, False, False, False, True],
    )


def donor_sort_key(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    score_cols = ["alphaops_vnext_score", "weighting_score", "concentrated_score", "score"]
    score = pd.Series(0.0, index=out.index)
    for col in score_cols:
        if col in out.columns:
            score = pd.to_numeric(out[col], errors="coerce")
            break
    out["_donor_score_sort"] = score.fillna(0.0)
    weight = out["weight"] if "weight" in out.columns else pd.Series(index=out.index, dtype=float)
    out["_donor_weight_sort"] = pd.to_numeric(weight, errors="coerce").fillna(0.0)
    return out.sort_values(["_donor_score_sort", "_donor_weight_sort", "ticker"], ascending=[True, True, True])


def copy_candidate_fields(target_row: pd.Series, candidate: pd.Series, *, rule: str, donor_ticker: str) -> pd.Series:
    row = target_row.copy()
    field_map = {
        "ticker": "ticker",
        "Name": "Name",
        "theme": "theme",
        "sector": "sector",
        "subindustry": "subindustry",
        "portfolio_sleeve_label": "lane",
        "primary_lane": "lane",
        "leader_rank_ex_ante": "leader_rank_ex_ante",
        "rs_spy_3m": "rs_spy_3m",
        "revenue_growth": "revenue_growth",
        "liquidity_score": "liquidity_score",
    }
    for target_col, source_col in field_map.items():
        if target_col in row.index and source_col in candidate.index and str(candidate.get(source_col, "")) != "":
            row[target_col] = candidate.get(source_col)
    row["ticker"] = normalize_ticker(candidate.get("ticker"))
    if "selection_reason" in row.index:
        base_reason = str(row.get("selection_reason") or "")
        row["selection_reason"] = (
            f"{base_reason}|research_only_cap_replacement_counterfactual:{rule}:replaced_{donor_ticker}"
        ).strip("|")
    if "production_policy" in row.index:
        row["production_policy"] = "research_only_counterfactual"
    if "operating_target_source" in row.index:
        row["operating_target_source"] = "fixed_book_cap_replacement_counterfactual"
    return row


def exposure_by_date(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.date.astype(str)
    d["ticker"] = d["ticker"].map(normalize_ticker)
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    rows: list[dict[str, Any]] = []
    for dt, day in d.groupby("rebalance_date", dropna=False):
        stock = day[~day["ticker"].isin(CASH_TICKERS)]
        cash = day[day["ticker"].isin(CASH_TICKERS)]
        rows.append(
            {
                "rebalance_date": dt,
                "stock_weight": float(stock["weight"].sum()),
                "cash_weight": float(cash["weight"].sum()),
                "total_weight": float(day["weight"].sum()),
                "max_single_stock_weight": float(stock["weight"].max()) if not stock.empty else 0.0,
            }
        )
    return pd.DataFrame(rows)


def portfolio_concentration_metrics(replay_dir: Path) -> dict[str, Any]:
    """Summarize broker-held stock concentration from holdings_daily.csv."""

    holdings_path = replay_dir / "holdings_daily.csv"
    empty = {
        "status": "missing_holdings",
        "avg_stock_hhi": 0.0,
        "max_stock_hhi": 0.0,
        "latest_stock_hhi": 0.0,
        "avg_top1_weight": 0.0,
        "max_top1_weight": 0.0,
        "latest_top1_weight": 0.0,
        "avg_top3_weight": 0.0,
        "max_top3_weight": 0.0,
        "latest_top3_weight": 0.0,
        "avg_top5_weight": 0.0,
        "max_top5_weight": 0.0,
        "latest_top5_weight": 0.0,
        "avg_position_count": 0.0,
        "min_position_count": 0,
        "latest_position_count": 0,
        "latest_top_ticker": "",
        "latest_top_ticker_weight": 0.0,
        "latest_stock_gross_weight": 0.0,
        "latest_cash_or_uninvested_weight": 0.0,
    }
    if not holdings_path.exists():
        return empty
    raw = pd.read_csv(holdings_path)
    if raw.empty or not {"date", "ticker", "weight"}.issubset(raw.columns):
        return empty

    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"])
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
    frame = frame.loc[(frame["weight"] > 0.0) & ~frame["ticker"].isin(CASH_TICKERS)].copy()
    if frame.empty:
        return {**empty, "status": "empty_after_filters"}

    rows: list[dict[str, Any]] = []
    for dt, day in frame.groupby("date", sort=True):
        weights = sorted((float(x) for x in day["weight"].tolist() if float(x) > 0.0), reverse=True)
        if not weights:
            continue
        stock_gross = float(sum(weights))
        normalized = [weight / stock_gross for weight in weights] if stock_gross > 0.0 else []
        top = day.sort_values("weight", ascending=False).iloc[0]
        rows.append(
            {
                "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                "stock_gross_weight": stock_gross,
                "stock_hhi": float(sum(weight * weight for weight in normalized)),
                "top1_weight": float(sum(weights[:1])),
                "top3_weight": float(sum(weights[:3])),
                "top5_weight": float(sum(weights[:5])),
                "position_count": int(len(weights)),
                "top_ticker": str(top["ticker"]),
                "top_ticker_weight": float(top["weight"]),
                "cash_or_uninvested_weight": float(max(0.0, 1.0 - stock_gross)),
            }
        )
    if not rows:
        return {**empty, "status": "empty_daily_rows"}
    daily = pd.DataFrame(rows)
    latest = daily.sort_values("date").iloc[-1]
    return {
        "status": "completed",
        "avg_stock_hhi": float(daily["stock_hhi"].mean()),
        "max_stock_hhi": float(daily["stock_hhi"].max()),
        "latest_stock_hhi": float(latest["stock_hhi"]),
        "avg_top1_weight": float(daily["top1_weight"].mean()),
        "max_top1_weight": float(daily["top1_weight"].max()),
        "latest_top1_weight": float(latest["top1_weight"]),
        "avg_top3_weight": float(daily["top3_weight"].mean()),
        "max_top3_weight": float(daily["top3_weight"].max()),
        "latest_top3_weight": float(latest["top3_weight"]),
        "avg_top5_weight": float(daily["top5_weight"].mean()),
        "max_top5_weight": float(daily["top5_weight"].max()),
        "latest_top5_weight": float(latest["top5_weight"]),
        "avg_position_count": float(daily["position_count"].mean()),
        "min_position_count": int(daily["position_count"].min()),
        "latest_position_count": int(latest["position_count"]),
        "latest_top_ticker": str(latest["top_ticker"]),
        "latest_top_ticker_weight": float(latest["top_ticker_weight"]),
        "latest_stock_gross_weight": float(latest["stock_gross_weight"]),
        "latest_cash_or_uninvested_weight": float(latest["cash_or_uninvested_weight"]),
    }


def portfolio_concentration_delta(
    baseline: dict[str, Any],
    challenger: dict[str, Any],
    *,
    top1_delta_warning: float = 0.05,
    top3_delta_warning: float = 0.10,
    hhi_delta_warning: float = 0.05,
    absolute_top1_warning: float = 0.40,
    absolute_top1_block: float = 0.45,
    absolute_top3_warning: float = 0.85,
    absolute_top3_severe_warning: float = 0.90,
) -> dict[str, Any]:
    deltas = {
        "latest_top1_delta": safe_float(challenger.get("latest_top1_weight")) - safe_float(baseline.get("latest_top1_weight")),
        "latest_top3_delta": safe_float(challenger.get("latest_top3_weight")) - safe_float(baseline.get("latest_top3_weight")),
        "latest_top5_delta": safe_float(challenger.get("latest_top5_weight")) - safe_float(baseline.get("latest_top5_weight")),
        "latest_stock_hhi_delta": safe_float(challenger.get("latest_stock_hhi")) - safe_float(baseline.get("latest_stock_hhi")),
        "latest_stock_gross_delta": safe_float(challenger.get("latest_stock_gross_weight")) - safe_float(baseline.get("latest_stock_gross_weight")),
        "latest_position_count_delta": safe_float(challenger.get("latest_position_count")) - safe_float(baseline.get("latest_position_count")),
        "latest_top_ticker_changed": bool(
            str(challenger.get("latest_top_ticker") or "") != str(baseline.get("latest_top_ticker") or "")
        ),
    }
    latest_top1 = safe_float(challenger.get("latest_top1_weight"))
    latest_top3 = safe_float(challenger.get("latest_top3_weight"))
    warning_reasons: list[str] = []
    severe_warning_reasons: list[str] = []
    if deltas["latest_top1_delta"] > top1_delta_warning:
        warning_reasons.append("top1_delta")
    if deltas["latest_top3_delta"] > top3_delta_warning:
        warning_reasons.append("top3_delta")
    if deltas["latest_stock_hhi_delta"] > hhi_delta_warning:
        warning_reasons.append("hhi_delta")
    if latest_top1 > absolute_top1_warning:
        warning_reasons.append("absolute_top1_warning")
    if latest_top3 > absolute_top3_warning:
        warning_reasons.append("absolute_top3_warning")
    if latest_top3 > absolute_top3_severe_warning:
        severe_warning_reasons.append("absolute_top3_severe_warning")
    block_reasons: list[str] = []
    if latest_top1 > absolute_top1_block:
        block_reasons.append("absolute_top1_block")
    return {
        **deltas,
        "portfolio_concentration_warning": bool(warning_reasons),
        "portfolio_concentration_warning_reasons": warning_reasons,
        "portfolio_concentration_severe_warning": bool(severe_warning_reasons),
        "portfolio_concentration_severe_warning_reasons": severe_warning_reasons,
        "portfolio_concentration_block": bool(block_reasons),
        "portfolio_concentration_block_reasons": block_reasons,
        "concentration_thresholds": {
            "top1_delta_warning": top1_delta_warning,
            "top3_delta_warning": top3_delta_warning,
            "hhi_delta_warning": hhi_delta_warning,
            "absolute_top1_warning": absolute_top1_warning,
            "absolute_top1_block": absolute_top1_block,
            "absolute_top3_warning": absolute_top3_warning,
            "absolute_top3_severe_warning": absolute_top3_severe_warning,
        },
    }


def build_counterfactual_book(
    *,
    base_book: pd.DataFrame,
    missed: pd.DataFrame,
    rule: str,
    max_swaps_per_date: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    book = base_book.copy()
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)
    book["ticker"] = book["ticker"].map(normalize_ticker)
    book["weight"] = pd.to_numeric(book["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in book.columns:
        book["target_weight"] = pd.to_numeric(book["target_weight"], errors="coerce").fillna(book["weight"])

    candidates = missed[rule_mask(missed, rule)].copy()
    candidates = sort_candidates(candidates)
    rebuilt: list[pd.DataFrame] = []
    swaps: list[dict[str, Any]] = []
    skipped_no_slot = 0
    skipped_already_held = 0

    for dt, day in book.groupby("rebalance_date", sort=True):
        day_out = day.copy()
        day_candidates = candidates[candidates["rebalance_date"].eq(str(dt))].copy()
        if day_candidates.empty:
            rebuilt.append(day_out)
            continue
        held = set(day_out["ticker"].map(normalize_ticker))
        usable = day_candidates[~day_candidates["ticker"].isin(held)].copy()
        skipped_already_held += int(len(day_candidates) - len(usable))
        if usable.empty:
            rebuilt.append(day_out)
            continue
        donor_pool = day_out[~day_out["ticker"].isin(CASH_TICKERS)].copy()
        if donor_pool.empty:
            skipped_no_slot += int(len(usable))
            rebuilt.append(day_out)
            continue
        swaps_done = 0
        for _, candidate in usable.iterrows():
            if swaps_done >= max_swaps_per_date:
                break
            current_tickers = set(day_out["ticker"].map(normalize_ticker))
            if normalize_ticker(candidate.get("ticker")) in current_tickers:
                skipped_already_held += 1
                continue
            donor_pool = day_out[~day_out["ticker"].isin(CASH_TICKERS)].copy()
            donor_pool = donor_pool[~donor_pool["ticker"].map(normalize_ticker).eq(normalize_ticker(candidate.get("ticker")))]
            if donor_pool.empty:
                skipped_no_slot += 1
                continue
            donor = donor_sort_key(donor_pool).iloc[0]
            donor_idx = donor.name
            donor_ticker = normalize_ticker(donor.get("ticker"))
            donor_weight = safe_float(donor.get("weight"))
            new_row = copy_candidate_fields(day_out.loc[donor_idx], candidate, rule=rule, donor_ticker=donor_ticker)
            new_row["weight"] = donor_weight
            if "target_weight" in new_row.index:
                new_row["target_weight"] = donor_weight
            day_out.loc[donor_idx] = new_row
            swaps_done += 1
            audit = {
                "rule": rule,
                "rebalance_date": str(dt),
                "era": era_for_date(dt),
                "added_ticker": normalize_ticker(candidate.get("ticker")),
                "removed_ticker": donor_ticker,
                "replacement_weight": donor_weight,
                "leader_rank_ex_ante": candidate.get("leader_rank_ex_ante", ""),
                "rs_spy_3m": candidate.get("rs_spy_3m", ""),
                "revenue_growth": candidate.get("revenue_growth", ""),
                "theme": candidate.get("theme", ""),
                "sector": candidate.get("sector", ""),
                "forward_return_is_audit_label_only": True,
                "forward_labels_used_for_ranking": False,
            }
            for col in FORWARD_LABEL_COLUMNS:
                audit[col] = candidate.get(col, "")
            swaps.append(audit)
        rebuilt.append(day_out)

    result = pd.concat(rebuilt, ignore_index=True) if rebuilt else book
    result = result.sort_values(["rebalance_date", "weight", "ticker"], ascending=[True, False, True]).reset_index(drop=True)
    swap_df = pd.DataFrame(swaps)

    base_exp = exposure_by_date(book)
    chal_exp = exposure_by_date(result)
    merged = base_exp.merge(chal_exp, on="rebalance_date", suffixes=("_base", "_challenger"))
    for col in ("stock_weight", "cash_weight", "total_weight", "max_single_stock_weight"):
        merged[f"{col}_delta"] = merged[f"{col}_challenger"] - merged[f"{col}_base"]
    diagnostics = {
        "swap_count": int(len(swap_df)),
        "eligible_candidate_rows": int(len(candidates)),
        "skipped_already_held": int(skipped_already_held),
        "skipped_no_slot": int(skipped_no_slot),
        "cash_weight_max_abs_delta": float(merged["cash_weight_delta"].abs().max()) if not merged.empty else 0.0,
        "stock_weight_max_abs_delta": float(merged["stock_weight_delta"].abs().max()) if not merged.empty else 0.0,
        "total_weight_max_abs_delta": float(merged["total_weight_delta"].abs().max()) if not merged.empty else 0.0,
        "max_single_stock_weight_delta_max": float(merged["max_single_stock_weight_delta"].max()) if not merged.empty else 0.0,
        "cap_breach": bool((merged["total_weight_challenger"] > 1.050000001).any()) if not merged.empty else False,
        "broad_cash_reduction": bool((merged["cash_weight_delta"] < -1e-9).any()) if not merged.empty else False,
    }
    return result, swap_df, diagnostics


def concentration(
    swaps: pd.DataFrame,
    *,
    top_added_ticker_warning: float = 0.35,
    top_added_ticker_block: float = 0.50,
    top_era_warning: float = 0.65,
    top_era_block: float = 0.70,
    top_year_block: float = 0.70,
) -> dict[str, Any]:
    if swaps.empty:
        return {
            "swap_count": 0,
            "unique_added_ticker_count": 0,
            "top_added_ticker": "",
            "top_added_ticker_share": 0.0,
            "top_era": "",
            "top_era_share": 0.0,
            "top_year": "",
            "top_year_share": 0.0,
            "ticker_counts": {},
            "era_counts": {},
            "year_counts": {},
            "concentration_warning": False,
            "concentration_warning_reasons": [],
            "concentration_block": False,
            "concentration_block_reasons": [],
        }
    ticker_counts = Counter(swaps["added_ticker"].astype(str))
    era_counts = Counter(swaps["era"].astype(str))
    years = pd.to_datetime(swaps["rebalance_date"], errors="coerce").dt.year.astype("Int64").astype(str)
    year_counts = Counter(years[~years.eq("<NA>")])
    top_ticker, top_ticker_count = ticker_counts.most_common(1)[0]
    top_era, top_era_count = era_counts.most_common(1)[0]
    top_year, top_year_count = year_counts.most_common(1)[0] if year_counts else ("", 0)
    n = len(swaps)
    top_ticker_share = top_ticker_count / n
    top_era_share = top_era_count / n
    top_year_share = top_year_count / n if n else 0.0
    warning_reasons: list[str] = []
    block_reasons: list[str] = []
    if top_ticker_share > top_added_ticker_warning:
        warning_reasons.append("top_added_ticker_share")
    if top_era_share > top_era_warning:
        warning_reasons.append("top_era_share")
    if top_ticker_share > top_added_ticker_block:
        block_reasons.append("top_added_ticker_share")
    if top_era_share > top_era_block:
        block_reasons.append("top_era_share")
    if top_year_share > top_year_block:
        block_reasons.append("top_year_share")
    return {
        "swap_count": int(n),
        "unique_added_ticker_count": int(len(ticker_counts)),
        "top_added_ticker": top_ticker,
        "top_added_ticker_share": float(top_ticker_share),
        "top_era": top_era,
        "top_era_share": float(top_era_share),
        "top_year": top_year,
        "top_year_share": float(top_year_share),
        "ticker_counts": dict(ticker_counts.most_common(12)),
        "era_counts": dict(era_counts.most_common()),
        "year_counts": dict(year_counts.most_common()),
        "concentration_warning": bool(warning_reasons),
        "concentration_warning_reasons": warning_reasons,
        "concentration_block": bool(block_reasons),
        "concentration_block_reasons": block_reasons,
        "concentration_thresholds": {
            "top_added_ticker_warning": top_added_ticker_warning,
            "top_added_ticker_block": top_added_ticker_block,
            "top_era_warning": top_era_warning,
            "top_era_block": top_era_block,
            "top_year_block": top_year_block,
        },
    }


def window_deltas(baseline: dict[str, Any], challenger: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    base_windows = baseline.get("windows") if isinstance(baseline.get("windows"), dict) else {}
    challenger_windows = challenger.get("windows") if isinstance(challenger.get("windows"), dict) else {}
    for label in ("full", "is", "oos", "oos2"):
        b = base_windows.get(label) if label != "full" else (base_windows.get("full") or baseline)
        c = challenger_windows.get(label) if label != "full" else (challenger_windows.get("full") or challenger)
        if not isinstance(b, dict) or not isinstance(c, dict) or b.get("status") != "completed" or c.get("status") != "completed":
            out[label] = {"status": "missing_or_incomplete"}
            continue
        out[label] = {
            "status": "completed",
            "baseline_cagr": b.get("cagr"),
            "challenger_cagr": c.get("cagr"),
            "delta_cagr": safe_float(c.get("cagr")) - safe_float(b.get("cagr")),
            "baseline_max_dd": b.get("max_dd"),
            "challenger_max_dd": c.get("max_dd"),
            "delta_max_dd": safe_float(c.get("max_dd")) - safe_float(b.get("max_dd")),
            "baseline_sharpe": b.get("sharpe"),
            "challenger_sharpe": c.get("sharpe"),
            "delta_sharpe": safe_float(c.get("sharpe")) - safe_float(b.get("sharpe")),
        }
    return out


def flatten_arm_row(arm: dict[str, Any]) -> dict[str, Any]:
    portfolio_conc = arm.get("portfolio_concentration") or {}
    portfolio_delta = arm.get("portfolio_concentration_delta") or {}
    row = {
        "rule": arm.get("rule"),
        "status": arm.get("status"),
        "swap_count": arm.get("swap_count"),
        "eligible_candidate_rows": arm.get("eligible_candidate_rows"),
        "cap_breach": arm.get("cap_breach"),
        "broad_cash_reduction": arm.get("broad_cash_reduction"),
        "top_added_ticker": (arm.get("concentration") or {}).get("top_added_ticker"),
        "top_added_ticker_share": (arm.get("concentration") or {}).get("top_added_ticker_share"),
        "top_era": (arm.get("concentration") or {}).get("top_era"),
        "top_era_share": (arm.get("concentration") or {}).get("top_era_share"),
        "top_year": (arm.get("concentration") or {}).get("top_year"),
        "top_year_share": (arm.get("concentration") or {}).get("top_year_share"),
        "gain_concentration_warning": (arm.get("concentration") or {}).get("concentration_warning"),
        "gain_concentration_block": (arm.get("concentration") or {}).get("concentration_block"),
        "gain_concentration_warning_reasons": ",".join((arm.get("concentration") or {}).get("concentration_warning_reasons") or []),
        "gain_concentration_block_reasons": ",".join((arm.get("concentration") or {}).get("concentration_block_reasons") or []),
        "latest_top_ticker": portfolio_conc.get("latest_top_ticker"),
        "latest_top1_weight": portfolio_conc.get("latest_top1_weight"),
        "latest_top3_weight": portfolio_conc.get("latest_top3_weight"),
        "latest_top5_weight": portfolio_conc.get("latest_top5_weight"),
        "latest_stock_hhi": portfolio_conc.get("latest_stock_hhi"),
        "latest_position_count": portfolio_conc.get("latest_position_count"),
        "latest_stock_gross_weight": portfolio_conc.get("latest_stock_gross_weight"),
        "latest_top1_delta": portfolio_delta.get("latest_top1_delta"),
        "latest_top3_delta": portfolio_delta.get("latest_top3_delta"),
        "latest_top5_delta": portfolio_delta.get("latest_top5_delta"),
        "latest_stock_hhi_delta": portfolio_delta.get("latest_stock_hhi_delta"),
        "portfolio_concentration_warning": portfolio_delta.get("portfolio_concentration_warning"),
        "portfolio_concentration_block": portfolio_delta.get("portfolio_concentration_block"),
        "portfolio_concentration_warning_reasons": ",".join(portfolio_delta.get("portfolio_concentration_warning_reasons") or []),
        "portfolio_concentration_severe_warning": portfolio_delta.get("portfolio_concentration_severe_warning"),
        "portfolio_concentration_severe_warning_reasons": ",".join(portfolio_delta.get("portfolio_concentration_severe_warning_reasons") or []),
        "portfolio_concentration_block_reasons": ",".join(portfolio_delta.get("portfolio_concentration_block_reasons") or []),
    }
    for label, delta in (arm.get("metric_deltas") or {}).items():
        if isinstance(delta, dict):
            row[f"{label}_delta_cagr"] = delta.get("delta_cagr")
            row[f"{label}_delta_max_dd"] = delta.get("delta_max_dd")
            row[f"{label}_delta_sharpe"] = delta.get("delta_sharpe")
            row[f"{label}_challenger_cagr"] = delta.get("challenger_cagr")
            row[f"{label}_challenger_max_dd"] = delta.get("challenger_max_dd")
    return row


def pct(value: Any) -> str:
    try:
        return f"{float(value):.2%}"
    except (TypeError, ValueError):
        return ""


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Concentrated Cap/Replacement Broker Counterfactual",
        "",
        f"- status: `{payload.get('status')}`",
        f"- source doc: `{payload.get('source_doc')}`",
        f"- target book: `{payload.get('target_book')}`",
        f"- missed leaders: `{payload.get('missed_leaders')}`",
        f"- cash-carry mode: `{payload.get('cash_carry_mode')}`",
        f"- baseline cash-carry comparable: `{payload.get('baseline_cash_carry_comparable')}`",
        "- research only: `true`",
        "- production mutation allowed: `false`",
        "- fullrun executed: `false`",
        "- broad cash reduction allowed: `false`",
        "- forward returns used for ranking: `false`",
        "",
        "The challenger swaps PIT-filtered missed leaders into existing non-cash slots at the donor slot weight, preserving cash and total exposure.",
        "",
        "## Broker-Ledger Deltas",
        "",
        "| rule | swaps | full CAGR delta | full MDD delta | IS CAGR delta | OOS CAGR delta | top ticker share | top era share | top year share | warning | block |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for arm in payload.get("arms", []):
        deltas = arm.get("metric_deltas") or {}
        full = deltas.get("full") or {}
        is_ = deltas.get("is") or {}
        oos = deltas.get("oos") or {}
        conc = arm.get("concentration") or {}
        warning = ",".join(conc.get("concentration_warning_reasons") or []) if conc.get("concentration_warning") else ""
        block = ",".join(conc.get("concentration_block_reasons") or []) if conc.get("concentration_block") else ""
        lines.append(
            f"| {arm.get('rule')} | {arm.get('swap_count')} | {pct(full.get('delta_cagr'))} | "
            f"{pct(full.get('delta_max_dd'))} | {pct(is_.get('delta_cagr'))} | {pct(oos.get('delta_cagr'))} | "
            f"{pct(conc.get('top_added_ticker_share'))} | {pct(conc.get('top_era_share'))} | "
            f"{pct(conc.get('top_year_share'))} | {warning} | {block} |"
        )
    lines += [
        "",
        "## Portfolio Concentration",
        "",
        "This table is measured from broker `holdings_daily.csv`. CASH is excluded from stock-book HHI, while top weights are raw account weights.",
        "",
        "| rule | latest top | top1 | top3 | top5 | stock HHI | stock gross | top1 delta | HHI delta | warning | block |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for arm in payload.get("arms", []):
        conc = arm.get("portfolio_concentration") or {}
        delta = arm.get("portfolio_concentration_delta") or {}
        if conc.get("status") != "completed":
            continue
        warning_reasons = list(delta.get("portfolio_concentration_warning_reasons") or [])
        warning_reasons.extend(delta.get("portfolio_concentration_severe_warning_reasons") or [])
        warning = ",".join(warning_reasons) if warning_reasons else ""
        block = ",".join(delta.get("portfolio_concentration_block_reasons") or []) if delta.get("portfolio_concentration_block") else ""
        lines.append(
            f"| {arm.get('rule')} | {conc.get('latest_top_ticker', '')} | "
            f"{pct(conc.get('latest_top1_weight'))} | {pct(conc.get('latest_top3_weight'))} | "
            f"{pct(conc.get('latest_top5_weight'))} | {safe_float(conc.get('latest_stock_hhi')):.4f} | "
            f"{pct(conc.get('latest_stock_gross_weight'))} | {pct(delta.get('latest_top1_delta'))} | "
            f"{safe_float(delta.get('latest_stock_hhi_delta')):.4f} | {warning} | {block} |"
        )
    lines += [
        "",
        "## Interpretation Guardrails",
        "",
        "- This is not a production hook and does not mutate operating books.",
        "- Deltas are valid only when `baseline_cash_carry_comparable=true`.",
        "- Forward returns remain audit labels only.",
        "- Any arm that works only through one ticker or one era needs a separate robustness review before becoming a policy candidate.",
        "- A positive audit result still requires governance review before any policy hook or fullrun.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_book = repo_path(args.target_book)
    missed_path = repo_path(args.missed_leaders)
    price_cache = repo_path(args.price_cache)
    baseline_metrics_path = repo_path(args.baseline_metrics)
    source_doc = repo_path(args.source_doc)

    base_book = pd.read_csv(target_book)
    missed = prepare_missed(missed_path)
    baseline_metrics = read_json(baseline_metrics_path)
    baseline_replay_dir = baseline_metrics_path.parent
    baseline_portfolio_concentration = portfolio_concentration_metrics(baseline_replay_dir)
    replay_end_date = args.replay_end_date or baseline_metrics.get("end_date") or ""
    cash_carry_config = resolve_cash_carry_config(
        mode=args.cash_carry_mode,
        rate_source=args.cash_rate_source,
        rate_path=args.cash_rate_path,
        rate_lag_days=args.cash_rate_lag_days,
        haircut_bps=args.cash_carry_haircut_bps,
        day_count=args.cash_carry_day_count,
    )
    baseline_carry_mode = metrics_cash_carry_mode(baseline_metrics)
    baseline_cash_carry_comparable = baseline_carry_mode == cash_carry_config.mode

    arms: list[dict[str, Any]] = []
    for rule in parse_arms(args.arms):
        slug = arm_slug(rule)
        arm_dir = output_dir / slug
        arm_dir.mkdir(parents=True, exist_ok=True)
        challenger_book, swaps, diagnostics = build_counterfactual_book(
            base_book=base_book,
            missed=missed,
            rule=rule,
            max_swaps_per_date=max(1, int(args.max_swaps_per_date)),
        )
        challenger_book_path = arm_dir / "target_book.csv"
        swaps_path = arm_dir / "swaps.csv"
        challenger_book.to_csv(challenger_book_path, index=False)
        swaps.to_csv(swaps_path, index=False)
        broker_metrics: dict[str, Any] = {"status": "skipped", "reason": "no_swaps"}
        if not swaps.empty:
            broker_metrics = replay(
                target_book=challenger_book_path,
                price_cache=price_cache,
                output_dir=arm_dir / "broker_replay",
                portfolio_kind="concentrated",
                starting_capital=float(args.starting_capital),
                fill_mode="next_close",
                cost_bps=float(args.cost_bps),
                integer_shares=not bool(args.fractional_shares),
                max_fill_lag_days=int(args.max_fill_lag_days),
                disable_concentrated_champion_filter=True,
                max_reasonable_weight_sum=float(args.max_reasonable_weight_sum),
                oos_start=args.oos_start or None,
                oos_end=args.oos_end or None,
                oos2_start=args.oos2_start or None,
                oos2_end=args.oos2_end or None,
                replay_end_date=replay_end_date or None,
                official_baseline_end_date=baseline_metrics.get("end_date") or replay_end_date or None,
                cash_carry_config=cash_carry_config,
            )
        challenger_portfolio_concentration = portfolio_concentration_metrics(arm_dir / "broker_replay")
        challenger_portfolio_concentration_delta = portfolio_concentration_delta(
            baseline_portfolio_concentration,
            challenger_portfolio_concentration,
            top1_delta_warning=float(getattr(args, "concentration_top1_delta_warning", 0.05)),
            top3_delta_warning=float(getattr(args, "concentration_top3_delta_warning", 0.10)),
            hhi_delta_warning=float(getattr(args, "concentration_hhi_delta_warning", 0.05)),
            absolute_top1_warning=float(getattr(args, "concentration_absolute_top1_warning", 0.40)),
            absolute_top1_block=float(getattr(args, "concentration_absolute_top1_block", 0.45)),
            absolute_top3_warning=float(getattr(args, "concentration_absolute_top3_warning", 0.85)),
            absolute_top3_severe_warning=float(getattr(args, "concentration_absolute_top3_severe_warning", 0.90)),
        )
        arm = {
            "rule": rule,
            "status": broker_metrics.get("status"),
            "target_book": str(challenger_book_path),
            "swaps_csv": str(swaps_path),
            "broker_metrics": str(arm_dir / "broker_replay" / "metrics.json"),
            "metric_deltas": window_deltas(baseline_metrics, broker_metrics),
            "concentration": concentration(
                swaps,
                top_added_ticker_warning=float(getattr(args, "gain_top_added_ticker_warning", 0.35)),
                top_added_ticker_block=float(getattr(args, "gain_top_added_ticker_block", 0.50)),
                top_era_warning=float(getattr(args, "gain_top_era_warning", 0.65)),
                top_era_block=float(getattr(args, "gain_top_era_block", 0.70)),
                top_year_block=float(getattr(args, "gain_top_year_block", 0.70)),
            ),
            "portfolio_concentration": challenger_portfolio_concentration,
            "portfolio_concentration_delta": challenger_portfolio_concentration_delta,
            "forward_return_is_audit_label_only": True,
            "forward_labels_used_for_ranking": False,
            "production_activation_allowed": False,
            "policy_mutation_allowed": False,
            "live_trading_enabled": False,
            **diagnostics,
        }
        arms.append(arm)

    flat = pd.DataFrame([flatten_arm_row(arm) for arm in arms])
    flat.to_csv(output_dir / "arm_metrics.csv", index=False)
    payload = {
        "schema_version": "concentrated-cap-replacement-broker-counterfactual-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_doc": str(source_doc),
        "target_book": str(target_book),
        "missed_leaders": str(missed_path),
        "price_cache": str(price_cache),
        "baseline_metrics": str(baseline_metrics_path),
        "baseline_replay_dir": str(baseline_replay_dir),
        "baseline_portfolio_concentration": baseline_portfolio_concentration,
        "baseline_metric_mode": str(baseline_metrics.get("metric_mode") or ""),
        "baseline_cash_carry_mode": baseline_carry_mode,
        "baseline_cash_carry_comparable": bool(baseline_cash_carry_comparable),
        "replay_end_date": replay_end_date,
        "arms_requested": parse_arms(args.arms),
        "research_only": True,
        "fullrun_executed": False,
        "production_mutation_allowed": False,
        "production_activation_allowed": False,
        "policy_mutation_allowed": False,
        "live_trading_enabled": False,
        "broad_cash_reduction_allowed": False,
        "cap_breach_allowed": False,
        "cash_carry_mode": cash_carry_config.mode,
        "cash_rate_source": cash_carry_config.rate_source,
        "cash_rate_path": str(cash_carry_config.rate_path) if cash_carry_config.rate_path else "",
        "cash_rate_lag_days": int(cash_carry_config.rate_lag_days),
        "cash_carry_haircut_bps": float(cash_carry_config.haircut_bps),
        "cash_carry_day_count": int(cash_carry_config.day_count),
        "forward_return_is_audit_label_only": True,
        "forward_labels_used_for_ranking": False,
        "pit_filter_columns": list(PIT_RULE_COLUMNS),
        "concentration_guard_config": {
            "top1_delta_warning": float(getattr(args, "concentration_top1_delta_warning", 0.05)),
            "top3_delta_warning": float(getattr(args, "concentration_top3_delta_warning", 0.10)),
            "hhi_delta_warning": float(getattr(args, "concentration_hhi_delta_warning", 0.05)),
            "absolute_top1_warning": float(getattr(args, "concentration_absolute_top1_warning", 0.40)),
            "absolute_top1_block": float(getattr(args, "concentration_absolute_top1_block", 0.45)),
            "absolute_top3_warning": float(getattr(args, "concentration_absolute_top3_warning", 0.85)),
            "absolute_top3_severe_warning": float(getattr(args, "concentration_absolute_top3_severe_warning", 0.90)),
            "bucket_delta_warning": float(getattr(args, "concentration_bucket_delta_warning", 0.10)),
            "bucket_guard_status": "pending_bucket_mapping",
        },
        "gain_concentration_guard_config": {
            "top_added_ticker_warning": float(getattr(args, "gain_top_added_ticker_warning", 0.35)),
            "top_added_ticker_block": float(getattr(args, "gain_top_added_ticker_block", 0.50)),
            "top_era_warning": float(getattr(args, "gain_top_era_warning", 0.65)),
            "top_era_block": float(getattr(args, "gain_top_era_block", 0.70)),
            "top_year_block": float(getattr(args, "gain_top_year_block", 0.70)),
        },
        "arms": arms,
        "arm_metrics_csv": str(output_dir / "arm_metrics.csv"),
        "report_md": str(output_dir / "report.md"),
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--missed-leaders", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--baseline-metrics", required=True)
    parser.add_argument("--source-doc", default="docs/CODEX_P4_ROTATION_REPLACEMENT_AUDIT_20260703.md")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--arms", default=DEFAULT_ARMS)
    parser.add_argument("--max-swaps-per-date", type=int, default=1)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--fractional-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--max-reasonable-weight-sum", type=float, default=1.05)
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--oos-start", default="2024-07-01")
    parser.add_argument("--oos-end", default="")
    parser.add_argument("--oos2-start", default="2023-01-01")
    parser.add_argument("--oos2-end", default="")
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default=CASH_CARRY_MODE_NONE)
    parser.add_argument("--cash-rate-source", default=None)
    parser.add_argument("--cash-rate-path", default=None)
    parser.add_argument("--cash-rate-lag-days", type=int, default=None)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=None)
    parser.add_argument("--cash-carry-day-count", type=int, default=None)
    parser.add_argument("--concentration-top1-delta-warning", type=float, default=0.05)
    parser.add_argument("--concentration-top3-delta-warning", type=float, default=0.10)
    parser.add_argument("--concentration-hhi-delta-warning", type=float, default=0.05)
    parser.add_argument("--concentration-absolute-top1-warning", type=float, default=0.40)
    parser.add_argument("--concentration-absolute-top1-block", type=float, default=0.45)
    parser.add_argument("--concentration-absolute-top3-warning", type=float, default=0.85)
    parser.add_argument("--concentration-absolute-top3-severe-warning", type=float, default=0.90)
    parser.add_argument("--concentration-bucket-delta-warning", type=float, default=0.10)
    parser.add_argument("--gain-top-added-ticker-warning", type=float, default=0.35)
    parser.add_argument("--gain-top-added-ticker-block", type=float, default=0.50)
    parser.add_argument("--gain-top-era-warning", type=float, default=0.65)
    parser.add_argument("--gain-top-era-block", type=float, default=0.70)
    parser.add_argument("--gain-top-year-block", type=float, default=0.70)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
