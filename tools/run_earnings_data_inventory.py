#!/usr/bin/env python3
"""Inventory earnings data layers without promoting them into policy.

This separates three concepts that are easy to confuse:

1. SEC actuals / historical financial statements.
2. Candidate-book proxy scores derived from actuals or internal features.
3. True PIT estimate-revision / guidance feeds.

The output is a research-only status report. It does not build signals, select
stocks, dispatch workflows, or change production state.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.validate_earnings_revision_feed import validate_feed  # noqa: E402
from tools.check_earnings_guidance_coverage import coverage_summary_from_frame  # noqa: E402

SCHEMA_VERSION = "earnings-data-inventory-v1"
DEFAULT_OUTPUT_DIR = "outputs/earnings_data_inventory"

ACTUAL_FINANCIAL_COLUMNS = [
    "revenues_ttm",
    "gross_profit_ttm",
    "op_income_ttm",
    "net_income_ttm",
    "ocf_ttm",
    "capex_ttm",
    "sales_growth_yoy",
    "eps_growth_yoy",
    "op_income_growth_yoy",
    "revenue_growth_final",
]

PROXY_SCORE_COLUMNS = [
    "actual_results_score",
    "eps_revision_score",
    "revision_score",
    "eps_revision_proxy",
    "phase9_c3_eps_turn_positive",
    "ni_loss_narrowing_4q",
]

TRUE_REVISION_COLUMNS = [
    "eps_revision_4w",
    "eps_revision_13w",
    "eps_revision_26w",
    "revenue_revision_13w",
    "margin_revision_score",
    "positive_guidance_flag",
    "negative_guidance_flag",
    "guidance_vs_consensus_score",
]

SERVICE_LABELS = {
    "actuals_confirmed": {
        "display_label": "Reported actuals confirmed",
        "description": "Backward-looking SEC actuals. This does not imply analyst estimate revision.",
        "revision_confirmed": False,
        "guidance_confirmed": False,
    },
    "analyst_revision_confirmed": {
        "display_label": "PIT analyst estimate revision confirmed",
        "description": "Forward estimate revision from a dated, coverage-eligible source.",
        "revision_confirmed": True,
        "guidance_confirmed": False,
    },
    "company_guidance_confirmed": {
        "display_label": "Company guidance direction confirmed",
        "description": "Company guidance direction from a dated, coverage-eligible source.",
        "revision_confirmed": False,
        "guidance_confirmed": True,
    },
    "proxy_score_diagnostic_only": {
        "display_label": "Internal diagnostic proxy",
        "description": "Internal proxy score. Not a substitute for analyst revision or guidance.",
        "revision_confirmed": False,
        "guidance_confirmed": False,
    },
    "data_insufficient": {
        "display_label": "Insufficient PIT revision/guidance data",
        "description": "Do not use as earnings confirmation.",
        "revision_confirmed": False,
        "guidance_confirmed": False,
    },
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def count_nonzero(frame: pd.DataFrame, columns: list[str]) -> tuple[list[str], dict[str, int]]:
    present = [col for col in columns if col in frame.columns]
    counts: dict[str, int] = {}
    for col in present:
        values = pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
        counts[col] = int((values.abs() > 1e-12).sum())
    return present, counts


def summarize_sec_archive(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "layer": "sec_companyfacts_actuals",
            "status": "missing",
            "path": str(path),
            "description": "SEC companyfacts actual financial statements are unavailable.",
        }
    stat = path.stat()
    age_days = (datetime.now(timezone.utc).timestamp() - stat.st_mtime) / 86400.0
    return {
        "layer": "sec_companyfacts_actuals",
        "status": "available",
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "age_days": round(age_days, 3),
        "description": "Historical SEC actuals source; not analyst estimate revision or guidance.",
    }


def summarize_candidate_book(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "status": "missing"}
    try:
        frame = read_table(path)
    except Exception as exc:
        return {"path": str(path), "status": "read_failed", "error": str(exc)}
    tickers = (
        frame["ticker"].astype(str).str.upper().str.strip()
        if "ticker" in frame.columns
        else pd.Series([], dtype=str)
    )
    actual_cols, actual_nonzero = count_nonzero(frame, ACTUAL_FINANCIAL_COLUMNS)
    proxy_cols, proxy_nonzero = count_nonzero(frame, PROXY_SCORE_COLUMNS)
    return {
        "path": str(path),
        "status": "available",
        "row_count": int(len(frame)),
        "ticker_count": int(tickers[tickers.ne("")].nunique()) if not tickers.empty else 0,
        "actual_financial_columns_present": actual_cols,
        "actual_financial_nonzero_counts": actual_nonzero,
        "proxy_score_columns_present": proxy_cols,
        "proxy_score_nonzero_counts": proxy_nonzero,
        "contains_true_revision_guidance_feed": False,
        "interpretation": "candidate actual/proxy fields are diagnostic inputs, not vendor guidance history.",
    }


def summarize_raw_feed(path: Path, as_of: pd.Timestamp | None) -> dict[str, Any]:
    if not path.exists():
        return {
            "layer": "raw_true_revision_guidance_feed",
            "status": "missing",
            "path": str(path),
            "regime_nowcast_coverage_ready": False,
        }
    try:
        frame = pd.read_csv(path, low_memory=False)
    except Exception as exc:
        return {
            "layer": "raw_true_revision_guidance_feed",
            "status": "read_failed",
            "path": str(path),
            "error": str(exc),
            "regime_nowcast_coverage_ready": False,
        }
    payload = validate_feed(frame, as_of=as_of)
    payload.update({"layer": "raw_true_revision_guidance_feed", "path": str(path)})
    return payload


def summarize_pit_signals(path: Path, as_of: pd.Timestamp | None) -> dict[str, Any]:
    if not path.exists():
        return {
            "layer": "pit_true_revision_guidance_signals",
            "status": "missing",
            "path": str(path),
            "regime_nowcast_coverage_ready": False,
        }
    try:
        frame = read_table(path)
    except Exception as exc:
        return {
            "layer": "pit_true_revision_guidance_signals",
            "status": "read_failed",
            "path": str(path),
            "error": str(exc),
            "regime_nowcast_coverage_ready": False,
        }
    if "available_from" in frame.columns:
        available_from = pd.to_datetime(frame["available_from"], errors="coerce").dt.normalize()
        if as_of is not None:
            frame = frame[available_from <= as_of].copy()
            available_from = pd.to_datetime(frame["available_from"], errors="coerce").dt.normalize()
    else:
        available_from = pd.Series([], dtype="datetime64[ns]")
    tickers = frame["ticker"].astype(str).str.upper().str.strip() if "ticker" in frame.columns else pd.Series([], dtype=str)
    present, nonzero = count_nonzero(frame, TRUE_REVISION_COLUMNS)
    coverage_mask = pd.Series(False, index=frame.index)
    if "source_type_coverage_eligible" in frame.columns:
        coverage_mask = frame["source_type_coverage_eligible"].astype(str).str.lower().isin({"1", "true", "yes"})
    elif "source_type" in frame.columns:
        coverage_mask = frame["source_type"].astype(str).str.lower().str.strip().isin(
            {"historical_revision", "vendor_estimate_revision", "company_guidance", "manual_research_import"}
        )
    eligible = frame[coverage_mask].copy()
    eligible_revision_mask = pd.Series(False, index=eligible.index)
    for col in ["eps_revision_13w", "revenue_revision_13w", "margin_revision_score"]:
        if col in eligible.columns:
            eligible_revision_mask = eligible_revision_mask | (pd.to_numeric(eligible[col], errors="coerce").fillna(0.0).abs() > 1e-12)
    eligible_guidance_mask = pd.Series(False, index=eligible.index)
    for col in ["positive_guidance_flag", "negative_guidance_flag"]:
        if col in eligible.columns:
            eligible_guidance_mask = eligible_guidance_mask | (pd.to_numeric(eligible[col], errors="coerce").fillna(0.0) > 0.0)
    eligible_revision_tickers = int(eligible.loc[eligible_revision_mask, "ticker"].nunique()) if "ticker" in eligible.columns else 0
    eligible_guidance_tickers = int(eligible.loc[eligible_guidance_mask, "ticker"].nunique()) if "ticker" in eligible.columns else 0
    coverage = coverage_summary_from_frame(frame, as_of=as_of)
    return {
        "layer": "pit_true_revision_guidance_signals",
        "status": "available" if len(frame) else "empty",
        "path": str(path),
        "row_count": int(len(frame)),
        "ticker_count": int(tickers[tickers.ne("")].nunique()) if not tickers.empty else 0,
        "columns_present": present,
        "nonzero_counts": nonzero,
        "coverage_eligible_revision_ticker_count": eligible_revision_tickers,
        "coverage_eligible_guidance_ticker_count": eligible_guidance_tickers,
        "earnings_guidance_plumbing_ready": bool(coverage.get("plumbing_ready", False)),
        "earnings_guidance_research_ready": bool(coverage.get("research_ready", False)),
        "earnings_guidance_service_ready": bool(coverage.get("service_ready", False)),
        "earnings_guidance_policy_ready": bool(coverage.get("policy_ready", False)),
        "earnings_guidance_coverage_status": coverage.get("status", "DATA_INSUFFICIENT"),
        "min_available_from": available_from.min().date().isoformat() if len(available_from) and available_from.notna().any() else None,
        "max_available_from": available_from.max().date().isoformat() if len(available_from) and available_from.notna().any() else None,
        "regime_nowcast_coverage_ready": bool(coverage.get("research_ready", False)),
    }


def write_layers_csv(path: Path, summary: dict[str, Any]) -> None:
    rows = []
    for item in [summary["sec_companyfacts"], summary["raw_feed"], summary["pit_signals"]]:
        rows.append(
            {
                "layer": item.get("layer"),
                "status": item.get("status"),
                "path": item.get("path"),
                "row_count": item.get("row_count", ""),
                "ticker_count": item.get("ticker_count", ""),
                "regime_nowcast_coverage_ready": item.get("regime_nowcast_coverage_ready", ""),
                "description": item.get("description", item.get("reason", "")),
            }
        )
    for item in summary["candidate_books"]:
        rows.append(
            {
                "layer": "candidate_book_actuals_and_proxy_scores",
                "status": item.get("status"),
                "path": item.get("path"),
                "row_count": item.get("row_count", ""),
                "ticker_count": item.get("ticker_count", ""),
                "regime_nowcast_coverage_ready": False,
                "description": item.get("interpretation", ""),
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Earnings Data Inventory",
        "",
        "This is a research-only inventory. It separates SEC actuals, candidate proxy scores, and true PIT revision/guidance feeds.",
        "",
        f"- generated_at_utc: `{summary['generated_at_utc']}`",
        f"- true_revision_guidance_ready: `{str(summary['true_revision_guidance_ready']).lower()}`",
        f"- production_activation_allowed: `{str(summary['production_activation_allowed']).lower()}`",
        "",
        "## Layer Status",
        "",
        "| Layer | Status | Coverage Ready | Path |",
        "|---|---:|---:|---|",
    ]
    for item in [summary["sec_companyfacts"], summary["raw_feed"], summary["pit_signals"]]:
        lines.append(
            f"| {item.get('layer')} | {item.get('status')} | {item.get('regime_nowcast_coverage_ready', '')} | `{item.get('path')}` |"
        )
    for item in summary["candidate_books"]:
        lines.append(f"| candidate_book_actuals_and_proxy_scores | {item.get('status')} | False | `{item.get('path')}` |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- SEC companyfacts actuals can confirm historical fundamentals, but they are not analyst estimate revisions.",
            "- Candidate-book scores such as `actual_results_score` and `eps_revision_score` are internal/proxy fields unless a true feed is joined.",
            "- `sec_actual_snapshot` and `current_snapshot` source types are allowed for inventory, but they do not count toward R1 earnings/guidance coverage.",
            "- A true revision/guidance layer requires dated PIT rows with coverage-eligible source types and `available_from <= decision_date`.",
            "",
            "## Service Labels",
            "",
            "| Label | Meaning | Revision Confirmed | Guidance Confirmed |",
            "|---|---|---:|---:|",
        ]
    )
    for key, value in summary["service_label_contract"].items():
        lines.append(
            f"| `{key}` | {value['description']} | {value['revision_confirmed']} | {value['guidance_confirmed']} |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sec-companyfacts", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--earnings-feed", default="data_raw/events/earnings_revisions.csv")
    parser.add_argument("--pit-signals", default="data_pit/events/earnings_revision_signals.parquet")
    parser.add_argument("--candidate-book", action="append", default=[])
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    as_of = pd.Timestamp(args.as_of).normalize() if args.as_of else None
    output_dir = repo_path(args.output_dir)
    sec = summarize_sec_archive(repo_path(args.sec_companyfacts))
    raw = summarize_raw_feed(repo_path(args.earnings_feed), as_of)
    pit = summarize_pit_signals(repo_path(args.pit_signals), as_of)
    candidates = [summarize_candidate_book(repo_path(path)) for path in args.candidate_book]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_only": True,
        "production_activation_allowed": False,
        "live_trading_allowed": False,
        "selection_or_weighting_mutation": False,
        "sec_companyfacts": sec,
        "raw_feed": raw,
        "pit_signals": pit,
        "candidate_books": candidates,
        "actuals_managed": bool(sec.get("status") == "available" or any(c.get("actual_financial_columns_present") for c in candidates)),
        "proxy_scores_present": bool(any(c.get("proxy_score_columns_present") for c in candidates)),
        "true_revision_guidance_ready": bool(
            raw.get("regime_nowcast_coverage_ready") or pit.get("regime_nowcast_coverage_ready")
        ),
        "service_label_contract": SERVICE_LABELS,
    }
    write_json(output_dir / "summary.json", summary)
    write_layers_csv(output_dir / "earnings_data_layers.csv", summary)
    write_report(output_dir / "report.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
