#!/usr/bin/env python3
"""Audit whether run287 Main drawdown has ex-ante exit-timing latency.

This is a measurement-only diagnostic. It does not dispatch a workflow, replay
trades, mutate target books, tune thresholds, or select a new alpha rule. It
checks whether the generated Main book had decision-time exit/reduction signals
before or during the max drawdown while broker holdings stayed exposed long
enough for latency to be a plausible MDD lever.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ZERO_WEIGHT_EPS = 1e-6
ACTUAL_WEIGHT_EPS = 0.001
REDUCTION_EPS = 0.02
ALIGNMENT_SLACK = 0.005
DEFAULT_LOOKBACK_DAYS = 63
DEFAULT_TOP_N = 12


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def load_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"required input not found: {path}")
    frame = pd.read_csv(path)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")
    return frame


def normalize_date_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    out = frame.copy()
    out[column] = pd.to_datetime(out[column], errors="coerce")
    return out.dropna(subset=[column]).sort_values(column).reset_index(drop=True)


def max_drawdown_window(equity: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(equity["equity_usd"], errors="coerce").astype(float)
    running_peak = values.cummax()
    drawdown = values / running_peak - 1.0
    trough_idx = int(drawdown.idxmin())
    peak_idx = int(values.loc[:trough_idx].idxmax())
    return {
        "peak_date": pd.Timestamp(equity.loc[peak_idx, "date"]),
        "trough_date": pd.Timestamp(equity.loc[trough_idx, "date"]),
        "peak_equity_usd": safe_float(equity.loc[peak_idx, "equity_usd"]),
        "trough_equity_usd": safe_float(equity.loc[trough_idx, "equity_usd"]),
        "max_dd": safe_float(drawdown.loc[trough_idx]),
        "peak_index": peak_idx,
        "trough_index": trough_idx,
    }


def add_mtm_pnl(holdings: pd.DataFrame) -> pd.DataFrame:
    d = holdings.copy()
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["ticker"] = d["ticker"].astype(str).str.upper()
    for col in ["shares", "price", "market_value_usd", "weight"]:
        d[col] = pd.to_numeric(d[col], errors="coerce").fillna(0.0)
    d = d.dropna(subset=["date"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    d["prev_date"] = d.groupby("ticker")["date"].shift(1)
    d["prev_shares"] = d.groupby("ticker")["shares"].shift(1).fillna(0.0)
    d["prev_price"] = d.groupby("ticker")["price"].shift(1)
    gap_days = (d["date"] - d["prev_date"]).dt.days.fillna(9999)
    d.loc[gap_days > 7, "prev_shares"] = 0.0
    d["mtm_pnl_usd"] = d["prev_shares"] * (d["price"] - d["prev_price"].fillna(d["price"]))
    d.loc[d["prev_shares"].abs() <= 1e-12, "mtm_pnl_usd"] = 0.0
    return d


def drawdown_contributors(holdings: pd.DataFrame, window: dict[str, Any], top_n: int) -> pd.DataFrame:
    start = pd.Timestamp(window["peak_date"])
    end = pd.Timestamp(window["trough_date"])
    d = holdings[(holdings["date"] >= start) & (holdings["date"] <= end)].copy()
    if d.empty:
        return pd.DataFrame()
    grouped = (
        d.groupby("ticker", as_index=False)
        .agg(
            mtm_pnl_usd=("mtm_pnl_usd", "sum"),
            min_weight=("weight", "min"),
            max_weight=("weight", "max"),
            avg_weight=("weight", "mean"),
            held_days=("date", "nunique"),
            first_seen=("date", "min"),
            last_seen=("date", "max"),
        )
        .sort_values("mtm_pnl_usd", ascending=True)
        .head(top_n)
        .reset_index(drop=True)
    )
    peak_equity = max(safe_float(window.get("peak_equity_usd")), 1.0)
    grouped["mtm_pnl_pct_of_peak_equity"] = grouped["mtm_pnl_usd"] / peak_equity
    grouped["first_seen"] = grouped["first_seen"].dt.date.astype(str)
    grouped["last_seen"] = grouped["last_seen"].dt.date.astype(str)
    return grouped


def target_weight_column(target: pd.DataFrame) -> str:
    for column in ["target_weight", "weight"]:
        if column in target.columns:
            return column
    raise ValueError("target book must include target_weight or weight")


def prepare_target_book(path: Path) -> tuple[pd.DataFrame, str]:
    target = load_csv(path, {"rebalance_date", "ticker"})
    target = normalize_date_column(target, "rebalance_date")
    target["ticker"] = target["ticker"].astype(str).str.upper()
    target = target[target["ticker"] != "CASH"].copy()
    weight_col = target_weight_column(target)
    target[weight_col] = pd.to_numeric(target[weight_col], errors="coerce").fillna(0.0)
    return target, weight_col


def value_from_row(row: pd.Series, column: str, default: Any = "") -> Any:
    return row[column] if column in row.index else default


def row_signal_flags(row: pd.Series | None, actual_weight: float, target_weight: float, target_missing: bool) -> dict[str, Any]:
    if row is None:
        hold_replace_decision = ""
        trim_status = ""
        trend_template_full = math.nan
        rs_1m = math.nan
        rs_3m = math.nan
        ticker_ret_1m = math.nan
    else:
        hold_replace_decision = safe_str(value_from_row(row, "hold_replace_decision")).lower()
        trim_status = safe_str(value_from_row(row, "main_quality_hold_weak_timing_trim_status")).lower()
        trend_template_full = safe_float(value_from_row(row, "trend_template_full"), math.nan)
        rs_1m = safe_float(value_from_row(row, "rs_benchmark_1m"), math.nan)
        rs_3m = safe_float(value_from_row(row, "rs_benchmark_3m"), math.nan)
        ticker_ret_1m = safe_float(value_from_row(row, "ticker_ret_1m"), math.nan)

    target_removed = bool(target_missing or target_weight <= ZERO_WEIGHT_EPS)
    material_reduction = bool(target_weight + REDUCTION_EPS < actual_weight)
    replacement_exit = any(token in hold_replace_decision for token in ["replace", "exit", "broken", "drop"])
    trim_applied = bool(trim_status and trim_status not in {"not_applicable", "none", "false", "0"})
    trend_broken = bool(math.isfinite(trend_template_full) and trend_template_full <= 0)
    weak_rs = bool((math.isfinite(rs_1m) and rs_1m < 0) or (math.isfinite(rs_3m) and rs_3m < 0))
    negative_1m = bool(math.isfinite(ticker_ret_1m) and ticker_ret_1m < 0)
    hard_exit_or_reduction = bool(target_removed or material_reduction or replacement_exit or trim_applied)
    any_pressure = bool(hard_exit_or_reduction or trend_broken or weak_rs or negative_1m)
    return {
        "target_removed": target_removed,
        "material_reduction": material_reduction,
        "replacement_exit": replacement_exit,
        "trim_applied": trim_applied,
        "trend_broken": trend_broken,
        "weak_rs": weak_rs,
        "negative_1m": negative_1m,
        "hard_exit_or_reduction": hard_exit_or_reduction,
        "any_pressure": any_pressure,
        "hold_replace_decision": hold_replace_decision,
        "trim_status": trim_status,
        "trend_template_full": trend_template_full,
        "rs_benchmark_1m": rs_1m,
        "rs_benchmark_3m": rs_3m,
        "ticker_ret_1m": ticker_ret_1m,
    }


def actual_weight_at(holdings_by_date: dict[pd.Timestamp, dict[str, float]], date: pd.Timestamp, ticker: str) -> float:
    return safe_float(holdings_by_date.get(pd.Timestamp(date), {}).get(ticker, 0.0))


def first_trading_date_on_or_after(trading_dates: list[pd.Timestamp], date: pd.Timestamp) -> pd.Timestamp | None:
    date = pd.Timestamp(date)
    for candidate in trading_dates:
        if candidate >= date:
            return candidate
    return None


def first_alignment_date(
    trading_dates: list[pd.Timestamp],
    holdings_by_date: dict[pd.Timestamp, dict[str, float]],
    *,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    ticker: str,
    target_weight: float,
) -> pd.Timestamp | None:
    threshold = max(ACTUAL_WEIGHT_EPS, target_weight + ALIGNMENT_SLACK)
    for candidate in trading_dates:
        if candidate < start_date:
            continue
        if candidate > end_date:
            break
        if actual_weight_at(holdings_by_date, candidate, ticker) <= threshold:
            return candidate
    return None


def pnl_after_signal(holdings: pd.DataFrame, ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float:
    d = holdings[
        (holdings["ticker"] == ticker)
        & (holdings["date"] >= pd.Timestamp(start_date))
        & (holdings["date"] <= pd.Timestamp(end_date))
    ]
    return safe_float(d["mtm_pnl_usd"].sum()) if not d.empty else 0.0


def analyze_ticker(
    *,
    ticker: str,
    target: pd.DataFrame,
    weight_col: str,
    trading_dates: list[pd.Timestamp],
    decision_dates: list[pd.Timestamp],
    holdings_by_date: dict[pd.Timestamp, dict[str, float]],
    holdings_mtm: pd.DataFrame,
    peak_date: pd.Timestamp,
    trough_date: pd.Timestamp,
    lookback_days: int,
) -> dict[str, Any]:
    start_decision = pd.Timestamp(peak_date) - pd.DateOffset(days=int(lookback_days))
    ticker_target = target[target["ticker"] == ticker].copy()
    ticker_targets_by_date = {pd.Timestamp(row["rebalance_date"]): row for _, row in ticker_target.iterrows()}
    first_signal: dict[str, Any] | None = None
    pressure_rows: list[dict[str, Any]] = []

    for decision_date in decision_dates:
        decision_date = pd.Timestamp(decision_date)
        if decision_date < start_decision or decision_date > trough_date:
            continue
        actual_date = first_trading_date_on_or_after(trading_dates, decision_date)
        if actual_date is None or actual_date > trough_date:
            continue
        actual_weight = actual_weight_at(holdings_by_date, actual_date, ticker)
        if actual_weight <= ACTUAL_WEIGHT_EPS:
            continue
        row = ticker_targets_by_date.get(decision_date)
        target_missing = row is None
        target_weight = 0.0 if row is None else safe_float(row[weight_col])
        flags = row_signal_flags(row, actual_weight, target_weight, target_missing)
        if not flags["any_pressure"]:
            continue
        item = {
            "ticker": ticker,
            "decision_date": decision_date.date().isoformat(),
            "actual_date": actual_date.date().isoformat(),
            "actual_weight": actual_weight,
            "target_weight": target_weight,
            "target_missing": target_missing,
            **flags,
        }
        pressure_rows.append(item)
        if first_signal is None and flags["hard_exit_or_reduction"]:
            first_signal = item

    if first_signal is None:
        return {
            "ticker": ticker,
            "hard_exit_signal_found": False,
            "pressure_event_count": len(pressure_rows),
            "weak_pressure_event_count": len(pressure_rows),
            "first_signal_date": "",
            "alignment_date": "",
            "latency_calendar_days": 0,
            "latency_trading_days": 0,
            "latency_censored_at_trough": False,
            "loss_after_first_signal_usd": 0.0,
            "first_signal_reason": "",
            "first_signal_target_weight": 0.0,
            "first_signal_actual_weight": 0.0,
        }

    signal_date = pd.Timestamp(first_signal["actual_date"])
    target_weight = safe_float(first_signal["target_weight"])
    alignment = first_alignment_date(
        trading_dates,
        holdings_by_date,
        start_date=signal_date,
        end_date=trough_date,
        ticker=ticker,
        target_weight=target_weight,
    )
    censored = alignment is None
    effective_alignment = alignment or trough_date
    latency_trading_days = sum(1 for date in trading_dates if signal_date <= date <= effective_alignment)
    reasons = [
        key
        for key in ["target_removed", "material_reduction", "replacement_exit", "trim_applied"]
        if bool(first_signal.get(key))
    ]
    return {
        "ticker": ticker,
        "hard_exit_signal_found": True,
        "pressure_event_count": len(pressure_rows),
        "weak_pressure_event_count": sum(1 for row in pressure_rows if not bool(row.get("hard_exit_or_reduction"))),
        "first_signal_date": signal_date.date().isoformat(),
        "alignment_date": "" if alignment is None else alignment.date().isoformat(),
        "latency_calendar_days": int((effective_alignment - signal_date).days),
        "latency_trading_days": int(latency_trading_days),
        "latency_censored_at_trough": censored,
        "loss_after_first_signal_usd": pnl_after_signal(holdings_mtm, ticker, signal_date, trough_date),
        "first_signal_reason": ",".join(reasons),
        "first_signal_target_weight": target_weight,
        "first_signal_actual_weight": safe_float(first_signal["actual_weight"]),
    }


def render_report(payload: dict[str, Any], contributors: pd.DataFrame, latency: pd.DataFrame) -> str:
    window = payload["max_drawdown_window"]
    lines = [
        "# Run287 Main Exit Latency Audit",
        "",
        "Status: `completed`",
        "",
        "This is a research-only diagnostic. It does not replay trades, dispatch",
        "a fullrun, mutate target books, tune thresholds, or create a crash",
        "predictor.",
        "",
        "## Max Drawdown Window",
        "",
        f"- Peak: `{window['peak_date']}` equity `${window['peak_equity_usd']:,.2f}`",
        f"- Trough: `{window['trough_date']}` equity `${window['trough_equity_usd']:,.2f}`",
        f"- MaxDD: `{window['max_dd']:.2%}`",
        "",
        "## Top Mark-to-Market Contributors",
        "",
        "| Ticker | MTM PnL | Pct of peak equity | Avg weight | Held days |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in contributors.head(10).to_dict("records"):
        lines.append(
            "| {ticker} | ${pnl:,.0f} | {pct:.2%} | {avg:.2%} | {days} |".format(
                ticker=row.get("ticker", ""),
                pnl=safe_float(row.get("mtm_pnl_usd")),
                pct=safe_float(row.get("mtm_pnl_pct_of_peak_equity")),
                avg=safe_float(row.get("avg_weight")),
                days=int(safe_float(row.get("held_days"))),
            )
        )
    lines.extend(["", "## Exit-Latency Signals", "", "| Ticker | Hard signal | First signal | Latency TD | Loss after signal | Reason |", "| --- | --- | --- | ---: | ---: | --- |"])
    for row in latency.head(10).to_dict("records"):
        lines.append(
            "| {ticker} | {signal} | {date} | {days} | ${loss:,.0f} | {reason} |".format(
                ticker=row.get("ticker", ""),
                signal=str(bool(row.get("hard_exit_signal_found"))).lower(),
                date=row.get("first_signal_date", ""),
                days=int(safe_float(row.get("latency_trading_days"))),
                loss=safe_float(row.get("loss_after_first_signal_usd")),
                reason=row.get("first_signal_reason", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Diagnosis",
            "",
            f"- Latency candidate present: `{str(payload['latency_candidate_present']).lower()}`",
            f"- Diagnosis: `{payload['diagnosis']}`",
            f"- Next action: `{payload['next_action']}`",
            "",
            "Research boundary: if a candidate exists, the next step is an ex-ante",
            "counterfactual with held-out validation. Directly editing losing",
            "months or tickers remains forbidden.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    main_root = repo_path(args.main_root)
    target_book = repo_path(args.target_book)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    equity = normalize_date_column(load_csv(main_root / "equity_curve.csv", {"date", "equity_usd"}), "date")
    holdings = normalize_date_column(
        load_csv(main_root / "holdings_daily.csv", {"date", "ticker", "shares", "price", "market_value_usd", "weight"}),
        "date",
    )
    holdings["ticker"] = holdings["ticker"].astype(str).str.upper()
    holdings = add_mtm_pnl(holdings)
    target, weight_col = prepare_target_book(target_book)

    window = max_drawdown_window(equity)
    contributors = drawdown_contributors(holdings, window, int(args.top_n))
    trading_dates = [pd.Timestamp(x) for x in equity["date"].drop_duplicates().sort_values().tolist()]
    decision_dates = [pd.Timestamp(x) for x in target["rebalance_date"].drop_duplicates().sort_values().tolist()]
    holdings_by_date: dict[pd.Timestamp, dict[str, float]] = {}
    for date, group in holdings.groupby("date"):
        holdings_by_date[pd.Timestamp(date)] = {
            str(row["ticker"]).upper(): safe_float(row["weight"]) for _, row in group.iterrows()
        }

    latency_rows: list[dict[str, Any]] = []
    for _, contributor in contributors.iterrows():
        ticker = str(contributor["ticker"]).upper()
        item = analyze_ticker(
            ticker=ticker,
            target=target,
            weight_col=weight_col,
            trading_dates=trading_dates,
            decision_dates=decision_dates,
            holdings_by_date=holdings_by_date,
            holdings_mtm=holdings,
            peak_date=pd.Timestamp(window["peak_date"]),
            trough_date=pd.Timestamp(window["trough_date"]),
            lookback_days=int(args.lookback_days),
        )
        item.update(
            {
                "mtm_pnl_usd": safe_float(contributor.get("mtm_pnl_usd")),
                "mtm_pnl_pct_of_peak_equity": safe_float(contributor.get("mtm_pnl_pct_of_peak_equity")),
                "avg_weight": safe_float(contributor.get("avg_weight")),
                "max_weight": safe_float(contributor.get("max_weight")),
                "held_days": int(safe_float(contributor.get("held_days"))),
            }
        )
        latency_rows.append(item)
    latency = pd.DataFrame(latency_rows)
    if latency.empty:
        latency = pd.DataFrame(columns=["ticker", "hard_exit_signal_found", "loss_after_first_signal_usd", "latency_trading_days"])

    total_negative_after_signal = safe_float(
        latency.loc[latency["loss_after_first_signal_usd"] < 0, "loss_after_first_signal_usd"].sum()
        if "loss_after_first_signal_usd" in latency
        else 0.0
    )
    peak_equity = max(safe_float(window["peak_equity_usd"]), 1.0)
    hard_signal_count = int(latency["hard_exit_signal_found"].fillna(False).astype(bool).sum()) if "hard_exit_signal_found" in latency else 0
    material_latency_count = int(
        (
            latency["hard_exit_signal_found"].fillna(False).astype(bool)
            & (pd.to_numeric(latency["latency_trading_days"], errors="coerce").fillna(0) >= int(args.material_latency_days))
            & (pd.to_numeric(latency["loss_after_first_signal_usd"], errors="coerce").fillna(0) < 0)
        ).sum()
    )
    material_loss_threshold = -abs(float(args.material_loss_bps)) / 10000.0 * peak_equity
    latency_candidate_present = bool(material_latency_count > 0 and total_negative_after_signal <= material_loss_threshold)
    if latency_candidate_present:
        diagnosis = "exit_latency_candidate_for_ex_ante_counterfactual"
        next_action = "build_ex_ante_exit_latency_counterfactual_before_any_alpha_tuning"
    elif hard_signal_count == 0:
        diagnosis = "no_hard_ex_ante_exit_or_reduction_signal_found_on_top_drawdown_contributors"
        next_action = "do_not_add_shock_guard; investigate other ex_ante alpha/risk levers"
    else:
        diagnosis = "hard_signals_found_but_latency_or_post_signal_loss_not_material"
        next_action = "record_negative_latency_evidence; do_not_tune_losing_months"

    contributors_path = output_dir / "drawdown_contributors.csv"
    latency_path = output_dir / "position_latency.csv"
    contributors.to_csv(contributors_path, index=False)
    latency.to_csv(latency_path, index=False)

    serial_window = {
        "peak_date": pd.Timestamp(window["peak_date"]).date().isoformat(),
        "trough_date": pd.Timestamp(window["trough_date"]).date().isoformat(),
        "peak_equity_usd": safe_float(window["peak_equity_usd"]),
        "trough_equity_usd": safe_float(window["trough_equity_usd"]),
        "max_dd": safe_float(window["max_dd"]),
    }
    payload: dict[str, Any] = {
        "schema_version": "run287-exit-latency-audit-v1",
        "status": "completed",
        "research_only": True,
        "fullrun_dispatched": False,
        "production_mutation_allowed": False,
        "threshold_tuning_performed": False,
        "direct_losing_month_edit_allowed": False,
        "portfolio": "main",
        "metric_mode": "broker_ledger_next_close_cash_carry",
        "main_root": str(main_root),
        "target_book": str(target_book),
        "target_weight_column": weight_col,
        "max_drawdown_window": serial_window,
        "top_n": int(args.top_n),
        "lookback_days": int(args.lookback_days),
        "hard_signal_count": hard_signal_count,
        "material_latency_count": material_latency_count,
        "total_negative_loss_after_first_signal_usd": total_negative_after_signal,
        "total_negative_loss_after_first_signal_pct_of_peak_equity": total_negative_after_signal / peak_equity,
        "material_loss_threshold_usd": material_loss_threshold,
        "latency_candidate_present": latency_candidate_present,
        "diagnosis": diagnosis,
        "next_action": next_action,
        "artifacts": {
            "summary": str(output_dir / "summary.json"),
            "report": str(output_dir / "report.md"),
            "drawdown_contributors": str(contributors_path),
            "position_latency": str(latency_path),
        },
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, contributors, latency), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-root", default="outputs/run287_metric_sidecar/generated_book_cash_carry/main")
    parser.add_argument(
        "--target-book",
        default="outputs/run_28725350727_user_operating_artifact/outputs/reports/operating_main_target_book.csv",
    )
    parser.add_argument("--output-dir", default="outputs/run287_exit_latency")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--material-latency-days", type=int, default=5)
    parser.add_argument("--material-loss-bps", type=float, default=10.0)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(
        json.dumps(
            {
                "status": payload["status"],
                "latency_candidate_present": payload["latency_candidate_present"],
                "diagnosis": payload["diagnosis"],
                "summary": payload["artifacts"]["summary"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
