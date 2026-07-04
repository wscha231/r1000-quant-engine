#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_chameleon_policy_audit import run  # noqa: E402


def test_data_insufficient_outputs_data_review_only_without_reserve_guidance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        summary = root / "r1_summary.json"
        summary.write_text(
            json.dumps({"current_state": "DATA_INSUFFICIENT", "bear_warning_score": 5, "confidence": 0.3}),
            encoding="utf-8",
        )
        payload = run(
            argparse.Namespace(
                regime_summary=str(summary),
                state_history=str(root / "missing.csv"),
                state="",
                shock_panel="",
                output_dir=str(root / "out"),
            )
        )
        actions = pd.read_csv(root / "out" / "recommended_actions.csv")
        labels = set(actions["action_label"].astype(str))
        details = " ".join(actions["action_detail"].astype(str).tolist()).lower()
        assert payload["current_state"] == "DATA_INSUFFICIENT", payload
        assert payload["data_insufficient_no_allocation_guidance"] is True, payload
        assert "data_review_required" in labels
        assert "cash/t-bill" not in details
        assert "reserve" not in details
        assert not actions["executable_order_allowed"].astype(bool).any()


def main() -> int:
    test_data_insufficient_outputs_data_review_only_without_reserve_guidance()
    print("chameleon_policy_data_insufficient_no_allocation_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
