#!/usr/bin/env python3
"""Smoke test for repeated-leak self-correction router."""
from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.run_self_correction_router import run  # noqa: E402


def row(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "portfolios": {
            "concentrated": {
                "leak_year_tags": {
                    "2021": "structural_underinvestment_bull",
                    "2023": "structural_underinvestment_bull",
                }
            },
            "main": {"leak_year_tags": {}},
        },
    }


def test_self_correction_router_queues_repeated_concentrated_bull_leak() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger_dir = root / "ledger"
        ledger_dir.mkdir()
        (ledger_dir / "ledger.jsonl").write_text(
            json.dumps(row("a")) + "\n" + json.dumps(row("b")) + "\n",
            encoding="utf-8",
        )
        (ledger_dir / "latest_verdict.json").write_text(
            json.dumps({"dominant_open_leak": "concentrated:structural_underinvestment_bull"}),
            encoding="utf-8",
        )
        out = root / "router"
        queue = run(Namespace(ledger_dir=str(ledger_dir), output_dir=str(out), min_repeat=2))
        assert queue["production_mutation_allowed"] is False
        assert queue["repeat_confirmed"] is True
        assert len(queue["queued_experiments"]) == 4
        assert all(item["requires_user_approval"] is True for item in queue["queued_experiments"])
        assert (out / "router_queue.md").exists()


if __name__ == "__main__":
    test_self_correction_router_queues_repeated_concentrated_bull_leak()
    print("self_correction_router_smoke: PASS")
