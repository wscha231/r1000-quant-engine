#!/usr/bin/env python3
"""Build PIT membership rows for the universe membership audit.

This tool is intentionally evidence-only. It converts a historical membership
file into the per-ticker monthly schema consumed by run_pit_membership_audit.py,
then runs that audit. It does not change selection, scoring, target books,
broker replay, production gates, or live trading.
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

from tools.run_pit_membership_audit import audit_membership_file, write_json  # noqa: E402

SCHEMA_VERSION = "pit-membership-producer-v1"
OUTPUT_SCHEMA_COLUMNS = [
    "rebalance_date",
    "ticker",
    "membership_source",
    "membership_available_from",
    "membership_end_date",
    "universe_label",
    "official_r1000_membership_proven",
    "proxy_universe_flag",
    "survivorship_status",
    "delisted_coverage_status",
    "ticker_change_coverage_status",
    "membership_pit_status",
]
CLEAN_SOURCE_KINDS = {"official_historical_membership", "historical_membership_file"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_table_auto(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix in {".csv", ".txt"}:
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        if isinstance(raw, dict):
            payload = raw.get("data", raw)
            if isinstance(payload, list):
                return pd.DataFrame(payload)
            if isinstance(payload, dict):
                try:
                    return pd.DataFrame(payload)
                except Exception:
                    return pd.DataFrame([payload])
    return pd.DataFrame()


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def first_col(columns: dict[str, str], names: list[str]) -> str | None:
    for name in names:
        if name in columns:
            return columns[name]
    return None


def normalize_ticker(value: Any) -> str:
    text = str(value or "").strip().upper().replace(".", "-")
    return text


def business_month_ends(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    if pd.isna(start) or pd.isna(end) or start > end:
        return []
    try:
        dates = pd.date_range(start=start.normalize(), end=end.normalize(), freq="BME")
    except ValueError:
        dates = pd.date_range(start=start.normalize(), end=end.normalize(), freq="BM")
    return [pd.Timestamp(d).normalize() for d in dates]


def normalize_source_kind(kind: str) -> str:
    text = str(kind or "").strip().lower()
    if text in {"official", "official_pit_r1000", "official_historical_membership"}:
        return "official_historical_membership"
    if text in {"historical", "historical_membership_file"}:
        return "historical_membership_file"
    if text in {"pit_proxy", "pit_proxy_universe", "proxy"}:
        return "pit_proxy_universe"
    if text in {"current", "current_constituents", "current_constituents_proxy"}:
        return "current_constituents_proxy"
    if text in {"static", "static_seed", "static_iwb_seed"}:
        return "static_seed"
    return text or "unknown"


def source_defaults(source_kind: str, source_name: str) -> dict[str, Any]:
    clean_source = source_kind in CLEAN_SOURCE_KINDS
    official = source_kind == "official_historical_membership"
    proxy = not clean_source
    if official:
        universe_label = "official_pit_r1000"
    elif source_kind == "historical_membership_file":
        universe_label = "historical_membership_file"
    else:
        universe_label = source_kind
    pit_status = "pit_clean" if clean_source else f"blocked_{source_kind}"
    return {
        "membership_source": source_name or source_kind,
        "universe_label": universe_label,
        "official_r1000_membership_proven": bool(official),
        "proxy_universe_flag": bool(proxy),
        "survivorship_status": "clean" if clean_source else "unknown",
        "delisted_coverage_status": "clean" if clean_source else "unknown",
        "ticker_change_coverage_status": "clean" if clean_source else "unknown",
        "membership_pit_status": pit_status,
    }


def normalize_membership_input(
    raw: pd.DataFrame,
    *,
    source_kind: str,
    source_name: str,
    default_available_from: str,
) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    d = raw.copy()
    cols = {str(c).strip().lower(): c for c in d.columns}
    ticker_col = first_col(cols, ["ticker", "symbol"])
    if not ticker_col:
        return pd.DataFrame()
    snap_col = first_col(cols, ["rebalance_date", "asof_date", "effective_date", "date"])
    from_col = first_col(cols, ["date_from", "effective_from", "start_date", "from_date"])
    to_col = first_col(cols, ["date_to", "effective_to", "end_date", "to_date", "membership_end_date"])
    available_col = first_col(
        cols,
        [
            "membership_available_from",
            "available_from",
            "published_at",
            "published_date",
            "accepted_at",
            "filing_date",
        ],
    )
    membership_source_col = first_col(cols, ["membership_source", "source", "universe_source"])
    universe_label_col = first_col(cols, ["universe_label"])
    official_col = first_col(cols, ["official_r1000_membership_proven", "official_pit_r1000"])
    proxy_col = first_col(cols, ["proxy_universe_flag"])
    survivorship_col = first_col(cols, ["survivorship_status"])
    delisted_col = first_col(cols, ["delisted_coverage_status"])
    ticker_change_col = first_col(cols, ["ticker_change_coverage_status"])
    pit_col = first_col(cols, ["membership_pit_status"])

    out = pd.DataFrame()
    out["ticker"] = d[ticker_col].map(normalize_ticker)
    out = out[out["ticker"].astype(str).str.len() > 0].copy()
    out["rebalance_date"] = pd.to_datetime(d[snap_col], errors="coerce") if snap_col else pd.NaT
    out["date_from"] = pd.to_datetime(d[from_col], errors="coerce") if from_col else pd.NaT
    out["date_to"] = pd.to_datetime(d[to_col], errors="coerce") if to_col else pd.NaT
    if available_col:
        out["membership_available_from"] = pd.to_datetime(d[available_col], errors="coerce")
    elif default_available_from:
        out["membership_available_from"] = pd.to_datetime(default_available_from, errors="coerce")
    else:
        out["membership_available_from"] = pd.NaT

    defaults = source_defaults(source_kind, source_name)
    out["membership_source"] = d[membership_source_col].astype(str) if membership_source_col else defaults["membership_source"]
    out["universe_label"] = d[universe_label_col].astype(str) if universe_label_col else defaults["universe_label"]
    out["official_r1000_membership_proven"] = (
        d[official_col].map(normalize_bool) if official_col else defaults["official_r1000_membership_proven"]
    )
    out["proxy_universe_flag"] = d[proxy_col].map(normalize_bool) if proxy_col else defaults["proxy_universe_flag"]
    out["survivorship_status"] = d[survivorship_col].astype(str) if survivorship_col else defaults["survivorship_status"]
    out["delisted_coverage_status"] = d[delisted_col].astype(str) if delisted_col else defaults["delisted_coverage_status"]
    out["ticker_change_coverage_status"] = d[ticker_change_col].astype(str) if ticker_change_col else defaults["ticker_change_coverage_status"]
    out["membership_pit_status"] = d[pit_col].astype(str) if pit_col else defaults["membership_pit_status"]
    return out.drop_duplicates().reset_index(drop=True)


def expand_membership_by_month(
    membership: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if membership is None or membership.empty:
        return pd.DataFrame(columns=OUTPUT_SCHEMA_COLUMNS)
    start = pd.to_datetime(start_date, errors="coerce")
    end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        raise ValueError("start-date and end-date are required")

    rows: list[dict[str, Any]] = []
    exact = membership[membership["rebalance_date"].notna()].copy()
    if not exact.empty:
        exact = exact[(exact["rebalance_date"] >= start) & (exact["rebalance_date"] <= end)]
        for row in exact.itertuples(index=False):
            rows.append(row_to_output_dict(row, getattr(row, "rebalance_date"), getattr(row, "date_to", pd.NaT)))

    ranged = membership[membership["rebalance_date"].isna() & (membership["date_from"].notna() | membership["date_to"].notna())].copy()
    month_ends = business_month_ends(start, end)
    for row in ranged.itertuples(index=False):
        row_start = getattr(row, "date_from", pd.NaT)
        row_end = getattr(row, "date_to", pd.NaT)
        effective_start = max(start, pd.Timestamp(row_start).normalize()) if pd.notna(row_start) else start
        effective_end = min(end, pd.Timestamp(row_end).normalize()) if pd.notna(row_end) else end
        for dt in month_ends:
            if effective_start <= dt <= effective_end:
                rows.append(row_to_output_dict(row, dt, row_end))

    undated = membership[
        membership["rebalance_date"].isna() & membership["date_from"].isna() & membership["date_to"].isna()
    ].copy()
    for row in undated.itertuples(index=False):
        # Static lists are not PIT monthly evidence. Emit one diagnostic row at
        # end_date so the audit can block clean labels instead of silently
        # projecting current constituents through history.
        rows.append(row_to_output_dict(row, end, pd.NaT))

    out = pd.DataFrame(rows, columns=OUTPUT_SCHEMA_COLUMNS)
    if out.empty:
        return pd.DataFrame(columns=OUTPUT_SCHEMA_COLUMNS)
    out = out.drop_duplicates(["rebalance_date", "ticker", "membership_source"], keep="last")
    out = out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    return out


def iso_date(value: Any) -> str:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return ""
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def row_to_output_dict(row: Any, rebalance_date: Any, membership_end_date: Any) -> dict[str, Any]:
    return {
        "rebalance_date": iso_date(rebalance_date),
        "ticker": str(getattr(row, "ticker", "")).upper(),
        "membership_source": str(getattr(row, "membership_source", "")),
        "membership_available_from": iso_date(getattr(row, "membership_available_from", pd.NaT)),
        "membership_end_date": iso_date(membership_end_date),
        "universe_label": str(getattr(row, "universe_label", "")),
        "official_r1000_membership_proven": bool(getattr(row, "official_r1000_membership_proven", False)),
        "proxy_universe_flag": bool(getattr(row, "proxy_universe_flag", False)),
        "survivorship_status": str(getattr(row, "survivorship_status", "unknown")),
        "delisted_coverage_status": str(getattr(row, "delisted_coverage_status", "unknown")),
        "ticker_change_coverage_status": str(getattr(row, "ticker_change_coverage_status", "unknown")),
        "membership_pit_status": str(getattr(row, "membership_pit_status", "unknown")),
    }


def build_manifest(output: pd.DataFrame, audit: dict[str, Any], *, source_path: Path, source_kind: str) -> dict[str, Any]:
    dates = pd.to_datetime(output.get("rebalance_date", pd.Series(dtype=str)), errors="coerce")
    tickers = output.get("ticker", pd.Series(dtype=str)).dropna().astype(str)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "source_path": str(source_path),
        "source_kind": source_kind,
        "output_rows": int(len(output)),
        "rebalance_date_count": int(dates.dropna().nunique()),
        "ticker_count": int(tickers.nunique()),
        "start_date": iso_date(dates.min()) if dates.notna().any() else "",
        "end_date": iso_date(dates.max()) if dates.notna().any() else "",
        "pit_universe_label_clean": bool(audit.get("pit_universe_label_clean")),
        "historical_universe_pit_clean": bool(audit.get("historical_universe_pit_clean")),
        "official_pit_r1000": bool(audit.get("official_pit_r1000")),
        "production_mutation_allowed": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build per-ticker PIT membership rows and audit artifacts.")
    ap.add_argument("--membership-file", required=True)
    ap.add_argument("--output-dir", default="outputs/universe_health")
    ap.add_argument("--start-date", required=True)
    ap.add_argument("--end-date", required=True)
    ap.add_argument("--source-kind", default="historical_membership_file")
    ap.add_argument("--source-name", default="")
    ap.add_argument("--default-available-from", default="")
    ap.add_argument("--coverage-floor", type=int, default=400)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    source_path = Path(args.membership_file)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_kind = normalize_source_kind(args.source_kind)
    source_name = args.source_name or source_path.name

    raw = read_table_auto(source_path)
    normalized = normalize_membership_input(
        raw,
        source_kind=source_kind,
        source_name=source_name,
        default_available_from=args.default_available_from,
    )
    output = expand_membership_by_month(normalized, start_date=args.start_date, end_date=args.end_date)
    out_path = output_dir / "pit_membership_by_month.csv"
    output.to_csv(out_path, index=False)

    audit_payload = audit_membership_file(out_path, output_dir, coverage_floor=args.coverage_floor)
    producer_manifest = build_manifest(output, audit_payload["audit"], source_path=source_path, source_kind=source_kind)
    write_json(output_dir / "pit_membership_producer_manifest.json", producer_manifest)

    if args.strict and not audit_payload["audit"].get("pit_universe_label_clean"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
