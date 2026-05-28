#!/usr/bin/env python3
"""Build and broker-replay Market Leader historical target books.

This is a research-only sidecar. It never patches latest holdings, production
scores, feature-store schemas, or live target defaults. The tool builds new
monthly target books from the first historical rebalance date and replays those
books through the broker-ledger next-close path.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_market_leader_engine import (  # noqa: E402
    BENCHMARKS,
    MarketLeaderVariant,
    apply_benchmark_risk_overlay,
    apply_state_history,
    default_variants,
    load_prices,
    rejection_reason,
    safe_float,
    score_market_leaders,
    select_market_leader_targets,
    target_book_columns,
    target_rows_from_selection,
)
from tools.run_broker_ledger_replay import replay as broker_replay  # noqa: E402
from tools.run_broker_ledger_replay import DISABLE_CONCENTRATED_CHAMPION_FILTERS  # noqa: E402
from tools.run_weekly_evaluation import price_on_or_before  # noqa: E402


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/market_leader_challenger"
EXPERIMENT_ID = "market_leader_concentration_historical_broker_replay"
DEFAULT_MAIN_VARIANT = "main_N18_cap12_sub40_theme60_risk"
DEFAULT_CONCENTRATED_VARIANT = "concentrated_N5_cap30_sub70_risk"
STRESS_WINDOWS = {
    "covid_2020": ("2020-02-01", "2020-05-31"),
    "inflation_2022": ("2021-11-01", "2022-12-31"),
    "ai_semis_2024": ("2024-01-01", "2024-12-31"),
    "latest_12m": ("LATEST_12M", "LATEST"),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pct(value: Any) -> str:
    number = safe_float(value, math.nan)
    return "" if not math.isfinite(number) else f"{number:.2%}"


def resolve_candidate_book(latest_run: Path, explicit: str | None) -> tuple[Path, str]:
    if explicit:
        return repo_path(explicit), "explicit"
    candidates = [
        latest_run / "reports" / "candidate_replay_book.csv",
        latest_run / "candidate_replay_book.csv",
        latest_run / "reports" / "candidate_replay_book.parquet",
        latest_run / "scored_history.csv",
    ]
    for path in candidates:
        if path.exists():
            return path, "historical_candidate_book"
    scored_latest = latest_run / "scored_latest.csv"
    if scored_latest.exists():
        return scored_latest, "latest_only_blocked"
    return latest_run / "reports" / "candidate_replay_book.csv", "missing"


def normalize_candidate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame()
    d = frame.copy()
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d = d.dropna(subset=["rebalance_date"])
    d = d[(d["ticker"] != "") & (d["ticker"] != "CASH")]
    return d.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)


def blocked_outputs(output_dir: Path, reason: str, candidate_book: Path, source_mode: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "status": "blocked",
        "reason": reason,
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "research_only": True,
        "production_activation_allowed": False,
        "metric_mode": "DO_NOT_USE",
        "promotion_evaluation_status": "blocked",
    }
    write_json(output_dir / "summary.json", payload)
    write_json(output_dir / "main_metrics.json", payload)
    write_json(output_dir / "concentrated_metrics.json", payload)
    for name in [
        "grid_results.csv",
        "main_target_book.csv",
        "concentrated_target_book.csv",
        "selected_leaders_latest.csv",
        "leader_state_history.csv",
        "leader_state_latest.csv",
        "rejected_leaders.csv",
        "attribution_by_component.csv",
        "parameter_stability.csv",
        "stress_window_metrics.csv",
        "benchmark_relative_metrics.csv",
        "holding_churn_diagnostics.csv",
        "cost_sensitivity.csv",
    ]:
        pd.DataFrame().to_csv(output_dir / name, index=False)
    write_text(output_dir / "report.md", render_report(payload, [], []))
    return payload


def variant_filter(portfolio_kind: str, variants: list[MarketLeaderVariant]) -> list[MarketLeaderVariant]:
    return [variant for variant in variants if variant.portfolio_kind == portfolio_kind]


def default_variant_id(portfolio_kind: str) -> str:
    return DEFAULT_CONCENTRATED_VARIANT if portfolio_kind == "concentrated" else DEFAULT_MAIN_VARIANT


def prepare_prices(candidate: pd.DataFrame, price_cache: Path) -> dict[str, pd.DataFrame]:
    tickers = {str(x).upper() for x in candidate["ticker"].dropna().unique()}
    tickers.update(BENCHMARKS)
    return load_prices(price_cache, tickers)


def build_target_books(
    candidate: pd.DataFrame,
    price_cache: Path,
    variants: list[MarketLeaderVariant],
) -> dict[str, Any]:
    prices = prepare_prices(candidate, price_cache)
    state_by_ticker: dict[str, dict[str, int]] = {}
    target_rows: dict[str, list[dict[str, Any]]] = {variant.variant_id: [] for variant in variants}
    prev_holdings_by_variant: dict[str, dict[str, float]] = {variant.variant_id: {} for variant in variants}
    holding_streak_by_variant: dict[str, dict[str, int]] = {variant.variant_id: {} for variant in variants}
    default_latest_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    attribution_rows: list[dict[str, Any]] = []
    churn_rows: list[dict[str, Any]] = []
    dates = sorted(pd.to_datetime(candidate["rebalance_date"], errors="coerce").dropna().unique())
    latest_dt = pd.Timestamp(dates[-1]).normalize() if dates else None

    for raw_dt in dates:
        dt = pd.Timestamp(raw_dt).normalize()
        month = candidate[candidate["rebalance_date"].eq(dt)].copy()
        scored = score_market_leaders(month, prices, dt)
        scored = apply_state_history(scored, state_by_ticker)
        for row in scored.to_dict("records"):
            state_rows.append(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "ticker": row.get("ticker"),
                    "leader_tier": row.get("leader_tier"),
                    "leader_state": row.get("leader_state"),
                    "leader_state_reason": row.get("leader_state_reason"),
                    "warning_streak": row.get("warning_streak"),
                    "exit_streak": row.get("exit_streak"),
                    "shakeout_guard_active": row.get("shakeout_guard_active"),
                    "rs_qqq_1m": row.get("rs_qqq_1m"),
                    "rs_qqq_3m": row.get("rs_qqq_3m"),
                    "rs_qqq_6m": row.get("rs_qqq_6m"),
                    "sector_leadership_score": row.get("sector_leadership_score"),
                    "price_structure_state": "above_ma50_ma200"
                    if safe_float(row.get("price_above_ma50"), 1.0) >= 0.5 and safe_float(row.get("price_above_ma200"), 1.0) >= 0.5
                    else "broken_price_structure",
                }
            )
        for variant in variants:
            prev_weights = prev_holdings_by_variant.get(variant.variant_id, {})
            selected = select_market_leader_targets(scored, variant, prev_holdings=prev_weights)
            selected = apply_benchmark_risk_overlay(selected, variant, prices, dt)
            new_weights: dict[str, float] = {}
            if not selected.empty:
                selected = selected.copy()
                tickers = selected["ticker"].astype(str).str.upper().tolist()
                prev_streak = holding_streak_by_variant.get(variant.variant_id, {})
                holding_months = {ticker: int(prev_streak.get(ticker, 0)) + 1 for ticker in tickers}
                selected["holding_months"] = selected["ticker"].astype(str).str.upper().map(holding_months).fillna(1).astype(int)
                new_weights = {
                    str(row.ticker).upper(): safe_float(row.weight)
                    for row in selected.itertuples(index=False)
                    if str(row.ticker).upper() != "CASH"
                }
                holding_streak_by_variant[variant.variant_id] = holding_months
            else:
                holding_streak_by_variant[variant.variant_id] = {}
            rows = target_rows_from_selection(selected, variant, dt)
            target_rows[variant.variant_id].extend(rows)
            all_weight_keys = set(prev_weights) | set(new_weights)
            turnover_proxy = 0.5 * sum(abs(float(new_weights.get(ticker, 0.0)) - float(prev_weights.get(ticker, 0.0))) for ticker in all_weight_keys)
            prev_names = {ticker for ticker, weight in prev_weights.items() if weight > 1e-12}
            new_names = {ticker for ticker, weight in new_weights.items() if weight > 1e-12}
            state_lookup = {
                str(row.get("ticker") or "").upper(): str(row.get("leader_state") or "")
                for row in scored.to_dict("records")
            }
            residual_reason = ""
            if rows:
                residual_reason = str(next((row.get("residual_cash_reason") for row in rows if row.get("residual_cash_reason")), "") or "")
            churn_rows.append(
                {
                    "rebalance_date": dt.date().isoformat(),
                    "portfolio_kind": variant.portfolio_kind,
                    "variant_id": variant.variant_id,
                    "avg_name_overlap": (len(prev_names & new_names) / max(len(prev_names), 1)) if prev_names else 0.0,
                    "monthly_turnover_proxy": turnover_proxy,
                    "median_holding_months": float(selected["holding_months"].median()) if not selected.empty and "holding_months" in selected.columns else 0.0,
                    "leader_exit_count": int(sum(1 for ticker in prev_names if state_lookup.get(ticker) == "EXIT_REPLACE")),
                    "warning_hold_count": int((selected["leader_state"].astype(str).eq("WARNING")).sum()) if not selected.empty else 0,
                    "shakeout_guard_count": int((selected["leader_state"].astype(str).eq("SHAKEOUT_GUARD")).sum()) if not selected.empty else 0,
                    "benchmark_risk_score": float(pd.to_numeric(selected.get("benchmark_risk_score", pd.Series(dtype=float)), errors="coerce").max())
                    if not selected.empty
                    else 0.0,
                    "gross_exposure_cap": float(pd.to_numeric(selected.get("gross_exposure_cap", pd.Series(dtype=float)), errors="coerce").min())
                    if not selected.empty
                    else 1.0,
                    "market_regime": str(selected.get("market_regime", pd.Series(dtype=str)).iloc[0]) if not selected.empty and "market_regime" in selected.columns else "",
                    "residual_cash_reason": residual_reason,
                }
            )
            prev_holdings_by_variant[variant.variant_id] = new_weights
            if dt == latest_dt and variant.variant_id in {DEFAULT_MAIN_VARIANT, DEFAULT_CONCENTRATED_VARIANT}:
                default_latest_rows.extend(rows)
            if variant.variant_id in {DEFAULT_MAIN_VARIANT, DEFAULT_CONCENTRATED_VARIANT}:
                selected_tickers = {str(x).upper() for x in selected.get("ticker", pd.Series(dtype=str)).tolist()} if not selected.empty else set()
                score_col = "concentrated_leader_score" if variant.portfolio_kind == "concentrated" else "main_leader_score"
                review = scored.sort_values(score_col, ascending=False).head(50)
                for rank, (_, row) in enumerate(review.iterrows(), start=1):
                    reason = rejection_reason(row, selected_tickers, variant, selected)
                    if reason == "selected":
                        continue
                    rejected_rows.append(
                        {
                            "rebalance_date": dt.date().isoformat(),
                            "portfolio_kind": variant.portfolio_kind,
                            "variant_id": variant.variant_id,
                            "ticker": row.get("ticker"),
                            "leader_tier": row.get("leader_tier"),
                            "would_have_rank": rank,
                            "rejection_reason": reason,
                            "rs_spy_3m": row.get("rs_spy_3m"),
                            "rs_qqq_3m": row.get("rs_qqq_3m"),
                            "rs_qqq_6m": row.get("rs_qqq_6m"),
                            "sector_leadership_score": row.get("sector_leadership_score"),
                            "future_winner_score": row.get("future_winner_confirmation_score"),
                            "smart_money_confirmation_score": row.get("smart_money_confirmation_score"),
                            "chase_risk_score": row.get("leader_chase_risk_score"),
                            "liquidity_capacity_score": row.get("liquidity_capacity_score"),
                            "valuation_risk": row.get("overheat_penalty", ""),
                            "missing_data_flags": "" if bool(row.get("rs_price_coverage_flag")) else "missing_price_history",
                        }
                    )
                if not selected.empty:
                    attribution_rows.append(
                        {
                            "rebalance_date": dt.date().isoformat(),
                            "portfolio_kind": variant.portfolio_kind,
                            "variant_id": variant.variant_id,
                            "position_count": int(selected["ticker"].nunique()),
                            "avg_market_leader_tape_score": float(pd.to_numeric(selected["market_leader_tape_score"], errors="coerce").mean()),
                            "avg_sector_leadership_score": float(pd.to_numeric(selected["sector_leadership_score"], errors="coerce").mean()),
                            "avg_future_winner_confirmation_score": float(pd.to_numeric(selected["future_winner_confirmation_score"], errors="coerce").mean()),
                            "avg_smart_money_confirmation_score": float(pd.to_numeric(selected["smart_money_confirmation_score"], errors="coerce").mean()),
                            "avg_leader_chase_risk_score": float(pd.to_numeric(selected["leader_chase_risk_score"], errors="coerce").mean()),
                            "dual_leader_share": float(selected["leader_tier"].astype(str).eq("DUAL_LEADER").mean()),
                            "evidence_confidence_avg": float(pd.to_numeric(selected["smart_money_evidence_confidence"], errors="coerce").mean()),
                        }
                    )

    return {
        "prices": prices,
        "target_rows": target_rows,
        "leader_state_history": pd.DataFrame(state_rows),
        "selected_leaders_latest": pd.DataFrame(default_latest_rows),
        "leader_state_latest": pd.DataFrame(state_rows)[lambda x: x["rebalance_date"].eq(pd.Timestamp(latest_dt).date().isoformat())] if latest_dt is not None and state_rows else pd.DataFrame(),
        "rejected_leaders": pd.DataFrame(rejected_rows),
        "attribution_by_component": pd.DataFrame(attribution_rows),
        "holding_churn_diagnostics": pd.DataFrame(churn_rows),
    }


def write_variant_target_book(rows: list[dict[str, Any]], path: Path) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    cols = target_book_columns()
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    df = df[cols]
    df.to_csv(path, index=False)
    return df


def run_broker_variant(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    cost_bps: float,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    try:
        metrics = broker_replay(
            target_book=target_book,
            price_cache=price_cache,
            output_dir=output_dir,
            portfolio_kind=portfolio_kind,
            fill_mode="next_close",
            cost_bps=cost_bps,
            integer_shares=True,
            max_fill_lag_days=max_fill_lag_days,
            concentrated_champion_filters=DISABLE_CONCENTRATED_CHAMPION_FILTERS.copy(),
        )
    except Exception as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
            "status": "error",
            "metric_mode": "DO_NOT_USE",
            "reason": str(exc),
            "research_only": True,
            "valid_for_production": False,
        }
        write_json(output_dir / "metrics.json", metrics)
    if metrics.get("metric_mode") != "broker_ledger_next_close":
        metrics["metric_mode_review"] = "DO_NOT_USE"
        metrics["valid_for_production"] = False
    metrics["research_only"] = True
    metrics["production_activation_allowed"] = False
    return metrics


def cost_label(cost_bps: float) -> str:
    if float(cost_bps).is_integer():
        return f"{int(cost_bps)}bps"
    return f"{cost_bps:g}bps"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def metric_delta(candidate: dict[str, Any], baseline: dict[str, Any], key: str) -> float | None:
    lhs = safe_float(candidate.get(key), math.nan)
    rhs = safe_float(baseline.get(key), math.nan)
    if not math.isfinite(lhs) or not math.isfinite(rhs):
        return None
    return lhs - rhs


def grid_row(
    variant: MarketLeaderVariant,
    metrics: dict[str, Any],
    baseline_metrics: dict[str, Any] | None,
    target_book: Path,
) -> dict[str, Any]:
    row = {
        "variant_id": variant.variant_id,
        "portfolio_kind": variant.portfolio_kind,
        "target_n": variant.target_n,
        "single_cap": variant.single_cap,
        "subindustry_cap": variant.subindustry_cap,
        "theme_cap": variant.theme_cap,
        "risk_mode": variant.risk_mode,
        "status": metrics.get("status", "missing"),
        "metric_mode": metrics.get("metric_mode", metrics.get("metric_mode_review", "")),
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "trade_count": metrics.get("trade_count"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "target_book": str(target_book),
        "research_only": True,
        "production_activation_allowed": False,
    }
    if baseline_metrics:
        row["cagr_delta_vs_baseline"] = metric_delta(metrics, baseline_metrics, "cagr")
        row["mdd_improvement_vs_baseline"] = metric_delta(metrics, baseline_metrics, "max_dd")
    else:
        row["cagr_delta_vs_baseline"] = ""
        row["mdd_improvement_vs_baseline"] = ""
    return row


def broker_completed(metrics: dict[str, Any]) -> bool:
    return (
        str(metrics.get("status") or "") == "completed"
        and str(metrics.get("metric_mode") or "") == "broker_ledger_next_close"
        and str(metrics.get("metric_mode_review") or "") != "DO_NOT_USE"
    )


def churn_summary(churn: pd.DataFrame) -> pd.DataFrame:
    if churn.empty or "variant_id" not in churn.columns:
        return pd.DataFrame()
    numeric = churn.copy()
    for col in [
        "monthly_turnover_proxy",
        "avg_name_overlap",
        "median_holding_months",
        "leader_exit_count",
        "warning_hold_count",
        "shakeout_guard_count",
        "benchmark_risk_score",
        "gross_exposure_cap",
    ]:
        if col in numeric.columns:
            numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    rows = []
    for variant_id, group in numeric.groupby("variant_id"):
        rows.append(
            {
                "variant_id": variant_id,
                "avg_monthly_turnover": float(group.get("monthly_turnover_proxy", pd.Series(dtype=float)).mean()),
                "avg_name_overlap": float(group.get("avg_name_overlap", pd.Series(dtype=float)).mean()),
                "median_holding_months": float(group.get("median_holding_months", pd.Series(dtype=float)).median()),
                "leader_exit_count": int(group.get("leader_exit_count", pd.Series(dtype=float)).sum()),
                "warning_hold_count": int(group.get("warning_hold_count", pd.Series(dtype=float)).sum()),
                "shakeout_guard_count": int(group.get("shakeout_guard_count", pd.Series(dtype=float)).sum()),
                "avg_benchmark_risk_score": float(group.get("benchmark_risk_score", pd.Series(dtype=float)).mean()),
                "min_gross_exposure_cap": float(group.get("gross_exposure_cap", pd.Series(dtype=float)).min()),
            }
        )
    return pd.DataFrame(rows)


def max_drawdown(values: pd.Series) -> float | None:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return None
    peak = x.cummax()
    dd = x / peak - 1.0
    return float(dd.min())


def window_metrics(equity_path: Path, portfolio_kind: str, variant_id: str) -> list[dict[str, Any]]:
    eq = read_table(equity_path)
    if eq.empty or "date" not in eq.columns or "equity_usd" not in eq.columns:
        return []
    eq = eq.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date")
    rows: list[dict[str, Any]] = []
    latest_end = pd.Timestamp(eq["date"].max()).normalize()
    for name, (raw_start, raw_end) in STRESS_WINDOWS.items():
        start = latest_end - pd.DateOffset(months=12) if raw_start == "LATEST_12M" else pd.Timestamp(raw_start)
        end = latest_end if raw_end == "LATEST" else pd.Timestamp(raw_end)
        part = eq[(eq["date"] >= start) & (eq["date"] <= end)].copy()
        if part.empty:
            continue
        first = safe_float(part["equity_usd"].iloc[0], math.nan)
        last = safe_float(part["equity_usd"].iloc[-1], math.nan)
        rows.append(
            {
                "portfolio_kind": portfolio_kind,
                "variant_id": variant_id,
                "window": name,
                "start": start.date().isoformat(),
                "end": end.date().isoformat(),
                "window_return": (last / first - 1.0) if math.isfinite(first) and first > 0 and math.isfinite(last) else "",
                "window_mdd": max_drawdown(part["equity_usd"]),
                "avg_cash_weight": float(pd.to_numeric(part.get("cash_weight", pd.Series(dtype=float)), errors="coerce").mean())
                if "cash_weight" in part.columns
                else "",
                "position_count_avg": float(pd.to_numeric(part.get("position_count", pd.Series(dtype=float)), errors="coerce").mean())
                if "position_count" in part.columns
                else "",
            }
        )
    return rows


def benchmark_return(prices: dict[str, pd.DataFrame], ticker: str, date_like: Any) -> tuple[pd.Timestamp | None, float | None]:
    return price_on_or_before(prices.get(ticker, pd.DataFrame()), date_like, "close")


def benchmark_relative_metrics(
    equity_path: Path,
    prices: dict[str, pd.DataFrame],
    portfolio_kind: str,
    variant_id: str,
) -> list[dict[str, Any]]:
    eq = read_table(equity_path)
    if eq.empty or "date" not in eq.columns or "equity_usd" not in eq.columns:
        return []
    eq = eq.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date")
    portfolio_mdd = max_drawdown(eq["equity_usd"])
    start = pd.Timestamp(eq["date"].iloc[0])
    end = pd.Timestamp(eq["date"].iloc[-1])
    rows: list[dict[str, Any]] = []
    for benchmark in BENCHMARKS:
        _, start_px = benchmark_return(prices, benchmark, start)
        _, end_px = benchmark_return(prices, benchmark, end)
        curve_vals: list[float] = []
        if start_px and start_px > 0:
            for dt in eq["date"]:
                _, px = benchmark_return(prices, benchmark, dt)
                curve_vals.append(float(px / start_px) if px else np.nan)
        bench_mdd = max_drawdown(pd.Series(curve_vals)) if curve_vals else None
        bench_ret = (float(end_px / start_px - 1.0) if start_px and end_px and start_px > 0 else None)
        port_first = safe_float(eq["equity_usd"].iloc[0], math.nan)
        port_last = safe_float(eq["equity_usd"].iloc[-1], math.nan)
        port_ret = port_last / port_first - 1.0 if math.isfinite(port_first) and port_first > 0 and math.isfinite(port_last) else None
        rows.append(
            {
                "portfolio_kind": portfolio_kind,
                "variant_id": variant_id,
                "benchmark": benchmark,
                "portfolio_return": port_ret,
                "benchmark_return": bench_ret,
                "excess_return": (port_ret - bench_ret) if port_ret is not None and bench_ret is not None else None,
                "portfolio_mdd": portfolio_mdd,
                "benchmark_mdd": bench_mdd,
                "relative_mdd_gap": (portfolio_mdd - bench_mdd) if portfolio_mdd is not None and bench_mdd is not None else None,
            }
        )
    return rows


def parameter_stability(grid: pd.DataFrame) -> pd.DataFrame:
    if grid.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for portfolio_kind, group in grid.groupby("portfolio_kind"):
        completed = group[group["status"].astype(str).eq("completed")].copy()
        if completed.empty:
            rows.append({"portfolio_kind": portfolio_kind, "status": "no_completed_variants"})
            continue
        completed["cagr_num"] = pd.to_numeric(completed["cagr"], errors="coerce")
        completed["max_dd_num"] = pd.to_numeric(completed["max_dd"], errors="coerce")
        completed = completed.dropna(subset=["cagr_num", "max_dd_num"])
        if completed.empty:
            rows.append({"portfolio_kind": portfolio_kind, "status": "no_numeric_metrics"})
            continue
        best = completed.sort_values(["cagr_num", "max_dd_num"], ascending=[False, False]).iloc[0]
        top3 = completed.sort_values(["cagr_num", "max_dd_num"], ascending=[False, False]).head(3)
        rows.append(
            {
                "portfolio_kind": portfolio_kind,
                "status": "completed",
                "variant_count": int(len(completed)),
                "best_variant_id": best["variant_id"],
                "best_cagr": best["cagr_num"],
                "median_cagr": float(completed["cagr_num"].median()),
                "top3_median_cagr": float(top3["cagr_num"].median()),
                "best_mdd": best["max_dd_num"],
                "median_mdd": float(completed["max_dd_num"].median()),
                "top3_median_mdd": float(top3["max_dd_num"].median()),
                "best_is_extreme_parameter": bool(
                    int(best["target_n"]) in {int(completed["target_n"].min()), int(completed["target_n"].max())}
                    and safe_float(best["single_cap"]) in {float(completed["single_cap"].min()), float(completed["single_cap"].max())}
                ),
                "best_vs_median_cagr_delta": float(best["cagr_num"] - completed["cagr_num"].median()),
                "parameter_stability_warning": bool((best["cagr_num"] - completed["cagr_num"].median()) > 0.05),
            }
        )
    return pd.DataFrame(rows)


def render_report(summary: dict[str, Any], main_rows: list[dict[str, Any]], concentrated_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Market Leader Concentration Challenger",
        "",
        "Research-only sidecar. It rebuilds monthly target books from the historical candidate book and replays them through broker-ledger next-close.",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Candidate source: `{summary.get('candidate_source_mode')}`",
        f"- Promotion evaluation: `{summary.get('promotion_evaluation_status')}`",
        f"- Production activation allowed: `{str(summary.get('production_activation_allowed')).lower()}`",
        "",
        "## Default Variants",
        "",
    ]
    for label, rows in (("Main", main_rows), ("Concentrated", concentrated_rows)):
        if not rows:
            lines.append(f"- {label}: no completed variant")
            continue
        row = rows[0]
        lines.append(
            f"- {label} `{row.get('variant_id')}`: CAGR {pct(row.get('cagr'))}, MDD {pct(row.get('max_dd'))}, Sharpe {safe_float(row.get('sharpe'), 0.0):.3f}, mode `{row.get('metric_mode')}`"
        )
    lines.extend(
        [
            "",
            "Rules:",
            "- Latest-only rankings are blocked from producing broker metrics.",
            "- Missing 13F/Form4/ETF evidence lowers confidence only; it is not a quality penalty.",
            "- Production defaults, feature store, and live target books are unchanged.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--candidate-book", default=None)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--cost-bps-list", nargs="*", type=float, default=[25.0, 50.0, 75.0, 100.0])
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--baseline-lock", default=None)
    parser.add_argument("--allow-missing-baseline-lock", action="store_true")
    parser.add_argument("--max-grid-variants", type=int, default=0, help="0 means all variants")
    parser.add_argument("--default-only", action="store_true", help="Run only the default main/concentrated variants")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    candidate_book, source_mode = resolve_candidate_book(latest_run, args.candidate_book)
    frame = normalize_candidate_frame(read_table(candidate_book))
    unique_dates = sorted(frame["rebalance_date"].dropna().unique()) if not frame.empty and "rebalance_date" in frame.columns else []
    if source_mode == "latest_only_blocked" or len(unique_dates) < 3:
        blocked_outputs(
            output_dir,
            "historical candidate_replay_book with at least three rebalance dates is required; latest-only ranking cannot produce broker metrics",
            candidate_book,
            source_mode,
        )
        return 0
    if frame.empty:
        blocked_outputs(output_dir, "candidate replay book is empty or invalid", candidate_book, source_mode)
        return 0

    variants = default_variants()
    if args.portfolio_kind != "both":
        variants = variant_filter(args.portfolio_kind, variants)
    if args.default_only:
        wanted = {DEFAULT_MAIN_VARIANT, DEFAULT_CONCENTRATED_VARIANT}
        variants = [variant for variant in variants if variant.variant_id in wanted]
    if args.max_grid_variants and args.max_grid_variants > 0:
        variants = variants[: int(args.max_grid_variants)]

    build = build_target_books(frame, price_cache, variants)
    target_root = output_dir / "variant_target_books"
    replay_root = output_dir / "broker_replay"
    sensitivity_root = output_dir / "broker_replay_cost_sensitivity"
    grid_rows: list[dict[str, Any]] = []
    stress_rows: list[dict[str, Any]] = []
    bench_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    metrics_by_variant: dict[str, dict[str, Any]] = {}
    target_paths_by_variant: dict[str, Path] = {}

    baseline_lock_path = repo_path(args.baseline_lock) if args.baseline_lock else None
    baseline_payload = load_json(baseline_lock_path) if baseline_lock_path else {}
    promotion_status = "blocked_missing_baseline_lock" if not baseline_payload else "baseline_lock_loaded"
    if args.allow_missing_baseline_lock and not baseline_payload:
        promotion_status = "research_only_no_baseline_lock"

    for variant in variants:
        rows = build["target_rows"].get(variant.variant_id, [])
        target_path = target_root / f"{variant.variant_id}.csv"
        target_paths_by_variant[variant.variant_id] = target_path
        target_df = write_variant_target_book(rows, target_path)
        if target_df.empty:
            metrics = {"status": "blocked", "reason": "empty market leader target book", "metric_mode": "DO_NOT_USE"}
        else:
            metrics = run_broker_variant(
                target_book=target_path,
                price_cache=price_cache,
                output_dir=replay_root / variant.variant_id,
                portfolio_kind=variant.portfolio_kind,
                cost_bps=args.cost_bps,
                max_fill_lag_days=args.max_fill_lag_days,
            )
        metrics_by_variant[variant.variant_id] = metrics
        baseline_metrics = {}
        if baseline_payload:
            key = "main" if variant.portfolio_kind == "main" else "concentrated"
            baseline_metrics = baseline_payload.get(key) or baseline_payload.get(f"{key}_metrics") or {}
        grid_rows.append(grid_row(variant, metrics, baseline_metrics, target_path))
        stress_rows.extend(window_metrics(replay_root / variant.variant_id / "equity_curve.csv", variant.portfolio_kind, variant.variant_id))
        bench_rows.extend(benchmark_relative_metrics(replay_root / variant.variant_id / "equity_curve.csv", build["prices"], variant.portfolio_kind, variant.variant_id))

    output_dir.mkdir(parents=True, exist_ok=True)
    grid = pd.DataFrame(grid_rows)
    churn = build["holding_churn_diagnostics"]
    churn.to_csv(output_dir / "holding_churn_diagnostics.csv", index=False)
    churn_agg = churn_summary(churn)
    if not grid.empty and not churn_agg.empty:
        grid = grid.merge(churn_agg, on="variant_id", how="left")

    cost_values = sorted({float(args.cost_bps), *[float(x) for x in (args.cost_bps_list or [])]})
    default_variant_ids = {
        DEFAULT_MAIN_VARIANT if DEFAULT_MAIN_VARIANT in metrics_by_variant else next((v.variant_id for v in variants if v.portfolio_kind == "main"), ""),
        DEFAULT_CONCENTRATED_VARIANT if DEFAULT_CONCENTRATED_VARIANT in metrics_by_variant else next((v.variant_id for v in variants if v.portfolio_kind == "concentrated"), ""),
    }
    default_variant_ids.discard("")
    variant_by_id = {variant.variant_id: variant for variant in variants}
    for variant_id in sorted(default_variant_ids):
        variant = variant_by_id.get(variant_id)
        target_path = target_paths_by_variant.get(variant_id)
        if variant is None or target_path is None or not target_path.exists():
            continue
        for cost_bps in cost_values:
            if abs(float(cost_bps) - float(args.cost_bps)) < 1e-9:
                metrics = metrics_by_variant.get(variant_id, {})
            else:
                metrics = run_broker_variant(
                    target_book=target_path,
                    price_cache=price_cache,
                    output_dir=sensitivity_root / variant_id / cost_label(cost_bps),
                    portfolio_kind=variant.portfolio_kind,
                    cost_bps=float(cost_bps),
                    max_fill_lag_days=args.max_fill_lag_days,
                )
            cost_rows.append(
                {
                    "portfolio_kind": variant.portfolio_kind,
                    "variant_id": variant_id,
                    "cost_bps": float(cost_bps),
                    "status": metrics.get("status", "missing"),
                    "metric_mode": metrics.get("metric_mode", metrics.get("metric_mode_review", "")),
                    "cagr": metrics.get("cagr"),
                    "max_dd": metrics.get("max_dd"),
                    "sharpe": metrics.get("sharpe"),
                    "trade_count": metrics.get("trade_count"),
                    "total_fees_usd": metrics.get("total_fees_usd"),
                    "avg_cash_weight": metrics.get("avg_cash_weight"),
                    "research_only": True,
                    "production_activation_allowed": False,
                }
            )
    pd.DataFrame(cost_rows).to_csv(output_dir / "cost_sensitivity.csv", index=False)

    grid.to_csv(output_dir / "grid_results.csv", index=False)
    pd.DataFrame(stress_rows).to_csv(output_dir / "stress_window_metrics.csv", index=False)
    pd.DataFrame(bench_rows).to_csv(output_dir / "benchmark_relative_metrics.csv", index=False)
    build["leader_state_history"].to_csv(output_dir / "leader_state_history.csv", index=False)
    build["leader_state_latest"].to_csv(output_dir / "leader_state_latest.csv", index=False)
    build["selected_leaders_latest"].to_csv(output_dir / "selected_leaders_latest.csv", index=False)
    build["rejected_leaders"].to_csv(output_dir / "rejected_leaders.csv", index=False)
    build["attribution_by_component"].to_csv(output_dir / "attribution_by_component.csv", index=False)
    stability = parameter_stability(grid)
    stability.to_csv(output_dir / "parameter_stability.csv", index=False)

    default_main = DEFAULT_MAIN_VARIANT if DEFAULT_MAIN_VARIANT in metrics_by_variant else next((v.variant_id for v in variants if v.portfolio_kind == "main"), "")
    default_conc = DEFAULT_CONCENTRATED_VARIANT if DEFAULT_CONCENTRATED_VARIANT in metrics_by_variant else next((v.variant_id for v in variants if v.portfolio_kind == "concentrated"), "")
    if default_main:
        write_variant_target_book(build["target_rows"].get(default_main, []), output_dir / "main_target_book.csv")
        write_json(output_dir / "main_metrics.json", metrics_by_variant.get(default_main, {}))
    else:
        pd.DataFrame().to_csv(output_dir / "main_target_book.csv", index=False)
        write_json(output_dir / "main_metrics.json", {"status": "blocked", "reason": "main variants not run", "metric_mode": "DO_NOT_USE"})
    if default_conc:
        write_variant_target_book(build["target_rows"].get(default_conc, []), output_dir / "concentrated_target_book.csv")
        write_json(output_dir / "concentrated_metrics.json", metrics_by_variant.get(default_conc, {}))
    else:
        pd.DataFrame().to_csv(output_dir / "concentrated_target_book.csv", index=False)
        write_json(output_dir / "concentrated_metrics.json", {"status": "blocked", "reason": "concentrated variants not run", "metric_mode": "DO_NOT_USE"})

    main_default_rows = grid[grid["variant_id"].eq(default_main)].to_dict("records") if default_main and not grid.empty else []
    conc_default_rows = grid[grid["variant_id"].eq(default_conc)].to_dict("records") if default_conc and not grid.empty else []
    required_default_metrics: list[dict[str, Any]] = []
    if args.portfolio_kind in {"main", "both"}:
        required_default_metrics.append(metrics_by_variant.get(default_main, {}))
    if args.portfolio_kind in {"concentrated", "both"}:
        required_default_metrics.append(metrics_by_variant.get(default_conc, {}))
    defaults_completed = bool(required_default_metrics) and all(broker_completed(metrics) for metrics in required_default_metrics)
    summary_status = "completed" if defaults_completed else "partial_or_blocked"
    summary_metric_mode = "broker_ledger_next_close" if defaults_completed else "DO_NOT_USE"
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "status": summary_status,
        "candidate_book": str(candidate_book),
        "candidate_source_mode": source_mode,
        "rebalance_date_count": int(len(unique_dates)),
        "first_rebalance_date": pd.Timestamp(unique_dates[0]).date().isoformat() if unique_dates else "",
        "last_rebalance_date": pd.Timestamp(unique_dates[-1]).date().isoformat() if unique_dates else "",
        "variant_count": int(len(variants)),
        "default_main_variant_id": default_main,
        "default_concentrated_variant_id": default_conc,
        "promotion_evaluation_status": promotion_status,
        "baseline_lock": str(baseline_lock_path) if baseline_lock_path else "",
        "official_metric_required": "broker_ledger_next_close",
        "research_only": True,
        "production_activation_allowed": False,
        "feature_store_mutated": False,
        "score_total_changed": False,
        "production_target_defaults_changed": False,
        "metric_mode": summary_metric_mode,
        "default_variants_completed_broker_ledger": defaults_completed,
        "cost_sensitivity_path": str(output_dir / "cost_sensitivity.csv"),
        "holding_churn_diagnostics_path": str(output_dir / "holding_churn_diagnostics.csv"),
    }
    write_json(output_dir / "summary.json", summary)
    write_text(output_dir / "report.md", render_report(summary, main_default_rows, conc_default_rows))
    print(f"[market-leader] wrote {output_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
