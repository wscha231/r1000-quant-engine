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

from tools.check_earnings_guidance_coverage import coverage_summary_from_frame  # noqa: E402
from tools.materialize_sec_actuals_snapshot import main  # noqa: E402


def test_sec_actuals_materialize_but_never_count_as_guidance_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "sec_actuals.csv"
        out = root / "sec_actuals.parquet"
        summary = root / "summary.json"
        rows = [
            {
                "ticker": f"A{idx}",
                "cik": f"{idx:010d}",
                "form_type": "10-Q",
                "filing_date": "2026-06-10",
                "accepted_ts": "2026-06-10T16:30:00Z",
                "period_end": "2026-05-31",
                "fact_name": "Revenues",
                "metric": "revenue",
                "reported_value": 100.0 + idx,
                "unit": "USD",
                "fiscal_period": "2026Q2",
                "available_from": "2026-06-11",
                "source_file": "companyfacts.zip",
                "source_hash": "abc123",
            }
            for idx in range(12)
        ]
        pd.DataFrame(rows).to_csv(raw, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "materialize_sec_actuals_snapshot.py",
                "--input",
                str(raw),
                "--output",
                str(out),
                "--summary",
                str(summary),
                "--as-of",
                "2026-07-01",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        payload = json.loads(summary.read_text(encoding="utf-8"))
        assert payload["status"] == "completed", payload
        assert payload["source_type"] == "sec_actual_snapshot", payload
        assert payload["is_coverage_eligible"] is False, payload
        actuals = pd.read_parquet(out)
        assert actuals["is_actual"].all()
        assert not actuals["is_coverage_eligible"].any()
        coverage = coverage_summary_from_frame(actuals, as_of=pd.Timestamp("2026-07-01"))
        assert coverage["coverage_eligible_rows"] == 0, coverage
        assert coverage["research_ready"] is False, coverage
        assert coverage["actuals_context_available"] is True, coverage
        assert coverage["earnings_guidance_group_status"] == "DATA_INSUFFICIENT", coverage


def main_smoke() -> int:
    test_sec_actuals_materialize_but_never_count_as_guidance_coverage()
    print("sec_actuals_not_coverage_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_smoke())
