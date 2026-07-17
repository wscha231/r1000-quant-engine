#!/usr/bin/env python3
"""Synthetic checks for the exact fundamental-break sidecar."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_run287_exact_fundamental_breaks as breaks  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="run287-fundamental-break-") as raw:
        root = Path(raw)
        events = root / "events.parquet"
        screen = root / "screen.json"
        held = root / "held.csv"
        output = root / "out"
        pd.DataFrame(
            [
                {
                    "ticker": "AAA", "accession_number": "a1", "form": "10-Q", "fiscal_period": "2026:Q1",
                    "accepted_at": "2026-07-15T20:00:00Z", "available_from": "2026-07-15T20:00:00Z",
                    "exact_acceptance": True, "component_coverage": 4, "sec_filing_quality_event": "negative",
                },
                {
                    "ticker": "BBB", "accession_number": "b1", "form": "10-Q", "fiscal_period": "2026:Q1",
                    "accepted_at": "2026-07-16T19:00:00Z", "available_from": "2026-07-16T19:00:00Z",
                    "exact_acceptance": True, "component_coverage": 4, "sec_filing_quality_event": "positive",
                },
                {
                    "ticker": "AAA", "accession_number": "future", "form": "10-Q", "fiscal_period": "2026:Q2",
                    "accepted_at": "2026-07-18T19:00:00Z", "available_from": "2026-07-18T19:00:00Z",
                    "exact_acceptance": True, "component_coverage": 4, "sec_filing_quality_event": "positive",
                },
            ]
        ).to_parquet(events, index=False)
        pd.DataFrame(
            [
                {"as_of_date": "2026-07-16", "portfolio_kind": "main", "ticker": "AAA"},
                {"as_of_date": "2026-07-16", "portfolio_kind": "concentrated", "ticker": "BBB"},
                {"as_of_date": "2026-07-16", "portfolio_kind": "main", "ticker": "CCC"},
            ]
        ).to_csv(held, index=False)
        screen.write_text(json.dumps({"verdict": "REJECT_SOURCE_SCREEN"}), encoding="utf-8")
        args = argparse.Namespace(
            contract=str(ROOT / "docs" / "run287_exact_fundamental_break_contract_v1.json"),
            events=str(events), source_screen_summary=str(screen), held_risk_watch=str(held),
            decision_time_utc="2026-07-17T04:15:00Z", recorded_at_utc="2026-07-17T04:16:00Z",
            output_dir=str(output),
        )
        result = breaks.build(args)
        frame = pd.read_csv(output / "confirmed_breaks.csv").set_index("ticker")
        assert frame.loc["AAA", "break_status"] == "NEGATIVE_EXACT_FILING_REVIEW_ONLY"
        assert frame.loc["BBB", "break_status"] == "NO_EXACT_BREAK_EVIDENCE"
        assert frame.loc["CCC", "break_status"] == "NO_EXACT_BREAK_EVIDENCE"
        assert result["confirmed_break_count"] == 0
        assert result["future_row_count_excluded"] == 1
        assert result["portfolio_ab_allowed"] is False
        assert result["rejected_signal_reused_as_action_gate"] is False

        screen.write_text(json.dumps({"verdict": "PASS_SOURCE_SCREEN"}), encoding="utf-8")
        passed_output = root / "passed"
        args.output_dir = str(passed_output)
        passed = breaks.build(args)
        passed_frame = pd.read_csv(passed_output / "confirmed_breaks.csv").set_index("ticker")
        assert passed_frame.loc["AAA", "break_status"] == "CONFIRMED_EXACT_ACCEPTED_BREAK"
        assert passed["confirmed_break_count"] == 1
        assert passed["portfolio_ab_allowed"] is True
        assert passed["orders_generated"] is False

    print("run287_exact_fundamental_breaks_smoke: PASS")


if __name__ == "__main__":
    main()
