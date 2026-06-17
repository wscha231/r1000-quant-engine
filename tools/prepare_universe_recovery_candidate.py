#!/usr/bin/env python3
"""Prepare a review-only universe recovery candidate from the selected fallback.

This tool does not mutate the production universe, target books, scores, or
broker replay inputs. It materializes the fallback source recommended by
``run_universe_health_audit.py`` into ``outputs/universe_recovery_candidate/``
so agents can inspect and explicitly approve a recovery path before any
expensive rebuild or operating selection uses it.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def clean_ticker(value: Any) -> str:
    text = "" if value is None else str(value).strip().upper()
    return "" if text in {"", "NAN", "NONE", "NULL"} else text.replace("-", ".")


def first_existing(paths: list[str | Path]) -> Path | None:
    for item in paths:
        if str(item or "").strip() == "":
            continue
        path = repo_path(item)
        if path.is_file():
            return path
    return None


def nested_path(payload: dict[str, Any], *keys: str) -> str:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    if isinstance(current, dict):
        return str(current.get("path") or "")
    return str(current or "")


def load_universe_health(latest_run: Path) -> dict[str, Any]:
    for path in (
        latest_run / "universe_health" / "universe_source_audit.json",
        latest_run / "universe_health" / "summary.json",
    ):
        payload = read_json(path)
        if payload:
            payload["_source_path"] = str(path)
            return payload
    return {}


def fallback_chain(payload: dict[str, Any]) -> dict[str, Any]:
    chain = payload.get("fallback_source_chain")
    return chain if isinstance(chain, dict) else {}


def candidate_paths_for_source(source: str, chain: dict[str, Any]) -> list[Path]:
    if source == "restored_Drive_or_cache_IWB_holdings":
        restored = chain.get("restored_drive_iwb") if isinstance(chain.get("restored_drive_iwb"), dict) else {}
        paths = restored.get("paths") if isinstance(restored.get("paths"), dict) else {}
        return [
            repo_path(nested_path(paths, "parquet")),
            repo_path(nested_path(paths, "csv")),
            REPO_ROOT / "aggressive" / "cache" / "universe" / "iwb_holdings.parquet",
            REPO_ROOT / "aggressive" / "cache" / "universe" / "iwb_holdings.csv",
        ]
    if source == "previous_healthy_current_constituents_proxy":
        checked = chain.get("all_checked_paths") if isinstance(chain.get("all_checked_paths"), dict) else {}
        return [
            repo_path(nested_path(checked, "previous_healthy_candidate_universe")),
            repo_path(nested_path(checked, "latest_run_candidate_universe")),
            REPO_ROOT / "feature_store" / "candidate_universe_latest.parquet",
        ]
    if source == "committed_static_IWB_seed":
        static = chain.get("static_iwb_seed") if isinstance(chain.get("static_iwb_seed"), dict) else {}
        paths = static.get("paths") if isinstance(static.get("paths"), dict) else {}
        return [
            repo_path(nested_path(paths, "data_static")),
            repo_path(nested_path(paths, "data_raw")),
            REPO_ROOT / "data_static" / "iwb_holdings_seed.csv",
            REPO_ROOT / "data_raw" / "iwb_holdings_seed.csv",
        ]
    return []


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return []
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return []
    return frame.to_dict("records")


def read_source_rows(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_csv_rows(path)
    if suffix == ".parquet":
        return read_parquet_rows(path)
    return []


def normalize_rows(rows: list[dict[str, Any]], *, recovery_source: str, source_path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        ticker = clean_ticker(row.get("ticker") or row.get("Ticker") or row.get("symbol") or row.get("Symbol"))
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append(
            {
                "ticker": ticker,
                "name": row.get("Name") or row.get("name") or row.get("company_name") or "",
                "sector": row.get("Sector") or row.get("sector") or "",
                "asset_class": row.get("Asset Class") or row.get("asset_class") or "",
                "universe_source": recovery_source,
                "recovery_source_path": str(source_path),
                "review_only": True,
                "canonical_production_sync": False,
                "production_mutation_allowed": False,
                "production_promotion_allowed": False,
                "live_trading_enabled": False,
                "human_approval_required": True,
            }
        )
    return sorted(out, key=lambda item: str(item["ticker"]))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "ticker",
        "name",
        "sector",
        "asset_class",
        "universe_source",
        "recovery_source_path",
        "review_only",
        "canonical_production_sync",
        "production_mutation_allowed",
        "production_promotion_allowed",
        "live_trading_enabled",
        "human_approval_required",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def classify_recovery_candidate(latest_run: str | Path, *, min_r1000_base: int = 400) -> dict[str, Any]:
    run_dir = repo_path(latest_run)
    universe = load_universe_health(run_dir)
    chain = fallback_chain(universe)
    recovery_source = str(universe.get("recommended_recovery_source") or "")
    recovery_action = str(universe.get("recovery_action") or "")
    source_path: Path | None = None
    rows: list[dict[str, Any]] = []

    if not universe:
        status = "not_ready"
        blockers = ["universe_health_missing"]
    elif recovery_action == "none_required" or recovery_source == "none_required":
        status = "none_required"
        blockers = []
    elif recovery_action != "repair_universe_from_fallback":
        status = "not_ready"
        blockers = [f"unsupported_recovery_action:{recovery_action or 'missing'}"]
    else:
        source_path = first_existing(candidate_paths_for_source(recovery_source, chain))
        if source_path is None:
            status = "not_ready"
            blockers = [f"recovery_source_file_missing:{recovery_source or 'missing'}"]
        else:
            rows = normalize_rows(read_source_rows(source_path), recovery_source=recovery_source, source_path=source_path)
            if len(rows) < min_r1000_base:
                status = "not_ready"
                blockers = [f"recovery_candidate_below_floor:{len(rows)}<{min_r1000_base}"]
            else:
                status = "candidate_ready"
                blockers = []

    return {
        "schema_version": "universe-recovery-candidate-v1",
        "generated_at_utc": now_utc(),
        "latest_run": str(run_dir),
        "status": status,
        "review_only": True,
        "canonical_production_sync": False,
        "production_mutation_allowed": False,
        "production_promotion_allowed": False,
        "promotion_allowed": False,
        "promotion_allowed_scope": "universe_recovery_candidate_review_only",
        "live_trading_enabled": False,
        "automatic_repair_allowed": False,
        "human_approval_required": True,
        "recovery_action": recovery_action,
        "recommended_recovery_source": recovery_source,
        "recommended_recovery_reason": universe.get("recommended_recovery_reason"),
        "source_path": str(source_path or ""),
        "candidate_row_count": len(rows),
        "min_r1000_base": int(min_r1000_base),
        "candidate_ready_for_review": status == "candidate_ready",
        "blockers": blockers,
        "outputs": {
            "candidate_csv": "outputs/universe_recovery_candidate/candidate_universe_recovery.csv",
            "summary": "outputs/universe_recovery_candidate/summary.json",
            "report": "outputs/universe_recovery_candidate/report.md",
        },
        "notes": [
            "This is a review-only recovery candidate.",
            "It does not update scored_latest, candidate_replay_book, target books, broker replay, or production universe files.",
            "It does not authorize production promotion, canonical production sync, workflow dispatch, or live trading.",
        ],
        "_rows": rows,
    }


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Universe Recovery Candidate",
        "",
        f"- status: `{payload.get('status')}`",
        f"- review_only: `{str(payload.get('review_only')).lower()}`",
        f"- canonical_production_sync: `{str(payload.get('canonical_production_sync')).lower()}`",
        f"- production_mutation_allowed: `{str(payload.get('production_mutation_allowed')).lower()}`",
        f"- production_promotion_allowed: `{str(payload.get('production_promotion_allowed')).lower()}`",
        f"- promotion_allowed_scope: `{payload.get('promotion_allowed_scope')}`",
        f"- automatic_repair_allowed: `{str(payload.get('automatic_repair_allowed')).lower()}`",
        f"- live_trading_enabled: `{str(payload.get('live_trading_enabled')).lower()}`",
        f"- human_approval_required: `{str(payload.get('human_approval_required')).lower()}`",
        f"- recommended_recovery_source: `{payload.get('recommended_recovery_source')}`",
        f"- recovery_action: `{payload.get('recovery_action')}`",
        f"- source_path: `{payload.get('source_path')}`",
        f"- candidate_row_count: `{payload.get('candidate_row_count')}`",
        f"- min_r1000_base: `{payload.get('min_r1000_base')}`",
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend(f"- `{item}`" for item in blockers) if blockers else lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This artifact is a review-only recovery candidate.",
            "- Human approval is required before any production universe or rebuild input uses it.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(payload: dict[str, Any], output_dir: str | Path) -> None:
    out = repo_path(output_dir)
    rows = payload.pop("_rows", [])
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "candidate_universe_recovery.csv", rows)
    write_json(out / "summary.json", payload)
    (out / "report.md").write_text(render_report(payload), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/universe_recovery_candidate")
    parser.add_argument("--min-r1000-base", type=int, default=400)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = classify_recovery_candidate(args.latest_run, min_r1000_base=args.min_r1000_base)
    write_outputs(payload, args.output_dir)
    print(json.dumps({k: v for k, v in payload.items() if k != "_rows"}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
