"""Policy schema helpers for the research-only AutoLearning Policy Engine.

This module deliberately avoids applying policies to production code. It only
builds, validates, and renders proposal artifacts that can later be used in a
champion/challenger workflow.
"""
from __future__ import annotations

import difflib
from datetime import datetime, timedelta, timezone
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
