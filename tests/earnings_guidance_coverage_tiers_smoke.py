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

from tools.check_earnings_guidance_coverage import coverage_summary_from_frame, main  # noqa: E402


def test_five_rows_are_plumbing_not_research_ready() -> None:
    rows = [
        {
            "ticker": f"P{idx}",
            "available_from": "2026-06-15",
            "eps_estimate": 1.0,
            "eps_revision_13w": 0.05,
            "source_type": "vendor_estimate_revision",
        }
        for idx in range(5)
    ]
    payload = coverage_summary_from_frame(pd.DataFrame(rows), as_of=pd.Timestamp("2026-07-01"))
    assert payload["plumbing_ready"] is True, payload
    assert payload["research_ready"] is False, payload
    assert payload["status"] == "PLUMBING_READY", payload
    assert payload["earnings_guidance_group_status"] == "DATA_INSUFFICIENT", payload


def test_true_revision_history_can_be_research_ready() -> None:
    rows = []
    for idx in range(10):
        ticker = f"R{idx}"
        rows.append({"ticker": ticker, "available_from": "2026-05-01", "eps_estimate": 1.0, "eps_revision_13w": 0.0, "source_type": "vendor_estimate_revision"})
        rows.append({"ticker": ticker, "available_from": "2026-06-20", "eps_estimate": 1.1, "eps_revision_13w": 0.04, "source_type": "vendor_estimate_revision"})
    payload = coverage_summary_from_frame(pd.DataFrame(rows), as_of=pd.Timestamp("2026-07-01"))
    assert payload["plumbing_ready"] is True, payload
    assert payload["research_ready"] is True, payload
    assert payload["service_ready"] is False, payload
    assert payload["status"] == "RESEARCH_READY", payload
    assert payload["history_depth_ticker_count"] == 10, payload


def test_proxy_and_actual_rows_do_not_count() -> None:
    rows = []
    for idx in range(10):
        rows.append({"ticker": f"A{idx}", "available_from": "2026-06-20", "eps_revision_13w": 0.1, "source_type": "sec_actual_snapshot"})
        rows.append({"ticker": f"X{idx}", "available_from": "2026-06-20", "eps_revision_13w": 0.1, "source_type": "internal_proxy_score"})
    payload = coverage_summary_from_frame(pd.DataFrame(rows), as_of=pd.Timestamp("2026-07-01"))
    assert payload["coverage_eligible_rows"] == 0, payload
    assert payload["plumbing_ready"] is False, payload
    assert payload["actuals_context_available"] is True, payload
    assert payload["proxy_context_available"] is True, payload
    assert payload["status"] == "DATA_INSUFFICIENT", payload


def test_cli_writes_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "signals.csv"
        out = root / "out"
        rows = []
        for idx in range(10):
            rows.append({"ticker": f"R{idx}", "available_from": "2026-05-01", "eps_estimate": 1.0, "eps_revision_13w": 0.0, "source_type": "vendor_estimate_revision"})
            rows.append({"ticker": f"R{idx}", "available_from": "2026-06-20", "eps_estimate": 1.1, "eps_revision_13w": 0.04, "source_type": "vendor_estimate_revision"})
        pd.DataFrame(rows).to_csv(raw, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "check_earnings_guidance_coverage.py",
                "--raw-feed",
                str(raw),
                "--earnings-signals",
                str(root / "missing.parquet"),
                "--as-of",
                "2026-07-01",
                "--output-dir",
                str(out),
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        payload = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert payload["research_ready"] is True, payload
        assert (out / "report.md").exists()


def main_smoke() -> int:
    test_five_rows_are_plumbing_not_research_ready()
    test_true_revision_history_can_be_research_ready()
    test_proxy_and_actual_rows_do_not_count()
    test_cli_writes_summary()
    print("earnings_guidance_coverage_tiers_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
