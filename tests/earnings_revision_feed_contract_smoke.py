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
            },
            {
                "ticker": "BBB",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-12-01",
                "available_from": "2026-12-02",
                "eps_estimate": 9.99,
                "guidance_direction": "negative",
                "source": "vendor_export",
            },
        ]
    )
    payload = validate_feed(raw, as_of=pd.Timestamp("2026-07-01"))
    assert payload["status"] == "warning", payload
    assert payload["future_available_from_rows"] == 1, payload
    assert "future_available_from_rows_will_be_filtered_by_builder" in payload["reason"], payload
    assert payload["production_activation_allowed"] is False
    assert payload["forward_return_columns_allowed"] is False


def test_validate_blocks_missing_available_from() -> None:
    payload = validate_feed(pd.DataFrame([{"ticker": "AAA", "eps_estimate": 1.0}]), as_of=pd.Timestamp("2026-07-01"))
    assert payload["status"] == "blocked", payload
    assert payload["reason"] == "missing_required_columns", payload


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
    test_cli_writes_missing_input_summary()
    print("earnings_revision_feed_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
