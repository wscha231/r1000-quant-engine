#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_earnings_call_keyword_signals import build_signals, main  # noqa: E402


def _raw() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "MEM",
                "available_from": "2026-05-01",
                "text": "HBM memory tight supply, price increase, backlog and sold out capacity.",
            },
            {
                "ticker": "COST",
                "available_from": "2026-05-01",
                "text": "Oil, fuel and freight cost pressure drove guidance risk and customer delay.",
            },
            {
                "ticker": "FUTURE",
                "available_from": "2026-12-31",
                "text": "future text must be filtered",
            },
        ]
    )


def test_keyword_signals_count_families_and_filter_future() -> None:
    out, summary = build_signals(_raw(), as_of=pd.Timestamp("2026-06-01"))
    assert summary["future_available_from_rows_filtered"] == 1
    mem = out[out["ticker"].eq("MEM")].iloc[0]
    cost = out[out["ticker"].eq("COST")].iloc[0]
    assert mem["bottleneck_pricing_power_keyword_score"] > 0
    assert mem["ai_capex_demand_keyword_score"] > 0
    assert cost["downstream_cost_pressure_keyword_score"] > 0
    assert cost["guidance_risk_keyword_score"] > 0


def test_cli_writes_keyword_parquet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        raw = root / "keywords.csv"
        out = root / "keywords.parquet"
        summary = root / "summary.json"
        _raw().to_csv(raw, index=False)
        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "build_earnings_call_keyword_signals.py",
                "--input",
                str(raw),
                "--output",
                str(out),
                "--summary",
                str(summary),
                "--as-of",
                "2026-06-01",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        assert out.exists()
        assert summary.exists()


if __name__ == "__main__":
    test_keyword_signals_count_families_and_filter_future()
    test_cli_writes_keyword_parquet()
    print("earnings_call_keyword_signals_smoke: PASS")
