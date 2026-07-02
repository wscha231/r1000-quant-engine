#!/usr/bin/env python3
"""Broker A/B harness for conservative re-entry timing candidates.

This tool is research-only. It generates target books that add small cash-funded
re-entry positions after PIT price-reclaim triggers, then replays them through
the broker ledger. It does not mutate production targets or dispatch fullruns.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS, replay as broker_replay  # noqa: E402
from tools.run_reentry_timing_whipsaw_screen import (  # noqa: E402
    default_price_cache,
    default_trades_path,
    price_frame,
    read_trades,
    screen as reentry_screen,
)

SCHEMA_VERSION = "reentry-timing-broker-ab-v1"
DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/reentry_timing_broker_ab"
CASH_TICKERS = {"CASH", "__CASH__"}


@dataclass(frozen=True)
class Arm:
    name: str
    trigger: str
    reentry_weight: float
    require_above_ma200: bool = True
    require_market_above_ma200: bool = False
    market_ticker: str = "SPY"
    max_additions_per_date: int = 1
    max_active_reentries: int = 2
    min_cash_after: float = 0.03


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def default_target_book(latest_run: Path, portfolio: str) -> Path:
    candidates = [
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "alphaops_vnext" / f"{portfolio}_target_book.csv",
        latest_run / "user_current" / "02_target_weights.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def read_target_book(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    d = pd.read_csv(path, low_memory=False)
    if d.empty or "rebalance_date" not in d.columns or "ticker" not in d.columns or "weight" not in d.columns:
        return pd.DataFrame()
    d = d[["rebalance_date", "ticker", "weight"]].copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    d = d[d["rebalance_date"].notna()]
    d = d[d["ticker"].ne("")]
    return d.groupby(["rebalance_date", "ticker"], as_index=False)["weight"].sum()


def target_weights_by_date(target: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    out: dict[pd.Timestamp, dict[str, float]] = {}
    for raw_dt, group in target.groupby("rebalance_date"):
        dt = pd.Timestamp(raw_dt).normalize()
        weights: dict[str, float] = {}
        for _, row in group.iterrows():
            ticker = clean_ticker(row.get("ticker"))
            weight = safe_float(row.get("weight"), 0.0)
            if ticker and weight > 1e-12:
                weights[ticker] = weights.get(ticker, 0.0) + weight
        stock_sum = sum(weight for ticker, weight in weights.items() if ticker not in CASH_TICKERS)
        cash = sum(weight for ticker, weight in weights.items() if ticker in CASH_TICKERS)
        weights = {ticker: weight for ticker, weight in weights.items() if ticker not in CASH_TICKERS}
        weights["CASH"] = max(cash, 1.0 - stock_sum)
        out[dt] = weights
    return out


def market_above_ma200_by_date(price_cache: Path, ticker: str) -> dict[pd.Timestamp, bool]:
    px = price_frame(price_cache, ticker)
    if px.empty or "date" not in px.columns or "close" not in px.columns or "ma200" not in px.columns:
        return {}
    d = px.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["ma200"] = pd.to_numeric(d["ma200"], errors="coerce")
    d = d[d["date"].notna() & d["close"].notna() & d["ma200"].notna()]
    return {pd.Timestamp(row["date"]).normalize(): bool(row["close"] > row["ma200"]) for _, row in d.iterrows()}


def active_cash(active: dict[str, float]) -> float:
    return max(0.0, safe_float(active.get("CASH"), 0.0))


def normalize_active(active: dict[str, float]) -> dict[str, float]:
    out = {ticker: max(0.0, float(weight)) for ticker, weight in active.items() if weight > 1e-12}
    stock_sum = sum(weight for ticker, weight in out.items() if ticker not in CASH_TICKERS)
    cash = safe_float(out.get("CASH"), max(0.0, 1.0 - stock_sum))
    out = {ticker: weight for ticker, weight in out.items() if ticker not in CASH_TICKERS}
    out["CASH"] = max(0.0, min(1.0, cash))
    return out


def emit_rows(active: dict[str, float], dt: pd.Timestamp, arm_name: str) -> list[dict[str, Any]]:
    return [
        {
            "rebalance_date": pd.Timestamp(dt).date().isoformat(),
            "ticker": ticker,
            "weight": float(weight),
            "research_reentry_arm": arm_name,
            "production_activation_allowed": False,
            "review_only": True,
        }
        for ticker, weight in sorted(normalize_active(active).items())
        if weight > 1e-12
    ]


def generate_reentry_target_book(
    base_target: pd.DataFrame,
    trigger_events: pd.DataFrame,
    arm: Arm,
    *,
    market_above_ma200: dict[pd.Timestamp, bool] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    base_by_date = target_weights_by_date(base_target)
    if not base_by_date:
        return pd.DataFrame(), pd.DataFrame(), {"status": "blocked", "reason": "empty_base_target"}
    events = trigger_events.copy()
    if events.empty:
        events = pd.DataFrame(columns=["trigger_date", "ticker", "trigger_hit", "trigger", "sell_date"])
    for col in ["trigger_date", "ticker", "trigger_hit", "trigger", "sell_date"]:
        if col not in events.columns:
            events[col] = pd.NA
    events["trigger_date"] = pd.to_datetime(events.get("trigger_date"), errors="coerce").dt.normalize()
    events["ticker"] = events.get("ticker", pd.Series(dtype=str)).map(clean_ticker)
    events = events[
        events["trigger_hit"].eq(True)
        & events["trigger"].eq(arm.trigger)
        & events["trigger_date"].notna()
        & events["ticker"].ne("")
    ].copy()
    if arm.require_above_ma200 and "trigger_above_ma200" in events.columns:
        events = events[events["trigger_above_ma200"].fillna(False).astype(str).str.lower().isin({"true", "1"})]
    events = events.sort_values(["trigger_date", "ticker", "sell_date"], kind="mergesort")
    events_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for _, row in events.iterrows():
        events_by_date.setdefault(pd.Timestamp(row["trigger_date"]).normalize(), []).append(row.to_dict())
    all_dates = sorted(set(base_by_date) | set(events_by_date))
    active: dict[str, float] = {}
    active_reentries: set[str] = set()
    rows: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    official_dates = set(base_by_date)
    for dt in all_dates:
        wrote = False
        if dt in official_dates:
            active = dict(base_by_date[dt])
            active_reentries = set()
        added_today = 0
        for event in events_by_date.get(dt, []):
            ticker = clean_ticker(event.get("ticker"))
            if not ticker or ticker in CASH_TICKERS:
                continue
            if arm.require_market_above_ma200 and not bool((market_above_ma200 or {}).get(dt, False)):
                skipped.append({**event, "skip_reason": "market_below_ma200"})
                continue
            if ticker in active and safe_float(active.get(ticker), 0.0) > 1e-12:
                skipped.append({**event, "skip_reason": "already_active"})
                continue
            if len(active_reentries) >= arm.max_active_reentries:
                skipped.append({**event, "skip_reason": "max_active_reentries"})
                continue
            if added_today >= arm.max_additions_per_date:
                skipped.append({**event, "skip_reason": "max_additions_per_date"})
                continue
            cash = active_cash(active)
            available = max(0.0, cash - arm.min_cash_after)
            weight = min(float(arm.reentry_weight), available)
            if weight <= 1e-12:
                skipped.append({**event, "skip_reason": "insufficient_cash"})
                continue
            active[ticker] = weight
            active["CASH"] = max(0.0, cash - weight)
            active_reentries.add(ticker)
            added_today += 1
            applied.append({**event, "applied_weight": weight, "cash_after": active["CASH"]})
            wrote = True
        if dt in official_dates or wrote:
            rows.extend(emit_rows(active, dt, arm.name))
    generated = pd.DataFrame(rows)
    applied_df = pd.DataFrame(applied)
    skipped_df = pd.DataFrame(skipped)
    summary = {
        "status": "completed",
        "arm": arm.name,
        "trigger": arm.trigger,
        "reentry_weight": arm.reentry_weight,
        "require_above_ma200": arm.require_above_ma200,
        "require_market_above_ma200": arm.require_market_above_ma200,
        "market_ticker": arm.market_ticker,
        "max_additions_per_date": arm.max_additions_per_date,
        "max_active_reentries": arm.max_active_reentries,
        "min_cash_after": arm.min_cash_after,
        "generated_rows": int(len(generated)),
        "applied_count": int(len(applied_df)),
        "skipped_count": int(len(skipped_df)),
    }
    return generated, applied_df, summary


def metric_row(arm: str, metrics: dict[str, Any], baseline: dict[str, Any] | None = None, *, applied_count: int = 0) -> dict[str, Any]:
    row = {
        "arm": arm,
        "status": metrics.get("status"),
        "metric_mode": metrics.get("metric_mode"),
        "cagr": safe_float(metrics.get("cagr"), math.nan),
        "max_dd": safe_float(metrics.get("max_dd"), math.nan),
        "sharpe": safe_float(metrics.get("sharpe"), math.nan),
        "years": safe_float(metrics.get("years"), math.nan),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight"), math.nan),
        "trade_count": int(safe_float(metrics.get("trade_count"), 0.0)),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd"), 0.0),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd"), 0.0),
        "applied_count": int(applied_count),
    }
    if baseline:
        row["delta_cagr_pp"] = (row["cagr"] - safe_float(baseline.get("cagr"), 0.0)) * 100.0
        row["delta_max_dd_pp"] = (row["max_dd"] - safe_float(baseline.get("max_dd"), 0.0)) * 100.0
        row["delta_sharpe"] = row["sharpe"] - safe_float(baseline.get("sharpe"), 0.0)
    else:
        row["delta_cagr_pp"] = 0.0
        row["delta_max_dd_pp"] = 0.0
        row["delta_sharpe"] = 0.0
    return row


def render_report(summary: dict[str, Any], arm_metrics: pd.DataFrame) -> str:
    lines = [
        "# Re-Entry Timing Broker A/B",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Verdict: `{summary.get('verdict')}`",
        "",
        "| Arm | Applied | CAGR | MaxDD | Delta CAGR pp | Delta MaxDD pp | Verdict |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for _, row in arm_metrics.iterrows():
        lines.append(
            f"| {row.get('arm')} | {int(safe_float(row.get('applied_count')))} | "
            f"{safe_float(row.get('cagr')):.2%} | {safe_float(row.get('max_dd')):.2%} | "
            f"{safe_float(row.get('delta_cagr_pp')):.2f} | {safe_float(row.get('delta_max_dd_pp')):.2f} | "
            f"`{row.get('verdict', '')}` |"
        )
    lines.extend(["", "Research-only. No production target or live trading mutation.", ""])
    return "\n".join(lines)


def parse_arms(raw: str) -> list[Arm]:
    arms: list[Arm] = []
    for part in str(raw).split(","):
        text = part.strip()
        if not text:
            continue
        fields = text.split(":")
        name = fields[0]
        trigger = fields[1] if len(fields) > 1 else "reclaim_5pct"
        weight = safe_float(fields[2], 0.05) if len(fields) > 2 else 0.05
        market_gate = len(fields) > 3 and fields[3].strip().lower() in {"spy_ma200", "market_ma200", "market"}
        market_ticker = clean_ticker(fields[4]) if len(fields) > 4 else "SPY"
        arms.append(
            Arm(
                name=name,
                trigger=trigger,
                reentry_weight=weight,
                require_market_above_ma200=market_gate,
                market_ticker=market_ticker or "SPY",
            )
        )
    return arms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--target-book", default=None)
    parser.add_argument("--trades", default=None)
    parser.add_argument("--price-cache", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--arms", default="reclaim5_w03:reclaim_5pct:0.03,reclaim5_w05:reclaim_5pct:0.05")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    target_book = repo_path(args.target_book) if args.target_book else default_target_book(latest_run, "concentrated")
    trades_path = repo_path(args.trades) if args.trades else default_trades_path(latest_run, "concentrated")
    price_cache = repo_path(args.price_cache) if args.price_cache else default_price_cache(latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_target = read_target_book(target_book)
    trades = read_trades(trades_path)
    if base_target.empty or trades.empty or not price_cache.exists():
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "missing_target_trades_or_price_cache",
            "target_book": str(target_book),
            "trades": str(trades_path),
            "price_cache": str(price_cache),
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "summary.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    events, _, screen_payload = reentry_screen(
        trades=trades,
        price_cache=price_cache,
        cooldown_trading_days=3,
        max_horizon_trading_days=63,
        triggers=sorted({arm.trigger for arm in parse_arms(args.arms)}),
    )
    write_csv(output_dir / "screen_events.csv", events)
    baseline_dir = output_dir / "baseline" / "broker"
    baseline_metrics = broker_replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=baseline_dir,
        portfolio_kind="concentrated",
        fill_mode="next_close",
        cost_bps=float(args.cost_bps),
        integer_shares=True,
        max_fill_lag_days=int(args.max_fill_lag_days),
        disable_concentrated_champion_filter=True,
        concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy(),
    )
    rows = [metric_row("baseline", baseline_metrics, None, applied_count=0)]
    arm_summaries: list[dict[str, Any]] = []
    for arm in parse_arms(args.arms):
        arm_dir = output_dir / arm.name
        market_state = market_above_ma200_by_date(price_cache, arm.market_ticker) if arm.require_market_above_ma200 else None
        generated, applied, arm_summary = generate_reentry_target_book(
            base_target,
            events,
            arm,
            market_above_ma200=market_state,
        )
        target_out = arm_dir / "target_book.csv"
        applied_out = arm_dir / "applied_reentries.csv"
        write_csv(target_out, generated)
        write_csv(applied_out, applied)
        metrics = broker_replay(
            target_book=target_out,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            portfolio_kind="concentrated",
            fill_mode="next_close",
            cost_bps=float(args.cost_bps),
            integer_shares=True,
            max_fill_lag_days=int(args.max_fill_lag_days),
            disable_concentrated_champion_filter=True,
            concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy(),
        )
        row = metric_row(arm.name, metrics, baseline_metrics, applied_count=int(arm_summary.get("applied_count") or 0))
        row["verdict"] = (
            "research_pass_candidate"
            if row["applied_count"] > 0 and row["delta_cagr_pp"] >= 0.50 and row["delta_max_dd_pp"] >= -1e-9
            else ("reject_mdd_worse" if row["delta_max_dd_pp"] < -1e-9 else "reject_no_cagr_edge")
        )
        rows.append(row)
        arm_summary.update({"metrics": metrics, "metric_row": row, "target_book": str(target_out)})
        arm_summaries.append(arm_summary)
    arm_metrics = pd.DataFrame(rows)
    passed = arm_metrics[arm_metrics.get("verdict", pd.Series(dtype=str)).eq("research_pass_candidate")]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "screen_summary": screen_payload,
        "target_book": str(target_book),
        "trades": str(trades_path),
        "price_cache": str(price_cache),
        "arm_summaries": arm_summaries,
        "screen_pass": bool(not passed.empty),
        "verdict": "research_pass_candidate" if not passed.empty else "reject_or_inconclusive",
        "next_action": "default_off_hook_review" if not passed.empty else "discard_or_tighten_without_fullrun",
    }
    write_csv(output_dir / "arm_metrics.csv", arm_metrics)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, arm_metrics), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
