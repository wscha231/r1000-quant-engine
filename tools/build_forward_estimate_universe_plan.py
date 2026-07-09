#!/usr/bin/env python3
"""Build shard plans for forward-only earnings-estimate universe scans.

This does not collect vendor data. It prepares deterministic ticker shards for
`.github/workflows/earnings_estimates_daily.yml` so broad universe scans can run
through the existing forward-only archive without turning the repo into a data
lake.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "forward-estimate-universe-plan-v1"
DEFAULT_OUTPUT_DIR = "outputs/forward_estimate_universe_plan"
DEFAULT_VENDOR_ORDER = "fmp,finnhub"
DEFAULT_WORKFLOW = "earnings_estimates_daily.yml"
DEFAULT_REPO = "wscha231/r1000-quant-engine"
DEFAULT_REF = "master"
DEFAULT_EXCLUDE_TICKERS = {
    "",
    "CASH",
    "USD",
    "US DOLLAR",
    "U.S. DOLLAR",
    "N/A",
    "NA",
    "NONE",
    "NULL",
}
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def normalize_ticker(value: Any) -> str:
    if value is None:
        return ""
    ticker = str(value).strip().upper()
    if ticker.endswith(".0") and ticker[:-2].isalpha():
        ticker = ticker[:-2]
    return ticker


def is_valid_equity_ticker(ticker: str, excludes: set[str]) -> bool:
    if ticker in excludes:
        return False
    if not TICKER_RE.match(ticker):
        return False
    return True


def expand_sources(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        if not value:
            continue
        pattern = str(repo_path(value))
        matches = [Path(x) for x in glob.glob(pattern)]
        paths.extend(matches if matches else [repo_path(value)])
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def select_ticker_column(frame: pd.DataFrame, preferred: list[str]) -> str:
    lowered = {str(col).lower(): str(col) for col in frame.columns}
    for name in preferred:
        if name in frame.columns:
            return name
        if name.lower() in lowered:
            return lowered[name.lower()]
    return str(frame.columns[0])


def collect_tickers(
    sources: list[Path],
    *,
    ticker_columns: list[str],
    excludes: set[str],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    by_ticker: dict[str, dict[str, Any]] = {}
    source_summaries: list[dict[str, Any]] = []
    for source in sources:
        if not source.exists():
            source_summaries.append({"source": display_path(source), "exists": False, "row_count": 0, "ticker_count": 0})
            continue
        frame = read_frame(source)
        if frame.empty:
            source_summaries.append({"source": display_path(source), "exists": True, "row_count": 0, "ticker_count": 0})
            continue
        column = select_ticker_column(frame, ticker_columns)
        raw_values = frame[column].tolist()
        source_tickers: set[str] = set()
        for raw in raw_values:
            ticker = normalize_ticker(raw)
            if not is_valid_equity_ticker(ticker, excludes):
                continue
            source_tickers.add(ticker)
            row = by_ticker.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "source_count": 0,
                    "row_count": 0,
                    "source_files": set(),
                    "first_source": display_path(source),
                },
            )
            row["row_count"] += 1
            row["source_files"].add(display_path(source))
        for ticker in source_tickers:
            by_ticker[ticker]["source_count"] += 1
        source_summaries.append(
            {
                "source": display_path(source),
                "exists": True,
                "row_count": int(len(frame)),
                "ticker_column": column,
                "ticker_count": int(len(source_tickers)),
            }
        )
    rows = []
    for ticker, row in by_ticker.items():
        source_files = sorted(row["source_files"])
        rows.append(
            {
                "ticker": ticker,
                "source_count": int(row["source_count"]),
                "row_count": int(row["row_count"]),
                "first_source": row["first_source"],
                "source_files": "|".join(source_files),
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["ticker"], kind="stable").reset_index(drop=True)
    return out, source_summaries


def split_shards(tickers: list[str], shard_size: int) -> list[list[str]]:
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")
    return [tickers[i : i + shard_size] for i in range(0, len(tickers), shard_size)]


def workflow_command(
    tickers: list[str],
    *,
    repo: str,
    ref: str,
    vendor_order: str,
    workflow: str,
) -> str:
    joined = ",".join(tickers)
    return (
        f"gh workflow run {workflow} --repo {repo} --ref {ref} "
        f"-f tickers='{joined}' -f ticker_limit=0 -f vendor_order='{vendor_order}'"
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def render_report(summary: dict[str, Any], shard_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Forward Estimate Universe Scan Plan",
        "",
        "## Verdict",
        "",
        "Use this as a forward-only archive plan. It does not change historical 7Y CAGR/MDD evidence, does not dispatch a fullrun, and does not enable production.",
        "",
        "## Summary",
        "",
        f"- status: `{summary['status']}`",
        f"- ticker_count: {summary['ticker_count']}",
        f"- shard_size: {summary['shard_size']}",
        f"- shard_count: {summary['shard_count']}",
        f"- vendor_order: `{summary['vendor_order']}`",
        f"- workflow: `{summary['workflow']}`",
        f"- backtest_acceptance_allowed: `{str(summary['backtest_acceptance_allowed']).lower()}`",
        f"- production_activation_allowed: `{str(summary['production_activation_allowed']).lower()}`",
        f"- live_trading_enabled: `{str(summary['live_trading_enabled']).lower()}`",
        "",
        "## Leakage Contract",
        "",
        "- `available_from` must remain the workflow fetch date.",
        "- Missing vendor coverage is neutral, not a reject signal.",
        "- Current/free estimate snapshots are forward paper-ledger evidence only.",
        "- Historical CAGR/MDD claims still require PIT estimate history or another PIT-safe source.",
        "- Alpha Vantage remains out of the default vendor order until key rotation is confirmed.",
        "",
        "## Shards",
        "",
        "| shard | tickers | csv | txt |",
        "|---:|---:|---|---|",
    ]
    for row in shard_rows:
        lines.append(f"| {row['shard_id']} | {row['ticker_count']} | `{row['csv']}` | `{row['txt']}` |")
    lines.extend(
        [
            "",
            "## Dispatch",
            "",
            "Run shards gradually because free vendor coverage and rate limits are uncertain. Inspect `summary.json` and `collector.log` for redacted errors after each run.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_plan(
    *,
    sources: list[str],
    output_dir: str,
    shard_size: int,
    max_tickers: int,
    vendor_order: str,
    repo: str,
    ref: str,
    workflow: str,
    ticker_columns: list[str],
    extra_excludes: list[str],
) -> dict[str, Any]:
    out_dir = repo_path(output_dir)
    source_paths = expand_sources(sources)
    excludes = set(DEFAULT_EXCLUDE_TICKERS)
    excludes.update(normalize_ticker(x) for x in extra_excludes)
    universe, source_summaries = collect_tickers(source_paths, ticker_columns=ticker_columns, excludes=excludes)
    if max_tickers > 0 and len(universe) > max_tickers:
        universe = universe.head(max_tickers).copy()
    tickers = universe["ticker"].tolist() if not universe.empty else []
    shards = split_shards(tickers, shard_size) if tickers else []

    out_dir.mkdir(parents=True, exist_ok=True)
    shard_dir = out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    universe_path = out_dir / "ticker_universe.csv"
    universe.to_csv(universe_path, index=False)

    shard_rows: list[dict[str, Any]] = []
    command_lines = [
        "# Generated dispatch commands. Forward-only archive; no fullrun.",
        "# Run gradually and inspect artifacts after each shard.",
    ]
    for idx, shard in enumerate(shards):
        shard_id = f"shard_{idx:03d}"
        csv_path = shard_dir / f"{shard_id}.csv"
        txt_path = shard_dir / f"{shard_id}.txt"
        pd.DataFrame({"ticker": shard}).to_csv(csv_path, index=False)
        txt_path.write_text(",".join(shard) + "\n", encoding="utf-8")
        cmd = workflow_command(shard, repo=repo, ref=ref, vendor_order=vendor_order, workflow=workflow)
        command_lines.append(cmd)
        shard_rows.append(
            {
                "shard_id": shard_id,
                "ticker_count": len(shard),
                "csv": display_path(csv_path),
                "txt": display_path(txt_path),
                "command": cmd,
            }
        )
    commands_path = out_dir / "dispatch_commands.ps1"
    commands_path.write_text("\n".join(command_lines) + "\n", encoding="utf-8")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "ready_for_forward_archive_dispatch" if tickers else "blocked_no_tickers",
        "research_only": True,
        "forward_only": True,
        "backtest_acceptance_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "alpha_vantage_default_paused_until_rotation": True,
        "vendor_order": vendor_order,
        "workflow": workflow,
        "repo": repo,
        "ref": ref,
        "source_files": [display_path(path) for path in source_paths],
        "source_file_count": len(source_paths),
        "source_summaries": source_summaries,
        "ticker_count": len(tickers),
        "shard_size": shard_size,
        "shard_count": len(shards),
        "ticker_universe_csv": display_path(universe_path),
        "dispatch_commands": display_path(commands_path),
        "shards": shard_rows,
        "missing_vendor_coverage_policy": "neutral",
        "acceptance_label": "forward_archive_plan_only",
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "report.md").write_text(render_report(summary, shard_rows), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", default=[], help="CSV/parquet source or glob containing a ticker column.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--shard-size", type=int, default=50)
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument("--vendor-order", default=DEFAULT_VENDOR_ORDER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--ticker-column", action="append", default=["ticker", "symbol", "Ticker", "Symbol"])
    parser.add_argument("--exclude-ticker", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = args.source or ["research/entry_classifier_predictions.csv"]
    summary = build_plan(
        sources=sources,
        output_dir=args.output_dir,
        shard_size=args.shard_size,
        max_tickers=args.max_tickers,
        vendor_order=args.vendor_order,
        repo=args.repo,
        ref=args.ref,
        workflow=args.workflow,
        ticker_columns=args.ticker_column,
        extra_excludes=args.exclude_ticker,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "ready_for_forward_archive_dispatch" else 2


if __name__ == "__main__":
    raise SystemExit(main())
