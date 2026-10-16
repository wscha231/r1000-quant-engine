"""Smoke tests for Concentrated cash-funded early-entry policy hook."""

from __future__ import annotations

import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_alphaops_vnext_policy_replay import (  # noqa: E402
    apply_concentrated_cashfunded_early_entry,
)


ENV_KEYS = (
    "PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_SIGNAL",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_ADD_WEIGHT",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_MIN_BREAKOUT_QUALITY",
    "R1000_CONC_CASHFUNDED_EARLY_ENTRY_ALLOW_CRISIS",
)


class EnvGuard:
    def __enter__(self) -> None:
        self.old = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)

    def __exit__(self, exc_type, exc, tb) -> None:
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _weighted(cash_left: float = 0.50) -> list[dict[str, object]]:
    invested = max(0.0, 1.0 - cash_left)
    return [
        {"ticker": "AAA", "weight": invested * 0.60, "target_weight": invested * 0.60, "primary_lane": "MARKET_LEADER"},
        {"ticker": "BBB", "weight": invested * 0.40, "target_weight": invested * 0.40, "primary_lane": "MARKET_LEADER"},
    ]


def _month_records() -> list[dict[str, object]]:
    return [
        {
            "ticker": "AAA",
            "future_winner_scout_score": 9.0,
            "breakout_setup_quality_score": 1.0,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
        },
        {
            "ticker": "CCC",
            "future_winner_scout_score": 7.0,
            "breakout_setup_quality_score": 0.55,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
        },
        {
            "ticker": "DDD",
            "future_winner_scout_score": 5.0,
            "breakout_setup_quality_score": 0.20,
            "primary_lane": "MARKET_LEADER",
            "crisis_state": "GREEN",
        },
    ]


def test_default_off_preserves_weighted_book() -> None:
    with EnvGuard():
        weighted = _weighted()
        out = apply_concentrated_cashfunded_early_entry(weighted, _month_records(), "concentrated")
        assert out == weighted


def test_enabled_adds_best_unheld_candidate_from_cash_only() -> None:
    with EnvGuard():
        os.environ["PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED"] = "1"
        out = apply_concentrated_cashfunded_early_entry(_weighted(), _month_records(), "concentrated")
        weights = {str(row["ticker"]): float(row["weight"]) for row in out}
        assert weights["AAA"] == 0.30
        assert weights["BBB"] == 0.20
        assert weights["CCC"] == 0.058
        assert "DDD" not in weights
        added = [row for row in out if row.get("concentrated_cashfunded_early_entry_applied")]
        assert len(added) == 1
        assert added[0]["ticker"] == "CCC"
        assert added[0]["hold_replace_decision"] == "cashfunded_early_entry"
        assert added[0]["concentrated_cashfunded_early_entry_non_sticky"] is True
        assert float(added[0]["concentrated_cashfunded_early_entry_min_breakout_quality"]) == 0.50


def test_enabled_add_weight_is_capped_by_cash() -> None:
    with EnvGuard():
        os.environ["PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED"] = "1"
        out = apply_concentrated_cashfunded_early_entry(_weighted(cash_left=0.02), _month_records(), "concentrated")
        added = [row for row in out if row.get("concentrated_cashfunded_early_entry_applied")]
        assert len(added) == 1
        assert added[0]["ticker"] == "CCC"
        assert abs(float(added[0]["weight"]) - 0.02) < 1e-12


def test_low_breakout_top_candidate_blocks_instead_of_falling_back() -> None:
    with EnvGuard():
        os.environ["PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED"] = "1"
        rows = _month_records()
        rows[2]["future_winner_scout_score"] = 8.0
        out = apply_concentrated_cashfunded_early_entry(_weighted(), rows, "concentrated")
        added = [row for row in out if row.get("concentrated_cashfunded_early_entry_applied")]
        assert not added
        assert all(
            row["concentrated_cashfunded_early_entry_status"]
            == "blocked_top_candidate_low_breakout_quality"
            for row in out
        )


def test_forward_return_signal_is_rejected() -> None:
    with EnvGuard():
        os.environ["PHASE_CONCENTRATED_CASHFUNDED_EARLY_ENTRY_ENABLED"] = "1"
        os.environ["R1000_CONC_CASHFUNDED_EARLY_ENTRY_SIGNAL"] = "period_forward_return"
        try:
            apply_concentrated_cashfunded_early_entry(_weighted(), _month_records(), "concentrated")
        except ValueError as exc:
            assert "forward-return" in str(exc)
        else:
            raise AssertionError("period_forward_return must be rejected")


def main() -> int:
    test_default_off_preserves_weighted_book()
    test_enabled_adds_best_unheld_candidate_from_cash_only()
    test_enabled_add_weight_is_capped_by_cash()
    test_low_breakout_top_candidate_blocks_instead_of_falling_back()
    test_forward_return_signal_is_rejected()
    print("concentrated_cashfunded_early_entry_hook_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
