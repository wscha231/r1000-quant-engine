#!/usr/bin/env python3
"""Smoke tests for the integrated system acceptance audit."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_system_acceptance_audit import run  # noqa: E402


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def broker_metrics(*, years: float, cagr: float, max_dd: float, kind: str) -> dict:
    return {
        "status": "completed",
        "metric_mode": "broker_ledger_next_close",
        "valid_for_production": True,
        "start_date": "2018-06-01" if years >= 8.0 else "2019-06-03",
        "end_date": "2026-06-12",
        "years": years,
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": 1.6,
        "avg_cash_weight": 0.25,
        "fill_mode": "next_close",
        "integer_shares": True,
        "cost_bps_per_side": 25.0,
        "max_fill_lag_days": 7,
        "target_book": f"outputs/reports/operating_{kind}_target_book.csv",
        "windows": {
            "is": {"cagr": 0.32 if kind == "concentrated" else 0.27, "max_dd": max_dd},
            "oos": {"cagr": 0.40, "max_dd": -0.20},
            "oos2": {"cagr": 0.35, "max_dd": -0.22},
        },
    }


def seed_common_sidecars(root: Path) -> None:
    write_json(root / "data_readiness" / "summary.json", {"status": "ok", "ready_for_policy_replay": True, "blockers": []})
    write_json(
        root / "eight_year_backtest_readiness" / "summary.json",
        {"status": "official_eight_year_ready", "official_window_ready": True, "blockers": []},
    )
    write_json(root / "era_leadership" / "summary.json", {"status": "completed", "feature_count": 3, "row_count": 100})
    write_json(
        root / "era_aware_scoring_challenger" / "summary.json",
        {
            "status": "completed",
            "production_activation_allowed": False,
            "rebalance_date_count": 96,
            "goal_verdicts": {"all_strengthened_pass": False},
        },
    )
    write_json(
        root / "daily_crisis_monitor" / "summary.json",
        {"state": "GREEN", "raw_state": "GREEN", "auto_trade_allowed": False, "paper_actions_only": True},
    )
    write_json(
        root / "crisis_paper_order_bridge" / "summary.json",
        {"status": "completed", "paper_only": True, "approval_required": True},
    )
    write_json(
        root / "self_correction_router" / "router_queue.json",
        {"production_mutation_allowed": False, "latest_focus": "main:flat_alpha_invested", "repeat_confirmed": True, "queued_experiments": [{}], "dispatch_payload_count": 1},
    )
    write_json(root / "portfolio_system_guard" / "error_check.json", {"hard_error_count": 0, "checks": [{"passed": True}]})


def seed_account(root: Path, *, years: float, concentrated_pass: bool) -> None:
    main = broker_metrics(years=years, cagr=0.35, max_dd=-0.24, kind="main")
    conc = broker_metrics(years=years, cagr=0.52 if concentrated_pass else 0.44, max_dd=-0.26, kind="concentrated")
    write_json(root / "broker_replay" / "main" / "metrics.json", main)
    write_json(root / "broker_replay" / "concentrated" / "metrics.json", conc)
    write_json(
        root / "account_evaluation" / "official_metrics.json",
        {
            "official_metric_mode": "broker_ledger_next_close",
            "production_target_pass": concentrated_pass,
            "strengthened_pass": concentrated_pass and years >= 8.0,
            "portfolios": {
                "main": {**main, "official_metric_mode": "broker_ledger_next_close", "target_pass": True, "strengthened_pass": True},
                "concentrated": {
                    **conc,
                    "official_metric_mode": "broker_ledger_next_close",
                    "target_pass": concentrated_pass,
                    "strengthened_pass": concentrated_pass,
                    "tier2_failing": [] if concentrated_pass else ["is_cagr_min", "oos_is_cagr_ratio_max"],
                },
            },
        },
    )


def test_acceptance_audit_reports_not_ready_for_short_concentrated_fail() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=7.02, concentrated_pass=False)
        write_json(
            latest / "eight_year_backtest_readiness" / "summary.json",
            {"status": "not_ready", "official_window_ready": False, "blockers": ["broker-ledger official replay does not yet cover 8 years"]},
        )
        out = Path(tmp) / "audit"
        payload = run(
            Namespace(
                latest_run=str(latest),
                output_dir=str(out),
                ref="codex/self-sustaining-loop-20260615",
                repo="wscha231/r1000-quant-engine",
            )
        )
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "goal_contract_main30_conc50_mdd" in blockers
        assert "eight_year_broker_ledger_window" in blockers
        assert payload["workflow_dispatch_payload_count"] == 6
        dispatches = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert [row["plan_id"] for row in dispatches[:2]] == [
            "bootstrap_free_data_for_8y_window",
            "full_rebuild_8y_official_after_data_bootstrap",
        ]
        assert [row["plan_id"] for row in dispatches[2:]] == [
            "ab_conc_bull_floor_stock_min",
            "ab_conc_continuation_winner_relaxation",
            "ab_conc_theme_leadership_boost",
            "ab_conc_concentration_cap_relaxation",
        ]
        assert dispatches[0]["workflow_id"] == "free_data_lake_bootstrap.yml"
        assert dispatches[0]["inputs"]["price_mode"] == "target_books"
        assert dispatches[0]["inputs"]["run_proxy_replay"] == "true"
        assert dispatches[1]["workflow_id"] == "full_rebuild_manual.yml"
        assert dispatches[1]["inputs"]["backtest_years"] == "8"
        assert dispatches[1]["inputs"]["portfolio_policy"] == "alphaops_vnext_production"
        for row in dispatches[2:]:
            assert row["workflow_id"] == "full_rebuild_manual.yml"
            assert row["source_portfolio"] == "concentrated"
            assert row["source_requirement_id"] == "goal_contract_main30_conc50_mdd"
            assert row["depends_on_plan_ids"] == ["full_rebuild_8y_official_after_data_bootstrap"]
            assert row["inputs"]["backtest_years"] == "8"
            assert row["inputs"]["skip_collector"] == "true"
            assert row["inputs"]["portfolio_policy"] == "alphaops_vnext_production"
            assert "PHASE_" in row["inputs"]["experiment_env_json"]
        assert all(row["requires_user_approval"] for row in dispatches)
        assert not any(row["production_mutation_allowed"] for row in dispatches)
        commands = (out / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")
        assert "gh workflow run free_data_lake_bootstrap.yml" in commands
        assert "gh workflow run full_rebuild_manual.yml" in commands
        assert "cache_key_suffix=ab_conc_bull_floor_stock_min" in commands
        assert payload["production_activation_allowed"] is False
        saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert saved["live_trading_allowed"] is False


def test_acceptance_audit_queues_concentrated_ab_when_8y_ready_but_goal_short() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=False)
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        assert payload["workflow_dispatch_payload_count"] == 4
        dispatches = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert [row["plan_id"] for row in dispatches] == [
            "ab_conc_bull_floor_stock_min",
            "ab_conc_continuation_winner_relaxation",
            "ab_conc_theme_leadership_boost",
            "ab_conc_concentration_cap_relaxation",
        ]
        assert all(row["depends_on_plan_ids"] == [] for row in dispatches)
        assert all(row["source_evidence"]["target_pass"] is False for row in dispatches)
        assert all(row["source_evidence"]["tier2_failing"] for row in dispatches)


def test_acceptance_audit_passes_when_evidence_contract_is_complete() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "production_evidence_ready"
        assert payload["hard_blocker_count"] == 0
        assert payload["warning_count"] == 0
        assert payload["workflow_dispatch_payload_count"] == 0
        dispatches = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert dispatches == []
        ids = {row["requirement_id"]: row["status"] for row in payload["requirements"]}
        assert ids["official_broker_ledger_metrics"] == "pass"
        assert ids["daily_crisis_paper_action_wire"] == "pass"
        adr = next(row for row in payload["requirements"] if row["requirement_id"] == "adr_universe_review_automation")
        assert adr["status"] == "pass"
        assert adr["evidence"]["updater_exists"] is True
        assert adr["evidence"]["updater_requires_approval_token"] is True
        assert adr["evidence"]["updater_blocks_placeholders"] is True
        assert (out / "report.md").exists()


if __name__ == "__main__":
    test_acceptance_audit_reports_not_ready_for_short_concentrated_fail()
    test_acceptance_audit_queues_concentrated_ab_when_8y_ready_but_goal_short()
    test_acceptance_audit_passes_when_evidence_contract_is_complete()
    print("system_acceptance_audit_smoke: PASS")
