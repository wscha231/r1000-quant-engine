#!/usr/bin/env python3
"""Smoke checks for D1 13F position event builder."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_13f_position_event_builder import build_position_events, run  # noqa: E402


def holdings_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2025-12-31",
                "filing_date": "2026-02-14",
                "accepted_at": "2026-02-14T18:00:00Z",
                "available_from": "2026-02-14T18:00:00Z",
                "cusip": "037833100",
                "issuer_name": "Apple Inc",
                "ticker_mapped": "AAPL",
                "shares": 100_000,
                "market_value_usd": 10_000_000,
            },
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2025-12-31",
                "filing_date": "2026-02-14",
                "accepted_at": "2026-02-14T18:00:00Z",
                "available_from": "2026-02-14T18:00:00Z",
                "cusip": "594918104",
                "issuer_name": "Microsoft Corp",
                "ticker_mapped": "MSFT",
                "shares": 50_000,
                "market_value_usd": 8_000_000,
            },
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00Z",
                "available_from": "2026-05-15T18:00:00Z",
                "cusip": "037833100",
                "issuer_name": "Apple Inc",
                "ticker_mapped": "AAPL",
                "shares": 125_000,
                "market_value_usd": 15_000_000,
            },
            {
                "manager_cik": "1067983",
                "manager_name": "Example Manager",
                "report_period": "2026-03-31",
                "filing_date": "2026-05-15",
                "accepted_at": "2026-05-15T18:00:00Z",
                "available_from": "2026-05-15T18:00:00Z",
                "cusip": "18452B209",
                "issuer_name": "CleanSpark Inc",
                "ticker_mapped": "CLSK",
                "shares": 200_000,
                "market_value_usd": 4_000_000,
            },
        ]
    )


def metadata_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": "AAPL", "market_cap_for_audit": 3_000_000_000_000, "shares_float": 15_000_000_000, "dollar_volume_20d": 5_000_000_000, "sector": "Technology"},
            {"ticker": "MSFT", "market_cap_for_audit": 2_800_000_000_000, "shares_float": 7_400_000_000, "dollar_volume_20d": 4_000_000_000, "sector": "Technology"},
            {"ticker": "CLSK", "market_cap_for_audit": 1_500_000_000, "shares_float": 250_000_000, "dollar_volume_20d": 60_000_000, "sector": "Crypto"},
        ]
    )


def test_event_builder_detects_add_new_and_exit() -> None:
    events = build_position_events(holdings_fixture(), metadata_fixture())
    second = events[events["report_period"].eq("2026-03-31")].set_index("ticker")
    assert second.loc["AAPL", "event_type"] == "add"
    assert second.loc["CLSK", "event_type"] == "new"
    assert second.loc["MSFT", "event_type"] == "exit"
    assert int(second.loc["CLSK", "position_rank"]) == 2
    assert float(second.loc["CLSK", "manager_stake_to_float"]) > 0.0
    assert second.loc["CLSK", "market_cap_bucket"] == "small"
    assert bool(second.loc["CLSK", "research_only"]) is True
    assert bool(second.loc["CLSK", "production_activation_allowed"]) is False


def test_initial_period_is_not_false_new_signal() -> None:
    events = build_position_events(holdings_fixture(), metadata_fixture())
    first = events[events["report_period"].eq("2025-12-31")]
    assert set(first["event_type"]) == {"initial"}
    assert first["history_boundary"].astype(bool).all()


def test_manager_universe_metadata_is_attached() -> None:
    manager_universe = pd.DataFrame(
        [
            {
                "label": "ATREIDES",
                "manager_name": "Atreides Management LP",
                "cik10": "0001067983",
                "user_priority": 6,
                "external_performance_2y": 1.744,
                "allocation_tier": "growth_hedge",
            }
        ]
    )
    events = build_position_events(holdings_fixture(), metadata_fixture(), manager_universe)
    latest = events[events["report_period"].eq("2026-03-31")]
    assert float(latest["manager_rank"].max()) == 6.0
    assert float(latest["external_performance_2y"].max()) == 1.744
    assert set(latest["allocation_tier"]) == {"growth_hedge"}
    assert set(latest["manager_name"]) == {"Atreides Management LP"}


def test_restatement_replaces_base_snapshot_in_position_events() -> None:
    holdings = holdings_fixture().iloc[:2].copy()
    holdings["source_accession"] = "base"
    holdings["form_type"] = "13F-HR"
    holdings["amendment_type"] = ""
    restatement = holdings.iloc[[0]].copy()
    restatement["source_accession"] = "restatement"
    restatement["form_type"] = "13F-HR/A"
    restatement["amendment_type"] = "RESTATEMENT"
    restatement["accepted_at"] = "2026-02-17T18:00:00Z"
    restatement["available_from"] = "2026-02-17T18:00:00Z"
    events = build_position_events(pd.concat([holdings, restatement], ignore_index=True), metadata_fixture())
    base_events = events[events["available_from"].eq("2026-02-14T18:00:00Z")]
    assert set(base_events["ticker"]) == {"AAPL", "MSFT"}
    restatement_events = events[events["available_from"].eq("2026-02-17T18:00:00Z")]
    assert set(restatement_events["ticker"]) == {"MSFT"}
    assert restatement_events.iloc[0]["event_type"] == "exit"
    assert float(restatement_events.iloc[0]["previous_shares"]) == 50_000.0
    assert float(restatement_events.iloc[0]["shares"]) == 0.0


def test_late_restatement_keeps_earlier_disclosure_events() -> None:
    holdings = holdings_fixture().copy()
    holdings["source_accession"] = holdings["report_period"].map(
        {"2025-12-31": "prior-base", "2026-03-31": "current-base"}
    )
    holdings["form_type"] = "13F-HR"
    holdings["amendment_type"] = ""
    restatement = holdings[holdings["report_period"].eq("2025-12-31") & holdings["ticker_mapped"].eq("AAPL")].copy()
    restatement["source_accession"] = "late-prior-restatement"
    restatement["form_type"] = "13F-HR/A"
    restatement["amendment_type"] = "RESTATEMENT"
    restatement["accepted_at"] = "2026-06-01T18:00:00Z"
    restatement["available_from"] = "2026-06-01T18:00:00Z"
    added_then_exited = restatement.copy()
    added_then_exited["ticker_mapped"] = "NVDA"
    added_then_exited["cusip"] = "67066G104"
    added_then_exited["issuer_name"] = "NVIDIA Corp"
    restatement = pd.concat([restatement, added_then_exited], ignore_index=True)
    events = build_position_events(pd.concat([holdings, restatement], ignore_index=True), metadata_fixture())
    assert set(events[events["available_from"].eq("2026-02-14T18:00:00Z")]["ticker"]) == {"AAPL", "MSFT"}
    assert set(events[events["available_from"].eq("2026-05-15T18:00:00Z")]["ticker"]) == {"AAPL", "CLSK", "MSFT"}
    late = events[events["available_from"].eq("2026-06-01T18:00:00Z")]
    assert set(late["ticker"]) == {"NVDA"}
    assert late.iloc[0]["event_type"] == "exit"
    assert late.iloc[0]["report_period"] == "2026-03-31"
    assert float(late.iloc[0]["previous_shares"]) > 0.0
    assert float(late.iloc[0]["shares"]) == 0.0


def test_cli_writes_pit_and_latest_outputs() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="13f_events_"))
    try:
        holdings = tmp / "holdings.parquet"
        metadata = tmp / "metadata.csv"
        pit = tmp / "data_pit" / "sec" / "13f_position_events.parquet"
        out = tmp / "outputs" / "13f_position_events"
        holdings_fixture().to_parquet(holdings, index=False)
        metadata_fixture().to_csv(metadata, index=False)
        payload = run(
            type(
                "Args",
                (),
                {
                    "holdings": str(holdings),
                    "metadata": str(metadata),
                    "pit_output": str(pit),
                    "output_dir": str(out),
                },
            )()
        )
        assert payload["status"] == "completed"
        assert payload["schema_version"] == "13f-position-events-v2"
        assert payload["available_from_before_accepted_at"] == 0
        assert pit.exists()
        assert (out / "latest.csv").exists()
        latest = pd.read_csv(out / "latest.csv")
        assert set(latest["event_type"]) == {"add", "new", "exit"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_event_builder_detects_add_new_and_exit()
    test_initial_period_is_not_false_new_signal()
    test_manager_universe_metadata_is_attached()
    test_restatement_replaces_base_snapshot_in_position_events()
    test_late_restatement_keeps_earlier_disclosure_events()
    test_cli_writes_pit_and_latest_outputs()
    print("sec_13f_position_event_builder_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
