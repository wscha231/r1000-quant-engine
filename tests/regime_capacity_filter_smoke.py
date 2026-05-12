#!/usr/bin/env python3
"""Smoke tests for the regime-conditioned capacity filter (Iter 3)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_regime_capacity_filter import (  # noqa: E402
    DEFAULT_REGIME_MULTIPLIERS,
    apply_filter,
    build_regime_map_from_book,
    dominant_regime,
    parse_multipliers_arg,
    regime_map_lookup,
    run,
)


def _book(rows: list[tuple[str, str, float, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"rebalance_date": d, "ticker": t, "weight": w, "regime_state": r} for d, t, w, r in rows]
    )


def test_bear_regime_halves_weights() -> None:
    book = _book([
        ("2022-04-30", "AAA", 0.50, "bear"),
        ("2022-04-30", "BBB", 0.30, "bear"),
        ("2022-04-30", "CASH", 0.20, "bear"),
        ("2023-04-30", "AAA", 0.50, "bull"),
    ])
    out, decisions = apply_filter(book)
    out = out.set_index(["rebalance_date", "ticker"])
    # bear date: AAA halved, BBB halved, CASH untouched
    assert float(out.loc[(pd.Timestamp("2022-04-30"), "AAA"), "weight"]) == 0.25
    assert float(out.loc[(pd.Timestamp("2022-04-30"), "BBB"), "weight"]) == 0.15
    assert float(out.loc[(pd.Timestamp("2022-04-30"), "CASH"), "weight"]) == 0.20
    # bull date: untouched
    assert float(out.loc[(pd.Timestamp("2023-04-30"), "AAA"), "weight"]) == 0.50
    bear_decision = [d for d in decisions if d["regime"] == "bear"][0]
    assert bear_decision["multiplier"] == 0.5
    assert bear_decision["rows_affected"] == 2


def test_deep_bear_quarters_weights() -> None:
    book = _book([
        ("2020-03-31", "AAA", 0.60, "deep_bear"),
        ("2020-03-31", "BBB", 0.40, "deep_bear"),
    ])
    out, _ = apply_filter(book)
    out = out.set_index(["rebalance_date", "ticker"])
    assert float(out.loc[(pd.Timestamp("2020-03-31"), "AAA"), "weight"]) == 0.15
    assert float(out.loc[(pd.Timestamp("2020-03-31"), "BBB"), "weight"]) == 0.10


def test_neutral_and_bull_pass_through() -> None:
    # Per Iter 1 lesson, neutral is NOT touched by default.
    book = _book([
        ("2024-01-31", "AAA", 0.50, "neutral"),
        ("2024-02-29", "AAA", 0.50, "bull"),
        ("2024-03-31", "AAA", 0.50, "strong_bull"),
    ])
    out, _ = apply_filter(book)
    assert (out["weight"] == 0.50).all()


def test_dominant_regime_uses_mode_when_mixed() -> None:
    # If a single date has mixed regime labels (data noise), mode wins.
    s = pd.Series(["bear", "bear", "neutral"])
    assert dominant_regime(s) == "bear"
    assert dominant_regime(pd.Series([])) == "unknown"


def test_custom_multipliers_override_defaults() -> None:
    book = _book([
        ("2022-04-30", "AAA", 0.40, "neutral"),
    ])
    mult = {**DEFAULT_REGIME_MULTIPLIERS, "neutral": 0.8}
    out, _ = apply_filter(book, multipliers=mult)
    out = out.set_index(["rebalance_date", "ticker"])
    assert abs(float(out.loc[(pd.Timestamp("2022-04-30"), "AAA"), "weight"]) - 0.32) < 1e-9


def test_parse_multipliers_arg() -> None:
    mult = parse_multipliers_arg("bear=0.3,deep_bear=0.10")
    assert mult["bear"] == 0.3
    assert mult["deep_bear"] == 0.10
    # Unspecified regimes keep defaults.
    assert mult["bull"] == 1.0


def test_missing_regime_column_yields_no_op_pass_through() -> None:
    book = pd.DataFrame([
        {"rebalance_date": "2022-04-30", "ticker": "AAA", "weight": 0.50},
    ])
    out, decisions = apply_filter(book)
    assert float(out.iloc[0]["weight"]) == 0.50
    assert decisions[0]["regime"] == "no_regime_column"


def test_run_writes_csv_and_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        input_path = root / "in.csv"
        _book([
            ("2020-02-29", "AAA", 0.50, "bear"),
            ("2020-03-31", "AAA", 0.50, "deep_bear"),
            ("2020-04-30", "AAA", 0.50, "bear"),
            ("2020-05-29", "AAA", 0.50, "neutral"),
        ]).to_csv(input_path, index=False)
        out_path = root / "out.csv"
        diag_path = root / "diag.json"
        payload = run(input_book=input_path, output_book=out_path, diagnostics_path=diag_path)
        assert payload["status"] == "completed"
        assert payload["schema_version"] == "regime-capacity-filter-v1"
        assert payload["rebalance_dates_dampened"] == 3
        assert payload["rebalance_dates_total"] == 4
        assert out_path.exists()
        assert diag_path.exists()


def test_external_regime_map_overrides_missing_column() -> None:
    """Iter 4 unblock: concentrated book has regime_state mostly null.
    With an external regime_map supplied (typically derived from main
    book), the filter must still dampen on bear/deep_bear dates."""
    # Concentrated-style book: no regime_state column at all.
    book = pd.DataFrame([
        {"rebalance_date": "2020-02-29", "ticker": "AAA", "weight": 0.50},
        {"rebalance_date": "2020-03-31", "ticker": "AAA", "weight": 0.50},
        {"rebalance_date": "2020-04-30", "ticker": "AAA", "weight": 0.50},
        {"rebalance_date": "2020-05-29", "ticker": "AAA", "weight": 0.50},
    ])
    external_map = {
        pd.Timestamp("2020-02-29"): "bear",
        pd.Timestamp("2020-03-31"): "deep_bear",
        pd.Timestamp("2020-04-30"): "bear",
        pd.Timestamp("2020-05-29"): "neutral",
    }
    out, decisions = apply_filter(book, regime_map=external_map)
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    weights = out.set_index("rebalance_date")["weight"]
    assert float(weights[pd.Timestamp("2020-02-29")]) == 0.25
    assert float(weights[pd.Timestamp("2020-03-31")]) == 0.125
    assert float(weights[pd.Timestamp("2020-04-30")]) == 0.25
    assert float(weights[pd.Timestamp("2020-05-29")]) == 0.50


def test_build_regime_map_from_book_takes_dominant_per_date() -> None:
    src = pd.DataFrame([
        {"rebalance_date": "2020-03-31", "ticker": "AAA", "regime_state": "deep_bear"},
        {"rebalance_date": "2020-03-31", "ticker": "BBB", "regime_state": "deep_bear"},
        {"rebalance_date": "2020-04-30", "ticker": "AAA", "regime_state": "bear"},
        {"rebalance_date": "2020-05-29", "ticker": "AAA", "regime_state": "neutral"},
        {"rebalance_date": "2020-05-29", "ticker": "BBB", "regime_state": "bull"},
    ])
    regime_map = build_regime_map_from_book(src)
    assert regime_map[pd.Timestamp("2020-03-31")] == "deep_bear"
    assert regime_map[pd.Timestamp("2020-04-30")] == "bear"
    # 2020-05-29 has neutral and bull tied; mode returns smallest alphabetically
    # (pandas behavior). We just assert it's one of the input labels.
    assert regime_map[pd.Timestamp("2020-05-29")] in {"neutral", "bull"}


def test_regime_map_lookup_carries_forward_to_undefined_dates() -> None:
    rm = {
        pd.Timestamp("2020-02-29"): "bear",
        pd.Timestamp("2020-05-29"): "bull",
    }
    # Date BEFORE any entry: returns unknown.
    assert regime_map_lookup(rm, pd.Timestamp("2020-01-31")) == "unknown"
    # Date matching an entry exactly: returns that entry.
    assert regime_map_lookup(rm, pd.Timestamp("2020-02-29")) == "bear"
    # Date between entries: returns most recent prior.
    assert regime_map_lookup(rm, pd.Timestamp("2020-03-15")) == "bear"
    # Date after last entry: returns last entry.
    assert regime_map_lookup(rm, pd.Timestamp("2020-12-31")) == "bull"


def main() -> int:
    test_bear_regime_halves_weights()
    test_deep_bear_quarters_weights()
    test_neutral_and_bull_pass_through()
    test_dominant_regime_uses_mode_when_mixed()
    test_custom_multipliers_override_defaults()
    test_parse_multipliers_arg()
    test_missing_regime_column_yields_no_op_pass_through()
    test_run_writes_csv_and_diagnostics()
    test_external_regime_map_overrides_missing_column()
    test_build_regime_map_from_book_takes_dominant_per_date()
    test_regime_map_lookup_carries_forward_to_undefined_dates()
    print("regime_capacity_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
