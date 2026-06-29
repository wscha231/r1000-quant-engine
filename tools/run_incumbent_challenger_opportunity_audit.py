#!/usr/bin/env python3
"""Audit incumbent-vs-challenger replacement opportunities with 2-week RS.

This research-only diagnostic reconstructs monthly concentrated-book reduction
events from an existing target book, compares the reduced incumbent against the
best contemporaneous capital-receiving challenger, and asks whether PIT-visible
short-term relative strength would have helped avoid selling a later winner.

Forward returns are audit labels only.  This tool does not mutate target books,
does not implement a policy hook, and does not dispatch any workflow.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, price_on_or_before  # noqa: E402
from tools.run_whipsaw_cost_audit import CASH_TICKERS, clean_ticker, read_csv, safe_float, write_json, write_text  # noqa: E402

DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/incumbent_challenger_opportunity_audit"
DEFAULT_OOS_START = "2024-06-03"
SCHEMA_VERSION = "incumbent-challenger-opportunity-audit-v1"
CORE_BENCHMARKS = ("SPY", "QQQ")
FEATURE_COLS = [
    "alphaops_vnext_score",
    "alphaops_vnext_weight_score",
    "relative_strength_composite",
    "rs_benchmark_1w",
    "rs_benchmark_1m",
    "rs_benchmark_3m",
    "rs_benchmark_6m",
    "rs_benchmark_12m",
    "actual_results_score",
    "eps_revision_score",
    "revision_score",
    "event_reaction_score",
    "sector_leadership_score",
    "smart_money_evidence_confidence",
    "price_above_ma200",
    "price_above_ma50",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def target_book_path(latest_run: Path, portfolio: str, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "alphaops_vnext" / f"official_{portfolio}_target_book.csv",
        latest_run / "reports" / f"operating_{portfolio}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def candidate_book_path(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "sec_enriched_candidate_replay" / "candidate_replay_book_sec_enriched.csv",
        latest_run / "candidate_replay_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def normalize_book(frame: pd.DataFrame, *, weight_col: str = "weight") -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    if weight_col not in d.columns:
        weight_col = "target_weight" if "target_weight" in d.columns else ""
    d["_weight"] = pd.to_numeric(d[weight_col], errors="coerce").fillna(0.0) if weight_col else 0.0
    d = d[d["rebalance_date"].notna()]
    d = d[(d["ticker"] != "") & (~d["ticker"].isin(CASH_TICKERS))]
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def latest_row_by_date_ticker(frame: pd.DataFrame, date: pd.Timestamp, ticker: str) -> dict[str, Any]:
    if frame.empty:
        return {}
    mask = frame["ticker"].eq(clean_ticker(ticker)) & frame["rebalance_date"].eq(pd.Timestamp(date).normalize())
    part = frame[mask]
    if part.empty:
        return {}
    return part.iloc[-1].to_dict()


def row_feature(row: dict[str, Any], col: str) -> float:
    return safe_float(row.get(col), 0.0)


def row_text(row: dict[str, Any], col: str) -> str:
    val = row.get(col, "")
    try:
        if pd.isna(val):
            return ""
    except TypeError:
        pass
    return str(val or "").strip()


def price_at_or_before(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp) -> tuple[pd.Timestamp | None, float | None]:
    return price_on_or_before(prices.get(clean_ticker(ticker), pd.DataFrame()), date, "close")


def return_over_trading_days(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp, days: int) -> tuple[float, bool]:
    px = prices.get(clean_ticker(ticker), pd.DataFrame())
    if px.empty:
        return 0.0, False
    end_dt, end_px = price_on_or_before(px, date, "close")
    if end_dt is None or end_px is None:
        return 0.0, False
    idx = pd.DatetimeIndex(px.index)
    end_pos = int(idx.searchsorted(pd.Timestamp(end_dt), side="right")) - 1
    start_pos = end_pos - int(days)
    if start_pos < 0:
        return 0.0, False
    start_px = safe_float(px["close"].iloc[start_pos], 0.0)
    if start_px <= 0:
        return 0.0, False
    return float(end_px / start_px - 1.0), True


def forward_return_over_trading_days(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp, days: int) -> tuple[float, bool]:
    px = prices.get(clean_ticker(ticker), pd.DataFrame())
    if px.empty:
        return 0.0, False
    start_dt, start_px = price_on_or_before(px, date, "close")
    if start_dt is None or start_px is None:
        return 0.0, False
    idx = pd.DatetimeIndex(px.index)
    start_pos = int(idx.searchsorted(pd.Timestamp(start_dt), side="right")) - 1
    end_pos = start_pos + int(days)
    if end_pos >= len(idx):
        return 0.0, False
    end_px = safe_float(px["close"].iloc[end_pos], 0.0)
    if end_px <= 0:
        return 0.0, False
    return float(end_px / start_px - 1.0), True


def core_rs(prices: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp, days: int) -> tuple[float, bool]:
    ticker_ret, ticker_ok = return_over_trading_days(prices, ticker, date, days)
    bench_returns: list[float] = []
    for bench in CORE_BENCHMARKS:
        ret, ok = return_over_trading_days(prices, bench, date, days)
        if ok:
            bench_returns.append(ret)
    if not ticker_ok or not bench_returns:
        return 0.0, False
    return float(ticker_ret - float(np.mean(bench_returns))), True


def load_prices(price_cache: Path, tickers: set[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for ticker in sorted(t for t in tickers if t and t not in CASH_TICKERS):
        out[ticker] = load_price_series(price_cache, ticker)
    for bench in CORE_BENCHMARKS:
        out[bench] = load_price_series(price_cache, bench)
    return out


def choose_challenger(cur: pd.DataFrame, prev_weights: dict[str, float], incumbent: str) -> dict[str, Any]:
    if cur.empty:
        return {}
    d = cur.copy()
    d["prev_weight"] = d["ticker"].map(prev_weights).fillna(0.0)
    d["weight_increase"] = d["_weight"] - d["prev_weight"]
    d = d[(d["ticker"] != clean_ticker(incumbent)) & d["weight_increase"].gt(1e-9)]
    if d.empty:
        return {}
    rank_cols = [col for col in ["weight_increase", "alphaops_vnext_score", "alphaops_vnext_weight_score", "_weight"] if col in d.columns]
    return d.sort_values(rank_cols, ascending=[False] * len(rank_cols)).iloc[0].to_dict()


def reconstruct_events(
    target: pd.DataFrame,
    candidate: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    *,
    min_reduction: float,
    short_rs_days: int,
    forward_days: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if target.empty:
        return pd.DataFrame(rows)
    dates = sorted(pd.Timestamp(x).normalize() for x in target["rebalance_date"].dropna().unique())
    for i in range(1, len(dates)):
        prev_dt, cur_dt = dates[i - 1], dates[i]
        prev = target[target["rebalance_date"].eq(prev_dt)].copy()
        cur = target[target["rebalance_date"].eq(cur_dt)].copy()
        if prev.empty or cur.empty:
            continue
        prev_weights = dict(zip(prev["ticker"], pd.to_numeric(prev["_weight"], errors="coerce").fillna(0.0)))
        cur_weights = dict(zip(cur["ticker"], pd.to_numeric(cur["_weight"], errors="coerce").fillna(0.0)))
        for incumbent, prev_weight in prev_weights.items():
            cur_weight = float(cur_weights.get(incumbent, 0.0))
            reduction = float(prev_weight - cur_weight)
            if reduction < float(min_reduction):
                continue
            challenger = choose_challenger(cur, prev_weights, incumbent)
            if not challenger:
                continue
            inc_row = latest_row_by_date_ticker(target, cur_dt, incumbent)
            inc_source = "current_target"
            if not inc_row:
                inc_row = latest_row_by_date_ticker(candidate, cur_dt, incumbent)
                inc_source = "current_candidate"
            if not inc_row:
                inc_row = prev[prev["ticker"].eq(incumbent)].iloc[-1].to_dict()
                inc_source = "previous_target_fallback"
            ch_row = dict(challenger)
            ch_ticker = clean_ticker(ch_row.get("ticker"))
            inc_rs2w, inc_rs2w_ok = core_rs(prices, incumbent, cur_dt, short_rs_days)
            ch_rs2w, ch_rs2w_ok = core_rs(prices, ch_ticker, cur_dt, short_rs_days)
            inc_fwd, inc_fwd_ok = forward_return_over_trading_days(prices, incumbent, cur_dt, forward_days)
            ch_fwd, ch_fwd_ok = forward_return_over_trading_days(prices, ch_ticker, cur_dt, forward_days)
            payload: dict[str, Any] = {
                "rebalance_date": cur_dt.date().isoformat(),
                "previous_rebalance_date": prev_dt.date().isoformat(),
                "incumbent_ticker": incumbent,
                "challenger_ticker": ch_ticker,
                "incumbent_previous_weight": float(prev_weight),
                "incumbent_current_weight": float(cur_weight),
                "incumbent_reduction": float(reduction),
                "challenger_previous_weight": float(prev_weights.get(ch_ticker, 0.0)),
                "challenger_current_weight": safe_float(ch_row.get("_weight")),
                "challenger_weight_increase": safe_float(ch_row.get("weight_increase")),
                "incumbent_feature_source": inc_source,
                "audit_forward_days": int(forward_days),
                "incumbent_forward_return": inc_fwd,
                "challenger_forward_return": ch_fwd,
                "forward_coverage": bool(inc_fwd_ok and ch_fwd_ok),
                "incumbent_forward_excess_vs_challenger": inc_fwd - ch_fwd if inc_fwd_ok and ch_fwd_ok else 0.0,
                "incumbent_outperformed_challenger": bool(inc_fwd_ok and ch_fwd_ok and inc_fwd > ch_fwd),
                "incumbent_rs_benchmark_2w": inc_rs2w,
                "challenger_rs_benchmark_2w": ch_rs2w,
                "rs2w_coverage": bool(inc_rs2w_ok and ch_rs2w_ok),
                "incumbent_rs2w_minus_challenger": inc_rs2w - ch_rs2w if inc_rs2w_ok and ch_rs2w_ok else 0.0,
            }
            for col in FEATURE_COLS:
                inc_val = row_feature(inc_row, col)
                ch_val = row_feature(ch_row, col)
                payload[f"incumbent_{col}"] = inc_val
                payload[f"challenger_{col}"] = ch_val
                payload[f"{col}_delta_incumbent_minus_challenger"] = inc_val - ch_val
            payload["incumbent_leader_tier"] = row_text(inc_row, "leader_tier")
            payload["challenger_leader_tier"] = row_text(ch_row, "leader_tier")
            payload["incumbent_holding_state"] = row_text(inc_row, "holding_state")
            payload["challenger_holding_state"] = row_text(ch_row, "holding_state")
            payload["incumbent_rs2w_stronger"] = bool(payload["rs2w_coverage"] and payload["incumbent_rs2w_minus_challenger"] > 0.0)
            payload["incumbent_rs2w_and_long_rs_intact"] = bool(
                payload["incumbent_rs2w_stronger"]
                and payload["incumbent_rs_benchmark_3m"] > 0.0
                and payload["incumbent_rs_benchmark_6m"] > 0.0
            )
            payload["incumbent_rs2w_score_not_worse"] = bool(
                payload["incumbent_rs2w_stronger"]
                and payload["alphaops_vnext_score_delta_incumbent_minus_challenger"] >= -0.25
            )
            payload["incumbent_rs2w_actual_positive"] = bool(
                payload["incumbent_rs2w_stronger"] and payload["incumbent_actual_results_score"] > 0.0
            )
            payload["challenger_rs2w_stronger"] = bool(payload["rs2w_coverage"] and payload["incumbent_rs2w_minus_challenger"] < 0.0)
            rows.append(payload)
    return pd.DataFrame(rows)


def summarize_predicate(frame: pd.DataFrame, label: str, mask: pd.Series, *, oos_start: pd.Timestamp) -> dict[str, Any]:
    part = frame[mask.fillna(False)].copy() if not frame.empty else pd.DataFrame()
    if part.empty:
        return {
            "predicate": label,
            "event_count": 0,
            "positive_rate": 0.0,
            "mean_forward_excess": None,
            "oos_event_count": 0,
            "oos_positive_rate": 0.0,
            "oos_mean_forward_excess": None,
        }
    dates = pd.to_datetime(part["rebalance_date"], errors="coerce")
    oos = part[dates.ge(oos_start)]
    excess = pd.to_numeric(part.get("incumbent_forward_excess_vs_challenger"), errors="coerce")
    positive = part.get("incumbent_outperformed_challenger", pd.Series(False, index=part.index)).astype(bool)
    oos_excess = pd.to_numeric(oos.get("incumbent_forward_excess_vs_challenger"), errors="coerce") if not oos.empty else pd.Series(dtype=float)
    oos_positive = oos.get("incumbent_outperformed_challenger", pd.Series(False, index=oos.index)).astype(bool) if not oos.empty else pd.Series(dtype=bool)
    return {
        "predicate": label,
        "event_count": int(len(part)),
        "positive_count": int(positive.sum()),
        "positive_rate": float(positive.mean()) if len(part) else 0.0,
        "mean_forward_excess": float(excess.mean()) if excess.notna().any() else None,
        "median_forward_excess": float(excess.median()) if excess.notna().any() else None,
        "oos_event_count": int(len(oos)),
        "oos_positive_count": int(oos_positive.sum()) if len(oos) else 0,
        "oos_positive_rate": float(oos_positive.mean()) if len(oos) else 0.0,
        "oos_mean_forward_excess": float(oos_excess.mean()) if oos_excess.notna().any() else None,
    }


def predicate_summary(events: pd.DataFrame, *, oos_start: pd.Timestamp) -> list[dict[str, Any]]:
    if events.empty:
        return []
    predicates = [
        ("all_reductions", pd.Series(True, index=events.index)),
        ("incumbent_rs2w_stronger", events["incumbent_rs2w_stronger"].astype(bool)),
        ("incumbent_rs2w_and_long_rs_intact", events["incumbent_rs2w_and_long_rs_intact"].astype(bool)),
        ("incumbent_rs2w_score_not_worse", events["incumbent_rs2w_score_not_worse"].astype(bool)),
        ("incumbent_rs2w_actual_positive", events["incumbent_rs2w_actual_positive"].astype(bool)),
        ("challenger_rs2w_stronger", events["challenger_rs2w_stronger"].astype(bool)),
    ]
    return [summarize_predicate(events, label, mask, oos_start=oos_start) for label, mask in predicates]


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Incumbent vs Challenger RS2W Opportunity Audit",
        "",
        "Research-only audit of reduced incumbents versus contemporaneous capital-receiving challengers.",
        "",
        f"- portfolio: `{payload.get('portfolio')}`",
        f"- event_count: `{payload.get('event_count')}`",
        f"- primary_predicate: `{payload.get('primary_predicate')}`",
        f"- verdict: `{payload.get('verdict')}`",
        f"- next_action: `{payload.get('next_action')}`",
        "",
        "## Predicate Summary",
        "",
        "| predicate | events | positive rate | mean 126d excess | OOS events | OOS positive | OOS mean excess |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("predicate_summary", []):
        mean = row.get("mean_forward_excess")
        oos_mean = row.get("oos_mean_forward_excess")
        lines.append(
            f"| `{row.get('predicate')}` | {row.get('event_count', 0)} | "
            f"{row.get('positive_rate', 0.0):.1%} | "
            f"{mean if mean is not None else 0.0:.2%} | "
            f"{row.get('oos_event_count', 0)} | "
            f"{row.get('oos_positive_rate', 0.0):.1%} | "
            f"{oos_mean if oos_mean is not None else 0.0:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This is not a score change or policy hook.",
            "- 2-week RS is computed from prices available on or before the decision date.",
            "- 63d/126d forward returns are audit labels only and must not enter live ranking.",
            "- Any policy use requires a later default-OFF hook and broker-ledger A/B.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    portfolio = str(args.portfolio).lower().strip()
    target_path = target_book_path(latest_run, portfolio, args.target_book or None)
    candidate_path = candidate_book_path(latest_run, args.candidate_book or None)
    price_cache = repo_path(args.price_cache)
    target = normalize_book(read_csv(target_path))
    candidate = normalize_book(read_csv(candidate_path)) if candidate_path.exists() else pd.DataFrame()
    tickers = set(target.get("ticker", pd.Series(dtype=str)).map(clean_ticker)) | set(candidate.get("ticker", pd.Series(dtype=str)).map(clean_ticker))
    prices = load_prices(price_cache, tickers)
    events = reconstruct_events(
        target,
        candidate,
        prices,
        min_reduction=float(args.min_reduction),
        short_rs_days=int(args.short_rs_days),
        forward_days=int(args.forward_days),
    )
    oos_start = pd.Timestamp(args.oos_start).normalize()
    summary_rows = predicate_summary(events, oos_start=oos_start)
    primary_label = "incumbent_rs2w_score_not_worse"
    primary = next((row for row in summary_rows if row.get("predicate") == primary_label), {})
    all_row = next((row for row in summary_rows if row.get("predicate") == "all_reductions"), {})
    primary_count = int(primary.get("event_count", 0) or 0)
    primary_oos_count = int(primary.get("oos_event_count", 0) or 0)
    primary_mean = safe_float(primary.get("mean_forward_excess"), 0.0)
    primary_oos_mean = safe_float(primary.get("oos_mean_forward_excess"), 0.0)
    all_mean = safe_float(all_row.get("mean_forward_excess"), 0.0)
    screen_pass = bool(
        primary_count >= int(args.min_events)
        and primary_oos_count >= int(args.min_oos_events)
        and primary_mean > max(0.0, all_mean)
        and primary_oos_mean >= 0.0
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "portfolio": portfolio,
        "inputs": {
            "target_book": str(target_path),
            "candidate_book": str(candidate_path),
            "price_cache": str(price_cache),
        },
        "event_count": int(len(events)),
        "short_rs_days": int(args.short_rs_days),
        "forward_days": int(args.forward_days),
        "min_reduction": float(args.min_reduction),
        "oos_start": args.oos_start,
        "primary_predicate": primary_label,
        "predicate_summary": summary_rows,
        "screen_pass": screen_pass,
        "verdict": "screen_pass_design_default_off_incumbent_challenger_hook" if screen_pass else "screen_reject_or_telemetry_only",
        "next_action": "design_default_off_hook_candidate" if screen_pass else "do_not_add_rs2w_to_score",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_dir / "events.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(output_dir / "predicate_summary.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--target-book", default="")
    parser.add_argument("--candidate-book", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--portfolio", choices=["main", "concentrated"], default="concentrated")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-reduction", type=float, default=0.02)
    parser.add_argument("--short-rs-days", type=int, default=10)
    parser.add_argument("--forward-days", type=int, default=126)
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--min-events", type=int, default=10)
    parser.add_argument("--min-oos-events", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
