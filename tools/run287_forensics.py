#!/usr/bin/env python3
"""Build a leakage-guarded forensic package for GitHub Actions run 28725350727.

This tool does not dispatch workflows, retune thresholds, or create alpha hooks.
It only reuses existing artifacts to separate measurement/window/book effects.
Exact cash-carry replay is reported as blocked when the replay price cache is
not present, because estimating it from equity curves would change the metric
contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import calc_metrics  # noqa: E402
from tools.alphaops_governance import (  # noqa: E402
    measurement_contract_acceptance_blockers,
    measurement_contract_caveat_fields,
)


PORTFOLIOS = ("main", "concentrated")
DEFAULT_RUN_ROOT = "outputs/run_28725350727_user_operating_artifact/outputs"
DEFAULT_FROZEN_ROOT = "outputs/policy_path_combo_probe_20260704_final_candidate"
DEFAULT_OUTPUT_DIR = "outputs/run287_forensics"
DEFAULT_PRICE_CACHE = "outputs/run287_price_cache_latest/cache_prices"
DEFAULT_METRIC_SIDECAR_ROOT = "outputs/run287_metric_sidecar"
DEFAULT_PARITY_SUMMARY = "outputs/run287_parity/summary.json"
DEFAULT_SURVIVORSHIP_SUMMARY = "outputs/run287_survivorship/summary.json"

HOOK_COLUMNS = {
    "main": [
        "main_post_selection_topn_filter_enabled",
        "main_post_selection_topn_filter_applied",
        "main_post_selection_topn_target_n",
        "main_ai_capex_momentum_tilt_enabled",
        "main_ai_capex_momentum_tilt_applied",
        "main_ai_capex_momentum_tilt_strength",
    ],
    "concentrated": [
        "concentrated_replacement_quality_enabled",
        "concentrated_replacement_quality_applied",
        "concentrated_replacement_quality_status",
        "concentrated_cashfunded_early_entry_enabled",
        "concentrated_cashfunded_early_entry_applied",
        "concentrated_cashfunded_early_entry_add_weight",
        "concentrated_cashfunded_early_entry_min_breakout_quality",
    ],
}
ACCEPTANCE_STYLE_LABELS = {
    "measurement_mismatch_only",
    "production_blocked_research_pass",
    "ready_for_human_review",
    "research_7y_fullrun_pass",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def target_book_path(root: Path, portfolio: str) -> Path:
    alphaops = root / "alphaops_vnext" / f"official_{portfolio}_target_book.csv"
    if alphaops.exists():
        return alphaops
    reports_name = "operating_main_target_book.csv" if portfolio == "main" else "operating_concentrated_target_book.csv"
    reports = root / "reports" / reports_name
    if reports.exists():
        return reports
    return root / f"official_{portfolio}_target_book.csv"


def frozen_cash_carry_metrics_path(frozen_root: Path, portfolio: str) -> Path:
    name = "broker_main_cash_carry" if portfolio == "main" else "broker_concentrated_cash_carry"
    return frozen_root / name / "metrics.json"


def normalize_book(path: Path) -> pd.DataFrame:
    frame = load_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "target_weight"])
    if "rebalance_date" not in frame.columns or "ticker" not in frame.columns:
        return pd.DataFrame(columns=["rebalance_date", "ticker", "target_weight"])
    frame = frame.copy()
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    if "target_weight" not in frame.columns:
        if "weight" in frame.columns:
            frame["target_weight"] = frame["weight"]
        else:
            frame["target_weight"] = 0.0
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce").fillna(0.0)
    if "period_forward_return" in frame.columns:
        frame["period_forward_return"] = pd.to_numeric(frame["period_forward_return"], errors="coerce")
    return frame.dropna(subset=["rebalance_date"]).copy()


def metric_subset(metrics: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "status",
        "metric_mode",
        "start_date",
        "end_date",
        "actual_equity_curve_end_date",
        "replay_end_date_clamped",
        "cagr",
        "max_dd",
        "sharpe",
        "avg_cash_weight",
        "starting_capital_usd",
        "ending_capital_usd",
        "trade_count",
    ]
    return {key: metrics.get(key) for key in keep if key in metrics}


def read_official_metrics(run_root: Path, portfolio: str) -> dict[str, Any]:
    return read_json(run_root / "broker_replay" / portfolio / "metrics.json")


def sidecar_metrics_path(sidecar_root: Path, arm: str, portfolio: str) -> Path:
    return sidecar_root / arm / portfolio / "metrics.json"


def metric_target_pass(metrics: dict[str, Any], portfolio: str) -> bool:
    cagr = safe_float(metrics.get("cagr"))
    max_dd = safe_float(metrics.get("max_dd"))
    if cagr is None or max_dd is None:
        return False
    target_cagr = 0.35 if portfolio == "main" else 0.50
    return cagr >= target_cagr and max_dd >= -0.25


def build_metric_sidecar_summary(
    run_root: Path,
    sidecar_root: Path,
    output_dir: Path,
    contract_caveats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract_caveats = contract_caveats or {}
    arms = [
        ("official_run287_zero_yield", "official_run287_artifact", None),
        ("generated_book_zero_yield", "generated_book_latest_replay", "generated_book_zero_yield"),
        ("generated_book_cash_carry", "generated_book_latest_replay", "generated_book_cash_carry"),
    ]
    rows: list[dict[str, Any]] = []
    by_arm: dict[str, Any] = {}
    for arm, target_source, sidecar_arm in arms:
        arm_status = "completed"
        arm_portfolios: dict[str, Any] = {}
        for portfolio in PORTFOLIOS:
            if sidecar_arm is None:
                path = run_root / "broker_replay" / portfolio / "metrics.json"
            else:
                path = sidecar_metrics_path(sidecar_root, sidecar_arm, portfolio)
            metrics = metric_subset(read_json(path))
            if not metrics:
                metrics = {"status": "missing", "metric_mode": ""}
                arm_status = "missing_metrics"
            target_pass = metric_target_pass(metrics, portfolio)
            row = {
                "arm": arm,
                "portfolio": portfolio,
                "status": metrics.get("status"),
                "metric_mode": metrics.get("metric_mode"),
                "target_book_source": target_source,
                "metrics_path": display_path(path),
                "start_date": metrics.get("start_date"),
                "end_date": metrics.get("end_date") or metrics.get("actual_equity_curve_end_date"),
                "cagr": metrics.get("cagr"),
                "max_dd": metrics.get("max_dd"),
                "sharpe": metrics.get("sharpe"),
                "avg_cash_weight": metrics.get("avg_cash_weight"),
                "ending_capital_usd": metrics.get("ending_capital_usd"),
                "cash_interest_accrued_usd": read_json(path).get("cash_interest_accrued_usd") if path.exists() else None,
                "target_pass": target_pass,
                "production_promotion_allowed": False,
                "production_evidence_valid": False,
                "public_display_allowed": False,
                "live_trading_enabled": False,
                "runner_parity_status": contract_caveats.get("runner_parity_status", "missing"),
                "survivorship_inflation_estimate_cagr_pp": contract_caveats.get(
                    "survivorship_inflation_estimate_cagr_pp"
                ),
                "survivorship_inflation_label": contract_caveats.get("survivorship_inflation_label", "missing"),
                "survivorship_unmeasured_component": contract_caveats.get(
                    "survivorship_unmeasured_component", "missing"
                ),
            }
            rows.append(row)
            arm_portfolios[portfolio] = row
        by_arm[arm] = {
            "status": arm_status,
            "portfolios": arm_portfolios,
            "all_targets_pass": all(bool(arm_portfolios[p].get("target_pass")) for p in PORTFOLIOS),
        }
    row_frame = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    sidecar_root.mkdir(parents=True, exist_ok=True)
    row_frame.to_csv(output_dir / "metric_sidecar_arm_metrics.csv", index=False)
    row_frame.to_csv(sidecar_root / "arm_metrics.csv", index=False)
    summary = {
        "status": "completed" if by_arm.get("generated_book_cash_carry", {}).get("status") == "completed" else "partial",
        "sidecar_root": display_path(sidecar_root),
        "arms": by_arm,
        "latest_generated_book_cash_carry_pass": bool(
            by_arm.get("generated_book_cash_carry", {}).get("all_targets_pass")
        ),
        "runner_parity_status": contract_caveats.get("runner_parity_status", "missing"),
        "survivorship_inflation_estimate": contract_caveats.get("survivorship_inflation_estimate", {}),
        "survivorship_inflation_estimate_cagr_pp": contract_caveats.get(
            "survivorship_inflation_estimate_cagr_pp"
        ),
        "survivorship_inflation_label": contract_caveats.get("survivorship_inflation_label", "missing"),
        "survivorship_unmeasured_component": contract_caveats.get("survivorship_unmeasured_component", "missing"),
    }
    write_json(sidecar_root / "summary.json", summary)
    (sidecar_root / "report.md").write_text(render_metric_sidecar_report(summary), encoding="utf-8")
    return summary


def render_metric_sidecar_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Run287 Metric Sidecar",
        "",
        "Research-only generated-book replay package. No fullrun was dispatched.",
        "",
        "| Arm | Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Target pass |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for arm, arm_payload in summary.get("arms", {}).items():
        for portfolio in PORTFOLIOS:
            row = arm_payload.get("portfolios", {}).get(portfolio, {})
            lines.append(
                "| {arm} | {portfolio} | {mode} | {cagr:.2%} | {max_dd:.2%} | {sharpe:.3f} | {target_pass} |".format(
                    arm=arm,
                    portfolio=portfolio,
                    mode=row.get("metric_mode") or "",
                    cagr=float(row.get("cagr") or 0.0),
                    max_dd=float(row.get("max_dd") or 0.0),
                    sharpe=float(row.get("sharpe") or 0.0),
                    target_pass=bool(row.get("target_pass")),
                )
            )
    lines.extend(
        [
            "",
            "Cash-carry rows are official research accounting only. Production remains blocked by PIT membership.",
            "",
        ]
    )
    return "\n".join(lines)


def compute_window_metrics(run_root: Path, portfolio: str, end_date: str) -> dict[str, Any]:
    replay_dir = run_root / "broker_replay" / portfolio
    equity = load_csv(replay_dir / "equity_curve.csv")
    trades = load_csv(replay_dir / "trades.csv")
    if equity.empty:
        return {"status": "blocked", "reason": "missing_equity_curve", "portfolio": portfolio, "end_date": end_date}
    equity_dates = pd.to_datetime(equity["date"], errors="coerce")
    end_ts = pd.to_datetime(end_date, errors="coerce")
    equity = equity[equity_dates <= end_ts].copy()
    if not trades.empty and "date" in trades.columns:
        trade_dates = pd.to_datetime(trades["date"], errors="coerce")
        trades = trades[trade_dates <= end_ts].copy()
    official = read_official_metrics(run_root, portfolio)
    starting_capital = float(official.get("starting_capital_usd") or 100000.0)
    metrics = calc_metrics(equity, trades, starting_capital, label=f"{portfolio}_{end_date}")
    metrics["portfolio"] = portfolio
    metrics["requested_end_date"] = end_date
    metrics["source"] = "generated_book_equity_curve_truncation"
    return metrics


def build_window_attribution(run_root: Path, output_dir: Path, official_end: str, actual_end: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        official_metrics = read_official_metrics(run_root, portfolio)
        by_end = {
            official_end: compute_window_metrics(run_root, portfolio, official_end),
            actual_end: compute_window_metrics(run_root, portfolio, actual_end),
        }
        for end_date, metrics in by_end.items():
            row = {
                "portfolio": portfolio,
                "metric_mode": metrics.get("metric_mode"),
                "target_book_source": "run287_generated",
                "requested_end_date": end_date,
                "actual_end_date": metrics.get("end_date"),
                "cagr": metrics.get("cagr"),
                "max_dd": metrics.get("max_dd"),
                "sharpe": metrics.get("sharpe"),
                "ending_capital_usd": metrics.get("ending_capital_usd"),
                "trade_count": metrics.get("trade_count"),
            }
            rows.append(row)
        early = by_end[official_end]
        late = by_end[actual_end]
        early_cagr = safe_float(early.get("cagr"))
        late_cagr = safe_float(late.get("cagr"))
        early_equity = safe_float(early.get("ending_capital_usd"))
        late_equity = safe_float(late.get("ending_capital_usd"))
        summary[portfolio] = {
            "official_metrics_reproduced": (
                round(float(official_metrics.get("cagr", 0.0)), 12) == round(float(late.get("cagr", 0.0)), 12)
                and round(float(official_metrics.get("max_dd", 0.0)), 12) == round(float(late.get("max_dd", 0.0)), 12)
            ),
            "clamp_end": metric_subset(early),
            "actual_end": metric_subset(late),
            "delta_actual_minus_clamp": {
                "cagr": late_cagr - early_cagr if late_cagr is not None and early_cagr is not None else None,
                "cagr_pp": (late_cagr - early_cagr) * 100.0 if late_cagr is not None and early_cagr is not None else None,
                "ending_capital_usd": (
                    late_equity - early_equity if late_equity is not None and early_equity is not None else None
                ),
                "ending_capital_pct": (
                    late_equity / early_equity - 1.0
                    if late_equity is not None and early_equity not in (None, 0.0)
                    else None
                ),
            },
        }
    pd.DataFrame(rows).to_csv(output_dir / "window_attribution.csv", index=False)
    return summary


def compare_books(frozen_root: Path, run_root: Path, output_dir: Path) -> dict[str, Any]:
    date_rows: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        frozen_path = target_book_path(frozen_root, portfolio)
        generated_path = target_book_path(run_root, portfolio)
        frozen = normalize_book(frozen_path)
        generated = normalize_book(generated_path)
        frozen_dates = set(frozen["rebalance_date"]) if not frozen.empty else set()
        generated_dates = set(generated["rebalance_date"]) if not generated.empty else set()
        common_dates = sorted(frozen_dates & generated_dates)
        portfolio_date_rows: list[dict[str, Any]] = []
        portfolio_ticker_rows: list[pd.DataFrame] = []
        if common_dates:
            frozen_common = frozen[frozen["rebalance_date"].isin(common_dates)].copy()
            generated_common = generated[generated["rebalance_date"].isin(common_dates)].copy()
            frozen_common = frozen_common[frozen_common["ticker"] != "CASH"].copy()
            generated_common = generated_common[generated_common["ticker"] != "CASH"].copy()
            merged = frozen_common.rename(
                columns={"target_weight": "frozen_weight", "period_forward_return": "frozen_period_forward_return"}
            ).merge(
                generated_common.rename(
                    columns={"target_weight": "generated_weight", "period_forward_return": "generated_period_forward_return"}
                ),
                on=["rebalance_date", "ticker"],
                how="outer",
            )
            merged["frozen_weight"] = pd.to_numeric(merged.get("frozen_weight"), errors="coerce").fillna(0.0)
            merged["generated_weight"] = pd.to_numeric(merged.get("generated_weight"), errors="coerce").fillna(0.0)
            generated_return = pd.to_numeric(merged.get("generated_period_forward_return"), errors="coerce")
            frozen_return = pd.to_numeric(merged.get("frozen_period_forward_return"), errors="coerce")
            merged["period_forward_return"] = generated_return.combine_first(frozen_return).fillna(0.0)
            merged["delta_weight"] = merged["generated_weight"] - merged["frozen_weight"]
            merged["abs_delta_weight"] = merged["delta_weight"].abs()
            merged["proxy_delta_return"] = merged["delta_weight"] * merged["period_forward_return"]
            for date, group in merged.groupby("rebalance_date"):
                frozen_set = set(group.loc[group["frozen_weight"].abs() > 1e-12, "ticker"])
                generated_set = set(group.loc[group["generated_weight"].abs() > 1e-12, "ticker"])
                union = frozen_set | generated_set
                intersection = frozen_set & generated_set
                added = group[group["frozen_weight"].abs() <= 1e-12]
                dropped = group[group["generated_weight"].abs() <= 1e-12]
                row = {
                    "portfolio": portfolio,
                    "rebalance_date": date,
                    "ticker_overlap_jaccard": len(intersection) / len(union) if union else 1.0,
                    "frozen_ticker_count": len(frozen_set),
                    "generated_ticker_count": len(generated_set),
                    "added_ticker_count": int(len(added)),
                    "dropped_ticker_count": int(len(dropped)),
                    "added_weight": float(added["generated_weight"].sum()),
                    "dropped_weight": float(dropped["frozen_weight"].sum()),
                    "l1_weight_diff": float(group["abs_delta_weight"].sum()),
                    "proxy_delta_return": float(group["proxy_delta_return"].sum()),
                }
                portfolio_date_rows.append(row)
                date_rows.append(row)
            changed = merged[merged["abs_delta_weight"] > 1e-10].copy()
            if not changed.empty:
                ticker_agg = (
                    changed.groupby("ticker", as_index=False)
                    .agg(
                        changed_dates=("rebalance_date", "nunique"),
                        abs_delta_weight=("abs_delta_weight", "sum"),
                        proxy_delta_return=("proxy_delta_return", "sum"),
                    )
                    .sort_values("proxy_delta_return")
                )
                ticker_agg.insert(0, "portfolio", portfolio)
                portfolio_ticker_rows.append(ticker_agg)
                ticker_rows.extend(ticker_agg.to_dict(orient="records"))
        date_frame = pd.DataFrame(portfolio_date_rows)
        ticker_frame = pd.concat(portfolio_ticker_rows, ignore_index=True) if portfolio_ticker_rows else pd.DataFrame()
        summary[portfolio] = {
            "frozen_target_book": display_path(frozen_path),
            "generated_target_book": display_path(generated_path),
            "frozen_book_sha256": sha256_file(frozen_path),
            "generated_book_sha256": sha256_file(generated_path),
            "common_date_count": int(len(common_dates)),
            "frozen_only_date_count": int(len(frozen_dates - generated_dates)),
            "generated_only_date_count": int(len(generated_dates - frozen_dates)),
            "average_ticker_overlap": safe_float(date_frame["ticker_overlap_jaccard"].mean()) if not date_frame.empty else None,
            "min_ticker_overlap": safe_float(date_frame["ticker_overlap_jaccard"].min()) if not date_frame.empty else None,
            "average_l1_weight_diff": safe_float(date_frame["l1_weight_diff"].mean()) if not date_frame.empty else None,
            "max_l1_weight_diff": safe_float(date_frame["l1_weight_diff"].max()) if not date_frame.empty else None,
            "proxy_delta_return_sum": safe_float(date_frame["proxy_delta_return"].sum()) if not date_frame.empty else None,
            "top_drift_months": date_frame.sort_values("proxy_delta_return").head(10).to_dict(orient="records")
            if not date_frame.empty
            else [],
            "top_negative_tickers": ticker_frame.head(10).to_dict(orient="records") if not ticker_frame.empty else [],
        }
    pd.DataFrame(date_rows).to_csv(output_dir / "date_level_drift.csv", index=False)
    pd.DataFrame(ticker_rows).to_csv(output_dir / "ticker_level_drift.csv", index=False)
    return summary


def summarize_hook_telemetry(run_root: Path, output_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for portfolio in PORTFOLIOS:
        path = target_book_path(run_root, portfolio)
        frame = load_csv(path)
        portfolio_summary: dict[str, Any] = {"target_book": display_path(path)}
        if frame.empty:
            portfolio_summary["status"] = "missing_target_book"
            summary[portfolio] = portfolio_summary
            continue
        for column in HOOK_COLUMNS[portfolio]:
            if column not in frame.columns:
                continue
            series = frame[column]
            non_null = series.dropna()
            value_counts = non_null.astype(str).value_counts().head(20).to_dict()
            true_count = 0
            if series.dtype == bool:
                true_count = int(series.fillna(False).sum())
            else:
                true_count = int(series.astype(str).str.lower().isin({"true", "1", "yes"}).sum())
            unique_values = sorted(non_null.astype(str).unique().tolist())[:20]
            row = {
                "portfolio": portfolio,
                "column": column,
                "non_null_count": int(non_null.shape[0]),
                "true_like_count": true_count,
                "unique_values": "|".join(unique_values),
            }
            rows.append(row)
            portfolio_summary[column] = {
                "non_null_count": row["non_null_count"],
                "true_like_count": row["true_like_count"],
                "value_counts": value_counts,
            }
        summary[portfolio] = portfolio_summary
    pd.DataFrame(rows).to_csv(output_dir / "hook_telemetry.csv", index=False)
    return {
        "status": "telemetry_only_pending_counterfactual",
        "note": "Applied counts prove hooks were present, but do not prove contribution without a hook-off replay.",
        "portfolios": summary,
    }


def find_cash_rate_file(cache_macro: Path) -> Path:
    candidates = [
        cache_macro / "fred_dgs3mo_DGS3MO.parquet",
        cache_macro / "DGS3MO.parquet",
        cache_macro / "DGS3MO.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    for path in cache_macro.rglob("*DGS3MO*"):
        if path.is_file():
            return path
    return cache_macro / "fred_dgs3mo_DGS3MO.parquet"


def cash_carry_status(price_cache: Path, macro_cache: Path) -> dict[str, Any]:
    dgs3mo = find_cash_rate_file(macro_cache)
    price_manifest = price_cache / "replay_price_cache_manifest.json"
    price_files = [
        path
        for path in price_cache.rglob("*")
        if path.is_file() and path.name != "replay_price_cache_manifest.json"
    ] if price_cache.exists() else []
    if not price_cache.exists():
        status = "blocked_missing_price_cache"
        reason = "cache_prices is required for exact broker-ledger cash-carry replay and is absent locally"
    elif not price_manifest.exists():
        status = "blocked_missing_price_cache_manifest"
        reason = "cache_prices exists but replay_price_cache_manifest.json is missing"
    elif not price_files:
        status = "blocked_price_cache_manifest_only"
        reason = "cache_prices contains a manifest but no ticker price files for exact broker-ledger replay"
    else:
        status = "ready_for_exact_replay"
        reason = ""
    return {
        "status": status,
        "reason": reason,
        "price_cache_path": display_path(price_cache),
        "price_cache_exists": price_cache.exists(),
        "price_cache_manifest_exists": price_manifest.exists(),
        "price_cache_file_count_ex_manifest": len(price_files),
        "cash_rate_source": "DGS3MO",
        "cash_rate_cache_path": display_path(dgs3mo),
        "cash_rate_cache_exists": dgs3mo.exists(),
        "cash_rate_cache_sha256": sha256_file(dgs3mo),
        "contract": {
            "mode": "broker_ledger_next_close_cash_carry",
            "rate": "DGS3MO",
            "lag": "1BD",
            "day_count": "ACT/365",
            "haircut_bps": 50,
        },
    }


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Run 28725350727 Forensic Attribution",
        "",
        "This package is research-only. It does not dispatch another fullrun, tune thresholds, or promote production.",
        "",
        "## Governance",
        "",
        f"- `production_promotion_allowed`: `{payload['production_promotion_allowed']}`",
        f"- `pit_universe_label_clean`: `{payload['pit_universe_label_clean']}`",
        f"- `public_display_allowed`: `{payload['public_display_allowed']}`",
        f"- `live_trading_enabled`: `{payload['live_trading_enabled']}`",
        f"- `decision_label`: `{payload['decision_label']}`",
        f"- `result_label`: `{payload.get('result_label', payload['decision_label'])}`",
        f"- `runner_parity_status`: `{payload.get('runner_parity_status', 'missing')}`",
        "- `survivorship_inflation_estimate_cagr_pp`: `{}`".format(
            payload.get("survivorship_inflation_estimate_cagr_pp")
        ),
        f"- `survivorship_inflation_label`: `{payload.get('survivorship_inflation_label', 'missing')}`",
        f"- `survivorship_unmeasured_component`: `{payload.get('survivorship_unmeasured_component', 'missing')}`",
        f"- `measurement_contract_acceptance_allowed`: `{payload.get('measurement_contract_acceptance_allowed')}`",
        f"- `measurement_contract_acceptance_blockers`: `{','.join(payload.get('measurement_contract_acceptance_blockers', []))}`",
        "",
        "## Cash-Carry Replay Status",
        "",
        f"- `status`: `{payload['cash_carry_exact_replay']['status']}`",
        f"- `reason`: {payload['cash_carry_exact_replay']['reason'] or 'ready'}",
        "",
        "## Window Attribution",
        "",
        "| Portfolio | 2026-06-29 CAGR | 2026-07-02 CAGR | Delta pp | 2026-07-02 MaxDD | End equity delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for portfolio in PORTFOLIOS:
        row = payload["window_attribution"][portfolio]
        clamp = row["clamp_end"]
        actual = row["actual_end"]
        delta = row["delta_actual_minus_clamp"]
        lines.append(
            "| {portfolio} | {clamp_cagr:.2%} | {actual_cagr:.2%} | {delta_pp:.2f} | {max_dd:.2%} | {equity_delta:,.0f} |".format(
                portfolio=portfolio,
                clamp_cagr=float(clamp.get("cagr") or 0.0),
                actual_cagr=float(actual.get("cagr") or 0.0),
                delta_pp=float(delta.get("cagr_pp") or 0.0),
                max_dd=float(actual.get("max_dd") or 0.0),
                equity_delta=float(delta.get("ending_capital_usd") or 0.0),
            )
        )
    lines.extend(
        [
            "",
            "The 2026-06-29 clamp is attribution-only. It is not a current pass label.",
            "",
            "## Target-Book Drift",
            "",
            "| Portfolio | Common dates | Avg ticker overlap | Avg L1 diff | Max L1 diff | Proxy delta sum |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for portfolio in PORTFOLIOS:
        row = payload["target_book_drift"][portfolio]
        lines.append(
            "| {portfolio} | {common} | {overlap:.2%} | {avg_l1:.4f} | {max_l1:.4f} | {proxy:.4f} |".format(
                portfolio=portfolio,
                common=int(row.get("common_date_count") or 0),
                overlap=float(row.get("average_ticker_overlap") or 0.0),
                avg_l1=float(row.get("average_l1_weight_diff") or 0.0),
                max_l1=float(row.get("max_l1_weight_diff") or 0.0),
                proxy=float(row.get("proxy_delta_return_sum") or 0.0),
            )
        )
    lines.extend(
        [
            "",
            "## Metric Sidecar",
            "",
            "| Arm | Portfolio | Metric mode | CAGR | MaxDD | Sharpe | Target pass |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for arm, arm_payload in payload.get("metric_sidecar", {}).get("arms", {}).items():
        for portfolio in PORTFOLIOS:
            row = arm_payload.get("portfolios", {}).get(portfolio, {})
            lines.append(
                "| {arm} | {portfolio} | {mode} | {cagr:.2%} | {max_dd:.2%} | {sharpe:.3f} | {target_pass} |".format(
                    arm=arm,
                    portfolio=portfolio,
                    mode=row.get("metric_mode") or "",
                    cagr=float(row.get("cagr") or 0.0),
                    max_dd=float(row.get("max_dd") or 0.0),
                    sharpe=float(row.get("sharpe") or 0.0),
                    target_pass=bool(row.get("target_pass")),
                )
            )
    lines.extend(
        [
            "",
            "## Anti-Leakage Notes",
            "",
            "- Frozen-book results are fixed-book research evidence, not regenerated fullrun acceptance.",
            "- Regenerated-book results must be compared on the same metric mode and replay end date.",
            "- Exact cash-carry replay is blocked until the price cache is present; it is not approximated here.",
            "- Date/month/ticker attribution is diagnostic only. It must not be used to hand-edit losing months.",
            "- Forward-label screens are audit labels only. Any rule sourced from them needs OOS validation before promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(
    run_root: Path,
    frozen_root: Path,
    output_dir: Path,
    official_window_end: str,
    actual_window_end: str,
    price_cache: Path,
    macro_cache: Path,
    metric_sidecar_root: Path,
    parity_summary: Path,
    survivorship_summary: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    official_account = read_json(run_root / "account_evaluation" / "official_metrics.json")
    official_metrics = {portfolio: metric_subset(read_official_metrics(run_root, portfolio)) for portfolio in PORTFOLIOS}
    frozen_metrics = {
        portfolio: metric_subset(read_json(frozen_cash_carry_metrics_path(frozen_root, portfolio)))
        for portfolio in PORTFOLIOS
    }
    contract_caveats = measurement_contract_caveat_fields(
        parity_summary_path=parity_summary,
        survivorship_summary_path=survivorship_summary,
    )
    payload: dict[str, Any] = {
        "schema_version": "run287-forensics-v1",
        "run_id": "28725350727",
        "status": "completed",
        "production_promotion_allowed": False,
        "production_blocker": "pit_universe_label_clean_false",
        "pit_universe_label_clean": bool(official_account.get("pit_universe_label_clean", False)),
        "public_display_allowed": False,
        "live_trading_enabled": False,
        "new_fullrun_dispatched": False,
        "threshold_tuning_performed": False,
        "official_account_evaluation": official_account,
        "official_run287_zero_yield_metrics": official_metrics,
        "frozen_candidate_cash_carry_metrics": frozen_metrics,
        "cash_carry_exact_replay": cash_carry_status(price_cache, macro_cache),
        **contract_caveats,
    }
    acceptance_blockers = measurement_contract_acceptance_blockers(contract_caveats)
    payload["measurement_contract_acceptance_blockers"] = acceptance_blockers
    payload["measurement_contract_acceptance_allowed"] = not acceptance_blockers
    payload["window_attribution"] = build_window_attribution(run_root, output_dir, official_window_end, actual_window_end)
    payload["target_book_drift"] = compare_books(frozen_root, run_root, output_dir)
    payload["hook_telemetry"] = summarize_hook_telemetry(run_root, output_dir)
    payload["metric_sidecar"] = build_metric_sidecar_summary(run_root, metric_sidecar_root, output_dir, contract_caveats)
    if not all(payload["window_attribution"][p]["official_metrics_reproduced"] for p in PORTFOLIOS):
        payload["decision_label"] = "blocked_unreproducible"
        payload["next_action"] = "fix_zero_yield_reproduction_before_strategy_work"
    elif payload["metric_sidecar"]["status"] != "completed":
        payload["decision_label"] = "window_shock_and_regenerated_book_drift_explain_drop_pending_exact_cash_carry_replay"
        payload["next_action"] = (
            "restore_or_build_price_cache_before_exact_cash_carry_replay"
            if payload["cash_carry_exact_replay"]["status"] != "ready_for_exact_replay"
            else "run_exact_generated_book_cash_carry_sidecar_without_dispatch"
        )
    elif payload["metric_sidecar"].get("latest_generated_book_cash_carry_pass") and acceptance_blockers:
        payload["decision_label"] = "blocked_measurement_contract_caveat"
        payload["next_action"] = "restore_runner_parity_and_resolve_survivorship_caveats_before_acceptance_label"
    elif payload["metric_sidecar"].get("latest_generated_book_cash_carry_pass"):
        payload["decision_label"] = "measurement_mismatch_only"
        payload["next_action"] = "update_fullrun_to_emit_cash_carry_sidecar_as_research_metric"
    else:
        payload["decision_label"] = "alpha_candidate_rejected_on_generated_book"
        payload["next_action"] = "write_negative_evidence_and_prioritize_w1_window_book_drift_before_new_alpha"
    payload["result_label"] = payload["decision_label"]
    payload["acceptance_style_label_blocked"] = (
        bool(acceptance_blockers) and payload["result_label"] not in ACCEPTANCE_STYLE_LABELS
    )
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(build_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", default=DEFAULT_RUN_ROOT)
    parser.add_argument("--frozen-root", default=DEFAULT_FROZEN_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--official-window-end", default="2026-06-29")
    parser.add_argument("--actual-window-end", default="2026-07-02")
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--macro-cache", default="cache_macro")
    parser.add_argument("--metric-sidecar-root", default=DEFAULT_METRIC_SIDECAR_ROOT)
    parser.add_argument("--parity-summary", default=DEFAULT_PARITY_SUMMARY)
    parser.add_argument("--survivorship-summary", default=DEFAULT_SURVIVORSHIP_SUMMARY)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        run_root=repo_path(args.run_root),
        frozen_root=repo_path(args.frozen_root),
        output_dir=repo_path(args.output_dir),
        official_window_end=args.official_window_end,
        actual_window_end=args.actual_window_end,
        price_cache=repo_path(args.price_cache),
        macro_cache=repo_path(args.macro_cache),
        metric_sidecar_root=repo_path(args.metric_sidecar_root),
        parity_summary=repo_path(args.parity_summary),
        survivorship_summary=repo_path(args.survivorship_summary),
    )
    print(json.dumps({"status": payload["status"], "decision_label": payload["decision_label"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
