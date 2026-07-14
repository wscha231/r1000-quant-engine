#!/usr/bin/env python3
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_pinned_git_import import pinned_import_context
from tools import run_run287_current_advisory_selector as advisory


PINNED_COMMIT = "15176b588d5bb0792bce1df6367758d795a8a33a"


def candidate_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rebalance_date": [pd.Timestamp("2026-07-10")] * 5,
            "ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
            "market_leader_lane_score": [1.0, 0.9, 0.8, 0.7, 0.6],
            "quality_compounder_lane_score": [0.5] * 5,
            "emerging_tenbagger_lane_score": [0.0] * 5,
            "top7_manager_discovery_lane_score": [0.0] * 5,
            "cyclical_recovery_lane_score": [0.0] * 5,
            "crisis_beneficiary_lane_score": [0.0] * 5,
            "rs_spy_3m": [0.2, 0.18, 0.16, 0.14, 0.12],
            "rs_qqq_3m": [0.2, 0.18, 0.16, 0.14, 0.12],
            "rs_spy_6m": [0.2] * 5,
            "rs_qqq_6m": [0.2] * 5,
            "rs_benchmark_1w": [0.1] * 5,
            "rs_semis_3m": [0.1] * 5,
            "valuation_support_score": [0.1] * 5,
            "top7_support_boost": [0.0] * 5,
            "sector": ["Technology"] * 5,
            "industry_group": ["Software"] * 5,
            "relative_strength_composite": [1.0] * 5,
            "crisis_new_buy_allowed": [True] * 5,
            "registered_ranking_eligible": [True] * 5,
        }
    )


def test_core_adapter_matches_pinned_one_date_variant_without_prior() -> None:
    phase_keys = [
        key for key in os.environ if key.startswith("PHASE_") or key.startswith("R1000_")
    ]
    saved = {key: os.environ.get(key) for key in phase_keys}
    for key in phase_keys:
        os.environ[key] = ""
    try:
        with pinned_import_context(PINNED_COMMIT, REPO_ROOT):
            policy = importlib.import_module("tools.run_alphaops_vnext_policy_replay")
            candidate = candidate_frame()
            crisis = pd.DataFrame(
                {"date": ["2026-07-10"], "crisis_state": ["GREEN"]}
            )
            direct, _lanes, _rejects, _exposure = policy.build_variant_book(
                candidate,
                portfolio_kind="main",
                target_n=3,
                crisis_states=crisis,
                prices={},
            )
            adapted, _transition, _rejection, _telemetry = advisory.run_core_selector(
                policy,
                month_input=candidate,
                prior_book=pd.DataFrame(columns=["ticker", "weight"]),
                portfolio_kind="main",
                scenario="fixture",
                target_n=3,
                crisis_states=crisis,
                prices={},
                registered_eligible=set(candidate["ticker"]),
            )
            stage_audit: list[dict] = []
            postbook, _post_transition, _post_rejection, post_telemetry = (
                advisory.run_core_selector(
                    policy,
                    month_input=candidate,
                    prior_book=pd.DataFrame(columns=["ticker", "weight"]),
                    portfolio_kind="main",
                    scenario="fixture_postbook",
                    target_n=3,
                    crisis_states=crisis,
                    prices={},
                    registered_eligible=set(candidate["ticker"]),
                    apply_postbook=True,
                    stage_audit_sink=stage_audit,
                )
            )
            direct_weights = direct.set_index("ticker")["weight"].sort_index()
            adapted_weights = adapted.set_index("ticker")["advisory_weight"].sort_index()
            pd.testing.assert_series_equal(
                direct_weights,
                adapted_weights,
                check_names=False,
                atol=1e-12,
                rtol=0.0,
            )
            assert bool(adapted["execution_allowed"].eq(False).all())
            assert abs(float(postbook["advisory_weight"].sum()) - 1.0) <= 1e-12
            assert post_telemetry["postbook_controls_applied"] is True
            assert stage_audit
            assert {row["stage_name"] for row in stage_audit}.issuperset(
                {"assign_weights"}
            )
            assert all(row["execution_allowed"] is False for row in stage_audit)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_determinism_comparison_detects_weight_change() -> None:
    left = pd.DataFrame(
        {
            "scenario": ["x"],
            "portfolio_kind": ["main"],
            "ticker": ["AAA"],
            "advisory_weight": [1.0],
            "prior_weight": [0.0],
            "registered_eligible": [True],
            "prior_holding": [False],
            "holding_state": ["NEW"],
            "hold_replace_decision": ["new_entry"],
            "primary_lane": ["MARKET_LEADER"],
            "alphaops_vnext_score": [1.0],
            "alphaops_vnext_weight_score": [1.0],
            "crisis_state": ["GREEN"],
        }
    )
    assert advisory.deterministic_projection(left, left.copy()) is True
    changed = left.copy()
    changed.loc[0, "advisory_weight"] = 0.9
    assert advisory.deterministic_projection(left, changed) is False


def main() -> int:
    test_core_adapter_matches_pinned_one_date_variant_without_prior()
    test_determinism_comparison_detects_weight_change()
    print("run287_current_advisory_selector_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
