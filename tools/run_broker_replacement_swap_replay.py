#!/usr/bin/env python3
"""Replay broker-compatible replacement swaps for stale or weak holdings.

This is a research-only challenger. It does not alter production portfolio
construction. The tool mutates a copy of an existing operating target book by
replacing weak held names with stronger same-date candidates, then sends that
book through the standard broker-ledger replay:

- signal dated T is filled at the next available close;
- integer shares, fees, cash, and daily account equity are preserved;
- candidate selection uses only same-date observable score/risk columns;
- forward-return columns are never used to choose replacements.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402
from tools.run_broker_ledger_replay import repo_path, safe_float  # noqa: E402


DEFAULT_OUT_DIR = "outputs/broker_replacement_swap_replay"
DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"

SCORE_COLUMNS = [
    "score_total",
    "score",
    "concentrated_score",
    "portfolio_future_winner_engine_score",
    "portfolio_monster_early_score",
    "h6_dynamic_leader_score",
    "relative_strength_composite",
    "oneil_leadership_score",
    "industry_group_strength_score",
    "rs_acceleration_score",
    "entry_quality_score",
    "selection_confirmation_score",
]
RISK_COLUMNS = [
    "portfolio_risk_entry_block_score",
    "portfolio_stale_mega_leader_score",
    "risk_penalty",
    "stage2_overext_penalty",
    "overheat_penalty",
]
FORWARD_LABEL_TOKENS = ("forward_return", "weighted_forward_return", "period_forward_return")
PROTECTED_TEMPLATE_COLUMNS = {
    "weight",
    "target_stock_names",
    "weighting_mode",
    "active_rebalance_interval_months",
    "portfolio_mode",
    "portfolio_kind",
    "operating_target_source",
    "decision_frequency",
    "operating_decision_semantics",
    "operating_appended",
    "operating_signal_source_date",
    "operating_latest_price_date",
}


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def clean_text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def parse_regimes(value: str) -> set[str]:
    return {part.strip().lower() for part in str(value or "").split(",") if part.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", default="main")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--max-swaps-per-date", type=int, default=2)
    parser.add_argument("--min-score-advantage", type=float, default=0.20)
    parser.add_argument("--weak-score-threshold", type=float, default=0.35)
    parser.add_argument("--min-market-cap-usd", type=float, default=1_000_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=5_000_000.0)
    parser.add_argument("--replacement-weight-scale", type=float, default=1.0)
    parser.add_argument("--allowed-regimes", default="bull,strong_bull,green,recovery,neutral,balanced")
    parser.add_argument("--allow-monster-gate-override", action="store_true", default=True)
    return parser.parse_args()


def prepare_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.normalize()
    return out.dropna(subset=["rebalance_date"]).copy()


def rank01(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(0.5, index=series.index)
    ranked = numeric.rank(pct=True, ascending=higher_is_better)
    return ranked.fillna(0.5).clip(0.0, 1.0)


def score_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    out = frame.copy()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out = out[out["ticker"].ne("")].copy()
    score_parts: list[pd.Series] = []
    for col in SCORE_COLUMNS:
        if col in out.columns:
            score_parts.append(out.groupby("rebalance_date", group_keys=False)[col].apply(rank01))
    risk_parts: list[pd.Series] = []
    for col in RISK_COLUMNS:
        if col in out.columns:
            risk_parts.append(out.groupby("rebalance_date", group_keys=False)[col].apply(lambda s: rank01(s, higher_is_better=False)))
    if score_parts:
        score = pd.concat(score_parts, axis=1).mean(axis=1)
    else:
        score = pd.Series(0.5, index=out.index)
    if risk_parts:
        risk = pd.concat(risk_parts, axis=1).mean(axis=1)
        score = 0.80 * score + 0.20 * risk
    out["replacement_candidate_score"] = score.fillna(0.5).clip(0.0, 1.0)
    out["replacement_risk_score"] = 1.0 - (pd.concat(risk_parts, axis=1).mean(axis=1) if risk_parts else pd.Series(0.5, index=out.index)).fillna(0.5)
    def numeric_col(name: str) -> pd.Series:
        if name not in out.columns:
            return pd.Series(0.0, index=out.index)
        return pd.to_numeric(out[name], errors="coerce").fillna(0.0)

    penalty = (
        0.35 * numeric_col("portfolio_stale_mega_leader_score")
        + 0.35 * numeric_col("portfolio_risk_entry_block_score")
        + 0.20 * numeric_col("risk_penalty")
        + 0.15 * numeric_col("overheat_penalty")
    )
    out["replacement_adjusted_score"] = (out["replacement_candidate_score"] - penalty).clip(0.0, 1.0)
    return out


def candidate_dates(candidates: pd.DataFrame) -> list[pd.Timestamp]:
    if candidates.empty:
        return []
    return sorted(pd.to_datetime(candidates["rebalance_date"], errors="coerce").dropna().dt.normalize().unique())


def group_for_date(candidates: pd.DataFrame, signal_date: pd.Timestamp) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    dates = candidate_dates(candidates)
    if not dates:
        return pd.DataFrame()
    signal = pd.Timestamp(signal_date).normalize()
    eligible_dates = [pd.Timestamp(dt).normalize() for dt in dates if pd.Timestamp(dt).normalize() <= signal]
    chosen = max(eligible_dates) if eligible_dates else min(pd.Timestamp(dt).normalize() for dt in dates)
    return candidates[candidates["rebalance_date"].eq(chosen)].copy()


def gate_allows_candidate(row: pd.Series, args: argparse.Namespace) -> tuple[bool, str]:
    mktcap = max(safe_float(row.get("market_cap_live"), 0.0), safe_float(row.get("mktcap"), 0.0))
    dollar_vol = safe_float(row.get("dollar_vol_20d"), 0.0)
    if mktcap < float(args.min_market_cap_usd):
        return False, "market_cap_below_floor"
    if dollar_vol < float(args.min_dollar_volume_usd):
        return False, "dollar_volume_below_floor"
    risk = safe_float(row.get("portfolio_risk_entry_block_score"), 0.0)
    stale = safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0)
    if risk >= 0.85:
        return False, "risk_entry_block"
    if stale >= 0.85:
        return False, "stale_candidate_block"
    label = clean_text(row.get("portfolio_candidate_gate_label")).lower()
    hard_gate = any(token in label for token in ["reject", "blocked", "failed", "fail"])
    if hard_gate:
        monster = max(
            safe_float(row.get("portfolio_monster_early_score"), 0.0),
            safe_float(row.get("h6_dynamic_leader_score"), 0.0),
            safe_float(row.get("portfolio_future_winner_engine_score"), 0.0),
        )
        if not (bool(args.allow_monster_gate_override) and monster >= 0.80):
            return False, f"candidate_gate_{label or 'rejected'}"
        return True, "monster_gate_override"
    return True, "candidate_gate_pass"


def held_weakness(row: pd.Series, held_score: float, args: argparse.Namespace) -> tuple[bool, float, str]:
    stale = safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0)
    risk = safe_float(row.get("portfolio_risk_entry_block_score"), 0.0)
    rs3 = safe_float(row.get("rs_benchmark_3m"), 0.0)
    rs_accel = safe_float(row.get("rs_acceleration_score"), 0.0)
    defensive = clean_text(row.get("portfolio_defensive_rotation_action")).lower()
    monster = safe_float(row.get("portfolio_monster_early_score"), 0.0)
    long_hold = safe_float(row.get("long_hold_compounder_score"), 0.0)
    protected = monster >= 0.70 or long_hold >= 0.80
    reasons: list[str] = []
    weakness = max(0.0, 1.0 - held_score)
    if stale >= 0.35:
        weakness += stale
        reasons.append("stale_leader_score")
    if risk >= 0.65:
        weakness += risk
        reasons.append("risk_entry_block_score")
    if rs3 <= -0.08:
        weakness += abs(rs3)
        reasons.append("relative_3m_lag")
    if rs_accel <= -0.10:
        weakness += abs(rs_accel)
        reasons.append("rs_acceleration_negative")
    if defensive and defensive not in {"neutral", "hold", "nan"}:
        weakness += 0.25
        reasons.append("defensive_rotation_action")
    if held_score < float(args.weak_score_threshold):
        reasons.append("held_score_below_threshold")
    if protected and not {"stale_leader_score", "risk_entry_block_score"}.intersection(reasons):
        return False, weakness, "protected_winner"
    return bool(reasons), weakness, "+".join(reasons) if reasons else "not_weak"


def copy_candidate_into_target(candidate: pd.Series, template: pd.Series, columns: list[str], weight: float) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for col in columns:
        if col in PROTECTED_TEMPLATE_COLUMNS:
            row[col] = template.get(col, "")
        elif col in candidate.index:
            row[col] = candidate.get(col, "")
        else:
            row[col] = template.get(col, "")
        if any(token in col.lower() for token in FORWARD_LABEL_TOKENS):
            row[col] = 0.0
    row["ticker"] = clean_ticker(candidate.get("ticker"))
    row["Name"] = candidate.get("Name", template.get("Name", "")) if "Name" in columns else row.get("Name", "")
    row["sector"] = candidate.get("sector", template.get("sector", "")) if "sector" in columns else row.get("sector", "")
    row["weight"] = float(weight)
    for col, value in {
        "replacement_swap_applied": True,
        "replacement_swap_from": clean_ticker(template.get("ticker")),
        "replacement_swap_to": clean_ticker(candidate.get("ticker")),
        "replacement_swap_source": "broker_replacement_swap_replay",
    }.items():
        if col not in row:
            row[col] = value
    return row


def build_replacement_book(targets: pd.DataFrame, candidates: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    targets = prepare_dates(targets)
    candidates = score_candidate_frame(prepare_dates(candidates))
    if targets.empty or candidates.empty:
        return targets, pd.DataFrame()
    allowed_regimes = parse_regimes(args.allowed_regimes)
    output_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    extra_cols = [
        "replacement_swap_applied",
        "replacement_swap_from",
        "replacement_swap_to",
        "replacement_swap_source",
    ]
    columns = list(dict.fromkeys(list(targets.columns) + extra_cols))
    for signal_date, period in targets.groupby("rebalance_date", sort=True):
        period = period.copy()
        cands = group_for_date(candidates, pd.Timestamp(signal_date))
        if cands.empty:
            output_rows.extend(period.to_dict("records"))
            continue
        candidate_by_ticker = {clean_ticker(row["ticker"]): row for _, row in cands.iterrows()}
        period["ticker"] = period["ticker"].map(clean_ticker)
        regime_values = period["regime_state"].dropna().astype(str) if "regime_state" in period.columns and not period.empty else pd.Series(dtype=str)
        regime = clean_text(regime_values.iloc[0] if not regime_values.empty else "").lower()
        regime_allowed = not allowed_regimes or not regime or regime in allowed_regimes
        if not regime_allowed:
            output_rows.extend(period.to_dict("records"))
            continue

        held_tickers = set(period["ticker"])
        weak_rows: list[tuple[float, pd.Series, float, str]] = []
        for _, held in period.iterrows():
            ticker = clean_ticker(held.get("ticker"))
            if not ticker:
                continue
            candidate_row = candidate_by_ticker.get(ticker)
            held_score = safe_float(candidate_row.get("replacement_adjusted_score"), 0.5) if candidate_row is not None else 0.5
            is_weak, weakness, reason = held_weakness(held if candidate_row is None else candidate_row, held_score, args)
            if is_weak:
                weak_rows.append((weakness, held, held_score, reason))
        weak_rows = sorted(weak_rows, key=lambda item: item[0], reverse=True)[: int(args.max_swaps_per_date)]

        replacements: dict[str, dict[str, Any]] = {}
        removed: set[str] = set()
        available = cands[~cands["ticker"].isin(held_tickers)].copy()
        if not available.empty:
            available = available.sort_values("replacement_adjusted_score", ascending=False)
        used_candidates: set[str] = set()
        for _, held, held_score, reason in weak_rows:
            held_ticker = clean_ticker(held.get("ticker"))
            chosen: pd.Series | None = None
            chosen_gate = ""
            chosen_score = 0.0
            for _, cand in available.iterrows():
                cand_ticker = clean_ticker(cand.get("ticker"))
                if not cand_ticker or cand_ticker in used_candidates:
                    continue
                allowed, gate_reason = gate_allows_candidate(cand, args)
                if not allowed:
                    continue
                cand_score = safe_float(cand.get("replacement_adjusted_score"), 0.0)
                if cand_score - held_score < float(args.min_score_advantage):
                    continue
                chosen = cand
                chosen_gate = gate_reason
                chosen_score = cand_score
                break
            if chosen is None:
                decision_rows.append(
                    {
                        "rebalance_date": pd.Timestamp(signal_date).date().isoformat(),
                        "held_ticker": held_ticker,
                        "replacement_ticker": "",
                        "decision": "no_swap_candidate",
                        "held_score": held_score,
                        "candidate_score": "",
                        "score_advantage": "",
                        "weakness_reason": reason,
                        "gate_reason": "",
                    }
                )
                continue
            new_weight = max(0.0, safe_float(held.get("weight"), 0.0) * float(args.replacement_weight_scale))
            if new_weight <= 1e-12:
                continue
            chosen_ticker = clean_ticker(chosen.get("ticker"))
            replacement_row = copy_candidate_into_target(chosen, held, columns, new_weight)
            replacement_row["replacement_swap_reason"] = reason
            replacement_row["replacement_swap_candidate_score"] = chosen_score
            replacement_row["replacement_swap_held_score"] = held_score
            replacement_row["replacement_swap_score_advantage"] = chosen_score - held_score
            replacements[held_ticker] = replacement_row
            removed.add(held_ticker)
            used_candidates.add(chosen_ticker)
            decision_rows.append(
                {
                    "rebalance_date": pd.Timestamp(signal_date).date().isoformat(),
                    "held_ticker": held_ticker,
                    "replacement_ticker": chosen_ticker,
                    "decision": "swap",
                    "held_score": held_score,
                    "candidate_score": chosen_score,
                    "score_advantage": chosen_score - held_score,
                    "held_weight": safe_float(held.get("weight"), 0.0),
                    "replacement_weight": new_weight,
                    "weakness_reason": reason,
                    "gate_reason": chosen_gate,
                }
            )
        for _, row in period.iterrows():
            ticker = clean_ticker(row.get("ticker"))
            if ticker in removed:
                output_rows.append(replacements[ticker])
            else:
                rec = row.to_dict()
                rec.setdefault("replacement_swap_applied", False)
                rec.setdefault("replacement_swap_from", "")
                rec.setdefault("replacement_swap_to", "")
                rec.setdefault("replacement_swap_source", "")
                output_rows.append(rec)
    out = pd.DataFrame(output_rows)
    if not out.empty:
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    return out, pd.DataFrame(decision_rows)


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Broker Replacement-Swap Replay",
            "",
            "Research-only account-ledger challenger. Weak holdings are replaced by stronger same-date candidates before broker replay.",
            "",
            f"- Portfolio: `{metrics.get('portfolio_kind')}`",
            f"- Status: `{metrics.get('status')}`",
            f"- Metric mode: `{metrics.get('metric_mode')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Swap count: {int(safe_float(metrics.get('replacement_swap_count'), 0))}",
            f"- Total trades: {int(safe_float(metrics.get('trade_count'), 0))}",
            "",
            "Promotion requires target gates, stress windows, and human approval. This sidecar does not change production defaults.",
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    candidate_book = repo_path(args.candidate_book)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_targets = read_csv(target_book)
    raw_candidates = read_csv(candidate_book)
    modified, decisions = build_replacement_book(raw_targets, raw_candidates, args)
    modified_path = output_dir / "replacement_target_book.csv"
    decisions_path = output_dir / "replacement_swap_decisions.csv"
    modified.to_csv(modified_path, index=False)
    decisions.to_csv(decisions_path, index=False)
    comparison = target_book.parent / "concentrated_strategy_comparison.csv"
    if args.portfolio_kind == "concentrated" and comparison.exists():
        shutil.copy2(comparison, output_dir / "concentrated_strategy_comparison.csv")
    if modified.empty:
        payload = {
            "status": "blocked",
            "reason": "replacement target book is empty",
            "target_book": str(target_book),
            "candidate_book": str(candidate_book),
            "production_activation_allowed": False,
        }
        write_json(output_dir / "metrics.json", payload)
        (output_dir / "replay_report.md").write_text(render_report(payload), encoding="utf-8")
        return payload
    try:
        metrics = broker_replay(
            target_book=modified_path,
            price_cache=price_cache,
            output_dir=output_dir,
            portfolio_kind=args.portfolio_kind,
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            integer_shares=not bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
        )
    except Exception as exc:
        metrics = {
            "status": "blocked",
            "reason": f"broker replay failed: {type(exc).__name__}: {exc}",
            "valid_for_production": False,
            "portfolio_kind": args.portfolio_kind,
            "target_book": str(modified_path),
            "price_cache": str(price_cache),
        }
    swap_count = int((decisions.get("decision", pd.Series(dtype=str)).astype(str).eq("swap")).sum()) if not decisions.empty else 0
    metrics.update(
        {
            "candidate_id": f"{args.portfolio_kind}_broker_replacement_swap_replay",
            "metric_mode": "broker_replacement_swap_next_close",
            "data_mode": "same_date_candidate_replacement_account_ledger",
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": bool(metrics.get("valid_for_production")),
            "replacement_swap_count": swap_count,
            "replacement_decision_count": int(len(decisions)),
            "replacement_target_book": str(modified_path),
            "replacement_decisions": str(decisions_path),
            "candidate_book": str(candidate_book),
            "min_score_advantage": float(args.min_score_advantage),
            "weak_score_threshold": float(args.weak_score_threshold),
            "max_swaps_per_date": int(args.max_swaps_per_date),
            "used_forward_return_for_selection": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_json(output_dir / "metrics.json", metrics)
    (output_dir / "replay_report.md").write_text(render_report(metrics), encoding="utf-8")
    return metrics


def main() -> int:
    args = parse_args()
    payload = run(args)
    print(json.dumps({"status": payload.get("status"), "cagr": payload.get("cagr"), "max_dd": payload.get("max_dd")}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
