#!/usr/bin/env python3
"""Regime-conditioned capacity filter for operating target books.

Iteration 3 of the overnight attribution loop. Iter 2 (SPY 200ma macro
circuit breaker) was infrastructure-blocked in Tier-2: SPY price series
was not present in the Tier-2 cache, so the filter never executed and
no macro_circuit_broker_replay metrics were produced. Iter 3 pivots to
the SAME hypothesis (cut exposure in confirmed bearish regimes) but
uses the regime_state label already embedded in the operating book.
That label is PIT-computed by the engine and shipped in every row of
operating_*_target_book.csv, so no external SPY data is required.

Coverage check on the latest run (2026-05-12):
    Main operating book regime distribution across 84 monthly dates:
      neutral 42  bull 23  bear 16  deep_bear 1  strong_bull 1  unknown 1
    Bear + deep_bear = 17/84 (20.2%) — exactly the months in which the
    headline MaxDDs lived. 2020-02 bear, 2020-03 deep_bear, 2020-04
    bear, 2022 Apr-Dec all bear.

Default multipliers (winners-safe by construction — the indicator is
the engine's own regime label, not per-stock price moves; NVDA/SMCI/MU
single-name shakeouts do NOT shift the engine's regime label):

    exceptional_bull  1.0
    strong_bull       1.0
    bull              1.0
    neutral           1.0   (Iter 1 lesson: don't touch neutral; it was
                             fragile to mechanical filters)
    bear              0.5
    deep_bear         0.25
    <unknown / missing> 1.0

Outputs (parallel to existing operating books):
    outputs/reports/operating_<kind>_target_book_regime_capacity_filtered.csv
    outputs/regime_capacity_filter/<kind>/diagnostics.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CASH_TICKERS = {"CASH", "__CASH__"}
DEFAULT_REGIME_MULTIPLIERS = {
    "exceptional_bull": 1.0,
    "strong_bull": 1.0,
    "bull": 1.0,
    "neutral": 1.0,
    "bear": 0.5,
    "deep_bear": 0.25,
    "unknown": 1.0,
}


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def dominant_regime(values: pd.Series) -> str:
    if values is None or values.empty:
        return "unknown"
    s = values.dropna().astype(str).str.strip().str.lower()
    s = s[s != ""]
    if s.empty:
        return "unknown"
    mode = s.mode()
    if mode.empty:
        return "unknown"
    return str(mode.iloc[0])


def apply_filter(
    book: pd.DataFrame,
    *,
    multipliers: dict[str, float] = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    mult = multipliers if multipliers is not None else DEFAULT_REGIME_MULTIPLIERS
    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns:
        return book, []
    if "regime_state" not in book.columns:
        return book, [{"rebalance_date": None, "regime": "no_regime_column", "multiplier": 1.0, "rows_affected": 0}]
    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    decisions: list[dict[str, Any]] = []
    for date in sorted(out["rebalance_date"].unique()):
        date_mask = out["rebalance_date"] == date
        regime_label = dominant_regime(out.loc[date_mask, "regime_state"])
        factor = float(mult.get(regime_label, 1.0))
        if factor >= 1.0 - 1e-12:
            decisions.append({
                "rebalance_date": pd.Timestamp(date).date().isoformat(),
                "regime": regime_label,
                "multiplier": 1.0,
                "rows_affected": 0,
            })
            continue
        stock_mask = date_mask & (~out["ticker"].isin(CASH_TICKERS))
        rows_affected = int(stock_mask.sum())
        out.loc[stock_mask, "weight"] = out.loc[stock_mask, "weight"] * factor
        decisions.append({
            "rebalance_date": pd.Timestamp(date).date().isoformat(),
            "regime": regime_label,
            "multiplier": factor,
            "rows_affected": rows_affected,
        })
    return out, decisions


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    multipliers: dict[str, float] = None,
) -> dict[str, Any]:
    mult = multipliers if multipliers is not None else DEFAULT_REGIME_MULTIPLIERS
    if not input_book.exists():
        payload = {
            "status": "blocked",
            "reason": f"input book not found: {input_book}",
            "input_book": str(input_book),
        }
        write_json(diagnostics_path, payload)
        return payload
    book = pd.read_csv(input_book, low_memory=False)
    if book.empty:
        payload = {"status": "blocked", "reason": "empty input book", "input_book": str(input_book)}
        write_json(diagnostics_path, payload)
        return payload
    filtered, decisions = apply_filter(book, multipliers=mult)
    out_for_csv = filtered.copy()
    if "rebalance_date" in out_for_csv.columns:
        out_for_csv["rebalance_date"] = pd.to_datetime(out_for_csv["rebalance_date"], errors="coerce").dt.date.astype(str)
    output_book.parent.mkdir(parents=True, exist_ok=True)
    out_for_csv.to_csv(output_book, index=False)
    by_regime: dict[str, dict[str, Any]] = {}
    n_dampened = 0
    n_total = len(decisions)
    weight_dropped = float(
        book["weight"].astype(float).sum() - filtered["weight"].astype(float).sum()
    )
    for d in decisions:
        regime = str(d.get("regime") or "unknown")
        rec = by_regime.setdefault(regime, {"dates": 0, "multiplier": d.get("multiplier"), "rows_affected": 0})
        rec["dates"] += 1
        rec["rows_affected"] += int(d.get("rows_affected") or 0)
        rec["multiplier"] = d.get("multiplier")
        if float(d.get("multiplier") or 1.0) < 1.0:
            n_dampened += 1
    payload = {
        "status": "completed",
        "schema_version": "regime-capacity-filter-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_book": str(input_book),
        "output_book": str(output_book),
        "multipliers": {k: float(v) for k, v in mult.items()},
        "rebalance_dates_total": n_total,
        "rebalance_dates_dampened": n_dampened,
        "dampened_share": float(n_dampened / n_total) if n_total else 0.0,
        "weight_dropped_total": weight_dropped,
        "by_regime": by_regime,
        "decisions_sample": decisions[:40],
        "research_only": True,
        "production_activation_allowed": False,
    }
    write_json(diagnostics_path, payload)
    return payload


def parse_multipliers_arg(text: str) -> dict[str, float]:
    """Parse a string like 'bear=0.5,deep_bear=0.25' into a dict.
    Unknown regimes default to 1.0 via fallback.
    """
    mult: dict[str, float] = dict(DEFAULT_REGIME_MULTIPLIERS)
    if not text:
        return mult
    for pair in text.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        try:
            mult[key.strip().lower()] = float(val.strip())
        except ValueError:
            continue
    return mult


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-book", required=True)
    parser.add_argument("--output-book", required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument(
        "--multipliers",
        default="",
        help="Comma-separated regime=factor overrides, e.g. 'bear=0.5,deep_bear=0.25'. Unspecified regimes default to 1.0.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    multipliers = parse_multipliers_arg(args.multipliers)
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        multipliers=multipliers,
    )
    print(json.dumps({k: v for k, v in payload.items() if k != "decisions_sample"}, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
