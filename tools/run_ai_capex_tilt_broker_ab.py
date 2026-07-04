#!/usr/bin/env python3
"""Broker-ledger A/B for AI Capex target-book tilt candidates.

This is a cheap, research-only bridge between the AI Capex screen and any
future policy hook. It reuses existing target books, preserves the selected
ticker set, keeps cash unchanged when caps are feasible, and measures the
result through `run_broker_ledger_replay.py`.

It does not run a full policy replay and does not mutate production outputs.
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

from tools.run_ai_capex_bottleneck_screen import prepare, read_table  # noqa: E402

SCHEMA_VERSION = "ai-capex-tilt-broker-ab-v1"
DEFAULT_OUTPUT_DIR = "outputs/ai_capex_tilt_broker_ab"
CASH_TICKERS = {"CASH", "__CASH__"}

ARMS: list[dict[str, Any]] = [
    {
        "arm": "baseline",
        "description": "unchanged target book",
        "tilt_strength": 0.0,
        "requires_ai": False,
        "requires_bottleneck": False,
        "requires_momentum": False,
        "requires_earnings": False,
    },
    {
        "arm": "ai_bottleneck_momentum_tilt15",
        "description": "tilt existing selected weights toward AI bottleneck + momentum rows",
        "tilt_strength": 0.15,
        "requires_ai": True,
        "requires_bottleneck": True,
        "requires_momentum": True,
        "requires_earnings": False,
    },
    {
        "arm": "ai_bottleneck_momentum_earnings_tilt15",
        "description": "same tilt, but only rows with earnings confirmation",
        "tilt_strength": 0.15,
        "requires_ai": True,
        "requires_bottleneck": True,
        "requires_momentum": True,
        "requires_earnings": True,
    },
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
    return str(value or "").strip().upper()


def is_cash_row(row: pd.Series | dict[str, Any]) -> bool:
    return clean_ticker(row.get("ticker")) in CASH_TICKERS


def weight_value(row: pd.Series | dict[str, Any]) -> float:
    return safe_float(row.get("target_weight"), safe_float(row.get("weight")))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def resolve_target_book(latest_run: Path, portfolio_kind: str, explicit: str | None = None) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"target book not found: {path}")
        return path
    name = f"official_{portfolio_kind}_target_book.csv"
    candidates = [
        latest_run / "alphaops_vnext" / name,
        latest_run / "reports" / f"operating_{portfolio_kind}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio_kind}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"no {portfolio_kind} target book found under latest-run")


def resolve_price_cache(latest_run: Path, price_cache: str) -> Path:
    path = repo_path(price_cache)
    if path.exists():
        return path
    fallback = latest_run.parent / "cache_prices"
    if fallback.exists():
        return fallback
    return path


def row_cap(row: pd.Series | dict[str, Any], default_cap: float) -> float:
    for col in ("effective_single_weight_cap", "single_name_cap", "max_weight_cap"):
        value = safe_float(row.get(col), float("nan"))
        if math.isfinite(value) and value > 0:
            return value
    return default_cap


def arm_mask(stocks: pd.DataFrame, arm: dict[str, Any]) -> pd.Series:
    if arm["arm"] == "baseline":
        return pd.Series(False, index=stocks.index)
    mask = pd.Series(True, index=stocks.index)
    if arm.get("requires_ai"):
        mask &= stocks["is_ai_capex_bucket"].astype(bool)
    if arm.get("requires_bottleneck"):
        mask &= stocks["ai_bottleneck_high"].astype(bool)
    if arm.get("requires_momentum"):
        mask &= stocks["momentum_high"].astype(bool)
    if arm.get("requires_earnings"):
        mask &= stocks["earnings_confirmation_positive"].astype(bool)
    return mask


def cap_waterfill(raw_weights: list[float], caps: list[float], target_gross: float) -> tuple[list[float], str, float]:
    weights = [max(0.0, min(w, cap)) for w, cap in zip(raw_weights, caps)]
    residual = max(0.0, target_gross - sum(weights))
    status = "gross_preserved"
    for _ in range(100):
        if residual <= 1e-12:
            break
        room = [max(0.0, cap - weight) for weight, cap in zip(weights, caps)]
        total_room = sum(room)
        if total_room <= 1e-12:
            status = "cap_infeasible_cash_residual"
            break
        add_total = min(residual, total_room)
        for idx, capacity in enumerate(room):
            if capacity <= 0:
                continue
            weights[idx] += add_total * (capacity / total_room)
        residual = max(0.0, target_gross - sum(weights))
    return weights, status, residual


def add_cash_residual(cash_rows: list[dict[str, Any]], residual: float, template: dict[str, Any], date_text: str) -> list[dict[str, Any]]:
    if residual <= 1e-12:
        return cash_rows
    out = [dict(row) for row in cash_rows]
    if out:
        old = weight_value(out[0])
        out[0]["weight"] = old + residual
        out[0]["target_weight"] = old + residual
        return out
    row = {key: "" for key in template.keys()}
    row.update(
        {
            "rebalance_date": date_text,
            "ticker": "CASH",
            "Name": "Cash",
            "sector": "Cash",
            "weight": residual,
            "target_weight": residual,
            "selection_reason": "ai_capex_tilt_cash_residual",
        }
    )
    return [row]


def generate_arm_book(
    book: pd.DataFrame,
    arm: dict[str, Any],
    *,
    default_single_cap: float,
    earnings_signals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    prepared, signal_meta = prepare(book, earnings_signals)
    out_groups: list[pd.DataFrame] = []
    date_rows: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []

    for date_text, group in prepared.groupby("rebalance_date", sort=True):
        cash_mask = group.apply(is_cash_row, axis=1)
        stocks = group.loc[~cash_mask].copy()
        cash = group.loc[cash_mask].copy()
        before_weights = [weight_value(row) for _, row in stocks.iterrows()]
        stock_gross = float(sum(max(0.0, w) for w in before_weights))
        cash_weight_before = float(sum(max(0.0, weight_value(row)) for _, row in cash.iterrows()))
        if arm["arm"] == "baseline" or stocks.empty or stock_gross <= 0:
            after_weights = before_weights
            eligible = pd.Series(False, index=stocks.index)
            status = "baseline" if arm["arm"] == "baseline" else "no_stock_gross"
            residual = 0.0
        else:
            eligible = arm_mask(stocks, arm)
            if int(eligible.sum()) == 0:
                after_weights = before_weights
                status = "no_eligible_rows"
                residual = 0.0
            else:
                multipliers = [1.0 + float(arm["tilt_strength"]) if bool(flag) else 1.0 for flag in eligible.tolist()]
                raw = [w * m for w, m in zip(before_weights, multipliers)]
                raw_sum = sum(raw)
                raw = [w * stock_gross / raw_sum for w in raw] if raw_sum > 0 else before_weights
                caps = [row_cap(row, default_single_cap) for _, row in stocks.iterrows()]
                after_weights, status, residual = cap_waterfill(raw, caps, stock_gross)

        out_stock = stocks.copy()
        out_stock["pre_ai_capex_tilt_weight"] = before_weights
        out_stock["ai_capex_tilt_weight"] = after_weights
        out_stock["ai_capex_tilt_delta"] = [a - b for a, b in zip(after_weights, before_weights)]
        out_stock["ai_capex_tilt_eligible"] = eligible.astype(bool).tolist()
        out_stock["ai_capex_tilt_arm"] = arm["arm"]
        for col in ("weight", "target_weight"):
            if col in out_stock.columns:
                out_stock[col] = after_weights
        cash_records = add_cash_residual(cash.to_dict(orient="records"), residual, group.iloc[0].to_dict(), str(date_text))
        after_cash = float(sum(max(0.0, weight_value(row)) for row in cash_records))

        date_rows.append(
            {
                "arm": arm["arm"],
                "rebalance_date": date_text,
                "eligible_count": int(eligible.sum()),
                "stock_count": int(len(stocks)),
                "stock_gross_before": stock_gross,
                "stock_gross_after": float(sum(after_weights)),
                "cash_weight_before": cash_weight_before,
                "cash_weight_after": after_cash,
                "total_abs_weight_delta": float(sum(abs(a - b) for a, b in zip(after_weights, before_weights))),
                "max_weight_before": float(max(before_weights)) if before_weights else 0.0,
                "max_weight_after": float(max(after_weights)) if after_weights else 0.0,
                "cap_breach_count": int(sum(1 for _, row in out_stock.iterrows() if weight_value(row) > row_cap(row, default_single_cap) + 1e-10)),
                "cash_residual_weight": residual,
                "gross_preservation_status": status,
            }
        )
        for _, row in out_stock.iterrows():
            stock_rows.append(
                {
                    "arm": arm["arm"],
                    "rebalance_date": date_text,
                    "ticker": clean_ticker(row.get("ticker")),
                    "pre_ai_capex_tilt_weight": safe_float(row.get("pre_ai_capex_tilt_weight")),
                    "ai_capex_tilt_weight": safe_float(row.get("ai_capex_tilt_weight")),
                    "ai_capex_tilt_delta": safe_float(row.get("ai_capex_tilt_delta")),
                    "ai_capex_tilt_eligible": bool(row.get("ai_capex_tilt_eligible")),
                    "screen_group": row.get("screen_group", ""),
                    "earnings_confirmation_source": row.get("earnings_confirmation_source", ""),
                }
            )
        out_groups.append(pd.concat([out_stock, pd.DataFrame(cash_records)], ignore_index=True))

    return (
        pd.concat(out_groups, ignore_index=True) if out_groups else book.copy(),
        pd.DataFrame(date_rows),
        pd.DataFrame(stock_rows),
        signal_meta,
    )


def run_broker_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    cost_bps: float,
    max_fill_lag_days: int,
    starting_capital: float,
    cash_carry_mode: str,
    cash_rate_path: str,
    cash_rate_source: str,
    cash_rate_lag_days: int,
    cash_carry_haircut_bps: float,
    cash_carry_day_count: int,
    replay_end_date: str,
    official_baseline_end_date: str,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_broker_ledger_replay.py"),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--portfolio-kind",
        portfolio_kind,
        "--output-dir",
        str(output_dir),
        "--fill-mode",
        "next_close",
        "--cost-bps",
        str(cost_bps),
        "--max-fill-lag-days",
        str(max_fill_lag_days),
        "--starting-capital",
        str(starting_capital),
    ]
    if cash_carry_mode:
        cmd.extend(["--cash-carry-mode", cash_carry_mode])
    if cash_rate_path:
        cmd.extend(["--cash-rate-path", str(repo_path(cash_rate_path))])
    if cash_rate_source:
        cmd.extend(["--cash-rate-source", cash_rate_source])
    if cash_rate_lag_days is not None:
        cmd.extend(["--cash-rate-lag-days", str(cash_rate_lag_days)])
    if cash_carry_haircut_bps is not None:
        cmd.extend(["--cash-carry-haircut-bps", str(cash_carry_haircut_bps)])
    if cash_carry_day_count is not None:
        cmd.extend(["--cash-carry-day-count", str(cash_carry_day_count)])
    if replay_end_date:
        cmd.extend(["--replay-end-date", replay_end_date])
    if official_baseline_end_date:
        cmd.extend(["--official-baseline-end-date", official_baseline_end_date])
    if portfolio_kind == "concentrated":
        cmd.append("--disable-concentrated-champion-filter")
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    metrics_path = output_dir / "metrics.json"
    if not metrics_path.exists():
        return {"status": "missing_metrics", "broker_metrics_path": str(metrics_path)}
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["broker_metrics_path"] = str(metrics_path)
    return payload


def window_metric(metrics: dict[str, Any], window: str, key: str) -> float | None:
    block = (metrics.get("windows") or {}).get(window)
    if not isinstance(block, dict) or key not in block:
        return None
    return safe_float(block.get(key), float("nan"))


def arm_metric_row(arm: dict[str, Any], metrics: dict[str, Any], date_telemetry: pd.DataFrame, target_book_path: Path) -> dict[str, Any]:
    total_abs_delta = float(pd.to_numeric(date_telemetry.get("total_abs_weight_delta", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not date_telemetry.empty else 0.0
    eligible_events = int(pd.to_numeric(date_telemetry.get("eligible_count", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not date_telemetry.empty else 0
    cash_delta = float(
        (
            pd.to_numeric(date_telemetry.get("cash_weight_after", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
            - pd.to_numeric(date_telemetry.get("cash_weight_before", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        ).abs().sum()
    ) if not date_telemetry.empty else 0.0
    row = {
        "arm": arm["arm"],
        "description": arm.get("description", ""),
        "status": metrics.get("status", "unknown"),
        "metric_mode": metrics.get("metric_mode", ""),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "years": safe_float(metrics.get("years")),
        "start_date": metrics.get("start_date", ""),
        "end_date": metrics.get("end_date", ""),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "eligible_events": eligible_events,
        "total_abs_weight_delta": total_abs_delta,
        "cash_abs_delta_sum": cash_delta,
        "cap_breach_count": int(pd.to_numeric(date_telemetry.get("cap_breach_count", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not date_telemetry.empty else 0,
        "max_weight_after": float(pd.to_numeric(date_telemetry.get("max_weight_after", pd.Series(dtype=float)), errors="coerce").fillna(0.0).max()) if not date_telemetry.empty else 0.0,
        "target_book_path": str(target_book_path),
        "broker_metrics_path": str(metrics.get("broker_metrics_path", "")),
    }
    for window in ("is", "oos", "oos2"):
        for key in ("cagr", "max_dd"):
            row[f"windows.{window}.{key}"] = window_metric(metrics, window, key)
    return row


def add_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((row for row in rows if row["arm"] == "baseline"), None)
    if not baseline:
        return rows
    for row in rows:
        row["delta_cagr_pp"] = (safe_float(row.get("cagr")) - safe_float(baseline.get("cagr"))) * 100.0
        row["delta_max_dd_pp"] = (safe_float(row.get("max_dd")) - safe_float(baseline.get("max_dd"))) * 100.0
        row["delta_sharpe"] = safe_float(row.get("sharpe")) - safe_float(baseline.get("sharpe"))
        row["delta_avg_cash_weight_pp"] = (safe_float(row.get("avg_cash_weight")) - safe_float(baseline.get("avg_cash_weight"))) * 100.0
        for window in ("is", "oos", "oos2"):
            for key in ("cagr", "max_dd"):
                base_key = f"windows.{window}.{key}"
                row[f"delta_{base_key}_pp"] = (
                    (safe_float(row.get(base_key)) - safe_float(baseline.get(base_key))) * 100.0
                    if row.get(base_key) is not None and baseline.get(base_key) is not None
                    else None
                )
    return rows


def classify(row: dict[str, Any], baseline: dict[str, Any]) -> str:
    if row["arm"] == "baseline":
        return "baseline"
    if row.get("metric_mode") not in {"broker_ledger_next_close", "broker_ledger_next_close_cash_carry"}:
        return "blocked_invalid_metric_mode"
    if abs(safe_float(row.get("years")) - safe_float(baseline.get("years"))) > 0.03:
        return "blocked_window_mismatch"
    if safe_float(row.get("eligible_events")) <= 0 or safe_float(row.get("total_abs_weight_delta")) <= 1e-10:
        return "blocked_no_signal"
    if safe_float(row.get("cap_breach_count")) > 0:
        return "blocked_cap_breach"
    if safe_float(row.get("cash_abs_delta_sum")) > 0.05:
        return "reject_cash_changed"
    if safe_float(row.get("delta_max_dd_pp")) < -0.25:
        return "reject_mdd_worse"
    oos_delta = row.get("delta_windows.oos.cagr_pp")
    if oos_delta is not None and safe_float(oos_delta) < -0.25:
        return "reject_oos_cagr_worse"
    if safe_float(row.get("delta_cagr_pp")) >= 0.50:
        return "research_pass_policy_candidate"
    if safe_float(row.get("delta_cagr_pp")) > 0.0:
        return "research_edge_too_small"
    return "reject_no_cagr_edge"


def render_report(rows: list[dict[str, Any]], *, target_book: Path, price_cache: Path, portfolio_kind: str) -> str:
    metric_modes = sorted({str(row.get("metric_mode", "")) for row in rows if row.get("metric_mode")})
    metric_source = ", ".join(metric_modes) if metric_modes else "unknown"
    lines = [
        "# AI Capex Tilt Broker A/B",
        "",
        f"- portfolio: `{portfolio_kind}`",
        f"- target book: `{target_book}`",
        f"- price cache: `{price_cache}`",
        f"- metric source: `{metric_source}`",
        "- selected tickers preserved; cash is intended to remain unchanged",
        "- production promotion: blocked unless PIT universe evidence is clean",
        "",
        "| arm | verdict | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | eligible events | abs weight delta |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {arm} | `{verdict}` | {cagr:.2%} | {mdd:.2%} | {sharpe:.3f} | {dc:+.2f} | {dm:+.2f} | {eligible} | {delta:.3f} |".format(
                arm=row.get("arm"),
                verdict=row.get("ab_verdict"),
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                sharpe=safe_float(row.get("sharpe")),
                dc=safe_float(row.get("delta_cagr_pp")),
                dm=safe_float(row.get("delta_max_dd_pp")),
                eligible=int(safe_float(row.get("eligible_events"))),
                delta=safe_float(row.get("total_abs_weight_delta")),
            )
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    target_book = resolve_target_book(latest_run, args.portfolio_kind, args.target_book)
    price_cache = resolve_price_cache(latest_run, args.price_cache)
    earnings_signals = read_table(repo_path(args.earnings_signals)) if args.earnings_signals else pd.DataFrame()
    book = pd.read_csv(target_book, low_memory=False)
    if "rebalance_date" not in book.columns or "ticker" not in book.columns:
        raise ValueError("target book must include rebalance_date and ticker")
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)

    rows: list[dict[str, Any]] = []
    signal_meta: dict[str, Any] = {}
    for arm in ARMS:
        arm_dir = output_dir / args.portfolio_kind / arm["arm"]
        arm_book, date_telemetry, stock_telemetry, signal_meta = generate_arm_book(
            book,
            arm,
            default_single_cap=float(args.single_cap),
            earnings_signals=earnings_signals,
        )
        arm_book_path = arm_dir / "target_book.csv"
        write_csv(arm_book_path, arm_book)
        write_csv(arm_dir / "tilt_date_telemetry.csv", date_telemetry)
        write_csv(arm_dir / "tilt_stock_telemetry.csv", stock_telemetry)
        metrics = run_broker_replay(
            target_book=arm_book_path,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            portfolio_kind=args.portfolio_kind,
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            starting_capital=float(args.starting_capital),
            cash_carry_mode=str(args.cash_carry_mode),
            cash_rate_path=str(args.cash_rate_path),
            cash_rate_source=str(args.cash_rate_source),
            cash_rate_lag_days=int(args.cash_rate_lag_days),
            cash_carry_haircut_bps=float(args.cash_carry_haircut_bps),
            cash_carry_day_count=int(args.cash_carry_day_count),
            replay_end_date=str(args.replay_end_date),
            official_baseline_end_date=str(args.official_baseline_end_date),
        )
        rows.append(arm_metric_row(arm, metrics, date_telemetry, arm_book_path))

    rows = add_deltas(rows)
    baseline = next(row for row in rows if row["arm"] == "baseline")
    for row in rows:
        row["ab_verdict"] = classify(row, baseline)
    table = pd.DataFrame(rows)
    portfolio_out = output_dir / args.portfolio_kind
    write_csv(portfolio_out / "arm_metrics.csv", table)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "portfolio_kind": args.portfolio_kind,
        "latest_run": str(latest_run),
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "earnings_signal_path": str(repo_path(args.earnings_signals)) if args.earnings_signals else None,
        "cash_carry_mode": str(args.cash_carry_mode),
        "cash_rate_path": str(repo_path(args.cash_rate_path)) if args.cash_rate_path else "",
        "cash_rate_source": str(args.cash_rate_source),
        "cash_rate_lag_days": int(args.cash_rate_lag_days),
        "cash_carry_haircut_bps": float(args.cash_carry_haircut_bps),
        "cash_carry_day_count": int(args.cash_carry_day_count),
        "replay_end_date": str(args.replay_end_date),
        "official_baseline_end_date": str(args.official_baseline_end_date),
        **signal_meta,
        "arms": rows,
        "policy_candidates": [row for row in rows if row.get("ab_verdict") == "research_pass_policy_candidate"],
        "production_promotion_allowed": False,
        "production_promotion_blocker": "pit_universe_label_clean_required",
    }
    write_json(portfolio_out / "summary.json", payload)
    write_text(portfolio_out / "report.md", render_report(rows, target_book=target_book, price_cache=price_cache, portfolio_kind=args.portfolio_kind))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="concentrated")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--earnings-signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--single-cap", type=float, default=0.30)
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default="none")
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--official-baseline-end-date", default="")
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
