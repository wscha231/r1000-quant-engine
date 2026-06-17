#!/usr/bin/env python3
"""Smoke tests for review-only A/B result verifier."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_ab_result_verifier import run  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_run(
    root: Path,
    *,
    cagr: float,
    max_dd: float,
    is_cagr: float,
    years: float,
    target_pass: bool,
    strengthened_pass: bool,
    valid_for_production: bool = True,
    trading_days: int = 2050,
    system_acceptance: bool = True,
    hard_blockers: int = 0,
    production_activation_allowed: bool = False,
    oos_lock: bool = True,
    oos_lock_pass: bool = True,
    oos_is_ratio: float = 1.8,
    data_ready: bool = True,
    universe_count: int = 650,
    cash_trap_false: bool = True,
    clean_7y_ready: bool | None = True,
) -> None:
    row = {
        "portfolio": "concentrated",
        "status": "completed",
        "official_metric_mode": "broker_ledger_next_close",
        "valid_for_production": valid_for_production,
        "target_pass": target_pass,
        "strengthened_pass": strengthened_pass,
        "tier2_failing": [] if strengthened_pass else ["is_cagr_min"],
        "cagr": cagr,
        "cagr_target": 0.50,
        "max_dd": max_dd,
        "max_dd_target": -0.28,
        "is_cagr": is_cagr,
        "oos_cagr": 0.55,
        "sharpe": 1.55,
        "avg_cash_weight": 0.35,
        "years": years,
        "start_date": "2018-06-01",
        "end_date": "2026-06-12",
        "broker_ledger_actual_trading_days": trading_days,
        "broker_ledger_window_gate": {
            "status": "ok" if valid_for_production else "invalid_window",
            "valid": valid_for_production,
            "reasons": [] if valid_for_production else ["broker_ledger_years_below_8"],
            "trading_days_estimate": trading_days,
        },
    }
    write_json(
        root / "account_evaluation" / "official_metrics.json",
        {
            "official_metric_mode": "broker_ledger_next_close",
            "production_target_pass": target_pass,
            "strengthened_pass": strengthened_pass,
            "portfolios": {"concentrated": row},
        },
    )
    write_json(
        root / "broker_replay" / "concentrated" / "metrics.json",
        {
            "status": "completed",
            "metric_mode": "broker_ledger_next_close",
            "valid_for_production": valid_for_production,
            "cagr": cagr,
            "max_dd": max_dd,
            "years": years,
            "days": trading_days,
            "windows": {"is": {"cagr": is_cagr}, "oos": {"cagr": 0.55}},
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
        root / "cash_reentry_quality" / "summary.json",
        {
            "status": "completed",
            "cash_trap_flag": not cash_trap_false,
            "cash_trap_rows": 0 if cash_trap_false else 3,
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
    if clean_7y_ready is not None:
        write_json(
            root / "clean_7y_research_readiness" / "summary.json",
            {
                "status": "clean_7y_research_ready" if clean_7y_ready else "not_ready",
                "ready_for_alpha_plane_ab_research": clean_7y_ready,
                "promotion_allowed": False,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
                "human_approval_required": True,
                "blockers": [] if clean_7y_ready else ["cash_trap_false"],
            },
        )
    write_json(
        root / "is_attribution" / "summary.json",
        {
            "concentrated": {
                "is_cagr": is_cagr,
                "oos_cagr": 0.55,
                "leak_year_tags": {"2021": "healthy"},
                "structural_underinvestment_bull_years": [],
            }
        },
    )
    if system_acceptance:
        effective_blockers = hard_blockers + (0 if oos_lock_pass else 1)
        status = "production_evidence_ready" if effective_blockers == 0 else "not_ready"
        requirements = [
            {
                "requirement_id": "attribution_package_year_mdd_name",
                "status": "pass" if hard_blockers == 0 else "fail",
                "hard_blocker": hard_blockers != 0,
            }
        ]
        if oos_lock:
            requirements.append(
                {
                    "requirement_id": "oos_holdout_lock",
                    "status": "pass" if oos_lock_pass else "fail",
                    "hard_blocker": not oos_lock_pass,
                }
            )
        write_json(
            root / "system_acceptance_audit" / "summary.json",
            {
                "status": status,
                "production_activation_allowed": production_activation_allowed,
                "hard_blocker_count": effective_blockers,
                "requirements": requirements,
            },
        )
    if oos_lock:
        failures = [] if oos_lock_pass else ["oos_is_cagr_ratio_above_lock"]
        write_json(
            root / "oos_lock" / "summary.json",
            {
                "status": "pass" if oos_lock_pass else "fail",
                "lock_pass": oos_lock_pass,
                "hard_blocker_count": 0 if oos_lock_pass else 1,
                "production_activation_allowed": False,
                "config": {"oos_start": "2024-07-01", "max_oos_is_cagr_ratio": 3.0},
                "failures": {} if oos_lock_pass else {"concentrated": failures},
                "portfolios": {
                    "concentrated": {
                        "status": "pass" if oos_lock_pass else "fail",
                        "cagr_is": is_cagr,
                        "cagr_oos": 0.55,
                        "oos_is_cagr_ratio": oos_is_ratio,
                        "max_oos_is_cagr_ratio": 3.0,
                        "failures": failures,
                    }
                },
            },
        )


def args(baseline: Path, candidates: list[Path], out: Path) -> Namespace:
    return Namespace(
        baseline_run=str(baseline),
        candidate_run=[str(path) for path in candidates],
        output_dir=str(out),
        portfolio="concentrated",
        min_cagr_delta_pp=0.0,
        min_is_cagr_delta_pp=0.5,
        max_mdd_regression_pp=1.0,
        allow_missing_evidence=False,
    )


def seed_daily_user_current(root: Path) -> None:
    out = root / "user_current"
    write_json(
        out / "summary.json",
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
    (out / "01_current_holdings.csv").parent.mkdir(parents=True, exist_ok=True)
    (out / "01_current_holdings.csv").write_text("portfolio,ticker,current_weight\nconcentrated,AAA,0.20\n", encoding="utf-8")
    (out / "02_target_weights.csv").write_text("portfolio,ticker,target_weight\nconcentrated,AAA,0.20\n", encoding="utf-8")
    (out / "03_order_preview.csv").write_text("portfolio,ticker,action\nconcentrated,AAA,HOLD\n", encoding="utf-8")
    write_json(
        out / "08_rebalance_decision.json",
        {
            "review_only": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "canonical_production_sync": False,
            "human_approval_required": True,
        },
    )
    write_json(
        out / "09_daily_output_contract_summary.json",
        {
            "review_only": True,
            "current_snapshot_used_for_order_preview": True,
            "live_trading_enabled": False,
            "production_mutation_allowed": False,
            "canonical_production_sync": False,
            "human_approval_required": True,
        },
    )


def test_verifier_marks_clean_candidate_review_promotable() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(candidate, cagr=0.52, max_dd=-0.26, is_cagr=0.31, years=8.10, target_pass=True, strengthened_pass=True)
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "review_candidate_ready"
        assert payload["production_activation_allowed"] is False
        row = payload["candidates"][0]
        assert row["decision"] == "promote_candidate_review_only"
        assert row["review_valid_for_promotion"] is True
        assert row["is_cagr_delta_vs_baseline_pp"] > 8.0
        assert (root / "out" / "candidate_verdicts.csv").exists()


def test_verifier_rejects_is_cagr_regression_even_if_headline_passes() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.51, max_dd=-0.25, is_cagr=0.32, years=8.10, target_pass=True, strengthened_pass=True)
        seed_run(candidate, cagr=0.53, max_dd=-0.25, is_cagr=0.30, years=8.10, target_pass=True, strengthened_pass=True)
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "rejected"
        row = payload["candidates"][0]
        assert row["decision"] == "reject_regression"
        assert any("is_cagr_delta_below_min" in issue for issue in row["issues"])


def test_verifier_measures_clean_short_7y_candidate_without_promotion() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "measured_research_7y"
        row = payload["candidates"][0]
        assert row["decision"] == "measured_research_7y"
        assert row["evidence_tier"] == "1_research_7y"
        assert row["review_valid_for_promotion"] is False
        assert row["production_activation_allowed"] is False
        assert row["ready_for_human_review"] is False
        assert payload["review_valid_candidate_count"] == 0
        assert payload["ready_for_human_review_candidate_count"] == 0
        assert payload["measured_research_7y_candidate_count"] == 1


def test_verifier_marks_clean_7y_operating_candidate_for_human_review_only() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
            cash_trap_false=True,
        )
        seed_daily_user_current(candidate)
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "human_review_candidate_ready"
        assert payload["review_valid_candidate_count"] == 0
        assert payload["ready_for_human_review_candidate_count"] == 1
        assert payload["production_activation_allowed"] is False
        row = payload["candidates"][0]
        assert row["decision"] == "ready_for_human_review"
        assert row["evidence_tier"] == "2_operating_candidate"
        assert row["review_valid_for_promotion"] is False
        assert row["ready_for_human_review"] is True
        assert row["production_activation_allowed"] is False


def test_verifier_blocks_candidate_when_daily_summary_is_not_review_only() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
            cash_trap_false=True,
        )
        seed_daily_user_current(candidate)
        summary_path = candidate / "user_current" / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary.pop("review_only", None)
        summary["live_trading_enabled"] = True
        write_json(summary_path, summary)

        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "rejected"
        assert payload["ready_for_human_review_candidate_count"] == 0
        row = payload["candidates"][0]
        assert row["decision"] == "do_not_use_evidence_tier"
        assert row["evidence_tier"] == "0_do_not_use"
        assert row["ready_for_human_review"] is False
        assert "user_current_summary.review_only_not_true" in row["issues"]
        assert "user_current_summary.live_trading_enabled_not_false" in row["issues"]


def test_verifier_rejects_dirty_short_7y_as_do_not_use() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
            data_ready=False,
            universe_count=259,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "rejected"
        row = payload["candidates"][0]
        assert row["decision"] == "do_not_use_evidence_tier"
        assert row["evidence_tier"] == "0_do_not_use"
        assert any("data_readiness" in issue for issue in row["issues"])


def test_verifier_blocks_dirty_baseline_before_candidate_review() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(
            baseline,
            cagr=0.4443,
            max_dd=-0.2592,
            is_cagr=0.2241,
            years=7.02,
            target_pass=False,
            strengthened_pass=False,
            data_ready=False,
            universe_count=259,
        )
        seed_run(candidate, cagr=0.52, max_dd=-0.26, is_cagr=0.31, years=8.10, target_pass=True, strengthened_pass=True)
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked_missing_baseline"
        assert payload["baseline_valid_for_research"] is False
        assert "baseline_evidence_tier0" in payload["baseline_issues"]
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_missing_baseline"
        assert "baseline_evidence_tier0" in row["issues"]
        assert any("baseline:data_readiness" in issue for issue in row["issues"])


def test_verifier_blocks_clean_7y_candidate_without_readiness_artifact() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
            clean_7y_ready=None,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_clean_7y_readiness"
        assert "clean_7y_research_readiness_missing" in row["issues"]


def test_verifier_surfaces_clean_7y_recovery_when_readiness_blocked() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=7.50,
            trading_days=1800,
            target_pass=True,
            strengthened_pass=True,
            valid_for_production=False,
            clean_7y_ready=False,
        )
        write_json(
            candidate / "clean_7y_research_readiness" / "summary.json",
            {
                "status": "not_ready",
                "ready_for_alpha_plane_ab_research": False,
                "blockers": ["pre_broker_substrate_gate_blocked"],
                "promotion_allowed": False,
                "evidence_recovery": {
                    "fallback_available": True,
                    "recommended_recovery_source": "committed_static_IWB_seed",
                    "recommended_recovery_reason": "static seed is available above floor",
                    "recovery_action": "repair_universe_from_fallback",
                },
            },
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_clean_7y_readiness"
        assert row["clean_7y_recovery_source"] == "committed_static_IWB_seed"
        assert row["clean_7y_recovery_action"] == "repair_universe_from_fallback"
        report = (root / "out" / "report.md").read_text(encoding="utf-8")
        assert "repair_universe_from_fallback via committed_static_IWB_seed" in report
        csv_text = (root / "out" / "candidate_verdicts.csv").read_text(encoding="utf-8")
        assert "clean_7y_recovery_source" in csv_text
        assert "committed_static_IWB_seed" in csv_text


def test_verifier_blocks_missing_acceptance_evidence() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=8.10,
            target_pass=True,
            strengthened_pass=True,
            system_acceptance=False,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_missing_evidence"
        assert "system_acceptance_audit_missing" in row["issues"]


def test_verifier_blocks_missing_oos_lock_evidence() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=8.10,
            target_pass=True,
            strengthened_pass=True,
            oos_lock=False,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_missing_evidence"
        assert "oos_lock_summary_missing" in row["issues"]
        assert "oos_holdout_lock:missing" in row["issues"]


def test_verifier_blocks_failed_oos_lock() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(
            candidate,
            cagr=0.52,
            max_dd=-0.26,
            is_cagr=0.31,
            years=8.10,
            target_pass=True,
            strengthened_pass=True,
            oos_lock_pass=False,
            oos_is_ratio=5.5,
        )
        payload = run(args(baseline, [candidate], root / "out"))
        assert payload["status"] == "blocked"
        row = payload["candidates"][0]
        assert row["decision"] == "blocked_oos_lock"
        assert "oos_is_cagr_ratio_above_lock" in row["issues"]


def test_verifier_carries_dispatch_context_for_queue_closure() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline = root / "baseline"
        candidate = root / "candidate"
        seed_run(baseline, cagr=0.4443, max_dd=-0.2592, is_cagr=0.2241, years=7.02, target_pass=False, strengthened_pass=False)
        seed_run(candidate, cagr=0.52, max_dd=-0.26, is_cagr=0.31, years=8.10, target_pass=True, strengthened_pass=True)
        ns = args(baseline, [candidate], root / "out")
        ns.experiment_id = "conc_continuation_winner_relaxation"
        ns.payload_hash = "payload-ready"
        ns.workflow_run_id = "27599999999"
        ns.dispatch_run_id = "dispatcher-smoke"
        payload = run(ns)
        row = payload["candidates"][0]
        assert payload["dispatch_context"]["experiment_id"] == "conc_continuation_winner_relaxation"
        assert row["experiment_id"] == "conc_continuation_winner_relaxation"
        assert row["payload_hash"] == "payload-ready"
        assert row["workflow_run_id"] == "27599999999"
        assert row["dispatch_run_id"] == "dispatcher-smoke"
        assert row["candidate_run"] == "candidate"


if __name__ == "__main__":
    test_verifier_marks_clean_candidate_review_promotable()
    test_verifier_rejects_is_cagr_regression_even_if_headline_passes()
    test_verifier_measures_clean_short_7y_candidate_without_promotion()
    test_verifier_marks_clean_7y_operating_candidate_for_human_review_only()
    test_verifier_blocks_candidate_when_daily_summary_is_not_review_only()
    test_verifier_rejects_dirty_short_7y_as_do_not_use()
    test_verifier_blocks_dirty_baseline_before_candidate_review()
    test_verifier_blocks_clean_7y_candidate_without_readiness_artifact()
    test_verifier_surfaces_clean_7y_recovery_when_readiness_blocked()
    test_verifier_blocks_missing_acceptance_evidence()
    test_verifier_blocks_missing_oos_lock_evidence()
    test_verifier_blocks_failed_oos_lock()
    test_verifier_carries_dispatch_context_for_queue_closure()
    print("ab_result_verifier_smoke: PASS")
