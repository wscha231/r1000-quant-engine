#!/usr/bin/env python3
"""Phase E7 -- Crisis Governor Counterfactual Replay (CODEX_HANDOFF v3.6 §17.8)

Counterfactual: would the CAGR-preserving crisis governor (E5+E6) have
reduced MDD on the historical equity curve without sacrificing total CAGR?

The replay is conservative -- it only adjusts the CASH allocation per period,
re-scaling net returns by the new equity exposure. It does NOT model
winner-hold vs broken-trim swap quality (that requires holdings detail and
belongs in Phase F + Phase G integrated challenger).

Inputs (all auto-discovered, tool exits cleanly when absent):
  outputs/equity_curve.csv                          (existing pipeline output)
  outputs/crisis_signals/daily_features.parquet     (Phase E2)
  outputs/crisis_signals/daily_classification.csv   (Phase E3, optional)
  outputs/reports/concentrated_strategy_monthly.csv (concentrated counterfactual)

Outputs:
  outputs/crisis_governor_replay/main_with_governor.csv
  outputs/crisis_governor_replay/concentrated_with_governor.csv     (if data)
  outputs/crisis_governor_replay/stress_window_metrics.csv
  outputs/crisis_governor_replay/replay_audit.json

Stress windows (CODEX_HANDOFF v3.6 §17.8):
  2020-02-01 to 2020-05-31      (COVID shock)
  2021-11-01 to 2022-12-31      (rate hike slow bear)
  2024-01-01 to 2024-12-31      (recent year sanity)
  2025-01-01 to (latest)        (live forward walk)

Usage:
    py -3 tools/run_crisis_governor_replay.py
    py -3 tools/run_crisis_governor_replay.py --base-dir /alt/path

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md §17.8 (Phase E7)
    research/final_integrated_engine_20260524/plan.md §2 E7
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = Path("/content/drive/MyDrive/r1000_top30_institutional")

# Reuse pure governor module
sys.path.insert(0, str(ROOT))
from r1000_crisis_governor import (
    crisis_zone,
    evaluate_exposure_target,
    reentry_exposure_multiplier,
    compute_reentry_score,
)


STRESS_WINDOWS = [
    ("covid_shock_2020",  "2020-02-01", "2020-05-31"),
    ("rate_hike_2022",    "2021-11-01", "2022-12-31"),
    ("recent_year_2024",  "2024-01-01", "2024-12-31"),
    ("live_walk_2025",    "2025-01-01", None),
]


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


@dataclass
class ReplayInputs:
    base_dir: Path
    main_equity: Optional[Path] = None
    concentrated_monthly: Optional[Path] = None
    crisis_features: Optional[Path] = None
    crisis_classification: Optional[Path] = None


def discover_inputs(base_dir: Optional[Path]) -> ReplayInputs:
    candidates = [base_dir] if base_dir else []
    candidates += [DEFAULT_BASE, ROOT]
    chosen = None
    for cand in candidates:
        if cand is None or not cand.exists():
            continue
        out = cand / "outputs"
        if out.exists():
            chosen = cand
            break
    if chosen is None:
        chosen = ROOT
    out = chosen / "outputs"
    inp = ReplayInputs(base_dir=chosen)
    if (out / "equity_curve.csv").exists():
        inp.main_equity = out / "equity_curve.csv"
    if (out / "broker_ledger_replay" / "main_equity_curve.csv").exists():
        # Prefer broker-ledger when available
        inp.main_equity = out / "broker_ledger_replay" / "main_equity_curve.csv"
    if (out / "reports" / "concentrated_strategy_monthly.csv").exists():
        inp.concentrated_monthly = out / "reports" / "concentrated_strategy_monthly.csv"
    if (out / "crisis_signals" / "daily_features.parquet").exists():
        inp.crisis_features = out / "crisis_signals" / "daily_features.parquet"
    if (out / "crisis_signals" / "daily_classification.csv").exists():
        inp.crisis_classification = out / "crisis_signals" / "daily_classification.csv"
    return inp


# ---------------------------------------------------------------------------
# Counterfactual replay
# ---------------------------------------------------------------------------


def _resample_features_to_dates(
    features: pd.DataFrame, dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """For each date in `dates`, take the most-recent feature row at or before
    that date (PIT discipline). Returns frame aligned to `dates`."""
    if features.empty:
        return pd.DataFrame(index=dates)
    feats = features.copy()
    feats.index = pd.to_datetime(feats.index, errors="coerce")
    feats = feats[~feats.index.isna()].sort_index()
    out = feats.reindex(feats.index.union(dates)).ffill().reindex(dates)
    return out


def compute_governed_curve(
    equity_curve: pd.DataFrame,
    features: pd.DataFrame,
    date_col: str,
    return_col: str,
    cash_col: Optional[str],
    label: str,
) -> tuple[pd.DataFrame, dict]:
    """Apply exposure ladder to the cash weight per period; rebuild equity.

    Returns: (per-period DataFrame, summary dict).
    """
    eq = equity_curve.copy()
    eq[date_col] = pd.to_datetime(eq[date_col], errors="coerce")
    eq = eq.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    if eq.empty:
        return eq, {"rows": 0, "status": "empty_equity"}
    dates = pd.DatetimeIndex(eq[date_col].values)
    aligned = _resample_features_to_dates(features, dates) if not features.empty else pd.DataFrame(index=dates)
    # Crisis score per period (default 0.0 when missing -> normal zone)
    crisis_score_per_row = (
        pd.to_numeric(aligned.get("crisis_score"), errors="coerce").fillna(0.0).values
        if "crisis_score" in aligned.columns
        else np.zeros(len(eq))
    )
    # Original cash weight per period (when available)
    if cash_col and cash_col in eq.columns:
        original_cash = pd.to_numeric(eq[cash_col], errors="coerce").fillna(0.0).values
    else:
        original_cash = np.full(len(eq), 0.0)
    # Original return per period
    original_return = pd.to_numeric(eq[return_col], errors="coerce").fillna(0.0).values

    governed_cash = np.zeros(len(eq))
    governed_return = np.zeros(len(eq))
    governed_reentry = np.zeros(len(eq))
    reentry_mult = 0.0  # state carries across periods inside "normal" zone only
    for i in range(len(eq)):
        cs = float(crisis_score_per_row[i])
        target = evaluate_exposure_target(cs)
        # Re-entry score recomputed per period from features (PIT-safe)
        if not aligned.empty:
            re_score = compute_reentry_score(aligned.iloc[i])
        else:
            re_score = 1.0
        # State transitions:
        #   * Inside defense/crisis zones: governor enforces cash floor, multi
        #     resets so the next "normal" zone starts at 0 and ramps up via the
        #     reentry ladder.
        #   * Inside normal zone: multi monotonically rises with reentry_score.
        if target.zone in ("defense", "crisis"):
            reentry_mult = 0.0
        elif target.zone == "normal":
            reentry_mult = reentry_exposure_multiplier(re_score, prior_multiplier=reentry_mult)
        # "caution" zone leaves reentry_mult untouched (gentle middle ground)
        governed_reentry[i] = reentry_mult

        # Target cash per zone -- floors enforced even when original_cash < floor
        if target.zone == "crisis":
            target_cash = (target.target_cash_floor + target.target_cash_ceiling) / 2.0
        elif target.zone == "defense":
            target_cash = target.target_cash_floor + (target.target_cash_ceiling - target.target_cash_floor) * 0.4
        elif target.zone == "caution":
            target_cash = target.target_cash_floor
        else:  # normal
            target_cash = float(np.clip(original_cash[i], target.target_cash_floor, target.target_cash_ceiling))
        governed_cash[i] = target_cash
        # Re-scale return: equity_return = original_return / (1 - original_cash)
        # then governed_return = equity_return * (1 - target_cash)
        denom = max(1.0 - original_cash[i], 1e-6)
        equity_return = original_return[i] / denom
        governed_return[i] = equity_return * (1.0 - target_cash)

    eq["original_cash_weight"] = original_cash
    eq["governed_cash_weight"] = governed_cash
    eq["original_return"] = original_return
    eq["governed_return"] = governed_return
    eq["crisis_score"] = crisis_score_per_row
    eq["reentry_multiplier"] = governed_reentry
    # Rebuild equity curves
    eq["original_equity"] = (1.0 + pd.Series(original_return)).cumprod().values
    eq["governed_equity"] = (1.0 + pd.Series(governed_return)).cumprod().values
    summary = {
        "label": label,
        "rows": len(eq),
        "first_date": eq[date_col].min().date().isoformat(),
        "last_date": eq[date_col].max().date().isoformat(),
        "original_cagr": _cagr(eq[date_col], eq["original_equity"]),
        "governed_cagr": _cagr(eq[date_col], eq["governed_equity"]),
        "original_mdd": _mdd(eq["original_equity"]),
        "governed_mdd": _mdd(eq["governed_equity"]),
        "original_avg_cash": float(np.mean(original_cash)),
        "governed_avg_cash": float(np.mean(governed_cash)),
        "status": "ok",
    }
    return eq, summary


def _cagr(dates: pd.Series, equity: pd.Series) -> float:
    if len(equity) < 2:
        return float("nan")
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float(equity.iloc[-1] ** (1.0 / years) - 1.0)


def _mdd(equity: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    return float(dd.min())


def stress_window_metrics(
    eq: pd.DataFrame, date_col: str, windows: list[tuple]
) -> pd.DataFrame:
    rows = []
    for name, start, end in windows:
        s = pd.Timestamp(start)
        e = pd.Timestamp(end) if end else None
        mask = eq[date_col] >= s
        if e is not None:
            mask &= eq[date_col] <= e
        sub = eq.loc[mask].copy()
        if len(sub) < 2:
            rows.append({"window": name, "start": start, "end": end or "open",
                         "rows": int(len(sub)), "status": "insufficient_data"})
            continue
        rows.append({
            "window": name,
            "start": start,
            "end": end or sub[date_col].max().date().isoformat(),
            "rows": int(len(sub)),
            "original_cagr": _cagr(sub[date_col], sub["original_equity"]),
            "governed_cagr": _cagr(sub[date_col], sub["governed_equity"]),
            "delta_cagr_pp": (_cagr(sub[date_col], sub["governed_equity"])
                              - _cagr(sub[date_col], sub["original_equity"])) * 100.0,
            "original_mdd": _mdd(sub["original_equity"]),
            "governed_mdd": _mdd(sub["governed_equity"]),
            "delta_mdd_pp": (_mdd(sub["governed_equity"]) - _mdd(sub["original_equity"])) * 100.0,
            "original_avg_cash": float(sub["original_cash_weight"].mean()),
            "governed_avg_cash": float(sub["governed_cash_weight"].mean()),
            "status": "ok",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None)
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    inp = discover_inputs(Path(args.base_dir) if args.base_dir else None)
    if not args.quiet:
        print(f"base_dir:    {inp.base_dir}")
        print(f"main_equity: {inp.main_equity}")
        print(f"crisis_features: {inp.crisis_features}")
        print(f"concentrated:    {inp.concentrated_monthly}")
    out_dir = inp.base_dir / "outputs" / "crisis_governor_replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit: dict = {"inputs": {k: str(v) if v else None for k, v in inp.__dict__.items() if k != "base_dir"}}
    audit["base_dir"] = str(inp.base_dir)
    audit["runs"] = {}
    features = (
        pd.read_parquet(inp.crisis_features)
        if inp.crisis_features and inp.crisis_features.exists()
        else pd.DataFrame()
    )
    stress_rows: list[pd.DataFrame] = []
    if inp.main_equity is not None:
        eq = pd.read_csv(inp.main_equity)
        date_col = "rebalance_date" if "rebalance_date" in eq.columns else "date"
        return_col = "net_return"
        cash_col = "cash_weight" if "cash_weight" in eq.columns else None
        governed, summary = compute_governed_curve(
            eq, features, date_col, return_col, cash_col, label="main"
        )
        out_path = out_dir / "main_with_governor.csv"
        governed.to_csv(out_path, index=False)
        audit["runs"]["main"] = summary
        windows = stress_window_metrics(governed, date_col, STRESS_WINDOWS)
        windows["portfolio"] = "main"
        stress_rows.append(windows)
        if not args.quiet:
            print(f"\nmain: {summary['rows']} rows  "
                  f"orig_cagr={summary['original_cagr']:.4f}  "
                  f"gov_cagr={summary['governed_cagr']:.4f}  "
                  f"orig_mdd={summary['original_mdd']:.4f}  "
                  f"gov_mdd={summary['governed_mdd']:.4f}")
    if inp.concentrated_monthly is not None:
        eq = pd.read_csv(inp.concentrated_monthly)
        date_col = "rebalance_date" if "rebalance_date" in eq.columns else "date"
        return_col = "net_return" if "net_return" in eq.columns else "return"
        cash_col = "cash_weight" if "cash_weight" in eq.columns else None
        if date_col in eq.columns and return_col in eq.columns:
            governed, summary = compute_governed_curve(
                eq, features, date_col, return_col, cash_col, label="concentrated"
            )
            out_path = out_dir / "concentrated_with_governor.csv"
            governed.to_csv(out_path, index=False)
            audit["runs"]["concentrated"] = summary
            windows = stress_window_metrics(governed, date_col, STRESS_WINDOWS)
            windows["portfolio"] = "concentrated"
            stress_rows.append(windows)
            if not args.quiet:
                print(f"concentrated: {summary['rows']} rows  "
                      f"orig_cagr={summary['original_cagr']:.4f}  "
                      f"gov_cagr={summary['governed_cagr']:.4f}  "
                      f"orig_mdd={summary['original_mdd']:.4f}  "
                      f"gov_mdd={summary['governed_mdd']:.4f}")
    if stress_rows:
        all_windows = pd.concat(stress_rows, ignore_index=True)
        (out_dir / "stress_window_metrics.csv").write_text(
            all_windows.to_csv(index=False)
        )
        audit["stress_windows_path"] = str(
            (out_dir / "stress_window_metrics.csv").relative_to(ROOT)
        )
    if not audit["runs"]:
        audit["status"] = "no_inputs"
        if not args.quiet:
            print("\nERROR: no equity curves available. Run a pipeline first.", file=sys.stderr)
        (out_dir / "replay_audit.json").write_text(json.dumps(audit, indent=2, default=str))
        return 1
    audit["status"] = "ok"
    (out_dir / "replay_audit.json").write_text(json.dumps(audit, indent=2, default=str))
    if not args.quiet:
        print(f"\noutputs: {out_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
