#!/usr/bin/env python3
"""Byte-exact verification for Refactor Phase A stages.

Compares current pipeline outputs against frozen Stage 0 reference copies
stored in this directory. Used after every stage commit (1..7) to confirm
the module split did not change any pipeline behaviour.

Usage
-----
    py -3 .refactor_baseline/verify.py

Exit codes
----------
    0 - all outputs byte-exact vs reference
    1 - one or more outputs diverged; see printed "FAIL" lines

Reference contents
------------------
    reference.json              SHA256 hashes + numeric snapshot of baseline
    scored_latest.ref.csv       Frozen scored_latest.csv from Stage 0
    portfolio_latest.ref.csv    Frozen portfolio_latest.csv
    weights_latest.ref.json     Frozen weights_latest.json
    backtest_metrics.ref.json   Frozen backtest_metrics.json (for numeric diff)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REF = Path(__file__).resolve().parent
REPO_ROOT = REF.parent
BASE_DEFAULT = Path(r"G:\내 드라이브\r1000_top30_institutional")
OUTPUTS = BASE_DEFAULT / "outputs"

if not OUTPUTS.exists():
    print(f"ERROR: outputs dir missing: {OUTPUTS}")
    print("       Run `py -3 run_local.py --no-collector` first to populate it.")
    sys.exit(2)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nums_equal(a, b, tol: float = 1e-10) -> bool:
    """Deep numeric equality with float tolerance."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_nums_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_nums_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        if a != a and b != b:  # both NaN
            return True
        return abs(a - b) < tol
    return a == b


def main() -> int:
    ok = True

    # SHA256 checks on byte-exact files
    for fname in ["scored_latest.csv", "portfolio_latest.csv", "weights_latest.json"]:
        cur_path = OUTPUTS / fname
        ref_path = REF / f"{Path(fname).stem}.ref{Path(fname).suffix}"
        if not cur_path.exists():
            print(f"  FAIL  {fname}: current file missing at {cur_path}")
            ok = False
            continue
        if not ref_path.exists():
            print(f"  FAIL  {fname}: reference missing at {ref_path}")
            ok = False
            continue
        cur_h = _sha256(cur_path)
        ref_h = _sha256(ref_path)
        match = cur_h == ref_h
        ok &= match
        tag = "OK  " if match else "FAIL"
        print(f"  {tag}  {fname}  cur={cur_h[:10]} ref={ref_h[:10]}  size_cur={cur_path.stat().st_size:,} size_ref={ref_path.stat().st_size:,}")

    # Numeric JSON diff
    cur_bm_path = OUTPUTS / "backtest_metrics.json"
    ref_bm_path = REF / "backtest_metrics.ref.json"
    if cur_bm_path.exists() and ref_bm_path.exists():
        cur_j = json.loads(cur_bm_path.read_text(encoding="utf-8"))
        ref_j = json.loads(ref_bm_path.read_text(encoding="utf-8"))
        match = _nums_equal(cur_j, ref_j)
        ok &= match
        tag = "OK  " if match else "FAIL"
        print(f"  {tag}  backtest_metrics.json (numeric, tol=1e-10)")
        if not match:
            # Show first 5 divergent keys for debugging
            divergent = []
            for k in sorted(set(cur_j.keys()) | set(ref_j.keys())):
                if k not in cur_j:
                    divergent.append(f"    + missing in ref: {k}")
                elif k not in ref_j:
                    divergent.append(f"    + missing in cur: {k}")
                elif not _nums_equal(cur_j[k], ref_j[k]):
                    divergent.append(f"    ~ diff {k}: cur={cur_j[k]!r} ref={ref_j[k]!r}")
                if len(divergent) >= 5:
                    break
            for line in divergent:
                print(line)
    else:
        print(f"  FAIL  backtest_metrics.json: files missing (cur_exists={cur_bm_path.exists()}, ref_exists={ref_bm_path.exists()})")
        ok = False

    print()
    print("VERDICT:", "BYTE-EXACT MATCH (ok to proceed)" if ok else "DIVERGENCE DETECTED (revert stage)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
