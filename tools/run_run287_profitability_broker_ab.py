#!/usr/bin/env python3
"""Default-off broker A/B for run287 profitability-inflection tilts.

This is a cheap research bridge after the run287 financial proxy screen. It
keeps the selected ticker set fixed, preserves stock gross and cash whenever
caps allow it, and measures each arm with broker-ledger replay. It does not
run a full rebuild, add a policy hook, or mutate production outputs.
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

SCHEMA_VERSION = "run287-profitability-broker-ab-v1"
DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/run287_profitability_broker_ab"
DEFAULT_SIGNAL = "profitability_inflection_score"
DEFAULT_SCORE_QUANTILE = 0.80
DEFAULT_REPLAY_END_DATE = "2026-07-06"
CASH_TICKERS = {"CASH", "__CASH__"}
ARMS: list[dict[str, Any]] = [
    {
        "arm": "baseline",
        "description": "unchanged official target book",
        "tilt_strength": 0.0,
        "score_quantile": DEFAULT_SCORE_QUANTILE,
    },
    {
        "arm": "profitability_top_quintile_tilt05",
        "description": "shift 5% of stock gross toward selected top-quintile profitability-inflection rows",
        "tilt_strength": 0.05,
        "score_quantile": DEFAULT_SCORE_QUANTILE,
    },
    {
        "arm": "profitability_top_quintile_tilt10",
        "description": "shift 10% of stock gross toward selected top-quintile profitability-inflection rows",
        "tilt_strength": 0.10,
        "score_quantile": DEFAULT_SCORE_QUANTILE,
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


def weight_value(row: pd.Series | dict[str, Any]) -> float:
    return safe_float(row.get("target_weight"), safe_float(row.get("weight")))


def is_cash_row(row: pd.Series | dict[str, Any]) -> bool:
    return clean_ticker(row.get("ticker")) in CASH_TICKERS


def row_cap(row: pd.Series | dict[str, Any], current_weight: float, default_cap: float) -> float:
    candidates = [current_weight, default_cap]
    for col in ("effective_single_weight_cap", "single_name_cap", "max_weight_cap"):
        value = safe_float(row.get(col), float("nan"))
        if math.isfinite(value) and value > 0:
            candidates.append(value)
    return max(candidates)


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
    candidates = [
        latest_run / "alphaops_vnext" / f"official_{portfolio_kind}_target_book.csv",
        latest_run / "reports" / f"operating_{portfolio_kind}_target_book.csv",
        latest_run / "market_leader_challenger" / f"{portfolio_kind}_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"no {portfolio_kind} target book found under {latest_run}")


def cap_waterfill(raw_weights: list[float], caps: list[float], target_gross: float) -> tuple[list[float], str, float]:
    weights = [max(0.0, min(weight, cap)) for weight, cap in zip(raw_weights, caps)]
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
            if capacity > 0:
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
            "selection_reason": "profitability_broker_ab_cash_residual",
        }
    )
    return [row]


def baseline_telemetry(date_text: str, stocks: pd.DataFrame, cash: pd.DataFrame, signal: str) -> dict[str, Any]:
    weights = [weight_value(row) for _, row in stocks.iterrows()]
    cash_weight = float(sum(weight_value(row) for _, row in cash.iterrows()))
    return {
        "rebalance_date": date_text,
        "status": "baseline",
        "signal": signal,
        "stock_count": int(len(stocks)),
        "valid_signal_count": int(pd.to_numeric(stocks.get(signal, pd.Series(dtype=float)), errors="coerce").notna().sum()),
        "eligible_count": 0,
        "stock_gross_before": float(sum(weights)),
        "stock_gross_after": float(sum(weights)),
        "cash_weight_before": cash_weight,
        "cash_weight_after": cash_weight,
        "requested_shift_weight": 0.0,
        "realized_shift_weight": 0.0,
        "total_abs_weight_delta": 0.0,
        "max_weight_after": float(max(weights)) if weights else 0.0,
        "gross_preservation_status": "baseline",
        "cash_residual_weight": 0.0,
        "score_threshold": None,
    }


def apply_profitability_tilt(
    stocks: pd.DataFrame,
    *,
    arm: dict[str, Any],
    signal: str,
    default_single_cap: float,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, float]:
    out = stocks.copy()
    if out.empty:
        return out, {"status": "no_stocks"}, pd.DataFrame(), 0.0
    weights = [weight_value(row) for _, row in out.iterrows()]
    scores = pd.to_numeric(out.get(signal, pd.Series(index=out.index, dtype=float)), errors="coerce")
    valid = scores.notna()
    stock_gross = float(sum(max(0.0, weight) for weight in weights))
    if valid.sum() < 2 or stock_gross <= 1e-12:
        return out, {"status": "blocked_insufficient_signal", "valid_signal_count": int(valid.sum())}, pd.DataFrame(), 0.0

    threshold = float(scores.loc[valid].quantile(float(arm["score_quantile"])))
    eligible = valid & scores.ge(threshold)
    donor = ~eligible
    eligible_positions = [idx for idx, flag in enumerate(eligible.tolist()) if flag]
    donor_positions = [idx for idx, flag in enumerate(donor.tolist()) if flag and weights[idx] > 0]
    if not eligible_positions or not donor_positions:
        return (
            out,
            {
                "status": "blocked_no_donor_or_eligible",
                "valid_signal_count": int(valid.sum()),
                "eligible_count": int(len(eligible_positions)),
            },
            pd.DataFrame(),
            0.0,
        )

    donor_gross = float(sum(weights[idx] for idx in donor_positions))
    requested_shift = min(stock_gross * float(arm["tilt_strength"]), donor_gross)
    raw = list(weights)
    for idx in donor_positions:
        raw[idx] -= requested_shift * (weights[idx] / donor_gross)

    eligible_scores = [safe_float(scores.iloc[idx]) for idx in eligible_positions]
    min_score = min(eligible_scores)
    allocation_scores = [max(score - min_score, 0.0) + 1e-9 for score in eligible_scores]
    allocation_sum = sum(allocation_scores)
    for idx, allocation_score in zip(eligible_positions, allocation_scores):
        raw[idx] += requested_shift * (allocation_score / allocation_sum)

    caps = [row_cap(row, current_weight=weights[pos], default_cap=default_single_cap) for pos, (_, row) in enumerate(out.iterrows())]
    new_weights, gross_status, residual = cap_waterfill(raw, caps, stock_gross)
    stock_rows: list[dict[str, Any]] = []
    for pos, (idx, row) in enumerate(out.iterrows()):
        old_weight = weights[pos]
        new_weight = new_weights[pos]
        out.at[idx, "weight"] = new_weight
        out.at[idx, "target_weight"] = new_weight
        out.at[idx, "profitability_broker_ab_arm"] = arm["arm"]
        out.at[idx, "profitability_broker_ab_signal"] = signal
        out.at[idx, "profitability_broker_ab_score_threshold"] = threshold
        out.at[idx, "profitability_broker_ab_eligible"] = bool(eligible.iloc[pos])
        out.at[idx, "profitability_broker_ab_pre_weight"] = old_weight
        out.at[idx, "profitability_broker_ab_post_weight"] = new_weight
        out.at[idx, "profitability_broker_ab_delta"] = new_weight - old_weight
        stock_rows.append(
            {
                "ticker": clean_ticker(row.get("ticker")),
                "score": safe_float(scores.iloc[pos], float("nan")),
                "eligible": bool(eligible.iloc[pos]),
                "pre_weight": old_weight,
                "post_weight": new_weight,
                "delta_weight": new_weight - old_weight,
            }
        )

    realized_shift = 0.5 * float(sum(abs(new - old) for new, old in zip(new_weights, weights)))
    meta = {
        "status": gross_status,
        "valid_signal_count": int(valid.sum()),
        "eligible_count": int(len(eligible_positions)),
        "score_threshold": threshold,
        "stock_gross_before": stock_gross,
        "stock_gross_after": float(sum(new_weights)),
        "requested_shift_weight": float(requested_shift),
        "realized_shift_weight": float(realized_shift),
        "total_abs_weight_delta": float(sum(abs(new - old) for new, old in zip(new_weights, weights))),
        "max_weight_after": float(max(new_weights)) if new_weights else 0.0,
        "cash_residual_weight": float(residual),
    }
    return out, meta, pd.DataFrame(stock_rows), float(residual)


def generate_arm_book(
    book: pd.DataFrame,
    arm: dict[str, Any],
    *,
    signal: str,
    default_single_cap: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if signal not in book.columns:
        raise ValueError(f"target book missing signal column: {signal}")
    out_groups: list[pd.DataFrame] = []
    date_rows: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []
    for date_text, group in book.groupby("rebalance_date", sort=True):
        cash_mask = group.apply(is_cash_row, axis=1)
        stocks = group.loc[~cash_mask].copy()
        cash = group.loc[cash_mask].copy()
        if arm["arm"] == "baseline":
            date_rows.append({"arm": arm["arm"], **baseline_telemetry(str(date_text), stocks, cash, signal)})
            out_groups.append(group.copy())
            continue

        tilted, meta, stock_telemetry, residual = apply_profitability_tilt(
            stocks,
            arm=arm,
            signal=signal,
            default_single_cap=default_single_cap,
        )
        cash_rows = add_cash_residual(cash.to_dict("records"), residual, group.iloc[0].to_dict(), str(date_text))
        cash_after = pd.DataFrame(cash_rows, columns=group.columns if cash_rows else group.columns)
        out_group = tilted.copy() if cash_after.empty else pd.concat([cash_after, tilted], ignore_index=True)
        out_groups.append(out_group)
        cash_before_weight = float(sum(weight_value(row) for _, row in cash.iterrows()))
        cash_after_weight = float(sum(weight_value(row) for _, row in cash_after.iterrows()))
        date_rows.append(
            {
                "arm": arm["arm"],
                "rebalance_date": str(date_text),
                "signal": signal,
                "stock_count": int(len(stocks)),
                "cash_weight_before": cash_before_weight,
                "cash_weight_after": cash_after_weight,
                "gross_preservation_status": meta.get("status", "unknown"),
                **meta,
            }
        )
        if not stock_telemetry.empty:
            stock_telemetry.insert(0, "rebalance_date", str(date_text))
            stock_telemetry.insert(0, "arm", arm["arm"])
            stock_rows.extend(stock_telemetry.to_dict("records"))
    non_empty_groups = [group for group in out_groups if not group.empty]
    out_book = pd.concat(non_empty_groups, ignore_index=True) if non_empty_groups else pd.DataFrame(columns=book.columns)
    return out_book, pd.DataFrame(date_rows), pd.DataFrame(stock_rows)


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
        "--cash-carry-mode",
        str(cash_carry_mode),
        "--cash-rate-source",
        str(cash_rate_source),
        "--cash-rate-lag-days",
        str(cash_rate_lag_days),
        "--cash-carry-haircut-bps",
        str(cash_carry_haircut_bps),
        "--cash-carry-day-count",
        str(cash_carry_day_count),
    ]
    if cash_rate_path:
        cmd.extend(["--cash-rate-path", str(cash_rate_path)])
    if replay_end_date:
        cmd.extend(["--replay-end-date", str(replay_end_date)])
    if official_baseline_end_date:
        cmd.extend(["--official-baseline-end-date", str(official_baseline_end_date)])
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


def arm_metric_row(
    arm: dict[str, Any],
    metrics: dict[str, Any],
    date_telemetry: pd.DataFrame,
    target_book_path: Path,
) -> dict[str, Any]:
    total_abs_delta = (
        float(pd.to_numeric(date_telemetry.get("total_abs_weight_delta", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not date_telemetry.empty
        else 0.0
    )
    eligible_events = (
        int(pd.to_numeric(date_telemetry.get("eligible_count", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
        if not date_telemetry.empty
        else 0
    )
    cash_abs_delta = 0.0
    if not date_telemetry.empty and {"cash_weight_before", "cash_weight_after"}.issubset(date_telemetry.columns):
        cash_abs_delta = float(
            (
                pd.to_numeric(date_telemetry["cash_weight_after"], errors="coerce").fillna(0.0)
                - pd.to_numeric(date_telemetry["cash_weight_before"], errors="coerce").fillna(0.0)
            )
            .abs()
            .sum()
        )
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
        "cash_interest_accrued_usd": metrics.get("cash_interest_accrued_usd"),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "eligible_events": eligible_events,
        "total_abs_weight_delta": total_abs_delta,
        "cash_abs_delta_sum": cash_abs_delta,
        "cap_infeasible_date_count": int(
            date_telemetry.get("gross_preservation_status", pd.Series(dtype=str)).astype(str).eq("cap_infeasible_cash_residual").sum()
        )
        if not date_telemetry.empty
        else 0,
        "max_weight_after": float(pd.to_numeric(date_telemetry.get("max_weight_after", pd.Series(dtype=float)), errors="coerce").fillna(0.0).max())
        if not date_telemetry.empty
        else 0.0,
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
        row["delta_trade_count"] = int(safe_float(row.get("trade_count")) - safe_float(baseline.get("trade_count")))
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
    if row.get("metric_mode") != "broker_ledger_next_close_cash_carry":
        return "blocked_invalid_metric_mode"
    if abs(safe_float(row.get("years")) - safe_float(baseline.get("years"))) > 0.03:
        return "blocked_window_mismatch"
    if safe_float(row.get("eligible_events")) <= 0 or safe_float(row.get("total_abs_weight_delta")) <= 1e-10:
        return "blocked_no_signal"
    if safe_float(row.get("cash_abs_delta_sum")) > 0.01:
        return "reject_cash_changed"
    if safe_float(row.get("cap_infeasible_date_count")) > 0:
        return "reject_cap_infeasible"
    if safe_float(row.get("delta_max_dd_pp")) < -0.25:
        return "reject_mdd_worse"
    oos_delta = row.get("delta_windows.oos.cagr_pp")
    if oos_delta is not None and safe_float(oos_delta) < -0.25:
        return "reject_oos_cagr_worse"
    if safe_float(row.get("delta_cagr_pp")) >= 0.50:
        return "broker_ab_positive_requires_review"
    if safe_float(row.get("delta_cagr_pp")) > 0.0:
        return "broker_ab_edge_too_small"
    return "reject_no_cagr_edge"


def render_report(payload: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Run287 Profitability Broker A/B",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        f"- Portfolio: `{payload['portfolio_kind']}`",
        f"- Signal: `{payload['signal']}`",
        f"- Target book: `{payload['target_book']}`",
        f"- Price cache: `{payload['price_cache']}`",
        f"- Replay end date: `{payload['replay_end_date']}`",
        f"- Metric mode: `{payload['cash_carry_mode']}` / broker-ledger cash-carry",
        "- Selected ticker set preserved; cash target is unchanged unless cap infeasible.",
        "- This is default-off research evidence only. No fullrun, hook, production promotion, or live trading.",
        "",
        "| arm | verdict | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | eligible events | abs weight delta | cash d pp |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {arm} | `{verdict}` | {cagr:.2%} | {mdd:.2%} | {sharpe:.3f} | {dc:+.2f} | {dm:+.2f} | {eligible} | {delta:.3f} | {cash:+.3f} |".format(
                arm=row.get("arm"),
                verdict=row.get("ab_verdict"),
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                sharpe=safe_float(row.get("sharpe")),
                dc=safe_float(row.get("delta_cagr_pp")),
                dm=safe_float(row.get("delta_max_dd_pp")),
                eligible=int(safe_float(row.get("eligible_events"))),
                delta=safe_float(row.get("total_abs_weight_delta")),
                cash=safe_float(row.get("delta_avg_cash_weight_pp")),
            )
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- `period_forward_return` is not used by this tool.",
            "- `candidate_allowed=false` even when an arm is positive; a positive result only permits review of default-off broker A/B evidence.",
            "- Production remains blocked while `pit_universe_label_clean=false`.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir) / args.portfolio_kind
    target_book = resolve_target_book(latest_run, args.portfolio_kind, args.target_book)
    price_cache = repo_path(args.price_cache)
    book = pd.read_csv(target_book, low_memory=False)
    if "rebalance_date" not in book.columns or "ticker" not in book.columns:
        raise ValueError("target book must include rebalance_date and ticker")
    if args.signal not in book.columns:
        raise ValueError(f"target book must include {args.signal}")
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)

    rows: list[dict[str, Any]] = []
    for arm in ARMS:
        arm_dir = output_dir / arm["arm"]
        arm_book, date_telemetry, stock_telemetry = generate_arm_book(
            book,
            arm,
            signal=args.signal,
            default_single_cap=float(args.single_cap),
        )
        arm_book_path = arm_dir / "target_book.csv"
        write_csv(arm_book_path, arm_book)
        write_csv(arm_dir / "date_telemetry.csv", date_telemetry)
        write_csv(arm_dir / "stock_telemetry.csv", stock_telemetry)
        metrics = run_broker_replay(
            target_book=arm_book_path,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            portfolio_kind=args.portfolio_kind,
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            starting_capital=float(args.starting_capital),
            cash_carry_mode=str(args.cash_carry_mode),
            cash_rate_path=str(repo_path(args.cash_rate_path)) if args.cash_rate_path else "",
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
        row["target_35_50_25_restored"] = (
            safe_float(row.get("cagr")) >= (0.35 if args.portfolio_kind == "main" else 0.50)
            and safe_float(row.get("max_dd")) >= -0.25
        )
    positive_rows = [row for row in rows if row.get("ab_verdict") == "broker_ab_positive_requires_review"]
    decision_label = "positive_broker_ab_requires_review" if positive_rows else "no_positive_broker_ab_candidate"
    table = pd.DataFrame(rows)
    write_csv(output_dir / "arm_metrics.csv", table)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_label": decision_label,
        "portfolio_kind": args.portfolio_kind,
        "latest_run": str(latest_run),
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "signal": args.signal,
        "score_quantile": DEFAULT_SCORE_QUANTILE,
        "cash_carry_mode": str(args.cash_carry_mode),
        "cash_rate_path": str(repo_path(args.cash_rate_path)) if args.cash_rate_path else "",
        "cash_rate_source": str(args.cash_rate_source),
        "cash_rate_lag_days": int(args.cash_rate_lag_days),
        "cash_carry_haircut_bps": float(args.cash_carry_haircut_bps),
        "cash_carry_day_count": int(args.cash_carry_day_count),
        "replay_end_date": str(args.replay_end_date),
        "official_baseline_end_date": str(args.official_baseline_end_date),
        "arms": rows,
        "positive_arms": positive_rows,
        "candidate_allowed": False,
        "next_action_allowed": "review_default_off_broker_ab_only" if positive_rows else "do_not_design_hook_from_this_ab",
        "research_only": True,
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "used_forward_return_in_ranking": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(payload, rows))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--target-book", default="")
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="concentrated")
    parser.add_argument("--price-cache", default="outputs/run287_price_cache_latest/cache_prices")
    parser.add_argument("--signal", default=DEFAULT_SIGNAL)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--single-cap", type=float, default=0.30)
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default="risk_free_rate")
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--replay-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--official-baseline-end-date", default=DEFAULT_REPLAY_END_DATE)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
