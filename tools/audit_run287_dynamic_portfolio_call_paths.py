#!/usr/bin/env python3
"""Audit Run287 target-writer, ledger-consumer, and legacy EXIT call paths."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shlex
import subprocess
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = "docs/run287_dynamic_portfolio_call_path_contract.json"
DEFAULT_OUTPUT = "outputs/run287_dynamic_portfolio_call_path_audit.json"
SCHEMA_VERSION = "run287-dynamic-portfolio-call-path-contract-v1"
PASS_STATUS = "PASS_CALL_PATH_CONTRACT"
BLOCKED_STATUS = "BLOCKED_CALL_PATH_CONTRACT"
STDIN_ENTRYPOINTS = {"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def tracked_python_paths(root: Path) -> list[str]:
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
    return sorted(set(paths))


def tracked_python_texts(root: Path) -> dict[str, str]:
    return {
        path: (root / path).read_text(encoding="utf-8")
        for path in tracked_python_paths(root)
        if (root / path).is_file()
    }


def shell_logical_commands(text: str) -> list[tuple[int, str]]:
    commands: list[tuple[int, str]] = []
    parts: list[str] = []
    start_line = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = strip_shell_comment(raw.strip())
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


def strip_shell_comment(command: str) -> str:
    """Strip a Bash comment without treating embedded or quoted # as a comment."""
    quote = ""
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "#" and (
            index == 0 or command[index - 1].isspace() or command[index - 1] in ";|&"
        ):
            return command[:index].rstrip()
    return command


def shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(
        strip_shell_comment(command), posix=True, punctuation_chars=";&|<>"
    )
    lexer.commenters = ""
    lexer.whitespace_split = True
    return list(lexer)


def module_entrypoint(module: str) -> str:
    return f"{str(module).replace('.', '/')}.py"


def normalize_script_entrypoint(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    root_prefix = ROOT.as_posix().rstrip("/") + "/"
    if normalized.casefold().startswith(root_prefix.casefold()):
        normalized = normalized[len(root_prefix):]
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


@lru_cache(maxsize=512)
def python_invocations(text: str) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    boundaries = {";", "&&", "||", "|", "&"}
    redirections = {
        "<", ">", "<<", ">>", "<<<", "<>", ">&", "<&", ">|",
        "&>", "&>>",
    }
    options_with_values = {"-X", "-W", "--check-hash-based-pycs"}
    for line, command in shell_logical_commands(text):
        try:
            tokens = shell_tokens(command)
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            shell_name = token.rsplit("/", 1)[-1]
            if shell_name in {"bash", "sh", "dash", "zsh", "ksh"}:
                for option_index in range(index + 1, len(tokens) - 1):
                    if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", tokens[option_index]):
                        nested = python_invocations(tokens[option_index + 1])
                        for row in nested:
                            copied = dict(row)
                            copied["line"] = line
                            copied["wrapped_by"] = shell_name
                            result.append(copied)
                        break
            executable = token.rsplit("/", 1)[-1]
            if (
                "/" in token.replace("\\", "/")
                and token.endswith(".py")
                and (index == 0 or tokens[index - 1] in boundaries)
            ):
                end = index + 1
                while end < len(tokens) and tokens[end] not in boundaries:
                    end += 1
                raw_argv = tokens[index:end]
                argv: list[str] = []
                cursor = 0
                while cursor < len(raw_argv):
                    value = raw_argv[cursor]
                    if value in redirections:
                        cursor += 2
                        continue
                    argv.append(value)
                    cursor += 1
                result.append(
                    {
                        "line": line,
                        "entrypoint": normalize_script_entrypoint(token),
                        "argv": argv,
                        "command": command,
                        "command_source": "",
                        "direct_executable": True,
                    }
                )
                continue
            if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
                continue
            end = index + 1
            while end < len(tokens) and tokens[end] not in boundaries:
                end += 1
            raw_argv = tokens[index:end]
            argv: list[str] = []
            cursor = 0
            while cursor < len(raw_argv):
                value = raw_argv[cursor]
                if (
                    value.isdigit()
                    and cursor + 1 < len(raw_argv)
                    and raw_argv[cursor + 1] in redirections
                ):
                    cursor += 1
                    value = raw_argv[cursor]
                if value in redirections:
                    cursor += 2
                    continue
                argv.append(value)
                cursor += 1
            cursor = 1
            entrypoint = ""
            command_source = ""
            while cursor < len(argv):
                value = argv[cursor]
                if value == "-m" and cursor + 1 < len(argv):
                    entrypoint = module_entrypoint(argv[cursor + 1])
                    break
                if value == "-c":
                    entrypoint = value
                    if cursor + 1 < len(argv):
                        command_source = argv[cursor + 1]
                    break
                if value == "-":
                    entrypoint = value
                    break
                if value in options_with_values:
                    cursor += 2
                    continue
                if value.startswith("-"):
                    cursor += 1
                    continue
                entrypoint = normalize_script_entrypoint(value)
                break
            result.append(
                {
                    "line": line,
                    "entrypoint": entrypoint,
                    "argv": argv,
                    "command": command,
                    "command_source": command_source,
                }
            )
    return tuple(result)


def executable_commands(text: str, entrypoint: str) -> list[tuple[int, str]]:
    return [
        (int(row["line"]), " ".join(str(value) for value in row["argv"]))
        for row in python_invocations(text)
        if row["entrypoint"] == entrypoint
    ]


def executable_invocations(text: str, entrypoint: str) -> list[int]:
    return [number for number, _command in executable_commands(text, entrypoint)]


def python_entrypoints(text: str) -> set[str]:
    return {
        str(row["entrypoint"])
        for row in python_invocations(text)
        if row["entrypoint"] not in {"", "-c", *STDIN_ENTRYPOINTS}
    }


@lru_cache(maxsize=512)
def inline_python_blocks(text: str) -> tuple[dict[str, Any], ...]:
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    index = 0
    heredoc = re.compile(
        r"<<-?\s*(?:['\"]|\\)?([A-Za-z_][A-Za-z0-9_]*)(?:['\"])?"
    )
    while index < len(lines):
        start = index
        command_parts: list[str] = []
        delimiter = ""
        while index < len(lines):
            command_parts.append(lines[index].strip())
            match = heredoc.search(lines[index])
            if match:
                delimiter = match.group(1)
                break
            if not lines[index].rstrip().endswith("\\"):
                break
            index += 1
        command = " ".join(command_parts)
        is_python_stdin = any(
            row["entrypoint"] in STDIN_ENTRYPOINTS
            for row in python_invocations(command)
        )
        if delimiter and is_python_stdin:
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
    return tuple(blocks)


def _module_candidates(module: str) -> tuple[str, str]:
    base = module.replace(".", "/")
    return f"{base}.py", f"{base}/__init__.py"


def dynamic_import_callables(tree: ast.AST) -> set[str]:
    callables = {"importlib.import_module", "__import__", "builtins.__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "importlib":
                    callables.add(f"{local}.import_module")
                elif alias.name == "builtins":
                    callables.add(f"{local}.__import__")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == "importlib" and alias.name == "import_module":
                    callables.add(alias.asname or alias.name)
                elif node.module == "builtins" and alias.name == "__import__":
                    callables.add(alias.asname or alias.name)
    return callables


def literal_dynamic_import_module(
    node: ast.AST, callables: set[str] | None = None
) -> str:
    """Resolve common dynamic imports only when their module is a literal."""
    if not isinstance(node, ast.Call) or not node.args:
        return ""
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return ""
    func = dotted_expression_name(node.func)
    if func in (callables or {"importlib.import_module", "__import__", "builtins.__import__"}):
        return first.value
    return ""


@lru_cache(maxsize=4096)
def local_import_candidates(source: str, source_path: str) -> tuple[str, ...]:
    """Parse import candidates once; callers filter them against a repository."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    result: set[str] = set()
    dynamic_callables = dynamic_import_callables(tree)
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
        elif isinstance(node, ast.Call):
            dynamic_module = literal_dynamic_import_module(node, dynamic_callables)
            if dynamic_module:
                candidates.append(dynamic_module)
        for module in candidates:
            result.update(_module_candidates(module))
    return tuple(sorted(result))


def local_import_paths(
    source: str,
    source_path: str,
    sources: Mapping[str, str],
    known_paths: set[str] | None = None,
) -> set[str]:
    known = set(sources) if known_paths is None else set(known_paths)
    return {
        candidate
        for candidate in local_import_candidates(source, source_path)
        if candidate in known
    }


@lru_cache(maxsize=2048)
def python_main_call_counts(source: str) -> tuple[tuple[str, int], ...]:
    """Count explicit calls to imported module `main` entrypoints."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    names: dict[str, str] = {}
    modules: dict[str, str] = {}
    dynamic_callables = dynamic_import_callables(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            module_path = module_entrypoint(node.module)
            for alias in node.names:
                if alias.name == "main":
                    names[alias.asname or alias.name] = module_path
                elif node.module == "tools":
                    modules[alias.asname or alias.name] = module_entrypoint(
                        f"tools.{alias.name}"
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name] = module_entrypoint(
                    alias.name
                )
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = ""
        if isinstance(node.func, ast.Name):
            target = names.get(node.func.id, "")
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "main":
            target = modules.get(dotted_expression_name(node.func.value), "")
            if not target:
                dynamic_module = literal_dynamic_import_module(
                    node.func.value, dynamic_callables
                )
                if dynamic_module:
                    target = module_entrypoint(dynamic_module)
        if target:
            counts[target] = counts.get(target, 0) + 1
    return tuple(sorted(counts.items()))


def dotted_expression_name(node: ast.AST) -> str:
    """Return a dotted Name/Attribute expression, or an empty string."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_expression_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else ""
    return ""


def embedded_python_sources(text: str) -> list[dict[str, Any]]:
    sources = [
        {
            "line": int(row["line"]),
            "kind": "command",
            "source": str(row["command_source"]),
        }
        for row in python_invocations(text)
        if row["entrypoint"] == "-c" and row["command_source"]
    ]
    sources.extend(
        {
            "line": int(block["line"]),
            "kind": "stdin",
            "source": str(block["source"]),
        }
        for block in inline_python_blocks(text)
    )
    return sources


def reachable_python_paths(
    roots: set[str],
    sources: Mapping[str, str],
    known_paths: set[str] | None = None,
) -> tuple[set[str], dict[str, str]]:
    known = set(sources) if known_paths is None else set(known_paths)
    seen: set[str] = set()
    parents: dict[str, str] = {}
    stack = sorted(root for root in roots if root in known)
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        if path not in sources:
            continue
        for imported in sorted(
            local_import_paths(sources[path], path, sources, known)
        ):
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


@lru_cache(maxsize=4096)
def noncomment_text(text: str) -> str:
    return "\n".join(
        raw for raw in text.splitlines() if raw.strip() and not raw.lstrip().startswith("#")
    )


def contains_argv_sequence(argv: list[str], sequence: list[str]) -> bool:
    if not sequence or len(sequence) > len(argv):
        return False
    return any(
        argv[index:index + len(sequence)] == sequence
        for index in range(len(argv) - len(sequence) + 1)
    )


def argv_option_values(argv: list[str], option: str) -> list[str | None]:
    """Return every effective operand supplied for a long option."""
    values: list[str | None] = []
    prefix = f"{option}="
    for index, value in enumerate(argv):
        if value == option:
            operand = argv[index + 1] if index + 1 < len(argv) else None
            if operand is not None and operand.startswith("--"):
                operand = None
            values.append(operand)
        elif value.startswith(prefix):
            values.append(value[len(prefix):])
    return values


def invocation_matches_requirement(
    argv: list[str], requirement: Mapping[str, Any]
) -> bool:
    sequences = [
        shlex.split(str(token), posix=True)
        for token in requirement.get("required_tokens") or []
    ]
    if not all(contains_argv_sequence(argv, sequence) for sequence in sequences):
        return False
    for flag in requirement.get("required_flags") or []:
        if argv.count(str(flag)) != 1:
            return False
    for option, expected in (
        requirement.get("required_option_values") or {}
    ).items():
        if argv_option_values(argv, str(option)) != [str(expected)]:
            return False
    for option in requirement.get("required_nonempty_options") or []:
        values = argv_option_values(argv, str(option))
        if len(values) != 1 or values[0] in {None, ""}:
            return False
    return True


def shell_boolean_flag_guard_matches(
    text: str,
    *,
    variable: str,
    input_name: str,
    enabled_value: str,
    allowed_occurrence_lines: list[str] | None = None,
) -> bool:
    """Validate a fail-closed empty default and one named-input assignment."""
    if allowed_occurrence_lines is not None:
        observed_lines = shell_variable_occurrence_lines(text, variable)
        if observed_lines != sorted(str(value) for value in allowed_occurrence_lines):
            return False
    assignment = re.compile(
        rf"^\s*(?:(?:export|readonly)\s+|declare(?:\s+-[A-Za-z]+)?\s+)?"
        rf"{re.escape(variable)}=(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))\s*$",
        re.MULTILINE,
    )
    values = [next(value for value in match.groups() if value is not None) for match in assignment.finditer(text)]
    if values != ["", enabled_value]:
        return False
    block = re.compile(
        rf"^\s*{re.escape(variable)}=\"\"\s*$\n"
        rf"\s*if \[ \"\$\{{\{{ github\.event\.inputs\.{re.escape(input_name)} \}}\}}\" = \"true\" \]; then\s*$\n"
        rf"\s*{re.escape(variable)}=\"{re.escape(enabled_value)}\"\s*$\n"
        rf"\s*fi\s*$",
        re.MULTILINE,
    )
    return block.search(text) is not None


def shell_variable_occurrence_lines(text: str, variable: str) -> list[str]:
    return sorted(
        raw.strip()
        for raw in text.splitlines()
        if re.search(rf"\b{re.escape(variable)}\b", raw)
    )


@lru_cache(maxsize=4096)
def authority_write_sinks(
    source: str, sensitive_terms: tuple[str, ...]
) -> tuple[str, ...]:
    """Find direct writes whose literal destination is authority-sensitive."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    write_methods = {
        "write_text", "write_bytes", "to_csv", "to_json", "to_parquet",
        "rename", "replace",
    }
    findings: set[str] = set()
    open_aliases = {"open", "io.open", "builtins.open"}
    for imported in ast.walk(tree):
        if isinstance(imported, ast.Import):
            for alias in imported.names:
                local = alias.asname or alias.name
                if alias.name in {"io", "builtins"}:
                    open_aliases.add(f"{local}.open")
        elif isinstance(imported, ast.ImportFrom) and imported.module in {"io", "builtins"}:
            for alias in imported.names:
                if alias.name == "open":
                    open_aliases.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = dotted_expression_name(node.func)
        path_method_open = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and isinstance(node.func.value, ast.Call)
        )
        if func_name in open_aliases or path_method_open:
            path_args = node.func.value.args if path_method_open else node.args
            literal_path = next(
                (
                    str(value.value)
                    for value in path_args
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ),
                "",
            )
            mode = "r"
            mode_position = 0 if path_method_open else 1
            if len(node.args) > mode_position and isinstance(
                node.args[mode_position], ast.Constant
            ):
                mode = str(node.args[mode_position].value)
            for keyword in node.keywords:
                if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                    mode = str(keyword.value.value)
            sensitive = sorted(
                term for term in sensitive_terms if term in literal_path.casefold()
            )
            if sensitive and any(marker in mode for marker in "wax+"):
                findings.add(
                    f"line={getattr(node, 'lineno', 0)}:open:{','.join(sensitive)}"
                )
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method not in write_methods:
            continue
        literals = [
            value.value
            for value in ast.walk(node)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
        sensitive = sorted(
            {
                term
                for literal in literals
                for term in sensitive_terms
                if term in literal.casefold()
            }
        )
        if sensitive:
            findings.add(f"line={getattr(node, 'lineno', 0)}:{method}:{','.join(sensitive)}")
    return tuple(sorted(findings))


@lru_cache(maxsize=4096)
def shell_authority_write_sinks(
    text: str, sensitive_terms: tuple[str, ...]
) -> tuple[str, ...]:
    """Inventory literal authority-sensitive destinations written by shell."""
    findings: set[str] = set()
    redirections = {">", ">>", ">|", "&>", "&>>"}
    copy_commands = {"cp", "mv", "install", "tee", "touch", "truncate"}

    def sensitive(value: str) -> tuple[str, ...]:
        normalized = value.casefold()
        return tuple(term for term in sensitive_terms if term in normalized)

    for line, command in shell_logical_commands(text):
        try:
            tokens = shell_tokens(command)
        except ValueError:
            continue
        for index, token in enumerate(tokens[:-1]):
            if token in redirections:
                destination = tokens[index + 1]
                terms = sensitive(destination)
                if terms:
                    findings.add(
                        f"line={line}:redirect:{destination}:{','.join(terms)}"
                    )
        executable_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if token.rsplit("/", 1)[-1] in copy_commands
            ),
            None,
        )
        if executable_index is not None:
            executable = tokens[executable_index].rsplit("/", 1)[-1]
            operands = [
                token
                for token in tokens[executable_index + 1:]
                if token not in redirections and not token.startswith("-")
            ]
            destinations = operands if executable in {"tee", "touch", "truncate"} else operands[-1:]
            for destination in destinations:
                terms = sensitive(destination)
                if terms:
                    findings.add(
                        f"line={line}:{executable}:{destination}:{','.join(terms)}"
                    )
        for token in tokens:
            if token.startswith("of="):
                destination = token[3:]
                terms = sensitive(destination)
                if terms:
                    findings.add(
                        f"line={line}:dd:{destination}:{','.join(terms)}"
                    )
    return tuple(sorted(findings))


def authority_fingerprint(
    *,
    reachable_sensitive: list[str],
    python_write_sinks: list[str],
    shell_write_sinks: list[str],
) -> str:
    return canonical_sha256(
        {
            "reachable_sensitive": sorted(reachable_sensitive),
            "python_write_sinks": sorted(python_write_sinks),
            "shell_write_sinks": sorted(shell_write_sinks),
        }
    )


def workflow_local_references(
    path: str,
    text: str,
    sources: Mapping[str, str],
    known_paths: set[str],
) -> set[str]:
    references = set(python_entrypoints(text))
    for invocation in python_invocations(text):
        if invocation["entrypoint"] != "-c" or not invocation["command_source"]:
            continue
        references.update(
            local_import_paths(
                str(invocation["command_source"]),
                f"{path}::command:{invocation['line']}",
                sources,
                known_paths,
            )
        )
    for block in inline_python_blocks(text):
        references.update(
            local_import_paths(
                str(block["source"]),
                f"{path}::inline:{block['line']}",
                sources,
                known_paths,
            )
        )
    return references


def workflow_dispatch_input_default(text: str, input_name: str) -> str | None:
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
        value = payload["on"]["workflow_dispatch"]["inputs"][input_name]["default"]
    except (KeyError, TypeError, yaml.YAMLError):
        return None
    return str(value).casefold()


@lru_cache(maxsize=512)
def workflow_run_text(text: str) -> str:
    """Return only executable GitHub Actions `run` blocks, fail-open to raw fixtures."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, dict):
            return text
        blocks: list[str] = []
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if isinstance(step, dict) and isinstance(step.get("run"), str):
                    blocks.append(str(step["run"]))
        return "\n".join(blocks)
    except (TypeError, yaml.YAMLError):
        return text


def audit_texts(
    contract: Mapping[str, Any],
    workflows: Mapping[str, str],
    accepted_files: Mapping[str, str],
    known_python_paths: set[str] | None = None,
) -> dict[str, Any]:
    validate_contract(contract)
    known_paths = set(accepted_files) if known_python_paths is None else set(known_python_paths)
    executable_workflows = {
        path: workflow_run_text(text) for path, text in workflows.items()
    }
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    expected_workflow_hashes = contract.get("tracked_workflow_sha256") or {}
    observed_workflow_hashes = {
        path: text_sha256(text) for path, text in sorted(workflows.items())
    }
    if sorted(expected_workflow_hashes) != sorted(observed_workflow_hashes):
        failures.append(
            "tracked_workflow_set_mismatch:"
            f"expected={','.join(sorted(expected_workflow_hashes))}:"
            f"observed={','.join(sorted(observed_workflow_hashes))}"
        )
    for path, observed_hash in observed_workflow_hashes.items():
        expected_hash = str(expected_workflow_hashes.get(path) or "")
        if observed_hash != expected_hash:
            failures.append(
                f"tracked_workflow_hash_mismatch:{path}:"
                f"expected={expected_hash}:observed={observed_hash}"
            )
    roles = contract.get("workflow_roles") or {}
    if sorted(roles) != sorted(workflows):
        failures.append(
            "workflow_role_set_mismatch:"
            f"expected={','.join(sorted(workflows))}:"
            f"observed={','.join(sorted(roles))}"
        )
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
        for path, text in sorted(executable_workflows.items()):
            lines = executable_invocations(text, entrypoint)
            embedded_lines: list[int] = []
            for source in embedded_python_sources(text):
                call_counts = dict(python_main_call_counts(str(source["source"])))
                embedded_lines.extend(
                    [int(source["line"])] * int(call_counts.get(entrypoint, 0))
                )
            if not lines and not embedded_lines:
                continue
            observed.append(path)
            invocation_count += len(lines) + len(embedded_lines)
            records.append(
                {
                    "entrypoint": entrypoint,
                    "role": role,
                    "workflow": path,
                    "line_numbers": lines,
                    "embedded_main_call_lines": embedded_lines,
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

    for requirement in contract.get("required_workflow_input_defaults") or []:
        path = str(requirement.get("workflow") or "")
        input_name = str(requirement.get("input") or "")
        expected = str(requirement.get("expected") or "").casefold()
        observed = workflow_dispatch_input_default(
            workflows.get(path, ""), input_name
        )
        if observed != expected:
            failures.append(
                f"workflow_input_default_mismatch:{path}:{input_name}:"
                f"expected={expected}:observed={observed}"
            )

    for path, tokens in sorted((contract.get("required_workflow_tokens") or {}).items()):
        text = noncomment_text(workflows.get(path, ""))
        for token in tokens:
            if str(token) not in text:
                failures.append(f"required_workflow_token_missing:{path}:{token}")

    for requirement in contract.get("required_shell_boolean_flag_derivations") or []:
        path = str(requirement.get("workflow") or "")
        variable = str(requirement.get("variable") or "")
        input_name = str(requirement.get("input") or "")
        enabled_value = str(requirement.get("enabled_value") or "")
        if not shell_boolean_flag_guard_matches(
            executable_workflows.get(path, ""),
            variable=variable,
            input_name=input_name,
            enabled_value=enabled_value,
            allowed_occurrence_lines=[
                str(value)
                for value in requirement.get("allowed_occurrence_lines") or []
            ],
        ):
            failures.append(
                f"workflow_shell_flag_derivation_mismatch:{path}:{variable}:"
                f"input={input_name}:enabled={enabled_value}"
            )

    for requirement in contract.get("required_shell_variable_occurrences") or []:
        path = str(requirement.get("workflow") or "")
        variable = str(requirement.get("variable") or "")
        expected_lines = sorted(
            str(value) for value in requirement.get("allowed_occurrence_lines") or []
        )
        observed_lines = shell_variable_occurrence_lines(
            executable_workflows.get(path, ""), variable
        )
        if observed_lines != expected_lines:
            failures.append(
                f"workflow_shell_variable_occurrence_mismatch:{path}:{variable}:"
                f"expected={canonical_sha256(expected_lines)}:"
                f"observed={canonical_sha256(observed_lines)}"
            )

    profile_coverage: dict[tuple[str, str, str], dict[int, int]] = {}
    profile_actual_counts: dict[tuple[str, str, str], int] = {}
    for requirement in contract.get("required_executable_commands") or []:
        path = str(requirement.get("workflow") or "")
        entrypoint = str(requirement.get("entrypoint") or "")
        command_rows = [
            row
            for row in python_invocations(executable_workflows.get(path, ""))
            if row["entrypoint"] == entrypoint
        ]
        matches = [
            (index, int(row["line"]), list(row["argv"]))
            for index, row in enumerate(command_rows)
            if invocation_matches_requirement(list(row["argv"]), requirement)
        ]
        exact_matches = int(requirement.get("exact_match_count", 1))
        if len(matches) != exact_matches:
            failures.append(
                f"required_executable_command_mismatch:{path}:{entrypoint}:"
                f"expected_matches={exact_matches}:observed_matches={len(matches)}"
            )
        profile_group = str(requirement.get("exclusive_profile_group") or "")
        if profile_group:
            key = (path, entrypoint, profile_group)
            profile_actual_counts[key] = len(command_rows)
            coverage = profile_coverage.setdefault(key, {})
            for index, _line, _argv in matches:
                coverage[index] = coverage.get(index, 0) + 1

    for key, actual_count in sorted(profile_actual_counts.items()):
        coverage = profile_coverage.get(key, {})
        if set(coverage) != set(range(actual_count)) or any(
            count != 1 for count in coverage.values()
        ):
            path, entrypoint, group = key
            rendered = ",".join(
                f"{index}:{coverage.get(index, 0)}"
                for index in range(actual_count)
            )
            failures.append(
                f"exclusive_invocation_profile_mismatch:{path}:{entrypoint}:"
                f"group={group}:coverage={rendered}"
            )

    forbidden = tuple(contract.get("forbidden_accepted_path_tokens") or [])
    for path in contract.get("accepted_path_files") or []:
        text = accepted_files.get(path)
        if text is None:
            failures.append(f"accepted_path_file_missing:{path}")

    accepted_workflow = str(contract.get("accepted_daily_workflow") or "")
    inline_blocks = inline_python_blocks(executable_workflows.get(accepted_workflow, ""))
    inline_local_paths: set[str] = set()
    for block in inline_blocks:
        source = str(block["source"])
        virtual_path = f"{accepted_workflow}::inline:{block['line']}"
        inline_local_paths.update(
            local_import_paths(source, virtual_path, accepted_files, known_paths)
        )
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

    observed_sensitive = sorted(
        entrypoint
        for entrypoint in python_entrypoints(executable_workflows.get(accepted_workflow, ""))
        if authority_sensitive(entrypoint, contract)
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

    observed_local_entrypoints = sorted(
        entrypoint
        for entrypoint in python_entrypoints(executable_workflows.get(accepted_workflow, ""))
        if entrypoint in known_paths
    )
    expected_local_entrypoints = sorted(
        set(contract.get("accepted_workflow_local_entrypoints") or [])
    )
    if observed_local_entrypoints != expected_local_entrypoints:
        failures.append(
            "accepted_workflow_local_entrypoint_mismatch:"
            f"expected={','.join(expected_local_entrypoints)}:"
            f"observed={','.join(observed_local_entrypoints)}"
        )

    expected_by_workflow = contract.get("workflow_authority_sensitive_entrypoints") or {}
    expected_no_writer_reachable = (
        contract.get("no_writer_reachable_authority_sensitive_modules") or {}
    )
    expected_no_writer_write_sinks = (
        contract.get("no_writer_authority_write_sinks") or {}
    )
    expected_authority_fingerprints = (
        contract.get("workflow_authority_fingerprints") or {}
    )
    if sorted(expected_authority_fingerprints) != sorted(workflows):
        failures.append("workflow_authority_fingerprint_set_mismatch")
    observed_by_workflow: dict[str, list[str]] = {}
    observed_no_writer_reachable: dict[str, list[str]] = {}
    workflow_python_reachable: dict[str, list[str]] = {}
    no_writer_authority_write_sinks: dict[str, list[str]] = {}
    workflow_python_authority_write_sinks: dict[str, list[str]] = {}
    workflow_shell_authority_write_sinks: dict[str, list[str]] = {}
    observed_authority_fingerprints: dict[str, str] = {}
    local_references_by_workflow: dict[str, set[str]] = {}
    sensitive_terms = tuple(
        sorted(
            {
                str(term).casefold()
                for term in contract.get("authority_sensitive_name_terms") or []
                if str(term)
            }
        )
    )
    for path, text in sorted(executable_workflows.items()):
        references = workflow_local_references(path, text, accepted_files, known_paths)
        local_references_by_workflow[path] = references
        sensitive = sorted(
            reference for reference in references if authority_sensitive(reference, contract)
        )
        workflow_reachable, _workflow_parents = reachable_python_paths(
            {reference for reference in references if reference in known_paths},
            accepted_files,
            known_paths,
        )
        workflow_python_reachable[path] = sorted(workflow_reachable)
        reachable_sensitive = sorted(
            reference
            for reference in workflow_reachable
            if authority_sensitive(reference, contract)
        )
        python_write_findings = sorted(
            f"{source_path}:{finding}"
            for source_path in workflow_reachable
            if source_path in accepted_files
            for finding in authority_write_sinks(
                accepted_files[source_path], sensitive_terms
            )
        )
        shell_write_findings = list(
            shell_authority_write_sinks(text, sensitive_terms)
        )
        if python_write_findings:
            workflow_python_authority_write_sinks[path] = python_write_findings
        if shell_write_findings:
            workflow_shell_authority_write_sinks[path] = shell_write_findings
        fingerprint = authority_fingerprint(
            reachable_sensitive=reachable_sensitive,
            python_write_sinks=python_write_findings,
            shell_write_sinks=shell_write_findings,
        )
        observed_authority_fingerprints[path] = fingerprint
        expected_fingerprint = str(expected_authority_fingerprints.get(path) or "")
        if fingerprint != expected_fingerprint:
            failures.append(
                f"workflow_authority_fingerprint_mismatch:{path}:"
                f"expected={expected_fingerprint}:observed={fingerprint}"
            )
        if reachable_sensitive and path not in roles:
            failures.append(f"reachable_authority_workflow_role_missing:{path}")
        if sensitive:
            observed_by_workflow[path] = sensitive
            if path not in roles:
                failures.append(f"authority_sensitive_workflow_role_missing:{path}")
        expected = sorted(set(expected_by_workflow.get(path) or []))
        if sensitive != expected:
            failures.append(
                f"workflow_authority_sensitive_mismatch:{path}:"
                f"expected={','.join(expected)}:observed={','.join(sensitive)}"
            )
        role = str(roles.get(path) or "")
        if role.endswith("_no_target_writer"):
            observed_no_writer_reachable[path] = reachable_sensitive
            expected_reachable = sorted(
                set(expected_no_writer_reachable.get(path) or [])
            )
            if reachable_sensitive != expected_reachable:
                failures.append(
                    f"no_writer_reachable_authority_mismatch:{path}:"
                    f"expected={','.join(expected_reachable)}:"
                    f"observed={','.join(reachable_sensitive)}"
                )
            write_findings = python_write_findings
            if write_findings:
                no_writer_authority_write_sinks[path] = write_findings
            expected_write_findings = sorted(
                set(expected_no_writer_write_sinks.get(path) or [])
            )
            if write_findings != expected_write_findings:
                failures.append(
                    f"no_writer_authority_write_sink:{path}:"
                    f"expected={','.join(expected_write_findings)}:"
                    f"observed={','.join(write_findings)}"
                )

    root_paths = {
        str(path)
        for path in contract.get("accepted_path_files") or []
        if str(path).endswith(".py")
    }
    root_paths.update(inline_local_paths)
    root_paths.update(
        reference
        for reference in local_references_by_workflow.get(accepted_workflow, set())
        if reference in known_paths
    )
    reachable, import_parents = reachable_python_paths(
        root_paths, accepted_files, known_paths
    )
    legacy_paths: list[str] = []
    for path in sorted(reachable):
        if path not in accepted_files:
            failures.append(f"reachable_python_file_missing:{path}")
            continue
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

    reachable_sensitive = sorted(
        path for path in reachable if authority_sensitive(path, contract)
    )
    expected_reachable_sensitive = sorted(
        set(contract.get("accepted_reachable_authority_sensitive_modules") or [])
    )
    if reachable_sensitive != expected_reachable_sensitive:
        failures.append(
            "accepted_reachable_authority_sensitive_mismatch:"
            f"expected={','.join(expected_reachable_sensitive)}:"
            f"observed={','.join(reachable_sensitive)}"
        )

    authority = contract.get("writer_authority") or {}
    accepted_entrypoint = str(authority.get("accepted_current_target_writer") or "")
    if not any(
        row["entrypoint"] == accepted_entrypoint
        and row["workflow"] == accepted_workflow
        for row in records
    ):
        failures.append("accepted_daily_writer_binding_missing")
    return {
        "schema_version": "run287-dynamic-portfolio-call-path-audit-v1",
        "status": PASS_STATUS if not failures else BLOCKED_STATUS,
        "contract_sha256": canonical_sha256(contract),
        "tracked_workflow_count": len(workflows),
        "accepted_daily_workflow": accepted_workflow,
        "accepted_current_target_writer": accepted_entrypoint,
        "accepted_workflow_authority_sensitive_entrypoints": observed_sensitive,
        "accepted_workflow_local_entrypoints": observed_local_entrypoints,
        "workflow_authority_sensitive_entrypoints": observed_by_workflow,
        "workflow_authority_fingerprints": observed_authority_fingerprints,
        "workflow_python_authority_write_sinks": (
            workflow_python_authority_write_sinks
        ),
        "workflow_shell_authority_write_sinks": (
            workflow_shell_authority_write_sinks
        ),
        "workflow_python_reachable_files": workflow_python_reachable,
        "no_writer_reachable_authority_sensitive_modules": (
            observed_no_writer_reachable
        ),
        "no_writer_authority_write_sinks": no_writer_authority_write_sinks,
        "accepted_workflow_inline_local_imports": observed_inline,
        "accepted_python_reachable_files": sorted(reachable),
        "accepted_reachable_authority_sensitive_modules": reachable_sensitive,
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


def git_path_tracked_at_head(root: Path, path: str) -> bool:
    normalized = str(path).replace("\\", "/")
    try:
        subprocess.check_output(
            ["git", "ls-files", "--error-unmatch", "--", normalized],
            cwd=root,
            timeout=30,
            stderr=subprocess.DEVNULL,
        )
        subprocess.check_call(
            ["git", "cat-file", "-e", f"HEAD:{normalized}"],
            cwd=root,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def run_audit(
    root: Path,
    contract: Mapping[str, Any],
    *,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    tracked = tracked_workflow_paths(root)
    workflows = workflow_texts(root, tracked)
    python_paths = set(tracked_python_paths(root))
    python_sources = {
        path: (root / path).read_text(encoding="utf-8")
        for path in sorted(python_paths)
        if (root / path).is_file()
    }
    accepted_files = {**python_sources, **workflows}
    result = audit_texts(
        contract,
        workflows,
        accepted_files,
        known_python_paths=python_paths,
    )
    relevant = list(tracked)
    relevant.extend(result.get("accepted_python_reachable_files") or [])
    for reachable_files in (
        result.get("workflow_python_reachable_files") or {}
    ).values():
        relevant.extend(str(path) for path in reachable_files)
    relevant.extend(str(path) for path in contract.get("accepted_path_files") or [])
    tool_path = Path(__file__).resolve()
    result["audit_runtime_path"] = str(tool_path)
    result["audit_runtime_sha256"] = hashlib.sha256(tool_path.read_bytes()).hexdigest()
    try:
        relevant.append(tool_path.relative_to(root).as_posix())
    except ValueError:
        result["audit_runtime_head_bound"] = False
        result["failures"].append("audit_runtime_outside_selected_repository")
    else:
        result["audit_runtime_head_bound"] = True
        runtime_relative = tool_path.relative_to(root).as_posix()
        if not git_path_tracked_at_head(root, runtime_relative):
            result["audit_runtime_head_bound"] = False
            result["failures"].append("audit_runtime_not_tracked_at_head")
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
