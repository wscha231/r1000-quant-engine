#!/usr/bin/env python3
"""Smoke tests for ETF holding event construction."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_etf_holding_event_builder import build_etf_holding_events, run  # noqa: E402


def sample_holdings(*, coverage_kind: str = "FULL") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "AAA",
                "holding_name": "AAA Inc",
                "holding_weight": 0.10,
                "coverage_kind": coverage_kind,
                "source": "fixture",
                "as_of_date": "2026-04-30T00:00:00Z",
                "available_from": "2026-04-30T00:00:00Z",
            },
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "CCC",
                "holding_name": "CCC Inc",
                "holding_weight": 0.04,
                "coverage_kind": coverage_kind,
                "source": "fixture",
                "as_of_date": "2026-04-30T00:00:00Z",
                "available_from": "2026-04-30T00:00:00Z",
            },
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "AAA",
                "holding_name": "AAA Inc",
                "holding_weight": 0.15,
                "coverage_kind": coverage_kind,
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            },
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "BBB",
                "holding_name": "BBB Inc",
                "holding_weight": 0.06,
                "coverage_kind": coverage_kind,
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            },
            {
                "etf_ticker": "BOTZ",
                "etf_label": "Global X Robotics ETF",
                "theme": "robotics_ai",
                "holding_ticker": "AAA",
                "holding_name": "AAA Inc",
                "holding_weight": 0.08,
                "coverage_kind": coverage_kind,
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            },
        ]
    )


def test_etf_holding_event_builder_detects_inclusion_weight_change_and_removal() -> None:
    events = build_etf_holding_events(sample_holdings(), change_threshold=0.0025)
    assert len(events) == 6
    counts = events["event_type"].value_counts().to_dict()
    assert counts["initial"] == 3
    assert counts["weight_increase"] == 1
    assert counts["inclusion"] == 1
    assert counts["removal"] == 1
    increase = events[(events["etf_ticker"].eq("SMH")) & (events["ticker"].eq("AAA")) & (events["event_type"].eq("weight_increase"))].iloc[0]
    assert abs(float(increase["holding_weight_delta"]) - 0.05) < 1e-9
    assert int(increase["etf_consensus_count"]) == 2
    assert float(increase["etf_event_seed_score"]) > 0
    assert bool(increase["membership_change_confirmed"]) is True
    removal = events[events["event_type"].eq("removal")].iloc[0]
    assert float(removal["etf_event_seed_score"]) < 0
    assert bool(removal["membership_change_confirmed"]) is True
    assert bool(events["research_only"].all()) is True
    assert bool((~events["production_activation_allowed"]).all()) is True


def test_partial_coverage_does_not_prove_membership_change() -> None:
    events = build_etf_holding_events(sample_holdings(coverage_kind="TOP_ONLY"), change_threshold=0.0025)
    counts = events["event_type"].value_counts().to_dict()
    assert counts["presence_observed"] == 1
    assert counts["absence_unconfirmed"] == 1
    presence = events[events["event_type"].eq("presence_observed")].iloc[0]
    absence = events[events["event_type"].eq("absence_unconfirmed")].iloc[0]
    assert float(presence["etf_event_seed_score"]) == 0.0
    assert float(absence["etf_event_seed_score"]) == 0.0
    assert bool(presence["membership_change_confirmed"]) is False
    assert bool(absence["membership_change_confirmed"]) is False


def test_invalid_weight_is_dropped_instead_of_becoming_zero_event() -> None:
    bad = pd.DataFrame(
        [
            {
                "etf_ticker": "SMH",
                "etf_label": "VanEck Semiconductor ETF",
                "theme": "semiconductors",
                "holding_ticker": "BAD",
                "holding_name": "Bad Row",
                "holding_weight": "N/A",
                "coverage_kind": "FULL",
                "source": "fixture",
                "as_of_date": "2026-05-31T00:00:00Z",
                "available_from": "2026-05-31T00:00:00Z",
            }
        ]
    )
    events = build_etf_holding_events(pd.concat([sample_holdings(), bad], ignore_index=True), change_threshold=0.0025)
    assert "BAD" not in set(events["ticker"])
    assert len(events) == 6


def test_invalid_row_downgrades_full_snapshot_before_membership_change() -> None:
    holdings = pd.DataFrame(
        [
            {"etf_ticker": "ETF1", "etf_label": "ETF One", "theme": "fixture", "holding_ticker": "A", "holding_name": "A", "holding_weight": 0.80, "coverage_kind": "FULL", "source": "fixture", "as_of_date": "2026-04-30T00:00:00Z", "available_from": "2026-04-30T00:00:00Z"},
            {"etf_ticker": "ETF1", "etf_label": "ETF One", "theme": "fixture", "holding_ticker": "BAD", "holding_name": "Bad", "holding_weight": 0.20, "coverage_kind": "FULL", "source": "fixture", "as_of_date": "2026-04-30T00:00:00Z", "available_from": "2026-04-30T00:00:00Z"},
            {"etf_ticker": "ETF1", "etf_label": "ETF One", "theme": "fixture", "holding_ticker": "A", "holding_name": "A", "holding_weight": 1.00, "coverage_kind": "FULL", "source": "fixture", "as_of_date": "2026-05-31T00:00:00Z", "available_from": "2026-05-31T00:00:00Z"},
            {"etf_ticker": "ETF1", "etf_label": "ETF One", "theme": "fixture", "holding_ticker": "BAD", "holding_name": "Bad", "holding_weight": "N/A", "coverage_kind": "FULL", "source": "fixture", "as_of_date": "2026-05-31T00:00:00Z", "available_from": "2026-05-31T00:00:00Z"},
        ]
    )
    events = build_etf_holding_events(holdings, change_threshold=0.0025)
    event_times = pd.to_datetime(events["available_from"], errors="coerce", utc=True)
    bad = events[(events["ticker"].eq("BAD")) & event_times.eq(pd.Timestamp("2026-05-31T00:00:00Z"))].iloc[0]
    assert bad["event_type"] == "absence_unconfirmed"
    assert bad["current_coverage_kind"] == "PARTIAL"
    assert bool(bad["membership_change_confirmed"]) is False
    assert float(bad["etf_event_seed_score"]) == 0.0


def test_etf_holding_event_builder_cli_outputs_summary() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        holdings = root / "data_pit" / "etf_holdings" / "etf_holdings.parquet"
        pit = root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"
        out = root / "outputs" / "etf_holding_events"
        holdings.parent.mkdir(parents=True, exist_ok=True)
        sample_holdings().to_parquet(holdings, index=False)
        payload = run(Namespace(holdings=str(holdings), pit_output=str(pit), output_dir=str(out), change_threshold=0.0025))
        assert payload["status"] == "completed", payload
        assert payload["event_rows"] == 6
        assert payload["candidate_event_rows"] == 6
        assert payload["candidate_excluded_unconfirmed_rows"] == 0
        assert payload["ticker_count"] == 3
        assert payload["schema_version"] == "etf-holding-events-v2"
        saved = pd.read_parquet(pit)
        assert len(saved) == 6
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["score_total_changed"] is False


def test_cli_keeps_unconfirmed_membership_events_audit_only() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        holdings = root / "data_pit" / "etf_holdings" / "etf_holdings.parquet"
        pit = root / "data_pit" / "etf_holdings" / "etf_holding_events.parquet"
        out = root / "outputs" / "etf_holding_events"
        holdings.parent.mkdir(parents=True, exist_ok=True)
        sample_holdings(coverage_kind="TOP_ONLY").to_parquet(holdings, index=False)
        payload = run(Namespace(holdings=str(holdings), pit_output=str(pit), output_dir=str(out), change_threshold=0.0025))
        candidate = pd.read_parquet(pit)
        audit = pd.read_csv(out / "etf_holding_events.csv", low_memory=False)
        unconfirmed = {"presence_observed", "absence_unconfirmed"}
        assert unconfirmed.isdisjoint(set(candidate["event_type"]))
        assert unconfirmed.issubset(set(audit["event_type"]))
        assert payload["event_rows"] == 6
        assert payload["candidate_event_rows"] == 4
        assert payload["candidate_excluded_unconfirmed_rows"] == 2
        assert len(candidate) == 4
        assert len(audit) == 6


if __name__ == "__main__":
    test_etf_holding_event_builder_detects_inclusion_weight_change_and_removal()
    test_partial_coverage_does_not_prove_membership_change()
    test_invalid_weight_is_dropped_instead_of_becoming_zero_event()
    test_invalid_row_downgrades_full_snapshot_before_membership_change()
    test_etf_holding_event_builder_cli_outputs_summary()
    test_cli_keeps_unconfirmed_membership_events_audit_only()
    print("etf_holding_event_builder_smoke: PASS")
