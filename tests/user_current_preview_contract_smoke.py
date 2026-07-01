#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verify_user_current_preview_contract import run  # noqa: E402


class Args:
    pass


def _args(root: Path, out_name: str = "contract") -> Args:
    args = Args()
    args.latest_run = str(root)
    args.user_current_target = ""
    args.output_dir = str(root / out_name)
    args.weight_tolerance = 1e-6
    args.strict = False
    return args


def _write_targets(root: Path, *, preview_hash: str = "hash-a", preview_weight_delta: float = 0.0) -> None:
    (root / "user_current").mkdir(parents=True)
    rows = []
    for portfolio in ["main", "concentrated"]:
        rows.extend(
            [
                {
                    "portfolio": portfolio,
                    "ticker": "AAA",
                    "target_weight": 0.60,
                    "target_snapshot_hash": "hash-a",
                    "target_snapshot_semantics": "alphaops_vnext_operating_target",
                },
                {
                    "portfolio": portfolio,
                    "ticker": "CASH",
                    "target_weight": 0.40,
                    "target_snapshot_hash": "hash-a",
                    "target_snapshot_semantics": "alphaops_vnext_operating_target",
                },
            ]
        )
    pd.DataFrame(rows).to_csv(root / "user_current" / "02_target_weights.csv", index=False)
    for portfolio in ["main", "concentrated"]:
        out = root / "account_ledger_preview" / portfolio
        out.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "target_weight": 0.60 + preview_weight_delta,
                    "target_snapshot_hash": preview_hash,
                    "target_snapshot_semantics": "alphaops_vnext_operating_target",
                },
                {
                    "ticker": "CASH",
                    "target_weight": 0.40,
                    "target_snapshot_hash": preview_hash,
                    "target_snapshot_semantics": "alphaops_vnext_operating_target",
                },
            ]
        ).to_csv(out / "target_weights.csv", index=False)


def test_user_current_preview_contract_passes_matching_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_targets(root)
        payload = run(_args(root))
        assert payload["status"] == "pass", payload
        assert (root / "contract" / "summary.json").exists()


def test_user_current_preview_contract_blocks_hash_or_weight_mismatch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_targets(root, preview_hash="hash-b", preview_weight_delta=0.01)
        payload = run(_args(root, "contract_bad"))
        assert payload["status"] == "blocked"
        check_ids = {row["check_id"] for row in payload["issues"]}
        assert "main_target_snapshot_hash_mismatch" in check_ids
        assert "concentrated_target_weight_mismatch" in check_ids


def main() -> int:
    test_user_current_preview_contract_passes_matching_snapshot()
    test_user_current_preview_contract_blocks_hash_or_weight_mismatch()
    print("user_current_preview_contract_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
