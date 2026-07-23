#!/usr/bin/env python3
"""Research MDD reduction from daily crisis-state cash overlays.

This sidecar is intentionally artifact-only. It reads the completed broker
ledger replay, daily crisis-state history, and execution records, then asks:

If daily crisis monitoring had raised cash after observable close-of-day
signals, how much would full-period CAGR/MaxDD/Sharpe have changed?

It does not mutate production target books and it does not claim broker-ready
execution. The output is a research bridge used to decide whether the next
implementation should become an account-ledger overlay.
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
from tools.run287_crisis_policy import adapt_crisis_state, canonical_state  # noqa: E402


SCHEMA_VERSION = "mdd-cash-overlay-research-v1"
PORTFOLIOS = ("main", "concentrated")
CASH_FLOORS = {
    "main": {
        "GREEN": 0.03,
        "REENTRY_STAGE_1": 0.20,
        "REENTRY_STAGE_2": 0.20,
        "REENTRY_STAGE_3": 0.20,
        "WATCH": 0.15,
        "DEFENSE": 0.35,
        "CRISIS": 0.55,
        "DEGRADED_DATA": 0.35,
    },
    "concentrated": {
        "GREEN": 0.03,
        "REENTRY_STAGE_1": 0.30,
        "REENTRY_STAGE_2": 0.30,
        "REENTRY_STAGE_3": 0.30,
        "WATCH": 0.25,
        "DEFENSE": 0.45,
        "CRISIS": 0.70,
        "DEGRADED_DATA": 0.45,
    },
}
EQUITY_DD_BREAKERS = {
    "main": [(-0.10, 0.35), (-0.15, 0.55), (-0.20, 0.75)],
    "concentrated": [(-0.08, 0.45), (-0.12, 0.65), (-0.18, 0.85)],
}
SWEEP_VARIANTS = [
    {
        "variant": "crisis_only_confirm2",
        "description": "Daily crisis-state floors only; no account equity drawdown breaker.",
        "enable_equity_breaker": False,
        "confirm_days": 2,
        "release_step": 0.10,
        "change_band": 0.03,
        "cash_floors": CASH_FLOORS,
        "equity_breakers": {"main": [], "concentrated": []},
    },
    {
        "variant": "crisis_only_fast_reentry",
        "description": "Crisis-state floors only with faster confirmation and cash release.",
        "enable_equity_breaker": False,
        "confirm_days": 1,
        "release_step": 0.20,
        "change_band": 0.02,
        "cash_floors": CASH_FLOORS,
        "equity_breakers": {"main": [], "concentrated": []},
    },
    {
        "variant": "balanced_lite_dd",
        "description": "Lower crisis floors plus a delayed portfolio drawdown breaker.",
        "enable_equity_breaker": True,
        "confirm_days": 2,
        "release_step": 0.20,
        "change_band": 0.03,
        "cash_floors": {
            "main": {"GREEN": 0.03, "REENTRY_STAGE_1": 0.10, "REENTRY_STAGE_2": 0.10, "REENTRY_STAGE_3": 0.10, "WATCH": 0.08, "DEFENSE": 0.25, "CRISIS": 0.45, "DEGRADED_DATA": 0.25},
            "concentrated": {"GREEN": 0.03, "REENTRY_STAGE_1": 0.12, "REENTRY_STAGE_2": 0.12, "REENTRY_STAGE_3": 0.12, "WATCH": 0.10, "DEFENSE": 0.30, "CRISIS": 0.55, "DEGRADED_DATA": 0.30},
        },
        "equity_breakers": {
            "main": [(-0.15, 0.25), (-0.25, 0.45), (-0.35, 0.60)],
            "concentrated": [(-0.12, 0.35), (-0.20, 0.50), (-0.30, 0.70)],
        },
    },
    {
        "variant": "late_dd_fast_release",
        "description": "Late drawdown breaker intended to avoid long cash lockups.",
        "enable_equity_breaker": True,
        "confirm_days": 1,
        "release_step": 0.30,
        "change_band": 0.04,
        "cash_floors": {
            "main": {"GREEN": 0.03, "REENTRY_STAGE_1": 0.08, "REENTRY_STAGE_2": 0.08, "REENTRY_STAGE_3": 0.08, "WATCH": 0.05, "DEFENSE": 0.20, "CRISIS": 0.35, "DEGRADED_DATA": 0.20},
            "concentrated": {"GREEN": 0.03, "REENTRY_STAGE_1": 0.10, "REENTRY_STAGE_2": 0.10, "REENTRY_STAGE_3": 0.10, "WATCH": 0.08, "DEFENSE": 0.25, "CRISIS": 0.45, "DEGRADED_DATA": 0.25},
        },
        "equity_breakers": {
            "main": [(-0.20, 0.30), (-0.30, 0.50), (-0.40, 0.65)],
            "concentrated": [(-0.18, 0.40), (-0.30, 0.60), (-0.42, 0.75)],
        },
    },
    {
        "variant": "strong_dd_cap",
        "description": "Aggressive account drawdown defense; useful as an MDD lower-bound test.",
        "enable_equity_breaker": True,
        "confirm_days": 2,
        "release_step": 0.10,
        "change_band": 0.03,
        "cash_floors": CASH_FLOORS,
        "equity_breakers": EQUITY_DD_BREAKERS,
    },
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


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
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def json_ready_record(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, np.bool_):
            out[key] = bool(value)
        elif isinstance(value, np.integer):
            out[key] = int(value)
        elif isinstance(value, np.floating):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2%}"


def crisis_state_path(latest_run: Path, explicit: str | Path | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "alphaops_vnext" / "daily_crisis_state.csv",
        latest_run / "daily_crisis_monitor" / "daily_crisis_state.csv",
        latest_run / "daily_crisis_state.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def prepare_equity(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns or "equity_usd" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["equity_usd"] = pd.to_numeric(out["equity_usd"], errors="coerce")
    out["cash_weight"] = pd.to_numeric(out.get("cash_weight", 0.0), errors="coerce").fillna(0.0).clip(0.0, 1.0)
    out = out.dropna(subset=["date", "equity_usd"]).sort_values("date").drop_duplicates("date", keep="last")
    return out.reset_index(drop=True)


def prepare_crisis(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame(columns=["date", "crisis_state"])
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    if "crisis_state" not in out.columns:
        if "state" in out.columns:
            out["crisis_state"] = out["state"]
        else:
            out["crisis_state"] = "DEGRADED_DATA"
    stages = out.get("reentry_stage", pd.Series("", index=out.index))
    out["crisis_state"] = [
        adapt_crisis_state(state, stage)
        for state, stage in zip(out["crisis_state"], stages)
    ]
    return out.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")[["date", "crisis_state"]]


def max_drawdown_info(dates: pd.Series, values: pd.Series) -> dict[str, Any]:
    values = pd.to_numeric(values, errors="coerce")
    dates = pd.to_datetime(dates, errors="coerce")
    d = pd.DataFrame({"date": dates, "value": values}).dropna().reset_index(drop=True)
    if d.empty:
        return {"max_dd": None}
    running_peak = d["value"].cummax()
    drawdown = d["value"] / running_peak - 1.0
    trough_pos = int(drawdown.idxmin())
    peak_pos = int(d.loc[:trough_pos, "value"].idxmax())
    return {
        "max_dd": float(drawdown.min()),
        "peak_date": pd.Timestamp(d.loc[peak_pos, "date"]).date().isoformat(),
        "trough_date": pd.Timestamp(d.loc[trough_pos, "date"]).date().isoformat(),
        "peak_value": float(d.loc[peak_pos, "value"]),
        "trough_value": float(d.loc[trough_pos, "value"]),
        "duration_days": int((pd.Timestamp(d.loc[trough_pos, "date"]) - pd.Timestamp(d.loc[peak_pos, "date"])).days),
    }


def calc_metrics(curve: pd.DataFrame, value_col: str, cash_col: str) -> dict[str, Any]:
    if curve.empty or value_col not in curve.columns:
        return {"status": "blocked", "reason": f"missing {value_col}"}
    values = pd.to_numeric(curve[value_col], errors="coerce")
    dates = pd.to_datetime(curve["date"], errors="coerce")
    valid = pd.DataFrame({"date": dates, "value": values, "cash": curve.get(cash_col, np.nan)}).dropna(subset=["date", "value"])
    if valid.empty:
        return {"status": "blocked", "reason": "empty curve"}
    returns = valid["value"].pct_change().dropna()
    years = max((valid["date"].max() - valid["date"].min()).days / 365.25, len(returns) / 252.0, 1e-6)
    dd = max_drawdown_info(valid["date"], valid["value"])
    vol = float(returns.std(ddof=0) * math.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = float((returns.mean() * 252.0) / (vol + 1e-12)) if not returns.empty else 0.0
    return {
        "status": "completed",
        "start_date": valid["date"].min().date().isoformat(),
        "end_date": valid["date"].max().date().isoformat(),
        "days": int(len(valid)),
        "years": float(years),
        "starting_capital_usd": float(valid["value"].iloc[0]),
        "ending_capital_usd": float(valid["value"].iloc[-1]),
        "total_return": float(valid["value"].iloc[-1] / max(valid["value"].iloc[0], 1e-12) - 1.0),
        "cagr": float((valid["value"].iloc[-1] / max(valid["value"].iloc[0], 1e-12)) ** (1.0 / years) - 1.0),
        "sharpe": sharpe,
        "max_dd": dd.get("max_dd"),
        "max_dd_peak_date": dd.get("peak_date"),
        "max_dd_trough_date": dd.get("trough_date"),
        "max_dd_peak_equity_usd": dd.get("peak_value"),
        "max_dd_trough_equity_usd": dd.get("trough_value"),
        "avg_cash_weight": float(pd.to_numeric(valid["cash"], errors="coerce").mean()),
    }


def floor_for_state(portfolio: str, state: str, cash_floors: dict[str, dict[str, float]] | None = None) -> float:
    floors = cash_floors or CASH_FLOORS
    portfolio_floors = floors.get(portfolio, floors.get("main", CASH_FLOORS["main"]))
    return float(portfolio_floors[canonical_state(state)])


def equity_breaker_floor(
    portfolio: str,
    drawdown: float,
    enabled: bool,
    equity_breakers: dict[str, list[tuple[float, float]]] | None = None,
) -> float:
    if not enabled:
        return 0.0
    floor = 0.0
    breakers = equity_breakers or EQUITY_DD_BREAKERS
    for threshold, cash_floor in breakers.get(portfolio, []):
        if drawdown <= threshold:
            floor = max(floor, cash_floor)
    return float(floor)


def confirmed_policy_floor(
    *,
    portfolio: str,
    states: list[str],
    requested_state: str,
    current_cash: float,
    confirm_days: int,
    cash_floors: dict[str, dict[str, float]] | None = None,
) -> float:
    requested = floor_for_state(portfolio, requested_state, cash_floors)
    if requested <= current_cash or confirm_days <= 1:
        return requested
    recent = states[-int(confirm_days):]
    if len(recent) < int(confirm_days):
        return current_cash
    return min(floor_for_state(portfolio, state, cash_floors) for state in recent)


def next_cash_weight(
    *,
    current_cash: float,
    target_floor: float,
    release_step: float,
    change_band: float,
) -> tuple[float, str]:
    current_cash = float(np.clip(current_cash, 0.0, 0.98))
    target_floor = float(np.clip(target_floor, 0.0, 0.98))
    if target_floor > current_cash + change_band:
        return target_floor, "RAISE_CASH"
    if target_floor < current_cash - change_band:
        return max(target_floor, current_cash - release_step), "RELEASE_CASH"
    return current_cash, "HOLD_CASH"


def simulate_overlay(
    *,
    equity: pd.DataFrame,
    crisis: pd.DataFrame,
    portfolio: str,
    cost_bps: float,
    confirm_days: int,
    release_step: float,
    change_band: float,
    enable_equity_breaker: bool,
    cash_floors: dict[str, dict[str, float]] | None = None,
    equity_breakers: dict[str, list[tuple[float, float]]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    merged = equity.merge(crisis, on="date", how="left")
    merged["crisis_state"] = merged["crisis_state"].fillna("DEGRADED_DATA").map(
        canonical_state
    )
    rows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    states_seen: list[str] = []
    overlay_equity = float(merged["equity_usd"].iloc[0])
    overlay_cash = float(merged["cash_weight"].iloc[0])
    rows.append(
        {
            "date": merged["date"].iloc[0].date().isoformat(),
            "base_equity_usd": float(merged["equity_usd"].iloc[0]),
            "overlay_equity_usd": overlay_equity,
            "base_cash_weight": float(merged["cash_weight"].iloc[0]),
            "overlay_cash_weight": overlay_cash,
            "crisis_state": str(merged["crisis_state"].iloc[0]),
            "policy_cash_floor": floor_for_state(portfolio, str(merged["crisis_state"].iloc[0]), cash_floors),
            "equity_drawdown_cash_floor": 0.0,
            "target_cash_weight_next": overlay_cash,
            "cash_action": "INIT",
            "turnover_from_cash_action": 0.0,
            "cash_action_cost_usd": 0.0,
        }
    )
    overlay_peak = overlay_equity
    for i in range(1, len(merged)):
        prev = merged.iloc[i - 1]
        cur = merged.iloc[i]
        prev_base_cash = float(np.clip(safe_float(prev.get("cash_weight"), 0.0), 0.0, 0.98))
        base_return = float(cur["equity_usd"] / max(prev["equity_usd"], 1e-12) - 1.0)
        stock_return = base_return / max(1.0 - prev_base_cash, 0.02)
        overlay_equity *= 1.0 + (1.0 - overlay_cash) * stock_return
        overlay_peak = max(overlay_peak, overlay_equity)
        overlay_drawdown_now = overlay_equity / max(overlay_peak, 1e-12) - 1.0

        state = canonical_state(cur.get("crisis_state"))
        states_seen.append(state)
        policy_floor = confirmed_policy_floor(
            portfolio=portfolio,
            states=states_seen,
            requested_state=state,
            current_cash=overlay_cash,
            confirm_days=confirm_days,
            cash_floors=cash_floors,
        )
        dd_floor = equity_breaker_floor(portfolio, overlay_drawdown_now, enable_equity_breaker, equity_breakers)
        base_cash_floor = float(np.clip(safe_float(cur.get("cash_weight"), 0.0), 0.0, 0.98))
        target_floor = max(policy_floor, dd_floor, base_cash_floor)
        new_cash, action = next_cash_weight(
            current_cash=overlay_cash,
            target_floor=target_floor,
            release_step=release_step,
            change_band=change_band,
        )
        turnover = abs(new_cash - overlay_cash) if action != "HOLD_CASH" else 0.0
        cost = overlay_equity * turnover * (float(cost_bps) / 10000.0)
        if cost > 0:
            overlay_equity = max(0.0, overlay_equity - cost)
        if action != "HOLD_CASH":
            actions.append(
                {
                    "signal_date": pd.Timestamp(cur["date"]).date().isoformat(),
                    "effective_next_trading_day": (
                        pd.Timestamp(merged.iloc[i + 1]["date"]).date().isoformat() if i + 1 < len(merged) else ""
                    ),
                    "portfolio": portfolio,
                    "crisis_state": state,
                    "prior_cash_weight": overlay_cash,
                    "target_cash_weight": new_cash,
                    "policy_cash_floor": policy_floor,
                    "equity_drawdown": overlay_drawdown_now,
                    "equity_drawdown_cash_floor": dd_floor,
                    "base_cash_floor": base_cash_floor,
                    "turnover_from_cash_action": turnover,
                    "estimated_cost_usd": cost,
                    "cash_action": action,
                }
            )
        overlay_cash = new_cash
        rows.append(
            {
                "date": pd.Timestamp(cur["date"]).date().isoformat(),
                "base_equity_usd": float(cur["equity_usd"]),
                "overlay_equity_usd": float(overlay_equity),
                "base_cash_weight": base_cash_floor,
                "overlay_cash_weight": float(overlay_cash),
                "crisis_state": state,
                "policy_cash_floor": float(policy_floor),
                "equity_drawdown_cash_floor": float(dd_floor),
                "target_cash_weight_next": float(new_cash),
                "cash_action": action,
                "turnover_from_cash_action": float(turnover),
                "cash_action_cost_usd": float(cost),
            }
        )
    curve = pd.DataFrame(rows)
    for col in ["base_equity_usd", "overlay_equity_usd"]:
        curve[f"{col}_peak"] = curve[col].cummax()
    curve["base_drawdown"] = curve["base_equity_usd"] / curve["base_equity_usd_peak"] - 1.0
    curve["overlay_drawdown"] = curve["overlay_equity_usd"] / curve["overlay_equity_usd_peak"] - 1.0
    return curve, pd.DataFrame(actions)


def window_filter(frame: pd.DataFrame, date_col: str, start: str, end: str) -> pd.DataFrame:
    if frame.empty or date_col not in frame.columns or not start or not end:
        return pd.DataFrame()
    out = frame.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce").dt.normalize()
    return out[(out[date_col] >= pd.Timestamp(start)) & (out[date_col] <= pd.Timestamp(end))].copy()


def summarize_mdd_trades(trades: pd.DataFrame, peak: str, trough: str) -> dict[str, Any]:
    window = window_filter(trades, "date", peak, trough)
    if window.empty:
        return {"trade_count": 0, "gross_value_usd": 0.0, "sell_count": 0, "buy_count": 0, "net_cash_delta_usd": 0.0}
    window["gross_value"] = pd.to_numeric(window.get("gross_value", 0.0), errors="coerce").fillna(0.0)
    window["cash_delta"] = pd.to_numeric(window.get("cash_delta", 0.0), errors="coerce").fillna(0.0)
    by_ticker = (
        window.groupby("ticker", dropna=False)["gross_value"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .reset_index()
        .rename(columns={"gross_value": "gross_value_usd"})
    )
    return {
        "trade_count": int(len(window)),
        "gross_value_usd": float(window["gross_value"].sum()),
        "sell_count": int(window["side"].astype(str).str.upper().eq("SELL").sum()) if "side" in window.columns else 0,
        "buy_count": int(window["side"].astype(str).str.upper().eq("BUY").sum()) if "side" in window.columns else 0,
        "net_cash_delta_usd": float(window["cash_delta"].sum()),
        "top_tickers_by_gross": by_ticker.to_dict("records"),
    }


def holdings_contributors(holdings: pd.DataFrame, peak: str, trough: str) -> pd.DataFrame:
    if holdings.empty or not peak or not trough:
        return pd.DataFrame()
    d = holdings.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["market_value_usd"] = pd.to_numeric(d.get("market_value_usd", 0.0), errors="coerce").fillna(0.0)
    peak_rows = d[d["date"].eq(pd.Timestamp(peak))][["ticker", "market_value_usd", "weight"]].rename(
        columns={"market_value_usd": "peak_market_value_usd", "weight": "peak_weight"}
    )
    trough_rows = d[d["date"].eq(pd.Timestamp(trough))][["ticker", "market_value_usd", "weight"]].rename(
        columns={"market_value_usd": "trough_market_value_usd", "weight": "trough_weight"}
    )
    if peak_rows.empty:
        return pd.DataFrame()
    joined = peak_rows.merge(trough_rows, on="ticker", how="left")
    joined["trough_market_value_usd"] = pd.to_numeric(joined["trough_market_value_usd"], errors="coerce").fillna(0.0)
    joined["trough_weight"] = pd.to_numeric(joined["trough_weight"], errors="coerce").fillna(0.0)
    joined["peak_to_trough_value_delta_usd"] = joined["trough_market_value_usd"] - joined["peak_market_value_usd"]
    return joined.sort_values("peak_to_trough_value_delta_usd").head(15).reset_index(drop=True)


def target_eval(portfolio: str, metrics: dict[str, Any]) -> dict[str, Any]:
    targets = PORTFOLIO_GOAL_TARGETS.get(portfolio, {})
    cagr = safe_float(metrics.get("cagr"), float("nan"))
    max_dd = safe_float(metrics.get("max_dd"), float("nan"))
    cagr_target = safe_float(targets.get("cagr"), 0.0)
    max_dd_target = safe_float(targets.get("max_dd"), -1.0)
    cagr_gap = max(0.0, cagr_target - cagr)
    mdd_gap = max(0.0, max_dd_target - max_dd)
    return {
        "cagr_target": cagr_target,
        "max_dd_target": max_dd_target,
        "cagr_gap": float(cagr_gap),
        "max_dd_gap": float(mdd_gap),
        "target_pass": bool(cagr >= cagr_target and max_dd >= max_dd_target),
    }


def sweep_cash_variants(
    *,
    equity: pd.DataFrame,
    crisis: pd.DataFrame,
    portfolio: str,
    base_metrics: dict[str, Any],
    cost_bps: float,
    include_default: dict[str, Any],
) -> pd.DataFrame:
    variants = [
        {
            "variant": "workflow_default",
            "description": "Workflow command-line parameters.",
            **include_default,
            "cash_floors": CASH_FLOORS,
            "equity_breakers": EQUITY_DD_BREAKERS,
        },
        *SWEEP_VARIANTS,
    ]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        name = str(variant["variant"])
        if name in seen:
            continue
        seen.add(name)
        curve, actions = simulate_overlay(
            equity=equity,
            crisis=crisis,
            portfolio=portfolio,
            cost_bps=cost_bps,
            confirm_days=int(variant["confirm_days"]),
            release_step=float(variant["release_step"]),
            change_band=float(variant["change_band"]),
            enable_equity_breaker=bool(variant["enable_equity_breaker"]),
            cash_floors=variant.get("cash_floors"),
            equity_breakers=variant.get("equity_breakers"),
        )
        metrics = calc_metrics(curve, "overlay_equity_usd", "overlay_cash_weight")
        target = target_eval(portfolio, metrics)
        cagr_delta = safe_float(metrics.get("cagr")) - safe_float(base_metrics.get("cagr"))
        max_dd_improvement = safe_float(metrics.get("max_dd")) - safe_float(base_metrics.get("max_dd"))
        avg_cash_delta = safe_float(metrics.get("avg_cash_weight")) - safe_float(base_metrics.get("avg_cash_weight"))
        cagr_loss = max(0.0, -cagr_delta)
        score = (
            100.0 * max_dd_improvement
            - 55.0 * cagr_loss
            - 20.0 * avg_cash_delta
            - 150.0 * safe_float(target.get("cagr_gap"))
            - 100.0 * safe_float(target.get("max_dd_gap"))
        )
        if target["target_pass"]:
            score += 100.0
        rows.append(
            {
                "portfolio": portfolio,
                "variant": name,
                "description": variant.get("description", ""),
                "target_pass": target["target_pass"],
                "score": float(score),
                "cagr": safe_float(metrics.get("cagr")),
                "max_dd": safe_float(metrics.get("max_dd")),
                "sharpe": safe_float(metrics.get("sharpe")),
                "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
                "cagr_delta": float(cagr_delta),
                "max_dd_improvement": float(max_dd_improvement),
                "avg_cash_delta": float(avg_cash_delta),
                "cagr_gap": safe_float(target.get("cagr_gap")),
                "max_dd_gap": safe_float(target.get("max_dd_gap")),
                "cash_action_count": int(len(actions)),
                "estimated_cash_action_cost_usd": float(
                    pd.to_numeric(actions.get("estimated_cost_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
                )
                if not actions.empty
                else 0.0,
                "confirm_days": int(variant["confirm_days"]),
                "release_step": float(variant["release_step"]),
                "change_band": float(variant["change_band"]),
                "equity_drawdown_breaker_enabled": bool(variant["enable_equity_breaker"]),
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["target_pass", "score"], ascending=[False, False]).reset_index(drop=True)


def render_report(payload: dict[str, Any]) -> str:
    base = payload.get("base_metrics") or {}
    overlay = payload.get("overlay_metrics") or {}
    trade = payload.get("base_mdd_trade_summary") or {}
    best = payload.get("best_variant") or {}
    lines = [
        f"# MDD Cash Overlay Research - {payload.get('portfolio')}",
        "",
        "Artifact-only research replay. Daily crisis state is observed at close and applied to the next trading interval.",
        "",
        "| Metric | Base broker replay | Cash overlay | Delta |",
        "| --- | ---: | ---: | ---: |",
        f"| CAGR | {pct(base.get('cagr'))} | {pct(overlay.get('cagr'))} | {pct(payload.get('cagr_delta'))} |",
        f"| MaxDD | {pct(base.get('max_dd'))} | {pct(overlay.get('max_dd'))} | {pct(payload.get('max_dd_improvement'))} |",
        f"| Sharpe | {safe_float(base.get('sharpe')):.3f} | {safe_float(overlay.get('sharpe')):.3f} | {safe_float(payload.get('sharpe_delta')):+.3f} |",
        f"| Avg Cash | {pct(base.get('avg_cash_weight'))} | {pct(overlay.get('avg_cash_weight'))} | {pct(payload.get('avg_cash_delta'))} |",
        "",
        "## Base MDD Trade Window",
        "",
        f"- Window: `{base.get('max_dd_peak_date')}` to `{base.get('max_dd_trough_date')}`",
        f"- Raw executions inside window: `{trade.get('trade_count', 0)}`",
        f"- Gross traded: `${safe_float(trade.get('gross_value_usd')):,.0f}`",
        f"- Net cash delta from executions: `${safe_float(trade.get('net_cash_delta_usd')):,.0f}`",
        "",
        "## Cash Overlay",
        "",
        f"- Crisis state source: `{payload.get('crisis_state_path')}`",
        f"- Cash actions: `{payload.get('cash_action_count')}`",
        f"- Estimated cash-action cost: `${safe_float(payload.get('estimated_cash_action_cost_usd')):,.0f}`",
        f"- Confirm days: `{payload.get('confirm_days')}`",
        f"- Release step: `{pct(payload.get('release_step'))}`",
        "",
        "## Variant Sweep",
        "",
        f"- Best variant: `{best.get('variant', '')}`",
        f"- Best CAGR / MaxDD: `{pct(best.get('cagr'))}` / `{pct(best.get('max_dd'))}`",
        f"- Best target pass: `{best.get('target_pass', False)}`",
        f"- Best cash actions: `{best.get('cash_action_count', 0)}`",
        "",
        "Research-only. Promotion requires an account-ledger implementation with real orders and next-close fills.",
        "",
    ]
    return "\n".join(lines)


def analyze_portfolio(
    *,
    latest_run: Path,
    output_root: Path,
    portfolio: str,
    crisis: pd.DataFrame,
    crisis_path: Path,
    cost_bps: float,
    confirm_days: int,
    release_step: float,
    change_band: float,
    enable_equity_breaker: bool,
) -> dict[str, Any]:
    metrics = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    equity = prepare_equity(read_csv(latest_run / "broker_replay" / portfolio / "equity_curve.csv"))
    if equity.empty or crisis.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "portfolio": portfolio,
            "status": "blocked",
            "reason": "missing broker equity curve or crisis state",
            "crisis_state_path": str(crisis_path),
        }
        write_json(output_root / portfolio / "metrics.json", payload)
        return payload
    curve, actions = simulate_overlay(
        equity=equity,
        crisis=crisis,
        portfolio=portfolio,
        cost_bps=cost_bps,
        confirm_days=confirm_days,
        release_step=release_step,
        change_band=change_band,
        enable_equity_breaker=enable_equity_breaker,
        cash_floors=CASH_FLOORS,
        equity_breakers=EQUITY_DD_BREAKERS,
    )
    base_metrics = {
        **calc_metrics(curve, "base_equity_usd", "base_cash_weight"),
        **{
            key: metrics.get(key)
            for key in [
                "cagr",
                "max_dd",
                "sharpe",
                "avg_cash_weight",
                "max_dd_peak_date",
                "max_dd_trough_date",
                "max_dd_peak_equity_usd",
                "max_dd_trough_equity_usd",
            ]
            if key in metrics
        },
    }
    overlay_metrics = calc_metrics(curve, "overlay_equity_usd", "overlay_cash_weight")
    trades = read_csv(latest_run / "broker_replay" / portfolio / "trades.csv")
    holdings = read_csv(latest_run / "broker_replay" / portfolio / "holdings_daily.csv")
    trade_summary = summarize_mdd_trades(trades, str(base_metrics.get("max_dd_peak_date") or ""), str(base_metrics.get("max_dd_trough_date") or ""))
    contributors = holdings_contributors(holdings, str(base_metrics.get("max_dd_peak_date") or ""), str(base_metrics.get("max_dd_trough_date") or ""))
    sweep = sweep_cash_variants(
        equity=equity,
        crisis=crisis,
        portfolio=portfolio,
        base_metrics=base_metrics,
        cost_bps=cost_bps,
        include_default={
            "confirm_days": int(confirm_days),
            "release_step": float(release_step),
            "change_band": float(change_band),
            "enable_equity_breaker": bool(enable_equity_breaker),
        },
    )
    best_variant = json_ready_record(sweep.iloc[0].to_dict()) if not sweep.empty else {}
    target = target_eval(portfolio, overlay_metrics)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "portfolio": portfolio,
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(latest_run),
        "crisis_state_path": str(crisis_path),
        "cash_floor_policy": CASH_FLOORS[portfolio],
        "confirm_days": int(confirm_days),
        "release_step": float(release_step),
        "change_band": float(change_band),
        "equity_drawdown_breaker_enabled": bool(enable_equity_breaker),
        "equity_drawdown_breakers": EQUITY_DD_BREAKERS.get(portfolio, []),
        "cost_bps_per_side_proxy": float(cost_bps),
        "base_metrics": base_metrics,
        "overlay_metrics": overlay_metrics,
        "overlay_target_eval": target,
        "cagr_delta": safe_float(overlay_metrics.get("cagr")) - safe_float(base_metrics.get("cagr")),
        "max_dd_improvement": safe_float(overlay_metrics.get("max_dd")) - safe_float(base_metrics.get("max_dd")),
        "sharpe_delta": safe_float(overlay_metrics.get("sharpe")) - safe_float(base_metrics.get("sharpe")),
        "avg_cash_delta": safe_float(overlay_metrics.get("avg_cash_weight")) - safe_float(base_metrics.get("avg_cash_weight")),
        "cash_action_count": int(len(actions)),
        "estimated_cash_action_cost_usd": float(pd.to_numeric(actions.get("estimated_cost_usd", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not actions.empty else 0.0,
        "base_mdd_trade_summary": trade_summary,
        "best_variant": best_variant,
        "cash_overlay_target_pass": bool(target.get("target_pass")),
        "cash_overlay_sweep_target_pass": bool(best_variant.get("target_pass")) if best_variant else False,
        "research_only": True,
        "production_activation_allowed": False,
        "next_step": (
            "Convert to broker-account order overlay only if a sweep variant meets target gates after cash-action costs."
            if best_variant.get("target_pass")
            else "Cash conversion alone did not meet target gates; combine with selection/cluster-risk changes before production."
        ),
    }
    out_dir = output_root / portfolio
    out_dir.mkdir(parents=True, exist_ok=True)
    curve.to_csv(out_dir / "overlay_equity_curve.csv", index=False)
    actions.to_csv(out_dir / "cash_actions.csv", index=False)
    contributors.to_csv(out_dir / "mdd_holdings_contributors.csv", index=False)
    sweep.to_csv(out_dir / "variant_sweep.csv", index=False)
    window_filter(trades, "date", str(base_metrics.get("max_dd_peak_date") or ""), str(base_metrics.get("max_dd_trough_date") or "")).to_csv(out_dir / "mdd_trade_window.csv", index=False)
    write_json(out_dir / "metrics.json", payload)
    write_text(out_dir / "research_report.md", render_report(payload))
    return payload


def run(
    *,
    latest_run: Path,
    output_dir: Path,
    crisis_state: Path | None,
    portfolios: list[str],
    cost_bps: float,
    confirm_days: int,
    release_step: float,
    change_band: float,
    enable_equity_breaker: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cpath = crisis_state_path(latest_run, crisis_state)
    crisis = prepare_crisis(read_csv(cpath))
    reports = {}
    for portfolio in portfolios:
        reports[portfolio] = analyze_portfolio(
            latest_run=latest_run,
            output_root=output_dir,
            portfolio=portfolio,
            crisis=crisis,
            crisis_path=cpath,
            cost_bps=cost_bps,
            confirm_days=confirm_days,
            release_step=release_step,
            change_band=change_band,
            enable_equity_breaker=enable_equity_breaker,
        )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": str(latest_run),
        "crisis_state_path": str(cpath),
        "portfolios": reports,
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/mdd_cash_overlay_research")
    parser.add_argument("--crisis-state", default="")
    parser.add_argument("--portfolios", nargs="+", default=list(PORTFOLIOS))
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--confirm-days", type=int, default=2)
    parser.add_argument("--release-step", type=float, default=0.10)
    parser.add_argument("--change-band", type=float, default=0.03)
    parser.add_argument("--disable-equity-drawdown-breaker", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run(
        latest_run=repo_path(args.latest_run),
        output_dir=repo_path(args.output_dir),
        crisis_state=repo_path(args.crisis_state) if args.crisis_state else None,
        portfolios=[str(p) for p in args.portfolios],
        cost_bps=float(args.cost_bps),
        confirm_days=int(args.confirm_days),
        release_step=float(args.release_step),
        change_band=float(args.change_band),
        enable_equity_breaker=not bool(args.disable_equity_drawdown_breaker),
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "portfolios"}, indent=2, sort_keys=True, default=str))
    completed = [p for p in summary["portfolios"].values() if p.get("status") == "completed"]
    return 0 if completed else 2


if __name__ == "__main__":
    raise SystemExit(main())
