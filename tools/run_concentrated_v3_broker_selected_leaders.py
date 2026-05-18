#!/usr/bin/env python3
"""Concentrated v3 broker-selected leader challenger.

Research-only concentrated challenger that rejects N7 as a champion path and
tests only N2/N3/N5 concentrated leader books through the official broker-ledger
evaluator. It favors replacement-before-cash by filling the target count first,
then applies staged entry and same-theme caps.
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
DEFAULT_OUT_DIR = "outputs/concentrated_v3_broker_selected_leaders"


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


def add_scores(frame: pd.DataFrame, score_source: str) -> pd.DataFrame:
    d = frame.copy()
    if "market_confirmation_score" not in d.columns:
        d["market_confirmation_score"] = (
            0.40 * rank_feature(d, "rs_acceleration_score")
            + 0.35 * rank_feature(d, "relative_strength_composite")
            + 0.25 * rank_feature(d, "dollar_vol_20d")
        ).clip(0.0, 1.0)
    if score_source == "monster_future":
        score = (
            0.34 * rank_feature(d, "portfolio_monster_early_score")
            + 0.30 * rank_feature(d, "portfolio_future_winner_engine_score")
            + 0.18 * rank_feature(d, "portfolio_early_scout_engine_score")
            + 0.10 * rank_feature(d, "rs_acceleration_score")
            + 0.08 * rank_feature(d, "industry_group_strength_score")
        )
    elif score_source == "leader_onset_sec":
        score = (
            0.34 * rank_feature(d, "leader_onset_score")
            + 0.24 * rank_feature(d, "portfolio_future_winner_engine_score")
            + 0.16 * rank_feature(d, "market_confirmation_score")
            + 0.12 * rank_feature(d, "early_evidence_score")
            + 0.08 * rank_feature(d, "sec_form4_cluster_buy_score")
            + 0.06 * rank_feature(d, "portfolio_monster_early_score")
        )
    else:
        score = (
            0.45 * rank_feature(d, "portfolio_future_winner_engine_score")
            + 0.30 * rank_feature(d, "market_confirmation_score")
            + 0.15 * rank_feature(d, "portfolio_monster_early_score")
            + 0.10 * rank_feature(d, "portfolio_early_scout_engine_score")
        )
    risk_safe = rank_feature(d, "portfolio_risk_entry_block_score", lower_is_better=True)
    stale_safe = rank_feature(d, "portfolio_stale_mega_leader_score", lower_is_better=True)
    d["concentrated_v3_score"] = (0.92 * score + 0.04 * risk_safe + 0.04 * stale_safe).fillna(0.0).clip(0.0, 1.0)
    return d


def apply_same_theme_cap(selected: pd.DataFrame, weights: list[float], cap: float) -> list[float]:
    if selected.empty or "sector" not in selected.columns:
        return weights
    out = list(float(w) for w in weights)
    sectors = selected["sector"].fillna("").astype(str).tolist()
    for sector in sorted(set(sectors)):
        idxs = [i for i, value in enumerate(sectors) if value == sector]
        total = sum(out[i] for i in idxs)
        if total > float(cap) and total > 0:
            scale = float(cap) / total
            for i in idxs:
                out[i] *= scale
    return out


def build_target_book(
    candidates: pd.DataFrame,
    *,
    score_source: str,
    target_n: int,
    single_name_cap: float,
    same_theme_cap: float,
    staged_entry: tuple[float, float, float],
    min_mcap: float,
    min_dollar_vol: float,
    min_price: float,
    require_price_cache: bool,
) -> pd.DataFrame:
    d = add_scores(candidates, score_source)
    mask = liquidity_mask(d, min_mcap=min_mcap, min_dollar_vol=min_dollar_vol, min_price=min_price) & gate_mask(d)
    if require_price_cache:
        mask = mask & d.get("price_cache_tradeable", pd.Series(False, index=d.index)).astype(bool)
    rows: list[dict[str, Any]] = []
    hold_age: dict[str, int] = {}
    for dt, group in d[mask].groupby("rebalance_date", sort=True):
        selected = group.sort_values("concentrated_v3_score", ascending=False).head(int(target_n)).copy()
        if selected.empty:
            hold_age = {}
            continue
        base = capped_score_weights(selected["concentrated_v3_score"], single_name_cap).tolist()
        staged_weights: list[float] = []
        next_age: dict[str, int] = {}
        for (_, row), weight in zip(selected.iterrows(), base):
            ticker = str(row["ticker"]).upper()
            age = int(hold_age.get(ticker, 0))
            scale = staged_entry[0] if age <= 0 else (staged_entry[1] if age == 1 else staged_entry[2])
            staged_weights.append(float(weight) * float(scale))
            next_age[ticker] = age + 1
        staged_weights = apply_same_theme_cap(selected, staged_weights, same_theme_cap)
        for (_, row), weight in zip(selected.iterrows(), staged_weights):
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
                    "portfolio_monster_early_score": safe_float(row.get("portfolio_monster_early_score")),
                    "market_confirmation_score": safe_float(row.get("market_confirmation_score")),
                    "leader_onset_score": safe_float(row.get("leader_onset_score")),
                    "early_evidence_score": safe_float(row.get("early_evidence_score")),
                    "sec_form4_cluster_buy_score": safe_float(row.get("sec_form4_cluster_buy_score")),
                    "concentrated_v3_score": safe_float(row.get("concentrated_v3_score")),
                    "concentrated_v3_score_source": score_source,
                    "target_stock_names": int(target_n),
                    "single_name_cap": float(single_name_cap),
                    "same_theme_cap": float(same_theme_cap),
                    "staged_entry": "/".join(f"{x:.2f}" for x in staged_entry),
                    "weighting_mode": "concentrated_v3_broker_selected",
                    "active_rebalance_interval_months": 1,
                    "replacement_swap_before_cash": True,
                    "research_only_backtest": True,
                    "production_activation_allowed": False,
                }
            )
        hold_age = next_age
    return pd.DataFrame(rows)


def parse_staged(value: str) -> tuple[float, float, float]:
    vals = parse_csv_floats(value.replace("/", ","), [0.5, 0.8, 1.0])
    vals = (vals + [1.0, 1.0, 1.0])[:3]
    return (float(vals[0]), float(vals[1]), float(vals[2]))


def champion_key(metrics: dict[str, Any]) -> tuple[float, float, float, float, float]:
    return (
        safe_float(metrics.get("cagr"), -1.0),
        safe_float(metrics.get("max_dd", metrics.get("max_drawdown")), -1.0),
        safe_float(metrics.get("sharpe"), -1.0),
        -safe_float(metrics.get("turnover", metrics.get("annual_turnover")), 1e9),
        -safe_float(metrics.get("total_fees_usd", metrics.get("total_fees")), 1e9),
    )


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

    target_ns = [n for n in parse_csv_ints(args.target_ns, [2, 3, 5]) if n in {2, 3, 5}]
    banned = [n for n in parse_csv_ints(args.target_ns, [2, 3, 5]) if n >= 7]
    caps = parse_csv_floats(args.single_name_caps, [0.40, 0.45, 0.50])
    theme_caps = parse_csv_floats(args.same_theme_caps, [0.70, 0.80])
    costs = parse_csv_floats(args.cost_bps_list, [float(args.cost_bps)])
    score_sources = [s.strip() for s in str(args.score_sources).split(",") if s.strip()]
    staged = parse_staged(args.staged_entry)
    rows: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    variant_count = 0
    for source in score_sources:
        for n in target_ns:
            for cap in caps:
                for theme_cap in theme_caps:
                    variant_count += 1
                    vid = f"{clean_label(source)}_N{int(n)}_cap{clean_label(cap)}_theme{clean_label(theme_cap)}"
                    variant_dir = output_dir / vid
                    variant_dir.mkdir(parents=True, exist_ok=True)
                    target = build_target_book(
                        candidates,
                        score_source=source,
                        target_n=int(n),
                        single_name_cap=float(cap),
                        same_theme_cap=float(theme_cap),
                        staged_entry=staged,
                        min_mcap=float(args.min_market_cap_usd),
                        min_dollar_vol=float(args.min_dollar_volume_usd),
                        min_price=float(args.min_price),
                        require_price_cache=require_price_cache,
                    )
                    target_path = variant_dir / "target_book.csv"
                    target.to_csv(target_path, index=False)
                    filters = {
                        "target_stock_names": str(int(n)),
                        "weighting_mode": "concentrated_v3_broker_selected",
                        "active_rebalance_interval_months": "1",
                    }
                    for cost in costs:
                        cost_dir = variant_dir / f"cost_{clean_label(cost)}bps"
                        try:
                            metrics = broker_replay(
                                target_book=target_path,
                                price_cache=price_cache,
                                output_dir=cost_dir,
                                portfolio_kind="concentrated",
                                starting_capital=float(args.starting_capital),
                                fill_mode=args.fill_mode,
                                cost_bps=float(cost),
                                integer_shares=not bool(args.no_integer_shares),
                                max_fill_lag_days=int(args.max_fill_lag_days),
                                concentrated_champion_filters=filters,
                            )
                        except Exception as exc:
                            metrics = {"status": "blocked", "reason": f"broker replay failed: {type(exc).__name__}: {exc}"}
                        metrics.update(
                            {
                                "candidate_id": f"concentrated_v3_broker_selected_leaders_{vid}_cost_{clean_label(cost)}bps",
                                "metric_mode": "concentrated_v3_broker_selected_next_close",
                                "portfolio_kind": "concentrated",
                                "variant_id": vid,
                                "score_source": source,
                                "target_stock_names": int(n),
                                "single_name_cap": float(cap),
                                "same_theme_cap": float(theme_cap),
                                "staged_entry": "/".join(f"{x:.2f}" for x in staged),
                                "cost_bps": float(cost),
                                "n7_champion_allowed": False,
                                "banned_target_ns_requested": banned,
                                "sec_signal_source": sec_signal_source,
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
                                "score_source": source,
                                "target_stock_names": int(n),
                                "single_name_cap": float(cap),
                                "same_theme_cap": float(theme_cap),
                                "cost_bps": float(cost),
                                "status": metrics.get("status"),
                                "cagr": metrics.get("cagr"),
                                "max_dd": metrics.get("max_dd", metrics.get("max_drawdown")),
                                "sharpe": metrics.get("sharpe"),
                                "trade_count": metrics.get("trade_count"),
                                "avg_cash_weight": metrics.get("avg_cash_weight"),
                                "valid_for_production": bool(metrics.get("valid_for_production")),
                                "reason": metrics.get("reason", ""),
                            }
                        )
                        if float(cost) == float(args.cost_bps) and metrics.get("status") == "completed":
                            completed.append(metrics)

    summary = pd.DataFrame(rows)
    if not summary.empty:
        summary = summary.sort_values(["cagr", "max_dd", "sharpe"], ascending=[False, False, False])
    summary.to_csv(output_dir / "summary.csv", index=False)
    if completed:
        best = sorted(completed, key=champion_key, reverse=True)[0]
        best_payload = dict(best)
        best_payload.update(
            {
                "status": "completed",
                "candidate_id": "concentrated_v3_broker_selected_leaders_best",
                "selection_rule": "broker_cagr_then_daily_maxdd_then_sharpe_then_turnover_then_fees",
                "variant_count": variant_count,
                "n7_champion_allowed": False,
                "banned_target_ns_requested": banned,
                "research_only": True,
                "production_activation_allowed": False,
            }
        )
    else:
        best_payload = {
            "status": "blocked",
            "reason": "no completed concentrated v3 variants",
            "variant_count": variant_count,
            "n7_champion_allowed": False,
            "banned_target_ns_requested": banned,
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": False,
        }
    write_json(output_dir / "best_metrics.json", best_payload)
    report = [
        "# Concentrated v3 Broker Selected Leaders",
        "",
        f"- status: `{best_payload.get('status')}`",
        f"- best_cagr: {safe_float(best_payload.get('cagr')):.2%}",
        f"- best_max_dd: {safe_float(best_payload.get('max_dd', best_payload.get('max_drawdown'))):.2%}",
        f"- best_sharpe: {safe_float(best_payload.get('sharpe')):.3f}",
        f"- variants: {variant_count}",
        f"- n7_champion_allowed: `{best_payload.get('n7_champion_allowed')}`",
        f"- sec_signal_source: `{sec_signal_source or 'none'}`",
        "",
        "Research-only challenger. N7 is intentionally excluded from champion selection.",
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
    parser.add_argument("--target-ns", default="2,3,5")
    parser.add_argument("--single-name-caps", default="0.40,0.45,0.50")
    parser.add_argument("--same-theme-caps", default="0.70,0.80")
    parser.add_argument("--staged-entry", default="0.50,0.80,1.00")
    parser.add_argument("--score-sources", default="future_market,monster_future,leader_onset_sec")
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
