#!/usr/bin/env python3
"""Fuse AlphaOps sidecar evidence into an explicit policy activation plan.

This runner is intentionally artifact-only. It does not change portfolio
construction, weights, active gates, or broker execution. Its job is to make
the currently separate sidecars work as one governance layer:

  sidecar/replay evidence -> conflict arbitration -> activation plan

The output answers two questions after every full rebuild:

1. Which research policy has the best evidence for main/concentrated goals?
2. If two policies disagree, which one wins and why?
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tools"))

from r1000_config import PORTFOLIO_GOAL_TARGETS  # noqa: E402
from run_portfolio_goal_search import collect_candidates, invalid_metric_reason  # noqa: E402


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/policy_fusion"

TARGETS = PORTFOLIO_GOAL_TARGETS


POLICY_PRECEDENCE: list[dict[str, Any]] = [
    {
        "policy_id": "position_hard_stop_distribution",
        "precedence": 100,
        "domain": "risk_exit",
        "description": "Hard stop, distribution exit, and broken-position controls.",
        "activation_rule": "May force exits even for high-conviction winners; never vetoed by shakeout or long-hold rules.",
    },
    {
        "policy_id": "macro_crisis_cash_ladder",
        "precedence": 95,
        "domain": "portfolio_cash",
        "description": "Raise cash quickly in red/crisis regimes and redeploy in recovery.",
        "activation_rule": "Overrides idle-cash redeploy and new monster adds when macro risk is red/crisis.",
    },
    {
        "policy_id": "stale_leader_trim",
        "precedence": 90,
        "domain": "leader_rotation",
        "description": "Trim or exit old leaders when relative strength and recent returns deteriorate.",
        "activation_rule": "Overrides long-winner patience unless shakeout evidence is strong and hard-distribution evidence is absent.",
    },
    {
        "policy_id": "shakeout_hold_veto",
        "precedence": 86,
        "domain": "risk_exit_veto",
        "description": "Distinguish temporary shake-outs from true distribution.",
        "activation_rule": "Can veto partial stale-leader trims, but cannot override hard stop or distribution exits.",
    },
    {
        "policy_id": "monster_early_staged_sizing",
        "precedence": 80,
        "domain": "alpha_capture",
        "description": "Scout early leaders, then scale winners in stages instead of all-at-once sizing.",
        "activation_rule": "Can add risk only after hard-stop, macro-crisis, liquidity, and market-cap gates pass.",
    },
    {
        "policy_id": "long_winner_hold_template",
        "precedence": 76,
        "domain": "holding_period",
        "description": "Hold structural compounders for years when leadership remains intact.",
        "activation_rule": "Defends winners from churn but yields to stale-leader, hard-stop, and macro-crisis exits.",
    },
    {
        "policy_id": "idle_cash_redeploy",
        "precedence": 70,
        "domain": "portfolio_cash",
        "description": "Keep normal/bull-regime cash low and redeploy idle cash into ranked holdings.",
        "activation_rule": "Allowed only in green/recovery regimes and after crisis cash floors are satisfied.",
    },
    {
        "policy_id": "style_macro_router",
        "precedence": 64,
        "domain": "style_allocation",
        "description": "Route between breakout growth, turnaround, quality compounder, and cash-defense styles.",
        "activation_rule": "Chooses the opportunity set; does not override hard exits or crisis defense.",
    },
    {
        "policy_id": "governance_catalyst_watch",
        "precedence": 58,
        "domain": "catalyst_watch",
        "description": "Detect governance/ownership/catalyst changes for watchlist elevation.",
        "activation_rule": "Can add candidates to review/scout lists but cannot force production buys.",
    },
    {
        "policy_id": "auto_learning_policy_candidate",
        "precedence": 50,
        "domain": "learning",
        "description": "Let AutoLearning propose policy changes from historical wins/losses.",
        "activation_rule": "Proposal-only unless an executable replay clears portfolio gates.",
    },
]


CONFLICT_RULES: list[dict[str, str]] = [
    {
        "policy_a": "position_hard_stop_distribution",
        "policy_b": "shakeout_hold_veto",
        "winner": "position_hard_stop_distribution",
        "reason": "A hard stop or confirmed distribution is a survival rule; shakeout logic can only veto soft/partial trims.",
    },
    {
        "policy_a": "position_hard_stop_distribution",
        "policy_b": "long_winner_hold_template",
        "winner": "position_hard_stop_distribution",
        "reason": "Long-hold patience never protects a position that has hit hard exit criteria.",
    },
    {
        "policy_a": "macro_crisis_cash_ladder",
        "policy_b": "idle_cash_redeploy",
        "winner": "macro_crisis_cash_ladder",
        "reason": "Crisis cash floors must be satisfied before normal-market idle cash is redeployed.",
    },
    {
        "policy_a": "macro_crisis_cash_ladder",
        "policy_b": "monster_early_staged_sizing",
        "winner": "macro_crisis_cash_ladder",
        "reason": "New risk-on scouting is blocked in red/crisis regimes unless the policy is explicitly a recovery re-entry.",
    },
    {
        "policy_a": "stale_leader_trim",
        "policy_b": "long_winner_hold_template",
        "winner": "stale_leader_trim",
        "reason": "A former winner that underperforms SPY/QQQ and loses trend quality is trimmed before long-hold protection applies.",
    },
    {
        "policy_a": "shakeout_hold_veto",
        "policy_b": "stale_leader_trim",
        "winner": "conditional",
        "reason": "Shakeout evidence can defer the first half-trim, but only when hard-distribution and relative-strength breakdown are absent.",
    },
    {
        "policy_a": "monster_early_staged_sizing",
        "policy_b": "idle_cash_redeploy",
        "winner": "conditional",
        "reason": "Idle cash should fund confirmed monster stages first; otherwise it is spread across the ranked book.",
    },
    {
        "policy_a": "style_macro_router",
        "policy_b": "monster_early_staged_sizing",
        "winner": "style_macro_router",
        "reason": "The style router determines whether breakout growth, turnaround, or quality is the preferred opportunity set.",
    },
    {
        "policy_a": "auto_learning_policy_candidate",
        "policy_b": "all_production_policies",
        "winner": "all_production_policies",
        "reason": "AutoLearning may propose and replay policies, but it cannot mutate production without passing gates.",
    },
]


EVIDENCE_WEIGHTS = {
    "production": 1.00,
    "historical_replay": 0.80,
    "weekly_validation": 0.76,
    "monthly_proxy": 0.62,
    "diagnostic": 0.40,
    "proposal": 0.32,
    "missing": 0.00,
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


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


def write_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def pct(value: Any) -> str:
    numeric = safe_float(value)
    if numeric is None:
        return ""
    return f"{numeric:.2%}"


def pp(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 4)


def load_production_metrics(latest_run: Path, portfolio: str) -> dict[str, Any]:
    filename = "backtest_metrics.json" if portfolio == "main" else "concentrated_backtest_metrics.json"
    broker_path = latest_run / "broker_replay" / portfolio / "metrics.json"
    payload = read_json(broker_path)
    source = broker_path
    metric_mode = "broker_ledger_next_close"
    if not payload:
        payload = read_json(latest_run / filename)
        source = latest_run / filename
        metric_mode = "legacy_weight_backtest"
    return {
        "cagr": safe_float(payload.get("cagr") or payload.get("strategy_cagr")),
        "max_dd": safe_float(payload.get("max_dd") or payload.get("max_drawdown")),
        "sharpe": safe_float(payload.get("sharpe")),
        "avg_cash_weight": safe_float(payload.get("avg_cash_weight")),
        "avg_turnover_monthly": safe_float(payload.get("avg_turnover_monthly")),
        "source": rel(source),
        "metric_mode": metric_mode,
    }


def metric_value(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = safe_float(row.get(name))
        if value is not None:
            return value
    return None


def score_policy(
    *,
    policy_id: str,
    portfolio: str,
    evidence_type: str,
    metrics: dict[str, Any],
    production: dict[str, Any],
    source: str,
    notes: str,
    production_ready: bool = False,
    dependencies: str = "",
    conflict_scope: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = TARGETS.get(portfolio, {})
    cagr = metric_value(metrics, "cagr", "strategy_cagr", "annual_return")
    max_dd = metric_value(metrics, "max_dd", "max_drawdown")
    sharpe = metric_value(metrics, "sharpe", "Sharpe")
    turnover = metric_value(metrics, "avg_turnover_monthly", "turnover", "monthly_turnover")
    base_cagr = safe_float(production.get("cagr"))
    base_dd = safe_float(production.get("max_dd"))
    base_sharpe = safe_float(production.get("sharpe"))
    delta_cagr = cagr - base_cagr if cagr is not None and base_cagr is not None else None
    delta_dd = max_dd - base_dd if max_dd is not None and base_dd is not None else None
    delta_sharpe = sharpe - base_sharpe if sharpe is not None and base_sharpe is not None else None
    cagr_target = safe_float(target.get("cagr"))
    dd_target = safe_float(target.get("max_dd"))
    cagr_gap = max(0.0, cagr_target - cagr) if cagr is not None and cagr_target is not None else None
    dd_gap = max(0.0, dd_target - max_dd) if max_dd is not None and dd_target is not None else None
    invalid_reason = invalid_metric_reason(cagr, max_dd, sharpe, metrics)
    metrics_valid = invalid_reason is None
    target_pass = bool(
        metrics_valid
        and cagr is not None
        and max_dd is not None
        and cagr_target is not None
        and dd_target is not None
        and cagr >= cagr_target
        and max_dd >= dd_target
    )
    evidence_weight = EVIDENCE_WEIGHTS.get(evidence_type, EVIDENCE_WEIGHTS["missing"])
    improvement_score = (
        (delta_cagr or 0.0) * 250.0
        + (delta_dd or 0.0) * 140.0
        + (delta_sharpe or 0.0) * 4.0
    )
    target_penalty = ((cagr_gap or 0.0) * 120.0) + ((dd_gap or 0.0) * 90.0)
    score = (40.0 if target_pass else 0.0) + improvement_score * evidence_weight - target_penalty
    if not metrics_valid:
        score = -1000.0 - target_penalty
    if production_ready:
        score += 4.0
    if evidence_type in {"monthly_proxy", "diagnostic", "proposal"}:
        score -= 2.0

    if not metrics_valid:
        stage = "blocked_invalid_metrics"
    elif cagr is None or max_dd is None:
        stage = "blocked_missing_metrics"
    elif target_pass and production_ready:
        stage = "ready_for_human_activation_review"
    elif target_pass:
        stage = "confirm_with_production_compatible_replay"
    elif (delta_cagr or 0.0) > 0 and (delta_dd or 0.0) >= -0.01:
        stage = "candidate_for_combination"
    elif (delta_dd or 0.0) > 0.03 and (delta_cagr or 0.0) < 0:
        stage = "conditional_defense_only"
    elif (delta_cagr or 0.0) < -0.01 and (delta_dd or 0.0) < 0:
        stage = "reject_current_form"
    else:
        stage = "shadow_watch"

    precedence = next((int(row["precedence"]) for row in POLICY_PRECEDENCE if row["policy_id"] == policy_id), 0)
    out = {
        "policy_id": policy_id,
        "portfolio": portfolio,
        "precedence": precedence,
        "evidence_type": evidence_type,
        "source": source,
        "production_ready": bool(production_ready),
        "activation_stage": stage,
        "metrics_valid": bool(metrics_valid),
        "invalid_reason": invalid_reason,
        "target_pass": target_pass,
        "cagr": cagr,
        "cagr_target": cagr_target,
        "cagr_gap_pp": pp(cagr_gap),
        "max_dd": max_dd,
        "max_dd_target": dd_target,
        "max_dd_gap_pp": pp(dd_gap),
        "sharpe": sharpe,
        "avg_turnover_monthly": turnover,
        "delta_cagr_pp": pp(delta_cagr),
        "delta_max_dd_pp": pp(delta_dd),
        "delta_sharpe": None if delta_sharpe is None else round(delta_sharpe, 4),
        "fusion_score": round(score, 4),
        "dependencies": dependencies,
        "conflict_scope": conflict_scope,
        "notes": notes,
    }
    if extra:
        out.update(extra)
    return out


def find_candidate(candidates: list[dict[str, Any]], candidate_id: str) -> dict[str, Any]:
    for row in candidates:
        if row.get("candidate_id") == candidate_id:
            return row
    return {}


def candidate_is_usable(row: dict[str, Any]) -> bool:
    return bool(row) and row.get("metrics_valid", True) is not False


def best_metric_from_summary(path: Path, key: str = "best_by_cagr") -> dict[str, Any]:
    payload = read_json(path)
    metrics = payload.get(key) if isinstance(payload, dict) else None
    return metrics if isinstance(metrics, dict) else {}


def build_metric_policies(latest_run: Path) -> list[dict[str, Any]]:
    main_production = load_production_metrics(latest_run, "main")
    concentrated_production = load_production_metrics(latest_run, "concentrated")
    main_candidates, concentrated_candidates = collect_candidates(latest_run)
    rows: list[dict[str, Any]] = []
    main_position_risk = find_candidate(main_candidates, "main_position_risk_weekly_validation")
    main_position_risk_evidence = "weekly_validation"
    if not candidate_is_usable(main_position_risk):
        main_position_risk = find_candidate(main_candidates, "main_v2_position_aware_risk_proxy")
        main_position_risk_evidence = "monthly_proxy"
    concentrated_position_risk = find_candidate(concentrated_candidates, "concentrated_position_risk_weekly_validation")
    concentrated_position_risk_evidence = "weekly_validation"
    if not candidate_is_usable(concentrated_position_risk):
        concentrated_position_risk = find_candidate(concentrated_candidates, "concentrated_position_risk_proxy")
        concentrated_position_risk_evidence = "monthly_proxy"

    metric_map = [
        (
            "monster_early_staged_sizing",
            "main",
            "historical_replay",
            find_candidate(main_candidates, "monster_lifecycle_review_main"),
            main_production,
            "Staged monster entry, long-hold winners, stale-leader exits for main.",
            "Requires hard-stop/distribution, macro-crisis, liquidity, and minimum market-cap gates.",
            "Conflicts with macro crisis defense and hard exits.",
        ),
        (
            "monster_early_staged_sizing",
            "concentrated",
            "historical_replay",
            find_candidate(concentrated_candidates, "monster_lifecycle_review_concentrated"),
            concentrated_production,
            "Concentrated staged monster sizing up to the 50% policy cap.",
            "Requires weekly/intramonth validation before production activation.",
            "Conflicts with hard stops and macro crisis defense.",
        ),
        (
            "position_hard_stop_distribution",
            "main",
            main_position_risk_evidence,
            main_position_risk,
            main_production,
            "Main position-aware risk evidence for hard stops, decay, and risk exits.",
            "Requires order-ticket simulation and true weekly/daily scored snapshots before production activation.",
            "Overrides shakeout and long-hold rules when hard exits trigger.",
        ),
        (
            "position_hard_stop_distribution",
            "concentrated",
            concentrated_position_risk_evidence,
            concentrated_position_risk,
            concentrated_production,
            "Concentrated hard-stop evidence near the 50% CAGR / -18% MaxDD goal.",
            "Requires cost sensitivity, rolling windows, order-ticket simulation, and weekly/daily scored confirmation.",
            "Overrides 50% conviction sizing when a position breaks.",
        ),
        (
            "style_macro_router",
            "main",
            "historical_replay",
            find_candidate(main_candidates, "main_v2_historical_replay"),
            main_production,
            "Main v2 sleeve router for core/future/early style allocation.",
            "Requires style-regime monthly attribution and no regression versus production.",
            "Determines opportunity style before monster/stale rules act.",
        ),
        (
            "style_macro_router",
            "concentrated",
            "historical_replay",
            find_candidate(concentrated_candidates, "concentrated_policy_replay"),
            concentrated_production,
            "Concentrated policy replay for capacity, target N, and entry quality.",
            "Requires finite monthly strategy and non-empty concentrated books.",
            "Determines concentrated opportunity set before risk gates.",
        ),
        (
            "long_winner_hold_template",
            "main",
            "historical_replay",
            find_candidate(main_candidates, "lifecycle_review_overlay_main"),
            main_production,
            "Monthly lifecycle overlay to reduce unnecessary churn in long winners.",
            "Requires stale-leader and hard-stop vetoes to avoid holding broken former leaders.",
            "Conflicts with stale-leader trim and hard stops.",
        ),
    ]
    for policy_id, portfolio, evidence_type, metrics, production, notes, dependencies, conflicts in metric_map:
        if not metrics:
            continue
        rows.append(
            score_policy(
                policy_id=policy_id,
                portfolio=portfolio,
                evidence_type=evidence_type,
                metrics=metrics,
                production=production,
                source=str(metrics.get("source") or ""),
                notes=notes,
                production_ready=bool(metrics.get("valid_for_production")),
                dependencies=dependencies,
                conflict_scope=conflicts,
                extra={"candidate_id": metrics.get("candidate_id", "")},
            )
        )

    crisis_metrics = best_metric_from_summary(latest_run / "crisis_reentry_replay" / "metrics.json")
    if crisis_metrics:
        rows.append(
            score_policy(
                policy_id="macro_crisis_cash_ladder",
                portfolio="main",
                evidence_type="monthly_proxy",
                metrics=crisis_metrics,
                production=main_production,
                source=rel(latest_run / "crisis_reentry_replay" / "metrics.json") + "#best_by_cagr",
                notes="Crisis cash ladder plus staged bargain re-entry.",
                production_ready=False,
                dependencies="Requires macro_policy_engine risk states and production-compatible cash accounting.",
                conflict_scope="Overrides idle cash redeploy and new risk-on adds in red/crisis regimes.",
                extra={"policy_variant": crisis_metrics.get("policy_id") or crisis_metrics.get("model", "")},
            )
        )

    cash_metrics = best_metric_from_summary(latest_run / "main_cash_drag_replay" / "summary.json")
    if cash_metrics:
        rows.append(
            score_policy(
                policy_id="idle_cash_redeploy",
                portfolio="main",
                evidence_type="monthly_proxy",
                metrics=cash_metrics,
                production=main_production,
                source=rel(latest_run / "main_cash_drag_replay" / "summary.json") + "#best_by_cagr",
                notes="Redeploy normal-market idle cash while respecting single-name caps.",
                production_ready=False,
                dependencies="Blocked by macro crisis cash ladder; allowed in green/recovery regimes only.",
                conflict_scope="Conflicts with crisis cash floors and confirmed monster stage funding.",
                extra={"policy_variant": cash_metrics.get("model", "")},
            )
        )

    return rows


def build_diagnostic_policies(latest_run: Path) -> list[dict[str, Any]]:
    main_production = load_production_metrics(latest_run, "main")
    rows: list[dict[str, Any]] = []
    priorities = read_csv_rows(latest_run / "historical_trade_journey" / "historical_decision_priorities.csv")
    action_counts: dict[str, int] = {}
    for row in priorities:
        action = str(row.get("action") or "")
        action_counts[action] = action_counts.get(action, 0) + 1
    stale_count = action_counts.get("current_position_stale_review", 0) + action_counts.get("review_trim_or_exit", 0)
    premature_count = action_counts.get("study_premature_exit_or_fast_capture", 0)
    long_winner_count = action_counts.get("preserve_winner_hold_template", 0)
    quick_loss_count = action_counts.get("tighten_entry_or_fast_exit", 0)

    if stale_count:
        rows.append(
            score_policy(
                policy_id="stale_leader_trim",
                portfolio="main",
                evidence_type="diagnostic",
                metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")},
                production=main_production,
                source=rel(latest_run / "historical_trade_journey" / "historical_decision_priorities.csv"),
                notes="Historical journey found stale leaders that should be reviewed for half-trim or exit.",
                dependencies="Requires relative-strength underperformance and no shakeout veto.",
                conflict_scope="Can be delayed by shakeout_hold_veto; yields to hard exits.",
                extra={"priority_count": stale_count, "diagnostic_action": "review_trim_or_exit"},
            )
        )
    if premature_count or long_winner_count:
        rows.append(
            score_policy(
                policy_id="long_winner_hold_template",
                portfolio="main",
                evidence_type="diagnostic",
                metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")},
                production=main_production,
                source=rel(latest_run / "historical_trade_journey" / "historical_decision_priorities.csv"),
                notes="Historical journey found short big winners and long-winner templates that should reduce premature exits.",
                dependencies="Requires structural theme, no hard distribution, and no stale-leader breakdown.",
                conflict_scope="Yields to stale_leader_trim, hard stops, and crisis defense.",
                extra={"priority_count": premature_count + long_winner_count, "diagnostic_action": "preserve_or_repair_winner_hold"},
            )
        )
    if quick_loss_count:
        rows.append(
            score_policy(
                policy_id="position_hard_stop_distribution",
                portfolio="main",
                evidence_type="diagnostic",
                metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")},
                production=main_production,
                source=rel(latest_run / "historical_trade_journey" / "historical_decision_priorities.csv"),
                notes="Historical journey found quick-loss patterns; entry gates or fast exits should be tightened.",
                dependencies="Requires trade-level reason attribution before production activation.",
                conflict_scope="Overrides long-hold and shakeout rules when hard exits trigger.",
                extra={"priority_count": quick_loss_count, "diagnostic_action": "tighten_entry_or_fast_exit"},
            )
        )

    onset_summary = read_json(latest_run / "winner_onset_study" / "pattern_summary.json")
    if onset_summary:
        rows.append(
            score_policy(
                policy_id="monster_early_staged_sizing",
                portfolio="main",
                evidence_type="diagnostic",
                metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")},
                production=main_production,
                source=rel(latest_run / "winner_onset_study" / "pattern_summary.json"),
                notes="Winner-onset study is available to refine early monster entry patterns without ticker hardcoding.",
                dependencies="Requires conversion from event-level onset evidence into portfolio-level challenger replay.",
                conflict_scope="Can support monster staged sizing only after macro/risk/liquidity gates pass.",
                extra={
                    "priority_count": onset_summary.get("event_count", 0),
                    "diagnostic_action": "refine_monster_entry_pattern",
                },
            )
        )

    shakeout_summary = read_json(latest_run / "shakeout_breakdown_study" / "pattern_summary.json")
    winner_challenger_summary = read_json(latest_run / "autolearning_winner_challenger" / "summary.json")
    # The shakeout path is optional; if absent, still expose the rule as a
    # guarded placeholder so conflict arbitration stays explicit.
    rows.append(
        score_policy(
            policy_id="shakeout_hold_veto",
            portfolio="main",
            evidence_type="diagnostic" if shakeout_summary or winner_challenger_summary else "missing",
            metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")} if shakeout_summary or winner_challenger_summary else {},
            production=main_production,
            source=rel(latest_run / "shakeout_breakdown_study" / "pattern_summary.json") if shakeout_summary else (rel(latest_run / "autolearning_winner_challenger" / "summary.json") if winner_challenger_summary else "missing_shakeout_breakdown_study"),
            notes="Protects valid shake-outs from soft stale trims; not yet hard-wired to production exits.",
            dependencies="Needs shakeout/distribution classifier with volume, RS recovery, sector context, and fundamental deterioration flags.",
            conflict_scope="Cannot override hard stops or confirmed distribution.",
            extra={
                "priority_count": shakeout_summary.get("event_count", 0) if shakeout_summary else 0,
                "diagnostic_action": "shakeout_veto_candidate" if shakeout_summary else "shakeout_veto_placeholder",
            },
        )
    )

    macro_summary = read_json(latest_run / "macro_policy_engine" / "summary.json")
    if macro_summary:
        latest = macro_summary.get("latest") if isinstance(macro_summary.get("latest"), dict) else {}
        rows.append(
            score_policy(
                policy_id="style_macro_router",
                portfolio="main",
                evidence_type="diagnostic",
                metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")},
                production=main_production,
                source=rel(latest_run / "macro_policy_engine" / "summary.json"),
                notes="Macro/style sidecar is available for routing breakout growth, turnaround, compounder, or defense styles.",
                dependencies="Needs long-history macro learner and policy replay before production activation.",
                conflict_scope="Sets style opportunity set but yields to crisis and hard exits.",
                extra={
                    "macro_latest_risk_state": latest.get("macro_risk_state", ""),
                    "macro_latest_style_state": latest.get("macro_style_state", ""),
                },
            )
        )

    governance_summary = read_json(latest_run / "governance_catalyst" / "summary.json")
    rows.append(
        score_policy(
            policy_id="governance_catalyst_watch",
            portfolio="main",
            evidence_type="diagnostic" if governance_summary else "missing",
            metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")} if governance_summary else {},
            production=main_production,
            source=rel(latest_run / "governance_catalyst" / "summary.json") if governance_summary else "missing_governance_catalyst_summary",
            notes="Tracks insider/ownership/governance catalysts such as large buyers or government involvement.",
            dependencies="Can add to scout watchlists; needs data coverage and replay to affect buys.",
            conflict_scope="Does not override score, hard exits, or macro defense.",
            extra={"diagnostic_action": "watchlist_elevation_only"},
        )
    )

    autolearning_v2 = read_json(latest_run / "auto_learning_v2" / "promotion_decision.json")
    if autolearning_v2 or winner_challenger_summary:
        rows.append(
            score_policy(
                policy_id="auto_learning_policy_candidate",
                portfolio="main",
                evidence_type="proposal",
                metrics={"cagr": main_production.get("cagr"), "max_dd": main_production.get("max_dd"), "sharpe": main_production.get("sharpe")},
                production=main_production,
                source=rel(latest_run / "autolearning_winner_challenger" / "summary.json") if winner_challenger_summary else rel(latest_run / "auto_learning_v2" / "promotion_decision.json"),
                notes="AutoLearning proposes policy changes from anomalies, winner-onset, shakeout, cash, and replay evidence.",
                dependencies="Must generate executable challenger configs and pass replay gates before activation.",
                conflict_scope="Never overrides production policies directly.",
                extra={
                    "diagnostic_action": "proposal_only",
                    "autolearning_status": winner_challenger_summary.get("status", "") if isinstance(winner_challenger_summary, dict) else autolearning_v2.get("status", ""),
                },
            )
        )
    return rows


def dedupe_policy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("policy_id")), str(row.get("portfolio")))
        current = by_key.get(key)
        if current is None or safe_float(row.get("fusion_score"), -9999.0) > safe_float(current.get("fusion_score"), -9999.0):
            by_key[key] = row
    return sorted(by_key.values(), key=lambda row: (int(row.get("precedence") or 0), safe_float(row.get("fusion_score"), -9999.0)), reverse=True)


def activation_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for row in rows:
        stage = str(row.get("activation_stage") or "")
        if stage in {"reject_current_form", "blocked_missing_metrics"}:
            priority = "blocked"
        elif row.get("target_pass"):
            priority = "highest"
        elif stage in {"candidate_for_combination", "conditional_defense_only"}:
            priority = "high"
        else:
            priority = "watch"
        queue.append(
            {
                "priority": priority,
                "policy_id": row.get("policy_id"),
                "portfolio": row.get("portfolio"),
                "activation_stage": row.get("activation_stage"),
                "fusion_score": row.get("fusion_score"),
                "target_pass": row.get("target_pass"),
                "evidence_type": row.get("evidence_type"),
                "dependencies": row.get("dependencies"),
                "conflict_scope": row.get("conflict_scope"),
            }
        )
    priority_rank = {"highest": 3, "high": 2, "watch": 1, "blocked": 0}
    return sorted(queue, key=lambda row: (priority_rank.get(str(row.get("priority")), 0), safe_float(row.get("fusion_score"), -9999.0)), reverse=True)


def render_yaml_plan(rows: list[dict[str, Any]], queue: list[dict[str, Any]]) -> str:
    lines = [
        "alphaops_policy_fusion:",
        "  mode: shadow",
        "  production_mutation_allowed: false",
        "  precedence:",
    ]
    for item in POLICY_PRECEDENCE:
        lines.append(f"    - policy_id: {item['policy_id']}")
        lines.append(f"      precedence: {item['precedence']}")
        lines.append(f"      domain: {item['domain']}")
    lines.append("  activation_queue:")
    for item in queue[:12]:
        lines.append(f"    - policy_id: {item['policy_id']}")
        lines.append(f"      portfolio: {item['portfolio']}")
        lines.append(f"      priority: {item['priority']}")
        lines.append(f"      activation_stage: {item['activation_stage']}")
        lines.append(f"      target_pass: {str(bool(item['target_pass'])).lower()}")
        lines.append(f"      evidence_type: {item['evidence_type']}")
    lines.append("  conflict_rules:")
    for item in CONFLICT_RULES:
        lines.append(f"    - policy_a: {item['policy_a']}")
        lines.append(f"      policy_b: {item['policy_b']}")
        lines.append(f"      winner: {item['winner']}")
    return "\n".join(lines) + "\n"


def render_report(payload: dict[str, Any]) -> str:
    rows = payload.get("policy_candidates", [])
    queue = payload.get("activation_queue", [])
    lines = [
        "# AlphaOps Policy Fusion",
        "",
        "This report fuses sidecar and replay evidence into one conflict-aware activation plan.",
        "It does not mutate production defaults.",
        "",
        "## Production Rule",
        "",
        "1. Hard exits and crisis defense win over alpha expansion.",
        "2. Shakeout logic can defer soft trims, but never hard stops.",
        "3. Monster staged sizing can add risk only after liquidity, market-cap, macro, and risk gates pass.",
        "4. AutoLearning can propose policies, but replay gates decide activation.",
        "",
        "## Activation Queue",
        "",
        "| Priority | Policy | Portfolio | Stage | Evidence | Target Pass | Score |",
        "| --- | --- | --- | --- | --- | ---: | ---: |",
    ]
    for item in queue[:12]:
        lines.append(
            "| {priority} | `{policy}` | {portfolio} | `{stage}` | {evidence} | {passed} | {score} |".format(
                priority=item.get("priority"),
                policy=item.get("policy_id"),
                portfolio=item.get("portfolio"),
                stage=item.get("activation_stage"),
                evidence=item.get("evidence_type"),
                passed=str(item.get("target_pass")).lower(),
                score="" if item.get("fusion_score") is None else f"{safe_float(item.get('fusion_score'), 0.0):.2f}",
            )
        )
    lines.extend(["", "## Policy Evidence", "", "| Policy | Portfolio | CAGR | MaxDD | Sharpe | Delta CAGR | Delta MaxDD | Stage | Source |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"])
    for row in rows:
        lines.append(
            "| `{policy}` | {portfolio} | {cagr} | {maxdd} | {sharpe} | {dcagr} | {ddd} | `{stage}` | {source} |".format(
                policy=row.get("policy_id"),
                portfolio=row.get("portfolio"),
                cagr=pct(row.get("cagr")),
                maxdd=pct(row.get("max_dd")),
                sharpe="" if row.get("sharpe") is None else f"{safe_float(row.get('sharpe'), 0.0):.3f}",
                dcagr="" if row.get("delta_cagr_pp") is None else f"{safe_float(row.get('delta_cagr_pp'), 0.0):.2f}pp",
                ddd="" if row.get("delta_max_dd_pp") is None else f"{safe_float(row.get('delta_max_dd_pp'), 0.0):.2f}pp",
                stage=row.get("activation_stage"),
                source=row.get("source"),
            )
        )
    lines.extend(["", "## Conflict Matrix", "", "| Policy A | Policy B | Winner | Reason |", "| --- | --- | --- | --- |"])
    for rule in CONFLICT_RULES:
        lines.append(f"| `{rule['policy_a']}` | `{rule['policy_b']}` | `{rule['winner']}` | {rule['reason']} |")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    metric_rows = build_metric_policies(latest_run)
    diagnostic_rows = build_diagnostic_policies(latest_run)
    policy_rows = dedupe_policy_rows(metric_rows + diagnostic_rows)
    queue = activation_queue(policy_rows)
    actionable = [row for row in queue if row.get("priority") != "blocked"]
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "latest_run": rel(latest_run),
        "mode": "shadow",
        "production_mutation_allowed": False,
        "targets": TARGETS,
        "policy_precedence": POLICY_PRECEDENCE,
        "conflict_rules": CONFLICT_RULES,
        "policy_candidates": policy_rows,
        "activation_queue": queue,
        "top_recommendation": actionable[0] if actionable else {
            "priority": "blocked",
            "policy_id": "no_actionable_policy",
            "activation_stage": "blocked_missing_or_insufficient_evidence",
            "reason": "No policy has enough metrics evidence in the current artifact set.",
        },
    }
    fields = [
        "policy_id",
        "portfolio",
        "precedence",
        "candidate_id",
        "policy_variant",
        "evidence_type",
        "source",
        "production_ready",
        "activation_stage",
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
        "delta_cagr_pp",
        "delta_max_dd_pp",
        "delta_sharpe",
        "fusion_score",
        "priority_count",
        "diagnostic_action",
        "autolearning_status",
        "macro_latest_risk_state",
        "macro_latest_style_state",
        "dependencies",
        "conflict_scope",
        "notes",
    ]
    write_json(output_dir / "policy_fusion_summary.json", payload)
    write_rows(output_dir / "policy_candidates.csv", policy_rows, fields)
    write_rows(output_dir / "conflict_matrix.csv", CONFLICT_RULES, ["policy_a", "policy_b", "winner", "reason"])
    write_text(output_dir / "activation_plan.yaml", render_yaml_plan(policy_rows, queue))
    write_text(output_dir / "policy_fusion_report.md", render_report(payload))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(
        json.dumps(
            {
                "mode": payload.get("mode"),
                "top_recommendation": payload.get("top_recommendation"),
                "policy_count": len(payload.get("policy_candidates", [])),
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
