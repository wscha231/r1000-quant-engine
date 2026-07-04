#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_earnings_revision_feed import main, validate_feed  # noqa: E402


def test_validate_good_feed_and_future_warning() -> None:
    raw = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-06-01",
                "available_from": "2026-06-02",
                "eps_estimate": 1.25,
                "revenue_estimate": 120.0,
                "guidance_direction": "positive",
                "source": "vendor_export",
                "source_type": "vendor_estimate_revision",
            },
            {
                "ticker": "BBB",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-12-01",
                "available_from": "2026-12-02",
                "eps_estimate": 9.99,
                "guidance_direction": "negative",
                "source": "vendor_export",
                "source_type": "vendor_estimate_revision",
            },
        ]
    )
    payload = validate_feed(raw, as_of=pd.Timestamp("2026-07-01"))
    assert payload["status"] == "warning", payload
    assert payload["future_available_from_rows"] == 1, payload
    assert "future_available_from_rows_will_be_filtered_by_builder" in payload["reason"], payload
    assert payload["production_activation_allowed"] is False
    assert payload["forward_return_columns_allowed"] is False
    assert payload["regime_nowcast_coverage_ready"] is False


def test_validate_blocks_missing_available_from() -> None:
    payload = validate_feed(pd.DataFrame([{"ticker": "AAA", "eps_estimate": 1.0}]), as_of=pd.Timestamp("2026-07-01"))
    assert payload["status"] == "blocked", payload
    assert payload["reason"] == "missing_required_columns", payload


def test_validate_flags_regime_ready_with_enough_history() -> None:
    rows = []
    for idx in range(10):
        ticker = f"T{idx}"
        rows.append(
            {
                "ticker": ticker,
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-06-01",
                "available_from": "2026-06-02",
                "eps_estimate": 1.0,
                "source": "vendor_export",
                "source_type": "historical_revision",
            }
        )
        rows.append(
            {
                "ticker": ticker,
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-06-20",
                "available_from": "2026-06-21",
                "eps_estimate": 1.2,
                "source": "vendor_export",
                "source_type": "historical_revision",
            }
        )
    payload = validate_feed(pd.DataFrame(rows), as_of=pd.Timestamp("2026-07-01"))
    assert payload["status"] in {"completed", "warning"}, payload
    assert payload["history_depth_ticker_count"] == 10, payload
    assert payload["coverage_eligible_history_depth_ticker_count"] == 10, payload
    assert payload["earnings_guidance_plumbing_ready"] is True, payload
    assert payload["earnings_guidance_research_ready"] is True, payload
    assert payload["regime_nowcast_coverage_ready"] is True, payload


def test_actual_snapshot_does_not_count_for_regime_coverage() -> None:
    rows = []
    for idx in range(5):
        ticker = f"A{idx}"
        rows.append(
            {
                "ticker": ticker,
                "fiscal_period": "2026Q1",
                "estimate_date": "2026-04-01",
                "available_from": "2026-04-02",
                "eps_estimate": 1.0,
                "guidance_direction": "positive",
                "source": "sec_companyfacts",
                "source_type": "sec_actual_snapshot",
            }
        )
        rows.append(
            {
                "ticker": ticker,
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-07-01",
                "available_from": "2026-07-02",
                "eps_estimate": 1.2,
                "guidance_direction": "positive",
                "source": "sec_companyfacts",
                "source_type": "sec_actual_snapshot",
            }
        )
    payload = validate_feed(pd.DataFrame(rows), as_of=pd.Timestamp("2026-07-03"))
    assert payload["history_depth_ticker_count"] == 5, payload
    assert payload["coverage_eligible_history_depth_ticker_count"] == 0, payload
    assert payload["coverage_eligible_directional_guidance_row_count"] == 0, payload
    assert payload["actual_only_source_rows"] == 10, payload
    assert payload["regime_nowcast_coverage_ready"] is False, payload
    assert "actual_only_sources_do_not_count_for_regime_nowcast" in payload["reason"], payload


def test_cli_writes_missing_input_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        summary = root / "summary.json"
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "validate_earnings_revision_feed.py",
                "--input",
                str(root / "missing.csv"),
                "--summary",
                str(summary),
                "--as-of",
                "2026-07-01",
            ]
            assert main() == 2
        finally:
            sys.argv = old_argv
        payload = json.loads(summary.read_text(encoding="utf-8"))
        assert payload["status"] == "blocked", payload
        assert payload["reason"] == "missing_input", payload
        assert payload["available_from_required"] is True


def main_smoke() -> int:
    test_validate_good_feed_and_future_warning()
    test_validate_blocks_missing_available_from()
    test_validate_flags_regime_ready_with_enough_history()
    test_actual_snapshot_does_not_count_for_regime_coverage()
    test_cli_writes_missing_input_summary()
    print("earnings_revision_feed_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
