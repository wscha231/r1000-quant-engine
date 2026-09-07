#!/usr/bin/env python3
"""One-shot RESEARCH_ONLY consumer of explicit market exports."""
import argparse
import contextlib
import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def verified_source_snapshot(root):
    """Stdlib-only gate: retain the exact source bytes checked before imports."""
    root = Path(root).absolute()
    paths = ["tools/research_decision_v1", "tools/__init__.py",
             "tools/run_research_decision_v1.py", "tools/export_research_decision_market.py",
             "docs/research_decision_v1_config.json"]
    required = {paths[2], paths[3], paths[4], "tools/research_decision_v1/__init__.py"}
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        tracked = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", commit, "--", *paths], cwd=root, text=True).splitlines()
        tracked = {p for p in tracked if p.endswith((".py", ".json"))}
        actual = {p.relative_to(root).as_posix() for p in (root/paths[0]).rglob("*.py")}
        actual.update(p for p in paths[1:] if (root/p).exists() or (root/p).is_symlink())
        if not required <= tracked or actual != tracked: return None
        if any(p.suffix in {".so", ".pyd"} for p in (root/paths[0]).rglob("*")): return None
        files = {}
        for path in sorted(tracked):
            local = root/path
            if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (local, *local.parents)): return None
            with local.open("rb") as handle:
                before = os.fstat(handle.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size > 32_000_000: return None
                content = handle.read(32_000_001)
                after = os.fstat(handle.fileno())
            if len(content) > 32_000_000 or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns): return None
            expected = subprocess.check_output(["git", "show", commit+":"+path], cwd=root)
            if content.replace(b"\r\n", b"\n") != expected.replace(b"\r\n", b"\n"): return None
            files[path] = content
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != commit: return None
        return {"commit": commit, "files": files}
    except (OSError, ValueError, subprocess.CalledProcessError): return None


def source_paths_match_commit(root):
    return verified_source_snapshot(root) is not None


@contextlib.contextmanager
def load_verified_runtime(snapshot):
    if any(name == "tools" or name.startswith("tools.") for name in sys.modules):
        raise ValueError("preloaded_research_namespace_forbidden")
    with tempfile.TemporaryDirectory(prefix="research-verified-") as directory:
        stage = Path(directory)
        for name, content in snapshot["files"].items():
            path = stage/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        parent = stage/"tools/__init__.py"
        if not parent.exists(): parent.write_bytes(b"")
        sys.path.insert(0, str(stage))
        try:
            data = importlib.import_module("tools.research_decision_v1.data")
            engine = importlib.import_module("tools.research_decision_v1.engine")
            io = importlib.import_module("tools.research_decision_v1.io")
            renderer = importlib.import_module("tools.run_research_decision_v1")
            yield stage, data, engine, io, renderer
        finally:
            sys.path.remove(str(stage))
            for name in list(sys.modules):
                if name == "tools" or name.startswith("tools."): del sys.modules[name]


def render_report(decision):
    p = decision["portfolio_proposal"]
    lines = ["# Research decision V1", "", f"Data kind: {decision['data_kind']}; cutoff: {decision['decision_cutoff']}",
             f"Mode: {decision['mode']}; orders_allowed=false", "", "Subjective scenarios; OOS and MDD validation incomplete.", "",
             "| Security | Local total return (currency) | KRW total return | KRW return rank | KRW investment rank |",
             "|---|---:|---:|---:|---:|"]
    actions = {r["security_id"]: r for r in p["rows"]}
    for r in decision["ranking"]:
        expected = f"{r['expected_total_return']:.2%}" if r["expected_total_return"] is not None else "N/A"
        krw = f"{r['expected_total_return_krw']:.2%}" if r["expected_total_return_krw"] is not None else "N/A"
        lines.append(f"| {r['security_id']} | {expected} ({r['currency']}) | {krw} | {r['expected_return_rank'] or 'N/A'} | {r['investment_rank'] or 'N/A'} |")
    lines += ["", "| Security | Action | Weight | Reason |", "|---|---|---:|---|"]
    for a in p["rows"]:
        weight = f"{a['target_weight']:.2%}" if a["target_weight"] is not None else "N/A"
        reason = "; ".join(a["reasons"]).replace("|", "/").replace("\n", " ")
        lines.append(f"| {a['security_id']} | {a['action']} | {weight} | {reason} |")
    lines += ["", "| Security | Good company? | Good stock? | Buy price now? | Portfolio value? |", "|---|---|---|---|---|"]
    questions = {r["security_id"]: r["four_questions"] for r in decision["ranking"]}
    for a in p["rows"]:
        q = questions.get(a["security_id"], a.get("four_questions", {}))
        lines.append("| "+" | ".join([a["security_id"], *(q.get(k, "unverified") for k in ("good_company", "good_stock", "buy_price_now", "portfolio_value"))])+" |")
    if p["cash_weight"] is not None: lines += ["", f"Cash / unallocated capital: {p['cash_weight']:.2%}."]
    if p["blockers"]:
        lines += ["", "Proposal blockers:", ""] + ["- "+str(reason).replace("\n", " ") for reason in p["blockers"]]
    audit = p.get("constraints", {})
    if audit:
        lines += ["", "| Constraint audit | Observed |", "|---|---|",
                  f"| Gross exposure | {audit['gross_exposure']:.2%} |",
                  f"| Scenario stress loss / limit | {audit['scenario_stress_loss']:.2%} / {audit['scenario_stress_limit']:.2%} |",
                  "| Country exposure | "+json.dumps(audit["country_exposure"], sort_keys=True)+" |",
                  "| Country counts | "+json.dumps(audit["country_counts"], sort_keys=True)+" |",
                  "| Common risk exposure | "+json.dumps(audit["common_risk_exposure"], sort_keys=True)+" |",
                  "| Violations | "+("; ".join(audit["violations"]) or "none")+" |"]
    lines += ["", "Readiness: `"+json.dumps(decision["readiness"], sort_keys=True)+"`", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-export", action="append", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--config", default=str(ROOT / "docs/research_decision_v1_config.json"))
    parser.add_argument("--previous")
    args = parser.parse_args()
    snapshot = verified_source_snapshot(ROOT)
    if snapshot is None:
        print(json.dumps({"status": "BLOCKED_SOURCE_MISMATCH", "source_paths_match_commit": False,
                          "artifacts_written": False}, sort_keys=True))
        return 2
    with load_verified_runtime(snapshot) as runtime:
        return run_verified(args, snapshot, runtime)


def run_verified(args, snapshot, runtime):
    stage, data, engine, io, renderer = runtime
    digest, read_json, immutable_json, immutable_bytes = data.digest, io.read_json, io.immutable_json, io.immutable_bytes
    code_commit = snapshot["commit"]
    exports = [read_json(p) for p in args.market_export]
    config_path = stage/"docs/research_decision_v1_config.json" if Path(args.config).resolve() == ROOT/"docs/research_decision_v1_config.json" else args.config
    context, config = read_json(args.context), read_json(config_path)
    previous = read_json(args.previous) if args.previous else None
    decision = engine.run_decisions(exports, context, config, previous)
    directory = io.research_root(ROOT) / "runs" / decision["decision_hash"] / code_commit
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
    report_bytes = renderer.render_report(decision).encode()
    immutable_bytes(report_path, report_bytes)
    manifest = {"schema_version": "research-run-manifest-v1", "decision_hash": decision["decision_hash"],
                "source_commit": code_commit,
                "source_code_hash": digest({name: content.decode("utf-8") for name, content in snapshot["files"].items()
                                            if name.startswith("tools/research_decision_v1/") or name == "tools/__init__.py"}),
                "renderer_source_hash": hashlib.sha256(snapshot["files"]["tools/run_research_decision_v1.py"]).hexdigest(),
                "execution_layout": "decision_hash/source_commit", "executed_verified_source_snapshot": True,
                "config_hash": digest(config), "context_hash": digest(context),
                "cutoff": decision["decision_cutoff"], "data_kind": decision["data_kind"],
                "input_export_hashes": decision["input_export_hashes"], "readiness": decision["readiness"],
                "artifacts": {name: digest(value) for name, value in artifacts.items()},
                "artifact_hash_kind": "canonical_json_sha256",
                "artifact_file_sha256": {name: hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in [*artifacts, "report.md"]},
                "status": "RESEARCH_PROPOSAL" if decision["readiness"]["portfolio_proposal_ready"] else "BLOCKED_OR_PARTIAL",
                "validation_is_profitability_proof": False,
                "source_paths_match_commit": True}
    # Receipt keyed by source commit permits replay under different code without
    # overwriting an earlier execution receipt for the same decision content.
    immutable_json(directory / ("research_run_manifest_"+code_commit+".json"), manifest)
    print(json.dumps({"directory": str(directory), "decision_hash": decision["decision_hash"], "status": manifest["status"], "readiness": decision["readiness"]}, sort_keys=True))
    return 0 if decision["readiness"]["portfolio_proposal_ready"] else 2


if __name__ == "__main__": raise SystemExit(main())
