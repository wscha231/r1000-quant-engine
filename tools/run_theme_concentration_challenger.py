#!/usr/bin/env python3
"""Historical 1-3 name theme concentration challenger.

This research-only replay tests the user's core hypothesis:

1. Detect the currently dominant theme from point-in-time candidate data.
2. Select only the strongest 1-3 liquid tickers inside that theme.
3. Concentrate with a single-name cap, costs, and basic downside clipping.

It intentionally does not use future returns for selection. The `r_*` columns
are treated as forward labels in this codebase and are used only after weights
are chosen for the month.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from historical_replay_lib import (  # noqa: E402
    blocked_payload,
    calc_metrics,
    equity_curve_rows,
    infer_return_col,
    normalize_rebalance_frame,
    read_table,
    repo_path,
    safe_float,
    score_power_weights,
    turnover,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)
from run_theme_leadership_tape import infer_theme  # noqa: E402


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/theme_concentration_challenger"
EXPERIMENT_ID = "theme_concentration_top3_challenger"


def robust_z(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    x = pd.to_numeric(frame[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    med = float(x.median(skipna=True)) if x.notna().any() else 0.0
    mad = float((x - med).abs().median(skipna=True)) if x.notna().any() else 0.0
    if not math.isfinite(mad) or mad <= 1e-12:
        std = float(x.std(skipna=True, ddof=0)) if x.notna().any() else 0.0
        denom = std if std > 1e-12 else 1.0
        return ((x - med) / denom).fillna(0.0).clip(-6, 6)
    return ((x - med) / (1.4826 * mad)).fillna(0.0).clip(-6, 6)


def numeric(frame: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce").fillna(default)


def first_numeric(frame: pd.DataFrame, cols: tuple[str, ...], default: float = 0.0) -> pd.Series:
    values = [numeric(frame, col, np.nan) for col in cols if col in frame.columns]
    if not values:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.concat(values, axis=1).bfill(axis=1).iloc[:, 0].fillna(default)


def add_theme_and_scores(month: pd.DataFrame) -> pd.DataFrame:
    d = month.copy()
    d["leadership_theme"] = d.apply(infer_theme, axis=1)
    d["mom_1m_current"] = first_numeric(d, ("mom_1m", "ret_1m"))
    d["mom_3m_current"] = first_numeric(d, ("mom_3m", "ret_3m"))
    d["mom_6m_current"] = first_numeric(d, ("mom_6m", "ret_6m"))
    d["rs_benchmark_current"] = first_numeric(d, ("rs_benchmark_3m", "rs_benchmark_6m", "rs_benchmark_12m"))
    d["market_cap_current"] = pd.concat(
        [
            numeric(d, "market_cap_live", np.nan),
            numeric(d, "mktcap", np.nan),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    d["price_current"] = pd.concat(
        [
            numeric(d, "current_price_live", np.nan),
            numeric(d, "px", np.nan),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    d["dollar_vol_current"] = numeric(d, "dollar_vol_20d")
    d["risk_stack"] = pd.concat(
        [
            numeric(d, "risk_penalty"),
            numeric(d, "stage2_overext_penalty"),
            numeric(d, "overheat_penalty"),
            numeric(d, "explosion_exit_score"),
            numeric(d, "live_event_risk_score"),
        ],
        axis=1,
    ).max(axis=1).fillna(0.0)
    d["theme_member_score"] = (
        0.18 * robust_z(d, "score")
        + 0.12 * robust_z(d, "mom_1m_current")
        + 0.08 * robust_z(d, "mom_3m_current")
        + 0.05 * robust_z(d, "mom_6m_current")
        + 0.05 * robust_z(d, "rs_benchmark_current")
        + 0.15 * robust_z(d, "rs_acceleration_score")
        + 0.10 * robust_z(d, "industry_group_strength_score")
        + 0.10 * robust_z(d, "breakout_setup_quality_score")
        + 0.08 * robust_z(d, "h6_dynamic_leader_score")
        + 0.07 * robust_z(d, "portfolio_monster_early_score")
        + 0.07 * robust_z(np.log1p(d["dollar_vol_current"].clip(lower=0)).to_frame("log_dv"), "log_dv")
        + 0.05 * robust_z(d, "theme_phase_multiplier_max")
        - 0.20 * d["risk_stack"].clip(lower=0.0)
    )
    return d


def liquidity_filter(frame: pd.DataFrame, min_mcap: float, min_dollar_vol: float, min_price: float) -> pd.DataFrame:
    d = frame.copy()
    return d[
        (d["market_cap_current"] >= float(min_mcap))
        & (d["dollar_vol_current"] >= float(min_dollar_vol))
        & (d["price_current"] >= float(min_price))
    ].copy()


def rank_themes(month: pd.DataFrame, min_theme_members: int, allow_single_name_theme: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for theme, group in month.groupby("leadership_theme"):
        g = group.sort_values("theme_member_score", ascending=False)
        if not allow_single_name_theme and len(g) < int(min_theme_members):
            continue
        top = g.head(8)
        rows.append(
            {
                "leadership_theme": theme,
                "member_count": int(len(g)),
                "top3_mean_member_score": float(g.head(3)["theme_member_score"].mean()),
                "median_mom_1m": float(pd.to_numeric(g["mom_1m_current"], errors="coerce").median(skipna=True)),
                "breadth_mom_1m_positive": float((pd.to_numeric(g["mom_1m_current"], errors="coerce") > 0).mean()),
                "total_dollar_vol_20d": float(pd.to_numeric(g["dollar_vol_current"], errors="coerce").sum()),
                "top_tickers": ",".join(top["ticker"].astype(str).head(8)),
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["theme_attention_score"] = (
        0.45 * robust_z(out, "top3_mean_member_score")
        + 0.20 * robust_z(out, "median_mom_1m")
        + 0.15 * out["breadth_mom_1m_positive"].fillna(0.0)
        + 0.20 * robust_z(np.log1p(out["total_dollar_vol_20d"].clip(lower=0)).to_frame("log_dv"), "log_dv")
    )
    return out.sort_values("theme_attention_score", ascending=False).reset_index(drop=True)


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Theme Concentration Challenger",
            "",
            "Research-only replay: select the strongest current theme each month and hold at most three liquid leaders.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Months: {metrics.get('months')}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Average positions: {safe_float(metrics.get('avg_positions')):.2f}",
            f"- Average invested: {safe_float(metrics.get('avg_invested')):.2%}",
            "",
            "Selection uses only same-month candidate features such as `mom_*`, relative strength, liquidity, and setup scores; forward `r_*` labels are applied only after weights are fixed.",
            "ETF look-through remains a daily/latest discovery aid; historical replay uses point-in-time candidate theme leadership to avoid latest-holdings bias.",
            "",
        ]
    )


def replay(
    candidate_book: Path,
    output_dir: Path,
    *,
    top_n: int = 3,
    single_name_cap: float = 0.50,
    min_mcap: float = 5_000_000_000,
    min_dollar_vol: float = 20_000_000,
    min_price: float = 10.0,
    min_theme_members: int = 2,
    allow_single_name_theme: bool = False,
    cost_bps: float = 50.0,
    hard_stop_proxy: float = -0.20,
) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, EXPERIMENT_ID)
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no usable forward return column", candidate_book, output_dir, EXPERIMENT_ID)

    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    theme_rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    for dt, group in frame.groupby("rebalance_date", sort=True):
        scored = add_theme_and_scores(group)
        liquid = liquidity_filter(scored, min_mcap=min_mcap, min_dollar_vol=min_dollar_vol, min_price=min_price)
        theme_rank = rank_themes(liquid, min_theme_members=min_theme_members, allow_single_name_theme=allow_single_name_theme)
        for rank, row in enumerate(theme_rank.to_dict("records"), start=1):
            theme_rows.append({"rebalance_date": dt, "theme_rank": rank, **row})
        if theme_rank.empty:
            weights: dict[str, float] = {}
            selected_theme = ""
            selected = pd.DataFrame()
        else:
            selected_theme = str(theme_rank.iloc[0]["leadership_theme"])
            selected = liquid[liquid["leadership_theme"].eq(selected_theme)].sort_values("theme_member_score", ascending=False).head(int(top_n))
            weights = score_power_weights(selected.to_dict("records"), "theme_member_score", single_name_cap=single_name_cap)

        lookup = {str(row.get("ticker") or "").upper(): row for row in selected.to_dict("records")}
        gross_return = 0.0
        for ticker, weight in weights.items():
            source = lookup.get(ticker, {})
            raw_ret = safe_float(source.get(return_col), 0.0)
            clipped_ret = max(raw_ret, float(hard_stop_proxy))
            gross_return += weight * clipped_ret
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "weight": weight,
                    "selected_theme": selected_theme,
                    "theme_member_score": source.get("theme_member_score"),
                    "raw_period_forward_return": raw_ret,
                    "risk_clipped_return": clipped_ret,
                    "weighted_forward_return": weight * clipped_ret,
                    "market_cap_current": source.get("market_cap_current"),
                    "dollar_vol_current": source.get("dollar_vol_current"),
                    "mom_1m_current": source.get("mom_1m_current"),
                    "mom_3m_current": source.get("mom_3m_current"),
                    "mom_6m_current": source.get("mom_6m_current"),
                    "rs_benchmark_current": source.get("rs_benchmark_current"),
                    "rs_acceleration_score": source.get("rs_acceleration_score"),
                    "breakout_setup_quality_score": source.get("breakout_setup_quality_score"),
                    "industry_group_strength_score": source.get("industry_group_strength_score"),
                }
            )
        turn = turnover(prev_weights, weights)
        cost = turn * (float(cost_bps) / 10000.0)
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "selected_theme": selected_theme,
                "selected_tickers": ",".join(weights.keys()),
                "n_positions": len(weights),
                "invested_weight": sum(weights.values()),
                "cash_weight": max(0.0, 1.0 - sum(weights.values())),
                "gross_return": gross_return,
                "turnover": turn,
                "cost": cost,
                "net_return": gross_return - cost,
            }
        )
        prev_weights = weights

    returns = [safe_float(row.get("net_return")) for row in monthly_rows]
    metrics = calc_metrics(returns)
    metrics.update(
        {
            "experiment_id": EXPERIMENT_ID,
            "status": "completed",
            "data_mode": "candidate_replay_book_theme_proxy",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "top_n": int(top_n),
            "single_name_cap": float(single_name_cap),
            "min_mcap": float(min_mcap),
            "min_dollar_vol": float(min_dollar_vol),
            "min_price": float(min_price),
            "min_theme_members": int(min_theme_members),
            "allow_single_name_theme": bool(allow_single_name_theme),
            "cost_bps": float(cost_bps),
            "hard_stop_proxy": float(hard_stop_proxy),
            "avg_positions": float(np.mean([safe_float(row.get("n_positions")) for row in monthly_rows])) if monthly_rows else 0.0,
            "avg_invested": float(np.mean([safe_float(row.get("invested_weight")) for row in monthly_rows])) if monthly_rows else 0.0,
            "research_only": True,
            "production_activation_allowed": False,
        }
    )
    curve = equity_curve_rows(monthly_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "holdings.csv", holding_rows)
    write_rows(output_dir / "theme_rankings.csv", theme_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--single-name-cap", type=float, default=0.50)
    parser.add_argument("--min-mcap", type=float, default=5_000_000_000)
    parser.add_argument("--min-dollar-vol", type=float, default=20_000_000)
    parser.add_argument("--min-price", type=float, default=10.0)
    parser.add_argument("--min-theme-members", type=int, default=2)
    parser.add_argument("--allow-single-name-theme", action="store_true")
    parser.add_argument("--cost-bps", type=float, default=50.0)
    parser.add_argument("--hard-stop-proxy", type=float, default=-0.20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, EXPERIMENT_ID)
        return 0
    payload = replay(
        candidate_book,
        output_dir,
        top_n=args.top_n,
        single_name_cap=args.single_name_cap,
        min_mcap=args.min_mcap,
        min_dollar_vol=args.min_dollar_vol,
        min_price=args.min_price,
        min_theme_members=args.min_theme_members,
        allow_single_name_theme=args.allow_single_name_theme,
        cost_bps=args.cost_bps,
        hard_stop_proxy=args.hard_stop_proxy,
    )
    print(f"[theme-concentration] wrote {output_dir / 'metrics.json'}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
