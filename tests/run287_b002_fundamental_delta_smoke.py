#!/usr/bin/env python3
"""Smoke tests for the B002 exact-accepted fundamental delta."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_b002_fundamental_delta import (build, build_exact_fundamental_panel, select_accession_field_records)  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path), "exists": True}


def fact(
    *,
    start: str | None,
    end: str,
    value: float,
    accession: str,
    fp: str,
    form: str,
    filed: str,
) -> dict:
    output = {
        "end": end,
        "val": value,
        "accn": accession,
        "fy": 2026,
        "fp": fp,
        "form": form,
        "filed": filed,
    }
    if start:
        output["start"] = start
    return output


def fixture(
    root: Path,
    *,
    missing_expected_index: bool = False,
    empty_expected_facts: bool = False,
) -> argparse.Namespace:
    output = root / "output"
    cik = "0000000001"
    ticker = "AAA"
    periods = [
        ("2025-01-01", "2025-03-31", "Q1", "10-Q", "0000000001-25-000001"),
        ("2025-04-01", "2025-06-30", "Q2", "10-Q", "0000000001-25-000002"),
        ("2025-07-01", "2025-09-30", "Q3", "10-Q", "0000000001-25-000003"),
        ("2025-01-01", "2025-12-31", "FY", "10-K", "0000000001-26-000001"),
        ("2026-01-01", "2026-03-31", "Q1", "10-Q", "0000000001-26-000002"),
    ]
    accepted = [
        "2025-04-20T20:00:00Z",
        "2025-07-20T20:00:00Z",
        "2025-10-20T20:00:00Z",
        "2026-02-20T20:00:00Z",
        "2026-04-20T20:00:00Z",
    ]
    amendment_accession = "0000000001-26-000003"
    amendment_accepted = "2026-04-21T20:00:00Z"
    future_accession = "0000000001-26-000004"
    future_accepted = "2026-08-01T20:00:00Z"
    index_rows = []
    for (_, end, _, form, accession), accepted_at in zip(periods, accepted):
        index_rows.append(
            {
                "ticker": ticker,
                "cik10": cik,
                "accession_number": accession,
                "form_type": form,
                "filing_date": accepted_at[:10],
                "accepted_at": accepted_at,
                "available_from": accepted_at,
                "period_of_report": end,
            }
        )
    index_rows.extend(
        [
            {
                "ticker": ticker,
                "cik10": cik,
                "accession_number": amendment_accession,
                "form_type": "10-Q/A",
                "filing_date": "2026-04-21",
                "accepted_at": amendment_accepted,
                "available_from": amendment_accepted,
                "period_of_report": "2026-03-31",
            },
            {
                "ticker": ticker,
                "cik10": cik,
                "accession_number": future_accession,
                "form_type": "10-Q/A",
                "filing_date": "2026-08-01",
                "accepted_at": future_accepted,
                "available_from": future_accepted,
                "period_of_report": "2026-03-31",
            },
        ]
    )
    if missing_expected_index:
        index_rows = [
            row for row in index_rows if row["accession_number"] != amendment_accession
        ]
    sec_index = root / "sec_index.parquet"
    pd.DataFrame(index_rows).to_parquet(sec_index, index=False)

    tags = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": [],
        "OperatingIncomeLoss": [],
        "NetIncomeLoss": [],
        "Assets": [],
        "Liabilities": [],
        "CommonStockSharesOutstanding": [],
    }
    for index, (start, end, fp, form, accession) in enumerate(periods):
        days_start = "2025-01-01" if fp == "FY" else start
        tags["RevenueFromContractWithCustomerExcludingAssessedTax"].append(
            fact(
                start=days_start,
                end=end,
                value=100.0 + 10.0 * index,
                accession=accession,
                fp=fp,
                form=form,
                filed=accepted[index][:10],
            )
        )
        tags["OperatingIncomeLoss"].append(
            fact(
                start=days_start,
                end=end,
                value=20.0 + index,
                accession=accession,
                fp=fp,
                form=form,
                filed=accepted[index][:10],
            )
        )
        tags["NetIncomeLoss"].append(
            fact(
                start=days_start,
                end=end,
                value=10.0 + index,
                accession=accession,
                fp=fp,
                form=form,
                filed=accepted[index][:10],
            )
        )
        for tag, value in [
            ("Assets", 1000.0 + index),
            ("Liabilities", 400.0 + index),
            ("CommonStockSharesOutstanding", 50.0 + index),
        ]:
            tags[tag].append(
                fact(
                    start=None,
                    end=end,
                    value=value,
                    accession=accession,
                    fp=fp,
                    form=form,
                    filed=accepted[index][:10],
                )
            )

    for accession, form, filed, revenue in [
        (amendment_accession, "10-Q/A", "2026-04-21", 999.0),
        (future_accession, "10-Q/A", "2026-01-01", 7777.0),
    ]:
        if empty_expected_facts and accession == amendment_accession:
            continue
        for tag, value, has_start in [
            ("RevenueFromContractWithCustomerExcludingAssessedTax", revenue, True),
            ("OperatingIncomeLoss", 99.0, True),
            ("NetIncomeLoss", 88.0, True),
            ("Assets", 1200.0, False),
            ("Liabilities", 450.0, False),
            ("CommonStockSharesOutstanding", 55.0, False),
        ]:
            tags[tag].append(
                fact(
                    start="2026-01-01" if has_start else None,
                    end="2026-03-31",
                    value=value,
                    accession=accession,
                    fp="Q1",
                    form=form,
                    filed=filed,
                )
            )
    # Unmatched accession with an early filed date must never become available.
    tags["Assets"].append(
        fact(
            start=None,
            end="2026-03-31",
            value=99999.0,
            accession="0000000001-26-UNMATCHED",
            fp="Q1",
            form="10-Q",
            filed="2026-01-01",
        )
    )
    # Comparative period in the amendment must be rejected by period matching.
    if not empty_expected_facts:
        tags["Assets"].append(
            fact(
                start=None,
                end="2025-12-31",
                value=88888.0,
                accession=amendment_accession,
                fp="Q1",
                form="10-Q/A",
                filed="2026-04-21",
            )
        )
    facts_payload = {
        "entityName": "Fixture Corp",
        "facts": {
            "us-gaap": {
                tag: {
                    "units": {
                        "shares" if tag == "CommonStockSharesOutstanding" else "USD": values
                    }
                }
                for tag, values in tags.items()
            }
        },
    }
    companyfacts = root / "companyfacts.zip"
    with zipfile.ZipFile(companyfacts, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"CIK{cik}.json", json.dumps(facts_payload))

    ranked = root / "ranked.csv"
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "cik": 1,
                "feature_date": "2026-03-31",
                "px": 100.0,
                "mktcap": 5000.0,
                "revenues_ttm": 400.0,
                "op_income_ttm": 80.0,
                "net_income_ttm": 40.0,
                "assets": 1004.0,
                "liabilities": 404.0,
                "sales_growth_yoy": 0.0,
            }
        ]
    ).to_csv(ranked, index=False)
    delta_audit = root / "delta_audit.csv"
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "ticker_parity_pass": True,
                "fundamental_recompute_required": True,
                "event_actual_recompute_required": True,
                "composite_technical_eligible": False,
                "frozen_feature_date": "2026-04-21",
                "new_statement_filing_count": 1,
                "latest_new_form": "8-K",
                "latest_new_accession_number": "0000000001-26-000099",
            }
        ]
    ).to_csv(delta_audit, index=False)
    delta_latest = root / "delta_latest.csv"
    pd.DataFrame([{"ticker": ticker, "technical_px": 100.0}]).to_csv(
        delta_latest, index=False
    )
    technical_manifest = root / "technical.json"
    write_json(
        technical_manifest,
        {
            "status": "TECHNICAL_PARITY_READY_MACRO_FUNDAMENTAL_BLOCKED",
            "valuation_price_cutoff_date": "2026-07-10",
            "decision_ranking_allowed": False,
            "network_requests_executed": 0,
            "source_inputs_mutated": False,
            "fullrun_executed": False,
            "delta_eligibility": {"composite_context_ticker_count": 1},
            "outputs": {
                "delta_ticker_audit": record(delta_audit),
                "delta_latest_technical_features": record(delta_latest),
            },
            "source_inputs": {"ranked_universe": record(ranked)},
        },
    )
    event_audit = root / "event_audit.csv"
    pd.DataFrame([{"ticker": ticker, "accession_number": "8k-fixture"}]).to_csv(
        event_audit, index=False
    )
    model_meta = root / "model_meta.json"
    write_json(
        model_meta,
        {"model_features": ["sales_growth_yoy", "op_margin_ttm", "ep_ttm"]},
    )
    event_manifest = root / "event.json"
    write_json(
        event_manifest,
        {
            "status": "READY_8K_FROZEN_SCHEMA_NOOP_SIDECAR",
            "valuation_price_cutoff_date": "2026-07-10",
            "event_actual_refresh_gate_resolved": True,
            "network_requests_executed": 0,
            "source_inputs_mutated": False,
            "fullrun_executed": False,
            "outputs": {"event_actual_audit": record(event_audit)},
            "source_inputs": {"model_meta": record(model_meta)},
        },
    )
    return argparse.Namespace(
        technical_manifest=str(technical_manifest),
        event_manifest=str(event_manifest),
        companyfacts_zip=str(companyfacts),
        sec_index=str(sec_index),
        model_meta=str(model_meta),
        expected_statement_tickers=ticker,
        expected_promotion_tickers=ticker,
        expected_post_gate_context_count=2,
        decision_time_utc="2026-07-11T00:00:00Z",
        output_dir=str(output),
    )


def test_exact_acceptance_amendment_and_missing_neutral() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        source_hashes = {
            "companyfacts": sha(Path(args.companyfacts_zip)),
            "index": sha(Path(args.sec_index)),
        }
        payload = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert payload["status"] == "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE", (
            payload.get("blockers")
        )
        assert payload["fundamental_refresh_gate_resolved"] is True
        assert payload["technical_context_promotion_allowed"] is True
        assert payload["coverage"]["future_selected_row_count"] == 0
        assert payload["coverage"]["filed_fallback_used_count"] == 0
        assert payload["promotion"]["newly_promoted_tickers"] == ["AAA"]
        assert payload["promotion"]["post_gate_context_ticker_count"] == 2
        overrides = pd.read_csv(root / "output" / "latest_fundamental_overrides.csv")
        assert overrides.loc[0, "accession_number"] == "0000000001-26-000003"
        assert overrides.loc[0, "revenues"] == 999.0
        assert pd.isna(overrides.loc[0, "capex_ttm"])
        assert bool(overrides.loc[0, "exact_acceptance"])
        audit = pd.read_csv(root / "output" / "ticker_fundamental_audit.csv")
        assert audit.loc[0, "technical_latest_new_form"] == "8-K"
        assert (
            audit.loc[0, "technical_latest_new_accession_number"]
            == "0000000001-26-000099"
        )
        assert (
            audit.loc[0, "expected_accession_number"]
            == "0000000001-26-000003"
        )
        assert audit.loc[0, "future_available_fact_count"] > 0
        assert audit.loc[0, "unmatched_accession_fact_count"] > 0
        assert audit.loc[0, "period_mismatch_fact_count"] > 0
        assert source_hashes == {
            "companyfacts": sha(Path(args.companyfacts_zip)),
            "index": sha(Path(args.sec_index)),
        }


def test_current_only_statement_uses_pinned_universe_identity_and_sec_baseline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        technical_path = Path(args.technical_manifest)
        technical = json.loads(technical_path.read_text(encoding="utf-8"))
        ranked_path = Path(technical["source_inputs"]["ranked_universe"]["path"])
        ranked = pd.read_csv(ranked_path)
        ranked.loc[:, "ticker"] = "ZZZ"
        ranked.to_csv(ranked_path, index=False)

        delta_path = Path(technical["outputs"]["delta_ticker_audit"]["path"])
        delta = pd.read_csv(delta_path)
        delta["frozen_feature_date"] = ""
        delta["sec_baseline_feature_date"] = "2026-04-21"
        delta["frozen_reference_available"] = False
        delta["parity_applicable"] = False
        delta.to_csv(delta_path, index=False)

        universe = root / "universe.csv"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "cik10": "0000000001",
                    "is_equity_issuer": True,
                    "cik_mapping_status": "resolved_sec_company_tickers",
                }
            ]
        ).to_csv(universe, index=False)
        args.universe_snapshot = str(universe)
        args.expected_universe_snapshot_sha256 = sha(universe)

        technical["source_inputs"]["ranked_universe"] = record(ranked_path)
        technical["outputs"]["delta_ticker_audit"] = record(delta_path)
        technical["delta_eligibility"]["no_frozen_reference_tickers"] = ["AAA"]
        write_json(technical_path, technical)

        payload = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert payload["status"] == "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE", (
            payload.get("blockers")
        )
        assert payload["coverage"]["current_only_identity_ticker_count"] == 1
        audit = pd.read_csv(root / "output" / "ticker_fundamental_audit.csv")
        assert audit.loc[0, "identity_source"] == "universe_snapshot_identity_only"
        assert audit.loc[0, "baseline_feature_date"] == "2026-04-21"
        assert audit.loc[0, "baseline_feature_date_source"] == (
            "sec_baseline_feature_date"
        )
        assert audit.loc[0, "cik10"] == 1


def test_exact_balance_identity_derives_missing_total_liabilities() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        companyfacts = Path(args.companyfacts_zip)
        with zipfile.ZipFile(companyfacts) as zf:
            member = zf.namelist()[0]
            facts_payload = json.loads(zf.read(member))
        tags = facts_payload["facts"]["us-gaap"]
        liability_values = tags.pop("Liabilities")["units"]["USD"]
        liability_lookup = {
            (row.get("accn"), row.get("end"), row.get("form")): row.get("val")
            for row in liability_values
        }
        assets = tags["Assets"]["units"]["USD"]
        liabilities_and_equity = [dict(row) for row in assets]
        stockholders_equity = []
        for row in assets:
            key = (row.get("accn"), row.get("end"), row.get("form"))
            liability = liability_lookup.get(key)
            if liability is None:
                continue
            equity_row = dict(row)
            equity_row["val"] = float(row["val"]) - float(liability)
            stockholders_equity.append(equity_row)
        tags["LiabilitiesAndStockholdersEquity"] = {
            "units": {"USD": liabilities_and_equity}
        }
        tags["StockholdersEquity"] = {"units": {"USD": stockholders_equity}}
        with zipfile.ZipFile(
            companyfacts, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            zf.writestr(member, json.dumps(facts_payload))

        payload = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert payload["status"] == "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE", (
            payload.get("blockers")
        )
        assert payload["coverage"]["liabilities_derivation_ticker_count"] == 1
        audit = pd.read_csv(root / "output" / "ticker_fundamental_audit.csv")
        assert bool(audit.loc[0, "liabilities_derivation_applied"])
        assert audit.loc[0, "liabilities_derivation_source"] == (
            "exact_liabilities_and_equity_minus_stockholders_equity"
        )
        overrides = pd.read_csv(root / "output" / "latest_fundamental_overrides.csv")
        assert overrides.loc[0, "liabilities"] == 450.0


def test_missing_expected_exact_accession_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = build(
            fixture(root, missing_expected_index=True),
            observed_at_utc="2026-07-11T00:00:00Z",
        )
        assert payload["status"] == "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA"
        assert any(
            "new_statement_index_count" in item for item in payload["blockers"]
        )
        assert payload["fundamental_refresh_gate_resolved"] is False
        assert payload["decision_ranking_allowed"] is False


def test_empty_exact_accession_requires_explicit_missing_neutral_policy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        blocked = build(
            fixture(root, empty_expected_facts=True),
            observed_at_utc="2026-07-11T00:00:00Z",
        )
        assert blocked["status"] == "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA"
        assert any(
            "expected_accession_has_no_selected_components" in item
            for item in blocked["blockers"]
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root, empty_expected_facts=True)
        args.allow_empty_expected_accession_neutral = True
        payload = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert payload["status"] == "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE"
        assert payload["coverage"]["missing_neutral_override_count"] == 1
        assert payload["promotion"]["newly_promoted_tickers"] == ["AAA"]
        audit = pd.read_csv(root / "output" / "ticker_fundamental_audit.csv")
        assert audit.loc[0, "expected_accession_companyfacts_fact_count"] == 0
        assert bool(audit.loc[0, "missing_neutral_override_applied"])
        overrides = pd.read_csv(root / "output" / "latest_fundamental_overrides.csv")
        assert overrides.loc[0, "accession_number"] == "0000000001-26-000003"
        assert overrides.loc[0, "component_coverage"] == 0
        assert pd.isna(overrides.loc[0, "sales_growth_yoy"])
        assert "capex_cum_value" in overrides.columns
        assert pd.isna(overrides.loc[0, "capex_cum_value"])
        assert "op_margin_calc_ttm" in overrides.columns
        assert pd.isna(overrides.loc[0, "op_margin_calc_ttm"])
        assert overrides.loc[0, "current_price_live"] == 100.0
        assert pd.isna(overrides.loc[0, "mktcap"])
        assert overrides.loc[0, "mktcap_missing_reason"] == "missing_or_invalid_shares_unit"


def remove_expected_operating_income(args: argparse.Namespace) -> None:
    companyfacts = Path(args.companyfacts_zip)
    with zipfile.ZipFile(companyfacts) as zf:
        member = zf.namelist()[0]
        payload = json.loads(zf.read(member))
    payload["facts"]["us-gaap"].pop("OperatingIncomeLoss")
    with zipfile.ZipFile(
        companyfacts, "w", compression=zipfile.ZIP_DEFLATED
    ) as zf:
        zf.writestr(member, json.dumps(payload))


def test_declared_single_partial_core_field_is_missing_neutral() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        remove_expected_operating_income(args)
        blocked = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert blocked["status"] == "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA"
        assert "AAA:core_component_coverage:4/5" in blocked["blockers"]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        remove_expected_operating_income(args)
        args.expected_partial_core_missing_neutral = ["AAA=op_income_ttm"]
        payload = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert payload["status"] == "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE", (
            payload.get("blockers")
        )
        assert payload["coverage"]["partial_core_missing_neutral_count"] == 1
        audit = pd.read_csv(root / "output" / "ticker_fundamental_audit.csv")
        assert bool(audit.loc[0, "partial_core_missing_neutral_applied"])
        assert audit.loc[0, "partial_core_missing_fields"] == "op_income_ttm"
        overrides = pd.read_csv(root / "output" / "latest_fundamental_overrides.csv")
        assert pd.isna(overrides.loc[0, "op_income_ttm"])
        assert "partial_core_missing_neutral" not in overrides.columns

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args = fixture(root)
        remove_expected_operating_income(args)
        args.expected_partial_core_missing_neutral = ["AAA=net_income_ttm"]
        mismatched = build(args, observed_at_utc="2026-07-11T00:00:00Z")
        assert mismatched["status"] == "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA"
        assert any(
            "partial_core_missing_neutral_mismatch" in item
            for item in mismatched["blockers"]
        )


class NativeFinancialContextTests(unittest.TestCase):
    """Synthetic boundaries; unittest checks remain active under python -O."""
    @staticmethod
    def row(**changes):
        row = dict(ticker="SYN", cik="0000000001", accession_number="a1", field_name="revenues",
            value=100.0, unit="EUR", start=pd.Timestamp("2026-01-01"), period=pd.Timestamp("2026-03-31"),
            accepted=pd.Timestamp("2026-04-20"), fy=2026, fp="Q1", frame=None, form="10-Q",
            fiscal_period="Q1", semantic_rank=0, source_namespace="ifrs-full", source_tag="Revenue",
            context_dimensions=None, duration_days=90)
        row.update(changes)
        return row

    @staticmethod
    def price_context(**changes):
        out = dict(price_currency="USD", price_asof="2026-07-10T20:00:00Z",
            valuation_asof="2026-07-11T00:00:00Z", shares_basis="ordinary", price_share_basis="ordinary",
            share_basis_status="VERIFIED", share_basis_reference="synthetic-reviewed-basis",
            share_basis_asof="2026-07-01T00:00:00Z")
        out.update(changes)
        return out

    @staticmethod
    def financial(currency="USD", income=50.0):
        values = dict(cik="0000000001", financial_metadata_version="native-unit-fiscal-v1", shares=100.0,
            shares_unit="shares", net_income_ttm=income, net_income_ttm_unit=currency,
            revenues_ttm=500.0, revenues_ttm_unit=currency, ocf_ttm=80.0, ocf_ttm_unit=currency,
            capex_ttm=20.0, capex_ttm_unit=currency, fcf_ttm=60.0, fcf_ttm_unit=currency,
            assets=1000.0, assets_unit=currency, liabilities=400.0, liabilities_unit=currency)
        for field in ("shares", "net_income_ttm", "revenues_ttm", "ocf_ttm", "capex_ttm", "fcf_ttm", "assets", "liabilities"):
            start = "2025-01-01" if field.endswith("_ttm") else None
            context = dict(identities={"cik":"0000000001"}, scope={"dimensions":None}, period_start=start, period_end="2025-12-31")
            values[field + "_financial_context"] = json.dumps(context)
            values[field + "_provenance"] = json.dumps([dict(cik="0000000001", context_dimensions=None,
                start=start, period="2025-12-31", source_tag=field)])
        return pd.Series(values)

    def test_native_usd_preference_keeps_original_foreign_proof(self):
        rows = [self.row(unit="EUR"), self.row(unit="USD", value=120.0)]
        for order in (rows, rows[::-1]):
            selected = select_accession_field_records(pd.DataFrame(order)).iloc[0]
            self.assertEqual((selected["unit"], selected["value"]), ("USD", 120.0))
            self.assertEqual({p["unit"] for p in json.loads(selected["fact_provenance"])}, {"USD", "EUR"})

    def test_ambiguous_unit_and_value_conflicts_are_order_independent(self):
        for changed, reason in ((dict(unit="JPY"), "conflicting_native_units"),
            (dict(value=101.0), "conflicting_native_facts_or_contexts")):
            rows = [self.row(), self.row(**changed)]
            panels = []
            for order in (rows, rows[::-1]):
                selected = select_accession_field_records(pd.DataFrame(order))
                self.assertTrue(pd.isna(selected.iloc[0]["value"]))
                self.assertEqual(selected.iloc[0]["missing_reason"], reason)
                panel = build_exact_fundamental_panel(selected)
                self.assertEqual(len(panel), 1)
                self.assertTrue(pd.isna(panel.iloc[0]["revenues"]))
                self.assertIn("JPY" if "unit" in changed else "101.0", panel.iloc[0]["revenues_fact_provenance"])
                panels.append(panel)
            pd.testing.assert_frame_equal(panels[0], panels[1])

    def test_shares_only_exact_native_unit(self):
        import r1000_pipeline as pipe
        self.assertEqual(pipe.preferred_companyfacts_unit_keys("shares", ["USD/shares", "pure", "shares", "USD"]), ["shares"])
        self.assertEqual(pipe.preferred_companyfacts_unit_keys("shares", ["USD/shares", "pure"]), [])
        selected = select_accession_field_records(pd.DataFrame([self.row(field_name="shares", unit="USD/shares")])).iloc[0]
        self.assertTrue(pd.isna(selected["value"]))
        self.assertEqual(selected["missing_reason"], "invalid_shares_unit")

    def test_native_foreign_metadata_survives_pivot_and_disk_readback(self):
        selected = select_accession_field_records(pd.DataFrame([self.row(field_name="assets", start=pd.NaT)]))
        panel = build_exact_fundamental_panel(selected)
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv", "parquet"):
                path = Path(tmp) / ("panel." + suffix)
                if suffix == "csv":
                    panel.to_csv(path, index=False)
                    reread = pd.read_csv(path)
                else:
                    panel.to_parquet(path, index=False)
                    reread = pd.read_parquet(path)
                self.assertEqual(reread.loc[0, "assets"], 100.0)
                self.assertEqual(reread.loc[0, "assets_unit"], "EUR")
                self.assertEqual(reread.loc[0, "assets_accession_number"], "a1")
                self.assertEqual(reread.loc[0, "assets_fact_provenance"], panel.loc[0, "assets_fact_provenance"])

    def test_ytd_requires_compatible_currency_start_context_and_clock(self):
        import r1000_pipeline as pipe
        first = self.row()
        second = self.row(accession_number="a2", fp="Q2", period=pd.Timestamp("2026-06-30"),
            duration_days=181, value=250.0, semantic_rank=1, accepted=pd.Timestamp("2026-07-20"))
        positive = pipe.companyfacts_quarterly_flows(pd.DataFrame([first, second])).iloc[-1]
        self.assertEqual(positive["flow"], 150.0)
        self.assertIn("a1", positive["flow_provenance"])
        self.assertIn("a2", positive["flow_provenance"])
        for change, reason in ((dict(unit="USD"), "incompatible_ytd_unit"),
            (dict(start=pd.Timestamp("2026-01-02")), "incompatible_ytd_fiscal_start"),
            (dict(context_dimensions="segment-x"), "incompatible_ytd_context_parent"),
            (dict(accepted=pd.Timestamp("2026-04-01")), "future_ytd_parent")):
            bad = {**second, **change}
            row = pipe.companyfacts_quarterly_flows(pd.DataFrame([first, bad])).iloc[-1]
            self.assertTrue(pd.isna(row["flow"]))
            self.assertEqual(row["flow_missing_reason"], reason)
            self.assertEqual(row["cum_value"], 250.0)  # native YTD remains observed

    def test_annual_preference_53_week_14_week_q4_loss_and_zero(self):
        import r1000_pipeline as pipe
        start = pd.Timestamp("2025-08-31")
        q3 = self.row(start=start, period=pd.Timestamp("2026-05-30"), fp="Q3", value=100.0,
            duration_days=273, semantic_rank=1, accepted=pd.Timestamp("2026-06-20"))
        annual = self.row(start=start, period=pd.Timestamp("2026-09-05"), fp="FY", form="10-K",
            value=80.0, duration_days=371, accession_number="annual", accepted=pd.Timestamp("2026-10-01"))
        short = {**annual, "start": pd.Timestamp("2026-01-01"), "duration_days": 248, "semantic_rank": 2, "value": 999.0}
        selected = select_accession_field_records(pd.DataFrame([annual, short]))
        self.assertEqual(selected.iloc[0]["value"], 80.0)
        flows = pipe.companyfacts_quarterly_flows(pd.DataFrame([q3, annual]))
        self.assertEqual(flows.iloc[-1]["flow"], -20.0)
        self.assertEqual((flows.iloc[-1]["period"] - flows.iloc[-1]["flow_start"]).days + 1, 98)
        zero = pipe.companyfacts_quarterly_flows(pd.DataFrame([q3, {**annual, "value": 100.0}])).iloc[-1]
        self.assertEqual(zero["flow"], 0.0)
        refused = pipe.companyfacts_quarterly_flows(pd.DataFrame([q3, short])).iloc[-1]
        self.assertTrue(pd.isna(refused["flow"]))
        self.assertTrue(pd.isna(refused["cum_value"]))
        self.assertEqual(refused["flow_missing_reason"], "short_fy_without_fiscal_grid_proof")

    def test_ttm_cannot_roll_mixed_currency_or_short_fy(self):
        rows = []
        for q, start, end in ((1,"2026-01-01","2026-03-31"),(2,"2026-04-01","2026-06-30"),
            (3,"2026-07-01","2026-09-30"),(4,"2026-10-01","2026-12-31")):
            rows.append(self.row(fp="Q"+str(q), start=pd.Timestamp(start), period=pd.Timestamp(end),
                accepted=pd.Timestamp(end)+pd.Timedelta(days=20), accession_number="q"+str(q),
                duration_days=91, unit="USD" if q == 4 else "EUR"))
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertTrue(pd.isna(panel.iloc[-1]["revenues_ttm"]))
        short = self.row(fp="FY", form="10-K", start=pd.Timestamp("2026-01-01"), period=pd.Timestamp("2026-09-30"), duration_days=273)
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame([short])))
        self.assertTrue(pd.isna(panel.iloc[0]["revenues_ttm"]))

    def test_verified_native_and_fx_valuations_preserve_loss_zero_and_missing(self):
        from r1000_features import native_valuation_overrides
        for income in (50.0, 0.0, -50.0):
            row = native_valuation_overrides(self.financial(income=income), technical_price=10.0, price_context=self.price_context())
            self.assertEqual(row["mktcap"], 1000.0)
            self.assertEqual(row["ep_ttm"], income / 1000.0)
        foreign = self.financial("EUR")
        unknown = native_valuation_overrides(foreign, technical_price=10.0, price_context=self.price_context())
        self.assertTrue(pd.isna(unknown["ep_ttm"]))
        self.assertEqual(unknown["net_income_ttm"], 50.0)
        self.assertEqual(unknown["net_income_ttm_unit"], "EUR")
        fx = self.price_context(fx_status="VERIFIED", fx_reference="synthetic-fx", fx_rate=1.2,
            fx_from_currency="EUR", fx_to_currency="USD", fx_asof="2026-07-10T19:00:00Z", fx_valid_until="2026-07-10T21:00:00Z")
        self.assertEqual(native_valuation_overrides(foreign, technical_price=10.0, price_context=fx)["ep_ttm"], 0.06)
        for change in (dict(fx_from_currency="USD"), dict(fx_asof="2026-07-11T00:00:00Z"),
            dict(fx_valid_until="2026-07-10T18:00:00Z"), dict(fx_reference=None)):
            row = native_valuation_overrides(foreign, technical_price=10.0, price_context={**fx, **change})
            self.assertTrue(pd.isna(row["ep_ttm"]))
            self.assertEqual(row["mktcap"], 1000.0)

    def test_ads_requires_explicit_ratio_and_does_not_infer_from_price(self):
        from r1000_features import native_valuation_overrides
        context = self.price_context(price_share_basis="ADS")
        row = native_valuation_overrides(self.financial(), technical_price=10.0, price_context=context)
        self.assertTrue(pd.isna(row["mktcap"]))
        context.update(ordinary_shares_per_ads=5.0, ads_ratio_status="VERIFIED", ads_ratio_reference="synthetic-reviewed-ads", ads_ratio_asof="2026-07-01T00:00:00Z")
        row = native_valuation_overrides(self.financial(), technical_price=10.0, price_context=context)
        self.assertEqual(row["shares_effective"], 20.0)
        self.assertEqual(row["mktcap"], 200.0)
        context["share_basis_status"] = "UNKNOWN"
        self.assertTrue(pd.isna(native_valuation_overrides(self.financial(), technical_price=10.0, price_context=context)["mktcap"]))

    def test_combine_and_asof_do_not_splice_or_refill_refused_values(self):
        import r1000_pipeline as pipe
        primary = pd.DataFrame([dict(cik="0000000001", period=pd.Timestamp("2026-03-31"), accepted=pd.Timestamp("2026-04-20"),
            assets=float("nan"), assets_unit="EUR", assets_accession_number="primary", financial_metadata_version="native-unit-fiscal-v1")])
        secondary = primary.copy()
        secondary["assets"], secondary["assets_unit"], secondary["assets_accession_number"] = 999.0, "USD", "secondary"
        combined = pipe.combine_fund_panels(primary, secondary)
        self.assertTrue(pd.isna(combined.loc[0, "assets"]))
        self.assertEqual(combined.loc[0, "assets_accession_number"], "primary")
        base = pd.DataFrame(dict(ticker=["SYN", "UNKNOWN"], cik10=["0000000001", None], rebalance_date=["2026-05-01"]*2))
        joined = pipe.asof_join_fundamentals(base, combined)
        self.assertEqual(list(joined["ticker"]), ["SYN", "UNKNOWN"])
        self.assertEqual(joined.loc[joined["ticker"].eq("UNKNOWN"), "fundamental_missing_reason"].iloc[0], "unknown_issuer_identity")
        self.assertTrue(joined["assets"].isna().all())
        self.assertEqual(joined.loc[joined["ticker"].eq("SYN"), "assets_unit"].iloc[0], "EUR")

    def test_main_ingest_preserves_native_metadata_and_all_missing_requested_cik(self):
        import r1000_pipeline as pipe
        from r1000_config import EngineConfig
        payload = {"facts": {"ifrs-full": {"Assets": {"units": {"EUR": [dict(end="2026-03-31", filed="2026-04-20", form="20-F", val=100.0, accn="native-accession")]}}}}}
        with patch.object(pipe, "companyfacts_bulk_sources", return_value=[]), patch.object(pipe, "load_sec_companyfacts_json", side_effect=lambda cfg, paths, cik: payload if cik.endswith("1") else {}):
            panel = pipe.build_companyfacts_panel_for_ciks(EngineConfig(), {}, ["1", "2"])
        self.assertEqual(set(panel["cik"]), {"0000000001", "0000000002"})
        first = panel[panel["cik"].eq("0000000001")].iloc[0]
        self.assertEqual(first["assets_unit"], "EUR")
        self.assertEqual(first["assets_accession_number"], "native-accession")
        missing = panel[panel["cik"].eq("0000000002")].iloc[0]
        self.assertEqual(missing["candidate_ordinal"], 1)
        self.assertEqual(missing["fundamental_missing_reason"], "no_native_financial_facts")
        self.assertTrue(pd.isna(missing["assets"]))

    def test_live_and_main_valuation_fallbacks_do_not_resurrect_unknown(self):
        import r1000_pipeline as pipe
        import r1000_features as features
        row = self.financial("EUR").to_dict()
        row.update(ticker="SYN", mktcap=1000.0, mktcap_proxy=1000.0, px=10.0,
            current_price_live=10.0, ep_ttm=999.0, av_forward_pe=20.0, price_to_sales=3.0)
        frame = pd.DataFrame([row])
        for call in (pipe.compute_valuation_columns, features.compute_live_factor_columns):
            with patch.object(features, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()):
                result = call(frame).iloc[0]
            self.assertTrue(pd.isna(result["ep_ttm"]))
            self.assertTrue(pd.isna(result["mktcap"]))
            self.assertTrue(pd.isna(result["shares_effective"]))
            self.assertTrue(pd.isna(result["forward_pe_final"]))
        frame = pd.DataFrame([{**row, **self.price_context()}])
        with patch.object(features, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()):
            result = features.compute_live_factor_columns(frame).iloc[0]
        self.assertEqual(result["mktcap"], 1000.0)
        self.assertTrue(pd.isna(result["ep_ttm"]))  # no EUR->USD FX proof
        self.assertTrue(pd.isna(result["earnings_yield_recomputed"]))


    def test_ttm_valid_52_week_rolling_and_cumulative_comparison_lineage(self):
        import r1000_features as features
        import r1000_pipeline as pipe
        rows = []
        for q, start, end in ((1,"2026-01-01","2026-03-31"),(2,"2026-04-01","2026-06-30"),
            (3,"2026-07-01","2026-09-30"),(4,"2026-10-01","2026-12-31")):
            rows.append(self.row(fp="Q"+str(q), start=pd.Timestamp(start), period=pd.Timestamp(end),
                accepted=pd.Timestamp(end)+pd.Timedelta(days=20), accession_number="q"+str(q), duration_days=91))
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertEqual(panel.iloc[-1]["revenues_ttm"], 400.0)
        self.assertEqual(panel.iloc[-1]["revenues_ttm_unit"], "EUR")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ttm.parquet"
            panel.to_parquet(path, index=False)
            readback = pd.read_parquet(path)
            self.assertEqual(readback.iloc[-1]["revenues_ttm_provenance"], panel.iloc[-1]["revenues_ttm_provenance"])
            self.assertEqual(readback.iloc[-1]["revenues_ttm_unit"], "EUR")
        for accession in ("q1", "q2", "q3", "q4"):
            self.assertIn(accession, panel.iloc[-1]["revenues_ttm_provenance"])
        # Annual + current YTD - comparable prior YTD remains a valid fallback.
        rows = [self.row(start=pd.Timestamp("2025-01-01"), period=pd.Timestamp("2025-03-31"),
            accepted=pd.Timestamp("2025-04-20"), fy=2025, accession_number="prior-q1", value=20.0),
            self.row(start=pd.Timestamp("2025-01-01"), period=pd.Timestamp("2025-12-31"),
                accepted=pd.Timestamp("2026-02-20"), fy=2025, fp="FY", form="10-K", duration_days=365, accession_number="prior-fy", value=100.0),
            self.row(accession_number="current-q1", value=30.0)]
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertEqual(panel.iloc[-1]["revenues_ttm"], 110.0)
        for accession in ("prior-q1", "prior-fy", "current-q1"):
            self.assertIn(accession, panel.iloc[-1]["revenues_ttm_provenance"])
        rows[0]["unit"] = "JPY"
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertTrue(pd.isna(panel.iloc[-1]["revenues_ttm"]))

    def test_bad_units_missing_zero_and_future_evidence_remain_distinct(self):
        from r1000_features import native_valuation_overrides
        selected = select_accession_field_records(pd.DataFrame([self.row(unit="pure")])).iloc[0]
        self.assertTrue(pd.isna(selected["value"]))
        self.assertEqual(selected["missing_reason"], "invalid_monetary_unit")
        for change, reason in ((dict(share_basis_asof="2026-07-11T00:00:00Z"), "missing_or_future_share_basis_clock"),
            (dict(valuation_asof=None), "missing_valuation_cutoff_clock"),
            (dict(valuation_asof="2026-07-09T00:00:00Z"), "future_price_clock"),
            (dict(share_basis_reference="nan"), "missing_verified_share_basis_or_price_clock")):
            out = native_valuation_overrides(self.financial(), technical_price=10.0, price_context=self.price_context(**change))
            self.assertTrue(pd.isna(out["mktcap"]))
            self.assertEqual(out["mktcap_missing_reason"], reason)
        out = native_valuation_overrides(self.financial(income=float("nan")), technical_price=10.0, price_context=self.price_context())
        self.assertTrue(pd.isna(out["ep_ttm"]))
        self.assertEqual(out["ep_ttm_missing_reason"], "missing_native_amount")
        # Technical context cannot replace a native count/value.
        out = native_valuation_overrides(self.financial(), technical_price=10.0,
            price_context={**self.price_context(), "shares":99999.0, "net_income_ttm":99999.0})
        self.assertEqual(out["mktcap"], 1000.0)
        self.assertEqual(out["ep_ttm"], 0.05)


    def test_statement_repair_cannot_borrow_native_units_or_revive_refusal(self):
        import r1000_features as features
        from r1000_config import EngineConfig
        cfg = EngineConfig()
        cfg.alpha_vantage_api_key = "synthetic-test-only"
        cfg.latest_statement_repair_enabled = True
        row = self.financial().to_dict()
        row.update(ticker="SYN", assets=float("nan"), shares=float("nan"),
            gross_profit=float("nan"), revenues=100.0, cost_of_revenue=50.0,
            assets_missing_reason="conflicting_native_facts_or_contexts")
        with patch.object(features, "effective_latest_statement_repair_tickers", return_value=1), \
            patch.object(features, "load_or_fetch_alpha_vantage_statement_snapshot", return_value={"ticker":"SYN", "av_stmt_assets":999.0, "av_stmt_shares":888.0}), \
            patch.object(features.time, "sleep", return_value=None):
            out = features.repair_latest_statement_fundamentals(cfg, {}, pd.DataFrame([row])).iloc[0]
        self.assertTrue(pd.isna(out["assets"]))
        self.assertTrue(pd.isna(out["shares"]))
        self.assertTrue(pd.isna(out["gross_profit"]))
        self.assertEqual(out["assets_unit"], "USD")
        self.assertFalse(out["latest_statement_repair_used"])


    def test_growth_comparisons_require_the_same_native_currency(self):
        periods = pd.date_range("2025-03-31", periods=5, freq="QE-DEC")
        rows = [self.row(field_name="assets", start=pd.NaT, period=p, accepted=p+pd.Timedelta(days=20),
            accession_number="assets-"+str(i), value=100.0+i*10.0, unit="EUR" if i==0 else "USD") for i,p in enumerate(periods)]
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertTrue(pd.isna(panel.iloc[-1]["asset_growth_yoy"]))
        self.assertEqual(panel.iloc[0]["assets"], 100.0)
        self.assertEqual(panel.iloc[-1]["assets"], 140.0)
        rows[0]["unit"] = "USD"
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertAlmostEqual(panel.iloc[-1]["asset_growth_yoy"], 0.4)


    def test_balance_identity_uses_compatible_native_parent_evidence(self):
        total = self.row(field_name="liabilities_and_equity", start=pd.NaT, value=1000.0)
        equity = self.row(field_name="stockholders_equity_for_liabilities", start=pd.NaT, value=400.0)
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame([total,equity])))
        self.assertEqual(panel.iloc[0]["liabilities"], 600.0)
        self.assertEqual(panel.iloc[0]["liabilities_unit"], "EUR")
        self.assertIn("liabilities_and_equity_minus_stockholders_equity", panel.iloc[0]["liabilities_fact_provenance"])
        for change in (dict(unit="USD"), dict(accession_number="unrelated-parent"), dict(context_dimensions="segment-x")):
            bad = {**equity, **change}
            panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame([total,bad])))
            self.assertTrue(pd.isna(panel.iloc[0]["liabilities"]))


    def test_sparse_typed_lag_is_invariant_to_unrelated_missing_issuers(self):
        import r1000_features as features
        periods = pd.date_range("2025-03-31", periods=5, freq="QE-DEC")
        for mixed in (False, True):
            rows = []
            for i, period in enumerate(periods):
                row = self.financial().to_dict()
                context = json.loads(row["revenues_ttm_financial_context"])
                context.update(period_start=(period-pd.DateOffset(years=1)+pd.Timedelta(days=1)).strftime("%Y-%m-%d"), period_end=period.strftime("%Y-%m-%d"))
                row.update(period=period, revenues_ttm=200.0 if i==4 else 100.0,
                    revenues_ttm_unit="JPY" if mixed and i==0 else "USD",
                    revenues_ttm_financial_context=json.dumps(context))
                proof=json.loads(row["revenues_ttm_provenance"])
                proof[0].update(start=context["period_start"],period=context["period_end"])
                row["revenues_ttm_provenance"]=json.dumps(proof)
                rows.append(row)
            frame = pd.DataFrame(rows)
            missing = pd.DataFrame([dict(cik=str(i).zfill(10), period=pd.NaT,
                financial_metadata_version="native-unit-fiscal-v1") for i in range(2,10)])
            outputs = []
            for candidate in (frame, pd.concat([frame,missing],ignore_index=True)):
                lag, quarters = features._flexible_lag(candidate, "revenues_ttm", 4, tol=1)
                cagr = features._cagr_from_lag(candidate["revenues_ttm"],lag,quarters,require_positive=False)
                outputs.append(cagr.iloc[4])
            if mixed:
                self.assertTrue(all(pd.isna(value) for value in outputs))
            else:
                self.assertGreater(outputs[0], 0.99)
                self.assertEqual(outputs[0], outputs[1])
            # A typed row without an actual date has no positional substitute.
            frame["period"] = pd.NaT
            lag, _ = features._flexible_lag(frame,"revenues_ttm",4,tol=1)
            self.assertTrue(lag.isna().all())
            lag, _ = features._flexible_lag(frame.drop(columns="period"),"revenues_ttm",4,tol=1)
            self.assertTrue(lag.isna().all())

    def test_cross_field_scope_period_and_entity_must_match(self):
        from r1000_features import native_valuation_overrides
        base = self.financial()
        positive = native_valuation_overrides(base,technical_price=10.0,price_context=self.price_context())
        self.assertEqual(positive["fcf_ttm"],60.0)  # different measure tags are compatible
        self.assertEqual(positive["fcfy_ttm"],0.06)
        self.assertEqual(positive["equity_native"],600.0)
        for field, change in (("capex_ttm",dict(context_dimensions="segment-B")),
            ("capex_ttm",dict(cik="0000000002")),
            ("capex_ttm",dict(start="2024-01-01",period="2024-12-31")),
            ("liabilities",dict(context_dimensions="segment-B")),
            ("liabilities",dict(entity_id="other-company"))):
            row = base.copy()
            proof = json.loads(row[field+"_provenance"])
            proof[0].update(change)
            row[field+"_provenance"] = json.dumps(proof)
            if "start" in change:
                context = json.loads(row[field+"_financial_context"])
                context.update(period_start=change["start"],period_end=change["period"])
                row[field+"_financial_context"] = json.dumps(context)
            out = native_valuation_overrides(row,technical_price=10.0,price_context=self.price_context())
            if field == "capex_ttm":
                self.assertTrue(pd.isna(out["fcf_ttm"]))
                self.assertTrue(pd.isna(out["fcfy_ttm"]))
                self.assertEqual(out["ocf_ttm"],80.0)
                self.assertEqual(out["capex_ttm"],20.0)
            else:
                self.assertTrue(pd.isna(out["equity_native"]))
                self.assertTrue(pd.isna(out["book_to_market_proxy"]))
                self.assertTrue(pd.isna(out["roe_proxy"]))
        row = base.copy()
        for field in ("ocf_ttm","capex_ttm"):
            row.pop(field+"_financial_context")
            row.pop(field+"_provenance")
        self.assertTrue(pd.isna(native_valuation_overrides(row,technical_price=10.0,price_context=self.price_context())["fcf_ttm"]))

    def test_guard_refreshes_status_references_and_is_reversible(self):
        from r1000_features import enforce_native_valuation_context
        row = {**self.financial().to_dict(),**self.price_context(),"current_price_live":10.0}
        valid = enforce_native_valuation_context(pd.DataFrame([row]))
        invalid = valid.copy()
        invalid["share_basis_status"] = "UNKNOWN"
        invalid["share_basis_reference"] = "current-unverified-reference"
        invalid = enforce_native_valuation_context(invalid)
        self.assertTrue(pd.isna(invalid.loc[0,"mktcap"]))
        self.assertTrue(pd.isna(invalid.loc[0,"mktcap_unit"]))
        self.assertEqual(invalid.loc[0,"valuation_context_status"],"UNKNOWN")
        self.assertEqual(invalid.loc[0,"mktcap_missing_reason"],"missing_verified_share_basis_or_price_clock")
        evidence = json.loads(invalid.loc[0,"valuation_evidence_reference"])
        self.assertEqual(evidence["share_basis_reference"],"current-unverified-reference")
        self.assertEqual(evidence["share_basis_status"],"UNKNOWN")
        for key,value in self.price_context().items():
            invalid[key]=value
        restored = enforce_native_valuation_context(invalid)
        for field in ("mktcap","ep_ttm","sp_ttm","fcfy_ttm","mktcap_unit","valuation_context_status","mktcap_missing_reason","valuation_evidence_reference"):
            self.assertEqual(restored.loc[0,field],valid.loc[0,field])
        pd.testing.assert_frame_equal(restored,enforce_native_valuation_context(restored))

    def test_actual_projection_readback_normalization_retains_evidence(self):
        import r1000_pipeline as pipe
        import r1000_features as features
        from r1000_config import EngineConfig
        cfg = EngineConfig()
        original_features = list(cfg.features)
        row = {**self.financial("EUR").to_dict(),**self.price_context(),"ticker":"SYN","cik10":"0000000001",
            "rebalance_date":"2026-07-11","px":10.0,"current_price_live":10.0,"revenue_growth_final":0.0,
            "fx_status":"VERIFIED","fx_reference":"synthetic-fx","fx_rate":2.0,"fx_from_currency":"EUR","fx_to_currency":"USD",
            "fx_asof":"2026-07-10T19:00:00Z","fx_valid_until":"2026-07-10T21:00:00Z"}
        for field in ("shares","net_income_ttm","revenues_ttm","ocf_ttm","capex_ttm","fcf_ttm","assets","liabilities"):
            dimensions = {"region":"ALL"}
            row[field+"_context_dimensions"] = dimensions
            context=json.loads(row[field+"_financial_context"])
            context["scope"]["dimensions"]=dimensions
            row[field+"_financial_context"]=json.dumps(context)
            proof=json.loads(row[field+"_provenance"])
            proof[0]["context_dimensions"]=dimensions
            row[field+"_provenance"]=json.dumps(proof)
        keep = ["ticker","cik10","rebalance_date","px","mktcap","shares","assets","liabilities",
            "net_income_ttm","revenues_ttm","ocf_ttm","capex_ttm","fcf_ttm","revenue_growth_final"]
        projected = pipe.project_feature_store_frame(pd.DataFrame([row]),keep)
        self.assertEqual(cfg.features,original_features)
        self.assertNotIn("fx_rate",cfg.features)
        self.assertIn("net_income_ttm_financial_context",projected)
        self.assertIn("share_basis_reference",projected)
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv","parquet"):
                path=Path(tmp)/("feature_store."+suffix)
                if suffix=="csv":
                    projected.to_csv(path,index=False)
                    reread=pd.read_csv(path,dtype={"cik":str,"cik10":str})
                else:
                    projected.to_parquet(path,index=False)
                    reread=pd.read_parquet(path)
                with patch.object(pipe,"repair_latest_history_depth_from_diagnostics",side_effect=lambda paths,frame:frame), \
                    patch.object(features,"_load_finnhub_features_for_fallback",return_value=pd.DataFrame()):
                    normalized=pipe.normalize_latest_fundamental_snapshot(cfg,{},reread,apply_statement_repair=False,add_fundamental_flags=False)
                self.assertEqual(normalized.loc[0,"mktcap"],1000.0)
                self.assertEqual(normalized.loc[0,"ep_ttm"],0.1)
                self.assertEqual(normalized.loc[0,"sp_ttm"],1.0)
                self.assertEqual(normalized.loc[0,"forward_ps"],1.0)
                self.assertEqual(normalized.loc[0,"forward_ps_final"],1.0)
                self.assertEqual(normalized.loc[0,"net_income_ttm_provenance"],row["net_income_ttm_provenance"])

    def test_gp_assets_ratio_cannot_be_refilled_after_unit_refusal(self):
        import r1000_pipeline as pipe
        row = {**self.financial().to_dict(),**self.price_context(),"px":10.0,"mktcap":1000.0,
            "gross_profit_ttm":100.0,"gross_profit_ttm_unit":"EUR","gp_to_assets_ttm":float("nan")}
        row["gross_profit_ttm_financial_context"] = row["net_income_ttm_financial_context"]
        row["gross_profit_ttm_provenance"] = row["net_income_ttm_provenance"]
        out=pipe.compute_valuation_columns(pd.DataFrame([row])).iloc[0]
        self.assertTrue(pd.isna(out["gp_to_assets_ttm"]))
        self.assertEqual(out["gp_to_assets_ttm_missing_reason"],"incompatible_or_missing_component_units_or_context")
        row["gross_profit_ttm_unit"]="USD"
        self.assertEqual(pipe.compute_valuation_columns(pd.DataFrame([row])).iloc[0]["gp_to_assets_ttm"],0.1)

    def test_long_q3_ytd_is_not_an_annual_ttm(self):
        q3=self.row(fp="Q3",start=pd.Timestamp("2026-01-01"),period=pd.Timestamp("2026-10-27"),
            accepted=pd.Timestamp("2026-11-01"),value=900.0,duration_days=300,semantic_rank=1)
        panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame([q3])))
        self.assertEqual(panel.loc[0,"revenues_cum_value"],900.0)
        self.assertTrue(pd.isna(panel.loc[0,"revenues_ttm"]))
        annual={**q3,"fp":"FY","fiscal_period":"FY","form":"10-K","start":pd.Timestamp("2025-10-22"),"duration_days":371,"semantic_rank":0}
        for value in (900.0,0.0,-20.0):
            annual["value"]=value
            panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame([annual])))
            self.assertEqual(panel.loc[0,"revenues_ttm"],value)


    def test_forward_ps_final_is_guarded_before_score_consumption(self):
        import r1000_features as features
        row={**self.financial("EUR").to_dict(),**self.price_context(),"ticker":"SYN","px":10.0,
            "current_price_live":10.0,"revenue_growth_final":0.0,"price_to_sales":2.0,
            "fx_status":"VERIFIED","fx_reference":"synthetic-fx","fx_rate":2.0,
            "fx_from_currency":"EUR","fx_to_currency":"USD","fx_asof":"2026-07-10T19:00:00Z",
            "fx_valid_until":"2026-07-10T21:00:00Z"}
        consumed=[]
        original=features.cross_sectional_robust_z
        def capture(frame,column,*args,**kwargs):
            if column=="forward_ps_final":
                consumed.extend(frame[column].tolist())
            return original(frame,column,*args,**kwargs)
        with patch.object(features,"_load_finnhub_features_for_fallback",return_value=pd.DataFrame()), \
            patch.object(features,"cross_sectional_robust_z",side_effect=capture):
            result=features.compute_live_factor_columns(pd.DataFrame([row]))
        self.assertEqual(result.loc[0,"sp_ttm"],1.0)
        self.assertEqual(result.loc[0,"forward_ps"],1.0)
        self.assertEqual(result.loc[0,"forward_ps_final"],1.0)
        self.assertTrue(consumed)
        self.assertTrue(all(value==1.0 for value in consumed))


    def test_missing_fcf_parent_invalidates_cached_outputs_and_recovers(self):
        import r1000_features as features
        base={**self.financial().to_dict(),**self.price_context(),"ticker":"SYN","current_price_live":10.0,
            "fcf_margin":0.12,"fcf_cagr_1y":0.2,"rule_of_40":0.3}
        for field in ("ocf_ttm","capex_ttm"):
            cache={}
            valid=features.enforce_native_valuation_context(pd.DataFrame([base]),_operation_cache=cache)
            self.assertEqual(valid.loc[0,"fcf_ttm"],60.0)
            missing=valid.copy();missing[field]=float("nan")
            refused=features.enforce_native_valuation_context(missing,_operation_cache=cache)
            for column in ("fcf_ttm","fcfy_ttm","fcf_margin","fcf_cagr_1y","rule_of_40"):
                self.assertTrue(pd.isna(refused.loc[0,column]),column)
            for column in ("fcf_ttm_unit","fcf_ttm_financial_context","fcf_ttm_provenance"):
                self.assertTrue(pd.isna(refused.loc[0,column]),column)
            self.assertEqual(refused.loc[0,"fcf_ttm_status"],"UNKNOWN")
            self.assertIn(field,refused.loc[0,"fcf_ttm_missing_reason"])
            self.assertIn(field,refused.loc[0,"fcfy_ttm_missing_reason"])
            self.assertEqual(refused.loc[0,field+"_provenance"],base[field+"_provenance"])
            restored=refused.copy();restored[field]=base[field]
            restored=features.enforce_native_valuation_context(restored,_operation_cache=cache)
            self.assertEqual(restored.loc[0,"fcf_ttm"],60.0)
            self.assertEqual(restored.loc[0,"fcfy_ttm"],0.06)
            zero=restored.copy();zero[field]=0.0
            zero=features.enforce_native_valuation_context(zero,_operation_cache=cache)
            self.assertEqual(zero.loc[0,"fcf_ttm"],-20.0 if field=="ocf_ttm" else 80.0)

    def test_original_period_conflict_cannot_be_overridden_by_stored_context(self):
        import r1000_features as features
        row=self.financial()
        proof=json.loads(row["capex_ttm_provenance"])
        proof[0].update(start="2024-01-01",period="2024-12-31")
        row["capex_ttm_provenance"]=json.dumps(proof)
        self.assertIsNone(features.native_financial_context(row,"capex_ttm"))
        out=features.native_valuation_overrides(row,technical_price=10.0,price_context=self.price_context())
        self.assertTrue(pd.isna(out["fcf_ttm"]))
        self.assertTrue(pd.isna(out["fcfy_ttm"]))
        self.assertEqual(out["capex_ttm"],20.0)
        proof[0].update(start="2025-01-01",period="2025-12-31")
        row["capex_ttm_provenance"]=json.dumps(proof)
        self.assertEqual(features.native_valuation_overrides(row,technical_price=10.0,price_context=self.price_context())["fcf_ttm"],60.0)
        records=[]
        for i,p in enumerate(pd.date_range("2025-03-31",periods=4,freq="QE-DEC")):
            start=p-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            records.append(self.row(start=start,period=p,accepted=p+pd.Timedelta(days=20),fp="Q"+str(i+1),
                accession_number="proof-"+str(i),duration_days=(p-start).days+1))
        panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(records)))
        latest=panel.iloc[-1].copy()
        self.assertIsNotNone(features.native_financial_context(latest,"revenues_ttm"))
        lineage=json.loads(latest["revenues_ttm_provenance"])
        native=json.loads(lineage[0]["native_proof"])
        native[0]["period"]="2024-03-31"
        lineage[0]["native_proof"]=json.dumps(native)
        latest["revenues_ttm_provenance"]=json.dumps(lineage)
        self.assertIsNone(features.native_financial_context(latest,"revenues_ttm"))

    def test_eps_lineage_supports_valid_growth_and_refuses_scope_mismatch(self):
        import r1000_features as features
        rows=[]
        for i,p in enumerate(pd.date_range("2024-03-31",periods=8,freq="QE-DEC")):
            start=p-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            common=dict(period=p,accepted=p+pd.Timedelta(days=20),fy=p.year,fp="Q"+str((p.month-1)//3+1),
                accession_number="eps-"+str(i),unit="USD")
            rows.append(self.row(**common,field_name="net_income",source_tag="NetIncomeLoss",value=25.0+i*5.0,
                start=start,duration_days=(p-start).days+1))
            rows.append(self.row(**{**common,"unit":"shares"},field_name="shares",source_tag="CommonStockSharesOutstanding",value=100.0,start=pd.NaT))
        panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        latest=panel.iloc[-1]
        self.assertAlmostEqual(latest["eps_ttm"],2.1)
        self.assertGreater(latest["eps_cagr_1y"],0.5)
        self.assertIn("net_income_divided_by_reported_shares",latest["eps_ttm_provenance"])
        self.assertIsNotNone(features.native_financial_context(latest,"eps_ttm"))
        guarded=features.enforce_native_valuation_context(pd.DataFrame([{**latest.to_dict(),**self.price_context(),"current_price_live":10.0}])).iloc[0]
        self.assertEqual(guarded["eps_ttm_unit"],"USD/shares")
        self.assertGreater(guarded["eps_cagr_1y"],0.5)
        foreign=[{**row,"unit":"EUR"} if row["field_name"]=="net_income" else dict(row) for row in rows]
        native_foreign=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(foreign))).iloc[-1]
        foreign_guarded=features.enforce_native_valuation_context(pd.DataFrame([{**native_foreign.to_dict(),**self.price_context(),"current_price_live":10.0}])).iloc[0]
        self.assertEqual(foreign_guarded["eps_ttm_unit"],"EUR/shares")
        self.assertGreater(foreign_guarded["eps_cagr_1y"],0.5)
        self.assertTrue(pd.isna(foreign_guarded["ep_ttm"]))  # no listing-currency FX proof

        annual=[]
        for year,income in ((2024,100.0),(2025,200.0)):
            p=pd.Timestamp(str(year)+"-12-31")
            common=dict(period=p,accepted=p+pd.Timedelta(days=40),fy=year,fp="FY",form="10-K",accession_number="annual-eps-"+str(year))
            annual.append(self.row(**common,field_name="net_income",source_tag="NetIncomeLoss",unit="USD",value=income,start=pd.Timestamp(str(year)+"-01-01"),duration_days=366 if year==2024 else 365))
            annual.append(self.row(**common,field_name="shares",source_tag="CommonStockSharesOutstanding",unit="shares",value=100.0,start=pd.NaT))
        annual_panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(annual)))
        self.assertEqual(annual_panel.iloc[-1]["eps_ttm"],2.0)
        self.assertGreater(annual_panel.iloc[-1]["eps_cagr_1y"],0.99)
        self.assertGreater(annual_panel.iloc[-1]["eps_cagr_best"],0.99)
        bad=[dict(row) for row in rows];bad[-1]["context_dimensions"]="other-segment"
        refused=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(bad))).iloc[-1]
        self.assertTrue(pd.isna(refused["eps_ttm"]))
        self.assertTrue(pd.isna(refused["eps_cagr_1y"]))

    def test_gross_profit_fallback_has_validated_derived_lineage(self):
        common=dict(unit="USD",start=pd.Timestamp("2025-01-01"),period=pd.Timestamp("2025-12-31"),
            accepted=pd.Timestamp("2026-02-01"),fy=2025,fp="FY",form="10-K",duration_days=365)
        rows=[self.row(**common,field_name="revenues",source_tag="Revenue",value=1000.0),
            self.row(**common,field_name="cost_of_revenue",source_tag="CostOfRevenue",value=400.0),
            self.row(**{**common,"start":pd.NaT},field_name="assets",source_tag="Assets",value=2000.0)]
        panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        latest=panel.iloc[-1]
        self.assertEqual(latest["gross_profit_ttm"],600.0)
        self.assertEqual(latest["gross_margin_ttm"],0.6)
        self.assertEqual(latest["gp_to_assets_ttm"],0.3)
        self.assertEqual(latest["gross_profit_ttm_fact_status"],"DERIVED_NOT_OBSERVED")
        self.assertEqual(latest["gross_profit_ttm_missing_reason"],"")
        self.assertIn("revenues_minus_cost_of_revenue",latest["gross_profit_ttm_provenance"])
        import r1000_features as features
        prior=panel.drop(columns=[column for column in panel if column.endswith(("_derivation","_fact_status"))]).copy()
        prior["cost_of_revenue_context_dimensions"]="other-segment"
        refreshed=features.recompute_fund_panel_derived_columns(prior).iloc[-1]
        self.assertTrue(pd.isna(refreshed["gross_profit_ttm"]))
        rows[1]["context_dimensions"]="other-segment"
        bad=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows))).iloc[-1]
        self.assertTrue(pd.isna(bad["gross_profit_ttm"]))
        self.assertTrue(pd.isna(bad["gross_profit"]))
        self.assertEqual(bad["cost_of_revenue_cum_value"],400.0)
        self.assertEqual(bad["cost_of_revenue_ttm"],400.0)
        # A separately observed direct fact replaces stale derived markers;
        # subsequent loss of that fact returns to a validated component result.
        direct_rows = [dict(row) for row in rows]
        direct_rows.append(self.row(**common,field_name="gross_profit",source_tag="GrossProfit",value=650.0))
        direct = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(direct_rows)))
        self.assertEqual(direct.iloc[-1]["gross_profit_ttm"],650.0)
        direct["gross_profit_derivation"] = direct["gross_profit_ttm_derivation"] = "revenues_minus_cost_of_revenue"
        direct["gross_profit_fact_status"] = direct["gross_profit_ttm_fact_status"] = "DERIVED_NOT_OBSERVED"
        reread = features.recompute_fund_panel_derived_columns(direct).iloc[-1]
        self.assertEqual(reread["gross_profit_ttm"],650.0)
        self.assertEqual(reread["gross_profit_ttm_fact_status"],"OBSERVED")
        self.assertTrue(pd.isna(reread["gross_profit_ttm_derivation"]))
        restored = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame([
            {**row,"context_dimensions":None} for row in rows]))).iloc[-1]
        self.assertEqual(restored["gross_profit_ttm"],600.0)
        self.assertEqual(restored["gross_profit_ttm_fact_status"],"DERIVED_NOT_OBSERVED")

    def test_dividend_payout_uses_valid_fcf_without_earnings_and_clears_invalid_score(self):
        import r1000_pipeline as pipe
        import r1000_features as features
        row={**self.financial(income=float("nan")).to_dict(),**self.price_context(),"ticker":"SYN","px":10.0,
            "mktcap":1000.0,"current_price_live":10.0,"dividends_ttm_ps":0.30,"dividend_yield_ttm":0.03,
            "dividend_policy_score":0.9,"dividends_ttm_ps_unit":"USD/shares","dividends_share_basis":"ordinary"}
        out=pipe.compute_valuation_columns(pd.DataFrame([row]))
        self.assertEqual(out.loc[0,"dividend_payout_ratio"],0.5)
        self.assertEqual(out.loc[0,"dividend_payout_source"],"fcf_ttm")
        self.assertGreater(out.loc[0,"dividend_policy_score"],0.0)
        bad=out.copy();bad["ocf_ttm"]=float("nan")
        bad=features.enforce_native_valuation_context(bad)
        self.assertTrue(pd.isna(bad.loc[0,"dividend_payout_ratio"]))
        self.assertEqual(bad.loc[0,"dividend_policy_score"],0.0)
        wrong=out.copy();wrong["dividends_share_basis"]="ADS"
        wrong=features.enforce_native_valuation_context(wrong)
        self.assertTrue(pd.isna(wrong.loc[0,"dividend_payout_ratio"]))
        self.assertEqual(wrong.loc[0,"dividend_policy_score"],0.0)

    def test_operation_cache_reuses_only_unchanged_operand_evidence(self):
        import r1000_features as features
        frame=pd.DataFrame([{**self.financial().to_dict(),**self.price_context(),"current_price_live":10.0}])
        cache={}
        original=features.native_valuation_overrides
        with patch.object(features,"native_valuation_overrides",wraps=original) as call:
            first=features.enforce_native_valuation_context(frame,_operation_cache=cache)
            second=features.enforce_native_valuation_context(first,_operation_cache=cache)
            self.assertEqual(call.call_count,1)
            self.assertEqual(second.loc[0,"fcf_ttm"],60.0)
            changed=second.copy();proof=json.loads(changed.loc[0,"capex_ttm_provenance"])
            proof[0].update(start="2024-01-01",period="2024-12-31")
            changed.loc[0,"capex_ttm_provenance"]=json.dumps(proof)
            refused=features.enforce_native_valuation_context(changed,_operation_cache=cache)
            self.assertEqual(call.call_count,2)
            self.assertTrue(pd.isna(refused.loc[0,"fcf_ttm"]))
            changed=first.copy();changed["share_basis_status"]="UNKNOWN"
            refused=features.enforce_native_valuation_context(changed,_operation_cache=cache)
            self.assertEqual(call.call_count,3)
            self.assertTrue(pd.isna(refused.loc[0,"mktcap"]))
            changed=first.copy();changed["source_hashes"]="changed-evidence-reference"
            features.enforce_native_valuation_context(changed,_operation_cache=cache)
            self.assertEqual(call.call_count,4)


    def test_cache_hit_tracks_current_columns_and_candidate_order(self):
        import r1000_features as features
        frame = pd.DataFrame([{**self.financial().to_dict(), **self.price_context(),
            "ticker":"SYN", "current_price_live":10.0, "ocf_ttm":float("nan")}])
        cache = {}
        first = features.enforce_native_valuation_context(frame, _operation_cache=cache)
        first["fcf_cagr_1y"], first["fcf_margin"], first["rule_of_40"] = 0.4, 0.12, 0.5
        cached = features.enforce_native_valuation_context(first, _operation_cache=cache)
        fresh = features.enforce_native_valuation_context(first)
        pd.testing.assert_frame_equal(cached, fresh)
        for field in ("fcf_cagr_1y", "fcf_margin", "rule_of_40"):
            self.assertTrue(pd.isna(cached.loc[0, field]))
        # Valid caller histories survive; removing columns never revives them.
        rows = [{**self.financial().to_dict(), **self.price_context(), "ticker":ticker,
            "current_price_live":10.0} for ticker in ("A", "B", "UNKNOWN")]
        rows[-1]["shares_provenance"] = None
        cache = {}
        base = features.enforce_native_valuation_context(pd.DataFrame(rows), _operation_cache=cache)
        base["fcf_cagr_1y"] = [0.4, 0.6, float("nan")]
        for candidate in (base, base.drop(columns="fcf_cagr_1y"), base.iloc[[2, 0, 1, 0]], base.iloc[[1, 0]]):
            candidate = candidate.copy()
            candidate.index = [7] * len(candidate)  # duplicate/noncontiguous caller labels
            pd.testing.assert_frame_equal(
                features.enforce_native_valuation_context(candidate, _operation_cache=cache),
                features.enforce_native_valuation_context(candidate))
            self.assertEqual(list(features.enforce_native_valuation_context(candidate)["ticker"]), list(candidate["ticker"]))
        valid = features.enforce_native_valuation_context(base)
        self.assertEqual(valid.loc[0, "fcf_cagr_1y"], 0.4)
        self.assertTrue(pd.isna(valid.loc[2, "mktcap"]))

    def test_dividend_metadata_rejects_objects_and_preserves_null_readback(self):
        import r1000_features as features
        import r1000_pipeline as pipe
        row = {**self.financial(income=float("nan")).to_dict(), **self.price_context(),
            "ticker":"SYN", "current_price_live":10.0, "dividends_ttm_ps":0.3,
            "dividend_yield_ttm":0.03, "dividend_policy_score":0.9}
        for field in ("dividends_ttm_ps_unit", "dividends_share_basis"):
            for value in (True, False, {}, [], {"unexpected":"ordinary"}, 1, "INVALID"):
                with self.subTest(field=field, malformed=value):
                    data = pd.DataFrame([{**row, field:value}])
                    guarded = features.enforce_native_valuation_context(data).iloc[0]
                    self.assertTrue(pd.isna(guarded["dividend_payout_ratio"]))
                    self.assertEqual(guarded["dividend_policy_score"], 0.0)
                    projected = pipe.project_feature_store_frame(data, list(row))
                    with tempfile.TemporaryDirectory() as tmp:
                        for suffix in ("csv", "parquet"):
                            path = Path(tmp)/("dividend."+suffix)
                            if suffix == "csv":
                                projected.to_csv(path, index=False)
                                read = pd.read_csv(path, dtype={"cik":str})
                            else:
                                projected.to_parquet(path, index=False)
                                read = pd.read_parquet(path)
                            result = features.enforce_native_valuation_context(read).iloc[0]
                            self.assertTrue(pd.isna(result["dividend_payout_ratio"]))
                            self.assertEqual(result["dividend_policy_score"], 0.0)
            for value in (None, float("nan"), pd.NA, "null", "None", "nan", ""):
                with self.subTest(field=field, legacy_null=str(value)):
                    data = pd.DataFrame([{**row, field:value}])
                    self.assertEqual(features.enforce_native_valuation_context(data).iloc[0]["dividend_payout_ratio"], 0.5)
                    projected = pipe.project_feature_store_frame(data, list(row))
                    with tempfile.TemporaryDirectory() as tmp:
                        for suffix in ("csv", "parquet"):
                            path = Path(tmp)/("null."+suffix)
                            if suffix == "csv":
                                projected.to_csv(path, index=False)
                                read = pd.read_csv(path, dtype={"cik":str})
                            else:
                                projected.to_parquet(path, index=False)
                                read = pd.read_parquet(path)
                            self.assertEqual(features.enforce_native_valuation_context(read).iloc[0]["dividend_payout_ratio"], 0.5)

    def test_fcf_lineage_precedes_annual_growth_and_survives_guard(self):
        import r1000_features as features
        rows = []
        for year, cash in ((2024, 80.0), (2025, 140.0)):
            common = dict(unit="USD", period=pd.Timestamp(str(year)+"-12-31"),
                start=pd.Timestamp(str(year)+"-01-01"), accepted=pd.Timestamp(str(year+1)+"-02-10"),
                fy=year, fp="FY", form="10-K", accession_number="fcf-"+str(year), duration_days=366 if year==2024 else 365)
            for field, amount in (("ocf", cash), ("capex", 20.0)):
                rows.append(self.row(**common, field_name=field, source_tag=field, value=amount))
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        latest = panel.iloc[-1]
        self.assertEqual(latest["fcf_ttm"], 120.0)
        expected_growth = 2.0 ** (365.25 / 365.0) - 1.0  # actual dated annual interval
        self.assertAlmostEqual(latest["fcf_cagr_1y"], expected_growth)
        self.assertIsNotNone(features.native_financial_context(latest, "fcf_ttm"))
        self.assertIn("ocf_minus_abs_capex", latest["fcf_ttm_provenance"])
        guarded = features.enforce_native_valuation_context(pd.DataFrame([{**latest.to_dict(), **self.price_context(), "current_price_live":10.0}])).iloc[0]
        self.assertEqual(guarded["fcf_ttm_provenance"], latest["fcf_ttm_provenance"])
        self.assertAlmostEqual(guarded["fcf_cagr_1y"], expected_growth)
        bad = [dict(row) for row in rows]
        bad[-1]["entity_scope"] = "different-scope"
        refused = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(bad))).iloc[-1]
        self.assertTrue(pd.isna(refused["fcf_ttm"]))
        self.assertTrue(pd.isna(refused["fcf_cagr_1y"]))

    def test_dividend_projection_keeps_basis_and_original_proof_through_normalize(self):
        import r1000_features as features
        import r1000_pipeline as pipe
        from r1000_config import EngineConfig
        cfg = EngineConfig()
        model = list(cfg.features)
        row = {**self.financial().to_dict(), **self.price_context(), "ticker":"SYN", "cik10":"0000000001",
            "rebalance_date":"2026-07-11", "px":10.0, "current_price_live":10.0, "mktcap":1000.0,
            "dividends_ttm_ps":0.3, "dividend_yield_ttm":0.03, "dividend_policy_score":0.9,
            "dividends_ttm_ps_unit":"USD/shares", "dividends_share_basis":"ADS"}
        context = json.loads(row["net_income_ttm_financial_context"])
        row["dividends_ttm_ps_financial_context"] = json.dumps(context)
        row["dividends_ttm_ps_provenance"] = row["net_income_ttm_provenance"]
        keep = [key for key in row if not key.startswith("dividends_") or key=="dividends_ttm_ps"]
        projected = pipe.project_feature_store_frame(pd.DataFrame([row]), keep)
        self.assertEqual(cfg.features, model)
        for field in ("dividends_share_basis", "dividends_ttm_ps_unit", "dividends_ttm_ps_financial_context", "dividends_ttm_ps_provenance"):
            self.assertEqual(projected.loc[0, field], row[field])
            self.assertNotIn(field, cfg.features)
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv", "parquet"):
                path = Path(tmp)/("feature_store."+suffix)
                if suffix=="csv":
                    projected.to_csv(path,index=False)
                    reread=pd.read_csv(path,dtype={"cik":str,"cik10":str})
                else:
                    projected.to_parquet(path,index=False)
                    reread=pd.read_parquet(path)
                with patch.object(pipe,"repair_latest_history_depth_from_diagnostics",side_effect=lambda paths,frame:frame), \
                    patch.object(features,"_load_finnhub_features_for_fallback",return_value=pd.DataFrame()):
                    normalized=pipe.normalize_latest_fundamental_snapshot(cfg,{},reread,apply_statement_repair=False,add_fundamental_flags=False)
                self.assertTrue(pd.isna(normalized.loc[0,"dividend_payout_ratio"]))
                self.assertEqual(normalized.loc[0,"dividend_policy_score"],0.0)
                restored = reread.copy(); restored["dividends_share_basis"] = "ordinary"
                self.assertEqual(features.enforce_native_valuation_context(restored).loc[0,"dividend_payout_ratio"], 0.6)
                proof = json.loads(row["dividends_ttm_ps_provenance"])
                proof[0]["context_dimensions"] = "other-segment"
                restored["dividends_ttm_ps_provenance"] = json.dumps(proof)
                self.assertTrue(pd.isna(features.enforce_native_valuation_context(restored).loc[0,"dividend_payout_ratio"]))

    def test_valid_fcf_changes_invalidate_history_on_cached_and_direct_paths(self):
        import r1000_features as features
        seed = pd.DataFrame([{**self.financial().to_dict(), **self.price_context(), "current_price_live":10.0,"revenue_growth_final":0.1}])
        cache = {}
        first = features.enforce_native_valuation_context(seed, _operation_cache=cache)
        history = ("fcf_cagr_1y", "fcf_growth_yoy", "fcf_sign_flip_pos")
        for field in history:
            first[field] = 0.4
        unchanged = features.enforce_native_valuation_context(first, _operation_cache=cache)
        for field in history:
            self.assertEqual(unchanged.loc[0,field],0.4)
        self.assertEqual(unchanged.loc[0,"fcf_margin"],0.12)
        self.assertAlmostEqual(unchanged.loc[0,"rule_of_40"],0.22)
        for change in ("value", "currency", "proof", "reason"):
            changed = first.copy()
            if change=="value":
                changed["ocf_ttm"]=140.0
            elif change=="currency":
                changed["ocf_ttm_unit"]=changed["capex_ttm_unit"]="EUR"
            elif change=="proof":
                proof=json.loads(changed.loc[0,"ocf_ttm_provenance"])
                proof[0]["original_receipt"]="corrected-receipt"
                changed["ocf_ttm_provenance"]=json.dumps(proof)
            else:
                changed["fcf_ttm_missing_reason"]="old-refusal"
            fresh=features.enforce_native_valuation_context(changed)
            cached=features.enforce_native_valuation_context(changed,_operation_cache=cache)
            pd.testing.assert_frame_equal(cached,fresh)
            direct=features.native_valuation_overrides(changed.iloc[0],technical_price=10.0)
            for field in history:
                self.assertTrue(pd.isna(cached.loc[0,field]),(change,field))
                self.assertTrue(pd.isna(direct[field]),(change,field))
            self.assertEqual(cached.loc[0,"fcf_ttm"],120.0 if change=="value" else 60.0)
            if change=="currency":
                self.assertTrue(pd.isna(cached.loc[0,"fcf_margin"]))
                self.assertTrue(pd.isna(cached.loc[0,"rule_of_40"]))
            else:
                margin=0.24 if change=="value" else 0.12
                self.assertEqual(cached.loc[0,"fcf_margin"],margin)
                self.assertAlmostEqual(cached.loc[0,"rule_of_40"],0.1+margin)
        # EPS/equity refresh their entire bundle on loss and restoration of
        # parents; neither stale metadata nor old histories authorize recovery.
        changed = first.copy()
        changed["assets"] = changed["net_income_ttm"] = float("nan")
        changed["eps_cagr_1y"] = 0.3
        refused = features.enforce_native_valuation_context(changed, _operation_cache=cache)
        for field in ("equity_native", "eps_ttm"):
            self.assertTrue(pd.isna(refused.loc[0,field]))
            for suffix in ("_unit", "_financial_context", "_provenance"):
                self.assertTrue(pd.isna(refused.loc[0,field+suffix]))
            self.assertTrue(refused.loc[0,field+"_missing_reason"])
        self.assertTrue(pd.isna(refused.loc[0,"eps_cagr_1y"]))
        refused["assets"], refused["net_income_ttm"] = 1000.0, 50.0
        restored = features.enforce_native_valuation_context(refused, _operation_cache=cache)
        self.assertEqual(restored.loc[0,"equity_native"],600.0)
        self.assertEqual(restored.loc[0,"eps_ttm"],0.5)
        self.assertEqual(restored.loc[0,"equity_native_missing_reason"],"")
        self.assertEqual(restored.loc[0,"eps_ttm_missing_reason"],"")
        self.assertTrue(pd.isna(restored.loc[0,"eps_cagr_1y"]))

    def test_market_cap_requires_current_native_shares_identity_and_period(self):
        import r1000_features as features
        frame=pd.DataFrame([{**self.financial().to_dict(),**self.price_context(),"current_price_live":10.0}])
        valid=features.enforce_native_valuation_context(frame)
        for change in ("other-cik","missing-proof","future-period"):
            bad=valid.copy()
            if change=="other-cik":
                proof=json.loads(bad.loc[0,"shares_provenance"])
                proof[0]["cik"]="0000000002"
                bad["shares_provenance"]=json.dumps(proof)
            elif change=="missing-proof":
                bad["shares_provenance"]=None
            else:
                context=json.loads(bad.loc[0,"shares_financial_context"])
                context["period_end"]="2026-12-31"
                proof=json.loads(bad.loc[0,"shares_provenance"])
                proof[0]["period"]="2026-12-31"
                bad["shares_financial_context"],bad["shares_provenance"]=json.dumps(context),json.dumps(proof)
            out=features.enforce_native_valuation_context(bad).iloc[0]
            for field in ("mktcap","market_cap_live","shares_effective","ep_ttm","sp_ttm","fcfy_ttm"):
                self.assertTrue(pd.isna(out[field]),(change,field))
            self.assertEqual(out["valuation_context_status"],"UNKNOWN")
            self.assertTrue(out["mktcap_missing_reason"])
        self.assertEqual(features.enforce_native_valuation_context(valid).loc[0,"mktcap"],1000.0)

    def test_liability_identity_checks_full_scope_before_core_coverage(self):
        common=dict(unit="USD",start=pd.Timestamp("2025-01-01"),period=pd.Timestamp("2025-12-31"),
            accepted=pd.Timestamp("2026-02-01"),fy=2025,fp="FY",form="10-K",duration_days=365)
        rows=[self.row(**common,field_name=field,source_tag=field,value=amount)
            for field,amount in (("revenues",1000.0),("op_income",100.0),("net_income",50.0))]
        rows += [self.row(**{**common,"start":pd.NaT},field_name=field,source_tag=field,value=amount)
            for field,amount in (("assets",1000.0),("liabilities_and_equity",1000.0),("stockholders_equity_for_liabilities",400.0))]
        valid=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows))).iloc[0]
        self.assertEqual(valid["liabilities"],600.0)
        self.assertEqual(valid["fund_panel_ttm_ready"],1.0)
        for change in (dict(entity_scope="subsidiary"),dict(entity_id="other-company"),dict(segment="other-segment")):
            bad=[dict(row) for row in rows];bad[-1].update(change)
            refused=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(bad))).iloc[0]
            self.assertTrue(pd.isna(refused["liabilities"]),change)
            self.assertFalse(refused["liabilities_derivation_applied"])
            self.assertEqual(refused["fund_panel_ttm_ready"],0.0)
            self.assertIn("liability_parent_context",refused["liabilities_missing_reason"])
            self.assertEqual(refused["liabilities_and_equity"],1000.0)
            self.assertEqual(refused["stockholders_equity_for_liabilities"],400.0)

    def test_refused_rolling_scope_does_not_hide_independent_annual(self):
        import r1000_features as features
        rows=[]
        for i,end in enumerate(pd.date_range("2025-03-31",periods=4,freq="QE-DEC")):
            start=end-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            annual=i==3
            native_start=pd.Timestamp("2025-01-01") if annual else start
            scope="consolidated" if annual else "subsidiary"
            proof=json.dumps([dict(cik="0000000001",context_dimensions=None,entity_scope=scope,
                start=str(native_start.date()),period=str(end.date()))])
            rows.append(dict(cik="0000000001",period=end,accepted=end+pd.Timedelta(days=30),quarter_index=i+1,
                revenues=250.0,revenues_unit="USD",revenues_start=native_start,revenues_entity_scope=scope,
                revenues_context_dimensions=None,revenues_context_parent="same-selected-parent",revenues_flow_start=start,
                revenues_fact_provenance=proof,revenues_flow_provenance=proof,revenues_cum_value_cum_provenance=proof,
                revenues_cum_value=1000.0 if annual else 250.0*(i+1),revenues_cum_value_cum_start=pd.Timestamp("2025-01-01"),
                revenues_fp="FY" if annual else "Q"+str(i+1),revenues_form="10-K" if annual else "10-Q"))
        frame=pd.DataFrame(rows)
        independent=features.native_flow_ttm_context(frame.iloc[[-1]],"revenues").iloc[-1]
        combined=features.native_flow_ttm_context(frame,"revenues").iloc[-1]
        self.assertEqual(independent["value"],1000.0)
        self.assertEqual(combined["value"],1000.0)
        self.assertEqual(combined["fallback_used"],1.0)
        self.assertEqual(combined["provenance"],independent["provenance"])
        self.assertEqual(combined["financial_context"],independent["financial_context"])


    def test_derived_gp_refreshes_current_parents_and_cache_preserves_direct_fact(self):
        import r1000_features as f
        common=dict(unit="USD",start=pd.Timestamp("2025-01-01"),period=pd.Timestamp("2025-12-31"),
            accepted=pd.Timestamp("2026-02-01"),fy=2025,fp="FY",form="10-K",duration_days=365)
        rows=[self.row(**common,field_name=field,source_tag=field,value=amount)
            for field,amount in (("revenues",1000.0),("cost_of_revenue",400.0))]
        base=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        base["current_price_live"]=10.0
        cache={}
        good=f.enforce_native_valuation_context(base,_operation_cache=cache)
        self.assertEqual(good.loc[0,"gross_profit_ttm"],600.0)
        self.assertEqual(good.loc[0,"gross_margins"],0.6)
        good["gp_sign_flip_pos"]=1.0
        self.assertEqual(f.enforce_native_valuation_context(good).loc[0,"gp_sign_flip_pos"],1.0)
        for change in ("value","missing","currency","scope","proof"):
            changed=good.copy()
            if change=="value":changed["cost_of_revenue_ttm"]=700.0
            elif change=="missing":changed["cost_of_revenue_ttm"]=float("nan")
            elif change=="currency":changed["cost_of_revenue_ttm_unit"]="EUR"
            else:
                proof=json.loads(changed.loc[0,"cost_of_revenue_ttm_provenance"])
                # Original annual proof is wrapped by the existing TTM producer.
                native=json.loads(proof[0]["native_proof"])
                native[0]["context_dimensions" if change=="scope" else "original_receipt"]="changed"
                proof[0]["native_proof"]=json.dumps(native)
                changed["cost_of_revenue_ttm_provenance"]=json.dumps(proof)
            cached=f.enforce_native_valuation_context(changed,_operation_cache=cache)
            fresh=f.enforce_native_valuation_context(changed)
            pd.testing.assert_frame_equal(cached,fresh)
            self.assertTrue(pd.isna(cached.loc[0,"gp_sign_flip_pos"]),change)
            if change in ("value","proof"):
                self.assertEqual(cached.loc[0,"gross_profit_ttm"],300.0 if change=="value" else 600.0)
                self.assertEqual(cached.loc[0,"gross_profit_ttm_missing_reason"],"")
                self.assertEqual(cached.loc[0,"gross_margins"],0.3 if change=="value" else 0.6)
            else:
                for field in ("gross_profit_ttm","gross_margins","gross_margin_ttm"):
                    self.assertTrue(pd.isna(cached.loc[0,field]),(change,field))
                self.assertTrue(cached.loc[0,"gross_profit_ttm_missing_reason"])
                for suffix in ("unit","financial_context","provenance"):
                    self.assertTrue(pd.isna(cached.loc[0,"gross_profit_ttm_"+suffix]))
        direct=self.financial().to_dict()
        direct.update(self.price_context(),current_price_live=10.0,gross_profit_ttm=650.0,gross_profit_ttm_unit="USD",
            gross_profit_ttm_financial_context=direct["revenues_ttm_financial_context"],
            gross_profit_ttm_provenance=direct["revenues_ttm_provenance"],cost_of_revenue_ttm=float("nan"))
        mixed=pd.concat([good,pd.DataFrame([direct])],ignore_index=True)
        mixed.loc[0,"cost_of_revenue_ttm"]=700.0
        observed=f.enforce_native_valuation_context(mixed)
        self.assertEqual(observed.loc[0,"gross_profit_ttm"],300.0)
        self.assertEqual(observed.loc[1,"gross_profit_ttm"],650.0)
        self.assertEqual(observed.loc[1,"gross_margins"],1.3)

    def test_negative_capex_keeps_unchanged_native_fcf_growth_through_main(self):
        import r1000_features as f
        import r1000_pipeline as p
        seed=pd.DataFrame([{**self.financial().to_dict(),**self.price_context(),"ticker":"SYN",
            "current_price_live":10.0,"px":10.0,"mktcap":1000.0,"capex_ttm":-20.0,"revenue_growth_final":0.38}])
        first=f.enforce_native_valuation_context(seed)
        first["fcf_cagr_1y"],first["fcf_margin"],first["rule_of_40"]=0.4,0.12,0.5
        for capex in (-20.0,20.0):
            current=first.copy();current["capex_ttm"]=capex
            out=p.compute_valuation_columns(current)
            self.assertEqual(out.loc[0,"fcf_ttm"],60.0)
            self.assertEqual(out.loc[0,"fcf_cagr_1y"],0.4)
            self.assertEqual(out.loc[0,"fcf_margin"],0.12)
            self.assertEqual(out.loc[0,"rule_of_40"],0.5)
            self.assertEqual(out.loc[0,"fcf_ttm_provenance"],first.loc[0,"fcf_ttm_provenance"])
            self.assertEqual(out.loc[0,"fcf_ttm_missing_reason"],"")

    def test_null_optional_dividend_proof_columns_are_row_local_and_roundtrip_stable(self):
        import r1000_features as f
        import r1000_pipeline as p
        row={**self.financial().to_dict(),**self.price_context(),"ticker":"SYN","current_price_live":10.0,
            "dividends_ttm_ps":0.3,"dividend_yield_ttm":0.03,"dividend_policy_score":0.9}
        baseline=f.enforce_native_valuation_context(pd.DataFrame([row])).iloc[0]
        self.assertEqual(baseline["dividend_payout_ratio"],0.6)
        proof_fields=("dividends_ttm_ps_provenance","dividends_ttm_ps_financial_context")
        for missing in (None,float("nan"),pd.NA,"","null"):
            data=pd.DataFrame([{**row,**dict.fromkeys(proof_fields,missing)}])
            result=f.enforce_native_valuation_context(data).iloc[0]
            self.assertEqual(result["dividend_payout_ratio"],0.6)
            self.assertEqual(result["dividend_policy_score"],baseline["dividend_policy_score"])
        explicit={**row,"dividends_ttm_ps_provenance":row["net_income_ttm_provenance"],
            "dividends_ttm_ps_financial_context":row["net_income_ttm_financial_context"],"dividends_ttm_ps_unit":"USD/shares"}
        malformed={**row,"dividends_ttm_ps_provenance":True}
        conflict={**explicit,"dividends_ttm_ps_financial_context":json.dumps({"wrong":"context"})}
        data=pd.DataFrame([row,explicit,malformed,conflict],index=[9,2,9,4])
        expected=f.enforce_native_valuation_context(data)
        for position in (0,1):self.assertEqual(expected.iloc[position]["dividend_payout_ratio"],0.6)
        for position in (2,3):
            self.assertTrue(pd.isna(expected.iloc[position]["dividend_payout_ratio"]))
            self.assertEqual(expected.iloc[position]["dividend_policy_score"],0.0)
        projected=p.project_feature_store_frame(data,list(row))
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv","parquet"):
                path=Path(tmp)/("mixed."+suffix)
                if suffix=="csv":
                    projected.to_csv(path,index=False);reread=pd.read_csv(path,dtype={"cik":str})
                else:
                    projected.to_parquet(path,index=False);reread=pd.read_parquet(path)
                out=f.enforce_native_valuation_context(reread)
                pd.testing.assert_series_equal(out["dividend_payout_ratio"].reset_index(drop=True),expected["dividend_payout_ratio"].reset_index(drop=True))
                pd.testing.assert_series_equal(out["dividend_policy_score"].reset_index(drop=True),expected["dividend_policy_score"].reset_index(drop=True))

    def test_quarter_cumulative_full_scope_refusal_preserves_independent_observations(self):
        import r1000_pipeline as p
        raw=[self.row(unit="USD",period=pd.Timestamp(end),start=pd.Timestamp(start),accepted=pd.Timestamp(end)+pd.Timedelta(days=30),
            fy=year,fp=fp,form=form,accession_number="scope-"+end,value=value,duration_days=duration,entity_scope="consolidated")
            for start,end,year,fp,form,value,duration in (
                ("2024-01-01","2024-06-30",2024,"Q2","10-Q",200.0,182),
                ("2024-01-01","2024-12-31",2024,"FY","10-K",1000.0,366),
                ("2025-01-01","2025-03-31",2025,"Q1","10-Q",50.0,90),
                ("2025-04-01","2025-06-30",2025,"Q2","10-Q",300.0,91))]
        extras=[]
        for field in ("net_income","op_income"):
            for index in (0,1,3):
                item={**raw[index],"field_name":field,"source_tag":field,"value":{0:20.0,1:100.0,3:50.0}[index]}
                if index==3:item.update(start=pd.Timestamp("2025-01-01"),duration_days=181)
                extras.append(item)
        for field,amount in (("assets",1000.0),("liabilities",400.0),("shares",100.0)):
            extras.append({**raw[-1],"field_name":field,"source_tag":field,"value":amount,"start":pd.NaT,
                "unit":"shares" if field=="shares" else "USD"})
        positive=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(raw+extras))).iloc[-1]
        self.assertEqual(positive["revenues_cum_value"],350.0)
        self.assertEqual(positive["revenues_ttm"],1150.0)
        self.assertEqual(positive["fund_panel_ttm_ready"],1.0)
        for change in (dict(entity_scope="subsidiary"),dict(entity_id="other-company"),dict(segment="other-segment")):
            bad=[dict(item) for item in raw];bad[2].update(change)
            flows=p.companyfacts_quarterly_flows(select_accession_field_records(pd.DataFrame(bad)))
            self.assertEqual(flows.iloc[-1]["flow"],300.0)
            self.assertTrue(pd.isna(flows.iloc[-1]["cum_value"]))
            self.assertTrue(flows.iloc[-1]["cum_missing_reason"])
            panel=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(bad+extras)))
            latest=panel.iloc[-1]
            self.assertEqual(latest["revenues"],300.0)
            self.assertTrue(pd.isna(latest["revenues_cum_value"]))
            self.assertTrue(pd.isna(latest["revenues_ttm"]))
            self.assertEqual(latest["fund_panel_ttm_ready"],0.0)
            self.assertEqual(panel.iloc[1]["revenues_ttm"],1000.0)  # independent annual survives

    def test_mixed_native_legacy_and_source_interleave_preserves_each_history(self):
        import r1000_features as f
        periods=pd.date_range("2024-03-31",periods=5,freq="QE-DEC")
        legacy=pd.DataFrame([dict(cik="0000000001",ticker="LEG",source="fsds",period=end,
            accepted=end+pd.Timedelta(days=20),revenues=100.0,ocf=15.0,capex=5.0,assets=1000.0,
            liabilities=400.0,shares=100.0,net_income=10.0,op_income=20.0) for end in periods])
        alone=f.recompute_fund_panel_derived_columns(legacy)
        self.assertEqual(alone.iloc[-1]["revenues_ttm"],400.0)
        self.assertEqual(alone.iloc[-1]["fcf_ttm"],40.0)
        self.assertEqual(alone.iloc[-1]["financial_context_status"],"UNVERIFIED")
        typed=[]
        for i,end in enumerate(periods):
            start=end-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            for field,amount in (("revenues",200.0),("ocf",25.0),("capex",5.0)):
                typed.append(self.row(cik="0000000001",ticker="NAT",unit="USD",period=end,start=start,
                    accepted=end+pd.Timedelta(days=20),fy=end.year,fp="Q"+str((end.month-1)//3+1),form="10-Q",
                    accession_number="mixed-"+str(i),field_name=field,source_tag=field,value=amount,duration_days=(end-start).days+1))
        native=build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(typed)))
        native["source"]="companyfacts"
        native_alone=f.recompute_fund_panel_derived_columns(native)
        yf=legacy.copy();yf["source"]="yfinance";yf["ticker"]="YF";yf["revenues"]=300.0
        placeholder={key:float("nan") for key in legacy.columns}
        placeholder.update(cik="0000000002",ticker="UNKNOWN",source="companyfacts",
            period=periods[-1],accepted=periods[-1]+pd.Timedelta(days=20),financial_metadata_version="native-unit-fiscal-v1")
        for null in (None,float("nan"),"","null"):
            current=legacy.copy();current["financial_metadata_version"]=null
            mixed=pd.concat([current,native,yf,pd.DataFrame([placeholder])],ignore_index=True)
            for frame in (mixed,mixed.iloc[::-1]):
                out=f.recompute_fund_panel_derived_columns(frame)
                for source,want in (("fsds",400.0),("companyfacts",800.0),("yfinance",1200.0)):
                    selected=out[(out["source"]==source)&(out["cik"]=="0000000001")].sort_values("period")
                    self.assertEqual(len(selected),5)
                    self.assertEqual(selected.iloc[-1]["revenues_ttm"],want)
                    self.assertEqual(selected.iloc[-1]["fcf_ttm"],80.0 if source=="companyfacts" else 40.0)
                    self.assertEqual(selected.iloc[-1]["financial_context_status"],"NATIVE_TYPED_NOT_SOURCE_ADMISSION" if source=="companyfacts" else "UNVERIFIED")
                unknown=out[out["ticker"]=="UNKNOWN"].iloc[0]
                self.assertTrue(pd.isna(unknown["revenues_ttm"]))
                self.assertEqual(unknown["fund_ttm_ready"],0.0)
        # The lower-level APIs share the same classification, including when
        # called directly with a new issuer/schema column rather than via panel.
        mixed=pd.concat([legacy,pd.DataFrame([placeholder])],ignore_index=True)
        ttm,_=f.compute_flow_ttm_with_cum_fallback(mixed,"revenues")
        self.assertEqual(ttm.iloc[4],400.0)
        lag,_=f._flexible_lag(mixed,"assets",4,1)
        self.assertEqual(lag.iloc[4],1000.0)
        unsupported=pd.DataFrame([{**placeholder,"financial_metadata_version":True}])
        refused=f.recompute_fund_panel_derived_columns(pd.concat([legacy,unsupported],ignore_index=True))
        self.assertEqual(refused.iloc[4]["fcf_ttm"],40.0)
        self.assertEqual(refused.iloc[-1]["financial_context_status"],"UNKNOWN_FINANCIAL_METADATA")
        self.assertEqual(refused.iloc[-1]["fundamental_missing_reason"],"unknown_financial_metadata_version")
        unknowns=pd.DataFrame([{**placeholder,"cik":None,"ticker":name} for name in ("UNBOUND_A","UNBOUND_B")])
        preserved=f.recompute_fund_panel_derived_columns(pd.concat([legacy,unknowns],ignore_index=True))
        self.assertEqual(list(preserved["ticker"])[-2:],["UNBOUND_A","UNBOUND_B"])
        self.assertEqual(len(preserved),7)
        # Adding a null scope column or reordering raw native records does not
        # change native scope equivalence or the independently derived values.
        expanded=pd.DataFrame(typed);expanded["entity_id"]=None
        expanded=expanded.iloc[::-1]
        from_null=build_exact_fundamental_panel(select_accession_field_records(expanded))
        self.assertEqual(from_null.iloc[-1]["revenues_ttm"],native_alone.iloc[-1]["revenues_ttm"])


    def test_current_fcf_margin_and_rule_of_40_revalidate_all_semantic_parents(self):
        import r1000_features as f
        import r1000_pipeline as p
        seed=pd.DataFrame([{**self.financial().to_dict(),**self.price_context(),"ticker":"SYN",
            "current_price_live":10.0,"px":10.0,"mktcap":1000.0,"revenue_growth_final":0.0}])
        cache={}
        original=f.enforce_native_valuation_context(seed,_operation_cache=cache)
        original["fcf_cagr_1y"]=0.4
        self.assertEqual(original.loc[0,"fcf_margin"],0.12)
        self.assertEqual(original.loc[0,"rule_of_40"],0.12)
        for change in ("revenue","growth","both","unit","scope","period","zero","missing","negative","growth_missing"):
            changed=original.copy()
            if change in ("revenue","both"):changed["revenues_ttm"]=1000.0
            if change in ("growth","both"):changed["revenue_growth_final"]=0.1
            if change=="unit":changed["revenues_ttm_unit"]="EUR"
            if change=="scope":
                proof=json.loads(changed.loc[0,"revenues_ttm_provenance"])
                proof[0]["context_dimensions"]="other-segment"
                changed["revenues_ttm_provenance"]=json.dumps(proof)
            if change=="period":
                context=json.loads(changed.loc[0,"revenues_ttm_financial_context"])
                context.update(period_start="2024-01-01",period_end="2024-12-31")
                proof=json.loads(changed.loc[0,"revenues_ttm_provenance"])
                proof[0].update(start="2024-01-01",period="2024-12-31")
                changed["revenues_ttm_financial_context"],changed["revenues_ttm_provenance"]=json.dumps(context),json.dumps(proof)
            if change=="zero":changed["revenues_ttm"]=0.0
            if change=="missing":changed["revenues_ttm"]=float("nan")
            if change=="negative":changed["revenues_ttm"]=-500.0
            if change=="growth_missing":changed["revenue_growth_final"]=float("nan")
            cached=f.enforce_native_valuation_context(changed,_operation_cache=cache)
            fresh=f.enforce_native_valuation_context(changed)
            pd.testing.assert_frame_equal(cached,fresh)
            direct=f.native_valuation_overrides(changed.iloc[0],technical_price=10.0)
            self.assertEqual(cached.loc[0,"fcf_ttm"],60.0)
            self.assertEqual(cached.loc[0,"fcf_cagr_1y"],0.4)  # revenue/growth do not invalidate FCF history
            if change in ("unit","scope","period","zero","missing"):
                for field in ("fcf_margin","rule_of_40"):
                    self.assertTrue(pd.isna(cached.loc[0,field]),(change,field))
                    self.assertTrue(pd.isna(direct[field]),(change,field))
                    self.assertTrue(cached.loc[0,field+"_missing_reason"])
            else:
                margin=-0.12 if change=="negative" else 0.06 if change in ("revenue","both") else 0.12
                self.assertAlmostEqual(cached.loc[0,"fcf_margin"],margin)
                self.assertEqual(cached.loc[0,"fcf_margin_missing_reason"],"")
                if change=="growth_missing":
                    self.assertTrue(pd.isna(cached.loc[0,"rule_of_40"]))
                    self.assertEqual(cached.loc[0,"rule_of_40_missing_reason"],"missing_current_revenue_growth")
                else:
                    expected=margin+(0.1 if change in ("growth","both") else 0.0)
                    self.assertAlmostEqual(cached.loc[0,"rule_of_40"],expected)
                    self.assertAlmostEqual(direct["rule_of_40"],expected)
                    self.assertEqual(cached.loc[0,"rule_of_40_missing_reason"],"")
        # Current growth is a tail dependency on every hit, without another
        # native parse; the same current value reaches actual Main valuation.
        cache={}
        with patch.object(f,"native_valuation_overrides",wraps=f.native_valuation_overrides) as native:
            stable=f.enforce_native_valuation_context(original,_operation_cache=cache)
            stable["revenue_growth_final"]=0.1
            tail=f.enforce_native_valuation_context(stable,_operation_cache=cache)
            self.assertEqual(native.call_count,1)
            self.assertAlmostEqual(tail.loc[0,"rule_of_40"],0.22)
            self.assertEqual(tail.loc[0,"fcf_cagr_1y"],0.4)
        changed=original.copy();changed["revenues_ttm"],changed["revenue_growth_final"]=1000.0,0.1
        main=p.compute_valuation_columns(changed)
        self.assertEqual(main.loc[0,"fcf_margin"],0.06)
        self.assertAlmostEqual(main.loc[0,"rule_of_40"],0.16)
        self.assertEqual(main.loc[0,"fcf_cagr_1y"],0.4)
        zero=original.copy();zero["ocf_ttm"]=20.0
        self.assertEqual(f.enforce_native_valuation_context(zero).loc[0,"fcf_margin"],0.0)
        loss=original.copy();loss["ocf_ttm"]=-40.0
        self.assertEqual(f.enforce_native_valuation_context(loss).loc[0,"fcf_margin"],-0.12)


    def test_public_mixed_legacy_native_unknown_calculate_store_read_normalize(self):
        import r1000_features as f
        import r1000_pipeline as p
        from r1000_config import EngineConfig
        native = {**self.financial().to_dict(), **self.price_context(), "ticker": "NATIVE",
            "px": 10.0, "current_price_live": 10.0, "mktcap": 1000.0, "revenue_growth_final": 0.1,
            "fcf_cagr_1y": 0.4, "eps_ttm": 0.5}
        legacy = {key: value for key, value in native.items()
            if not key.endswith(("_unit", "_provenance", "_financial_context"))
            and key != "financial_metadata_version"}
        legacy.update(ticker="LEGACY", source="fsds", financial_context_status="UNVERIFIED")
        unknown = {**native, "ticker": "UNKNOWN", "financial_metadata_version": "unsupported-v99"}
        keep = ["ticker", "source", "px", "current_price_live", "mktcap", "shares", "assets", "liabilities",
            "net_income_ttm", "revenues_ttm", "ocf_ttm", "capex_ttm", "fcf_ttm", "eps_ttm",
            "fcf_cagr_1y", "revenue_growth_final"]
        for rows in ([legacy, native, unknown], [unknown, native, legacy]):
            with patch.object(f, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()):
                calculated = p.compute_valuation_columns(f.compute_live_factor_columns(pd.DataFrame(rows)))
                projected = p.project_feature_store_frame(calculated, keep)
                with tempfile.TemporaryDirectory() as tmp:
                    for suffix in ("csv", "parquet"):
                        path = Path(tmp) / ("mixed." + suffix)
                        if suffix == "csv":
                            projected.to_csv(path, index=False)
                            reread = pd.read_csv(path, dtype={"cik": str})
                        else:
                            projected.to_parquet(path, index=False)
                            reread = pd.read_parquet(path)
                        with patch.object(p, "repair_latest_history_depth_from_diagnostics", side_effect=lambda paths, frame: frame):
                            result = p.normalize_latest_fundamental_snapshot(EngineConfig(), {}, reread,
                                apply_statement_repair=False, add_fundamental_flags=False).set_index("ticker")
                        self.assertEqual(set(result.index), {"LEGACY", "NATIVE", "UNKNOWN"})
                        for column, amount in (("fcf_ttm", 60.0), ("eps_ttm", 0.5), ("fcf_cagr_1y", 0.4)):
                            self.assertEqual(result.loc["LEGACY", column], amount, (suffix, column))
                        self.assertEqual(result.loc["LEGACY", "financial_context_status"], "UNVERIFIED")
                        self.assertEqual(result.loc["LEGACY", "valuation_context_status"], "UNVERIFIED")
                        self.assertEqual(result.loc["LEGACY", "fund_ttm_ready"], 0.0)
                        self.assertAlmostEqual(result.loc["NATIVE", "ep_ttm"], 0.05)
                        self.assertTrue(pd.isna(result.loc["UNKNOWN", "mktcap"]))
                        self.assertTrue(pd.isna(result.loc["UNKNOWN", "fcf_ttm"]))

    def test_nullable_proof_aliases_preserve_eps_and_equity_but_not_malformed_primary(self):
        import r1000_features as f
        for absent in (None, float("nan"), pd.NA, "", "null"):
            row = self.financial().copy()
            for field in ("shares", "net_income_ttm", "assets", "liabilities"):
                row[field + "_fact_provenance"] = row[field + "_provenance"]
                row[field + "_provenance"] = absent
            out = f.native_valuation_overrides(row, technical_price=10.0, price_context=self.price_context())
            self.assertEqual(out["eps_ttm"], 0.5)
            self.assertIsNotNone(f.native_financial_context(out, "eps_ttm"))
            self.assertIsNotNone(f.native_financial_context(out, "equity_native"))
            self.assertNotIn(None, json.loads(out["eps_ttm_provenance"])["parents"])
            for malformed in (True, 123, "not-json"):
                bad = row.copy(); bad["shares_provenance"] = malformed
                refused = f.native_valuation_overrides(bad, technical_price=10.0, price_context=self.price_context())
                self.assertTrue(pd.isna(refused["eps_ttm"]))
        rows = []
        for i, period in enumerate(pd.date_range("2024-03-31", periods=8, freq="QE-DEC")):
            start = period - pd.offsets.QuarterEnd() + pd.Timedelta(days=1)
            common = dict(period=period, accepted=period+pd.Timedelta(days=20), fy=period.year,
                fp="Q"+str((period.month-1)//3+1), accession_number="alias-"+str(i))
            rows.append(self.row(**common, field_name="net_income", unit="USD", start=start, value=10.0,
                duration_days=(period-start).days+1))
            rows.append(self.row(**common, field_name="shares", unit="shares", start=pd.NaT, value=100.0))
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        panel["shares_provenance"] = None
        result = f.recompute_fund_panel_derived_columns(panel).iloc[-1]
        self.assertEqual(result["eps_ttm"], 0.4)
        self.assertIsNotNone(f.native_financial_context(result, "eps_ttm"))

    def test_native_yoy_scope_refusal_precedes_downstream_growth_consumers(self):
        import r1000_features as f
        rows = []
        for i, period in enumerate(pd.date_range("2024-03-31", periods=8, freq="QE-DEC")):
            start = period-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            rows.append(self.row(unit="USD", period=period, start=start, accepted=period+pd.Timedelta(days=20),
                fy=period.year, fp="Q"+str((period.month-1)//3+1), accession_number="scope-yoy-"+str(i),
                value=100.0 if i < 4 else 200.0, duration_days=(period-start).days+1,
                context_dimensions=None if i < 4 else "subsidiary"))
        refused = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertEqual(refused.iloc[-1]["revenues_ttm"], 800.0)
        self.assertTrue(pd.isna(refused.iloc[-1]["sales_growth_yoy"]))
        self.assertTrue(pd.isna(refused.iloc[-1]["sales_cagr_1y"]))
        self.assertEqual(refused.iloc[-1]["sales_growth_yoy_missing_reason"], "incompatible_or_missing_native_comparison_context")
        with patch.object(f, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()):
            downstream = f.compute_live_factor_columns(refused.tail(1))
        self.assertTrue(pd.isna(downstream.iloc[0]["revenue_growth_final"]))
        same = [{**row, "context_dimensions": None} for row in rows]
        control = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(same)))
        self.assertEqual(control.iloc[-1]["sales_growth_yoy"], 1.0)

    def test_malformed_text_evidence_roundtrip_retains_each_row_and_refusal(self):
        import r1000_features as f
        import r1000_pipeline as p
        from r1000_config import EngineConfig
        base = {**self.financial().to_dict(), **self.price_context(), "ticker": "VALID",
            "px": 10.0, "current_price_live": 10.0, "mktcap": 1000.0, "revenue_growth_final": 0.1,
            "price_to_sales": 2.0, "valuation_px": 10.0, "price_above_ma200": 1.0, "valuation_blueprint_score": 0.3}
        for field, malformed in [(field, True) for field in ("shares_unit", "shares_basis", "price_currency", "price_asof",
            "share_basis_status", "share_basis_reference", "financial_metadata_version")] + [
            ("share_basis_reference", value) for value in ({}, [], {"claimed": "reference"}, ["reference"],
                pd.Timestamp("2026-07-01"), np.datetime64("2026-07-01"),
                pd.Timestamp("2026-07-01").to_pydatetime(), pd.Timestamp("2026-07-01").date())]:
            rows = [base, {**base, "ticker": "ABSENT", field: None}, {**base, "ticker": "MALFORMED", field: malformed}]
            frame = pd.DataFrame(rows)
            # Observe the actual pre-serialization refusal; no malformed scalar
            # may become an accepted reference merely by converting to text.
            before = f.enforce_native_valuation_context(frame).set_index("ticker")
            self.assertTrue(pd.isna(before.loc["MALFORMED", "mktcap"]))
            projected = p.project_feature_store_frame(frame, ["ticker", "px", "current_price_live", "mktcap",
                "shares", "assets", "liabilities", "net_income_ttm", "revenues_ttm", "ocf_ttm", "capex_ttm", "revenue_growth_final"])
            for column in ("price_to_sales", "valuation_px", "price_above_ma200", "valuation_blueprint_score"):
                self.assertTrue(pd.api.types.is_numeric_dtype(projected[column]), column)
                self.assertEqual(projected.loc[0, column], base[column])
            with tempfile.TemporaryDirectory() as tmp:
                for suffix in ("csv", "parquet"):
                    path = Path(tmp) / ("text." + suffix)
                    if suffix == "csv":
                        projected.to_csv(path, index=False)
                        read = pd.read_csv(path, dtype={"cik": str})
                    else:
                        projected.to_parquet(path, index=False)
                        read = pd.read_parquet(path)
                    with patch.object(f, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()), \
                        patch.object(p, "repair_latest_history_depth_from_diagnostics", side_effect=lambda paths, frame: frame):
                        result = p.normalize_latest_fundamental_snapshot(EngineConfig(), {}, read,
                            apply_statement_repair=False, add_fundamental_flags=False).set_index("ticker")
                    self.assertEqual(len(result), 3)
                    self.assertEqual(result.loc["VALID", "mktcap"], 1000.0)
                    self.assertTrue(pd.isna(result.loc["MALFORMED", "mktcap"]), (field, suffix))
                    if field != "financial_metadata_version":
                        self.assertTrue(pd.isna(result.loc["ABSENT", "mktcap"]), (field, suffix))
                    else:
                        self.assertEqual(result.loc["ABSENT", "valuation_context_status"], "UNVERIFIED")
        # Existing validators explicitly allow numeric CIKs and these three
        # datetime types; projection must preserve their economic meaning.
        frame = pd.DataFrame([{**base, "ticker": str(i), "cik": cik} for i, cik in enumerate((1, 1.0, np.int64(1)))])
        frame["price_asof"] = pd.Series([np.datetime64("2026-07-10T20:00:00"),
            pd.Timestamp("2026-07-10T20:00:00Z"), pd.Timestamp("2026-07-10T20:00:00Z").to_pydatetime()], dtype=object)
        self.assertTrue(f.enforce_native_valuation_context(frame)["mktcap"].eq(1000.0).all())
        projected = p.project_feature_store_frame(frame, ["ticker", "px", "mktcap", "shares",
            "assets", "liabilities", "net_income_ttm", "revenues_ttm", "ocf_ttm", "capex_ttm"])
        self.assertTrue(projected["cik"].eq("0000000001").all())
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv", "parquet"):
                path = Path(tmp) / ("valid_roles." + suffix)
                if suffix == "csv":
                    projected.to_csv(path, index=False)
                    read = pd.read_csv(path, dtype={"cik": str})
                else:
                    projected.to_parquet(path, index=False)
                    read = pd.read_parquet(path)
                with patch.object(f, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()), \
                    patch.object(p, "repair_latest_history_depth_from_diagnostics", side_effect=lambda paths, frame: frame):
                    result = p.normalize_latest_fundamental_snapshot(EngineConfig(), {}, read,
                        apply_statement_repair=False, add_fundamental_flags=False)
                self.assertTrue(result["mktcap"].eq(1000.0).all())

    def test_guarded_forward_ps_preserves_existing_growth_clip_with_fx(self):
        import r1000_features as f
        import r1000_pipeline as p
        for currency, fx in (("USD", {}), ("EUR", dict(fx_rate=2.0, fx_status="VERIFIED", fx_reference="synthetic-fx",
            fx_from_currency="EUR", fx_to_currency="USD", fx_asof="2026-07-10T19:00:00Z", fx_valid_until="2026-07-10T21:00:00Z"))):
            for growth, expected in ((-0.8, 4.0), (-1.0, 4.0), (5.0, 2.0/3.0), (0.0, 2.0)):
                row = {**self.financial(currency).to_dict(), **self.price_context(), **fx, "ticker": "SYN",
                    "px": 10.0, "current_price_live": 10.0, "mktcap": 1000.0, "revenue_growth_final": growth}
                with patch.object(f, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()):
                    result = p.compute_valuation_columns(f.compute_live_factor_columns(pd.DataFrame([row]))).iloc[0]
                for column in ("forward_ps", "forward_ps_final"):
                    self.assertAlmostEqual(result[column], expected / (2 if currency == "EUR" else 1))


    def test_projection_preserves_every_validated_owner_and_field_identity_conflict(self):
        import r1000_features as f
        import r1000_pipeline as p
        row = {**self.financial().to_dict(), **self.price_context(), "ticker": "SYN", "current_price_live": 10.0}
        identities = {"cik": "0000000001", "issuer_id": "issuer-one", "entity_id": "entity-one", "entity": "owner-one"}
        row.update(identities)
        for field in ("shares", "net_income_ttm", "revenues_ttm", "ocf_ttm", "capex_ttm", "fcf_ttm", "assets", "liabilities"):
            proof = json.loads(row[field + "_provenance"])
            proof[0].update(identities)
            context = json.loads(row[field + "_financial_context"])
            context["identities"] = identities
            row[field + "_provenance"] = json.dumps(proof)
            row[field + "_financial_context"] = json.dumps(context)
        cases = [("valid", row)]
        for identity in identities:
            bad = "0000000002" if identity == "cik" else "conflicting-owner"
            cases.append(("owner-" + identity, {**row, identity: bad}))
            cases.append(("field-" + identity, {**row, "shares_" + identity: bad, "shares_context_dimensions": None}))
        frame = pd.DataFrame([{**value, "ticker": label} for label, value in cases])
        before = f.enforce_native_valuation_context(frame).set_index("ticker")
        self.assertEqual(before.loc["valid", "mktcap"], 1000.0)
        self.assertTrue(before.drop(index="valid")["mktcap"].isna().all())
        projected = p.project_feature_store_frame(frame, ["ticker", "current_price_live", "shares", "assets",
            "liabilities", "net_income_ttm", "revenues_ttm", "ocf_ttm", "capex_ttm"])
        self.assertIn("entity", projected)
        self.assertIn("shares_entity", projected)
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv", "parquet"):
                path = Path(tmp) / ("owner_identity." + suffix)
                if suffix == "csv":
                    projected.to_csv(path, index=False)
                    read = pd.read_csv(path, dtype={"cik": str, "shares_cik": str})
                else:
                    projected.to_parquet(path, index=False)
                    read = pd.read_parquet(path)
                guarded = f.enforce_native_valuation_context(read).set_index("ticker")
                self.assertEqual(guarded.loc["valid", "mktcap"], 1000.0)
                self.assertAlmostEqual(guarded.loc["valid", "ep_ttm"], 0.05)
                self.assertTrue(guarded.drop(index="valid")["mktcap"].isna().all(), suffix)
                self.assertTrue(guarded.drop(index="valid")["ep_ttm"].isna().all(), suffix)

    def test_margin_stability_uses_validated_native_ratios_before_public_scores(self):
        import r1000_features as f
        rows = []
        for i, period in enumerate(pd.date_range("2024-03-31", periods=8, freq="QE-DEC")):
            start = period-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            common = dict(period=period, start=start, accepted=period+pd.Timedelta(days=20), fy=period.year,
                fp="Q"+str((period.month-1)//3+1), accession_number="margin-history-"+str(i),
                duration_days=(period-start).days+1)
            for field, value in (("revenues", 100.0), ("op_income", 20.0)):
                rows.append(self.row(**common, field_name=field, value=value, unit="EUR", source_tag=field))
        control = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        self.assertAlmostEqual(control.iloc[-1]["op_margin_ttm"], 0.2)
        self.assertAlmostEqual(control.iloc[-1]["margin_stability_8q"], 0.0)
        for mismatch in ("unit", "scope"):
            bad = [{**row, **({"unit": "USD"} if mismatch == "unit" else {"context_dimensions": "subsidiary"})}
                if row["field_name"] == "op_income" else row for row in rows]
            panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(bad)))
            self.assertTrue(panel["op_margin_ttm"].isna().all())
            self.assertTrue(panel["margin_stability_8q"].isna().all())
            with patch.object(f, "_load_finnhub_features_for_fallback", return_value=pd.DataFrame()):
                public = f.compute_live_factor_columns(panel.tail(2))
            self.assertTrue(public["margin_stability_8q"].isna().all())
        # A subsequently refused current operand cannot retain old histories,
        # on either a direct guard pass or an operation-cache hit.
        latest = control.tail(1).copy(); cache = {}
        stable = f.enforce_native_valuation_context(latest, _operation_cache=cache)
        self.assertAlmostEqual(stable.iloc[0]["margin_stability_8q"], 0.0)
        stable["op_income_ttm_unit"] = "USD"
        for result in (f.enforce_native_valuation_context(stable), f.enforce_native_valuation_context(stable, _operation_cache=cache)):
            self.assertTrue(pd.isna(result.iloc[0]["margin_stability_8q"]))
        # Each current ratio may be valid while old/current scopes differ.
        # Keep the original eight-observation window and minimum four, using
        # only compatible observations in that window.
        scoped = []
        for i, period in enumerate(pd.date_range("2024-03-31", periods=11, freq="QE-DEC")):
            start = period-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            for field, value in (("revenues", 100.0), ("op_income", 20.0 if i < 4 else 40.0)):
                scoped.append(self.row(period=period, start=start, accepted=period+pd.Timedelta(days=20),
                    fy=period.year, fp="Q"+str((period.month-1)//3+1), accession_number="scope-rolling-"+str(i),
                    duration_days=(period-start).days+1, field_name=field, value=value, unit="USD", source_tag=field,
                    context_dimensions=None if i < 4 else "subsidiary"))
        histories = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(scoped)))
        self.assertTrue(pd.isna(histories.iloc[9]["margin_stability_8q"]))
        self.assertAlmostEqual(histories.iloc[10]["margin_stability_8q"], 0.0)
        def rescope(value):
            if isinstance(value, str):
                try:
                    return json.dumps(rescope(json.loads(value)), sort_keys=True)
                except (ValueError, TypeError):
                    return value
            if isinstance(value, list):
                return [rescope(item) for item in value]
            if isinstance(value, dict):
                return {key: "subsidiary" if key in {"context_dimensions", "dimensions"} else rescope(item)
                    for key, item in value.items()}
            return value
        unchanged_ratio = control.tail(1).copy()
        for field in ("op_income_ttm", "revenues_ttm"):
            for suffix in ("_financial_context", "_provenance"):
                unchanged_ratio[field + suffix] = unchanged_ratio[field + suffix].map(rescope)
        changed_scope = f.enforce_native_valuation_context(unchanged_ratio)
        self.assertAlmostEqual(changed_scope.iloc[0]["op_margin_ttm"], 0.2)
        self.assertTrue(pd.isna(changed_scope.iloc[0]["margin_stability_8q"]))
        # The ratio's own context/proof must survive production projection too.
        import r1000_pipeline as p
        projected = p.project_feature_store_frame(control.tail(1), ["cik", "op_income_ttm", "revenues_ttm",
            "op_margin_ttm", "margin_stability_8q"])
        self.assertIn("op_margin_ttm_financial_context", projected)
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("csv", "parquet"):
                path = Path(tmp) / ("margin_history." + suffix)
                if suffix == "csv":
                    projected.to_csv(path, index=False)
                    read = pd.read_csv(path, dtype={"cik": str})
                else:
                    projected.to_parquet(path, index=False)
                    read = pd.read_parquet(path)
                out = f.enforce_native_valuation_context(read)
                self.assertAlmostEqual(out.iloc[0]["margin_stability_8q"], 0.0)


    def test_mixed_direct_and_ytd_proofs_preserve_valid_ttm_context_and_refuse_changed_selection(self):
        import r1000_features as f
        rows = []
        for year, scale in ((2025, 1.0), (2026, 1.2)):
            cumulative = 0.0
            for quarter, amount in enumerate((100.0, 150.0, 200.0, 250.0), 1):
                period = pd.Timestamp(year=year, month=quarter*3, day=1)+pd.offsets.MonthEnd()
                start = period-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
                cumulative += amount*scale
                common = dict(unit="USD", period=period, accepted=period+pd.Timedelta(days=20), fy=year,
                    fp="FY" if quarter == 4 else "Q"+str(quarter), form="10-K" if quarter == 4 else "10-Q",
                    accession_number=f"mixed-{year}-{quarter}", field_name="revenues", source_tag="Revenue")
                if quarter != 4:
                    rows.append(self.row(**common, start=start, value=amount*scale,
                        duration_days=(period-start).days+1, semantic_rank=0))
                if quarter != 1:
                    fy_start = pd.Timestamp(year=year, month=1, day=1)
                    rows.append(self.row(**common, start=fy_start, value=cumulative,
                        duration_days=(period-fy_start).days+1, semantic_rank=0 if quarter == 4 else 1))
        panel = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        latest = panel.iloc[-1]
        self.assertAlmostEqual(latest["revenues_ttm"], 840.0)
        self.assertIsNotNone(f.native_financial_context(latest, "revenues_ttm"))
        self.assertIn("native_quarter_plus_prior_ytd", latest["revenues_ttm_provenance"])
        self.assertIn("native_ytd_minus_prior_ytd", latest["revenues_ttm_provenance"])
        wrong = latest.copy()
        proof = json.loads(wrong["revenues_ttm_provenance"])
        proof[1]["native_period_start"] = "2020-01-01"
        wrong["revenues_ttm_provenance"] = json.dumps(proof)
        self.assertIsNone(f.native_financial_context(wrong, "revenues_ttm"))

    def test_roe_and_debt_history_validate_before_trends_and_turnaround(self):
        import r1000_features as f
        rows = []
        for i, period in enumerate(pd.date_range("2024-03-31", periods=8, freq="QE-DEC")):
            start = period-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            common = dict(period=period, accepted=period+pd.Timedelta(days=20), fy=period.year,
                fp="Q"+str((period.month-1)//3+1), accession_number="roe-"+str(i))
            rows.append(self.row(**common, field_name="net_income", source_tag="NetIncomeLoss", start=start,
                duration_days=(period-start).days+1, value=20.0, unit="USD"))
            rows.append(self.row(**common, field_name="assets", source_tag="Assets", start=pd.NaT,
                value=100.0 if i < 4 else 400.0, unit="USD"))
            rows.append(self.row(**common, field_name="liabilities", source_tag="Liabilities", start=pd.NaT,
                value=250.0, unit="EUR"))
        bad = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows)))
        for column in ("roe_proxy", "roe_trend_4q", "debt_to_equity", "debt_to_equity_delta_4q"):
            self.assertTrue(bad[column].isna().all(), column)
        for column in ("roe_turn_positive_4q", "any_profitability_turn_positive_4q"):
            self.assertTrue(bad[column].eq(0).all(), column)
        good_rows = [{**row, "unit": "USD"} for row in rows]
        good = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(good_rows)))
        self.assertGreater(good.iloc[-1]["roe_trend_4q"], 0)
        self.assertEqual(good.iloc[-1]["roe_turn_positive_4q"], 1.0)
        cache = {}
        stable = f.enforce_native_valuation_context(good.tail(1), _operation_cache=cache)
        self.assertEqual(stable.iloc[0]["roe_turn_positive_4q"], 1.0)
        stable["liabilities_unit"] = "EUR"
        for guarded in (f.enforce_native_valuation_context(stable), f.enforce_native_valuation_context(stable, _operation_cache=cache)):
            self.assertTrue(pd.isna(guarded.iloc[0]["roe_trend_4q"]))
            self.assertEqual(guarded.iloc[0]["roe_turn_positive_4q"], 0.0)
            self.assertEqual(guarded.iloc[0]["any_profitability_turn_positive_4q"], 0.0)

    def test_public_turnaround_aliases_use_only_valid_current_parent_signals(self):
        import r1000_features as f
        rows = []
        for i, period in enumerate(pd.date_range("2024-03-31", periods=8, freq="QE-DEC")):
            start = period-pd.offsets.QuarterEnd()+pd.Timedelta(days=1)
            common = dict(period=period, accepted=period+pd.Timedelta(days=20), fy=period.year,
                fp="Q"+str((period.month-1)//3+1), accession_number="signals-"+str(i))
            for field, value in (("net_income", 20.0), ("ocf", -10.0 if i < 4 else 30.0), ("capex", 0.0)):
                rows.append(self.row(**common, field_name=field, source_tag=field, start=start,
                    duration_days=(period-start).days+1, value=value, unit="USD"))
            for field, value in (("assets", 100.0 if i < 4 else 400.0), ("liabilities", 250.0)):
                rows.append(self.row(**common, field_name=field, source_tag=field, start=pd.NaT, value=value, unit="USD"))
        seed = build_exact_fundamental_panel(select_accession_field_records(pd.DataFrame(rows))).tail(1)
        cache = {}
        stable = f.enforce_native_valuation_context(seed, _operation_cache=cache)
        self.assertEqual(stable.iloc[0]["cashflow_turn_positive_4q"], 1.0)
        for bad_field, expected_cash in (("ocf_ttm_unit", 0.0), ("capex_ttm_unit", 1.0)):
            bad = stable.copy()
            bad["liabilities_unit"] = "EUR"
            bad[bad_field] = "EUR"
            for options in ({}, {"_operation_cache": cache}):
                actual = f.enforce_native_valuation_context(bad, **options).iloc[0]
                self.assertTrue(pd.isna(actual["fcf_ttm"]))
                self.assertTrue(pd.isna(actual["roe_proxy"]))
                self.assertEqual(actual["roe_turn_positive_4q"], 0.0)
                self.assertEqual(actual["cashflow_turn_positive_4q"], expected_cash)
                self.assertEqual(actual["any_profitability_turn_positive_4q"], expected_cash)
                self.assertEqual(actual["any_profit_sign_flip_pos"], expected_cash)
        for field, value in (("ocf_ttm_unit", None), ("ocf_ttm", float("inf")), ("ocf_ttm", True)):
            bad = stable.copy()
            bad["liabilities_unit"] = "EUR"
            bad[field] = value
            for options in ({}, {"_operation_cache": cache}):
                actual = f.enforce_native_valuation_context(bad, **options).iloc[0]
                self.assertEqual(actual["cashflow_turn_positive_4q"], 0.0, (field, value))
                self.assertEqual(actual["any_profitability_turn_positive_4q"], 0.0, (field, value))
        # Feature projections can retain the user alias without internal leaves.
        projected = stable.drop(columns=["ocf_sign_flip_pos", "fcf_sign_flip_pos"])
        projected["liabilities_unit"] = projected["ocf_ttm_unit"] = "EUR"
        actual = f.enforce_native_valuation_context(projected).iloc[0]
        self.assertEqual(actual["cashflow_turn_positive_4q"], 0.0)
        self.assertEqual(actual["any_profitability_turn_positive_4q"], 0.0)

    def test_undated_candidate_does_not_replace_existing_latest_history(self):
        import r1000_pipeline as p
        periods = pd.date_range("2025-03-31", periods=5, freq="QE-DEC")
        history = pd.DataFrame([dict(cik="0000000001", ticker="KNOWN", source="fsds", period=end,
            accepted=end+pd.Timedelta(days=20), revenues_ttm=400.0, net_income_ttm=40.0, op_income_ttm=60.0)
            for end in periods])
        missing = pd.DataFrame([dict(cik=cik, ticker=ticker, source="companyfacts", period=pd.NaT, accepted=pd.NaT,
            financial_metadata_version="native-unit-fiscal-v1", revenues_ttm=float("nan"),
            net_income_ttm=float("nan"), op_income_ttm=float("nan"))
            for cik, ticker in (("0000000001", "KNOWN"), ("0000000002", "MISSING"))])
        combined = p.combine_fund_panels(missing, history)
        self.assertEqual(len(combined), 7)
        retained = p.prefer_dated_financial_history(combined)
        self.assertEqual(len(retained), 6)
        self.assertIn("MISSING", retained["ticker"].tolist())
        self.assertAlmostEqual(p.panel_latest_flow_coverage(combined), 0.5)
        known = combined[combined["ticker"] == "KNOWN"]
        self.assertEqual(p.panel_latest_flow_coverage(known), 1.0)
        selected = p.prefer_dated_financial_history(known).sort_values(["accepted", "period"]).iloc[-1]
        self.assertEqual(selected["period"], periods[-1])
        self.assertTrue(history["period"].notna().all())
        self.assertEqual(len(history), 5)
        unknown = pd.DataFrame([dict(cik=None, ticker="UNKNOWN_A", period=periods[-1]),
            dict(cik=None, ticker="UNKNOWN_B", period=pd.NaT)])
        self.assertEqual(len(p.prefer_dated_financial_history(unknown)), 2)


def main() -> int:
    test_exact_acceptance_amendment_and_missing_neutral()
    test_current_only_statement_uses_pinned_universe_identity_and_sec_baseline()
    test_exact_balance_identity_derives_missing_total_liabilities()
    test_missing_expected_exact_accession_fails_closed()
    test_empty_exact_accession_requires_explicit_missing_neutral_policy()
    test_declared_single_partial_core_field_is_missing_neutral()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeFinancialContextTests))
    if not result.wasSuccessful():
        return 1
    print(f"run287_b002_fundamental_delta_smoke: PASS (6 legacy + {result.testsRun} native context cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
