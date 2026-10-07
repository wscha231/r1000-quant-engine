#!/usr/bin/env python3
"""Smoke tests for the canonical Run287 P5 hold and sell-taxonomy policy."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.run287_hold_exit_policy import (  # noqa: E402
    MODULE_ID,
    MODULE_VERSION,
    POLICY_ID,
    LeadershipPersistencePolicy,
    SELL_TAXONOMY,
    build_leadership_persistence_book,
    challenger_eligible,
    classify_execution_sell,
    incumbent_protection,
    load_scored_candidate_cache,
    minimum_score_gap_candidate,
    policy_audit_identity,
    policy_module_config,
    serialize_policy_config,
)
from tools.security_lifecycle import REQUIRED_COLUMNS  # noqa: E402


def candidate_row(day: str, ticker: str, score: float, rs: float, sector: str) -> dict[str, object]:
    return {
        "rebalance_date": day,
        "ticker": ticker,
        "alphaops_vnext_score": score,
        "rs_benchmark_1w": 0.05,
        "rs_benchmark_3m": rs,
        "price_above_ma50": 1.0,
        "price_above_ma200": 1.0,
        "leader_tier": "DUAL_LEADER",
        "rs_sector_3m": 0.10,
        "industry_group_strength_score": 0.20,
        "portfolio_risk_entry_block_score": 0.10,
        "portfolio_stale_mega_leader_score": 0.0,
        "emerging_tenbagger_hard_reject_reason": "",
        "top7_standalone_blocked": False,
        "pit_evidence_blocked": False,
        "primary_lane": "MARKET_LEADER",
        "sector": sector,
        "industry_group": sector + " Group",
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lifecycle = root / "lifecycle.csv"
        pd.DataFrame(columns=sorted(REQUIRED_COLUMNS)).to_csv(lifecycle, index=False)
        control = pd.DataFrame(
            [
                {"rebalance_date": "2024-01-31", "ticker": "AAA", "weight": 0.40, "sector": "Tech", "industry_group": "Tech Group"},
                {"rebalance_date": "2024-01-31", "ticker": "BBB", "weight": 0.40, "sector": "Health", "industry_group": "Health Group"},
                {"rebalance_date": "2024-01-31", "ticker": "CASH", "weight": 0.20, "sector": "", "industry_group": ""},
                {"rebalance_date": "2024-02-29", "ticker": "CCC", "weight": 0.40, "sector": "Tech", "industry_group": "Tech Group"},
                {"rebalance_date": "2024-02-29", "ticker": "BBB", "weight": 0.40, "sector": "Health", "industry_group": "Health Group"},
                {"rebalance_date": "2024-02-29", "ticker": "CASH", "weight": 0.20, "sector": "", "industry_group": ""},
            ]
        )
        rows = []
        for day in ("2024-01-31", "2024-02-29"):
            rows.extend(
                [
                    candidate_row(day, "AAA", 1.00, 0.30, "Tech"),
                    candidate_row(day, "BBB", 0.50, 0.05, "Health"),
                    candidate_row(day, "CCC", 1.10, 0.20, "Tech"),
                ]
            )
            for index in range(7):
                rows.append(candidate_row(day, f"X{index}", 0.20 + index * 0.01, -0.20 + index * 0.02, "Other"))
        scored = pd.DataFrame(rows)
        control_before = control.copy(deep=True)
        scored_before = scored.copy(deep=True)
        treatment, decisions, exits, audit = build_leadership_persistence_book(
            control,
            scored,
            portfolio="main",
            lifecycle_path=lifecycle,
            policy=LeadershipPersistencePolicy(),
        )
        pd.testing.assert_frame_equal(control, control_before)
        pd.testing.assert_frame_equal(scored, scored_before)
        assert audit["status"] == "APPLIED", audit
        assert audit["applied_retention_count"] == 1
        feb = treatment[pd.to_datetime(treatment["rebalance_date"]).eq(pd.Timestamp("2024-02-29"))]
        assert "AAA" in set(feb["ticker"])
        assert "CCC" not in set(feb["ticker"])
        assert abs(float(feb["weight"].sum()) - 1.0) < 1e-12
        assert abs(float(feb.loc[feb["ticker"].eq("CASH"), "weight"].sum()) - 0.20) < 1e-12
        assert set(exits.get("sell_taxonomy", pd.Series(dtype=str))).issubset(set(SELL_TAXONOMY))
        assert decisions.iloc[0]["reason"] == "fixed_margin_not_met"

        # Legacy/default behavior is identical when the bounded candidate
        # helper is used with no hypothesis override.
        legacy = build_leadership_persistence_book(
            control, scored, portfolio="main", lifecycle_path=lifecycle,
        )
        candidate_default = build_leadership_persistence_book(
            control, scored, portfolio="main", lifecycle_path=lifecycle,
            policy=minimum_score_gap_candidate(),
        )
        for left, right in zip(legacy[:3], candidate_default[:3]):
            pd.testing.assert_frame_equal(left, right)
        assert legacy[3] == candidate_default[3]

        # Module/config identity is deterministic and only the bounded
        # hypothesis changes its identity.
        default_policy = LeadershipPersistencePolicy()
        config_a = serialize_policy_config(default_policy)
        config_b = serialize_policy_config(LeadershipPersistencePolicy())
        assert config_a == config_b
        module_config = policy_module_config(default_policy)
        assert module_config["module_id"] == MODULE_ID
        assert module_config["module_version"] == MODULE_VERSION
        assert module_config["policy_id"] == POLICY_ID
        identity_a = policy_audit_identity(default_policy)
        identity_b = policy_audit_identity(LeadershipPersistencePolicy())
        assert identity_a == identity_b
        changed_gap = minimum_score_gap_candidate(minimum_score_gap=0.23)
        assert policy_audit_identity(changed_gap) != identity_a
        assert serialize_policy_config(minimum_score_gap_candidate()) == config_a

        # Future labels may exist physically in the source CSV but are not
        # admitted to the policy input frame.
        scored_path = root / "scored_with_future_labels.csv"
        scored_with_future = scored.copy()
        scored_with_future["forward_return_63d"] = 0.50
        scored_with_future["label_target"] = 1
        scored_with_future.to_csv(scored_path, index=False)
        loaded = load_scored_candidate_cache(scored_path)
        assert "forward_return_63d" not in loaded.columns
        assert "label_target" not in loaded.columns
        assert set(loaded.attrs["future_columns_physically_excluded"]) == {
            "forward_return_63d", "label_target",
        }

        # PIT-blocked evidence cannot protect an incumbent or admit a challenger.
        pit_record = candidate_row("2024-02-29", "PIT", 1.50, 0.40, "Tech")
        pit_record["pit_evidence_blocked"] = True
        eligible, reason = challenger_eligible(
            pit_record, lifecycle_terminal=False, policy=default_policy,
        )
        assert not eligible and reason == "pit_future_evidence_block"
        protected, reason, taxonomy = incumbent_protection(
            pit_record,
            portfolio="main",
            score_median=0.50,
            score_sigma=0.20,
            rs_percentile=1.0,
            lifecycle_terminal=False,
            policy=default_policy,
        )
        assert not protected and reason == "pit_future_evidence_block"
        assert taxonomy == "RISK_EXIT"

        # Missing replacement cost is never silently converted to zero.
        try:
            policy_module_config(LeadershipPersistencePolicy(round_trip_cost_penalty=None))
        except ValueError as exc:
            assert "round_trip_cost_penalty" in str(exc)
        else:
            raise AssertionError("missing replacement cost was silently accepted")

        # A single rebalance event cannot simultaneously retain and exit the
        # same incumbent, and output keys remain unique.
        assert not treatment.duplicated(["rebalance_date", "ticker"]).any()
        assert not exits.duplicated(["rebalance_date", "portfolio", "ticker"]).any()
        retained_aaa = decisions[
            decisions["rebalance_date"].eq("2024-02-29")
            & decisions["incumbent_ticker"].eq("AAA")
        ]
        assert len(retained_aaa) == 1
        assert retained_aaa.iloc[0]["action"] == "RETAIN_INCUMBENT"
        aaa_exit = exits[
            exits.get("rebalance_date", pd.Series(dtype=str)).eq("2024-02-29")
            & exits.get("ticker", pd.Series(dtype=str)).eq("AAA")
        ]
        assert aaa_exit.empty
        assert int(feb["ticker"].eq("AAA").sum()) == 1

        assert classify_execution_sell(
            ticker="AAA", target_weight=0.0, target_gross_reduced=False,
            replacement_tickers={"CCC"},
        )[0] == "REPLACEMENT_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.2, target_gross_reduced=True,
            replacement_tickers={"CCC"},
        )[0] == "RISK_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.0, target_gross_reduced=True,
            replacement_tickers={"CCC"},
            lifecycle_terminal=True,
        )[0] == "LIFECYCLE_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.0, target_gross_reduced=False,
            thesis_break=True,
        )[0] == "THESIS_EXIT"
        assert classify_execution_sell(
            ticker="AAA", target_weight=0.3, target_gross_reduced=False,
        )[0] == "EXECUTION_RECONCILIATION"
    print("run287_hold_exit_policy_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
