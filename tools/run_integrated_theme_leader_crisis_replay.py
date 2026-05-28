#!/usr/bin/env python3
"""AlphaOps vNext integrated lane/leader/crisis broker-ledger replay.

Research-only sidecar. It does not change production scores, feature-store
columns, target defaults, or live activation. The tool builds an 8-case A/B
matrix from existing full-rebuild artifacts and replays each target book through
the broker-ledger next-close path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_candidate_lanes import lane_feature_mapping_payload, score_candidate_lanes  # noqa: E402
from r1000_market_leader_engine import (  # noqa: E402
    MarketLeaderVariant,
    apply_state_history,
    load_prices,
    safe_float,
    score_market_leaders,
    select_market_leader_targets,
    target_rows_from_selection,
)
from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay as broker_replay  # noqa: E402
from tools.run_market_leader_challenger import normalize_candidate_frame, read_table, resolve_candidate_book  # noqa: E402
from tools.run_replay_integrity_preflight import build_report as build_preflight_report  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/integrated_theme_leader_crisis_replay"
CASH_TICKERS = {"CASH", "__CASH__"}
PROTECTED_OUTPUT_NAMES = [
    "portfolio_latest.csv",
    "concentrated_portfolio_latest.csv",
    "scored_latest.csv",
    "feature_store_latest.parquet",
    "reports/operating_main_target_book.csv",
    "reports/operating_concentrated_target_book.csv",
    "account_evaluation",
    "broker_replay",
    "user_current",
]


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    selection_layer: str
    crisis_overlay: bool
    hold_replace_enabled: bool
    purpose: str


CASES = [
    CaseSpec("A", "production", False, False, "baseline"),
    CaseSpec("B", "production", True, False, "crisis_only"),
    CaseSpec("C", "market_leader", False, False, "leader_only"),
    CaseSpec("D", "market_leader", True, False, "leader_crisis"),
    CaseSpec("E", "market_leader", False, True, "leader_hold_replace"),
    CaseSpec("F", "market_leader", True, True, "leader_crisis_hold"),
    CaseSpec("G", "multi_lane", False, True, "lane_allocator"),
    CaseSpec("H", "multi_lane", True, True, "final_candidate"),
]


LANE_BUDGETS_NORMAL = {
    "QUALITY_COMPOUNDER": 0.30,
    "MARKET_LEADER": 0.42,
    "EMERGING_TENBAGGER": 0.10,
    "TOP7_MANAGER_DISCOVERY": 0.07,
    "CYCLICAL_RECOVERY": 0.09,
    "CRISIS_BENEFICIARY": 0.02,
}

CRISIS_SETTINGS = {
    "GREEN": {
        "cash": 0.03,
        "lane_multiplier": {"EMERGING_TENBAGGER": 1.0, "CYCLICAL_RECOVERY": 1.0, "MARKET_LEADER": 1.0, "QUALITY_COMPOUNDER": 1.0},
        "new_buy_allowed": {"EMERGING_TENBAGGER": True, "MARKET_LEADER": True, "QUALITY_COMPOUNDER": True, "CYCLICAL_RECOVERY": True},
    },
    "WATCH": {
        "cash": 0.08,
        "lane_multiplier": {"EMERGING_TENBAGGER": 0.70, "CYCLICAL_RECOVERY": 0.85, "MARKET_LEADER": 0.95, "QUALITY_COMPOUNDER": 1.0},
        "new_buy_allowed": {"EMERGING_TENBAGGER": False, "MARKET_LEADER": True, "QUALITY_COMPOUNDER": True, "CYCLICAL_RECOVERY": False},
    },
    "DEFENSE_REVIEW": {
        "cash": 0.20,
        "lane_multiplier": {"EMERGING_TENBAGGER": 0.35, "CYCLICAL_RECOVERY": 0.60, "MARKET_LEADER": 0.80, "QUALITY_COMPOUNDER": 0.95},
        "new_buy_allowed": {"EMERGING_TENBAGGER": False, "MARKET_LEADER": False, "QUALITY_COMPOUNDER": True, "CYCLICAL_RECOVERY": False},
    },
    "CRISIS_DEFENSE": {
        "cash": 0.40,
        "lane_multiplier": {"EMERGING_TENBAGGER": 0.10, "CYCLICAL_RECOVERY": 0.35, "MARKET_LEADER": 0.55, "QUALITY_COMPOUNDER": 0.85},
        "new_buy_allowed": {"EMERGING_TENBAGGER": False, "MARKET_LEADER": False, "QUALITY_COMPOUNDER": True, "CYCLICAL_RECOVERY": False},
    },
    "REENTRY_READY": {
        "cash": 0.18,
        "lane_multiplier": {"EMERGING_TENBAGGER": 0.45, "CYCLICAL_RECOVERY": 0.85, "MARKET_LEADER": 1.05, "QUALITY_COMPOUNDER": 1.0},
        "new_buy_allowed": {"EMERGING_TENBAGGER": False, "MARKET_LEADER": True, "QUALITY_COMPOUNDER": True, "CYCLICAL_RECOVERY": True},
    },
}

CRISIS_HYSTERESIS = {
    "minimum_action_gap_days": 3,
    "max_crisis_actions_per_month": 4,
    "state_downgrade_confirmation_days": 2,
    "state_upgrade_reentry_confirmation_days": 3,
    "shock_crash_immediate_bypass": True,
}

HOLD_REPLACE_POLICY = {
    "min_hold_months_by_lane": {
        "QUALITY_COMPOUNDER": 3,
        "MARKET_LEADER": 2,
        "EMERGING_TENBAGGER": 1,
        "TOP7_MANAGER_DISCOVERY": 1,
        "CYCLICAL_RECOVERY": 2,
        "CRISIS_BENEFICIARY": 1,
    },
    "max_replacements_by_portfolio": {"main": 4, "concentrated": 2},
    "max_replacements_by_lane": {"EMERGING_TENBAGGER": 1, "TOP7_MANAGER_DISCOVERY": 1},
    "replacement_threshold_sigma": {"normal": 0.75, "broken": 0.35},
}

LANE_RULES_YAML = """# Research-only lane rules for AlphaOps vNext.
QUALITY_COMPOUNDER:
  hard_reject:
    - severe_balance_sheet_or_data_failure
  risk_cap:
    - valuation_overheat
    - margin_deceleration
MARKET_LEADER:
  hard_reject:
    - missing_price_history
    - liquidity_too_low
  risk_cap:
    - chase_risk
    - high_volatility
EMERGING_TENBAGGER:
  hard_reject:
    - insufficient_price_history
    - liquidity_too_low
    - data_confidence_too_low
    - delisting_risk
    - catastrophic_runway
  risk_cap:
    - negative_fcf
    - operating_loss
    - high_sbc
    - high_volatility
    - dilution_risk
TOP7_MANAGER_DISCOVERY:
  hard_reject:
    - top7_signal_without_price_or_theme_confirmation
  risk_cap:
    - stale_13f_event
CYCLICAL_RECOVERY:
  hard_reject:
    - sector_cycle_not_confirmed
  risk_cap:
    - earnings_inflection_uncertain
CRISIS_BENEFICIARY:
  hard_reject:
    - crisis_state_not_active
  risk_cap:
    - low_liquidity
"""


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


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


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return df


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def production_snapshot(latest_run: Path) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for name in PROTECTED_OUTPUT_NAMES:
        path = latest_run / name
        if path.is_file():
            snapshot[str(path)] = {"exists": True, "sha256": file_sha256(path), "size": path.stat().st_size}
        elif path.is_dir():
            for child in sorted(p for p in path.rglob("*") if p.is_file()):
                snapshot[str(child)] = {"exists": True, "sha256": file_sha256(child), "size": child.stat().st_size}
        else:
            snapshot[str(path)] = {"exists": False, "sha256": "", "size": 0}
    return snapshot


def compare_snapshots(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, Any]:
    changed: list[str] = []
    missing: list[str] = []
    created: list[str] = []
    for path, meta in before.items():
        other = after.get(path)
        if other is None or not other.get("exists"):
            if meta.get("exists"):
                missing.append(path)
            continue
        if meta.get("sha256") != other.get("sha256") or meta.get("size") != other.get("size"):
            changed.append(path)
    for path, meta in after.items():
        if path not in before and meta.get("exists"):
            created.append(path)
    return {
        "status": "passed" if not changed and not missing and not created else "failed",
        "before_file_count": int(sum(1 for x in before.values() if x.get("exists"))),
        "after_file_count": int(sum(1 for x in after.values() if x.get("exists"))),
        "changed_files": changed,
        "missing_files": missing,
        "created_files": created,
        "allowed_output_roots": [
            "outputs/integrated_theme_leader_crisis_replay",
            "outputs/replay_integrity",
            "outputs/lane_allocator",
            "outputs/strategy_logic_ledger",
            "outputs/crisis_adjusted_replay",
        ],
    }


def pct(value: Any) -> str:
    number = safe_float(value, math.nan)
    return "" if not math.isfinite(number) else f"{number:.2%}"


def normalize_target_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "weight"])
    d = frame.copy()
    if "target_weight" in d.columns and "weight" not in d.columns:
        d["weight"] = d["target_weight"]
    for col in ("rebalance_date", "ticker", "weight"):
        if col not in d.columns:
            d[col] = "" if col != "weight" else 0.0
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)]
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def default_operating_book(latest_run: Path, portfolio_kind: str) -> Path:
    name = "operating_concentrated_target_book.csv" if portfolio_kind == "concentrated" else "operating_main_target_book.csv"
    return latest_run / "reports" / name


def target_rows_from_frame(frame: pd.DataFrame, portfolio_kind: str, variant_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in frame.to_dict("records"):
        out = dict(record)
        out["rebalance_date"] = pd.Timestamp(record["rebalance_date"]).date().isoformat()
        out["ticker"] = str(record.get("ticker") or "").upper()
        out["weight"] = safe_float(record.get("weight"))
        out["target_weight"] = safe_float(record.get("target_weight"), out["weight"])
        out["portfolio_kind"] = portfolio_kind
        out["variant_id"] = variant_id
        out.setdefault("primary_lane", record.get("primary_lane", "PRODUCTION_BASELINE"))
        out.setdefault("buy_reason", record.get("buy_reason", "production_baseline"))
        out.setdefault("hold_reason", record.get("hold_reason", "production_baseline"))
        rows.append(out)
    return rows


def target_price_coverage(target: pd.DataFrame, price_cache: Path) -> dict[str, Any]:
    if target.empty or "ticker" not in target.columns:
        return {"coverage": 0.0, "missing": []}
    tickers = sorted({str(x).upper().strip() for x in target["ticker"].dropna().unique() if str(x).upper().strip() not in {"", "CASH", "__CASH__"}})
    if not tickers:
        return {"coverage": 1.0, "missing": []}
    missing = [ticker for ticker in tickers if not (price_cache / px_cache_name(ticker)).exists()]
    return {"coverage": float((len(tickers) - len(missing)) / max(len(tickers), 1)), "missing": missing[:50]}


def price_frame(cache: Path, ticker: str) -> pd.DataFrame:
    px = load_price_series(cache, ticker)
    if px.empty:
        return pd.DataFrame()
    d = px.copy()
    d.index = pd.to_datetime(d.index, errors="coerce")
    d = d[~d.index.isna()].sort_index()
    d.index = pd.DatetimeIndex(d.index).normalize()
    if "close" not in d.columns:
        for col in ("Adj Close", "Close"):
            if col in d.columns:
                d["close"] = pd.to_numeric(d[col], errors="coerce")
                break
    return d.dropna(subset=["close"]) if "close" in d.columns else pd.DataFrame()


def build_daily_crisis_state(price_cache: Path, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    spy = price_frame(price_cache, "SPY")
    if spy.empty:
        dates = pd.bdate_range(start, end)
        return pd.DataFrame(
            {
                "date": dates,
                "crisis_state": "GREEN",
                "crisis_score": 0.0,
                "reentry_stage": "",
                "reentry_trigger": "",
            }
        )
    spy = spy[(spy.index >= start.normalize()) & (spy.index <= end.normalize())].copy()
    if spy.empty:
        dates = pd.bdate_range(start, end)
        return pd.DataFrame({"date": dates, "crisis_state": "GREEN", "crisis_score": 0.0, "reentry_stage": "", "reentry_trigger": ""})
    close = pd.to_numeric(spy["close"], errors="coerce")
    peak = close.cummax()
    drawdown = close / peak - 1.0
    ma20 = close.rolling(20, min_periods=5).mean()
    ma50 = close.rolling(50, min_periods=10).mean()
    states: list[str] = []
    stages: list[str] = []
    triggers: list[str] = []
    reentry_count = 0
    prior_defense = False
    for dt, dd in drawdown.items():
        px = float(close.loc[dt])
        above20 = bool(px >= float(ma20.loc[dt])) if pd.notna(ma20.loc[dt]) else True
        above50 = bool(px >= float(ma50.loc[dt])) if pd.notna(ma50.loc[dt]) else True
        if dd <= -0.20:
            state = "CRISIS_DEFENSE"
            prior_defense = True
            reentry_count = 0
            trigger = "drawdown_below_20pct"
        elif dd <= -0.12 or (dd <= -0.08 and not above50):
            state = "DEFENSE_REVIEW"
            prior_defense = True
            reentry_count = 0
            trigger = "drawdown_or_ma50_damage"
        elif prior_defense and dd > -0.12 and above20:
            state = "REENTRY_READY"
            reentry_count += 1
            trigger = "ma20_recovery_after_defense"
        elif dd <= -0.06 or not above20:
            state = "WATCH"
            trigger = "pullback_or_ma20_damage"
        else:
            state = "GREEN"
            prior_defense = False
            reentry_count = 0
            trigger = "risk_on"
        if state == "REENTRY_READY":
            stage = "REENTRY_STAGE_1" if reentry_count <= 5 else "REENTRY_STAGE_2" if reentry_count <= 15 else "REENTRY_STAGE_3"
        else:
            stage = ""
        states.append(state)
        stages.append(stage)
        triggers.append(trigger)
    out = pd.DataFrame(
        {
            "date": spy.index,
            "crisis_state": states,
            "crisis_score": (-drawdown * 2.0).clip(lower=0.0, upper=1.0).to_numpy(),
            "reentry_stage": stages,
            "reentry_trigger": triggers,
        }
    )
    return out.reset_index(drop=True)


def mutation_dates(states: pd.DataFrame, target_dates: list[pd.Timestamp]) -> set[pd.Timestamp]:
    out = {pd.Timestamp(x).normalize() for x in target_dates}
    if states.empty:
        return out
    d = states.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d = d.dropna(subset=["date"]).sort_values("date")
    last_emitted_state = ""
    last_action: pd.Timestamp | None = None
    monthly_counts: dict[str, int] = {}
    for row in d.to_dict("records"):
        dt = pd.Timestamp(row["date"]).normalize()
        state = str(row.get("crisis_state") or "GREEN")
        month_key = dt.strftime("%Y-%m")
        gap_ok = last_action is None or (dt - last_action).days >= int(CRISIS_HYSTERESIS["minimum_action_gap_days"])
        count_ok = monthly_counts.get(month_key, 0) < int(CRISIS_HYSTERESIS["max_crisis_actions_per_month"])
        shock_bypass = state == "CRISIS_DEFENSE" and bool(CRISIS_HYSTERESIS["shock_crash_immediate_bypass"])
        if state != last_emitted_state and count_ok and (gap_ok or shock_bypass):
            out.add(dt)
            last_action = dt
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
            last_emitted_state = state
        gap_ok = last_action is None or (dt - last_action).days >= int(CRISIS_HYSTERESIS["minimum_action_gap_days"])
        count_ok = monthly_counts.get(month_key, 0) < int(CRISIS_HYSTERESIS["max_crisis_actions_per_month"])
        if dt.weekday() == 4 and state != "GREEN" and count_ok and gap_ok:
            out.add(dt)
            last_action = dt
            monthly_counts[month_key] = monthly_counts.get(month_key, 0) + 1
            last_emitted_state = state
    return out


def latest_snapshot(target: pd.DataFrame, dt: pd.Timestamp) -> pd.DataFrame:
    dates = pd.to_datetime(target["rebalance_date"], errors="coerce").dropna()
    eligible = dates[dates <= dt.normalize()]
    if eligible.empty:
        return pd.DataFrame()
    snap_dt = pd.Timestamp(eligible.max()).normalize()
    return target[target["rebalance_date"].eq(snap_dt)].copy()


def latest_lane_snapshot(lane_history: pd.DataFrame, dt: pd.Timestamp) -> pd.DataFrame:
    if lane_history.empty or "rebalance_date" not in lane_history.columns:
        return pd.DataFrame()
    d = lane_history.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    eligible = d[d["rebalance_date"] <= dt.normalize()]
    if eligible.empty:
        return pd.DataFrame()
    snap_dt = pd.Timestamp(eligible["rebalance_date"].max()).normalize()
    return eligible[eligible["rebalance_date"].eq(snap_dt)].copy()


def apply_crisis_overlay(target: pd.DataFrame, lane_history: pd.DataFrame, states: pd.DataFrame, case_id: str, portfolio_kind: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target = normalize_target_book(target)
    if target.empty:
        return target, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    target_dates = sorted(pd.to_datetime(target["rebalance_date"], errors="coerce").dropna().unique())
    states = states.copy()
    states["date"] = pd.to_datetime(states["date"], errors="coerce").dt.normalize()
    states = states.dropna(subset=["date"]).sort_values("date")
    state_by_date = states.set_index("date").to_dict("index")
    dates = sorted(mutation_dates(states, [pd.Timestamp(x) for x in target_dates]))
    rows: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    cash_rows: list[dict[str, Any]] = []
    reentry_rows: list[dict[str, Any]] = []
    action_counts_by_month: dict[str, int] = {}
    for dt in dates:
        snap = latest_snapshot(target, dt)
        if snap.empty:
            continue
        state_row = state_by_date.get(dt)
        if state_row is None:
            prior = states[states["date"] <= dt]
            state_row = prior.iloc[-1].to_dict() if not prior.empty else {"crisis_state": "GREEN", "crisis_score": 0.0}
        state = str(state_row.get("crisis_state") or "GREEN")
        setting = CRISIS_SETTINGS.get(state, CRISIS_SETTINGS["GREEN"])
        cash_target = float(setting["cash"])
        lane_snap = latest_lane_snapshot(lane_history, dt)
        lane_map = {
            str(row.get("ticker") or "").upper(): str(row.get("primary_lane") or "MARKET_LEADER")
            for row in lane_snap.to_dict("records")
        }
        adjusted: list[dict[str, Any]] = []
        original_stock = float(snap.loc[~snap["ticker"].isin(CASH_TICKERS), "weight"].sum())
        for rec in snap.to_dict("records"):
            ticker = str(rec.get("ticker") or "").upper()
            if ticker in CASH_TICKERS:
                continue
            lane = str(rec.get("primary_lane") or lane_map.get(ticker) or "MARKET_LEADER")
            mult = float(setting["lane_multiplier"].get(lane, 0.80 if state != "GREEN" else 1.0))
            out = dict(rec)
            out["rebalance_date"] = dt.date().isoformat()
            out["primary_lane"] = lane
            out["weight"] = max(0.0, safe_float(rec.get("weight")) * mult)
            out["target_weight"] = out["weight"]
            out["crisis_state"] = state
            out["crisis_action_reason"] = str(state_row.get("reentry_trigger") or state)
            out["new_buy_allowed_by_lane"] = json.dumps(setting["new_buy_allowed"], sort_keys=True)
            adjusted.append(out)
        stock_total = sum(safe_float(x.get("weight")) for x in adjusted)
        target_stock = max(0.0, 1.0 - cash_target)
        scale = (target_stock / stock_total) if stock_total > target_stock and stock_total > 0 else 1.0
        for out in adjusted:
            out["weight"] = safe_float(out.get("weight")) * scale
            out["target_weight"] = out["weight"]
            rows.append(out)
        invested = sum(safe_float(x.get("weight")) for x in adjusted)
        cash_weight = max(0.0, 1.0 - invested)
        rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "ticker": "CASH",
                "weight": cash_weight,
                "target_weight": cash_weight,
                "portfolio_kind": portfolio_kind,
                "variant_id": f"{case_id}_{portfolio_kind}",
                "primary_lane": "CASH",
                "crisis_state": state,
                "crisis_action_reason": str(state_row.get("reentry_trigger") or state),
            }
        )
        month_key = dt.strftime("%Y-%m")
        action_counts_by_month[month_key] = action_counts_by_month.get(month_key, 0) + 1
        actions.append(
            {
                "case_id": case_id,
                "portfolio_kind": portfolio_kind,
                "date": dt.date().isoformat(),
                "from_state": "",
                "to_state": state,
                "action_type": "lane_aware_crisis_target_mutation",
                "lane_budget_before": json.dumps(LANE_BUDGETS_NORMAL, sort_keys=True),
                "lane_budget_after": json.dumps(setting["lane_multiplier"], sort_keys=True),
                "new_buy_allowed_by_lane": json.dumps(setting["new_buy_allowed"], sort_keys=True),
                "cash_target_before": max(0.0, 1.0 - original_stock),
                "cash_target_after": cash_weight,
                "gross_exposure_before": original_stock,
                "gross_exposure_after": invested,
                "affected_tickers": ",".join([str(x.get("ticker")) for x in adjusted]),
                "action_reason": str(state_row.get("reentry_trigger") or state),
                "lane_impacts": json.dumps(setting["lane_multiplier"], sort_keys=True),
                "theme_impacts": "",
                "action_blocked_by_hysteresis": False,
                "minimum_action_gap_days": CRISIS_HYSTERESIS["minimum_action_gap_days"],
                "crisis_action_count_month": action_counts_by_month[month_key],
                "max_crisis_actions_per_month": CRISIS_HYSTERESIS["max_crisis_actions_per_month"],
                "state_downgrade_confirmation_days": CRISIS_HYSTERESIS["state_downgrade_confirmation_days"],
                "state_upgrade_reentry_confirmation_days": CRISIS_HYSTERESIS["state_upgrade_reentry_confirmation_days"],
            }
        )
        cash_rows.append({"case_id": case_id, "portfolio_kind": portfolio_kind, "date": dt.date().isoformat(), "crisis_state": state, "cash_weight": cash_weight})
        if state == "REENTRY_READY":
            reentry_rows.append(
                {
                    "case_id": case_id,
                    "portfolio_kind": portfolio_kind,
                    "date": dt.date().isoformat(),
                    "reentry_stage": state_row.get("reentry_stage") or "REENTRY_STAGE_1",
                    "reentry_trigger": state_row.get("reentry_trigger") or "",
                    "reentry_deployed_cash": max(0.0, original_stock - invested),
                    "reentry_target_themes": "",
                }
            )
    return normalize_target_book(pd.DataFrame(rows)), pd.DataFrame(actions), pd.DataFrame(cash_rows), pd.DataFrame(reentry_rows)


def build_market_leader_book(candidate: pd.DataFrame, price_cache: Path, portfolio_kind: str, hold_replace: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    variant = (
        MarketLeaderVariant("concentrated", "integrated_market_leader_concentrated_N5", 5, 0.35, 0.70, 1.0)
        if portfolio_kind == "concentrated"
        else MarketLeaderVariant("main", "integrated_market_leader_main_N15", 15, 0.15, 0.40, 0.60)
    )
    tickers = {str(x).upper() for x in candidate["ticker"].dropna().unique()}
    tickers.update({"SPY", "QQQ"})
    prices = load_prices(price_cache, tickers)
    state_by_ticker: dict[str, dict[str, int]] = {}
    prev: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    for raw_dt in sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        month = candidate[candidate["rebalance_date"].eq(dt)].copy()
        scored = apply_state_history(score_market_leaders(month, prices, dt), state_by_ticker)
        selected = select_market_leader_targets(scored, variant, prev_holdings=prev if hold_replace else {})
        rows.extend(target_rows_from_selection(selected, variant, dt))
        prev = {str(row.get("ticker") or "").upper(): safe_float(row.get("weight")) for row in selected.to_dict("records")} if hold_replace else {}
        for rec in scored.to_dict("records"):
            state_rows.append({"rebalance_date": dt.date().isoformat(), "ticker": rec.get("ticker"), "leader_state": rec.get("leader_state"), "leader_tier": rec.get("leader_tier")})
    return normalize_target_book(pd.DataFrame(rows)), pd.DataFrame(state_rows)


def build_multi_lane_book(candidate: pd.DataFrame, portfolio_kind: str, hold_replace: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target_n = 5 if portfolio_kind == "concentrated" else 15
    single_cap = 0.35 if portfolio_kind == "concentrated" else 0.15
    max_emerging = 1 if portfolio_kind == "concentrated" else 3
    rows: list[dict[str, Any]] = []
    lane_history: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    exposure_rows: list[dict[str, Any]] = []
    prev: dict[str, float] = {}
    for raw_dt in sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        month = score_candidate_lanes(candidate[candidate["rebalance_date"].eq(dt)].copy())
        if month.empty:
            continue
        lane_history.extend(month.assign(rebalance_date=dt.date().isoformat()).to_dict("records"))
        selected: list[dict[str, Any]] = []
        selected_tickers: set[str] = set()
        if hold_replace and prev:
            month_by_ticker = {str(row.get("ticker") or "").upper(): row for row in month.to_dict("records")}
            for ticker, old_weight in sorted(prev.items(), key=lambda kv: -kv[1]):
                rec = month_by_ticker.get(ticker)
                if rec is None:
                    continue
                if str(rec.get("primary_lane")) == "EMERGING_TENBAGGER" and str(rec.get("emerging_tenbagger_hard_reject_reason") or ""):
                    rejected.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "rejection_reason": rec.get("emerging_tenbagger_hard_reject_reason"), "primary_lane": rec.get("primary_lane")})
                    continue
                out = dict(rec)
                out["weight"] = min(single_cap, safe_float(old_weight))
                out["hold_reason"] = "prior_holding_persistence"
                selected.append(out)
                selected_tickers.add(ticker)
                if len(selected) >= target_n:
                    break
        emerging_count = sum(1 for row in selected if str(row.get("primary_lane")) in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"})
        ranked = month.sort_values(["lane_confidence", "market_leader_lane_score"], ascending=False)
        for rec in ranked.to_dict("records"):
            ticker = str(rec.get("ticker") or "").upper()
            if not ticker or ticker in selected_tickers:
                continue
            lane = str(rec.get("primary_lane") or "")
            if lane == "EMERGING_TENBAGGER" and str(rec.get("emerging_tenbagger_hard_reject_reason") or ""):
                rejected.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "rejection_reason": rec.get("emerging_tenbagger_hard_reject_reason"), "primary_lane": lane})
                continue
            if lane in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"} and emerging_count >= max_emerging:
                rejected.append({"rebalance_date": dt.date().isoformat(), "ticker": ticker, "rejection_reason": "emerging_or_top7_seat_cap", "primary_lane": lane})
                continue
            out = dict(rec)
            out["weight"] = single_cap
            out["buy_reason"] = f"{lane}+lane_score"
            selected.append(out)
            selected_tickers.add(ticker)
            if lane in {"EMERGING_TENBAGGER", "TOP7_MANAGER_DISCOVERY"}:
                emerging_count += 1
            if len(selected) >= target_n:
                break
        raw_weight = sum(safe_float(row.get("weight")) for row in selected)
        scale = 1.0 / raw_weight if raw_weight > 1.0 else 1.0
        prev = {}
        lane_totals: dict[str, float] = {}
        for rec in selected:
            weight = safe_float(rec.get("weight")) * scale
            prev[str(rec.get("ticker") or "").upper()] = weight
            lane = str(rec.get("primary_lane") or "")
            lane_totals[lane] = lane_totals.get(lane, 0.0) + weight
            out = dict(rec)
            out.update(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": str(rec.get("ticker") or "").upper(),
                    "weight": weight,
                    "target_weight": weight,
                    "portfolio_kind": portfolio_kind,
                    "variant_id": f"integrated_multi_lane_{portfolio_kind}",
                    "lane_reason": rec.get("lane_reason", ""),
                    "theme_reason": rec.get("theme_reason", ""),
                    "evidence_reason": rec.get("evidence_reason", ""),
                }
            )
            rows.append(out)
        invested = sum(prev.values())
        if invested < 0.999:
            rows.append({"rebalance_date": dt.date().isoformat(), "ticker": "CASH", "weight": max(0.0, 1.0 - invested), "target_weight": max(0.0, 1.0 - invested), "portfolio_kind": portfolio_kind, "variant_id": f"integrated_multi_lane_{portfolio_kind}", "primary_lane": "CASH"})
        exposure_rows.append({"rebalance_date": dt.date().isoformat(), "portfolio_kind": portfolio_kind, **lane_totals})
    return normalize_target_book(pd.DataFrame(rows)), pd.DataFrame(lane_history), pd.DataFrame(rejected), pd.DataFrame(exposure_rows)


def stress_metrics(equity: pd.DataFrame, case_id: str, portfolio_kind: str) -> list[dict[str, Any]]:
    if equity.empty or "date" not in equity.columns or "equity_usd" not in equity.columns:
        return []
    d = equity.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    windows = {
        "covid_2020": ("2020-02-01", "2020-05-31"),
        "inflation_2022": ("2021-11-01", "2022-12-31"),
        "latest_12m": (pd.Timestamp(d["date"].max()) - pd.DateOffset(months=12), pd.Timestamp(d["date"].max())),
    }
    rows: list[dict[str, Any]] = []
    for name, (start, end) in windows.items():
        part = d[(d["date"] >= pd.Timestamp(start)) & (d["date"] <= pd.Timestamp(end))]
        if part.empty:
            continue
        eq = pd.to_numeric(part["equity_usd"], errors="coerce").dropna()
        if eq.empty:
            continue
        mdd = float((eq / eq.cummax() - 1.0).min())
        rows.append({"case_id": case_id, "portfolio_kind": portfolio_kind, "window": name, "window_mdd": mdd, "window_return": float(eq.iloc[-1] / eq.iloc[0] - 1.0), "avg_cash_weight": float(pd.to_numeric(part.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean()) if "cash_weight" in part.columns else ""})
    return rows


def enrich_ab_matrix(ab: pd.DataFrame, stress: pd.DataFrame, cash_by_state: pd.DataFrame) -> pd.DataFrame:
    if ab.empty:
        return ab
    out = ab.copy()
    if not stress.empty:
        for window, col in (("covid_2020", "covid_mdd"), ("inflation_2022", "rate_2022_mdd")):
            part = stress[stress["window"].astype(str).eq(window)].copy()
            if not part.empty:
                mapping = {
                    (str(row.get("case_id")), str(row.get("portfolio_kind"))): row.get("window_mdd")
                    for row in part.to_dict("records")
                }
                out[col] = [mapping.get((str(row.case_id), str(row.portfolio_kind)), row._asdict().get(col, "")) for row in out.itertuples(index=False)]
    if not cash_by_state.empty and {"case_id", "portfolio_kind", "crisis_state", "cash_weight"}.issubset(cash_by_state.columns):
        green = cash_by_state[cash_by_state["crisis_state"].astype(str).eq("GREEN")].copy()
        if not green.empty:
            green["cash_weight"] = pd.to_numeric(green["cash_weight"], errors="coerce")
            mapping = green.groupby(["case_id", "portfolio_kind"])["cash_weight"].mean().to_dict()
            out["green_avg_cash"] = [mapping.get((row.case_id, row.portfolio_kind), getattr(row, "green_avg_cash", "")) for row in out.itertuples(index=False)]
    return out


def add_numeric_completeness_flags(ab: pd.DataFrame) -> pd.DataFrame:
    if ab.empty:
        return ab
    out = ab.copy()
    flags_by_row: list[str] = []
    status_by_row: list[str] = []
    numeric_required = {
        "covid_mdd": "missing_covid_mdd",
        "rate_2022_mdd": "missing_rate_2022_mdd",
    }
    crisis_required = {
        "green_avg_cash": "missing_green_avg_cash",
        "cash_trap_days": "missing_cash_trap_days",
    }

    for record in out.to_dict("records"):
        flags: list[str] = []
        completed = str(record.get("status") or "").lower() == "completed"
        crisis_enabled = bool(record.get("crisis_overlay_enabled"))
        if completed:
            for col, flag in numeric_required.items():
                value = safe_float(record.get(col), math.nan)
                if not math.isfinite(value):
                    flags.append(flag)
        if completed and crisis_enabled:
            for col, flag in crisis_required.items():
                value = safe_float(record.get(col), math.nan)
                if not math.isfinite(value):
                    flags.append(flag)
        flags_by_row.append(",".join(flags))
        status_by_row.append("REVIEW_REQUIRED" if flags else "OK")
    out["review_flags"] = flags_by_row
    out["review_status"] = status_by_row
    return out


def delta_decomposition(ab: pd.DataFrame) -> pd.DataFrame:
    pairs = [
        ("B-A", "B", "A", "crisis-only effect"),
        ("C-A", "C", "A", "leader-only effect"),
        ("D-C", "D", "C", "crisis effect on leader portfolio"),
        ("E-C", "E", "C", "hold/replace effect"),
        ("F-D", "F", "D", "hold/replace effect under crisis"),
        ("G-E", "G", "E", "multi-lane effect"),
        ("H-G", "H", "G", "crisis effect on multi-lane"),
        ("H-A", "H", "A", "total integrated effect"),
    ]
    if ab.empty:
        return pd.DataFrame(columns=["delta_id", "portfolio_kind", "effect", "cagr_delta", "max_dd_delta", "avg_cash_delta", "fees_delta"])
    rows: list[dict[str, Any]] = []
    by_key = {(str(row.get("case_id")), str(row.get("portfolio_kind"))): row for row in ab.to_dict("records")}
    for portfolio_kind in sorted({str(x) for x in ab["portfolio_kind"].dropna().unique()}):
        for delta_id, lhs, rhs, effect in pairs:
            left = by_key.get((lhs, portfolio_kind))
            right = by_key.get((rhs, portfolio_kind))
            def diff(col: str) -> float | str:
                if left is None or right is None:
                    return ""
                a = safe_float(left.get(col), math.nan)
                b = safe_float(right.get(col), math.nan)
                return (a - b) if math.isfinite(a) and math.isfinite(b) else ""
            rows.append(
                {
                    "delta_id": delta_id,
                    "portfolio_kind": portfolio_kind,
                    "lhs_case": lhs,
                    "rhs_case": rhs,
                    "effect": effect,
                    "cagr_delta": diff("cagr"),
                    "max_dd_delta": diff("max_dd"),
                    "avg_cash_delta": diff("avg_cash_weight"),
                    "fees_delta": diff("total_fees_usd"),
                }
            )
    return pd.DataFrame(rows)


def top3_stability_report(ab: pd.DataFrame, baseline: dict[str, Any]) -> pd.DataFrame:
    if ab.empty:
        return pd.DataFrame(
            columns=[
                "portfolio_kind",
                "top3_median_cagr",
                "top3_median_max_dd",
                "best_vs_top3_median_cagr_gap",
                "top3_median_cagr_required",
                "top3_median_max_dd_required",
                "top3_median_pass",
            ]
        )
    rows: list[dict[str, Any]] = []
    d = ab.copy()
    d["cagr"] = pd.to_numeric(d["cagr"], errors="coerce")
    d["max_dd"] = pd.to_numeric(d["max_dd"], errors="coerce")
    d = d.dropna(subset=["cagr", "max_dd"])
    for portfolio_kind, part in d.groupby("portfolio_kind"):
        top = part.sort_values("cagr", ascending=False).head(3)
        baseline_cagr = safe_float(baseline.get(f"{portfolio_kind}_cagr"), math.nan)
        if not math.isfinite(baseline_cagr):
            base_port = baseline.get(portfolio_kind, {}) if isinstance(baseline.get(portfolio_kind), dict) else {}
            baseline_cagr = safe_float(base_port.get("cagr"), math.nan)
        if str(portfolio_kind) == "concentrated":
            cagr_required = baseline_cagr - 0.03 if math.isfinite(baseline_cagr) else math.nan
            mdd_required = -0.32
            gap_required = 0.05
        else:
            cagr_required = baseline_cagr - 0.005 if math.isfinite(baseline_cagr) else math.nan
            mdd_required = -0.27
            gap_required = 0.03
        top3_cagr = float(top["cagr"].median()) if not top.empty else math.nan
        top3_mdd = float(top["max_dd"].median()) if not top.empty else math.nan
        gap = float(top["cagr"].max() - top3_cagr) if not top.empty and math.isfinite(top3_cagr) else math.nan
        pass_flag = (
            math.isfinite(top3_cagr)
            and math.isfinite(top3_mdd)
            and (not math.isfinite(cagr_required) or top3_cagr >= cagr_required)
            and top3_mdd >= mdd_required
            and (not math.isfinite(gap) or gap <= gap_required)
        )
        rows.append(
            {
                "portfolio_kind": portfolio_kind,
                "top3_median_cagr": top3_cagr if math.isfinite(top3_cagr) else "",
                "top3_median_max_dd": top3_mdd if math.isfinite(top3_mdd) else "",
                "best_vs_top3_median_cagr_gap": gap if math.isfinite(gap) else "",
                "top3_median_cagr_required": cagr_required if math.isfinite(cagr_required) else "",
                "top3_median_max_dd_required": mdd_required,
                "best_vs_top3_median_cagr_gap_required": gap_required,
                "cost_sensitivity_required_bps": "25,50,75,100",
                "cost_sensitivity_50bps_required": "thesis_maintained",
                "cost_sensitivity_75bps_action": "review_if_sharp_decay",
                "cost_sensitivity_100bps_action": "reject_if_collapsed",
                "top3_median_pass": bool(pass_flag),
            }
        )
    return pd.DataFrame(rows)


def case_failure_reasons(ab: pd.DataFrame) -> pd.DataFrame:
    if ab.empty:
        return pd.DataFrame(columns=["case_id", "portfolio_kind", "failure_reason"])
    rows: list[dict[str, Any]] = []
    for rec in ab.to_dict("records"):
        reasons: list[str] = []
        if str(rec.get("status") or "").lower() != "completed":
            reasons.append(str(rec.get("status") or "not_completed"))
        if str(rec.get("metric_mode") or "") != "broker_ledger_next_close":
            reasons.append("metric_mode_not_broker_ledger_next_close")
        if str(rec.get("metric_mode_review") or "") == "DO_NOT_USE":
            reasons.append("preflight_do_not_use")
        review_flags = str(rec.get("review_flags") or "").strip()
        if review_flags and review_flags.lower() not in {"nan", "none"}:
            reasons.append(review_flags)
        if str(rec.get("target_book_filter_source") or "") == "default_static":
            reasons.append("default_static_filter")
        if reasons:
            rows.append(
                {
                    "case_id": rec.get("case_id"),
                    "portfolio_kind": rec.get("portfolio_kind"),
                    "selection_layer": rec.get("selection_layer"),
                    "failure_reason": ",".join(reasons),
                }
            )
    return pd.DataFrame(rows)


def emerging_outputs(lane_history: pd.DataFrame, rejected: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    empty_cols = [
        "rebalance_date",
        "ticker",
        "lane",
        "negative_fcf",
        "loss_making",
        "cash_runway_quarters",
        "dilution_4q",
        "liquidity_pass",
        "theme_status",
        "rs_1m_3m_6m",
        "risk_cap_multiplier",
        "hard_reject_reason",
    ]
    if lane_history.empty:
        return pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols)
    d = lane_history.copy()
    emerging = d[d.get("primary_lane", pd.Series(dtype=str)).astype(str).eq("EMERGING_TENBAGGER")].copy()
    if emerging.empty:
        return pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols), pd.DataFrame(columns=empty_cols)
    out = pd.DataFrame(
        {
            "rebalance_date": emerging.get("rebalance_date", ""),
            "ticker": emerging.get("ticker", ""),
            "lane": "EMERGING_TENBAGGER",
            "negative_fcf": (
                pd.to_numeric(emerging.get("fcf_ttm", pd.Series(0.0, index=emerging.index)), errors="coerce").fillna(0.0) < 0
            )
            | (
                pd.to_numeric(emerging.get("fcf_margin", pd.Series(0.0, index=emerging.index)), errors="coerce").fillna(0.0) < 0
            ),
            "loss_making": (
                pd.to_numeric(emerging.get("net_income_ttm", pd.Series(0.0, index=emerging.index)), errors="coerce").fillna(0.0) < 0
            )
            | (
                pd.to_numeric(emerging.get("op_income_ttm", pd.Series(0.0, index=emerging.index)), errors="coerce").fillna(0.0) < 0
            ),
            "cash_runway_quarters": emerging.get("cash_runway_quarters", ""),
            "dilution_4q": emerging.get("dilution_4q", ""),
            "liquidity_pass": pd.to_numeric(emerging.get("dollar_vol_20d", pd.Series(0.0, index=emerging.index)), errors="coerce").fillna(0.0) >= 5_000_000,
            "theme_status": emerging.get("theme_phase_primary", ""),
            "rs_1m_3m_6m": emerging.get("rs_benchmark_3m", ""),
            "risk_cap_multiplier": emerging.get("emerging_tenbagger_risk_cap", ""),
            "hard_reject_reason": emerging.get("emerging_tenbagger_hard_reject_reason", ""),
        }
    )
    survivors = out[out["hard_reject_reason"].astype(str).eq("")].copy()
    rejected_emerging = out[out["hard_reject_reason"].astype(str).ne("")].copy()
    if not rejected.empty and "primary_lane" in rejected.columns:
        extra = rejected[rejected["primary_lane"].astype(str).eq("EMERGING_TENBAGGER")].copy()
        if not extra.empty:
            extra_out = pd.DataFrame(
                {
                    "rebalance_date": extra.get("rebalance_date", ""),
                    "ticker": extra.get("ticker", ""),
                    "lane": "EMERGING_TENBAGGER",
                    "negative_fcf": "",
                    "loss_making": "",
                    "cash_runway_quarters": "",
                    "dilution_4q": "",
                    "liquidity_pass": "",
                    "theme_status": "",
                    "rs_1m_3m_6m": "",
                    "risk_cap_multiplier": "",
                    "hard_reject_reason": extra.get("rejection_reason", ""),
                }
            )
            rejected_emerging = pd.concat([rejected_emerging, extra_out], ignore_index=True)
    return survivors, rejected_emerging, out


def run_case(
    *,
    case: CaseSpec,
    portfolio_kind: str,
    latest_run: Path,
    candidate: pd.DataFrame,
    price_cache: Path,
    out_dir: Path,
    crisis_states: pd.DataFrame,
    baseline_lock: Path | None,
    artifact_id: str,
    cost_bps: float,
) -> tuple[dict[str, Any], pd.DataFrame, dict[str, pd.DataFrame]]:
    case_dir = out_dir / "cases" / case.case_id / portfolio_kind
    case_dir.mkdir(parents=True, exist_ok=True)
    diagnostics: dict[str, pd.DataFrame] = {}
    if case.selection_layer == "production":
        source_path = default_operating_book(latest_run, portfolio_kind)
        target = normalize_target_book(read_table(source_path))
        target["variant_id"] = f"{case.case_id}_{portfolio_kind}"
        target["primary_lane"] = target.get("primary_lane", "PRODUCTION_BASELINE")
        lane_history = pd.DataFrame()
        rejected = pd.DataFrame()
    elif case.selection_layer == "market_leader":
        target, leader_state = build_market_leader_book(candidate, price_cache, portfolio_kind, hold_replace=case.hold_replace_enabled)
        target["variant_id"] = f"{case.case_id}_{portfolio_kind}"
        lane_history = pd.DataFrame()
        rejected = pd.DataFrame()
        diagnostics["leader_state_history"] = leader_state.assign(case_id=case.case_id, portfolio_kind=portfolio_kind)
    else:
        target, lane_history, rejected, lane_exposure = build_multi_lane_book(candidate, portfolio_kind, hold_replace=case.hold_replace_enabled)
        target["variant_id"] = f"{case.case_id}_{portfolio_kind}"
        diagnostics["lane_scores_history"] = lane_history.assign(case_id=case.case_id, portfolio_kind=portfolio_kind) if not lane_history.empty else lane_history
        diagnostics["rejected_by_lane_reason"] = rejected.assign(case_id=case.case_id, portfolio_kind=portfolio_kind) if not rejected.empty else rejected
        diagnostics["lane_exposure_by_month"] = lane_exposure.assign(case_id=case.case_id, portfolio_kind=portfolio_kind) if not lane_exposure.empty else lane_exposure
    actions = cash_by_state = reentry = pd.DataFrame()
    if case.crisis_overlay:
        target, actions, cash_by_state, reentry = apply_crisis_overlay(target, lane_history, crisis_states, case.case_id, portfolio_kind)
        diagnostics["crisis_actions"] = actions
        diagnostics["cash_by_crisis_state"] = cash_by_state
        diagnostics["reentry_events"] = reentry
    target_path = case_dir / "target_book.csv"
    target.to_csv(target_path, index=False)
    coverage = target_price_coverage(target, price_cache)
    if safe_float(coverage.get("coverage"), 0.0) < 0.80:
        (case_dir / "broker_replay").mkdir(parents=True, exist_ok=True)
        metrics = {
            "status": "blocked",
            "reason": "PRICE_CACHE_INCOMPLETE",
            "reason_detail": "price_cache_coverage_below_80pct",
            "metric_mode": "DO_NOT_USE",
            "metric_mode_review": "DO_NOT_USE",
            "valid_for_production": False,
            "research_only": True,
            "production_activation_allowed": False,
            "price_cache_coverage": coverage.get("coverage"),
            "price_cache_missing_tickers": coverage.get("missing"),
            "target_book_filter_source": "disabled_explicit" if portfolio_kind == "concentrated" and case.selection_layer != "production" else "",
        }
        write_json(case_dir / "broker_replay" / "metrics.json", metrics)
    else:
        try:
            metrics = broker_replay(
                target_book=target_path,
                price_cache=price_cache,
                output_dir=case_dir / "broker_replay",
                portfolio_kind=portfolio_kind,
                fill_mode="next_close",
                cost_bps=cost_bps,
                integer_shares=True,
                concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy() if case.selection_layer != "production" else None,
            )
        except Exception as exc:
            (case_dir / "broker_replay").mkdir(parents=True, exist_ok=True)
            metrics = {
                "status": "error",
                "reason": str(exc),
                "metric_mode": "DO_NOT_USE",
                "metric_mode_review": "DO_NOT_USE",
                "valid_for_production": False,
                "research_only": True,
                "production_activation_allowed": False,
            }
            write_json(case_dir / "broker_replay" / "metrics.json", metrics)
    preflight = build_preflight_report(
        latest_run=latest_run,
        output_dir=case_dir / "replay_integrity",
        baseline_lock=baseline_lock,
        candidate_book_arg=None,
        target_book=target_path,
        broker_output_dir=case_dir / "broker_replay",
        metrics_json=case_dir / "broker_replay" / "metrics.json",
        price_cache=price_cache,
        portfolio_kind=portfolio_kind,
        artifact_id=artifact_id,
        asof_date=None,
    )
    if preflight.get("blockers"):
        metrics["metric_mode_review"] = "DO_NOT_USE"
    metrics["candidate_source_mode"] = preflight.get("candidate_source_mode", "")
    metrics["target_book_filter_source"] = preflight.get("target_book_filter_source", metrics.get("target_book_filter_source", ""))
    metrics["requested_target_n"] = preflight.get("requested_target_n", "")
    metrics["actual_median_position_count"] = preflight.get("actual_median_position_count", "")
    metrics["actual_latest_position_count"] = preflight.get("actual_latest_position_count", "")
    metrics["price_cache_coverage"] = preflight.get("price_cache_coverage", metrics.get("price_cache_coverage", ""))
    write_json(case_dir / "case_summary.json", {"case": case.__dict__, "metrics": metrics, "preflight": preflight})
    return metrics, target, diagnostics


def case_row(case: CaseSpec, portfolio_kind: str, metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    base_port = baseline.get(portfolio_kind, {}) if isinstance(baseline.get(portfolio_kind), dict) else {}
    cagr = safe_float(metrics.get("cagr"), math.nan)
    mdd = safe_float(metrics.get("max_dd"), math.nan)
    base_cagr = safe_float(base_port.get("cagr") or baseline.get(f"{portfolio_kind}_cagr"), math.nan)
    base_mdd = safe_float(base_port.get("max_dd") or baseline.get(f"{portfolio_kind}_max_dd"), math.nan)
    return {
        "case_id": case.case_id,
        "portfolio_kind": portfolio_kind,
        "selection_layer": case.selection_layer,
        "lane_allocator_enabled": case.selection_layer == "multi_lane",
        "market_leader_enabled": case.selection_layer == "market_leader",
        "crisis_overlay": bool(case.crisis_overlay),
        "crisis_overlay_enabled": bool(case.crisis_overlay),
        "hold_replace_enabled": bool(case.hold_replace_enabled),
        "reentry_enabled": bool(case.crisis_overlay),
        "top7_enabled": case.selection_layer == "multi_lane",
        "theme_enabled": case.selection_layer in {"market_leader", "multi_lane"},
        "purpose": case.purpose,
        "status": metrics.get("status"),
        "metric_mode": metrics.get("metric_mode"),
        "metric_mode_review": metrics.get("metric_mode_review", ""),
        "candidate_source_mode": metrics.get("candidate_source_mode", ""),
        "target_book_filter_source": metrics.get("target_book_filter_source", ""),
        "requested_target_n": metrics.get("requested_target_n", ""),
        "actual_median_position_count": metrics.get("actual_median_position_count", ""),
        "actual_latest_position_count": metrics.get("actual_latest_position_count", ""),
        "price_cache_coverage": metrics.get("price_cache_coverage", ""),
        "cagr": cagr,
        "max_dd": mdd,
        "sharpe": metrics.get("sharpe"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "green_avg_cash": "",
        "covid_mdd": "",
        "rate_2022_mdd": "",
        "reentry_lag_days": "",
        "rebound_capture": "",
        "cash_trap_days": "",
        "turnover": metrics.get("turnover") or metrics.get("trade_count"),
        "trade_count": metrics.get("trade_count"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "fees": metrics.get("total_fees_usd"),
        "cagr_delta_vs_baseline": (cagr - base_cagr) if math.isfinite(cagr) and math.isfinite(base_cagr) else "",
        "mdd_improvement_vs_baseline": (mdd - base_mdd) if math.isfinite(mdd) and math.isfinite(base_mdd) else "",
        "research_only": True,
        "production_activation_allowed": False,
    }


def render_report(summary: dict[str, Any], ab: pd.DataFrame) -> str:
    lines = [
        "# Integrated Theme-Leader-Crisis Replay",
        "",
        "Research-only 8-case A/B matrix. Production activation remains forbidden.",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Baseline lock: `{summary.get('baseline_lock')}`",
        f"- Candidate source: `{summary.get('candidate_source_mode')}`",
        "",
        "## A/B Matrix",
        "",
    ]
    for row in ab.to_dict("records"):
        lines.append(
            f"- `{row.get('case_id')}` {row.get('portfolio_kind')} {row.get('purpose')}: CAGR {pct(row.get('cagr'))}, MDD {pct(row.get('max_dd'))}, cash {pct(row.get('avg_cash_weight'))}, mode `{row.get('metric_mode')}`"
        )
    lines.extend(["", "All metrics are broker-ledger next-close research evidence only."])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--baseline-lock", default="outputs/baseline_lock/active_baseline.json")
    parser.add_argument("--allow-missing-baseline-lock", action="store_true")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--artifact-id", default="")
    parser.add_argument("--default-only", action="store_true", help="Run A/F/H only for quick local inspection")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    price_cache = repo_path(args.price_cache)
    baseline_lock = repo_path(args.baseline_lock) if args.baseline_lock else None
    baseline = read_json(baseline_lock) if baseline_lock else {}
    output_dir.mkdir(parents=True, exist_ok=True)
    production_before = production_snapshot(latest_run)
    if not baseline and not args.allow_missing_baseline_lock:
        payload = {
            "status": "blocked",
            "reason": "active_baseline.json is required unless --allow-missing-baseline-lock is set",
            "metric_mode": "DO_NOT_USE",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        print(f"[integrated-replay] blocked: {payload['reason']}")
        return 0

    candidate_book, source_mode = resolve_candidate_book(latest_run, args.candidate_book)
    candidate = normalize_candidate_frame(read_table(candidate_book))
    if candidate.empty or source_mode == "latest_only_blocked":
        payload = {
            "status": "blocked",
            "reason": "historical candidate_replay_book.csv is required",
            "candidate_book": str(candidate_book),
            "candidate_source_mode": source_mode,
            "metric_mode": "DO_NOT_USE",
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        print(f"[integrated-replay] blocked: {payload['reason']}")
        return 0

    dates = pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna()
    crisis_states = build_daily_crisis_state(price_cache, pd.Timestamp(dates.min()), pd.Timestamp(dates.max()))
    crisis_states.to_csv(output_dir / "daily_crisis_state.csv", index=False)
    write_json(output_dir / "lane_feature_mapping.json", lane_feature_mapping_payload())
    write_json(output_dir / "lane_budget_by_regime.json", {"normal": LANE_BUDGETS_NORMAL, "crisis_settings": CRISIS_SETTINGS})
    write_json(output_dir / "crisis_hysteresis_config.json", CRISIS_HYSTERESIS)
    write_json(output_dir / "hold_replace_policy.json", HOLD_REPLACE_POLICY)
    (output_dir / "lane_rules.yaml").write_text(LANE_RULES_YAML, encoding="utf-8")

    portfolio_kinds = ["main", "concentrated"] if args.portfolio_kind == "both" else [args.portfolio_kind]
    case_specs = CASES
    if args.default_only:
        case_specs = [case for case in CASES if case.case_id in {"A", "F", "H"}]
    ab_rows: list[dict[str, Any]] = []
    stress_rows: list[dict[str, Any]] = []
    all_targets: list[pd.DataFrame] = []
    diag_frames: dict[str, list[pd.DataFrame]] = {
        "crisis_actions": [],
        "cash_by_crisis_state": [],
        "reentry_events": [],
        "lane_scores_history": [],
        "lane_exposure_by_month": [],
        "rejected_by_lane_reason": [],
        "leader_state_history": [],
    }
    for case in case_specs:
        for portfolio_kind in portfolio_kinds:
            metrics, target, diagnostics = run_case(
                case=case,
                portfolio_kind=portfolio_kind,
                latest_run=latest_run,
                candidate=candidate,
                price_cache=price_cache,
                out_dir=output_dir,
                crisis_states=crisis_states,
                baseline_lock=baseline_lock if baseline else None,
                artifact_id=str(args.artifact_id or ""),
                cost_bps=float(args.cost_bps),
            )
            ab_rows.append(case_row(case, portfolio_kind, metrics, baseline))
            target["case_id"] = case.case_id
            target["portfolio_kind"] = portfolio_kind
            all_targets.append(target)
            eq = read_table(output_dir / "cases" / case.case_id / portfolio_kind / "broker_replay" / "equity_curve.csv")
            stress_rows.extend(stress_metrics(eq, case.case_id, portfolio_kind))
            for name, frame in diagnostics.items():
                if name in diag_frames and frame is not None and not frame.empty:
                    diag_frames[name].append(frame)

    stress_df = pd.DataFrame(stress_rows)
    cash_df = pd.concat(diag_frames["cash_by_crisis_state"], ignore_index=True) if diag_frames["cash_by_crisis_state"] else pd.DataFrame()
    ab = enrich_ab_matrix(pd.DataFrame(ab_rows), stress_df, cash_df)
    ab = add_numeric_completeness_flags(ab)
    ab = write_csv(output_dir / "ab_matrix.csv", ab)
    write_csv(output_dir / "ab_delta_decomposition.csv", delta_decomposition(ab))
    top3_stability = write_csv(output_dir / "top3_stability.csv", top3_stability_report(ab, baseline))
    failures = write_csv(output_dir / "case_failure_reasons.csv", case_failure_reasons(ab))
    write_csv(output_dir / "stress_window_metrics.csv", stress_df)
    write_csv(output_dir / "lane_target_book.csv", pd.concat(all_targets, ignore_index=True) if all_targets else pd.DataFrame())
    for name, frames in diag_frames.items():
        write_csv(output_dir / f"{name}.csv", pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    lane_history_all = pd.concat(diag_frames["lane_scores_history"], ignore_index=True) if diag_frames["lane_scores_history"] else pd.DataFrame()
    rejected_all = pd.concat(diag_frames["rejected_by_lane_reason"], ignore_index=True) if diag_frames["rejected_by_lane_reason"] else pd.DataFrame()
    emerging_survivors, emerging_rejected, emerging_risk_caps = emerging_outputs(lane_history_all, rejected_all)
    write_csv(output_dir / "emerging_survivors.csv", emerging_survivors)
    write_csv(output_dir / "emerging_rejected.csv", emerging_rejected)
    write_csv(output_dir / "emerging_risk_caps.csv", emerging_risk_caps)
    # Contract placeholders for downstream dashboards; populated as the replay matures.
    for name in [
        "cost_sensitivity.csv",
        "cash_trap_days.csv",
        "leader_rotation_events.csv",
        "theme_exposure_by_month.csv",
        "hold_duration_distribution.csv",
        "reentry_lag_by_event.csv",
        "missed_rebound_report.csv",
        "wrong_substitution_report.csv",
        "false_alarm_report.csv",
        "false_alarm_cash_drag.csv",
        "cash_trap_after_reentry.csv",
        "same_subindustry_exposure.csv",
        "actual_median_position_count.csv",
    ]:
        path = output_dir / name
        if not path.exists():
            pd.DataFrame().to_csv(path, index=False)
    mutation_check = compare_snapshots(production_before, production_snapshot(latest_run))
    write_json(output_dir / "production_mutation_check.json", mutation_check)
    write_json(output_dir / "replay_integrity" / "production_mutation_check.json", mutation_check)
    replay_gate_status = {
        "status": "passed" if failures.empty and mutation_check.get("status") == "passed" else "review_required",
        "case_failure_count": int(len(failures)),
        "production_mutation_check": mutation_check.get("status"),
        "top3_stability_rows": int(len(top3_stability)),
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(output_dir / "replay_gate_status.json", replay_gate_status)
    (output_dir / "case_level_summary.md").write_text(
        "# Case Level Summary\n\n"
        f"- Cases: `{len(ab)}`\n"
        f"- Case failures/reviews: `{len(failures)}`\n"
        f"- Production mutation check: `{mutation_check.get('status')}`\n"
        "- Production activation remains forbidden.\n",
        encoding="utf-8",
    )
    summary = {
        "schema_version": "integrated-theme-leader-crisis-replay-v1",
        "status": "completed",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "rebalance_date_count": int(dates.nunique()),
        "baseline_lock": str(baseline_lock) if baseline_lock else "",
        "baseline_lock_loaded": bool(baseline),
        "case_count": int(len(ab)),
        "research_only": True,
        "production_activation_allowed": False,
        "production_score_mutated": False,
        "production_target_defaults_changed": False,
        "feature_store_mutated": False,
        "production_mutation_check": mutation_check.get("status"),
        "official_metric_required": "broker_ledger_next_close",
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, ab), encoding="utf-8")
    print(f"[integrated-replay] wrote {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
