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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
        root / "cash_contract" / "cash_contract_summary.json",
        {
            "cash_contract_pass": True,
            "mean_drift_limit_pp": 2.0,
            "max_drift_limit_pp": 5.0,
            "portfolios": {
                portfolio: {
                    "status": "passed",
                    "cash_contract_pass": True,
                    "target": {
                        "status": "completed",
                        "target_cash_contract_pass": True,
                        "missing_explicit_cash_date_count": 0,
                        "invalid_total_weight_date_count": 0,
                        "negative_cash_date_count": 0,
                    },
                    "broker": {"status": "completed", "avg_broker_cash_weight": 0.25},
                    "drift": {
                        "status": "completed",
                        "cash_drift_pass": True,
                        "rebalance_day_cash_drift_pass": True,
                        "month_mean_cash_drift_pass": True,
                        "rebalance_day_mean_cash_drift_pp": 0.10,
                        "month_mean_cash_drift_pp": 0.15,
                    },
                }
                for portfolio in ("main", "concentrated")
            },
        },
    )
    write_json(
        root / "eight_year_backtest_readiness" / "summary.json",
        {"status": "official_eight_year_ready", "official_window_ready": True, "blockers": []},
    )
    write_json(
        root / "oos_lock" / "summary.json",
        {
            "status": "pass",
            "lock_pass": True,
            "production_activation_allowed": False,
            "config": {"oos_start": "2024-07-01"},
            "failures": {},
            "portfolios": {
                "main": {
                    "status": "pass",
                    "cagr_is": 0.27,
                    "cagr_oos": 0.31,
                    "oos_degradation_pp": -4.0,
                    "oos_is_cagr_ratio": 1.15,
                    "max_allowed_degradation_pp": 5.0,
                    "max_oos_is_cagr_ratio": 3.0,
                    "oos_trading_days": 490,
                },
                "concentrated": {
                    "status": "pass",
                    "cagr_is": 0.32,
                    "cagr_oos": 0.38,
                    "oos_degradation_pp": -6.0,
                    "oos_is_cagr_ratio": 1.19,
                    "max_allowed_degradation_pp": 6.0,
                    "max_oos_is_cagr_ratio": 3.0,
                    "oos_trading_days": 490,
                },
            },
        },
    )
    write_json(root / "era_leadership" / "summary.json", {"status": "completed", "feature_count": 3, "row_count": 100})
    write_text(root / "era_leadership" / "era_leaders.csv", "era,ticker,contribution\n2023_2024_ai_bull,AAA,0.125\n")
    write_json(
        root / "is_attribution" / "summary.json",
        {
            portfolio: {
                "portfolio": portfolio,
                "start_date": "2018-06-01",
                "end_date": "2026-06-12",
                "full_cagr": 0.35 if portfolio == "main" else 0.52,
                "is_cagr": 0.27 if portfolio == "main" else 0.32,
                "oos_cagr": 0.40,
                "oos_is_ratio": 1.48 if portfolio == "main" else 1.25,
                "leak_year_tags": {"2019": "healthy", "2022": "mixed"},
                "structural_underinvestment_bull_years": [],
            }
            for portfolio in ("main", "concentrated")
        },
    )
    for portfolio in ("main", "concentrated"):
        write_text(
            root / "is_attribution" / f"{portfolio}_yearly.csv",
            "year,year_return,year_cagr,max_dd_in_year,avg_cash_weight,leak_tag\n"
            "2019,0.20,0.24,-0.08,0.20,healthy\n"
            "2022,-0.05,-0.05,-0.14,0.35,mixed\n",
        )
        write_json(
            root / "trade_attribution" / portfolio / "findings.json",
            {
                "status": "completed",
                "production_activation_allowed": False,
                "mdd_window": {
                    "peak_date": "2022-01-03",
                    "trough_date": "2022-10-14",
                    "top_position_pnl_contributors": [{"ticker": "AAA", "pnl_usd": -1250.0}],
                },
            },
        )
        write_text(root / "trade_attribution" / portfolio / "mdd_position_pnl_by_ticker.csv", "ticker,pnl_usd\nAAA,-1250\n")
        write_json(
            root / "mdd_cash_overlay_research" / portfolio / "metrics.json",
            {
                "status": "completed",
                "base_metrics": {
                    "max_dd_peak_date": "2022-01-03",
                    "max_dd_trough_date": "2022-10-14",
                    "max_dd": -0.20,
                },
                "production_activation_allowed": False,
                "research_only": True,
            },
        )
        write_text(
            root / "mdd_cash_overlay_research" / portfolio / "mdd_holdings_contributors.csv",
            "ticker,peak_market_value_usd,peak_weight,trough_market_value_usd,trough_weight,peak_to_trough_value_delta_usd\n"
            "AAA,10000,0.10,8000,0.08,-2000\n",
        )
    write_json(root / "mdd_cash_overlay_research" / "summary.json", {"status": "completed", "portfolios": {"main": {}, "concentrated": {}}})
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
        {
            "state": "GREEN",
            "raw_state": "GREEN",
            "auto_trade_allowed": False,
            "paper_actions_only": True,
            "allowed_action_types": ["raise_cash", "trim_position", "block_new_buys", "reentry_watch", "no_op"],
            "paper_action_candidates": [{"action_type": "no_op", "priority": 0}],
        },
    )
    write_json(
        root / "crisis_paper_order_bridge" / "summary.json",
        {
            "status": "completed",
            "auto_trade_allowed": False,
            "paper_only": True,
            "approval_required": True,
            "paper_action_types": ["no_op"],
            "portfolios": [
                {"portfolio": "main", "auto_trade_allowed": False, "paper_only": True, "approval_required": True},
                {"portfolio": "concentrated", "auto_trade_allowed": False, "paper_only": True, "approval_required": True},
            ],
        },
    )
    write_json(
        root / "self_correction_router" / "router_queue.json",
        {
            "production_mutation_allowed": False,
            "latest_focus": "main:flat_alpha_invested",
            "repeat_confirmed": True,
            "queued_experiments": [
                {
                    "experiment_id": "main_era_aware_scoring_challenger_review",
                    "dispatch_mode": "workflow_dispatch_payload_only",
                    "requires_user_approval": True,
                    "production_mutation_allowed": False,
                }
            ],
            "dispatch_payload_count": 1,
        },
    )
    write_json(
        root / "self_correction_router" / "workflow_dispatch_payloads.json",
        [
            {
                "plan_id": "main_era_aware_scoring_challenger_review",
                "experiment_id": "main_era_aware_scoring_challenger_review",
                "workflow_id": "full_rebuild_manual.yml",
                "ref": "master",
                "requires_user_approval": True,
                "production_mutation_allowed": False,
                "inputs": {
                    "backtest_years": "8",
                    "portfolio_policy": "alphaops_vnext_production",
                    "cache_key_suffix": "main_era_aware_scoring_challenger_review",
                    "experiment_env_json": "{\"PHASE_ERA_AWARE_SCORING_CHALLENGER_REVIEW\": \"1\"}",
                },
            }
        ],
    )
    write_json(
        root / "review_dispatcher_self_correction" / "summary.json",
        {
            "schema_version": "review-dispatcher-v1",
            "status": "dry_run_ready",
            "execute_requested": False,
            "repo": "wscha231/r1000-quant-engine",
            "selected_count": 1,
            "ready_count": 1,
            "blocked_count": 0,
            "dispatched_count": 0,
            "plan_rows": [
                {
                    "id": "main_era_aware_scoring_challenger_review",
                    "status": "ready",
                    "workflow_id": "full_rebuild_manual.yml",
                    "requires_user_approval": True,
                    "production_mutation_allowed": False,
                    "errors": [],
                }
            ],
        },
    )
    write_json(
        root / "adr_candidates" / "adr_universe_update_manifest.json",
        {
            "schema_version": "adr-universe-update-manifest-v1",
            "production_mutation_allowed": False,
            "manual_review_required": True,
            "proposed_add_count": 0,
            "proposed_additions": [],
            "review_steps": [],
        },
    )
    for portfolio in ("main", "concentrated"):
        preview = root / "account_ledger_preview" / portfolio
        write_json(
            preview / "preview_metrics.json",
            {
                "status": "completed",
                "schema_version": "account-ledger-preview-v1",
                "portfolio_kind": portfolio,
                "preview_semantics": "order_preview_not_operating_snapshot",
                "account_source_kind": "simulated_broker_replay",
                "target_source_kind": "sleeve_model_target",
                "account_state": f"outputs/broker_replay/{portfolio}/account_state_latest.json",
                "target": f"outputs/reports/operating_{portfolio}_target_book.csv",
                "cost_bps_per_side": 25.0,
                "integer_shares": True,
                "blocked_order_count": 0,
                "ready_order_count": 1,
                "order_count": 1,
            },
        )
        write_json(preview / "order_batch_manifest.json", {"schema_version": "account-ledger-preview-order-batch-v1", "order_count": 1})
        write_text(preview / "orders_preview.csv", "ticker,side,quantity,status,client_order_id\nAAA,BUY,1,ready,r1k-test\n")
        write_text(preview / "positions_current.csv", "ticker,shares,price,price_date\nAAA,0,100,2026-06-12\n")
        write_text(preview / "projected_positions_after_orders.csv", "ticker,projected_weight\nAAA,0.1\nCASH,0.9\n")
    write_json(root / "live_trading_safety" / "safety_audit_summary.json", {"status": "pass", "error_count": 0, "warning_count": 0})
    write_json(
        root / "live_trading_risk_controls" / "risk_controls_summary.json",
        {
            "status": "pass",
            "account_mode": "simulated",
            "strict_live": False,
            "error_count": 0,
            "warning_count": 0,
            "manifest_order_count": 2,
            "fill_template_order_count": 2,
        },
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
        assert payload["workflow_dispatch_payload_count"] == 7
        dispatches = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert [row["plan_id"] for row in dispatches[:2]] == [
            "bootstrap_free_data_for_8y_window",
            "full_rebuild_8y_official_after_data_bootstrap",
        ]
        assert dispatches[0].get("depends_on_plan_ids", []) == []
        assert dispatches[1]["depends_on_plan_ids"] == ["bootstrap_free_data_for_8y_window"]
        assert [row["plan_id"] for row in dispatches[2:]] == [
            "ab_conc_continuation_winner_relaxation",
            "ab_conc_bull_floor_stock_min",
            "ab_conc_reentry_quality",
            "ab_conc_theme_leadership_boost",
            "ab_conc_concentration_cap_relaxation",
        ]
        assert [row["experiment_id"] for row in dispatches[2:]] == [
            "conc_continuation_winner_relaxation",
            "conc_bull_floor_stock_min",
            "conc_reentry_quality",
            "conc_theme_leadership_boost",
            "conc_concentration_cap_relaxation",
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
            assert row["payload_hash"]
            assert row["post_run_review"]["tool"] == "tools/run_ab_result_verifier.py"
            assert row["post_run_review"]["experiment_id"] == row["experiment_id"]
            assert row["post_run_review"]["payload_hash"] == row["payload_hash"]
            assert row["post_run_review"]["dispatch_run_id"] == row["plan_id"]
            assert "--experiment-id" in row["post_run_review"]["verifier_args"]
            assert "--payload-hash" in row["post_run_review"]["verifier_args"]
            assert row["post_run_review"]["production_mutation_allowed"] is False
        assert all(row["requires_user_approval"] for row in dispatches)
        assert not any(row["production_mutation_allowed"] for row in dispatches)
        commands = (out / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")
        assert "gh workflow run free_data_lake_bootstrap.yml" in commands
        assert "blocked until completed_plan_id: bootstrap_free_data_for_8y_window" in commands
        assert "blocked until completed_plan_id: full_rebuild_8y_official_after_data_bootstrap" in commands
        assert "# gh workflow run full_rebuild_manual.yml" in commands
        assert "\ngh workflow run full_rebuild_manual.yml" not in commands
        assert "cache_key_suffix=ab_conc_continuation_winner_relaxation" in commands
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "| Plan | Workflow | Dependencies | Reason |" in report
        assert "full_rebuild_8y_official_after_data_bootstrap | full_rebuild_manual.yml | bootstrap_free_data_for_8y_window" in report
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
        assert payload["workflow_dispatch_payload_count"] == 5
        dispatches = json.loads((out / "workflow_dispatch_payloads.json").read_text(encoding="utf-8"))
        assert [row["plan_id"] for row in dispatches] == [
            "ab_conc_continuation_winner_relaxation",
            "ab_conc_bull_floor_stock_min",
            "ab_conc_reentry_quality",
            "ab_conc_theme_leadership_boost",
            "ab_conc_concentration_cap_relaxation",
        ]
        assert all(row["depends_on_plan_ids"] == [] for row in dispatches)
        commands = (out / "workflow_dispatch_commands.sh").read_text(encoding="utf-8")
        assert "blocked until completed_plan_id" not in commands
        assert "\ngh workflow run full_rebuild_manual.yml" in commands
        assert all(row["source_evidence"]["target_pass"] is False for row in dispatches)
        assert all(row["source_evidence"]["tier2_failing"] for row in dispatches)
        assert all(row["post_run_review"]["tool"] == "tools/run_ab_result_verifier.py" for row in dispatches)
        assert all(row["post_run_review"]["experiment_id"] == row["experiment_id"] for row in dispatches)
        assert all(row["post_run_review"]["payload_hash"] == row["payload_hash"] for row in dispatches)


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
        assert ids["oos_holdout_lock"] == "pass"
        assert ids["target_book_broker_cash_contract"] == "pass"
        assert ids["attribution_package_year_mdd_name"] == "pass"
        assert ids["operational_order_preview_safety_bridge"] == "pass"
        assert ids["daily_crisis_paper_action_wire"] == "pass"
        assert ids["self_correction_router_queue"] == "pass"
        cash_contract = next(row for row in payload["requirements"] if row["requirement_id"] == "target_book_broker_cash_contract")
        assert cash_contract["evidence"]["portfolios"]["main"]["missing_explicit_cash_date_count"] == 0
        assert cash_contract["evidence"]["portfolios"]["concentrated"]["cash_drift_pass"] is True
        attribution = next(row for row in payload["requirements"] if row["requirement_id"] == "attribution_package_year_mdd_name")
        assert attribution["evidence"]["era_leader_rows"] == 1
        assert attribution["evidence"]["portfolios"]["main"]["trade_mdd_contributor_count"] == 1
        assert attribution["evidence"]["portfolios"]["concentrated"]["mdd_trough_holding_rows"] == 1
        bridge = next(row for row in payload["requirements"] if row["requirement_id"] == "operational_order_preview_safety_bridge")
        assert bridge["evidence"]["live_order_submission_allowed"] is False
        assert bridge["evidence"]["risk_controls_status"] == "pass"
        assert bridge["evidence"]["previews"]["main"]["order_batch_manifest_exists"] is True
        crisis = next(row for row in payload["requirements"] if row["requirement_id"] == "daily_crisis_paper_action_wire")
        assert crisis["evidence"]["monitor_action_types"] == ["no_op"]
        assert crisis["evidence"]["monitor_unknown_actions"] == []
        assert crisis["evidence"]["bridge_action_types"] == ["no_op"]
        assert crisis["evidence"]["unsafe_portfolio_previews"] == []
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["evidence"]["dispatcher_summary_exists"] is True
        assert self_correction["evidence"]["dispatcher_execute_requested"] is False
        assert self_correction["evidence"]["dispatcher_dispatched_count"] == 0
        assert self_correction["evidence"]["dispatcher_selected_count"] == 1
        adr = next(row for row in payload["requirements"] if row["requirement_id"] == "adr_universe_review_automation")
        assert adr["status"] == "pass"
        assert adr["evidence"]["updater_exists"] is True
        assert adr["evidence"]["updater_requires_approval_token"] is True
        assert adr["evidence"]["updater_blocks_placeholders"] is True
        assert (out / "report.md").exists()


def test_acceptance_audit_blocks_when_operational_order_bridge_missing() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        (latest / "live_trading_risk_controls" / "risk_controls_summary.json").unlink()
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "operational_order_preview_safety_bridge" in blockers
        bridge = next(row for row in payload["requirements"] if row["requirement_id"] == "operational_order_preview_safety_bridge")
        assert "live_trading_risk_controls:not_pass" in bridge["evidence"]["failures"]


def test_acceptance_audit_blocks_when_cash_contract_fails() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        cash_path = latest / "cash_contract" / "cash_contract_summary.json"
        cash = json.loads(cash_path.read_text(encoding="utf-8"))
        cash["cash_contract_pass"] = False
        cash["portfolios"]["concentrated"]["cash_contract_pass"] = False
        cash["portfolios"]["concentrated"]["target"]["target_cash_contract_pass"] = False
        cash["portfolios"]["concentrated"]["target"]["missing_explicit_cash_date_count"] = 1
        cash_path.write_text(json.dumps(cash, indent=2, sort_keys=True), encoding="utf-8")
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "target_book_broker_cash_contract" in blockers
        cash_contract = next(row for row in payload["requirements"] if row["requirement_id"] == "target_book_broker_cash_contract")
        assert "overall_cash_contract_not_pass" in cash_contract["evidence"]["failures"]
        assert "concentrated:target_cash_contract_not_pass" in cash_contract["evidence"]["failures"]
        assert cash_contract["evidence"]["portfolios"]["concentrated"]["missing_explicit_cash_date_count"] == 1


def test_acceptance_audit_blocks_when_oos_lock_fails() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        write_json(
            latest / "oos_lock" / "summary.json",
            {
                "status": "fail",
                "lock_pass": False,
                "config": {"oos_start": "2024-07-01"},
                "failures": {"concentrated": ["oos_cagr_degradation_above_lock"]},
                "portfolios": {
                    "concentrated": {
                        "status": "fail",
                        "cagr_is": 0.45,
                        "cagr_oos": 0.25,
                        "oos_degradation_pp": 20.0,
                        "max_allowed_degradation_pp": 6.0,
                        "oos_trading_days": 490,
                    }
                },
            },
        )
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "oos_holdout_lock" in blockers
        oos = next(row for row in payload["requirements"] if row["requirement_id"] == "oos_holdout_lock")
        assert oos["evidence"]["failures"]["concentrated"] == ["oos_cagr_degradation_above_lock"]


def test_acceptance_audit_blocks_unsafe_crisis_action_types() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        monitor_path = latest / "daily_crisis_monitor" / "summary.json"
        monitor = json.loads(monitor_path.read_text(encoding="utf-8"))
        monitor["paper_action_candidates"] = [{"action_type": "market_sell_all", "priority": 0}]
        monitor_path.write_text(json.dumps(monitor, indent=2, sort_keys=True), encoding="utf-8")
        bridge_path = latest / "crisis_paper_order_bridge" / "summary.json"
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
        bridge["paper_action_types"] = ["market_sell_all"]
        bridge_path.write_text(json.dumps(bridge, indent=2, sort_keys=True), encoding="utf-8")
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "daily_crisis_paper_action_wire" in blockers
        crisis = next(row for row in payload["requirements"] if row["requirement_id"] == "daily_crisis_paper_action_wire")
        assert crisis["status"] == "fail"
        assert crisis["evidence"]["monitor_unknown_actions"] == ["market_sell_all"]
        assert crisis["evidence"]["bridge_unknown_actions"] == ["market_sell_all"]


def test_acceptance_audit_blocks_unsafe_crisis_portfolio_preview_flags() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        bridge_path = latest / "crisis_paper_order_bridge" / "summary.json"
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
        bridge["portfolios"][0]["approval_required"] = False
        bridge_path.write_text(json.dumps(bridge, indent=2, sort_keys=True), encoding="utf-8")
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "daily_crisis_paper_action_wire" in blockers
        crisis = next(row for row in payload["requirements"] if row["requirement_id"] == "daily_crisis_paper_action_wire")
        assert crisis["status"] == "fail"
        assert crisis["evidence"]["unsafe_portfolio_previews"] == ["main"]


def test_acceptance_audit_surfaces_oos_manual_review_tasks() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        write_json(
            latest / "oos_lock" / "summary.json",
            {
                "status": "fail",
                "lock_pass": False,
                "config": {"oos_start": "2024-07-01"},
                "failures": {"concentrated": ["oos_is_cagr_ratio_above_lock"]},
                "portfolios": {
                    "concentrated": {
                        "status": "fail",
                        "cagr_is": 0.22,
                        "cagr_oos": 1.20,
                        "oos_is_cagr_ratio": 5.45,
                        "max_oos_is_cagr_ratio": 3.0,
                        "oos_trading_days": 490,
                    }
                },
            },
        )
        write_json(
            latest / "self_correction_router" / "router_queue.json",
            {
                "production_mutation_allowed": False,
                "latest_focus": "concentrated:structural_underinvestment_bull",
                "repeat_confirmed": True,
                "queued_experiments": [],
                "dispatch_payload_count": 0,
                "oos_robustness": {"status": "fail", "queued_review_task_count": 1},
                "queued_review_tasks": [
                    {
                        "task_id": "concentrated_oos_lottery_era_name_review",
                        "source": "oos_lock",
                        "portfolio": "concentrated",
                        "failure": "oos_is_cagr_ratio_above_lock",
                        "description": "review OOS lottery risk",
                        "next_action": "Compare IS/OOS top-name contribution and era buckets.",
                        "review_artifacts": ["oos_lock/report.md", "era_leadership/summary.json"],
                        "dispatch_mode": "manual_review_no_workflow_dispatch",
                        "requires_user_approval": True,
                        "production_mutation_allowed": False,
                        "metrics": {"oos_is_cagr_ratio": 5.45},
                    }
                ],
            },
        )
        write_json(latest / "self_correction_router" / "workflow_dispatch_payloads.json", [])
        write_json(
            latest / "review_dispatcher_self_correction" / "summary.json",
            {
                "schema_version": "review-dispatcher-v1",
                "status": "dry_run_ready",
                "execute_requested": False,
                "selected_count": 0,
                "ready_count": 0,
                "blocked_count": 0,
                "dispatched_count": 0,
                "plan_rows": [],
            },
        )
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        assert payload["manual_review_task_count"] == 1
        task = payload["manual_review_tasks"][0]
        assert task["task_id"] == "concentrated_oos_lottery_era_name_review"
        assert task["dispatch_mode"] == "manual_review_no_workflow_dispatch"
        assert task["production_mutation_allowed"] is False
        assert json.loads((out / "manual_review_tasks.json").read_text(encoding="utf-8"))[0]["failure"] == "oos_is_cagr_ratio_above_lock"
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "## Manual Review Tasks" in report
        assert "concentrated_oos_lottery_era_name_review" in report
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["status"] == "pass"
        assert self_correction["evidence"]["queued_review_task_count"] == 1
        assert self_correction["evidence"]["unsafe_review_tasks"] == []


def test_acceptance_audit_blocks_missing_self_correction_dispatcher_summary() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        (latest / "review_dispatcher_self_correction" / "summary.json").unlink()
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "self_correction_router_queue" in blockers
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["evidence"]["dispatcher_summary_missing"] is True


def test_acceptance_audit_blocks_executed_self_correction_dispatcher_summary() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        dispatcher_path = latest / "review_dispatcher_self_correction" / "summary.json"
        dispatcher = json.loads(dispatcher_path.read_text(encoding="utf-8"))
        dispatcher["execute_requested"] = True
        dispatcher["dispatched_count"] = 1
        dispatcher_path.write_text(json.dumps(dispatcher, indent=2, sort_keys=True), encoding="utf-8")
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "self_correction_router_queue" in blockers
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["evidence"]["dispatcher_execution_requested"] is True
        assert self_correction["evidence"]["dispatcher_dispatched"] is True


def test_acceptance_audit_blocks_unsafe_self_correction_experiments() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        router_path = latest / "self_correction_router" / "router_queue.json"
        router = json.loads(router_path.read_text(encoding="utf-8"))
        router["queued_experiments"] = [
            {
                "experiment_id": "unsafe_auto_mutation",
                "dispatch_mode": "workflow_dispatch_payload_only",
                "requires_user_approval": True,
                "production_mutation_allowed": True,
            }
        ]
        router_path.write_text(json.dumps(router, indent=2, sort_keys=True), encoding="utf-8")
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "self_correction_router_queue" in blockers
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["status"] == "fail"
        assert self_correction["evidence"]["unsafe_queued_experiments"] == ["unsafe_auto_mutation"]


def test_acceptance_audit_blocks_unsafe_self_correction_payload_file() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        payload_path = latest / "self_correction_router" / "workflow_dispatch_payloads.json"
        payloads = json.loads(payload_path.read_text(encoding="utf-8"))
        payloads[0]["production_mutation_allowed"] = True
        payload_path.write_text(json.dumps(payloads, indent=2, sort_keys=True), encoding="utf-8")
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "self_correction_router_queue" in blockers
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["status"] == "fail"
        assert self_correction["evidence"]["unsafe_dispatch_payloads"] == ["main_era_aware_scoring_challenger_review"]


def test_acceptance_audit_blocks_self_correction_payload_count_mismatch() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        write_json(latest / "self_correction_router" / "workflow_dispatch_payloads.json", [])
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        self_correction = next(row for row in payload["requirements"] if row["requirement_id"] == "self_correction_router_queue")
        assert self_correction["evidence"]["dispatch_payload_count_mismatch"] is True


def test_acceptance_audit_warns_when_adr_candidates_need_review() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        write_json(
            latest / "adr_candidates" / "adr_universe_update_manifest.json",
            {
                "schema_version": "adr-universe-update-manifest-v1",
                "production_mutation_allowed": False,
                "manual_review_required": True,
                "proposed_add_count": 1,
                "proposed_additions": [
                    {
                        "ticker": "TSM",
                        "candidate_status": "review_add",
                        "proposed_entry": {
                            "ticker": "TSM",
                            "name": "",
                            "country": "",
                            "sector": "ADR_REVIEW_REQUIRED",
                            "sub_sector": "",
                            "listed_since": "",
                            "themes": [],
                        },
                    }
                ],
                "review_steps": ["fill metadata before apply"],
            },
        )
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "review_ready_with_warnings"
        adr = next(row for row in payload["requirements"] if row["requirement_id"] == "adr_universe_review_automation")
        assert adr["status"] == "warn"
        assert adr["evidence"]["proposed_add_count"] == 1
        assert adr["evidence"]["placeholder_proposed_count"] == 1
        assert payload["manual_review_task_count"] == 1
        task = payload["manual_review_tasks"][0]
        assert task["task_id"] == "adr_universe_metadata_review"
        assert task["production_mutation_allowed"] is False
        assert task["dispatch_mode"] == "manual_review_no_workflow_dispatch"
        assert task["metrics"]["proposed_tickers"] == ["TSM"]
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "adr_universe_metadata_review" in report


def test_acceptance_audit_blocks_when_attribution_package_missing() -> None:
    with TemporaryDirectory() as tmp:
        latest = Path(tmp) / "latest"
        seed_common_sidecars(latest)
        seed_account(latest, years=8.10, concentrated_pass=True)
        (latest / "trade_attribution" / "concentrated" / "findings.json").unlink()
        out = Path(tmp) / "audit"
        payload = run(Namespace(latest_run=str(latest), output_dir=str(out)))
        assert payload["status"] == "not_ready"
        blockers = {row["requirement_id"] for row in payload["requirements"] if row["hard_blocker"]}
        assert "attribution_package_year_mdd_name" in blockers
        attribution = next(row for row in payload["requirements"] if row["requirement_id"] == "attribution_package_year_mdd_name")
        assert "concentrated:trade_attribution_not_completed" in attribution["evidence"]["failures"]
        assert "concentrated:trade_mdd_window_missing" in attribution["evidence"]["failures"]


if __name__ == "__main__":
    test_acceptance_audit_reports_not_ready_for_short_concentrated_fail()
    test_acceptance_audit_queues_concentrated_ab_when_8y_ready_but_goal_short()
    test_acceptance_audit_passes_when_evidence_contract_is_complete()
    test_acceptance_audit_blocks_when_operational_order_bridge_missing()
    test_acceptance_audit_blocks_when_cash_contract_fails()
    test_acceptance_audit_blocks_when_oos_lock_fails()
    test_acceptance_audit_blocks_unsafe_crisis_action_types()
    test_acceptance_audit_blocks_unsafe_crisis_portfolio_preview_flags()
    test_acceptance_audit_surfaces_oos_manual_review_tasks()
    test_acceptance_audit_blocks_missing_self_correction_dispatcher_summary()
    test_acceptance_audit_blocks_executed_self_correction_dispatcher_summary()
    test_acceptance_audit_blocks_unsafe_self_correction_experiments()
    test_acceptance_audit_blocks_unsafe_self_correction_payload_file()
    test_acceptance_audit_blocks_self_correction_payload_count_mismatch()
    test_acceptance_audit_warns_when_adr_candidates_need_review()
    test_acceptance_audit_blocks_when_attribution_package_missing()
    print("system_acceptance_audit_smoke: PASS")
