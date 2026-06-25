#!/usr/bin/env python3
"""Smoke test for the fusion candidate review sidecar."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_fusion_candidate_review import run  # noqa: E402


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def build_fixture(root: Path) -> Path:
    base = root / "outputs"
    write_csv(
        base / "right_tail_entry_signal_audit" / "winner_entry_signals.csv",
        [
            {
                "portfolio": "concentrated",
                "ticker": "AAA",
                "entry_signal_date": "2024-01-31",
                "skill_evidence_flag": True,
                "entry_signal_stack_count": 7,
                "candidate_rank_percentile": 0.91,
                "rs_benchmark_3m": 0.24,
                "sector": "Industrials",
                "subindustry": "Capital Goods - Machinery",
            },
            {
                "portfolio": "concentrated",
                "ticker": "BBB",
                "entry_signal_date": "2024-01-31",
                "skill_evidence_flag": False,
                "entry_signal_stack_count": 1,
                "candidate_rank_percentile": 0.10,
            },
        ],
    )
    write_csv(
        base / "right_tail_entry_signal_audit" / "drop_signal_reviews.csv",
        [
            {
                "portfolio": "concentrated",
                "ticker": "AAA",
                "drop_date": "2024-03-29",
                "drop_skill_evidence_flag": True,
                "drop_candidate_rank_percentile": 0.88,
            }
        ],
    )
    write_csv(
        base / "right_tail_drop_counterfactual_audit" / "drop_counterfactuals.csv",
        [
            {
                "portfolio": "concentrated",
                "ticker": "AAA",
                "drop_date": "2024-03-29",
                "drop_skill_evidence_flag": True,
                "drop_candidate_rank_percentile": 0.90,
                "drop_entry_signal_stack_count": 8,
                "fwd_63d_excess_spy": -0.20,
                "fwd_126d_excess_spy": -0.30,
                "sector": "Industrials",
                "subindustry": "Capital Goods - Machinery",
            },
            {
                "portfolio": "concentrated",
                "ticker": "LUCK",
                "drop_date": "2024-03-29",
                "drop_skill_evidence_flag": False,
                "drop_candidate_rank_percentile": 0.10,
                "drop_entry_signal_stack_count": 1,
                "fwd_63d_excess_spy": 9.99,
                "fwd_126d_excess_spy": 9.99,
            },
        ],
    )
    write_csv(
        base / "right_tail_drop_counterfactual_audit" / "segment_summary.csv",
        [
            {
                "portfolio": "concentrated",
                "group_field": "subindustry",
                "group_value": "Capital Goods - Machinery",
                "subset": "high_signal",
                "observations": 3,
                "avg_126d_excess_spy": 0.20,
                "positive_rate_126d_excess_spy": 0.67,
            }
        ],
    )
    write_csv(
        base / "concentrated_cap_replacement_audit" / "top_missed_cap_replacement.csv",
        [
            {
                "portfolio": "concentrated",
                "ticker": "AAA",
                "rebalance_date": "2024-01-31",
                "rs_benchmark_3m": 0.25,
                "leader_rank_percentile": 0.92,
                "forward_126d_excess": -0.10,
            },
            {
                "portfolio": "concentrated",
                "ticker": "LUCK",
                "rebalance_date": "2024-01-31",
                "rs_benchmark_3m": 0.01,
                "leader_rank_percentile": 0.05,
                "forward_126d_excess": 99.0,
            },
        ],
    )
    write_csv(
        base / "alpha_beta_attribution" / "concentrated" / "name_contribution.csv",
        [
            {
                "ticker": "AAA",
                "contribution_return_on_start": 0.25,
            }
        ],
    )
    return base


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = build_fixture(root)
        out = root / "fusion"
        payload = run(base, out)
        assert payload["schema_version"] == "fusion-candidate-review-v1"
        assert payload["research_only"] is True
        assert payload["policy_eligible"] is False
        assert payload["used_forward_return_in_ranking"] is False
        assert payload["fusion_review_candidate_count"] == 1, payload
        rows = pd.read_csv(out / "candidate_signals.csv")
        aaa = rows[rows["ticker"].eq("AAA")].iloc[0]
        assert bool(aaa["fusion_review_candidate"]) is True
        assert int(aaa["independent_source_count"]) >= 4
        assert float(aaa["audit_forward_126d_excess_spy_max"]) < 0.0
        assert bool(aaa["used_forward_return_in_ranking"]) is False
        assert bool(aaa["policy_eligible"]) is False
        assert "LUCK" not in set(rows[rows["fusion_review_candidate"].astype(bool)]["ticker"])
        segments = pd.read_csv(out / "segment_fusion_summary.csv")
        assert bool(segments.iloc[0]["segment_review_candidate"]) is True
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["segment_review_candidate_count"] == 1
        report = (out / "report.md").read_text(encoding="utf-8")
        assert "Forward returns are audit labels only" in report
    print("fusion candidate review smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
