"""Anomaly detection for research-only AutoLearning v2."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from r1000_auto_learning_evidence import read_json, safe_float


DEFAULT_LATEST_RUN = Path("cloud_results/full_rebuild/latest_global_alpha_universe")
SEVERITY_WEIGHT = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _latest_path(root: Path, latest_run: str | Path) -> Path:
    path = Path(latest_run)
    return path if path.is_absolute() else root / path


def _signal_row(rows: list[dict[str, str]], signal: str) -> dict[str, str]:
    for row in rows:
        if row.get("signal") == signal:
            return row
    return {}


def _experiment_row(summary: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    for row in summary.get("ranked") or []:
        if row.get("experiment_id") == experiment_id:
            return row
    return {}


def _anomaly(
    anomaly_id: str,
    category: str,
    severity: str,
    confidence: float,
    observation: str,
    evidence: dict[str, Any],
    breaks_assumption: str,
    hypothesis_types: list[str],
    regime: str | None = None,
) -> dict[str, Any]:
    return {
        "id": anomaly_id,
        "category": category,
        "severity": severity,
        "severity_score": SEVERITY_WEIGHT.get(severity, 1.0),
        "confidence": round(confidence, 4),
        "regime": regime,
        "observation": observation,
        "evidence": evidence,
        "breaks_assumption": breaks_assumption,
        "suggested_hypothesis_types": hypothesis_types,
    }


def detect_anomalies(
    evidence: dict[str, Any],
    root: str | Path,
    latest_run: str | Path = DEFAULT_LATEST_RUN,
) -> list[dict[str, Any]]:
    """Detect system-level anomalies from existing research artifacts.

    The output is intentionally explanatory and proposal-oriented. It never
    changes a policy or model directly.
    """
    root_path = Path(root)
    run_path = _latest_path(root_path, latest_run)
    insights_path = run_path / "trade_journal" / "insights"
    ic_rows = _read_csv(insights_path / "ic_matrix.csv")
    cluster_rows = _read_csv(insights_path / "cluster_winrate.csv")
    experiment_summary = read_json(root_path / "outputs" / "experiments" / "experiment_matrix_summary.json")
    orchestrator_latest = read_json(run_path / "orchestrator" / "unified_target_latest.json")

    anomalies: list[dict[str, Any]] = []
    rs = _signal_row(ic_rows, "rs_acceleration_score")
    h1 = _signal_row(ic_rows, "h1_oversold_value_score")
    theme_primary = _signal_row(ic_rows, "theme_phase_multiplier_primary")
    theme_max = _signal_row(ic_rows, "theme_phase_multiplier_max")
    explosion_entry = _signal_row(ic_rows, "explosion_entry_score")
    explosion_exit = _signal_row(ic_rows, "explosion_exit_score")

    rs_bear = safe_float(rs.get("ic_bear"), None)
    h1_bear = safe_float(h1.get("ic_bear"), None)
    theme_primary_bear = safe_float(theme_primary.get("ic_bear"), None)
    theme_max_bear = safe_float(theme_max.get("ic_bear"), None)
    if rs_bear is not None and theme_primary_bear is not None and rs_bear >= 0.08 and theme_primary_bear <= -0.05:
        anomalies.append(
            _anomaly(
                "bear_rs_theme_inversion",
                "signal_regime_inversion",
                "high",
                0.82,
                "Bear-regime trade journal IC favors RS acceleration while theme multipliers are negative.",
                {
                    "rs_acceleration_ic_bear": rs_bear,
                    "h1_oversold_value_ic_bear": h1_bear,
                    "theme_phase_multiplier_primary_ic_bear": theme_primary_bear,
                    "theme_phase_multiplier_max_ic_bear": theme_max_bear,
                    "n_bear": int(safe_float(rs.get("n_bear"), 0)),
                },
                "The static rule that theme phase should help selection in every regime is not reliable in bear regimes.",
                ["bear_rs_reversal", "theme_disable_in_bear", "bear_type_classifier"],
                regime="bear",
            )
        )

    if h1_bear is not None and h1_bear >= 0.08:
        anomalies.append(
            _anomaly(
                "bear_oversold_value_positive_ic",
                "counter_consensus_factor",
                "medium",
                0.74,
                "Oversold value has positive IC in bear months, suggesting bear is not purely momentum-off.",
                {"h1_oversold_value_ic_bear": h1_bear, "n_bear": int(safe_float(h1.get("n_bear"), 0))},
                "The engine should not assume all bear exposure must be cash/core only.",
                ["bear_oversold_value_recovery", "defensive_leader_substitution"],
                regime="bear",
            )
        )

    explosion_numeric = [
        safe_float(explosion_entry.get("ic_all"), None),
        safe_float(explosion_exit.get("ic_all"), None),
        safe_float(explosion_entry.get("ic_bull"), None),
        safe_float(explosion_exit.get("ic_bull"), None),
    ]
    if all(value is None for value in explosion_numeric) and explosion_entry:
        anomalies.append(
            _anomaly(
                "explosion_stack_dormant",
                "dormant_signal_stack",
                "medium",
                0.68,
                "Explosion entry/exit rows exist in the trade journal IC matrix but have no numeric IC evidence.",
                {
                    "explosion_entry_n_all": int(safe_float(explosion_entry.get("n_all"), 0)),
                    "explosion_exit_n_all": int(safe_float(explosion_exit.get("n_all"), 0)),
                },
                "Alpha Sprint cannot depend on explosion_* alone until the feature stack produces usable nonzero evidence.",
                ["alpha_sprint_breakout_fallback", "explosion_feature_repair"],
            )
        )

    metrics = evidence.get("metrics") or {}
    main = metrics.get("main") or {}
    concentrated = metrics.get("concentrated") or {}
    main_names = safe_float(main.get("avg_stock_names"), 0.0)
    main_turnover = safe_float(main.get("avg_turnover_monthly"), 0.0)
    if main_names >= 20 and main_turnover >= 0.40:
        anomalies.append(
            _anomaly(
                "main_broad_high_turnover",
                "portfolio_construction_drag",
                "high",
                0.78,
                "Main remains broad while monthly turnover is high, which can dilute future_winner alpha.",
                {
                    "main_avg_stock_names": main_names,
                    "main_avg_turnover_monthly": main_turnover,
                    "main_cagr": safe_float(main.get("cagr"), 0.0),
                    "main_max_dd": safe_float(main.get("max_dd"), 0.0),
                },
                "A broad one-flow main portfolio is not guaranteed to be the best carrier for sleeve-specific alpha.",
                ["main_future_alpha_concentration", "target_n_compression", "sleeve_orchestrator_inside_main"],
            )
        )

    main_cagr = safe_float(main.get("cagr"), 0.0)
    main_sharpe = safe_float(main.get("sharpe"), 0.0)
    conc_cagr = safe_float(concentrated.get("cagr"), 0.0)
    conc_sharpe = safe_float(concentrated.get("sharpe"), 0.0)
    conc_dd = safe_float(concentrated.get("max_dd"), 0.0)
    main_dd = safe_float(main.get("max_dd"), 0.0)
    capacity = ((orchestrator_latest.get("capacity_by_mandate") or {}).get("concentrated"))
    if capacity is None:
        capacity = ((orchestrator_latest.get("audit") or {}).get("capacity_by_mandate") or {}).get("concentrated")
    conc_capacity = safe_float(capacity, 0.10)
    if conc_cagr >= main_cagr + 0.10 and conc_sharpe >= main_sharpe and conc_capacity <= 0.15:
        anomalies.append(
            _anomaly(
                "concentrated_alpha_underallocated",
                "capital_allocation_mismatch",
                "high",
                0.80,
                "Concentrated has materially stronger standalone return/Sharpe but the orchestrator keeps it small.",
                {
                    "main_cagr": main_cagr,
                    "main_sharpe": main_sharpe,
                    "main_max_dd": main_dd,
                    "concentrated_cagr": conc_cagr,
                    "concentrated_sharpe": conc_sharpe,
                    "concentrated_max_dd": conc_dd,
                    "latest_concentrated_capacity": conc_capacity,
                },
                "High alpha sources should be tested with dynamic risk budgets instead of permanently small fixed capacity.",
                ["concentrated_neutral_20_25", "bear_top2_survivor", "dynamic_concentrated_n"],
            )
        )

    e6 = _experiment_row(experiment_summary, "E6_risk_sensing_on")
    if e6 and safe_float(e6.get("maxdd_delta_pp"), 0.0) >= 2.0 and safe_float(e6.get("cagr_delta_pp"), 0.0) < 0:
        anomalies.append(
            _anomaly(
                "risk_sensing_defense_return_tradeoff",
                "risk_policy_tradeoff",
                "medium",
                0.72,
                "Simplified risk sensing improves drawdown but reduces CAGR/Sharpe in the aggressive matrix.",
                {
                    "cagr_delta_pp": safe_float(e6.get("cagr_delta_pp"), 0.0),
                    "maxdd_delta_pp": safe_float(e6.get("maxdd_delta_pp"), 0.0),
                    "sharpe_delta": safe_float(e6.get("sharpe_delta"), 0.0),
                    "status": e6.get("status"),
                },
                "A blunt portfolio breaker may protect capital but suppress upside without position-aware exits and swaps.",
                ["risk_governor_layered_exit", "better_replacement_swap", "drawdown_kill_switch"],
            )
        )

    strong_clusters: list[dict[str, Any]] = []
    weak_clusters: list[dict[str, Any]] = []
    for row in cluster_rows:
        win_rate = safe_float(row.get("win_rate"), 0.0)
        avg_ret = safe_float(row.get("avg_realized_return"), 0.0)
        n = int(safe_float(row.get("n"), 0))
        cluster = {"cluster_id": row.get("cluster_id"), "n": n, "win_rate": win_rate, "avg_realized_return": avg_ret}
        if n >= 50 and win_rate >= 0.62 and avg_ret >= 0.08:
            strong_clusters.append(cluster)
        if n >= 15 and (win_rate <= 0.50 or avg_ret <= 0.02):
            weak_clusters.append(cluster)
    if strong_clusters or weak_clusters:
        anomalies.append(
            _anomaly(
                "cluster_conviction_asymmetry",
                "trade_pattern_asymmetry",
                "medium",
                0.70,
                "Trade clusters show large dispersion between strong amplification candidates and weak/caution patterns.",
                {"strong_clusters": strong_clusters, "weak_clusters": weak_clusters},
                "Signal IC alone misses pattern-level context; cluster routing can amplify winners and block traps.",
                ["cluster_conviction_router", "pattern_block_or_amplify"],
            )
        )

    missing_replay = []
    for row in experiment_summary.get("ranked") or []:
        if row.get("requires_full_challenger_backtest") and not row.get("backtest_executed"):
            missing_replay.append({"experiment_id": row.get("experiment_id"), "status": row.get("status")})
    if len(missing_replay) >= 3:
        anomalies.append(
            _anomaly(
                "sidecar_without_counterfactual_replay",
                "research_infrastructure_gap",
                "high",
                0.76,
                "Several high-impact sidecars produce snapshots but still lack historical challenger replay.",
                {"missing_replay": missing_replay[:8], "missing_count": len(missing_replay)},
                "Creative policy generation is unsafe without counterfactual replay for each capital-allocation change.",
                ["counterfactual_replay_priority", "shadow_only_until_replay"],
            )
        )

    anomalies.sort(key=lambda item: (safe_float(item.get("severity_score"), 0.0), safe_float(item.get("confidence"), 0.0)), reverse=True)
    return anomalies


def render_anomaly_report(anomalies: list[dict[str, Any]]) -> str:
    lines = [
        "# AutoLearning v2 Anomalies",
        "",
        "Research-only anomaly inventory. These observations generate hypotheses; they do not activate production rules.",
        "",
    ]
    if not anomalies:
        lines.append("No anomalies detected from the available artifacts.")
        return "\n".join(lines) + "\n"
    for idx, anomaly in enumerate(anomalies, 1):
        lines.extend(
            [
                f"## {idx}. {anomaly['id']}",
                "",
                f"- Category: `{anomaly['category']}`",
                f"- Severity: `{anomaly['severity']}`",
                f"- Confidence: {safe_float(anomaly.get('confidence'), 0.0):.2f}",
                f"- Observation: {anomaly['observation']}",
                f"- Broken assumption: {anomaly['breaks_assumption']}",
                f"- Suggested hypothesis types: {', '.join(anomaly.get('suggested_hypothesis_types') or [])}",
                "",
                "Evidence:",
                "",
                "```json",
                json.dumps(anomaly.get("evidence") or {}, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    return "\n".join(lines)
