#!/usr/bin/env python3
"""Research-only lifecycle overlay on existing monthly portfolio picks.

This tests the user's desired behavior directly:
monthly review, not monthly churn. The baseline engine still discovers names;
this overlay keeps confirmed winners longer, scales them by lifecycle stage,
holds likely shakeouts, and exits persistent stale/distribution behavior.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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
    turnover,
    worst_month_rows,
    write_json,
    write_rows,
    write_text,
)
from run_monster_lifecycle_replay import (  # noqa: E402
    POLICIES,
    classify_exit,
    distribution_risk_score,
    entry_qualified,
    monster_onset_score,
    next_stage,
    normalize_weights,
    trend_ok,
)


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUT_DIR = "outputs/lifecycle_review_overlay_main"


STAGE_MULTIPLIER = {
    "scout": 0.55,
    "confirm": 0.85,
    "winner": 1.20,
    "monster": 1.45,
}


def scale_weights_up(weights: dict[str, float], capacity: float, max_single: float) -> dict[str, float]:
    out = {ticker: min(max(weight, 0.0), max_single) for ticker, weight in weights.items() if weight > 0}
    for _ in range(8):
        total = sum(out.values())
        if total <= 0 or total >= capacity - 1e-10:
            break
        eligible = {ticker: weight for ticker, weight in out.items() if weight < max_single - 1e-10}
        if not eligible:
            break
        eligible_total = sum(eligible.values())
        if eligible_total <= 0:
            break
        needed = capacity - total
        changed = False
        for ticker, weight in list(eligible.items()):
            add = needed * weight / eligible_total
            new_weight = min(max_single, out[ticker] + add)
            if new_weight > out[ticker]:
                changed = True
            out[ticker] = new_weight
        if not changed:
            break
    return out


def row_key(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or "").upper().strip()


def replay(
    monthly_weights: Path,
    candidate_book: Path,
    output_dir: Path,
    policy_name: str = "lifecycle_review_main",
    cost_bps: float = 50.0,
) -> dict[str, Any]:
    policy = dict(POLICIES[policy_name])
    monthly = normalize_rebalance_frame(read_table(monthly_weights))
    candidates = normalize_rebalance_frame(read_table(candidate_book))
    if monthly.empty:
        return blocked_payload("monthly weights are empty", monthly_weights, output_dir, "lifecycle_review_overlay")
    if candidates.empty:
        return blocked_payload("candidate replay book is empty", candidate_book, output_dir, "lifecycle_review_overlay")
    return_col = infer_return_col(candidates)
    if return_col is None:
        return blocked_payload("candidate replay book has no period return column", candidate_book, output_dir, "lifecycle_review_overlay")

    candidate_by_date: dict[str, dict[str, dict[str, Any]]] = {}
    for dt, group in candidates.groupby("rebalance_date", sort=True):
        candidate_by_date[str(dt)] = {row_key(row): row for row in group.to_dict("records") if row_key(row)}

    state: dict[str, dict[str, Any]] = {}
    prev_weights: dict[str, float] = {}
    monthly_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for dt, rec_group in monthly.groupby("rebalance_date", sort=True):
        dt_key = str(dt)
        rec_rows = [row for row in rec_group.to_dict("records") if row_key(row)]
        rec_by_ticker = {row_key(row): row for row in rec_rows}
        by_ticker = dict(candidate_by_date.get(dt_key, {}))
        for ticker, rec_row in rec_by_ticker.items():
            merged = dict(by_ticker.get(ticker, {}))
            merged.update(rec_row)
            by_ticker[ticker] = merged
        cash_target = max(safe_float(rec_rows[0].get("cash_target"), 0.0) if rec_rows else 0.0, 0.0)
        baseline_invested = min(1.0, max(sum(max(safe_float(row.get("weight")), 0.0) for row in rec_rows), 1.0 - cash_target))

        raw_weights: dict[str, float] = {}
        active_state: dict[str, dict[str, Any]] = {}
        for ticker, pos in list(state.items()):
            row = by_ticker.get(ticker)
            if not row:
                event_rows.append({"rebalance_date": dt_key, "ticker": ticker, "action": "exit", "reason": "missing_return_row", "stage": pos.get("stage")})
                continue
            cum_before = safe_float(pos.get("cum_return"))
            peak_before = safe_float(pos.get("peak_return"))
            action, reason, next_bad_months = classify_exit(
                row,
                safe_float(pos.get("last_return"), 0.0),
                cum_before,
                peak_before,
                pos,
                policy,
            )
            if action == "exit":
                event_rows.append({"rebalance_date": dt_key, "ticker": ticker, "action": "exit", "reason": reason, "stage": pos.get("stage")})
                continue
            score = monster_onset_score(row)
            stage = next_stage(str(pos.get("stage", "scout")), score, cum_before, int(pos.get("months_held", 0)), policy)
            baseline_weight = safe_float(rec_by_ticker.get(ticker, {}).get("weight"), safe_float(pos.get("last_weight"), 0.0) * 0.98)
            weight = baseline_weight * STAGE_MULTIPLIER.get(stage, 1.0)
            if action == "trim":
                weight *= safe_float(policy.get("trim_scale"), 0.5)
            raw_weights[ticker] = max(weight, 0.0)
            active_state[ticker] = {
                "stage": stage,
                "cum_return": cum_before,
                "peak_return": peak_before,
                "months_held": int(pos.get("months_held", 0)),
                "last_score": score,
                "last_return": safe_float(pos.get("last_return"), 0.0),
                "last_weight": weight,
                "bad_months": next_bad_months,
            }
            event_rows.append({"rebalance_date": dt_key, "ticker": ticker, "action": action, "reason": reason, "stage": stage, "score": score})

        slots = max(0, int(policy.get("max_total_positions", 12)) - len(active_state))
        new_limit = min(slots, int(policy.get("max_new_scouts_per_month", 3)))
        if new_limit > 0:
            entrants: list[dict[str, Any]] = []
            for rec_row in sorted(rec_rows, key=lambda r: safe_float(r.get("weight")), reverse=True):
                ticker = row_key(rec_row)
                if not ticker or ticker in active_state:
                    continue
                row = dict(by_ticker.get(ticker, rec_row))
                score = monster_onset_score(row)
                baseline_entry_ok = (
                    score >= safe_float(policy.get("min_entry_score"), 0.60) * 0.55
                    and distribution_risk_score(row) < 0.85
                    and (trend_ok(row) or row.get("price_above_ma50", "") == "" or row.get("price_above_ma200", "") == "")
                )
                if entry_qualified(row, score, policy) or baseline_entry_ok:
                    item = dict(row)
                    item["monster_onset_score"] = score
                    entrants.append(item)
            entrants.sort(key=lambda r: (safe_float(r.get("monster_onset_score")), safe_float(r.get("weight"))), reverse=True)
            for row in entrants[:new_limit]:
                ticker = row_key(row)
                weight = min(max(safe_float(row.get("weight")), 0.0) * STAGE_MULTIPLIER["scout"], safe_float(policy.get("scout_weight"), 0.03))
                raw_weights[ticker] = max(weight, 0.0)
                active_state[ticker] = {
                    "stage": "scout",
                    "cum_return": 0.0,
                    "peak_return": 0.0,
                    "months_held": 0,
                    "last_score": safe_float(row.get("monster_onset_score")),
                    "last_return": 0.0,
                    "last_weight": weight,
                    "bad_months": 0,
                }
                event_rows.append({"rebalance_date": dt_key, "ticker": ticker, "action": "enter", "reason": "baseline_lifecycle_scout", "stage": "scout", "score": row.get("monster_onset_score")})

        max_single = safe_float(policy.get("max_single_name_weight"), 0.33)
        weights = normalize_weights(raw_weights, baseline_invested, max_single)
        weights = scale_weights_up(weights, baseline_invested, max_single)
        month_turnover = turnover(prev_weights, weights)
        gross_return = 0.0
        next_state: dict[str, dict[str, Any]] = {}
        for ticker, weight in weights.items():
            row = by_ticker.get(ticker, {})
            pos = active_state.get(ticker, {})
            ret = safe_float(row.get(return_col), 0.0)
            cum_before = safe_float(pos.get("cum_return"))
            cum_after = (1.0 + cum_before) * (1.0 + ret) - 1.0
            peak_after = max(safe_float(pos.get("peak_return")), cum_after)
            next_state[ticker] = {
                "stage": pos.get("stage", "scout"),
                "cum_return": cum_after,
                "peak_return": peak_after,
                "months_held": int(pos.get("months_held", 0)) + 1,
                "last_score": safe_float(pos.get("last_score")),
                "last_return": ret,
                "last_weight": weight,
                "bad_months": int(pos.get("bad_months", 0)),
            }
            gross_return += weight * ret
            holding_rows.append(
                {
                    "rebalance_date": dt_key,
                    "ticker": ticker,
                    "weight": weight,
                    "baseline_weight": rec_by_ticker.get(ticker, {}).get("weight", ""),
                    "stage": pos.get("stage"),
                    "months_held": next_state[ticker]["months_held"],
                    "cum_return": cum_after,
                    "peak_return": peak_after,
                    "period_forward_return": ret,
                    "weighted_forward_return": weight * ret,
                    "monster_onset_score": pos.get("last_score"),
                    "sector": row.get("sector", ""),
                    "portfolio_defensive_rotation_action": row.get("portfolio_defensive_rotation_action", ""),
                }
            )
        cost = month_turnover * (cost_bps / 10000.0)
        net_return = gross_return - cost
        monthly_rows.append(
            {
                "rebalance_date": dt_key,
                "policy": policy_name,
                "gross_return": gross_return,
                "cost": cost,
                "turnover": month_turnover,
                "net_return": net_return,
                "cash_weight": max(0.0, 1.0 - sum(weights.values())),
                "n_positions": len(weights),
                "selected_tickers": ",".join(weights.keys()),
                "baseline_recommendation_count": len(rec_rows),
                "carried_count": sum(1 for ticker in weights if ticker not in rec_by_ticker),
            }
        )
        state = next_state
        prev_weights = weights

    curve = equity_curve_rows(monthly_rows)
    metrics = calc_metrics([safe_float(row.get("net_return")) for row in monthly_rows])
    metrics.update(
        {
            "experiment_id": "lifecycle_review_overlay",
            "status": "completed",
            "policy": policy_name,
            "data_mode": "main_monthly_weights_plus_candidate_replay_book",
            "monthly_weights": str(monthly_weights),
            "candidate_book": str(candidate_book),
            "return_column": return_col,
            "avg_cash_weight": sum(safe_float(row.get("cash_weight")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "avg_turnover_monthly": sum(safe_float(row.get("turnover")) for row in monthly_rows) / max(len(monthly_rows), 1),
            "research_only": True,
            "production_activation_allowed": False,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "metrics.json", metrics)
    write_rows(output_dir / "monthly.csv", monthly_rows)
    write_rows(output_dir / "holdings.csv", holding_rows)
    write_rows(output_dir / "events.csv", event_rows)
    write_rows(output_dir / "equity_curve.csv", curve)
    write_rows(output_dir / "stress_windows.csv", worst_month_rows(curve))
    write_text(output_dir / "replay_report.md", render_report(metrics))
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Lifecycle Review Overlay",
            "",
            "Research-only overlay on existing monthly portfolio picks.",
            "",
            f"- Policy: `{metrics.get('policy')}`",
            f"- Status: `{metrics.get('status')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Avg turnover: {safe_float(metrics.get('avg_turnover_monthly')):.2%}",
            "",
            "This is not production-active; it tests monthly lifecycle review versus monthly churn.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--monthly-weights", default=None)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--policy", choices=sorted(POLICIES), default="lifecycle_review_main")
    parser.add_argument("--cost-bps", type=float, default=50.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    monthly_weights = repo_path(args.monthly_weights) if args.monthly_weights else latest_run / "reports" / "main_monthly_weights.csv"
    candidate_book = repo_path(args.candidate_book) if args.candidate_book else latest_run / "reports" / "candidate_replay_book.csv"
    output_dir = repo_path(args.output_dir)
    replay(monthly_weights, candidate_book, output_dir, policy_name=args.policy, cost_bps=args.cost_bps)
    print(f"[lifecycle-overlay] wrote {output_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
