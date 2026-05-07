"""Policy schema helpers for the research-only AutoLearning Policy Engine.

This module deliberately avoids applying policies to production code. It only
builds, validates, and renders proposal artifacts that can later be used in a
champion/challenger workflow.
"""
from __future__ import annotations

import difflib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_POLICY_VERSION_PREFIX = "2026-05-alphaops"
DEFAULT_POLICY_MODE = "proposal_only"
DEFAULT_TTL_DAYS = 90

DEFAULT_GUARDRAILS = {
    "production_activation_allowed": False,
    "requires_human_approval": True,
    "requires_challenger_backtest": True,
    "max_sleeve_weight_delta": 0.10,
    "max_cash_floor_delta": 0.15,
    "max_target_n_delta": 5,
    "max_stop_delta": 0.03,
    "min_trade_count": 250,
    "ttl_days": DEFAULT_TTL_DAYS,
}


REQUIRED_TOP_LEVEL_KEYS = {
    "policy_version",
    "generated_at",
    "expires_at",
    "mode",
    "guardrails",
    "evidence_summary",
    "feature_gates",
    "sleeve_policy",
    "target_n",
    "orchestrator_policy",
    "entry_timing",
    "exit_rules",
    "cash_policy",
    "execution_policy",
    "promotion_gates",
    "proposals",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def policy_dates(generated_at: datetime | None = None, ttl_days: int = DEFAULT_TTL_DAYS) -> tuple[str, str]:
    generated = generated_at or utc_now()
    expires = generated + timedelta(days=int(ttl_days))
    return isoformat_z(generated), expires.strftime("%Y-%m-%d")


def make_policy_version(generated_at: datetime | None = None) -> str:
    generated = generated_at or utc_now()
    return f"{DEFAULT_POLICY_VERSION_PREFIX}-{generated.strftime('%Y%m%d')}-v1"


def empty_policy(evidence_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    generated_at, expires_at = policy_dates()
    return {
        "policy_version": make_policy_version(),
        "generated_at": generated_at,
        "expires_at": expires_at,
        "mode": DEFAULT_POLICY_MODE,
        "guardrails": dict(DEFAULT_GUARDRAILS),
        "evidence_summary": evidence_summary or {},
        "feature_gates": [],
        "sleeve_policy": {},
        "target_n": {},
        "orchestrator_policy": {},
        "entry_timing": {},
        "exit_rules": {},
        "cash_policy": {},
        "execution_policy": {},
        "promotion_gates": {},
        "proposals": [],
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


def _parse_yaml_block(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    while index < len(lines) and (not lines[index].strip() or lines[index].lstrip().startswith("#")):
        index += 1
    if index >= len(lines):
        return {}, index

    first = lines[index]
    first_indent = _line_indent(first)
    if first_indent < indent:
        return {}, index
    is_list = first.lstrip().startswith("-") and first_indent == indent

    if is_list:
        items: list[Any] = []
        while index < len(lines):
            line = lines[index]
            if not line.strip() or line.lstrip().startswith("#"):
                index += 1
                continue
            cur_indent = _line_indent(line)
            stripped = line.lstrip()
            if cur_indent < indent or not stripped.startswith("-"):
                break
            if cur_indent != indent:
                break
            item_text = stripped[1:].strip()
            index += 1
            if item_text == "":
                item, index = _parse_yaml_block(lines, index, indent + 2)
            elif ":" in item_text and not item_text.startswith(("'", '"')):
                key, value = _split_key_value(item_text)
                item = {}
                if value == "":
                    child, index = _parse_yaml_block(lines, index, indent + 2)
                    item[key] = child
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
        if stripped.startswith("-"):
            break
        key, value = _split_key_value(stripped)
        index += 1
        if value == "":
            child, index = _parse_yaml_block(lines, index, indent + 2)
            mapping[key] = child
        else:
            mapping[key] = _parse_scalar(value)
    return mapping, index


def load_policy(path_like: str | Path) -> dict[str, Any]:
    path = Path(path_like)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text)
    except ModuleNotFoundError:
        parsed, _ = _parse_yaml_block(text.splitlines(), 0, 0)
    if not isinstance(parsed, dict):
        return {}
    return parsed


def merge_candidate_policy(base_policy: dict[str, Any], candidate_policy: dict[str, Any]) -> dict[str, Any]:
    """Shallow-recursive merge for review tooling.

    This does not activate production behavior; callers use it to display what
    would change if a candidate became the active policy.
    """
    merged = dict(base_policy or {})
    for key, value in (candidate_policy or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_candidate_policy(merged[key], value)
        else:
            merged[key] = value
    return merged


def expire_old_policy(policy: dict[str, Any], today: datetime | None = None) -> dict[str, Any]:
    today_dt = today or utc_now()
    expires_at = str(policy.get("expires_at") or "")
    expired = False
    if expires_at:
        try:
            expired = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).date() < today_dt.date()
        except ValueError:
            expired = True
    out = dict(policy)
    out["expired"] = expired
    if expired:
        out["mode"] = "expired_proposal"
        out.setdefault("guardrails", {})["production_activation_allowed"] = False
    return out


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(policy))
    guardrails = dict(policy.get("guardrails") or {})
    mode = str(policy.get("mode") or "")
    issues: list[str] = []
    if missing:
        issues.append("missing_top_level_keys")
    if mode != DEFAULT_POLICY_MODE:
        issues.append("mode_must_be_proposal_only")
    if guardrails.get("production_activation_allowed") is not False:
        issues.append("production_activation_must_be_false")
    if guardrails.get("requires_human_approval") is not True:
        issues.append("human_approval_required")
    if guardrails.get("requires_challenger_backtest") is not True:
        issues.append("challenger_backtest_required")
    if not policy.get("expires_at"):
        issues.append("expires_at_required")
    return {
        "valid": not issues,
        "issues": issues,
        "missing": missing,
        "mode": mode,
        "production_activation_allowed": guardrails.get("production_activation_allowed"),
    }


def _quote_string(value: str) -> str:
    if value == "":
        return "''"
    safe = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{safe}"'


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return _quote_string(str(value))


def _render_yaml_node(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_render_yaml_node(child, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(child)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(prefix + "-")
                lines.extend(_render_yaml_node(item, indent + 2))
            elif isinstance(item, list):
                lines.append(prefix + "-")
                lines.extend(_render_yaml_node(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return lines
    return [prefix + _yaml_scalar(value)]


def render_policy_yaml(policy: dict[str, Any]) -> str:
    lines = [
        "# AUTO-GENERATED by tools/auto_policy_proposal.py.",
        "# Research-only candidate. Do not wire to production without",
        "# challenger backtest, promotion gate, and human approval.",
        "",
    ]
    lines.extend(_render_yaml_node(policy, 0))
    lines.append("")
    return "\n".join(lines)


def diff_text(old_text: str, new_text: str, old_label: str, new_label: str) -> str:
    diff = difflib.unified_diff(
        (old_text or "").splitlines(),
        (new_text or "").splitlines(),
        fromfile=old_label,
        tofile=new_label,
        lineterm="",
        n=3,
    )
    body = "\n".join(diff)
    return body if body else "(no changes)"
