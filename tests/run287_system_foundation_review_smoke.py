#!/usr/bin/env python3
"""Foundation review remains fail-closed and machine-readable."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "docs" / "run287_system_foundation_review_20260727.json"


def main() -> None:
    payload = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert payload["verdict"] == "BLOCK_PERFORMANCE_CLAIMS_UNTIL_CORRECTED_REBASELINE"
    assert payload["performance_claim"]["cagr_improved"] is False
    assert payload["performance_claim"]["mdd_improved"] is False
    assert payload["performance_claim"]["reason"]
    constraints = payload["operating_constraints"]
    for key in (
        "new_worktree_allowed",
        "fullrun_allowed",
        "production_allowed",
        "live_trading_allowed",
        "automatic_champion_promotion_allowed",
        "catchup_2026_07_27_allowed_before_completed_nyse_close",
    ):
        assert constraints[key] is False
    findings = {row["id"]: row for row in payload["critical_findings"]}
    for fixed in (
        "F0_LABEL_MATURITY",
        "F0_BENCHMARK_FORWARD_JOIN",
        "F0_OOS_INDEPENDENCE",
        "F0_AUTOMATIC_PROMOTION",
    ):
        assert findings[fixed]["status"] == "FIXED_AND_SMOKE_TESTED"
    assert payload["ordered_next_work"][0]["id"] == "corrected_canonical_rebaseline"
    assert payload["ordered_next_work"][0]["requires_fullrun_approval"] is True
    assert payload["ordered_next_work"][-1]["maximum_active_arms"] == 1
    print("run287_system_foundation_review_smoke: PASS")


if __name__ == "__main__":
    main()
