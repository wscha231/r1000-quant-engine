#!/usr/bin/env python3
"""Main v4 future-winner/evidence challenger.

Research-only broker-ledger challenger for the main portfolio. It deliberately
keeps production defaults unchanged while testing a more concentrated,
future-winner-driven target book with:

- target N 12/15/18;
- future winner, market confirmation, leader-onset, and Form 4 shadow variants;
- no-trade band / winner-intact hold discipline;
- next-close broker-ledger evaluation with cost sensitivity.

Forward-return labels are never used for target selection.
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

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from tools.run_alpha_selector_broker_grid import (  # noqa: E402
    add_price_cache_tradeability,
    capped_score_weights,
    gate_mask,
    liquidity_mask,
    parse_csv_floats,
    parse_csv_ints,
    prepare_candidates,
    rank_feature,
    read_csv,
)
from tools.run_broker_ledger_replay import replay as broker_replay, repo_path, safe_float  # noqa: E402
from tools.sec_signal_merge import load_and_merge_sec_signals  # noqa: E402


DEFAULT_CANDIDATE_BOOK = "outputs/reports/candidate_replay_book.csv"
DEFAULT_SEC_SIGNALS = "data_pit/sec/sec_ownership_signals.parquet"
DEFAULT_OUT_DIR = "outputs/main_v4_future_winner_evidence"
FORWARD_LABEL_PATTERNS = ("forward", "future_return", "next_return", "horizon_return")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def clean_label(value: Any) -> str:
    import re

    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("_") or "na"


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def add_market_confirmation_score(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    components = {
        "relative_strength_composite": 0.25,
        "rs_acceleration_score": 0.20,
        "price_above_ma50": 0.20,
        "price_above_ma200": 0.15,
        "breakout_setup_quality_score": 0.10,
        "volume_accumulation_score": 0.10,
    }
    score = pd.Series(0.0, index=d.index, dtype=float)
    used = 0.0
    for col, weight in components.items():
        if col in d.columns:
            score += float(weight) * numeric(d, col).clip(0.0, 1.0)
            used += float(weight)
    if used <= 0:
        # Fallback to same-date ranks already available in most candidate books.
        score = 0.55 * rank_feature(d, "rs_acceleration_score") + 0.45 * rank_feature(d, "dollar_vol_20d")
        used = 1.0
    d["market_confirmation_score"] = (score / used).fillna(0.0).clip(0.0, 1.0)
    return d


def score_source_series(frame: pd.DataFrame, source: str) -> pd.Series:
    source = str(source)
    if source == "future_winner":
        return rank_feature(frame, "portfolio_future_winner_engine_score")
    if source == "future_winner_market_confirmation":
        return (
            0.65 * rank_feature(frame, "portfolio_future_winner_engine_score")
            + 0.35 * rank_feature(frame, "market_confirmation_score")
        )
    if source == "leader_onset_shadow":
        return (
            0.55 * rank_feature(frame, "leader_onset_score")
            + 0.25 * rank_feature(frame, "portfolio_future_winner_engine_score")
            + 0.20 * rank_feature(frame, "market_confirmation_score")
        )
    if source == "leader_onset_sec_shadow":
        return (
            0.42 * rank_feature(frame, "leader_onset_score")
            + 0.25 * rank_feature(frame, "portfolio_future_winner_engine_score")
            + 0.15 * rank_feature(frame, "market_confirmation_score")
            + 0.10 * rank_feature(frame, "early_evidence_score")
            + 0.08 * rank_feature(frame, "sec_form4_cluster_buy_score")
        )
    return rank_feature(frame, "portfolio_future_winner_engine_score")


def is_broken(row: pd.Series) -> bool:
    risk = safe_float(row.get("portfolio_risk_entry_block_score"), 0.0)
    stale = safe_float(row.get("portfolio_stale_mega_leader_score"), 0.0)
    gate = str(row.get("portfolio_candidate_gate_label") or "").lower()
    leader_like = str(row.get("portfolio_sleeve_label") or "").lower()
    rejected = any(token in gate for token in ("reject", "block", "fail"))
    is_leader = any(token in leader_like for token in ("future", "early", "monster", "leader", "concentrated"))
    return bool(risk >= 0.75 or stale >= 0.75 or (rejected and not is_leader))


def score_z(group: pd.DataFrame) -> pd.Series:
    scores = pd.to_numeric(group["main_v4_score"], errors="coerce").fillna(0.0)
    std = float(scores.std(ddof=0))
    if not math.isfinite(std) or std <= 1e-12:
        return pd.Series(0.0, index=group.index, dtype=float)
    return (scores - float(scores.mean())) / std


def apply_hold_discipline(
    group: pd.DataFrame,
    prev_tickers: set[str],
    *,
    target_n: int,
    replace_threshold_z: float,
    broken_threshold_z: float,
) -> pd.DataFrame:
    g = group.copy().sort_values("main_v4_score", ascending=False)
    g["main_v4_score_z"] = score_z(g)
    by_ticker = {str(row["ticker"]): row for _, row in g.iterrows()}
    selected: list[pd.Series] = []
    selected_tickers: set[str] = set()

    for ticker in sorted(prev_tickers):
        row = by_ticker.get(ticker)
        if row is not None and not is_broken(row):
            selected.append(row)
            selected_tickers.add(ticker)
    if len(selected) > int(target_n):
        selected = sorted(selected, key=lambda r: safe_float(r.get("main_v4_score")), reverse=True)[: int(target_n)]
        selected_tickers = {str(r["ticker"]) for r in selected}

    for _, row in g.iterrows():
        ticker = str(row["ticker"])
        if ticker in selected_tickers:
            continue
        if len(selected) < int(target_n):
            selected.append(row)
            selected_tickers.add(ticker)
            continue
        worst_i = min(range(len(selected)), key=lambda i: safe_float(selected[i].get("main_v4_score_z")))
        worst = selected[worst_i]
        threshold = broken_threshold_z if is_broken(worst) else replace_threshold_z
        if safe_float(row.get("main_v4_score_z")) - safe_float(worst.get("main_v4_score_z")) >= float(threshold):
            selected_tickers.discard(str(worst["ticker"]))
            selected[worst_i] = row
            selected_tickers.add(ticker)

    if not selected:
        return pd.DataFrame(columns=g.columns)
    out = pd.DataFrame([row.to_dict() for row in selected])
    return out.sort_values("main_v4_score", ascending=False).head(int(target_n))


def build_target_book(
    candidates: pd.DataFrame,
    *,
    score_source: str,
    target_n: int,
    single_name_cap: float,
    cash_floor: float,
    replace_threshold_z: float,
    broken_threshold_z: float,
    min_mcap: float,
    min_dollar_vol: float,
    min_price: float,
    require_price_cache: bool,
) -> pd.DataFrame:
    d = add_market_confirmation_score(candidates)
    d["main_v4_score"] = score_source_series(d, score_source).fillna(0.0).clip(0.0, 1.0)
    mask = liquidity_mask(d, min_mcap=min_mcap, min_dollar_vol=min_dollar_vol, min_price=min_price) & gate_mask(d)
    if require_price_cache:
        mask = mask & d.get("price_cache_tradeable", pd.Series(False, index=d.index)).astype(bool)

    rows: list[dict[str, Any]] = []
    prev_tickers: set[str] = set()
    invested = max(0.0, min(1.0, 1.0 - float(cash_floor)))
    for dt, group in d[mask].groupby("rebalance_date", sort=True):
        selected = apply_hold_discipline(
            group,
            prev_tickers,
            target_n=target_n,
            replace_threshold_z=replace_threshold_z,
            broken_threshold_z=broken_threshold_z,
        )
        if selected.empty:
            prev_tickers = set()
            continue
        weights = capped_score_weights(selected["main_v4_score"], single_name_cap) * invested
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
                    "portfolio_future_winner_engine_score": safe_float(row.get("portfolio_future_winner_engine_score")),
                    "market_confirmation_score": safe_float(row.get("market_confirmation_score")),
                    "leader_onset_score": safe_float(row.get("leader_onset_score")),
                    "early_evidence_score": safe_float(row.get("early_evidence_score")),
                    "evidence_confidence_score": safe_float(row.get("evidence_confidence_score")),
                    "sec_form4_cluster_buy_score": safe_float(row.get("sec_form4_cluster_buy_score")),
                    "main_v4_score": safe_float(row.get("main_v4_score")),
                    "main_v4_score_source": score_source,
                    "target_stock_names": int(target_n),
                    "single_name_cap": float(single_name_cap),
                    "cash_floor": float(cash_floor),
                    "replace_threshold_z": float(replace_threshold_z),
                    "broken_threshold_z": float(broken_threshold_z),
                    "winner_intact_hold_enabled": True,
                    "research_only_backtest": True,
                    "production_activation_allowed": False,
                }
            )
        prev_tickers = {str(x).upper() for x in selected["ticker"].tolist()}
    return pd.DataFrame(rows)


def target_distance(metrics: dict[str, Any]) -> float:
    target = PORTFOLIO_GOAL_TARGETS.get("main", {"cagr": 0.30, "max_dd": -0.15})
    cagr = safe_float(metrics.get("cagr"), math.nan)
    max_dd = safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), math.nan)
    if not math.isfinite(cagr) or not math.isfinite(max_dd):
        return math.inf
    return max(0.0, target["cagr"] - cagr) + max(0.0, target["max_dd"] - max_dd)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = read_csv(repo_path(args.candidate_book))
    sec_path = repo_path(args.sec_signals) if args.sec_signals else Path("")
    sec_signal_source = ""
    if args.sec_signals and sec_path.exists() and not raw.empty:
        raw = load_and_merge_sec_signals(raw, sec_path, date_col="rebalance_date", overwrite=False)
        sec_signal_source = str(sec_path)
    candidates = prepare_candidates(raw)
    candidates = add_market_confirmation_score(candidates)
    require_price_cache = not bool(args.allow_unfillable_targets)
    if require_price_cache:
        candidates = add_price_cache_tradeability(candidates, price_cache, int(args.max_fill_lag_days))
    if candidates.empty:
        payload = {
            "status": "blocked",
            "reason": "candidate replay book is missing or empty",
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
        write_json(output_dir / "best_metrics.json", payload)
        return payload

    target_ns = parse_csv_ints(args.target_ns, [12, 15, 18])
    caps = parse_csv_floats(args.single_name_caps, [0.33])
    costs = parse_csv_floats(args.cost_bps_list, [float(args.cost_bps)])
    score_sources = [s.strip() for s in str(args.score_sources).split(",") if s.strip()]
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    variant_count = 0
    forbidden_cols = [c for c in candidates.columns if any(token in c.lower() for token in FORWARD_LABEL_PATTERNS)]
    for score_source in score_sources:
        for n in target_ns:
            for cap in caps:
                variant_count += 1
                vid = f"{clean_label(score_source)}_N{int(n)}_cap{clean_label(cap)}"
                variant_dir = output_dir / vid
                variant_dir.mkdir(parents=True, exist_ok=True)
                target = build_target_book(
                    candidates,
                    score_source=score_source,
                    target_n=int(n),
                    single_name_cap=float(cap),
                    cash_floor=float(args.cash_floor),
                    replace_threshold_z=float(args.replace_threshold_z),
                    broken_threshold_z=float(args.broken_threshold_z),
                    min_mcap=float(args.min_market_cap_usd),
                    min_dollar_vol=float(args.min_dollar_volume_usd),
                    min_price=float(args.min_price),
                    require_price_cache=require_price_cache,
                )
                target_path = variant_dir / "target_book.csv"
                target.to_csv(target_path, index=False)
                for cost in costs:
                    cost_dir = variant_dir / f"cost_{clean_label(cost)}bps"
                    try:
                        metrics = broker_replay(
                            target_book=target_path,
                            price_cache=price_cache,
                            output_dir=cost_dir,
                            portfolio_kind="main",
                            starting_capital=float(args.starting_capital),
                            fill_mode=args.fill_mode,
                            cost_bps=float(cost),
                            integer_shares=not bool(args.no_integer_shares),
                            max_fill_lag_days=int(args.max_fill_lag_days),
                        )
                    except Exception as exc:
                        metrics = {"status": "blocked", "reason": f"broker replay failed: {type(exc).__name__}: {exc}"}
                    metrics.update(
                        {
                            "candidate_id": f"main_v4_future_winner_evidence_{vid}_cost_{clean_label(cost)}bps",
                            "metric_mode": "main_v4_future_winner_evidence_next_close",
                            "portfolio_kind": "main",
                            "variant_id": vid,
                            "score_source": score_source,
                            "target_stock_names": int(n),
                            "single_name_cap": float(cap),
                            "cash_floor": float(args.cash_floor),
                            "cost_bps": float(cost),
                            "sec_signal_source": sec_signal_source,
                            "forbidden_forward_label_columns_present_but_unused": forbidden_cols[:50],
                            "target_book": str(target_path),
                            "research_only": True,
                            "production_activation_allowed": False,
                            "valid_for_production": bool(metrics.get("valid_for_production")),
                        }
                    )
                    write_json(cost_dir / "metrics.json", metrics)
                    rows.append(
                        {
                            "variant_id": vid,
                            "score_source": score_source,
                            "target_stock_names": int(n),
                            "single_name_cap": float(cap),
                            "cash_floor": float(args.cash_floor),
                            "cost_bps": float(cost),
                            "status": metrics.get("status"),
                            "cagr": metrics.get("cagr"),
                            "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                            "sharpe": metrics.get("sharpe"),
                            "trade_count": metrics.get("trade_count"),
                            "avg_cash_weight": metrics.get("avg_cash_weight"),
                            "target_distance": target_distance(metrics),
                            "valid_for_production": bool(metrics.get("valid_for_production")),
                            "reason": metrics.get("reason", ""),
                        }
                    )
                    if float(cost) == float(args.cost_bps) and metrics.get("status") == "completed":
                        completed.append(metrics)

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["target_distance", "cagr", "max_dd"], ascending=[True, False, False])
    summary.to_csv(output_dir / "summary.csv", index=False)
    if completed:
        best = sorted(completed, key=lambda m: (target_distance(m), -safe_float(m.get("cagr"), -1.0), -safe_float(m.get("sharpe"), -1.0)))[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "status": "completed",
                "candidate_id": "main_v4_future_winner_evidence_best",
                "selection_rule": "lowest_target_distance_then_cagr_then_sharpe",
                "variant_count": variant_count,
                "research_only": True,
                "production_activation_allowed": False,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed main v4 variants",
            "variant_count": variant_count,
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        "# Main v4 Future Winner Evidence",
        "",
        f"- status: `{best_payload.get('status')}`",
        f"- best_cagr: {safe_float(best_payload.get('cagr')):.2%}",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown'))):.2%}",
        f"- best_sharpe: {safe_float(best_payload.get('sharpe')):.3f}",
        f"- variants: {variant_count}",
        f"- sec_signal_source: `{sec_signal_source or 'none'}`",
        "",
        "Research-only challenger. Production activation requires broker-ledger gates, PIT/leakage audit, and human approval.",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return best_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--sec-signals", default=DEFAULT_SEC_SIGNALS)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--cost-bps-list", default="25,50,75,100")
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--target-ns", default="12,15,18")
    parser.add_argument(
        "--score-sources",
        default="future_winner,future_winner_market_confirmation,leader_onset_shadow,leader_onset_sec_shadow",
    )
    parser.add_argument("--single-name-caps", default="0.33")
    parser.add_argument("--cash-floor", type=float, default=0.03)
    parser.add_argument("--replace-threshold-z", type=float, default=0.75)
    parser.add_argument("--broken-threshold-z", type=float, default=0.35)
    parser.add_argument("--min-market-cap-usd", type=float, default=1_000_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=5_000_000.0)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--allow-unfillable-targets", action="store_true")
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
