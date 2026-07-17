#!/usr/bin/env python3
"""Synthetic exact-acceptance debt/cash snapshot checks."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_exact_debt_snapshot as debt  # noqa: E402


def fact(tag: str, old_value: float, future_value: float) -> dict[str, object]:
    return {
        "label": tag,
        "units": {
            "USD": [
                {
                    "end": "2026-03-31",
                    "val": old_value,
                    "accn": "0000000001-26-000001",
                    "form": "10-Q",
                    "filed": "2026-04-30",
                },
                {
                    "end": "2026-06-30",
                    "val": future_value,
                    "accn": "0000000001-26-000002",
                    "form": "10-Q",
                    "filed": "2026-07-30",
                },
            ]
        },
    }


def payload() -> dict[str, object]:
    return {
        "cik": 1,
        "entityName": "Test",
        "facts": {
            "us-gaap": {
                "Assets": fact("Assets", 100.0, 200.0),
                "CashAndCashEquivalentsAtCarryingValue": fact("Cash", 20.0, 5.0),
                "LongTermDebtNoncurrent": fact("Long debt", 10.0, 100.0),
                "ShortTermBorrowings": fact("Current debt", 5.0, 50.0),
            }
        },
    }


def sec_index() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik10": "0000000001",
                "accession_number": "0000000001-26-000001",
                "form_type": "10-Q",
                "accepted_at": "2026-04-30T20:00:00Z",
                "available_from": "2026-04-30T20:00:00Z",
                "period_of_report": "2026-03-31",
            },
            {
                "cik10": "0000000001",
                "accession_number": "0000000001-26-000002",
                "form_type": "10-Q",
                "accepted_at": "2026-07-30T20:00:00Z",
                "available_from": "2026-07-30T20:00:00Z",
                "period_of_report": "2026-06-30",
            },
        ]
    )


def test_latest_available_accession_and_debt_arithmetic() -> None:
    index = debt.prepare_index(sec_index(), pd.Timestamp("2026-07-14T05:00:00Z"))
    statement = debt.latest_companyfacts_statement(payload(), index)
    assert statement is not None
    assert statement["accession_number"] == "0000000001-26-000001"
    row = debt.build_row("AAA", "0000000001", payload(), index)
    assert row["exact_acceptance"] is True
    assert row["available_from"] == "2026-04-30T20:00:00+00:00"
    assert row["total_debt_exact"] == 15.0
    assert row["net_debt_exact"] == -5.0
    assert np.isclose(row["exact_debt_to_assets"], 0.15)
    assert np.isclose(row["exact_net_debt_to_assets"], -0.05)
    assert row["exact_debt_component_coverage"] == 1.0
    assert row["debt_scope_status"] == "NONCURRENT_PLUS_CURRENT_COMPLETE"
    assert row["filed_fallback_used"] is False


def test_end_to_end_missing_member_is_neutral_not_zero() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-debt-") as raw:
        root = Path(raw)
        context_path = root / "context.parquet"
        index_path = root / "index.parquet"
        zip_path = root / "companyfacts.zip"
        output = root / "out"
        pd.DataFrame(
            [
                {"ticker": "AAA", "cik10": "0000000001"},
                {"ticker": "BBB", "cik10": "0000000002"},
            ]
        ).to_parquet(context_path, index=False)
        sec_index().to_parquet(index_path, index=False)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("companyfacts/CIK0000000001.json", json.dumps(payload()))
        result = debt.build(
            argparse.Namespace(
                selection_context=str(context_path),
                companyfacts_zip=str(zip_path),
                sec_index=str(index_path),
                decision_time_utc="2026-07-14T05:00:00Z",
                output_dir=str(output),
                prior_snapshot="",
            )
        )
        assert result["universe_count"] == 2
        assert result["exact_debt_complete_count"] == 1
        assert result["companyfacts_member_missing_count"] == 1
        assert result["future_row_count"] == 0
        snapshot = pd.read_csv(output / "exact_debt_snapshot.csv")
        missing = snapshot.set_index("ticker").loc["BBB"]
        assert pd.isna(missing["total_debt_exact"])
        assert missing["debt_scope_status"] == "NO_COMPANYFACTS_STATEMENT"
        manifest = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert manifest["missing_debt_is_zero"] is False
        assert not manifest["backtest_executed"]
        assert not manifest["orders_generated"]

        second_output = root / "out-second"
        second = debt.build(
            argparse.Namespace(
                selection_context=str(context_path),
                companyfacts_zip=str(zip_path),
                sec_index=str(index_path),
                decision_time_utc="2026-07-14T05:00:00Z",
                output_dir=str(second_output),
                prior_snapshot=str(output / "exact_debt_snapshot.csv"),
            )
        )
        assert second["prior_snapshot_reused_count"] == 1
        assert second["refreshed_ticker_count"] == 1
        second_snapshot = pd.read_csv(second_output / "exact_debt_snapshot.csv")
        assert second_snapshot.set_index("ticker").loc["AAA", "snapshot_refresh_status"] == (
            "REUSED_NO_NEW_ACCEPTED_STATEMENT"
        )


if __name__ == "__main__":
    test_latest_available_accession_and_debt_arithmetic()
    test_end_to_end_missing_member_is_neutral_not_zero()
    print("run287_exact_debt_snapshot_smoke: PASS")
