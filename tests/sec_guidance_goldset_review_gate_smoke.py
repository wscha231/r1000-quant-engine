#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.evaluate_sec_guidance_goldset_reviews import evaluate  # noqa: E402


def write_fixture(root: Path) -> tuple[Path, Path, Path]:
    contract = json.loads(
        (REPO_ROOT / "docs/run287_sec_guidance_goldset_contract.json").read_text(encoding="utf-8")
    )
    contract["expected_filing_count"] = 4
    contract_path = root / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    packet = root / "packet"
    packet.mkdir()
    ids = [f"row-{idx}" for idx in range(4)]
    pd.DataFrame(
        {
            "review_row_id": ids,
            "ticker": ["A", "B", "C", "D"],
            "accession_number": [f"acc-{idx}" for idx in range(4)],
            "accepted_at": ["2024-01-01T00:00:00+00:00"] * 4,
        }
    ).to_csv(packet / "review_manifest.csv", index=False)

    def labels(reviewer: str, classes: list[str], precision: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "review_row_id": ids,
                "ticker": ["A", "B", "C", "D"],
                "accession_number": [f"acc-{idx}" for idx in range(4)],
                "reviewer_id": [reviewer] * 4,
                "filing_class": classes,
                "precision_label": precision,
                "exclusion_reason": [""] * 4,
                "semantic_event_id": [""] * 4,
                "republication_of_review_row_id": [""] * 4,
                "reviewed_at_utc": ["2026-07-14T00:00:00Z"] * 4,
                "notes": [""] * 4,
            }
        )

    labels(
        "reviewer_a",
        ["TRUE_GUIDANCE", "FALSE_POSITIVE", "NO_GUIDANCE", "NO_GUIDANCE"],
        ["TP", "FP", "TN", "TN"],
    ).to_csv(packet / "filing_labels_reviewer_a.csv", index=False)
    labels(
        "reviewer_b",
        ["TRUE_GUIDANCE", "TRUE_GUIDANCE", "NO_GUIDANCE", "NO_GUIDANCE"],
        ["TP", "TP", "TN", "TN"],
    ).to_csv(packet / "filing_labels_reviewer_b.csv", index=False)
    adjudication = root / "adjudication.csv"
    pd.DataFrame(
        [
            {
                "review_row_id": "row-1",
                "adjudicated_filing_class": "FALSE_POSITIVE",
                "adjudicated_precision_label": "FP",
                "adjudicator_id": "fixture",
                "adjudicated_at_utc": "2026-07-14T00:00:00Z",
                "rationale": "not eligible guidance",
            }
        ]
    ).to_csv(adjudication, index=False)
    return contract_path, packet, adjudication


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        contract, packet, adjudication = write_fixture(root)
        summary = evaluate(
            contract_path=contract,
            packet_dir=packet,
            adjudication_path=adjudication,
            output_dir=root / "output",
        )
        assert summary["status"] == "CLOSED_SOURCE_PRECISION_OR_RECALL_GATE", summary
        assert summary["reviewer_disagreement_count"] == 1
        assert summary["reviewer_agreement_rate"] == 0.75
        assert summary["adjudicated_metrics"]["tp"] == 1
        assert summary["adjudicated_metrics"]["fp"] == 1
        assert summary["adjudicated_metrics"]["precision"] == 0.5
        assert summary["precision_gate"]["passed"] is False
        assert summary["deterministic_parser_allowed"] is False
        assert summary["return_join_allowed"] is False
        assert summary["component_adjudication_status"] == "NOT_RUN_EARLY_STOP"

        pd.DataFrame(columns=pd.read_csv(adjudication).columns).to_csv(adjudication, index=False)
        try:
            evaluate(
                contract_path=contract,
                packet_dir=packet,
                adjudication_path=adjudication,
                output_dir=root / "blocked",
            )
        except ValueError as exc:
            assert "unresolved_or_extra_adjudication" in str(exc)
        else:
            raise AssertionError("an unresolved filing disagreement must block evaluation")

    print("sec_guidance_goldset_review_gate_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
