#!/usr/bin/env python3
"""Smoke checks for the explicit Run287 next-scheduled-artifact gate."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_run287_next_scheduled_artifact_gate.py"
SPEC = importlib.util.spec_from_file_location("audit_run287_next_scheduled_artifact_gate", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def safety() -> dict[str, Any]:
    return {
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "live_trading_enabled": False,
        "production_activation_allowed": False,
        "target_books_mutated": False,
    }


def fixture(td: str, *, one_day_completed: int = 26) -> dict[str, Path]:
    root = Path(td)
    paths = {name: root / f"{name}.json" for name in (
        "estimate", "session", "coverage", "upstream", "registry", "producer", "decision", "risk"
    )}
    circuit = {
        "enabled": True,
        "run_scoped": True,
        "persistent_vendor_block_written": False,
        "circuit_status_codes": [401, 403],
        "tripped_vendors": ["finnhub"],
        "tripped_vendor_count": 1,
        "estimated_estimate_http_requests_avoided": 294,
        "vendors": {
            "finnhub": {"tripped": True, "trip_signature": "403:recommendation"},
            "fmp": {"tripped": False, "trip_signature": ""},
        },
    }
    write_json(paths["estimate"], {
        "schema_version": "earnings-estimate-archive-manifest-v1",
        "verdict": "archive_manifest_written",
        "fetch_date": "2026-07-15",
        "collector_status": "blocked_partial_coverage",
        "collection_queue_status": "ready_for_forward_archive_incremental",
        "collection_queue_selected_ticker_count": 150,
        "ticker_count_requested": 150,
        "ticker_count_attempted": 150,
        "collection_universe_ticker_count": 993,
        "collection_eligible_ticker_count": 992,
        "collection_non_equity_placeholder_ticker_count": 1,
        "collection_attempt_ack": {
            "status": "acknowledged",
            "attempted_ticker_count": 150,
            "acknowledged_ticker_count": 150,
            "unacknowledged_tickers": [],
        },
        "missing_vendor_coverage_policy": "neutral",
        "entitlement_circuit_threshold": 3,
        "vendor_entitlement_circuit": circuit,
        "request_snapshot_rows": 12,
        "request_has_forward_estimate_rows": 2,
        "error_count": 103,
        "error_budget_count": 1,
        "entitlement_error_warn_only_count": 102,
        "entitlement_error_probe_count": 3,
        "text_secret_scan": {"unmasked_secret_pattern_found": False},
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
    })
    write_json(paths["session"], {
        "schema_version": "daily-market-session-gate-v1", "status": "READY_COMPLETED_SESSION",
        "session_date": "2026-07-14", "ready": True,
    })
    write_json(paths["coverage"], {
        "schema_version": "daily-close-price-coverage-v1", "status": "PASS", "session_date": "2026-07-14",
        "exact_close_coverage": True, "prior_session_fallback_allowed": False,
        "missing_ticker_count": 0, "exact_ticker_count": 1, "required_ticker_count": 1,
        "rows": [{"ticker": "SPY", "actual_price_date": "2026-07-14", "exact_close_present": True}],
    })
    write_json(paths["upstream"], {
        "schema_version": "run287-exact-packet-upstream-orchestrator-v2",
        "status": "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
        "valuation_price_cutoff_date": "2026-07-14", "upstream_ready": True, "research_only": True,
        "historical_cagr_mdd_evidence_changed": False,
        "stage_audit": [{"name": "source_bundle", "failures": []}],
        "source_bundle": {"path": "bundle.json", "sha256": "a" * 64}, **safety(),
    })
    write_json(paths["registry"], {
        "schema_version": "run287-exact-packet-input-registry-builder-v1",
        "status": "READY_EXACT_PACKET_INPUTS_REVIEW_ONLY", "valuation_price_cutoff_date": "2026-07-14",
        "contract_failures": [], "research_only": True, **safety(),
    })
    write_json(paths["producer"], {
        "schema_version": "run287-exact-packet-producer-v1",
        "status": "READY_EXISTING_EXACT_SELECTOR_RISK_PACKET_REVIEW_ONLY", "valuation_price_cutoff_date": "2026-07-14",
        "exact_packet_ready": True, "contract_failures": [], "research_only": True,
        "historical_cagr_mdd_evidence_changed": False, "selector_weights_changed_by_producer": False, **safety(),
    })
    write_json(paths["decision"], {
        "schema_version": "run287-decision-observation-archive-v1",
        "status": "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY", "latest_as_of_date": "2026-07-14",
        "archive_passed": True, "contract_failures": [], "review_only": True, "archive_may_promote": False,
        "source_inputs_mutated": False, "historical_cagr_mdd_evidence_changed": False,
        "selector_weights_changed": False, "cash_policy_changed": False,
        **safety(),
    })
    one_day = {"completed": one_day_completed} if one_day_completed else {"pending_not_elapsed": 26}
    metrics = ({
        "warning": {"count": 7, "mean_spy_excess_total_return": -0.01},
        "normal": {"count": 19, "mean_spy_excess_total_return": 0.01},
        "warning_minus_normal": {"mean_spy_excess_total_return": -0.02},
    } if one_day_completed else {})
    write_json(paths["risk"], {
        "schema_version": "run287-risk-outcome-archive-v1",
        "status": "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY", "as_of_date": "2026-07-14",
        "blockers": [], "review_only": True, "historical_cagr_mdd_evidence_changed": False,
        "horizon_status_counts": {"1d": one_day}, "group_metrics": {"1d": metrics},
        "mechanism_review_ready": False, "stop_or_exit_rule_created": False,
        "threshold_tuning_allowed": False, "portfolio_transition_allowed": False,
        "mechanism_promotion_allowed": False, "selector_weights_changed": False, "cash_policy_changed": False,
        **safety(),
    })
    paths["output"] = root / "output"
    return paths


def run(paths: dict[str, Path], **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "contract_path": ROOT / "docs" / "run287_next_scheduled_artifact_gate_contract.json",
        "expected_session_date": "2026-07-14",
        "expected_estimate_fetch_date": "2026-07-15",
        "estimate_manifest_path": paths.get("estimate"),
        "market_session_path": paths.get("session"),
        "close_coverage_path": paths.get("coverage"),
        "exact_upstream_status_path": paths.get("upstream"),
        "exact_registry_status_path": paths.get("registry"),
        "exact_producer_status_path": paths.get("producer"),
        "decision_archive_manifest_path": paths.get("decision"),
        "risk_outcome_summary_path": paths.get("risk"),
        "output_dir": paths["output"],
        "generated_at": "2026-07-15T00:00:00Z",
    }
    values.update(overrides)
    return MOD.audit(**values)


def test_ready_is_diagnostic_only() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        result = run(paths)
        assert result["status"] == MOD.READY_STATUS
        assert result["estimate_gate"]["acknowledged_ticker_count"] == 150
        assert result["daily_gate"]["completed_1d_count"] == 26
        assert result["daily_gate"]["warning_minus_normal_1d"]["mean_spy_excess_total_return"] == -0.02
        assert result["rule_change_allowed"] is False
        assert result["historical_ab_allowed"] is False
        assert result["network_requests_executed"] == 0


def test_missing_is_pending_without_latest_discovery() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        result = run(paths, exact_upstream_status_path=None)
        assert result["status"] == MOD.PENDING_MISSING_STATUS
        assert result["missing_artifacts"] == ["exact_upstream"]


def test_valid_artifacts_with_no_elapsed_1d_stay_pending() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td, one_day_completed=0)
        result = run(paths)
        assert result["status"] == MOD.PENDING_1D_STATUS
        assert result["daily_gate"]["first_1d_available"] is False


def test_partial_ack_and_stale_session_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        estimate = json.loads(paths["estimate"].read_text(encoding="utf-8"))
        estimate["ticker_count_attempted"] = 149
        estimate["collection_attempt_ack"]["attempted_ticker_count"] = 149
        estimate["collection_attempt_ack"]["acknowledged_ticker_count"] = 149
        write_json(paths["estimate"], estimate)
        session = json.loads(paths["session"].read_text(encoding="utf-8"))
        session["session_date"] = "2026-07-13"
        write_json(paths["session"], session)
        result = run(paths)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any("ticker_count_attempted" in failure for failure in result["contract_failures"])
        assert any("market_session.session_date" in failure for failure in result["contract_failures"])


def test_402_may_warn_but_can_never_trip_global_circuit() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        estimate = json.loads(paths["estimate"].read_text(encoding="utf-8"))
        estimate["vendor_entitlement_circuit"]["vendors"]["fmp"] = {
            "tripped": True, "trip_signature": "402:analyst-estimates"
        }
        write_json(paths["estimate"], estimate)
        result = run(paths)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert any("invalid_entitlement_trip" in failure for failure in result["contract_failures"])


def test_unsafe_present_artifact_blocks() -> None:
    with tempfile.TemporaryDirectory() as td:
        paths = fixture(td)
        risk = json.loads(paths["risk"].read_text(encoding="utf-8"))
        risk["cash_policy_changed"] = True
        write_json(paths["risk"], risk)
        result = run(paths)
        assert result["status"] == MOD.BLOCKED_STATUS
        assert "risk_outcome.cash_policy_changed:not_false" in result["contract_failures"]


def main() -> int:
    test_ready_is_diagnostic_only()
    test_missing_is_pending_without_latest_discovery()
    test_valid_artifacts_with_no_elapsed_1d_stay_pending()
    test_partial_ack_and_stale_session_block()
    test_402_may_warn_but_can_never_trip_global_circuit()
    test_unsafe_present_artifact_blocks()
    print("run287_next_scheduled_artifact_gate_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
