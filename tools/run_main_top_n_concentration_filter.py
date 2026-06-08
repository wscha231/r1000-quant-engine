#!/usr/bin/env python3
"""Main top-N concentration filter for operating target books (research-only).

Post-hoc reshape of the monthly main target book: at every rebalance date,
keep only the top-N non-cash rows by weight, drop the rest, then rebuild a
single ``CASH`` row so total weight sums to 1.0. The rest of the row columns
on surviving names are preserved so downstream broker-replay reads correctly.

This is a fast-replay overlay, NOT a portfolio-construction change. It does
not retrain models, does not re-select tickers, does not change the
``rebalance_date``/``ticker`` columns of the survivors. It is the cheapest
honest way to answer "what if the main book were narrower?" against the
official broker-daily metric without burning a full rebuild.

Outputs (parallel to existing operating books):
    outputs/reports/operating_main_target_book_top<N>.csv
    outputs/main_top_n_filter/<kind>/diagnostics.json

CLI mirrors the other overlay filters (run_neutral_regime_churn_filter,
run_regime_capacity_filter) so run_overlay_combination_search can chain it
exactly the same way.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CASH_TICKERS = {"CASH", "__CASH__"}


def repo_path(path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else REPO_ROOT / p


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def apply_top_n(
    book: pd.DataFrame,
    *,
    top_n: int,
    keep_cash_floor: bool,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Per rebalance_date: keep top-N non-cash rows by weight, drop the rest.

    Build a single CASH row whose weight = 1 - sum(survivor weights). If
    ``keep_cash_floor`` is True and the original book had a CASH row, the
    larger of (original cash, residual) is used so we never lower the cash
    target below what the engine already prescribed.
    """
    if top_n <= 0:
        return book, [{"reason": "top_n<=0 — passthrough"}]
    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns or "ticker" not in book.columns:
        return book, [{"reason": "missing required columns — passthrough"}]
    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)

    kept: list[pd.DataFrame] = []
    decisions: list[dict[str, Any]] = []
    for date in sorted(out["rebalance_date"].unique()):
        sub = out.loc[out["rebalance_date"] == date].copy()
        is_cash = sub["ticker"].isin(CASH_TICKERS)
        orig_cash_weight = float(sub.loc[is_cash, "weight"].sum())
        stocks = sub.loc[~is_cash].sort_values("weight", ascending=False)
        kept_stocks = stocks.head(top_n).copy()
        n_input_stocks = int(len(stocks))
        n_kept = int(len(kept_stocks))
        survivor_w = float(kept_stocks["weight"].sum())
        residual_cash = max(0.0, 1.0 - survivor_w)
        cash_weight = max(residual_cash, orig_cash_weight) if keep_cash_floor else residual_cash
        # Rescale stocks if the cash floor would otherwise push total > 1.0
        if survivor_w + cash_weight > 1.0 + 1e-9:
            scale = max(0.0, 1.0 - cash_weight) / survivor_w if survivor_w > 0 else 0.0
            kept_stocks["weight"] = kept_stocks["weight"] * scale
            survivor_w = float(kept_stocks["weight"].sum())
            cash_weight = max(0.0, 1.0 - survivor_w)
        # Build CASH row by copying any source row (preserve columns) then
        # overwriting ticker + weight. Fall back to a dict if sub is empty.
        if not sub.empty:
            cash_row = sub.iloc[[0]].copy()
            cash_row["ticker"] = "CASH"
            cash_row["weight"] = cash_weight
        else:
            cash_row = pd.DataFrame([{"rebalance_date": date, "ticker": "CASH", "weight": cash_weight}])
        kept.append(pd.concat([kept_stocks, cash_row], ignore_index=True))
        decisions.append({
            "rebalance_date": pd.Timestamp(date).date().isoformat(),
            "input_stocks": n_input_stocks,
            "kept_stocks": n_kept,
            "dropped_stocks": n_input_stocks - n_kept,
            "survivor_weight": round(survivor_w, 6),
            "cash_weight": round(cash_weight, 6),
            "orig_cash_weight": round(orig_cash_weight, 6),
        })
    if not kept:
        return out.iloc[0:0], decisions
    result = pd.concat(kept, ignore_index=True)
    return result, decisions


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    top_n: int,
    keep_cash_floor: bool,
) -> dict[str, Any]:
    if not input_book.exists():
        payload = {"status": "blocked", "reason": f"input book not found: {input_book}", "input_book": str(input_book)}
        write_json(diagnostics_path, payload)
        return payload
    book = pd.read_csv(input_book, low_memory=False)
    if book.empty:
        payload = {"status": "blocked", "reason": "empty input book", "input_book": str(input_book)}
        write_json(diagnostics_path, payload)
        return payload
    filtered, decisions = apply_top_n(book, top_n=top_n, keep_cash_floor=keep_cash_floor)
    output_book.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(output_book, index=False)
    payload = {
        "status": "completed",
        "input_book": str(input_book),
        "output_book": str(output_book),
        "top_n": int(top_n),
        "keep_cash_floor": bool(keep_cash_floor),
        "rebalance_dates": len(decisions),
        "total_kept_rows": int((filtered["ticker"] != "CASH").sum()) if not filtered.empty else 0,
        "total_dropped_stocks": int(sum(d.get("dropped_stocks", 0) for d in decisions)),
        "avg_cash_weight": (
            float(filtered.loc[filtered["ticker"] == "CASH", "weight"].mean())
            if not filtered.empty else None
        ),
        "decisions": decisions,
    }
    write_json(diagnostics_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-book", required=True)
    p.add_argument("--output-book", required=True)
    p.add_argument("--diagnostics", required=True)
    p.add_argument("--top-n", type=int, required=True,
                   help="Max number of non-cash stocks per rebalance_date (e.g. 6, 8, 10).")
    p.add_argument("--keep-cash-floor", action="store_true",
                   help="If set, never lower cash below the engine's original cash_weight for that date.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        top_n=int(args.top_n),
        keep_cash_floor=bool(args.keep_cash_floor),
    )
    print(json.dumps({k: v for k, v in payload.items() if k != "decisions"}, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
