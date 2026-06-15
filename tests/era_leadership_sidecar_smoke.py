#!/usr/bin/env python3
"""Smoke test for era leadership diagnostic sidecar."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_era_leadership_sidecar import run  # noqa: E402


def test_era_leadership_sidecar_outputs_ic_and_leaders() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "scored.csv"
        rows = []
        for date in ["2019-06-30", "2022-06-30", "2024-06-30", "2025-06-30"]:
            for idx, ticker in enumerate(["AAA", "BBB", "CCC", "DDD"]):
                rows.append(
                    {
                        "date": date,
                        "ticker": ticker,
                        "alphaops_vnext_score": idx + 1,
                        "theme_leadership_score": 4 - idx,
                        "forward_return_63d": (idx + 1) / 100.0,
                        "weight": 0.05 * (idx + 1),
                        "regime_state": "bull" if date != "2022-06-30" else "bear",
                    }
                )
        pd.DataFrame(rows).to_csv(source, index=False)
        out = root / "era"
        summary = run(Namespace(latest_run=str(root), input_csv=str(source), output_dir=str(out)))
        assert summary["status"] == "completed"
        assert summary["production_activation_allowed"] is False
        assert summary["feature_count"] >= 2
        assert not pd.read_csv(out / "era_feature_ic.csv").empty
        assert not pd.read_csv(out / "era_leaders.csv").empty
        saved = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert saved["production_activation_allowed"] is False


if __name__ == "__main__":
    test_era_leadership_sidecar_outputs_ic_and_leaders()
    print("era_leadership_sidecar_smoke: PASS")
