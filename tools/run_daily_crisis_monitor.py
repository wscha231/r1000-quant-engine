#!/usr/bin/env python3
"""Daily after-close crisis monitor for the current operating book.

This tool emits review states only.  It never changes target books, raises cash,
or places orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_long_crisis_liquidity import cash_raise_decision  # noqa: E402


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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.suffix.lower() == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except Exception:
        return default


def _latest_observable_long_crisis_row(features_path: Path) -> tuple[pd.Timestamp | None, pd.Series]:
    features = read_table(features_path)
    if features.empty:
        return None, pd.Series(dtype=float)
    d = features.copy()
    date_col = None
    for candidate in ("date", "Date", "as_of_date"):
        if candidate in d.columns:
            date_col = candidate
            break
    if date_col is not None:
        idx = pd.to_datetime(d.pop(date_col), errors="coerce")
    else:
        idx = pd.to_datetime(d.index, errors="coerce")
    d.index = idx
    d = d[~d.index.isna()].sort_index()
    if d.empty:
        return None, pd.Series(dtype=float)

    # The long-crisis research table carries future labels for learning.
    # The daily monitor must never use them when deciding today's state.
    observable_cols = [
        col
        for col in d.columns
        if not str(col).startswith("future_") and str(col) not in {"false_alarm_no_drawdown_63d"}
    ]
    d = d[observable_cols]
    row = d.iloc[-1].copy()
    return pd.Timestamp(d.index[-1]).normalize(), row


def _load_long_crisis_thresholds(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    governor = payload.get("governor_thresholds") if isinstance(payload.get("governor_thresholds"), dict) else {}
    cash_gate = payload.get("cash_hard_gate") if isinstance(payload.get("cash_hard_gate"), dict) else {}
    return {
        "low": safe_float(governor.get("low"), 0.35),
        "mid": safe_float(governor.get("mid"), 0.55),
        "high": safe_float(governor.get("high"), 0.75),
        "liquidity_gate": safe_float(cash_gate.get("liquidity_gate"), 0.35),
        "trend_gate": safe_float(cash_gate.get("trend_gate"), 0.35),
        "credit_gate": safe_float(cash_gate.get("credit_gate"), 0.55),
        "source": str(path) if path.exists() else "default_thresholds",
    }


def infer_long_crisis_state(features_path: Path, thresholds_path: Path) -> tuple[str, list[str], dict[str, Any]]:
    latest_date, row = _latest_observable_long_crisis_row(features_path)
    if latest_date is None or row.empty:
        return "GREEN", [], {
            "available": False,
            "features": str(features_path),
            "thresholds": str(thresholds_path),
            "reason": "missing_long_crisis_features",
        }

    thresholds = _load_long_crisis_thresholds(thresholds_path)
    crisis_score = safe_float(row.get("crisis_score"), 0.0)
    decision = cash_raise_decision(
        row,
        crisis_score,
        mid_threshold=float(thresholds["mid"]),
        liquidity_gate=float(thresholds["liquidity_gate"]),
        trend_gate=float(thresholds["trend_gate"]),
        credit_gate=float(thresholds["credit_gate"]),
    )
    low = float(thresholds["low"])
    mid = float(thresholds["mid"])
    if crisis_score >= mid and decision.allowed and decision.reason == "systemic_confirmation_pass":
        state = "DEFENSE_REVIEW"
    elif crisis_score >= low:
        state = "WATCH"
    else:
        state = "GREEN"

    meta = {
        "available": True,
        "features": str(features_path),
        "thresholds": str(thresholds_path),
        "threshold_source": thresholds["source"],
        "latest_date": latest_date.date().isoformat(),
        "crisis_score": crisis_score,
        "low_threshold": low,
        "mid_threshold": mid,
        "high_threshold": float(thresholds["high"]),
        "liquidity_confirmation_score": safe_float(row.get("liquidity_confirmation_score"), 0.0),
        "market_trend_damage_score": safe_float(row.get("market_trend_damage_score"), 0.0),
        "credit_stress_score": safe_float(row.get("credit_stress_score"), 0.0),
        "cash_gate_allowed": bool(decision.allowed),
        "cash_gate_reason": decision.reason,
        "observable_field_count": int(len(row.index)),
        "future_labels_excluded": True,
        "state": state,
    }
    reasons = [
        "long-crisis learned "
        f"state={state} score={crisis_score:.3f} date={meta['latest_date']} cash_gate={decision.reason}"
    ]
    return state, reasons, meta


def infer_raw_state(latest_run: Path, long_crisis_features: Path, long_crisis_thresholds: Path) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    risk = read_json(latest_run / "live_trading_risk_controls" / "risk_controls_summary.json")
    safety = read_json(latest_run / "live_trading_safety" / "safety_audit_summary.json")
    macro = read_json(latest_run / "macro_policy_engine" / "summary.json")
    snapshot = read_json(latest_run / "operating_snapshot" / "current_portfolio_snapshot_summary.json")
    long_state, long_reasons, long_meta = infer_long_crisis_state(long_crisis_features, long_crisis_thresholds)
    reasons.extend(long_reasons)

    cash_flag = str(snapshot.get("cash_policy_flag") or "")
    if cash_flag:
        reasons.append(f"cash policy review active: {cash_flag}")

    hard_issues = 0
    for payload in (risk, safety):
        for row in payload.get("issues") or []:
            severity = str(row.get("severity") or row.get("level") or "").lower()
            if severity in {"hard", "critical", "blocker", "error"}:
                hard_issues += 1
    if hard_issues:
        reasons.append(f"hard safety/risk issue count={hard_issues}")

    latest_macro = macro.get("latest") if isinstance(macro.get("latest"), dict) else {}
    cash_gate = str(latest_macro.get("cash_raise_gate") or "").lower()
    confirmations = safe_float(latest_macro.get("cash_raise_confirmation_count"), 0.0)
    market_state = str(latest_macro.get("market_state") or latest_macro.get("risk_state") or "").lower()

    if "credit" in cash_gate or "liquidity" in cash_gate:
        reasons.append(f"macro liquidity/credit confirmation: {cash_gate}")
        return "DEFENSE_REVIEW", reasons, long_meta
    if long_state == "DEFENSE_REVIEW":
        return "DEFENSE_REVIEW", reasons, long_meta
    if hard_issues:
        return "DEFENSE_REVIEW", reasons, long_meta
    if confirmations >= 2:
        reasons.append(f"macro confirmation count={confirmations:g}")
        return "WATCH", reasons, long_meta
    if market_state in {"bear", "deep_bear", "risk_off"}:
        reasons.append(f"macro market_state={market_state}")
        return "WATCH", reasons, long_meta
    if long_state == "WATCH":
        return "WATCH", reasons, long_meta
    if cash_flag:
        return "WATCH", reasons, long_meta
    return "GREEN", reasons or ["no confirmed crisis signal"], long_meta


def apply_hysteresis(raw_state: str, history: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    prev = str(history.get("state") or "GREEN")
    streak_state = str(history.get("raw_state") or "")
    streak = int(safe_float(history.get("raw_state_streak"), 0))
    streak = streak + 1 if raw_state == streak_state else 1

    state = prev
    if prev == "GREEN":
        state = "WATCH" if raw_state in {"WATCH", "DEFENSE_REVIEW"} and streak >= 2 else "GREEN"
    elif prev == "WATCH":
        if raw_state == "DEFENSE_REVIEW" and streak >= 2:
            state = "DEFENSE_REVIEW"
        elif raw_state == "GREEN" and streak >= 3:
            state = "GREEN"
        else:
            state = "WATCH"
    elif prev == "DEFENSE_REVIEW":
        if raw_state == "GREEN" and streak >= 3:
            state = "REENTRY_READY"
        else:
            state = "DEFENSE_REVIEW"
    elif prev == "REENTRY_READY":
        state = "GREEN" if raw_state == "GREEN" and streak >= 2 else "WATCH"

    next_history = {
        "state": state,
        "raw_state": raw_state,
        "raw_state_streak": streak,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return state, next_history


def build_monitor(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history_path = repo_path(args.history)
    history = read_json(history_path)
    raw_state, reasons, long_crisis = infer_raw_state(
        latest_run,
        repo_path(args.long_crisis_features),
        repo_path(args.long_crisis_thresholds),
    )
    state, next_history = apply_hysteresis(raw_state, history)

    holdings = read_csv(latest_run / "operating_snapshot" / "current_operating_holdings_latest.csv")
    leader_rows = 0
    if not holdings.empty:
        text = holdings.astype(str).agg(" ".join, axis=1).str.lower()
        leader_rows = int(text.str.contains("leader|monster|future_winner", regex=True).sum())

    payload = {
        "schema_version": "daily-crisis-monitor-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "auto_trade_allowed": False,
        "state": state,
        "raw_state": raw_state,
        "long_crisis": long_crisis,
        "hysteresis": next_history,
        "reasons": reasons,
        "shakeout_guard": {
            "vix_only_cash_raise_forbidden": True,
            "single_name_shakeout_cash_raise_forbidden": True,
            "requires_liquidity_trend_credit_confirmation": True,
            "leader_like_current_rows": leader_rows,
        },
        "actions": {
            "GREEN": "hold normal operating posture",
            "WATCH": "monitor; do not raise cash without confirmation",
            "DEFENSE_REVIEW": "review defense; no automatic sell",
            "REENTRY_READY": "review redeployment candidates; no automatic buy",
        },
    }
    (output_dir / "crisis_action_status.md").write_text(render_report(payload), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.update_history:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(json.dumps(next_history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def render_report(payload: dict[str, Any]) -> str:
    long_crisis = payload.get("long_crisis") if isinstance(payload.get("long_crisis"), dict) else {}
    lines = [
        "# Daily Crisis Monitor",
        "",
        f"- state: `{payload.get('state')}`",
        f"- raw_state: `{payload.get('raw_state')}`",
        "- auto_trade_allowed: `false`",
        "",
        "## Reasons",
        "",
    ]
    lines.extend([f"- {item}" for item in payload.get("reasons") or []])
    if long_crisis.get("available"):
        lines.extend(
            [
                "",
                "## Long Crisis Learning",
                "",
                f"- latest_date: `{long_crisis.get('latest_date')}`",
                f"- crisis_score: `{long_crisis.get('crisis_score')}`",
                f"- cash_gate_reason: `{long_crisis.get('cash_gate_reason')}`",
                "- future drawdown labels are excluded from daily monitor decisions.",
            ]
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- VIX-only cash raise is forbidden.",
            "- Single-name shakeout cash raise is forbidden.",
            "- Liquidity/trend/credit confirmation is required for defense review.",
            "- Reentry is review-only; this tool never buys automatically.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/daily_crisis_monitor")
    parser.add_argument("--history", default="outputs/daily_crisis_monitor/state_history.json")
    parser.add_argument("--long-crisis-features", default="data_pit/macro/long_crisis_daily_features.parquet")
    parser.add_argument("--long-crisis-thresholds", default="outputs/long_crisis_learning/best_thresholds.json")
    parser.add_argument("--update-history", action="store_true")
    return parser.parse_args()


def main() -> int:
    payload = build_monitor(parse_args())
    print(json.dumps({"state": payload["state"], "raw_state": payload["raw_state"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
