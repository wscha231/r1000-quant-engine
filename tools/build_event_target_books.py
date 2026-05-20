#!/usr/bin/env python3
"""Build event-driven target books from monthly/operating target books.

This is the first bridge from monthly research targets to account-like daily
operation. It does not rescore the whole universe every day. Instead, it starts
from the existing main/concentrated target books and injects observable
daily/weekly event rows when a held position hits risk or stale-leader rules.

The output can be replayed by `run_broker_ledger_replay.py`, so CAGR/Sharpe/MDD
are measured with shares, cash, fees, fills, and daily equity rather than
weight-level proxy math.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_TICKERS,
    filter_concentrated_champion,
    resolve_concentrated_champion_filters,
    safe_float,
)
from tools.run_position_risk_weekly_validation import simulate_position  # noqa: E402
from tools.run_weekly_evaluation import load_price_series  # noqa: E402


DEFAULT_OUTPUT_DIR = "outputs/event_target_books"
DEFAULT_REPORTS_DIR = "outputs/reports"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def normalize_targets(frame: pd.DataFrame, portfolio_kind: str, target_book: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns or "weight" not in frame.columns:
        return pd.DataFrame(), {"target_book_filter": {}, "target_book_filter_source": "not_applicable", "target_book_filter_warning": ""}
    raw = frame.copy()
    filters, source, warning = resolve_concentrated_champion_filters(
        target_book=target_book,
        raw_targets=raw,
        portfolio_kind=portfolio_kind,
        explicit_filters=None,
    )
    d = filter_concentrated_champion(raw, portfolio_kind, filters).copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["weight"] = pd.to_numeric(d["weight"], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["weight"] > 1e-12)].copy()
    if d.empty:
        return d, {"target_book_filter": filters, "target_book_filter_source": source, "target_book_filter_warning": warning}
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True), {
        "target_book_filter": filters,
        "target_book_filter_source": source,
        "target_book_filter_warning": warning,
    }


def latest_period_end(targets: pd.DataFrame, prices: dict[str, pd.DataFrame], dt: pd.Timestamp, idx: int, dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    if idx + 1 < len(dates):
        return pd.Timestamp(dates[idx + 1]).normalize()
    period = targets[targets["rebalance_date"].eq(dt)]
    latest: list[pd.Timestamp] = []
    for ticker in period["ticker"].astype(str).str.upper().unique():
        if ticker in CASH_TICKERS:
            continue
        px = prices.get(ticker, pd.DataFrame())
        if not px.empty:
            latest.append(pd.Timestamp(px.index.max()).normalize())
    return max(latest) if latest else None


def original_template_by_ticker(period: pd.DataFrame) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for row in period.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        templates[ticker] = row
    return templates


def snapshot_rows(
    *,
    snapshot_date: pd.Timestamp,
    weights: dict[str, float],
    templates: dict[str, dict[str, Any]],
    portfolio_kind: str,
    event_kind: str,
    event_reason: str,
    event_source_tickers: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stock_sum = 0.0
    for ticker, weight in sorted(weights.items()):
        if ticker in CASH_TICKERS or weight <= 1e-12:
            continue
        base = dict(templates.get(ticker, {}))
        base["rebalance_date"] = snapshot_date.date().isoformat()
        base["ticker"] = ticker
        base["weight"] = float(weight)
        base["portfolio_kind"] = portfolio_kind
        base["event_target_book"] = True
        base["event_kind"] = event_kind
        base["event_reason"] = event_reason
        base["event_source_tickers"] = ",".join(event_source_tickers)
        rows.append(base)
        stock_sum += float(weight)
    cash_weight = max(0.0, 1.0 - stock_sum)
    if cash_weight > 1e-8:
        rows.append(
            {
                "rebalance_date": snapshot_date.date().isoformat(),
                "ticker": "CASH",
                "weight": float(cash_weight),
                "portfolio_kind": portfolio_kind,
                "event_target_book": True,
                "event_kind": event_kind,
                "event_reason": event_reason,
                "event_source_tickers": ",".join(event_source_tickers),
            }
        )
    return rows


def period_base_weights(period: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in period.to_dict("records"):
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker or ticker in CASH_TICKERS:
            continue
        out[ticker] = out.get(ticker, 0.0) + max(0.0, safe_float(row.get("weight"), 0.0))
    stock_sum = sum(out.values())
    if stock_sum > 1.0 + 1e-9:
        scale = 1.0 / stock_sum
        out = {ticker: weight * scale for ticker, weight in out.items()}
    return out


def price_dict_for_targets(price_cache: Path, targets: pd.DataFrame, benchmark_ticker: str) -> dict[str, pd.DataFrame]:
    tickers = sorted({str(x).upper() for x in targets["ticker"].unique() if str(x).upper() not in CASH_TICKERS})
    prices = {ticker: load_price_series(price_cache, ticker) for ticker in tickers + [benchmark_ticker.upper()]}
    return {ticker: frame for ticker, frame in prices.items() if not frame.empty}


def build_event_book(
    *,
    target_book: Path,
    price_cache: Path,
    portfolio_kind: str,
    benchmark_ticker: str,
    hard_stop: float,
    trailing_stop: float,
    trailing_activation: float,
    relative_trim_threshold: float,
    relative_exit_threshold: float,
    trim_weight: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    raw = read_csv(target_book)
    targets, filter_meta = normalize_targets(raw, portfolio_kind, target_book)
    if targets.empty:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "blocked",
            "reason": "target book is empty or invalid",
            "target_book": str(target_book),
            **filter_meta,
        }
    prices = price_dict_for_targets(price_cache, targets, benchmark_ticker)
    if not prices:
        return pd.DataFrame(), pd.DataFrame(), {
            "status": "blocked",
            "reason": "price cache has no usable target prices",
            "target_book": str(target_book),
            **filter_meta,
        }

    dates = [pd.Timestamp(x).normalize() for x in sorted(targets["rebalance_date"].dropna().unique())]
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    event_rows_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    event_count = 0
    trim_count = 0
    exit_count = 0
    missing_price_count = 0
    skipped_same_or_after_count = 0

    for idx, dt in enumerate(dates):
        period = targets[targets["rebalance_date"].eq(dt)].copy()
        if period.empty:
            continue
        end_dt = latest_period_end(targets, prices, dt, idx, dates)
        if end_dt is None or end_dt <= dt:
            continue
        templates = original_template_by_ticker(period)
        current_weights = period_base_weights(period)
        rows.extend(
            snapshot_rows(
                snapshot_date=dt,
                weights=current_weights,
                templates=templates,
                portfolio_kind=portfolio_kind,
                event_kind="scheduled_rebalance",
                event_reason="base_target_book",
                event_source_tickers=[],
            )
        )
        action_records: list[dict[str, Any]] = []
        for row in period.to_dict("records"):
            ticker = str(row.get("ticker") or "").upper().strip()
            if not ticker or ticker in CASH_TICKERS:
                continue
            result, actions = simulate_position(
                row,
                prices.get(ticker, pd.DataFrame()),
                prices.get(benchmark_ticker.upper(), pd.DataFrame()),
                dt + pd.Timedelta(days=1),
                end_dt,
                hard_stop=hard_stop,
                trailing_stop=trailing_stop,
                trailing_activation=trailing_activation,
                relative_trim_threshold=relative_trim_threshold,
                relative_exit_threshold=relative_exit_threshold,
                trim_weight=trim_weight,
            )
            if str(result.get("exit_action") or "") == "missing_price_hold_cash_proxy":
                missing_price_count += 1
            for action in actions:
                action_dt = pd.to_datetime(action.get("action_date"), errors="coerce")
                if pd.isna(action_dt):
                    continue
                action_dt = pd.Timestamp(action_dt).normalize()
                if action_dt <= dt or action_dt >= end_dt:
                    skipped_same_or_after_count += 1
                    continue
                active_after = float(np.clip(safe_float(action.get("active_multiplier_after"), 1.0), 0.0, 1.0))
                action_name = str(action.get("action") or "")
                action_records.append(
                    {
                        "action_date": action_dt,
                        "ticker": ticker,
                        "action": action_name,
                        "reason": action.get("reason", ""),
                        "active_multiplier_after": active_after,
                        "original_weight": safe_float(row.get("weight"), 0.0),
                        "new_weight": safe_float(row.get("weight"), 0.0) * active_after,
                        "price_return": action.get("price_return", ""),
                        "benchmark_return": action.get("benchmark_return", ""),
                        "relative_return": action.get("relative_return", ""),
                        "action_price": action.get("action_price", ""),
                    }
                )
        for action in sorted(action_records, key=lambda item: (item["action_date"], item["ticker"], item["action"])):
            action_dt = pd.Timestamp(action["action_date"]).normalize()
            ticker = str(action["ticker"])
            current_weights[ticker] = max(0.0, safe_float(action.get("new_weight"), 0.0))
            if current_weights[ticker] <= 1e-12:
                current_weights.pop(ticker, None)
            event_count += 1
            if "trim" in str(action.get("action") or ""):
                trim_count += 1
            if "exit" in str(action.get("action") or ""):
                exit_count += 1
            event_rows_by_date[action_dt].append(action)
            events.append(
                {
                    "portfolio_kind": portfolio_kind,
                    "base_rebalance_date": dt.date().isoformat(),
                    "period_end_date": end_dt.date().isoformat(),
                    "action_date": action_dt.date().isoformat(),
                    "ticker": ticker,
                    "action": action.get("action"),
                    "reason": action.get("reason"),
                    "original_weight": action.get("original_weight"),
                    "new_weight": current_weights.get(ticker, 0.0),
                    "cash_weight_after": max(0.0, 1.0 - sum(current_weights.values())),
                    "price_return": action.get("price_return"),
                    "benchmark_return": action.get("benchmark_return"),
                    "relative_return": action.get("relative_return"),
                    "action_price": action.get("action_price"),
                }
            )
            same_day = event_rows_by_date[action_dt]
            rows = [row for row in rows if not (str(row.get("rebalance_date")) == action_dt.date().isoformat() and str(row.get("event_kind")) == "event_overlay")]
            rows.extend(
                snapshot_rows(
                    snapshot_date=action_dt,
                    weights=current_weights,
                    templates=templates,
                    portfolio_kind=portfolio_kind,
                    event_kind="event_overlay",
                    event_reason=";".join(sorted({str(item.get("action")) for item in same_day})),
                    event_source_tickers=sorted({str(item.get("ticker")) for item in same_day}),
                )
            )

    out = pd.DataFrame(rows)
    if not out.empty:
        out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
        out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
        out = out[(out["ticker"].astype(str).str.upper().str.strip() != "") & (out["weight"] > 1e-12)].copy()
        out = out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    events_df = pd.DataFrame(events)
    summary = {
        "status": "completed" if not out.empty else "blocked",
        "portfolio_kind": portfolio_kind,
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "benchmark_ticker": benchmark_ticker.upper(),
        "data_mode": "target_book_plus_daily_price_event_overlay",
        "research_only": True,
        "production_activation_allowed": False,
        "valid_for_production": False,
        "promotion_note": "Event target book encodes observable daily/weekly exits and trims from existing target holdings. It does not yet create new daily entries from daily scored snapshots.",
        "base_decision_count": int(len(dates)),
        "output_row_count": int(len(out)),
        "event_count": int(event_count),
        "exit_count": int(exit_count),
        "trim_count": int(trim_count),
        "missing_price_count": int(missing_price_count),
        "skipped_same_or_after_count": int(skipped_same_or_after_count),
        "hard_stop": hard_stop,
        "trailing_stop": trailing_stop,
        "trailing_activation": trailing_activation,
        "relative_trim_threshold": relative_trim_threshold,
        "relative_exit_threshold": relative_exit_threshold,
        "trim_weight": trim_weight,
        **filter_meta,
    }
    return out, events_df, summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Event Target Books",
        "",
        "Research-only bridge from monthly/operating targets to daily event-aware broker replay.",
        "",
        "| Portfolio | Status | Rows | Events | Exits | Trims |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("books", []):
        lines.append(
            "| {portfolio} | {status} | {rows} | {events} | {exits} | {trims} |".format(
                portfolio=row.get("portfolio_kind"),
                status=row.get("status"),
                rows=row.get("output_row_count"),
                events=row.get("event_count"),
                exits=row.get("exit_count"),
                trims=row.get("trim_count"),
            )
        )
    lines.extend(
        [
            "",
            "These books can be replayed by the broker-ledger engine. They are not a daily alpha rescore yet; new daily entries require historical daily/weekly scored snapshots.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    reports_dir = repo_path(args.reports_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    specs = [
        ("main", latest_run / "reports" / "operating_main_target_book.csv"),
        ("concentrated", latest_run / "reports" / "operating_concentrated_target_book.csv"),
    ]
    summaries: list[dict[str, Any]] = []
    outputs: dict[str, str] = {}
    for portfolio_kind, default_path in specs:
        target_book = repo_path(getattr(args, f"{portfolio_kind}_target_book")) if getattr(args, f"{portfolio_kind}_target_book") else default_path
        book, events, summary = build_event_book(
            target_book=target_book,
            price_cache=price_cache,
            portfolio_kind=portfolio_kind,
            benchmark_ticker=args.benchmark_ticker,
            hard_stop=args.hard_stop,
            trailing_stop=args.trailing_stop,
            trailing_activation=args.trailing_activation,
            relative_trim_threshold=args.relative_trim_threshold,
            relative_exit_threshold=args.relative_exit_threshold,
            trim_weight=args.trim_weight,
        )
        book_path = reports_dir / f"event_{portfolio_kind}_target_book.csv"
        events_path = output_dir / f"{portfolio_kind}_events.csv"
        if not book.empty:
            book.to_csv(book_path, index=False)
        else:
            pd.DataFrame(columns=["rebalance_date", "ticker", "weight"]).to_csv(book_path, index=False)
        events.to_csv(events_path, index=False)
        summary["event_target_book_path"] = str(book_path)
        summary["events_path"] = str(events_path)
        summaries.append(summary)
        outputs[f"{portfolio_kind}_event_target_book"] = str(book_path)
        outputs[f"{portfolio_kind}_events"] = str(events_path)

    payload = {
        "schema_version": "event-target-books-v1",
        "generated_at_utc": now_utc(),
        "status": "completed" if all(row.get("status") == "completed" for row in summaries) else "partial",
        "latest_run": str(latest_run),
        "price_cache": str(price_cache),
        "books": summaries,
        "outputs": {
            **outputs,
            "summary_json": str(output_dir / "summary.json"),
            "report_md": str(output_dir / "report.md"),
        },
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload))
    print(json.dumps(payload, indent=2, default=str))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--main-target-book", default="")
    parser.add_argument("--concentrated-target-book", default="")
    parser.add_argument("--benchmark-ticker", default="SPY")
    parser.add_argument("--hard-stop", type=float, default=-0.08)
    parser.add_argument("--trailing-stop", type=float, default=-0.15)
    parser.add_argument("--trailing-activation", type=float, default=0.15)
    parser.add_argument("--relative-trim-threshold", type=float, default=-0.06)
    parser.add_argument("--relative-exit-threshold", type=float, default=-0.12)
    parser.add_argument("--trim-weight", type=float, default=0.50)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    return 0 if payload.get("status") in {"completed", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
