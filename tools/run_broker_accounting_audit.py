#!/usr/bin/env python3
"""A1/A2 Broker Accounting Audit (CODEX_HANDOFF v3.5 Section 6, v3.6 §22)

Read-only forensic audit of two integrity gates the broker-ledger replay
ultimately depends on. NO production code is modified by this tool.

Gates:
  A1 delisted_cost_basis_fallback_eliminated
      For tickers that exit the historical R1000 universe (delisting
      candidates), do we still have prices in cache_prices around their
      exit window? If a ticker is in the universe at month T but vanishes
      by month T+1 AND we have no Close on its exit window, the broker
      replay must either (a) refuse to size the position or (b) use the
      last available close. Silent NaN -> zero is the bug A1 watches for.
  A2 survivorship_coverage_audited
      For every (ticker, rebalance_date) row in historical_universe_membership,
      do we actually have a price cache file with a close near that date?
      Coverage percent below 95% means the backtest universe silently
      shrunk to the survivors-only set.

Outputs:
  research/broker_accounting_audit.json   structured gate verdict
  research/broker_accounting_audit.md     human-readable summary

Both gates default to passed=None until enough membership rows are
inspected. After inspection, they flip to passed=True (>= threshold) or
passed=False (< threshold) with a concrete failing-row count.

Usage:
    py -3 tools/run_broker_accounting_audit.py
    py -3 tools/run_broker_accounting_audit.py --base-dir /alt/path
    py -3 tools/run_broker_accounting_audit.py --coverage-min 0.95

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 6 (A1/A2 fix track)
    research/final_integrated_engine_20260524/plan.md Section 9 (no auto-promotion
        until A1/A2 pass)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = Path("/content/drive/MyDrive/r1000_top30_institutional")

# Match r1000_helpers.px_cache_name (we re-implement here so the tool has
# zero coupling to the engine module).
def px_cache_name(ticker: str) -> str:
    return f"{hashlib.sha1(ticker.encode('utf-8')).hexdigest()[:16]}.parquet"


# ---------------------------------------------------------------------------
# Paths + membership loading
# ---------------------------------------------------------------------------


def discover_paths(base_dir: Optional[Path]) -> dict:
    candidates = [base_dir] if base_dir else []
    candidates += [DEFAULT_BASE, ROOT]
    base = None
    for cand in candidates:
        if cand is None or not cand.exists():
            continue
        cp = cand / "cache_prices"
        dr = cand / "data_raw"
        if cp.exists() or dr.exists():
            base = cand
            break
    if base is None:
        base = ROOT
    return {
        "base": base,
        "data_raw": base / "data_raw",
        "cache_prices": base / "cache_prices",
        "research": ROOT / "research",
    }


def membership_candidates(paths: dict) -> list[Path]:
    dr = paths["data_raw"]
    return [
        dr / "historical_universe_membership_auto.csv",
        dr / "historical_universe_membership.parquet",
        dr / "historical_universe_membership.csv",
        dr / "historical_universe_membership.xlsx",
    ]


def load_membership(paths: dict) -> pd.DataFrame:
    """Return normalised DataFrame with cols: ticker, rebalance_date, date_from, date_to.
    Empty DataFrame (with correct columns) if no file found."""
    for p in membership_candidates(paths):
        if not p.exists():
            continue
        try:
            if p.suffix == ".parquet":
                df = pd.read_parquet(p)
            elif p.suffix in (".csv",):
                df = pd.read_csv(p)
            elif p.suffix == ".xlsx":
                df = pd.read_excel(p)
            else:
                continue
        except Exception as exc:
            print(f"WARN: failed to read {p}: {exc}", file=sys.stderr)
            continue
        if "ticker" not in df.columns:
            continue
        out = df.copy()
        out["ticker"] = out["ticker"].astype(str).str.strip().str.upper()
        for c in ("rebalance_date", "date_from", "date_to"):
            if c in out.columns:
                out[c] = pd.to_datetime(out[c], errors="coerce")
            else:
                out[c] = pd.NaT
        return out[["ticker", "rebalance_date", "date_from", "date_to"]].dropna(
            subset=["ticker"]
        )
    return pd.DataFrame(columns=["ticker", "rebalance_date", "date_from", "date_to"])


# ---------------------------------------------------------------------------
# Price cache lookup (lightweight)
# ---------------------------------------------------------------------------


def has_close_near(
    paths: dict, ticker: str, target_date: pd.Timestamp, window_days: int = 7
) -> tuple[bool, Optional[pd.Timestamp]]:
    """Check if cache_prices has a row within +-window_days of target_date.

    Returns (found, observed_date). observed_date is the closest available
    timestamp (or None if not found).
    """
    cache = paths["cache_prices"]
    if not cache.exists():
        return False, None
    p = cache / px_cache_name(ticker)
    if not p.exists():
        return False, None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return False, None
    idx = pd.to_datetime(df.index, errors="coerce")
    idx = idx[~idx.isna()]
    if len(idx) == 0:
        return False, None
    delta = (idx - target_date).total_seconds().__abs__()
    # The above doesn't work directly; recompute properly
    diffs = pd.Series(idx).apply(lambda t: abs((t - target_date).days))
    if diffs.min() <= window_days:
        return True, idx[int(diffs.idxmin())]
    return False, idx[int(diffs.idxmin())]


# ---------------------------------------------------------------------------
# A2 -- Survivorship coverage audit
# ---------------------------------------------------------------------------


@dataclass
class A2Result:
    total_rows: int = 0
    covered_rows: int = 0
    coverage_pct: float = 0.0
    missing_examples: list[dict] = field(default_factory=list)
    per_year_coverage: dict = field(default_factory=dict)
    status: str = "no_data"
    passed: Optional[bool] = None


def audit_a2(
    paths: dict, membership: pd.DataFrame, sample_per_year: int = 200,
    coverage_min: float = 0.95
) -> A2Result:
    res = A2Result()
    if membership.empty:
        res.status = "no_membership_data"
        return res
    if not paths["cache_prices"].exists():
        res.status = "no_price_cache"
        return res
    # Filter rows with concrete rebalance_date (date_from/date_to-only rows
    # are harder to audit per-row; skip for now)
    rows = membership.dropna(subset=["rebalance_date"]).copy()
    if rows.empty:
        res.status = "no_dated_rows"
        return res
    # Sample by year to keep runtime bounded
    rows["year"] = rows["rebalance_date"].dt.year

    def _sample_grp(g):
        return g.sample(min(len(g), sample_per_year), random_state=42)

    try:
        sampled = rows.groupby("year", group_keys=False).apply(
            _sample_grp, include_groups=False
        )
        # include_groups=False drops the 'year' column; add it back from index
        if "year" not in sampled.columns:
            sampled = sampled.assign(year=sampled.index.map(
                lambda i: rows.loc[i, "year"] if i in rows.index else None
            ))
    except TypeError:
        # Older pandas without include_groups
        sampled = rows.groupby("year", group_keys=False).apply(_sample_grp)
    per_year = {}
    missing: list[dict] = []
    for year, grp in sampled.groupby("year"):
        cov = 0
        for r in grp.itertuples(index=False):
            found, observed = has_close_near(paths, r.ticker, r.rebalance_date)
            if found:
                cov += 1
            elif len(missing) < 30:
                missing.append(
                    {
                        "ticker": r.ticker,
                        "rebalance_date": r.rebalance_date.date().isoformat(),
                        "closest_available": observed.date().isoformat() if observed is not None else None,
                    }
                )
        per_year[int(year)] = {"sampled": int(len(grp)), "covered": int(cov),
                                "pct": round(cov / max(len(grp), 1), 4)}
        res.total_rows += int(len(grp))
        res.covered_rows += int(cov)
    res.coverage_pct = round(res.covered_rows / max(res.total_rows, 1), 4)
    res.missing_examples = missing
    res.per_year_coverage = per_year
    if res.total_rows == 0:
        res.status = "no_dated_rows"
    else:
        res.status = "audited"
        res.passed = bool(res.coverage_pct >= coverage_min)
    return res


# ---------------------------------------------------------------------------
# A1 -- Delisted cost basis fallback audit
# ---------------------------------------------------------------------------


@dataclass
class A1Result:
    delisted_candidates: int = 0
    with_exit_price: int = 0
    without_exit_price: int = 0
    examples: list[dict] = field(default_factory=list)
    status: str = "no_data"
    passed: Optional[bool] = None


def audit_a1(paths: dict, membership: pd.DataFrame, exit_threshold: float = 0.95) -> A1Result:
    """A1 = no silent NaN substitution for delisted tickers.

    Definition of "delisted candidate": ticker appears in early membership
    months but is absent from the LATEST membership month. We check whether
    cache_prices has a recent close for that ticker around the last month
    it was present.
    """
    res = A1Result()
    if membership.empty:
        res.status = "no_membership_data"
        return res
    if not paths["cache_prices"].exists():
        res.status = "no_price_cache"
        return res
    rows = membership.dropna(subset=["rebalance_date"]).copy()
    if rows.empty:
        res.status = "no_dated_rows"
        return res
    latest_date = rows["rebalance_date"].max()
    latest_tickers = set(
        rows.loc[rows["rebalance_date"] == latest_date, "ticker"].tolist()
    )
    # For every ticker NOT in the latest month, find its last appearance
    all_tickers = set(rows["ticker"].tolist())
    delisted = sorted(all_tickers - latest_tickers)
    res.delisted_candidates = len(delisted)
    if not delisted:
        res.status = "no_delisted_candidates"
        return res
    examples: list[dict] = []
    with_px = 0
    without_px = 0
    for t in delisted:
        last_date = rows.loc[rows["ticker"] == t, "rebalance_date"].max()
        found, observed = has_close_near(paths, t, last_date, window_days=14)
        if found:
            with_px += 1
            if len(examples) < 15:
                examples.append(
                    {
                        "ticker": t,
                        "last_membership_date": last_date.date().isoformat(),
                        "closest_close": observed.date().isoformat() if observed else None,
                        "status": "ok",
                    }
                )
        else:
            without_px += 1
            if len(examples) < 15:
                examples.append(
                    {
                        "ticker": t,
                        "last_membership_date": last_date.date().isoformat(),
                        "closest_close": observed.date().isoformat() if observed else None,
                        "status": "missing",
                    }
                )
    res.with_exit_price = with_px
    res.without_exit_price = without_px
    res.examples = examples
    res.status = "audited"
    pct = with_px / max(len(delisted), 1)
    res.passed = bool(pct >= exit_threshold)
    return res


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------


def build_audit_payload(a1: A1Result, a2: A2Result, paths: dict, args: argparse.Namespace) -> dict:
    return {
        "schema_version": "1.0",
        "audited_at": date.today().isoformat(),
        "base_dir": str(paths["base"]),
        "thresholds": {
            "a1_min_exit_price_coverage": args.exit_threshold,
            "a2_min_membership_coverage": args.coverage_min,
            "a2_sample_per_year": args.sample_per_year,
        },
        "gates": {
            "A1": {
                "name": "delisted_cost_basis_fallback_eliminated",
                "passed": a1.passed,
                "status": a1.status,
                "delisted_candidates": a1.delisted_candidates,
                "with_exit_price": a1.with_exit_price,
                "without_exit_price": a1.without_exit_price,
                "exit_price_coverage_pct": round(
                    a1.with_exit_price / max(a1.delisted_candidates, 1), 4
                )
                if a1.delisted_candidates
                else None,
                "examples": a1.examples,
            },
            "A2": {
                "name": "survivorship_coverage_audited",
                "passed": a2.passed,
                "status": a2.status,
                "total_rows": a2.total_rows,
                "covered_rows": a2.covered_rows,
                "coverage_pct": a2.coverage_pct,
                "per_year_coverage": a2.per_year_coverage,
                "missing_examples": a2.missing_examples,
            },
        },
    }


def render_markdown(payload: dict) -> str:
    lines: list[str] = []
    lines.append("# A1/A2 Broker Accounting Audit")
    lines.append("")
    lines.append(f"- Audited: **{payload['audited_at']}**")
    lines.append(f"- Base dir: `{payload['base_dir']}`")
    lines.append("")
    lines.append("## Gates")
    lines.append("")
    for key in ("A1", "A2"):
        g = payload["gates"][key]
        verdict = "**PASS**" if g["passed"] is True else (
            "**FAIL**" if g["passed"] is False else "_inconclusive_"
        )
        lines.append(f"### {key} -- {g['name']}")
        lines.append(f"- verdict: {verdict}")
        lines.append(f"- status: `{g['status']}`")
        if key == "A1":
            lines.append(
                f"- delisted candidates: {g['delisted_candidates']}, "
                f"with exit price: {g['with_exit_price']}, "
                f"without: {g['without_exit_price']}"
            )
            if g.get("exit_price_coverage_pct") is not None:
                lines.append(f"- coverage: {g['exit_price_coverage_pct']*100:.2f}%")
            if g.get("examples"):
                lines.append("")
                lines.append("Examples (first 15):")
                lines.append("| ticker | last_membership | closest_close | status |")
                lines.append("|---|---|---|---|")
                for ex in g["examples"]:
                    lines.append(
                        f"| {ex['ticker']} | {ex['last_membership_date']} | "
                        f"{ex.get('closest_close') or '-'} | {ex['status']} |"
                    )
        else:
            lines.append(
                f"- total sampled: {g['total_rows']}, covered: {g['covered_rows']}, "
                f"coverage: **{g['coverage_pct']*100:.2f}%**"
            )
            if g.get("per_year_coverage"):
                lines.append("")
                lines.append("Per-year coverage:")
                lines.append("| year | sampled | covered | pct |")
                lines.append("|---|---:|---:|---:|")
                for yr, v in sorted(g["per_year_coverage"].items()):
                    lines.append(f"| {yr} | {v['sampled']} | {v['covered']} | {v['pct']*100:.2f}% |")
            if g.get("missing_examples"):
                lines.append("")
                lines.append("Missing samples (first 30):")
                lines.append("| ticker | rebalance_date | closest_available |")
                lines.append("|---|---|---|")
                for ex in g["missing_examples"]:
                    lines.append(
                        f"| {ex['ticker']} | {ex['rebalance_date']} | "
                        f"{ex.get('closest_available') or '-'} |"
                    )
        lines.append("")
    lines.append("## Interpretation guide")
    lines.append("")
    lines.append(
        "- **A1 FAIL** means delisted tickers lack last-close prices in cache. "
        "Until fixed, the broker-ledger replay must either skip these positions "
        "or use a conservative fallback (last-known close, with a written log)."
    )
    lines.append(
        "- **A2 FAIL** below 95% means the historical universe is partially "
        "shrunk to survivors-only. CAGR/MDD numbers may be inflated by survivorship."
    )
    lines.append(
        "- **inconclusive** means data sources are missing (no membership file or "
        "empty price cache). Run the data collector first."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None)
    p.add_argument("--sample-per-year", type=int, default=200,
                   help="Max membership rows sampled per year for A2")
    p.add_argument("--coverage-min", type=float, default=0.95,
                   help="A2 pass threshold (default 0.95)")
    p.add_argument("--exit-threshold", type=float, default=0.95,
                   help="A1 pass threshold for delisted exit price coverage (default 0.95)")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    paths = discover_paths(Path(args.base_dir) if args.base_dir else None)
    membership = load_membership(paths)
    if not args.quiet:
        print(f"base_dir: {paths['base']}")
        print(f"membership_rows: {len(membership)}")
        print(f"cache_prices_exists: {paths['cache_prices'].exists()}")
    a2 = audit_a2(paths, membership, sample_per_year=args.sample_per_year,
                  coverage_min=args.coverage_min)
    a1 = audit_a1(paths, membership, exit_threshold=args.exit_threshold)
    payload = build_audit_payload(a1, a2, paths, args)
    out_dir = paths["research"]
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "broker_accounting_audit.json"
    md_path = out_dir / "broker_accounting_audit.md"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(render_markdown(payload))
    if not args.quiet:
        print(f"json:     {json_path.relative_to(ROOT)}")
        print(f"md:       {md_path.relative_to(ROOT)}")
        for key in ("A1", "A2"):
            g = payload["gates"][key]
            verdict = "PASS" if g["passed"] is True else (
                "FAIL" if g["passed"] is False else "INCONCLUSIVE"
            )
            print(f"  {key} {verdict}  ({g['status']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
