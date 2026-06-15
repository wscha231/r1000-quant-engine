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

from tools.crisis_state_engine import (  # noqa: E402
    apply_hysteresis,
    infer_latest_long_crisis_state,
)

ALLOWED_PAPER_ACTION_TYPES = ("raise_cash", "trim_position", "block_new_buys", "reentry_watch", "no_op")


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except Exception:
        return default


def first_existing_column(frame: pd.DataFrame, names: list[str]) -> str | None:
    lower = {str(c).lower(): c for c in frame.columns}
    for name in names:
        if name.lower() in lower:
            return str(lower[name.lower()])
    return None


def top_trim_candidates(holdings: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    if holdings.empty:
        return []
    ticker_col = first_existing_column(holdings, ["ticker", "symbol"])
    weight_col = first_existing_column(holdings, ["weight", "current_weight", "actual_weight", "target_weight"])
    if not ticker_col or not weight_col:
        return []
    work = holdings[[ticker_col, weight_col]].copy()
    work["_weight"] = pd.to_numeric(work[weight_col], errors="coerce").fillna(0.0)
    work = work.sort_values("_weight", ascending=False).head(limit)
    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        rows.append({"ticker": str(row.get(ticker_col)), "current_weight": float(row.get("_weight", 0.0))})
    return rows


def build_paper_action_candidates(
    *,
    state: str,
    raw_state: str,
    reasons: list[str],
    holdings: pd.DataFrame,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    context = {"state": state, "raw_state": raw_state, "reasons": reasons[:5]}
    if state == "GREEN":
        actions.append({"action_type": "no_op", "priority": 0, "context": context})
    elif state == "WATCH":
        actions.append({"action_type": "block_new_buys", "priority": 1, "scope": "new_positions", "context": context})
    elif state in {"DEFENSE_REVIEW", "CRISIS_DEFENSE"}:
        target_cash = 0.30 if state == "DEFENSE_REVIEW" else 0.50
        actions.append({"action_type": "block_new_buys", "priority": 1, "scope": "new_positions", "context": context})
        actions.append({"action_type": "raise_cash", "priority": 2, "target_cash_weight": target_cash, "context": context})
        for item in top_trim_candidates(holdings):
            actions.append({"action_type": "trim_position", "priority": 3, **item, "context": context})
    elif state == "REENTRY_READY":
        actions.append({"action_type": "reentry_watch", "priority": 1, "scope": "approved_watchlist_only", "context": context})
    else:
        actions.append({"action_type": "no_op", "priority": 0, "context": context})
    return [item for item in actions if item.get("action_type") in ALLOWED_PAPER_ACTION_TYPES]


def infer_raw_state(latest_run: Path, long_crisis_features: Path, long_crisis_thresholds: Path) -> tuple[str, list[str], dict[str, Any]]:
    reasons: list[str] = []
    risk = read_json(latest_run / "live_trading_risk_controls" / "risk_controls_summary.json")
    safety = read_json(latest_run / "live_trading_safety" / "safety_audit_summary.json")
    macro = read_json(latest_run / "macro_policy_engine" / "summary.json")
    snapshot = read_json(latest_run / "operating_snapshot" / "current_portfolio_snapshot_summary.json")
    long_state, long_reasons, long_meta = infer_latest_long_crisis_state(long_crisis_features, long_crisis_thresholds)
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
    paper_actions = build_paper_action_candidates(state=state, raw_state=raw_state, reasons=reasons, holdings=holdings)

    payload = {
        "schema_version": "daily-crisis-monitor-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "auto_trade_allowed": False,
        "paper_actions_only": True,
        "allowed_action_types": list(ALLOWED_PAPER_ACTION_TYPES),
        "paper_action_candidates": paper_actions,
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
            "CRISIS_DEFENSE": "review defense; no automatic sell",
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
    lines.extend(
        [
            "",
            "## Paper Action Candidates",
            "",
            "- paper_actions_only: `true`",
            "- production_mutation_allowed: `false`",
            "",
            "| Action | Priority | Scope/Ticker | Detail |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for item in payload.get("paper_action_candidates") or []:
        scope = item.get("ticker") or item.get("scope") or ""
        detail = ""
        if item.get("action_type") == "raise_cash":
            detail = f"target_cash_weight={safe_float(item.get('target_cash_weight'), 0.0):.2f}"
        elif item.get("action_type") == "trim_position":
            detail = f"current_weight={safe_float(item.get('current_weight'), 0.0):.4f}"
        lines.append(f"| {item.get('action_type')} | {item.get('priority')} | {scope} | {detail} |")
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
