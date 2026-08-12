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
HEREDOC_WORD = re.compile(
    r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|\\([^\s;&|<>]+)|([^\s;&|<>]+))"
)


def heredoc_delimiter(match: re.Match[str]) -> str:
    return next((value for value in match.groups() if value is not None), "")


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


def tracked_file_paths(root: Path) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-files"],
            cwd=root,
            timeout=30,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
        return sorted({
            line.strip().replace("\\", "/")
            for line in raw.splitlines()
            if line.strip()
        })
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )


def tracked_shell_paths(root: Path) -> list[str]:
    """Discover tracked shell sources, including arbitrary interpreter operands."""
    tracked = set(tracked_file_paths(root))
    paths = {
        path
        for path in tracked
        if path.endswith(".sh") or (
            not Path(path).suffix and not path.endswith((".py", ".yml", ".yaml"))
        )
    }
    seed_paths = {
        path
        for path in tracked
        if path.endswith((".py", ".yml", ".yaml")) or path in paths
    }
    texts: dict[str, str] = {}
    for path in sorted(seed_paths):
        try:
            texts[path] = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    by_name: dict[str, list[str]] = {}
    for path in tracked:
        by_name.setdefault(Path(path).name, []).append(path)
    inspected: set[str] = set()
    while True:
        candidates: set[str] = set()
        for path, source in list(texts.items()):
            if path in inspected:
                continue
            inspected.add(path)
            if path.endswith((".yml", ".yaml")):
                for _shell, run_source, _workdir in workflow_run_records(source):
                    candidates.update(shell_script_candidates(run_source))
            else:
                candidates.update(shell_script_candidates(source))
            if path.endswith(".py"):
                candidates.update(local_process_shell_candidates(source))
        new_paths: set[str] = set()
        for candidate in candidates:
            matches = (
                [candidate]
                if candidate in tracked
                else by_name.get(Path(candidate).name, [])
            )
            if len(matches) != 1:
                continue
            path = matches[0]
            if path.endswith((".py", ".yml", ".yaml")) or path in paths:
                continue
            try:
                raw_bytes = (root / path).read_bytes()
                source = raw_bytes.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if b"\x00" in raw_bytes:
                continue
            texts[path] = source
            new_paths.add(path)
        paths.update(new_paths)
        if not new_paths:
            break
    return sorted(paths)


def tracked_shell_texts(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in tracked_shell_paths(root):
        try:
            result[path] = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    return result


def tracked_local_action_paths(root: Path) -> list[str]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "--", "*action.yml", "*action.yaml"],
            cwd=root,
            timeout=30,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
        return sorted(
            {
                line.strip().replace("\\", "/")
                for line in raw.splitlines()
                if line.strip()
            }
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return []


def local_action_implementation_paths(
    action_path: str, text: str, known_paths: set[str]
) -> set[str]:
    """Resolve Node/Docker action implementation files relative to action.yml."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return set()
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not isinstance(runs, dict):
        return set()
    action_dir = Path(action_path).parent
    candidates: set[str] = set()
    for field in ("main", "pre", "post"):
        value = runs.get(field)
        if isinstance(value, str) and value and not value.startswith("docker://"):
            candidates.add(Path(action_dir, value).as_posix())
    using = str(runs.get("using") or "").casefold()
    image = str(runs.get("image") or "")
    if using == "docker" and image and not image.startswith("docker://"):
        candidates.add(Path(action_dir, image).as_posix())
    return {candidate for candidate in candidates if candidate in known_paths}


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


def resolve_working_directory_path(value: str, working_directory: str = "") -> str:
    normalized = normalize_script_entrypoint(value)
    working = normalize_script_entrypoint(working_directory)
    if (
        not working
        or not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or normalized.startswith("${{")
    ):
        return normalized
    return Path(working, normalized).as_posix()


SHELL_COMMAND_BOUNDARIES = {";", "&&", "||", "|", "&"}
SHELL_ASSIGNMENT_WORD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", re.DOTALL)


def shell_command_position(tokens: list[str], index: int) -> bool:
    """Return whether *index* is the executable after assignments/wrappers."""
    start = 0
    for cursor in range(index - 1, -1, -1):
        if tokens[cursor] in SHELL_COMMAND_BOUNDARIES:
            start = cursor + 1
            break
    cursor = start
    while cursor < index:
        token = tokens[cursor]
        executable = token.rsplit("/", 1)[-1]
        if SHELL_ASSIGNMENT_WORD.fullmatch(token):
            cursor += 1
            continue
        if executable == "exec":
            cursor += 1
            while cursor < index:
                value = tokens[cursor]
                if value == "-a":
                    cursor += 2
                    continue
                if value.startswith("-"):
                    cursor += 1
                    continue
                break
            continue
        if executable in {"command", "builtin", "nohup", "time"}:
            cursor += 1
            while cursor < index:
                value = tokens[cursor]
                if executable == "time" and value in {"-f", "--format", "-o", "--output"}:
                    cursor += 2
                    continue
                if value.startswith("-"):
                    cursor += 1
                    continue
                break
            continue
        if executable == "env":
            cursor += 1
            while cursor < index:
                value = tokens[cursor]
                if SHELL_ASSIGNMENT_WORD.fullmatch(value):
                    cursor += 1
                    continue
                if value in {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}:
                    cursor += 2
                    continue
                if value.startswith("--split-string="):
                    cursor += 1
                    continue
                if value.startswith("-"):
                    cursor += 1
                    continue
                break
            continue
        return False
    return cursor == index


@lru_cache(maxsize=512)
def python_invocations(text: str) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    literal_names: dict[str, str] = {}
    boundaries = SHELL_COMMAND_BOUNDARIES
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
        for token in tokens:
            if SHELL_ASSIGNMENT_WORD.fullmatch(token):
                name, value = token.split("=", 1)
                if not re.search(r"[$`]", value):
                    literal_names[name] = value

        def resolved_token(value: str) -> str:
            match = re.fullmatch(
                r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
                value,
            )
            if not match:
                return value
            return literal_names.get(match.group(1) or match.group(2), value)

        for index, token in enumerate(tokens):
            shell_name = token.rsplit("/", 1)[-1]
            if shell_name in {"bash", "sh", "dash", "zsh", "ksh"}:
                for option_index in range(index + 1, len(tokens) - 1):
                    if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", tokens[option_index]):
                        nested_source = resolved_token(tokens[option_index + 1])
                        nested = python_invocations(nested_source)
                        for row in nested:
                            copied = dict(row)
                            copied["line"] = line
                            copied["wrapped_by"] = shell_name
                            result.append(copied)
                        break
            executable = resolved_token(token).rsplit("/", 1)[-1]
            if executable == "env" and shell_command_position(tokens, index):
                cursor = index + 1
                while cursor < len(tokens):
                    value = tokens[cursor]
                    split_source = ""
                    if value in {"-S", "--split-string"} and cursor + 1 < len(tokens):
                        split_source = tokens[cursor + 1]
                    elif value.startswith("--split-string="):
                        split_source = value.split("=", 1)[1]
                    if split_source:
                        for row in python_invocations(split_source):
                            copied = dict(row)
                            copied["line"] = line
                            copied["wrapped_by"] = "env-split-string"
                            result.append(copied)
                        break
                    if not value.startswith("-") and not SHELL_ASSIGNMENT_WORD.fullmatch(value):
                        break
                    cursor += 1
            if (
                not SHELL_ASSIGNMENT_WORD.fullmatch(token)
                and
                "/" in resolved_token(token).replace("\\", "/")
                and resolved_token(token).endswith(".py")
                and shell_command_position(tokens, index)
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
                        "entrypoint": normalize_script_entrypoint(resolved_token(token)),
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
                value = resolved_token(argv[cursor])
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
    heredoc = HEREDOC_WORD
    while index < len(lines):
        start = index
        command_parts: list[str] = []
        delimiter = ""
        while index < len(lines):
            command_parts.append(lines[index].strip())
            match = heredoc.search(lines[index])
            if match:
                delimiter = heredoc_delimiter(match)
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
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(node, ast.Assign):
                pairs.extend((target, node.value) for target in node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                pairs.append((node.target, node.value))
            elif isinstance(node, ast.NamedExpr):
                pairs.append((node.target, node.value))
            expanded: list[tuple[ast.AST, ast.AST]] = []
            while pairs:
                target, value = pairs.pop()
                if (
                    isinstance(target, (ast.Tuple, ast.List))
                    and isinstance(value, (ast.Tuple, ast.List))
                    and len(target.elts) == len(value.elts)
                ):
                    pairs.extend(zip(target.elts, value.elts))
                else:
                    expanded.append((target, value))
            for target, value in expanded:
                if (
                    isinstance(target, ast.Name)
                    and dotted_expression_name(value) in callables
                    and target.id not in callables
                ):
                    callables.add(target.id)
                    changed = True
    return callables


def literal_dynamic_import_module(
    node: ast.AST,
    callables: set[str] | None = None,
    source_path: str = "",
) -> str:
    """Resolve common dynamic imports only when their module is a literal."""
    if not isinstance(node, ast.Call) or not node.args:
        return ""
    first = node.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return ""
    func = dotted_expression_name(node.func)
    if func in (callables or {"importlib.import_module", "__import__", "builtins.__import__"}):
        module = first.value
        if not module.startswith("."):
            return module
        package = ""
        for keyword in node.keywords:
            if (
                keyword.arg == "package"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                package = keyword.value.value
        if not package and source_path:
            concrete_path = source_path.split("::", 1)[0]
            package = ".".join(Path(concrete_path).with_suffix("").parts[:-1])
        if not package:
            return ""
        level = len(module) - len(module.lstrip("."))
        tail = module[level:]
        package_parts = package.split(".")
        keep = max(0, len(package_parts) - level + 1)
        parts = package_parts[:keep]
        if tail:
            parts.extend(tail.split("."))
        return ".".join(parts)
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
    run_path_callables = {"runpy.run_path"}
    run_module_callables = {"runpy.run_module"}
    for imported in ast.walk(tree):
        if isinstance(imported, ast.Import):
            for alias in imported.names:
                if alias.name == "runpy":
                    local = alias.asname or alias.name
                    run_path_callables.add(f"{local}.run_path")
                    run_module_callables.add(f"{local}.run_module")
        elif isinstance(imported, ast.ImportFrom) and imported.module == "runpy":
            for alias in imported.names:
                if alias.name == "run_path":
                    run_path_callables.add(alias.asname or alias.name)
                elif alias.name == "run_module":
                    run_module_callables.add(alias.asname or alias.name)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(node, ast.Assign):
                pairs.extend((target, node.value) for target in node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                pairs.append((node.target, node.value))
            elif isinstance(node, ast.NamedExpr):
                pairs.append((node.target, node.value))
            for target, value in pairs:
                if not isinstance(target, ast.Name):
                    continue
                dotted = dotted_expression_name(value)
                if dotted in run_path_callables and target.id not in run_path_callables:
                    run_path_callables.add(target.id)
                    changed = True
                if dotted in run_module_callables and target.id not in run_module_callables:
                    run_module_callables.add(target.id)
                    changed = True
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
            dynamic_module = literal_dynamic_import_module(
                node, dynamic_callables, source_path
            )
            if dynamic_module:
                candidates.append(dynamic_module)
            call_name = dotted_expression_name(node.func)
            if node.args and call_name in run_module_callables:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    candidates.append(value.value)
            elif node.args and call_name in run_path_callables:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    result.add(normalize_script_entrypoint(value.value))
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


PROCESS_CALL_BASENAMES = {
    "run", "_run", "popen", "call", "check_call", "check_output",
    "getoutput", "getstatusoutput", "run_command", "execute", "exec_command",
    "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
    "execlpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv",
    "spawnve", "spawnvp", "spawnvpe", "posix_spawn", "posix_spawnp",
}


def process_argv_expressions(node: ast.Call) -> tuple[ast.AST, ...]:
    """Return argv-bearing expressions for subprocess and os exec/spawn APIs."""
    basename = dotted_expression_name(node.func).casefold().rsplit(".", 1)[-1]
    if basename in {"execv", "execve", "execvp", "execvpe"}:
        return tuple(node.args[1:2])
    if basename in {"spawnv", "spawnve", "spawnvp", "spawnvpe"}:
        return tuple(node.args[2:3])
    if basename in {"posix_spawn", "posix_spawnp"}:
        return tuple(node.args[1:2])
    if basename in {
        "execl", "execle", "execlp", "execlpe", "spawnl", "spawnle",
        "spawnlp", "spawnlpe",
    }:
        offset = 2 if basename.startswith("spawn") else 1
        return tuple(node.args[offset:])
    if node.args:
        return (node.args[0],)
    keyword = next(
        (keyword.value for keyword in node.keywords if keyword.arg == "args"),
        None,
    )
    return (keyword,) if keyword is not None else ()


@lru_cache(maxsize=4096)
def local_process_candidates(source: str) -> tuple[str, ...]:
    """Return literal Python entrypoints passed through process-launch calls."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments.setdefault(node.target.id, []).append(node.value)

    expressions: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_expression_name(node.func).casefold()
        basename = name.rsplit(".", 1)[-1]
        if basename not in PROCESS_CALL_BASENAMES:
            continue
        argv_expressions = process_argv_expressions(node)
        if not argv_expressions:
            continue
        for expression in argv_expressions:
            if isinstance(expression, ast.Name) and expression.id in assignments:
                expressions.extend(assignments[expression.id])
            else:
                expressions.append(expression)

    candidates: set[str] = set()
    for expression in expressions:
        strings = [
            str(node.value)
            for node in ast.walk(expression)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        for index, value in enumerate(strings):
            normalized = normalize_script_entrypoint(value)
            if normalized.endswith(".py"):
                candidates.add(normalized)
            if value == "-m" and index + 1 < len(strings):
                candidates.add(module_entrypoint(strings[index + 1]))
            candidates.update(python_entrypoints(value))
    return tuple(sorted(candidates))


def local_process_paths(
    source: str, known_paths: set[str], working_directory: str = ""
) -> set[str]:
    result: set[str] = set()
    for candidate in local_process_candidates(source):
        candidate = resolve_working_directory_path(candidate, working_directory)
        if candidate in known_paths:
            result.add(candidate)
            continue
        matches = sorted(
            path for path in known_paths if Path(path).name == Path(candidate).name
        )
        if len(matches) == 1:
            result.add(matches[0])
    return result


@lru_cache(maxsize=4096)
def local_process_shell_candidates(source: str) -> tuple[str, ...]:
    """Return literal shell executables/scripts in process argv expressions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    candidates: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        basename = dotted_expression_name(node.func).casefold().rsplit(".", 1)[-1]
        if basename not in PROCESS_CALL_BASENAMES:
            continue
        for expression in process_argv_expressions(node):
            strings = [
                str(value.value)
                for value in ast.walk(expression)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ]
            for command_text in strings:
                if re.search(r"\s|[;&|<>]", command_text):
                    candidates.update(shell_script_candidates(command_text))
            if not strings:
                continue
            first = normalize_script_entrypoint(strings[0])
            first_name = first.rsplit("/", 1)[-1]
            first_suffix = Path(first).suffix.casefold()
            if (
                "/" in first
                and not first.endswith(".py")
                and (not first_suffix or first_suffix in {".sh", ".bash", ".zsh", ".ksh"})
            ):
                candidates.add(first)
            if first_name not in {"bash", "sh", "dash", "zsh", "ksh"}:
                continue
            cursor = 1
            while cursor < len(strings):
                value = strings[cursor]
                if value == "-c" or (
                    value.startswith("-") and "c" in value[1:]
                ):
                    if cursor + 1 < len(strings):
                        candidates.update(shell_script_candidates(strings[cursor + 1]))
                    break
                if value.startswith("-"):
                    cursor += 1
                    continue
                candidates.add(normalize_script_entrypoint(value))
                break
    return tuple(sorted(candidates))


def local_process_shell_paths(
    source: str, known_paths: set[str], working_directory: str = ""
) -> set[str]:
    """Return tracked shell files named anywhere in a process argv expression."""
    result: set[str] = set()
    by_name: dict[str, list[str]] = {}
    for path in known_paths:
        by_name.setdefault(Path(path).name, []).append(path)
    for candidate in local_process_shell_candidates(source):
        candidate = resolve_working_directory_path(candidate, working_directory)
        if candidate in known_paths:
            result.add(candidate)
            continue
        matches = by_name.get(Path(candidate).name, [])
        if len(matches) == 1:
            result.add(matches[0])
    return result


@lru_cache(maxsize=4096)
def python_process_launches(source: str) -> tuple[str, ...]:
    """Fingerprint process launches, including unresolved dynamic argv."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    os_process_names = {
        "system", "popen", "execv", "execve", "execvp", "execvpe", "execl",
        "execle", "execlp", "execlpe", "spawnl", "spawnle", "spawnlp",
        "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "posix_spawn", "posix_spawnp",
    }
    callables = {
        "subprocess.run", "subprocess.popen", "subprocess.call",
        "subprocess.check_call", "subprocess.check_output", "subprocess.getoutput",
        "subprocess.getstatusoutput", "os.system",
        "os.popen",
    }
    callables.update(f"os.{name}" for name in os_process_names)
    wrappers = {"_run", "run_command", "execute", "exec_command"} | os_process_names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "subprocess":
                    callables.update(
                        f"{local}.{name}"
                        for name in (
                            "run", "Popen", "call", "check_call", "check_output",
                            "getoutput", "getstatusoutput",
                        )
                    )
                elif alias.name == "os":
                    callables.update(f"{local}.{name}" for name in os_process_names)
        elif isinstance(node, ast.ImportFrom) and node.module in {"subprocess", "os"}:
            for alias in node.names:
                if alias.name in {
                    "run", "Popen", "call", "check_call", "check_output",
                    "getoutput", "getstatusoutput",
                } | os_process_names:
                    callables.add(alias.asname or alias.name)
    normalized_callables = {value.casefold() for value in callables}
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments.setdefault(node.target.id, []).append(node.value)
    findings: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_expression_name(node.func)
        if (
            name.casefold() not in normalized_callables
            and name.rsplit(".", 1)[-1].casefold() not in wrappers
        ):
            continue
        argv_expressions = process_argv_expressions(node)
        if not argv_expressions:
            continue
        expressions: list[ast.AST] = []
        for expression in argv_expressions:
            expressions.extend(
                assignments.get(expression.id, [expression])
                if isinstance(expression, ast.Name)
                else [expression]
            )
        # ``ast.dump`` is not a stable serialization contract across Python
        # minor versions.  PR validation runs on 3.12 while developer hosts
        # may be newer, so bind the exact source expression instead.  Parsed
        # nodes have end-position metadata; the full source is a fail-closed
        # fallback for synthetic or otherwise unlocatable nodes.
        for expression in expressions:
            expression_source = ast.get_source_segment(source, expression) or source
            expression_source = expression_source.replace("\r\n", "\n").replace(
                "\r", "\n"
            )
            expression_hash = hashlib.sha256(
                expression_source.strip().encode("utf-8")
            ).hexdigest()[:16]
            candidates = sorted(
                {
                    normalize_script_entrypoint(str(value.value))
                    for value in ast.walk(expression)
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and str(value.value).endswith(".py")
                }
            )
            detail = ",".join(candidates) if candidates else "UNRESOLVED_LOCAL_PROCESS"
            findings.add(
                f"line={getattr(node, 'lineno', 0)}:{name or '<call>'}:"
                f"argv={expression_hash}:{detail}"
            )
    return tuple(sorted(findings))


@lru_cache(maxsize=2048)
def python_main_call_counts(
    source: str, source_path: str = ""
) -> tuple[tuple[str, int], ...]:
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

    def main_target(value: ast.AST) -> str:
        if isinstance(value, ast.Name):
            return names.get(value.id, "")
        if isinstance(value, ast.Attribute) and value.attr == "main":
            target = modules.get(dotted_expression_name(value.value), "")
            if target:
                return target
            dynamic_module = literal_dynamic_import_module(
                value.value, dynamic_callables, source_path
            )
            return module_entrypoint(dynamic_module) if dynamic_module else ""
        if (
            isinstance(value, ast.Call)
            and dotted_expression_name(value.func) in {"getattr", "builtins.getattr"}
            and len(value.args) >= 2
            and isinstance(value.args[1], ast.Constant)
            and value.args[1].value == "main"
        ):
            module_expression = value.args[0]
            target = modules.get(dotted_expression_name(module_expression), "")
            if target:
                return target
            dynamic_module = literal_dynamic_import_module(
                module_expression, dynamic_callables, source_path
            )
            return module_entrypoint(dynamic_module) if dynamic_module else ""
        return ""

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(node, ast.Assign):
                pairs.extend((target, node.value) for target in node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                pairs.append((node.target, node.value))
            elif isinstance(node, ast.NamedExpr):
                pairs.append((node.target, node.value))
            while pairs:
                target_node, value_node = pairs.pop()
                if (
                    isinstance(target_node, (ast.Tuple, ast.List))
                    and isinstance(value_node, (ast.Tuple, ast.List))
                    and len(target_node.elts) == len(value_node.elts)
                ):
                    pairs.extend(zip(target_node.elts, value_node.elts))
                    continue
                if isinstance(target_node, ast.Name):
                    target = main_target(value_node)
                    if target and names.get(target_node.id) != target:
                        names[target_node.id] = target
                        changed = True
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = main_target(node.func)
        if target:
            counts[target] = counts.get(target, 0) + 1
    return tuple(sorted(counts.items()))


def dotted_expression_name(node: ast.AST) -> str:
    """Return a dotted Name/Attribute expression, or an empty string."""
    if isinstance(node, ast.NamedExpr):
        return dotted_expression_name(node.target)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_expression_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else ""
    return ""


def embedded_python_sources(
    text: str, *, workflow_text: str | None = None
) -> list[dict[str, Any]]:
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
    for line, command in shell_logical_commands(text):
        try:
            tokens = shell_tokens(command)
        except ValueError:
            continue
        if not any(
            row["entrypoint"] in STDIN_ENTRYPOINTS
            for row in python_invocations(command)
        ):
            continue
        for index, token in enumerate(tokens[:-1]):
            if token == "<<<":
                sources.append(
                    {
                        "line": line,
                        "kind": "here-string",
                        "source": tokens[index + 1] + "\n",
                    }
                )
    if workflow_text is not None:
        sources.extend(workflow_python_shell_sources(workflow_text))
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
            | local_process_paths(sources[path], known)
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
    text = executable_shell_text(text)
    if shell_uses_indirect_assignment(text):
        return False
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
    # The guard itself must be top-level.  Allowing arbitrary indentation lets
    # an inert wrapper such as ``if false; then`` make the reviewed text appear
    # present without ever deriving the flag at runtime.
    block = re.compile(
        rf"^{re.escape(variable)}=\"\"\s*$\n"
        rf"^if \[ \"\$\{{\{{ github\.event\.inputs\.{re.escape(input_name)} \}}\}}\" = \"true\" \]; then\s*$\n"
        rf"^  {re.escape(variable)}=\"{re.escape(enabled_value)}\"\s*$\n"
        rf"^fi\s*$",
        re.MULTILINE,
    )
    return block.search(text) is not None


def shell_variable_occurrence_lines(text: str, variable: str) -> list[str]:
    return sorted(
        raw.strip()
        for raw in text.splitlines()
        if re.search(rf"\b{re.escape(variable)}\b", raw)
    )


def executable_shell_text(text: str) -> str:
    """Blank heredoc bodies so inert text cannot satisfy shell contracts."""
    lines = text.splitlines()
    result = list(lines)
    heredoc = HEREDOC_WORD
    index = 0
    while index < len(lines):
        match = heredoc.search(lines[index])
        if not match:
            index += 1
            continue
        delimiter = heredoc_delimiter(match)
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            result[index] = ""
            index += 1
        if index < len(lines):
            result[index] = ""
            index += 1
    return "\n".join(result)


def shell_uses_indirect_assignment(text: str) -> bool:
    """Reject shell primitives that can assign guarded names indirectly."""
    for _line, command in shell_logical_commands(text):
        try:
            tokens = shell_tokens(command)
        except ValueError:
            continue
        for index, token in enumerate(tokens):
            executable = token.rsplit("/", 1)[-1]
            if not shell_command_position(tokens, index):
                continue
            if executable in {"eval", "read", "mapfile", "readarray", "getopts"}:
                return True
            if executable == "printf" and "-v" in tokens[index + 1:]:
                return True
            if executable in {"declare", "typeset"} and any(
                value == "-n" or (value.startswith("-") and "n" in value[1:])
                for value in tokens[index + 1:]
            ):
                return True
    return False


def literal_path_values(
    node: ast.AST | None, names: Mapping[str, set[str]]
) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {str(node.value)}
    if isinstance(node, ast.Name):
        return set(names.get(node.id, set()))
    if isinstance(node, ast.Call):
        func = dotted_expression_name(node.func).rsplit(".", 1)[-1]
        if func in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}:
            parts = [literal_path_values(arg, names) for arg in node.args]
            if parts and all(part for part in parts):
                combined = {""}
                for choices in parts:
                    combined = {
                        f"{left.rstrip('/\\')}/{right.lstrip('/\\')}"
                        if left else right
                        for left in combined
                        for right in choices
                    }
                return combined
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = literal_path_values(node.left, names)
        right = literal_path_values(node.right, names)
        return {
            f"{a.rstrip('/\\')}/{b.lstrip('/\\')}"
            for a in left
            for b in right
        }
    return set()


@lru_cache(maxsize=4096)
def authority_write_sinks(
    source: str, sensitive_terms: tuple[str, ...]
) -> tuple[str, ...]:
    """Find direct writes whose literal destination is authority-sensitive."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    path_unique_methods = {
        "write_text", "write_bytes", "unlink", "rmdir", "touch", "link_to",
        "symlink_to", "hardlink_to",
    }
    generic_output_methods = {"to_csv", "to_json", "to_parquet"}
    path_move_methods = {"rename", "replace"}
    copy_functions = {
        f"shutil.{name}"
        for name in ("copy", "copy2", "copyfile", "copytree", "move")
    }
    delete_functions = {
        f"os.{name}" for name in ("remove", "unlink", "rmdir", "removedirs")
    }
    link_functions = {
        f"os.{name}" for name in ("link", "symlink", "rename", "replace")
    }
    delete_functions.add("shutil.rmtree")
    findings: set[str] = set()
    normalized_source = source.replace("\r\n", "\n").replace("\r", "\n")
    source_binding_hash = hashlib.sha256(
        normalized_source.encode("utf-8")
    ).hexdigest()

    def unresolved_destination(node: ast.AST | None) -> str:
        expression = ast.get_source_segment(source, node) if node is not None else ""
        binding_hash = hashlib.sha256(
            f"{expression or '<missing>'}:{source_binding_hash}".encode("utf-8")
        ).hexdigest()[:16]
        return f"UNRESOLVED_DESTINATION:binding={binding_hash}"

    literal_names: dict[str, set[str]] = {}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            targets: list[ast.AST] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            resolved = literal_path_values(value, literal_names)
            if not resolved:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    existing = literal_names.setdefault(target.id, set())
                    before = len(existing)
                    existing.update(resolved)
                    changed |= len(existing) != before
    open_aliases = {"open", "io.open", "builtins.open"}
    for imported in ast.walk(tree):
        if isinstance(imported, ast.Import):
            for alias in imported.names:
                local = alias.asname or alias.name
                if alias.name in {"io", "builtins"}:
                    open_aliases.add(f"{local}.open")
                elif alias.name == "shutil":
                    copy_functions.update(
                        f"{local}.{name}"
                        for name in (
                            "copy", "copy2", "copyfile", "copytree", "move"
                        )
                    )
                    delete_functions.add(f"{local}.rmtree")
                elif alias.name == "os":
                    delete_functions.update(
                        f"{local}.{name}"
                        for name in ("remove", "unlink", "rmdir", "removedirs")
                    )
                    link_functions.update(
                        f"{local}.{name}"
                        for name in ("link", "symlink", "rename", "replace")
                    )
        elif isinstance(imported, ast.ImportFrom) and imported.module in {
            "io", "builtins", "shutil", "os"
        }:
            for alias in imported.names:
                if alias.name == "open":
                    open_aliases.add(alias.asname or alias.name)
                elif imported.module == "shutil" and alias.name in {
                    "copy", "copy2", "copyfile", "copytree", "move"
                }:
                    copy_functions.add(alias.asname or alias.name)
                elif imported.module == "shutil" and alias.name == "rmtree":
                    delete_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name in {
                    "remove", "unlink", "rmdir", "removedirs"
                }:
                    delete_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name in {
                    "link", "symlink", "rename", "replace"
                }:
                    link_functions.add(alias.asname or alias.name)
    callable_groups = (
        open_aliases,
        copy_functions,
        delete_functions,
        link_functions,
    )
    changed = True
    while changed:
        changed = False
        for assigned in ast.walk(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(assigned, ast.Assign):
                pairs.extend((target, assigned.value) for target in assigned.targets)
            elif isinstance(assigned, ast.AnnAssign) and assigned.value is not None:
                pairs.append((assigned.target, assigned.value))
            elif isinstance(assigned, ast.NamedExpr):
                pairs.append((assigned.target, assigned.value))
            for target, value in pairs:
                if not isinstance(target, ast.Name):
                    continue
                dotted = dotted_expression_name(value)
                for group in callable_groups:
                    if dotted in group and target.id not in group:
                        group.add(target.id)
                        changed = True
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = dotted_expression_name(node.func)
        path_method_open = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and func_name not in open_aliases
        )
        if func_name in open_aliases or path_method_open:
            destination_node = (
                node.func.value
                if path_method_open
                else (node.args[0] if node.args else None)
            )
            literal_paths = (
                literal_path_values(destination_node, literal_names)
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
                {
                    term
                    for literal_path in literal_paths
                    for term in sensitive_terms
                    if term in literal_path.casefold()
                }
            )
            if any(marker in mode for marker in "wax+") and (sensitive or not literal_paths):
                findings.add(
                    f"line={getattr(node, 'lineno', 0)}:open:"
                    f"{','.join(sensitive) if sensitive else unresolved_destination(destination_node)}"
                )
            continue
        func_name = dotted_expression_name(node.func)
        method = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else func_name.rsplit(".", 1)[-1]
        )
        destinations: set[str] = set()
        unresolved = False
        if func_name in copy_functions:
            destination_node = node.args[1] if len(node.args) > 1 else None
            destinations.update(literal_path_values(destination_node, literal_names))
            unresolved = not destinations
        elif func_name in delete_functions:
            destination_node = node.args[0] if node.args else None
            destinations.update(literal_path_values(destination_node, literal_names))
            unresolved = not destinations
        elif func_name in link_functions:
            destination_node = node.args[1] if len(node.args) > 1 else None
            destinations.update(literal_path_values(destination_node, literal_names))
            unresolved = not destinations
        elif isinstance(node.func, ast.Attribute) and method in (
            path_unique_methods | generic_output_methods | path_move_methods
        ):
            if method in path_unique_methods:
                destination_node = node.func.value
                destinations.update(literal_path_values(node.func.value, literal_names))
                unresolved = not destinations
            elif method in generic_output_methods:
                destination_node = node.args[0] if node.args else None
                destinations.update(
                    literal_path_values(destination_node, literal_names)
                )
                unresolved = not destinations
            else:
                receiver = literal_path_values(node.func.value, literal_names)
                destination_node = node.args[0] if node.args else None
                destination = literal_path_values(destination_node, literal_names)
                if not receiver and not destination:
                    continue
                destinations.update(receiver)
                destinations.update(destination)
                unresolved = not destination
        else:
            continue
        sensitive = sorted(
            {
                term
                for literal in destinations
                for term in sensitive_terms
                if term in literal.casefold()
            }
        )
        if sensitive:
            findings.add(f"line={getattr(node, 'lineno', 0)}:{method}:{','.join(sensitive)}")
        elif unresolved:
            findings.add(
                f"line={getattr(node, 'lineno', 0)}:{method}:"
                f"{unresolved_destination(destination_node)}"
            )
    return tuple(sorted(findings))


@lru_cache(maxsize=4096)
def shell_authority_write_sinks(
    text: str, sensitive_terms: tuple[str, ...]
) -> tuple[str, ...]:
    """Inventory literal authority-sensitive destinations written by shell."""
    findings: set[str] = set()
    literal_names: dict[str, set[str]] = {}
    redirections = {">", ">>", ">|", "&>", "&>>"}
    copy_commands = {
        "cp", "mv", "install", "tee", "touch", "truncate", "rsync", "ln",
    }

    def sensitive(value: str) -> tuple[str, ...]:
        normalized = value.casefold()
        return tuple(term for term in sensitive_terms if term in normalized)

    def resolved_values(value: str) -> set[str]:
        variables = re.findall(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))", value)
        if not variables:
            return {value}
        values = {value}
        for braced, plain in variables:
            name = braced or plain
            choices = literal_names.get(name, set())
            if not choices:
                return set()
            next_values: set[str] = set()
            for current in values:
                for choice in choices:
                    next_values.add(
                        current.replace(f"${{{name}}}", choice).replace(f"${name}", choice)
                    )
            values = next_values
        return values

    def record_destination(line: int, kind: str, destination: str) -> None:
        values = resolved_values(destination)
        if not values:
            findings.add(f"line={line}:{kind}:UNRESOLVED_DESTINATION")
            return
        for value in sorted(values):
            terms = sensitive(value)
            if terms:
                findings.add(f"line={line}:{kind}:{value}:{','.join(terms)}")

    for line, command in shell_logical_commands(text):
        try:
            tokens = shell_tokens(command)
        except ValueError:
            continue
        for token in tokens:
            if token in SHELL_COMMAND_BOUNDARIES:
                continue
            assignment = SHELL_ASSIGNMENT_WORD.fullmatch(token)
            if not assignment:
                continue
            name, value = token.split("=", 1)
            resolved = resolved_values(value)
            if resolved:
                literal_names.setdefault(name, set()).update(resolved)
        for index, token in enumerate(tokens):
            executable = token.rsplit("/", 1)[-1]
            if executable not in {"bash", "sh", "dash", "zsh", "ksh"}:
                continue
            for option_index in range(index + 1, len(tokens) - 1):
                if not re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", tokens[option_index]):
                    continue
                operand = tokens[option_index + 1]
                if re.search(r"\$(?:\{|[A-Za-z_])", operand) and not resolved_values(operand):
                    binding = hashlib.sha256(
                        command.encode("utf-8")
                    ).hexdigest()[:16]
                    findings.add(
                        f"line={line}:dynamic-shell-c:UNRESOLVED_COMMAND:binding={binding}"
                    )
                break
        for index, token in enumerate(tokens[:-1]):
            if token in redirections:
                destination = tokens[index + 1]
                record_destination(line, "redirect", destination)
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
                record_destination(line, executable, destination)
        sed_index = next(
            (
                index
                for index, token in enumerate(tokens)
                if token.rsplit("/", 1)[-1] == "sed" and shell_command_position(tokens, index)
            ),
            None,
        )
        if sed_index is not None and any(
            value == "-i" or value.startswith("--in-place")
            for value in tokens[sed_index + 1:]
        ):
            for destination in tokens[sed_index + 1:]:
                if not destination.startswith("-"):
                    record_destination(line, "sed-in-place", destination)
        recognized = redirections | copy_commands | {"sed", "dd"}
        for index, token in enumerate(tokens):
            if not shell_command_position(tokens, index):
                continue
            executable = token.rsplit("/", 1)[-1]
            if executable in recognized:
                break
            for operand in tokens[index + 1:]:
                for resolved in sorted(resolved_values(operand)):
                    terms = sensitive(resolved)
                    if terms:
                        findings.add(
                            f"line={line}:unclassified-authority-operand:"
                            f"{executable}:{resolved}:{','.join(terms)}"
                        )
            break
        for token in tokens:
            if token.startswith("of="):
                destination = token[3:]
                record_destination(line, "dd", destination)
    return tuple(sorted(findings))


def authority_fingerprint(
    *,
    reachable_sensitive: list[str],
    python_write_sinks: list[str],
    python_process_launches: list[str],
    shell_write_sinks: list[str],
    reachable_shell_scripts: list[str] | None = None,
    reachable_yaml_files: list[str] | None = None,
    reachable_action_files: list[str] | None = None,
) -> str:
    payload = {
        "reachable_sensitive": sorted(reachable_sensitive),
        "python_write_sinks": sorted(python_write_sinks),
        "python_process_launches": sorted(python_process_launches),
        "shell_write_sinks": sorted(shell_write_sinks),
        "reachable_shell_scripts": sorted(reachable_shell_scripts or []),
    }
    # Preserve the established fingerprint for repositories without local
    # action/reusable-workflow edges; once an edge exists its exact YAML bytes
    # become contract-bound.
    if reachable_yaml_files:
        payload["reachable_yaml_files"] = sorted(reachable_yaml_files)
    if reachable_action_files:
        payload["reachable_action_files"] = sorted(reachable_action_files)
    return canonical_sha256(payload)


def workflow_local_references(
    path: str,
    text: str,
    sources: Mapping[str, str],
    known_paths: set[str],
    working_directory: str = "",
) -> set[str]:
    references = {
        resolve_working_directory_path(entrypoint, working_directory)
        for entrypoint in python_entrypoints(text)
    }
    for invocation in python_invocations(text):
        if invocation["entrypoint"] != "-c" or not invocation["command_source"]:
            continue
        references.update(
            local_import_paths(
                str(invocation["command_source"]),
                f"{Path(working_directory, '__workflow_command__.py').as_posix() if working_directory else path}::command:{invocation['line']}",
                sources,
                known_paths,
            )
        )
        references.update(
            local_process_paths(
                str(invocation["command_source"]),
                known_paths,
                working_directory,
            )
        )
    for block in inline_python_blocks(text):
        references.update(
            local_import_paths(
                str(block["source"]),
                f"{Path(working_directory, '__workflow_inline__.py').as_posix() if working_directory else path}::inline:{block['line']}",
                sources,
                known_paths,
            )
        )
        references.update(
            local_process_paths(
                str(block["source"]), known_paths, working_directory
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
def workflow_run_records(text: str) -> tuple[tuple[str, str, str], ...]:
    """Return effective ``(shell, source, working_directory)`` run records."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
        if not isinstance(payload, dict):
            return (("", text, ""),)
        jobs = payload.get("jobs")
        blocks: list[tuple[str, str]] = []
        workflow_default = str(
            (((payload.get("defaults") or {}).get("run") or {}).get("shell") or "")
            if isinstance(payload.get("defaults"), dict)
            else ""
        )
        workflow_workdir = str(
            (((payload.get("defaults") or {}).get("run") or {}).get("working-directory") or "")
            if isinstance(payload.get("defaults"), dict)
            else ""
        )
        if isinstance(jobs, dict):
            for job in jobs.values():
                if not isinstance(job, dict):
                    continue
                job_default = workflow_default
                job_workdir = workflow_workdir
                defaults = job.get("defaults")
                if isinstance(defaults, dict):
                    run_defaults = defaults.get("run")
                    if isinstance(run_defaults, dict) and run_defaults.get("shell"):
                        job_default = str(run_defaults["shell"])
                    if (
                        isinstance(run_defaults, dict)
                        and run_defaults.get("working-directory")
                    ):
                        job_workdir = str(run_defaults["working-directory"])
                steps = job.get("steps")
                if not isinstance(steps, list):
                    continue
                for step in steps:
                    if isinstance(step, dict) and isinstance(step.get("run"), str):
                        blocks.append(
                            (
                                str(step.get("shell") or job_default),
                                str(step["run"]),
                                str(step.get("working-directory") or job_workdir),
                            )
                        )
        else:
            runs = payload.get("runs")
            steps = runs.get("steps") if isinstance(runs, dict) else None
            if isinstance(steps, list):
                for step in steps:
                    if isinstance(step, dict) and isinstance(step.get("run"), str):
                        blocks.append(
                            (
                                str(step.get("shell") or ""),
                                str(step["run"]),
                                str(step.get("working-directory") or ""),
                            )
                        )
        if not blocks and not isinstance(jobs, dict) and not isinstance(payload.get("runs"), dict):
            return (("", text, ""),)
        return tuple(blocks)
    except (TypeError, yaml.YAMLError):
        return (("", text, ""),)


@lru_cache(maxsize=512)
def workflow_run_blocks(text: str) -> tuple[tuple[str, str], ...]:
    """Compatibility view of effective ``(shell, source)`` run records."""
    return tuple((shell, source) for shell, source, _workdir in workflow_run_records(text))


def python_declared_shell(value: str) -> bool:
    shell = str(value or "").strip().replace("\\", "/").casefold()
    executable = shell.split()[0].rsplit("/", 1)[-1] if shell else ""
    return bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable))


@lru_cache(maxsize=512)
def workflow_run_text(text: str) -> str:
    """Return non-Python run blocks for shell parsing and flag validation."""
    return "\n".join(
        source
        for shell, source in workflow_run_blocks(text)
        if not python_declared_shell(shell)
    )


@lru_cache(maxsize=512)
def workflow_python_shell_sources(text: str) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"line": index, "kind": "declared-python-shell", "source": source}
        for index, (shell, source) in enumerate(workflow_run_blocks(text), start=1)
        if python_declared_shell(shell)
    )


def resolved_workflow_python_invocations(
    records: list[tuple[str, str, str, str]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for yaml_path, shell, source, working_directory in records:
        if python_declared_shell(shell):
            continue
        for invocation in python_invocations(source):
            copied = dict(invocation)
            copied["entrypoint"] = resolve_working_directory_path(
                str(invocation["entrypoint"]), working_directory
            )
            copied["yaml_path"] = yaml_path
            copied["working_directory"] = working_directory
            result.append(copied)
    return result


def shell_script_candidates(text: str) -> set[str]:
    text = executable_shell_text(text)
    candidates: set[str] = set()
    shells = {"bash", "sh", "dash", "zsh", "ksh"}
    literal_names: dict[str, str] = {}
    for _line, command in shell_logical_commands(text):
        try:
            tokens = shell_tokens(command)
        except ValueError:
            continue
        for token in tokens:
            if SHELL_ASSIGNMENT_WORD.fullmatch(token):
                name, value = token.split("=", 1)
                if not re.search(r"[$`]", value):
                    literal_names[name] = value

        def resolved(value: str) -> str:
            match = re.fullmatch(
                r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
                value,
            )
            return literal_names.get(match.group(1) or match.group(2), value) if match else value

        for index, token in enumerate(tokens):
            if not shell_command_position(tokens, index):
                continue
            executable_token = resolved(token)
            executable = executable_token.rsplit("/", 1)[-1]
            if SHELL_ASSIGNMENT_WORD.fullmatch(token) or executable in {
                "exec", "command", "builtin", "nohup", "time", "env"
            }:
                continue
            candidate = ""
            if "/" in executable_token.replace("\\", "/"):
                candidate = normalize_script_entrypoint(executable_token)
            elif executable in {"source", "."} and index + 1 < len(tokens):
                candidate = normalize_script_entrypoint(resolved(tokens[index + 1]))
            elif executable in shells:
                cursor = index + 1
                while cursor < len(tokens):
                    value = resolved(tokens[cursor])
                    if value == "-c" or (
                        value.startswith("-") and "c" in value[1:]
                    ):
                        break
                    if value.startswith("-"):
                        cursor += 1
                        continue
                    # A named shell interpreter can execute extensionless files.
                    candidate = normalize_script_entrypoint(value)
                    break
            if candidate:
                candidates.add(candidate)
                break
            if executable in shells:
                break
    return candidates


def local_uses_paths(text: str, known_paths: set[str]) -> set[str]:
    """Resolve repository-local composite actions and reusable workflows."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return set()
    values: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "uses" and isinstance(child, str):
                    values.append(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    result: set[str] = set()
    for value in values:
        if not value.startswith("./"):
            continue
        candidate = normalize_script_entrypoint(value)
        candidates = [candidate]
        if not Path(candidate).suffix:
            candidates.extend(
                [f"{candidate.rstrip('/')}/action.yml", f"{candidate.rstrip('/')}/action.yaml"]
            )
        result.update(path for path in candidates if path in known_paths)
    return result


def reachable_local_yaml_paths(
    root_path: str, root_text: str, sources: Mapping[str, str]
) -> set[str]:
    known = set(sources)
    seen: set[str] = set()
    stack = sorted(local_uses_paths(root_text, known))
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for child in sorted(local_uses_paths(sources[path], known)):
            if child not in seen:
                stack.append(child)
    seen.discard(root_path)
    return seen


def local_shell_script_paths(
    text: str, known_paths: set[str], working_directory: str = ""
) -> set[str]:
    result: set[str] = set()
    for candidate in shell_script_candidates(text):
        candidate = resolve_working_directory_path(candidate, working_directory)
        if candidate in known_paths:
            result.add(candidate)
            continue
        matches = sorted(
            path for path in known_paths if Path(path).name == Path(candidate).name
        )
        if len(matches) == 1:
            result.add(matches[0])
    return result


def reachable_shell_paths(
    roots: set[str], sources: Mapping[str, str]
) -> set[str]:
    known = set(sources)
    seen: set[str] = set()
    stack = sorted(root for root in roots if root in known)
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        for child in sorted(local_shell_script_paths(sources[path], known)):
            if child not in seen:
                stack.append(child)
    return seen


def audit_texts(
    contract: Mapping[str, Any],
    workflows: Mapping[str, str],
    accepted_files: Mapping[str, str],
    known_python_paths: set[str] | None = None,
    known_tracked_paths: set[str] | None = None,
) -> dict[str, Any]:
    validate_contract(contract)
    known_paths = (
        {path for path in accepted_files if path.endswith(".py")}
        if known_python_paths is None
        else set(known_python_paths)
    )
    yaml_sources = {
        path: source
        for path, source in accepted_files.items()
        if path.endswith((".yml", ".yaml"))
    }
    tracked_paths = set(accepted_files) if known_tracked_paths is None else set(known_tracked_paths)
    shell_sources = {
        path: source
        for path, source in accepted_files.items()
        if path not in known_paths and path not in yaml_sources
    }
    known_shell_paths = set(shell_sources)
    workflow_yaml_reachable: dict[str, list[str]] = {}
    workflow_action_implementations: dict[str, list[str]] = {}
    executable_workflows: dict[str, str] = {}
    workflow_yaml_texts: dict[str, list[tuple[str, str]]] = {}
    workflow_run_record_map: dict[
        str, list[tuple[str, str, str, str]]
    ] = {}
    for path, text in sorted(workflows.items()):
        yaml_reachable = reachable_local_yaml_paths(path, text, yaml_sources)
        workflow_yaml_reachable[path] = sorted(yaml_reachable)
        action_implementations = {
            implementation
            for yaml_path in yaml_reachable
            for implementation in local_action_implementation_paths(
                yaml_path, yaml_sources[yaml_path], tracked_paths
            )
        }
        workflow_action_implementations[path] = sorted(action_implementations)
        sources = [(path, text)] + [
            (yaml_path, yaml_sources[yaml_path])
            for yaml_path in sorted(yaml_reachable)
        ]
        workflow_yaml_texts[path] = sources
        run_records = [
            (yaml_path, shell, source, workdir)
            for yaml_path, yaml_text in sources
            for shell, source, workdir in workflow_run_records(yaml_text)
        ]
        workflow_run_record_map[path] = run_records
        executable_workflows[path] = "\n".join(
            source
            for _yaml_path, shell, source, _workdir in run_records
            if not python_declared_shell(shell)
        )
    workflow_shell_reachable: dict[str, list[str]] = {}
    workflow_direct_invocations = {
        path: resolved_workflow_python_invocations(records)
        for path, records in workflow_run_record_map.items()
    }
    workflow_embedded: dict[str, list[dict[str, Any]]] = {}
    workflow_references: dict[str, set[str]] = {}
    workflow_reachable_python: dict[str, set[str]] = {}
    for path, text in sorted(executable_workflows.items()):
        references: set[str] = set()
        embedded: list[dict[str, Any]] = []
        shell_roots: set[str] = set()
        for yaml_path, shell, run_text, workdir in workflow_run_record_map[path]:
            if python_declared_shell(shell):
                embedded.append(
                    {
                        "line": 1,
                        "kind": "declared-python-shell",
                        "source": run_text,
                        "working_directory": workdir,
                    }
                )
                continue
            references.update(
                workflow_local_references(
                    yaml_path,
                    run_text,
                    accepted_files,
                    known_paths,
                    workdir,
                )
            )
            for source in embedded_python_sources(run_text):
                copied = dict(source)
                copied["working_directory"] = workdir
                embedded.append(copied)
            shell_roots.update(
                local_shell_script_paths(run_text, known_shell_paths, workdir)
            )
        shell_reachable: set[str] = set()
        reachable: set[str] = set()
        processed_shells: set[str] = set()
        processed_embedded = 0
        while True:
            shell_reachable = reachable_shell_paths(
                shell_roots | shell_reachable, shell_sources
            )
            for shell_path in sorted(shell_reachable - processed_shells):
                shell_source = shell_sources[shell_path]
                references.update(
                    workflow_local_references(
                        shell_path, shell_source, accepted_files, known_paths
                    )
                )
                embedded.extend(embedded_python_sources(shell_source))
                processed_shells.add(shell_path)
            while processed_embedded < len(embedded):
                source = embedded[processed_embedded]
                processed_embedded += 1
                virtual_path = (
                    f"{path}::embedded:{source['kind']}:{source['line']}"
                )
                python_source = str(source["source"])
                working_directory = str(source.get("working_directory") or "")
                references.update(
                    local_import_paths(
                        python_source, virtual_path, accepted_files, known_paths
                    )
                )
                references.update(
                    local_process_paths(
                        python_source, known_paths, working_directory
                    )
                )
                shell_roots.update(
                    local_process_shell_paths(
                        python_source, known_shell_paths, working_directory
                    )
                )
            reachable, _parents = reachable_python_paths(
                {reference for reference in references if reference in known_paths},
                accepted_files,
                known_paths,
            )
            launched_shells = {
                shell_path
                for source_path in reachable
                if source_path in accepted_files
                for shell_path in local_process_shell_paths(
                    accepted_files[source_path], known_shell_paths
                )
            }
            before = (len(shell_roots), len(processed_shells), len(reachable))
            shell_roots.update(launched_shells)
            if (
                shell_roots <= shell_reachable
                and processed_shells == shell_reachable
                and processed_embedded == len(embedded)
            ):
                break
            after = (len(shell_roots), len(processed_shells), len(reachable))
            if after == before and shell_roots <= shell_reachable:
                break
        workflow_shell_reachable[path] = sorted(shell_reachable)
        workflow_embedded[path] = embedded
        workflow_references[path] = references
        workflow_reachable_python[path] = reachable
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
            lines = [
                int(row["line"])
                for row in workflow_direct_invocations.get(path, [])
                if row["entrypoint"] == entrypoint
            ]
            shell_lines: list[str] = []
            for shell_path in workflow_shell_reachable.get(path, []):
                shell_lines.extend(
                    f"{shell_path}:{line}"
                    for line in executable_invocations(
                        shell_sources[shell_path], entrypoint
                    )
                )
            embedded_lines: list[int] = []
            for source in workflow_embedded.get(path, []):
                call_counts = dict(
                    python_main_call_counts(
                        str(source["source"]),
                        f"{path}::embedded:{source['kind']}:{source['line']}",
                    )
                )
                embedded_lines.extend(
                    [int(source["line"])] * int(call_counts.get(entrypoint, 0))
                )
            transitive_main_calls: list[str] = []
            for source_path in sorted(workflow_reachable_python.get(path, set())):
                if source_path not in accepted_files:
                    continue
                call_count = dict(
                    python_main_call_counts(
                        accepted_files[source_path], source_path
                    )
                ).get(entrypoint, 0)
                transitive_main_calls.extend(
                    [source_path] * int(call_count)
                )
            if not lines and not shell_lines and not embedded_lines and not transitive_main_calls:
                continue
            observed.append(path)
            invocation_count += (
                len(lines)
                + len(shell_lines)
                + len(embedded_lines)
                + len(transitive_main_calls)
            )
            records.append(
                {
                    "entrypoint": entrypoint,
                    "role": role,
                    "workflow": path,
                    "line_numbers": lines,
                    "shell_script_invocations": shell_lines,
                    "embedded_main_call_lines": embedded_lines,
                    "transitive_python_main_calls": transitive_main_calls,
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
            for row in workflow_direct_invocations.get(path, [])
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
        for entrypoint in {
            str(row["entrypoint"])
            for row in workflow_direct_invocations.get(accepted_workflow, [])
        }
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
        for entrypoint in {
            str(row["entrypoint"])
            for row in workflow_direct_invocations.get(accepted_workflow, [])
        }
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
    workflow_python_process_launches: dict[str, list[str]] = {}
    workflow_shell_authority_write_sinks: dict[str, list[str]] = {}
    observed_authority_fingerprints: dict[str, str] = {}
    local_references_by_workflow: dict[str, set[str]] = {}
    sensitive_terms = tuple(
        sorted(
            {
                str(term).casefold()
                for term in (
                    contract.get("authority_write_destination_terms")
                    or contract.get("authority_sensitive_name_terms")
                    or []
                )
                if str(term)
            }
        )
    )
    for path, text in sorted(executable_workflows.items()):
        references = workflow_references.get(path, set())
        local_references_by_workflow[path] = references
        sensitive = sorted(
            reference for reference in references if authority_sensitive(reference, contract)
        )
        workflow_reachable = workflow_reachable_python.get(path, set())
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
        python_write_findings.extend(
            sorted(
                f"{path}::embedded:{source['kind']}:{source['line']}:{finding}"
            for source in workflow_embedded.get(path, [])
                for finding in authority_write_sinks(
                    str(source["source"]), sensitive_terms
                )
            )
        )
        python_write_findings = sorted(set(python_write_findings))
        python_process_findings = sorted(
            {
                f"{source_path}:{finding}"
                for source_path in workflow_reachable
                if source_path in accepted_files
                for finding in python_process_launches(accepted_files[source_path])
            }
        )
        python_process_findings.extend(
            sorted(
                f"{path}::embedded:{source['kind']}:{source['line']}:{finding}"
            for source in workflow_embedded.get(path, [])
                for finding in python_process_launches(str(source["source"]))
            )
        )
        python_process_findings = sorted(set(python_process_findings))
        shell_write_findings = [
            f"{path}:{finding}"
            for finding in shell_authority_write_sinks(text, sensitive_terms)
        ]
        shell_write_findings.extend(
            f"{shell_path}:{finding}"
            for shell_path in workflow_shell_reachable.get(path, [])
            for finding in shell_authority_write_sinks(
                shell_sources[shell_path], sensitive_terms
            )
        )
        shell_write_findings = sorted(set(shell_write_findings))
        if python_write_findings:
            workflow_python_authority_write_sinks[path] = python_write_findings
        if python_process_findings:
            workflow_python_process_launches[path] = python_process_findings
        if shell_write_findings:
            workflow_shell_authority_write_sinks[path] = shell_write_findings
        fingerprint = authority_fingerprint(
            reachable_sensitive=reachable_sensitive,
            python_write_sinks=python_write_findings,
            python_process_launches=python_process_findings,
            shell_write_sinks=shell_write_findings,
            reachable_shell_scripts=[
                f"{shell_path}:{text_sha256(shell_sources[shell_path])}"
                for shell_path in workflow_shell_reachable.get(path, [])
            ],
            reachable_yaml_files=[
                f"{yaml_path}:{text_sha256(yaml_sources[yaml_path])}"
                for yaml_path in workflow_yaml_reachable.get(path, [])
            ],
            reachable_action_files=[
                f"{implementation}:{text_sha256(accepted_files[implementation])}"
                if implementation in accepted_files
                else f"{implementation}:NON_TEXT_TRACKED_IMPLEMENTATION"
                for implementation in workflow_action_implementations.get(path, [])
            ],
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
            write_findings = sorted(
                set(python_write_findings) | set(shell_write_findings)
            )
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
        "workflow_python_process_launches": workflow_python_process_launches,
        "workflow_shell_authority_write_sinks": (
            workflow_shell_authority_write_sinks
        ),
        "workflow_python_reachable_files": workflow_python_reachable,
        "workflow_shell_reachable_files": workflow_shell_reachable,
        "workflow_yaml_reachable_files": workflow_yaml_reachable,
        "workflow_action_implementation_files": workflow_action_implementations,
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
    head_input_hashes: dict[str, str] = {}
    canonical_worktree_blob_ids: dict[str, str] = {}
    canonical_head_blob_ids: dict[str, str] = {}
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
        for path in normalized:
            try:
                head_bytes = subprocess.check_output(
                    ["git", "show", f"HEAD:{path}"],
                    cwd=root,
                    timeout=30,
                    stderr=subprocess.DEVNULL,
                )
                head_hash = hashlib.sha256(head_bytes).hexdigest()
                head_blob_id = subprocess.check_output(
                    ["git", "rev-parse", f"HEAD:{path}"],
                    cwd=root,
                    timeout=30,
                    stderr=subprocess.DEVNULL,
                ).decode("ascii").strip()
                worktree_blob_id = subprocess.check_output(
                    ["git", "hash-object", "--path", path, "--", path],
                    cwd=root,
                    timeout=30,
                    stderr=subprocess.DEVNULL,
                ).decode("ascii").strip()
            except (OSError, subprocess.SubprocessError):
                head_hash = "MISSING_AT_HEAD"
                head_blob_id = "MISSING_AT_HEAD"
                worktree_blob_id = "MISSING_IN_WORKTREE"
            head_input_hashes[path] = head_hash
            canonical_head_blob_ids[path] = head_blob_id
            canonical_worktree_blob_ids[path] = worktree_blob_id
            # Compare Git's canonical worktree bytes to the exact HEAD blob.
            # This catches assume-unchanged/skip-worktree bypasses while still
            # respecting declared checkout filters such as CRLF normalization.
            if worktree_blob_id != head_blob_id:
                dirty.append(f"HEAD_BYTE_MISMATCH:{path}")
        dirty = sorted(set(dirty))
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
        "head_audit_input_tree_sha256": canonical_sha256(head_input_hashes),
        "head_audit_input_hashes": head_input_hashes,
        "canonical_worktree_blob_ids": canonical_worktree_blob_ids,
        "canonical_head_blob_ids": canonical_head_blob_ids,
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
    all_tracked_paths = set(tracked_file_paths(root))
    workflows = workflow_texts(root, tracked)
    python_paths = set(tracked_python_paths(root))
    python_sources = {
        path: (root / path).read_text(encoding="utf-8")
        for path in sorted(python_paths)
        if (root / path).is_file()
    }
    shell_sources = tracked_shell_texts(root)
    local_action_paths = tracked_local_action_paths(root)
    local_action_sources = workflow_texts(root, local_action_paths)
    implementation_paths = {
        implementation
        for action_path, action_text in local_action_sources.items()
        for implementation in local_action_implementation_paths(
            action_path, action_text, all_tracked_paths
        )
    }
    implementation_sources: dict[str, str] = {}
    for path in sorted(implementation_paths):
        try:
            implementation_sources[path] = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    accepted_files = {
        **python_sources,
        **shell_sources,
        **local_action_sources,
        **implementation_sources,
        **workflows,
    }
    result = audit_texts(
        contract,
        workflows,
        accepted_files,
        known_python_paths=python_paths,
        known_tracked_paths=all_tracked_paths,
    )
    relevant = list(tracked)
    relevant.extend(result.get("accepted_python_reachable_files") or [])
    for reachable_files in (
        result.get("workflow_python_reachable_files") or {}
    ).values():
        relevant.extend(str(path) for path in reachable_files)
    for reachable_files in (
        result.get("workflow_shell_reachable_files") or {}
    ).values():
        relevant.extend(str(path) for path in reachable_files)
    for reachable_files in (
        result.get("workflow_yaml_reachable_files") or {}
    ).values():
        relevant.extend(str(path) for path in reachable_files)
    for reachable_files in (
        result.get("workflow_action_implementation_files") or {}
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
            contract_relative = contract_path.resolve().relative_to(root).as_posix()
            relevant.append(contract_relative)
        except ValueError:
            result["contract_head_bound"] = False
            result["failures"].append("contract_outside_selected_repository")
        else:
            result["contract_head_bound"] = git_path_tracked_at_head(
                root, contract_relative
            )
            if not result["contract_head_bound"]:
                result["failures"].append("contract_not_tracked_at_head")
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
