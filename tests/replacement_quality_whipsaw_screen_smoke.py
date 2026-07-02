from __future__ import annotations

import tempfile
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_replacement_quality_whipsaw_screen import build_screen, main


def _candidate_rows() -> pd.DataFrame:
    rows = [
        {
            "rebalance_date": "2020-01-31",
            "ticker": "OLD",
            "leader_tier": "DUAL_LEADER",
            "alphaops_vnext_score": 1.0,
            "rs_benchmark_3m": 0.20,
            "rs_benchmark_6m": 0.25,
            "actual_results_score": 1.0,
            "sector_leadership_score": 0.8,
            "eps_revision_score": 0.1,
            "price_above_ma200": 1.0,
            "price_above_ma50": 1.0,
            "period_forward_return": 0.30,
        },
        {
            "rebalance_date": "2020-01-31",
            "ticker": "NEW",
            "leader_tier": "SECTOR_LEADER",
            "alphaops_vnext_score": 1.4,
            "rs_benchmark_3m": 0.04,
            "rs_benchmark_6m": 0.02,
            "actual_results_score": 0.0,
            "sector_leadership_score": 0.1,
            "eps_revision_score": 0.0,
            "price_above_ma200": 1.0,
            "price_above_ma50": 1.0,
            "period_forward_return": -0.10,
        },
        {
            "rebalance_date": "2020-02-29",
            "ticker": "NEW",
            "leader_tier": "SECTOR_LEADER",
            "alphaops_vnext_score": 1.3,
            "rs_benchmark_3m": 0.15,
            "rs_benchmark_6m": 0.10,
            "actual_results_score": 0.5,
            "sector_leadership_score": 0.5,
            "eps_revision_score": 0.0,
            "price_above_ma200": 1.0,
            "price_above_ma50": 1.0,
            "period_forward_return": 0.05,
        },
        {
            "rebalance_date": "2020-02-29",
            "ticker": "BAD",
            "leader_tier": "LAGGING",
            "alphaops_vnext_score": 0.8,
            "rs_benchmark_3m": -0.05,
            "rs_benchmark_6m": -0.02,
            "actual_results_score": 2.0,
            "sector_leadership_score": 1.0,
            "eps_revision_score": 0.5,
            "price_above_ma200": 1.0,
            "price_above_ma50": 1.0,
            "period_forward_return": 9.99,
        },
    ]
    d = pd.DataFrame(rows)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"])
    return d


def _target_rows() -> pd.DataFrame:
    rows = [
        {"rebalance_date": "2019-12-31", "ticker": "OLD", "weight": 1.0},
        {"rebalance_date": "2020-01-31", "ticker": "NEW", "weight": 1.0},
        {"rebalance_date": "2020-02-29", "ticker": "BAD", "weight": 1.0},
    ]
    d = pd.DataFrame(rows)
    d["rebalance_date"] = pd.to_datetime(d["rebalance_date"])
    return d


def test_build_screen_uses_pit_quality_not_forward_for_candidate_selection() -> None:
    events, summary = build_screen(
        candidate=_candidate_rows(),
        target=_target_rows(),
        quality_margin=0.20,
        min_events=1,
        min_positive_rate=0.50,
        min_mean_forward_edge=0.0,
    )
    candidates = events[events["screen_candidate"].eq(True)]
    assert len(candidates) == 1
    row = candidates.iloc[0].to_dict()
    assert row["incumbent_ticker"] == "OLD"
    assert row["challenger_ticker"] == "NEW"
    assert row["audit_forward_edge_incumbent_minus_challenger"] > 0
    assert summary["screen_pass"] is True
    assert summary["forward_columns_used_for_selection"] is False


def test_cli_writes_summary_and_candidate_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.csv"
        target = root / "target.csv"
        output = root / "out"
        _candidate_rows().to_csv(candidate, index=False)
        _target_rows().to_csv(target, index=False)
        import sys

        old_argv = sys.argv[:]
        try:
            sys.argv = [
                "run_replacement_quality_whipsaw_screen.py",
                "--candidate-book",
                str(candidate),
                "--target-book",
                str(target),
                "--output-dir",
                str(output),
                "--min-events",
                "1",
                "--min-positive-rate",
                "0.5",
            ]
            assert main() == 0
        finally:
            sys.argv = old_argv
        assert (output / "summary.json").exists()
        assert (output / "replacement_quality_candidates.csv").exists()


if __name__ == "__main__":
    test_build_screen_uses_pit_quality_not_forward_for_candidate_selection()
    test_cli_writes_summary_and_candidate_files()
    print("replacement_quality_whipsaw_screen_smoke: PASS")
