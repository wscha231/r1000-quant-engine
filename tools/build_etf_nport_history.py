#!/usr/bin/env python3
"""Build a historical PIT series of ETF holdings from SEC Form N-PORT filings.

ROOT CAUSE THIS FIXES: run_etf_holdings_refresh.py stamps every holding with
``available_from = <run date>``. In a historical replay, _etf_snapshot_asof()
keeps only holdings with available_from <= rebalance_date, so a single
today-stamped snapshot matches NO past rebalance date -> ETF coverage 0% across
the entire backtest. The ETF lane's alpha was structurally dead.

FIX: ETFs file Form N-PORT (NPORT-P) with the SEC. Each filing carries a full
holdings list as of a reporting-period end, and EDGAR records the *accepted*
timestamp when it became public (~60 days after period end). Stamping each
holding with available_from = SEC accepted timestamp gives a true point-in-time
holdings series going back years with no lookahead.

This module separates a pure, unit-tested PARSER (parse_nport_holdings) from the
network layer (resolve_ticker_cik / fetch_nport_filings), so the
correctness-critical XML + PIT logic is fully testable offline. Output:
data_pit/etf_holdings/etf_holdings_nport_history.parquet with the same schema
run_etf_holdings_refresh.py emits, so it concatenates cleanly.

Research-only shadow evidence. Network calls hit data.sec.gov with a contact
User-Agent per SEC fair-access policy.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

try:
    import requests  # noqa: F401
except Exception:  # pragma: no cover - requests always present in CI
    requests = None  # type: ignore

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
SEC_BASE = "https://data.sec.gov"
SEC_WWW = "https://www.sec.gov"
DEFAULT_UNIVERSE = "research/etf_holdings_universe_20260520/thematic_etfs.yaml"
DEFAULT_OUTPUT = "data_pit/etf_holdings/etf_holdings_nport_history.parquet"

OUTPUT_COLUMNS = [
    "etf_ticker", "etf_label", "theme", "holding_ticker", "holding_name",
    "holding_weight", "source", "as_of_date", "available_from",
]


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def _strip_ns(tag: str) -> str:
    """Drop an XML namespace prefix: '{ns}name' -> 'name'."""
    return tag.split("}", 1)[1] if "}" in tag else tag


def _find_first(elem: ET.Element, name: str) -> Optional[ET.Element]:
    for child in elem.iter():
        if _strip_ns(child.tag) == name:
            return child
    return None


def _text(elem: Optional[ET.Element]) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _to_weight(pct_text: str) -> float:
    """N-PORT pctVal is already a percentage of net assets (e.g. 7.34 = 7.34%)."""
    try:
        v = float(str(pct_text).replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    # Normalise to fraction in [0,1] to match run_etf_holdings_refresh weights.
    return max(0.0, v / 100.0 if abs(v) > 1.0 else v)


def parse_nport_holdings(
    xml_text: str,
    *,
    spec: dict[str, Any],
    accepted_ts: str,
    max_holdings: int = 200,
) -> pd.DataFrame:
    """Parse one N-PORT primary_doc.xml into normalised holding rows.

    available_from is the SEC accepted timestamp (PIT-correct public
    availability), NOT the reporting-period end. as_of_date is the
    reporting-period end (repPdEnd) when present, for provenance only.
    """
    if not xml_text or not xml_text.strip():
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # NOTE: a childless ElementTree Element is falsy, so `a or b` would silently
    # drop a valid <repPdEnd> that has only text. Use explicit `is not None`.
    rep_pd_end = ""
    gen = _find_first(root, "repPdEnd")
    if gen is None:
        gen = _find_first(root, "repPdDate")
    if gen is not None:
        rep_pd_end = _text(gen)

    rows: list[dict[str, Any]] = []
    for sec in root.iter():
        if _strip_ns(sec.tag) != "invstOrSec":
            continue
        name = ""
        ticker = ""
        pct = ""
        for child in sec:
            tag = _strip_ns(child.tag)
            if tag == "name" and not name:
                name = _text(child)
            elif tag == "pctVal":
                pct = _text(child)
            elif tag == "identifiers":
                # ticker can appear as <ticker value="AAPL"/>; fall back to none.
                for ident in child.iter():
                    itag = _strip_ns(ident.tag)
                    if itag == "ticker":
                        val = (ident.get("value") or _text(ident)).strip()
                        if val and val.upper() not in {"N/A", "NA", "NONE"}:
                            ticker = val
        ticker = ticker.upper().strip()
        if not ticker:
            continue
        rows.append({
            "holding_ticker": ticker,
            "holding_name": name,
            "holding_weight": _to_weight(pct),
        })

    if not rows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    out = pd.DataFrame(rows)
    # Collapse duplicate identifiers within one filing (multiple lots).
    out = (
        out.groupby("holding_ticker", as_index=False)
        .agg({"holding_name": "first", "holding_weight": "sum"})
        .sort_values("holding_weight", ascending=False)
        .head(int(max_holdings))
    )
    out["etf_ticker"] = spec["etf_ticker"]
    out["etf_label"] = spec["etf_label"]
    out["theme"] = spec["theme"]
    out["source"] = "sec_nport"
    out["as_of_date"] = rep_pd_end
    out["available_from"] = accepted_ts
    return out[OUTPUT_COLUMNS].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Network layer (isolated; not exercised by the offline smoke test).
# --------------------------------------------------------------------------- #

def _session(user_agent: str):  # pragma: no cover - network
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return s


def load_ticker_cik_map(session, *, user_agent: str) -> dict[str, str]:  # pragma: no cover - network
    """ticker (upper) -> zero-padded 10-digit CIK from SEC's public mapping."""
    resp = session.get(f"{SEC_WWW}/files/company_tickers.json", timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    out: dict[str, str] = {}
    for row in payload.values():
        t = str(row.get("ticker", "")).upper().strip()
        cik = str(row.get("cik_str", "")).strip()
        if t and cik:
            out[t] = cik.zfill(10)
    return out


def fetch_nport_filings(  # pragma: no cover - network
    session, cik: str, *, max_filings: int, throttle_s: float = 0.2,
) -> list[dict[str, str]]:
    """Return [{accepted, report_date, primary_doc_url}] for NPORT-P filings."""
    resp = session.get(f"{SEC_BASE}/submissions/CIK{cik}.json", timeout=30)
    resp.raise_for_status()
    recent = resp.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accepted = recent.get("acceptanceDateTime", [])
    report_dates = recent.get("reportDate", [])
    accession = recent.get("accessionNumber", [])
    primary = recent.get("primaryDocument", [])
    out: list[dict[str, str]] = []
    for i, form in enumerate(forms):
        if not str(form).upper().startswith("NPORT-P"):
            continue
        acc = accession[i].replace("-", "") if i < len(accession) else ""
        doc = primary[i] if i < len(primary) else "primary_doc.xml"
        url = f"{SEC_WWW}/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
        out.append({
            "accepted": accepted[i] if i < len(accepted) else "",
            "report_date": report_dates[i] if i < len(report_dates) else "",
            "primary_doc_url": url,
        })
        if len(out) >= max_filings:
            break
        time.sleep(throttle_s)
    return out


def build_history(  # pragma: no cover - network
    specs: list[dict[str, Any]],
    *,
    user_agent: str,
    max_filings_per_etf: int,
    max_holdings: int,
) -> pd.DataFrame:
    session = _session(user_agent)
    cik_map = load_ticker_cik_map(session, user_agent=user_agent)
    frames: list[pd.DataFrame] = []
    for spec in specs:
        cik = cik_map.get(spec["etf_ticker"])
        if not cik:
            print(f"[nport] no CIK for {spec['etf_ticker']}; skipping")
            continue
        try:
            filings = fetch_nport_filings(session, cik, max_filings=max_filings_per_etf)
        except Exception as exc:
            print(f"[nport] {spec['etf_ticker']} filing list failed: {exc!r}")
            continue
        for f in filings:
            try:
                doc = session.get(f["primary_doc_url"], timeout=30)
                doc.raise_for_status()
                parsed = parse_nport_holdings(
                    doc.text, spec=spec, accepted_ts=f["accepted"], max_holdings=max_holdings
                )
                if not parsed.empty:
                    frames.append(parsed)
                time.sleep(0.2)
            except Exception as exc:
                print(f"[nport] {spec['etf_ticker']} doc {f['primary_doc_url']} failed: {exc!r}")
        print(f"[nport] {spec['etf_ticker']} cik={cik} filings={len(filings)}")
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def load_universe(path: Path) -> list[dict[str, Any]]:
    if yaml is None or not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = payload.get("etfs", []) if isinstance(payload, dict) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        out.append({
            "etf_ticker": ticker,
            "etf_label": str(row.get("label") or ticker).strip(),
            "theme": str(row.get("theme") or "unknown").strip(),
        })
    return out


def merge_with_existing(history: pd.DataFrame, existing_path: Path) -> pd.DataFrame:
    """Concatenate N-PORT history with any existing holdings file, dedup on the
    PIT key (etf_ticker, holding_ticker, available_from)."""
    if existing_path.exists():
        try:
            existing = pd.read_parquet(existing_path)
        except Exception:
            existing = pd.DataFrame(columns=OUTPUT_COLUMNS)
    else:
        existing = pd.DataFrame(columns=OUTPUT_COLUMNS)
    combined = pd.concat([existing, history], ignore_index=True) if not existing.empty else history
    if combined.empty:
        return combined
    for col in OUTPUT_COLUMNS:
        if col not in combined.columns:
            combined[col] = "" if col not in {"holding_weight"} else 0.0
    combined = combined.drop_duplicates(["etf_ticker", "holding_ticker", "available_from"], keep="last")
    return combined[OUTPUT_COLUMNS].reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--merge-into", default="data_pit/etf_holdings/etf_holdings.parquet",
                   help="Also write the union of N-PORT history + this file back to it (PIT-dedup).")
    p.add_argument("--user-agent", default="R1000QuantEngine research andrewcha231@gmail.com")
    p.add_argument("--max-filings-per-etf", type=int, default=24, help="~6 years of quarterly N-PORT.")
    p.add_argument("--max-holdings", type=int, default=200)
    p.add_argument("--offline", action="store_true", help="Skip network; only re-merge existing files.")
    return p.parse_args()


def main() -> int:  # pragma: no cover - orchestration
    args = parse_args()
    specs = load_universe(repo_path(args.universe))
    out_path = repo_path(args.output)
    print(f"[nport] universe etfs={len(specs)}  offline={args.offline}")

    if args.offline:
        history = pd.read_parquet(out_path) if out_path.exists() else pd.DataFrame(columns=OUTPUT_COLUMNS)
    else:
        history = build_history(
            specs,
            user_agent=args.user_agent,
            max_filings_per_etf=args.max_filings_per_etf,
            max_holdings=args.max_holdings,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        history.to_parquet(out_path, index=False)

    print(f"[nport] history rows={len(history)}  etfs={history['etf_ticker'].nunique() if not history.empty else 0}")
    if not history.empty:
        af = pd.to_datetime(history["available_from"], errors="coerce", utc=True)
        print(f"[nport] available_from range: {af.min()} .. {af.max()}")

    if args.merge_into and not history.empty:
        merge_path = repo_path(args.merge_into)
        merged = merge_with_existing(history, merge_path)
        merge_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(merge_path, index=False)
        print(f"[nport] merged into {merge_path}  total_rows={len(merged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
