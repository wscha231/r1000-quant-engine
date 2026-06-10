#!/usr/bin/env python3
"""Build a canonical 13F CUSIP -> ticker map from PIT holdings evidence.

SEC 13F information tables usually contain CUSIP and issuer name, not ticker.
This sidecar creates a durable mapping file before institutional signal scoring
so 13F evidence does not silently collapse to zero tickers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_13f_parser import normalize_cusip  # noqa: E402
from tools.run_sec_submissions_collector import load_company_tickers, repo_path  # noqa: E402

DEFAULT_HOLDINGS = "data_pit/sec/institutional_13f_holdings.parquet"
DEFAULT_RAW_DIR = "data_raw/sec"
DEFAULT_OUTPUT = "data_pit/sec/cusip_ticker_map.parquet"
DEFAULT_CSV_OUTPUT = "data_pit/sec/cusip_ticker_map.csv"
DEFAULT_AUDIT = "outputs/sec_institutional_signals/mapping_audit.json"
DEFAULT_UNMAPPED = "outputs/sec_institutional_signals/unmapped_13f_holdings.csv"
DEFAULT_MANUAL_OVERRIDES = "research/sec_13f_cusip_map_overrides.csv"
DEFAULT_SEED_FILES = [
    "outputs/reports/scored_latest.csv",
    "outputs/reports/candidate_replay_book.csv",
    "outputs/scored_latest.csv",
    "research/phase14_artifact/scored_latest.csv",
]


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def issuer_name_key(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9 ]+", " ", str(value or "").upper().replace("&", " AND "))
    aliases = {
        "AIRLS": "AIRLINES",
        "AMER": "AMERICA",
        "BK": "BANK",
        "CENTY": "CENTURY",
        "FINL": "FINANCIAL",
        "INDS": "INDUSTRIES",
        "INTL": "INTERNATIONAL",
        "MACHS": "MACHINES",
        "MTRS": "MOTORS",
        "PETE": "PETROLEUM",
        "PHARMACEUTICAL": "PHARMACEUTICAL",
        "SVCS": "SERVICES",
        "TECH": "TECHNOLOGY",
        "COMMUNICATIONS": "COMMUNICATION",
        "HLDGS": "HOLDINGS",
        "MGMT": "MANAGEMENT",
    }
    stop = {
        "THE",
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "COS",
        "LTD",
        "LIMITED",
        "PLC",
        "SA",
        "NV",
        "AG",
        "SE",
        "LP",
        "LLC",
        "COM",
        "COMMON",
        "STOCK",
        "SHARE",
        "SHARES",
        "CLASS",
        "CL",
        "NEW",
        "ORD",
        "ORDINARY",
        "SHS",
        "ADR",
        "ADS",
        "SPONSORED",
        "DEPOSITARY",
        "HOLDING",
        "HOLDINGS",
        "GROUP",
        "AND",
        "DEL",
        "DELAWARE",
        "N",
        "OF",
    }
    tokens = [aliases.get(tok, tok) for tok in text.split() if tok and tok not in stop]
    return " ".join(tokens)


def _first_present(cols: dict[str, str], names: list[str]) -> str:
    for name in names:
        if name.lower() in cols:
            return cols[name.lower()]
    return ""


def mapping_from_ticker_name_frame(frame: pd.DataFrame, *, source: str, confidence: float) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["issuer_key", "ticker", "source", "confidence"])
    cols = {str(c).lower(): str(c) for c in frame.columns}
    ticker_col = _first_present(cols, ["ticker", "symbol", "ticker_mapped"])
    name_col = _first_present(cols, ["name", "Name", "title", "issuer_name", "company", "security_name"])
    if not ticker_col or not name_col:
        return pd.DataFrame(columns=["issuer_key", "ticker", "source", "confidence"])
    d = frame[[ticker_col, name_col]].copy()
    d.columns = ["ticker", "issuer_name"]
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()
    d["issuer_key"] = d["issuer_name"].map(issuer_name_key)
    d = d[d["ticker"].ne("") & d["ticker"].ne("NAN") & d["issuer_key"].ne("")].copy()
    if d.empty:
        return pd.DataFrame(columns=["issuer_key", "ticker", "source", "confidence"])
    counts = d.groupby("issuer_key")["ticker"].nunique()
    unique_keys = set(counts[counts.eq(1)].index)
    d = d[d["issuer_key"].isin(unique_keys)].drop_duplicates("issuer_key", keep="first")
    d["source"] = source
    d["confidence"] = float(confidence)
    return d[["issuer_key", "ticker", "source", "confidence"]].copy()


def load_company_ticker_name_map(raw_dir: Path, *, user_agent: str, refresh: bool) -> pd.DataFrame:
    try:
        companies = load_company_tickers(raw_dir, user_agent=user_agent, refresh=refresh)
    except Exception as exc:
        print(f"[cusip-map] warning: company_tickers unavailable: {exc}", file=sys.stderr)
        companies = pd.DataFrame()
    return mapping_from_ticker_name_frame(companies, source="sec_company_tickers", confidence=0.95)


def load_seed_maps(paths: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for item in paths:
        path = repo_path(item)
        if not path.exists():
            continue
        try:
            seed = read_table(path)
        except Exception as exc:
            print(f"[cusip-map] warning: seed read failed {path}: {exc}", file=sys.stderr)
            continue
        mapped = mapping_from_ticker_name_frame(seed, source=f"seed:{path.name}", confidence=0.90)
        if not mapped.empty:
            frames.append(mapped)
    if not frames:
        return pd.DataFrame(columns=["issuer_key", "ticker", "source", "confidence"])
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["confidence", "source"], ascending=[False, True]).drop_duplicates("issuer_key", keep="first")
    return out


def load_manual_overrides(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["cusip", "ticker", "issuer_name", "issuer_key", "source", "confidence"])
    d = read_table(path)
    cols = {str(c).lower(): str(c) for c in d.columns}
    cusip_col = cols.get("cusip")
    ticker_col = cols.get("ticker") or cols.get("ticker_mapped")
    if not cusip_col or not ticker_col:
        return pd.DataFrame(columns=["cusip", "ticker", "issuer_name", "issuer_key", "source", "confidence"])
    out = d.copy()
    out["cusip"] = out[cusip_col].map(normalize_cusip)
    out["ticker"] = out[ticker_col].astype(str).str.upper().str.strip()
    name_col = cols.get("issuer_name") or cols.get("name") or cols.get("title")
    out["issuer_name"] = out[name_col].astype(str) if name_col else ""
    out["issuer_key"] = out["issuer_name"].map(issuer_name_key)
    out["source"] = "manual_override"
    out["confidence"] = 1.0
    out = out[out["cusip"].ne("") & out["ticker"].ne("")].copy()
    return out[["cusip", "ticker", "issuer_name", "issuer_key", "source", "confidence"]].drop_duplicates("cusip", keep="first")


def build_cusip_map(
    holdings: pd.DataFrame,
    *,
    raw_dir: Path,
    manual_overrides: Path,
    seed_files: list[str],
    user_agent: str,
    refresh_company_tickers: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if holdings.empty:
        empty = pd.DataFrame(columns=["cusip", "ticker", "issuer_name", "issuer_key", "source", "confidence"])
        return empty, empty, {"holding_rows": 0, "unique_cusips": 0, "mapped_unique_cusips": 0}

    d = holdings.copy()
    if "cusip" not in d.columns:
        d["cusip"] = ""
    if "issuer_name" not in d.columns:
        d["issuer_name"] = ""
    d["cusip"] = d["cusip"].map(normalize_cusip)
    d["issuer_name"] = d["issuer_name"].astype(str).str.strip()
    d["issuer_key"] = d["issuer_name"].map(issuer_name_key)
    d = d[d["cusip"].ne("")].copy()

    manual = load_manual_overrides(manual_overrides)
    source_maps = [
        load_company_ticker_name_map(raw_dir, user_agent=user_agent, refresh=refresh_company_tickers),
        load_seed_maps(seed_files),
    ]
    source_maps = [frame for frame in source_maps if not frame.empty]
    key_maps = (
        pd.concat(source_maps, ignore_index=True)
        if source_maps
        else pd.DataFrame(columns=["issuer_key", "ticker", "source", "confidence"])
    )
    if not key_maps.empty:
        key_maps = key_maps.sort_values(["confidence", "source"], ascending=[False, True]).drop_duplicates(
            "issuer_key", keep="first"
        )
    key_lookup = key_maps.set_index("issuer_key").to_dict("index") if not key_maps.empty else {}
    manual_lookup = manual.set_index("cusip").to_dict("index") if not manual.empty else {}

    rows: list[dict[str, Any]] = []
    for cusip, group in d.groupby("cusip"):
        issuer_name = str(group["issuer_name"].replace("", pd.NA).dropna().mode().iloc[0]) if group["issuer_name"].replace("", pd.NA).dropna().size else ""
        issuer_key = issuer_name_key(issuer_name)
        if cusip in manual_lookup:
            item = manual_lookup[cusip]
            rows.append(
                {
                    "cusip": cusip,
                    "ticker": str(item.get("ticker") or "").upper().strip(),
                    "issuer_name": issuer_name or item.get("issuer_name", ""),
                    "issuer_key": issuer_key or item.get("issuer_key", ""),
                    "source": item.get("source", "manual_override"),
                    "confidence": float(item.get("confidence", 1.0)),
                }
            )
            continue
        item = key_lookup.get(issuer_key)
        if item:
            rows.append(
                {
                    "cusip": cusip,
                    "ticker": str(item.get("ticker") or "").upper().strip(),
                    "issuer_name": issuer_name,
                    "issuer_key": issuer_key,
                    "source": item.get("source", "issuer_name_exact"),
                    "confidence": float(item.get("confidence", 0.90)),
                }
            )

    mapped = pd.DataFrame(rows, columns=["cusip", "ticker", "issuer_name", "issuer_key", "source", "confidence"])
    if not mapped.empty:
        mapped = mapped[mapped["cusip"].ne("") & mapped["ticker"].ne("")].drop_duplicates("cusip", keep="first")

    mapped_cusips = set(mapped["cusip"].astype(str)) if not mapped.empty else set()
    unmapped = (
        d[~d["cusip"].isin(mapped_cusips)]
        .groupby(["cusip", "issuer_name", "issuer_key"], dropna=False)
        .size()
        .reset_index(name="holding_rows")
        .sort_values("holding_rows", ascending=False)
    )
    total_unique = int(d["cusip"].nunique())
    mapped_unique = int(mapped["cusip"].nunique()) if not mapped.empty else 0
    audit = {
        "research_only": True,
        "production_activation_allowed": False,
        "score_total_changed": False,
        "holding_rows": int(len(holdings)),
        "unique_cusips": total_unique,
        "mapped_unique_cusips": mapped_unique,
        "mapped_pct": float(mapped_unique / total_unique) if total_unique else 0.0,
        "mapped_ticker_count": int(mapped["ticker"].nunique()) if not mapped.empty else 0,
        "unmapped_unique_cusips": int(total_unique - mapped_unique),
        "manual_override_rows": int(len(manual)),
        "issuer_key_source_rows": int(len(key_maps)),
        "sources": mapped["source"].value_counts().to_dict() if not mapped.empty else {},
    }
    return mapped, unmapped, audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings", default=DEFAULT_HOLDINGS)
    parser.add_argument("--raw-dir", default=DEFAULT_RAW_DIR)
    parser.add_argument("--manual-overrides", default=DEFAULT_MANUAL_OVERRIDES)
    parser.add_argument("--seed-file", action="append", default=[])
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--csv-output", default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--audit", default=DEFAULT_AUDIT)
    parser.add_argument("--unmapped", default=DEFAULT_UNMAPPED)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--refresh-company-tickers", action="store_true")
    args = parser.parse_args()

    seed_files = list(args.seed_file or []) or list(DEFAULT_SEED_FILES)
    mapped, unmapped, audit = build_cusip_map(
        read_table(repo_path(args.holdings)),
        raw_dir=repo_path(args.raw_dir),
        manual_overrides=repo_path(args.manual_overrides),
        seed_files=seed_files,
        user_agent=args.user_agent,
        refresh_company_tickers=bool(args.refresh_company_tickers),
    )

    output = repo_path(args.output)
    csv_output = repo_path(args.csv_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    mapped.to_parquet(output, index=False)
    mapped.to_csv(csv_output, index=False)

    unmapped_path = repo_path(args.unmapped)
    unmapped_path.parent.mkdir(parents=True, exist_ok=True)
    unmapped.to_csv(unmapped_path, index=False)

    audit.update({"parquet": str(output), "csv": str(csv_output), "unmapped_csv": str(unmapped_path)})
    write_json(repo_path(args.audit), audit)
    print(json.dumps({"status": "ok", **audit}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
