#!/usr/bin/env python3
"""Inventory local W4 external feeds without importing them into policy.

This is a read-only readiness check. It records whether PIT SEC Form4 and 13F
artifacts exist locally with `available_from` timestamps, and keeps them
separate from true earnings/guidance feeds. It does not build signals, add
hooks, dispatch fullruns, or mutate production state.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_VERSION = "run287-w4-external-feed-inventory-v1"
DEFAULT_OUTPUT_DIR = "outputs/run287_w4_external_feed_inventory"
DEFAULT_FORM4_PATH = (
    "H:/codex/alphaops_deep_research_context/artifacts/form4_26425151497/"
    "sec-form4-daily-26425151497/data_pit/sec/form4_transactions.parquet"
)
DEFAULT_13F_PATH = (
    "H:/codex/alphaops_deep_research_context/artifacts/sec_13f_26387370997/"
    "sec-13f-quarterly-26387370997/data_pit/sec/institutional_13f_holdings.parquet"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_parquet_inventory(path: Path, *, ticker_column: str, required_columns: list[str]) -> dict[str, Any]:
    exists = path.exists()
    payload: dict[str, Any] = {
        "path": str(path),
        "exists": bool(exists),
        "status": "missing",
        "row_count": 0,
        "ticker_count": 0,
        "has_available_from": False,
        "available_from_min": None,
        "available_from_max": None,
        "required_columns_present": [],
        "required_columns_missing": list(required_columns),
        "decision_time_usable": False,
    }
    if not exists:
        return payload
    frame = pd.read_parquet(path)
    payload["status"] = "available"
    payload["row_count"] = int(len(frame))
    payload["columns"] = list(frame.columns)
    present = [col for col in required_columns if col in frame.columns]
    payload["required_columns_present"] = present
    payload["required_columns_missing"] = [col for col in required_columns if col not in frame.columns]
    if ticker_column in frame.columns:
        payload["ticker_count"] = int(frame[ticker_column].dropna().astype(str).str.upper().str.strip().nunique())
    if "available_from" in frame.columns:
        available = pd.to_datetime(frame["available_from"], errors="coerce", utc=True).dropna()
        payload["has_available_from"] = bool(not available.empty)
        if not available.empty:
            payload["available_from_min"] = available.min().isoformat()
            payload["available_from_max"] = available.max().isoformat()
            payload["future_available_from_rows"] = int((available > pd.Timestamp.utcnow()).sum())
    payload["decision_time_usable"] = bool(
        payload["row_count"] > 0
        and payload["has_available_from"]
        and not payload["required_columns_missing"]
        and safe_float(payload.get("future_available_from_rows")) == 0.0
    )
    return payload


def render_report(payload: dict[str, Any]) -> str:
    rows = payload["feeds"]
    lines = [
        "# Run287 W4 External Feed Inventory",
        "",
        f"- Status: `{payload['status']}`",
        f"- Decision label: `{payload['decision_label']}`",
        "- This is read-only inventory. No signal, hook, fullrun, production promotion, or live trading path is enabled.",
        "",
        "| Feed | Status | Rows | Tickers | Available From Max | Decision-time usable |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for name, feed in rows.items():
        lines.append(
            "| {name} | `{status}` | {rows} | {tickers} | {max_date} | {usable} |".format(
                name=name,
                status=feed.get("status"),
                rows=int(safe_float(feed.get("row_count"))),
                tickers=int(safe_float(feed.get("ticker_count"))),
                max_date=feed.get("available_from_max") or "",
                usable=feed.get("decision_time_usable"),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- SEC Form4 and 13F feeds can be local W4 evidence sources when present with PIT `available_from` timestamps.",
            "- They are not true earnings/guidance feeds and do not unblock earnings revision/guidance confirmation.",
            "- A usable inventory only permits source-screen work. It does not permit policy hooks or fullruns.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    feeds = {
        "sec_form4_transactions": read_parquet_inventory(
            repo_path(args.form4_path),
            ticker_column="issuer_ticker",
            required_columns=["issuer_ticker", "transaction_date", "filing_date", "available_from", "transaction_code"],
        ),
        "sec_13f_holdings": read_parquet_inventory(
            repo_path(args.sec13f_path),
            ticker_column="ticker_mapped",
            required_columns=["manager_cik", "report_period", "filing_date", "available_from", "ticker_mapped", "market_value_usd"],
        ),
        "repo_earnings_revision_signals": {
            "path": str(repo_path(args.earnings_revision_signals)),
            "exists": repo_path(args.earnings_revision_signals).exists(),
            "status": "available" if repo_path(args.earnings_revision_signals).exists() else "missing",
            "decision_time_usable": False,
            "interpretation": "true earnings/guidance feed remains required for revision/guidance confirmation",
        },
    }
    usable_external = [name for name, feed in feeds.items() if feed.get("decision_time_usable") and name.startswith("sec_")]
    true_guidance_ready = bool(feeds["repo_earnings_revision_signals"].get("decision_time_usable"))
    decision_label = (
        "sec_w4_sources_available_but_guidance_feed_missing"
        if usable_external and not true_guidance_ready
        else "blocked_missing_w4_external_sources"
        if not usable_external
        else "w4_external_sources_ready_for_source_screen"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "completed",
        "decision_label": decision_label,
        "feeds": feeds,
        "usable_external_source_count": int(len(usable_external)),
        "usable_external_sources": usable_external,
        "true_revision_guidance_ready": true_guidance_ready,
        "source_screen_allowed": bool(usable_external),
        "candidate_allowed": False,
        "hook_allowed": False,
        "research_only": True,
        "fullrun_dispatched": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "production_promotion_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--form4-path", default=DEFAULT_FORM4_PATH)
    parser.add_argument("--sec13f-path", default=DEFAULT_13F_PATH)
    parser.add_argument("--earnings-revision-signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
