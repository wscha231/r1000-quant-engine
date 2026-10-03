#!/usr/bin/env python3
"""Current-contract revision windows retain the existing smoke entrypoint."""
from pathlib import Path
import sys
import pandas as pd
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earnings_consensus_h1_smoke import snapshot, features, AdmissionTests


def test_same_period_windows_are_source_only():
    out = features([snapshot("2026-04-01T18:00:00Z", 1),
                    snapshot("2026-06-01T18:00:00Z", 1.1),
                    snapshot("2026-07-01T18:00:00Z", 1.25)])
    latest = out.iloc[-1]
    assert latest.est_eps_revision_30d > 0
    assert latest.est_eps_revision_90d > 0
    assert pd.isna(latest.est_eps_revision_breadth)
    assert latest.estimate_revision_confirmed == 0
    assert latest.estimate_revision_replacement_gate_pass == 0
    assert latest.estimate_revision_future_winner_multiplier == 1
    assert not latest.h2_eligible


def test_missing_forward_estimate_cannot_confirm_revision():
    latest = features([snapshot(eps_payload={}, revenue_payload={})]).iloc[0]
    assert pd.isna(latest.est_eps_revision_30d)
    assert latest.estimate_revision_confirmed == 0
    assert latest.estimate_revision_future_winner_multiplier == 1


if __name__ == "__main__":
    test_same_period_windows_are_source_only()
    test_missing_forward_estimate_cannot_confirm_revision()
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(AdmissionTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("estimate_revision_features_smoke: PASS (including H1 admission regressions)")
