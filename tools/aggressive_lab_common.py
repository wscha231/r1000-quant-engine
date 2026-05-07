#!/usr/bin/env python3
"""Shared helpers for AlphaOps aggressive lab tools.

The helpers are deliberately lightweight. They avoid importing the production
engine so lab setup, attribution, and gate checks cannot mutate portfolio
behavior or require heavy ML dependencies.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return ROOT / path


def read_json(path_like: str | Path, default: Any = None) -> Any:
    path = repo_path(path_like)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path_like: str | Path, payload: Any) -> Path:
    path = repo_path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def read_csv_rows(path_like: str | Path, limit: int | None = None) -> list[dict[str, str]]:
    path = repo_path(path_like)
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
            if limit is not None and len(rows) >= limit:
                break
    return rows


def write_csv_rows(path_like: str | Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> Path:
    path = repo_path(path_like)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def pct(value: Any) -> str:
    num = safe_float(value)
    if num is None:
        return "n/a"
    return f"{num * 100:.2f}%"


def metric_delta(left: Any, right: Any) -> dict[str, float | None]:
    l_val = safe_float(left)
    r_val = safe_float(right)
    if l_val is None or r_val is None:
        return {"left": l_val, "right": r_val, "delta": None, "delta_pp": None}
    return {
        "left": l_val,
        "right": r_val,
        "delta": r_val - l_val,
        "delta_pp": (r_val - l_val) * 100.0,
    }


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if text == "":
        return ""
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "None", "~"}:
        return None
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        if any(ch in text for ch in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _split_key_value(text: str) -> tuple[str, str]:
    key, _, value = text.partition(":")
    return key.strip(), value.strip()


def _parse_block_scalar(lines: list[str], index: int, indent: int) -> tuple[str, int]:
    parts: list[str] = []
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            parts.append("")
            index += 1
            continue
        if _line_indent(line) < indent:
            break
        parts.append(line[indent:].rstrip())
        index += 1
    return "\n".join(parts).strip(), index


def _parse_yaml_block(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    while index < len(lines) and (not lines[index].strip() or lines[index].lstrip().startswith("#")):
        index += 1
    if index >= len(lines):
        return {}, index

    first = lines[index]
    first_indent = _line_indent(first)
    if first_indent < indent:
        return {}, index
    is_list = first.lstrip().startswith("- ") and first_indent == indent

    if is_list:
        items: list[Any] = []
        while index < len(lines):
            line = lines[index]
            if not line.strip() or line.lstrip().startswith("#"):
                index += 1
                continue
            cur_indent = _line_indent(line)
            if cur_indent < indent or not line.lstrip().startswith("- "):
                break
            if cur_indent != indent:
                break
            item_text = line.lstrip()[2:].strip()
            index += 1
            if item_text == "":
                item, index = _parse_yaml_block(lines, index, indent + 2)
            elif ":" in item_text and not item_text.startswith(("'", '"')):
                key, value = _split_key_value(item_text)
                item = {}
                if value == "":
                    child, index = _parse_yaml_block(lines, index, indent + 2)
                    item[key] = child
                elif value == ">":
                    block, index = _parse_block_scalar(lines, index, indent + 2)
                    item[key] = block
                else:
                    item[key] = _parse_scalar(value)
                if index < len(lines):
                    child, new_index = _parse_yaml_block(lines, index, indent + 2)
                    if isinstance(child, dict) and new_index != index:
                        item.update(child)
                        index = new_index
            else:
                item = _parse_scalar(item_text)
            items.append(item)
        return items, index

    mapping: dict[str, Any] = {}
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        cur_indent = _line_indent(line)
        if cur_indent < indent:
            break
        if cur_indent > indent:
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            break
        key, value = _split_key_value(stripped)
        index += 1
        if value == "":
            child, index = _parse_yaml_block(lines, index, indent + 2)
            mapping[key] = child
        elif value == ">":
            block, index = _parse_block_scalar(lines, index, indent + 2)
            mapping[key] = block
        else:
            mapping[key] = _parse_scalar(value)
    return mapping, index


def load_yaml(path_like: str | Path) -> Any:
    path = repo_path(path_like)
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        lines = path.read_text(encoding="utf-8").splitlines()
        parsed, _ = _parse_yaml_block(lines, 0, 0)
        return parsed


def ensure_required_outputs(experiment_dir: Path, required_outputs: list[str]) -> dict[str, bool]:
    return {name: (experiment_dir / name).exists() for name in required_outputs}


def count_csv_rows(path_like: str | Path) -> int:
    rows = read_csv_rows(path_like)
    return len(rows)
