#!/usr/bin/env python3
"""Evaluate blind SEC guidance reviews and stop before downstream tuning.

This tool operates on source-only labels. It does not inspect prices, returns,
portfolio state, or parser output. Every filing-level reviewer disagreement
must have one explicit adjudication row. If a mandatory gate fails, downstream
schema adjudication and parser work remain closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = "docs/run287_sec_guidance_goldset_contract.json"
DEFAULT_PACKET = "outputs/run287_sec_guidance_goldset_packet_20260714"
DEFAULT_ADJUDICATION = "docs/run287_sec_guidance_goldset_adjudication.csv"
DEFAULT_OUTPUT = "outputs/run287_sec_guidance_goldset_review_gate_20260714"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def metric(labels: pd.DataFrame) -> dict[str, Any]:
    counts = labels["precision_label"].value_counts().to_dict()
    tp = int(counts.get("TP", 0))
    fp = int(counts.get("FP", 0))
    tn = int(counts.get("TN", 0))
    fn = int(counts.get("FN", 0))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "unlabeled_precision_count": int((labels["precision_label"] == "").sum()),
        "precision": precision,
        "recall": recall,
    }


def validate_labels(
    labels: pd.DataFrame,
    *,
    reviewer_id: str,
    manifest_ids: set[str],
    contract: dict[str, Any],
) -> None:
    required = {
        "review_row_id",
        "reviewer_id",
        "filing_class",
        "precision_label",
        "reviewed_at_utc",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError(f"BLOCKED_REVIEW_GATE:missing_columns:{reviewer_id}:{sorted(missing)}")
    if len(labels) != len(manifest_ids) or set(labels["review_row_id"]) != manifest_ids:
        raise ValueError(f"BLOCKED_REVIEW_GATE:manifest_id_mismatch:{reviewer_id}")
    if labels["review_row_id"].duplicated().any():
        raise ValueError(f"BLOCKED_REVIEW_GATE:duplicate_ids:{reviewer_id}")
    if set(labels["reviewer_id"]) != {reviewer_id}:
        raise ValueError(f"BLOCKED_REVIEW_GATE:reviewer_id_mismatch:{reviewer_id}")
    allowed_classes = set(contract["filing_class_values"])
    allowed_precision = set(contract["precision_label_values"]) | {""}
    if not set(labels["filing_class"]).issubset(allowed_classes):
        raise ValueError(f"BLOCKED_REVIEW_GATE:invalid_class:{reviewer_id}")
    if not set(labels["precision_label"]).issubset(allowed_precision):
        raise ValueError(f"BLOCKED_REVIEW_GATE:invalid_precision:{reviewer_id}")
    if (labels["reviewed_at_utc"] == "").any():
        raise ValueError(f"BLOCKED_REVIEW_GATE:missing_review_time:{reviewer_id}")
    expected = {
        "TRUE_GUIDANCE": {"TP", "FN"},
        "FALSE_POSITIVE": {"FP"},
        "NO_GUIDANCE": {"TN"},
        "UNREADABLE": {""},
    }
    invalid = labels.apply(
        lambda row: row["precision_label"] not in expected[row["filing_class"]], axis=1
    )
    if invalid.any():
        raise ValueError(f"BLOCKED_REVIEW_GATE:class_precision_mismatch:{reviewer_id}")


def evaluate(
    *,
    contract_path: str | Path,
    packet_dir: str | Path,
    adjudication_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    contract_file = repo_path(contract_path)
    packet = repo_path(packet_dir)
    adjudication_file = repo_path(adjudication_path)
    output = repo_path(output_dir)
    contract = read_json(contract_file)
    manifest_path = packet / "review_manifest.csv"
    manifest = read_csv(manifest_path)
    expected_count = int(contract["expected_filing_count"])
    if len(manifest) != expected_count or manifest["review_row_id"].duplicated().any():
        raise ValueError("BLOCKED_REVIEW_GATE:manifest_integrity")
    manifest_ids = set(manifest["review_row_id"])

    reviewer_frames: dict[str, pd.DataFrame] = {}
    reviewer_hashes: dict[str, str] = {}
    for reviewer_id in contract["reviewer_ids"]:
        path = packet / f"filing_labels_{reviewer_id}.csv"
        frame = read_csv(path)
        validate_labels(
            frame,
            reviewer_id=reviewer_id,
            manifest_ids=manifest_ids,
            contract=contract,
        )
        reviewer_frames[reviewer_id] = frame.set_index("review_row_id", drop=False)
        reviewer_hashes[f"filing_labels_{reviewer_id}_sha256"] = sha256_file(path)

    reviewer_a, reviewer_b = contract["reviewer_ids"]
    a = reviewer_frames[reviewer_a]
    b = reviewer_frames[reviewer_b]
    disagreement_ids = sorted(
        review_id
        for review_id in manifest_ids
        if a.at[review_id, "filing_class"] != b.at[review_id, "filing_class"]
        or a.at[review_id, "precision_label"] != b.at[review_id, "precision_label"]
    )
    adjudications = read_csv(adjudication_file)
    required_adj = {
        "review_row_id",
        "adjudicated_filing_class",
        "adjudicated_precision_label",
        "adjudicator_id",
        "adjudicated_at_utc",
        "rationale",
    }
    if required_adj - set(adjudications.columns):
        raise ValueError("BLOCKED_REVIEW_GATE:adjudication_columns")
    if adjudications["review_row_id"].duplicated().any():
        raise ValueError("BLOCKED_REVIEW_GATE:duplicate_adjudication")
    if set(adjudications["review_row_id"]) != set(disagreement_ids):
        raise ValueError("BLOCKED_REVIEW_GATE:unresolved_or_extra_adjudication")
    if (adjudications[["adjudicator_id", "adjudicated_at_utc", "rationale"]].eq("").any(axis=1)).any():
        raise ValueError("BLOCKED_REVIEW_GATE:incomplete_adjudication")
    adj = adjudications.set_index("review_row_id", drop=False)

    final_rows: list[dict[str, str]] = []
    for _, source in manifest.sort_values(["ticker", "accepted_at", "accession_number"]).iterrows():
        review_id = source["review_row_id"]
        if review_id in adj.index:
            filing_class = adj.at[review_id, "adjudicated_filing_class"]
            precision_label = adj.at[review_id, "adjudicated_precision_label"]
            provenance = "ADJUDICATED"
        else:
            filing_class = a.at[review_id, "filing_class"]
            precision_label = a.at[review_id, "precision_label"]
            provenance = "REVIEWER_AGREEMENT"
        final_rows.append(
            {
                "review_row_id": review_id,
                "ticker": source["ticker"],
                "accession_number": source["accession_number"],
                "filing_class": filing_class,
                "precision_label": precision_label,
                "label_provenance": provenance,
            }
        )
    final = pd.DataFrame(final_rows)
    validate_labels(
        final.assign(reviewer_id="adjudicated", reviewed_at_utc="frozen"),
        reviewer_id="adjudicated",
        manifest_ids=manifest_ids,
        contract=contract,
    )

    reviewer_metrics = {reviewer_id: metric(frame) for reviewer_id, frame in reviewer_frames.items()}
    final_metric = metric(final)
    gates = contract["promotion_gates"]
    precision_pass = final_metric["precision"] is not None and final_metric["precision"] >= float(gates["minimum_precision"])
    recall_pass = final_metric["recall"] is not None and final_metric["recall"] >= float(gates["minimum_recall"])
    source_pass = bool(precision_pass and recall_pass)
    status = "READY_FOR_COMPONENT_ADJUDICATION" if source_pass else "CLOSED_SOURCE_PRECISION_OR_RECALL_GATE"

    output.mkdir(parents=True, exist_ok=True)
    final_path = output / "adjudicated_filing_labels.csv"
    disagreement_path = output / "filing_disagreements.csv"
    final.to_csv(final_path, index=False)
    manifest[manifest["review_row_id"].isin(disagreement_ids)].merge(
        a[["review_row_id", "filing_class", "precision_label"]].reset_index(drop=True).rename(
            columns={"filing_class": "reviewer_a_class", "precision_label": "reviewer_a_precision"}
        ),
        on="review_row_id",
    ).merge(
        b[["review_row_id", "filing_class", "precision_label"]].reset_index(drop=True).rename(
            columns={"filing_class": "reviewer_b_class", "precision_label": "reviewer_b_precision"}
        ),
        on="review_row_id",
    ).merge(adjudications, on="review_row_id").to_csv(disagreement_path, index=False)

    summary = {
        "schema_version": "run287-sec-guidance-goldset-review-gate-v1",
        "status": status,
        "filing_count": int(len(final)),
        "reviewer_agreement_count": int(len(final) - len(disagreement_ids)),
        "reviewer_disagreement_count": int(len(disagreement_ids)),
        "reviewer_agreement_rate": (len(final) - len(disagreement_ids)) / len(final),
        "reviewer_metrics": reviewer_metrics,
        "adjudicated_metrics": final_metric,
        "adjudicated_class_counts": final["filing_class"].value_counts().to_dict(),
        "precision_gate": {"minimum": float(gates["minimum_precision"]), "passed": precision_pass},
        "recall_gate": {"minimum": float(gates["minimum_recall"]), "passed": recall_pass},
        "component_adjudication_status": "PENDING" if source_pass else "NOT_RUN_EARLY_STOP",
        "schema_completeness": None,
        "deterministic_parser_allowed": source_pass,
        "active_45_name_archive_allowed": False,
        "return_join_allowed": False,
        "portfolio_ab_allowed": False,
        "portfolio_mutation_allowed": False,
        "fullrun_allowed": False,
        "production_allowed": False,
        "live_trading_allowed": False,
        "input_hashes": {
            "contract_sha256": sha256_file(contract_file),
            "review_manifest_sha256": sha256_file(manifest_path),
            "adjudication_sha256": sha256_file(adjudication_file),
            **reviewer_hashes,
        },
        "output_hashes": {
            "adjudicated_filing_labels_sha256": sha256_file(final_path),
            "filing_disagreements_sha256": sha256_file(disagreement_path),
        },
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = [
        "# SEC guidance gold-set review gate",
        "",
        f"- status: `{status}`",
        f"- agreement: `{summary['reviewer_agreement_count']}/{summary['filing_count']}`",
        f"- adjudicated TP/FP/TN/FN: `{final_metric['tp']}/{final_metric['fp']}/{final_metric['tn']}/{final_metric['fn']}`",
        f"- precision: `{final_metric['precision']:.6f}` (minimum `{gates['minimum_precision']}`)",
        f"- recall: `{final_metric['recall']:.6f}` (minimum `{gates['minimum_recall']}`)",
        "",
        "No returns or portfolio outcomes were used. A failed mandatory source gate closes parser and archive expansion.",
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--packet-dir", default=DEFAULT_PACKET)
    parser.add_argument("--adjudication", default=DEFAULT_ADJUDICATION)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = evaluate(
        contract_path=args.contract,
        packet_dir=args.packet_dir,
        adjudication_path=args.adjudication,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
