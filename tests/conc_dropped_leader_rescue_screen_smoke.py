#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_conc_dropped_leader_rescue_screen import run


def _write_counterfactuals(base: Path, rows: list[dict[str, object]]) -> None:
    out = base / "right_tail_drop_counterfactual_audit"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "drop_counterfactuals.csv", index=False)


def _row(date: str, group: str, excess: float, ticker: str = "TEST") -> dict[str, object]:
    return {
        "portfolio": "concentrated",
        "ticker": ticker,
        "drop_date": date,
        "candidate_rank_percentile": 0.90,
        "drop_signal_stack_count": 8,
        "rs_benchmark_3m": 0.12,
        "rs_benchmark_6m": 0.25,
        "drop_ex_ante_signal_flags": "above_ma200;positive_3m_rs;positive_6m_rs;rank80",
        "candidate_sector": "Information Technology",
        "candidate_industry_group": group,
        "candidate_regime_state": "neutral",
        "candidate_market_style_regime_label": "balanced",
        "candidate_portfolio_sleeve_label": "future_winner",
        "fwd_126d_status": "completed",
        "fwd_126d_excess_spy": excess,
        "used_forward_return_in_ranking": False,
        "production_mutation_allowed": False,
    }


def test_no_segment_candidate_when_training_sample_is_too_thin() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        out = Path(td) / "out"
        _write_counterfactuals(
            base,
            [_row(f"2020-0{i + 1}-28", "Semiconductors", 0.10, ticker=f"A{i}") for i in range(4)],
        )
        summary = run(base_dir=base, output_dir=out)
        assert summary["status"] == "no_segment_candidate"
        assert summary["is_segment_candidate_count"] == 0
        assert summary["policy_eligible"] is False


def test_inconclusive_when_training_passes_but_oos_is_sparse() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        out = Path(td) / "out"
        rows = [_row(f"2020-0{i + 1}-28", "Semiconductors", 0.10, ticker=f"A{i}") for i in range(5)]
        rows += [_row(f"2025-0{i + 1}-28", "Semiconductors", 0.10, ticker=f"B{i}") for i in range(2)]
        _write_counterfactuals(base, rows)
        summary = run(base_dir=base, output_dir=out)
        assert summary["status"] == "inconclusive_oos_sample"
        assert summary["is_segment_candidate_count"] >= 1
        assert summary["oos_interpretable_segment_count"] == 0
        assert summary["policy_eligible"] is False


def test_ready_status_requires_training_and_oos_segment_pass() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "base"
        out = Path(td) / "out"
        rows = [_row(f"2020-0{i + 1}-28", "Semiconductors", 0.10, ticker=f"A{i}") for i in range(5)]
        rows += [_row(f"2025-0{i + 1}-28", "Semiconductors", 0.10, ticker=f"B{i}") for i in range(3)]
        _write_counterfactuals(base, rows)
        summary = run(base_dir=base, output_dir=out)
        assert summary["status"] == "segment_candidate_ready_for_target_book_screen"
        assert summary["oos_interpretable_segment_count"] >= 1
        assert summary["oos_pass_segment_count"] >= 1
        assert summary["policy_eligible"] is False
        assert summary["next_action"] == "target_book_screen_allowed_before_broker_ab"


if __name__ == "__main__":
    test_no_segment_candidate_when_training_sample_is_too_thin()
    test_inconclusive_when_training_passes_but_oos_is_sparse()
    test_ready_status_requires_training_and_oos_segment_pass()
    print("conc_dropped_leader_rescue_screen_smoke: PASS")
