#!/usr/bin/env python3
"""Create review-only percentile bands from the forward paper ledger.

The output intentionally does not publish point CAGR promises. Bands are based
only on elapsed paper-ledger observations and remain blocked for public display
until governance/readiness gates are cleared.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = "forward-expectation-band-v1"
DEFAULT_LEDGER = "outputs/forward_service_ledger/forward_paper_ledger.csv"
DEFAULT_OUTPUT_DIR = "outputs/forward_expectation_band"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def latest_by_portfolio(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("event_type") not in {"seed", "valuation", "correction"}:
            continue
        portfolio = row.get("portfolio_kind", "")
        row_date = parse_date(row.get("as_of_date", ""))
        old_date = parse_date(latest.get(portfolio, {}).get("as_of_date", "")) if portfolio in latest else None
        if row_date and (old_date is None or row_date >= old_date):
            latest[portfolio] = row
    return latest


def run(args: argparse.Namespace) -> dict[str, Any]:
    ledger = repo_path(args.ledger)
    out_dir = repo_path(args.output_dir)
    rows = read_csv(ledger)
    latest = latest_by_portfolio(rows)
    seed_dates = [parse_date(row.get("as_of_date", "")) for row in rows if row.get("event_type") == "seed"]
    latest_dates = [parse_date(row.get("as_of_date", "")) for row in latest.values()]
    valid_seed_dates = [d for d in seed_dates if d]
    valid_latest_dates = [d for d in latest_dates if d]
    elapsed_days = 0
    if valid_seed_dates and valid_latest_dates:
        elapsed_days = max(0, (max(valid_latest_dates) - min(valid_seed_dates)).days)

    latest_returns = [safe_float(row.get("period_return")) for row in latest.values()]
    band_status = "completed" if elapsed_days >= int(args.min_elapsed_days) and latest_returns else "insufficient_forward_history"
    bands = {
        "p10_return": percentile(latest_returns, 0.10),
        "p25_return": percentile(latest_returns, 0.25),
        "p50_return": percentile(latest_returns, 0.50),
        "p75_return": percentile(latest_returns, 0.75),
        "p90_return": percentile(latest_returns, 0.90),
    } if band_status == "completed" else {}
    band_rows = [
        {"band": key, "value": value, "basis": "paper_ledger_elapsed_return_distribution"}
        for key, value in bands.items()
    ]

    payload = {
        "status": band_status,
        "schema_version": SCHEMA_VERSION,
        "ledger": str(ledger),
        "portfolio_count": len(latest),
        "ledger_row_count": len(rows),
        "elapsed_days": elapsed_days,
        "min_elapsed_days": int(args.min_elapsed_days),
        "display_policy": "percentile_bands_only",
        "point_cagr_display_allowed": False,
        "public_display_allowed": False,
        "production_activation_allowed": False,
        "bands": bands,
        "blockers": [] if band_status == "completed" else ["insufficient_forward_history_for_expectation_band"],
        "research_only": True,
        "review_only": True,
    }
    write_json(out_dir / "expectation_bands.json", payload)
    write_csv(out_dir / "expectation_bands.csv", band_rows, ["band", "value", "basis"])
    report = [
        "# Forward Expectation Band",
        "",
        f"- Status: `{band_status}`",
        f"- Elapsed days: `{elapsed_days}`",
        "- Display policy: `percentile_bands_only`",
        "- Point CAGR display allowed: `false`",
        "- Public display allowed: `false`",
        "",
        "This artifact is review-only and must not be converted into a point CAGR promise.",
        "",
    ]
    (out_dir / "report.md").write_text("\n".join(report), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-elapsed-days", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
