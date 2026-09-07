#!/usr/bin/env python3
"""One-shot RESEARCH_ONLY consumer of explicit market exports."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.research_decision_v1.data import digest
from tools.research_decision_v1.engine import run_decisions
from tools.research_decision_v1.io import immutable_bytes, immutable_json, read_json, research_root, source_code_hash


def render_report(decision):
    p = decision["portfolio_proposal"]
    lines = ["# Research decision V1", "", f"Data kind: {decision['data_kind']}; cutoff: {decision['decision_cutoff']}",
             f"Mode: {decision['mode']}; orders_allowed=false", "", "Subjective scenarios; OOS and MDD validation incomplete.", "",
             "| Security | Investment rank | Expected total return | Action | Weight | Reason |",
             "|---|---:|---:|---|---:|---|"]
    actions = {r["security_id"]: r for r in p["rows"]}
    for r in decision["ranking"]:
        a = actions[r["security_id"]]
        expected = f"{r['expected_total_return']:.2%}" if r["expected_total_return"] is not None else "N/A"
        weight = f"{a['target_weight']:.2%}" if a["target_weight"] is not None else "N/A"
        reason = "; ".join(a["reasons"]).replace("|", "/").replace("\n", " ")
        lines.append(f"| {r['security_id']} | {r['investment_rank'] or 'N/A'} | {expected} | {a['action']} | {weight} | {reason} |")
    if p["cash_weight"] is not None: lines += ["", f"Cash / unallocated capital: {p['cash_weight']:.2%}."]
    lines += ["", "Readiness: `"+json.dumps(decision["readiness"], sort_keys=True)+"`", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-export", action="append", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--config", default=str(ROOT / "docs/research_decision_v1_config.json"))
    parser.add_argument("--previous")
    args = parser.parse_args()
    exports = [read_json(p) for p in args.market_export]
    context, config = read_json(args.context), read_json(args.config)
    previous = read_json(args.previous) if args.previous else None
    decision = run_decisions(exports, context, config, previous)
    directory = research_root(ROOT) / "runs" / decision["decision_hash"]
    code_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    # The result hash excludes runtime metadata. Byte identity is separately kept.
    artifacts = {
        "report.json": decision,
        "data_coverage_snapshot.json": decision["coverage"],
        "research_evidence_snapshot.json": {"market_exports": exports, "context": context, "config": config},
        "research_ranking.json": decision["ranking"],
        "portfolio_proposal_research.json": decision["portfolio_proposal"],
        "research_decision_ledger.json": {"parent": decision["previous_decision_hash"], "rows": decision["decision_ledger"]},
        "industry_discovery.json": decision["industry_discovery"]}
    for name, value in artifacts.items(): immutable_json(directory / name, value)
    report_path = directory / "report.md"
    report_bytes = render_report(decision).encode()
    immutable_bytes(report_path, report_bytes)
    manifest = {"schema_version": "research-run-manifest-v1", "decision_hash": decision["decision_hash"],
                "source_commit": code_commit, "source_code_hash": source_code_hash(ROOT),
                "config_hash": digest(config), "context_hash": digest(context),
                "cutoff": decision["decision_cutoff"], "data_kind": decision["data_kind"],
                "input_export_hashes": decision["input_export_hashes"], "readiness": decision["readiness"],
                "artifacts": {name: digest(value) for name, value in artifacts.items()},
                "artifact_hash_kind": "canonical_json_sha256",
                "artifact_file_sha256": {name: hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in [*artifacts, "report.md"]},
                "status": "RESEARCH_PROPOSAL" if decision["readiness"]["portfolio_proposal_ready"] else "BLOCKED_OR_PARTIAL",
                "validation_is_profitability_proof": False,
                "source_paths_match_commit": not bool(subprocess.check_output(["git", "status", "--porcelain", "--", "tools/research_decision_v1", "tools/run_research_decision_v1.py", "docs/research_decision_v1_config.json"], cwd=ROOT, text=True).strip())}
    # Receipt keyed by source commit permits replay under different code without
    # overwriting an earlier execution receipt for the same decision content.
    immutable_json(directory / ("research_run_manifest_"+code_commit+".json"), manifest)
    print(json.dumps({"directory": str(directory), "decision_hash": decision["decision_hash"], "status": manifest["status"], "readiness": decision["readiness"]}, sort_keys=True))
    return 0 if decision["readiness"]["portfolio_proposal_ready"] else 2


if __name__ == "__main__": raise SystemExit(main())
