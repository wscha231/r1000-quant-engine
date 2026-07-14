#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_exact_packet_input_registry import DYNAMIC_OUTPUTS
from tools.build_run287_exact_packet_source_bundle import (
    BLOCKED_STATUS,
    READY_STATUS,
    REUSED_STATUS,
    SKIPPED_STATUS,
    build_from_records,
)
from tools.run_run287_exact_packet_producer import sha256_file


DATE = "2026-07-13"
DYNAMIC = {
    "crisis_manifest": ("valuation_price_cutoff_date", "READY_CURRENT_CRISIS_STATE_NONSELECTING"),
    "decision_manifest": ("valuation_price_cutoff_date", "READY_COMPLETE_CURRENT_DECISION_FRAME"),
    "macro_manifest": ("valuation_close_date", "READY_CONSERVATIVE_MACRO_SIDECAR"),
    "price_manifest": ("session_date", "READY_RESEARCH_SCORED_LATEST"),
    "score_stack_manifest": (
        "valuation_price_cutoff_date",
        "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
    ),
    "soxx_manifest": ("valuation_price_cutoff_date", "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING"),
}
FIXED = (
    "concentrated_prior_book",
    "main_prior_book",
    "pinned_import_manifest",
    "price_map_manifest",
    "selector_contract_manifest",
    "target_generation_manifest",
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fixture(root: Path) -> tuple[Path, dict[str, Path]]:
    records: dict[str, Path] = {}
    for label, (date_field, status) in DYNAMIC.items():
        directory = root / label
        outputs = {}
        for output_name in DYNAMIC_OUTPUTS[label]:
            output = directory / output_name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"{label}:{output_name}\n", encoding="utf-8")
            outputs[output_name] = {
                "path": str(output),
                "sha256": sha256_file(output),
            }
        manifest = directory / "manifest.json"
        write_json(
            manifest,
            {
                "status": status,
                date_field: DATE,
                "fullrun_executed": False,
                "backtest_executed": False,
                "target_books_mutated": False,
                "outputs": outputs,
            },
        )
        records[label] = manifest
    fixed_hashes = {}
    for label in FIXED:
        path = root / "fixed" / f"{label}.dat"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{label}\n", encoding="utf-8")
        records[label] = path
        fixed_hashes[label] = sha256_file(path)
    contract = root / "contract.json"
    write_json(
        contract,
        {
            "schema_version": "run287-exact-packet-producer-contract-v1",
            "input_registry_schema_version": "run287-exact-packet-input-registry-v1",
            "required_dynamic_inputs": {
                label: {"date_field": date_field, "status": status}
                for label, (date_field, status) in DYNAMIC.items()
            },
            "required_fixed_inputs": fixed_hashes,
        },
    )
    return contract, records


class SourceBundleSmoke(unittest.TestCase):
    def test_ready_exact_reuse_missing_and_changed_date_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract, records = fixture(root)
            output = root / "bundle"
            first = build_from_records(
                valuation_date=DATE,
                input_records=records,
                producer_contract=contract,
                output_dir=output,
            )
            self.assertEqual(first["status"], READY_STATUS)
            bundle = json.loads((output / "source_bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(set(bundle["inputs"]), set(records))
            self.assertTrue(all(record.get("sha256") for record in bundle["inputs"].values()))

            reused = build_from_records(
                valuation_date=DATE,
                input_records=records,
                producer_contract=contract,
                output_dir=output,
            )
            self.assertEqual(reused["status"], REUSED_STATUS)

            missing = dict(records)
            missing["soxx_manifest"] = root / "missing.json"
            skipped = build_from_records(
                valuation_date=DATE,
                input_records=missing,
                producer_contract=contract,
                output_dir=root / "missing_bundle",
            )
            self.assertEqual(skipped["status"], SKIPPED_STATUS)

            decision = json.loads(records["decision_manifest"].read_text(encoding="utf-8"))
            decision["valuation_price_cutoff_date"] = "2026-07-14"
            write_json(records["decision_manifest"], decision)
            blocked = build_from_records(
                valuation_date=DATE,
                input_records=records,
                producer_contract=contract,
                output_dir=output,
            )
            self.assertEqual(blocked["status"], BLOCKED_STATUS)
            self.assertIn("input_date:decision_manifest", blocked["contract_failures"])

            decision["valuation_price_cutoff_date"] = DATE
            decision["diagnostic_note"] = "same-date input changed"
            write_json(records["decision_manifest"], decision)
            collision = build_from_records(
                valuation_date=DATE,
                input_records=records,
                producer_contract=contract,
                output_dir=output,
            )
            self.assertEqual(collision["status"], BLOCKED_STATUS)
            self.assertIn("immutable_date_collision", collision["contract_failures"])


if __name__ == "__main__":
    unittest.main()
