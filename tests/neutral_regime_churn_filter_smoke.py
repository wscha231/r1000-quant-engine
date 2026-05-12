#!/usr/bin/env python3
"""Smoke tests for the neutral-regime churn filter.

Verifies:
  * a ticker that bounces in/out 3 times within the window gets blocked
    on its next re-entry attempt during a neutral regime month
  * a ticker entered ONCE and held continuously (NVDA-style winner) is
    never blocked regardless of how long it sits in the book
  * non-neutral regimes (bull/bear/strong_bull/deep_bear) pass through
    completely untouched
  * the filter never forcibly holds an exit — declining names that the
    upstream book chose to drop continue to drop
  * blocked-entry weights fall to cash (output sum < 1.0) rather than
    being redistributed
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_neutral_regime_churn_filter import (  # noqa: E402
    apply_churn_filter,
    compute_swap_counts,
    run,
)


def _book(rows: list[tuple[str, str, float, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"rebalance_date": d, "ticker": t, "weight": w, "regime_state": r} for d, t, w, r in rows]
    ).assign(rebalance_date=lambda df: pd.to_datetime(df["rebalance_date"]))


def test_high_churn_ticker_blocked_on_neutral_reentry() -> None:
    # CHURNY bounces in/out under neutral regime. STABLE is genuinely
    # held continuously across all months. On month 7 CHURNY tries to
    # re-enter alongside STABLE; CHURNY must be blocked while STABLE
    # passes through as an existing holding.
    rows = [
        # Both held on month 1 (initial seed).
        ("2024-01-31", "CHURNY", 0.30, "neutral"),
        ("2024-01-31", "STABLE", 0.30, "neutral"),
        # STABLE always held; CHURNY out.
        ("2024-02-29", "STABLE", 0.30, "neutral"),
        # CHURNY back in.
        ("2024-03-31", "CHURNY", 0.30, "neutral"),
        ("2024-03-31", "STABLE", 0.30, "neutral"),
        # CHURNY out again.
        ("2024-04-30", "STABLE", 0.30, "neutral"),
        # CHURNY back in.
        ("2024-05-31", "CHURNY", 0.30, "neutral"),
        ("2024-05-31", "STABLE", 0.30, "neutral"),
        # CHURNY out.
        ("2024-06-28", "STABLE", 0.30, "neutral"),
        # Month 7: CHURNY tries to enter again. Over the prior 6 months
        # CHURNY's in/out pattern is [1,0,1,0,1,0] -> 5 transitions
        # >= swap_threshold(2). Must be blocked. STABLE passes through.
        ("2024-07-31", "CHURNY", 0.30, "neutral"),
        ("2024-07-31", "STABLE", 0.30, "neutral"),
    ]
    book = _book(rows)
    swap_counts = compute_swap_counts(book, window_months=6)
    out, decisions = apply_churn_filter(book, swap_counts, swap_threshold=2, target_regimes=("neutral",))
    last_month = out[out["rebalance_date"] == pd.Timestamp("2024-07-31")]
    assert "STABLE" in set(last_month["ticker"]), last_month
    assert "CHURNY" not in set(last_month["ticker"]), out
    blocked = [d for d in decisions if d["action"] == "blocked_entry"]
    assert any(d["ticker"] == "CHURNY" and d["rebalance_date"] == "2024-07-31" for d in blocked), decisions


def test_long_held_winner_never_blocked() -> None:
    # WINNER enters once and is held for 12 consecutive months in neutral
    # regime. It must never be blocked (zero in/out transitions).
    rows = [(f"2024-{m:02d}-28", "WINNER", 0.50, "neutral") for m in range(1, 13)]
    book = _book(rows)
    swap_counts = compute_swap_counts(book, window_months=6)
    out, decisions = apply_churn_filter(book, swap_counts, swap_threshold=2, target_regimes=("neutral",))
    assert len(out) == 12
    assert not any(d["action"] == "blocked_entry" for d in decisions)


def test_non_neutral_regimes_pass_through_unchanged() -> None:
    # Same CHURNY in/out pattern but under bull regime. Nothing should
    # be blocked.
    rows = [
        ("2024-01-31", "CHURNY", 0.30, "bull"),
        ("2024-02-29", "STABLE", 0.30, "bull"),
        ("2024-03-31", "CHURNY", 0.30, "bull"),
        ("2024-04-30", "STABLE", 0.30, "bull"),
        ("2024-05-31", "CHURNY", 0.30, "bull"),
        ("2024-06-28", "STABLE", 0.30, "bull"),
        ("2024-07-31", "CHURNY", 0.30, "bull"),
        ("2024-07-31", "STABLE", 0.30, "bull"),
    ]
    book = _book(rows)
    swap_counts = compute_swap_counts(book, window_months=6)
    out, decisions = apply_churn_filter(book, swap_counts, swap_threshold=2, target_regimes=("neutral",))
    assert len(out) == len(book), "bull-regime months must pass through unchanged"
    assert not any(d["action"] == "blocked_entry" for d in decisions)


def test_filter_does_not_force_hold_on_explicit_exit() -> None:
    # DECLINER held continuously then dropped from the book. The filter
    # must not resurrect the position.
    rows = [
        ("2024-01-31", "DECLINER", 0.50, "neutral"),
        ("2024-02-29", "DECLINER", 0.50, "neutral"),
        ("2024-03-31", "DECLINER", 0.50, "neutral"),
        # 2024-04-30: book explicitly drops DECLINER, holds STABLE.
        ("2024-04-30", "STABLE", 0.50, "neutral"),
    ]
    book = _book(rows)
    swap_counts = compute_swap_counts(book, window_months=6)
    out, _ = apply_churn_filter(book, swap_counts, swap_threshold=2, target_regimes=("neutral",))
    last_month = out[out["rebalance_date"] == pd.Timestamp("2024-04-30")]
    assert set(last_month["ticker"]) == {"STABLE"}, "filter must never force-hold an exit"


def test_blocked_weight_falls_to_cash_not_redistributed() -> None:
    # On the blocked month, the remaining stock weight sum must be
    # strictly less than the unfiltered original.
    rows = [
        ("2024-01-31", "CHURNY", 0.30, "neutral"),
        ("2024-01-31", "X", 0.30, "neutral"),
        ("2024-02-29", "X", 0.30, "neutral"),
        ("2024-03-31", "CHURNY", 0.30, "neutral"),
        ("2024-03-31", "X", 0.30, "neutral"),
        ("2024-04-30", "X", 0.30, "neutral"),
        ("2024-05-31", "CHURNY", 0.30, "neutral"),
        ("2024-05-31", "X", 0.30, "neutral"),
        ("2024-06-28", "X", 0.30, "neutral"),
        # Month 7: original book has CHURNY 0.30 + X 0.50 = 0.80.
        # Expected: CHURNY blocked, X stays at 0.50, total = 0.50.
        ("2024-07-31", "CHURNY", 0.30, "neutral"),
        ("2024-07-31", "X", 0.50, "neutral"),
    ]
    book = _book(rows)
    swap_counts = compute_swap_counts(book, window_months=6)
    out, _ = apply_churn_filter(book, swap_counts, swap_threshold=2, target_regimes=("neutral",))
    last_month = out[out["rebalance_date"] == pd.Timestamp("2024-07-31")]
    assert last_month["weight"].sum() < 0.80 + 1e-9, last_month
    # X (held continuously) keeps its 0.50.
    assert float(last_month.loc[last_month["ticker"] == "X", "weight"].iloc[0]) == 0.50


def test_run_wrapper_writes_csv_and_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        input_path = root / "in.csv"
        rows = [
            ("2024-01-31", "AAA", 0.50, "neutral"),
            ("2024-02-29", "BBB", 0.50, "neutral"),
            ("2024-03-31", "AAA", 0.50, "neutral"),
            ("2024-04-30", "BBB", 0.50, "neutral"),
            ("2024-05-31", "AAA", 0.50, "neutral"),
            ("2024-06-28", "BBB", 0.50, "neutral"),
            ("2024-07-31", "AAA", 0.50, "neutral"),
        ]
        _book(rows).to_csv(input_path, index=False)
        out_path = root / "out.csv"
        diag_path = root / "diag.json"
        payload = run(
            input_book=input_path,
            output_book=out_path,
            diagnostics_path=diag_path,
            swap_threshold=2,
            window_months=6,
            target_regimes=("neutral",),
        )
        assert payload["status"] == "completed"
        assert payload["schema_version"] == "neutral-regime-churn-filter-v1"
        assert out_path.exists()
        assert diag_path.exists()
        assert payload["neutral_entries_blocked"] >= 1


def main() -> int:
    test_high_churn_ticker_blocked_on_neutral_reentry()
    test_long_held_winner_never_blocked()
    test_non_neutral_regimes_pass_through_unchanged()
    test_filter_does_not_force_hold_on_explicit_exit()
    test_blocked_weight_falls_to_cash_not_redistributed()
    test_run_wrapper_writes_csv_and_diagnostics()
    print("neutral_regime_churn_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
