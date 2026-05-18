#!/usr/bin/env python3
"""Broker-ledger replay with daily benchmark crash circuit overlays.

Monthly macro filters reduce exposure only on scheduled rebalance dates, which
misses fast crashes such as February-March 2020. This challenger injects
additional target-book rows on benchmark circuit dates using only SPY/QQQ prices
available at the signal close, then evaluates the modified book through the
standard broker ledger.

This is research-only. It does not alter production defaults.
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

from tools.run_broker_ledger_replay import (  # noqa: E402
    normalize_targets,
    replay as broker_replay,
    repo_path,
    resolve_concentrated_champion_filters,
    safe_float,
)
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


DEFAULT_OUT_DIR = "outputs/broker_market_circuit_replay"
BENCHMARK_CANDIDATES = ("QQQ", "SPY", "^IXIC", "^GSPC")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_benchmark(price_cache: Path, tickers: tuple[str, ...] = BENCHMARK_CANDIDATES) -> tuple[pd.DataFrame, str]:
    for ticker in tickers:
        px = load_price_series(price_cache, ticker)
        if not px.empty:
            return px, ticker
    return pd.DataFrame(), ""


def compute_circuit_states(
    benchmark: pd.DataFrame,
    *,
    caution_multiplier: float,
    crisis_multiplier: float,
    trigger_mode: str = "return_ma",
) -> pd.DataFrame:
    if benchmark.empty or "close" not in benchmark.columns:
        return pd.DataFrame()
    idx = pd.DatetimeIndex(benchmark.index).tz_localize(None).normalize()
    close = pd.to_numeric(benchmark["close"], errors="coerce")
    d = pd.DataFrame({"close": close.values}, index=idx).dropna().sort_index()
    if len(d) < 80:
        return pd.DataFrame()
    d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
    d["ma50"] = d["close"].rolling(50, min_periods=50).mean()
    d["ma100"] = d["close"].rolling(100, min_periods=80).mean()
    d["ma200"] = d["close"].rolling(200, min_periods=120).mean()
    d["ret5"] = d["close"].pct_change(5)
    d["ret10"] = d["close"].pct_change(10)
    d["ret20"] = d["close"].pct_change(20)
    d["ret60"] = d["close"].pct_change(60)

    state = "normal"
    rows: list[dict[str, Any]] = []
    for dt, row in d.iterrows():
        close_now = safe_float(row.get("close"), math.nan)
        if not math.isfinite(close_now):
            continue
        ma20 = safe_float(row.get("ma20"), math.nan)
        ma50 = safe_float(row.get("ma50"), math.nan)
        ma100 = safe_float(row.get("ma100"), math.nan)
        ma200 = safe_float(row.get("ma200"), math.nan)
        ret10 = safe_float(row.get("ret10"), 0.0)
        ret20 = safe_float(row.get("ret20"), 0.0)
        ret60 = safe_float(row.get("ret60"), 0.0)

        mode = str(trigger_mode or "return_ma").lower()
        if mode == "ma50":
            severe_trigger = math.isfinite(ma100) and close_now < ma100 and ret20 < 0.0
            caution_trigger = math.isfinite(ma50) and close_now < ma50
        elif mode == "ma20_50":
            severe_trigger = math.isfinite(ma50) and close_now < ma50 and ret20 <= -0.03
            caution_trigger = math.isfinite(ma20) and close_now < ma20
        elif mode == "ma50_200":
            severe_trigger = math.isfinite(ma200) and close_now < ma200
            caution_trigger = math.isfinite(ma50) and close_now < ma50
        elif mode == "trend60":
            severe_trigger = math.isfinite(ma100) and close_now < ma100 and ret60 < 0.0
            caution_trigger = ret20 <= -0.04
        else:
            severe_trigger = ret20 <= -0.16 or (math.isfinite(ma200) and close_now < ma200 and ret20 <= -0.08)
            caution_trigger = ret10 <= -0.08 or (math.isfinite(ma50) and close_now < ma50 and ret20 <= -0.06)
        reentry_fast = math.isfinite(ma20) and close_now > ma20 and ret10 >= 0.03
        reentry_full = math.isfinite(ma50) and close_now > ma50 and ret20 >= 0.06

        if state == "normal":
            if severe_trigger:
                state = "crisis"
            elif caution_trigger:
                state = "caution"
        elif state == "caution":
            if severe_trigger:
                state = "crisis"
            elif reentry_fast:
                state = "normal"
        elif state == "crisis":
            if reentry_full:
                state = "normal"
            elif reentry_fast:
                state = "caution"

        multiplier = 1.0
        if state == "caution":
            multiplier = float(caution_multiplier)
        elif state == "crisis":
            multiplier = float(crisis_multiplier)
        rows.append(
            {
                "date": pd.Timestamp(dt).date().isoformat(),
                "state": state,
                "multiplier": multiplier,
                "close": close_now,
                "ret10": ret10,
                "ret20": ret20,
                "ret60": ret60,
                "below_ma50": bool(math.isfinite(ma50) and close_now < ma50),
                "below_ma200": bool(math.isfinite(ma200) and close_now < ma200),
                "trigger_mode": mode,
                "severe_trigger": bool(severe_trigger),
                "caution_trigger": bool(caution_trigger),
                "reentry_fast": bool(reentry_fast),
                "reentry_full": bool(reentry_full),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    return out


def normalize_source_book(
    path: Path,
    portfolio_kind: str,
    champion_filters: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    raw = pd.read_csv(path, low_memory=False)
    return normalize_targets(raw, portfolio_kind=portfolio_kind, champion_filters=champion_filters)


def latest_base_weights(base: pd.DataFrame, signal_date: pd.Timestamp) -> tuple[pd.Timestamp | None, pd.DataFrame]:
    if base.empty:
        return None, pd.DataFrame()
    dates = sorted(pd.to_datetime(base["rebalance_date"], errors="coerce").dropna().dt.normalize().unique())
    eligible = [pd.Timestamp(dt).normalize() for dt in dates if pd.Timestamp(dt).normalize() <= signal_date]
    if not eligible:
        return None, pd.DataFrame()
    chosen = max(eligible)
    return chosen, base[pd.to_datetime(base["rebalance_date"], errors="coerce").dt.normalize().eq(chosen)].copy()


def build_circuit_target_book(
    base: pd.DataFrame,
    states: pd.DataFrame,
    *,
    output_dir: Path,
) -> tuple[Path, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if base.empty or states.empty:
        path = output_dir / "market_circuit_target_book.csv"
        pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(path, index=False)
        return path, pd.DataFrame()

    base_dates = set(pd.to_datetime(base["rebalance_date"], errors="coerce").dropna().dt.normalize())
    states = states.sort_values("date").copy()
    states["prev_multiplier"] = states["multiplier"].shift(1)
    change_dates = set(states.loc[states["multiplier"].ne(states["prev_multiplier"]), "date"].dropna())
    event_dates = sorted(base_dates | change_dates)

    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    state_by_date = states.set_index("date")
    for raw_dt in event_dates:
        signal_date = pd.Timestamp(raw_dt).normalize()
        state_rows = state_by_date.loc[:signal_date]
        if state_rows.empty:
            multiplier = 1.0
            state = "normal"
        else:
            last = state_rows.iloc[-1]
            multiplier = safe_float(last.get("multiplier"), 1.0)
            state = str(last.get("state") or "normal")
        source_dt, target = latest_base_weights(base, signal_date)
        if source_dt is None or target.empty:
            continue
        for _, row in target.iterrows():
            weight = max(0.0, safe_float(row.get("weight"), 0.0) * multiplier)
            if weight <= 1e-12:
                continue
            rec = row.to_dict()
            rec["rebalance_date"] = signal_date.date().isoformat()
            rec["weight"] = weight
            rec["market_circuit_state"] = state
            rec["market_circuit_multiplier"] = multiplier
            rec["market_circuit_source_rebalance_date"] = pd.Timestamp(source_dt).date().isoformat()
            rec["market_circuit_target_book"] = True
            rows.append(rec)
        events.append(
            {
                "rebalance_date": signal_date.date().isoformat(),
                "source_rebalance_date": pd.Timestamp(source_dt).date().isoformat(),
                "state": state,
                "multiplier": multiplier,
                "stock_weight_sum": sum(safe_float(r.get("weight"), 0.0) for r in rows if r.get("rebalance_date") == signal_date.date().isoformat()),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    target_path = output_dir / "market_circuit_target_book.csv"
    events_df = pd.DataFrame(events)
    out.to_csv(target_path, index=False)
    events_df.to_csv(output_dir / "market_circuit_events.csv", index=False)
    return target_path, events_df


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_source = pd.read_csv(target_book, low_memory=False) if target_book.exists() else pd.DataFrame()
    champion_filters, champion_filter_source, champion_filter_warning = resolve_concentrated_champion_filters(
        target_book=target_book,
        raw_targets=raw_source,
        portfolio_kind=args.portfolio_kind,
    )
    base = normalize_targets(raw_source, portfolio_kind=args.portfolio_kind, champion_filters=champion_filters)
    benchmark, benchmark_ticker = load_benchmark(price_cache)
    if base.empty or benchmark.empty:
        payload = {
            "status": "blocked",
            "reason": "missing target book or benchmark price cache",
            "target_book": str(target_book),
            "price_cache": str(price_cache),
            "benchmark_ticker": benchmark_ticker,
            "valid_for_production": False,
            "research_only": True,
            "production_activation_allowed": False,
        }
        write_json(output_dir / "metrics.json", payload)
        return payload
    states = compute_circuit_states(
        benchmark,
        caution_multiplier=float(args.caution_multiplier),
        crisis_multiplier=float(args.crisis_multiplier),
        trigger_mode=str(getattr(args, "trigger_mode", "return_ma") or "return_ma"),
    )
    states.to_csv(output_dir / "market_circuit_states.csv", index=False)
    circuit_target, events = build_circuit_target_book(base, states, output_dir=output_dir)
    try:
        metrics = broker_replay(
            target_book=circuit_target,
            price_cache=price_cache,
            output_dir=output_dir,
            portfolio_kind=args.portfolio_kind,
            starting_capital=float(args.starting_capital),
            fill_mode=args.fill_mode,
            cost_bps=float(args.cost_bps),
            integer_shares=not bool(args.no_integer_shares),
            max_fill_lag_days=int(args.max_fill_lag_days),
            concentrated_champion_filters=champion_filters,
        )
    except Exception as exc:
        metrics = {
            "status": "blocked",
            "reason": f"broker replay failed: {type(exc).__name__}: {exc}",
            "valid_for_production": False,
        }
    metrics.update(
        {
            "candidate_id": f"{args.portfolio_kind}_broker_market_circuit_replay",
            "metric_mode": "broker_market_circuit_next_close",
            "data_mode": "daily_benchmark_circuit_target_book",
            "research_only": True,
            "production_activation_allowed": False,
            "valid_for_production": bool(metrics.get("valid_for_production")),
            "source_target_book": str(target_book),
            "source_target_book_filter": champion_filters,
            "source_target_book_filter_source": champion_filter_source,
            "source_target_book_filter_warning": champion_filter_warning,
            "market_circuit_target_book": str(circuit_target),
            "benchmark_ticker": benchmark_ticker,
            "trigger_mode": str(getattr(args, "trigger_mode", "return_ma") or "return_ma"),
            "caution_multiplier": float(args.caution_multiplier),
            "crisis_multiplier": float(args.crisis_multiplier),
            "circuit_event_count": int(len(events)),
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_json(output_dir / "metrics.json", metrics)
    (output_dir / "replay_report.md").write_text(render_report(metrics), encoding="utf-8")
    return metrics


def render_report(metrics: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Broker Market Circuit Replay",
            "",
            "Research-only broker-ledger challenger. Daily benchmark crash states scale the target book before next-close replay.",
            "",
            f"- Portfolio: `{metrics.get('portfolio_kind')}`",
            f"- Status: `{metrics.get('status')}`",
            f"- CAGR: {safe_float(metrics.get('cagr')):.2%}",
            f"- Sharpe: {safe_float(metrics.get('sharpe')):.3f}",
            f"- MaxDD: {safe_float(metrics.get('max_dd')):.2%}",
            f"- Avg cash: {safe_float(metrics.get('avg_cash_weight')):.2%}",
            f"- Trade count: {int(safe_float(metrics.get('trade_count')))}",
            "",
            "Promotion requires target gates, stress review, and human approval.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--portfolio-kind", default="main")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--no-integer-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--caution-multiplier", type=float, default=0.60)
    parser.add_argument("--crisis-multiplier", type=float, default=0.25)
    parser.add_argument(
        "--trigger-mode",
        choices=["return_ma", "ma50", "ma20_50", "ma50_200", "trend60"],
        default="return_ma",
    )
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload.get("status"), "cagr": payload.get("cagr"), "max_dd": payload.get("max_dd")}, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
