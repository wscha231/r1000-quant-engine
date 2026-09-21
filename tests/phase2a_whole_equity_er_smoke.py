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


def canonical_json_sha(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bridge_sha(value) -> str:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


SECURITIES_MEMBER = "outputs/theme_etf_source/securities/data.json"


def contract():
    return {
        "schema_version": "phase2a-whole-equity-er-contract-v1",
        "expected_return_family_id": MOD.EXPECTED_FAMILY_ID,
        "12m_policy": MOD.TWELVE_MONTH_BLOCKER,
    }


def cohort(registry_path: Path, ids=("US:A", "US:B", "US:ADR")):
    value = {
        "status": "ADMITTED_RESEARCH_ONLY",
        "runtime_executed": True,
        "company_evaluator_executed": False,
        "decision_at": STAMP,
        "expected_session": SESSION,
        "consumer_code_sha": "e" * 40,
        "contract_sha256": "f" * 64,
        "evidence": {
            SECURITIES_MEMBER: {
                "sha256": sha(registry_path),
                "bytes": registry_path.stat().st_size,
            }
        },
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
    value["bridge_sha256"] = bridge_sha(value)
    return value


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
        write_json(self.paths["registry"], registry())
        write_json(self.paths["cohort"], cohort(self.paths["registry"]))
        self.paths["er_contract"].write_text(
            '{\n  "schema_version": "synthetic-run287-contract",\n  "family_id": "future_expected_excess_return_multihorizon_v1",\n  "historical_gate": {"accepted_workflow_path": ".github/workflows/run287_u0_acceptance.yml"}\n}\n',
            encoding="utf-8",
        )
        self.original_expected_contract_sha = MOD.EXPECTED_ER_CONTRACT_SHA256
        MOD.EXPECTED_ER_CONTRACT_SHA256 = canonical_json_sha(self.paths["er_contract"])
        write_json(
            self.paths["summary"],
            {
                "schema_version": MOD.RUN287_SCHEMA_VERSION,
                "status": MOD.READY_CHALLENGER_STATUS,
                "family_id": MOD.EXPECTED_FAMILY_ID,
                "latest_decision_date": SESSION + "T00:00:00",
                "latest_candidate_count": 3,
                "historical_model_fit_executed": True,
                "historical_backtest_executed": False,
            },
        )
        self.write_proposal(proposal_rows())
        self.write_manifest()

    def tearDown(self):
        MOD.EXPECTED_ER_CONTRACT_SHA256 = self.original_expected_contract_sha
        self.tmp.cleanup()

    def write_registry(self, value, *, rebind=True):
        write_json(self.paths["registry"], value)
        if rebind:
            current = json.loads(self.paths["cohort"].read_text(encoding="utf-8"))
            current.pop("bridge_sha256", None)
            current["evidence"][SECURITIES_MEMBER] = {
                "sha256": sha(self.paths["registry"]),
                "bytes": self.paths["registry"].stat().st_size,
            }
            current["bridge_sha256"] = bridge_sha(current)
            write_json(self.paths["cohort"], current)

    def write_proposal(self, rows):
        fields = list(rows[0])
        with self.paths["proposal"].open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def write_manifest(self):
        with self.paths["proposal"].open("r", encoding="utf-8", newline="") as handle:
            candidate_count = sum(1 for _ in csv.DictReader(handle))
        summary = json.loads(self.paths["summary"].read_text(encoding="utf-8"))
        summary["latest_candidate_count"] = candidate_count
        write_json(self.paths["summary"], summary)
        write_json(
            self.paths["manifest"],
            {
                "schema_version": MOD.RUN287_SCHEMA_VERSION,
                "status": MOD.READY_CHALLENGER_STATUS,
                "created_at_utc": "2026-09-18T22:00:00Z",
                "git_commit_sha": "a" * 40,
                "historical_fit_executed": True,
                "historical_backtest_executed": False,
                "contract_sha256": canonical_json_sha(self.paths["er_contract"]),
                "inputs": {
                    "contract": {
                        "path": str(self.paths["er_contract"]),
                        "exists": True,
                        "bytes": self.paths["er_contract"].stat().st_size,
                        "sha256": sha(self.paths["er_contract"]),
                    },
                    "u0_canonical_artifact": {
                        "artifact_id": 123,
                        "workflow_run_id": 456,
                        "workflow_path": ".github/workflows/run287_u0_acceptance.yml",
                        "head_sha": "b" * 40,
                        "artifact_digest": "sha256:" + "c" * 64,
                    },
                    "feature_store": {
                        "path": "feature_store.parquet",
                        "exists": True,
                        "bytes": 12345,
                        "sha256": "d" * 64,
                    },
                },
                "outputs": {
                    "latest_expected_return_proposal.csv": {
                        "sha256": sha(self.paths["proposal"]),
                        "bytes": self.paths["proposal"].stat().st_size,
                    },
                    "summary.json": {
                        "sha256": sha(self.paths["summary"]),
                        "bytes": self.paths["summary"].stat().st_size,
                    },
                },
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
        self.assertEqual(out["partially_evaluated_security_count"], 0)
        row = out["rows"][0]
        self.assertAlmostEqual(row["expected_return_1m"], 0.01)
        self.assertAlmostEqual(row["expected_return_3m"], 0.02)
        self.assertAlmostEqual(row["expected_return_6m"], 0.03)
        self.assertAlmostEqual(row["benchmark_expected_return_1m"], 0.006)
        self.assertAlmostEqual(row["expected_alpha_6m"], 0.009)
        self.assertIsNone(row["downside_probability_1m"])
        self.assertAlmostEqual(row["raw_model_downside_probability_1m"], 0.2)
        self.assertEqual(out["downside_probability_status"], MOD.DOWNSIDE_CALIBRATION_BLOCKER)
        self.assertFalse(out["a3_quant_contract_ready"])
        self.assertEqual(out["expected_alpha_basis"], "GROSS_RESEARCH_NOT_AFTER_COSTS")
        self.assertEqual(row["horizon_status"]["12m"], MOD.TWELVE_MONTH_BLOCKER)
        self.assertIsNone(row["expected_return_12m"])
        self.assertFalse(out["global_ranking_ready"])
        self.assertFalse(out["a5_execution_allowed"])

    def test_uncalibrated_downside_is_null_while_raw_probability_is_diagnostic(self):
        out = MOD.run(self.args())
        for row in out["rows"]:
            self.assertIsNone(row["downside_probability_1m"])
            self.assertIsNone(row["downside_probability_3m"])
            self.assertIsNone(row["downside_probability_6m"])
            self.assertAlmostEqual(row["raw_model_downside_probability_1m"], 0.2)
            self.assertIn(MOD.DOWNSIDE_CALIBRATION_BLOCKER, row["blockers"])
        self.assertEqual(out["downside_probability_status"], MOD.DOWNSIDE_CALIBRATION_BLOCKER)

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
        self.write_registry(value)
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "AAA")
        self.assertIn("corporate_action_basis_unverified", row["blockers"])
        self.assertIsNone(row["expected_return_1m"])
        self.assertIsNone(row["expected_return_3m"])
        self.assertIsNone(row["expected_return_6m"])
        self.assertEqual(row["status"], MOD.ROW_BLOCKED)
        self.assertFalse(out["whole_equity_er_ready_1_3_6m"])

    def test_adr_without_ratio_is_blocked(self):
        value = registry()
        value["securities"][2].pop("adr_ratio")
        self.write_registry(value)
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "ADR")
        self.assertIn("adr_share_basis_unverified", row["blockers"])
        self.assertIsNone(row["expected_return_3m"])

    def test_future_identity_availability_is_blocked(self):
        value = registry()
        value["securities"][1]["available_at"] = "2026-09-19T00:00:00Z"
        self.write_registry(value)
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "BBB")
        self.assertIn("future_identity_availability", row["blockers"])

    def test_registry_bytes_must_match_authenticated_cohort_securities_member(self):
        value = registry()
        value["securities"][0]["corporate_action_verified"] = False
        write_json(self.paths["registry"], value)
        with self.assertRaisesRegex(ValueError, "cohort_registry_evidence_hash_mismatch"):
            MOD.run(self.args())

    def test_cohort_bridge_publication_hash_is_verified(self):
        value = json.loads(self.paths["cohort"].read_text(encoding="utf-8"))
        value["consumer_code_sha"] = "1" * 40
        write_json(self.paths["cohort"], value)
        with self.assertRaisesRegex(ValueError, "cohort_bridge_sha256_mismatch"):
            MOD.run(self.args())

    def test_duplicate_ticker_identity_fails_before_mapping(self):
        value = registry()
        value["securities"][1]["ticker"] = "AAA"
        self.write_registry(value)
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
        self.assertAlmostEqual(row["expected_return_1m"], 0.01)
        self.assertIsNone(row["expected_return_3m"])
        self.assertAlmostEqual(row["expected_return_6m"], 0.03)
        self.assertEqual(row["status"], MOD.ROW_PARTIAL)
        self.assertEqual(row["horizon_status"]["3m"], MOD.HORIZON_BLOCKED)
        self.assertEqual(out["partially_evaluated_security_count"], 1)
        self.assertFalse(out["whole_equity_er_ready_1_3_6m"])

    def test_one_horizon_failure_does_not_erase_other_validated_horizons(self):
        rows = proposal_rows()
        rows[1]["expected_alpha_21d"] = "NaN"
        self.write_proposal(rows)
        self.write_manifest()
        out = MOD.run(self.args())
        row = next(row for row in out["rows"] if row["ticker"] == "BBB")
        self.assertIsNone(row["expected_return_1m"])
        self.assertAlmostEqual(row["expected_return_3m"], 0.04)
        self.assertAlmostEqual(row["expected_return_6m"], 0.06)
        self.assertEqual(row["status"], MOD.ROW_PARTIAL)
        self.assertEqual(row["horizon_status"]["1m"], MOD.HORIZON_BLOCKED)

    def test_official_expected_return_contract_hash_constant_is_pinned(self):
        self.assertEqual(
            self.original_expected_contract_sha,
            "ef61acafc2c42b86d75d85becea816a4bca8e05fbbc392e77fa92b075c728b63",
        )

    def test_contract_manifest_uses_canonical_json_hash_not_raw_file_hash(self):
        self.assertNotEqual(sha(self.paths["er_contract"]), canonical_json_sha(self.paths["er_contract"]))
        out = MOD.run(self.args())
        self.assertEqual(out["status"], MOD.OVERALL_READY)

    def test_producer_timestamp_decision_date_normalizes_to_session(self):
        summary = json.loads(self.paths["summary"].read_text(encoding="utf-8"))
        summary["latest_decision_date"] = SESSION + "T00:00:00"
        write_json(self.paths["summary"], summary)
        self.write_manifest()
        out = MOD.run(self.args())
        self.assertEqual(out["status"], MOD.OVERALL_READY)

    def test_u0_workflow_path_must_match_pinned_contract(self):
        manifest = json.loads(self.paths["manifest"].read_text(encoding="utf-8"))
        manifest["inputs"]["u0_canonical_artifact"]["workflow_path"] = ".github/workflows/fake.yml"
        write_json(self.paths["manifest"], manifest)
        with self.assertRaisesRegex(ValueError, "er_manifest_u0_workflow_path_mismatch"):
            MOD.run(self.args())

    def test_raw_contract_input_fingerprint_is_bound_separately(self):
        manifest = json.loads(self.paths["manifest"].read_text(encoding="utf-8"))
        manifest["inputs"]["contract"]["sha256"] = "0" * 64
        write_json(self.paths["manifest"], manifest)
        with self.assertRaisesRegex(ValueError, "er_manifest_contract_input_hash_mismatch"):
            MOD.run(self.args())

    def test_summary_bytes_must_match_source_manifest(self):
        summary = json.loads(self.paths["summary"].read_text(encoding="utf-8"))
        summary["latest_candidate_count"] = 999
        write_json(self.paths["summary"], summary)
        with self.assertRaisesRegex(ValueError, "er_summary_hash_mismatch"):
            MOD.run(self.args())

    def test_manifest_requires_canonical_u0_artifact_identity(self):
        manifest = json.loads(self.paths["manifest"].read_text(encoding="utf-8"))
        manifest["inputs"].pop("u0_canonical_artifact")
        write_json(self.paths["manifest"], manifest)
        with self.assertRaisesRegex(ValueError, "er_manifest_u0_canonical_artifact_missing"):
            MOD.run(self.args())

    def test_artifact_hash_binds_payload_without_self_reference(self):
        out = MOD.run(self.args())
        digest = out.pop("artifact_sha256")
        self.assertEqual(digest, MOD.sha256_bytes(MOD.canonical_bytes(out)))


if __name__ == "__main__":
    unittest.main()
