#!/usr/bin/env python3
"""Research-only funded hedge overlay A/B for the Main target book.

This tool tests whether a small inverse-ETF hedge sleeve can repair Main MDD
without cutting the long alpha book through blunt cash/stops.  It never mutates
operating outputs and never claims production validity.  Hedge arms require a
real hedge ticker in the price cache; if the hedge price is missing, the arm is
blocked rather than simulated.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series  # noqa: E402

SCHEMA_VERSION = "main-hedge-overlay-broker-ab-v1"
DEFAULT_OUTPUT_DIR = "outputs/main_hedge_overlay_broker_ab"
CASH_TICKERS = {"CASH", "__CASH__"}
CRISIS_STATES = {"WATCH", "DEFENSE_REVIEW", "CRISIS_DEFENSE", "REENTRY_READY"}
ARMS = [
    {"arm": "baseline_main", "kind": "baseline", "hedge_weight": 0.0, "cash_raise": 0.0},
    {"arm": "static_small_hedge", "kind": "static", "hedge_weight": 0.025, "cash_raise": 0.0},
    {"arm": "crisis_state_hedge", "kind": "crisis_state", "watch_weight": 0.025, "defense_weight": 0.075, "crisis_weight": 0.10, "cash_raise": 0.0},
    {"arm": "trend_break_hedge", "kind": "trend_break", "hedge_weight": 0.05, "cash_raise": 0.0},
    {"arm": "fast_crash_hedge", "kind": "fast_crash", "hedge_weight": 0.075, "cash_raise": 0.0},
    {"arm": "hybrid_crisis_trend_hedge", "kind": "hybrid", "hedge_weight": 0.075, "cash_raise": 0.0},
    {"arm": "cash_plus_hedge", "kind": "cash_plus_hedge", "hedge_weight": 0.04, "cash_raise": 0.04},
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


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


def resolve_target_book(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"target book not found: {path}")
        return path
    candidates = [
        latest_run / "alphaops_vnext" / "official_main_target_book.csv",
        latest_run / "reports" / "operating_main_target_book.csv",
        latest_run / "market_leader_challenger" / "main_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("no Main target book found under latest-run")


def resolve_crisis_state(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        return repo_path(explicit)
    candidates = [
        latest_run / "alphaops_vnext" / "daily_crisis_state.csv",
        latest_run / "daily_crisis_state.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def normalize_book(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].map(clean_ticker)
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in d.columns:
        d["target_weight"] = pd.to_numeric(d["target_weight"], errors="coerce").fillna(d["weight"])
    else:
        d["target_weight"] = d["weight"]
    d = d[d["rebalance_date"].notna()]
    d = d[(d["ticker"] != "") & d["weight"].ge(0.0)]
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def crisis_lookup(frame: pd.DataFrame) -> dict[pd.Timestamp, str]:
    if frame.empty or "date" not in frame.columns:
        return {}
    d = frame.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    state_col = "crisis_state" if "crisis_state" in d.columns else "raw_state"
    d["_state"] = d.get(state_col, "").astype(str).str.upper().str.strip()
    d = d[d["date"].notna()].sort_values("date")
    return {pd.Timestamp(row["date"]).normalize(): str(row["_state"]) for _, row in d.iterrows()}


def state_at_or_before(states: dict[pd.Timestamp, str], dt: pd.Timestamp) -> str:
    if not states:
        return "UNKNOWN"
    keys = sorted(states)
    pos = pd.Index(keys).searchsorted(pd.Timestamp(dt).normalize(), side="right") - 1
    if pos < 0:
        return "UNKNOWN"
    return states[keys[int(pos)]] or "UNKNOWN"


def price_features(px: pd.DataFrame, dt: pd.Timestamp) -> dict[str, Any]:
    if px.empty:
        return {"coverage": False}
    idx = pd.DatetimeIndex(px.index)
    pos = int(idx.searchsorted(pd.Timestamp(dt).normalize(), side="right")) - 1
    if pos < 0:
        return {"coverage": False}
    close = pd.to_numeric(px["close"], errors="coerce")
    cur = safe_float(close.iloc[pos], 0.0)
    if cur <= 0:
        return {"coverage": False}
    start_5 = close.iloc[pos - 5] if pos >= 5 else float("nan")
    start_10 = close.iloc[pos - 10] if pos >= 10 else float("nan")
    ret_5d = float(cur / start_5 - 1.0) if safe_float(start_5) > 0 else 0.0
    ret_10d = float(cur / start_10 - 1.0) if safe_float(start_10) > 0 else 0.0
    ma50 = float(close.iloc[max(0, pos - 49) : pos + 1].mean())
    peak_63 = float(close.iloc[max(0, pos - 62) : pos + 1].max())
    dd_63 = float(cur / peak_63 - 1.0) if peak_63 > 0 else 0.0
    return {
        "coverage": True,
        "close": cur,
        "ret_5d": ret_5d,
        "ret_10d": ret_10d,
        "below_ma50": bool(cur < ma50),
        "drawdown_63d": dd_63,
    }


def hedge_weight_for_arm(arm: dict[str, Any], *, state: str, features: dict[str, Any]) -> tuple[float, float, str]:
    kind = str(arm["kind"])
    if kind == "baseline":
        return 0.0, 0.0, "baseline"
    if kind == "static":
        return float(arm["hedge_weight"]), float(arm.get("cash_raise", 0.0)), "static_small_hedge"
    state_u = str(state or "").upper()
    trend_break = bool(features.get("coverage") and features.get("below_ma50") and safe_float(features.get("drawdown_63d")) <= -0.06)
    fast_crash = bool(features.get("coverage") and (safe_float(features.get("ret_5d")) <= -0.05 or safe_float(features.get("ret_10d")) <= -0.08))
    crisis = state_u in CRISIS_STATES
    if kind == "crisis_state":
        if state_u == "WATCH":
            return float(arm["watch_weight"]), 0.0, "watch_state"
        if state_u == "DEFENSE_REVIEW":
            return float(arm["defense_weight"]), 0.0, "defense_review_state"
        if state_u in {"CRISIS_DEFENSE", "REENTRY_READY"}:
            return float(arm["crisis_weight"]), 0.0, "crisis_or_reentry_state"
        return 0.0, 0.0, "no_crisis_state"
    if kind == "trend_break":
        return (float(arm["hedge_weight"]), 0.0, "trend_break") if trend_break else (0.0, 0.0, "no_trend_break")
    if kind == "fast_crash":
        return (float(arm["hedge_weight"]), 0.0, "fast_crash") if fast_crash else (0.0, 0.0, "no_fast_crash")
    if kind == "hybrid":
        return (float(arm["hedge_weight"]), 0.0, "hybrid_crisis_trend") if crisis and (trend_break or fast_crash) else (0.0, 0.0, "no_hybrid_signal")
    if kind == "cash_plus_hedge":
        return (float(arm["hedge_weight"]), float(arm["cash_raise"]), "cash_plus_hedge") if crisis and (trend_break or fast_crash) else (0.0, 0.0, "no_cash_plus_signal")
    return 0.0, 0.0, "unknown_arm"


def build_hedged_book(
    book: pd.DataFrame,
    *,
    arm: dict[str, Any],
    hedge_ticker: str,
    benchmark_px: pd.DataFrame,
    states: dict[pd.Timestamp, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    out: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    for dt, group in book.groupby("rebalance_date", sort=True):
        date = pd.Timestamp(dt).normalize()
        state = state_at_or_before(states, date)
        features = price_features(benchmark_px, date)
        hedge_w, cash_raise, reason = hedge_weight_for_arm(arm, state=state, features=features)
        group_records = group.to_dict("records")
        stock_rows = [dict(row) for row in group_records if clean_ticker(row.get("ticker")) not in CASH_TICKERS]
        cash_rows = [dict(row) for row in group_records if clean_ticker(row.get("ticker")) in CASH_TICKERS]
        stock_gross = sum(max(0.0, safe_float(row.get("weight"))) for row in stock_rows)
        total_overlay = min(max(0.0, hedge_w + cash_raise), max(0.0, stock_gross))
        scale = (stock_gross - total_overlay) / stock_gross if stock_gross > 1e-12 else 1.0
        for row in stock_rows:
            old = safe_float(row.get("weight"))
            row["weight"] = old * scale
            row["target_weight"] = safe_float(row.get("target_weight"), old) * scale
            row["hedge_overlay_scale"] = scale
            out.append(row)
        if hedge_w > 1e-12:
            template = dict(group_records[0]) if group_records else {"rebalance_date": date.date().isoformat()}
            hedge = {key: "" for key in template.keys()}
            hedge.update(
                {
                    "rebalance_date": date.date().isoformat(),
                    "ticker": hedge_ticker,
                    "Name": f"{hedge_ticker} hedge sleeve",
                    "sector": "Hedge",
                    "weight": hedge_w,
                    "target_weight": hedge_w,
                    "portfolio_kind": "main",
                    "selection_reason": f"research_only_main_hedge_overlay:{arm['arm']}",
                }
            )
            out.append(hedge)
        if cash_rows:
            cash = dict(cash_rows[0])
            cash["weight"] = safe_float(cash.get("weight")) + cash_raise
            cash["target_weight"] = safe_float(cash.get("target_weight"), safe_float(cash.get("weight"))) + cash_raise
            out.append(cash)
        elif cash_raise > 1e-12:
            out.append(
                {
                    "rebalance_date": date.date().isoformat(),
                    "ticker": "CASH",
                    "Name": "Cash",
                    "sector": "Cash",
                    "weight": cash_raise,
                    "target_weight": cash_raise,
                    "portfolio_kind": "main",
                    "selection_reason": f"research_only_main_hedge_overlay_cash:{arm['arm']}",
                }
            )
        action_rows.append(
            {
                "rebalance_date": date.date().isoformat(),
                "arm": arm["arm"],
                "crisis_state": state,
                "hedge_ticker": hedge_ticker,
                "hedge_weight": hedge_w,
                "cash_raise_weight": cash_raise,
                "stock_gross_before": stock_gross,
                "stock_gross_after": stock_gross - total_overlay,
                "gross_total_after": stock_gross - total_overlay + hedge_w + cash_raise + sum(safe_float(row.get("weight")) for row in cash_rows),
                "reason": reason,
                "benchmark_ret_5d": features.get("ret_5d"),
                "benchmark_ret_10d": features.get("ret_10d"),
                "benchmark_drawdown_63d": features.get("drawdown_63d"),
                "benchmark_below_ma50": features.get("below_ma50"),
            }
        )
    return pd.DataFrame(out), pd.DataFrame(action_rows)


def run_broker_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    cost_bps: float,
    max_fill_lag_days: int,
    starting_capital: float,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_broker_ledger_replay.py"),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--output-dir",
        str(output_dir),
        "--portfolio-kind",
        "main",
        "--fill-mode",
        "next_close",
        "--cost-bps",
        str(cost_bps),
        "--max-fill-lag-days",
        str(max_fill_lag_days),
        "--starting-capital",
        str(starting_capital),
        "--oos-start",
        "2024-06-03",
        "--oos2-start",
        "2023-06-03",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    metrics = read_json(output_dir / "metrics.json")
    metrics["broker_returncode"] = proc.returncode
    if proc.returncode != 0:
        metrics["status"] = metrics.get("status") or "blocked"
        metrics["stderr_tail"] = "\n".join((proc.stderr or "").splitlines()[-20:])
    return metrics


def add_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((row for row in rows if row.get("arm") == "baseline_main"), rows[0] if rows else {})
    for row in rows:
        for col, out_col, scale in [
            ("cagr", "delta_cagr_pp", 100.0),
            ("max_dd", "delta_max_dd_pp", 100.0),
            ("sharpe", "delta_sharpe", 1.0),
            ("total_fees_usd", "delta_total_fees_usd", 1.0),
            ("trade_count", "delta_trade_count", 1.0),
        ]:
            row[out_col] = (safe_float(row.get(col)) - safe_float(baseline.get(col))) * scale
    return rows


def classify(row: dict[str, Any], baseline: dict[str, Any]) -> str:
    if row.get("arm") == "baseline_main":
        return "baseline"
    if row.get("status") == "blocked":
        return str(row.get("reason") or "blocked")
    if str(row.get("metric_mode")) != "broker_ledger_next_close":
        return "blocked_invalid_metric_mode"
    if safe_float(row.get("max_dd")) < -0.25:
        return "reject_mdd_not_repaired"
    if safe_float(row.get("cagr")) < safe_float(baseline.get("cagr")) - 0.005:
        return "reject_cagr_drag_too_large"
    if safe_float(row.get("sharpe")) < safe_float(baseline.get("sharpe")) - 0.05:
        return "reject_sharpe_deterioration"
    return "research_pass_main_mdd_candidate"


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Main Hedge Overlay Broker A/B",
        "",
        "Research-only funded hedge overlay screen for Main MDD repair.",
        "",
        f"- hedge_ticker: `{payload.get('hedge_ticker')}`",
        f"- benchmark_ticker: `{payload.get('benchmark_ticker')}`",
        f"- verdict: `{payload.get('verdict')}`",
        f"- production_activation_allowed: `{payload.get('production_activation_allowed')}`",
        "",
        "## Arms",
        "",
        "| arm | verdict | CAGR | MDD | Sharpe | dCAGR pp | dMDD pp | active dates | avg hedge | fees |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload.get("arms", []):
        lines.append(
            f"| `{row.get('arm')}` | `{row.get('ab_verdict')}` | "
            f"{safe_float(row.get('cagr')):.2%} | {safe_float(row.get('max_dd')):.2%} | "
            f"{safe_float(row.get('sharpe')):.3f} | {safe_float(row.get('delta_cagr_pp')):.2f} | "
            f"{safe_float(row.get('delta_max_dd_pp')):.2f} | {int(safe_float(row.get('hedge_active_dates')))} | "
            f"{safe_float(row.get('avg_hedge_weight')):.2%} | ${safe_float(row.get('total_fees_usd')):,.0f} |"
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- This is not production activation.",
            "- Hedge arms use funded long reduction; total gross is bounded by the original book.",
            "- A real hedge ticker must exist in the price cache. Missing hedge price blocks the arm.",
            "- A passing screen still requires governance review before any operating use.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    price_cache = repo_path(args.price_cache)
    target_path = resolve_target_book(latest_run, args.target_book or None)
    crisis_path = resolve_crisis_state(latest_run, args.crisis_state or None)
    book = normalize_book(read_csv(target_path))
    states = crisis_lookup(read_csv(crisis_path))
    hedge_ticker = clean_ticker(args.hedge_ticker)
    benchmark_ticker = clean_ticker(args.benchmark_ticker)
    hedge_px = load_price_series(price_cache, hedge_ticker)
    benchmark_px = load_price_series(price_cache, benchmark_ticker)
    if hedge_px.empty:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": utc_now(),
            "status": "blocked",
            "reason": "blocked_missing_hedge_price",
            "hedge_ticker": hedge_ticker,
            "price_cache": str(price_cache),
            "research_only": True,
            "production_activation_allowed": False,
            "next_action": f"refresh price cache with required ticker {hedge_ticker} before hedge A/B",
        }
        write_json(output_dir / "summary.json", payload)
        write_text(output_dir / "report.md", render_report({**payload, "arms": []}))
        return payload
    if benchmark_px.empty:
        raise FileNotFoundError(f"benchmark ticker missing from price cache: {benchmark_ticker}")

    arm_rows: list[dict[str, Any]] = []
    for arm in ARMS:
        arm_dir = output_dir / arm["arm"]
        arm_dir.mkdir(parents=True, exist_ok=True)
        if arm["kind"] == "baseline":
            arm_book = book.copy()
            actions = pd.DataFrame(
                [
                    {
                        "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                        "arm": arm["arm"],
                        "hedge_ticker": hedge_ticker,
                        "hedge_weight": 0.0,
                        "cash_raise_weight": 0.0,
                        "reason": "baseline",
                    }
                    for dt in sorted(book["rebalance_date"].dropna().unique())
                ]
            )
        else:
            arm_book, actions = build_hedged_book(book, arm=arm, hedge_ticker=hedge_ticker, benchmark_px=benchmark_px, states=states)
        target_out = arm_dir / "target_book.csv"
        actions_out = arm_dir / "hedge_actions.csv"
        arm_book.to_csv(target_out, index=False)
        actions.to_csv(actions_out, index=False)
        metrics = run_broker_replay(
            target_book=target_out,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            starting_capital=float(args.starting_capital),
        )
        hedge_weights = pd.to_numeric(actions.get("hedge_weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        row = {
            "arm": arm["arm"],
            **metrics,
            "target_book_path": str(target_out),
            "hedge_actions_path": str(actions_out),
            "hedge_active_dates": int(hedge_weights.gt(1e-12).sum()),
            "avg_hedge_weight": float(hedge_weights.mean()) if len(hedge_weights) else 0.0,
            "max_hedge_weight": float(hedge_weights.max()) if len(hedge_weights) else 0.0,
            "avg_cash_raise_weight": float(pd.to_numeric(actions.get("cash_raise_weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0).mean()) if len(actions) else 0.0,
        }
        arm_rows.append(row)
    arm_rows = add_deltas(arm_rows)
    baseline = next((row for row in arm_rows if row.get("arm") == "baseline_main"), {})
    for row in arm_rows:
        row["ab_verdict"] = classify(row, baseline)
    candidates = [row for row in arm_rows if row.get("ab_verdict") == "research_pass_main_mdd_candidate"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "research_only": True,
        "production_activation_allowed": False,
        "hedge_ticker": hedge_ticker,
        "benchmark_ticker": benchmark_ticker,
        "inputs": {
            "latest_run": str(latest_run),
            "target_book": str(target_path),
            "crisis_state": str(crisis_path),
            "price_cache": str(price_cache),
        },
        "arms": arm_rows,
        "policy_candidates": candidates,
        "verdict": "research_pass_main_hedge_overlay_candidate" if candidates else "screen_reject_hedge_overlay_no_mission_quality_tradeoff",
        "next_action": "governance_review_before_any_policy_hook" if candidates else "do_not_fullrun_hedge_overlay",
    }
    pd.DataFrame(arm_rows).to_csv(output_dir / "arm_metrics.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--crisis-state", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hedge-ticker", default="SH")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    return parser.parse_args()


def main() -> None:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
