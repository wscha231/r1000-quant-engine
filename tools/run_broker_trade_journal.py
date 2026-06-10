#!/usr/bin/env python3
"""Build an enriched trade journal from broker-ledger replay outputs.

The broker replay emits execution rows. This tool converts those executions into
round-trip trade records that AutoLearning can consume without relying on legacy
target-weight backtest metrics.

It is intentionally post-hoc and non-trading: it reads existing broker replay
artifacts, joins only point-in-time entry evidence from the monthly books or
candidate replay book, and writes journal CSV/JSON/Markdown outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/broker_trade_journal"
PORTFOLIOS = ("main", "concentrated")
LABEL_EXCLUDE_PATTERNS = (
    "forward",
    "weighted_forward_return",
    "raw_period_forward_return",
    "risk_adjusted_forward_return",
    "period_forward_return",
    "y_blend",
)
LABEL_EXCLUDE_EXACT = {"r_1m", "r_3m", "r_6m", "r_12m"}
SIGNAL_BREAKDOWN_COLUMNS = [
    "rs_acceleration_score",
    "h1_oversold_value_score",
    "h6_dynamic_leader_score",
    "stage2_overext_penalty",
    "theme_phase_multiplier_primary",
    "theme_phase_multiplier_max",
    "explosion_entry_score",
    "explosion_exit_score",
    "explosion_net_score",
]


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
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


def is_label_column(column: str) -> bool:
    col = str(column)
    lower = col.lower()
    if lower in LABEL_EXCLUDE_EXACT:
        return True
    return any(pattern in lower for pattern in LABEL_EXCLUDE_PATTERNS)


def prepare_entry_evidence(latest_run: Path, portfolio_kind: str) -> pd.DataFrame:
    if portfolio_kind == "concentrated":
        target = read_csv(latest_run / "reports" / "concentrated_strategy_holdings.csv")
    else:
        target = read_csv(latest_run / "reports" / "main_monthly_weights.csv")
    candidate = read_csv(latest_run / "reports" / "candidate_replay_book.csv")
    frames: list[pd.DataFrame] = []
    for frame in [candidate, target]:
        if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
            continue
        d = frame.copy()
        d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
        d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
        d = d.dropna(subset=["rebalance_date"])
        d = d[(d["ticker"] != "") & (d["ticker"] != "CASH")]
        keep = [col for col in d.columns if col in {"rebalance_date", "ticker"} or not is_label_column(col)]
        d = d[keep].copy()
        frames.append(d)
    if not frames:
        return pd.DataFrame(columns=["rebalance_date", "ticker"])
    merged = frames[0]
    for frame in frames[1:]:
        overlap = [col for col in frame.columns if col in merged.columns and col not in {"rebalance_date", "ticker"}]
        frame = frame.drop(columns=overlap, errors="ignore")
        merged = merged.merge(frame, on=["rebalance_date", "ticker"], how="outer")
    merged = merged.sort_values(["rebalance_date", "ticker"]).drop_duplicates(["rebalance_date", "ticker"], keep="last")
    return merged


def evidence_lookup(evidence: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    if evidence.empty:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in evidence.to_dict("records"):
        dt = pd.Timestamp(row.get("rebalance_date")).date().isoformat()
        ticker = str(row.get("ticker", "")).upper()
        out[(dt, ticker)] = row
    return out


def signal_breakdown(evidence: dict[str, Any]) -> str:
    payload = {
        key: safe_float(evidence.get(key), 0.0)
        for key in SIGNAL_BREAKDOWN_COLUMNS
        if key in evidence
    }
    return json.dumps(payload, sort_keys=True)


def add_entry_fields(row: dict[str, Any], entry_evidence: dict[str, Any]) -> dict[str, Any]:
    field_map = {
        "Name": "entry_name",
        "sector": "entry_sector",
        "industry_group": "entry_industry_group",
        "source_universe": "entry_source_universe",
        "score": "entry_score",
        "raw_score": "entry_raw_score",
        "portfolio_sleeve_label": "entry_sleeve",
        "portfolio_sleeve_role": "entry_sleeve_role",
        "portfolio_selection_path": "entry_selection_path",
        "portfolio_candidate_gate_label": "entry_candidate_gate_label",
        "portfolio_candidate_minimum_pass": "entry_candidate_minimum_pass",
        "portfolio_defensive_rotation_action": "entry_defensive_rotation_action",
        "portfolio_monster_early_score": "entry_monster_early_score",
        "portfolio_stale_mega_leader_score": "entry_stale_mega_leader_score",
        "portfolio_stale_leader_reason": "entry_stale_leader_reason",
        "portfolio_risk_entry_block_score": "entry_risk_entry_block_score",
        "theme_phase_primary": "entry_theme_phase",
        "theme_horizon_primary": "entry_theme_horizon",
        "theme_holding_profile_primary": "entry_theme_holding_profile",
        "theme_short_cycle_flag_primary": "entry_theme_short_cycle_flag",
        "theme_structural_growth_primary": "entry_theme_structural_growth",
        "market_style_regime_label": "entry_style_regime",
        "regime_state": "entry_regime_state",
        "regime_state_score": "entry_regime_state_score",
        "rs_acceleration_score": "entry_rs_acceleration_score",
        "h6_dynamic_leader_score": "entry_h6_dynamic_leader_score",
        "explosion_entry_score": "entry_explosion_entry_score",
        "explosion_exit_score": "entry_explosion_exit_score",
        "explosion_net_score": "entry_explosion_net_score",
        "entry_quality_score": "entry_quality_score",
        "concentrated_score": "entry_concentrated_score",
        "selection_confirmation_score": "entry_selection_confirmation_score",
        "ml_technical_agreement_score": "entry_ml_technical_agreement_score",
        "trend_template_full": "entry_trend_template_full",
        "breakout_setup_quality_score": "entry_breakout_setup_quality_score",
        "volatility_contraction_score": "entry_volatility_contraction_score",
        "oneil_leadership_score": "entry_oneil_leadership_score",
        "industry_group_strength_score": "entry_industry_group_strength_score",
        "future_winner_scout_score": "entry_future_winner_scout_score",
        "profitability_inflection_score": "entry_profitability_inflection_score",
        "market_cap_live": "entry_market_cap_live",
        "mktcap": "entry_mktcap",
        "dollar_vol_20d": "entry_dollar_vol_20d",
        "current_price_live": "entry_current_price_live",
        "px": "entry_px",
    }
    out = dict(row)
    for src, dst in field_map.items():
        if src in entry_evidence:
            value = entry_evidence.get(src)
            if isinstance(value, (np.integer, np.floating)):
                value = float(value)
            out[dst] = value
    out.setdefault("entry_regime_state", out.get("entry_style_regime") or "unknown")
    out.setdefault("entry_sleeve", "unknown")
    out["entry_signal_breakdown"] = signal_breakdown(entry_evidence)
    return out


def classify_trade(realized_return: float, holding_days: int) -> str:
    if realized_return >= 0.50:
        return "BIG_WIN"
    if realized_return >= 0.15:
        return "WIN"
    if realized_return <= -0.20:
        return "LOSS"
    if realized_return <= -0.08 and holding_days <= 45:
        return "TRAP"
    if realized_return > 0:
        return "SMALL_WIN"
    return "NEUTRAL_OR_SMALL_LOSS"


def build_round_trips(trades: pd.DataFrame, evidence: pd.DataFrame, portfolio_kind: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty:
        return pd.DataFrame(), pd.DataFrame()
    d = trades.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["signal_date"] = pd.to_datetime(d.get("signal_date"), errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d.dropna(subset=["date"])
    d = d.sort_values(["date", "ticker", "side"]).reset_index(drop=True)
    lookup = evidence_lookup(evidence)
    lots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    round_rows: list[dict[str, Any]] = []
    open_rows: list[dict[str, Any]] = []
    trade_id = 0
    for row in d.to_dict("records"):
        ticker = str(row.get("ticker", "")).upper()
        side = str(row.get("side", "")).upper()
        qty = safe_float(row.get("quantity"), 0.0)
        price = safe_float(row.get("fill_price"), 0.0)
        fee = safe_float(row.get("fee_usd"), 0.0)
        if not ticker or qty <= 0 or price <= 0:
            continue
        signal_date = pd.Timestamp(row.get("signal_date")).date().isoformat() if pd.notna(row.get("signal_date")) else ""
        if side == "BUY":
            entry_evidence = lookup.get((signal_date, ticker), {})
            lots[ticker].append(
                {
                    "ticker": ticker,
                    "entry_date": pd.Timestamp(row["date"]),
                    "entry_signal_date": signal_date,
                    "entry_price": price,
                    "quantity_remaining": qty,
                    "entry_fee_total": fee,
                    "entry_target_weight": safe_float(row.get("target_weight"), float("nan")),
                    "fill_mode": row.get("fill_mode"),
                    "entry_reason": row.get("reason"),
                    "evidence": entry_evidence,
                }
            )
            continue
        if side != "SELL":
            continue
        sell_qty_remaining = qty
        while sell_qty_remaining > 1e-9 and lots.get(ticker):
            lot = lots[ticker][0]
            lot_qty = safe_float(lot.get("quantity_remaining"), 0.0)
            matched_qty = min(sell_qty_remaining, lot_qty)
            if matched_qty <= 0:
                lots[ticker].pop(0)
                continue
            entry_fee_alloc = safe_float(lot.get("entry_fee_total"), 0.0) * matched_qty / max(lot_qty, 1e-12)
            exit_fee_alloc = fee * matched_qty / max(qty, 1e-12)
            entry_value = matched_qty * safe_float(lot.get("entry_price"), 0.0)
            exit_value = matched_qty * price
            pnl = exit_value - entry_value - entry_fee_alloc - exit_fee_alloc
            realized_return = pnl / max(entry_value + entry_fee_alloc, 1e-12)
            holding_days = int((pd.Timestamp(row["date"]) - pd.Timestamp(lot["entry_date"])).days)
            trade_id += 1
            base = {
                "trade_id": f"{portfolio_kind}_{trade_id:06d}",
                "portfolio_kind": portfolio_kind,
                "ticker": ticker,
                "entry_date": pd.Timestamp(lot["entry_date"]).date().isoformat(),
                "exit_date": pd.Timestamp(row["date"]).date().isoformat(),
                "entry_signal_date": lot.get("entry_signal_date", ""),
                "exit_signal_date": signal_date,
                "entry_reason": lot.get("entry_reason", ""),
                "exit_reason": row.get("reason", ""),
                "quantity": matched_qty,
                "entry_price": safe_float(lot.get("entry_price"), 0.0),
                "exit_price": price,
                "entry_value_usd": entry_value,
                "exit_value_usd": exit_value,
                "entry_fee_usd": entry_fee_alloc,
                "exit_fee_usd": exit_fee_alloc,
                "net_pnl_usd": pnl,
                "realized_return": realized_return,
                "holding_days": holding_days,
                "entry_target_weight": lot.get("entry_target_weight"),
                "exit_target_weight": safe_float(row.get("target_weight"), float("nan")),
                "fill_mode": lot.get("fill_mode") or row.get("fill_mode"),
                "grade_label": classify_trade(realized_return, holding_days),
            }
            round_rows.append(add_entry_fields(base, lot.get("evidence") or {}))
            lot["quantity_remaining"] = lot_qty - matched_qty
            sell_qty_remaining -= matched_qty
            if lot["quantity_remaining"] <= 1e-9:
                lots[ticker].pop(0)
    for ticker, ticker_lots in lots.items():
        for lot in ticker_lots:
            qty = safe_float(lot.get("quantity_remaining"), 0.0)
            if qty <= 1e-9:
                continue
            base = {
                "portfolio_kind": portfolio_kind,
                "ticker": ticker,
                "entry_date": pd.Timestamp(lot["entry_date"]).date().isoformat(),
                "entry_signal_date": lot.get("entry_signal_date", ""),
                "entry_reason": lot.get("entry_reason", ""),
                "quantity_open": qty,
                "entry_price": safe_float(lot.get("entry_price"), 0.0),
                "entry_value_usd": qty * safe_float(lot.get("entry_price"), 0.0),
                "entry_fee_unrealized_usd": safe_float(lot.get("entry_fee_total"), 0.0),
                "entry_target_weight": lot.get("entry_target_weight"),
                "fill_mode": lot.get("fill_mode"),
            }
            open_rows.append(add_entry_fields(base, lot.get("evidence") or {}))
    return pd.DataFrame(round_rows), pd.DataFrame(open_rows)


def summary_stats(round_trips: pd.DataFrame, metrics: dict[str, Any], portfolio_kind: str) -> dict[str, Any]:
    if round_trips.empty:
        return {
            "status": "blocked",
            "reason": "empty round trip journal",
            "portfolio_kind": portfolio_kind,
        }
    returns = pd.to_numeric(round_trips["realized_return"], errors="coerce").dropna()
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    by_grade = round_trips["grade_label"].astype(str).value_counts().to_dict() if "grade_label" in round_trips.columns else {}
    return {
        "status": "completed",
        "portfolio_kind": portfolio_kind,
        "journal_mode": "broker_ledger_round_trip",
        "valid_for_autolearning": True,
        "trade_count": int(len(round_trips)),
        "win_rate": float((returns > 0).mean()) if len(returns) else None,
        "avg_realized_return": float(returns.mean()) if len(returns) else None,
        "median_realized_return": float(returns.median()) if len(returns) else None,
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "profit_factor": float(wins.sum() / abs(losses.sum())) if abs(losses.sum()) > 1e-12 else None,
        "avg_holding_days": float(pd.to_numeric(round_trips["holding_days"], errors="coerce").mean()),
        "grade_counts": by_grade,
        "broker_cagr": metrics.get("cagr"),
        "broker_sharpe": metrics.get("sharpe"),
        "broker_max_dd": metrics.get("max_dd"),
        "broker_start_date": metrics.get("start_date"),
        "broker_end_date": metrics.get("end_date"),
        "broker_trade_count": metrics.get("trade_count"),
        "broker_total_fees_usd": metrics.get("total_fees_usd"),
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Broker Trade Journal",
        "",
        "Round-trip trade journal reconstructed from broker-ledger replay executions.",
        "",
    ]
    for key in ["main", "concentrated", "combined"]:
        item = payload.get(key) or {}
        if item.get("status") != "completed":
            lines.append(f"- `{key}`: blocked ({item.get('reason', 'unknown')})")
            continue
        lines.append(
            "- `{key}`: trades={trades}, win_rate={win:.2%}, avg_return={ret:.2%}, "
            "avg_holding_days={days:.1f}, broker_cagr={cagr:.2%}, broker_max_dd={dd:.2%}".format(
                key=key,
                trades=int(safe_float(item.get("trade_count"), 0.0)),
                win=safe_float(item.get("win_rate"), 0.0),
                ret=safe_float(item.get("avg_realized_return"), 0.0),
                days=safe_float(item.get("avg_holding_days"), 0.0),
                cagr=safe_float(item.get("broker_cagr"), 0.0),
                dd=safe_float(item.get("broker_max_dd"), 0.0),
            )
        )
    lines.extend(["", "This journal is evidence for AutoLearning. It does not place orders.", ""])
    return "\n".join(lines)


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    combined_round: list[pd.DataFrame] = []
    combined_open: list[pd.DataFrame] = []
    payload: dict[str, Any] = {
        "status": "completed",
        "latest_run": str(latest_run),
        "output_dir": str(output_dir),
    }
    for portfolio_kind in PORTFOLIOS:
        trades = read_csv(latest_run / "broker_replay" / portfolio_kind / "trades.csv")
        metrics = read_json(latest_run / "broker_replay" / portfolio_kind / "metrics.json")
        evidence = prepare_entry_evidence(latest_run, portfolio_kind)
        round_trips, open_positions = build_round_trips(trades, evidence, portfolio_kind)
        out = output_dir / portfolio_kind
        write_frame(out / "round_trips.csv", round_trips)
        write_frame(out / "open_positions.csv", open_positions)
        summary = summary_stats(round_trips, metrics, portfolio_kind)
        write_json(out / "summary.json", summary)
        payload[portfolio_kind] = summary
        if not round_trips.empty:
            combined_round.append(round_trips)
        if not open_positions.empty:
            combined_open.append(open_positions)
    combined_round_df = pd.concat(combined_round, ignore_index=True, sort=False) if combined_round else pd.DataFrame()
    combined_open_df = pd.concat(combined_open, ignore_index=True, sort=False) if combined_open else pd.DataFrame()
    write_frame(output_dir / "combined_round_trips.csv", combined_round_df)
    write_frame(output_dir / "combined_open_positions.csv", combined_open_df)
    payload["combined"] = summary_stats(combined_round_df, {}, "combined") if not combined_round_df.empty else {"status": "blocked", "reason": "empty combined journal"}
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "broker_trade_journal_report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
