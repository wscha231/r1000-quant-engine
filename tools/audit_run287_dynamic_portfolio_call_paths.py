#!/usr/bin/env python3
"""Audit Run287 target-writer, ledger-consumer, and legacy EXIT call paths."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = "docs/run287_dynamic_portfolio_call_path_contract.json"
DEFAULT_OUTPUT = "outputs/run287_dynamic_portfolio_call_path_audit.json"
SCHEMA_VERSION = "run287-dynamic-portfolio-call-path-contract-v1"
PASS_STATUS = "PASS_CALL_PATH_CONTRACT"
BLOCKED_STATUS = "BLOCKED_CALL_PATH_CONTRACT"


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def validate_contract(contract: Mapping[str, Any]) -> None:
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("dynamic-portfolio call-path contract schema mismatch")
    if contract.get("status") != "RESEARCH_ONLY_STATIC_AUTHORITY_CONTRACT":
        raise ValueError("dynamic-portfolio call-path authority broadened")
    authority = contract.get("writer_authority") or {}
    if authority.get("accepted_current_target_writer") != (
        "tools/build_run287_same_close_target_books.py"
    ):
        raise ValueError("accepted current target writer changed")
    if authority.get("durable_paper_ledger_consumer") != (
        "tools/run_daily_simulated_fill_ledger.py"
    ):
        raise ValueError("durable paper ledger consumer changed")
    safety = contract.get("safety") or {}
    required_false = (
        "changes_investment_behavior",
        "target_mutation_authorized",
        "paper_execution_authorized",
        "fullrun_authorized",
        "production_activation_allowed",
        "live_trading_enabled",
        "automatic_promotion_allowed",
        "untracked_workflows_are_authority",
    )
    if any(safety.get(field) is not False for field in required_false):
        raise ValueError("dynamic-portfolio call-path safety authority broadened")
    if not contract.get("authority_sensitive_name_terms"):
        raise ValueError("authority-sensitive name terms missing")


def tracked_workflow_paths(root: Path) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "--", ".github/workflows/*.yml", ".github/workflows/*.yaml"],
            cwd=root,
            timeout=30,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
        paths = [line.strip().replace("\\", "/") for line in raw.splitlines() if line.strip()]
        if paths:
            return sorted(set(paths))
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        pass
    workflows = root / ".github" / "workflows"
    return sorted(
        path.relative_to(root).as_posix()
        for pattern in ("*.yml", "*.yaml")
        for path in workflows.glob(pattern)
        if path.is_file()
    )


def workflow_texts(root: Path, paths: list[str]) -> dict[str, str]:
    return {
        path: (root / path).read_text(encoding="utf-8")
        for path in paths
        if (root / path).is_file()
    }


def tracked_python_texts(root: Path) -> dict[str, str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "--", "*.py"],
            cwd=root,
            timeout=30,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
        paths = [line.strip().replace("\\", "/") for line in raw.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        paths = [path.relative_to(root).as_posix() for path in root.rglob("*.py")]
    return {
        path: (root / path).read_text(encoding="utf-8")
        for path in sorted(set(paths))
        if (root / path).is_file()
    }


def shell_logical_commands(text: str) -> list[tuple[int, str]]:
    commands: list[tuple[int, str]] = []
    parts: list[str] = []
    start_line = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not parts and (not line or line.startswith("#")):
            continue
        if not parts:
            start_line = number
        parts.append(line[:-1].rstrip() if line.endswith("\\") else line)
        if line.endswith("\\"):
            continue
        commands.append((start_line, " ".join(part for part in parts if part)))
        parts = []
    if parts:
        commands.append((start_line, " ".join(part for part in parts if part)))
    return commands


def executable_commands(text: str, entrypoint: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for number, command in shell_logical_commands(text):
        if entrypoint not in command:
            continue
        prefix = command.split(entrypoint, 1)[0]
        if re.search(r"(?:^|\s)python(?:3)?(?:\s|$)", prefix):
            result.append((number, command))
    return result


def executable_invocations(text: str, entrypoint: str) -> list[int]:
    return [number for number, _command in executable_commands(text, entrypoint)]


def python_entrypoints(text: str) -> set[str]:
    result: set[str] = set()
    pattern = re.compile(r"(?:^|\s)python(?:3)?\s+([^\s\\]+)")
    for _number, command in shell_logical_commands(text):
        for match in pattern.finditer(command):
            if match.group(1) not in {"-", "-c", "-m"}:
                result.add(match.group(1))
    return result


def inline_python_blocks(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    index = 0
    python_stdin = re.compile(r"(?:^|\s)python(?:3)?\s+-(?:\s|\\|$)")
    heredoc = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
    while index < len(lines):
        start = index
        command_parts: list[str] = []
        delimiter = ""
        while index < len(lines):
            command_parts.append(lines[index].strip())
            match = heredoc.search(lines[index])
            if match:
                delimiter = match.group(2)
                break
            if not lines[index].rstrip().endswith("\\"):
                break
            index += 1
        command = " ".join(command_parts)
        if delimiter and python_stdin.search(command):
            body_start = index + 1
            body_end = body_start
            while body_end < len(lines) and lines[body_end].strip() != delimiter:
                body_end += 1
            if body_end < len(lines):
                source = textwrap.dedent("\n".join(lines[body_start:body_end])) + "\n"
                blocks.append(
                    {
                        "line": start + 1,
                        "command": command,
                        "source": source,
                    }
                )
                index = body_end
        index += 1
    return blocks


def _module_candidates(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def local_import_paths(source: str, source_path: str, sources: Mapping[str, str]) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    result: set[str] = set()
    source_parts = Path(source_path).with_suffix("").parts[:-1]
    for node in ast.walk(tree):
        candidates: list[str] = []
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base_parts = list(source_parts)
            if node.level:
                keep = max(0, len(base_parts) - node.level + 1)
                base_parts = base_parts[:keep]
            else:
                base_parts = []
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
            if base:
                candidates.append(base)
            candidates.extend(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
                if alias.name != "*"
            )
        for module in candidates:
            for candidate in _module_candidates(module):
                if candidate in sources:
                    result.add(candidate)
    return result


def reachable_python_paths(
    roots: set[str], sources: Mapping[str, str]
) -> tuple[set[str], dict[str, str]]:
    seen: set[str] = set()
    parents: dict[str, str] = {}
    stack = sorted(root for root in roots if root in sources)
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for imported in sorted(local_import_paths(sources[path], path, sources)):
            if imported not in seen:
                parents.setdefault(imported, path)
                stack.append(imported)
    return seen, parents


def authority_sensitive(name: str, contract: Mapping[str, Any]) -> bool:
    normalized = str(name).casefold()
    return any(
        str(term).casefold() in normalized
        for term in contract.get("authority_sensitive_name_terms") or []
    )


def noncomment_text(text: str) -> str:
    return "\n".join(
        raw for raw in text.splitlines() if raw.strip() and not raw.lstrip().startswith("#")
    )


def audit_texts(
    contract: Mapping[str, Any],
    workflows: Mapping[str, str],
    accepted_files: Mapping[str, str],
) -> dict[str, Any]:
    validate_contract(contract)
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    roles = contract.get("workflow_roles") or {}
    for path in sorted(roles):
        if path not in workflows:
            failures.append(f"declared_workflow_missing:{path}")

    bindings = contract.get("entrypoint_bindings") or []
    if not isinstance(bindings, list) or not bindings:
        failures.append("entrypoint_bindings_missing")
        bindings = []
    seen_entrypoints: set[str] = set()
    accepted_roles = 0
    for binding in bindings:
        if not isinstance(binding, dict):
            failures.append("malformed_entrypoint_binding")
            continue
        entrypoint = str(binding.get("entrypoint") or "")
        role = str(binding.get("role") or "")
        allowed = sorted(set(binding.get("allowed_workflows") or []))
        if not entrypoint or entrypoint in seen_entrypoints:
            failures.append(f"duplicate_or_missing_entrypoint:{entrypoint}")
            continue
        seen_entrypoints.add(entrypoint)
        if role == "accepted_current_target_writer":
            accepted_roles += 1
        observed: list[str] = []
        invocation_count = 0
        for path, text in sorted(workflows.items()):
            lines = executable_invocations(text, entrypoint)
            if not lines:
                continue
            observed.append(path)
            invocation_count += len(lines)
            records.append(
                {
                    "entrypoint": entrypoint,
                    "role": role,
                    "workflow": path,
                    "line_numbers": lines,
                }
            )
        if observed != allowed:
            failures.append(
                f"entrypoint_workflow_mismatch:{entrypoint}:"
                f"expected={','.join(allowed)}:observed={','.join(observed)}"
            )
        exact_count = binding.get("exact_invocation_count")
        if exact_count is not None and invocation_count != int(exact_count):
            failures.append(
                f"entrypoint_invocation_count_mismatch:{entrypoint}:"
                f"expected={int(exact_count)}:observed={invocation_count}"
            )
    if accepted_roles != 1:
        failures.append(f"accepted_target_writer_role_count:{accepted_roles}")

    for path, tokens in sorted((contract.get("required_workflow_tokens") or {}).items()):
        text = noncomment_text(workflows.get(path, ""))
        for token in tokens:
            if str(token) not in text:
                failures.append(f"required_workflow_token_missing:{path}:{token}")

    for requirement in contract.get("required_executable_commands") or []:
        path = str(requirement.get("workflow") or "")
        entrypoint = str(requirement.get("entrypoint") or "")
        tokens = [" ".join(str(token).split()) for token in requirement.get("required_tokens") or []]
        commands = executable_commands(workflows.get(path, ""), entrypoint)
        matches = [
            (line, command)
            for line, command in commands
            if all(token in " ".join(command.split()) for token in tokens)
        ]
        exact_matches = int(requirement.get("exact_match_count", 1))
        if len(matches) != exact_matches:
            failures.append(
                f"required_executable_command_mismatch:{path}:{entrypoint}:"
                f"expected_matches={exact_matches}:observed_matches={len(matches)}"
            )

    forbidden = tuple(contract.get("forbidden_accepted_path_tokens") or [])
    for path in contract.get("accepted_path_files") or []:
        text = accepted_files.get(path)
        if text is None:
            failures.append(f"accepted_path_file_missing:{path}")

    accepted_workflow = str(contract.get("accepted_daily_workflow") or "")
    inline_blocks = inline_python_blocks(workflows.get(accepted_workflow, ""))
    inline_local_paths: set[str] = set()
    for block in inline_blocks:
        source = str(block["source"])
        virtual_path = f"{accepted_workflow}::inline:{block['line']}"
        inline_local_paths.update(local_import_paths(source, virtual_path, accepted_files))
        for token in forbidden:
            if token in noncomment_text(source):
                failures.append(
                    f"forbidden_legacy_exit_reachability:{virtual_path}:{token}"
                )
    expected_inline = sorted(
        set(contract.get("accepted_workflow_inline_local_imports") or [])
    )
    observed_inline = sorted(inline_local_paths)
    if observed_inline != expected_inline:
        failures.append(
            "accepted_workflow_inline_import_mismatch:"
            f"expected={','.join(expected_inline)}:"
            f"observed={','.join(observed_inline)}"
        )

    root_paths = {
        str(path)
        for path in contract.get("accepted_path_files") or []
        if str(path).endswith(".py")
    }
    root_paths.update(inline_local_paths)
    reachable, import_parents = reachable_python_paths(root_paths, accepted_files)
    legacy_paths: list[str] = []
    for path in sorted(reachable):
        source = noncomment_text(accepted_files[path])
        path_blocked = path == "r1000_risk_sensing.py"
        for token in forbidden:
            if token in source:
                failures.append(f"forbidden_legacy_exit_reachability:{path}:{token}")
                path_blocked = True
        if path_blocked:
            chain = [path]
            cursor = path
            while cursor in import_parents:
                cursor = import_parents[cursor]
                chain.append(cursor)
            legacy_paths.append("<-".join(chain))

    for path, role in sorted(roles.items()):
        if not str(role).endswith("_no_target_writer"):
            continue
        references = set(python_entrypoints(workflows.get(path, "")))
        for block in inline_python_blocks(workflows.get(path, "")):
            references.update(
                local_import_paths(
                    str(block["source"]),
                    f"{path}::inline:{block['line']}",
                    accepted_files,
                )
            )
        sensitive = sorted(
            reference for reference in references if authority_sensitive(reference, contract)
        )
        if sensitive:
            failures.append(
                f"no_target_writer_role_violated:{path}:{','.join(sensitive)}"
            )

    authority = contract.get("writer_authority") or {}
    accepted_entrypoint = str(authority.get("accepted_current_target_writer") or "")
    if not any(
        row["entrypoint"] == accepted_entrypoint
        and row["workflow"] == accepted_workflow
        for row in records
    ):
        failures.append("accepted_daily_writer_binding_missing")
    sensitive_terms = ("target", "ledger", "order", "selector", "decision")
    observed_sensitive = sorted(
        entrypoint
        for entrypoint in python_entrypoints(workflows.get(accepted_workflow, ""))
        if any(term in entrypoint.casefold() for term in sensitive_terms)
    )
    expected_sensitive = sorted(
        set(contract.get("accepted_workflow_authority_sensitive_entrypoints") or [])
    )
    if observed_sensitive != expected_sensitive:
        failures.append(
            "accepted_workflow_sensitive_entrypoint_mismatch:"
            f"expected={','.join(expected_sensitive)}:"
            f"observed={','.join(observed_sensitive)}"
        )

    return {
        "schema_version": "run287-dynamic-portfolio-call-path-audit-v1",
        "status": PASS_STATUS if not failures else BLOCKED_STATUS,
        "contract_sha256": canonical_sha256(contract),
        "tracked_workflow_count": len(workflows),
        "accepted_daily_workflow": accepted_workflow,
        "accepted_current_target_writer": accepted_entrypoint,
        "accepted_workflow_authority_sensitive_entrypoints": observed_sensitive,
        "accepted_workflow_inline_local_imports": observed_inline,
        "accepted_python_reachable_files": sorted(reachable),
        "legacy_exit_reachability_paths": sorted(legacy_paths),
        "invocations": records,
        "failure_count": len(failures),
        "failures": failures,
        "safety": dict(contract.get("safety") or {}),
    }


def resolve_repo_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def git_source_identity(root: Path, paths: list[str]) -> dict[str, Any]:
    normalized = sorted(set(path.replace("\\", "/") for path in paths if path))
    input_hashes: dict[str, str] = {}
    for path in normalized:
        candidate = root / path
        if candidate.is_file():
            input_hashes[path] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        else:
            input_hashes[path] = "MISSING"
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, timeout=30
        ).decode("utf-8").strip()
        status = subprocess.check_output(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                *normalized,
            ],
            cwd=root,
            timeout=30,
        ).decode("utf-8")
        dirty = sorted(line for line in status.splitlines() if line.strip())
        identity_status = "CLEAN_HEAD_BOUND" if not dirty else "DIRTY_INPUTS_NOT_HEAD_BOUND"
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        head = ""
        dirty = ["git_identity_unavailable"]
        identity_status = "GIT_IDENTITY_UNAVAILABLE"
    return {
        "source_identity_status": identity_status,
        "source_commit_sha": head if not dirty else "",
        "observed_head_sha": head,
        "source_commit_clean": not dirty,
        "dirty_input_records": dirty,
        "audit_input_paths": normalized,
        "audit_input_tree_sha256": canonical_sha256(input_hashes),
        "audit_input_hashes": input_hashes,
    }


def run_audit(
    root: Path,
    contract: Mapping[str, Any],
    *,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    tracked = tracked_workflow_paths(root)
    workflows = workflow_texts(root, tracked)
    python_sources = tracked_python_texts(root)
    accepted_files = {**python_sources, **workflows}
    result = audit_texts(contract, workflows, accepted_files)
    relevant = list(tracked)
    relevant.extend(result.get("accepted_python_reachable_files") or [])
    relevant.extend(str(path) for path in contract.get("accepted_path_files") or [])
    tool_path = Path(__file__).resolve()
    result["audit_runtime_path"] = str(tool_path)
    result["audit_runtime_sha256"] = hashlib.sha256(tool_path.read_bytes()).hexdigest()
    try:
        relevant.append(tool_path.relative_to(root).as_posix())
    except ValueError:
        result["audit_runtime_head_bound"] = False
    else:
        result["audit_runtime_head_bound"] = True
    if contract_path is not None:
        try:
            relevant.append(contract_path.resolve().relative_to(root).as_posix())
        except ValueError:
            result["failures"].append("contract_outside_selected_repository")
    identity = git_source_identity(root, relevant)
    result.update(identity)
    if not identity["source_commit_clean"]:
        result["failures"].append("audit_inputs_not_clean_at_head")
    result["failures"] = sorted(set(result["failures"]))
    result["failure_count"] = len(result["failures"])
    result["status"] = PASS_STATUS if not result["failures"] else BLOCKED_STATUS
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo_root).resolve()
    contract_path = resolve_repo_path(root, args.contract)
    result = run_audit(root, read_json(contract_path), contract_path=contract_path)
    if not args.check_only:
        output = resolve_repo_path(root, args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == PASS_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
