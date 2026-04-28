#!/usr/bin/env python3
"""refresh_companyfacts_bulk — download SEC companyfacts.zip bulk archive.

Why this exists
---------------
The pipeline reads `<base_dir>/companyfacts.zip` as the bulk source for SEC
fundamentals. If the zip is missing or stale, every R1000 ticker silently
falls back to the per-CIK API path; with `companyfacts_refresh_days` cached
(or `--no-collector` set in the cloud workflow), per-CIK calls are skipped
too — and the entire fundamentals lane goes stale, taking the acceptance
gate (`fundamental_coverage_ok`) and `portfolio_latest.csv` with it.

This script downloads the bulk archive directly and atomically replaces
the on-disk file. It is safe to call from CI (no credentials, no Drive
mount).

Usage
-----
    python tools/refresh_companyfacts_bulk.py \\
        --base-dir "$(pwd)/outputs" \\
        --max-age-days 7 \\
        --required

Exits 0 on success / fresh-cache-skip, 1 on download/validation failure
(non-required mode degrades to warning).

Bulk archive endpoint: https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

SEC_BULK_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
DEFAULT_USER_AGENT = (
    "R1000InstitutionalBot (contact: andrewcha231@gmail.com)"
)
MIN_VALID_BYTES = 50 * 1024 * 1024  # 50MB floor — real archive is ~1GB+


def file_age_days(path: Path) -> float:
    if not path.exists():
        return float("inf")
    mtime = path.stat().st_mtime
    return (time.time() - mtime) / 86400.0


def download_with_retry(url: str, dest: Path, user_agent: str, retries: int = 4) -> None:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": user_agent,
                    "Accept-Encoding": "gzip, deflate",
                    "Host": "www.sec.gov",
                },
            )
            tmp = dest.with_suffix(dest.suffix + ".part")
            print(f"  attempt {attempt}/{retries}: GET {url}", flush=True)
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=600) as resp:
                with open(tmp, "wb") as out:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
            elapsed = time.time() - t0
            size_mb = tmp.stat().st_size / (1024 * 1024)
            print(f"  downloaded {size_mb:.1f} MB in {elapsed:.1f}s", flush=True)

            if tmp.stat().st_size < MIN_VALID_BYTES:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"download too small ({tmp.stat().st_size} bytes < {MIN_VALID_BYTES})"
                )
            with zipfile.ZipFile(tmp) as zf:
                bad = zf.testzip()
                if bad:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(f"zip integrity failed at member: {bad}")
                member_count = len(zf.namelist())
            if member_count < 1000:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"zip member count too low: {member_count}")

            tmp.replace(dest)
            print(f"  OK -> {dest} ({size_mb:.1f} MB, {member_count} members)", flush=True)
            return
        except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, zipfile.BadZipFile) as exc:
            last_err = str(exc)
            print(f"  attempt {attempt} failed: {last_err}", flush=True)
            if attempt < retries:
                wait_s = 2 ** attempt
                print(f"  retrying in {wait_s}s ...", flush=True)
                time.sleep(wait_s)
    raise RuntimeError(f"download failed after {retries} attempts: {last_err}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-dir", default=".", help="directory containing (or to receive) companyfacts.zip")
    p.add_argument("--max-age-days", type=float, default=7.0,
                   help="skip download if existing zip newer than this (default 7 = weekly)")
    p.add_argument("--required", action="store_true",
                   help="exit 1 on any failure (default: warn-only)")
    p.add_argument("--user-agent", default=os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT))
    p.add_argument("--url", default=SEC_BULK_URL)
    p.add_argument("--retries", type=int, default=4)
    args = p.parse_args()

    base = Path(args.base_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    dest = base / "companyfacts.zip"

    age = file_age_days(dest)
    print(f"[refresh_companyfacts_bulk] target: {dest}", flush=True)
    print(f"[refresh_companyfacts_bulk] age:    {age:.2f} days", flush=True)
    print(f"[refresh_companyfacts_bulk] threshold: {args.max_age_days} days", flush=True)

    if age <= args.max_age_days:
        print(f"[refresh_companyfacts_bulk] FRESH — skip download", flush=True)
        return 0

    print(f"[refresh_companyfacts_bulk] STALE — downloading from {args.url}", flush=True)
    try:
        download_with_retry(args.url, dest, args.user_agent, retries=args.retries)
    except Exception as exc:
        msg = f"[refresh_companyfacts_bulk] FAILED: {exc}"
        print(msg, flush=True, file=sys.stderr)
        if args.required:
            return 1
        print("[refresh_companyfacts_bulk] (continuing — --required not set)", flush=True)
        return 0

    print(f"[refresh_companyfacts_bulk] DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
