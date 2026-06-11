#!/usr/bin/env python3
"""Explain why monthly/proxy portfolio metrics differ from broker-ledger metrics.

This sidecar is diagnostic only. It intentionally reads the monthly target
book's `weighted_forward_return` when available so we can compare the legacy
research accounting path to the stricter account-ledger path. It must never be
used as a production signal.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import CONCENTRATED_CHAMPION_FILTERS, normalize_targets, read_csv
from tools.validate_target_book_cash_contract import validate_contract


DEFAULT_OUTPUT_DIR = "outputs/broker_gap_attribution"
STARTING_CAPITAL_USD = 100000.0


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if not math.isfinite(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


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


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2%}"


def max_drawdown(equity: pd.Series) -> float | None:
    s = pd.to_numeric(equity, errors="coerce").dropna()
    if s.empty:
        return None
    return float((s / s.cummax() - 1.0).min())


def cagr(equity: pd.Series, dates: pd.Series) -> float | None:
    s = pd.to_numeric(equity, errors="coerce").dropna()
    if len(s) < 2:
        return None
    dt = pd.to_datetime(dates, errors="coerce").dropna()
    if len(dt) < 2:
        return None
    years = (dt.iloc[-1] - dt.iloc[0]).days / 365.25
    if years <= 0 or s.iloc[0] <= 0:
        return None
    return float((s.iloc[-1] / s.iloc[0]) ** (1.0 / years) - 1.0)


def target_forward_stats(target_book: Path, portfolio_kind: str) -> tuple[dict[str, Any], pd.DataFrame]:
    raw = read_csv(target_book)
    targets = normalize_targets(raw, portfolio_kind)
    if raw.empty or targets.empty or "weighted_forward_return" not in raw.columns:
        return {"status": "missing_forward_target_book", "target_book": str(target_book)}, pd.DataFrame()
    raw = raw.copy()
    if portfolio_kind == "concentrated":
        for col, expected in CONCENTRATED_CHAMPION_FILTERS.items():
            if col not in raw.columns:
                continue
            mask = raw[col].astype(str).str.strip().eq(expected)
            if mask.any():
                raw = raw[mask].copy()
        targets_key = targets[["rebalance_date", "ticker"]].copy()
        targets_key["rebalance_date"] = pd.to_datetime(targets_key["rebalance_date"], errors="coerce").dt.normalize()
        raw["rebalance_date"] = pd.to_datetime(raw["rebalance_date"], errors="coerce").dt.normalize()
        raw["ticker"] = raw["ticker"].astype(str).str.upper().str.strip()
        raw = raw.merge(targets_key.drop_duplicates(), on=["rebalance_date", "ticker"], how="inner")
    raw["rebalance_date"] = pd.to_datetime(raw["rebalance_date"], errors="coerce").dt.normalize()
    raw["weight"] = pd.to_numeric(raw.get("weight"), errors="coerce").fillna(0.0)
    raw["weighted_forward_return"] = pd.to_numeric(raw.get("weighted_forward_return"), errors="coerce").fillna(0.0)
    raw = raw.dropna(subset=["rebalance_date"])
    monthly = (
        raw.groupby("rebalance_date", as_index=False)
        .agg(
            implied_return=("weighted_forward_return", "sum"),
            target_weight_sum=("weight", "sum"),
            names=("ticker", "nunique"),
        )
        .sort_values("rebalance_date")
    )
    monthly["implied_equity"] = (1.0 + monthly["implied_return"]).cumprod() * 100000.0
    prev: dict[str, float] = {}
    turnover_rows: list[dict[str, Any]] = []
    for dt, group in targets.groupby("rebalance_date"):
        cur = {str(row.ticker).upper(): float(row.weight) for row in group.itertuples(index=False)}
        tickers = set(cur) | set(prev)
        target_turnover = sum(abs(cur.get(ticker, 0.0) - prev.get(ticker, 0.0)) for ticker in tickers) / 2.0
        jaccard = None
        if prev:
            jaccard = len(set(cur) & set(prev)) / max(1, len(set(cur) | set(prev)))
        turnover_rows.append(
            {
                "rebalance_date": pd.Timestamp(dt).date().isoformat(),
                "target_turnover": target_turnover,
                "name_jaccard": jaccard,
            }
        )
        prev = cur
    turnover = pd.DataFrame(turnover_rows)
    if not turnover.empty:
        turnover["rebalance_date"] = pd.to_datetime(turnover["rebalance_date"], errors="coerce")
        monthly = monthly.merge(turnover, on="rebalance_date", how="left")
    summary = {
        "status": "completed",
        "metric_mode": "monthly_weighted_forward_return_diagnostic",
        "uses_forward_returns": True,
        "target_book": str(target_book),
        "legacy_implied_cagr": cagr(monthly["implied_equity"], monthly["rebalance_date"]),
        "legacy_implied_max_dd": max_drawdown(monthly["implied_equity"]),
        "avg_target_weight_sum": safe_float(monthly["target_weight_sum"].mean()),
        "avg_names": safe_float(monthly["names"].mean()),
        "avg_target_turnover": safe_float(monthly.get("target_turnover", pd.Series(dtype=float)).iloc[1:].mean()),
        "avg_name_jaccard": safe_float(monthly.get("name_jaccard", pd.Series(dtype=float)).mean()),
    }
    return summary, monthly


def broker_stats(broker_dir: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics = read_json(broker_dir / "metrics.json")
    equity = read_csv(broker_dir / "equity_curve.csv")
    trades = read_csv(broker_dir / "trades.csv")
    if equity.empty or "equity_usd" not in equity.columns:
        return {"status": "missing_broker_equity", "broker_dir": str(broker_dir), **metrics}, pd.DataFrame()
    equity["date"] = pd.to_datetime(equity["date"], errors="coerce")
    equity = equity.dropna(subset=["date"]).sort_values("date")
    month_end = equity.set_index("date")["equity_usd"].resample("ME").last().dropna()
    month_end_dates = pd.Series(month_end.index)
    summary = {
        "status": metrics.get("status", "completed"),
        "metric_mode": metrics.get("metric_mode"),
        "broker_cagr": safe_float(metrics.get("cagr")),
        "broker_max_dd_daily": safe_float(metrics.get("max_dd")),
        "broker_max_dd_month_end": max_drawdown(month_end),
        "broker_sharpe": safe_float(metrics.get("sharpe")),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"), 0) or 0),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "gross_traded_on_starting_capital": None,
        "fill_mode": metrics.get("fill_mode"),
        "integer_shares": metrics.get("integer_shares"),
        "valid_for_production": metrics.get("valid_for_production"),
        "max_fill_lag_days": metrics.get("max_fill_lag_days"),
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
    }
    if summary["gross_traded_usd"] is not None:
        summary["gross_traded_on_starting_capital"] = float(summary["gross_traded_usd"]) / 100000.0
    monthly = pd.DataFrame(
        {
            "rebalance_date": month_end_dates.dt.normalize(),
            "broker_month_end_equity": month_end.values,
            "broker_month_end_return": month_end.pct_change().fillna(0.0).values,
        }
    )
    if not trades.empty:
        trades["date"] = pd.to_datetime(trades.get("date"), errors="coerce")
        trade_month = trades.dropna(subset=["date"]).copy()
        if not trade_month.empty:
            trade_month["rebalance_date"] = trade_month["date"].dt.to_period("M").dt.to_timestamp("M").dt.normalize()
            agg = (
                trade_month.groupby("rebalance_date", as_index=False)
                .agg(
                    broker_trade_count=("ticker", "size"),
                    broker_fees_usd=("fee_usd", "sum"),
                    broker_gross_traded_usd=("gross_value", "sum"),
                )
            )
            monthly = monthly.merge(agg, on="rebalance_date", how="left")
    return summary, monthly


def operating_target_book_path(latest_run: Path, portfolio_kind: str) -> Path:
    return latest_run / "reports" / (
        "operating_main_target_book.csv" if portfolio_kind == "main" else "operating_concentrated_target_book.csv"
    )


def research_target_book_path(latest_run: Path, portfolio_kind: str) -> Path:
    return latest_run / "reports" / (
        "main_monthly_weights.csv" if portfolio_kind == "main" else "concentrated_strategy_holdings.csv"
    )


def target_vs_actual_stats(broker_dir: Path) -> dict[str, Any]:
    path = broker_dir / "target_vs_actual_weights.csv"
    d = read_csv(path)
    if d.empty or "target_weight" not in d.columns or "actual_weight" not in d.columns:
        return {"status": "unavailable", "reason": "missing target_vs_actual_weights.csv", "source": str(path)}
    d = d.copy()
    d["target_weight"] = pd.to_numeric(d["target_weight"], errors="coerce")
    d["actual_weight"] = pd.to_numeric(d["actual_weight"], errors="coerce")
    d = d.dropna(subset=["target_weight", "actual_weight"])
    if d.empty:
        return {"status": "unavailable", "reason": "empty target/actual weight rows", "source": str(path)}
    d["abs_weight_gap"] = (d["target_weight"] - d["actual_weight"]).abs()
    d["positive_shortfall"] = (d["target_weight"] - d["actual_weight"]).clip(lower=0.0)
    return {
        "status": "completed",
        "source": str(path),
        "row_count": int(len(d)),
        "mean_abs_weight_gap_pp": round(float(d["abs_weight_gap"].mean() * 100.0), 4),
        "p95_abs_weight_gap_pp": round(float(d["abs_weight_gap"].quantile(0.95) * 100.0), 4),
        "max_abs_weight_gap_pp": round(float(d["abs_weight_gap"].max() * 100.0), 4),
        "mean_unfilled_exposure_pp": round(float(d["positive_shortfall"].mean() * 100.0), 4),
        "max_unfilled_exposure_pp": round(float(d["positive_shortfall"].max() * 100.0), 4),
    }


def candidate_freshness_stats(latest_run: Path, target_book: Path) -> dict[str, Any]:
    candidate = read_csv(latest_run / "reports" / "candidate_replay_book.csv")
    target = read_csv(target_book)
    if candidate.empty:
        return {"status": "unavailable", "reason": "missing candidate_replay_book.csv"}
    date_cols = [col for col in ["as_of_date", "available_from", "rebalance_date", "date"] if col in candidate.columns]
    payload: dict[str, Any] = {
        "status": "metadata_only",
        "candidate_rows": int(len(candidate)),
        "date_columns": date_cols,
    }
    for col in date_cols:
        values = pd.to_datetime(candidate[col], errors="coerce").dropna()
        if not values.empty:
            payload[f"max_{col}"] = pd.Timestamp(values.max()).date().isoformat()
            payload[f"min_{col}"] = pd.Timestamp(values.min()).date().isoformat()
    if not target.empty and "rebalance_date" in target.columns:
        target_dates = pd.to_datetime(target["rebalance_date"], errors="coerce").dropna()
        if not target_dates.empty:
            payload["target_max_rebalance_date"] = pd.Timestamp(target_dates.max()).date().isoformat()
    payload["reason"] = "freshness delta needs a fast/full paired audit for causal attribution"
    return payload


def estimate_decomposition(
    *,
    latest_run: Path,
    portfolio_kind: str,
    research_target: dict[str, Any],
    broker: dict[str, Any],
    broker_dir: Path,
    monthly: pd.DataFrame,
) -> dict[str, Any]:
    operating_book = operating_target_book_path(latest_run, portfolio_kind)
    research_book = research_target_book_path(latest_run, portfolio_kind)
    cash_summary, _cash_by_date, cash_drift = validate_contract(
        target_book=operating_book if operating_book.exists() else research_book,
        broker_dir=broker_dir,
    )
    target_actual = target_vs_actual_stats(broker_dir)
    fees = safe_float(broker.get("total_fees_usd"), 0.0) or 0.0
    cagr_gap_pp = None
    target_cagr = safe_float(research_target.get("legacy_implied_cagr"))
    broker_cagr = safe_float(broker.get("broker_cagr"))
    if target_cagr is not None and broker_cagr is not None:
        cagr_gap_pp = round((target_cagr - broker_cagr) * 100.0, 4)

    export_gap: dict[str, Any] = {"status": "unavailable", "gap_pp": None}
    if operating_book.exists():
        operating_target, _operating_monthly = target_forward_stats(operating_book, portfolio_kind)
        operating_cagr = safe_float(operating_target.get("legacy_implied_cagr"))
        if target_cagr is not None and operating_cagr is not None:
            export_gap = {
                "status": "completed",
                "source": str(operating_book),
                "gap_pp": round((target_cagr - operating_cagr) * 100.0, 4),
                "research_legacy_cagr": target_cagr,
                "operating_legacy_cagr": operating_cagr,
            }
        else:
            export_gap = {
                "status": "unavailable",
                "source": str(operating_book),
                "reason": "operating target book has no weighted_forward_return diagnostic column",
                "gap_pp": None,
            }

    cash_drift_summary = cash_summary.get("drift", {})
    cash_contract_gap = {
        "status": cash_summary.get("status"),
        "cash_contract_pass": bool(cash_summary.get("cash_contract_pass")),
        "target_cash_contract_pass": bool(cash_summary.get("target", {}).get("target_cash_contract_pass")),
        "mean_cash_drift_pp": cash_drift_summary.get("mean_cash_drift_pp"),
        "max_monthly_cash_drift_pp": cash_drift_summary.get("max_monthly_cash_drift_pp"),
        "rebalance_day_mean_cash_drift_pp": cash_drift_summary.get("rebalance_day_mean_cash_drift_pp"),
        "rebalance_day_max_cash_drift_pp": cash_drift_summary.get("rebalance_day_max_cash_drift_pp"),
        "rebalance_day_cash_drift_pass": cash_drift_summary.get("rebalance_day_cash_drift_pass"),
        "month_mean_cash_drift_pp": cash_drift_summary.get("month_mean_cash_drift_pp"),
        "month_max_cash_drift_pp": cash_drift_summary.get("month_max_cash_drift_pp"),
        "month_mean_cash_drift_pass": cash_drift_summary.get("month_mean_cash_drift_pass"),
        "avg_target_cash_weight": cash_summary.get("target", {}).get("avg_target_cash_weight"),
        "avg_broker_cash_weight": cash_summary.get("broker", {}).get("avg_broker_cash_weight"),
    }
    if not cash_drift.empty:
        monthly = monthly.merge(
            cash_drift.rename(columns={"month_end": "rebalance_date"}),
            on="rebalance_date",
            how="left",
        )

    fill_lag = {
        "status": "metadata_only",
        "fill_mode": broker.get("metric_mode") or broker.get("fill_mode"),
        "max_fill_lag_days": broker.get("max_fill_lag_days"),
        "reason": "per-fill price slippage attribution is not emitted by broker replay yet",
    }
    integer_residual = {
        "status": target_actual.get("status"),
        "integer_shares": broker.get("integer_shares"),
        "mean_abs_weight_gap_pp": target_actual.get("mean_abs_weight_gap_pp"),
        "p95_abs_weight_gap_pp": target_actual.get("p95_abs_weight_gap_pp"),
        "max_abs_weight_gap_pp": target_actual.get("max_abs_weight_gap_pp"),
    }
    unfilled_exposure = {
        "status": target_actual.get("status"),
        "mean_unfilled_exposure_pp": target_actual.get("mean_unfilled_exposure_pp"),
        "max_unfilled_exposure_pp": target_actual.get("max_unfilled_exposure_pp"),
    }
    fee_drag = {
        "status": "completed",
        "fees_usd": fees,
        "fee_drag_on_starting_capital_pp": round((fees / STARTING_CAPITAL_USD) * 100.0, 4),
    }
    residual = {
        "status": "partial",
        "total_cagr_gap_pp": cagr_gap_pp,
        "unexplained_cagr_gap_pp": cagr_gap_pp,
        "reason": "available components are diagnostic and not additive CAGR terms; use fast/full and broker replay instrumentation for causal decomposition",
    }
    return {
        "target_book_export_gap": export_gap,
        "cash_contract_gap": cash_contract_gap,
        # Renamed from fill_lag_slippage: the block carries fill-mode metadata
        # only. Actual per-fill slippage is not measured yet and must not be
        # read as a 0-valued decomposed term (review C6, 9b2ce49).
        "fill_lag_metadata": fill_lag,
        "fee_drag": fee_drag,
        "integer_share_residual": integer_residual,
        "rounding_drag": {
            "status": "proxied",
            "proxy": "integer_share_residual.mean_abs_weight_gap_pp",
            "mean_abs_weight_gap_pp": target_actual.get("mean_abs_weight_gap_pp"),
        },
        "unfilled_exposure_drag": unfilled_exposure,
        "candidate_freshness_gap": candidate_freshness_stats(latest_run, operating_book if operating_book.exists() else research_book),
        "residual": residual,
    }


def portfolio_attribution(latest_run: Path, portfolio_kind: str) -> tuple[dict[str, Any], pd.DataFrame]:
    target_book = research_target_book_path(latest_run, portfolio_kind)
    broker_dir = latest_run / "broker_replay" / portfolio_kind
    target, target_monthly = target_forward_stats(target_book, portfolio_kind)
    broker, broker_monthly = broker_stats(broker_dir)
    monthly = pd.DataFrame()
    if not target_monthly.empty and not broker_monthly.empty:
        target_monthly = target_monthly.copy()
        target_monthly["rebalance_date"] = pd.to_datetime(target_monthly["rebalance_date"], errors="coerce").dt.to_period("M").dt.to_timestamp("M").dt.normalize()
        monthly = target_monthly.merge(broker_monthly, on="rebalance_date", how="outer").sort_values("rebalance_date")
        monthly["return_gap"] = pd.to_numeric(monthly.get("implied_return"), errors="coerce") - pd.to_numeric(monthly.get("broker_month_end_return"), errors="coerce")
    summary = {
        "portfolio": portfolio_kind,
        "target_forward": target,
        "broker_ledger": broker,
        "cagr_gap_pp": None,
        "daily_vs_month_end_dd_gap_pp": None,
        "decomposition": {},
        "diagnosis": [],
    }
    target_cagr = safe_float(target.get("legacy_implied_cagr"))
    broker_cagr = safe_float(broker.get("broker_cagr"))
    if target_cagr is not None and broker_cagr is not None:
        summary["cagr_gap_pp"] = round((target_cagr - broker_cagr) * 100.0, 4)
    broker_daily_dd = safe_float(broker.get("broker_max_dd_daily"))
    broker_month_dd = safe_float(broker.get("broker_max_dd_month_end"))
    if broker_daily_dd is not None and broker_month_dd is not None:
        summary["daily_vs_month_end_dd_gap_pp"] = round((broker_month_dd - broker_daily_dd) * 100.0, 4)
    if safe_float(target.get("avg_target_turnover"), 0.0) and float(target.get("avg_target_turnover")) > 0.35:
        summary["diagnosis"].append("high monthly target turnover creates execution cost and churn drag")
    broker_daily_for_diag = safe_float(broker.get("broker_max_dd_daily"))
    target_dd_for_diag = safe_float(target.get("legacy_implied_max_dd"))
    if broker_daily_for_diag is not None and target_dd_for_diag is not None:
        if broker_daily_for_diag < target_dd_for_diag - 0.10:
            summary["diagnosis"].append("monthly/proxy drawdown understates intramonth account drawdown")
    if safe_float(broker.get("avg_cash_weight"), 0.0) and float(broker["avg_cash_weight"]) > 0.05:
        summary["diagnosis"].append("cash/rounding/unfilled exposure drag is material")
    if safe_float(broker.get("total_fees_usd"), 0.0) and float(broker["total_fees_usd"]) > 10000:
        summary["diagnosis"].append("fees are material under realistic turnover")
    summary["decomposition"] = estimate_decomposition(
        latest_run=latest_run,
        portfolio_kind=portfolio_kind,
        research_target=target,
        broker=broker,
        broker_dir=broker_dir,
        monthly=monthly,
    )
    if not summary["decomposition"].get("cash_contract_gap", {}).get("cash_contract_pass", False):
        summary["diagnosis"].append("cash contract or broker cash drift fails production limits")
    if not summary["diagnosis"]:
        summary["diagnosis"].append("no single dominant attribution detected")
    return summary, monthly


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Broker Gap Attribution",
        "",
        "Diagnostic comparison of monthly/proxy accounting versus broker-ledger account replay.",
        "",
        "Important: target-book forward returns are used only for attribution. They are not production signals.",
        "",
        "| Portfolio | Legacy/Proxy CAGR | Broker CAGR | CAGR Gap | Legacy/Proxy MaxDD | Broker Daily MaxDD | Broker Month-End MaxDD | Avg Target Turnover | Cash Drift | Fees | Residual | Diagnosis |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for portfolio in ["main", "concentrated"]:
        row = payload.get(portfolio, {})
        target = row.get("target_forward", {})
        broker = row.get("broker_ledger", {})
        decomp = row.get("decomposition", {})
        cash_gap = decomp.get("cash_contract_gap", {})
        residual = decomp.get("residual", {})
        fee_drag = decomp.get("fee_drag", {})
        lines.append(
            "| {portfolio} | {legacy_cagr} | {broker_cagr} | {gap} | {legacy_dd} | {broker_dd} | {broker_month_dd} | {turnover} | {cash_drift} | {fees} | {residual} | {diagnosis} |".format(
                portfolio=portfolio,
                legacy_cagr=pct(safe_float(target.get("legacy_implied_cagr"))),
                broker_cagr=pct(safe_float(broker.get("broker_cagr"))),
                gap="" if row.get("cagr_gap_pp") is None else f"{row['cagr_gap_pp']:.2f}pp",
                legacy_dd=pct(safe_float(target.get("legacy_implied_max_dd"))),
                broker_dd=pct(safe_float(broker.get("broker_max_dd_daily"))),
                broker_month_dd=pct(safe_float(broker.get("broker_max_dd_month_end"))),
                turnover=pct(safe_float(target.get("avg_target_turnover"))),
                cash_drift=""
                if cash_gap.get("mean_cash_drift_pp") is None
                else f"{cash_gap.get('mean_cash_drift_pp'):.2f}pp mean / {cash_gap.get('max_monthly_cash_drift_pp'):.2f}pp max",
                fees=""
                if fee_drag.get("fees_usd") is None
                else f"${float(fee_drag['fees_usd']):,.0f} ({float(fee_drag.get('fee_drag_on_starting_capital_pp', 0.0)):.2f}pp)",
                residual="" if residual.get("unexplained_cagr_gap_pp") is None else f"{residual['unexplained_cagr_gap_pp']:.2f}pp",
                diagnosis="; ".join(row.get("diagnosis", [])),
            )
        )
    lines.extend(
        [
            "",
            "## Readout",
            "",
            "- If broker daily MaxDD is much worse than legacy/proxy MaxDD, monthly accounting was hiding intramonth losses.",
            "- If target turnover and fees are high, the strategy must be redesigned around account-aware holding, staging, and replacement rules.",
            "- Cash contract failures mean the target book, operating book, and broker ledger are not carrying the same cash semantics.",
            "- Decomposition fields are partly diagnostic; only fee drag is additive in starting-capital terms in this report.",
            "- A proxy target pass is not promotion evidence until the broker-ledger path also passes.",
            "",
        ]
    )
    return "\n".join(lines)


def run(latest_run: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"latest_run": str(latest_run), "metric_mode": "broker_gap_attribution"}
    monthly_frames: list[pd.DataFrame] = []
    for portfolio in ["main", "concentrated"]:
        summary, monthly = portfolio_attribution(latest_run, portfolio)
        payload[portfolio] = summary
        if not monthly.empty:
            monthly = monthly.copy()
            monthly.insert(0, "portfolio", portfolio)
            monthly_frames.append(monthly)
    if monthly_frames:
        pd.concat(monthly_frames, ignore_index=True).to_csv(output_dir / "monthly_gap_attribution.csv", index=False)
    write_json(output_dir / "gap_attribution_summary.json", payload)
    (output_dir / "gap_attribution_report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(repo_path(args.latest_run), repo_path(args.output_dir))
    print(json.dumps({k: payload[k] for k in ["main", "concentrated"] if k in payload}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
