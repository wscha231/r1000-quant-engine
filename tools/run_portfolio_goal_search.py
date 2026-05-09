#!/usr/bin/env python3
"""Rank portfolio candidates against explicit main/concentrated targets.

This is a fast, artifact-only management layer. It does not change production
defaults and does not promote any candidate. Its job is to make the target
gap operational after a full rebuild by ranking every available historical
candidate artifact against:

  - main: CAGR >= 30%, MaxDD >= -15%
  - concentrated: CAGR >= 50%, MaxDD >= -18%
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import PORTFOLIO_GOAL_TARGETS


DEFAULT_LATEST_RUN = "cloud_results/full_rebuild/latest_global_alpha_universe"
DEFAULT_OUTPUT_DIR = "outputs/portfolio_goal_search"

TARGETS = PORTFOLIO_GOAL_TARGETS
MAX_REASONABLE_PORTFOLIO_CAGR = 3.0
MAX_REASONABLE_ABS_SHARPE = 10.0


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    except Exception:
        return []


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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def first_metric(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in row:
            value = safe_float(row.get(name))
            if value is not None:
                return value
    return None


def pp(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) * 100.0, 4)


def pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2%}"


def candidate_action(cagr_pass: bool, dd_pass: bool) -> str:
    if cagr_pass and dd_pass:
        return "target_pass_review"
    if cagr_pass and not dd_pass:
        return "needs_drawdown_reduction"
    if dd_pass and not cagr_pass:
        return "needs_alpha_boost"
    return "blocked_both"


def invalid_metric_reason(cagr: float | None, max_dd: float | None, sharpe: float | None, metrics: dict[str, Any]) -> str | None:
    if metrics.get("status") == "blocked":
        return str(metrics.get("reason") or "blocked metrics payload")
    for name, value in (("cagr", cagr), ("max_dd", max_dd), ("sharpe", sharpe)):
        if value is not None and not math.isfinite(float(value)):
            return f"{name} is not finite"
    if cagr is not None and (cagr < -0.99 or cagr > MAX_REASONABLE_PORTFOLIO_CAGR):
        return f"cagr outside plausible portfolio range: {cagr}"
    if max_dd is not None and (max_dd < -1.0 or max_dd > 0.05):
        return f"max_dd outside plausible portfolio range: {max_dd}"
    if sharpe is not None and abs(sharpe) > MAX_REASONABLE_ABS_SHARPE:
        return f"sharpe outside plausible portfolio range: {sharpe}"
    try:
        invalid_weight_count = int(float(metrics.get("invalid_weight_date_count") or 0))
    except (TypeError, ValueError):
        invalid_weight_count = 0
    if invalid_weight_count > 0:
        return "holdings weight diagnostics flagged invalid periods"
    return None


def normalize_candidate(
    *,
    portfolio: str,
    candidate_id: str,
    source: str,
    metrics: dict[str, Any],
    valid_for_production: bool,
    notes: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = TARGETS[portfolio]
    cagr = first_metric(metrics, "cagr", "strategy_cagr", "annual_return")
    max_dd = first_metric(metrics, "max_dd", "max_drawdown")
    sharpe = first_metric(metrics, "sharpe", "Sharpe")
    turnover = first_metric(metrics, "avg_turnover_monthly", "turnover", "monthly_turnover")
    invalid_reason = invalid_metric_reason(cagr, max_dd, sharpe, metrics)
    metrics_valid = invalid_reason is None
    cagr_pass = metrics_valid and cagr is not None and cagr >= target["cagr"]
    dd_pass = metrics_valid and max_dd is not None and max_dd >= target["max_dd"]
    cagr_gap = max(0.0, target["cagr"] - cagr) if cagr is not None else None
    dd_gap = max(0.0, target["max_dd"] - max_dd) if max_dd is not None else None
    gap_score = (100.0 if cagr is None or max_dd is None else 0.0) + (cagr_gap or 0.0) * 100.0 + (dd_gap or 0.0) * 100.0
    reward = (cagr or -1.0) * 100.0 + (sharpe or 0.0) * 2.0 - abs(max_dd or -1.0) * 30.0
    rank_score = (1000.0 if cagr_pass and dd_pass else 0.0) - gap_score + reward / 100.0
    if not metrics_valid:
        rank_score = -1000.0 - gap_score
    return {
        "portfolio": portfolio,
        "candidate_id": candidate_id,
        "source": source,
        "valid_for_production": bool(valid_for_production),
        "metrics_valid": bool(metrics_valid),
        "invalid_reason": invalid_reason,
        "target_pass": bool(cagr_pass and dd_pass),
        "cagr": cagr,
        "cagr_target": target["cagr"],
        "cagr_gap_pp": pp(cagr_gap),
        "max_dd": max_dd,
        "max_dd_target": target["max_dd"],
        "max_dd_gap_pp": pp(dd_gap),
        "sharpe": sharpe,
        "avg_turnover_monthly": turnover,
        "governance_action": "invalid_metrics_blocked" if not metrics_valid else candidate_action(cagr_pass, dd_pass),
        "distance_to_target_pp": None if cagr_gap is None or dd_gap is None else round((cagr_gap + dd_gap) * 100.0, 4),
        "rank_score": rank_score,
        "notes": notes,
        "params": params or {},
    }


def candidate_from_json(
    path: Path,
    *,
    portfolio: str,
    candidate_id: str,
    source_label: str,
    valid_for_production: bool,
    notes: str = "",
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    metrics = read_json(path)
    if not metrics:
        return []
    params = dict(extra_params or {})
    for key in [
        "metric_mode",
        "data_mode",
        "validation_granularity",
        "price_coverage",
        "list_defense_mode",
        "defensive_holdings_path",
        "latest_defensive_holdings_path",
        "hard_stop",
        "trailing_stop",
        "proxy_warning",
    ]:
        if key in metrics:
            params[key] = metrics.get(key)
    return [
        normalize_candidate(
            portfolio=portfolio,
            candidate_id=candidate_id,
            source=f"{source_label}:{rel(path)}",
            metrics=metrics,
            valid_for_production=valid_for_production,
            notes=notes,
            params=params,
        )
    ]


def candidate_from_json_metric_validity(
    path: Path,
    *,
    portfolio: str,
    candidate_id: str,
    source_label: str,
    notes: str = "",
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    metrics = read_json(path)
    if not metrics:
        return []
    valid_for_production = bool(metrics.get("valid_for_production"))
    return [
        normalize_candidate(
            portfolio=portfolio,
            candidate_id=candidate_id,
            source=f"{source_label}:{rel(path)}",
            metrics=metrics,
            valid_for_production=valid_for_production,
            notes=notes,
            params=extra_params or {},
        )
    ]


def candidate_from_nested_metrics(
    path: Path,
    *,
    portfolio: str,
    candidate_id: str,
    metric_key: str,
    source_label: str,
    valid_for_production: bool,
    notes: str = "",
    extra_params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = read_json(path)
    metrics = payload.get(metric_key) if isinstance(payload, dict) else None
    if not isinstance(metrics, dict) or not metrics:
        return []
    params = dict(extra_params or {})
    for key in ["experiment_id", "data_mode", "hard_stop", "trailing_stop", "risk_exit_count", "risk_exit_rate"]:
        if key in payload:
            params[key] = payload.get(key)
    return [
        normalize_candidate(
            portfolio=portfolio,
            candidate_id=candidate_id,
            source=f"{source_label}:{rel(path)}#{metric_key}",
            metrics=metrics,
            valid_for_production=valid_for_production,
            notes=notes,
            params=params,
        )
    ]


def candidates_from_orchestrator_replay(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = read_json(path)
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    if not isinstance(metrics, dict):
        return [], []
    main: list[dict[str, Any]] = []
    concentrated: list[dict[str, Any]] = []
    common = {
        "experiment_id": payload.get("experiment_id"),
        "data_mode": payload.get("data_mode"),
        "valid_for_promotion": payload.get("valid_for_promotion"),
    }
    if isinstance(metrics.get("main_proxy"), dict):
        main.append(
            normalize_candidate(
                portfolio="main",
                candidate_id="orchestrator_replay_main_proxy",
                source=f"sidecar:{rel(path)}#metrics.main_proxy",
                metrics=metrics["main_proxy"],
                valid_for_production=False,
                notes="Orchestrator replay proxy for main returns; discovery-only until wired as a true portfolio path.",
                params=common,
            )
        )
    if isinstance(metrics.get("concentrated"), dict):
        concentrated.append(
            normalize_candidate(
                portfolio="concentrated",
                candidate_id="orchestrator_replay_concentrated_leg",
                source=f"sidecar:{rel(path)}#metrics.concentrated",
                metrics=metrics["concentrated"],
                valid_for_production=False,
                notes="Concentrated leg inside orchestrator replay; requires cap/timing validation before promotion.",
                params=common,
            )
        )
    return main, concentrated


def candidate_from_comparison_csv(
    path: Path,
    *,
    portfolio: str,
    candidate_prefix: str,
    source_label: str,
    valid_for_production: bool,
    notes: str = "",
) -> list[dict[str, Any]]:
    rows = read_csv_rows(path)
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        target_n = row.get("target_stock_names") or row.get("target_n") or row.get("portfolio_size") or row.get("n")
        mode = row.get("weighting_mode") or row.get("policy_mode") or row.get("method_label") or row.get("portfolio_mode")
        interval = row.get("rebalance_interval_months") or row.get("active_rebalance_interval_months")
        suffix_parts = []
        if target_n not in (None, ""):
            suffix_parts.append(f"N{target_n}")
        if mode:
            suffix_parts.append(str(mode))
        if interval not in (None, ""):
            suffix_parts.append(f"I{interval}")
        suffix = "_".join(part.replace(" ", "_") for part in suffix_parts) or f"row{idx + 1}"
        params = {
            key: row.get(key)
            for key in [
                "target_stock_names",
                "target_n",
                "portfolio_size",
                "weighting_mode",
                "rebalance_interval_months",
                "policy_mode",
                "method_label",
                "sleeve_test",
                "sleeve_role",
            ]
            if key in row
        }
        out.append(
            normalize_candidate(
                portfolio=portfolio,
                candidate_id=f"{candidate_prefix}_{suffix}",
                source=f"{source_label}:{rel(path)}",
                metrics=row,
                valid_for_production=valid_for_production,
                notes=notes,
                params=params,
            )
        )
    return out


def collect_candidates(latest_run: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main: list[dict[str, Any]] = []
    concentrated: list[dict[str, Any]] = []

    main += candidate_from_json(
        latest_run / "backtest_metrics.json",
        portfolio="main",
        candidate_id="main_latest_champion",
        source_label="latest_run",
        valid_for_production=True,
        notes="Current production baseline artifact.",
    )
    concentrated += candidate_from_json(
        latest_run / "concentrated_backtest_metrics.json",
        portfolio="concentrated",
        candidate_id="concentrated_latest_champion",
        source_label="latest_run",
        valid_for_production=True,
        notes="Current concentrated champion artifact.",
    )

    main += candidate_from_json(
        latest_run / "main_v2_backtest" / "metrics.json",
        portfolio="main",
        candidate_id="main_v2_historical_replay",
        source_label="sidecar",
        valid_for_production=False,
        notes="Research-only Main v2 replay from candidate_replay_book.",
    )
    main += candidate_from_nested_metrics(
        latest_run / "position_aware_risk_replay" / "metrics.json",
        portfolio="main",
        candidate_id="main_v2_position_aware_risk_proxy",
        metric_key="with_position_risk",
        source_label="sidecar",
        valid_for_production=False,
        notes="Monthly proxy for position-level stops/decay. Target pass here is not production evidence until weekly/intramonth replay confirms it.",
    )
    main += candidate_from_json(
        latest_run / "position_risk_weekly_validation" / "main" / "metrics.json",
        portfolio="main",
        candidate_id="main_position_risk_weekly_validation",
        source_label="sidecar",
        valid_for_production=False,
        notes="Daily stop / weekly relative-performance validation on official main monthly holdings. Stricter than monthly proxy, still research-only until true weekly scored snapshots and order tickets exist.",
    )
    main += candidate_from_json(
        latest_run / "position_risk_weekly_validation" / "main_v2" / "metrics.json",
        portfolio="main",
        candidate_id="main_v2_position_risk_weekly_validation",
        source_label="sidecar",
        valid_for_production=False,
        notes="Daily stop / weekly relative-performance validation on Main v2 research holdings. Kept separate from official main to avoid metric contamination.",
    )
    main += candidate_from_json_metric_validity(
        latest_run / "broker_replay" / "main" / "metrics.json",
        portfolio="main",
        candidate_id="main_broker_ledger_replay",
        source_label="sidecar",
        notes="Production-compatible monthly target replay when metrics mark next-close integer-share ledger as valid.",
    )
    concentrated += candidate_from_json(
        latest_run / "concentrated_policy_replay" / "metrics.json",
        portfolio="concentrated",
        candidate_id="concentrated_policy_replay",
        source_label="sidecar",
        valid_for_production=False,
        notes="Research-only concentrated policy replay from candidate_replay_book.",
    )
    concentrated += candidate_from_json(
        latest_run / "concentrated_position_risk_replay" / "metrics.json",
        portfolio="concentrated",
        candidate_id="concentrated_position_risk_proxy",
        source_label="sidecar",
        valid_for_production=False,
        notes="Monthly proxy for concentrated position-level hard stops. Target pass here requires weekly/intramonth confirmation before promotion.",
    )
    concentrated += candidate_from_json(
        latest_run / "position_risk_weekly_validation" / "concentrated" / "metrics.json",
        portfolio="concentrated",
        candidate_id="concentrated_position_risk_weekly_validation",
        source_label="sidecar",
        valid_for_production=False,
        notes="Daily stop / weekly relative-performance validation for concentrated holdings. This is the bridge from monthly proxy to production-compatible evidence.",
    )
    concentrated += candidate_from_json_metric_validity(
        latest_run / "broker_replay" / "concentrated" / "metrics.json",
        portfolio="concentrated",
        candidate_id="concentrated_broker_ledger_replay",
        source_label="sidecar",
        notes="Production-compatible monthly target replay when metrics mark next-close integer-share ledger as valid.",
    )
    concentrated += candidate_from_json(
        latest_run / "monster_lifecycle_replay" / "metrics.json",
        portfolio="concentrated",
        candidate_id="monster_lifecycle_replay",
        source_label="sidecar",
        valid_for_production=False,
        notes="Research-only monster lifecycle replay; useful for drawdown control discovery.",
    )
    main += candidate_from_json(
        latest_run / "lifecycle_review_overlay_main" / "metrics.json",
        portfolio="main",
        candidate_id="lifecycle_review_overlay_main",
        source_label="sidecar",
        valid_for_production=False,
        notes="Research-only overlay on production monthly picks: monthly lifecycle review instead of monthly churn.",
    )
    main += candidate_from_json(
        latest_run / "monster_lifecycle_review_main" / "metrics.json",
        portfolio="main",
        candidate_id="monster_lifecycle_review_main",
        source_label="sidecar",
        valid_for_production=False,
        notes="Research-only monthly lifecycle review: staged entry, long-hold winners, shakeout hold, stale-leader exits.",
    )
    concentrated += candidate_from_json(
        latest_run / "monster_lifecycle_review_concentrated" / "metrics.json",
        portfolio="concentrated",
        candidate_id="monster_lifecycle_review_concentrated",
        source_label="sidecar",
        valid_for_production=False,
        notes="Research-only concentrated lifecycle review with staged 5/14/32/50% sizing and stale-leader patience.",
    )
    orch_main, orch_concentrated = candidates_from_orchestrator_replay(
        latest_run / "orchestrator_replay" / "concentrated_balanced" / "metrics.json"
    )
    main += orch_main
    concentrated += orch_concentrated

    reports = latest_run / "reports"
    main_comparisons = [
        ("portfolio_size", "portfolio_size_comparison.csv"),
        ("rebalance_interval", "rebalance_interval_comparison.csv"),
        ("sleeve_cap_policy", "sleeve_cap_policy_comparison.csv"),
        ("regime_sleeve_map", "regime_sleeve_map_method_comparison.csv"),
        ("ai_four_sleeve", "ai_four_sleeve_adaptive_comparison.csv"),
    ]
    for prefix, filename in main_comparisons:
        main += candidate_from_comparison_csv(
            reports / filename,
            portfolio="main",
            candidate_prefix=f"main_{prefix}",
            source_label="latest_run_report",
            valid_for_production=False,
            notes="Comparison artifact; requires champion/challenger gate before production.",
        )

    concentrated += candidate_from_comparison_csv(
        reports / "concentrated_strategy_comparison.csv",
        portfolio="concentrated",
        candidate_prefix="concentrated_grid",
        source_label="latest_run_report",
        valid_for_production=False,
        notes="Historical concentrated grid; needs cap/timing/risk review before production.",
    )

    experiment_dir = REPO_ROOT / "outputs" / "experiments"
    if experiment_dir.exists():
        for metrics_path in sorted(experiment_dir.glob("*/metrics.json")):
            metrics = read_json(metrics_path)
            if not metrics:
                continue
            experiment_id = str(metrics.get("experiment_id") or metrics_path.parent.name)
            metric_mode = str(metrics.get("metric_mode") or metrics.get("artifact_mode") or "")
            if "concentrated" in experiment_id.lower() or "concentrated" in metric_mode.lower():
                concentrated.append(
                    normalize_candidate(
                        portfolio="concentrated",
                        candidate_id=f"experiment_{experiment_id}",
                        source=f"experiment:{rel(metrics_path)}",
                        metrics=metrics,
                        valid_for_production=False,
                        notes="Aggressive lab artifact; discovery-only unless replay-backed.",
                    )
                )
            else:
                main.append(
                    normalize_candidate(
                        portfolio="main",
                        candidate_id=f"experiment_{experiment_id}",
                        source=f"experiment:{rel(metrics_path)}",
                        metrics=metrics,
                        valid_for_production=False,
                        notes="Aggressive lab artifact; discovery-only unless replay-backed.",
                    )
                )

    return rank_candidates(main), rank_candidates(concentrated)


def rank_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: safe_float(row.get("rank_score"), -9999.0) or -9999.0, reverse=True)


def best_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"candidate_id": None, "target_pass": False, "governance_action": "missing_candidates"}
    return dict(rows[0])


def next_actions(best_main: dict[str, Any], best_concentrated: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if not best_main.get("target_pass"):
        action = best_main.get("governance_action")
        if action == "needs_alpha_boost":
            actions.append("Main: keep drawdown controls and test Main v2 target N 12/15 with future_winner-heavy sleeve allocation.")
        elif action == "needs_drawdown_reduction":
            actions.append("Main: preserve CAGR and add position-aware risk sensing Layer 1/3/4 plus stress-window gates.")
        else:
            actions.append("Main: run true Main v2 historical challenger; current artifacts do not meet both CAGR and MaxDD targets.")
    else:
        actions.append("Main: target-pass candidate exists; require strict gate, stress windows, turnover, and human approval.")

    if not best_concentrated.get("target_pass"):
        action = best_concentrated.get("governance_action")
        if action == "needs_alpha_boost":
            actions.append("Concentrated: search N/weighting grid, staged entry, and Alpha Sprint overlay; current best lacks CAGR.")
        elif action == "needs_drawdown_reduction":
            actions.append("Concentrated: keep alpha engine, add caps, weekly exit, hard/trailing stop, and replacement swap replay.")
        else:
            actions.append("Concentrated: run full concentrated grid replay from concentrated_strategy_monthly and reject proxy-only evidence.")
    else:
        actions.append("Concentrated: target-pass candidate exists; validate caps, timing, turnover, and production promotion gates.")
    return actions


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Portfolio Goal Search",
        "",
        "Artifact-only ranking against explicit portfolio targets. Production defaults are unchanged.",
        "",
        "## Targets",
        "",
        "| Portfolio | CAGR Target | MaxDD Target |",
        "| --- | ---: | ---: |",
        f"| main | {TARGETS['main']['cagr']:.2%} | {TARGETS['main']['max_dd']:.2%} |",
        f"| concentrated | {TARGETS['concentrated']['cagr']:.2%} | {TARGETS['concentrated']['max_dd']:.2%} |",
        "",
        "## Best Candidates",
        "",
        "| Portfolio | Candidate | CAGR | Gap | MaxDD | Gap | Target Pass | Action |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for key in ["best_main", "best_concentrated"]:
        row = payload.get(key) or {}
        lines.append(
            "| {portfolio} | `{candidate}` | {cagr} | {cagr_gap} | {max_dd} | {dd_gap} | {passed} | `{action}` |".format(
                portfolio=row.get("portfolio", key.replace("best_", "")),
                candidate=row.get("candidate_id"),
                cagr=pct(row.get("cagr")),
                cagr_gap="" if row.get("cagr_gap_pp") is None else f"{row.get('cagr_gap_pp'):.2f}pp",
                max_dd=pct(row.get("max_dd")),
                dd_gap="" if row.get("max_dd_gap_pp") is None else f"{row.get('max_dd_gap_pp'):.2f}pp",
                passed=str(row.get("target_pass")).lower(),
                action=row.get("governance_action"),
            )
        )
    lines.extend(["", "## Main Top 5", ""])
    lines.extend(render_table(payload.get("main_candidates", [])[:5]))
    lines.extend(["", "## Concentrated Top 5", ""])
    lines.extend(render_table(payload.get("concentrated_candidates", [])[:5]))
    lines.extend(["", "## Next Actions", ""])
    for item in payload.get("next_actions", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def render_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No candidates found."]
    out = [
        "| Candidate | CAGR | Gap | MaxDD | Gap | Sharpe | Pass | Source |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        out.append(
            "| `{candidate}` | {cagr} | {cagr_gap} | {max_dd} | {dd_gap} | {sharpe} | {passed} | {source} |".format(
                candidate=row.get("candidate_id"),
                cagr=pct(row.get("cagr")),
                cagr_gap="" if row.get("cagr_gap_pp") is None else f"{row.get('cagr_gap_pp'):.2f}pp",
                max_dd=pct(row.get("max_dd")),
                dd_gap="" if row.get("max_dd_gap_pp") is None else f"{row.get('max_dd_gap_pp'):.2f}pp",
                sharpe="" if row.get("sharpe") is None else f"{float(row.get('sharpe')):.3f}",
                passed=str(row.get("target_pass")).lower(),
                source=row.get("source"),
            )
        )
    return out


def flat_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["params"] = json.dumps(item.get("params") or {}, sort_keys=True)
        out.append(item)
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    main_candidates, concentrated_candidates = collect_candidates(latest_run)
    best_main = best_summary(main_candidates)
    best_concentrated = best_summary(concentrated_candidates)
    payload = {
        "latest_run": rel(latest_run),
        "target_pass": bool(best_main.get("target_pass") and best_concentrated.get("target_pass")),
        "production_target_pass": bool(
            best_main.get("target_pass")
            and best_main.get("valid_for_production")
            and best_concentrated.get("target_pass")
            and best_concentrated.get("valid_for_production")
        ),
        "best_main": best_main,
        "best_concentrated": best_concentrated,
        "main_candidates": main_candidates,
        "concentrated_candidates": concentrated_candidates,
        "next_actions": next_actions(best_main, best_concentrated),
    }

    fields = [
        "portfolio",
        "candidate_id",
        "source",
        "valid_for_production",
        "metrics_valid",
        "invalid_reason",
        "target_pass",
        "cagr",
        "cagr_target",
        "cagr_gap_pp",
        "max_dd",
        "max_dd_target",
        "max_dd_gap_pp",
        "sharpe",
        "avg_turnover_monthly",
        "governance_action",
        "distance_to_target_pp",
        "rank_score",
        "notes",
        "params",
    ]
    write_json(output_dir / "goal_search_summary.json", payload)
    write_csv(output_dir / "main_candidate_ranking.csv", flat_rows(main_candidates), fields)
    write_csv(output_dir / "concentrated_candidate_ranking.csv", flat_rows(concentrated_candidates), fields)
    write_text(output_dir / "goal_search_report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"target_pass": payload["target_pass"], "next_actions": payload["next_actions"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
