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

from tools.run_rs_horizon_ic_audit import run  # noqa: E402


def test_rs_horizon_ic_audit_keeps_forward_labels_audit_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rows = []
        for idx in range(30):
            rows.append(
                {
                    "portfolio": "concentrated" if idx % 2 else "main",
                    "rs_spy_1w": -idx,
                    "rs_spy_1m": -idx * 0.5,
                    "rs_spy_3m": idx,
                    "rs_spy_6m": idx * 0.8,
                    "rs_spy_12m": idx * 0.3,
                    "forward_126d_excess": idx / 100.0,
                }
            )
        source = root / "candidates.csv"
        pd.DataFrame(rows).to_csv(source, index=False)
        payload = run(argparse.Namespace(inputs=[str(source)], output_dir=str(root / "out"), min_samples=10))
        assert payload["status"] == "completed", payload
        assert payload["forward_return_is_audit_label_only"] is True
        assert payload["forward_labels_used_for_ranking"] is False
        assert payload["entry_side_short_horizon_demote_backlog"] is True
        by_horizon = pd.read_csv(root / "out" / "ic_by_horizon.csv")
        assert "rs_spy_3m" in set(by_horizon["horizon"])


def main() -> int:
    test_rs_horizon_ic_audit_keeps_forward_labels_audit_only()
    print("rs_horizon_ic_audit_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
