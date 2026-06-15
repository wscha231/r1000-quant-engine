#!/usr/bin/env python3
"""Build ADR/universe review candidates without editing the live YAML.

The monthly workflow should produce a PR-review artifact. Promotion into
adr_universe.yaml remains a human-approved repo change because universe edits
change the production search space.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO / path


def safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        out = float(value)
        return out if pd.notna(out) else None
    except Exception:
        return None


def read_existing_symbols(path: Path) -> set[str]:
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8", errors="ignore")
    found = set(re.findall(r"(?:ticker|symbol)\s*:\s*['\"]?([A-Z][A-Z0-9.\-]+)", text))
    for line in text.splitlines():
        item = line.strip().lstrip("-").strip()
        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", item):
            found.add(item)
    return found


def first_col(frame: pd.DataFrame, names: list[str]) -> str | None:
    lower = {str(c).lower(): c for c in frame.columns}
    for name in names:
        if name.lower() in lower:
            return str(lower[name.lower()])
    return None


def standardize_candidate_frame(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    ticker_col = first_col(frame, ["ticker", "symbol", "act_symbol"])
    if not ticker_col:
        return pd.DataFrame()
    price_col = first_col(frame, ["last_price", "price", "close", "adj_close", "adjusted_close"])
    volume_col = first_col(frame, ["avg_volume_20d", "avg_volume", "volume", "last_volume"])
    dollar_col = first_col(frame, ["avg_dollar_volume_20d", "dollar_volume", "avg_dollar_volume"])
    mcap_col = first_col(frame, ["market_cap", "mcap", "marketcap"])
    exchange_col = first_col(frame, ["exchange", "listing_exchange"])
    tradable_col = first_col(frame, ["alpaca_tradable", "tradable", "is_tradable"])
    adr_col = first_col(frame, ["is_adr", "adr", "security_type"])

    rows: list[dict[str, Any]] = []
    for _, raw in frame.iterrows():
        ticker = str(raw.get(ticker_col) or "").strip().upper()
        if not ticker:
            continue
        price = safe_float(raw.get(price_col)) if price_col else None
        volume = safe_float(raw.get(volume_col)) if volume_col else None
        dollar_volume = safe_float(raw.get(dollar_col)) if dollar_col else None
        if dollar_volume is None and price is not None and volume is not None:
            dollar_volume = price * volume
        mcap = safe_float(raw.get(mcap_col)) if mcap_col else None
        exchange = str(raw.get(exchange_col) or "").strip().upper() if exchange_col else ""
        tradable_raw = raw.get(tradable_col) if tradable_col else None
        tradable = None if tradable_raw is None else str(tradable_raw).strip().lower() in {"1", "true", "yes", "y"}
        adr_raw = str(raw.get(adr_col) or "").strip().lower() if adr_col else ""
        is_adr = None
        if adr_col:
            is_adr = adr_raw in {"1", "true", "yes", "y", "adr", "american depositary receipt"}
        rows.append(
            {
                "ticker": ticker,
                "source": source,
                "exchange": exchange,
                "is_adr": is_adr,
                "last_price": price,
                "avg_volume_20d": volume,
                "avg_dollar_volume_20d": dollar_volume,
                "market_cap": mcap,
                "alpaca_tradable": tradable,
            }
        )
    return pd.DataFrame(rows)


def load_candidate_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return standardize_candidate_frame(pd.read_csv(path, low_memory=False), str(path))


def scan_price_cache(price_cache: Path, max_files: int = 2000) -> pd.DataFrame:
    if not price_cache.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    files = list(price_cache.rglob("*.csv")) + list(price_cache.rglob("*.parquet"))
    for path in files[:max_files]:
        ticker = path.stem.upper().replace("_prices", "")
        try:
            frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)
        except Exception:
            continue
        if frame.empty:
            continue
        price_col = first_col(frame, ["adj_close", "adjusted_close", "close", "price"])
        volume_col = first_col(frame, ["volume", "vol"])
        if not price_col:
            continue
        tail = frame.tail(20)
        price = safe_float(tail[price_col].dropna().iloc[-1]) if not tail[price_col].dropna().empty else None
        volume = safe_float(tail[volume_col].dropna().mean()) if volume_col and not tail[volume_col].dropna().empty else None
        dollar_volume = price * volume if price is not None and volume is not None else None
        rows.append(
            {
                "ticker": ticker,
                "source": str(path),
                "exchange": "",
                "is_adr": None,
                "last_price": price,
                "avg_volume_20d": volume,
                "avg_dollar_volume_20d": dollar_volume,
                "market_cap": None,
                "alpaca_tradable": None,
            }
        )
    return pd.DataFrame(rows)


def score_candidates(
    candidates: pd.DataFrame,
    existing: set[str],
    *,
    min_price: float,
    min_dollar_volume: float,
    min_market_cap: float,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "candidate_status",
                "review_reason",
                "exchange",
                "is_adr",
                "last_price",
                "avg_dollar_volume_20d",
                "market_cap",
                "alpaca_tradable",
                "source",
            ]
        )
    rows: list[dict[str, Any]] = []
    for _, row in candidates.drop_duplicates("ticker").iterrows():
        ticker = str(row.get("ticker") or "").upper()
        price = safe_float(row.get("last_price"))
        dollar_volume = safe_float(row.get("avg_dollar_volume_20d"))
        market_cap = safe_float(row.get("market_cap"))
        tradable = row.get("alpaca_tradable")
        exchange = str(row.get("exchange") or "").upper()
        reasons: list[str] = []
        if ticker in existing:
            status = "already_listed"
            reasons.append("already_in_adr_universe")
        else:
            if price is None or price < min_price:
                reasons.append("price_below_floor_or_missing")
            if dollar_volume is None or dollar_volume < min_dollar_volume:
                reasons.append("liquidity_below_floor_or_missing")
            if market_cap is None:
                reasons.append("market_cap_missing")
            elif market_cap < min_market_cap:
                reasons.append("market_cap_below_floor")
            if tradable is not True:
                reasons.append("alpaca_tradability_missing_or_false")
            if exchange and exchange not in {"NYSE", "NASDAQ", "NYSEARCA", "NYSEMKT"}:
                reasons.append("non_nyse_nasdaq_exchange")
            status = "review_add" if not reasons else "review_watch"
        out = row.to_dict()
        out["candidate_status"] = status
        out["review_reason"] = ";".join(reasons) if reasons else "passes_price_liquidity_mcap_tradability"
        rows.append(out)
    return pd.DataFrame(rows).sort_values(["candidate_status", "avg_dollar_volume_20d", "ticker"], ascending=[True, False, True])


def render_markdown(review: pd.DataFrame, summary: dict[str, Any]) -> str:
    lines = [
        "# ADR Candidate Review",
        "",
        "- This artifact is review-only and does not edit adr_universe.yaml.",
        f"- generated_at_utc: `{summary['generated_at_utc']}`",
        f"- candidates: `{summary['candidate_count']}`",
        f"- review_add: `{summary['review_add_count']}`",
        "",
        "| Ticker | Status | Reason | Price | Dollar Volume | Market Cap | Exchange | Tradable |",
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for _, row in review.head(100).iterrows():
        lines.append(
            "| {ticker} | {status} | {reason} | {price} | {dvol} | {mcap} | {exchange} | {tradable} |".format(
                ticker=row.get("ticker"),
                status=row.get("candidate_status"),
                reason=row.get("review_reason"),
                price="" if pd.isna(row.get("last_price")) else f"{float(row.get('last_price')):.2f}",
                dvol="" if pd.isna(row.get("avg_dollar_volume_20d")) else f"{float(row.get('avg_dollar_volume_20d')):,.0f}",
                mcap="" if pd.isna(row.get("market_cap")) else f"{float(row.get('market_cap')):,.0f}",
                exchange=row.get("exchange") or "",
                tradable=row.get("alpaca_tradable"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def yaml_scalar(value: Any) -> str:
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def proposed_adr_records(review: pd.DataFrame) -> list[dict[str, Any]]:
    if review.empty or "candidate_status" not in review.columns:
        return []
    additions = review.loc[review["candidate_status"].astype(str).eq("review_add")].copy()
    if additions.empty:
        return []
    if "avg_dollar_volume_20d" in additions.columns:
        additions["_sort_dollar_volume"] = pd.to_numeric(additions["avg_dollar_volume_20d"], errors="coerce").fillna(0.0)
        additions = additions.sort_values(["_sort_dollar_volume", "ticker"], ascending=[False, True])
    records: list[dict[str, Any]] = []
    for _, row in additions.iterrows():
        market_cap = safe_float(row.get("market_cap"))
        mcap_usd_b = round(market_cap / 1_000_000_000.0, 3) if market_cap is not None else None
        ticker = str(row.get("ticker") or "").upper().strip()
        entry = {
            "ticker": ticker,
            "name": "",
            "country": "",
            "sector": "ADR_REVIEW_REQUIRED",
            "sub_sector": "",
            "mcap_usd_b": mcap_usd_b,
            "listed_since": "",
            "themes": [],
            "notes": "Candidate generated by run_adr_candidate_scanner.py; verify ADR/ADS status, country, sector, listing date, mcap, and liquidity before merging.",
        }
        records.append(
            {
                "ticker": ticker,
                "candidate_status": row.get("candidate_status"),
                "review_reason": row.get("review_reason"),
                "exchange": row.get("exchange"),
                "last_price": safe_float(row.get("last_price")),
                "avg_dollar_volume_20d": safe_float(row.get("avg_dollar_volume_20d")),
                "market_cap": market_cap,
                "alpaca_tradable": bool(row.get("alpaca_tradable")) if row.get("alpaca_tradable") is not None else None,
                "source": row.get("source"),
                "proposed_entry": entry,
            }
        )
    return records


def render_yaml_additions(records: list[dict[str, Any]]) -> str:
    lines = [
        "# Review-only ADR additions generated by tools/run_adr_candidate_scanner.py.",
        "# Do not paste blindly. Verify each name's ADR/ADS listing, country, sector,",
        "# listing date, market cap, liquidity, and Alpaca tradability before merging.",
        "adr_universe:",
    ]
    if not records:
        lines.append("  []")
        return "\n".join(lines) + "\n"
    for record in records:
        entry = record["proposed_entry"]
        lines.extend(
            [
                f"  - ticker: {entry['ticker']}",
                f"    name: {yaml_scalar(entry.get('name'))}",
                f"    country: {yaml_scalar(entry.get('country'))}",
                f"    sector: {yaml_scalar(entry.get('sector'))}",
                f"    sub_sector: {yaml_scalar(entry.get('sub_sector'))}",
                f"    mcap_usd_b: {entry.get('mcap_usd_b') if entry.get('mcap_usd_b') is not None else 'null'}",
                f"    listed_since: {yaml_scalar(entry.get('listed_since'))}",
                "    themes: []",
                f"    notes: {yaml_scalar(entry.get('notes'))}",
            ]
        )
    return "\n".join(lines) + "\n"


def write_update_manifest(output_dir: Path, review: pd.DataFrame, summary: dict[str, Any]) -> dict[str, str]:
    records = proposed_adr_records(review)
    manifest = {
        "schema_version": "adr-universe-update-manifest-v1",
        "generated_at_utc": summary["generated_at_utc"],
        "production_mutation_allowed": False,
        "manual_review_required": True,
        "target_file": summary["adr_universe_path"],
        "proposed_add_count": len(records),
        "proposed_additions": records,
        "review_steps": [
            "Confirm each ticker is a NYSE/NASDAQ ADR, ADS, or foreign ordinary share, not OTC.",
            "Fill name, country, sector, sub_sector, listed_since, and themes before editing adr_universe.yaml.",
            "Run ADR scanner and ADR data checks again after applying a reviewed YAML change.",
        ],
    }
    manifest_path = output_dir / "adr_universe_update_manifest.json"
    yaml_path = output_dir / "adr_universe_additions.yaml"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    yaml_path.write_text(render_yaml_additions(records), encoding="utf-8")
    return {
        "update_manifest_path": str(manifest_path),
        "yaml_additions_path": str(yaml_path),
        "proposed_add_count": str(len(records)),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = read_existing_symbols(repo_path(args.adr_universe))
    frames: list[pd.DataFrame] = []
    if args.candidate_csv:
        frames.append(load_candidate_csv(repo_path(args.candidate_csv)))
    if args.scan_price_cache:
        frames.append(scan_price_cache(repo_path(args.price_cache), max_files=args.max_files))
    candidates = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
    review = score_candidates(
        candidates,
        existing,
        min_price=float(args.min_price),
        min_dollar_volume=float(args.min_dollar_volume),
        min_market_cap=float(args.min_market_cap),
    )
    summary = {
        "schema_version": "adr-candidate-scanner-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "production_mutation_allowed": False,
        "adr_universe_path": str(repo_path(args.adr_universe)),
        "existing_adr_count": len(existing),
        "candidate_count": int(len(review)),
        "review_add_count": int((review.get("candidate_status") == "review_add").sum()) if not review.empty else 0,
        "thresholds": {
            "min_price": float(args.min_price),
            "min_dollar_volume": float(args.min_dollar_volume),
            "min_market_cap": float(args.min_market_cap),
        },
    }
    review.to_csv(output_dir / "adr_candidate_review.csv", index=False)
    manifest_paths = write_update_manifest(output_dir, review, summary)
    summary.update(
        {
            "manual_review_required": True,
            "proposed_add_count": int(manifest_paths["proposed_add_count"]),
            "update_manifest_path": manifest_paths["update_manifest_path"],
            "yaml_additions_path": manifest_paths["yaml_additions_path"],
        }
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "adr_candidate_review.md").write_text(render_markdown(review, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--adr-universe", default="adr_universe.yaml")
    parser.add_argument("--candidate-csv", default="")
    parser.add_argument("--output-dir", default="outputs/adr_candidates")
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-dollar-volume", type=float, default=5_000_000.0)
    parser.add_argument("--min-market-cap", type=float, default=1_000_000_000.0)
    parser.add_argument("--scan-price-cache", action="store_true")
    parser.add_argument("--max-files", type=int, default=2000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    run(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
