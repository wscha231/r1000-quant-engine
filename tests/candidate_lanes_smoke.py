#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from r1000_candidate_lanes import lane_feature_mapping_payload, score_candidate_lanes  # noqa: E402


def test_emerging_negative_fcf_is_risk_cap_not_hard_reject() -> None:
    frame = pd.DataFrame(
        [
            {
                "ticker": "RKLB",
                "fcf_ttm": -25_000_000,
                "fcf_margin": 0.10,
                "net_income_ttm": 5_000_000,
                "op_income_ttm": -10_000_000,
                "operating_margin": 0.05,
                "theme_phase_primary": "emerging",
                "theme_phase_multiplier_primary": 1.5,
                "rs_benchmark_3m": 0.25,
                "rs_acceleration_score": 0.8,
                "revenue_acceleration": 0.9,
                "backlog_or_contract_signal": 0.8,
                "dollar_vol_20d": 100_000_000,
                "market_cap_live": 8_000_000_000,
                "data_confidence": 0.9,
                "cash_runway_quarters": 6,
                "dilution_4q": 0.05,
                "price_above_ma50": 1,
                "price_above_ma200": 1,
            }
        ]
    )
    out = score_candidate_lanes(frame)
    assert out.loc[0, "emerging_tenbagger_hard_reject_reason"] == ""
    assert out.loc[0, "emerging_tenbagger_risk_cap"] < 1.0
    assert out.loc[0, "emerging_tenbagger_lane_score"] > -1.0


def test_lane_feature_mapping_documents_top7_not_standalone_buy() -> None:
    payload = lane_feature_mapping_payload()
    assert payload["rules"]["top7_13f"] == "universe_expansion_and_confidence_only_not_standalone_buy"
    assert "EMERGING_TENBAGGER" in payload["lanes"]


def main() -> int:
    test_emerging_negative_fcf_is_risk_cap_not_hard_reject()
    test_lane_feature_mapping_documents_top7_not_standalone_buy()
    print("candidate_lanes_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
