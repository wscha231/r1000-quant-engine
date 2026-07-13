#!/usr/bin/env python3
"""Smoke tests for the Run287 rejected-candidate preflight."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_run287_do_not_repeat import evaluate_candidate, load_registry  # noqa: E402


def test_exact_rejected_candidate_is_blocked() -> None:
    registry = load_registry()
    result = evaluate_candidate(
        registry,
        signal="target_weight_direction",
        mechanism="partial_resize_two_signal_confirmation",
        book="generated_baseline_books",
        window="2019-06-03_2026-07-10",
    )
    assert result["status"] == "BLOCKED_DO_NOT_REPEAT"
    assert result["allowed"] is False
    assert result["matched_entry_ids"] == ["partial_resize_two_signal_confirmation"]


def test_coverage_or_real_semantic_change_can_reopen() -> None:
    registry = load_registry()
    common = {
        "signal": "target_weight_direction",
        "mechanism": "partial_resize_two_signal_confirmation",
        "book": "generated_baseline_books",
        "window": "2019-06-03_2026-07-10",
    }
    coverage = evaluate_candidate(registry, **common, component_coverage_increase_pp=5.0)
    assert coverage["status"] == "ALLOWED_COVERAGE_CHANGE"
    semantic_without_note = evaluate_candidate(registry, **common, semantics_changed=True)
    assert semantic_without_note["status"] == "BLOCKED_DO_NOT_REPEAT"
    semantic = evaluate_candidate(
        registry,
        **common,
        semantics_changed=True,
        change_note="new decision-time source changes which resize is eligible",
    )
    assert semantic["status"] == "ALLOWED_SEMANTIC_CHANGE"


def test_new_combination_is_allowed() -> None:
    result = evaluate_candidate(
        load_registry(),
        signal="new_pit_estimate_revision",
        mechanism="source_screen",
        book="single_source_events",
        window="2019-06-03_2026-07-10",
    )
    assert result["status"] == "ALLOWED_NEW_COMBINATION"
    assert result["allowed"] is True


def main() -> int:
    test_exact_rejected_candidate_is_blocked()
    test_coverage_or_real_semantic_change_can_reopen()
    test_new_combination_is_allowed()
    print("run287_do_not_repeat_registry_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
