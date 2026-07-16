#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.audit_run287_pit_estimate_guidance_sample_v2 import (  # noqa: E402
    audit_local_forward_snapshot,
    audit_sample,
    selection_hash,
    write_outputs,
)


HASH = hashlib.sha256(b"fixture-source").hexdigest()


def contract() -> dict[str, object]:
    return {
        "schema_version": "fixture-v2",
        "window_start": "2019-06-03",
        "window_end": "2026-07-10",
        "sample_selection_seed": "fixture-seed",
        "sample_strata_exact_counts": {
            "active_us": 1,
            "delisted": 1,
            "adr_home": 1,
            "predecessor_corporate_action": 1,
        },
        "minimums": {
            "unique_security_count": 4,
            "event_count": 6,
            "revision_pair_security_count": 2,
            "explicit_guidance_event_count": 2,
            "delisted_outcome_count": 1,
            "adr_home_bridge_count": 1,
            "predecessor_continuity_count": 1,
            "stable_identity_count": 4,
            "asof_query_count": 2,
            "asof_reproduction_count": 2,
        },
        "security_master_required_columns": [
            "issuer_id", "security_id", "listing_id", "ticker", "mic", "sample_stratum",
            "is_delisted", "is_adr", "home_security_id", "home_listing_id",
            "predecessor_security_id", "corporate_action_type", "delisted_outcome_type",
            "delisted_outcome_value", "identity_source_hash",
        ],
        "event_required_columns": [
            "provider", "event_id", "issuer_id", "security_id", "listing_id", "ticker",
            "event_type", "metric", "fiscal_period_end", "fiscal_period_type", "value_role",
            "value", "currency", "unit", "observed_at", "available_from",
            "revision_of_event_id", "source_hash",
        ],
        "event_required_nonempty_columns": [
            "provider", "event_id", "issuer_id", "security_id", "listing_id", "ticker",
            "event_type", "metric", "fiscal_period_end", "fiscal_period_type", "value_role",
            "value", "currency", "unit", "observed_at", "available_from", "source_hash",
        ],
        "asof_query_required_columns": [
            "query_id", "decision_time", "security_id", "event_type", "metric",
            "fiscal_period_end", "fiscal_period_type", "expected_event_id", "selection_hash",
        ],
        "allowed_values": {
            "event_type": ["consensus_estimate", "company_guidance"],
            "metric": ["eps", "revenue"],
            "fiscal_period_type": ["FY", "FQ"],
            "value_role": ["consensus_mean", "guidance_low", "guidance_high", "guidance_midpoint"],
            "delisted_outcome_type": ["delisting_return", "cash_merger_proceeds", "bankruptcy_zero", "other_verified"],
            "corporate_action_type": ["ticker_change", "merger", "spin_off", "reorganization", "share_class_change"],
        },
        "rights_required_fields": [
            "provider", "export_id", "point_in_time_history_claimed",
            "exact_availability_semantics_documented", "timezone_semantics_documented",
            "revision_supersession_policy_documented", "stable_identity_history_included",
            "delisted_history_included", "adr_home_bridge_included", "predecessor_history_included",
            "sample_storage_allowed", "internal_research_reproduction_allowed",
            "derived_results_retention_allowed", "raw_redistribution_policy",
            "sample_quote_amount_usd", "rights_source_hash",
        ],
        "approved_sample_cost_hard_cap_usd": 300.0,
        "pass_status": "READY_PIT_SAMPLE_SCHEMA_GATE_ONLY",
        "blocked_status": "BLOCKED_PIT_SAMPLE_CONTRACT",
    }


def master() -> pd.DataFrame:
    common = {
        "mic": "XNYS", "home_security_id": "", "home_listing_id": "",
        "predecessor_security_id": "", "corporate_action_type": "",
        "delisted_outcome_type": "", "delisted_outcome_value": "",
        "identity_source_hash": HASH,
    }
    return pd.DataFrame(
        [
            {**common, "issuer_id": "ISS-A", "security_id": "SEC-A", "listing_id": "LST-A", "ticker": "AAA", "sample_stratum": "active_us", "is_delisted": False, "is_adr": False},
            {**common, "issuer_id": "ISS-B", "security_id": "SEC-B", "listing_id": "LST-B", "ticker": "OLD", "sample_stratum": "delisted", "is_delisted": True, "is_adr": False, "delisted_outcome_type": "cash_merger_proceeds", "delisted_outcome_value": "25.0"},
            {**common, "issuer_id": "ISS-C", "security_id": "SEC-C", "listing_id": "LST-C", "ticker": "ADR", "sample_stratum": "adr_home", "is_delisted": False, "is_adr": True, "home_security_id": "HOME-C", "home_listing_id": "HOME-LST-C"},
            {**common, "issuer_id": "ISS-D", "security_id": "SEC-D", "listing_id": "LST-D", "ticker": "NEW", "sample_stratum": "predecessor_corporate_action", "is_delisted": False, "is_adr": False, "predecessor_security_id": "OLD-D", "corporate_action_type": "ticker_change"},
        ]
    )


def events() -> pd.DataFrame:
    identity = {
        "SEC-A": ("ISS-A", "LST-A", "AAA"),
        "SEC-B": ("ISS-B", "LST-B", "OLD"),
        "SEC-C": ("ISS-C", "LST-C", "ADR"),
        "SEC-D": ("ISS-D", "LST-D", "NEW"),
    }
    rows: list[dict[str, object]] = []

    def add(event_id: str, security_id: str, event_type: str, metric: str, value_role: str, observed: str, available: str, revision: str = "") -> None:
        issuer, listing, ticker = identity[security_id]
        rows.append(
            {
                "provider": "fixture-vendor", "event_id": event_id, "issuer_id": issuer,
                "security_id": security_id, "listing_id": listing, "ticker": ticker,
                "event_type": event_type, "metric": metric, "fiscal_period_end": "2025-12-31",
                "fiscal_period_type": "FY", "value_role": value_role,
                "value": 1.0 + len(rows), "currency": "USD",
                "unit": "per_share" if metric == "eps" else "currency",
                "observed_at": observed, "available_from": available,
                "revision_of_event_id": revision, "source_hash": HASH,
            }
        )

    add("A1", "SEC-A", "consensus_estimate", "eps", "consensus_mean", "2024-01-02T13:00:00Z", "2024-01-02T13:01:00Z")
    add("A2", "SEC-A", "consensus_estimate", "eps", "consensus_mean", "2024-02-02T13:00:00Z", "2024-02-02T13:01:00Z", "A1")
    add("B1", "SEC-B", "consensus_estimate", "revenue", "consensus_mean", "2024-01-03T13:00:00Z", "2024-01-03T13:01:00Z")
    add("B2", "SEC-B", "consensus_estimate", "revenue", "consensus_mean", "2024-02-03T13:00:00Z", "2024-02-03T13:01:00Z", "B1")
    add("C1", "SEC-C", "company_guidance", "revenue", "guidance_midpoint", "2024-03-01T21:00:00Z", "2024-03-01T21:01:00Z")
    add("D1", "SEC-D", "company_guidance", "eps", "guidance_midpoint", "2024-03-02T21:00:00Z", "2024-03-02T21:01:00Z")
    return pd.DataFrame(rows)


def queries() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {"query_id": "Q1", "decision_time": "2024-02-05T21:00:00Z", "security_id": "SEC-A", "event_type": "consensus_estimate", "metric": "eps", "fiscal_period_end": "2025-12-31", "fiscal_period_type": "FY", "expected_event_id": "A2"},
            {"query_id": "Q2", "decision_time": "2024-02-05T21:00:00Z", "security_id": "SEC-B", "event_type": "consensus_estimate", "metric": "revenue", "fiscal_period_end": "2025-12-31", "fiscal_period_type": "FY", "expected_event_id": "B2"},
        ]
    )
    frame["selection_hash"] = frame.apply(lambda row: selection_hash("fixture-seed", row), axis=1)
    return frame


def rights() -> dict[str, object]:
    return {
        "provider": "fixture-vendor", "export_id": "fixture-export",
        "point_in_time_history_claimed": True,
        "exact_availability_semantics_documented": True,
        "timezone_semantics_documented": True,
        "revision_supersession_policy_documented": True,
        "stable_identity_history_included": True,
        "delisted_history_included": True,
        "adr_home_bridge_included": True,
        "predecessor_history_included": True,
        "sample_storage_allowed": True,
        "internal_research_reproduction_allowed": True,
        "derived_results_retention_allowed": True,
        "raw_redistribution_policy": "raw redistribution prohibited; derived audit allowed",
        "sample_quote_amount_usd": 0.0,
        "rights_source_hash": HASH,
    }


def run(events_frame: pd.DataFrame | None = None, master_frame: pd.DataFrame | None = None, query_frame: pd.DataFrame | None = None):
    return audit_sample(
        security_master=master_frame if master_frame is not None else master(),
        events=events_frame if events_frame is not None else events(),
        asof_queries=query_frame if query_frame is not None else queries(),
        rights=rights(),
        contract=contract(),
    )


def test_ready_fixture() -> None:
    summary, checks, master_audit, event_audit, asof_audit, strata, rights_audit = run()
    assert summary["status"] == "READY_PIT_SAMPLE_SCHEMA_GATE_ONLY"
    assert checks["status"].eq("PASS").all()
    assert len(master_audit) == 4
    assert len(event_audit) == 6
    assert asof_audit["reproduced"].all()
    assert strata["status"].eq("PASS").all()
    assert rights_audit["status"].eq("PASS").all()
    assert summary["alpha_screen_allowed"] is False
    assert summary["portfolio_arm_allowed"] is False
    assert summary["purchase_authorized"] is False
    assert summary["fullrun_dispatched"] is False
    with tempfile.TemporaryDirectory() as tmp:
        write_outputs(Path(tmp), summary, checks, master_audit, event_audit, asof_audit, strata, rights_audit)
        assert (Path(tmp) / "manifest.json").exists()
        assert (Path(tmp) / "asof_reproduction_audit.csv").exists()


def test_date_only_and_future_rows_fail_closed() -> None:
    frame = events()
    frame.loc[0, "available_from"] = "2026-07-11T01:00:00Z"
    frame.loc[1, "observed_at"] = "2024-02-02"
    summary, checks, *_ = run(events_frame=frame)
    indexed = checks.set_index("check_id")
    assert summary["status"] == "BLOCKED_PIT_SAMPLE_CONTRACT"
    assert indexed.loc["exact_timestamp_timezone", "status"] == "FAIL"
    assert indexed.loc["future_rows", "status"] == "FAIL"


def test_adr_bridge_and_asof_mismatch_fail_closed() -> None:
    master_frame = master()
    master_frame.loc[master_frame["sample_stratum"].eq("adr_home"), "home_security_id"] = ""
    query_frame = queries()
    query_frame.loc[0, "expected_event_id"] = "A1"
    summary, checks, *_ = run(master_frame=master_frame, query_frame=query_frame)
    indexed = checks.set_index("check_id")
    assert summary["status"] == "BLOCKED_PIT_SAMPLE_CONTRACT"
    assert indexed.loc["adr_home_bridges", "status"] == "FAIL"
    assert indexed.loc["asof_reproduction", "status"] == "FAIL"


def test_local_forward_snapshot_is_never_promoted() -> None:
    summary, gap = audit_local_forward_snapshot(
        snapshot=pd.DataFrame([{"ticker": "AAA", "has_forward_estimate": 1, "available_from": "2026-07-09"}]),
        request=pd.DataFrame([{"ticker": "AAA", "security_id": ""}]),
        source_summary={"feature_summary": {"available_from_is_fetch_date": True}},
        contract=contract(),
        input_hashes={},
    )
    assert summary["status"] == "BLOCKED_PIT_SAMPLE_CONTRACT_LOCAL_FORWARD_ONLY"
    assert summary["local_rows_promoted_to_historical_pit"] == 0
    assert gap.set_index("gate").loc["historical_pit_event_count", "status"] == "FAIL"


def test_repository_contract_keeps_gpt_pro_minimums() -> None:
    payload = json.loads(
        (ROOT / "docs" / "run287_pit_estimate_guidance_sample_contract_v2.json").read_text(encoding="utf-8")
    )
    assert payload["sample_strata_exact_counts"] == {
        "active_us": 20,
        "delisted": 10,
        "adr_home": 10,
        "predecessor_corporate_action": 10,
    }
    assert payload["minimums"]["unique_security_count"] == 50
    assert payload["minimums"]["event_count"] == 200
    assert payload["minimums"]["revision_pair_security_count"] == 40
    assert payload["minimums"]["asof_reproduction_count"] == 10
    assert payload["alpha_screen_allowed"] is False
    assert payload["fullrun_dispatched"] is False


def main() -> None:
    test_ready_fixture()
    test_date_only_and_future_rows_fail_closed()
    test_adr_bridge_and_asof_mismatch_fail_closed()
    test_local_forward_snapshot_is_never_promoted()
    test_repository_contract_keeps_gpt_pro_minimums()
    print("run287_pit_estimate_guidance_sample_v2_smoke: PASS")


if __name__ == "__main__":
    main()
