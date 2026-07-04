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


def test_chameleon_policy_never_emits_executable_orders_or_public_claims() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        summary = root / "r1_summary.json"
        summary.write_text(
            json.dumps({"current_state": "BULL", "bear_warning_score": 1, "confidence": 0.9}),
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
        assert payload["all_actions_review_only"] is True, payload
        assert payload["executable_order_allowed"] is False, payload
        assert payload["production_policy_mutation_allowed"] is False, payload
        assert payload["live_trading_allowed"] is False, payload
        assert payload["public_display_allowed"] is False, payload
        assert payload["current_holdings_are_not_forward_promise"] is True, payload
        assert not actions["executable_order_allowed"].astype(bool).any()
        assert not actions["production_policy_mutation_allowed"].astype(bool).any()
        assert not actions["live_trading_allowed"].astype(bool).any()


def main() -> int:
    test_chameleon_policy_never_emits_executable_orders_or_public_claims()
    print("chameleon_policy_no_orders_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
