#!/usr/bin/env python3
"""Compare fixed-bps replay with spread/ADV/impact execution costs.

This sidecar is research-only and cannot promote or mutate a portfolio.  It
preserves the existing 25bps broker replay as the control, then reruns the same
target book with prior-OHLCV half-spread, dollar-ADV, square-root market impact,
optional paper slippage, and 0.1%/0.5%/1.0 ADV capacity reporting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.execution_cost_model import (  # noqa: E402
    EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
    EXECUTION_COST_SCHEMA_VERSION,
    ExecutionCostConfig,
)
from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_TICKERS,
    CASH_CARRY_MODE_NONE,
    CashCarryConfig,
    redact_execution_performance,
    replay,
)
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


SIDECAR_SCHEMA_VERSION = "run287-execution-cost-capacity-sidecar-v1"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def file_sha256(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def build_source_manifest(
    *,
    target_book: Path,
    price_cache: Path,
    paper_slippage_path: Path | None,
    execution_cost_config: ExecutionCostConfig,
    realistic_trades_path: Path,
    target_fill_coverage_path: Path,
) -> dict[str, Any]:
    raw_target_tickers: set[str] = set()
    try:
        targets = pd.read_csv(target_book)
    except Exception:
        targets = pd.DataFrame()
    if not targets.empty and "ticker" in targets.columns:
        raw_target_tickers = {
            str(value).upper().strip()
            for value in targets["ticker"]
            if pd.notna(value)
            and str(value).upper().strip()
            and str(value).upper().strip() not in CASH_TICKERS
        }
    traded_tickers: set[str] = set()
    try:
        trades = pd.read_csv(realistic_trades_path)
    except Exception:
        trades = pd.DataFrame()
    if not trades.empty and "ticker" in trades.columns:
        traded_tickers = {
            str(value).upper().strip()
            for value in trades["ticker"]
            if pd.notna(value) and str(value).strip()
        }
    try:
        target_fill_rows = pd.read_csv(target_fill_coverage_path)
    except Exception:
        target_fill_rows = pd.DataFrame()
    required_values = (
        target_fill_rows["required_for_replay"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1"})
        if not target_fill_rows.empty
        and "required_for_replay" in target_fill_rows.columns
        else pd.Series(True, index=target_fill_rows.index, dtype=bool)
    )
    required_target_fill_rows = target_fill_rows.loc[required_values].copy()
    target_tickers = (
        {
            str(value).upper().strip()
            for value in required_target_fill_rows["ticker"]
            if pd.notna(value)
            and str(value).upper().strip()
            and str(value).upper().strip() not in CASH_TICKERS
        }
        if not required_target_fill_rows.empty
        and "ticker" in required_target_fill_rows.columns
        else set()
    )
    tickers = sorted(target_tickers | traded_tickers)
    fillable_values = (
        required_target_fill_rows["fillable"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1"})
        if not required_target_fill_rows.empty
        and "fillable" in required_target_fill_rows.columns
        else pd.Series(dtype=bool)
    )
    chronology_values = (
        required_target_fill_rows["chronology_safe"]
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1"})
        if not required_target_fill_rows.empty
        and "chronology_safe" in required_target_fill_rows.columns
        else pd.Series(dtype=bool)
    )
    audited_target_fill_count = int(len(target_fill_rows))
    required_target_fill_count = int(len(required_target_fill_rows))
    pending_target_fill_count = (
        audited_target_fill_count - required_target_fill_count
    )
    target_fill_coverage_complete = bool(
        audited_target_fill_count == 0
        or (
            required_target_fill_count > 0
            and len(fillable_values) == required_target_fill_count
            and fillable_values.all()
            and len(chronology_values) == required_target_fill_count
            and chronology_values.all()
        )
    )
    price_sources: list[dict[str, Any]] = []
    for ticker in tickers:
        path = price_cache / px_cache_name(ticker)
        liquidity_frame = load_price_series(
            price_cache,
            ticker,
            include_liquidity=True,
        )
        liquidity_ready = bool(
            not liquidity_frame.empty
            and {"close", "high", "low", "volume", "dollar_volume"}.issubset(
                liquidity_frame.columns
            )
        )
        price_sources.append(
            {
                "ticker": ticker,
                "required_by_target_book": ticker in target_tickers,
                "present_in_realistic_trades": ticker in traded_tickers,
                "path": str(path),
                "sha256": file_sha256(path),
                "exists": path.exists(),
                "liquidity_ohlcv_loadable": liquidity_ready,
                "history_start_date": (
                    pd.Timestamp(liquidity_frame.index.min()).date().isoformat()
                    if not liquidity_frame.empty
                    else ""
                ),
                "history_end_date": (
                    pd.Timestamp(liquidity_frame.index.max()).date().isoformat()
                    if not liquidity_frame.empty
                    else ""
                ),
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "run287-execution-cost-source-manifest-v1",
        "target_book": str(target_book),
        "target_book_sha256": file_sha256(target_book),
        "price_cache": str(price_cache),
        "price_sources": price_sources,
        "price_source_count": len(price_sources),
        "target_ticker_count": len(target_tickers),
        "raw_target_ticker_count": len(raw_target_tickers),
        "replay_filtered_target_tickers": sorted(target_tickers),
        "excluded_raw_target_tickers": sorted(
            raw_target_tickers - target_tickers
        ),
        "traded_ticker_count": len(traded_tickers),
        "untraded_target_tickers": sorted(target_tickers - traded_tickers),
        "target_fill_coverage_path": str(target_fill_coverage_path),
        "target_fill_coverage_sha256": file_sha256(target_fill_coverage_path),
        "audited_target_fill_count": audited_target_fill_count,
        "audited_transition_fill_count": audited_target_fill_count,
        "required_target_fill_count": required_target_fill_count,
        "required_transition_fill_count": required_target_fill_count,
        "pending_target_fill_count": pending_target_fill_count,
        "pending_transition_fill_count": pending_target_fill_count,
        "fillable_target_count": int(fillable_values.sum())
        if len(fillable_values)
        else 0,
        "transition_fill_chronology_safe": bool(
            audited_target_fill_count == 0
            or (
                required_target_fill_count > 0
                and len(chronology_values) == required_target_fill_count
                and chronology_values.all()
            )
        ),
        "target_fill_coverage_complete": target_fill_coverage_complete,
        "price_source_coverage_complete": bool(
            price_sources
            and all(
                row["sha256"] and row["liquidity_ohlcv_loadable"]
                for row in price_sources
            )
        ),
        "paper_slippage_path": (
            str(paper_slippage_path) if paper_slippage_path is not None else ""
        ),
        "paper_slippage_sha256": file_sha256(paper_slippage_path),
        "execution_cost_config": execution_cost_config.audit(),
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    return manifest


def clear_replay_child(directory: Path, parent: Path) -> None:
    resolved_parent = parent.resolve()
    resolved_directory = directory.resolve()
    if resolved_directory == resolved_parent or resolved_parent not in resolved_directory.parents:
        raise ValueError(f"unsafe sidecar replay directory: {resolved_directory}")
    if directory.exists():
        shutil.rmtree(directory)


def redact_nested_replay(
    directory: Path,
    metrics: dict[str, Any],
    *,
    reason: str,
) -> None:
    redacted = redact_execution_performance(metrics, reason=reason)
    artifact_names = [
        "equity_curve.csv",
        "holdings_daily.csv",
        "holdings_weekly.csv",
        "cash_ledger.csv",
        "target_vs_actual_weights.csv",
        "partial_resize_decisions.csv",
        "positions_latest.csv",
        "account_state_latest.json",
    ]
    if reason == "paper_slippage_out_of_bounds":
        artifact_names.append("trades.csv")
    for artifact_name in artifact_names:
        artifact_path = directory / artifact_name
        if artifact_path.is_file():
            artifact_path.unlink()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metrics.json").write_text(
        json.dumps(redacted, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (directory / "replay_report.md").write_text(
        "# Broker Ledger Replay\n\n"
        "Status: blocked\n\n"
        f"Reason: {reason}\n\n"
        "Performance artifacts were redacted because the execution-cost "
        "preflight did not pass.\n",
        encoding="utf-8",
    )


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def metric_view(
    metrics: dict[str, Any],
    *,
    performance_usable: bool,
) -> dict[str, Any]:
    return {
        "status": metrics.get("status"),
        "reason": metrics.get("reason", ""),
        "metric_mode": metrics.get("metric_mode"),
        "performance_usable": bool(performance_usable),
        "start_date": metrics.get("start_date"),
        "end_date": metrics.get("end_date"),
        "cagr": (
            finite_float(metrics.get("cagr")) if performance_usable else None
        ),
        "max_dd": (
            finite_float(metrics.get("max_dd")) if performance_usable else None
        ),
        "sharpe": (
            finite_float(metrics.get("sharpe")) if performance_usable else None
        ),
        "ending_capital_usd": (
            finite_float(metrics.get("ending_capital_usd"))
            if performance_usable
            else None
        ),
        "total_fees_usd": finite_float(metrics.get("total_fees_usd")),
        "trade_count": int(finite_float(metrics.get("trade_count")) or 0),
        "gross_traded_usd": finite_float(metrics.get("gross_traded_usd")),
    }


def metric_deltas(
    fixed_metrics: dict[str, Any],
    realistic_metrics: dict[str, Any],
) -> dict[str, Any]:
    if fixed_metrics.get("status") != "completed" or realistic_metrics.get("status") != "completed":
        return {}
    fixed_cagr = finite_float(fixed_metrics.get("cagr"))
    realistic_cagr = finite_float(realistic_metrics.get("cagr"))
    fixed_mdd = finite_float(fixed_metrics.get("max_dd"))
    realistic_mdd = finite_float(realistic_metrics.get("max_dd"))
    fixed_sharpe = finite_float(fixed_metrics.get("sharpe"))
    realistic_sharpe = finite_float(realistic_metrics.get("sharpe"))
    fixed_ending = finite_float(fixed_metrics.get("ending_capital_usd"))
    realistic_ending = finite_float(realistic_metrics.get("ending_capital_usd"))
    return {
        "cagr_delta_percentage_points": (
            (realistic_cagr - fixed_cagr) * 100.0
            if realistic_cagr is not None and fixed_cagr is not None
            else None
        ),
        "max_dd_delta_percentage_points": (
            (realistic_mdd - fixed_mdd) * 100.0
            if realistic_mdd is not None and fixed_mdd is not None
            else None
        ),
        "sharpe_delta": (
            realistic_sharpe - fixed_sharpe
            if realistic_sharpe is not None and fixed_sharpe is not None
            else None
        ),
        "ending_capital_delta_usd": (
            realistic_ending - fixed_ending
            if realistic_ending is not None and fixed_ending is not None
            else None
        ),
    }


def render_report(payload: dict[str, Any]) -> str:
    fixed = payload.get("fixed_bps_control") or {}
    realistic = payload.get("realistic_execution_cost") or {}
    deltas = payload.get("deltas_vs_fixed_bps") or {}
    def percent(value: Any) -> str:
        number = finite_float(value)
        return f"{number:.2%}" if number is not None else "blocked"

    def decimal(value: Any) -> str:
        number = finite_float(value)
        return f"{number:.3f}" if number is not None else "blocked"

    def delta(value: Any, suffix: str, digits: int) -> str:
        number = finite_float(value)
        return f"{number:+.{digits}f}{suffix}" if number is not None else "blocked"

    lines = [
        "# Run287 Execution Cost and Capacity Sidecar",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Portfolio: `{payload.get('portfolio_kind')}`",
        f"- Target SHA256: `{payload.get('target_book_sha256')}`",
        f"- Fixed base cost: `{payload.get('base_cost_bps')} bps per side`",
        f"- Liquidity coverage: `{payload.get('execution_cost_summary', {}).get('coverage_rate')}`",
        "",
        "| Metric | Fixed bps | Spread/ADV/impact | Delta |",
        "|---|---:|---:|---:|",
        f"| CAGR | {percent(fixed.get('cagr'))} | {percent(realistic.get('cagr'))} | "
        f"{delta(deltas.get('cagr_delta_percentage_points'), 'pp', 2)} |",
        f"| MaxDD | {percent(fixed.get('max_dd'))} | {percent(realistic.get('max_dd'))} | "
        f"{delta(deltas.get('max_dd_delta_percentage_points'), 'pp', 2)} |",
        f"| Sharpe | {decimal(fixed.get('sharpe'))} | {decimal(realistic.get('sharpe'))} | "
        f"{delta(deltas.get('sharpe_delta'), '', 3)} |",
        "",
        "## Capacity",
        "",
        "| ADV ceiling | Strict capacity | 5th-percentile capacity | Breaches at start capital |",
        "|---:|---:|---:|---:|",
    ]
    for scenario in payload.get("capacity_scenarios") or []:
        strict = finite_float(scenario.get("strict_capacity_usd"))
        p05 = finite_float(scenario.get("p05_capacity_usd"))
        lines.append(
            "| {limit:.1%} | {strict} | {p05} | {breaches} |".format(
                limit=float(scenario.get("max_adv_participation") or 0.0),
                strict=f"${strict:,.0f}" if strict is not None else "blocked",
                p05=f"${p05:,.0f}" if p05 is not None else "blocked",
                breaches=int(scenario.get("breach_trade_count_at_starting_capital") or 0),
            )
        )
    lines.extend(
        [
            "",
            "Research-only. This artifact cannot change the champion, targets, paper ledger, or live portfolio.",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio_kind: str,
    starting_capital: float,
    fill_mode: str,
    base_cost_bps: float,
    max_fill_lag_days: int,
    execution_cost_config: ExecutionCostConfig,
    disable_concentrated_champion_filter: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = output_dir / "fixed_bps_control"
    realistic_dir = output_dir / "spread_adv_impact"
    clear_replay_child(fixed_dir, output_dir)
    clear_replay_child(realistic_dir, output_dir)
    for artifact_name in ("summary.json", "source_manifest.json", "report.md"):
        artifact_path = output_dir / artifact_name
        if artifact_path.is_file():
            artifact_path.unlink()
    fixed_metrics = replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=fixed_dir,
        portfolio_kind=portfolio_kind,
        starting_capital=starting_capital,
        fill_mode=fill_mode,
        cost_bps=base_cost_bps,
        integer_shares=True,
        max_fill_lag_days=max_fill_lag_days,
        disable_concentrated_champion_filter=disable_concentrated_champion_filter,
        cash_carry_config=CashCarryConfig(mode=CASH_CARRY_MODE_NONE),
    )
    realistic_metrics = replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=realistic_dir,
        portfolio_kind=portfolio_kind,
        starting_capital=starting_capital,
        fill_mode=fill_mode,
        cost_bps=base_cost_bps,
        integer_shares=True,
        max_fill_lag_days=max_fill_lag_days,
        disable_concentrated_champion_filter=disable_concentrated_champion_filter,
        execution_cost_config=execution_cost_config,
        cash_carry_config=CashCarryConfig(mode=CASH_CARRY_MODE_NONE),
    )
    source_manifest = build_source_manifest(
        target_book=target_book,
        price_cache=price_cache,
        paper_slippage_path=execution_cost_config.paper_slippage_path,
        execution_cost_config=execution_cost_config,
        realistic_trades_path=realistic_dir / "trades.csv",
        target_fill_coverage_path=realistic_dir / "target_fill_coverage.csv",
    )
    execution_summary = realistic_metrics.get("execution_cost_summary") or {}
    complete = bool(
        fixed_metrics.get("status") == "completed"
        and realistic_metrics.get("status") == "completed"
        and int(execution_summary.get("trade_count") or 0) > 0
        and execution_summary.get("coverage_complete") is True
        and source_manifest.get("price_source_coverage_complete") is True
        and source_manifest.get("target_fill_coverage_complete") is True
    )
    promotion_blockers: list[str] = []
    if not complete:
        promotion_blockers.append("execution_cost_preflight_failed")
    if source_manifest.get("price_source_coverage_complete") is not True:
        promotion_blockers.append("price_source_manifest_incomplete")
    if source_manifest.get("target_fill_coverage_complete") is not True:
        promotion_blockers.append("target_fill_coverage_incomplete")
    paper_slippage_blocked = bool(
        realistic_metrics.get("reason") == "paper_slippage_out_of_bounds"
    )
    if paper_slippage_blocked:
        promotion_blockers.append("paper_slippage_out_of_bounds")
    elif int(execution_summary.get("paper_slippage_trade_count") or 0) == 0:
        promotion_blockers.append("paper_slippage_calibration_unavailable")
    if int(execution_summary.get("paper_slippage_exceeds_model_count") or 0) > 0:
        promotion_blockers.append("paper_slippage_exceeds_model_assumption")
    if not complete:
        nested_reason = str(
            realistic_metrics.get("reason")
            or fixed_metrics.get("reason")
            or "execution_cost_preflight_failed"
        )
        redact_nested_replay(
            fixed_dir,
            fixed_metrics,
            reason=nested_reason,
        )
        redact_nested_replay(
            realistic_dir,
            realistic_metrics,
            reason=nested_reason,
        )
    payload: dict[str, Any] = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "execution_cost_schema_version": EXECUTION_COST_SCHEMA_VERSION,
        "status": "completed" if complete else "blocked",
        "reason": (
            ""
            if complete
            else str(
                realistic_metrics.get("reason")
                or fixed_metrics.get("reason")
                or "execution_cost_preflight_failed"
            )
        ),
        "portfolio_kind": portfolio_kind,
        "target_book": str(target_book),
        "target_book_sha256": file_sha256(target_book),
        "price_cache": str(price_cache),
        "paper_slippage_sha256": file_sha256(execution_cost_config.paper_slippage_path),
        "source_manifest_sha256": source_manifest["manifest_sha256"],
        "starting_capital_usd": float(starting_capital),
        "fill_mode": fill_mode,
        "base_cost_bps": float(base_cost_bps),
        "max_fill_lag_days": int(max_fill_lag_days),
        "execution_cost_config": execution_cost_config.audit(),
        "fixed_bps_control": metric_view(
            fixed_metrics,
            performance_usable=complete,
        ),
        "realistic_execution_cost": metric_view(
            realistic_metrics,
            performance_usable=complete,
        ),
        "deltas_vs_fixed_bps": (
            metric_deltas(fixed_metrics, realistic_metrics) if complete else {}
        ),
        "execution_cost_summary": execution_summary,
        "capacity_scenarios": execution_summary.get("capacity_scenarios", []),
        "calibration_status": (
            "PAPER_CALIBRATION_AVAILABLE"
            if int(execution_summary.get("paper_slippage_trade_count") or 0) > 0
            else "PAPER_CALIBRATION_REQUIRED"
        ),
        "promotion_blockers": promotion_blockers,
        "promotion_allowed": False,
        "production_activation_allowed": False,
        "target_mutation_allowed": False,
        "paper_ledger_mutation_allowed": False,
        "research_only": True,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "source_manifest.json").write_text(
        json.dumps(source_manifest, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated"], required=True)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--fill-mode", choices=["next_close", "next_open", "same_close"], default="next_close")
    parser.add_argument("--base-cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--lookback-sessions", type=int, default=20)
    parser.add_argument("--min-history-sessions", type=int, default=12)
    parser.add_argument("--impact-coefficient", type=float, default=0.50)
    parser.add_argument("--minimum-half-spread-bps", type=float, default=1.0)
    parser.add_argument("--maximum-half-spread-bps", type=float, default=100.0)
    parser.add_argument("--maximum-market-impact-bps", type=float, default=500.0)
    parser.add_argument(
        "--capacity-participation-rates",
        nargs="+",
        type=float,
        default=[0.001, 0.005, 0.010],
    )
    parser.add_argument("--paper-slippage-path", default="")
    parser.add_argument("--disable-concentrated-champion-filter", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paper_path = (
        repo_path(args.paper_slippage_path)
        if str(args.paper_slippage_path or "").strip()
        else None
    )
    payload = run(
        target_book=repo_path(args.target_book),
        price_cache=repo_path(args.price_cache),
        output_dir=repo_path(args.output_dir),
        portfolio_kind=args.portfolio_kind,
        starting_capital=float(args.starting_capital),
        fill_mode=args.fill_mode,
        base_cost_bps=float(args.base_cost_bps),
        max_fill_lag_days=int(args.max_fill_lag_days),
        execution_cost_config=ExecutionCostConfig(
            mode=EXECUTION_COST_MODE_SPREAD_ADV_IMPACT,
            lookback_sessions=int(args.lookback_sessions),
            min_history_sessions=int(args.min_history_sessions),
            impact_coefficient=float(args.impact_coefficient),
            minimum_half_spread_bps=float(args.minimum_half_spread_bps),
            maximum_half_spread_bps=float(args.maximum_half_spread_bps),
            maximum_market_impact_bps=float(args.maximum_market_impact_bps),
            capacity_participation_rates=tuple(
                float(value) for value in args.capacity_participation_rates
            ),
            paper_slippage_path=paper_path,
            require_complete_liquidity_coverage=True,
        ),
        disable_concentrated_champion_filter=bool(
            args.disable_concentrated_champion_filter
        ),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
