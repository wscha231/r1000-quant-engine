from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_etf_holdings_refresh import (  # noqa: E402
    build_signals,
    normalize_holding_rows,
    previous_holdings,
)


def spec() -> dict[str, str]:
    return {"etf_ticker": "ETF1", "etf_label": "ETF One", "theme": "fixture"}


def test_percent_and_fraction_are_explicit() -> None:
    percent = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "weight": "0.5%"}, {"ticker": "B", "weight": "1"}]),
        spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="PERCENT",
        coverage_kind="FULL",
    )
    assert list(percent["holding_weight"].round(6)) == [0.005, 0.01]

    fraction = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "holding_weight": 0.5}]),
        spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="FRACTION",
        coverage_kind="FULL",
    )
    assert float(fraction.iloc[0]["holding_weight"]) == 0.5


def test_fraction_percent_conflict_and_invalid_values_fail_closed() -> None:
    conflict = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "weight": "0.5%"}]),
        spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="FRACTION",
        coverage_kind="FULL",
    )
    assert conflict.empty

    invalid = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "weight": "N/A"}]),
        spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="PERCENT",
        coverage_kind="FULL",
    )
    assert invalid.empty


def test_previous_holdings_selects_latest_per_fund() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "holdings.csv"
        pd.DataFrame(
            [
                {"etf_ticker": "ETF1", "holding_ticker": "A", "available_from": "2026-09-10T00:00:00Z"},
                {"etf_ticker": "ETF1", "holding_ticker": "B", "available_from": "2026-09-12T00:00:00Z"},
                {"etf_ticker": "ETF2", "holding_ticker": "C", "available_from": "2026-09-11T00:00:00Z"},
            ]
        ).to_csv(path, index=False)
        latest = previous_holdings(path)
        pairs = set(zip(latest["etf_ticker"], latest["holding_ticker"]))
        assert pairs == {("ETF1", "B"), ("ETF2", "C")}


def test_top_only_snapshot_does_not_create_recent_add_signal() -> None:
    previous = pd.DataFrame(
        [
            {
                "etf_ticker": "ETF1",
                "holding_ticker": "A",
                "holding_weight": 0.50,
                "coverage_kind": "TOP_ONLY",
                "available_from": "2026-09-14T00:00:00Z",
                "theme": "fixture",
            }
        ]
    )
    current = pd.DataFrame(
        [
            {
                "etf_ticker": "ETF1",
                "holding_ticker": "A",
                "holding_weight": 0.45,
                "coverage_kind": "TOP_ONLY",
                "available_from": "2026-09-15T00:00:00Z",
                "theme": "fixture",
            },
            {
                "etf_ticker": "ETF1",
                "holding_ticker": "B",
                "holding_weight": 0.10,
                "coverage_kind": "TOP_ONLY",
                "available_from": "2026-09-15T00:00:00Z",
                "theme": "fixture",
            },
        ]
    )
    signals = build_signals(current, previous).set_index("ticker")
    assert float(signals.loc["B", "etf_recent_add_score"]) == 0.0


def test_full_to_full_snapshot_can_create_recent_add_signal() -> None:
    previous = pd.DataFrame(
        [
            {
                "etf_ticker": "ETF1",
                "holding_ticker": "A",
                "holding_weight": 0.90,
                "coverage_kind": "FULL",
                "available_from": "2026-09-14T00:00:00Z",
                "theme": "fixture",
            }
        ]
    )
    current = pd.DataFrame(
        [
            {
                "etf_ticker": "ETF1",
                "holding_ticker": "A",
                "holding_weight": 0.80,
                "coverage_kind": "FULL",
                "available_from": "2026-09-15T00:00:00Z",
                "theme": "fixture",
            },
            {
                "etf_ticker": "ETF1",
                "holding_ticker": "B",
                "holding_weight": 0.20,
                "coverage_kind": "FULL",
                "available_from": "2026-09-15T00:00:00Z",
                "theme": "fixture",
            },
        ]
    )
    signals = build_signals(current, previous).set_index("ticker")
    assert float(signals.loc["B", "etf_recent_add_score"]) == 1.0


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"etf_holdings_integrity_smoke: PASS ({len(tests)})")


if __name__ == "__main__":
    main()
