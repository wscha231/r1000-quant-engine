#!/usr/bin/env python3
"""Build a manifest-driven allowlist for Google Drive sync.

The manifest keeps the default Drive root focused on user_current outputs and
marks research/deprecated files explicitly so they cannot be mistaken for
official broker-ledger performance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


USER_CURRENT_FILES = [
    "README_FIRST.md",
    "01_current_holdings.csv",
    "02_cash_summary.json",
    "03_period_returns.csv",
    "04_official_metrics.json",
    "05_action_summary.md",
    "06_benchmark_comparison.csv",
    "07_research_sidecar_context.json",
    "summary.json",
]
OFFICIAL_FILES = [
    "patch_application_manifest.json",
    "alphaops_vnext/summary.json",
    "alphaops_vnext/production_activation.json",
    "alphaops_vnext/official_main_target_book.csv",
    "alphaops_vnext/official_concentrated_target_book.csv",
    "account_evaluation/official_metrics.json",
    "universe_health/summary.json",
    "universe_health/universe_source_audit.json",
    "universe_health/universe_fallback_decision.md",
    "universe_health/scored_row_count_by_date.csv",
    "universe_health/universe_membership_by_month.csv",
    "universe_health/tradeable_universe_by_month.csv",
    "universe_health/iwb_fetch_status.json",
    "data_freshness_contract/status.json",
    "data_freshness_contract/data_watermarks.json",
    "data_freshness_contract/data_snapshot_manifest.json",
    "data_freshness_contract/report.md",
    "metric_hygiene/summary.json",
    "metric_hygiene/official_metrics.json",
    "metric_hygiene/report.md",
    "broker_replay/main/metrics.json",
    "broker_replay/main/account_state_latest.json",
    "broker_replay/main/positions_latest.csv",
    "broker_replay/main/trades.csv",
    "broker_replay/main/cash_ledger.csv",
    "broker_replay/main/equity_curve.csv",
    "broker_replay/main/target_vs_actual_weights.csv",
    "broker_replay/concentrated/metrics.json",
    "broker_replay/concentrated/account_state_latest.json",
    "broker_replay/concentrated/positions_latest.csv",
    "broker_replay/concentrated/trades.csv",
    "broker_replay/concentrated/cash_ledger.csv",
    "broker_replay/concentrated/equity_curve.csv",
    "broker_replay/concentrated/target_vs_actual_weights.csv",
    "operating_snapshot/current_operating_holdings_latest.csv",
    "operating_snapshot/current_portfolio_snapshot_summary.json",
]
MINIMAL_ANALYSIS_FILES = [
    "patch_application_manifest.json",
    "alphaops_vnext/summary.json",
    "alphaops_vnext/production_activation.json",
    "alphaops_vnext/official_main_target_book.csv",
    "alphaops_vnext/official_concentrated_target_book.csv",
    "account_evaluation/official_metrics.json",
    "universe_health/summary.json",
    "universe_health/universe_source_audit.json",
    "universe_health/universe_fallback_decision.md",
    "universe_health/scored_row_count_by_date.csv",
    "universe_health/universe_membership_by_month.csv",
    "universe_health/tradeable_universe_by_month.csv",
    "universe_health/iwb_fetch_status.json",
    "data_freshness_contract/status.json",
    "data_freshness_contract/data_watermarks.json",
    "data_freshness_contract/data_snapshot_manifest.json",
    "data_freshness_contract/report.md",
    "metric_hygiene/summary.json",
    "metric_hygiene/official_metrics.json",
    "metric_hygiene/report.md",
    "broker_replay/main/metrics.json",
    "broker_replay/main/account_state_latest.json",
    "broker_replay/main/positions_latest.csv",
    "broker_replay/main/trades.csv",
    "broker_replay/main/cash_ledger.csv",
    "broker_replay/main/equity_curve.csv",
    "broker_replay/main/target_vs_actual_weights.csv",
    "broker_replay/concentrated/metrics.json",
    "broker_replay/concentrated/account_state_latest.json",
    "broker_replay/concentrated/positions_latest.csv",
    "broker_replay/concentrated/trades.csv",
    "broker_replay/concentrated/cash_ledger.csv",
    "broker_replay/concentrated/equity_curve.csv",
    "broker_replay/concentrated/target_vs_actual_weights.csv",
    "reports/operating_main_target_book.csv",
    "reports/operating_concentrated_target_book.csv",
]
OPERATOR_REVIEW_FILES = [
    "operating_snapshot/proposed_target_deltas_latest.csv",
    "account_ledger_preview/main/orders_preview.csv",
    "account_ledger_preview/concentrated/orders_preview.csv",
    "operator_review/execution_lag_review.json",
    "operator_review/execution_lag_review.md",
    "operator_review/position_risk_review.json",
    "operator_review/position_risk_review.md",
    "operator_review/concentrated_broker_variant_review.json",
    "operator_review/concentrated_broker_variant_review.md",
    "operator_review/position_cleanup_review.json",
    "operator_review/position_cleanup_review.md",
    "operator_review/dust_positions_report.csv",
    "operator_review/dust_cleanup_orders.csv",
    "operator_review/projected_holdings_after_ready_orders.csv",
    "baseline_lock/latest_status.json",
    "market_leader_challenger/summary.json",
    "market_leader_challenger/report.md",
    "market_leader_challenger/grid_results.csv",
    "market_leader_challenger/main_metrics.json",
    "market_leader_challenger/concentrated_metrics.json",
    "market_leader_challenger/parameter_stability.csv",
    "market_leader_challenger/cost_sensitivity.csv",
    "market_leader_challenger/holding_churn_diagnostics.csv",
    "live_trading_safety/safety_audit_summary.json",
    "portfolio_system_guard/error_check.json",
    "metric_hygiene/deprecated_metric_manifest.json",
]
RESEARCH_FILES = [
    "scored_latest.csv",
    "scored_unified.csv",
    "reports/candidate_replay_book.csv",
    "universe_health/summary.json",
    "universe_health/universe_source_audit.json",
    "universe_health/universe_fallback_decision.md",
    "universe_health/scored_row_count_by_date.csv",
    "universe_health/universe_membership_by_month.csv",
    "universe_health/tradeable_universe_by_month.csv",
    "universe_health/iwb_fetch_status.json",
    "backtest_metrics.json",
    "concentrated_backtest_metrics.json",
    "pit_top_manager_follow_study/summary.json",
    "pit_top_manager_follow_study/report.md",
    "pit_top_manager_follow_study/cohort_history.csv",
    "pit_top_manager_follow_study/event_forward_returns.csv",
    "pit_top_manager_follow_study/bucket_performance.csv",
    "market_leader_challenger/main_target_book.csv",
    "market_leader_challenger/concentrated_target_book.csv",
    "market_leader_challenger/selected_leaders_latest.csv",
    "market_leader_challenger/leader_state_history.csv",
    "market_leader_challenger/rejected_leaders.csv",
    "market_leader_challenger/attribution_by_component.csv",
    "market_leader_challenger/stress_window_metrics.csv",
    "market_leader_challenger/benchmark_relative_metrics.csv",
    "metric_hygiene/deprecated_legacy_backtest_metrics.json",
    "metric_hygiene/deprecated_concentrated_weight_level_metrics.json",
]
DEPRECATED_NAMES = {
    "backtest_metrics.json",
    "concentrated_backtest_metrics.json",
    "deprecated_legacy_backtest_metrics.json",
    "deprecated_concentrated_weight_level_metrics.json",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(
    *,
    latest_run: Path,
    rel_source: str,
    rel_dest: str,
    required: bool,
    semantic_type: str,
    production_valid: bool,
    metric_mode: str = "",
) -> dict[str, Any]:
    src = latest_run / rel_source
    exists = src.exists()
    return {
        "source": str(src),
        "relative_source": rel_source,
        "destination": rel_dest.replace("\\", "/"),
        "required": bool(required),
        "exists": bool(exists),
        "copied": False,
        "skipped": not exists,
        "failed": False,
        "bytes": int(src.stat().st_size) if exists and src.is_file() else 0,
        "sha256": sha256_file(src) if exists and src.is_file() else "",
        "semantic_type": semantic_type,
        "production_valid": bool(production_valid),
        "metric_mode": metric_mode,
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def official_mode(latest_run: Path) -> str:
    payload = load_json(latest_run / "account_evaluation" / "official_metrics.json")
    return str(payload.get("official_metric_mode") or payload.get("metric_mode") or "")


def build_entries(args: argparse.Namespace) -> list[dict[str, Any]]:
    latest_run = repo_path(args.latest_run)
    mode = str(args.mode)
    metric_mode = official_mode(latest_run)
    entries: list[dict[str, Any]] = []

    if mode == "off":
        return entries

    for name in USER_CURRENT_FILES:
        entries.append(
            entry(
                latest_run=latest_run,
                rel_source=f"user_current/{name}",
                rel_dest=f"user_current/{name}",
                required=True,
                semantic_type="current_holding" if name == "01_current_holdings.csv" else "official",
                production_valid=True,
                metric_mode=metric_mode if name in {"03_period_returns.csv", "04_official_metrics.json"} else "",
            )
        )

    if mode == "minimal":
        for name in MINIMAL_ANALYSIS_FILES:
            entries.append(
                entry(
                    latest_run=latest_run,
                    rel_source=name,
                    rel_dest=f"official/{args.run_id}/{name}",
                    required=False,
                    semantic_type="official",
                    production_valid=True,
                    metric_mode=metric_mode,
                )
            )

    if mode in {"official", "research"}:
        for name in OFFICIAL_FILES:
            entries.append(
                entry(
                    latest_run=latest_run,
                    rel_source=name,
                    rel_dest=f"official/{args.run_id}/{name}",
                    required=False,
                    semantic_type="official",
                    production_valid=True,
                    metric_mode=metric_mode,
                )
            )
        for name in OPERATOR_REVIEW_FILES:
            entries.append(
                entry(
                    latest_run=latest_run,
                    rel_source=name,
                    rel_dest=f"operator_review/{args.run_id}/{name}",
                    required=False,
                    semantic_type="operator_review",
                    production_valid=False,
                )
            )

    if mode == "research":
        for name in RESEARCH_FILES:
            semantic = "deprecated" if Path(name).name in DEPRECATED_NAMES else "research"
            entries.append(
                entry(
                    latest_run=latest_run,
                    rel_source=name,
                    rel_dest=f"research_runs/{args.safe_branch}/{args.run_id}/research_full/{name}",
                    required=False,
                    semantic_type=semantic,
                    production_valid=False,
                    metric_mode="" if semantic == "research" else "weight_level_research_deprecated",
                )
            )

    return entries


def apply_copy_status(entries: list[dict[str, Any]], status_path: Path) -> None:
    if not status_path.exists():
        return
    status_by_source: dict[str, dict[str, Any]] = {}
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        status_by_source[str(row.get("source"))] = row
    for item in entries:
        row = status_by_source.get(str(item.get("source")))
        if not row:
            continue
        item["copied"] = bool(row.get("copied"))
        item["failed"] = bool(row.get("failed"))
        item["skipped"] = bool(row.get("skipped"))
        if row.get("error"):
            item["error"] = str(row.get("error"))


def write_tsv(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for item in entries:
        if not item.get("exists"):
            continue
        lines.append(
            "\t".join(
                [
                    str(item["source"]),
                    str(item["destination"]),
                    "true" if item.get("required") else "false",
                    str(item.get("semantic_type") or ""),
                    "true" if item.get("production_valid") else "false",
                    str(item.get("metric_mode") or ""),
                ]
            )
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    output = repo_path(args.output)
    tsv = repo_path(args.tsv)
    entries = build_entries(args)
    if args.copy_status:
        apply_copy_status(entries, repo_path(args.copy_status))
    missing_required = [item for item in entries if item.get("required") and not item.get("exists")]
    payload = {
        "schema_version": "gdrive-sync-manifest-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": str(args.run_id),
        "run_attempt": str(args.run_attempt),
        "head_sha": str(args.head_sha),
        "branch_name": str(args.branch_name),
        "safe_branch": str(args.safe_branch),
        "auth": str(args.auth),
        "mode": str(args.mode),
        "dest": str(args.dest),
        "portfolio_system_guard_hard_errors": str(args.portfolio_system_guard_hard_errors),
        "required_file_count": int(sum(1 for item in entries if item.get("required"))),
        "missing_required_count": int(len(missing_required)),
        "entries": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_tsv(tsv, entries)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--mode", choices=["minimal", "official", "research", "off"], default="minimal")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-attempt", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--branch-name", default="")
    parser.add_argument("--safe-branch", default="")
    parser.add_argument("--auth", default="")
    parser.add_argument("--dest", default="")
    parser.add_argument("--portfolio-system-guard-hard-errors", default="")
    parser.add_argument("--output", default="outputs/gdrive_sync_manifest.json")
    parser.add_argument("--tsv", default="outputs/gdrive_sync_files.tsv")
    parser.add_argument("--copy-status", default="")
    parser.add_argument("--strict-primary", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_manifest(args)
    print(json.dumps({k: payload[k] for k in ["schema_version", "mode", "required_file_count", "missing_required_count"]}, indent=2))
    if args.strict_primary and int(payload.get("missing_required_count") or 0) > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
