#!/usr/bin/env python3
"""Research-only concentrated v2 leader-hold / replacement challenger.

The existing concentrated sleeve has the best path toward the high-CAGR target,
but broker-ledger evidence shows too much alpha still leaks through drawdowns,
fees, and stale holdings. This challenger builds a broker-replayable target book
from point-in-time candidate rows with four explicit rules:

- keep true winners while their thesis/relative strength is intact;
- replace weak or stale holdings with stronger same-date leaders before cash;
- stage new entries unless the evidence is exceptional;
- keep cash low in green/bull regimes and raise it only in confirmed weak regimes.

This script is research-only. Production defaults are unchanged. The generated
`monthly_holdings.csv` must be evaluated with `run_broker_ledger_replay.py` for
official-style evidence.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from r1000_concentrated_policy import concentrated_conviction_score  # noqa: E402
from tools.historical_replay_lib import (  # noqa: E402
    blocked_payload,
    calc_metrics,
    equity_curve_rows,
    infer_return_col,
    normalize_rebalance_frame,
    read_table,
    repo_path,
    safe_float,
    turnover,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUT_DIR = "outputs/concentrated_v2_challenger"

REGIME_POLICY = {
    "deep_bear": {"target_n": 1, "single_cap": 0.25, "cash_floor": 0.35, "group_cap": 0.60},
    "bear": {"target_n": 2, "single_cap": 0.35, "cash_floor": 0.15, "group_cap": 0.75},
    "neutral": {"target_n": 3, "single_cap": 0.50, "cash_floor": 0.00, "group_cap": 0.90},
    "bull": {"target_n": 3, "single_cap": 0.50, "cash_floor": 0.00, "group_cap": 0.95},
    "strong_bull": {"target_n": 3, "single_cap": 0.50, "cash_floor": 0.00, "group_cap": 0.95},
}

SCORE_RANK_COLUMNS = [
    "score_total",
    "score",
    "concentrated_score",
    "oneil_leadership_score",
    "industry_group_strength_score",
    "future_winner_scout_score",
    "rs_acceleration_score",
    "relative_strength_composite",
    "entry_quality_score",
    "selection_confirmation_score",
]
RISK_RANK_COLUMNS = [
    "portfolio_risk_entry_block_score",
    "portfolio_stale_mega_leader_score",
    "risk_penalty",
    "stage2_overext_penalty",
    "overheat_penalty",
]


def clean_ticker(value: Any) -> str:
    ticker = str(value or "").upper().strip()
    return "" if ticker in {"", "NAN", "NONE", "CASH", "__CASH__"} else ticker


def rank01(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() <= 1:
        return pd.Series(0.5, index=series.index)
    return numeric.rank(pct=True, ascending=higher_is_better).fillna(0.5).clip(0.0, 1.0)


def clip01(value: Any) -> float:
    return max(0.0, min(1.0, safe_float(value, 0.0)))


def score_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["ticker"] = out["ticker"].map(clean_ticker)
    out = out[out["ticker"].ne("")].copy()
    if out.empty:
        return out

    for col in SCORE_RANK_COLUMNS:
        if col in out.columns:
            out[f"rank_{col}"] = out.groupby("rebalance_date", group_keys=False)[col].apply(rank01)
    for col in RISK_RANK_COLUMNS:
        if col in out.columns:
            out[f"rank_{col}_low"] = out.groupby("rebalance_date", group_keys=False)[col].apply(lambda s: rank01(s, higher_is_better=False))

    def row_score(row: pd.Series) -> float:
        conviction = concentrated_conviction_score(row.to_dict())
        score = (
            0.72 * clip01(row.get("portfolio_future_winner_engine_score"))
            + 0.14 * clip01(row.get("portfolio_monster_early_score"))
            + 0.05 * clip01(row.get("h6_dynamic_leader_score"))
            + 0.04 * safe_float(row.get("rank_score_total"), safe_float(row.get("rank_score"), 0.5))
            + 0.02 * safe_float(row.get("rank_industry_group_strength_score"), 0.5)
            + 0.02 * safe_float(row.get("rank_rs_acceleration_score"), 0.5)
            + 0.01 * clip01(conviction)
        )
        risk = (
            0.35 * clip01(row.get("portfolio_risk_entry_block_score"))
            + 0.30 * clip01(row.get("portfolio_stale_mega_leader_score"))
            + 0.15 * clip01(row.get("stage2_overext_penalty"))
            + 0.10 * clip01(row.get("overheat_penalty"))
            + 0.10 * max(0.0, -safe_float(row.get("rs_benchmark_3m"), 0.0))
        )
        return max(0.0, min(1.0, score - 0.10 * risk))

    out["concentrated_v2_score"] = out.apply(row_score, axis=1)
    out["concentrated_v2_rank"] = out.groupby("rebalance_date")["concentrated_v2_score"].rank(method="first", ascending=False)
    return out


def gate_allows(row: pd.Series, *, min_market_cap_usd: float, min_dollar_volume_usd: float) -> tuple[bool, str]:
    mktcap = max(safe_float(row.get("market_cap_live"), 0.0), safe_float(row.get("mktcap"), 0.0))
    dollar_vol = safe_float(row.get("dollar_vol_20d"), 0.0)
    if mktcap < min_market_cap_usd:
        return False, "market_cap_below_floor"
    if dollar_vol < min_dollar_volume_usd:
        return False, "dollar_volume_below_floor"
    if clip01(row.get("portfolio_risk_entry_block_score")) >= 0.90:
        return False, "risk_entry_block"
    if clip01(row.get("portfolio_stale_mega_leader_score")) >= 0.90:
        return False, "stale_candidate_block"
    label = str(row.get("portfolio_candidate_gate_label") or "").lower()
    hard_reject = any(token in label for token in ["reject", "blocked", "failed", "fail"])
    monster = max(
        clip01(row.get("portfolio_monster_early_score")),
        clip01(row.get("portfolio_future_winner_engine_score")),
        clip01(row.get("h6_dynamic_leader_score")),
    )
    if hard_reject and monster < 0.80:
        return False, f"candidate_gate_{label or 'rejected'}"
    if hard_reject:
        return True, "monster_gate_override"
    return True, "pass"


def is_broken_holding(row: pd.Series | None, score: float) -> tuple[bool, str]:
    if row is None:
        return True, "missing_from_candidate_book"
    stale = clip01(row.get("portfolio_stale_mega_leader_score"))
    risk = clip01(row.get("portfolio_risk_entry_block_score"))
    rs3 = safe_float(row.get("rs_benchmark_3m"), 0.0)
    rs_accel = safe_float(row.get("rs_acceleration_score"), 0.0)
    monster = clip01(row.get("portfolio_monster_early_score"))
    long_hold = safe_float(row.get("long_hold_compounder_score"), 0.0)
    rank = safe_float(row.get("concentrated_v2_rank"), 999.0)
    protected = (monster >= 0.78 or long_hold >= 0.85) and score >= 0.55 and rank <= 12
    reasons: list[str] = []
    if stale >= 0.55:
        reasons.append("stale_leader")
    if risk >= 0.78:
        reasons.append("risk_block")
    if rs3 <= -0.12:
        reasons.append("benchmark_lag_3m")
    if rs_accel <= -0.18:
        reasons.append("negative_rs_accel")
    if score <= 0.45:
        reasons.append("low_concentrated_v2_score")
    if rank > 10:
        reasons.append("leader_rank_decay")
    if protected and not {"stale_leader", "risk_block"}.intersection(reasons):
        return False, "protected_winner"
    return bool(reasons), "+".join(reasons) if reasons else "intact"


def regime_policy(regime: str, *, target_n_override: int | None, single_cap_override: float | None) -> dict[str, float]:
    base = dict(REGIME_POLICY.get(str(regime or "neutral").lower(), REGIME_POLICY["neutral"]))
    if target_n_override is not None:
        base["target_n"] = int(target_n_override)
    if single_cap_override is not None:
        base["single_cap"] = float(single_cap_override)
    return base


def group_key(row: pd.Series) -> str:
    for col in ("theme_phase_primary", "theme_horizon_primary", "industry_group", "sector"):
        text = str(row.get(col) or "").strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return "unknown"


def allocate_weights(selected: list[pd.Series], previous: dict[str, float], policy: dict[str, float]) -> tuple[dict[str, float], dict[str, str]]:
    if not selected:
        return {}, {}
    invested = max(0.0, min(1.0, 1.0 - safe_float(policy.get("cash_floor"), 0.0)))
    single_cap = max(0.05, min(1.0, safe_float(policy.get("single_cap"), 0.50)))
    group_cap = max(single_cap, min(1.0, safe_float(policy.get("group_cap"), 0.85)))
    raw: dict[str, float] = {}
    caps: dict[str, float] = {}
    stages: dict[str, str] = {}
    groups: dict[str, str] = {}
    for row in selected:
        ticker = clean_ticker(row.get("ticker"))
        if not ticker:
            continue
        score = max(0.05, safe_float(row.get("concentrated_v2_score"), 0.0))
        raw[ticker] = score * score
        if ticker in previous:
            stage = 1.0
            stages[ticker] = "held_full"
        else:
            monster = max(
                clip01(row.get("portfolio_monster_early_score")),
                clip01(row.get("h6_dynamic_leader_score")),
                safe_float(row.get("concentrated_v2_score"), 0.0),
            )
            if monster >= 0.78:
                stage = 1.0
                stages[ticker] = "new_full_exceptional"
            elif monster >= 0.64:
                stage = 0.80
                stages[ticker] = "new_stage_80"
            else:
                stage = 0.65
                stages[ticker] = "new_stage_65"
        caps[ticker] = single_cap * stage
        groups[ticker] = group_key(row)

    weights = {ticker: 0.0 for ticker in raw}
    remaining = invested
    active = set(raw)
    while active and remaining > 1e-9:
        total_raw = sum(raw[t] for t in active)
        if total_raw <= 0:
            break
        used = 0.0
        for ticker in list(active):
            proposed = remaining * raw[ticker] / total_raw
            add = min(proposed, max(0.0, caps[ticker] - weights[ticker]))
            weights[ticker] += add
            used += add
            if caps[ticker] - weights[ticker] <= 1e-9:
                active.remove(ticker)
        if used <= 1e-12:
            break
        remaining -= used

    # Same-theme/industry cap. Excess is moved to cash rather than forced into a
    # weaker third name, keeping this challenger honest under broker replay.
    group_totals: dict[str, float] = {}
    for ticker, weight in weights.items():
        group_totals[groups.get(ticker, "unknown")] = group_totals.get(groups.get(ticker, "unknown"), 0.0) + weight
    for grp, total in group_totals.items():
        if total <= group_cap:
            continue
        scale = group_cap / total if total > 0 else 1.0
        for ticker, weight in list(weights.items()):
            if groups.get(ticker, "unknown") == grp:
                weights[ticker] = weight * scale
                stages[ticker] = stages.get(ticker, "") + "|group_cap_scaled"
    return {ticker: weight for ticker, weight in weights.items() if weight > 1e-10}, stages


def replay(
    candidate_book: Path,
    output_dir: Path,
    *,
    cost_bps: float,
    target_n: int | None,
    single_cap: float | None,
    min_market_cap_usd: float,
    min_dollar_volume_usd: float,
) -> dict[str, Any]:
    frame = normalize_rebalance_frame(read_table(candidate_book))
    if frame.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "concentrated_v2_challenger")
    return_col = infer_return_col(frame)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "concentrated_v2_challenger")
    frame = score_candidates(frame)

    prev_weights: dict[str, float] = {}
    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    for dt, group in frame.groupby("rebalance_date", sort=True):
        period = group.sort_values("concentrated_v2_score", ascending=False).copy()
        regime = str(period["regime_state"].dropna().astype(str).iloc[0]) if "regime_state" in period.columns and not period.empty else "neutral"
        policy = regime_policy(regime, target_n_override=target_n, single_cap_override=single_cap)
        target_count = int(policy.get("target_n", 3))
        candidate_by_ticker = {clean_ticker(row.get("ticker")): row for _, row in period.iterrows()}

        selected: list[pd.Series] = []
        selected_tickers: set[str] = set()
        for ticker in sorted(prev_weights, key=lambda t: prev_weights[t], reverse=True):
            row = candidate_by_ticker.get(ticker)
            score = safe_float(row.get("concentrated_v2_score"), 0.0) if row is not None else 0.0
            broken, reason = is_broken_holding(row, score)
            decision_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "decision": "drop" if broken else "hold",
                    "reason": reason,
                    "score": score,
                    "previous_weight": prev_weights.get(ticker, 0.0),
                }
            )
            if not broken and row is not None and len(selected) < target_count:
                selected.append(row)
                selected_tickers.add(ticker)

        for _, row in period.iterrows():
            if len(selected) >= target_count:
                break
            ticker = clean_ticker(row.get("ticker"))
            if not ticker or ticker in selected_tickers:
                continue
            allowed, gate_reason = gate_allows(row, min_market_cap_usd=min_market_cap_usd, min_dollar_volume_usd=min_dollar_volume_usd)
            if not allowed:
                continue
            selected.append(row)
            selected_tickers.add(ticker)
            decision_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "decision": "add",
                    "reason": gate_reason,
                    "score": safe_float(row.get("concentrated_v2_score"), 0.0),
                    "previous_weight": prev_weights.get(ticker, 0.0),
                }
            )

        weights, stage_labels = allocate_weights(selected, prev_weights, policy)
        turn = turnover(prev_weights, weights)
        gross_return = 0.0
        names: list[str] = []
        for row in selected:
            ticker = clean_ticker(row.get("ticker"))
            weight = safe_float(weights.get(ticker), 0.0)
            if weight <= 0:
                continue
            ret = safe_float(row.get(return_col), 0.0)
            gross_return += weight * ret
            names.append(ticker)
            holding_rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "Name": row.get("Name", ""),
                    "sector": row.get("sector", ""),
                    "industry_group": row.get("industry_group", ""),
                    "weight": weight,
                    "period_forward_return": ret,
                    "weighted_forward_return": weight * ret,
                    "concentrated_v2_score": row.get("concentrated_v2_score"),
                    "concentrated_v2_stage": stage_labels.get(ticker, ""),
                    "concentrated_v2_group": group_key(row),
                    "regime_state": regime,
                    "portfolio_sleeve_label": row.get("portfolio_sleeve_label", ""),
                    "portfolio_candidate_gate_label": row.get("portfolio_candidate_gate_label", ""),
                    "portfolio_future_winner_engine_score": row.get("portfolio_future_winner_engine_score", ""),
                    "portfolio_monster_early_score": row.get("portfolio_monster_early_score", ""),
                    "portfolio_stale_mega_leader_score": row.get("portfolio_stale_mega_leader_score", ""),
                    "portfolio_risk_entry_block_score": row.get("portfolio_risk_entry_block_score", ""),
                    "rs_benchmark_3m": row.get("rs_benchmark_3m", ""),
                    "rs_acceleration_score": row.get("rs_acceleration_score", ""),
                    "theme_horizon_primary": row.get("theme_horizon_primary", ""),
                    "theme_holding_profile_primary": row.get("theme_holding_profile_primary", ""),
                    "research_only_backtest": True,
                    "production_activation_allowed": False,
                }
            )
        cost = turn * (cost_bps / 10000.0)
        net_return = gross_return - cost
        monthly_rows.append(
            {
                "rebalance_date": dt,
                "regime_state": regime,
                "target_n": target_count,
                "single_name_cap": policy.get("single_cap"),
                "cash_floor": policy.get("cash_floor"),
                "gross_return": gross_return,
                "cost": cost,
                "turnover": turn,
                "net_return": net_return,
                "cash_weight": max(0.0, 1.0 - sum(weights.values())),
                "n_positions": len(weights),
                "selected_tickers": ",".join(names),
            }
        )
        prev_weights = weights

    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "experiment_id": "concentrated_v2_challenger",
            "status": "completed",
            "data_mode": "historical_candidate_replay_book",
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "research_only": True,
            "production_activation_allowed": False,
            "broker_ledger_required_for_official_verdict": True,
            "used_forward_return_for_selection": False,
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_position_count": sum(safe_float(row.get("n_positions")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "max_single_cap": max((safe_float(row.get("single_name_cap")) for row in monthly_rows), default=None),
            "target_n_override": target_n,
            "single_cap_override": single_cap,
            "min_market_cap_usd": min_market_cap_usd,
            "min_dollar_volume_usd": min_dollar_volume_usd,
        }
    )
    curve = equity_curve_rows(monthly_rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "monthly_holdings.csv", holding_rows)
    write_rows(output_dir / "target_book.csv", holding_rows)
    write_rows(output_dir / "decisions.csv", decision_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Concentrated v2 Challenger",
            "",
            "Research-only concentrated target-book challenger. Production defaults are unchanged.",
            "",
            f"- Status: `{metrics.get('status')}`",
            f"- Months: {metrics.get('months')}",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Avg positions: {safe_float(metrics.get('avg_position_count')):.2f}",
            f"- Avg monthly turnover: {safe_float(metrics.get('avg_turnover_monthly')):.2%}",
            "",
            "The companion broker-ledger replay is required for production-compatible evidence.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=50.0)
    parser.add_argument("--target-n", type=int, default=None)
    parser.add_argument("--single-cap", type=float, default=None)
    parser.add_argument("--min-market-cap-usd", type=float, default=1_000_000_000.0)
    parser.add_argument("--min-dollar-volume-usd", type=float, default=5_000_000.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    if not candidate_book.exists():
        blocked_payload("missing reports/candidate_replay_book.csv from full rebuild", candidate_book, output_dir, "concentrated_v2_challenger")
        return 0
    payload = replay(
        candidate_book,
        output_dir,
        cost_bps=args.cost_bps,
        target_n=args.target_n,
        single_cap=args.single_cap,
        min_market_cap_usd=args.min_market_cap_usd,
        min_dollar_volume_usd=args.min_dollar_volume_usd,
    )
    print(f"[concentrated-v2] wrote {output_dir / 'metrics.json'} status={payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
