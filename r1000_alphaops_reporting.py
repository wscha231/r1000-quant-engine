"""AlphaOps report-only outputs.

This module writes comparison and governance artifacts for the AlphaOps
promotion path. It must stay additive: no portfolio selection, model features,
or backtest behavior are changed here.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from r1000_config import ENGINE_REUSE_VERSION, MANDATE_REGISTRY
from r1000_orchestrator import (
    audit_unified_portfolio,
    compose_unified_portfolio,
    write_orchestrator_output_bundle,
)


ALPHAOPS_REPORT_VERSION = "2026-05-02-alphaops-stage0-2"

BASELINE_CONTROLS = {
    "phase15d": {
        "name": "Phase 15-D global_alpha_universe",
        "cagr": 0.2451,
        "sharpe": 1.2453,
        "max_dd": -0.2579,
        "ir": 1.0244,
        "avg_turnover_monthly": 0.4854,
        "avg_stock_names": 24.33,
        "beat_month_ratio": 0.5663,
        "excess_cagr": 0.1102,
    },
    "latest_phase17_19_pre_alphaops": {
        "name": "Phase 17-19 sidecar validation run",
        "commit": "242f02f",
        "cagr": 0.23345,
        "sharpe": 1.2949,
        "max_dd": -0.2374,
        "concentrated_cagr": 0.37328,
        "concentrated_sharpe": 1.4471,
        "concentrated_max_dd": -0.2306,
        "verdict": "PARTIAL vs Phase 15-D",
    },
}


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_clean_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean_json(dict(payload)), indent=2), encoding="utf-8")


def _mode_text(frame: pd.DataFrame, column: str, default: str = "") -> str:
    if frame is None or frame.empty or column not in frame.columns:
        return default
    values = frame[column].dropna().astype(str).str.strip()
    values = values[values != ""]
    if values.empty:
        return default
    mode = values.mode()
    return str(mode.iloc[0]) if not mode.empty else default


def _frame_weights(frame: Optional[pd.DataFrame]) -> dict[str, float]:
    if frame is None or frame.empty or "ticker" not in frame.columns or "weight" not in frame.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in frame.iterrows():
        ticker = str(row.get("ticker", "") or "").strip().upper()
        if not ticker or ticker == "CASH":
            continue
        weight = pd.to_numeric(row.get("weight"), errors="coerce")
        if pd.notna(weight) and float(weight) > 0:
            out[ticker] = float(weight)
    return out


def _portfolio_summary(frame: Optional[pd.DataFrame]) -> dict[str, Any]:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return {"n_positions": 0, "cash_weight": 0.0, "tickers": []}
    tickers = frame["ticker"].astype(str).str.upper().str.strip()
    stock_mask = tickers.ne("CASH")
    cash_weight = 0.0
    if "weight" in frame.columns:
        cash_weight = float(pd.to_numeric(frame.loc[~stock_mask, "weight"], errors="coerce").fillna(0.0).sum())
    return {
        "n_positions": int(stock_mask.sum()),
        "cash_weight": cash_weight,
        "tickers": [str(t) for t in tickers[stock_mask].tolist()],
    }


def _scored_diagnostics(scored_latest: Optional[pd.DataFrame], portfolio_latest: Optional[pd.DataFrame]) -> dict[str, Any]:
    if scored_latest is None or scored_latest.empty:
        return {
            "n_scored_latest": 0,
            "regime_distribution": {},
            "explosion_columns_present": [],
            "explosion_nonzero": False,
        }
    scored = scored_latest.copy()
    tickers_selected = set(_portfolio_summary(portfolio_latest).get("tickers", []))
    ticker_col = scored["ticker"].astype(str).str.upper() if "ticker" in scored.columns else pd.Series(dtype=str)

    adr_cols = [
        c for c in scored.columns
        if c.lower() in {
            "is_adr",
            "is_adr_global_alpha",
            "adr_global_alpha_member",
            "global_alpha_universe_member",
            "is_global_alpha_adr",
        }
    ]
    adr_mask = pd.Series(False, index=scored.index)
    for col in adr_cols:
        adr_mask = adr_mask | scored[col].fillna(False).astype(bool)

    explosion_cols = [c for c in ["explosion_entry_score", "explosion_exit_score", "explosion_net_score"] if c in scored.columns]
    explosion_nonzero = False
    if explosion_cols:
        vals = scored[explosion_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).abs().sum().sum()
        explosion_nonzero = bool(vals > 0)

    return {
        "n_scored_latest": int(len(scored)),
        "regime_distribution": (
            scored["regime_state"].fillna("missing").astype(str).value_counts().to_dict()
            if "regime_state" in scored.columns else {}
        ),
        "live_event_alert_distribution": (
            scored["live_event_alert_label"].fillna("missing").astype(str).value_counts().to_dict()
            if "live_event_alert_label" in scored.columns else {}
        ),
        "explosion_columns_present": explosion_cols,
        "explosion_nonzero": explosion_nonzero,
        "adr_indicator_columns": adr_cols,
        "adr_rows": int(adr_mask.sum()) if adr_cols else None,
        "adr_selected_count": int(ticker_col[adr_mask].isin(tickers_selected).sum()) if adr_cols else None,
    }


def _extract_workflow_default(workflow_path: Path, input_name: str) -> Optional[str]:
    if not workflow_path.exists():
        return None
    text = workflow_path.read_text(encoding="utf-8")
    pattern = rf"(?ms)^\s*{re.escape(input_name)}:\s*\n(?P<body>(?:\s{{10,}}.*\n){{0,16}})"
    match = re.search(pattern, text)
    if not match:
        return None
    default_match = re.search(r"^\s*default:\s*['\"]?([^'\"\n]+)['\"]?\s*$", match.group("body"), re.MULTILINE)
    return default_match.group(1).strip() if default_match else None


def _read_colab_fast_mode(repo_root: Path) -> Optional[str]:
    nb_path = repo_root / "colab_run.ipynb"
    if not nb_path.exists():
        return None
    try:
        payload = json.loads(nb_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    source = "\n".join(
        "".join(cell.get("source", [])) if isinstance(cell.get("source", []), list) else str(cell.get("source", ""))
        for cell in payload.get("cells", [])
    )
    match = re.search(r"\bFAST_MODE\s*=\s*(True|False|true|false)", source)
    return match.group(1) if match else None


def write_baseline_registry(
    cfg: Any,
    paths: Mapping[str, Path],
    *,
    run_identity: Mapping[str, Any],
    backtest_metrics: Mapping[str, Any],
    concentrated_metrics: Mapping[str, Any],
    scored_latest: Optional[pd.DataFrame],
    portfolio_latest: Optional[pd.DataFrame],
    backtest_window_compare: Optional[pd.DataFrame],
    output_files: Mapping[str, Any],
) -> dict[str, str]:
    report_path = Path(paths["reports"]) / "baseline_registry.json"
    md_path = Path(paths["reports"]) / "baseline_registry.md"
    diagnostics = _scored_diagnostics(scored_latest, portfolio_latest)
    window_records = (
        backtest_window_compare.to_dict(orient="records")
        if backtest_window_compare is not None and not backtest_window_compare.empty
        else []
    )
    payload = {
        "report_version": ALPHAOPS_REPORT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "controls": BASELINE_CONTROLS,
        "current_run": {
            "run_identity": dict(run_identity),
            "engine_version": ENGINE_REUSE_VERSION,
            "base_dir": str(getattr(cfg, "base_dir", "")),
            "universe_mode": str(getattr(cfg, "universe_mode", "")),
            "default_backtest_years": int(getattr(cfg, "default_backtest_years", 0)),
            "fast_mode": bool(getattr(cfg, "fast_mode", False)),
            "trade_cost_bps_per_side": float(getattr(cfg, "trade_cost_bps_per_side", 0.0)),
            "metrics": dict(backtest_metrics or {}),
            "concentrated_metrics": dict(concentrated_metrics or {}),
            "portfolio": _portfolio_summary(portfolio_latest),
            "diagnostics": diagnostics,
            "backtest_window_comparison": window_records,
        },
        "artifact_paths": {str(k): str(v) for k, v in dict(output_files or {}).items()},
    }
    _write_json(report_path, payload)

    metrics = payload["current_run"]["metrics"]
    conc = payload["current_run"]["concentrated_metrics"]
    lines = [
        "# AlphaOps Baseline Registry",
        "",
        f"- Generated UTC: {payload['generated_at_utc']}",
        f"- Engine version: {ENGINE_REUSE_VERSION}",
        f"- Commit: {run_identity.get('git_commit')}",
        f"- Universe: {payload['current_run']['universe_mode']}",
        f"- Backtest years: {payload['current_run']['default_backtest_years']}",
        "",
        "## Current Main",
        "",
        f"- CAGR: {float(metrics.get('cagr', 0.0) or 0.0):.4f}",
        f"- Sharpe: {float(metrics.get('sharpe', 0.0) or 0.0):.4f}",
        f"- MaxDD: {float(metrics.get('max_dd', 0.0) or 0.0):.4f}",
        f"- Avg turnover monthly: {float(metrics.get('avg_turnover_monthly', 0.0) or 0.0):.4f}",
        "",
        "## Current Concentrated",
        "",
        f"- CAGR: {float(conc.get('cagr', conc.get('strategy_cagr', 0.0)) or 0.0):.4f}",
        f"- Sharpe: {float(conc.get('sharpe', 0.0) or 0.0):.4f}",
        f"- MaxDD: {float(conc.get('max_dd', 0.0) or 0.0):.4f}",
        "",
        "## Diagnostics",
        "",
        f"- Scored latest rows: {diagnostics.get('n_scored_latest')}",
        f"- Regime distribution: {diagnostics.get('regime_distribution')}",
        f"- Explosion nonzero: {diagnostics.get('explosion_nonzero')}",
        f"- ADR rows: {diagnostics.get('adr_rows')}",
        f"- ADR selected count: {diagnostics.get('adr_selected_count')}",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "baseline_registry": str(report_path),
        "baseline_registry_md": str(md_path),
    }


def write_config_audit(cfg: Any, paths: Mapping[str, Path], *, run_identity: Mapping[str, Any]) -> dict[str, str]:
    repo_root = Path(__file__).resolve().parent
    report_path = Path(paths["reports"]) / "config_audit.json"
    md_path = Path(paths["reports"]) / "config_audit.md"
    workflow = repo_root / ".github" / "workflows" / "full_rebuild_manual.yml"
    active_gates = repo_root / "research" / "auto_feature_gates.yaml"

    observed = {
        "cfg_default_backtest_years": int(getattr(cfg, "default_backtest_years", 0)),
        "cfg_backtest_window_comparison_years": [int(x) for x in getattr(cfg, "backtest_window_comparison_years", [])],
        "cfg_fast_mode": bool(getattr(cfg, "fast_mode", False)),
        "cfg_trade_cost_bps_per_side": float(getattr(cfg, "trade_cost_bps_per_side", 0.0)),
        "cfg_roundtrip_cost_bps": float(getattr(cfg, "roundtrip_cost_bps", 0.0)),
        "cfg_rebalance_interval_months": int(getattr(cfg, "rebalance_interval_months", 0)),
        "cfg_sleeve_rebalance_intervals": {
            "core": int(getattr(cfg, "core_compounder_rebalance_interval_months", 0)),
            "future": int(getattr(cfg, "future_winner_rebalance_interval_months", 0)),
            "early": int(getattr(cfg, "early_scout_rebalance_interval_months", 0)),
        },
        "cfg_portfolio_size_comparison_sizes": [int(x) for x in getattr(cfg, "portfolio_size_comparison_sizes", [])],
        "cfg_concentrated_top_n_candidates": [int(x) for x in getattr(cfg, "concentrated_top_n_candidates", [])],
        "cfg_concentrated_max_single_name_weight": float(getattr(cfg, "concentrated_max_single_name_weight", 0.0)),
        "mandate_registry": MANDATE_REGISTRY,
        "workflow_full_rebuild_default_backtest_years": _extract_workflow_default(workflow, "backtest_years"),
        "workflow_full_rebuild_default_fast_mode": _extract_workflow_default(workflow, "fast_mode"),
        "colab_fast_mode_literal": _read_colab_fast_mode(repo_root),
        "active_auto_feature_gates_exists": active_gates.exists(),
    }

    findings: list[dict[str, str]] = []
    if observed["cfg_trade_cost_bps_per_side"] != 25.0:
        findings.append({"severity": "warn", "code": "trade_cost_not_25bps", "message": "Configured per-side cost differs from 25 bps."})
    if observed["cfg_default_backtest_years"] != 8:
        findings.append({"severity": "warn", "code": "default_backtest_not_8y", "message": "Default backtest window is not 8 years."})
    if observed["active_auto_feature_gates_exists"]:
        findings.append({"severity": "block", "code": "active_auto_feature_gates", "message": "Active auto feature gates exist; confirm challenger promotion before production."})
    main_target = int(MANDATE_REGISTRY.get("main", {}).get("default_target_n", 0) or 0)
    if main_target >= 20:
        findings.append({"severity": "info", "code": "main_target_n_broad", "message": "Main mandate target_n is broad; target-N compression should be A/B tested, not changed blindly."})
    if float(getattr(cfg, "concentrated_max_single_name_weight", 0.0)) >= 1.0:
        findings.append({"severity": "warn", "code": "concentrated_single_name_uncapped", "message": "Concentrated max single-name weight is 100%; declare sleeve-level cap before production orchestration."})

    payload = {
        "report_version": ALPHAOPS_REPORT_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_identity": dict(run_identity),
        "observed": observed,
        "findings": findings,
        "status": "block" if any(f["severity"] == "block" for f in findings) else "warn" if any(f["severity"] == "warn" for f in findings) else "pass",
    }
    _write_json(report_path, payload)
    lines = [
        "# AlphaOps Config Audit",
        "",
        f"- Status: {payload['status']}",
        f"- Generated UTC: {payload['generated_at_utc']}",
        "",
        "## Findings",
        "",
    ]
    if findings:
        lines.extend([f"- [{f['severity']}] {f['code']}: {f['message']}" for f in findings])
    else:
        lines.append("- No findings.")
    lines.extend([
        "",
        "## Key Defaults",
        "",
        f"- Backtest years: {observed['cfg_default_backtest_years']}",
        f"- Cost per side bps: {observed['cfg_trade_cost_bps_per_side']}",
        f"- Main mandate target N: {main_target}",
        f"- Concentrated max single name weight: {observed['cfg_concentrated_max_single_name_weight']}",
    ])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "config_audit": str(report_path),
        "config_audit_md": str(md_path),
    }


def write_orchestrator_shadow_outputs(
    paths: Mapping[str, Path],
    *,
    scored_latest: Optional[pd.DataFrame],
    portfolio_latest: Optional[pd.DataFrame],
    concentrated_latest: Optional[pd.DataFrame],
) -> dict[str, str]:
    out_dir = Path(paths["out"]) / "orchestrator"
    out_dir.mkdir(parents=True, exist_ok=True)
    regime_state = (
        _mode_text(portfolio_latest if portfolio_latest is not None else pd.DataFrame(), "regime_state", "")
        or _mode_text(scored_latest if scored_latest is not None else pd.DataFrame(), "regime_state", "neutral")
        or "neutral"
    )
    if regime_state not in {"deep_bear", "bear", "neutral", "bull", "strong_bull"}:
        regime_state = "neutral"

    asof_date = None
    for frame in (portfolio_latest, scored_latest):
        if frame is not None and not frame.empty and "rebalance_date" in frame.columns:
            dt = pd.to_datetime(frame["rebalance_date"], errors="coerce").dropna()
            if not dt.empty:
                asof_date = str(dt.max().date())
                break

    main_weights = _frame_weights(portfolio_latest)
    concentrated_weights = _frame_weights(concentrated_latest)
    unified = compose_unified_portfolio(
        main_weights=main_weights,
        concentrated_weights=concentrated_weights,
        tactical_weights={},
        regime_state=regime_state,
    )
    unified_paths = write_orchestrator_output_bundle(unified, out_dir, asof_date=asof_date, prefix="unified_target")

    legacy_cash = max(0.0, min(1.0, 1.0 - sum(main_weights.values())))
    legacy = {
        "unified_weights": dict(sorted(main_weights.items(), key=lambda kv: -kv[1])),
        "cash_target": float(legacy_cash),
        "by_mandate_capacity": {"main": float(sum(main_weights.values())), "concentrated": 0.0, "tactical": 0.0},
        "conflicts": [],
        "regime_state": regime_state,
        "audit": {
            "mode": "legacy_passthrough",
            "n_unique_tickers": len(main_weights),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    legacy["audit_checks"] = audit_unified_portfolio(legacy)
    legacy_paths = write_orchestrator_output_bundle(legacy, out_dir, asof_date=asof_date, prefix="legacy_passthrough")

    mapping = {f"orchestrator_{k}": v for k, v in unified_paths.items()}
    mapping.update({f"orchestrator_legacy_{k}": v for k, v in legacy_paths.items()})
    return mapping


def write_alphaops_report_pack(
    cfg: Any,
    paths: Mapping[str, Path],
    *,
    run_identity: Mapping[str, Any],
    backtest_metrics: Mapping[str, Any],
    concentrated_metrics: Mapping[str, Any],
    scored_latest: Optional[pd.DataFrame],
    portfolio_latest: Optional[pd.DataFrame],
    concentrated_latest: Optional[pd.DataFrame],
    backtest_window_compare: Optional[pd.DataFrame],
    output_files: Mapping[str, Any],
) -> dict[str, str]:
    out: dict[str, str] = {}
    out.update(
        write_orchestrator_shadow_outputs(
            paths,
            scored_latest=scored_latest,
            portfolio_latest=portfolio_latest,
            concentrated_latest=concentrated_latest,
        )
    )
    out.update(
        write_baseline_registry(
            cfg,
            paths,
            run_identity=run_identity,
            backtest_metrics=backtest_metrics,
            concentrated_metrics=concentrated_metrics,
            scored_latest=scored_latest,
            portfolio_latest=portfolio_latest,
            backtest_window_compare=backtest_window_compare,
            output_files={**dict(output_files or {}), **out},
        )
    )
    out.update(write_config_audit(cfg, paths, run_identity=run_identity))
    return out

