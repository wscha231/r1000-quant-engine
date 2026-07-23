#!/usr/bin/env python3
"""Review AlphaOps daily/weekly/monthly decision cadence.

This sidecar does not mutate production targets. It makes the operating
cadence explicit:

* daily: crisis/reentry and current-holding deterioration/no-add checks
* weekly: current holdings plus watchlist RS/technical/valuation refresh
* monthly/event: full universe re-ranking and target book rebuild review
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

from tools.run_weekly_evaluation import load_price_series  # noqa: E402
from tools.run287_crisis_policy import adapt_crisis_state, canonical_state  # noqa: E402


CASH_TICKERS = {"CASH", "__CASH__"}
PORTFOLIOS = ("main", "concentrated")
VALUATION_COLUMNS = [
    "forward_pe_final",
    "pe_ttm",
    "ps_ttm",
    "ev_sales",
    "valuation_blueprint_score",
    "valuation_recovery_score",
    "fcf_margin",
    "sales_growth_yoy",
    "eps_growth_yoy",
    "market_cap_live",
    "dollar_vol_20d",
    "primary_lane",
    "leader_state",
    "leader_tier",
    "leader_chase_risk_score",
    "score",
    "rs_benchmark_3m",
    "rs_benchmark_6m",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def current_holdings(latest_run: Path) -> pd.DataFrame:
    for path in [
        latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv",
        latest_run / "user_current" / "01_current_holdings.csv",
        latest_run / "user_portfolio_reports" / "main_current_operating_holdings_latest.csv",
    ]:
        frame = read_csv(path)
        if not frame.empty:
            return normalize_current(frame)
    return pd.DataFrame(columns=["portfolio_kind", "ticker", "current_weight", "current_value_usd"])


def normalize_current(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.copy()
    if "portfolio_kind" not in d.columns:
        d["portfolio_kind"] = "main"
    if "ticker" not in d.columns:
        d["ticker"] = ""
    d["ticker"] = d["ticker"].map(clean_ticker)
    if "current_weight" not in d.columns:
        weight_col = "weight" if "weight" in d.columns else ""
        d["current_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
    if "current_value_usd" not in d.columns:
        value_col = "market_value_usd" if "market_value_usd" in d.columns else ""
        d["current_value_usd"] = pd.to_numeric(d[value_col], errors="coerce").fillna(0.0) if value_col else 0.0
    d["current_weight"] = pd.to_numeric(d["current_weight"], errors="coerce").fillna(0.0)
    d["current_value_usd"] = pd.to_numeric(d["current_value_usd"], errors="coerce").fillna(0.0)
    return d[(d["ticker"].ne("")) & (~d["ticker"].isin(CASH_TICKERS))].copy()


def latest_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["ticker"] = d["ticker"].map(clean_ticker)
    date_col = next((col for col in ("rebalance_date", "feature_date", "as_of_date", "date") if col in d.columns), "")
    if date_col:
        d[date_col] = pd.to_datetime(d[date_col], errors="coerce")
        d = d.sort_values([date_col, "ticker"])
        return d.dropna(subset=[date_col]).drop_duplicates("ticker", keep="last").copy()
    return d.drop_duplicates("ticker", keep="last").copy()


def valuation_snapshot(latest_run: Path) -> pd.DataFrame:
    frames = [
        read_csv(latest_run / "scored_latest.csv"),
        read_csv(latest_run / "reports" / "candidate_replay_book.csv"),
        read_csv(latest_run / "portfolio_latest.csv"),
        read_csv(latest_run / "concentrated_portfolio_latest.csv"),
    ]
    rows: list[pd.DataFrame] = []
    for frame in frames:
        latest = latest_rows(frame)
        if latest.empty:
            continue
        keep = ["ticker"] + [col for col in VALUATION_COLUMNS if col in latest.columns]
        rows.append(latest[keep].copy())
    if not rows:
        return pd.DataFrame(columns=["ticker"])
    out = pd.concat(rows, ignore_index=True)
    merged: dict[str, dict[str, Any]] = {}
    for rec in out.to_dict("records"):
        ticker = clean_ticker(rec.get("ticker"))
        if not ticker:
            continue
        merged.setdefault(ticker, {"ticker": ticker})
        for key, value in rec.items():
            if key == "ticker":
                continue
            if key not in merged[ticker] or str(merged[ticker].get(key) or "") == "":
                merged[ticker][key] = value
    return pd.DataFrame(merged.values())


def price_return(px: pd.DataFrame, as_of: pd.Timestamp, days: int) -> float:
    if px.empty or "close" not in px.columns:
        return math.nan
    d = px[px.index <= as_of].copy()
    if len(d) < max(2, days // 2):
        return math.nan
    end = safe_float(d["close"].iloc[-1], math.nan)
    start_idx = max(0, len(d) - days - 1)
    start = safe_float(d["close"].iloc[start_idx], math.nan)
    if not math.isfinite(start) or not math.isfinite(end) or start <= 0:
        return math.nan
    return end / start - 1.0


def ma_ratio(px: pd.DataFrame, as_of: pd.Timestamp, window: int) -> float:
    if px.empty or "close" not in px.columns:
        return math.nan
    d = px[px.index <= as_of].copy()
    if len(d) < max(5, window // 2):
        return math.nan
    close = safe_float(d["close"].iloc[-1], math.nan)
    ma = float(pd.to_numeric(d["close"], errors="coerce").tail(window).mean())
    if not math.isfinite(close) or not math.isfinite(ma) or ma <= 0:
        return math.nan
    return close / ma


def drawdown_from_high(px: pd.DataFrame, as_of: pd.Timestamp, days: int = 63) -> float:
    if px.empty or "close" not in px.columns:
        return math.nan
    d = px[px.index <= as_of].tail(days).copy()
    if d.empty:
        return math.nan
    close = safe_float(d["close"].iloc[-1], math.nan)
    high = float(pd.to_numeric(d["close"], errors="coerce").max())
    if not math.isfinite(close) or not math.isfinite(high) or high <= 0:
        return math.nan
    return close / high - 1.0


def price_metrics(price_cache: Path, tickers: set[str]) -> pd.DataFrame:
    bench_prices = {bench: load_price_series(price_cache, bench) for bench in ("SPY", "QQQ")}
    rows: list[dict[str, Any]] = []
    for ticker in sorted(tickers):
        px = load_price_series(price_cache, ticker)
        if px.empty:
            rows.append({"ticker": ticker, "price_available": False})
            continue
        as_of = pd.Timestamp(px.index.max()).normalize()
        ret_1m = price_return(px, as_of, 21)
        ret_3m = price_return(px, as_of, 63)
        ret_6m = price_return(px, as_of, 126)
        spy_3m = price_return(bench_prices.get("SPY", pd.DataFrame()), as_of, 63)
        qqq_3m = price_return(bench_prices.get("QQQ", pd.DataFrame()), as_of, 63)
        rows.append(
            {
                "ticker": ticker,
                "price_available": True,
                "price_latest_date": as_of.date().isoformat(),
                "close": safe_float(px.loc[px.index <= as_of, "close"].iloc[-1], math.nan),
                "ret_1m": ret_1m,
                "ret_3m": ret_3m,
                "ret_6m": ret_6m,
                "spy_excess_3m": ret_3m - spy_3m if math.isfinite(ret_3m) and math.isfinite(spy_3m) else math.nan,
                "qqq_excess_3m": ret_3m - qqq_3m if math.isfinite(ret_3m) and math.isfinite(qqq_3m) else math.nan,
                "price_to_ma50": ma_ratio(px, as_of, 50),
                "price_to_ma200": ma_ratio(px, as_of, 200),
                "drawdown_from_63d_high": drawdown_from_high(px, as_of, 63),
            }
        )
    return pd.DataFrame(rows)


def latest_targets(latest_run: Path) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for portfolio, path in [
        ("main", latest_run / "reports" / "operating_main_target_book.csv"),
        ("concentrated", latest_run / "reports" / "operating_concentrated_target_book.csv"),
    ]:
        d = read_csv(path)
        if d.empty or "ticker" not in d.columns:
            continue
        if "rebalance_date" in d.columns:
            dates = pd.to_datetime(d["rebalance_date"], errors="coerce")
            d = d[dates.eq(dates.max())].copy()
        d["portfolio_kind"] = portfolio
        d["ticker"] = d["ticker"].map(clean_ticker)
        weight_col = "target_weight" if "target_weight" in d.columns else "weight" if "weight" in d.columns else ""
        d["target_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
        rows.append(d[["portfolio_kind", "ticker", "target_weight"]].copy())
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["portfolio_kind", "ticker", "target_weight"])


def watchlist_candidates(latest_run: Path, max_candidates: int) -> pd.DataFrame:
    scored = latest_rows(read_csv(latest_run / "reports" / "candidate_replay_book.csv"))
    if scored.empty:
        scored = latest_rows(read_csv(latest_run / "scored_latest.csv"))
    if scored.empty:
        return pd.DataFrame(columns=["ticker"])
    for col in ("score", "rs_benchmark_3m", "rs_benchmark_6m"):
        if col not in scored.columns:
            scored[col] = 0.0
    scored["rank_score"] = (
        pd.to_numeric(scored["score"], errors="coerce").fillna(0.0)
        + pd.to_numeric(scored["rs_benchmark_3m"], errors="coerce").fillna(0.0)
        + 0.5 * pd.to_numeric(scored["rs_benchmark_6m"], errors="coerce").fillna(0.0)
    )
    return scored.sort_values("rank_score", ascending=False).head(int(max_candidates)).copy()


def crisis_context(latest_run: Path) -> dict[str, Any]:
    integrated_states = read_csv(latest_run / "integrated_theme_leader_crisis_replay" / "daily_crisis_state.csv")
    daily = read_json(latest_run / "daily_crisis_monitor" / "summary.json")
    state = str(daily.get("state") or daily.get("raw_state") or "")
    if not state and not integrated_states.empty and "crisis_state" in integrated_states.columns:
        state = str(integrated_states["crisis_state"].iloc[-1])
    reentry_stage = ""
    reentry_trigger = ""
    if not integrated_states.empty:
        for col in ("reentry_stage", "stage"):
            if col in integrated_states.columns:
                reentry_stage = str(integrated_states[col].iloc[-1])
                break
        for col in ("reentry_trigger", "trigger", "action_reason"):
            if col in integrated_states.columns:
                reentry_trigger = str(integrated_states[col].iloc[-1])
                break
    state = adapt_crisis_state(state, reentry_stage)
    raw_state = adapt_crisis_state(daily.get("raw_state"), reentry_stage)
    latest_integrated_state = (
        adapt_crisis_state(
            integrated_states["crisis_state"].iloc[-1], reentry_stage
        )
        if not integrated_states.empty and "crisis_state" in integrated_states.columns
        else ""
    )
    return {
        "daily_monitor_state": state,
        "daily_monitor_raw_state": raw_state,
        "integrated_daily_state_available": bool(not integrated_states.empty),
        "daily_crisis_state_latest": latest_integrated_state,
        "reentry_stage": reentry_stage,
        "reentry_trigger": reentry_trigger,
    }


def classify_daily(row: dict[str, Any], crisis_state: str) -> tuple[str, str, bool]:
    crisis_state = canonical_state(crisis_state)
    leader_state = str(row.get("leader_state") or row.get("daily_review_action") or "").upper()
    ret_1m = safe_float(row.get("ret_1m"), math.nan)
    spy_excess_3m = safe_float(row.get("spy_excess_3m"), math.nan)
    ma50 = safe_float(row.get("price_to_ma50"), math.nan)
    ma200 = safe_float(row.get("price_to_ma200"), math.nan)
    chase = safe_float(row.get("leader_chase_risk_score"), 0.0)
    if crisis_state in {"DEFENSE", "CRISIS", "DEGRADED_DATA"}:
        return "DEFENSE_NO_ADD", f"crisis_state={crisis_state}", False
    if "EXIT" in leader_state or (math.isfinite(ma200) and ma200 < 0.98 and math.isfinite(spy_excess_3m) and spy_excess_3m < -0.05):
        return "EXIT_REVIEW", "leader/technical breakdown", False
    if "WARNING" in leader_state:
        return "WARNING_NO_ADD", "leader warning state", False
    if math.isfinite(ma50) and ma50 < 0.99:
        return "WARNING_NO_ADD", "below MA50; no add until recovered", False
    if math.isfinite(ret_1m) and ret_1m < -0.08:
        return "WARNING_NO_ADD", "1M weakness; no add", False
    if chase >= 1.25:
        return "HOLD_NO_ADD", "high chase risk; hold only", False
    return "HOLD_REVIEW", "no daily breakdown signal", crisis_state == "GREEN"


def build_daily_review(current: pd.DataFrame, values: pd.DataFrame, prices: pd.DataFrame, crisis: dict[str, Any]) -> pd.DataFrame:
    d = current.merge(values, on="ticker", how="left").merge(prices, on="ticker", how="left")
    state = canonical_state(
        crisis.get("daily_monitor_state")
        or crisis.get("daily_crisis_state_latest")
    )
    rows: list[dict[str, Any]] = []
    for rec in d.to_dict("records"):
        action, reason, new_buy_allowed = classify_daily(rec, state)
        out = dict(rec)
        out["decision_cadence"] = "daily_current_holdings_review"
        out["daily_review_action"] = action
        out["daily_review_reason"] = reason
        out["new_buy_allowed"] = bool(new_buy_allowed)
        out["full_universe_rerank_today"] = False
        out["crisis_state"] = state
        rows.append(out)
    return pd.DataFrame(rows)


def build_weekly_watchlist(current: pd.DataFrame, targets: pd.DataFrame, candidates: pd.DataFrame, values: pd.DataFrame, prices: pd.DataFrame, crisis: dict[str, Any]) -> pd.DataFrame:
    current_tickers = set(current["ticker"].astype(str)) if not current.empty else set()
    frames = []
    if not current.empty:
        cur = current[["portfolio_kind", "ticker", "current_weight"]].copy()
        cur["watchlist_source"] = "current_holding"
        frames.append(cur)
    if not targets.empty:
        tgt = targets.copy()
        tgt["current_weight"] = 0.0
        tgt["watchlist_source"] = "current_target"
        frames.append(tgt)
    if not candidates.empty:
        cand = candidates.copy()
        if "portfolio_kind" not in cand.columns:
            cand["portfolio_kind"] = "watchlist"
        cand["current_weight"] = 0.0
        cand["target_weight"] = 0.0
        cand["watchlist_source"] = "candidate_top_rank"
        frames.append(cand[[col for col in ["portfolio_kind", "ticker", "current_weight", "target_weight", "watchlist_source"] if col in cand.columns]].copy())
    base = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["portfolio_kind", "ticker"])
    if base.empty:
        return base
    base["ticker"] = base["ticker"].map(clean_ticker)
    base = base.drop_duplicates(["ticker", "watchlist_source"], keep="last")
    d = base.merge(values, on="ticker", how="left").merge(prices, on="ticker", how="left")
    state = canonical_state(crisis.get("daily_monitor_state"))
    actions: list[str] = []
    reasons: list[str] = []
    for rec in d.to_dict("records"):
        ticker = clean_ticker(rec.get("ticker"))
        ma50 = safe_float(rec.get("price_to_ma50"), math.nan)
        excess = safe_float(rec.get("spy_excess_3m"), math.nan)
        is_current = ticker in current_tickers
        if state in {"DEFENSE", "CRISIS", "DEGRADED_DATA"}:
            actions.append("WATCH_ONLY")
            reasons.append(f"crisis_state={state}; no new weekly add")
        elif is_current and math.isfinite(ma50) and ma50 < 0.99 and math.isfinite(excess) and excess < -0.05:
            actions.append("REPLACE_CANDIDATE_REVIEW")
            reasons.append("current holding weekly technical/RS deterioration")
        elif not is_current and math.isfinite(ma50) and ma50 >= 1.0 and math.isfinite(excess) and excess > 0.03:
            actions.append("ADD_CANDIDATE_REVIEW")
            reasons.append("weekly watchlist RS/technical confirmation")
        elif is_current:
            actions.append("HOLD_REVIEW")
            reasons.append("weekly hold refresh")
        else:
            actions.append("WATCH_ONLY")
            reasons.append("insufficient weekly confirmation")
    d["decision_cadence"] = "weekly_holdings_watchlist_refresh"
    d["weekly_review_action"] = actions
    d["weekly_review_reason"] = reasons
    d["full_universe_rerank_today"] = False
    return d


def monthly_event_plan(daily: pd.DataFrame, weekly: pd.DataFrame, crisis: dict[str, Any], latest_run: Path) -> dict[str, Any]:
    crisis_state = canonical_state(crisis.get("daily_monitor_state"))
    exit_count = int(daily["daily_review_action"].astype(str).str.contains("EXIT").sum()) if not daily.empty else 0
    warning_count = int(daily["daily_review_action"].astype(str).str.contains("WARNING|NO_ADD", regex=True).sum()) if not daily.empty else 0
    add_candidates = int(weekly["weekly_review_action"].astype(str).eq("ADD_CANDIDATE_REVIEW").sum()) if not weekly.empty else 0
    event_triggers = []
    if crisis_state in {"DEFENSE", "CRISIS", "DEGRADED_DATA"} or crisis_state.startswith("REENTRY_STAGE_"):
        event_triggers.append("crisis_or_reentry_state")
    if exit_count >= 2:
        event_triggers.append("multiple_current_holdings_exit_review")
    if add_candidates >= 3:
        event_triggers.append("weekly_watchlist_has_multiple_add_candidates")
    if crisis_state.startswith("REENTRY_STAGE_"):
        event_triggers.append("mid_month_reentry_ready")
    return {
        "schema_version": "alphaops-decision-cadence-plan-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "production_mutated": False,
        "daily_decision_scope": [
            "crisis/reentry state",
            "current holdings technical/RS deterioration",
            "no-add flags for warning/high-chase names",
        ],
        "weekly_decision_scope": [
            "current holdings and watchlist RS refresh",
            "technical confirmation",
            "valuation snapshot from latest PIT candidate/scored rows",
            "replacement candidate review",
        ],
        "monthly_or_event_decision_scope": [
            "full universe re-ranking",
            "target book reconstruction",
            "sidecar promotion review before operating target changes",
        ],
        "daily_full_universe_rerank": False,
        "weekly_full_universe_rerank": False,
        "full_universe_rerank_frequency": "monthly_or_event_triggered",
        "mid_month_reentry_allowed": True,
        "mid_month_reentry_requires_full_universe_rerank": False,
        "target_mutation_policy": "monthly base book plus crisis/reentry/event-triggered mutation dates",
        "reentry_execution_policy": {
            "fill_semantics": "broker-ledger next_close after target mutation",
            "stage_1": "deploy 25% cash to DUAL_LEADER only after REENTRY_STAGE_1 confirmation",
            "stage_2": "deploy additional 25-35% cash to DUAL_LEADER and SECTOR_LEADER",
            "stage_3": "return to normal lane allocation and allow Emerging again",
            "confirmation_days": "2-3 trading days unless shock/reentry rule explicitly bypasses",
        },
        "crisis_month_start_example": (
            "If defense triggers early in the month, do not wait until month-end. "
            "Daily reentry state and weekly watchlist refresh can request a mid-month staged redeploy."
        ),
        "event_triggers_active": event_triggers,
        "daily_exit_review_count": exit_count,
        "daily_warning_or_no_add_count": warning_count,
        "weekly_add_candidate_count": add_candidates,
        "crisis_state": crisis_state,
        "reentry_stage": crisis.get("reentry_stage", ""),
        "reentry_trigger": crisis.get("reentry_trigger", ""),
        "latest_run": str(latest_run),
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Decision Cadence Review",
        "",
        "- production_mutated: `false`",
        "- daily full-universe rerank: `false`",
        f"- full_universe_rerank_frequency: `{summary.get('full_universe_rerank_frequency')}`",
        f"- crisis_state: `{summary.get('crisis_state')}`",
        f"- daily_exit_review_count: `{summary.get('daily_exit_review_count')}`",
        f"- daily_warning_or_no_add_count: `{summary.get('daily_warning_or_no_add_count')}`",
        f"- weekly_add_candidate_count: `{summary.get('weekly_add_candidate_count')}`",
        f"- mid_month_reentry_allowed: `{str(summary.get('mid_month_reentry_allowed')).lower()}`",
        "",
        "## Cadence",
        "",
        "- Daily: crisis/reentry plus current holdings breakdown/no-add review.",
        "- Weekly: holdings/watchlist RS, technicals, and valuation snapshot refresh.",
        "- Monthly/Event: full universe re-ranking and target book rebuild review.",
        "",
        "## Re-entry",
        "",
        "- If crisis defense triggers early in the month, re-entry does not wait for month-end.",
        "- `REENTRY_STAGE_1` plus confirmation can mutate the target book mid-month.",
        "- Redeploy is staged: DUAL_LEADER first, then sector leaders, then normal lane allocation.",
        "",
        "This report is operator-review only and does not place trades.",
    ]
    return "\n".join(lines) + "\n"


def build_review(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    current = current_holdings(latest_run)
    targets = latest_targets(latest_run)
    candidates = watchlist_candidates(latest_run, args.max_watchlist_candidates)
    values = valuation_snapshot(latest_run)
    tickers = set(current.get("ticker", pd.Series(dtype=str)).astype(str)) | set(targets.get("ticker", pd.Series(dtype=str)).astype(str)) | set(candidates.get("ticker", pd.Series(dtype=str)).astype(str))
    tickers = {clean_ticker(t) for t in tickers if clean_ticker(t)}
    prices = price_metrics(price_cache, tickers)
    crisis = crisis_context(latest_run)
    daily = build_daily_review(current, values, prices, crisis)
    weekly = build_weekly_watchlist(current, targets, candidates, values, prices, crisis)
    summary = monthly_event_plan(daily, weekly, crisis, latest_run)
    daily.to_csv(output_dir / "daily_holdings_review.csv", index=False)
    weekly.to_csv(output_dir / "weekly_watchlist_refresh.csv", index=False)
    write_json(output_dir / "monthly_event_rerank_plan.json", summary)
    write_json(output_dir / "decision_cadence_summary.json", summary)
    (output_dir / "decision_cadence_report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/decision_cadence")
    parser.add_argument("--max-watchlist-candidates", type=int, default=75)
    return parser.parse_args()


def main() -> int:
    payload = build_review(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
