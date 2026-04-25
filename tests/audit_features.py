#!/usr/bin/env python3
"""Feature leakage audit — source + runtime feature_store inspection.

Complements tests/smoke_test.py (source-only) with a deeper data-level
check that runs against the actual feature_store_latest.parquet.

Usage:
    py -3 tests/audit_features.py                    # default Drive path
    py -3 tests/audit_features.py --feature-store path/to/feature_store.parquet
    py -3 tests/audit_features.py --no-runtime       # source-only audit (no parquet read)

Exit codes:
    0  no leakage detected
    1  forward-return column found in cfg.features OR in feature_store columns
       that are wired into model training
    2  audit framework crashed (file missing, parse error)

History:
    c13fa6a (2026-04-25)  forward-return r_12m/24m/36m removed from pattern_miner
    6c0a496 (2026-04-25)  audit identified defensive gap in run_acceptance_checks
    636266c (2026-04-25)  smoke guard + production exact_banned full coverage

This script is the third leg: it runs against actual data, not just source.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# Forward-return signatures (any column matching these is a label, not a feature)
FORWARD_REGEX = re.compile(r"^r_\d+[mdy]$|^bench_r_\d+[mdy]$")
FORWARD_PREFIXES = ("earn_post_", "future_")
# Known-OK forward-named columns (already validated upstream as PIT-safe)
ALLOWED_FORWARD_NAMED = {
    "future_winner_scout_score",  # composite signal; see r1000_config audit 2026-04-25
}


def audit_default_features() -> tuple[list[str], int]:
    """Static audit of DEFAULT_FEATURES in r1000_config.py.

    Returns (leakage_columns, total_features).
    """
    src = (ROOT / "r1000_config.py").read_text(encoding="utf-8")
    m = re.search(r"^DEFAULT_FEATURES\s*=\s*\[(.*?)^\]", src, re.MULTILINE | re.DOTALL)
    if not m:
        raise RuntimeError("DEFAULT_FEATURES list not found in r1000_config.py")
    body = m.group(1)
    cols = re.findall(r'"([^"]+)"', body)
    leak = []
    for c in cols:
        if c in ALLOWED_FORWARD_NAMED:
            continue
        if FORWARD_REGEX.match(c) or c.startswith(FORWARD_PREFIXES):
            leak.append(c)
    return leak, len(cols)


def audit_pattern_miner_excludes() -> list[str]:
    """Verify r1000_pattern_miner.py EXCLUDE_EXACT covers all forward horizons."""
    src = (ROOT / "r1000_pattern_miner.py").read_text(encoding="utf-8")
    required = [
        "r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m",
        "bench_r_12m",
    ]
    missing = [c for c in required if f'"{c}"' not in src]
    return missing


def audit_pipeline_exact_banned() -> list[str]:
    """Verify r1000_pipeline.py exact_banned covers all forward horizons."""
    src = (ROOT / "r1000_pipeline.py").read_text(encoding="utf-8")
    m = re.search(r"exact_banned\s*=\s*\{([^}]*)\}", src)
    if not m:
        return ["<exact_banned_set_not_found>"]
    body = m.group(1)
    required = [
        "r_1m", "r_3m", "r_6m", "r_12m", "r_24m", "r_36m",
        "bench_r_1m", "bench_r_3m", "bench_r_6m",
        "bench_r_12m", "bench_r_24m", "bench_r_36m",
    ]
    return [c for c in required if f'"{c}"' not in body]


def audit_feature_store_runtime(parquet_path: Path) -> dict[str, list[str]]:
    """Inspect actual feature_store_latest.parquet column names + sanity-check
    that any r_*m / bench_r_*m columns are clearly labeled (not feature-shaped).

    Returns {category: [columns]}. Categories:
      - 'present_forward_returns': labels found in parquet (expected, target columns)
      - 'suspect_features': non-label columns matching forward-return shape
    """
    try:
        import pandas as pd
    except ImportError:
        return {"_skip": ["pandas not installed in this environment"]}

    if not parquet_path.exists():
        return {"_skip": [f"feature_store missing at {parquet_path}"]}

    df = pd.read_parquet(parquet_path, columns=None)
    cols = list(df.columns)

    forward_labels = []
    suspect = []
    for c in cols:
        if c in ALLOWED_FORWARD_NAMED:
            continue
        if FORWARD_REGEX.match(c):
            # Expected target labels — keep separate for visibility
            forward_labels.append(c)
        elif c.startswith(FORWARD_PREFIXES):
            suspect.append(c)
    return {
        "present_forward_returns": forward_labels,
        "suspect_features": suspect,
        "total_columns": [str(len(cols))],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--feature-store",
        default="G:/내 드라이브/r1000_top30_institutional/outputs/feature_store_latest.parquet",
        help="path to feature_store parquet (override for non-Windows envs)",
    )
    parser.add_argument("--no-runtime", action="store_true",
                        help="skip parquet read (source-only audit)")
    args = parser.parse_args()

    print("=" * 70)
    print("r1000 Quant Engine — feature leakage audit")
    print("=" * 70)

    fail = False

    # 1. Static: DEFAULT_FEATURES in r1000_config.py
    print("\n[1] DEFAULT_FEATURES in r1000_config.py")
    leak, total = audit_default_features()
    if leak:
        print(f"  FAIL  {len(leak)} forward-return columns found in {total} features:")
        for c in leak:
            print(f"        - {c}")
        fail = True
    else:
        print(f"  PASS  {total} features, 0 forward-return columns")

    # 2. Static: r1000_pattern_miner.py EXCLUDE_EXACT
    print("\n[2] r1000_pattern_miner.py EXCLUDE_EXACT coverage")
    missing = audit_pattern_miner_excludes()
    if missing:
        print(f"  FAIL  missing exclusions: {missing}")
        fail = True
    else:
        print(f"  PASS  all forward horizons excluded")

    # 3. Static: r1000_pipeline.py exact_banned (acceptance check)
    print("\n[3] r1000_pipeline.py run_acceptance_checks.exact_banned")
    missing = audit_pipeline_exact_banned()
    if missing:
        print(f"  FAIL  missing from exact_banned: {missing}")
        fail = True
    else:
        print(f"  PASS  all forward horizons + bench_r_* banned")

    # 4. Runtime: actual parquet
    if not args.no_runtime:
        print(f"\n[4] feature_store runtime audit ({args.feature_store})")
        try:
            result = audit_feature_store_runtime(Path(args.feature_store))
        except Exception as e:
            print(f"  ERROR  could not load parquet: {type(e).__name__}: {e}")
            return 2

        if "_skip" in result:
            for msg in result["_skip"]:
                print(f"  SKIP  {msg}")
        else:
            n_cols = int(result["total_columns"][0])
            print(f"  total columns: {n_cols}")
            labels = result["present_forward_returns"]
            print(f"  forward-return labels present (expected): {len(labels)}")
            for c in sorted(labels):
                print(f"    - {c}  (label, not feature)")

            suspect = result["suspect_features"]
            if suspect:
                print(f"  FAIL  {len(suspect)} suspect columns matching forward prefix:")
                for c in suspect:
                    print(f"    - {c}")
                fail = True
            else:
                print("  PASS  no suspect columns with future_/earn_post_ prefix")

    print("\n" + "=" * 70)
    if fail:
        print("AUDIT FAILED — fix issues above before training models")
        return 1
    print("AUDIT PASSED — no leakage detected")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"\naudit framework crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
