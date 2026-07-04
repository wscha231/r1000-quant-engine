#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_state_conditional_ic_audit import run  # noqa: E402


def test_state_conditional_ic_audit_is_gate_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        states = root / "state_history.csv"
        pd.DataFrame(
            [
                {"date": "2026-01-01", "state": "CORRECTION"},
                {"date": "2026-04-01", "state": "BULL"},
            ]
        ).to_csv(states, index=False)
        rows = []
        for idx in range(24):
            correction = idx < 12
            rows.append(
                {
                    "rebalance_date": (pd.Timestamp("2026-01-31") + pd.DateOffset(months=idx % 6)).date().isoformat(),
                    "rs_spy_3m": 24 - idx if correction else idx,
                    "rs_spy_6m": 12 - idx * 0.3,
                    "h1_oversold_value_score": idx if correction else idx * 0.1,
                    "profitability_inflection_score": idx if correction else idx * 0.1,
                    "forward_126d_excess": idx / 100.0 if correction else (24 - idx) / 100.0,
                }
            )
        candidates = root / "candidates.csv"
        pd.DataFrame(rows).to_csv(candidates, index=False)
        payload = run(
            argparse.Namespace(
                inputs=[str(candidates)],
                state_history=str(states),
                output_dir=str(root / "out"),
                min_samples=5,
                material_ic_gap=0.01,
            )
        )
        assert payload["status"] == "completed", payload
        assert payload["policy_hook_allowed"] is False
        assert payload["forward_labels_used_for_ranking"] is False
        assert (root / "out" / "ic_by_state_and_feature_family.csv").exists()


def test_state_conditional_ic_audit_does_not_pass_r3_with_insufficient_samples() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        states = root / "state_history.csv"
        pd.DataFrame([{"date": "2026-01-01", "state": "CORRECTION"}]).to_csv(states, index=False)
        rows = []
        for idx in range(4):
            rows.append(
                {
                    "rebalance_date": (pd.Timestamp("2026-01-31") + pd.DateOffset(months=idx)).date().isoformat(),
                    "rs_spy_3m": 4 - idx,
                    "h1_oversold_value_score": idx,
                    "forward_126d_excess": idx / 100.0,
                }
            )
        candidates = root / "candidates.csv"
        pd.DataFrame(rows).to_csv(candidates, index=False)
        payload = run(
            argparse.Namespace(
                inputs=[str(candidates)],
                state_history=str(states),
                output_dir=str(root / "out"),
                min_samples=10,
                material_ic_gap=0.01,
            )
        )
        assert payload["status"] == "completed", payload
        assert payload["proceed_to_r3_gate_pass"] is False, payload
        table = pd.read_csv(root / "out" / "ic_by_state_and_feature_family.csv")
        assert set(table["status"].astype(str)) == {"insufficient_sample"}


def main() -> int:
    test_state_conditional_ic_audit_is_gate_only()
    test_state_conditional_ic_audit_does_not_pass_r3_with_insufficient_samples()
    print("state_conditional_ic_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
