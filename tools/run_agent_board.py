#!/usr/bin/env python3
"""Build the research-only multi-agent board from official artifacts.

The board is an artifact-only control layer. It does not run model training,
change production defaults, promote a portfolio, or call any external LLM API.
It reads official broker-ledger/account-evaluation artifacts, compares them to
the locked baselines, then emits a task queue for specialist agents and manual
ChatGPT Pro review packets that the operator can copy/paste.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from r1000_config import PORTFOLIO_GOAL_TARGETS
except Exception:  # pragma: no cover - isolated smoke fallback
    PORTFOLIO_GOAL_TARGETS = {
        "main": {"cagr": 0.30, "max_dd": -0.15},
        "concentrated": {"cagr": 0.50, "max_dd": -0.18},
    }


DEFAULT_LATEST_RUN = "outputs"
DEFAULT_OUTPUT_DIR = "outputs/agent_board"
OFFICIAL_METRIC_MODE = "broker_ledger_next_close"
PORTFOLIOS = ("main", "concentrated")

BASELINES: dict[str, dict[str, Any]] = {
    "main": {
        "baseline_id": "codex/broker-ledger-replay-foundation",
        "run_id": "latest_global_alpha_universe",
        "cagr": 0.2184,
        "max_dd": -0.2862,
        "sharpe": 1.056,
        "note": "Best confirmed main research baseline under official broker-ledger evidence.",
    },
    "main_current_control": {
        "baseline_id": "20260511_global_alpha_universe",
        "run_id": "20260511_global_alpha_universe",
        "cagr": 0.2109,
        "max_dd": -0.3169,
        "sharpe": 1.003,
        "note": "Best confirmed main control on the current branch.",
    },
    "concentrated": {
        "baseline_id": "20260514_global_alpha_universe",
        "run_id": "20260514_global_alpha_universe",
        "cagr": 0.3510,
        "max_dd": -0.2268,
        "sharpe": 1.300,
        "note": "Best confirmed concentrated balance baseline; N7 latest is a regression case.",
    },
    "latest_20260516_regression": {
        "baseline_id": "latest_20260516",
        "main_cagr": 0.1286,
        "main_max_dd": -0.2707,
        "concentrated_cagr": 0.1689,
        "concentrated_max_dd": -0.3380,
        "note": "Regression case only; not a promotion baseline.",
    },
}

AGENT_CONTRACTS: dict[str, dict[str, Any]] = {
    "A0": {
        "name": "Orchestrator",
        "role": "Freeze baselines, rank work, and block production promotion when official evidence is weak.",
        "allowed": ["research/agent_board/", "outputs/agent_board/"],
    },
    "A2": {
        "name": "SEC Evidence",
        "role": "Expand PIT-safe filing-event evidence after Form 4: 13D/G, 8-K, 13F, and Form 144.",
        "allowed": ["tools/run_sec_*.py", "tests/sec_*_smoke.py", "data_pit/sec/", "outputs/sec_*"],
    },
    "A3": {
        "name": "Selection",
        "role": "Validate future-winner, market-confirmation, and early-evidence shadow scores.",
        "allowed": ["tools/run_selection_quality_report.py", "tools/run_alpha_selector_broker_grid.py"],
    },
    "A4": {
        "name": "Main PM",
        "role": "Build main challengers against the main official baseline only.",
        "allowed": ["tools/run_main_*", "outputs/alpha_selector_*", "outputs/portfolio_goal_search/"],
    },
    "A5": {
        "name": "Concentrated PM",
        "role": "Recover and improve concentrated N2/N3/N5 against the 20260514 baseline; N7 cannot be champion.",
        "allowed": ["tools/run_concentrated_*", "outputs/concentrated_*"],
    },
    "A6": {
        "name": "Broker/Risk",
        "role": "Regenerate or audit broker-ledger next-close account evidence and stress/cost sensitivity.",
        "allowed": ["tools/run_broker_*", "tools/run_account_evaluation.py", "outputs/broker_*"],
    },
    "A7": {
        "name": "Diagnostics",
        "role": "Explain run-to-run regressions, missed winners, wrong substitutions, and cash policy gaps.",
        "allowed": ["tools/run_*diagnostics*.py", "tools/run_*attribution*.py", "outputs/*diagnostics*/"],
    },
    "A10": {
        "name": "AutoLearning/Test Engine",
        "role": "Mine completed experiments into candidate specs without promoting production defaults.",
        "allowed": ["tools/run_auto_*", "tests/auto_*_smoke.py", "outputs/auto_learning/"],
    },
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def pct(value: float | None) -> str:
    if value is None:
        return "missing"
    return f"{value:.2%}"


def pp(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100.0, 4)


def metric(row: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in row:
            value = safe_float(row.get(name))
            if value is not None:
                return value
    return None


def target_for(portfolio: str) -> dict[str, float]:
    target = PORTFOLIO_GOAL_TARGETS.get(portfolio, {})
    return {
        "cagr": float(target.get("cagr", 0.30 if portfolio == "main" else 0.50)),
        "max_dd": float(target.get("max_dd", -0.15 if portfolio == "main" else -0.18)),
    }


def account_official_row(latest_run: Path, portfolio: str) -> tuple[dict[str, Any], str]:
    official = read_json(latest_run / "account_evaluation" / "official_metrics.json")
    portfolios = official.get("portfolios") if isinstance(official.get("portfolios"), dict) else {}
    row = portfolios.get(portfolio) if isinstance(portfolios, dict) else None
    if isinstance(row, dict):
        out = dict(row)
        out.setdefault("official_metric_mode", official.get("official_metric_mode"))
        return out, "account_evaluation/official_metrics.json"
    return {}, ""


def broker_metrics_row(latest_run: Path, portfolio: str) -> tuple[dict[str, Any], str]:
    row = read_json(latest_run / "broker_replay" / portfolio / "metrics.json")
    return row, f"broker_replay/{portfolio}/metrics.json" if row else ""


def load_portfolio_status(latest_run: Path, portfolio: str) -> dict[str, Any]:
    account_row, account_source = account_official_row(latest_run, portfolio)
    broker_row, broker_source = broker_metrics_row(latest_run, portfolio)
    row = account_row or broker_row
    source = account_source or broker_source or f"broker_replay/{portfolio}/metrics.json"
    baseline = BASELINES[portfolio]
    target = target_for(portfolio)

    cagr = metric(row, "cagr", "strategy_cagr", "annual_return")
    max_dd = metric(row, "max_dd", "max_drawdown")
    sharpe = metric(row, "sharpe", "Sharpe")
    status = str(row.get("status") or ("completed" if row else "missing"))
    metric_mode = str(row.get("official_metric_mode") or row.get("metric_mode") or "")
    valid_for_production = bool(row.get("valid_for_production")) and status == "completed"
    official = bool(valid_for_production and metric_mode == OFFICIAL_METRIC_MODE)
    cagr_delta = None if cagr is None else cagr - float(baseline["cagr"])
    dd_delta = None if max_dd is None else max_dd - float(baseline["max_dd"])
    cagr_gap_to_target = None if cagr is None else max(0.0, target["cagr"] - cagr)
    dd_gap_to_target = None if max_dd is None else max(0.0, target["max_dd"] - max_dd)
    baseline_beat = bool(
        official
        and cagr is not None
        and max_dd is not None
        and cagr >= float(baseline["cagr"])
        and max_dd >= float(baseline["max_dd"])
    )
    target_pass = bool(
        official
        and cagr is not None
        and max_dd is not None
        and cagr >= target["cagr"]
        and max_dd >= target["max_dd"]
    )

    if not row:
        governance_action = "rerun_broker_ledger_missing_official"
    elif not official:
        governance_action = "block_non_official_metric"
    elif target_pass:
        governance_action = "human_promotion_review_required"
    elif baseline_beat:
        governance_action = "keep_as_research_challenger"
    else:
        governance_action = "recover_against_locked_baseline"

    return {
        "portfolio": portfolio,
        "source": source,
        "status": status,
        "official_metric_mode": metric_mode or "missing",
        "valid_for_production": valid_for_production,
        "official_evidence": official,
        "target_pass": target_pass,
        "baseline_beat": baseline_beat,
        "governance_action": governance_action,
        "cagr": cagr,
        "baseline_cagr": baseline["cagr"],
        "cagr_delta_vs_baseline_pp": pp(cagr_delta),
        "cagr_target": target["cagr"],
        "cagr_gap_to_target_pp": pp(cagr_gap_to_target),
        "max_dd": max_dd,
        "baseline_max_dd": baseline["max_dd"],
        "max_dd_delta_vs_baseline_pp": pp(dd_delta),
        "max_dd_target": target["max_dd"],
        "max_dd_gap_to_target_pp": pp(dd_gap_to_target),
        "sharpe": sharpe,
        "trade_count": row.get("trade_count") or row.get("broker_trade_count"),
        "avg_cash_weight": metric(row, "avg_cash_weight"),
        "baseline": baseline,
    }


def first_existing_json(latest_run: Path, relative_paths: list[str]) -> tuple[dict[str, Any], str]:
    for rel_path in relative_paths:
        path = latest_run / rel_path
        payload = read_json(path)
        if payload:
            return payload, rel_path
    for rel_path in relative_paths:
        path = REPO_ROOT / rel_path
        payload = read_json(path)
        if payload:
            return payload, rel_path
    return {}, relative_paths[0] if relative_paths else ""


def load_artifact_status(latest_run: Path) -> dict[str, Any]:
    sec, sec_source = first_existing_json(
        latest_run,
        [
            "sec_enriched_candidate_replay/summary.json",
            "outputs/sec_enriched_candidate_replay/summary.json",
            "outputs/sec_ownership_signals/ownership_signal_summary.json",
        ],
    )
    goal, goal_source = first_existing_json(
        latest_run,
        [
            "portfolio_goal_search/goal_search_summary.json",
            "outputs/portfolio_goal_search/goal_search_summary.json",
        ],
    )
    selection, selection_source = first_existing_json(
        latest_run,
        [
            "selection_quality/selection_quality_summary.json",
            "outputs/selection_quality/selection_quality_summary.json",
            "selection_quality/summary.json",
            "outputs/selection_quality/summary.json",
        ],
    )
    diagnostics, diagnostics_source = first_existing_json(
        latest_run,
        [
            "leader_drop_diagnostics/summary.json",
            "outputs/leader_drop_diagnostics/summary.json",
            "market_circuit_attribution/summary.json",
            "outputs/market_circuit_attribution/summary.json",
        ],
    )
    auto_learning, auto_learning_source = first_existing_json(
        latest_run,
        [
            "auto_learning/summary.json",
            "outputs/auto_learning/summary.json",
            "auto_learning_v2/summary.json",
            "outputs/auto_learning_v2/summary.json",
        ],
    )
    return {
        "sec_evidence": summarize_artifact("sec_evidence", sec, sec_source),
        "portfolio_goal_search": summarize_artifact("portfolio_goal_search", goal, goal_source),
        "selection_quality": summarize_artifact("selection_quality", selection, selection_source),
        "diagnostics": summarize_artifact("diagnostics", diagnostics, diagnostics_source),
        "auto_learning": summarize_artifact("auto_learning", auto_learning, auto_learning_source),
    }


def summarize_artifact(name: str, payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "name": name,
        "source": source,
        "available": bool(payload),
        "status": payload.get("status") or ("available" if payload else "missing"),
        "research_only": payload.get("research_only"),
        "production_activation_allowed": payload.get("production_activation_allowed", False) if payload else False,
        "coverage_ratio": payload.get("coverage_ratio"),
        "target_pass": payload.get("target_pass"),
        "production_target_pass": payload.get("production_target_pass"),
        "keys": sorted(payload.keys())[:20] if payload else [],
    }


def task(
    *,
    agent: str,
    priority: str,
    title: str,
    rationale: str,
    inputs: list[str],
    next_command: str,
    success_criteria: list[str],
    pro_review: bool = True,
    parallel_group: str = "research",
) -> dict[str, Any]:
    contract = AGENT_CONTRACTS[agent]
    return {
        "agent": agent,
        "agent_name": contract["name"],
        "priority": priority,
        "parallel_group": parallel_group,
        "title": title,
        "rationale": rationale,
        "inputs": inputs,
        "suggested_next_command": next_command,
        "success_criteria": success_criteria,
        "manual_chatgpt_pro_review": pro_review,
        "allowed_paths": contract["allowed"],
        "forbidden_changes": [
            "production default activation",
            "score_total promotion without broker-ledger proof",
            "legacy/proxy metric relabeling as official",
        ],
    }


def build_task_queue(board: dict[str, Any]) -> list[dict[str, Any]]:
    portfolios = {row["portfolio"]: row for row in board["portfolios"]}
    artifacts = board["artifacts"]
    tasks: list[dict[str, Any]] = []
    any_missing_official = any(not row["official_evidence"] for row in portfolios.values())
    any_recovery = any(row["governance_action"] == "recover_against_locked_baseline" for row in portfolios.values())

    tasks.append(
        task(
            agent="A0",
            priority="P0" if any_missing_official or any_recovery else "P1",
            title="Review official baseline verdict and lock next sprint order",
            rationale="Every downstream agent needs a single source of truth for official status and locked baselines.",
            inputs=["outputs/agent_board/board_summary.json", "research/multi_agent_operating_plan_20260516/baseline_registry.md"],
            next_command="python tools/run_agent_board.py --latest-run outputs",
            success_criteria=[
                "Main and concentrated are judged separately against their locked baselines.",
                "Promotion remains blocked unless both portfolios pass official broker-ledger gates.",
                "Next three agent tasks are ordered by official metric impact.",
            ],
            parallel_group="control",
        )
    )

    if any_missing_official:
        tasks.append(
            task(
                agent="A6",
                priority="P0",
                title="Regenerate missing or non-official broker-ledger evidence",
                rationale="The board refuses promotion whenever broker-ledger next-close valid_for_production evidence is missing.",
                inputs=["broker_replay/main/metrics.json", "broker_replay/concentrated/metrics.json", "account_evaluation/official_metrics.json"],
                next_command="python tools/run_account_evaluation.py --latest-run outputs --output-dir outputs/account_evaluation",
                success_criteria=[
                    "Both portfolios have metric_mode broker_ledger_next_close.",
                    "Both portfolios have valid_for_production=true and status=completed.",
                    "Legacy/proxy metrics remain comparison-only.",
                ],
                pro_review=False,
                parallel_group="broker",
            )
        )

    sec_artifact = artifacts["sec_evidence"]
    if not sec_artifact["available"]:
        tasks.append(
            task(
                agent="A2",
                priority="P1",
                title="Create Form 4 SEC evidence artifacts before expanding to 13D/8-K/13F",
                rationale="SEC evidence must exist as PIT-safe shadow data before selector agents can test it.",
                inputs=["data_pit/sec/form4_transactions.parquet", "outputs/sec_enriched_candidate_replay/summary.json"],
                next_command="python tools/run_sec_enriched_candidate_replay.py --candidate-book outputs/reports/candidate_replay_book.csv --form4 data_pit/sec/form4_transactions.parquet",
                success_criteria=[
                    "accepted_at/available_from is enforced.",
                    "score_total is unchanged.",
                    "Form 4 evidence remains research-only.",
                ],
                parallel_group="data",
            )
        )
    else:
        tasks.append(
            task(
                agent="A2",
                priority="P2",
                title="Extend SEC shadow evidence after Form 4",
                rationale="Form 4 is only the first evidence source; 13D/G and 8-K are the next fast filing-event signals.",
                inputs=[sec_artifact["source"], "data_pit/sec/sec_filings_index.parquet"],
                next_command="python tools/run_sec_submissions_collector.py --forms 4,13D,13D/A,13G,13G/A,8-K",
                success_criteria=[
                    "13D/G and 8-K rows include accepted_at and available_from.",
                    "New SEC features are shadow-only.",
                    "No feature is visible before available_from.",
                ],
                parallel_group="data",
            )
        )

    if not artifacts["selection_quality"]["available"] or sec_artifact["available"]:
        tasks.append(
            task(
                agent="A3",
                priority="P1" if sec_artifact["available"] else "P2",
                title="Validate leader_onset_sec_v2 as a shadow ranking factor",
                rationale="SEC evidence should improve selection only after selection-quality and broker-ledger challengers confirm it.",
                inputs=["outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv", "outputs/selection_quality/"],
                next_command="python tools/run_selection_quality_report.py",
                success_criteria=[
                    "future_winner remains the control factor.",
                    "leader_onset_sec_v2 is reported separately from score_total.",
                    "Forward-return columns are diagnostics-only and not used for target construction.",
                ],
                parallel_group="selection",
            )
        )

    main = portfolios["main"]
    if not main["baseline_beat"] or not main["target_pass"]:
        tasks.append(
            task(
                agent="A4",
                priority="P1",
                title="Run main future-winner plus SEC-evidence challengers",
                rationale=(
                    "Main must beat the codex/broker-ledger baseline before any production review. "
                    f"Current official CAGR={pct(main['cagr'])}, MaxDD={pct(main['max_dd'])}."
                ),
                inputs=["outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv", "outputs/alpha_selector_broker_grid/main/"],
                next_command=(
                    "python tools/run_alpha_selector_broker_grid.py --candidate-book "
                    "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv "
                    "--portfolio-kind main --styles sec_evidence_shadow,leader_onset_shadow,smart_money_shadow --target-ns 12,15,18"
                ),
                success_criteria=[
                    "Official broker-ledger CAGR exceeds 21.84%.",
                    "Official broker-ledger MaxDD is no worse than -28.62%.",
                    "Candidate keeps production_activation_allowed=false until human review.",
                ],
                parallel_group="portfolio",
            )
        )

    concentrated = portfolios["concentrated"]
    if not concentrated["baseline_beat"] or not concentrated["target_pass"]:
        tasks.append(
            task(
                agent="A5",
                priority="P1",
                title="Recover concentrated N2/N3/N5 broker-selected leaders",
                rationale=(
                    "Concentrated must beat 20260514 and N7 cannot be champion. "
                    f"Current official CAGR={pct(concentrated['cagr'])}, MaxDD={pct(concentrated['max_dd'])}."
                ),
                inputs=["outputs/alpha_selector_broker_grid/concentrated/", "outputs/concentrated_broker_grid/"],
                next_command=(
                    "python tools/run_alpha_selector_broker_grid.py --candidate-book "
                    "outputs/sec_enriched_candidate_replay/candidate_replay_book_sec_enriched.csv "
                    "--portfolio-kind concentrated --styles sec_evidence_shadow,monster_heavy --target-ns 2,3,5"
                ),
                success_criteria=[
                    "N7 is not selected as concentrated champion.",
                    "Official broker-ledger CAGR exceeds 35.10%.",
                    "Official broker-ledger MaxDD is no worse than -22.68%.",
                ],
                parallel_group="portfolio",
            )
        )

    if any_recovery or not artifacts["diagnostics"]["available"]:
        tasks.append(
            task(
                agent="A7",
                priority="P1",
                title="Explain regression with hold-vs-replace and missed-leader diagnostics",
                rationale="A challenger should not be tuned further until the board knows whether the regression is churn, missed leaders, or cash drag.",
                inputs=["outputs/leader_drop_diagnostics/", "outputs/market_circuit_attribution/", "outputs/hold_vs_replace_audit/"],
                next_command="python tools/run_market_circuit_attribution.py",
                success_criteria=[
                    "Top wrong substitutions are listed.",
                    "Missed winner path is split into universe, score, target, and broker-fill stages.",
                    "Next three testable hypotheses are written for A10.",
                ],
                parallel_group="diagnostics",
            )
        )

    tasks.append(
        task(
            agent="A10",
            priority="P2",
            title="Turn completed experiments into candidate specs",
            rationale="AutoLearning should propose bounded candidate specs from historical artifacts; it must not activate production defaults.",
            inputs=["outputs/portfolio_goal_search/goal_search_summary.json", "outputs/selection_quality/", "outputs/agent_board/agent_task_queue.json"],
            next_command="python tools/run_agent_board.py --latest-run outputs --output-dir outputs/agent_board",
            success_criteria=[
                "Candidate specs include target_n, score_source, no-trade band, cash floor, and evaluation command.",
                "Each spec names its baseline and official success criterion.",
                "No spec is marked production-ready without broker-ledger evidence.",
            ],
            parallel_group="autolearning",
        )
    )

    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(tasks, key=lambda item: (priority_order.get(str(item["priority"]), 9), str(item["agent"])))


def promotion_gate(board: dict[str, Any]) -> dict[str, Any]:
    portfolios = board["portfolios"]
    official = all(bool(row.get("official_evidence")) for row in portfolios)
    target_pass = all(bool(row.get("target_pass")) for row in portfolios)
    baseline_beat = all(bool(row.get("baseline_beat")) for row in portfolios)
    allowed = bool(official and target_pass and baseline_beat)
    blockers: list[str] = []
    for row in portfolios:
        if not row.get("official_evidence"):
            blockers.append(f"{row['portfolio']}: missing official broker-ledger next-close evidence")
        elif not row.get("baseline_beat"):
            blockers.append(f"{row['portfolio']}: has not beaten locked baseline")
        elif not row.get("target_pass"):
            blockers.append(f"{row['portfolio']}: has not reached final portfolio target")
    return {
        "production_activation_allowed": False,
        "human_promotion_review_candidate": allowed,
        "automatic_promotion_allowed": False,
        "official_metric_mode_required": OFFICIAL_METRIC_MODE,
        "blockers": blockers,
        "rule": "Even a target pass requires human approval before production default changes.",
    }


def compact_inputs(board: dict[str, Any], agent: str) -> str:
    lines = [
        f"Generated at UTC: {board['generated_at_utc']}",
        f"Latest run: {board['latest_run']}",
        f"Run URL: {board.get('run_url') or 'not provided'}",
        "",
        "Official portfolio status:",
    ]
    for row in board["portfolios"]:
        lines.append(
            "- {portfolio}: official={official}, cagr={cagr}, max_dd={max_dd}, "
            "baseline_cagr={bcagr}, baseline_max_dd={bdd}, action={action}".format(
                portfolio=row["portfolio"],
                official=str(row["official_evidence"]).lower(),
                cagr=pct(row["cagr"]),
                max_dd=pct(row["max_dd"]),
                bcagr=pct(row["baseline_cagr"]),
                bdd=pct(row["baseline_max_dd"]),
                action=row["governance_action"],
            )
        )
    lines.append("")
    lines.append("Relevant artifacts:")
    for artifact in board["artifacts"].values():
        lines.append(f"- {artifact['name']}: available={str(artifact['available']).lower()}, source={artifact['source']}")
    lines.append("")
    lines.append(f"Agent focus: {agent} {AGENT_CONTRACTS[agent]['name']} - {AGENT_CONTRACTS[agent]['role']}")
    return "\n".join(lines)


def render_pro_packet(board: dict[str, Any], task_row: dict[str, Any]) -> str:
    agent = str(task_row["agent"])
    return "\n".join(
        [
            "[PRO_QUESTION]",
            "",
            "You are an external strategy/risk reviewer for the r1000-quant-engine project.",
            "",
            "Hard rules:",
            f"- Production performance evidence must be {OFFICIAL_METRIC_MODE}.",
            "- valid_for_production=true is required for promotion evidence.",
            "- Legacy/proxy/backtest_metrics numbers are reference-only.",
            "- Forward-return leakage, PIT violations, and SEC feature use before accepted_at/available_from are prohibited.",
            "- Production default changes require human approval.",
            "- Main and concentrated must be judged against separate locked baselines.",
            "",
            "Locked baselines:",
            "- Main: codex/broker-ledger-replay-foundation, CAGR 21.84%, MaxDD -28.62%.",
            "- Main current branch control: 20260511_global_alpha_universe, CAGR 21.09%, MaxDD -31.69%.",
            "- Concentrated: 20260514_global_alpha_universe, CAGR 35.10%, MaxDD -22.68%.",
            "- latest 20260516 is a regression case, not a promotion baseline.",
            "",
            f"Agent: {agent} {task_row['agent_name']}",
            f"Purpose: {task_row['title']}",
            "",
            "Context:",
            compact_inputs(board, agent),
            "",
            "Question:",
            task_row["rationale"],
            "Give the next concrete Codex task instruction for this agent. Keep it bounded and research-only.",
            "",
            "Required Output:",
            "1. Conclusion",
            "2. Official metric judgment",
            "3. Risk/leakage concerns",
            "4. Next Codex agent instructions",
            "5. Promotion possible: yes/no",
            "6. Human approval items",
            "",
        ]
    )


def render_report(board: dict[str, Any], tasks: list[dict[str, Any]], gate: dict[str, Any]) -> str:
    lines = [
        "# Agent Board",
        "",
        "Research-only automation board. It reads artifacts, assigns agent work, and writes manual Pro review packets. It does not change production defaults.",
        "",
        f"- generated_at_utc: `{board['generated_at_utc']}`",
        f"- latest_run: `{board['latest_run']}`",
        f"- run_url: `{board.get('run_url') or ''}`",
        f"- automatic_promotion_allowed: `{str(gate['automatic_promotion_allowed']).lower()}`",
        f"- human_promotion_review_candidate: `{str(gate['human_promotion_review_candidate']).lower()}`",
        "",
        "## Official Status",
        "",
        "| Portfolio | Official | CAGR | Baseline | Delta pp | MaxDD | Baseline | Delta pp | Action |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in board["portfolios"]:
        lines.append(
            "| {portfolio} | {official} | {cagr} | {bcagr} | {cdelta} | {dd} | {bdd} | {ddelta} | {action} |".format(
                portfolio=row["portfolio"],
                official=str(row["official_evidence"]).lower(),
                cagr=pct(row["cagr"]),
                bcagr=pct(row["baseline_cagr"]),
                cdelta="" if row["cagr_delta_vs_baseline_pp"] is None else f"{row['cagr_delta_vs_baseline_pp']:.2f}",
                dd=pct(row["max_dd"]),
                bdd=pct(row["baseline_max_dd"]),
                ddelta="" if row["max_dd_delta_vs_baseline_pp"] is None else f"{row['max_dd_delta_vs_baseline_pp']:.2f}",
                action=row["governance_action"],
            )
        )
    lines.extend(["", "## Artifact Status", "", "| Artifact | Available | Source | Status |", "| --- | ---: | --- | --- |"])
    for artifact in board["artifacts"].values():
        lines.append(
            f"| {artifact['name']} | {str(artifact['available']).lower()} | `{artifact['source']}` | {artifact['status']} |"
        )
    lines.extend(["", "## Agent Queue", "", "| Priority | Agent | Task | Parallel Group | Pro Packet |", "| --- | --- | --- | --- | --- |"])
    for item in tasks:
        pro_packet = f"pro_packets/{str(item['agent']).lower()}.md" if item["manual_chatgpt_pro_review"] else ""
        lines.append(
            f"| {item['priority']} | {item['agent']} {item['agent_name']} | {item['title']} | {item['parallel_group']} | `{pro_packet}` |"
        )
    lines.extend(["", "## Promotion Gate", ""])
    if gate["blockers"]:
        for blocker in gate["blockers"]:
            lines.append(f"- blocked: {blocker}")
    else:
        lines.append("- no metric blockers, but human approval is still required before production activation.")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    board = {
        "schema_version": "agent-board-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "latest_run": rel(latest_run),
        "run_url": args.run_url or "",
        "official_metric_mode_required": OFFICIAL_METRIC_MODE,
        "production_activation_allowed": False,
        "baselines": BASELINES,
        "agent_contracts": AGENT_CONTRACTS,
        "portfolios": [load_portfolio_status(latest_run, portfolio) for portfolio in PORTFOLIOS],
        "artifacts": load_artifact_status(latest_run),
    }
    tasks = build_task_queue(board)
    if args.max_tasks and args.max_tasks > 0:
        tasks = tasks[: int(args.max_tasks)]
    gate = promotion_gate(board)
    board["promotion_gate"] = gate
    board["task_count"] = len(tasks)

    write_json(output_dir / "board_summary.json", board)
    write_json(output_dir / "agent_task_queue.json", tasks)
    write_json(output_dir / "promotion_gate_review.json", gate)
    write_text(output_dir / "report.md", render_report(board, tasks, gate))
    pro_dir = output_dir / "pro_packets"
    for item in tasks:
        if item.get("manual_chatgpt_pro_review"):
            write_text(pro_dir / f"{str(item['agent']).lower()}.md", render_pro_packet(board, item))
    manifest = {
        "status": "ok",
        "output_dir": rel(output_dir),
        "board_summary": rel(output_dir / "board_summary.json"),
        "agent_task_queue": rel(output_dir / "agent_task_queue.json"),
        "promotion_gate_review": rel(output_dir / "promotion_gate_review.json"),
        "report": rel(output_dir / "report.md"),
        "pro_packets": sorted(rel(path) for path in pro_dir.glob("*.md")) if pro_dir.exists() else [],
    }
    write_json(output_dir / "manifest.json", manifest)
    return {**manifest, "task_count": len(tasks), "promotion_gate": gate}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-url", default="")
    parser.add_argument("--max-tasks", type=int, default=0, help="Optional cap for the emitted task queue; 0 keeps all tasks.")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
