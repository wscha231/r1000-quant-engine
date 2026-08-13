#!/usr/bin/env python3
"""Audit Run287 target-writer, ledger-consumer, and legacy EXIT call paths."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import posixpath
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
    r"(?<!<)<<-?(?!<)\s*(?:'([^']+)'|\"([^\"]+)\"|\\([^\s;&|<>]+)|([^\s;&|<>]+))"
)
SHELL_EXPANSION_BUDGET_SENTINEL = "__RUN287_SHELL_EXPANSION_BUDGET_EXCEEDED__"
SHELL_UNRESOLVED_CONTROL_SENTINEL = "__RUN287_UNRESOLVED_SHELL_CONTROL__"
PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL = (
    "__RUN287_UNRESOLVED_DYNAMIC_IMPORT__"
)
PYTHON_DYNAMIC_EXEC_BUDGET_SENTINEL = "__RUN287_DYNAMIC_EXEC_BUDGET_EXCEEDED__"
PYTHON_DYNAMIC_EXEC_SOURCE_BUDGET = 128
PROTECTED_AUTHORITY_SENSITIVE_TERMS = (
    "account", "broker", "cash", "decision", "execute", "fill", "ledger",
    "order", "portfolio", "position", "promotion", "publish", "rebalance",
    "reserve", "selector", "target", "trade", "weight", "writer",
)
PROTECTED_AUTHORITY_WRITE_TERMS = (
    "accepted_publication_manifest", "decision_packet",
    "operating_concentrated_target_book", "operating_main_target_book",
    "paper_account", "paper_ledger", "promotion_state",
    "same_close_concentrated_target_book", "same_close_main_target_book",
    "simulated_fill_ledger", "target_book",
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
    if tuple(contract.get("authority_sensitive_name_terms") or ()) != (
        PROTECTED_AUTHORITY_SENSITIVE_TERMS
    ):
        raise ValueError("protected authority-sensitive vocabulary changed")
    if tuple(contract.get("authority_write_destination_terms") or ()) != (
        PROTECTED_AUTHORITY_WRITE_TERMS
    ):
        raise ValueError("protected authority-write vocabulary changed")
    bindings = contract.get("entrypoint_bindings") or []
    by_entrypoint = {
        str(row.get("entrypoint") or ""): row
        for row in bindings
        if isinstance(row, dict)
    }
    immutable_bindings = {
        "tools/build_run287_same_close_target_books.py": {
            "role": "accepted_current_target_writer",
            "exact_invocation_count": 1,
            "allowed_workflows": [
                ".github/workflows/daily_operating_selection_refresh.yml"
            ],
        },
        "tools/run_daily_simulated_fill_ledger.py": {
            "role": "durable_review_only_paper_ledger_consumer",
            "exact_invocation_count": 2,
            "allowed_workflows": [
                ".github/workflows/daily_operating_selection_refresh.yml"
            ],
        },
    }
    for entrypoint, required in immutable_bindings.items():
        binding = by_entrypoint.get(entrypoint) or {}
        observed = {
            "role": binding.get("role"),
            "exact_invocation_count": binding.get("exact_invocation_count"),
            "allowed_workflows": sorted(binding.get("allowed_workflows") or []),
        }
        if observed != required:
            raise ValueError(f"protected entrypoint binding changed: {entrypoint}")
    protected_profiles = [
        row
        for row in contract.get("required_executable_commands") or []
        if isinstance(row, dict)
        and row.get("workflow")
        == ".github/workflows/daily_operating_selection_refresh.yml"
        and row.get("entrypoint") in immutable_bindings
    ]
    required_profiles = [
        {
            "workflow": ".github/workflows/daily_operating_selection_refresh.yml",
            "entrypoint": "tools/run_daily_simulated_fill_ledger.py",
            "required_flags": ["--suppress-new-orders"],
            "required_option_values": {"--cost-bps": "25"},
            "exclusive_profile_group": "daily_durable_ledger",
            "exact_match_count": 1,
        },
        {
            "workflow": ".github/workflows/daily_operating_selection_refresh.yml",
            "entrypoint": "tools/run_daily_simulated_fill_ledger.py",
            "required_option_values": {
                "--target-handoff-manifest": "$SAME_CLOSE_DIR/status.json",
                "--expected-target-handoff-sha256": "$TARGET_HANDOFF_SHA",
                "--main-target-sha256": "$MAIN_TARGET_SHA",
                "--concentrated-target-sha256": "$CONCENTRATED_TARGET_SHA",
                "--cost-bps": "25",
            },
            "exclusive_profile_group": "daily_durable_ledger",
            "exact_match_count": 1,
        },
        {
            "workflow": ".github/workflows/daily_operating_selection_refresh.yml",
            "entrypoint": "tools/build_run287_same_close_target_books.py",
            "required_nonempty_options": [
                "--producer-status", "--freshness-status", "--valuation-date",
                "--output-dir",
            ],
            "exact_match_count": 1,
        },
    ]
    normalize_profiles = lambda rows: sorted(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
    )
    if normalize_profiles(protected_profiles) != normalize_profiles(required_profiles):
        raise ValueError("protected executable command profiles changed")


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


@lru_cache(maxsize=16)
def tracked_python_paths(root: Path) -> list[str]:
    """Discover tracked Python sources, including arbitrary interpreter operands."""
    tracked = set(tracked_file_paths(root))
    paths = {path for path in tracked if path.endswith(".py")}
    seed_paths = {
        path
        for path in tracked
        if path.endswith((".py", ".yml", ".yaml"))
    }
    seed_paths.update(tracked_shell_paths(root))
    texts: dict[str, str] = {}
    for path in sorted(seed_paths):
        try:
            raw_bytes = (root / path).read_bytes()
            if b"\x00" in raw_bytes:
                continue
            texts[path] = raw_bytes.decode("utf-8")
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
                for _shell, run_source, working_directory in workflow_run_records(
                    source, path
                ):
                    candidates.update(
                        resolve_working_directory_path(candidate, working_directory)
                        for candidate in python_entrypoints(run_source)
                    )
            elif path in paths:
                candidates.update(local_process_candidates(source))
            else:
                candidates.update(python_entrypoints(source))
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
            if path in paths:
                continue
            try:
                raw_bytes = (root / path).read_bytes()
                if b"\x00" in raw_bytes:
                    continue
                source = raw_bytes.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            paths.add(path)
            texts[path] = source
            new_paths.add(path)
        if not new_paths:
            break
    return sorted(paths)


def tracked_python_texts(root: Path) -> dict[str, str]:
    return {
        path: (root / path).read_text(encoding="utf-8")
        for path in tracked_python_paths(root)
        if (root / path).is_file()
    }


@lru_cache(maxsize=16)
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


@lru_cache(maxsize=16)
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
                for _shell, run_source, _workdir in workflow_run_records(source, path):
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
    action_path: str,
    text: str,
    known_paths: set[str],
    sources: Mapping[str, str] | None = None,
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
    if using == "docker" or using.startswith("node"):
        # Bind the complete tracked local context. Dockerfile COPY/ADD sources
        # and transitive Node require/import helpers otherwise escape the
        # declared main/pre/post implementation list.
        context_prefix = action_dir.as_posix().rstrip("/") + "/"
        candidates.update(
            path for path in known_paths if path.startswith(context_prefix)
        )
    if using.startswith("node") and sources is not None:
        pending = [candidate for candidate in candidates if candidate in sources]
        seen: set[str] = set()
        while pending:
            source_path = pending.pop()
            if source_path in seen:
                continue
            seen.add(source_path)
            for value in re.findall(
                r"(?:\brequire\s*\(|\bimport\s*\(|\bfrom\s+|\bimport\s+)"
                r"[\"']([^\"']+)[\"']",
                sources[source_path],
            ):
                if not value.startswith("."):
                    continue
                base = normalize_script_entrypoint(
                    Path(Path(source_path).parent, value).as_posix()
                )
                choices = [
                    base,
                    f"{base}.js",
                    f"{base}.cjs",
                    f"{base}.mjs",
                    f"{base}.json",
                    f"{base}/index.js",
                    f"{base}/index.cjs",
                    f"{base}/index.mjs",
                ]
                matches = [candidate for candidate in choices if candidate in known_paths]
                if len(matches) == 1 and matches[0] not in seen:
                    candidates.add(matches[0])
                    if matches[0] in sources:
                        pending.append(matches[0])
    return {candidate for candidate in candidates if candidate in known_paths}


def _raw_shell_logical_commands(text: str) -> list[tuple[int, str]]:
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


def _multiline_static_control_commands(
    rows: list[tuple[int, str]],
) -> list[tuple[int, str]]:
    """Expand finite multiline loops and prune literal-true branches."""

    def opener_closer(command: str) -> str:
        stripped = command.strip()
        if (
            re.match(r"^if\b.*(?:;\s*|\s+)then\s*$", stripped)
            and not re.search(r";\s*fi\b", stripped)
        ):
            return "fi"
        if (
            re.match(r"^(?:for|select|while|until)\b.*(?:;\s*|\s+)do\s*$", stripped)
            and not re.search(r";\s*done\b", stripped)
        ):
            return "done"
        if re.match(r"^case\b.*\bin\s*$", stripped):
            return "esac"
        return ""

    def closes(command: str, closer: str) -> bool:
        return bool(re.match(rf"^{closer}(?:\s*;)?\s*$", command.strip()))

    def locate(start: int) -> tuple[int, int | None]:
        first = opener_closer(rows[start][1])
        if not first:
            return -1, None
        stack = [first]
        alternate: int | None = None
        for cursor in range(start + 1, len(rows)):
            stripped = rows[cursor][1].strip()
            if (
                len(stack) == 1
                and stack[-1] == "fi"
                and re.match(r"^(?:else|elif)\b", stripped)
                and alternate is None
            ):
                alternate = cursor
                continue
            nested = opener_closer(stripped)
            if nested:
                stack.append(nested)
                continue
            if closes(stripped, stack[-1]):
                stack.pop()
                if not stack:
                    return cursor, alternate
        return -1, alternate

    result: list[tuple[int, str]] = []
    index = 0
    while index < len(rows):
        line, command = rows[index]
        stripped = command.strip()
        static_for = re.match(
            r"^for\s+[A-Za-z_][A-Za-z0-9_]*\s+in\s+(.*?)\s*;?\s*do\s*$",
            stripped,
        )
        literal_true = bool(
            re.match(r"^if\s+(?:true|!\s*false)\s*;?\s*then\s*$", stripped)
        )
        if not static_for and not literal_true:
            result.append((line, command))
            index += 1
            continue
        end, alternate = locate(index)
        if end < 0:
            result.append((0, SHELL_UNRESOLVED_CONTROL_SENTINEL))
            index += 1
            continue
        if static_for:
            body_rows = rows[index + 1:end]
            try:
                values = shlex.split(static_for.group(1), posix=True)
            except ValueError:
                values = []
            if not values or any(re.search(r"[$`*?\[]", value) for value in values):
                body = _multiline_static_control_commands(body_rows)
                authority_body = "\n".join(command for _line, command in body).casefold()
                if any(term in authority_body for term in PROTECTED_AUTHORITY_SENSITIVE_TERMS):
                    result.append((0, SHELL_UNRESOLVED_CONTROL_SENTINEL))
                else:
                    # Unknown multiplicity is harmless to exact authority counts
                    # when the loop body contains no authority-bearing operation.
                    result.extend(body)
            else:
                body = _multiline_static_control_commands(body_rows)
                if len(body) * len(values) > 10000:
                    result.append((0, SHELL_EXPANSION_BUDGET_SENTINEL))
                else:
                    for _value in values:
                        result.extend(body)
        else:
            branch_end = alternate if alternate is not None else end
            result.extend(
                _multiline_static_control_commands(rows[index + 1:branch_end])
            )
        index = end + 1
    return result


def shell_logical_commands(text: str) -> list[tuple[int, str]]:
    """Return commands that execute, expanding definite local shell calls."""
    raw = _multiline_static_control_commands(_raw_shell_logical_commands(text))
    reachable_raw: list[tuple[int, str]] = []
    skipped_closers: list[str] = []
    for line, command in raw:
        stripped = command.strip()
        inline_for = re.match(
            r"^for\s+[A-Za-z_][A-Za-z0-9_]*\s+in\s+(.*?)\s*;\s*do\s+"
            r"(.*?)\s*;\s*done(?:\s*;\s*(.*))?$",
            stripped,
        )
        if inline_for:
            try:
                values = shlex.split(inline_for.group(1), posix=True)
            except ValueError:
                values = []
            if not values or any(re.search(r"[$`*?\[]", value) for value in values):
                reachable_raw.append((0, SHELL_UNRESOLVED_CONTROL_SENTINEL))
            else:
                reachable_raw.extend(
                    (line, inline_for.group(2)) for _value in values
                )
            if inline_for.group(3):
                reachable_raw.append((line, inline_for.group(3)))
            continue
        true_if = bool(
            re.match(r"^if\s+(?:true|!\s*false)\s*;?\s*then\b", stripped)
        )
        if true_if:
            inline_true = re.match(
                r"^if\s+(?:true|!\s*false)\s*;?\s*then\s+(.*?)"
                r"(?:;\s*(?:else|elif)\b.*)?;\s*fi(?:\s*;\s*(.*))?$",
                stripped,
            )
            if inline_true:
                reachable_raw.append((line, inline_true.group(1)))
                if inline_true.group(2):
                    reachable_raw.append((line, inline_true.group(2)))
                continue
        false_if = bool(re.match(r"^if\s+(?:false|!\s*true)\s*;?\s*then\b", stripped))
        false_loop = bool(
            re.match(
                r"^(?:while\s+(?:false|!\s*true)|until\s+(?:true|!\s*false))"
                r"\s*;?\s*do\b",
                stripped,
            )
        )
        if skipped_closers:
            if re.match(r"^(?:if\b.*\bthen|while\b.*\bdo|until\b.*\bdo)", stripped):
                skipped_closers.append("fi" if stripped.startswith("if") else "done")
            if stripped in {"else", "elif"} and len(skipped_closers) == 1:
                reachable_raw.append((0, SHELL_UNRESOLVED_CONTROL_SENTINEL))
            if stripped in {"fi", "done"} and stripped == skipped_closers[-1]:
                skipped_closers.pop()
            continue
        if false_if or false_loop:
            closer = "fi" if false_if else "done"
            if false_if and re.search(r";\s*(?:else|elif)\b", stripped):
                alternate = re.match(
                    r"^if\s+(?:false|!\s*true)\s*;?\s*then\b.*?;\s*else\s+"
                    r"(.*?);\s*fi(?:\s*;\s*(.*))?$",
                    stripped,
                )
                if alternate:
                    reachable_raw.append((line, alternate.group(1)))
                    if alternate.group(2):
                        reachable_raw.append((line, alternate.group(2)))
                else:
                    reachable_raw.append((0, SHELL_UNRESOLVED_CONTROL_SENTINEL))
                continue
            inline = re.match(
                rf"^.*;\s*{closer}(?:\s*;\s*(.*))?$", stripped
            )
            if inline:
                if inline.group(1):
                    reachable_raw.append((line, inline.group(1)))
                continue
            skipped_closers.append("fi" if false_if else "done")
            continue
        reachable_raw.append((line, command))
    raw = reachable_raw
    functions: dict[str, list[tuple[int, str]]] = {}
    top_level: list[tuple[int, str]] = []
    index = 0
    name_pattern = r"[A-Za-z_][A-Za-z0-9_]*"
    definition = re.compile(
        rf"^(?:function\s+({name_pattern})|({name_pattern})\s*\(\s*\))\s*\{{\s*$"
    )
    one_line_definition = re.compile(
        rf"^(?:function\s+({name_pattern})|({name_pattern})\s*\(\s*\))"
        rf"\s*\{{\s*(.*?)\s*;\s*\}}\s*(?:;\s*(.*))?$"
    )
    while index < len(raw):
        line, command = raw[index]
        stripped = command.strip()
        one_line = one_line_definition.match(stripped)
        if one_line:
            name = one_line.group(1) or one_line.group(2)
            functions[name] = [(line, one_line.group(3))]
            if one_line.group(4):
                top_level.append((line, one_line.group(4)))
            index += 1
            continue
        match = definition.match(stripped)
        if not match:
            top_level.append((line, command))
            index += 1
            continue
        body: list[tuple[int, str]] = []
        index += 1
        while index < len(raw) and raw[index][1].strip() not in {"}", "};"}:
            body.append(raw[index])
            index += 1
        if index < len(raw):
            index += 1
        functions[match.group(1) or match.group(2)] = body

    result: list[tuple[int, str]] = []
    expansion_budget = 10000

    def expand(commands: list[tuple[int, str]], stack: tuple[str, ...] = ()) -> None:
        nonlocal expansion_budget
        for line, command in commands:
            if expansion_budget <= 0:
                return
            expansion_budget -= 1
            result.append((line, command))
            try:
                tokens = shell_tokens(command)
            except ValueError:
                continue
            if any(
                token.rsplit("/", 1)[-1] == "eval"
                and shell_command_position(tokens, token_index)
                for token_index, token in enumerate(tokens)
            ):
                result.append((line, SHELL_UNRESOLVED_CONTROL_SENTINEL))
            if re.search(
                r"(?:\b(?:source|bash|sh|dash|zsh|ksh)|(?:^|[;&|]\s*)\.)"
                r"\s+(?:-[^\s]+\s+)*'[^']*\$[^']*'",
                strip_shell_comment(command),
            ):
                result.append((line, SHELL_UNRESOLVED_CONTROL_SENTINEL))
            for token_index, token in enumerate(tokens):
                if token.rsplit("/", 1)[-1] != "xargs":
                    continue
                command_end = next(
                    (
                        cursor
                        for cursor in range(token_index + 1, len(tokens))
                        if tokens[cursor] in SHELL_COMMAND_BOUNDARIES
                    ),
                    len(tokens),
                )
                if any(
                    value in {"-r", "--no-run-if-empty"}
                    for value in tokens[token_index + 1:command_end]
                ):
                    result.append((line, SHELL_UNRESOLVED_CONTROL_SENTINEL))
            for token_index, token in enumerate(tokens):
                name = token.rsplit("/", 1)[-1]
                if (
                    name in functions
                    and name not in stack
                    and shell_command_position(tokens, token_index)
                ):
                    expand(functions[name], (*stack, name))

    expand(top_level)
    if expansion_budget <= 0:
        result.append((0, SHELL_EXPANSION_BUDGET_SENTINEL))
    return result


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


def _raw_shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(
        strip_shell_comment(command), posix=True, punctuation_chars=";&|<>(){}"
    )
    lexer.commenters = ""
    lexer.whitespace_split = True
    return list(lexer)


def shell_tokens(command: str) -> list[str]:
    """Tokenize and prune branches unreachable after literal true/false."""
    tokens = _raw_shell_tokens(command)
    segments: list[tuple[list[str], str]] = []
    current: list[str] = []
    for token in tokens:
        if token in {"&&", "||", ";"}:
            segments.append((current, token))
            current = []
        else:
            current.append(token)
    segments.append((current, ""))
    result: list[str] = []
    prior_status: bool | None = None
    prior_operator = ""
    for segment, following_operator in segments:
        executes = not (
            (prior_operator == "&&" and prior_status is False)
            or (prior_operator == "||" and prior_status is True)
        )
        if executes and segment:
            if result and prior_operator:
                result.append(prior_operator)
            result.extend(segment)
            executable = next(
                (
                    value.rsplit("/", 1)[-1]
                    for value in segment
                    if not SHELL_ASSIGNMENT_WORD.fullmatch(value)
                    and value not in {"!", "if", "then", "elif", "else", "do"}
                ),
                "",
            )
            if executable in {"true", ":"}:
                prior_status = True
            elif executable == "false":
                prior_status = False
            else:
                prior_status = None
        prior_operator = following_operator
    return result


def module_entrypoint(module: str) -> str:
    return f"{str(module).replace('.', '/')}.py"


def module_execution_entrypoints(module: str) -> tuple[str, str]:
    """Return both file-module and package ``__main__`` execution targets."""
    base = str(module).replace(".", "/")
    return f"{base}.py", f"{base}/__main__.py"


def normalize_script_entrypoint(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    root_prefix = ROOT.as_posix().rstrip("/") + "/"
    if normalized.casefold().startswith(root_prefix.casefold()):
        normalized = normalized[len(root_prefix):]
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized and not normalized.startswith("${{"):
        normalized = posixpath.normpath(normalized)
        if normalized == ".":
            normalized = ""
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


SHELL_COMMAND_BOUNDARIES = {";", "&&", "||", "|", "&", "(", ")", "{", "}"}
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
        if executable in {
            "if", "then", "elif", "else", "while", "until", "do", "!", "{", "(",
        }:
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
        if executable == "timeout":
            cursor += 1
            while cursor < index:
                value = tokens[cursor]
                if value in {"-k", "--kill-after", "-s", "--signal"}:
                    cursor += 2
                    continue
                if value.startswith("-"):
                    cursor += 1
                    continue
                cursor += 1  # duration
                break
            continue
        if executable == "sudo":
            cursor += 1
            while cursor < index:
                value = tokens[cursor]
                if value in {
                    "-u", "--user", "-g", "--group", "-h", "--host",
                    "-p", "--prompt", "-C", "--close-from", "-T", "--command-timeout",
                }:
                    cursor += 2
                    continue
                if value.startswith("-"):
                    cursor += 1
                    continue
                break
            continue
        if executable in {"unshare", "nice", "ionice"}:
            cursor += 1
            while cursor < index and tokens[cursor].startswith("-"):
                cursor += 1
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
        if executable == "xargs":
            cursor += 1
            while cursor < index:
                value = tokens[cursor]
                if value in {
                    "-a", "--arg-file", "-E", "--eof", "-I", "--replace",
                    "-L", "--max-lines", "-n", "--max-args", "-P",
                    "--max-procs", "-s", "--max-chars",
                }:
                    cursor += 2
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
    text = executable_shell_text(text)
    result: list[dict[str, Any]] = []
    literal_names: dict[str, str] = {}
    dynamic_names: set[str] = set()
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
                    dynamic_names.discard(name)
                else:
                    literal_names.pop(name, None)
                    dynamic_names.add(name)

        def resolved_token(value: str) -> str:
            match = re.fullmatch(
                r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
                value,
            )
            if not match:
                return value
            return literal_names.get(match.group(1) or match.group(2), value)

        def unresolved_operand(value: str) -> bool:
            stripped = str(value).strip()
            return bool(
                re.fullmatch(
                    r"(?:\$\{\{.*?\}\}|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|"
                    r"`[^`]*`|\$\(.*\))",
                    stripped,
                    re.DOTALL,
                )
            )

        for index, token in enumerate(tokens):
            shell_name = token.rsplit("/", 1)[-1]
            if (
                shell_name in {"bash", "sh", "dash", "zsh", "ksh"}
                and shell_command_position(tokens, index)
            ):
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
            resolved_command_token = resolved_token(token)
            if (
                shell_command_position(tokens, index)
                and resolved_command_token != token
                and re.search(r"\s", resolved_command_token)
            ):
                for row in python_invocations(resolved_command_token):
                    copied = dict(row)
                    copied["line"] = line
                    copied["wrapped_by"] = "expanded-command-variable"
                    result.append(copied)
                continue
            executable = resolved_command_token.rsplit("/", 1)[-1]
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
            if not shell_command_position(tokens, index):
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
            module_name = ""
            unresolved_entrypoint = False
            while cursor < len(argv):
                value = resolved_token(argv[cursor])
                if value == "-m" and cursor + 1 < len(argv):
                    module_name = resolved_token(argv[cursor + 1])
                    entrypoint = module_entrypoint(module_name)
                    unresolved_entrypoint = bool(re.search(r"[$`]", module_name))
                    break
                if value.startswith("-m") and len(value) > 2:
                    module_name = value[2:]
                    entrypoint = module_entrypoint(module_name)
                    unresolved_entrypoint = bool(re.search(r"[$`]", module_name))
                    break
                if value == "-c":
                    entrypoint = value
                    if cursor + 1 < len(argv):
                        command_source = resolved_token(argv[cursor + 1])
                        unresolved_entrypoint = unresolved_operand(command_source)
                    else:
                        unresolved_entrypoint = True
                    break
                if value.startswith("-c") and len(value) > 2:
                    entrypoint = "-c"
                    command_source = value[2:]
                    unresolved_entrypoint = unresolved_operand(command_source)
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
                unresolved_entrypoint = bool(re.search(r"[$`]", entrypoint))
                break
            startup_entrypoints: list[str] = []
            pythonpath = literal_names.get("PYTHONPATH", "")
            ignores_environment = any(
                option in argv[1:] for option in {"-E", "-I", "-S"}
            )
            if pythonpath and not ignores_environment:
                for part in re.split(r"[;:]", pythonpath):
                    normalized = normalize_script_entrypoint(part or ".")
                    for startup in ("sitecustomize.py", "usercustomize.py"):
                        startup_entrypoints.append(
                            Path(normalized, startup).as_posix()
                            if normalized not in {"", "."}
                            else startup
                        )
            result.append(
                {
                    "line": line,
                    "entrypoint": entrypoint,
                    "argv": argv,
                    "command": command,
                    "command_source": command_source,
                    "module_name": module_name,
                    "startup_entrypoints": sorted(set(startup_entrypoints)),
                    "unresolved_entrypoint": unresolved_entrypoint,
                    "unresolved_pythonpath": bool(
                        "PYTHONPATH" in dynamic_names and not ignores_environment
                    ),
                    "unresolved_stdin_pipeline": bool(
                        entrypoint in STDIN_ENTRYPOINTS and "|" in tokens[:index]
                    ),
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
    result: set[str] = set()
    for row in python_invocations(text):
        entrypoint = str(row["entrypoint"])
        if entrypoint in {"", "-c", *STDIN_ENTRYPOINTS}:
            continue
        result.add(entrypoint)
        module_name = str(row.get("module_name") or "")
        if module_name:
            result.update(module_execution_entrypoints(module_name))
        result.update(str(value) for value in row.get("startup_entrypoints") or [])
    return result


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


def imported_callable_names(
    tree: ast.AST, module_members: Mapping[str, set[str]]
) -> set[str]:
    """Resolve imported callables and their definite assignment aliases."""
    callables = {
        f"{module}.{member}"
        for module, members in module_members.items()
        for member in members
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in module_members:
                    continue
                local = alias.asname or alias.name
                callables.update(
                    f"{local}.{member}" for member in module_members[alias.name]
                )
        elif isinstance(node, ast.ImportFrom) and node.module in module_members:
            for alias in node.names:
                if alias.name in module_members[node.module]:
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
            for target, value in pairs:
                if (
                    isinstance(target, ast.Name)
                    and dotted_expression_name(value) in callables
                    and target.id not in callables
                ):
                    callables.add(target.id)
                    changed = True
    return callables


def literal_inprocess_python_sources(source: str) -> tuple[str, ...]:
    """Return definite string payloads executed through built-in exec/eval."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    assignments = python_assignment_values(tree)
    callables = imported_callable_names(
        tree, {"builtins": {"exec", "eval"}}
    ) | {"exec", "eval"}
    payloads: set[str] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or dotted_expression_name(node.func) not in callables
            or not node.args
        ):
            continue
        for bound in bound_expression_nodes(node.args[0], assignments):
            if isinstance(bound, ast.Constant) and isinstance(bound.value, str):
                payload = str(bound.value)
                if payload and payload != source:
                    payloads.add(payload)
    return tuple(sorted(payloads))


def transitive_literal_python_sources(source: str) -> tuple[str, ...]:
    """Return the bounded transitive closure of literal exec/eval payloads."""
    seen = {source}
    result: set[str] = set()
    pending = list(literal_inprocess_python_sources(source))
    while pending and len(seen) <= PYTHON_DYNAMIC_EXEC_SOURCE_BUDGET:
        payload = pending.pop()
        if payload in seen:
            continue
        seen.add(payload)
        result.add(payload)
        pending.extend(literal_inprocess_python_sources(payload))
    if pending:
        result.add(PYTHON_DYNAMIC_EXEC_BUDGET_SENTINEL)
    return tuple(sorted(result))


def literal_dynamic_import_module(
    node: ast.AST,
    callables: set[str] | None = None,
    source_path: str = "",
    assignments: Mapping[str, list[ast.AST]] | None = None,
) -> str:
    """Resolve common dynamic imports when their module is definitely finite."""
    if not isinstance(node, ast.Call) or not node.args:
        return ""
    func = dotted_expression_name(node.func)
    if func not in (
        callables or {"importlib.import_module", "__import__", "builtins.__import__"}
    ):
        return ""
    first = node.args[0]
    module_values = {
        str(value.value)
        for bound in bound_expression_nodes(first, assignments or {})
        for value in ast.walk(bound)
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }
    if len(module_values) > 1:
        return PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL
    if not module_values:
        return ""
    if func in (callables or {"importlib.import_module", "__import__", "builtins.__import__"}):
        module = next(iter(module_values))
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


def resolved_import_from_module(node: ast.ImportFrom, source_path: str = "") -> str:
    """Resolve an ``ImportFrom`` module against its containing package."""
    concrete_path = source_path.split("::", 1)[0]
    source_parts = (
        list(Path(concrete_path).with_suffix("").parts[:-1])
        if concrete_path
        else []
    )
    if node.level:
        keep = max(0, len(source_parts) - node.level + 1)
        parts = source_parts[:keep]
    else:
        parts = []
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


@lru_cache(maxsize=4096)
def _local_import_candidates_direct(source: str, source_path: str) -> tuple[str, ...]:
    """Parse import candidates once; callers filter them against a repository."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    result: set[str] = set()
    assignments = python_assignment_values(tree)
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
    for node in ast.walk(tree):
        candidates: list[str] = []
        if isinstance(node, ast.Import):
            candidates.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolved_import_from_module(node, source_path)
            if base:
                candidates.append(base)
            candidates.extend(
                f"{base}.{alias.name}" if base else alias.name
                for alias in node.names
                if alias.name != "*"
            )
        elif isinstance(node, ast.Call):
            dynamic_module = literal_dynamic_import_module(
                node, dynamic_callables, source_path, assignments
            )
            if dynamic_module:
                candidates.append(dynamic_module)
            call_name = dotted_expression_name(node.func)
            if node.args and call_name in run_module_callables:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    result.update(module_execution_entrypoints(value.value))
                    candidates.append(value.value)
            elif node.args and call_name in run_path_callables:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    result.add(normalize_script_entrypoint(value.value))
            if (
                call_name.rsplit(".", 1)[-1] == "spec_from_file_location"
                and len(node.args) >= 2
            ):
                for bound in bound_expression_nodes(node.args[1], assignments):
                    if isinstance(bound, ast.Constant) and isinstance(
                        bound.value, str
                    ):
                        result.add(normalize_script_entrypoint(bound.value))
        for module in candidates:
            if module == PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL:
                result.add(module)
            else:
                result.update(_module_candidates(module))
    return tuple(sorted(result))


@lru_cache(maxsize=4096)
def local_import_candidates(source: str, source_path: str = "") -> tuple[str, ...]:
    """Return imports from source and literal in-process Python payloads."""
    result = set(_local_import_candidates_direct(source, source_path))
    for payload in transitive_literal_python_sources(source):
        result.update(_local_import_candidates_direct(payload, source_path))
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
    "create_subprocess_exec", "create_subprocess_shell",
}


def python_assignment_values(tree: ast.AST) -> dict[str, list[ast.AST]]:
    assignments: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        pairs: list[tuple[ast.AST, ast.AST]] = []
        if isinstance(node, ast.Assign):
            pairs.extend((target, node.value) for target in node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            pairs.append((node.target, node.value))
        elif isinstance(node, ast.NamedExpr):
            pairs.append((node.target, node.value))
        for target, value in pairs:
            if isinstance(target, ast.Name):
                assignments.setdefault(target.id, []).append(value)
    return assignments


def bound_expression_nodes(
    expression: ast.AST, assignments: Mapping[str, list[ast.AST]]
) -> list[ast.AST]:
    """Return an expression plus every definite assignment it references."""
    result: list[ast.AST] = []
    pending = [expression]
    seen_nodes: set[int] = set()
    expanded_names: set[str] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen_nodes:
            continue
        seen_nodes.add(id(current))
        result.append(current)
        for child in ast.walk(current):
            if not isinstance(child, ast.Name) or child.id in expanded_names:
                continue
            expanded_names.add(child.id)
            pending.extend(assignments.get(child.id, []))
    return result


def process_callable_names(tree: ast.AST) -> set[str]:
    """Return exact process-launch spellings, including definite aliases."""
    os_names = {
        "system", "popen", "execv", "execve", "execvp", "execvpe", "execl",
        "execle", "execlp", "execlpe", "spawnl", "spawnle", "spawnlp",
        "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "posix_spawn", "posix_spawnp",
    }
    subprocess_names = {
        "run", "popen", "call", "check_call", "check_output", "getoutput",
        "getstatusoutput",
    }
    asyncio_names = {"create_subprocess_exec", "create_subprocess_shell"}
    pty_names = {"spawn"}
    callables = {f"subprocess.{name}" for name in subprocess_names}
    callables.update(f"os.{name}" for name in os_names)
    callables.update(f"asyncio.{name}" for name in asyncio_names)
    callables.update(f"pty.{name}" for name in pty_names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "subprocess":
                    callables.update(f"{local}.{name}" for name in subprocess_names)
                elif alias.name == "os":
                    callables.update(f"{local}.{name}" for name in os_names)
                elif alias.name == "asyncio":
                    callables.update(f"{local}.{name}" for name in asyncio_names)
                elif alias.name == "pty":
                    callables.update(f"{local}.{name}" for name in pty_names)
        elif isinstance(node, ast.ImportFrom) and node.module in {
            "subprocess", "os", "asyncio", "pty",
        }:
            allowed = (
                subprocess_names
                if node.module == "subprocess"
                else asyncio_names
                if node.module == "asyncio"
                else pty_names
                if node.module == "pty"
                else os_names
            )
            for alias in node.names:
                if alias.name.casefold() in allowed:
                    callables.add(alias.asname or alias.name)
    normalized = {value.casefold() for value in callables}
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
                if (
                    dotted_expression_name(value).casefold() in normalized
                    and target.id.casefold() not in normalized
                ):
                    normalized.add(target.id.casefold())
                    changed = True
    return normalized


def recognized_process_call(node: ast.Call, callables: set[str]) -> bool:
    name = dotted_expression_name(node.func).casefold()
    return (
        name in callables
        or name.rsplit(".", 1)[-1] in PROCESS_CALL_BASENAMES
    )


def process_python_candidates(strings: list[str]) -> set[str]:
    candidates: set[str] = set()
    for value in strings:
        candidates.update(python_entrypoints(value))
        normalized = normalize_script_entrypoint(value)
        if normalized.endswith(".py"):
            candidates.add(normalized)
    for index, value in enumerate(strings):
        executable = normalize_script_entrypoint(value).rsplit("/", 1)[-1]
        if not re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable):
            continue
        cursor = index + 1
        while cursor < len(strings):
            operand = strings[cursor]
            if operand == "-m" and cursor + 1 < len(strings):
                candidates.update(module_execution_entrypoints(strings[cursor + 1]))
                break
            if operand == "-c" and cursor + 1 < len(strings):
                candidates.update(local_import_candidates(strings[cursor + 1]))
                break
            if operand.startswith("-"):
                cursor += 1
                continue
            candidates.add(normalize_script_entrypoint(operand))
            break
    return candidates


def process_argv_expressions(node: ast.Call) -> tuple[ast.AST, ...]:
    """Return argv-bearing expressions for subprocess and os exec/spawn APIs."""
    basename = dotted_expression_name(node.func).casefold().rsplit(".", 1)[-1]
    if basename == "create_subprocess_exec":
        return tuple(node.args)
    if basename == "create_subprocess_shell":
        return tuple(node.args[:1])
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


def process_cwd_values(
    node: ast.Call, assignments: Mapping[str, list[ast.AST]]
) -> tuple[str, ...]:
    cwd = next(
        (keyword.value for keyword in node.keywords if keyword.arg == "cwd"),
        None,
    )
    if cwd is None:
        return ()
    return tuple(
        sorted(
            {
                str(value.value)
                for bound in bound_expression_nodes(cwd, assignments)
                for value in ast.walk(bound)
                if isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            }
        )
    )


def process_pythonpath_values(
    node: ast.Call, assignments: Mapping[str, list[ast.AST]]
) -> tuple[str, ...]:
    environment = next(
        (keyword.value for keyword in node.keywords if keyword.arg == "env"),
        None,
    )
    if environment is None:
        return ()
    values: set[str] = set()
    for bound in bound_expression_nodes(environment, assignments):
        for candidate in ast.walk(bound):
            value_nodes: list[ast.AST] = []
            if isinstance(candidate, ast.Dict):
                value_nodes.extend(
                    value
                    for key, value in zip(candidate.keys, candidate.values)
                    if isinstance(key, ast.Constant) and key.value == "PYTHONPATH"
                )
            elif (
                isinstance(candidate, ast.Call)
                and dotted_expression_name(candidate.func) in {"dict", "builtins.dict"}
            ):
                value_nodes.extend(
                    keyword.value
                    for keyword in candidate.keywords
                    if keyword.arg == "PYTHONPATH"
                )
            for value in value_nodes:
                values.update(
                    str(item.value)
                    for item in bound_expression_nodes(value, assignments)
                    if isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                )
    return tuple(sorted(values))


def pythonpath_startup_candidates(
    values: tuple[str, ...], cwd_values: tuple[str, ...] = ()
) -> set[str]:
    result: set[str] = set()
    working_directories = cwd_values or ("",)
    for pythonpath in values:
        for part in re.split(r"[;:]", pythonpath):
            normalized = normalize_script_entrypoint(part or ".")
            for startup in ("sitecustomize.py", "usercustomize.py"):
                candidate = (
                    Path(normalized, startup).as_posix()
                    if normalized not in {"", "."}
                    else startup
                )
                result.update(
                    resolve_working_directory_path(candidate, cwd)
                    for cwd in working_directories
                )
    return result


@lru_cache(maxsize=4096)
def _local_process_candidates_direct(source: str) -> tuple[str, ...]:
    """Return literal Python entrypoints passed through process-launch calls."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    assignments = python_assignment_values(tree)
    callables = process_callable_names(tree)
    candidates: set[str] = set()
    has_process_call = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not recognized_process_call(node, callables):
            continue
        has_process_call = True
        argv_expressions = process_argv_expressions(node)
        if not argv_expressions:
            continue
        call_expressions: list[ast.AST] = []
        for expression in argv_expressions:
            call_expressions.extend(bound_expression_nodes(expression, assignments))
        strings = [
            str(value.value)
            for expression in call_expressions
            for value in ast.walk(expression)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
        call_candidates = process_python_candidates(strings)
        cwd_values = process_cwd_values(node, assignments)
        if cwd_values:
            call_candidates = {
                resolve_working_directory_path(candidate, cwd)
                for candidate in call_candidates
                for cwd in cwd_values
            }
        candidates.update(call_candidates)
        candidates.update(
            pythonpath_startup_candidates(
                process_pythonpath_values(node, assignments), cwd_values
            )
        )

    if has_process_call:
        # A helper can pass finite caller-built argv into the eventual process
        # sink. Conservatively bind every local-looking Python literal in that
        # source so allowlists/dispatch tables cannot escape reachability.
        for literal in ast.walk(tree):
            if not (
                isinstance(literal, ast.Constant)
                and isinstance(literal.value, str)
            ):
                continue
            normalized = normalize_script_entrypoint(str(literal.value))
            if normalized.endswith(".py"):
                candidates.add(normalized)

    return tuple(sorted(candidates))


@lru_cache(maxsize=4096)
def local_process_candidates(source: str) -> tuple[str, ...]:
    result = set(_local_process_candidates_direct(source))
    for payload in transitive_literal_python_sources(source):
        result.update(_local_process_candidates_direct(payload))
    return tuple(sorted(result))


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
def _local_process_shell_candidates_direct(source: str) -> tuple[str, ...]:
    """Return literal shell executables/scripts in process argv expressions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    assignments = python_assignment_values(tree)
    callables = process_callable_names(tree)
    candidates: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not recognized_process_call(node, callables):
            continue
        for expression in process_argv_expressions(node):
            strings = [
                str(value.value)
                for bound in bound_expression_nodes(expression, assignments)
                for value in ast.walk(bound)
                if isinstance(value, ast.Constant)
                and isinstance(value.value, str)
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


@lru_cache(maxsize=4096)
def local_process_shell_candidates(source: str) -> tuple[str, ...]:
    result = set(_local_process_shell_candidates_direct(source))
    for payload in transitive_literal_python_sources(source):
        result.update(_local_process_shell_candidates_direct(payload))
    return tuple(sorted(result))


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
def _python_process_launches_direct(source: str) -> tuple[str, ...]:
    """Fingerprint process launches, including unresolved dynamic argv."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    callables = process_callable_names(tree)
    assignments = python_assignment_values(tree)
    findings: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted_expression_name(node.func)
        if not recognized_process_call(node, callables):
            continue
        argv_expressions = process_argv_expressions(node)
        if not argv_expressions:
            continue
        cwd = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "cwd"),
            None,
        )
        cwd_nodes = bound_expression_nodes(cwd, assignments) if cwd is not None else []
        cwd_sources = [
            (ast.get_source_segment(source, bound) or source)
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .strip()
            for bound in cwd_nodes
        ]
        environment = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "env"),
            None,
        )
        environment_nodes = (
            bound_expression_nodes(environment, assignments)
            if environment is not None
            else []
        )
        environment_sources = [
            (ast.get_source_segment(source, bound) or source)
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .strip()
            for bound in environment_nodes
        ]
        for expression in argv_expressions:
            bound_nodes = bound_expression_nodes(expression, assignments)
            # Bind both argv syntax and referenced definite assignments.  A
            # variable-only target change must alter this fingerprint.
            expression_sources = [
                (ast.get_source_segment(source, bound) or source)
                .replace("\r\n", "\n")
                .replace("\r", "\n")
                .strip()
                for bound in bound_nodes
            ]
            expression_sources.extend(f"cwd:{value}" for value in cwd_sources)
            expression_sources.extend(
                f"env:{value}" for value in environment_sources
            )
            binding_source = (
                expression_sources[0]
                if len(expression_sources) == 1
                else json.dumps(
                    sorted(set(expression_sources)), separators=(",", ":")
                )
            )
            expression_hash = hashlib.sha256(
                binding_source.encode("utf-8")
            ).hexdigest()[:16]
            strings = [
                str(value.value)
                for bound in bound_nodes
                for value in ast.walk(bound)
                if isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ]
            candidates = sorted(
                process_python_candidates(strings)
                | pythonpath_startup_candidates(
                    process_pythonpath_values(node, assignments),
                    process_cwd_values(node, assignments),
                )
            )
            detail = ",".join(candidates) if candidates else "UNRESOLVED_LOCAL_PROCESS"
            findings.add(
                f"line={getattr(node, 'lineno', 0)}:{name or '<call>'}:"
                f"argv={expression_hash}:{detail}"
            )
    return tuple(sorted(findings))


@lru_cache(maxsize=4096)
def python_process_launches(source: str) -> tuple[str, ...]:
    result = set(_python_process_launches_direct(source))
    for payload in transitive_literal_python_sources(source):
        result.update(
            f"dynamic-exec:{finding}"
            for finding in _python_process_launches_direct(payload)
        )
    return tuple(sorted(result))


@lru_cache(maxsize=2048)
def python_main_call_counts(
    source: str, source_path: str = ""
) -> tuple[tuple[str, int], ...]:
    """Count protected executions, including definite local call graphs."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    names: dict[str, str] = {}
    modules: dict[str, str] = {}
    assignments = python_assignment_values(tree)
    dynamic_callables = dynamic_import_callables(tree)
    runpy_callables = imported_callable_names(
        tree, {"runpy": {"run_module", "run_path"}}
    )
    exec_callables = imported_callable_names(
        tree, {"builtins": {"exec", "eval"}}
    ) | {"exec", "eval", "builtins.exec", "builtins.eval"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            resolved_module = resolved_import_from_module(node, source_path)
            module_path = module_entrypoint(resolved_module)
            for alias in node.names:
                if node.module is not None and alias.name == "main":
                    names[alias.asname or alias.name] = module_path
                elif resolved_module:
                    modules[alias.asname or alias.name] = module_entrypoint(
                        f"{resolved_module}.{alias.name}"
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
                value.value, dynamic_callables, source_path, assignments
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
                module_expression, dynamic_callables, source_path, assignments
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
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    local_function_aliases = {name: name for name in function_names}
    alias_changed = True
    while alias_changed:
        alias_changed = False
        for node in ast.walk(tree):
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(node, ast.Assign):
                pairs.extend((target, node.value) for target in node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                pairs.append((node.target, node.value))
            elif isinstance(node, ast.NamedExpr):
                pairs.append((node.target, node.value))
            for target, value in pairs:
                if not isinstance(target, ast.Name) or not isinstance(value, ast.Name):
                    continue
                resolved = local_function_aliases.get(value.id)
                if resolved and local_function_aliases.get(target.id) != resolved:
                    local_function_aliases[target.id] = resolved
                    alias_changed = True
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    definition_time_owner: dict[ast.AST, ast.AST] = {}
    for definition_node in ast.walk(tree):
        if not isinstance(definition_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        expressions: list[ast.AST] = list(definition_node.decorator_list)
        expressions.extend(definition_node.args.defaults)
        expressions.extend(
            value for value in definition_node.args.kw_defaults if value is not None
        )
        if definition_node.returns is not None:
            expressions.append(definition_node.returns)
        for argument in (
            list(definition_node.args.posonlyargs)
            + list(definition_node.args.args)
            + list(definition_node.args.kwonlyargs)
        ):
            if argument.annotation is not None:
                expressions.append(argument.annotation)
        for expression in expressions:
            for descendant in ast.walk(expression):
                definition_time_owner[descendant] = definition_node

    def owner_scope(node: ast.AST) -> str:
        definition_owner = definition_time_owner.get(node)
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if current is definition_owner:
                    current = parents.get(current)
                    continue
                return current.name
            current = parents.get(current)
        return "<module>"

    protected_by_scope: dict[str, dict[str, int]] = {}
    local_calls: dict[str, dict[str, int]] = {}

    def add_protected(scope: str, target: str, count: int = 1) -> None:
        if not target or count <= 0:
            return
        bucket = protected_by_scope.setdefault(scope, {})
        bucket[target] = bucket.get(target, 0) + count

    assignments = python_assignment_values(tree)

    def thread_callback(expression: ast.AST) -> str:
        if not isinstance(expression, ast.Call):
            return ""
        call_name = dotted_expression_name(expression.func)
        if call_name.rsplit(".", 1)[-1] not in {"Thread", "Process"}:
            return ""
        callback = next(
            (keyword.value for keyword in expression.keywords if keyword.arg == "target"),
            expression.args[1] if len(expression.args) > 1 else None,
        )
        return main_target(callback) if callback is not None else ""

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        scope = owner_scope(node)
        target = main_target(node.func)
        if target:
            add_protected(scope, target)
        call_name = dotted_expression_name(node.func)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"start", "run"}
        ):
            launch_values = bound_expression_nodes(node.func.value, assignments)
            launched_callbacks = {
                callback
                for value in launch_values
                if (callback := thread_callback(value))
            }
            for callback_target in sorted(launched_callbacks):
                add_protected(scope, callback_target)
        if call_name in runpy_callables and node.args:
            values = [
                str(bound.value)
                for bound in bound_expression_nodes(
                    node.args[0], python_assignment_values(tree)
                )
                if isinstance(bound, ast.Constant) and isinstance(bound.value, str)
            ]
            basename = call_name.rsplit(".", 1)[-1]
            if basename == "run_path":
                for value in values:
                    add_protected(scope, normalize_script_entrypoint(value))
            elif basename == "run_module":
                run_name = next(
                    (
                        keyword.value.value
                        for keyword in node.keywords
                        if keyword.arg == "run_name"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ),
                    "",
                )
                if run_name == "__main__":
                    for value in values:
                        add_protected(scope, module_entrypoint(value))
        if call_name in exec_callables:
            if node.args:
                for bound in bound_expression_nodes(
                    node.args[0], python_assignment_values(tree)
                ):
                    if not (
                        isinstance(bound, ast.Constant)
                        and isinstance(bound.value, str)
                        and bound.value != source
                    ):
                        continue
                    for embedded_target, embedded_count in python_main_call_counts(
                        str(bound.value), f"{source_path}::dynamic-exec"
                    ):
                        add_protected(scope, embedded_target, embedded_count)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in local_function_aliases
        ):
            bucket = local_calls.setdefault(scope, {})
            function = local_function_aliases[node.func.id]
            bucket[function] = bucket.get(function, 0) + 1

    execution_count = {name: 0 for name in function_names}
    cap = 1_000_000
    for _ in range(max(1, len(function_names) + 1)):
        changed = False
        for function in sorted(function_names):
            total = local_calls.get("<module>", {}).get(function, 0)
            total += sum(
                execution_count.get(caller, 1) * edges.get(function, 0)
                for caller, edges in local_calls.items()
                if caller != "<module>"
            )
            updated = min(cap, max(0, total))
            if updated != execution_count[function]:
                execution_count[function] = updated
                changed = True
        if not changed:
            break

    counts: dict[str, int] = dict(protected_by_scope.get("<module>", {}))
    for scope, targets in protected_by_scope.items():
        if scope == "<module>":
            continue
        multiplier = execution_count.get(scope, 1)
        if multiplier <= 0:
            continue
        for protected_target, count in targets.items():
            counts[protected_target] = counts.get(protected_target, 0) + count * multiplier
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
    # The script-level option parser receives tokens after ``--`` as
    # positionals.  They cannot satisfy a reviewed command profile.
    effective_argv = argv[:argv.index("--")] if "--" in argv else argv
    sequences = [
        shlex.split(str(token), posix=True)
        for token in requirement.get("required_tokens") or []
    ]
    if not all(
        contains_argv_sequence(effective_argv, sequence) for sequence in sequences
    ):
        return False
    for flag in requirement.get("required_flags") or []:
        if effective_argv.count(str(flag)) != 1:
            return False
    for option, expected in (
        requirement.get("required_option_values") or {}
    ).items():
        if argv_option_values(effective_argv, str(option)) != [str(expected)]:
            return False
    for option in requirement.get("required_nonempty_options") or []:
        values = argv_option_values(effective_argv, str(option))
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
def _authority_write_sinks_direct(
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
        for name in ("copy", "copy2", "copyfile", "copytree")
    }
    move_functions = {"shutil.move"}
    delete_functions = {
        f"os.{name}" for name in ("remove", "unlink", "rmdir", "removedirs")
    }
    link_functions = {
        f"os.{name}" for name in ("link", "symlink")
    }
    rename_functions = {"os.rename", "os.replace", "os.renames"}
    os_open_functions = {"os.open"}
    truncate_functions = {"os.truncate"}
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
                            "copy", "copy2", "copyfile", "copytree"
                        )
                    )
                    move_functions.add(f"{local}.move")
                    delete_functions.add(f"{local}.rmtree")
                elif alias.name == "os":
                    delete_functions.update(
                        f"{local}.{name}"
                        for name in ("remove", "unlink", "rmdir", "removedirs")
                    )
                    link_functions.update(
                        f"{local}.{name}" for name in ("link", "symlink")
                    )
                    rename_functions.update(
                        f"{local}.{name}" for name in ("rename", "replace", "renames")
                    )
                    os_open_functions.add(f"{local}.open")
                    truncate_functions.add(f"{local}.truncate")
        elif isinstance(imported, ast.ImportFrom) and imported.module in {
            "io", "builtins", "shutil", "os"
        }:
            for alias in imported.names:
                if alias.name == "open":
                    open_aliases.add(alias.asname or alias.name)
                elif imported.module == "shutil" and alias.name in {
                    "copy", "copy2", "copyfile", "copytree"
                }:
                    copy_functions.add(alias.asname or alias.name)
                elif imported.module == "shutil" and alias.name == "move":
                    move_functions.add(alias.asname or alias.name)
                elif imported.module == "shutil" and alias.name == "rmtree":
                    delete_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name in {
                    "remove", "unlink", "rmdir", "removedirs"
                }:
                    delete_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name in {
                    "link", "symlink"
                }:
                    link_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name in {
                    "rename", "replace", "renames"
                }:
                    rename_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name == "open":
                    os_open_functions.add(alias.asname or alias.name)
                elif imported.module == "os" and alias.name == "truncate":
                    truncate_functions.add(alias.asname or alias.name)
    callable_groups = (
        open_aliases,
        copy_functions,
        move_functions,
        delete_functions,
        link_functions,
        rename_functions,
        os_open_functions,
        truncate_functions,
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

        if func_name in os_open_functions:
            destination_node = node.args[0] if node.args else None
            flag_node = node.args[1] if len(node.args) > 1 else next(
                (keyword.value for keyword in node.keywords if keyword.arg == "flags"),
                None,
            )
            flag_names = {
                dotted_expression_name(child).rsplit(".", 1)[-1]
                for child in ast.walk(flag_node)
            } if flag_node is not None else set()
            write_flag_names = {
                "O_WRONLY", "O_RDWR", "O_APPEND", "O_CREAT", "O_TRUNC",
            }
            numeric_write_mask = (
                os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
            )
            numeric_flags = (
                int(flag_node.value)
                if isinstance(flag_node, ast.Constant)
                and isinstance(flag_node.value, int)
                else 0
            )
            writes = bool(
                flag_names & write_flag_names
                or numeric_flags & numeric_write_mask
            )
            if writes:
                literal_paths = literal_path_values(destination_node, literal_names)
                sensitive = sorted(
                    {
                        term
                        for literal_path in literal_paths
                        for term in sensitive_terms
                        if term in literal_path.casefold()
                    }
                )
                if sensitive or not literal_paths:
                    findings.add(
                        f"line={getattr(node, 'lineno', 0)}:os.open:"
                        f"{','.join(sensitive) if sensitive else unresolved_destination(destination_node)}"
                    )
            continue
        if func_name in truncate_functions:
            destination_node = node.args[0] if node.args else next(
                (keyword.value for keyword in node.keywords if keyword.arg == "path"),
                None,
            )
            literal_paths = literal_path_values(destination_node, literal_names)
            sensitive = sorted(
                {
                    term
                    for literal_path in literal_paths
                    for term in sensitive_terms
                    if term in literal_path.casefold()
                }
            )
            if sensitive or not literal_paths:
                findings.add(
                    f"line={getattr(node, 'lineno', 0)}:os.truncate:"
                    f"{','.join(sensitive) if sensitive else unresolved_destination(destination_node)}"
                )
            continue
        path_method_open = (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and func_name not in open_aliases
            and func_name not in os_open_functions
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
            mode_node: ast.AST | None = None
            if len(node.args) > mode_position:
                mode_node = node.args[mode_position]
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode_node = keyword.value
            modes = literal_path_values(mode_node, literal_names) if mode_node else {mode}
            sensitive = sorted(
                {
                    term
                    for literal_path in literal_paths
                    for term in sensitive_terms
                    if term in literal_path.casefold()
                }
            )
            writes = any(
                marker in resolved_mode
                for resolved_mode in modes
                for marker in "wax+"
            )
            unresolved_mode = mode_node is not None and not modes
            if (writes or unresolved_mode) and (sensitive or not literal_paths):
                findings.add(
                    f"line={getattr(node, 'lineno', 0)}:open:"
                    f"{','.join(sensitive) if sensitive else unresolved_destination(destination_node)}"
                    f"{'::UNRESOLVED_MODE' if unresolved_mode else ''}"
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
        elif func_name in move_functions:
            source_node = node.args[0] if node.args else None
            destination_node = node.args[1] if len(node.args) > 1 else None
            destinations.update(literal_path_values(source_node, literal_names))
            destinations.update(literal_path_values(destination_node, literal_names))
            unresolved = not literal_path_values(source_node, literal_names) or not literal_path_values(
                destination_node, literal_names
            )
        elif func_name in delete_functions:
            destination_node = node.args[0] if node.args else None
            destinations.update(literal_path_values(destination_node, literal_names))
            unresolved = not destinations
        elif func_name in link_functions:
            destination_node = node.args[1] if len(node.args) > 1 else None
            destinations.update(literal_path_values(destination_node, literal_names))
            unresolved = not destinations
        elif func_name in rename_functions:
            source_node = node.args[0] if node.args else None
            destination_node = node.args[1] if len(node.args) > 1 else None
            source_paths = literal_path_values(source_node, literal_names)
            destination_paths = literal_path_values(destination_node, literal_names)
            destinations.update(source_paths)
            destinations.update(destination_paths)
            unresolved = not source_paths or not destination_paths
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
def authority_write_sinks(
    source: str, sensitive_terms: tuple[str, ...]
) -> tuple[str, ...]:
    """Find writes in source and transitive literal exec/eval payloads."""
    result = set(_authority_write_sinks_direct(source, sensitive_terms))
    for payload in transitive_literal_python_sources(source):
        result.update(
            f"dynamic-exec:{finding}"
            for finding in _authority_write_sinks_direct(payload, sensitive_terms)
        )
    return tuple(sorted(result))


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
            source_removing_rsync = executable == "rsync" and any(
                value == "--remove-source-files"
                or value.startswith("--remove-source-files=")
                for value in tokens[executable_index + 1:]
            )
            destinations = (
                operands
                if executable in {"tee", "touch", "truncate", "mv"}
                or source_removing_rsync
                else operands[-1:]
            )
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
    reachable_python_files: list[str] | None = None,
) -> str:
    payload = {
        "reachable_sensitive": sorted(reachable_sensitive),
        "python_write_sinks": sorted(python_write_sinks),
        "python_process_launches": sorted(python_process_launches),
        "shell_write_sinks": sorted(shell_write_sinks),
        "reachable_shell_scripts": sorted(reachable_shell_scripts or []),
        "reachable_python_files": sorted(reachable_python_files or []),
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
def statically_disabled_workflow_condition(value: Any) -> bool:
    normalized = re.sub(r"\s+", "", str(value or "")).casefold()
    if normalized in {"false", "0", "no", "off", "${{false}}"}:
        return True
    expression = normalized
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2]
    prior = None
    while expression != prior:
        prior = expression
        expression = re.sub(r"\((false|true)\)", r"\1", expression)
    return bool(
        re.match(r"^(?:false&&|!true(?:&&|\|\||$))", expression)
        or re.search(r"(?:^|&&)false(?:&&|$)", expression)
    )


def resolve_local_action_path_expressions(source: str, source_path: str) -> str:
    if Path(source_path).name not in {"action.yml", "action.yaml"}:
        return source
    action_dir = Path(source_path).parent.as_posix()
    return (
        source.replace("${{ github.action_path }}", action_dir)
        .replace("${{github.action_path}}", action_dir)
        .replace("${GITHUB_ACTION_PATH}", action_dir)
        .replace("$GITHUB_ACTION_PATH", action_dir)
    )


@lru_cache(maxsize=512)
def workflow_pythonpath_values(text: str) -> tuple[str, ...]:
    """Collect effective candidate PYTHONPATH values on active YAML paths."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return ()
    values: set[str] = set()

    def visit(container: Any, inherited: str = "") -> None:
        if not isinstance(container, dict) or statically_disabled_workflow_condition(
            container.get("if")
        ):
            return
        environment = container.get("env")
        current = inherited
        if isinstance(environment, dict) and "PYTHONPATH" in environment:
            current = str(environment["PYTHONPATH"])
        if current:
            values.add(current)
        steps = container.get("steps")
        if isinstance(steps, list):
            for step in steps:
                visit(step, current)

    if not isinstance(payload, dict):
        return ()
    root_env = payload.get("env")
    root_value = (
        str(root_env["PYTHONPATH"])
        if isinstance(root_env, dict) and "PYTHONPATH" in root_env
        else ""
    )
    if root_value:
        values.add(root_value)
    jobs = payload.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            visit(job, root_value)
    runs = payload.get("runs")
    if isinstance(runs, dict):
        visit(runs, root_value)
    return tuple(sorted(values))


@lru_cache(maxsize=512)
def workflow_bash_env_values(text: str) -> tuple[str, ...]:
    """Collect effective candidate BASH_ENV values on active YAML paths."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return ()
    values: set[str] = set()

    def visit(container: Any, inherited: str = "") -> None:
        if not isinstance(container, dict) or statically_disabled_workflow_condition(
            container.get("if")
        ):
            return
        environment = container.get("env")
        current = inherited
        if isinstance(environment, dict) and "BASH_ENV" in environment:
            current = str(environment["BASH_ENV"])
        if current:
            values.add(current)
        steps = container.get("steps")
        if isinstance(steps, list):
            for step in steps:
                visit(step, current)

    if not isinstance(payload, dict):
        return ()
    root_env = payload.get("env")
    root_value = (
        str(root_env["BASH_ENV"])
        if isinstance(root_env, dict) and "BASH_ENV" in root_env
        else ""
    )
    if root_value:
        values.add(root_value)
    jobs = payload.get("jobs")
    if isinstance(jobs, dict):
        for job in jobs.values():
            visit(job, root_value)
    runs = payload.get("runs")
    if isinstance(runs, dict):
        visit(runs, root_value)
    return tuple(sorted(values))


@lru_cache(maxsize=1024)
def workflow_run_records(
    text: str,
    source_path: str = "",
    inherited_pythonpaths: tuple[str, ...] = (),
    inherited_bash_envs: tuple[str, ...] = (),
) -> tuple[tuple[str, str, str], ...]:
    """Return effective ``(shell, source, working_directory)`` run records."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
        if not isinstance(payload, dict):
            return (("", text, ""),)
        jobs = payload.get("jobs")
        blocks: list[tuple[str, str]] = []
        workflow_env = (
            {str(key): str(value) for key, value in payload.get("env", {}).items()}
            if isinstance(payload.get("env"), dict)
            else {}
        )

        def with_effective_environment(
            source: str, *environments: Mapping[str, str]
        ) -> str:
            effective = dict(workflow_env)
            for environment in environments:
                effective.update(environment)
            prefixes: list[str] = []
            if "PYTHONPATH" in effective:
                prefixes.append(f"PYTHONPATH={shlex.quote(effective['PYTHONPATH'])}")
            if "BASH_ENV" in effective:
                bash_env = str(effective["BASH_ENV"])
                if re.search(r"[$`]", bash_env):
                    prefixes.append(SHELL_UNRESOLVED_CONTROL_SENTINEL)
                else:
                    prefixes.append(f"source {shlex.quote(bash_env)}")
            return "\n".join([*prefixes, source])
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
                if statically_disabled_workflow_condition(job.get("if")):
                    continue
                if isinstance(job.get("strategy"), dict) and "matrix" in job["strategy"]:
                    blocks.append(("", SHELL_UNRESOLVED_CONTROL_SENTINEL, ""))
                job_default = workflow_default
                job_workdir = workflow_workdir
                job_env = (
                    {str(key): str(value) for key, value in job.get("env", {}).items()}
                    if isinstance(job.get("env"), dict)
                    else {}
                )
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
                    if (
                        isinstance(step, dict)
                        and isinstance(step.get("run"), str)
                        and not statically_disabled_workflow_condition(step.get("if"))
                    ):
                        step_env = (
                            {
                                str(key): str(value)
                                for key, value in step.get("env", {}).items()
                            }
                            if isinstance(step.get("env"), dict)
                            else {}
                        )
                        blocks.append(
                            (
                                str(step.get("shell") or job_default),
                                resolve_local_action_path_expressions(
                                    with_effective_environment(
                                        str(step["run"]), job_env, step_env
                                    ),
                                    source_path,
                                ),
                                str(step.get("working-directory") or job_workdir),
                            )
                        )
        else:
            runs = payload.get("runs")
            steps = runs.get("steps") if isinstance(runs, dict) else None
            if isinstance(steps, list):
                for step in steps:
                    if (
                        isinstance(step, dict)
                        and isinstance(step.get("run"), str)
                        and not statically_disabled_workflow_condition(step.get("if"))
                    ):
                        step_env = (
                            {
                                str(key): str(value)
                                for key, value in step.get("env", {}).items()
                            }
                            if isinstance(step.get("env"), dict)
                            else {}
                        )
                        blocks.append(
                            (
                                str(step.get("shell") or ""),
                                resolve_local_action_path_expressions(
                                    with_effective_environment(
                                        str(step["run"]), step_env
                                    ),
                                    source_path,
                                ),
                                str(step.get("working-directory") or ""),
                            )
                        )
        if not blocks and not isinstance(jobs, dict) and not isinstance(payload.get("runs"), dict):
            return (("", text, ""),)
        if inherited_pythonpaths:
            expanded: list[tuple[str, str, str]] = []
            for shell, source, workdir in blocks:
                if re.search(r"(?m)^PYTHONPATH=", source):
                    expanded.append((shell, source, workdir))
                    continue
                expanded.extend(
                    (
                        shell,
                        f"PYTHONPATH={shlex.quote(value)}\n{source}",
                        workdir,
                    )
                    for value in inherited_pythonpaths
                )
            blocks = expanded
        if inherited_bash_envs:
            expanded = []
            for shell, source, workdir in blocks:
                if re.search(r"(?m)^source\s+", source):
                    expanded.append((shell, source, workdir))
                    continue
                expanded.extend(
                    (
                        shell,
                        f"source {shlex.quote(value)}\n{source}"
                        if not re.search(r"[$`]", value)
                        else f"{SHELL_UNRESOLVED_CONTROL_SENTINEL}\n{source}",
                        workdir,
                    )
                    for value in inherited_bash_envs
                )
            blocks = expanded
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


def supported_posix_declared_shell(value: str) -> bool:
    shell = str(value or "").strip().replace("\\", "/").casefold()
    if not shell:
        return True
    executable = shell.split()[0].rsplit("/", 1)[-1]
    return executable in {"bash", "sh", "dash", "zsh", "ksh"}


def supported_declared_shell(value: str) -> bool:
    return python_declared_shell(value) or supported_posix_declared_shell(value)


@lru_cache(maxsize=512)
def workflow_run_text(text: str) -> str:
    """Return non-Python run blocks for shell parsing and flag validation."""
    return "\n".join(
        source
        for shell, source in workflow_run_blocks(text)
        if not python_declared_shell(shell) and supported_posix_declared_shell(shell)
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
        if python_declared_shell(shell) or not supported_posix_declared_shell(shell):
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
            def replace(match: re.Match[str]) -> str:
                name = match.group(1) or match.group(2)
                return literal_names.get(name, match.group(0))

            return re.sub(
                r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))",
                replace,
                value,
            )

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


def local_uses_path_occurrences(text: str, known_paths: set[str]) -> list[str]:
    """Resolve repository-local composite actions and reusable workflows."""
    try:
        payload = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return set()
    values: list[str] = []

    def active_uses(container: Any) -> None:
        if not isinstance(container, dict):
            return
        if statically_disabled_workflow_condition(container.get("if")):
            return
        if isinstance(container.get("uses"), str):
            values.append(str(container["uses"]))
        steps = container.get("steps")
        if isinstance(steps, list):
            for step in steps:
                active_uses(step)

    if isinstance(payload, dict) and isinstance(payload.get("jobs"), dict):
        for job in payload["jobs"].values():
            active_uses(job)
    elif isinstance(payload, dict) and isinstance(payload.get("runs"), dict):
        active_uses(payload["runs"])
    else:
        active_uses(payload)
    result: list[str] = []
    for value in values:
        if not value.startswith("./"):
            continue
        candidate = normalize_script_entrypoint(value)
        candidates = [candidate]
        if not Path(candidate).suffix:
            candidates.extend(
                [f"{candidate.rstrip('/')}/action.yml", f"{candidate.rstrip('/')}/action.yaml"]
            )
        result.extend(path for path in candidates if path in known_paths)
    return result


def local_uses_paths(text: str, known_paths: set[str]) -> set[str]:
    return set(local_uses_path_occurrences(text, known_paths))


def reachable_local_yaml_execution_counts(
    root_path: str, root_text: str, sources: Mapping[str, str]
) -> tuple[dict[str, int], bool]:
    """Return local uses execution multiplicity and whether a cycle exists."""
    known = set(sources)
    counts: dict[str, int] = {}
    cycle = False

    def visit(text: str, multiplier: int, stack: tuple[str, ...]) -> None:
        nonlocal cycle
        for child in local_uses_path_occurrences(text, known):
            if child in stack:
                cycle = True
                continue
            counts[child] = counts.get(child, 0) + multiplier
            if counts[child] > 10000:
                cycle = True
                continue
            visit(sources[child], multiplier, (*stack, child))

    visit(root_text, 1, (root_path,))
    counts.pop(root_path, None)
    return counts, cycle


def reachable_local_yaml_paths(
    root_path: str, root_text: str, sources: Mapping[str, str]
) -> set[str]:
    counts, _cycle = reachable_local_yaml_execution_counts(
        root_path, root_text, sources
    )
    return set(counts)


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
    unsupported_declared_shells: list[tuple[str, str, str]] = []
    for path, text in sorted(workflows.items()):
        yaml_execution_counts, yaml_cycle = reachable_local_yaml_execution_counts(
            path, text, yaml_sources
        )
        yaml_reachable = set(yaml_execution_counts)
        workflow_yaml_reachable[path] = sorted(yaml_reachable)
        action_implementations = {
            implementation
            for yaml_path in yaml_reachable
            for implementation in local_action_implementation_paths(
                yaml_path, yaml_sources[yaml_path], tracked_paths, accepted_files
            )
        }
        workflow_action_implementations[path] = sorted(action_implementations)
        sources = [(path, text)] + [
            (yaml_path, yaml_sources[yaml_path])
            for yaml_path in sorted(yaml_reachable)
            for _occurrence in range(yaml_execution_counts[yaml_path])
        ]
        caller_pythonpaths = workflow_pythonpath_values(text)
        caller_bash_envs = workflow_bash_env_values(text)
        workflow_yaml_texts[path] = sources
        run_records = [
            (yaml_path, shell, source, workdir)
            for yaml_path, yaml_text in sources
            for shell, source, workdir in workflow_run_records(
                yaml_text,
                yaml_path,
                caller_pythonpaths if yaml_path != path else (),
                caller_bash_envs if yaml_path != path else (),
            )
        ]
        if yaml_cycle:
            run_records.append((path, "", SHELL_UNRESOLVED_CONTROL_SENTINEL, ""))
        workflow_run_record_map[path] = run_records
        unsupported_declared_shells.extend(
            (path, yaml_path, shell)
            for yaml_path, shell, _source, _workdir in run_records
            if not supported_declared_shell(shell)
        )
        executable_workflows[path] = "\n".join(
            source
            for _yaml_path, shell, source, _workdir in run_records
            if not python_declared_shell(shell)
            and supported_posix_declared_shell(shell)
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
            if not supported_posix_declared_shell(shell):
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
    failures.extend(
        f"unsupported_declared_shell:{path}:{yaml_path}:{shell}"
        for path, yaml_path, shell in unsupported_declared_shells
    )
    failures.extend(
        f"unresolved_python_entrypoint:{path}:{row.get('yaml_path', path)}:"
        f"line={row.get('line', 0)}"
        for path, rows in workflow_direct_invocations.items()
        for row in rows
        if bool(row.get("unresolved_entrypoint"))
    )
    failures.extend(
        f"unresolved_pythonpath_startup_hook:{path}:{row.get('yaml_path', path)}:"
        f"line={row.get('line', 0)}"
        for path, rows in workflow_direct_invocations.items()
        for row in rows
        if bool(row.get("unresolved_pythonpath"))
    )
    failures.extend(
        f"unresolved_python_stdin_pipeline:{path}:{row.get('yaml_path', path)}:"
        f"line={row.get('line', 0)}"
        for path, rows in workflow_direct_invocations.items()
        for row in rows
        if bool(row.get("unresolved_stdin_pipeline"))
    )
    failures.extend(
        f"unverified_direct_python_executable:{path}:{row.get('yaml_path', path)}:"
        f"line={row.get('line', 0)}:{row.get('entrypoint', '')}"
        for path, rows in workflow_direct_invocations.items()
        for row in rows
        if bool(row.get("direct_executable"))
    )
    failures.extend(
        f"shell_expansion_budget_exceeded:{path}:{yaml_path}"
        for path, records_for_workflow in workflow_run_record_map.items()
        for yaml_path, _shell, source, _workdir in records_for_workflow
        if any(
            command == SHELL_EXPANSION_BUDGET_SENTINEL
            for _line, command in shell_logical_commands(
                executable_shell_text(source)
            )
        )
    )
    failures.extend(
        f"shell_expansion_budget_exceeded:{path}:{shell_path}"
        for path, reachable_shells in workflow_shell_reachable.items()
        for shell_path in reachable_shells
        if any(
            command == SHELL_EXPANSION_BUDGET_SENTINEL
            for _line, command in shell_logical_commands(
                executable_shell_text(shell_sources[shell_path])
            )
        )
    )
    failures.extend(
        f"unresolved_shell_control:{path}:{yaml_path}"
        for path, records_for_workflow in workflow_run_record_map.items()
        for yaml_path, _shell, source, _workdir in records_for_workflow
        if any(
            command == SHELL_UNRESOLVED_CONTROL_SENTINEL
            for _line, command in shell_logical_commands(
                executable_shell_text(source)
            )
        )
    )
    failures.extend(
        f"unresolved_shell_control:{path}:{shell_path}"
        for path, reachable_shells in workflow_shell_reachable.items()
        for shell_path in reachable_shells
        if any(
            command == SHELL_UNRESOLVED_CONTROL_SENTINEL
            for _line, command in shell_logical_commands(
                executable_shell_text(shell_sources[shell_path])
            )
        )
    )
    for path, reachable_sources in workflow_reachable_python.items():
        for source_path in sorted(reachable_sources):
            if source_path not in accepted_files:
                continue
            source = accepted_files[source_path]
            if PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL in local_import_candidates(
                source, source_path
            ):
                failures.append(
                    f"unresolved_dynamic_import:{path}:{source_path}"
                )
            if PYTHON_DYNAMIC_EXEC_BUDGET_SENTINEL in (
                transitive_literal_python_sources(source)
            ):
                failures.append(
                    f"dynamic_exec_budget_exceeded:{path}:{source_path}"
                )
        for embedded in workflow_embedded.get(path, []):
            source = str(embedded["source"])
            label = f"{path}::embedded:{embedded['kind']}:{embedded['line']}"
            if PYTHON_UNRESOLVED_DYNAMIC_IMPORT_SENTINEL in local_import_candidates(
                source, label
            ):
                failures.append(f"unresolved_dynamic_import:{label}")
            if PYTHON_DYNAMIC_EXEC_BUDGET_SENTINEL in (
                transitive_literal_python_sources(source)
            ):
                failures.append(f"dynamic_exec_budget_exceeded:{label}")
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
            reachable_python_files=[
                f"{source_path}:{text_sha256(accepted_files[source_path])}"
                for source_path in workflow_reachable
                if source_path in accepted_files
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
    raw_worktree_blob_ids: dict[str, str] = {}
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
                raw_worktree_blob_id = subprocess.check_output(
                    ["git", "hash-object", "--no-filters", "--", path],
                    cwd=root,
                    timeout=30,
                    stderr=subprocess.DEVNULL,
                ).decode("ascii").strip()
            except (OSError, subprocess.SubprocessError):
                head_hash = "MISSING_AT_HEAD"
                head_blob_id = "MISSING_AT_HEAD"
                worktree_blob_id = "MISSING_IN_WORKTREE"
                raw_worktree_blob_id = "MISSING_IN_WORKTREE"
            head_input_hashes[path] = head_hash
            canonical_head_blob_ids[path] = head_blob_id
            canonical_worktree_blob_ids[path] = worktree_blob_id
            raw_worktree_blob_ids[path] = raw_worktree_blob_id
            # Compare Git's canonical worktree bytes to the exact HEAD blob.
            # This catches assume-unchanged/skip-worktree bypasses while still
            # respecting declared checkout filters such as CRLF normalization.
            # An exact raw-byte match is also authoritative: repositories can
            # contain historical CRLF blobs while the current global clean
            # filter would normalize a newly added copy differently.
            if (
                worktree_blob_id != head_blob_id
                and raw_worktree_blob_id != head_blob_id
            ):
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
        "raw_worktree_blob_ids": raw_worktree_blob_ids,
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
    tracked_node_sources: dict[str, str] = {}
    for path in sorted(
        candidate
        for candidate in all_tracked_paths
        if candidate.endswith((".js", ".cjs", ".mjs", ".json"))
    ):
        try:
            tracked_node_sources[path] = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    action_resolution_sources = {
        **local_action_sources,
        **tracked_node_sources,
    }
    implementation_paths = {
        implementation
        for action_path, action_text in local_action_sources.items()
        for implementation in local_action_implementation_paths(
            action_path,
            action_text,
            all_tracked_paths,
            action_resolution_sources,
        )
    }
    implementation_sources: dict[str, str] = {
        path: tracked_node_sources[path]
        for path in implementation_paths
        if path in tracked_node_sources
    }
    for path in sorted(implementation_paths):
        if path in implementation_sources:
            continue
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
