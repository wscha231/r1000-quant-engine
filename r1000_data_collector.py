from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from r1000_top30_institutional import (
    CASH_PROXY_TICKER,
    DEFAULT_CFG,
    build_universe_monthly,
    get_paths,
    log,
    log_core_fundamental_coverage,
    model_feature_columns,
    mount_drive_if_colab,
    normalize_latest_fundamental_snapshot,
    safe_float,
    to_cfg,
    validate_config,
    write_comprehensive_fundamental_coverage_report,
    write_fundamental_coverage_report,
    write_live_event_alert_report,
    write_live_fundamental_coverage_report,
    write_market_adaptation_report,
)


def collector_default_cfg(base_dir: Optional[str] = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CFG)
    cfg["base_dir"] = base_dir or os.getcwd()
    cfg["reuse_existing_artifacts"] = True
    cfg["resume_partial_walkforward"] = True
    cfg["show_output_previews_after_run"] = False
    return cfg


def _apply_notebook_runtime_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    base_dir = str(cfg.get("base_dir") or os.getcwd())
    companyfacts_zip = Path(base_dir) / "companyfacts.zip"
    if companyfacts_zip.exists():
        cfg["use_sec_companyfacts_bulk_local"] = True
        cfg["sec_companyfacts_bulk_path"] = str(companyfacts_zip)
    cfg.setdefault("default_backtest_years", 8)
    cfg.setdefault("backtest_window_comparison_years", [5, 8])
    cfg.setdefault("rebalance_interval_comparison_months", [1, 3, 6])
    cfg.setdefault("run_portfolio_size_comparison", True)
    cfg.setdefault("run_rebalance_interval_comparison", True)
    cfg.setdefault("run_backtest_window_comparison", True)
    cfg.setdefault("run_standalone_sleeve_backtest_comparison", True)
    cfg.setdefault("standalone_sleeve_top_n", 7)
    cfg.setdefault("standalone_sleeve_rebalance_intervals", [1, 3])
    cfg.setdefault("run_historical_data_quality_reports", True)
    cfg.setdefault("growth_history_confidence_penalty_weight", 0.18)
    cfg.setdefault("growth_history_confidence_min_for_full_sleeve", 0.35)
    cfg.setdefault("show_output_previews_after_run", False)
    cfg.setdefault("cash_target_growth_cap", 0.03)
    cfg.setdefault("cash_target_balanced_cap", 0.05)
    cfg.setdefault("cash_target_mild_risk_cap", 0.10)
    cfg.setdefault("core_compounder_sleeve_base_weight", 0.28)
    cfg.setdefault("future_winner_sleeve_base_weight", 0.52)
    cfg.setdefault("future_winner_sleeve_min_weight", 0.10)
    cfg.setdefault("future_winner_sleeve_max_weight", 0.70)
    cfg.setdefault("early_scout_sleeve_base_weight", 0.12)
    cfg.setdefault("early_scout_sleeve_min_weight", 0.02)
    cfg.setdefault("early_scout_sleeve_max_weight", 0.28)
    cfg.setdefault("early_scout_growth_floor_weight", 0.12)
    cfg.setdefault("early_scout_growth_floor_min_signal", 0.34)
    cfg.setdefault("early_scout_growth_floor_max_risk", 0.60)
    cfg.setdefault("early_scout_candidate_floor_min_share", 0.01)
    cfg.setdefault("run_sleeve_cap_policy_comparison", True)
    cfg.setdefault("sleeve_cap_policy_apply_champion", True)
    cfg.setdefault("sleeve_cap_policy_max_candidates", 9)
    return cfg


def apply_colab_free_runtime_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Recommended free-source Colab settings for the full collector -> engine run."""
    cfg["sec_user_agent"] = "R1000InstitutionalBot (contact: andrewcha231@gmail.com)"
    cfg["fred_api_key"] = "8d92fb5a5de226657d912fe0284dfc00"
    cfg["macro_refresh_days"] = 0
    cfg["live_refresh_days"] = 1
    cfg["companyfacts_refresh_days"] = 3
    cfg["alpha_vantage_free_refresh_tickers"] = 0
    cfg["alpha_vantage_free_statement_repair_tickers"] = 0
    cfg["alpha_vantage_free_statement_refresh_days"] = 7
    cfg["macro_slow_release_lag_months"] = 1
    cfg["cash_target_growth_cap"] = 0.03
    cfg["cash_target_balanced_cap"] = 0.05
    cfg["cash_target_mild_risk_cap"] = 0.10
    cfg["core_compounder_sleeve_base_weight"] = 0.28
    cfg["future_winner_sleeve_base_weight"] = 0.52
    cfg["future_winner_sleeve_min_weight"] = 0.10
    cfg["future_winner_sleeve_max_weight"] = 0.70
    cfg["early_scout_sleeve_base_weight"] = 0.12
    cfg["early_scout_sleeve_min_weight"] = 0.02
    cfg["early_scout_sleeve_max_weight"] = 0.28
    cfg["early_scout_growth_floor_weight"] = 0.12
    cfg["early_scout_growth_floor_min_signal"] = 0.34
    cfg["early_scout_growth_floor_max_risk"] = 0.60
    cfg["early_scout_candidate_floor_min_share"] = 0.01
    cfg["run_sleeve_cap_policy_comparison"] = True
    cfg["sleeve_cap_policy_apply_champion"] = True
    cfg["sleeve_cap_policy_max_candidates"] = 9
    cfg["run_historical_data_quality_reports"] = True
    cfg["growth_history_confidence_penalty_weight"] = 0.18
    cfg["growth_history_confidence_min_for_full_sleeve"] = 0.35
    return cfg


def collector_full_run_cfg(base_dir: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    cfg = collector_default_cfg(base_dir=base_dir)
    cfg["reuse_existing_artifacts"] = False
    cfg["resume_partial_walkforward"] = False
    cfg["reuse_phase4_models_for_latest_recommendations"] = False
    if end_date:
        cfg["end_date"] = str(end_date)
    return _apply_notebook_runtime_defaults(cfg)


def collector_lean_full_run_cfg(base_dir: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    cfg = collector_full_run_cfg(base_dir=base_dir, end_date=end_date)
    cfg["run_comparison_backtests"] = False
    cfg["run_portfolio_size_comparison"] = False
    cfg["run_rebalance_interval_comparison"] = True
    cfg["run_backtest_window_comparison"] = False
    cfg["export_extended_outputs"] = False
    cfg["export_explain_outputs"] = False
    return _apply_notebook_runtime_defaults(cfg)


def collector_colab_full_run_cfg(base_dir: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    """Full first-run config used by colab_run.ipynb.

    The notebook should keep these choices in one place instead of repeating a long
    list of overrides in multiple cells.
    """
    return apply_colab_free_runtime_overrides(
        collector_lean_full_run_cfg(base_dir=base_dir, end_date=end_date)
    )


def collector_reuse_step2_cfg(base_dir: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    cfg = collector_default_cfg(base_dir=base_dir)
    cfg["reuse_existing_artifacts"] = True
    cfg["resume_partial_walkforward"] = True
    cfg["reuse_phase4_models_for_latest_recommendations"] = True
    if end_date:
        cfg["end_date"] = str(end_date)
    return _apply_notebook_runtime_defaults(cfg)


def collector_coverage_debug_cfg(base_dir: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    cfg = collector_full_run_cfg(base_dir=base_dir, end_date=end_date)
    cfg["companyfacts_refresh_days"] = 0
    cfg["live_refresh_days"] = 0
    cfg["macro_refresh_days"] = 0
    cfg["alpha_vantage_free_refresh_tickers"] = max(int(cfg.get("alpha_vantage_free_refresh_tickers", 8)), 24)
    cfg["alpha_vantage_free_statement_repair_tickers"] = max(
        int(cfg.get("alpha_vantage_free_statement_repair_tickers", 6)),
        24,
    )
    cfg["alpha_vantage_free_statement_refresh_days"] = min(
        int(cfg.get("alpha_vantage_free_statement_refresh_days", 14)),
        7,
    )
    cfg["max_live_refresh_tickers"] = max(int(cfg.get("max_live_refresh_tickers", 1000)), 1000)
    return _apply_notebook_runtime_defaults(cfg)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _safe_ratio(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").notna().mean())


def _safe_read_csv(path: Path) -> pd.DataFrame:
    try:
        if path.exists():
            return pd.read_csv(path)
    except Exception:
        pass
    return pd.DataFrame()


def _safe_read_parquet(path: Path) -> pd.DataFrame:
    try:
        if path.exists():
            return pd.read_parquet(path)
    except Exception:
        pass
    return pd.DataFrame()


def _invalidate_downstream_artifacts(paths: dict[str, Path]) -> list[str]:
    targets = [
        paths["feature_store"] / "feature_store_latest.parquet",
        paths["feature_store"] / "scored_oos_latest.parquet",
        paths["feature_store"] / "scored_oos_partial.parquet",
        paths["feature_store"] / "latest_recommendations.parquet",
        paths["models"] / "model_bundle_latest.json",
        paths["checkpoints"] / "walkforward_progress.json",
        paths["checkpoints"] / "stage_flags.json",
        paths["out"] / "top30_latest.csv",
        paths["out"] / "top20_latest.csv",
        paths["out"] / "portfolio_latest.csv",
        paths["out"] / "full_fundamental_rank_latest.csv",
        paths["out"] / "partial_data_watchlist_latest.csv",
        paths["out"] / "research_only_top30_latest.csv",
        paths["out"] / "research_only_portfolio_latest.csv",
        paths["out"] / "scored_latest.csv",
        paths["out"] / "weights_latest.json",
        paths["out"] / "backtest_metrics.json",
        paths["out"] / "equity_curve.csv",
        paths["out"] / "run_summary.json",
        paths["out"] / "top30_explain_latest.csv",
        paths["out"] / "research_only_top30_explain_latest.csv",
        paths["out"] / "fundamental_comprehensive_coverage_latest.csv",
        paths["reports"] / "ranking_quality.json",
        paths["reports"] / "benchmark_comparison_latest.json",
        paths["reports"] / "portfolio_size_comparison.csv",
        paths["reports"] / "rebalance_interval_comparison.csv",
        paths["reports"] / "backtest_window_comparison.csv",
        paths["reports"] / "oos_performance.md",
        paths["reports"] / "sector_exposure.csv",
    ]
    removed: list[str] = []
    for path in targets:
        try:
            if path.exists():
                path.unlink()
                removed.append(str(path))
        except Exception:
            pass
    return removed


def run_data_collection(cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    cfg_obj = to_cfg(cfg or collector_default_cfg())
    validate_config(cfg_obj)
    mount_drive_if_colab()
    paths = get_paths(cfg_obj)

    log("Collector: building universe, prices, SEC fundamentals, and live fundamentals ...")
    monthly = build_universe_monthly(cfg_obj)
    latest_dt = pd.to_datetime(monthly["rebalance_date"], errors="coerce").max() if not monthly.empty else pd.NaT
    latest_view = monthly[monthly["rebalance_date"] == latest_dt].copy() if pd.notna(latest_dt) else monthly.copy()
    latest_view_normalized = normalize_latest_fundamental_snapshot(
        cfg_obj,
        paths,
        latest_view,
        clear_latest_only_signals=False,
        apply_statement_repair=True,
        add_fundamental_flags=True,
    )

    fundamental_cov_path = write_fundamental_coverage_report(paths, latest_view_normalized)
    comprehensive_cov_path = write_comprehensive_fundamental_coverage_report(paths, latest_view_normalized)
    live_cov_path = write_live_fundamental_coverage_report(paths, latest_view_normalized)
    market_adaptation_path = write_market_adaptation_report(paths, latest_view_normalized, cfg_obj)
    event_alert_path = write_live_event_alert_report(cfg_obj, paths)

    audit_path = paths["reports"] / "fundamental_collection_audit.json"
    universe_change_summary_path = paths["reports"] / "candidate_universe_change_latest.json"
    universe_change_detail_path = paths["reports"] / "candidate_universe_change_latest.csv"
    fund_missing_path = paths["reports"] / "fundamental_collection_missing_latest.csv"
    fund_snapshot_path = paths["reports"] / "fundamental_panel_latest_snapshot.csv"
    join_diag_path = paths["reports"] / "fundamental_join_latest_diagnostics.csv"
    fund_panel_path = paths["feature_store"] / "fund_panel_latest.parquet"
    universe_monthly_path = paths["feature_store"] / "universe_monthly_latest.parquet"
    candidate_universe_path = paths["feature_store"] / "candidate_universe_latest.parquet"
    live_latest_path = paths["cache_live_fund"] / "live_fundamentals_latest.parquet"

    audit = _safe_read_json(audit_path)
    universe_change = _safe_read_json(universe_change_summary_path)
    invalidated = _invalidate_downstream_artifacts(paths)

    summary = {
        "base_dir": cfg_obj.base_dir,
        "latest_rebalance_date": str(pd.Timestamp(latest_dt).date()) if pd.notna(latest_dt) else None,
        "latest_rows": int(len(latest_view)),
        "candidate_tickers": int(monthly.get("ticker", pd.Series(dtype=str)).astype(str).nunique()) if not monthly.empty else 0,
        "universe_source_mode": (
            latest_view.get("universe_source", pd.Series(dtype=str)).astype(str).mode().iloc[0]
            if not latest_view.empty
            and "universe_source" in latest_view.columns
            and not latest_view.get("universe_source", pd.Series(dtype=str)).mode().empty
            else "unknown"
        ),
        "core_latest_coverage": {
            "revenues_ttm": _safe_ratio(latest_view_normalized, "revenues_ttm"),
            "gross_profit_ttm": _safe_ratio(latest_view_normalized, "gross_profit_ttm"),
            "op_income_ttm": _safe_ratio(latest_view_normalized, "op_income_ttm"),
            "op_margin_ttm": _safe_ratio(latest_view_normalized, "op_margin_ttm"),
            "net_income_ttm": _safe_ratio(latest_view_normalized, "net_income_ttm"),
            "roe_proxy": _safe_ratio(latest_view_normalized, "roe_proxy"),
            "gross_margins": _safe_ratio(latest_view_normalized, "gross_margins"),
            "operating_margins": _safe_ratio(latest_view_normalized, "operating_margins"),
            "return_on_equity_live": _safe_ratio(latest_view_normalized, "return_on_equity_live"),
        },
        "fundamental_audit": audit,
        "universe_change": universe_change,
        "macro_style_tilt_label": str(_safe_read_json(market_adaptation_path).get("macro_style_tilt_label", "")),
        "invalidated_downstream_artifacts": invalidated,
        "output_files": {
            "candidate_universe_latest": str(candidate_universe_path),
            "universe_monthly_latest": str(universe_monthly_path),
            "fund_panel_latest": str(fund_panel_path),
            "live_fundamentals_latest": str(live_latest_path),
            "fundamental_coverage_latest": str(fundamental_cov_path),
            "fundamental_comprehensive_coverage_latest": str(comprehensive_cov_path),
            "live_fundamental_coverage_latest": str(live_cov_path),
            "market_adaptation_latest": str(market_adaptation_path),
            "event_alert_latest": str(event_alert_path),
            "fundamental_collection_audit": str(audit_path),
            "fundamental_collection_missing_latest": str(fund_missing_path),
            "fundamental_panel_latest_snapshot": str(fund_snapshot_path),
            "fundamental_join_latest_diagnostics": str(join_diag_path),
            "candidate_universe_change_summary": str(universe_change_summary_path),
            "candidate_universe_change_detail": str(universe_change_detail_path),
        },
    }

    summary_path = paths["out"] / "data_collection_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["output_files"]["data_collection_summary"] = str(summary_path)

    log("Collector summary:")
    log(
        "Latest coverage: "
        + ", ".join(f"{k}={v:.1%}" for k, v in summary["core_latest_coverage"].items())
    )
    if invalidated:
        log(f"Collector invalidated {len(invalidated)} downstream derived artifacts so the main pipeline rebuilds from fresh data.")
    log_core_fundamental_coverage(latest_view_normalized, "Collector coverage (latest universe)")
    if universe_change:
        log(
            "Universe change summary: "
            f"added={universe_change.get('added_count', 0)}, "
            f"removed={universe_change.get('removed_count', 0)}"
        )

    return summary


def run_full_validation_suite(
    cfg: Optional[dict[str, Any]] = None,
    rerun_pipeline: bool = False,
) -> dict[str, Any]:
    cfg_obj = to_cfg(cfg or collector_default_cfg())
    validate_config(cfg_obj)
    mount_drive_if_colab()
    paths = get_paths(cfg_obj)

    pipeline_result: dict[str, Any] | None = None
    if rerun_pipeline:
        from r1000_top30_institutional import run_default_pipeline

        log("Validation suite: running full pipeline before checks ...")
        pipeline_result = run_default_pipeline(cfg_obj)

    outputs = {
        "scored_latest": paths["out"] / "scored_latest.csv",
        "top20_latest": paths["out"] / "top20_latest.csv",
        "top30_latest": paths["out"] / "top30_latest.csv",
        "portfolio_latest": paths["out"] / "portfolio_latest.csv",
        "run_summary": paths["out"] / "run_summary.json",
        "fundamental_coverage_latest": paths["out"] / "fundamental_coverage_latest.csv",
        "fundamental_comprehensive_coverage_latest": paths["out"] / "fundamental_comprehensive_coverage_latest.csv",
        "live_fundamental_coverage_latest": paths["out"] / "live_fundamental_coverage_latest.csv",
        "portfolio_size_comparison": paths["reports"] / "portfolio_size_comparison.csv",
        "rebalance_interval_comparison": paths["reports"] / "rebalance_interval_comparison.csv",
        "sleeve_cap_policy_comparison": paths["reports"] / "sleeve_cap_policy_comparison.csv",
        "sleeve_cap_policy_champion_latest": paths["reports"] / "sleeve_cap_policy_champion_latest.json",
        "portfolio_sleeve_top7_standalone_comparison": paths["reports"] / "portfolio_sleeve_top7_standalone_comparison.csv",
        "historical_data_quality_by_month": paths["reports"] / "historical_data_quality_by_month.csv",
        "historical_data_quality_by_sleeve": paths["reports"] / "historical_data_quality_by_sleeve.csv",
        "historical_data_quality_latest": paths["reports"] / "historical_data_quality_latest.csv",
        "market_adaptation_latest": paths["reports"] / "market_adaptation_latest.json",
        "macro_regime_latest": paths["feature_store"] / "macro_regime_latest.parquet",
        "latest_recommendations": paths["feature_store"] / "latest_recommendations.parquet",
        "scored_oos_latest": paths["feature_store"] / "scored_oos_latest.parquet",
        "portfolio_decision_history": paths["ops"] / "portfolio_decision_history.parquet",
        "portfolio_holdings_history": paths["ops"] / "portfolio_holdings_history.parquet",
        "top30_recommendation_history": paths["ops"] / "top30_recommendation_history.parquet",
        "portfolio_realized_performance": paths["ops"] / "portfolio_realized_performance.parquet",
    }

    scored_latest = _safe_read_csv(outputs["scored_latest"])
    top20_latest = _safe_read_csv(outputs["top20_latest"])
    top30_latest = _safe_read_csv(outputs["top30_latest"])
    portfolio_latest = _safe_read_csv(outputs["portfolio_latest"])
    run_summary = _safe_read_json(outputs["run_summary"])
    fundamental_cov = _safe_read_csv(outputs["fundamental_coverage_latest"])
    comprehensive_cov = _safe_read_csv(outputs["fundamental_comprehensive_coverage_latest"])
    live_cov = _safe_read_csv(outputs["live_fundamental_coverage_latest"])
    portfolio_size_comp = _safe_read_csv(outputs["portfolio_size_comparison"])
    rebalance_interval_comp = _safe_read_csv(outputs["rebalance_interval_comparison"])
    sleeve_cap_policy_comp = _safe_read_csv(outputs["sleeve_cap_policy_comparison"])
    sleeve_cap_policy_champion = _safe_read_json(outputs["sleeve_cap_policy_champion_latest"])
    standalone_sleeve_comp = _safe_read_csv(outputs["portfolio_sleeve_top7_standalone_comparison"])
    historical_quality_monthly = _safe_read_csv(outputs["historical_data_quality_by_month"])
    historical_quality_sleeve = _safe_read_csv(outputs["historical_data_quality_by_sleeve"])
    historical_quality_latest = _safe_read_csv(outputs["historical_data_quality_latest"])
    market_adaptation = _safe_read_json(outputs["market_adaptation_latest"])
    macro_regime = _safe_read_parquet(outputs["macro_regime_latest"])
    latest_recommendations = _safe_read_parquet(outputs["latest_recommendations"])
    scored_oos_latest = _safe_read_parquet(outputs["scored_oos_latest"])
    portfolio_decision_history = _safe_read_parquet(outputs["portfolio_decision_history"])
    portfolio_holdings_history = _safe_read_parquet(outputs["portfolio_holdings_history"])
    top30_recommendation_history = _safe_read_parquet(outputs["top30_recommendation_history"])
    portfolio_realized_performance = _safe_read_parquet(outputs["portfolio_realized_performance"])

    model_features = model_feature_columns(cfg_obj)
    macro_cols = [
        "m2_yoy_lag1m",
        "fed_assets_bil",
        "reverse_repo_bil",
        "tga_bil",
        "net_liquidity_bil",
        "net_liquidity_change_1m_bil",
        "liquidity_impulse_score",
        "liquidity_drain_score",
    ]
    fear_greed_cols = [
        "fear_greed_score",
        "fear_greed_delta_1w",
        "fear_greed_risk_off_score",
        "fear_greed_risk_on_score",
    ]
    fundamental_cols = [
        "forward_pe_final",
        "peg_final",
        "op_margin_ttm",
        "gp_to_assets_ttm",
        "return_on_equity_effective",
        "roa_proxy",
        "asset_turnover_ttm",
        "book_to_market_proxy",
        "sales_growth_yoy",
        "sales_cagr_3y",
        "sales_cagr_5y",
        "op_income_cagr_3y",
        "op_income_cagr_5y",
        "net_income_cagr_3y",
        "net_income_cagr_5y",
        "revenues_ttm",
        "gross_profit_ttm",
        "op_income_ttm",
        "net_income_ttm",
        "ocf_ttm",
        "capex_ttm",
    ]
    ownership_cols = [
        "institutional_flow_signal_score",
        "insider_flow_signal_score",
        "ownership_flow_pillar_score",
        "multidimensional_confirmation_score",
    ]
    technical_cols = [
        "golden_cross_fresh_20d",
        "breakout_fresh_20d",
        "post_breakout_hold_score",
        "technical_blueprint_score",
    ]

    def _coverage_map(df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        return {c: _safe_ratio(df, c) for c in cols}

    portfolio_stock_count = 0
    portfolio_cash_weight = 0.0
    if not portfolio_latest.empty and "ticker" in portfolio_latest.columns:
        tickers = portfolio_latest["ticker"].astype(str).str.upper()
        portfolio_stock_count = int(tickers.ne(CASH_PROXY_TICKER).sum())
        if "weight" in portfolio_latest.columns:
            portfolio_cash_weight = float(
                pd.to_numeric(
                    portfolio_latest.loc[tickers.eq(CASH_PROXY_TICKER), "weight"],
                    errors="coerce",
                )
                .fillna(0.0)
                .sum()
            )

    sleeve_actual_weights: dict[str, float] = {}
    sleeve_selected_counts: dict[str, int] = {}
    if (
        not portfolio_latest.empty
        and "ticker" in portfolio_latest.columns
        and "weight" in portfolio_latest.columns
        and "portfolio_sleeve_label" in portfolio_latest.columns
    ):
        stock_only = portfolio_latest[
            portfolio_latest["ticker"].astype(str).str.upper().ne(CASH_PROXY_TICKER)
        ].copy()
        if not stock_only.empty:
            sleeve_grouped = (
                stock_only.assign(
                    portfolio_sleeve_label=stock_only["portfolio_sleeve_label"]
                    .fillna("core_compounder")
                    .astype(str)
                )
                .groupby("portfolio_sleeve_label")["weight"]
                .sum()
            )
            sleeve_actual_weights = {str(k): float(v) for k, v in sleeve_grouped.items()}
            sleeve_selected_counts = {
                str(k): int(v)
                for k, v in stock_only["portfolio_sleeve_label"]
                .fillna("core_compounder")
                .astype(str)
                .value_counts()
                .items()
            }

    dynamic_target_names = None
    fixed8_row: dict[str, Any] | None = None
    best_rebalance_row: dict[str, Any] | None = None
    best_sleeve_cap_policy_row: dict[str, Any] | None = None
    if not portfolio_size_comp.empty and "portfolio_mode" in portfolio_size_comp.columns:
        dynamic_rows = portfolio_size_comp[portfolio_size_comp["portfolio_mode"].astype(str).eq("dynamic")]
        if not dynamic_rows.empty:
            dynamic_target_names = safe_float(dynamic_rows.iloc[0].get("target_stock_names"))
        fixed_rows = portfolio_size_comp[
            portfolio_size_comp["target_stock_names"].astype(str).eq("8")
            | (pd.to_numeric(portfolio_size_comp["target_stock_names"], errors="coerce") == 8)
        ]
        if not fixed_rows.empty:
            fixed8_row = {}
            for k, v in fixed_rows.iloc[0].to_dict().items():
                if pd.isna(v):
                    fixed8_row[k] = None
                    continue
                num = safe_float(v)
                fixed8_row[k] = float(num) if pd.notna(num) else str(v)
    best_rebalance_summary = run_summary.get("rebalance_interval_optimization")
    if isinstance(best_rebalance_summary, dict) and best_rebalance_summary:
        best_rebalance_row = {}
        for k, v in best_rebalance_summary.items():
            if pd.isna(v):
                best_rebalance_row[k] = None
                continue
            num = safe_float(v)
            best_rebalance_row[k] = float(num) if pd.notna(num) else v
    elif not rebalance_interval_comp.empty and "rebalance_interval_months" in rebalance_interval_comp.columns:
        ranked = rebalance_interval_comp.copy()
        if "policy_mode" in ranked.columns:
            fixed_ranked = ranked[ranked["policy_mode"].astype(str).eq("fixed_interval")].copy()
            if not fixed_ranked.empty:
                ranked = fixed_ranked
        ir_source = ranked["ir"] if "ir" in ranked.columns else pd.Series(float("nan"), index=ranked.index)
        excess_source = (
            ranked["excess_cagr"] if "excess_cagr" in ranked.columns else pd.Series(float("nan"), index=ranked.index)
        )
        cagr_source = (
            ranked["strategy_cagr"] if "strategy_cagr" in ranked.columns else pd.Series(float("nan"), index=ranked.index)
        )
        ranked["ir_sort"] = pd.to_numeric(ir_source, errors="coerce").fillna(-1e18)
        ranked["excess_sort"] = pd.to_numeric(excess_source, errors="coerce").fillna(-1e18)
        ranked["cagr_sort"] = pd.to_numeric(cagr_source, errors="coerce").fillna(-1e18)
        ranked = ranked.sort_values(
            ["ir_sort", "excess_sort", "cagr_sort", "rebalance_interval_months"],
            ascending=[False, False, False, True],
        )
        if not ranked.empty:
            best_rebalance_row = {}
            for k, v in ranked.iloc[0].to_dict().items():
                if pd.isna(v):
                    best_rebalance_row[k] = None
                    continue
                num = safe_float(v)
                best_rebalance_row[k] = float(num) if pd.notna(num) else str(v)
    adaptive_rebalance_row = None
    if not rebalance_interval_comp.empty and "policy_mode" in rebalance_interval_comp.columns:
        adaptive_rows = rebalance_interval_comp[rebalance_interval_comp["policy_mode"].astype(str).eq("adaptive")]
        if not adaptive_rows.empty:
            adaptive_rebalance_row = {}
            for k, v in adaptive_rows.iloc[0].to_dict().items():
                if pd.isna(v):
                    adaptive_rebalance_row[k] = None
                    continue
                num = safe_float(v)
                adaptive_rebalance_row[k] = float(num) if pd.notna(num) else str(v)

    sleeve_cap_policy_summary = run_summary.get("champion_sleeve_cap_policy") or sleeve_cap_policy_champion
    if isinstance(sleeve_cap_policy_summary, dict) and sleeve_cap_policy_summary:
        best_sleeve_cap_policy_row = {}
        for k, v in sleeve_cap_policy_summary.items():
            if pd.isna(v):
                best_sleeve_cap_policy_row[k] = None
                continue
            num = safe_float(v)
            best_sleeve_cap_policy_row[k] = float(num) if pd.notna(num) else v
    elif not sleeve_cap_policy_comp.empty and "sleeve_cap_policy_objective" in sleeve_cap_policy_comp.columns:
        ranked_policy = sleeve_cap_policy_comp.copy()
        if "policy_status" in ranked_policy.columns:
            ranked_policy = ranked_policy[ranked_policy["policy_status"].astype(str).eq("ok")]
        ranked_policy["sleeve_cap_policy_objective"] = pd.to_numeric(
            ranked_policy["sleeve_cap_policy_objective"],
            errors="coerce",
        )
        ranked_policy = ranked_policy.dropna(subset=["sleeve_cap_policy_objective"]).sort_values(
            "sleeve_cap_policy_objective",
            ascending=False,
        )
        if not ranked_policy.empty:
            best_sleeve_cap_policy_row = {}
            for k, v in ranked_policy.iloc[0].to_dict().items():
                if pd.isna(v):
                    best_sleeve_cap_policy_row[k] = None
                    continue
                num = safe_float(v)
                best_sleeve_cap_policy_row[k] = float(num) if pd.notna(num) else str(v)

    def _jsonable_row(row: pd.Series) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in row.to_dict().items():
            if pd.isna(v):
                out[k] = None
                continue
            num = safe_float(v)
            out[k] = float(num) if pd.notna(num) else str(v)
        return out

    standalone_top_n_value = safe_float(run_summary.get("standalone_sleeve_top_n", 7))
    standalone_top_n = int(standalone_top_n_value) if pd.notna(standalone_top_n_value) and standalone_top_n_value >= 1 else 7
    standalone_sleeve_snapshot: dict[str, Any] = {
        "top_n": int(standalone_top_n),
        "rows": [],
        "best_by_sleeve": {},
        "adaptive_three_sleeve": None,
    }
    if not standalone_sleeve_comp.empty:
        standalone_sleeve_snapshot["rows"] = [
            _jsonable_row(row)
            for _, row in standalone_sleeve_comp.iterrows()
        ]
        if "portfolio_mode" in standalone_sleeve_comp.columns:
            adaptive_rows = standalone_sleeve_comp[
                standalone_sleeve_comp["portfolio_mode"].astype(str).eq("adaptive_three_sleeve")
            ]
            if not adaptive_rows.empty:
                standalone_sleeve_snapshot["adaptive_three_sleeve"] = _jsonable_row(adaptive_rows.iloc[0])
        if {"sleeve_test", "strategy_cagr"}.issubset(standalone_sleeve_comp.columns):
            standalone_rows = standalone_sleeve_comp.copy()
            if "portfolio_mode" in standalone_rows.columns:
                standalone_rows = standalone_rows[
                    standalone_rows["portfolio_mode"].astype(str).eq("standalone_sleeve_topn")
                ].copy()
            standalone_rows["strategy_cagr_sort"] = pd.to_numeric(
                standalone_rows["strategy_cagr"],
                errors="coerce",
            ).fillna(-1e18)
            sharpe_source = (
                standalone_rows["sharpe"]
                if "sharpe" in standalone_rows.columns
                else pd.Series(float("nan"), index=standalone_rows.index)
            )
            standalone_rows["sharpe_sort"] = pd.to_numeric(
                sharpe_source,
                errors="coerce",
            ).fillna(-1e18)
            for sleeve, grp in standalone_rows.groupby("sleeve_test", sort=True):
                ranked = grp.sort_values(["strategy_cagr_sort", "sharpe_sort"], ascending=False)
                if not ranked.empty:
                    standalone_sleeve_snapshot["best_by_sleeve"][str(sleeve)] = _jsonable_row(ranked.iloc[0])

    historical_quality_snapshot: dict[str, Any] = {
        "monthly_rows": int(len(historical_quality_monthly)),
        "sleeve_rows": int(len(historical_quality_sleeve)),
        "latest_rows": int(len(historical_quality_latest)),
        "latest_summary": run_summary.get("historical_data_quality_latest", {}),
        "latest_by_sleeve": [],
        "monthly_tail": [],
    }
    if not historical_quality_sleeve.empty:
        sleeve_view = historical_quality_sleeve.copy()
        if "rebalance_date" in sleeve_view.columns:
            sleeve_view["rebalance_date"] = pd.to_datetime(sleeve_view["rebalance_date"], errors="coerce")
            latest_q_dt = sleeve_view["rebalance_date"].max()
            if pd.notna(latest_q_dt):
                sleeve_view = sleeve_view[sleeve_view["rebalance_date"].eq(latest_q_dt)]
        cols = [
            c
            for c in [
                "rebalance_date",
                "portfolio_sleeve_label",
                "rows",
                "tickers",
                "fundamental_history_coverage_score_mean",
                "growth_sleeve_data_confidence_mean",
                "growth_sleeve_sparse_history_penalty_mean",
                "sales_cagr_3y_coverage",
                "forward_return_coverage_score_mean",
            ]
            if c in sleeve_view.columns
        ]
        historical_quality_snapshot["latest_by_sleeve"] = [
            _jsonable_row(row) for _, row in sleeve_view[cols].iterrows()
        ] if cols else []
    if not historical_quality_monthly.empty:
        monthly_view = historical_quality_monthly.tail(6).copy()
        historical_quality_snapshot["monthly_tail"] = [
            _jsonable_row(row) for _, row in monthly_view.iterrows()
        ]

    latest_fg_nonzero_share = 0.0
    latest_fg_abs_mean = 0.0
    if not latest_recommendations.empty and "score_fear_greed_satellite" in latest_recommendations.columns:
        fg_sat = pd.to_numeric(latest_recommendations["score_fear_greed_satellite"], errors="coerce").fillna(0.0)
        latest_fg_nonzero_share = float((fg_sat.abs() > 1e-12).mean())
        latest_fg_abs_mean = float(fg_sat.abs().mean())

    ops_snapshot = {
        "decision_rows": int(len(portfolio_decision_history)),
        "holdings_rows": int(len(portfolio_holdings_history)),
        "recommendation_rows": int(len(top30_recommendation_history)),
        "realized_rows": int(len(portfolio_realized_performance)),
        "latest_prev_holdings_applied": (
            bool(
                portfolio_latest.get("prev_holdings_applied", pd.Series(dtype=bool))
                .fillna(False)
                .astype(bool)
                .any()
            )
            if not portfolio_latest.empty and "prev_holdings_applied" in portfolio_latest.columns
            else False
        ),
    }
    if not portfolio_realized_performance.empty:
        latest_realized = portfolio_realized_performance.sort_values(
            [c for c in ["rebalance_date", "run_timestamp_utc"] if c in portfolio_realized_performance.columns]
        ).iloc[-1]
        ops_snapshot["latest_realized_1m"] = safe_float(latest_realized.get("portfolio_return_1m"))
        ops_snapshot["latest_realized_3m"] = safe_float(latest_realized.get("portfolio_return_3m"))
        ops_snapshot["latest_realized_6m"] = safe_float(latest_realized.get("portfolio_return_6m"))
        ops_snapshot["latest_realized_12m"] = safe_float(latest_realized.get("portfolio_return_12m"))
        ops_snapshot["latest_coverage_weight_1m"] = safe_float(latest_realized.get("coverage_weight_1m"))
        ops_snapshot["latest_coverage_weight_3m"] = safe_float(latest_realized.get("coverage_weight_3m"))
        ops_snapshot["latest_coverage_weight_6m"] = safe_float(latest_realized.get("coverage_weight_6m"))
        ops_snapshot["latest_coverage_weight_12m"] = safe_float(latest_realized.get("coverage_weight_12m"))
        ops_snapshot["latest_coverage_ok_1m"] = bool(latest_realized.get("coverage_ok_1m", False))
        ops_snapshot["latest_coverage_ok_3m"] = bool(latest_realized.get("coverage_ok_3m", False))
        ops_snapshot["latest_coverage_ok_6m"] = bool(latest_realized.get("coverage_ok_6m", False))
        ops_snapshot["latest_coverage_ok_12m"] = bool(latest_realized.get("coverage_ok_12m", False))
    if not portfolio_decision_history.empty:
        latest_decision = portfolio_decision_history.sort_values(
            [c for c in ["rebalance_date", "run_timestamp_utc"] if c in portfolio_decision_history.columns]
        ).iloc[-1]
        ops_snapshot["latest_rebalance_action"] = latest_decision.get("rebalance_action")
        ops_snapshot["latest_active_rebalance_interval_months"] = safe_float(
            latest_decision.get("active_rebalance_interval_months")
        )
        ops_snapshot["latest_scheduled_rebalance_due"] = bool(latest_decision.get("scheduled_rebalance_due", True))
        ops_snapshot["latest_next_scheduled_rebalance_date"] = latest_decision.get("next_scheduled_rebalance_date")
        ops_snapshot["latest_adaptive_rebalance_policy"] = bool(latest_decision.get("adaptive_rebalance_policy", False))
        ops_snapshot["latest_avg_rebalance_interval_months"] = safe_float(
            latest_decision.get("avg_rebalance_interval_months")
        )

    report = {
        "base_dir": cfg_obj.base_dir,
        "reran_pipeline": bool(rerun_pipeline),
        "pipeline_outputs": pipeline_result.get("outputs", {}) if pipeline_result else {},
        "acceptance_checks": pipeline_result.get("acceptance_checks", {}) if pipeline_result else run_summary.get("acceptance_checks", {}),
        "output_files": {k: str(v) for k, v in outputs.items()},
        "row_counts": {
            "scored_latest": int(len(scored_latest)),
            "top20_latest": int(len(top20_latest)),
            "top30_latest": int(len(top30_latest)),
            "portfolio_latest": int(len(portfolio_latest)),
            "latest_recommendations": int(len(latest_recommendations)),
            "scored_oos_latest": int(len(scored_oos_latest)),
        },
        "portfolio_shape": {
            "stock_count": int(portfolio_stock_count),
            "cash_weight": float(portfolio_cash_weight),
        },
        "sleeve_policy_snapshot": {
            "target_weights": run_summary.get("portfolio_sleeve_target_weights", {}),
            "actual_weights": run_summary.get("portfolio_sleeve_actual_weights", sleeve_actual_weights),
            "selected_counts": run_summary.get("portfolio_sleeve_selected_counts", sleeve_selected_counts),
            "future_winner_regime_strength": safe_float(run_summary.get("future_winner_regime_strength")),
            "early_scout_regime_strength": safe_float(run_summary.get("early_scout_regime_strength")),
            "growth_signal": safe_float(run_summary.get("sleeve_growth_signal")),
            "risk_signal": safe_float(run_summary.get("sleeve_risk_signal")),
        },
        "sleeve_cap_policy_optimization_snapshot": {
            "champion": best_sleeve_cap_policy_row,
            "applied": bool(run_summary.get("sleeve_cap_policy_applied", False)),
            "candidate_count": int(len(sleeve_cap_policy_comp)),
        },
        "standalone_sleeve_topn_backtest_snapshot": standalone_sleeve_snapshot,
        "historical_data_quality_snapshot": historical_quality_snapshot,
        "coverage": {
            "macro_scored_latest": _coverage_map(scored_latest, macro_cols),
            "macro_feature_store_latest": _coverage_map(latest_recommendations, macro_cols + fear_greed_cols),
            "macro_regime_latest": _coverage_map(macro_regime, macro_cols + fear_greed_cols),
            "macro_oos": _coverage_map(scored_oos_latest, macro_cols),
            "fundamental_scored_latest": _coverage_map(scored_latest, fundamental_cols),
            "ownership_scored_latest": _coverage_map(scored_latest, ownership_cols),
            "technical_scored_latest": _coverage_map(scored_latest, technical_cols),
        },
        "model_feature_checks": {
            "fear_greed_in_model_features": [c for c in fear_greed_cols if c in model_features],
            "macro_in_model_features": [c for c in macro_cols if c in model_features],
        },
        "p1_p2_p3_checks": {
            "p1_weight_model_simplified": bool(
                float(cfg_obj.weight_score_power) <= 1.30
                and float(cfg_obj.weight_invvol_power) <= 0.25
                and int(cfg_obj.min_dynamic_port_names) >= 4
                and float(cfg_obj.stock_weight_max_high_conviction) <= 0.50
                and float(cfg_obj.portfolio_confirmation_utility_boost) == 0.0
                and float(cfg_obj.portfolio_garp_utility_boost) == 0.0
                and float(cfg_obj.portfolio_anticipatory_utility_boost) == 0.0
                and float(cfg_obj.portfolio_top1_conviction_boost) == 0.0
                and float(cfg_obj.portfolio_top2_conviction_boost) == 0.0
            ),
            "p2_fear_greed_satellite_only": bool(
                len([c for c in fear_greed_cols if c in model_features]) == 0
                and float(getattr(cfg_obj, "fear_greed_live_overlay_weight", 0.0)) <= 0.05
            ),
            "p2_latest_overlay_active": bool(latest_fg_nonzero_share > 0.0),
            "sleeve_split_active": bool(
                "portfolio_sleeve_label" in portfolio_latest.columns
                and len(sleeve_actual_weights) >= 1
                and safe_float(run_summary.get("portfolio_sleeve_target_weights", {}).get("core_compounder", 0.0)) > 0.0
                and "early_scout" in (run_summary.get("portfolio_sleeve_target_weights", {}) or {})
            ),
            "p3_top30_rows_ok": bool(top30_latest.empty or len(top30_latest) >= min(max(int(cfg_obj.top_n), 30), len(scored_latest) or 0)),
            "p3_dynamic_target_names_populated": bool(dynamic_target_names is None or float(dynamic_target_names) > 0),
        },
        "design_guard_checks": {
            "live_backtest_alignment_strict": bool(
                run_summary.get("strict_live_backtest_alignment", getattr(cfg_obj, "strict_live_backtest_alignment", False))
            ),
            "ops_realized_coverage_guard_active": bool(
                safe_float(run_summary.get("ops_min_realized_coverage", getattr(cfg_obj, "ops_min_realized_coverage", 0.0))) >= 0.90
            ),
            "adaptive_policy_backtested": bool(run_summary.get("adaptive_rebalance_policy", False)),
            "sleeve_cap_policy_optimized": bool(best_sleeve_cap_policy_row),
        },
        "latest_sentiment_overlay": {
            "fear_greed_live_overlay_weight": float(getattr(cfg_obj, "fear_greed_live_overlay_weight", 0.0)),
            "score_fear_greed_satellite_nonzero_share": float(latest_fg_nonzero_share),
            "score_fear_greed_satellite_abs_mean": float(latest_fg_abs_mean),
        },
        "adaptive_ensemble_snapshot": {
            "enabled": bool(getattr(cfg_obj, "adaptive_ensemble_enabled", False)),
            "weights": run_summary.get("adaptive_ensemble_weights", {}),
            "diagnostics": run_summary.get("adaptive_ensemble_diagnostics", {}),
        },
        "backtest_policy_snapshot": {
            "adaptive_rebalance_policy": bool(run_summary.get("adaptive_rebalance_policy", False)),
            "avg_rebalance_interval_months": safe_float(run_summary.get("avg_rebalance_interval_months")),
            "rebalance_count": int(safe_float(run_summary.get("rebalance_count", 0)) or 0),
            "rebalanced_month_ratio": safe_float(run_summary.get("rebalanced_month_ratio")),
            "strict_live_backtest_alignment": bool(
                run_summary.get("strict_live_backtest_alignment", getattr(cfg_obj, "strict_live_backtest_alignment", False))
            ),
            "ops_min_realized_coverage": safe_float(
                run_summary.get("ops_min_realized_coverage", getattr(cfg_obj, "ops_min_realized_coverage", 0.0))
            ),
        },
        "ops_tracking_snapshot": ops_snapshot,
        "portfolio_size_comparison_snapshot": {
            "dynamic_target_stock_names": dynamic_target_names,
            "fixed8": fixed8_row,
        },
        "rebalance_interval_comparison_snapshot": {
            "best_interval": best_rebalance_row,
            "adaptive_policy_row": adaptive_rebalance_row,
        },
        "market_adaptation_snapshot": {
            "macro_style_tilt_label": market_adaptation.get("macro_style_tilt_label"),
            "liquidity_backdrop_label": market_adaptation.get("liquidity_backdrop_label"),
            "fear_greed_label": market_adaptation.get("fear_greed_label"),
        },
        "coverage_reports_preview": {
            "fundamental_coverage_rows": int(len(fundamental_cov)),
            "fundamental_comprehensive_rows": int(len(comprehensive_cov)),
            "live_fundamental_coverage_rows": int(len(live_cov)),
            "historical_data_quality_monthly_rows": int(len(historical_quality_monthly)),
            "historical_data_quality_sleeve_rows": int(len(historical_quality_sleeve)),
            "historical_data_quality_latest_rows": int(len(historical_quality_latest)),
        },
    }

    report_path = paths["reports"] / "full_validation_suite.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_files"]["full_validation_suite"] = str(report_path)
    log(f"Validation suite report saved to {report_path}")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect and audit Russell 1000 data only.")
    parser.add_argument("--base-dir", default=os.getcwd(), help="Project base directory for caches and outputs.")
    parser.add_argument(
        "--preset",
        default="collector",
        choices=["collector", "full-run", "lean-full-run", "reuse-step2", "coverage-debug"],
        help="Config preset tuned for default collection, full rebuild, lean rebuild, fast Step 2 reuse, or coverage debugging.",
    )
    parser.add_argument("--end-date", default="", help="Optional YYYY-MM-DD override for the pipeline end date.")
    parser.add_argument("--companyfacts-refresh-days", type=int, default=3, help="SEC companyfacts cache freshness days.")
    parser.add_argument("--live-refresh-days", type=int, default=0, help="Live fundamentals cache freshness days.")
    parser.add_argument("--macro-refresh-days", type=int, default=0, help="Macro cache freshness days.")
    parser.add_argument(
        "--alpha-vantage-free-refresh-tickers",
        type=int,
        default=8,
        help="Max Alpha Vantage overview/estimate refresh tickers under free-tier mode.",
    )
    parser.add_argument(
        "--alpha-vantage-free-statement-repair-tickers",
        type=int,
        default=6,
        help="Max Alpha Vantage statement-repair tickers under free-tier mode.",
    )
    parser.add_argument(
        "--alpha-vantage-free-statement-refresh-days",
        type=int,
        default=14,
        help="Cache freshness days for latest statement repair under free-tier mode.",
    )
    parser.add_argument(
        "--macro-slow-release-lag-months",
        type=int,
        default=1,
        help="Lag in months for slow macro series like CPI/PPI/UNRATE/Sahm.",
    )
    parser.add_argument(
        "--cash-target-growth-cap",
        type=float,
        default=0.03,
        help="Growth regime cash target cap.",
    )
    parser.add_argument(
        "--cash-target-balanced-cap",
        type=float,
        default=0.05,
        help="Balanced regime cash target cap.",
    )
    parser.add_argument(
        "--cash-target-mild-risk-cap",
        type=float,
        default=0.10,
        help="Mild risk regime cash target cap.",
    )
    parser.add_argument(
        "--core-compounder-sleeve-base-weight",
        type=float,
        default=0.55,
        help="Base portfolio weight for the core compounder sleeve.",
    )
    parser.add_argument(
        "--future-winner-sleeve-base-weight",
        type=float,
        default=0.35,
        help="Base portfolio weight for the future winner sleeve.",
    )
    parser.add_argument(
        "--future-winner-sleeve-min-weight",
        type=float,
        default=0.05,
        help="Minimum future winner sleeve weight.",
    )
    parser.add_argument(
        "--future-winner-sleeve-max-weight",
        type=float,
        default=0.60,
        help="Maximum future winner sleeve weight.",
    )
    parser.add_argument(
        "--early-scout-sleeve-base-weight",
        type=float,
        default=0.08,
        help="Base portfolio weight for the early scout sleeve.",
    )
    parser.add_argument(
        "--early-scout-sleeve-min-weight",
        type=float,
        default=0.00,
        help="Minimum early scout sleeve weight.",
    )
    parser.add_argument(
        "--early-scout-sleeve-max-weight",
        type=float,
        default=0.20,
        help="Maximum early scout sleeve weight.",
    )
    parser.add_argument(
        "--early-scout-growth-floor-weight",
        type=float,
        default=0.08,
        help="Minimum scout sleeve target to preserve in non-risk-off growth regimes when candidates exist.",
    )
    parser.add_argument(
        "--early-scout-growth-floor-min-signal",
        type=float,
        default=0.38,
        help="Growth signal threshold for activating the early scout floor.",
    )
    parser.add_argument(
        "--early-scout-growth-floor-max-risk",
        type=float,
        default=0.55,
        help="Risk signal ceiling for activating the early scout floor.",
    )
    parser.add_argument(
        "--early-scout-candidate-floor-min-share",
        type=float,
        default=0.01,
        help="Minimum early scout candidate share needed before applying the growth floor.",
    )
    parser.add_argument(
        "--disable-sleeve-cap-policy-comparison",
        action="store_true",
        help="Disable OOS sleeve/cap policy candidate optimization.",
    )
    parser.add_argument(
        "--disable-sleeve-cap-policy-champion",
        action="store_true",
        help="Identify but do not apply the sleeve/cap champion policy to the active run.",
    )
    parser.add_argument(
        "--sleeve-cap-policy-max-candidates",
        type=int,
        default=9,
        help="Maximum sleeve/cap policy candidates to backtest.",
    )
    parser.add_argument(
        "--disable-standalone-sleeve-backtest-comparison",
        action="store_true",
        help="Disable standalone core/future/early top-N sleeve backtest comparison.",
    )
    parser.add_argument(
        "--standalone-sleeve-top-n",
        type=int,
        default=7,
        help="Number of names in each standalone sleeve backtest portfolio.",
    )
    parser.add_argument(
        "--standalone-sleeve-rebalance-intervals",
        default="1,3",
        help="Comma-separated rebalance intervals for standalone sleeve backtests.",
    )
    parser.add_argument(
        "--disable-historical-data-quality-reports",
        action="store_true",
        help="Disable historical financial/forward-return data quality report exports.",
    )
    parser.add_argument(
        "--growth-history-confidence-penalty-weight",
        type=float,
        default=0.18,
        help="Mild penalty weight for growth sleeves when both financial history and technical confirmation are sparse.",
    )
    parser.add_argument(
        "--growth-history-confidence-min-for-full-sleeve",
        type=float,
        default=0.35,
        help="Diagnostic threshold for treating growth sleeve data confidence as adequate.",
    )
    parser.add_argument("--max-live-refresh-tickers", type=int, default=1000, help="Max tickers for live refresh.")
    parser.add_argument(
        "--force-full-fund-panel-rebuild",
        action="store_true",
        help="Force rebuilding the SEC/FSDS fundamental panel from scratch.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.preset == "full-run":
        cfg = collector_full_run_cfg(base_dir=args.base_dir, end_date=args.end_date or None)
    elif args.preset == "lean-full-run":
        cfg = collector_lean_full_run_cfg(base_dir=args.base_dir, end_date=args.end_date or None)
    elif args.preset == "reuse-step2":
        cfg = collector_reuse_step2_cfg(base_dir=args.base_dir, end_date=args.end_date or None)
    elif args.preset == "coverage-debug":
        cfg = collector_coverage_debug_cfg(base_dir=args.base_dir, end_date=args.end_date or None)
    else:
        cfg = collector_default_cfg(base_dir=args.base_dir)
        cfg = _apply_notebook_runtime_defaults(cfg)
        if args.end_date:
            cfg["end_date"] = str(args.end_date)
    cfg["companyfacts_refresh_days"] = int(args.companyfacts_refresh_days)
    cfg["live_refresh_days"] = int(args.live_refresh_days)
    cfg["macro_refresh_days"] = int(args.macro_refresh_days)
    cfg["alpha_vantage_free_refresh_tickers"] = int(args.alpha_vantage_free_refresh_tickers)
    cfg["alpha_vantage_free_statement_repair_tickers"] = int(args.alpha_vantage_free_statement_repair_tickers)
    cfg["alpha_vantage_free_statement_refresh_days"] = int(args.alpha_vantage_free_statement_refresh_days)
    cfg["macro_slow_release_lag_months"] = int(args.macro_slow_release_lag_months)
    cfg["cash_target_growth_cap"] = float(args.cash_target_growth_cap)
    cfg["cash_target_balanced_cap"] = float(args.cash_target_balanced_cap)
    cfg["cash_target_mild_risk_cap"] = float(args.cash_target_mild_risk_cap)
    cfg["core_compounder_sleeve_base_weight"] = float(args.core_compounder_sleeve_base_weight)
    cfg["future_winner_sleeve_base_weight"] = float(args.future_winner_sleeve_base_weight)
    cfg["future_winner_sleeve_min_weight"] = float(args.future_winner_sleeve_min_weight)
    cfg["future_winner_sleeve_max_weight"] = float(args.future_winner_sleeve_max_weight)
    cfg["early_scout_sleeve_base_weight"] = float(args.early_scout_sleeve_base_weight)
    cfg["early_scout_sleeve_min_weight"] = float(args.early_scout_sleeve_min_weight)
    cfg["early_scout_sleeve_max_weight"] = float(args.early_scout_sleeve_max_weight)
    cfg["early_scout_growth_floor_weight"] = float(args.early_scout_growth_floor_weight)
    cfg["early_scout_growth_floor_min_signal"] = float(args.early_scout_growth_floor_min_signal)
    cfg["early_scout_growth_floor_max_risk"] = float(args.early_scout_growth_floor_max_risk)
    cfg["early_scout_candidate_floor_min_share"] = float(args.early_scout_candidate_floor_min_share)
    cfg["run_sleeve_cap_policy_comparison"] = not bool(args.disable_sleeve_cap_policy_comparison)
    cfg["sleeve_cap_policy_apply_champion"] = not bool(args.disable_sleeve_cap_policy_champion)
    cfg["sleeve_cap_policy_max_candidates"] = int(args.sleeve_cap_policy_max_candidates)
    cfg["run_standalone_sleeve_backtest_comparison"] = not bool(args.disable_standalone_sleeve_backtest_comparison)
    cfg["standalone_sleeve_top_n"] = int(args.standalone_sleeve_top_n)
    cfg["standalone_sleeve_rebalance_intervals"] = [
        int(x.strip())
        for x in str(args.standalone_sleeve_rebalance_intervals).split(",")
        if x.strip()
    ]
    cfg["run_historical_data_quality_reports"] = not bool(args.disable_historical_data_quality_reports)
    cfg["growth_history_confidence_penalty_weight"] = float(args.growth_history_confidence_penalty_weight)
    cfg["growth_history_confidence_min_for_full_sleeve"] = float(
        args.growth_history_confidence_min_for_full_sleeve
    )
    cfg["max_live_refresh_tickers"] = int(args.max_live_refresh_tickers)
    cfg["force_full_fund_panel_rebuild"] = bool(args.force_full_fund_panel_rebuild)

    summary = run_data_collection(cfg)
    print(json.dumps(summary["output_files"], indent=2))


if __name__ == "__main__":
    main()
