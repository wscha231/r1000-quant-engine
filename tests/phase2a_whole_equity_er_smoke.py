from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "phase2a", ROOT / "tools" / "run_phase2a_whole_equity_er.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)

SESSION = "2026-09-18"
STAMP = "2026-09-18T21:35:00Z"


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract():
    return {
        "schema_version": "phase2a-whole-equity-er-contract-v1",
        "expected_return_family_id": MOD.EXPECTED_FAMILY_ID,
        "12m_policy": MOD.TWELVE_MONTH_BLOCKER,
    }


def cohort(ids=("US:A", "US:B", "US:ADR")):
    return {
        "status": "ADMITTED_RESEARCH_ONLY",
        "runtime_executed": True,
        "company_evaluator_executed": False,
        "decision_at": STAMP,
        "expected_session": SESSION,
        "evaluation_inventory": [
            {
                "security_id": sid,
                "status": "BLOCKED_COMPANY_EVALUATOR_RECEIPT_MISSING",
                "expected_return_1m": None,
                "expected_return_3m": None,
                "expected_return_6m": None,
                "expected_return_12m": None,
            }
            for sid in ids
        ],
        "data_queue_preview": {
            "items": [
                {"security_id": sid, "ticker": {"US:A": "AAA", "US:B": "BBB", "US:ADR": "ADR"}[sid]}
                for sid in ids
            ]
        },
    }


def registry():
    base = [
        {
            "security_id": "US:A",
            "issuer_id": "issuer:A",
            "ticker": "AAA",
            "identity_verified": True,
            "research_eligible": True,
            "available_at": STAMP,
            "instrument": "COMMON",
            "corporate_action_basis": "SPLIT_AND_DIVIDEND_ADJUSTED_TOTAL_RETURN",
            "corporate_action_verified": True,
        },
        {
            "security_id": "US:B",
            "issuer_id": "issuer:B",
            "ticker": "BBB",
            "identity_verified": True,
            "research_eligible": True,
            "available_at": STAMP,
            "instrument": "COMMON",
            "corporate_action_basis": "SPLIT_DIVIDEND_ADJUSTED_TOTAL_RETURN",
            "corporate_action_verified": True,
        },
        {
            "security_id": "US:ADR",
            "issuer_id": "issuer:ADR",
            "ticker": "ADR",
            "identity_verified": True,
            "research_eligible": True,
            "available_at": STAMP,
            "instrument": "ADR",
            "corporate_action_basis": "SPLIT_AND_DIVIDEND_ADJUSTED_TOTAL_RETURN",
            "corporate_action_verified": True,
            "adr_ratio": 5.0,
            "adr_share_basis_verified": True,
            "underlying_currency": "TWD",
        },
    ]
    return {"securities": base}


def proposal_rows(tickers=("AAA", "BBB", "ADR")):
    rows = []
    for i, ticker in enumerate(tickers, start=1):
        row = {"feature_date": SESSION, "ticker": ticker, "sector": "TECH", "research_only": "True"}
        for days, scale in ((21, 1.0), (63, 2.0), (126, 3.0)):
            absolute = 0.01 * i * scale
            benchmark_excess = 0.004 * i * scale
            row.update(
                {
                    f"expected_absolute_{days}d": absolute,
                    f"expected_benchmark_excess_{days}d": benchmark_excess,
                    f"expected_alpha_{days}d": 0.003 * i * scale,
                    f"downside_probability_{days}d": 0.2,
                    f"feature_coverage_{days}d": 1.0,
                    f"model_disagreement_{days}d": 0.01,
                }
            )
        rows.append(row)
    return rows


class Phase2A(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = {
            "contract": self.root / "phase2a_contract.json",
            "cohort": self.root / "cohort.json",
            "registry": self.root / "registry.json",
            "proposal": self.root / "proposal.csv",
            "summary": self.root / "summary.json",
            "manifest": self.root / "manifest.json",
            "er_contract": self.root / "er_contract.json",
            "output": self.root / "out.json",
        }
        write_json(self.paths["contract"], contract())
        write_json(self.paths["cohort"], cohort())
        write_json(self.paths["registry"], registry())
        self.paths["er_contract"].write_text('{"test":"existing-run287-contract"}\n', encoding="utf-8")
        write_json(
            self.paths["summary"],
            {
                "status": MOD.READY_CHALLENGER_STATUS,
                "family_id": MOD.EXPECTED_FAMILY_ID,
            },
        )
        self.write_proposal(proposal_rows())
        self.write_manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def write_proposal(self, rows):
        fields = list(rows[0])
        with self.paths["proposal"].open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def write_manifest(self):
        write_json(
            self.paths["manifest"],
            {
                "status": MOD.READY_CHALLENGER_STATUS,
                "historical_fit_executed": True,
                "contract_sha256": sha(self.paths["er_contract"]),
                "outputs": {
                    "latest_expected_return_proposal.csv": {
                        "sha256": sha(self.paths["proposal"]),
                        "bytes": self.paths["proposal"].stat().st_size,
                    }
                }
            },
        )
    def args(self):
        return argparse.Namespace(
            contract=str(self.paths["contract"]),
            cohort=str(self.paths["cohort"]),
            identity_registry=str(self.paths["registry"]),
            er_proposal=str(self.paths["proposal"]),
            er_summary=str(self.paths["summary"]),
            er_source_manifest=str(self.paths["manifest"]),
            er_contract=str(self.paths["er_contract"]),
            output=str(self.paths["output"]),
        )

    def test_full_verified_cohort_maps_existing_21_63_126_outputs(self):
        out = MOD.run(self.args())
        self.assertEqual(out["status"], MOD.OVERALL_READY)
        self.assertTrue(out["whole_equity_er_ready_1_3_6m"])
        self.assertEqual(out["requested_security_count"], 3)
        self.assertEqual(out["evaluated_security_count"], 3)
        row = out["rows"][0]
        self.assertAlmostEqual(row["expected_return_1m"], 0.01)
        self.assertAlmostEqual(row["expected_return_3m"], 0.02)
        self.assertAlmostEqual(row["expected_return_6m"], 0.03)
        self.assertAlmostEqual(row["benchmark_expected_return_1m"], 0.006)
        self.assertAlmostEqual(row["expected_alpha_6m"], 0.009)
        self.assertEqual(row["horizon_status"]["12m"], MOD.TWELVE_MONTH_BLOCKER)
        self.assertIsNone(row["expected_return_12m"])
        self.assertFalse(out["global_ranking_ready"])
        self.assertFalse(out["a5_execution_allowed"])

    def test_12m_is_never_synthesized_from_6m(self):
        out = MOD.run(self.args())
        for row in out["rows"]:
            self.assertIsNone(row["expected_return_12m"])
            self.assertIsNone(row["expected_alpha_12m"])
            self.assertIsNone(row["benchmark_expected_return_12m"])
            self.assertEqual(row["horizon_status"]["12m"], MOD.TWELVE_MONTH_BLOCKER)

    def test_partial_proposal_preserves_missing_security_and_blocks_readiness(self):
        self.write_proposal(proposal_rows(("AAA", "BBB")))
        self.write_manifest()
        out = MOD.run(self.args())
        self.assertEqual(out["status"], MOD.OVERALL_PARTIAL)
        self.assertFalse(out["whole_equity_er_ready_1_3_6m"])
        self.assertEqual(out["evaluated_security_count"], 2)
        missing = next(row for row in out["rows"] if row["ticker"] == "ADR")
        self.assertIn("expected_return_row_missing", missing["blockers"])
        self.assertIsNone(missing["expected_return_6m"])

    def test_corporate_action_basis_missing_fail_closes_row(self):
        value = registry()
        value["securities"][0].pop("corporate_action_basis")
        write_json(self.paths["registry"], value)
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "AAA")
        self.assertIn("corporate_action_basis_unverified", row["blockers"])
        self.assertIsNone(row["expected_return_1m"])
        self.assertFalse(out["whole_equity_er_ready_1_3_6m"])

    def test_adr_without_ratio_is_blocked(self):
        value = registry()
        value["securities"][2].pop("adr_ratio")
        write_json(self.paths["registry"], value)
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "ADR")
        self.assertIn("adr_share_basis_unverified", row["blockers"])
        self.assertIsNone(row["expected_return_3m"])

    def test_future_identity_availability_is_blocked(self):
        value = registry()
        value["securities"][1]["available_at"] = "2026-09-19T00:00:00Z"
        write_json(self.paths["registry"], value)
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "BBB")
        self.assertIn("future_identity_availability", row["blockers"])

    def test_duplicate_ticker_identity_fails_before_mapping(self):
        value = registry()
        value["securities"][1]["ticker"] = "AAA"
        write_json(self.paths["registry"], value)
        with self.assertRaisesRegex(ValueError, "ticker_not_one_to_one"):
            MOD.run(self.args())

    def test_manifest_must_bind_exact_proposal_bytes(self):
        with self.paths["proposal"].open("a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "er_proposal_hash_mismatch"):
            MOD.run(self.args())

    def test_stale_or_future_proposal_decision_is_rejected(self):
        rows = proposal_rows()
        rows[0]["feature_date"] = "2026-09-17"
        self.write_proposal(rows)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "proposal_stale_or_future_decision_date"):
            MOD.run(self.args())

    def test_forward_or_label_columns_cannot_enter_a3_packet(self):
        rows = proposal_rows()
        for row in rows:
            row["realized_absolute_63d"] = 0.9
        self.write_proposal(rows)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "proposal_contains_forward_or_label_columns"):
            MOD.run(self.args())

    def test_nonfinite_prediction_blocks_row_instead_of_defaulting(self):
        rows = proposal_rows()
        rows[0]["expected_absolute_63d"] = "NaN"
        self.write_proposal(rows)
        self.write_manifest()
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "AAA")
        self.assertIn("missing_or_nonfinite_expected_return_63d", row["blockers"])
        self.assertIsNone(row["expected_return_1m"])
        self.assertIsNone(row["expected_return_3m"])
        self.assertIsNone(row["expected_return_6m"])

    def test_artifact_hash_binds_payload_without_self_reference(self):
        out = MOD.run(self.args())
        digest = out.pop("artifact_sha256")
        self.assertEqual(digest, MOD.sha256_bytes(MOD.canonical_bytes(out)))


if __name__ == "__main__":
    unittest.main()
