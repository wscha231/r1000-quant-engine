#!/usr/bin/env python3
"""Focused checks for the P6 candidate-gate and stability contract."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from r1000_candidate_lanes import materialize_sector_relative_strength  # noqa: E402
from tools.run287_candidate_gate_stability_audit import (  # noqa: E402
    ACTIVE_HEADS,
    candidate_decomposition,
    map_rejection_reason,
    prediction_head_audit,
    rank_stability,
    repair_sector_rs,
    run,
)


def candidate_rows() -> pd.DataFrame:
    rows = []
    for date_index, day in enumerate(("2024-01-31", "2024-02-29")):
        for index, ticker in enumerate(("AAA", "BBB", "CCC")):
            rows.append({
                "rebalance_date": day,
                "ticker": ticker,
                "sector": "Technology" if ticker != "CCC" else "Health Care",
                "mom_1m": 0.01 + index * 0.01,
                "mom_3m": 0.10 + index * 0.10 + date_index * 0.01,
                "mom_6m": 0.20 + index * 0.10,
                "mom_12m": 0.30 + index * 0.10,
                "rs_sector_3m": np.nan,
                "alphaops_vnext_score": 3.0 - index + date_index * 0.01,
                "rs_benchmark_3m": 0.10 + index * 0.05,
                "price_above_ma200": 1.0,
                "dollar_vol_20d": 1_000_000.0,
                "industry_group_strength_score": 0.4,
                "sector_adjusted_quality_score": 0.5,
                "capital_efficiency_score": 0.6,
                "fundamental_reliability_score": 0.7,
            })
    return pd.DataFrame(rows)


def main() -> int:
    candidates = candidate_rows()
    repaired, audit = repair_sector_rs(candidates)
    assert audit["coverage_before"] == 0.0
    assert audit["coverage_after"] == 1.0
    assert audit["coverage_increase_pp"] == 100.0
    technology = repaired[
        repaired["sector"].eq("Technology")
        & repaired["rebalance_date"].eq("2024-01-31")
    ]
    assert np.allclose(technology["rs_sector_3m"], [-0.05, 0.05])

    existing = candidates.copy()
    existing["rs_sector_3m"] = 7.0
    preserved = materialize_sector_relative_strength(
        existing,
        periods=(("mom_3m", "rs_sector_3m"),),
        fill_missing_only=True,
    )
    assert preserved["rs_sector_3m"].eq(7.0).all()

    decomposition = candidate_decomposition(repaired)
    assert decomposition["critical_data_complete"].all()
    assert not decomposition["data_complete"].any()
    assert decomposition["neutralized_feature_count"].gt(0).all()
    assert "period_forward_return" not in decomposition.columns
    assert not decomposition["used_forward_return_for_selection"].any()
    stability = rank_stability(repaired)
    assert len(stability) == 1
    assert stability.iloc[0]["top_10_turnover"] == 0.7

    current = pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"]})
    reference = pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"]})
    for head_index, head in enumerate(ACTIVE_HEADS):
        current[head] = [0.1 + head_index, 0.2 + head_index, 0.3 + head_index]
        reference[head] = [0.11 + head_index, 0.21 + head_index, 0.31 + head_index]
    head_rows, summary = prediction_head_audit(current, reference)
    assert len(head_rows) == 6
    assert summary["all_heads_pass"] is True
    assert summary["silent_zero_fallback_detected"] is False

    current["pred_lin_ret_x"] = current["pred_lin_ret"]
    _, collision = prediction_head_audit(current, reference)
    assert collision["stale_suffix_collision_count"] == 1

    missing = current.drop(columns=["pred_lin_ret", "pred_lin_ret_x"])
    missing_rows, missing_summary = prediction_head_audit(missing, reference)
    assert missing_summary["all_heads_pass"] is False
    assert missing_summary["missing_current_heads"] == ["pred_lin_ret"]
    assert missing_rows.loc[
        missing_rows["prediction_head"].eq("pred_lin_ret"), "current_status"
    ].item() == "MISSING_HEAD_IN_CURRENT"

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candidate_path = root / "candidate.csv"
        scored_path = root / "scored.csv"
        main_path = root / "main.csv"
        concentrated_path = root / "concentrated.csv"
        rejections_path = root / "rejections.csv"
        current_path = root / "current.csv"
        reference_path = root / "reference.csv"
        output_dir = root / "blocked"
        price_cache = root / "prices"
        price_cache.mkdir()
        candidates.to_csv(candidate_path, index=False)
        candidates.to_csv(scored_path, index=False)
        pd.DataFrame(
            [{"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 1.0}]
        ).to_csv(main_path, index=False)
        pd.DataFrame(
            [{"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 1.0}]
        ).to_csv(concentrated_path, index=False)
        pd.DataFrame([{"ticker": "ZZZ", "reason": "candidate_gate"}]).to_csv(
            rejections_path, index=False
        )
        missing.to_csv(current_path, index=False)
        reference.to_csv(reference_path, index=False)
        payload = run(
            SimpleNamespace(
                candidate_artifact=str(candidate_path),
                scored_candidate_cache=str(scored_path),
                main_target_book=str(main_path),
                concentrated_target_book=str(concentrated_path),
                rejections=str(rejections_path),
                current_score_stack=str(current_path),
                reference_score_stack=str(reference_path),
                price_cache=str(price_cache),
                output_dir=str(output_dir),
            )
        )
        assert payload["status"] == "BLOCKED_PREDICTION_HEAD_INTEGRITY"
        assert payload["downstream_outcome_evaluation_executed"] is False
        assert "missing_current_prediction_head:pred_lin_ret" in payload["blockers"]
        assert (output_dir / "summary.json").is_file()
        assert (output_dir / "prediction_head_activity_and_drift.csv").is_file()
        assert not (output_dir / "selected_vs_rank_matched_metrics.csv").exists()
    assert map_rejection_reason("price_trend_not_alive") == "TREND_OR_RS_FAILURE"
    assert map_rejection_reason("concentrated_emerging_or_top7_seat_cap") == "NAME_OR_SECTOR_CAPACITY"
    print("run287_candidate_gate_stability_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
