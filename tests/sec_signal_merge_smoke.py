#!/usr/bin/env python3
"""Smoke checks for point-in-time SEC signal joins."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.sec_signal_merge import merge_sec_ownership_signals  # noqa: E402


def test_sec_signal_merge_is_point_in_time() -> None:
    candidates = pd.DataFrame(
        [
            {"rebalance_date": "2026-01-31", "ticker": "AAA", "score": 1.0},
            {"rebalance_date": "2026-03-31", "ticker": "AAA", "score": 1.0},
            {"rebalance_date": "2026-03-31", "ticker": "BBB", "score": 1.0},
        ]
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "as_of_date": "2026-02-15",
                "sec_form4_cluster_buy_score": 0.90,
                "early_evidence_score": 0.80,
                "evidence_confidence_score": 0.70,
            },
            {
                "ticker": "BBB",
                "as_of_date": "2026-04-15",
                "sec_form4_cluster_buy_score": 1.00,
                "early_evidence_score": 1.00,
                "evidence_confidence_score": 1.00,
            },
        ]
    )
    merged = merge_sec_ownership_signals(candidates, signals)
    jan_aaa = merged[(merged["ticker"].eq("AAA")) & (merged["rebalance_date"].eq("2026-01-31"))].iloc[0]
    mar_aaa = merged[(merged["ticker"].eq("AAA")) & (merged["rebalance_date"].eq("2026-03-31"))].iloc[0]
    mar_bbb = merged[(merged["ticker"].eq("BBB")) & (merged["rebalance_date"].eq("2026-03-31"))].iloc[0]
    assert float(jan_aaa["early_evidence_score"]) == 0.0
    assert bool(jan_aaa["sec_signal_available"]) is False
    assert float(mar_aaa["early_evidence_score"]) == 0.80
    assert str(mar_aaa["sec_signal_as_of_date"]) == "2026-02-15"
    assert float(mar_bbb["early_evidence_score"]) == 0.0
    assert bool(mar_bbb["sec_signal_available"]) is False


def main() -> int:
    test_sec_signal_merge_is_point_in_time()
    print("sec_signal_merge_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
