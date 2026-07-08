#!/usr/bin/env python3
"""Smoke checks for shared AlphaOps governance fields."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.alphaops_governance import research_production_gate_fields  # noqa: E402


def test_benchmark_relative_public_claim_is_forbidden() -> None:
    fields = research_production_gate_fields(pit_universe_label_clean=False)
    forbidden = set(fields["forbidden_labels"])
    assert "public_return_claim" in forbidden
    assert "benchmark_relative_public_claim" in forbidden
    assert fields["production_promotion_allowed"] is False
    assert fields["public_display_allowed"] is False


if __name__ == "__main__":
    test_benchmark_relative_public_claim_is_forbidden()
    print("alphaops_governance_smoke: PASS")
