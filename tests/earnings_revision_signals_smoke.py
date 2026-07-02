#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_earnings_revision_signals import build_signals, main  # noqa: E402


def _raw() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "sector": "Information Technology",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-01-01",
                "available_from": "2026-01-02",
                "eps_estimate": 1.00,
                "revenue_estimate": 100.0,
                "margin_estimate": 0.20,
                "guidance_direction": "neutral",
            },
            {
                "ticker": "AAA",
                "sector": "Information Technology",
                "fiscal_period": "2026Q2",
                "estimate_date": "2026-04-15",
                "available_from": "2026-04-16",
                "eps_estimate": 1.25,
                "revenue_estimate": 120.0,
                "margin_estimate": 0.23,
                "guidance_direction": "positive",
            },
            {
                "ticker": "LATE",
                "sector": "Information Technology",
                "available_from": "2026-12-31",
                "eps_estimate": 9.99,
                "guidance_direction": "positive",
            },
        ]
    )


def test_revision_signals_require_available_from_and_filter_future() -> None:
    out, summary = build_signals(_raw(), as_of=pd.Timestamp("2026-06-30"))
    assert summary["future_available_from_rows_filtered"] == 1
    latest = out[out["ticker"].eq("AAA")].sort_values("available_from").iloc[-1]
    assert latest["eps_revision_13w"] > 0
    assert latest["positive_guidance_flag"] == 1
    assert latest["sector_eps_revision_breadth"] >= 0


def test_cli_writes_parquet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "earnings_revisions.csv"
        out = root / "signals.parquet"
        summary = root / "summary.json"
        _raw().to_csv(raw, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "build_earnings_revision_signals.py",
                "--input",
                str(raw),
                "--output",
                str(out),
                "--summary",
                str(summary),
                "--as-of",
                "2026-06-30",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        assert out.exists()
        assert summary.exists()


if __name__ == "__main__":
    test_revision_signals_require_available_from_and_filter_future()
    test_cli_writes_parquet()
    print("earnings_revision_signals_smoke: PASS")
