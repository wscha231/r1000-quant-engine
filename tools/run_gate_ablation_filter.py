#!/usr/bin/env python3
"""Gate-ablation filter for operating target books (research-only).

Every concentrated/main operating target book carries paired ``pre_<gate>_weight``
columns alongside the ``<gate>_status`` flags. When a gate fired, the engine
recorded the row's PRE-cut weight in ``pre_<gate>_weight`` and then overwrote
``weight`` with the smaller cut value. This filter REVERSES selected gate cuts:
for each restored gate, the row's weight is set to max(weight, pre_<gate>_weight).

Renormalization is per rebalance_date: after restoration the surviving non-cash
weight may exceed 1.0; we rebuild a single CASH row so total weight == 1.0. If
the post-restore stock weight already sums to >= 1.0, cash drops to 0 and the
stock vector is scaled proportionally to land exactly on 1.0.

Two reasons this is the right ablation primitive:
  1. It's PER-GATE, so each restored gate's CAGR-lift vs MDD-cost can be
     attributed in isolation by a single broker-replay vs the baseline.
  2. It uses the engine's OWN pre-cut record, so the counterfactual is exactly
     "what would broker-daily metrics have been WITHOUT this specific gate" —
     no approximation, no second model.

Special token ``ALL`` restores every column whose name starts with ``pre_`` and
ends with ``_weight`` — useful for the upper-bound "no regulation" replay.

Outputs:
    --output-book CSV with the same schema as input but adjusted weight + CASH
    --diagnostics JSON: which gates were restored, per-date stats, sum lifted

CLI mirrors the other overlay filters (run_neutral_regime_churn_filter,
run_macro_circuit_breaker_filter, run_regime_capacity_filter,
run_main_top_n_concentration_filter) so the gate-ablation study script can
chain calls with a uniform interface.
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
ALL_TOKEN = "ALL"


def repo_path(path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else REPO_ROOT / p


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def discover_pre_weight_cols(columns) -> list[str]:
    return sorted(c for c in columns if c.startswith("pre_") and c.endswith("_weight"))


def gate_name(pre_col: str) -> str:
    """Strip 'pre_' prefix and '_weight' suffix to recover the gate name."""
    return pre_col[len("pre_"):-len("_weight")]


def apply_gate_ablation(
    book: pd.DataFrame,
    *,
    restore_gates: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Restore the ``pre_<gate>_weight`` of each named gate, then renormalise.

    ``restore_gates`` is a list of gate names (i.e. names without the ``pre_``
    prefix and ``_weight`` suffix). The special name ``ALL`` restores every
    ``pre_*_weight`` column present.
    """
    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns or "ticker" not in book.columns:
        return book, {"reason": "missing required columns; no-op"}
    all_pre = discover_pre_weight_cols(book.columns)
    pre_by_gate = {gate_name(c): c for c in all_pre}
    if ALL_TOKEN in restore_gates:
        wanted_pre = all_pre
        restored = list(pre_by_gate)
    else:
        wanted_pre = [pre_by_gate[g] for g in restore_gates if g in pre_by_gate]
        restored = [g for g in restore_gates if g in pre_by_gate]
    missing = [g for g in restore_gates if g != ALL_TOKEN and g not in pre_by_gate]

    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)

    rows_lifted = 0
    total_lifted = 0.0
    if wanted_pre:
        # Row-wise restore: take max(current weight, all selected pre_weights).
        # Cash rows ignore the pre_ columns (they shouldn't have any anyway).
        is_stock = ~out["ticker"].isin(CASH_TICKERS)
        for pre_col in wanted_pre:
            pre = pd.to_numeric(out[pre_col], errors="coerce").fillna(0.0)
            lift_mask = is_stock & (pre > out["weight"] + 1e-12)
            lifted = (pre - out["weight"]).where(lift_mask, 0.0).clip(lower=0.0)
            rows_lifted += int(lift_mask.sum())
            total_lifted += float(lifted.sum())
            out.loc[lift_mask, "weight"] = pre.loc[lift_mask]

    # Per-date renormalisation: rebuild a single CASH row so weights sum to 1.
    kept: list[pd.DataFrame] = []
    per_date: list[dict[str, Any]] = []
    for date in sorted(out["rebalance_date"].unique()):
        sub = out.loc[out["rebalance_date"] == date].copy()
        is_cash = sub["ticker"].isin(CASH_TICKERS)
        stocks = sub.loc[~is_cash].copy()
        stock_w = float(stocks["weight"].sum())
        orig_cash = float(sub.loc[is_cash, "weight"].sum())
        if stock_w <= 1.0:
            cash_w = 1.0 - stock_w
        else:
            # Restored more than 100% — proportional scaledown, no cash.
            scale = 1.0 / stock_w if stock_w > 0 else 0.0
            stocks["weight"] = stocks["weight"] * scale
            stock_w = float(stocks["weight"].sum())
            cash_w = 0.0
        if not sub.empty:
            cash_row = sub.iloc[[0]].copy()
            cash_row["ticker"] = "CASH"
            cash_row["weight"] = cash_w
        else:
            cash_row = pd.DataFrame([{"rebalance_date": date, "ticker": "CASH", "weight": cash_w}])
        kept.append(pd.concat([stocks, cash_row], ignore_index=True))
        per_date.append({
            "rebalance_date": pd.Timestamp(date).date().isoformat(),
            "n_stocks": int(len(stocks)),
            "stock_weight_sum": round(stock_w, 6),
            "cash_weight": round(cash_w, 6),
            "orig_cash_weight": round(orig_cash, 6),
        })

    result = pd.concat(kept, ignore_index=True) if kept else out.iloc[0:0]
    diagnostics = {
        "restored_gates": restored,
        "restored_count": len(restored),
        "available_gates": list(pre_by_gate),
        "missing_gates": missing,
        "rows_lifted": int(rows_lifted),
        "total_weight_lifted": round(total_lifted, 4),
        "rebalance_dates": len(per_date),
        "per_date": per_date,
    }
    return result, diagnostics


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    restore_gates: list[str],
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
    filtered, diagnostics = apply_gate_ablation(book, restore_gates=restore_gates)
    output_book.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(output_book, index=False)
    payload = {
        "status": "completed",
        "input_book": str(input_book),
        "output_book": str(output_book),
        **diagnostics,
        # Drop per_date in the headline payload for readability; keep below.
    }
    headline = {k: v for k, v in payload.items() if k != "per_date"}
    full = {**payload}
    write_json(diagnostics_path, full)
    return headline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-book", required=True)
    p.add_argument("--output-book", required=True)
    p.add_argument("--diagnostics", required=True)
    p.add_argument(
        "--restore-gates",
        nargs="+",
        required=True,
        help=(
            "Gate names to restore (i.e. the part between 'pre_' and '_weight' "
            "in the column name). Use the special token 'ALL' to restore every "
            "pre_*_weight column found in the input book."
        ),
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        restore_gates=list(args.restore_gates),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
