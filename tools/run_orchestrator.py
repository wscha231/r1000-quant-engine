#!/usr/bin/env python3
"""run_orchestrator - Phase 19a CLI for portfolio orchestrator.

Pulls the most recent per-mandate weight outputs and composes a unified target
dict via r1000_orchestrator.compose_unified_portfolio. Useful for manual
inspection between rebalances.

Usage
-----
    python tools/run_orchestrator.py
    python tools/run_orchestrator.py --regime bull
    python tools/run_orchestrator.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from r1000_orchestrator import (   # noqa: E402
    compose_unified_portfolio,
    audit_unified_portfolio,
    write_orchestrator_output,
)


def _try_load_csv_or_parquet(path: Path):
    if not path.exists():
        return None
    try:
        import pandas as pd
        if path.suffix == ".parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return None


def load_main_weights(override: Optional[str]) -> dict:
    """Latest rebalance row -> {ticker: weight} dict."""
    candidates = [override] if override else [
        "outputs/holdings_history.parquet",
        "cloud_results/full/holdings_history.parquet",
        "outputs/trade_journal/holdings_history.parquet",
    ]
    for p in candidates:
        if not p:
            continue
        path = REPO_ROOT / p if not Path(p).is_absolute() else Path(p)
        df = _try_load_csv_or_parquet(path)
        if df is None or df.empty:
            continue
        if "rebalance_date" not in df.columns or "ticker" not in df.columns:
            continue
        import pandas as pd
        df["rebalance_date"] = pd.to_datetime(df["rebalance_date"], errors="coerce")
        latest = df["rebalance_date"].max()
        snap = df[df["rebalance_date"] == latest]
        if snap.empty:
            continue
        weight_col = "weight" if "weight" in snap.columns else None
        if weight_col is None:
            continue
        out = {}
        for _, row in snap.iterrows():
            t = str(row["ticker"]).strip().upper()
            if not t:
                continue
            try:
                out[t] = float(row[weight_col])
            except (TypeError, ValueError):
                continue
        if out:
            print(f"[orchestrator] main loaded from {path} ({len(out)} tickers, asof {latest.date()})")
            return out
    return {}


def load_concentrated_weights(override: Optional[str]) -> dict:
    candidates = [override] if override else [
        "outputs/reports/concentrated_strategy_holdings.csv",
        "outputs/concentrated_holdings.csv",
        "cloud_results/full/reports/concentrated_strategy_holdings.csv",
    ]
    for p in candidates:
        if not p:
            continue
        path = REPO_ROOT / p if not Path(p).is_absolute() else Path(p)
        df = _try_load_csv_or_parquet(path)
        if df is None or df.empty:
            continue
        # Schema may vary; look for ticker + weight cols
        ticker_col = next((c for c in df.columns if c.lower() in ("ticker", "symbol")), None)
        weight_col = next((c for c in df.columns if c.lower() in ("weight", "weight_pct", "target_weight")), None)
        if not ticker_col or not weight_col:
            continue
        # If there's a date column, take latest
        date_col = next((c for c in df.columns if c.lower() in ("rebalance_date", "date", "asof")), None)
        if date_col:
            import pandas as pd
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            latest = df[date_col].max()
            df = df[df[date_col] == latest]
        out = {}
        for _, row in df.iterrows():
            t = str(row[ticker_col]).strip().upper()
            if not t:
                continue
            try:
                out[t] = float(row[weight_col])
            except (TypeError, ValueError):
                continue
        if out:
            print(f"[orchestrator] concentrated loaded from {path} ({len(out)} tickers)")
            return out
    return {}


def load_tactical_weights(override: Optional[str]) -> dict:
    """Tactical: take last week's holdings list, equal-weight."""
    if override:
        path = Path(override)
        df = _try_load_csv_or_parquet(path)
        if df is not None and "holdings" in df.columns:
            last = df.iloc[-1]
            try:
                tickers = json.loads(str(last["holdings"]))
                return {str(t).upper(): 1.0 / len(tickers) for t in tickers if t}
            except Exception:
                return {}
    candidates = [
        "outputs/tactical_backtest/weekly_returns.parquet",
        "outputs/tactical_backtest/weekly_returns.csv",
        "cloud_results/full/tactical_backtest/weekly_returns.parquet",
    ]
    for p in candidates:
        path = REPO_ROOT / p
        df = _try_load_csv_or_parquet(path)
        if df is None or df.empty or "holdings" not in df.columns:
            continue
        last = df.iloc[-1]
        try:
            tickers = json.loads(str(last["holdings"]))
            if tickers:
                eq = 1.0 / len(tickers)
                out = {str(t).upper(): eq for t in tickers if t}
                print(f"[orchestrator] tactical loaded from {path} ({len(out)} tickers)")
                return out
        except Exception:
            continue
    return {}


def load_regime_state(override: Optional[str]) -> str:
    """A manual override is an unverified research choice, never A4/A5 authority.

    Only the current producer report is eligible for automatic inspection.
    An absent or blocked report cannot be replaced by an old cache or neutral.
    """
    if override:
        return str(override)
    from tools.macro_daily_snapshot import clock, current_snapshot_reasons
    path = REPO_ROOT / "cloud_results/macro_daily/latest.json"
    try:
        snapshot = clock.decode(clock.bounded(path, limit=128*1024))
        # Also refuse numeric overflow (e.g. 1e999) in any JSON member.
        json.dumps(snapshot, allow_nan=False)
        if type(snapshot) is dict and any(key in snapshot for key in
                ("status", "input_status", "state", "market_regime")):
            raise ValueError("REGIME_INPUT_STATUS_CONFLICT")
        reasons = current_snapshot_reasons(snapshot, decision=clock.trusted_now())
    except (OSError, clock.Blocked, ValueError, TypeError, RecursionError, OverflowError):
        raise ValueError("REGIME_INPUT_UNAVAILABLE_OR_INVALID") from None
    if reasons:
        raise ValueError("REGIME_INPUT_BLOCKED: "+",".join(reasons))
    return snapshot["regime_state"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regime", default=None, help="unverified manual research override; no A4/A5/order authority")
    p.add_argument("--main-csv", default=None)
    p.add_argument("--concentrated-csv", default=None)
    p.add_argument("--tactical-csv", default=None)
    p.add_argument("--out-dir", default=str(REPO_ROOT / "outputs" / "orchestrator"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    try:
        regime = load_regime_state(args.regime)
    except ValueError as exc:
        # No portfolio composition/output on explicit failed upstream data.
        # This CLI is inspection-only and this does not authorize orders.
        print(f"[orchestrator] BLOCKED: {exc}")
        return 2
    main_w = load_main_weights(args.main_csv)
    conc_w = load_concentrated_weights(args.concentrated_csv)
    tact_w = load_tactical_weights(args.tactical_csv)

    print(f"[orchestrator] regime: {regime}")
    print(f"[orchestrator] inputs: main={len(main_w)}  conc={len(conc_w)}  tact={len(tact_w)}")

    if not (main_w or conc_w or tact_w):
        print("[orchestrator] WARN: all per-mandate inputs empty -- result will be 100% cash")

    result = compose_unified_portfolio(
        main_weights=main_w,
        concentrated_weights=conc_w,
        tactical_weights=tact_w,
        regime_state=regime,
    )
    result["regime_input"] = dict(
        mode="MANUAL_UNVERIFIED" if args.regime else "AUTOMATIC_RESEARCH_PROXY",
        authority="RESEARCH_ONLY", source_authenticated=False,
        historical_pit_certified=False, portfolio_mutation_allowed=False,
        orders_allowed=False, production_activation_allowed=False)
    audit = audit_unified_portfolio(result)

    print()
    print(f"[orchestrator] capacity per mandate: {result['by_mandate_capacity']}")
    print(f"[orchestrator] n_unique_tickers:     {result['audit']['n_unique_tickers']}")
    print(f"[orchestrator] n_conflicts:          {len(result['conflicts'])}")
    print(f"[orchestrator] invested_total:       {audit['invested_amount']:.4f}")
    print(f"[orchestrator] cash_target:          {result['cash_target']:.4f}")
    print(f"[orchestrator] audit all_passed:     {audit['all_passed']}")

    if result['conflicts']:
        print()
        print("[orchestrator] conflicts:")
        for c in result['conflicts'][:10]:
            print(f"   {c['ticker']:>6}: {c['mandates']} -> max={c['max_weight_used']:.4f} ({c['winning_mandate']})")

    print()
    print("[orchestrator] top 10 unified weights:")
    for t, w in list(result["unified_weights"].items())[:10]:
        print(f"   {t:>6}  {w:.4f}")

    if args.dry_run:
        print()
        print("[orchestrator] --dry-run: no file write")
        return 0

    out_dir = Path(args.out_dir)
    asof = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_path = write_orchestrator_output(result, out_dir, asof_date=asof)
    print(f"[orchestrator] wrote {daily_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
