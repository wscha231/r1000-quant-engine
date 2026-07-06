#!/usr/bin/env python3
"""Run287 R4 Concentrated decision-time alpha source readiness audit.

This tool records the user's R4 choice to open a stronger decision-time source
for Concentrated alpha work, then checks whether the feed is actually usable.
It does not build a hook, rank stocks, dispatch a fullrun, download data, tune
thresholds, or promote production.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.check_earnings_guidance_coverage import coverage_summary_from_frame  # noqa: E402


DEFAULT_RUN_ROOT = "cloud_results/full_rebuild/20260705_28725350727_global_alpha_universe"
DEFAULT_CANDIDATE_BOOK = DEFAULT_RUN_ROOT + "/reports/candidate_replay_book.csv"
DEFAULT_TARGET_BOOK = DEFAULT_RUN_ROOT + "/alphaops_vnext/official_concentrated_target_book.csv"
DEFAULT_EARNINGS_SIGNALS = "data_pit/events/earnings_revision_signals.parquet"
DEFAULT_RAW_EARNINGS_FEED = "data_raw/events/earnings_revisions.csv"
DEFAULT_OUTPUT_DIR = "outputs/run287_r4_conc_alpha_source"
DEFAULT_AS_OF = "2026-07-02"

ALT_SOURCE_PATHS = {
    "form4_transactions": "data_pit/sec/form4_transactions.parquet",
    "institutional_13f_holdings": "data_pit/sec/institutional_13f_holdings.parquet",
    "sec_ownership_signals": "data_pit/sec/sec_ownership_signals.parquet",
    "etf_thematic_signals": "data_pit/etf_holdings/etf_thematic_signals.parquet",
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def first_available(paths: list[Path]) -> Path:
    for path in paths:
        if path.exists():
            return path
    return paths[0]


def source_health(path: Path, ticker_cols: list[str]) -> dict[str, Any]:
    frame = read_table(path)
    out: dict[str, Any] = {
        "path": display_path(path),
        "exists": bool(path.exists()),
        "status": "missing" if not path.exists() else "available",
        "row_count": int(len(frame)),
        "ticker_count": 0,
        "min_available_from": None,
        "max_available_from": None,
        "missing_available_from": None,
        "decision_time_usable": False,
    }
    if frame.empty:
        return out
    for col in ticker_cols:
        if col in frame.columns:
            tickers = frame[col].astype(str).str.upper().str.strip()
            out["ticker_count"] = int(tickers[tickers.ne("") & tickers.ne("NAN")].nunique())
            break
    if "available_from" in frame.columns:
        available = pd.to_datetime(frame["available_from"], errors="coerce")
        out["missing_available_from"] = int(available.isna().sum())
        if available.notna().any():
            out["min_available_from"] = available.min().date().isoformat()
            out["max_available_from"] = available.max().date().isoformat()
        out["decision_time_usable"] = bool(out["row_count"] > 0 and out["ticker_count"] > 0 and out["missing_available_from"] == 0)
    else:
        out["missing_available_from"] = int(len(frame))
    return out


def summarize_earnings_guidance(
    *,
    signals_path: Path,
    raw_feed_path: Path,
    as_of: pd.Timestamp,
    target_book: Path,
    candidate_book: Path,
) -> dict[str, Any]:
    input_path = first_available([signals_path, raw_feed_path])
    frame = read_table(input_path)
    coverage = coverage_summary_from_frame(
        frame,
        as_of=as_of,
        target_book=target_book,
        candidate_book=candidate_book,
    )
    return {
        "input_used": display_path(input_path),
        "signals_path": display_path(signals_path),
        "raw_feed_path": display_path(raw_feed_path),
        "signals_exists": bool(signals_path.exists()),
        "raw_feed_exists": bool(raw_feed_path.exists()),
        "coverage": coverage,
        "research_ready": bool(coverage.get("research_ready", False)),
        "service_ready": bool(coverage.get("service_ready", False)),
        "policy_ready": bool(coverage.get("policy_ready", False)),
        "status": coverage.get("status", "DATA_INSUFFICIENT"),
    }


def render_report(payload: dict[str, Any]) -> str:
    earnings = payload["earnings_guidance"]
    coverage = earnings["coverage"]
    lines = [
        "# Run287 R4 Concentrated Alpha Source Readiness",
        "",
        f"Status: `{payload['status']}`",
        f"Decision label: `{payload['decision_label']}`",
        "",
        "Research-only readiness audit. No fullrun, hook, data download, threshold",
        "tuning, production promotion, or live-trading action was performed.",
        "",
        "## Decision",
        "",
        "- user_decision: `open_w4_decision_time_source`",
        "- rank_rs_revenue_variants_allowed: `false`",
        "- hook_allowed: `false`",
        "- next_action_requires_oos_source_screen: `true`",
        "",
        "## Earnings / Guidance Source",
        "",
        f"- input_used: `{earnings['input_used']}`",
        f"- raw_feed_exists: `{str(earnings['raw_feed_exists']).lower()}`",
        f"- signals_exists: `{str(earnings['signals_exists']).lower()}`",
        f"- coverage_status: `{earnings['status']}`",
        f"- research_ready: `{str(earnings['research_ready']).lower()}`",
        f"- coverage_eligible_rows: `{coverage.get('coverage_eligible_rows', 0)}`",
        f"- coverage_eligible_tickers: `{coverage.get('coverage_eligible_tickers', 0)}`",
        f"- directional_guidance_rows: `{coverage.get('directional_guidance_rows', 0)}`",
        f"- history_depth_ticker_count: `{coverage.get('history_depth_ticker_count', 0)}`",
        "",
        "## Alternate Source Inventory",
        "",
        "| Source | Exists | Rows | Tickers | Decision-time usable |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, item in payload["alternate_sources"].items():
        lines.append(
            "| {name} | {exists} | {rows} | {tickers} | {usable} |".format(
                name=name,
                exists=str(item.get("exists")).lower(),
                rows=item.get("row_count", 0),
                tickers=item.get("ticker_count", 0),
                usable=str(item.get("decision_time_usable")).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"- candidate_source_ready: `{str(payload['candidate_source_ready']).lower()}`",
            f"- candidate_allowed: `{str(payload['candidate_allowed']).lower()}`",
            "- A source becoming research-ready only permits an OOS source screen.",
            "- It does not permit a Concentrated hook or fullrun by itself.",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    as_of = pd.Timestamp(args.as_of).normalize()
    target_book = repo_path(args.target_book)
    candidate_book = repo_path(args.candidate_book)
    earnings = summarize_earnings_guidance(
        signals_path=repo_path(args.earnings_signals),
        raw_feed_path=repo_path(args.raw_earnings_feed),
        as_of=as_of,
        target_book=target_book,
        candidate_book=candidate_book,
    )
    alternate = {
        name: source_health(repo_path(path), ["ticker", "ticker_mapped", "issuer_ticker", "holding_ticker"])
        for name, path in ALT_SOURCE_PATHS.items()
    }
    alternate_ready = any(bool(item.get("decision_time_usable")) for item in alternate.values())
    candidate_source_ready = bool(earnings["research_ready"] or alternate_ready)
    decision_label = "ready_for_oos_source_screen" if candidate_source_ready else "blocked_missing_w4_decision_time_source"
    payload = {
        "schema_version": "run287-r4-conc-alpha-source-readiness-v1",
        "status": "completed",
        "decision_label": decision_label,
        "research_only": True,
        "run_id": "28725350727",
        "portfolio": "concentrated",
        "as_of": as_of.date().isoformat(),
        "user_decision": "open_w4_decision_time_source",
        "rank_rs_revenue_variants_allowed": False,
        "forward_returns_used_for_ranking": False,
        "new_alpha_hook_added": False,
        "threshold_tuning_performed": False,
        "fullrun_dispatched": False,
        "market_data_downloaded": False,
        "target_book_regenerated": False,
        "production_promotion_allowed": False,
        "live_trading_enabled": False,
        "candidate_source_ready": candidate_source_ready,
        "candidate_allowed": False,
        "hook_allowed": False,
        "next_action_requires_oos_source_screen": True,
        "target_book": display_path(target_book),
        "candidate_book": display_path(candidate_book),
        "earnings_guidance": earnings,
        "alternate_sources": alternate,
        "artifacts": {
            "summary": display_path(output_dir / "summary.json"),
            "source_readiness": display_path(output_dir / "source_readiness.csv"),
            "report": display_path(output_dir / "report.md"),
        },
    }
    source_rows: list[dict[str, Any]] = [
        {
            "source": "earnings_guidance",
            "exists": bool(earnings["signals_exists"] or earnings["raw_feed_exists"]),
            "status": earnings["status"],
            "research_ready": earnings["research_ready"],
            "decision_time_usable": earnings["research_ready"],
            "row_count": earnings["coverage"].get("input_rows", 0),
            "ticker_count": earnings["coverage"].get("coverage_eligible_tickers", 0),
        }
    ]
    for name, item in alternate.items():
        source_rows.append(
            {
                "source": name,
                "exists": item.get("exists"),
                "status": item.get("status"),
                "research_ready": False,
                "decision_time_usable": item.get("decision_time_usable"),
                "row_count": item.get("row_count"),
                "ticker_count": item.get("ticker_count"),
            }
        )
    pd.DataFrame(source_rows).to_csv(output_dir / "source_readiness.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-book", default=DEFAULT_CANDIDATE_BOOK)
    parser.add_argument("--target-book", default=DEFAULT_TARGET_BOOK)
    parser.add_argument("--earnings-signals", default=DEFAULT_EARNINGS_SIGNALS)
    parser.add_argument("--raw-earnings-feed", default=DEFAULT_RAW_EARNINGS_FEED)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps({"status": payload["status"], "decision_label": payload["decision_label"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
