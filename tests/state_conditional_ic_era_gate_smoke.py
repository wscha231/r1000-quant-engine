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


def test_large_ic_cannot_authorize_r3_with_one_era() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        states = root / "state_history.csv"
        pd.DataFrame([{"date": "2026-01-01", "state": "CORRECTION"}]).to_csv(states, index=False)
        rows = []
        for idx in range(24):
            rows.append(
                {
                    "rebalance_date": (pd.Timestamp("2026-01-31") + pd.DateOffset(days=idx * 7)).date().isoformat(),
                    "rs_spy_3m": 24 - idx,
                    "h1_oversold_value_score": idx,
                    "profitability_inflection_score": idx,
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
                min_samples=5,
                material_ic_gap=0.01,
                r3_min_samples=10,
                r3_min_eras=2,
                r3_min_state_months=2,
                oos_start="2026-04-01",
            )
        )
        table = pd.read_csv(root / "out" / "ic_by_state_and_feature_family.csv")
        assert payload["status"] == "completed", payload
        assert payload["r3_authorized"] is False, payload
        assert payload["proceed_to_r3_gate_pass"] is False, payload
        assert table["era_count"].max() == 1
        assert not table["r3_row_eligible"].astype(bool).any()


def main() -> int:
    test_large_ic_cannot_authorize_r3_with_one_era()
    print("state_conditional_ic_era_gate_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
