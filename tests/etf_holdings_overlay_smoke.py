from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_features import load_etf_holdings_overlay  # noqa: E402
from tools.run_etf_holdings_refresh import (  # noqa: E402
    build_signals,
    normalize_holding_rows,
    parse_args,
    previous_holdings,
    run,
)


def _spec() -> dict[str, str]:
    return {"etf_ticker": "ETF1", "etf_label": "ETF One", "theme": "fixture"}


def test_etf_holdings_refresh_builds_shadow_signals() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixture = root / "holdings.csv"
        pd.DataFrame(
            [
                {"etf_ticker": "SMH", "holding_ticker": "NVDA", "holding_weight": 0.20, "theme": "semiconductors"},
                {"etf_ticker": "SOXX", "holding_ticker": "NVDA", "holding_weight": 0.12, "theme": "semiconductors"},
                {"etf_ticker": "BOTZ", "holding_ticker": "NVDA", "holding_weight": 0.08, "theme": "robotics_ai"},
                {"etf_ticker": "SMH", "holding_ticker": "AMD", "holding_weight": 0.06, "theme": "semiconductors"},
            ]
        ).to_csv(fixture, index=False)

        args = parse_args()
        args.input_holdings = str(fixture)
        args.pit_dir = str(root / "data_pit" / "etf_holdings")
        args.output_dir = str(root / "outputs" / "etf_thematic_signals")
        args.as_of = "2026-05-20T00:00:00Z"
        args.max_holdings = 25
        payload = run(args)
        assert payload["signal_tickers"] >= 2
        assert payload["full_coverage_etfs"] == 0

        overlay = load_etf_holdings_overlay(base_dir=root / "outputs")
        nvda = overlay[overlay["ticker"].eq("NVDA")].iloc[0]
        assert int(nvda["etf_consensus_count"]) == 3
        assert float(nvda["etf_holdings_score"]) > 0.0


def test_etf_weight_units_are_explicit() -> None:
    percent = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "weight": "0.5%"}, {"ticker": "B", "weight": "1"}]),
        _spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="PERCENT",
        coverage_kind="FULL",
    )
    assert list(percent["holding_weight"].round(6)) == [0.005, 0.01]

    fraction = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "holding_weight": 0.5}]),
        _spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="FRACTION",
        coverage_kind="FULL",
    )
    assert float(fraction.iloc[0]["holding_weight"]) == 0.5


def test_etf_invalid_or_conflicting_weights_do_not_become_zero() -> None:
    conflict = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "weight": "0.5%"}]),
        _spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="FRACTION",
        coverage_kind="FULL",
    )
    assert conflict.empty

    invalid = normalize_holding_rows(
        pd.DataFrame([{"ticker": "A", "weight": "N/A"}]),
        _spec(),
        as_of="2026-09-15T00:00:00Z",
        source="fixture",
        max_holdings=25,
        weight_unit="PERCENT",
        coverage_kind="FULL",
    )
    assert invalid.empty


def test_previous_holdings_uses_latest_snapshot_per_fund() -> None:
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


def test_top_only_does_not_create_recent_add_signal() -> None:
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


def test_full_to_full_can_create_recent_add_signal() -> None:
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


def test_refresh_preserves_existing_pit_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pit_dir = root / "data_pit" / "etf_holdings"
        pit_dir.mkdir(parents=True, exist_ok=True)
        pit_file = pit_dir / "etf_holdings.parquet"
        pd.DataFrame(
            [
                {
                    "etf_ticker": "ETF1",
                    "etf_label": "ETF One",
                    "theme": "fixture",
                    "holding_ticker": "OLD",
                    "holding_name": "Old Holding",
                    "holding_weight": 0.20,
                    "coverage_kind": "NPORT",
                    "source": "historical",
                    "as_of_date": "2026-08-01T00:00:00Z",
                    "available_from": "2026-08-01T00:00:00Z",
                }
            ]
        ).to_parquet(pit_file, index=False)

        fixture = root / "current.csv"
        pd.DataFrame(
            [
                {
                    "etf_ticker": "ETF1",
                    "holding_ticker": "NEW",
                    "holding_weight": 0.30,
                    "theme": "fixture",
                }
            ]
        ).to_csv(fixture, index=False)

        args = parse_args()
        args.input_holdings = str(fixture)
        args.pit_dir = str(pit_dir)
        args.output_dir = str(root / "outputs" / "etf_thematic_signals")
        args.as_of = "2026-09-15T00:00:00Z"
        args.max_holdings = 25
        payload = run(args)

        saved = pd.read_parquet(pit_file)
        assert set(saved["holding_ticker"]) == {"OLD", "NEW"}
        assert set(saved["available_from"]) == {"2026-08-01T00:00:00Z", "2026-09-15T00:00:00Z"}
        assert payload["historical_rows_retained"] == 1
        assert payload["pit_rows_after_refresh"] == 2


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"etf_holdings_overlay_smoke: PASS ({len(tests)})")


if __name__ == "__main__":
    main()
