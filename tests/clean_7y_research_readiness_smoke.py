#!/usr/bin/env python3
"""Smoke tests for clean 7Y research readiness."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_clean_7y_research_readiness import READY, classify_clean_7y_readiness, write_outputs  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_base(
    root: Path,
    *,
    years: float = 7.05,
    data_ready: bool = True,
    universe_count: int = 650,
    daily_snapshot_pass: bool = True,
    cash_trap_rows: int = 0,
    metric_mode: str = "broker_ledger_next_close",
) -> None:
    portfolios = {}
    for portfolio in ("main", "concentrated"):
        row = {
            "portfolio": portfolio,
            "status": "completed",
            "official_metric_mode": metric_mode,
            "valid_for_production": False,
            "target_pass": False,
            "strengthened_pass": False,
            "years": years,
            "broker_ledger_actual_trading_days": int(years * 252),
            "broker_ledger_window_gate": {
                "status": "invalid_window",
                "valid": False,
                "years": years,
                "actual_trading_days": int(years * 252),
                "reasons": ["broker_ledger_years_below_8"],
            },
        }
        portfolios[portfolio] = row
        write_json(
            root / "broker_replay" / portfolio / "metrics.json",
            {
                "status": "completed",
                "metric_mode": metric_mode,
                "valid_for_production": False,
                "years": years,
                "days": int(years * 252),
            },
        )
    write_json(
        root / "account_evaluation" / "official_metrics.json",
        {
            "official_metric_mode": metric_mode,
            "production_target_pass": False,
            "strengthened_pass": False,
            "portfolios": portfolios,
        },
    )
    write_json(
        root / "data_readiness" / "summary.json",
        {
            "schema_version": "data-readiness-v1",
            "status": "ready" if data_ready else "blocked",
            "ready_for_policy_replay": data_ready,
            "ready_for_fullrun": data_ready,
            "blockers": [] if data_ready else ["data_readiness_not_ready_for_policy_replay"],
            "free_data_coverage": {"known_gaps": []},
        },
    )
    write_json(
        root / "universe_health" / "universe_source_audit.json",
        {
            "schema_version": "universe-health-v1",
            "status": "ready" if universe_count >= 400 else "INVALID_UNIVERSE",
            "promotion_allowed": universe_count >= 400,
            "hard_fail_before_expensive_rebuild": universe_count < 400,
            "monthly_universe_health_pass": universe_count >= 400,
            "r1000_base_count": universe_count,
            "min_r1000_base": 400,
            "blockers": [] if universe_count >= 400 else ["scored_r1000_base_below_floor"],
        },
    )
    write_json(
        root / "user_current" / "summary.json",
        {
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "canonical_production_sync": False,
            "human_approval_required": True,
            "valid_for_production": False,
            "production_promotion_allowed": False,
            "recommendation_status": "REVIEW_ONLY",
        },
    )
    (root / "user_current").mkdir(parents=True, exist_ok=True)
    (root / "user_current" / "01_current_holdings.csv").write_text(
        "portfolio,ticker,current_weight\nmain,AAA,0.10\n",
        encoding="utf-8",
    )
    (root / "user_current" / "02_target_weights.csv").write_text(
        "portfolio,ticker,target_weight\nmain,AAA,0.10\n",
        encoding="utf-8",
    )
    (root / "user_current" / "03_order_preview.csv").write_text(
        "portfolio,ticker,action\nmain,AAA,HOLD\n",
        encoding="utf-8",
    )
    write_json(
        root / "user_current" / "08_rebalance_decision.json",
        {
            "review_only": True,
            "canonical_production_sync": False,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "human_approval_required": True,
        },
    )
    write_json(
        root / "user_current" / "09_daily_output_contract_summary.json",
        {
            "snapshot_contract_pass": daily_snapshot_pass,
            "current_snapshot_used_for_order_preview": daily_snapshot_pass,
            "review_only": True,
            "canonical_production_sync": False,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "human_approval_required": True,
        },
    )
    write_json(
        root / "cash_reentry_quality" / "summary.json",
        {
            "status": "completed",
            "cash_trap_flag": cash_trap_rows > 0,
            "cash_trap_rows": cash_trap_rows,
        },
    )
    write_json(
        root / "pre_broker_substrate_gate" / "summary.json",
        {
            "schema_version": "pre-broker-substrate-gate-v1",
            "status": "pass",
            "broker_replay_allowed": True,
            "production_mutation_allowed": False,
            "live_trading_allowed": False,
            "promotion_allowed": False,
            "blockers": [],
        },
    )


def test_clean_7y_research_ready_even_if_not_production_valid() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root)
        payload = classify_clean_7y_readiness(root)
        assert payload["status"] == READY, payload
        assert payload["review_only"] is True, payload
        assert payload["canonical_production_sync"] is False, payload
        assert payload["promotion_allowed"] is False, payload
        assert payload["ready_for_alpha_plane_ab_research"] is True, payload
        assert "official_promotion" in payload["blocked_uses"], payload
        assert payload["checks"]["broker_window_years_min_7"] is True, payload
        assert payload["checks"]["data_readiness_policy_replay_ready"] is True, payload


def test_clean_7y_readiness_honors_external_user_current_dir() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root)
        external = root / "external_user_current"
        (root / "user_current").rename(external)

        payload = classify_clean_7y_readiness(root, user_current_dir=external)
        assert payload["status"] == READY, payload
        assert payload["ready_for_alpha_plane_ab_research"] is True, payload
        assert payload["source_files"]["daily_snapshot_contract"].startswith(str(external)), payload


def test_dirty_7y_blocked_data_or_starved_universe_is_not_ready() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root, data_ready=False, universe_count=259)
        payload = classify_clean_7y_readiness(root)
        assert payload["status"] == "not_ready", payload
        assert payload["ready_for_alpha_plane_ab_research"] is False, payload
        assert "data_readiness_policy_replay_ready" in payload["blockers"], payload
        assert any("universe" in item for item in payload["blockers"]), payload
        assert "alpha_plane_ab_research" in payload["blocked_uses"], payload


def test_pre_broker_recovery_surfaces_when_clean_7y_blocked() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root)
        write_json(
            root / "pre_broker_substrate_gate" / "summary.json",
            {
                "schema_version": "pre-broker-substrate-gate-v1",
                "status": "blocked",
                "broker_replay_allowed": False,
                "production_mutation_allowed": False,
                "live_trading_allowed": False,
                "promotion_allowed": False,
                "blockers": ["universe_health_promotion_not_allowed"],
                "recovery": {
                    "fallback_available": True,
                    "recommended_recovery_source": "committed_static_IWB_seed",
                    "recommended_recovery_reason": "static seed is available above floor",
                    "recovery_action": "repair_universe_from_fallback",
                },
            },
        )
        payload = classify_clean_7y_readiness(root)
        assert payload["status"] == "not_ready", payload
        assert "pre_broker_substrate_gate_blocked" in payload["blockers"], payload
        assert payload["pre_broker_substrate_gate_pass"] is False, payload
        assert payload["evidence_recovery"]["recommended_recovery_source"] == "committed_static_IWB_seed", payload
        assert payload["evidence_recovery"]["recovery_action"] == "repair_universe_from_fallback", payload
        assert payload["source_summaries"]["recommended_recovery_source"] == "committed_static_IWB_seed", payload
        out = root / "out"
        write_outputs(payload, out)
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "## Recovery" in report
        assert "recommended_recovery_source: `committed_static_IWB_seed`" in report


def test_cash_trap_or_missing_snapshot_blocks_clean_7y_research() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root, daily_snapshot_pass=False, cash_trap_rows=2)
        payload = classify_clean_7y_readiness(root)
        assert payload["status"] == "not_ready", payload
        assert "daily_snapshot_contract_pass" in payload["blockers"], payload
        assert "cash_trap_false" in payload["blockers"], payload


def test_wrong_metric_mode_blocks_research_readiness() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root, metric_mode="legacy_weight_level")
        payload = classify_clean_7y_readiness(root)
        assert payload["status"] == "not_ready", payload
        assert "broker_ledger_next_close" in payload["blockers"], payload
        assert "official_promotion" in payload["blocked_uses"], payload


def test_outputs_are_written() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_base(root)
        payload = classify_clean_7y_readiness(root)
        out = root / "out"
        write_outputs(payload, out)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["schema_version"] == "clean-7y-research-readiness-v1", summary
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "Clean 7Y Research Readiness" in report
        assert "official_promotion" in report


if __name__ == "__main__":
    test_clean_7y_research_ready_even_if_not_production_valid()
    test_clean_7y_readiness_honors_external_user_current_dir()
    test_dirty_7y_blocked_data_or_starved_universe_is_not_ready()
    test_pre_broker_recovery_surfaces_when_clean_7y_blocked()
    test_cash_trap_or_missing_snapshot_blocks_clean_7y_research()
    test_wrong_metric_mode_blocks_research_readiness()
    test_outputs_are_written()
    print("clean_7y_research_readiness_smoke: PASS")
