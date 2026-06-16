#!/usr/bin/env python3
"""Audit entry, exit, holding duration, and premature-sell timing.

Measurement-only sidecar. It reads broker trade journals/replays and writes
Alpha Plane timing diagnostics without changing target books or strategy.
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from historical_replay_lib import read_table, repo_path, safe_float, write_json, write_text


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/entry_exit_timing_audit"
CASH_TICKERS = {"CASH", "__CASH__", "BIL", "SGOV"}
PORTFOLIOS = ("main", "concentrated")
HORIZONS = (63, 126)

COMMON_METADATA_COLUMNS = [
    "source_run_id",
    "source_commit_sha",
    "source_branch",
    "portfolio_policy",
    "metric_mode",
    "official_metric_source",
    "candidate_source",
    "target_book_source",
    "generated_at",
    "production_mutation_allowed",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_value(args: list[str], default: str = "unknown") -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=repo_path("."), text=True, stderr=subprocess.DEVNULL).strip() or default
    except Exception:
        return default


def _metadata(latest_run: Path, generated_at: str) -> dict[str, Any]:
    return {
        "source_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "source_commit_sha": os.environ.get("GITHUB_SHA") or _git_value(["rev-parse", "--short", "HEAD"]),
        "source_branch": os.environ.get("GITHUB_REF_NAME") or _git_value(["branch", "--show-current"]),
        "portfolio_policy": os.environ.get("PORTFOLIO_POLICY", "alphaops_vnext_production"),
        "metric_mode": "broker_ledger_next_close",
        "official_metric_source": "outputs/account_evaluation/official_metrics.json",
        "candidate_source": str(latest_run / "reports" / "candidate_replay_book.csv"),
        "target_book_source": str(latest_run / "reports" / "operating_*_target_book.csv"),
        "generated_at": generated_at,
        "production_mutation_allowed": False,
    }


def _normalize_ticker(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    out = frame.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out = out[(out["ticker"] != "") & ~out["ticker"].isin(CASH_TICKERS)].copy()
    return out


def _load_round_trips(latest_run: Path, portfolio: str) -> pd.DataFrame:
    paths = [
        latest_run / "broker_trade_journal" / portfolio / "round_trips.csv",
        latest_run / "concentrated_trade_journal" / "round_trips.csv" if portfolio == "concentrated" else latest_run / "trade_journal" / "round_trips.csv",
    ]
    for path in paths:
        frame = _normalize_ticker(read_table(path))
        if not frame.empty:
            frame["portfolio"] = portfolio
            return frame
    return pd.DataFrame()


def _load_trades(latest_run: Path, portfolio: str) -> pd.DataFrame:
    frame = _normalize_ticker(read_table(latest_run / "broker_replay" / portfolio / "trades.csv"))
    if frame.empty:
        return pd.DataFrame()
    frame["portfolio"] = portfolio
    for col in ("date", "signal_date"):
        if col in frame.columns:
            frame[col] = pd.to_datetime(frame[col], errors="coerce")
    if "side" in frame.columns:
        frame["side"] = frame["side"].astype(str).str.upper()
    if "fill_price" in frame.columns:
        frame["fill_price"] = pd.to_numeric(frame["fill_price"], errors="coerce")
    return frame.dropna(subset=["date"]) if "date" in frame.columns else frame


def _lane(row: pd.Series) -> str:
    for col in ("lane", "portfolio_sleeve_label", "portfolio_sleeve_role", "entry_lane"):
        value = str(row.get(col, "") or "").strip()
        if value:
            return value
    return "unassigned"


def _entry_state(row: pd.Series) -> str:
    reason = str(row.get("entry_reason", "") or "").lower()
    if "reentry" in reason:
        return "REENTRY_BUY"
    if "add" in reason:
        return "ADD"
    return "NEW_BUY"


def _leader_state(row: pd.Series) -> str:
    for col in ("leader_state_at_exit", "leader_state", "exit_leader_state"):
        value = str(row.get(col, "") or "").strip().upper()
        if value:
            return value
    holding = safe_float(row.get("holding_days"), 0.0)
    realized = safe_float(row.get("realized_return"), 0.0)
    if holding >= 90 and realized > 0:
        return "HOLD"
    if holding >= 30 and realized > 0:
        return "WARNING_1"
    if realized < -0.12:
        return "EXIT_REPLACE"
    return "TRIM_REVIEW"


def _exit_state(row: pd.Series) -> str:
    state = _leader_state(row)
    if state in {"HOLD", "SHAKEOUT_GUARD", "WARNING_1", "WARNING_2"}:
        return state
    return "EXIT_REPLACE" if safe_float(row.get("realized_return"), 0.0) < 0 else "TRIM_REVIEW"


def _price_timelines(trades: pd.DataFrame) -> dict[str, list[tuple[pd.Timestamp, float]]]:
    timelines: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    if trades.empty or "date" not in trades.columns or "fill_price" not in trades.columns:
        return timelines
    for _, row in trades.dropna(subset=["date", "fill_price"]).sort_values("date").iterrows():
        price = safe_float(row.get("fill_price"), math.nan)
        if not math.isfinite(price) or price <= 0:
            continue
        timelines.setdefault(str(row["ticker"]).upper(), []).append((row["date"], price))
    return timelines


def _future_return(timelines: dict[str, list[tuple[pd.Timestamp, float]]], ticker: str, date: pd.Timestamp, price: float, horizon: int) -> float | None:
    target = date + pd.Timedelta(days=int(horizon))
    best_price = None
    best_dist = 10**9
    for obs_date, obs_price in timelines.get(ticker, []):
        if obs_date <= date:
            continue
        dist = abs((obs_date - target).days)
        if dist <= 18 and dist < best_dist:
            best_price = obs_price
            best_dist = dist
    if best_price is None or price <= 0:
        return None
    return float(best_price / price - 1.0)


def _same_day_replacement_return(trades: pd.DataFrame, timelines: dict[str, list[tuple[pd.Timestamp, float]]], date: pd.Timestamp, horizon: int) -> float | None:
    if trades.empty or "side" not in trades.columns:
        return None
    same_day = trades[(trades["date"].eq(date)) & (trades["side"].eq("BUY"))].copy()
    returns = []
    for _, row in same_day.iterrows():
        ret = _future_return(timelines, str(row["ticker"]).upper(), date, safe_float(row.get("fill_price"), math.nan), horizon)
        if ret is not None:
            returns.append(ret)
    return float(sum(returns) / len(returns)) if returns else None


def _build_entry_exit_rows(round_trips: pd.DataFrame, meta: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if round_trips.empty:
        empty = pd.DataFrame(columns=[*COMMON_METADATA_COLUMNS, "portfolio", "ticker", "entry_date", "exit_date"])
        return empty, empty.copy()
    rt = round_trips.copy()
    for col in ("entry_date", "exit_date"):
        if col in rt.columns:
            rt[col] = pd.to_datetime(rt[col], errors="coerce").dt.strftime("%Y-%m-%d")
    rt["lane"] = rt.apply(_lane, axis=1)
    rt["entry_state"] = rt.apply(_entry_state, axis=1)
    rt["exit_state"] = rt.apply(_exit_state, axis=1)
    rt["leader_state_at_exit"] = rt.apply(_leader_state, axis=1)
    rt["holding_days"] = pd.to_numeric(rt.get("holding_days"), errors="coerce").fillna(0.0)
    rt["realized_return"] = pd.to_numeric(rt.get("realized_return"), errors="coerce").fillna(0.0)
    for k, value in meta.items():
        rt[k] = value
    entry_cols = [
        *COMMON_METADATA_COLUMNS,
        "portfolio",
        "ticker",
        "entry_date",
        "entry_state",
        "entry_reason",
        "lane",
        "holding_days",
        "realized_return",
    ]
    exit_cols = [
        *COMMON_METADATA_COLUMNS,
        "portfolio",
        "ticker",
        "entry_date",
        "exit_date",
        "exit_state",
        "leader_state_at_exit",
        "exit_reason",
        "lane",
        "holding_days",
        "realized_return",
    ]
    for col in set(entry_cols + exit_cols):
        if col not in rt.columns:
            rt[col] = ""
    return rt[entry_cols].copy(), rt[exit_cols].copy()


def _premature_rows(round_trips: pd.DataFrame, trades: pd.DataFrame, meta: dict[str, Any]) -> pd.DataFrame:
    columns = [
        *COMMON_METADATA_COLUMNS,
        "portfolio",
        "ticker",
        "sell_date",
        "leader_state_at_exit",
        "exit_price",
        "sold_forward_return_63d",
        "same_day_replacement_return_63d",
        "premature_sell_excess_63d",
        "sold_forward_return_126d",
        "same_day_replacement_return_126d",
        "premature_sell_excess_126d",
        "premature_sell_candidate",
    ]
    if round_trips.empty:
        return pd.DataFrame(columns=columns)
    rt = round_trips.copy()
    rt["exit_date_ts"] = pd.to_datetime(rt.get("exit_date"), errors="coerce")
    rt = rt.dropna(subset=["exit_date_ts"])
    timelines = _price_timelines(trades)
    rows: list[dict[str, Any]] = []
    for _, row in rt.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        exit_date = row["exit_date_ts"]
        exit_price = safe_float(row.get("exit_price"), math.nan)
        if not math.isfinite(exit_price):
            sells = trades[(trades.get("side", pd.Series(dtype=str)).eq("SELL")) & (trades.get("ticker", pd.Series(dtype=str)).eq(ticker)) & (trades.get("date", pd.Series(dtype="datetime64[ns]")).eq(exit_date))]
            if not sells.empty:
                exit_price = safe_float(sells.iloc[-1].get("fill_price"), math.nan)
        if not math.isfinite(exit_price) or exit_price <= 0:
            continue
        leader_state = _leader_state(row)
        payload: dict[str, Any] = {
            **meta,
            "portfolio": row.get("portfolio", ""),
            "ticker": ticker,
            "sell_date": exit_date.date().isoformat(),
            "leader_state_at_exit": leader_state,
            "exit_price": exit_price,
            "premature_sell_candidate": False,
        }
        any_positive = False
        for horizon in HORIZONS:
            sold_ret = _future_return(timelines, ticker, exit_date, exit_price, horizon)
            repl_ret = _same_day_replacement_return(trades, timelines, exit_date, horizon)
            payload[f"sold_forward_return_{horizon}d"] = sold_ret if sold_ret is not None else ""
            payload[f"same_day_replacement_return_{horizon}d"] = repl_ret if repl_ret is not None else ""
            payload[f"premature_sell_excess_{horizon}d"] = (
                sold_ret - repl_ret if sold_ret is not None and repl_ret is not None else ""
            )
            if sold_ret is not None and sold_ret > 0:
                any_positive = True
        payload["premature_sell_candidate"] = bool(any_positive and leader_state in {"HOLD", "SHAKEOUT_GUARD", "WARNING_1"})
        rows.append(payload)
    return pd.DataFrame(rows, columns=columns)


def _hold_duration_by_lane(exit_audit: pd.DataFrame, meta: dict[str, Any]) -> pd.DataFrame:
    columns = [
        *COMMON_METADATA_COLUMNS,
        "portfolio",
        "lane",
        "trade_count",
        "median_holding_days",
        "pct_held_180d_plus",
        "pct_held_365d_plus",
    ]
    if exit_audit.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (portfolio, lane), group in exit_audit.groupby(["portfolio", "lane"], dropna=False):
        hd = pd.to_numeric(group["holding_days"], errors="coerce").dropna()
        if hd.empty:
            continue
        rows.append(
            {
                **meta,
                "portfolio": portfolio,
                "lane": lane,
                "trade_count": int(len(hd)),
                "median_holding_days": float(hd.median()),
                "pct_held_180d_plus": float((hd >= 180).mean()),
                "pct_held_365d_plus": float((hd >= 365).mean()),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _replacement_summary(exit_audit: pd.DataFrame, premature: pd.DataFrame, meta: dict[str, Any]) -> pd.DataFrame:
    columns = [*COMMON_METADATA_COLUMNS, "portfolio", "replacement_reason", "trade_count", "median_holding_days"]
    rows = []
    if not exit_audit.empty:
        for (portfolio, reason), group in exit_audit.groupby(["portfolio", "exit_state"], dropna=False):
            rows.append(
                {
                    **meta,
                    "portfolio": portfolio,
                    "replacement_reason": reason,
                    "trade_count": int(len(group)),
                    "median_holding_days": float(pd.to_numeric(group["holding_days"], errors="coerce").median()),
                }
            )
    if not premature.empty:
        for portfolio, group in premature.groupby("portfolio", dropna=False):
            rows.append(
                {
                    **meta,
                    "portfolio": portfolio,
                    "replacement_reason": "premature_sell_candidate",
                    "trade_count": int(pd.Series(group["premature_sell_candidate"]).astype(bool).sum()),
                    "median_holding_days": "",
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _summary(
    entry: pd.DataFrame,
    exit_audit: pd.DataFrame,
    premature: pd.DataFrame,
    meta: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "status": "completed" if not entry.empty or not exit_audit.empty else "skipped",
        "schema_version": "entry_exit_timing_audit_v1",
        **meta,
        "entry_rows": int(len(entry)),
        "exit_rows": int(len(exit_audit)),
        "premature_sell_rows": int(len(premature)),
        "premature_sell_candidates": int(pd.Series(premature.get("premature_sell_candidate", [])).astype(bool).sum()) if not premature.empty else 0,
        "by_portfolio": {},
    }
    for portfolio, group in exit_audit.groupby("portfolio", dropna=False) if not exit_audit.empty else []:
        hd = pd.to_numeric(group["holding_days"], errors="coerce").dropna()
        payload["by_portfolio"][str(portfolio)] = {
            "trade_count": int(len(hd)),
            "median_holding_days": float(hd.median()) if not hd.empty else 0.0,
            "pct_held_180d_plus": float((hd >= 180).mean()) if not hd.empty else 0.0,
            "pct_held_365d_plus": float((hd >= 365).mean()) if not hd.empty else 0.0,
        }
    return payload


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    generated_at = _now_iso()
    meta = _metadata(latest_run, generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    entry_frames = []
    exit_frames = []
    premature_frames = []
    for portfolio in PORTFOLIOS:
        round_trips = _load_round_trips(latest_run, portfolio)
        trades = _load_trades(latest_run, portfolio)
        entry, exit_audit = _build_entry_exit_rows(round_trips, meta)
        entry_frames.append(entry)
        exit_frames.append(exit_audit)
        premature_frames.append(_premature_rows(round_trips, trades, meta))

    entry_all = pd.concat(entry_frames, ignore_index=True) if entry_frames else pd.DataFrame()
    exit_all = pd.concat(exit_frames, ignore_index=True) if exit_frames else pd.DataFrame()
    premature_all = pd.concat([f for f in premature_frames if not f.empty], ignore_index=True) if any(not f.empty for f in premature_frames) else pd.DataFrame()
    hold_duration = _hold_duration_by_lane(exit_all, meta)
    replacement_summary = _replacement_summary(exit_all, premature_all, meta)

    entry_all.to_csv(output_dir / "entry_timing_audit.csv", index=False)
    exit_all.to_csv(output_dir / "exit_timing_audit.csv", index=False)
    premature_all.to_csv(output_dir / "premature_sell_counterfactual.csv", index=False)
    hold_duration.to_csv(output_dir / "hold_duration_by_lane.csv", index=False)
    replacement_summary.to_csv(output_dir / "replacement_reason_summary.csv", index=False)

    payload = _summary(entry_all, exit_all, premature_all, meta)
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", _render_report(payload))
    return payload


def _render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Entry/Exit Timing Audit",
        "",
        "Measurement-only diagnostic. No strategy or target-book mutation.",
        "",
        "## Summary",
        "",
        f"- status: `{payload.get('status')}`",
        f"- metric mode: `{payload.get('metric_mode')}`",
        f"- production mutation allowed: `{payload.get('production_mutation_allowed')}`",
        f"- entry rows: {payload.get('entry_rows', 0)}",
        f"- exit rows: {payload.get('exit_rows', 0)}",
        f"- premature sell candidates: {payload.get('premature_sell_candidates', 0)}",
        "",
        "## Portfolio Metrics",
        "",
    ]
    for portfolio, block in sorted((payload.get("by_portfolio") or {}).items()):
        lines.append(
            f"- `{portfolio}`: trades {block.get('trade_count', 0)}, "
            f"median hold {safe_float(block.get('median_holding_days'), 0.0):.1f}d, "
            f"held 180d+ {safe_float(block.get('pct_held_180d_plus'), 0.0):.1%}, "
            f"held 365d+ {safe_float(block.get('pct_held_365d_plus'), 0.0):.1%}"
        )
    lines.extend(
        [
            "",
            "## Interpretation Rules",
            "",
            "- Forward returns after a sell are audit labels only, not live signals.",
            "- Premature sell candidates require positive sold-name forward return and a non-broken leader state at exit.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(f"[entry-exit-timing] {payload.get('status')} -> {repo_path(args.output_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
