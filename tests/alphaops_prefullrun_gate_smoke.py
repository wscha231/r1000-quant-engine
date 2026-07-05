#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_alphaops_prefullrun_gate import evaluate  # noqa: E402


def ready_payload() -> dict:
    return {
        "price_readiness": {
            "status": "ready",
            "fullrun_ready": True,
            "blockers": [],
            "required_price_tickers": ["QQQ", "SPY"],
            "policy_payload_binding": {"frozen_payload_match": True, "dispatch_payload_hash": "abc"},
        },
        "control_repro": {
            "status": "completed",
            "acceptance": {
                "passes_required_gate": True,
                "official_only_date_count": {"main": 0, "concentrated": 0},
                "generated_only_date_count": {"main": 0, "concentrated": 0},
                "ticker_mismatch_date_count": {"main": 0, "concentrated": 0},
                "max_weight_delta_abs": {"main": 0.0, "concentrated": 0.0},
            },
        },
        "replacement_readiness": {
            "status": "ready",
            "fullrun_allowed": True,
            "blockers": [],
            "control_reproduction": {"control_reproduced": True},
            "swap_diff": {"hook_is_subset_of_fixed": True},
        },
        "main_hedge_off": {
            "status": "main_long_only_research_pass",
            "quote_long_only_allowed": True,
            "main_cash_carry_target_pass": True,
            "hedge_off_cash_carry_cagr": 0.351,
            "hedge_off_cash_carry_max_dd": -0.24,
            "end_date_matches_official": True,
        },
        "policy_combo": {"_missing": True},
        "earnings_coverage": {
            "status": "RESEARCH_READY",
            "research_ready": True,
            "plumbing_ready": True,
            "service_ready": False,
            "policy_ready": False,
            "coverage_eligible_rows": 100,
            "coverage_eligible_tickers": 30,
        },
        "universe_status": {
            "status": "valid",
            "blockers": [],
            "pit_universe_label_clean": False,
            "r1000_base_count": 950,
            "candidate_count": 1200,
        },
    }


def call(payload: dict, **kwargs) -> dict:
    return evaluate(
        price_readiness=payload["price_readiness"],
        control_repro=payload["control_repro"],
        replacement_readiness=payload["replacement_readiness"],
        main_hedge_off=payload["main_hedge_off"],
        policy_combo=payload["policy_combo"],
        earnings_coverage=payload["earnings_coverage"],
        universe_status=payload["universe_status"],
        **kwargs,
    )


def test_all_research_gates_pass_but_dispatch_still_needs_user() -> None:
    payload = call(ready_payload())
    assert payload["research_fullrun_preconditions_ready"] is True
    assert payload["status"] == "ready_for_user_approval"
    assert payload["fullrun_dispatch_allowed"] is False
    assert payload["dispatch_requires_explicit_user_approval"] is True
    assert payload["production_promotion_allowed"] is False
    assert payload["production_blockers"] == ["pit_universe_label_clean_false"]
    assert payload["research_evidence_valid"] is True
    assert payload["production_evidence_valid"] is False
    assert payload["public_display_allowed"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["result_label"] == "production_blocked_research_pass"
    assert payload["policy_payload_binding"]["frozen_payload_match"] is True


def test_w1_exact_control_failure_blocks() -> None:
    source = ready_payload()
    source["control_repro"]["acceptance"]["passes_required_gate"] = False
    source["control_repro"]["acceptance"]["ticker_mismatch_date_count"] = {"main": 1, "concentrated": 0}
    payload = call(source)
    assert payload["research_fullrun_preconditions_ready"] is False
    assert "target_book_control_repro_not_exact" in payload["blockers"]


def test_replacement_quality_blockers_block() -> None:
    source = ready_payload()
    source["replacement_readiness"]["status"] = "blocked"
    source["replacement_readiness"]["fullrun_allowed"] = False
    source["replacement_readiness"]["blockers"] = ["control_not_reproduced"]
    payload = call(source)
    assert "replacement_quality_not_fullrun_ready" in payload["blockers"]
    assert "replacement_control_not_reproduced" in payload["blockers"]


def test_earnings_required_gate_blocks_only_when_required() -> None:
    source = ready_payload()
    source["earnings_coverage"]["status"] = "DATA_INSUFFICIENT"
    source["earnings_coverage"]["research_ready"] = False
    blocked = call(source)
    assert "earnings_guidance_not_research_ready" in blocked["blockers"]
    allowed = call(source, require_earnings_research_ready=False)
    assert "earnings_guidance_not_research_ready" not in allowed["blockers"]


def test_universe_invalid_blocks_research_and_pit_blocks_production() -> None:
    source = ready_payload()
    source["universe_status"]["status"] = "invalid_universe"
    source["universe_status"]["blockers"] = ["candidate_replay_book.csv missing"]
    payload = call(source)
    assert "universe_health_not_ready" in payload["blockers"]
    assert payload["production_blockers"] == ["pit_universe_label_clean_false"]


def test_policy_combo_pass_supersedes_dirty_control_main_and_replacement_blockers() -> None:
    source = ready_payload()
    source["control_repro"]["acceptance"]["passes_required_gate"] = False
    source["control_repro"]["acceptance"]["ticker_mismatch_date_count"] = {"main": 52, "concentrated": 56}
    source["control_repro"]["acceptance"]["max_weight_delta_abs"] = {"main": 0.49, "concentrated": 0.30}
    source["control_repro"]["same_machine_double_reproduction"] = {
        "main": {"exact_control_reproduced": True},
        "concentrated": {"exact_control_reproduced": True},
    }
    source["replacement_readiness"]["status"] = "blocked"
    source["replacement_readiness"]["fullrun_allowed"] = False
    source["replacement_readiness"]["blockers"] = ["hook_swap_count_outside_tolerance"]
    source["main_hedge_off"]["main_cash_carry_target_pass"] = False
    source["main_hedge_off"]["hedge_off_cash_carry_cagr"] = 0.3499
    source["policy_combo"] = {
        "status": "loaded_from_broker_metric_dir",
        "path": "outputs/policy_path_combo_probe_20260704_final_candidate",
        "main": {
            "metric_mode": "broker_ledger_next_close_cash_carry",
            "cagr": 0.363,
            "max_dd": -0.249,
            "years": 7.07,
            "end_date_matches_official": True,
            "production_activation_allowed": False,
        },
        "concentrated": {
            "metric_mode": "broker_ledger_next_close_cash_carry",
            "cagr": 0.521,
            "max_dd": -0.231,
            "years": 7.07,
            "end_date_matches_official": True,
            "production_activation_allowed": False,
        },
    }

    payload = call(source)

    assert "target_book_control_repro_not_exact" not in payload["blockers"]
    assert "replacement_quality_not_fullrun_ready" not in payload["blockers"]
    assert "main_long_only_cash_carry_target_not_met" not in payload["blockers"]
    assert payload["checks"]["policy_path_combo"]["research_pass"] is True
    assert payload["checks"]["target_book_control_repro"]["official_dirty_mismatch_non_blocking"] is True


if __name__ == "__main__":
    test_all_research_gates_pass_but_dispatch_still_needs_user()
    test_w1_exact_control_failure_blocks()
    test_replacement_quality_blockers_block()
    test_earnings_required_gate_blocks_only_when_required()
    test_universe_invalid_blocks_research_and_pit_blocks_production()
    test_policy_combo_pass_supersedes_dirty_control_main_and_replacement_blockers()
    print("alphaops_prefullrun_gate_smoke: PASS")
