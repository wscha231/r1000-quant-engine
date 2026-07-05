#!/usr/bin/env python3
"""Decide whether AlphaOps integration fullrun can be dispatched.

Read-only operations gate. It consumes the daily latest-price audit and emits a
machine-readable readiness packet plus the exact fullrun command to use when
freshness is clean. It never dispatches workflows and never mutates production.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.alphaops_governance import (
    FROZEN_POLICY_PAYLOAD,
    frozen_payload_binding_fields,
    research_production_gate_fields,
    xnys_trading_day_count_between,
)
from tools.alphaops_required_price_tickers import parse_env_payload, required_price_tickers_for_env


DEFAULT_REF = "codex/integration-fullrun-clean-20260630"
DEFAULT_REPO = "wscha231/r1000-quant-engine"
DEFAULT_ENV: dict[str, str] = FROZEN_POLICY_PAYLOAD.copy()
MAX_AUDIT_AGE_DAYS = 2


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_invalid_json": str(exc)}


def parse_date(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    out = pd.to_datetime(value, errors="coerce")
    if pd.isna(out):
        return None
    return pd.Timestamp(out).normalize()


def audit_age_days(audit: dict[str, Any], *, today: pd.Timestamp | None = None) -> int | None:
    audit_date = parse_date(audit.get("audit_date"))
    if audit_date is None:
        return None
    current = today.normalize() if today is not None else pd.Timestamp(datetime.now(timezone.utc).date())
    current = current.normalize()
    if audit_date >= current:
        return 0
    days, _source = xnys_trading_day_count_between(audit_date, current)
    return int(days)


def audit_age_calendar_source(audit: dict[str, Any], *, today: pd.Timestamp | None = None) -> str:
    audit_date = parse_date(audit.get("audit_date"))
    if audit_date is None:
        return "none"
    current = today.normalize() if today is not None else pd.Timestamp(datetime.now(timezone.utc).date())
    current = current.normalize()
    if audit_date >= current:
        return "none"
    _days, source = xnys_trading_day_count_between(audit_date, current)
    return source


def future_dated_prices(audit: dict[str, Any]) -> list[dict[str, str]]:
    audit_date = parse_date(audit.get("audit_date"))
    if audit_date is None:
        return []
    out: list[dict[str, str]] = []
    per_ticker = audit.get("per_ticker") or {}
    if not isinstance(per_ticker, dict):
        return out
    for ticker, raw_date in sorted(per_ticker.items()):
        bar_date = parse_date(raw_date)
        if bar_date is not None and bar_date > audit_date:
            out.append({"ticker": str(ticker), "bar_date": bar_date.date().isoformat()})
    return out


def missing_required_price_tickers(audit: dict[str, Any], required: list[str]) -> list[str]:
    per_ticker = audit.get("per_ticker") or {}
    if not isinstance(per_ticker, dict):
        return list(required)
    available = {str(t).upper() for t, raw_date in per_ticker.items() if parse_date(raw_date) is not None}
    return [ticker for ticker in required if ticker.upper() not in available]


def stale_required_price_tickers(audit: dict[str, Any], required: list[str]) -> list[dict[str, str]]:
    anchor = parse_date(audit.get("benchmark_anchor_date") or audit.get("latest_cached_bar_date") or audit.get("audit_date"))
    if anchor is None:
        return []
    per_ticker = audit.get("per_ticker") or {}
    if not isinstance(per_ticker, dict):
        return []
    out: list[dict[str, str]] = []
    per_upper = {str(k).upper(): v for k, v in per_ticker.items()}
    for ticker in required:
        bar_date = parse_date(per_upper.get(ticker.upper()))
        if bar_date is not None and bar_date < anchor:
            out.append({"ticker": ticker.upper(), "bar_date": bar_date.date().isoformat(), "anchor_date": anchor.date().isoformat()})
    return out


def build_fullrun_command(*, repo: str, ref: str, env_payload: dict[str, str], skip_collector: bool) -> str:
    env_json = json.dumps(env_payload, sort_keys=True, separators=(",", ":"))
    skip_text = "true" if skip_collector else "false"
    lines = [
        f"$envJson = '{env_json}'",
        "$envJsonForGh = $envJson -replace '\"','\\\"'",
        "",
        "gh workflow run full_rebuild_manual.yml `",
        f"  -R {repo} `",
        f"  --ref {ref} `",
        "  -f universe_mode=global_alpha_universe `",
        "  -f backtest_years=7 `",
        "  -f pit_universe_label_clean=false `",
        f"  -f skip_collector={skip_text} `",
        "  -f fast_mode=true `",
        "  -f leader_rescue_mode=latest_only `",
        "  -f sidecar_profile=official `",
        "  -f artifact_profile=official `",
        "  -f gdrive_sync_mode=official `",
        "  -f portfolio_policy=alphaops_vnext_production `",
        "  -f experiment_env_json=$envJsonForGh",
    ]
    return "\n".join(lines)


def evaluate(
    audit: dict[str, Any],
    *,
    repo: str = DEFAULT_REPO,
    ref: str = DEFAULT_REF,
    env_payload: dict[str, str] | None = None,
    today: pd.Timestamp | None = None,
    max_audit_age_days: int = MAX_AUDIT_AGE_DAYS,
) -> dict[str, Any]:
    blockers: list[str] = []
    resolved_env_payload = DEFAULT_ENV.copy()
    if env_payload:
        resolved_env_payload.update({str(k): str(v) for k, v in env_payload.items()})
    payload_binding = frozen_payload_binding_fields(resolved_env_payload)
    if not payload_binding["frozen_payload_match"]:
        blockers.append("frozen_policy_payload_mismatch")
    required_tickers = required_price_tickers_for_env(resolved_env_payload)
    status = str(audit.get("status") or "missing")
    if not audit:
        blockers.append("missing_latest_price_date_audit")
    if audit.get("_invalid_json"):
        blockers.append("invalid_latest_price_date_audit_json")
    if status != "ok":
        blockers.append(f"price_audit_status_{status}")
    if bool(audit.get("stale_price_review")):
        blockers.append("stale_price_review_true")
    age = audit_age_days(audit, today=today)
    if age is None:
        blockers.append("missing_or_invalid_audit_date")
    elif age > int(max_audit_age_days):
        blockers.append("audit_record_stale")
    stale_days = audit.get("stale_trading_days")
    try:
        stale_days_int = int(stale_days)
    except Exception:
        stale_days_int = None
    if stale_days_int is None:
        blockers.append("missing_stale_trading_days")
    elif stale_days_int > int(audit.get("stale_trading_days_threshold", 2)):
        blockers.append("stale_trading_days_above_threshold")
    future = future_dated_prices(audit)
    if future:
        blockers.append("future_dated_prices")
    if not audit.get("benchmark_anchor_date"):
        blockers.append("missing_benchmark_anchor_date")
    missing_required = missing_required_price_tickers(audit, required_tickers)
    if missing_required:
        blockers.append("missing_required_env_price_tickers")
    stale_required = stale_required_price_tickers(audit, required_tickers)
    if stale_required:
        blockers.append("stale_required_env_price_tickers")

    fullrun_ready = not blockers
    command = build_fullrun_command(repo=repo, ref=ref, env_payload=resolved_env_payload, skip_collector=True)
    governance = research_production_gate_fields(
        pit_universe_label_clean=False,
        research_evidence_valid=fullrun_ready,
        research_fullrun_preconditions_ready=fullrun_ready,
    )
    return {
        "schema_version": "alphaops-fullrun-readiness-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if fullrun_ready else "blocked",
        "fullrun_ready": fullrun_ready,
        "blockers": blockers,
        "price_audit": {
            "status": status,
            "audit_date": audit.get("audit_date"),
            "audit_record_age_days": age,
            "audit_record_age_calendar": "XNYS",
            "audit_record_age_calendar_source": audit_age_calendar_source(audit, today=today),
            "max_audit_age_days": int(max_audit_age_days),
            "latest_cached_bar_date": audit.get("latest_cached_bar_date"),
            "benchmark_anchor_date": audit.get("benchmark_anchor_date"),
            "stale_trading_days": audit.get("stale_trading_days"),
            "stale_trading_days_threshold": audit.get("stale_trading_days_threshold", 2),
            "stale_trading_days_calendar": audit.get("stale_trading_days_calendar") or audit.get("calendar") or "",
            "stale_trading_days_calendar_source": audit.get("stale_trading_days_calendar_source") or "",
            "future_dated_prices": future,
            "missing_tickers": audit.get("missing_tickers") or [],
        },
        "required_experiment_env": resolved_env_payload,
        "policy_payload_binding": payload_binding,
        "required_price_ticker_source": "experiment_env",
        "required_price_tickers": required_tickers,
        "missing_required_price_tickers": missing_required,
        "stale_required_price_tickers": stale_required,
        "next_action": "dispatch_full_rebuild_manual" if fullrun_ready else "rerun_free_data_daily_update_or_fix_freshness",
        "fullrun_command": command if fullrun_ready else "",
        "non_mutating": True,
        **governance,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = ["# AlphaOps Fullrun Readiness", ""]
    lines.append(f"- status: `{payload.get('status')}`")
    lines.append(f"- fullrun_ready: `{str(payload.get('fullrun_ready')).lower()}`")
    lines.append(f"- next_action: `{payload.get('next_action')}`")
    blockers = payload.get("blockers") or []
    lines.append(f"- blockers: `{', '.join(blockers) if blockers else 'none'}`")
    lines.append("")
    lines.append("## Price Audit")
    lines.append("")
    price = payload.get("price_audit") or {}
    for key in (
        "status",
        "audit_date",
        "audit_record_age_days",
        "audit_record_age_calendar",
        "max_audit_age_days",
        "benchmark_anchor_date",
        "latest_cached_bar_date",
        "stale_trading_days",
    ):
        lines.append(f"- {key}: `{price.get(key)}`")
    lines.append("")
    binding = payload.get("policy_payload_binding") or {}
    lines.append("## Frozen Payload")
    lines.append("")
    lines.append(f"- frozen_payload_match: `{str(binding.get('frozen_payload_match')).lower()}`")
    lines.append(f"- frozen_policy_payload_hash: `{binding.get('frozen_policy_payload_hash')}`")
    lines.append(f"- dispatch_payload_hash: `{binding.get('dispatch_payload_hash')}`")
    lines.append("")
    if payload.get("fullrun_command"):
        lines.append("## Fullrun Command")
        lines.append("")
        lines.append("```powershell")
        lines.append(str(payload["fullrun_command"]))
        lines.append("```")
        lines.append("")
    lines.append("Production remains blocked until PIT universe membership evidence is clean.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-audit", default="outputs/latest_price_date_audit.json")
    parser.add_argument("--output-dir", default="outputs/fullrun_readiness")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--experiment-env-json", default="")
    parser.add_argument("--today", default="")
    parser.add_argument("--max-audit-age-days", type=int, default=MAX_AUDIT_AGE_DAYS)
    args = parser.parse_args()

    today = parse_date(args.today) if args.today else None
    payload = evaluate(
        read_json(Path(args.price_audit)),
        repo=args.repo,
        ref=args.ref,
        env_payload=parse_env_payload(args.experiment_env_json),
        today=today,
        max_audit_age_days=args.max_audit_age_days,
    )
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_report(payload), encoding="utf-8")
    print(render_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
