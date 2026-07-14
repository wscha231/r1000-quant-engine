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

from tools.audit_pit_estimate_guidance_source import audit_source, write_outputs  # noqa: E402


HASH = hashlib.sha256(b"provider-payload").hexdigest()


def requirements() -> dict[str, object]:
    return {
        "window_start": "2019-06-03",
        "window_end": "2026-07-10",
        "oos2_start": "2023-01-01",
        "oos_start": "2024-07-01",
        "history_start_grace_days": 1,
        "history_end_grace_days": 30,
        "min_requested_security_count": 3,
        "min_requested_delisted_count": 1,
        "min_exact_timestamp_ratio": 1.0,
        "min_source_hash_ratio": 1.0,
        "min_security_coverage_ratio": 1.0,
        "min_full_window_security_ratio": 1.0,
        "min_oos2_security_ratio": 1.0,
        "min_oos_security_ratio": 1.0,
        "min_revision_ready_security_ratio": 1.0,
        "min_guidance_pair_security_ratio": 1.0,
        "min_delisted_coverage_ratio": 1.0,
    }


def metadata() -> dict[str, object]:
    return {
        "provider": "fixture_vendor",
        "export_id": "sample-001",
        "point_in_time_history_claimed": True,
        "symbol_history_included": True,
        "delisted_history_included": True,
        "research_reproduction_allowed": True,
        "lock_in_required": False,
        "sample_quote_amount": 0.0,
        "approved_cost_ceiling_amount": 0.0,
        "quote_currency": "USD",
        "ceiling_currency": "USD",
    }


def universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"security_id": "SEC-A", "ticker": "AAA", "is_delisted": False},
            {"security_id": "SEC-B", "ticker": "BBB", "is_delisted": False},
            {"security_id": "SEC-C", "ticker": "OLD", "is_delisted": True},
        ]
    )


def events() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    sequence = 0

    def add(
        security_id: str,
        ticker: str,
        record_type: str,
        metric: str,
        period: str,
        value_role: str,
        value: float,
        observed_at: str,
        available_from: str,
    ) -> None:
        nonlocal sequence
        sequence += 1
        rows.append(
            {
                "provider": "fixture_vendor",
                "observation_id": f"obs-{sequence:04d}",
                "security_id": security_id,
                "ticker": ticker,
                "record_type": record_type,
                "metric": metric,
                "fiscal_period_end": period,
                "fiscal_period_type": "FY",
                "value_role": value_role,
                "value": value,
                "currency": "USD",
                "unit": "per_share" if metric == "eps" else "currency",
                "analyst_count": 0 if record_type == "company_guidance" else 8,
                "observed_at": observed_at,
                "available_from": available_from,
                "source_hash": HASH,
            }
        )

    for security_id, ticker in [("SEC-A", "AAA"), ("SEC-B", "BBB"), ("SEC-C", "OLD")]:
        for metric, base in [("eps", 2.0), ("revenue", 100.0)]:
            add(security_id, ticker, "consensus_estimate", metric, "2020-12-31", "consensus_mean", base, "2019-06-03T13:00:00Z", "2019-06-03T13:05:00Z")
            add(security_id, ticker, "consensus_estimate", metric, "2020-12-31", "consensus_mean", base + 0.1, "2019-06-04T13:00:00Z", "2019-06-04T13:05:00Z")
        add(security_id, ticker, "consensus_estimate", "eps", "2024-12-31", "consensus_mean", 3.0, "2023-01-02T13:00:00Z", "2023-01-02T13:05:00Z")
        add(security_id, ticker, "company_guidance", "eps", "2024-12-31", "guidance_midpoint", 3.2, "2023-01-03T21:00:00Z", "2023-01-03T21:01:00Z")
        add(security_id, ticker, "consensus_estimate", "revenue", "2025-12-31", "consensus_mean", 120.0, "2024-07-02T13:00:00Z", "2024-07-02T13:05:00Z")
        add(security_id, ticker, "consensus_estimate", "eps", "2026-12-31", "consensus_mean", 4.0, "2026-07-01T13:00:00Z", "2026-07-01T13:05:00Z")
    return pd.DataFrame(rows)


def run(events_frame: pd.DataFrame, universe_frame: pd.DataFrame | None = None, metadata_payload: dict[str, object] | None = None):
    return audit_source(
        events=events_frame,
        universe=universe_frame if universe_frame is not None else universe(),
        metadata=metadata_payload if metadata_payload is not None else metadata(),
        requirements=requirements(),
    )


def test_ready_sample() -> None:
    summary, checks, coverage = run(events())
    assert summary["status"] == "READY_FOR_SOURCE_SCREEN"
    assert summary["backtest_acceptance_allowed"] is False
    assert summary["portfolio_arm_allowed"] is False
    assert summary["purchase_authorized"] is False
    assert summary["fullrun_dispatched"] is False
    assert checks["status"].eq("PASS").all()
    assert coverage["revision_ready"].all()
    assert coverage["guidance_pair_ready"].all()
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp)
        write_outputs(output, summary, checks, coverage)
        assert (output / "summary.json").exists()
        assert "READY_FOR_SOURCE_SCREEN" in (output / "report.md").read_text(encoding="utf-8")


def test_date_only_timestamp_blocks_pit() -> None:
    frame = events()
    frame.loc[0, "observed_at"] = "2019-06-03"
    summary, checks, _ = run(frame)
    assert summary["status"] == "BLOCKED_PIT"
    assert checks.set_index("check_id").loc["exact_timestamp_ratio", "status"] == "FAIL"


def test_availability_before_observation_blocks_pit() -> None:
    frame = events()
    frame.loc[0, "available_from"] = "2019-06-03T12:59:00Z"
    summary, checks, _ = run(frame)
    assert summary["status"] == "BLOCKED_PIT"
    assert checks.set_index("check_id").loc["availability_chronology", "status"] == "FAIL"


def test_missing_security_is_undercovered_and_neutral() -> None:
    expanded = pd.concat(
        [
            universe(),
            pd.DataFrame([{"security_id": "SEC-D", "ticker": "DDD", "is_delisted": False}]),
        ],
        ignore_index=True,
    )
    req = requirements()
    req["min_requested_security_count"] = 4
    summary, checks, coverage = audit_source(events=events(), universe=expanded, metadata=metadata(), requirements=req)
    assert summary["status"] == "UNDER_COVERED"
    missing = coverage.set_index("security_id").loc["SEC-D"]
    assert not bool(missing["has_any_event"])
    assert not bool(missing["revision_ready"])
    assert checks.set_index("check_id").loc["security_coverage_ratio", "status"] == "FAIL"
    assert summary["missing_policy"] == "neutral"


def test_lock_in_blocks_procurement() -> None:
    payload = metadata()
    payload["lock_in_required"] = True
    summary, checks, _ = run(events(), metadata_payload=payload)
    assert summary["status"] == "BLOCKED_PROCUREMENT"
    assert checks.set_index("check_id").loc["no_provider_lock_in", "status"] == "FAIL"


def test_invalid_cost_blocks_without_crashing() -> None:
    payload = metadata()
    payload["sample_quote_amount"] = "not-a-number"
    summary, checks, _ = run(events(), metadata_payload=payload)
    assert summary["status"] == "BLOCKED_PROCUREMENT"
    assert checks.set_index("check_id").loc["valid_cost_values", "status"] == "FAIL"


def test_missing_event_schema_blocks_early() -> None:
    frame = events().drop(columns=["source_hash"])
    summary, _, coverage = run(frame)
    assert summary["status"] == "BLOCKED_SCHEMA"
    assert coverage.empty


def test_frozen_requirements_include_long_horizons() -> None:
    payload = json.loads(
        (ROOT / "docs" / "run287_pit_estimate_guidance_source_requirements.json").read_text(encoding="utf-8")
    )
    assert payload["required_return_horizons_trading_days"] == [21, 63, 126, 252, 504]
    outcome_path = ROOT / payload["outcome_contract"]
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    roles = {int(row["trading_days"]): row["role"] for row in outcome["horizons"]}
    assert roles[252] == "long_confirmation"
    assert roles[504] == "long_sensitivity"
    assert outcome["right_censoring_policy"].startswith("unresolved_outcomes_are_null")


def main() -> None:
    test_ready_sample()
    test_date_only_timestamp_blocks_pit()
    test_availability_before_observation_blocks_pit()
    test_missing_security_is_undercovered_and_neutral()
    test_lock_in_blocks_procurement()
    test_invalid_cost_blocks_without_crashing()
    test_missing_event_schema_blocks_early()
    test_frozen_requirements_include_long_horizons()
    print("pit_estimate_guidance_source_gate_smoke: PASS")


if __name__ == "__main__":
    main()
