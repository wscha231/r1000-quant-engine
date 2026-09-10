#!/usr/bin/env python3
"""One-shot RESEARCH_ONLY consumer of explicit market exports."""
import sys
if __name__ == "__main__" and not sys.flags.isolated:
    print("BLOCKED_RUNTIME: invoke this consumer with python -I from the pinned research environment", file=sys.stderr)
    raise SystemExit(2)
import argparse
import contextlib
import hashlib
import importlib
import json
import os
import stat
import subprocess
import sysconfig
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]



def trusted_git_executable():
    """Use an OS-managed install, never cwd/PATH or a caller-supplied wrapper.

    The OS/interpreter and administrative installation are the trust boundary.
    This is not protection against an administrator replacing the Git binary.
    Windows uses the OS known-folder API, not ProgramFiles environment overrides.
    """
    if os.name == "posix":
        candidates = [Path("/usr/bin/git"), Path("/bin/git")]
    elif os.name == "nt":
        import ctypes
        candidates = []
        for folder in (0x26, 0x2A):
            path = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None,folder,None,0,path)==0:
                candidates.append(Path(path.value)/"Git/cmd/git.exe")
    else:
        raise ValueError("trusted_git_platform_unsupported")
    for candidate in candidates:
        try:
            resolved=candidate.resolve(strict=True)
            info=resolved.stat()
            if not stat.S_ISREG(info.st_mode) or not os.access(resolved,os.X_OK): continue
            if os.name == "posix":
                nodes=[resolved,*resolved.parents]
                if any(p.stat().st_uid!=0 or p.stat().st_mode & 0o022 for p in nodes): continue
            elif any(p.is_symlink() or getattr(p,"is_junction",lambda:False)() for p in (candidate,*candidate.parents)):
                continue
            return str(resolved)
        except (OSError,ValueError):
            continue
    raise ValueError("trusted_git_installation_unavailable")


def git_read_environment():
    env={k:v for k,v in os.environ.items() if not k.startswith(("GIT_","LD_","DYLD_"))}
    env.update(PATH=os.defpath,GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0",GIT_OPTIONAL_LOCKS="0")
    return env


def verified_source_snapshot(root):
    """Stdlib-only gate: retain the exact source bytes checked before imports."""
    root = Path(root).absolute()
    paths = ["tools/research_decision_v1", "tools/__init__.py",
             "tools/run_research_decision_v1.py", "tools/export_research_decision_market.py",
             "docs/research_decision_v1_config.json"]
    required = {paths[2], paths[3], paths[4], "tools/research_decision_v1/__init__.py"}
    try:
        git=trusted_git_executable()
        git_env=git_read_environment()
        def read_git(*args, text=False):
            return subprocess.check_output([git,"--no-pager","--no-replace-objects","-c","core.fsmonitor=false",*args],
                cwd=root,text=text,env=git_env,timeout=30)
        commit = read_git("rev-parse", "HEAD", text=True).strip()
        tracked = read_git("ls-tree", "-r", "--name-only", commit, "--", *paths, text=True).splitlines()
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
            expected = read_git("show", commit+":"+path)
            if content.replace(b"\r\n", b"\n") != expected.replace(b"\r\n", b"\n"): return None
            files[path] = expected.replace(b"\r\n", b"\n")
        if read_git("rev-parse", "HEAD", text=True).strip() != commit: return None
        return {"commit": commit, "files": files, "git_executable":git}
    except (OSError, ValueError, subprocess.SubprocessError): return None


def source_paths_match_commit(root):
    return verified_source_snapshot(root) is not None


def trusted_runtime_paths():
    """Trust the selected interpreter installation, never inherited import paths."""
    if not sys.flags.isolated: raise ValueError("isolated_python_required")
    prefixes = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    configured = sysconfig.get_paths()
    candidates = [configured[key] for key in ("stdlib", "platstdlib", "purelib", "platlib")]
    # DESTSHARED can retain a build-time prefix in a relocated interpreter.
    # Resolve its conventional runtime directory from the active stdlib instead.
    candidates += [str(Path(configured["stdlib"])/"lib-dynload")]
    if os.name == "nt": candidates.append(str(Path(sys.base_prefix)/"DLLs"))
    paths = []
    for candidate in candidates:
        if not candidate: continue
        path = Path(candidate).resolve()
        if not any(path.is_relative_to(prefix) for prefix in prefixes):
            raise ValueError("runtime_location_outside_interpreter")
        if path.is_dir() and str(path) not in paths: paths.append(str(path))
    if not paths: raise ValueError("runtime_locations_unavailable")
    return paths


@contextlib.contextmanager
def load_verified_runtime(snapshot):
    runtime_paths = trusted_runtime_paths()
    if any(name == "tools" or name.startswith("tools.") for name in sys.modules):
        raise ValueError("preloaded_research_namespace_forbidden")
    with tempfile.TemporaryDirectory(prefix="research-verified-") as directory:
        stage = Path(directory)
        for name, content in snapshot["files"].items():
            path = stage/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
        parent = stage/"tools/__init__.py"
        if not parent.exists(): parent.write_bytes(b"")
        prior_paths = sys.path[:]
        sys.path[:] = [str(stage), *runtime_paths]
        try:
            data = importlib.import_module("tools.research_decision_v1.data")
            engine = importlib.import_module("tools.research_decision_v1.engine")
            io = importlib.import_module("tools.research_decision_v1.io")
            renderer = importlib.import_module("tools.run_research_decision_v1")
            yield stage, data, engine, io, renderer
        finally:
            sys.path[:] = prior_paths
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
    report_bytes = renderer.render_report(decision).encode("utf-8")
    immutable_bytes(report_path, report_bytes)
    manifest = {"schema_version": "research-run-manifest-v1", "decision_hash": decision["decision_hash"],
                "source_commit": code_commit,
                "source_code_hash": digest({name: content.decode("utf-8") for name, content in snapshot["files"].items()
                                            if name.startswith("tools/research_decision_v1/") or name == "tools/__init__.py"}),
                "renderer_source_hash": hashlib.sha256(snapshot["files"]["tools/run_research_decision_v1.py"]).hexdigest(),
                "execution_layout": "decision_hash/source_commit", "executed_verified_source_snapshot": True,
                "runtime_import_policy": "ISOLATED_INTERPRETER_LOCATIONS",
                "trusted_runtime_locations": trusted_runtime_paths(),
                "third_party_source_bytes_verified": False,
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
