#!/usr/bin/env python3
"""Residual-cash redeploy filter for operating target books (research-only).

The production AlphaOps operating book leaves idle cash in NORMAL regimes for a
mechanical reason, not a policy one: when the few selected leaders cluster in
one sub-industry, the sub-industry cap (0.70 concentrated / 0.40 main) blocks
deployment, and the post-weighting cap cascade trims weight that is never
recycled. The engine's own cash_target is ~0 in growth/balanced, so this idle
cash is pure drag.

This filter recovers that drag WITHOUT touching crisis defense:

  * NORMAL dates (crisis_state in {GREEN, WATCH, "", NaN}): redeploy idle cash
    into the surviving non-cash names, proportional to current weight, up to
    each name's single-name / sub-industry / theme cap. Iterates until the
    residual is gone or no name has room. Rebuilds the CASH row.

  * DEFENSE dates (crisis_state in {DEFENSE, CRISIS, DEGRADED_DATA}): LEFT
    UNTOUCHED. The crisis governor raised that cash on purpose;
    redeploying it would defeat the preemptive MDD defense. This is the
    non-negotiable guard that keeps "minimal cash in normal times" from
    colliding with "raise cash before a crisis".

A ``--min-cash-floor`` (default 0.0) lets a normal-date book keep a small cash
reserve if desired. Caps are read per-row from the book's own
effective_single_weight_cap / subindustry_cap / theme_cap columns when present,
else fall back to portfolio-kind defaults (concentrated 0.30/0.70/1.0,
main 0.12/0.40/0.60).

Research-only: writes a new book + diagnostics; never mutates production code,
the source book, or live policy. Designed to be broker-replayed and, only if it
lifts broker-daily CAGR without harming crisis-window MDD, promoted into
run_alphaops_vnext_policy_replay.assign_weights.

CLI mirrors the other overlay filters so the overlay search / ablation runners
chain it with a uniform interface.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_crisis_policy import adapt_crisis_state  # noqa: E402

CASH_TICKERS = {"CASH", "__CASH__"}
# Any of these (case-insensitive) marks a date whose cash must NOT be redeployed.
DEFENSE_STATES = {"DEFENSE", "CRISIS", "DEGRADED_DATA"}

SUB_KEYS = ("leader_subindustry", "subindustry", "sub_industry", "industry_group", "industry", "sector")
THEME_KEYS = ("leader_broad_theme", "theme_phase_primary", "theme", "sector")

DEFAULT_CAPS = {
    "concentrated": {"single": 0.30, "subindustry": 0.70, "theme": 1.0},
    "main": {"single": 0.12, "subindustry": 0.40, "theme": 0.60},
}


def repo_path(path_like: str | Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else REPO_ROOT / p


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _first_key(row: pd.Series, keys: tuple[str, ...]) -> str:
    for k in keys:
        if k in row.index:
            v = row.get(k)
            if pd.notna(v) and str(v).strip():
                return str(v).strip().lower()
    return "unknown"


def _row_cap(row: pd.Series, col: str, default: float) -> float:
    if col in row.index and pd.notna(row.get(col)):
        try:
            v = float(row.get(col))
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return default


def is_defense_date(crisis_state: Any) -> bool:
    return adapt_crisis_state(crisis_state) in DEFENSE_STATES


def redeploy_date(
    sub: pd.DataFrame,
    *,
    portfolio_kind: str,
    min_cash_floor: float,
    max_iters: int = 12,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Redeploy idle cash for ONE rebalance date into surviving names up to caps."""
    caps_default = DEFAULT_CAPS.get(portfolio_kind, DEFAULT_CAPS["concentrated"])
    is_cash = sub["ticker"].isin(CASH_TICKERS)
    stocks = sub.loc[~is_cash].copy()
    orig_cash = float(sub.loc[is_cash, "weight"].sum())
    if stocks.empty:
        return sub, {"skipped": "no_stocks", "orig_cash": round(orig_cash, 6)}

    weights = {i: float(stocks.at[i, "weight"]) for i in stocks.index}
    # Per-name caps.
    single_cap = {i: _row_cap(stocks.loc[i], "effective_single_weight_cap", caps_default["single"]) for i in stocks.index}
    sub_cap = {i: _row_cap(stocks.loc[i], "subindustry_cap", caps_default["subindustry"]) for i in stocks.index}
    theme_cap = {i: _row_cap(stocks.loc[i], "theme_cap", caps_default["theme"]) for i in stocks.index}
    sub_key = {i: _first_key(stocks.loc[i], SUB_KEYS) for i in stocks.index}
    theme_key = {i: _first_key(stocks.loc[i], THEME_KEYS) for i in stocks.index}

    target_invested = max(0.0, 1.0 - max(0.0, min_cash_floor))

    for _ in range(max_iters):
        invested = sum(weights.values())
        residual = target_invested - invested
        if residual <= 1e-6:
            break
        # Live running totals — updated AS each name is filled so a shared
        # sub-industry / theme cap is never overshot within an iteration
        # (the bug a naive per-name room calc would hit when several names
        # share one capped sub-industry).
        sub_tot: dict[str, float] = {}
        theme_tot: dict[str, float] = {}
        for i in stocks.index:
            sub_tot[sub_key[i]] = sub_tot.get(sub_key[i], 0.0) + weights[i]
            theme_tot[theme_key[i]] = theme_tot.get(theme_key[i], 0.0) + weights[i]
        # Names with any headroom, richest-first so conviction names fill first.
        order = sorted(stocks.index, key=lambda i: -weights[i])
        moved = 0.0
        for i in order:
            if residual <= 1e-9:
                break
            room = min(
                single_cap[i] - weights[i],
                sub_cap[i] - sub_tot[sub_key[i]],
                theme_cap[i] - theme_tot[theme_key[i]],
            )
            if room <= 1e-9:
                continue
            add = min(room, residual)
            weights[i] += add
            sub_tot[sub_key[i]] += add
            theme_tot[theme_key[i]] += add
            residual -= add
            moved += add
        if moved <= 1e-9:
            break

    for i in stocks.index:
        stocks.at[i, "weight"] = weights[i]
        if "target_weight" in stocks.columns:
            stocks.at[i, "target_weight"] = weights[i]
    new_invested = float(sum(weights.values()))
    new_cash = max(0.0, 1.0 - new_invested)
    cash_row = sub.loc[is_cash].copy()
    if cash_row.empty:
        base = sub.iloc[[0]].copy()
        base["ticker"] = "CASH"
        cash_row = base
    cash_row = cash_row.iloc[[0]].copy()
    cash_row["ticker"] = "CASH"
    cash_row["weight"] = new_cash
    if "target_weight" in cash_row.columns:
        cash_row["target_weight"] = new_cash
    out = pd.concat([stocks, cash_row], ignore_index=True)
    diag = {
        "orig_cash": round(orig_cash, 6),
        "new_cash": round(new_cash, 6),
        "cash_redeployed": round(max(0.0, orig_cash - new_cash), 6),
        "n_stocks": int(len(stocks)),
    }
    return out, diag


def apply_redeploy(
    book: pd.DataFrame,
    *,
    portfolio_kind: str,
    min_cash_floor: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if book.empty or "rebalance_date" not in book.columns or "weight" not in book.columns or "ticker" not in book.columns:
        return book, {"reason": "missing required columns; no-op"}
    out = book.copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce")
    out = out.dropna(subset=["rebalance_date"])
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce").fillna(0.0)
    has_crisis = "crisis_state" in out.columns

    kept: list[pd.DataFrame] = []
    per_date: list[dict[str, Any]] = []
    normal_dates = 0
    defense_dates = 0
    total_redeployed = 0.0
    for date in sorted(out["rebalance_date"].unique()):
        sub = out.loc[out["rebalance_date"] == date].copy()
        crisis_state = sub["crisis_state"].iloc[0] if has_crisis and len(sub) else ""
        if is_defense_date(crisis_state):
            defense_dates += 1
            kept.append(sub)
            per_date.append({
                "rebalance_date": pd.Timestamp(date).date().isoformat(),
                "crisis_state": str(crisis_state),
                "action": "preserved_defense_cash",
            })
            continue
        normal_dates += 1
        redeployed, diag = redeploy_date(sub, portfolio_kind=portfolio_kind, min_cash_floor=min_cash_floor)
        kept.append(redeployed)
        total_redeployed += diag.get("cash_redeployed", 0.0)
        per_date.append({
            "rebalance_date": pd.Timestamp(date).date().isoformat(),
            "crisis_state": str(crisis_state),
            "action": "redeployed",
            **diag,
        })

    result = pd.concat(kept, ignore_index=True) if kept else out.iloc[0:0]
    diagnostics = {
        "portfolio_kind": portfolio_kind,
        "min_cash_floor": min_cash_floor,
        "rebalance_dates": len(per_date),
        "normal_dates_redeployed": normal_dates,
        "defense_dates_preserved": defense_dates,
        "total_cash_redeployed": round(total_redeployed, 4),
        "crisis_state_column_present": bool(has_crisis),
        "per_date": per_date,
    }
    return result, diagnostics


def run(
    *,
    input_book: Path,
    output_book: Path,
    diagnostics_path: Path,
    portfolio_kind: str,
    min_cash_floor: float,
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
    filtered, diagnostics = apply_redeploy(book, portfolio_kind=portfolio_kind, min_cash_floor=min_cash_floor)
    output_book.parent.mkdir(parents=True, exist_ok=True)
    filtered.to_csv(output_book, index=False)
    headline = {k: v for k, v in diagnostics.items() if k != "per_date"}
    payload = {"status": "completed", "input_book": str(input_book), "output_book": str(output_book), **headline}
    write_json(diagnostics_path, {"status": "completed", "input_book": str(input_book), "output_book": str(output_book), **diagnostics})
    return payload


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-book", required=True)
    p.add_argument("--output-book", required=True)
    p.add_argument("--diagnostics", required=True)
    p.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="concentrated")
    p.add_argument("--min-cash-floor", type=float, default=0.0,
                   help="Minimum cash to retain on NORMAL dates (default 0.0 = fully invested).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = run(
        input_book=repo_path(args.input_book),
        output_book=repo_path(args.output_book),
        diagnostics_path=repo_path(args.diagnostics),
        portfolio_kind=args.portfolio_kind,
        min_cash_floor=float(args.min_cash_floor),
    )
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
