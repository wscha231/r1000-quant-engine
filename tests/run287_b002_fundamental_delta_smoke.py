#!/usr/bin/env python3
"""Smoke tests for the B002 exact-accepted fundamental delta."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_b002_fundamental_delta import build  # noqa: E402


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
        assert overrides.loc[0, "mktcap"] == 5000.0


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


def main() -> int:
    test_exact_acceptance_amendment_and_missing_neutral()
    test_current_only_statement_uses_pinned_universe_identity_and_sec_baseline()
    test_exact_balance_identity_derives_missing_total_liabilities()
    test_missing_expected_exact_accession_fails_closed()
    test_empty_exact_accession_requires_explicit_missing_neutral_policy()
    test_declared_single_partial_core_field_is_missing_neutral()
    print("run287_b002_fundamental_delta_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
