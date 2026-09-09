"""Offline partial-quality replay, not the H1 admission/portfolio CLI.

Run only from an inspected source tree with python -I. This bounded helper never
fetches data or writes account/operating artifacts. Its source hashes describe
executed files, not a secure Git verifier or a successful market-data admission.
The output directory must not already exist. Inspect input review receipts before
use: they are caller-supplied judgments, not authenticated independent approvals.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

if not sys.flags.isolated:
    raise SystemExit("Use python -I from an inspected checkout")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.research_decision_v1.data import canonical, digest
from tools.research_decision_v1.quality import AXES, SECURITY
from tools.research_decision_v1.quality_bridge import evaluate_with_quality


def validated_security_id(record):
    sid = record.get("security_id") if isinstance(record, dict) else None
    if not isinstance(sid, str) or SECURITY.fullmatch(sid) is None:
        raise ValueError("invalid_pilot_security_id")
    return sid


def expand_record(record, stamp):
    """Expand reviewed partial capture definitions, retaining unverified axes."""
    sid = validated_security_id(record)
    corpus, claims, source_definitions = {}, [], {}
    for row in record["captured_claims"]:
        source = row["source"]
        source_id = source["source_id"]
        if source_id in source_definitions and source_definitions[source_id] != source:
            raise ValueError("conflicting_pilot_source_id")
        source_definitions[source_id] = copy.deepcopy(source)
        text = source["captured_text"]
        sh = hashlib.sha256(text.encode()).hexdigest()
        corpus[source["source_id"]] = {**source, "capture_scope": "excerpt", "content_sha256": sh,
            "published_at": None, "available_from": stamp, "first_seen_at": stamp,
            "ingested_at": stamp, "supersedes_source_id": None}
        claims.append({"claim_id": row["claim_id"], "axis": row["axis"], "segment": row["segment"],
            "kind": row["kind"], "statement": row["statement"], "required": False,
            "verdict": "supported", "impact": row["impact"], "severity": "ordinary",
            "rationale": row["rationale"], "strongest_bear_case": row["strongest_bear_case"],
            "invalidation_condition": row["invalidation_condition"], "review_due_at": record["review_due_at"],
            "evidence": [{"source_id": source["source_id"], "relation": "support", "role": row["role"],
                          "quote": row["quote"], "locator": row["locator"], "content_sha256": sh}]})
    # The record keeps all seven predeclared open_questions. Captured claims are
    # optional factual observations, not substitutes for the still-open core axes.
    # assess_quality treats absent required axis evidence as UNVERIFIED.
    if set(record["open_questions"]) != set(AXES):
        raise ValueError("seven_axis_open_question_inventory_required")
    packet = {"schema_version": "research-quality-input-v1", "security_id": sid,
              "data_kind": "REAL", "created_at": stamp, "claims": claims,
              "bindings": copy.deepcopy(record["bindings"])}
    market = sid.split(":")[0]
    security = {"security_id": sid, "market": market, "currency": "USD" if market == "US" else "KRW",
        "discovery": None, "blocks": {}, "blockers": ["price:not_materialized_in_quality_pilot",
        "financials:ttm_not_reconciled", "risk:not_materialized_in_quality_pilot",
        "thesis:complete_business_review_pending", "scenario:no_12m_underwriting"]}
    return packet, corpus, security


def execute(document):
    if not isinstance(document, dict) or document.get("data_kind") != "REAL" or document.get("schema_version") != "quality-capture-pilot-v1":
        raise ValueError("pilot_input_schema")
    records = document.get("records")
    if not isinstance(records, list) or not 0 < len(records) <= 128:
        raise ValueError("pilot_records_required")
    identities = [validated_security_id(record) for record in records]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate_pilot_security_id")
    result = []
    for record in records:
        packet, corpus, security = expand_record(record, document["observed_at"])
        # Empty config is deliberate: the old evaluator must return BLOCKED before
        # any valuation math. No synthetic price/config is inserted into REAL data.
        row = evaluate_with_quality(security, {}, document["cutoff"], packet=packet,
            corpus=corpus, receipt=record["review_receipt"], data_kind="REAL")
        if row["valuation"]["valuation_ready"] or row["portfolio_proposal_ready"] or row["orders_allowed"]:
            raise ValueError("partial_pilot_must_not_become_investment_ready")
        result.append(row)
    return {"schema_version": "partial-quality-pilot-result-v1", "data_kind": "REAL",
        "decision_cutoff": document["cutoff"], "source_input_hash": digest(document),
        "rows": sorted(result, key=lambda row: row["security_id"]),
        "h1_market_admission_executed": False, "portfolio_proposal_ready": False,
        "orders_allowed": False, "oos_validated": False,
        "boundary": "Captured excerpt matching and partial model review; not full-document authentication or full company research."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if re.fullmatch("[0-9a-f]{40}", args.source_sha) is None:
        raise ValueError("source_sha_format")
    document = json.loads(args.input.read_text(encoding="utf-8"))
    first, second = execute(document), execute(copy.deepcopy(document))
    if canonical(first) != canonical(second):
        raise ValueError("nondeterministic_pilot")
    artifacts = {}
    for row in first["rows"]:
        validated_security_id(row)  # Defence in depth before deriving any path.
        artifacts[row["security_id"].replace(":", "_") + "/quality_assessment.json"] = row["quality"]
        artifacts[row["security_id"].replace(":", "_") + "/quality_valuation_bridge.json"] = row
    paths = ["tools/research_decision_v1/" + name for name in
             ("data.py", "valuation.py", "quality.py", "quality_bridge.py", "quality_index.py")]
    paths.append("research/decision_v1/run_quality_pilot.py")
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    file_hashes = {}
    for name, value in artifacts.items():
        dest = args.output_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = (canonical(value) + "\n").encode("utf-8")
        with dest.open("xb") as handle:
            handle.write(data)
        file_hashes[name] = hashlib.sha256(data).hexdigest()
    manifest = {"schema_version": "partial-quality-execution-v1", "data_kind": "REAL",
        "status": "blocked", "cutoff": document["cutoff"], "source_sha": args.source_sha,
        "source_sha_is_caller_label": True, "source_file_sha256": hashes,
        "input_hash": digest(document), "identical_repeat_results": True,
        "artifacts": file_hashes, "h1_market_admission_executed": False,
        "portfolio_proposal_ready": False, "oos_validated": False, "orders_allowed": False}
    (args.output_dir / "execution_manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    print(json.dumps({"status": "EXECUTED_PARTIAL_QUALITY_INVESTMENT_BLOCKED",
        "matched_claims": {r["security_id"]: r["quality"]["source_matched_claims"] for r in first["rows"]},
        "reviewed_claims": {r["security_id"]: r["quality"]["reviewed_claims"] for r in first["rows"]},
        "identical_repeat_results": True, "orders_allowed": False}))
    return 2  # Expected incomplete-investment result; not an operating failure.


if __name__ == "__main__":
    raise SystemExit(main())
