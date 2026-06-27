#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_concentrated_sizing_ab_screen import (  # noqa: E402
    EVAL_SPLIT_DATE,
    summarize_variants,
    variant_period_returns,
    variant_rows,
)


def _book(*, inverse_oos: bool = False) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = [
        "2021-06-30",
        "2022-06-30",
        "2023-06-30",
        EVAL_SPLIT_DATE.date().isoformat(),
        "2025-06-30",
        "2026-06-30",
    ]
    for dt in dates:
        oos = pd.Timestamp(dt) >= EVAL_SPLIT_DATE
        for ticker, score, forward, weight in [
            ("LOW", 1.0, -0.04, 0.45),
            ("MID", 2.0, 0.00, 0.30),
            ("HIGH", 3.0, 0.08, 0.25),
        ]:
            if inverse_oos and oos:
                forward = -forward
            rows.append(
                {
                    "rebalance_date": dt,
                    "ticker": ticker,
                    "base_weight": weight,
                    "period_forward_return": forward,
                    "forward_return": forward,
                    "alphaops_vnext_score": score,
                    "alphaops_vnext_weight_score": score,
                    "weighting_score": score,
                }
            )
    d = pd.DataFrame(rows)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"]).dt.normalize()
    return d


def test_score_reweight_preserves_gross_stock_weight_and_finds_candidate() -> None:
    rows = variant_rows(_book())
    periods = variant_period_returns(rows)
    summaries, table = summarize_variants(periods)

    gross_by_variant_date = rows.groupby(["variant", "signal", "rebalance_date"])["weight"].sum().round(10)
    assert gross_by_variant_date.nunique() == 1
    assert float(gross_by_variant_date.iloc[0]) == 1.0
    assert any(item["screen_candidate"] for item in summaries)
    candidate = table[table["screen_candidate"]].iloc[0]
    assert candidate["delta_cagr_proxy"] > 0
    assert candidate["oos_delta_cagr_proxy"] > 0


def test_oos_failure_blocks_candidate_even_when_is_looks_good() -> None:
    rows = variant_rows(_book(inverse_oos=True))
    periods = variant_period_returns(rows)
    summaries, _table = summarize_variants(periods)

    assert summaries
    assert not any(item["screen_candidate"] for item in summaries)


if __name__ == "__main__":
    test_score_reweight_preserves_gross_stock_weight_and_finds_candidate()
    test_oos_failure_blocks_candidate_even_when_is_looks_good()
    print("concentrated_sizing_ab_screen_smoke passed")
