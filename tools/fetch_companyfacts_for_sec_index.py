#!/usr/bin/env python3
"""Fetch full Companyfacts JSON for exact CIKs present in an SEC index.

The collector is bounded, append-only and research-only. It does not score a
security, change a universe or portfolio, run a backtest/fullrun, or create an
order. A Companyfacts response is issuer-level evidence and must not be treated
as listing-specific evidence for a home-market/ADR pair.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def default_fetcher(url: str, user_agent: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def build(
    args: argparse.Namespace,
    *,
    fetcher: Callable[[str, str], bytes] = default_fetcher,
) -> dict[str, Any]:
    index_path = repo_path(args.sec_index)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    frame = pd.read_parquet(index_path) if index_path.suffix.lower() == ".parquet" else pd.read_csv(index_path)
    required = {"ticker", "cik10"}
    if not required.issubset(frame.columns):
        raise ValueError(f"SEC index missing columns: {sorted(required - set(frame.columns))}")
    ciks = sorted({str(value).split(".")[0].zfill(10) for value in frame["cik10"] if pd.notna(value)})
    if not ciks:
        raise ValueError("SEC index contains no CIKs")
    if len(ciks) > int(args.max_network_requests):
        raise RuntimeError("Companyfacts CIK count exceeds network request budget")
    user_agent = str(args.user_agent or os.environ.get("SEC_USER_AGENT") or "").strip()
    if not user_agent or "@" not in user_agent or "contact@example.com" in user_agent:
        raise ValueError("a real SEC research contact user-agent is required")

    output_dir.mkdir(parents=True)
    facts_dir = output_dir / "companyfacts"
    facts_dir.mkdir()
    files: list[dict[str, Any]] = []
    for cik in ciks:
        raw = fetcher(URL.format(cik10=cik), user_agent)
        payload = json.loads(raw.decode("utf-8"))
        returned = str(payload.get("cik") or "").zfill(10)
        if returned != cik:
            raise ValueError(f"Companyfacts CIK mismatch: {returned}!={cik}")
        path = facts_dir / f"CIK{cik}.json"
        path.write_bytes(raw)
        tickers = sorted(set(frame.loc[frame["cik10"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10).eq(cik), "ticker"].astype(str)))
        files.append({"cik10": cik, "tickers": tickers, "url": URL.format(cik10=cik), **fingerprint(path)})

    manifest = {
        "schema_version": "companyfacts-for-sec-index-v1",
        "status": "READY_RESEARCH_ONLY_COMPANYFACTS_HISTORY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "issuer_level_not_listing_specific": True,
        "pit_universe_label_clean": False,
        "source_index": fingerprint(index_path),
        "network_request_budget": int(args.max_network_requests),
        "network_requests_executed": len(files),
        "companyfacts_cik_count": len(files),
        "companyfacts_files": files,
        "fullrun_executed": False,
        "backtest_executed": False,
        "orders_generated": False,
        "universe_mutated": False,
        "portfolio_weights_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sec-index", required=True)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--max-network-requests", type=int, default=25)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(build(parse_args()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
