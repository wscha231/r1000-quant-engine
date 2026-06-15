#!/usr/bin/env python3
"""Apply a reviewed ADR universe update manifest with explicit approval.

The candidate scanner intentionally emits placeholders. This tool refuses those
placeholders and only appends fully reviewed entries to adr_universe.yaml when
the operator supplies an approval token. Default mode is dry-run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
APPROVAL_TOKEN = "APPROVE_ADR_UNIVERSE_UPDATE"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
LISTED_SINCE_RE = re.compile(r"^\d{4}-\d{2}$")
ALLOWED_EXCHANGES = {"", "NYSE", "NASDAQ", "NYSEARCA", "NYSEMKT"}
REQUIRED_TEXT_FIELDS = ("ticker", "name", "country", "sector", "sub_sector", "listed_since")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read manifest JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return payload


def read_existing_symbols(path: Path) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r"(?:ticker|symbol)\s*:\s*['\"]?([A-Z][A-Z0-9.\-]+)", text))


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def yaml_list(values: Any) -> str:
    if not isinstance(values, list):
        return "[]"
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    if not cleaned:
        return "[]"
    return "[" + ", ".join(cleaned) + "]"


def normalize_entry(record: dict[str, Any]) -> dict[str, Any]:
    entry = record.get("proposed_entry") if isinstance(record.get("proposed_entry"), dict) else {}
    out = dict(entry)
    if not out.get("ticker") and record.get("ticker"):
        out["ticker"] = str(record.get("ticker")).upper()
    out["ticker"] = str(out.get("ticker") or "").strip().upper()
    if "themes" not in out or out.get("themes") is None:
        out["themes"] = []
    return out


def validate_entry(record: dict[str, Any], existing: set[str]) -> tuple[dict[str, Any], list[str]]:
    entry = normalize_entry(record)
    errors: list[str] = []
    ticker = str(entry.get("ticker") or "").upper()
    if not TICKER_RE.fullmatch(ticker):
        errors.append("invalid_ticker")
    if ticker in existing:
        errors.append("already_in_adr_universe")
    for field in REQUIRED_TEXT_FIELDS:
        value = str(entry.get(field) or "").strip()
        if not value:
            errors.append(f"missing_{field}")
    if str(entry.get("sector") or "").strip() == "ADR_REVIEW_REQUIRED":
        errors.append("placeholder_sector_not_reviewed")
    if str(entry.get("listed_since") or "") and not LISTED_SINCE_RE.fullmatch(str(entry.get("listed_since"))):
        errors.append("listed_since_must_be_yyyy_mm")
    themes = entry.get("themes")
    if not isinstance(themes, list) or not [item for item in themes if str(item).strip()]:
        errors.append("missing_themes")
    try:
        mcap = float(entry.get("mcap_usd_b"))
        if mcap <= 0:
            errors.append("mcap_usd_b_must_be_positive")
    except Exception:
        errors.append("mcap_usd_b_missing_or_invalid")
    exchange = str(record.get("exchange") or "").upper()
    if exchange not in ALLOWED_EXCHANGES:
        errors.append("exchange_not_allowed")
    if record.get("alpaca_tradable") is not True:
        errors.append("alpaca_tradable_not_true")
    if record.get("candidate_status") and record.get("candidate_status") != "review_add":
        errors.append("candidate_status_not_review_add")
    return entry, errors


def render_entry(entry: dict[str, Any]) -> str:
    lines = [
        f"  - ticker: {entry['ticker']}",
        f"    name: {yaml_scalar(entry.get('name'))}",
        f"    country: {yaml_scalar(entry.get('country'))}",
        f"    sector: {yaml_scalar(entry.get('sector'))}",
        f"    sub_sector: {yaml_scalar(entry.get('sub_sector'))}",
        f"    mcap_usd_b: {float(entry.get('mcap_usd_b')):g}",
        f"    listed_since: {yaml_scalar(entry.get('listed_since'))}",
        f"    themes: {yaml_list(entry.get('themes'))}",
        f"    notes: {yaml_scalar(entry.get('notes') or 'Reviewed ADR universe addition.')}",
    ]
    if entry.get("skip") is True:
        lines.append("    skip: true")
    return "\n".join(lines)


def render_patch(entries: list[dict[str, Any]], reviewed_by: str) -> str:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        "",
        f"  # ============== Reviewed ADR additions ({stamp}, {reviewed_by}) ==============",
    ]
    for entry in entries:
        lines.append(render_entry(entry))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# ADR Universe Update Apply Review",
        "",
        f"- status: `{summary.get('status')}`",
        f"- execute_requested: `{str(summary.get('execute_requested')).lower()}`",
        f"- target_file: `{summary.get('target_file')}`",
        f"- accepted_count: `{summary.get('accepted_count')}`",
        f"- blocked_count: `{summary.get('blocked_count')}`",
        "",
        "| Ticker | Status | Errors |",
        "| --- | --- | --- |",
    ]
    for row in summary.get("rows") or []:
        lines.append(f"| {row.get('ticker')} | {row.get('status')} | {', '.join(row.get('errors') or [])} |")
    lines.append("")
    return "\n".join(lines)


def build_summary(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = repo_path(args.manifest)
    target_file = repo_path(args.target_file)
    output_dir = repo_path(args.output_dir)
    manifest = read_json(manifest_path)
    existing = read_existing_symbols(target_file)
    proposed = manifest.get("proposed_additions") if isinstance(manifest.get("proposed_additions"), list) else []
    rows: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    manifest_errors: list[str] = []
    if manifest.get("production_mutation_allowed") is not False:
        manifest_errors.append("manifest_production_mutation_allowed_not_false")
    if manifest.get("manual_review_required") is not True:
        manifest_errors.append("manifest_manual_review_required_not_true")
    for record in proposed:
        if not isinstance(record, dict):
            continue
        entry, errors = validate_entry(record, existing)
        status = "accepted" if not errors else "blocked"
        rows.append({"ticker": entry.get("ticker"), "status": status, "errors": errors, "entry": entry})
        if not errors:
            accepted.append(entry)
    blocked = [row for row in rows if row["status"] != "accepted"]
    status = "dry_run_ready" if accepted and not blocked and not manifest_errors else "dry_run_blocked"
    execute = bool(getattr(args, "execute", False))
    refusal_reason = ""
    if execute:
        if str(getattr(args, "approval_token", "") or "") != APPROVAL_TOKEN:
            status = "refused"
            refusal_reason = "approval_token_mismatch"
        elif not bool(getattr(args, "review_complete", False)):
            status = "refused"
            refusal_reason = "review_complete_flag_missing"
        elif not str(getattr(args, "reviewed_by", "") or "").strip():
            status = "refused"
            refusal_reason = "reviewed_by_missing"
        elif blocked or manifest_errors or not accepted:
            status = "refused"
            refusal_reason = "manifest_not_ready"
        else:
            status = "applied"
    patch_text = render_patch(accepted, str(getattr(args, "reviewed_by", "") or "dry-run-reviewer")) if accepted else ""
    return {
        "schema_version": "adr-universe-apply-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "manifest_path": str(manifest_path),
        "target_file": str(target_file),
        "output_dir": str(output_dir),
        "status": status,
        "refusal_reason": refusal_reason,
        "execute_requested": execute,
        "approval_token_required": APPROVAL_TOKEN,
        "manifest_errors": manifest_errors,
        "accepted_count": len(accepted),
        "blocked_count": len(blocked) + len(manifest_errors),
        "rows": rows,
        "patch_text": patch_text,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    summary = build_summary(args)
    output_dir = Path(summary["output_dir"])
    target_file = Path(summary["target_file"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (output_dir / "adr_universe_patch_preview.yaml").write_text(summary["patch_text"], encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    if summary["status"] == "applied":
        current = target_file.read_text(encoding="utf-8") if target_file.exists() else "adr_universe:\n"
        if not current.endswith("\n"):
            current += "\n"
        target_file.write_text(current + summary["patch_text"], encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("status", "accepted_count", "blocked_count", "refusal_reason")}, indent=2))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="outputs/adr_candidates/adr_universe_update_manifest.json")
    parser.add_argument("--target-file", default="adr_universe.yaml")
    parser.add_argument("--output-dir", default="outputs/adr_universe_apply")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-token", default="")
    parser.add_argument("--review-complete", action="store_true")
    parser.add_argument("--reviewed-by", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = run(parse_args(argv))
    if summary["status"] in {"refused"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
