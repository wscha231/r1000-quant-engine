#!/usr/bin/env python3
"""Phase F -- Hold-vs-Replace Evaluator (CODEX_HANDOFF v3.6 Section 18)

Reads the current portfolio + a candidate pool, decides per-position whether
to HOLD / TRIM / REPLACE / CASH using the Phase F discipline. Optionally
uses the Phase E crisis_score (from outputs/crisis_signals/daily_features.parquet)
to gate replacement behaviour (e.g., crisis mode requires quality_growth_score
>= 0.70 for any replacement).

NO production behaviour change. This is a forensic + dry-run tool; the
output decisions.csv is meant for human review before any actual portfolio
mutation lands.

Inputs (all auto-discovered, gracefully exits when absent):
  outputs/portfolio_latest.csv                         (current holdings)
  outputs/smart_money/top30_latest.csv                 (Phase C6 watchlist)
  outputs/tenbagger_watchlist/latest.csv               (Phase C6 tenbagger pool)
  outputs/crisis_signals/daily_features.parquet        (Phase E2)
  outputs/scored_latest.csv                            (fallback for score_z)

Outputs:
  outputs/hold_vs_replace/decisions.csv
  outputs/hold_vs_replace/audit.json

Usage:
    py -3 tools/run_hold_vs_replace_evaluator.py
    py -3 tools/run_hold_vs_replace_evaluator.py --base-dir /alt/path
    py -3 tools/run_hold_vs_replace_evaluator.py --crisis-zone crisis

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 18 (Phase F)
    research/final_integrated_engine_20260524/plan.md Section 3 F1-F4
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

sys.path.insert(0, str(ROOT))
from r1000_hold_vs_replace import (
    evaluate_portfolio_holds_vs_replaces,
    decision_summary,
)
# crisis_zone classification function lives in r1000_crisis_governor
from r1000_crisis_governor import crisis_zone


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass
class FInputs:
    base_dir: Path
    portfolio: Optional[Path] = None
    smart_money: Optional[Path] = None
    tenbagger: Optional[Path] = None
    crisis_features: Optional[Path] = None
    scored_latest: Optional[Path] = None


def discover_inputs(base_dir: Optional[Path]) -> FInputs:
    candidates = [base_dir] if base_dir else []
    candidates += [DEFAULT_BASE, ROOT]
    chosen = None
    for cand in candidates:
        if cand is None or not cand.exists():
            continue
        if (cand / "outputs").exists():
            chosen = cand
            break
    if chosen is None:
        chosen = ROOT
    out = chosen / "outputs"
    inp = FInputs(base_dir=chosen)
    for path, attr in [
        (out / "portfolio_latest.csv", "portfolio"),
        (out / "smart_money" / "top30_latest.csv", "smart_money"),
        (out / "tenbagger_watchlist" / "latest.csv", "tenbagger"),
        (out / "crisis_signals" / "daily_features.parquet", "crisis_features"),
        (out / "scored_latest.csv", "scored_latest"),
    ]:
        if path.exists():
            setattr(inp, attr, path)
    return inp


# ---------------------------------------------------------------------------
# Normalisation -- adapt heterogeneous source schemas to the F module contract
# ---------------------------------------------------------------------------


def _zscore(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    mu = s.mean(skipna=True)
    sigma = s.std(skipna=True, ddof=0)
    if sigma is None or sigma == 0 or np.isnan(sigma):
        return pd.Series(np.zeros(len(s)), index=s.index, dtype=float)
    return (s - mu) / sigma


def normalize_holdings(
    portfolio: pd.DataFrame, scored: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """Map portfolio_latest.csv + scored_latest.csv into the F contract:
    ticker, current_price, entry_price, weight, score_z, sector, rs_rank, ma200, pe_zscore
    """
    if portfolio is None or portfolio.empty:
        return pd.DataFrame()
    df = portfolio.copy()
    df = df.rename(columns={
        "Ticker": "ticker",
        "weight_target": "weight",
        "weight_actual": "weight",
        "close": "current_price",
        "px_close": "current_price",
        "entry": "entry_price",
        "avg_cost": "entry_price",
    })
    if "ticker" not in df.columns:
        return pd.DataFrame()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    for col in ("current_price", "entry_price", "weight"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Score_z either from scored_latest or computed from any score column
    if scored is not None and not scored.empty and "ticker" in scored.columns:
        scored_local = scored.copy()
        scored_local["ticker"] = scored_local["ticker"].astype(str).str.upper()
        score_col = next(
            (c for c in ("score", "selection_score", "composite_score") if c in scored_local.columns),
            None,
        )
        if score_col:
            scored_local["score_z"] = _zscore(scored_local[score_col])
            df = df.merge(
                scored_local[["ticker", "score_z"]], on="ticker", how="left"
            )
    if "score_z" not in df.columns:
        df["score_z"] = 0.0
    df["score_z"] = pd.to_numeric(df["score_z"], errors="coerce").fillna(0.0)
    if "sector" not in df.columns:
        df["sector"] = "unknown"
    if "rs_rank" not in df.columns:
        df["rs_rank"] = np.nan
    if "ma200" not in df.columns:
        df["ma200"] = np.nan
    if "pe_zscore" not in df.columns:
        df["pe_zscore"] = np.nan
    return df[["ticker", "current_price", "entry_price", "weight", "score_z",
               "sector", "rs_rank", "ma200", "pe_zscore"]]


def normalize_candidates(
    smart_money: Optional[pd.DataFrame], tenbagger: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """Merge candidate pools into the F contract:
    ticker, score_z, sector, quality_growth_score, available_from_ts
    """
    frames = []
    for src in (smart_money, tenbagger):
        if src is None or src.empty:
            continue
        df = src.copy()
        df = df.rename(columns={
            "Ticker": "ticker",
            "composite_smart_money_score": "score",
            "tenbagger_discovery_score": "score",
        })
        if "ticker" not in df.columns:
            continue
        df["ticker"] = df["ticker"].astype(str).str.upper()
        score_col = next(
            (c for c in ("score", "selection_score", "composite_score") if c in df.columns),
            None,
        )
        if score_col is None:
            continue
        df["score_z"] = _zscore(df[score_col])
        if "sector" not in df.columns:
            df["sector"] = "unknown"
        if "quality_growth_score" not in df.columns:
            df["quality_growth_score"] = 0.5  # neutral assumption
        if "available_from_ts" not in df.columns:
            df["available_from_ts"] = pd.NaT
        frames.append(df[["ticker", "score_z", "sector", "quality_growth_score",
                          "available_from_ts"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # Deduplicate: keep highest score_z per ticker
    out = out.sort_values("score_z", ascending=False).drop_duplicates("ticker", keep="first")
    return out.reset_index(drop=True)


def infer_crisis_zone(features: Optional[pd.DataFrame], cli_override: Optional[str]) -> str:
    if cli_override is not None:
        return cli_override
    if features is None or features.empty or "crisis_score" not in features.columns:
        return "normal"
    latest_score = pd.to_numeric(features["crisis_score"], errors="coerce").iloc[-1]
    if pd.isna(latest_score):
        return "normal"
    return crisis_zone(float(latest_score))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None)
    p.add_argument("--crisis-zone", choices=("normal", "caution", "defense", "crisis"), default=None,
                   help="Override crisis zone (default: infer from E2 features)")
    p.add_argument("--concentrated-floor", type=float, default=0.30)
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    inp = discover_inputs(Path(args.base_dir) if args.base_dir else None)
    if not args.quiet:
        print(f"base_dir:        {inp.base_dir}")
        print(f"portfolio:       {inp.portfolio}")
        print(f"smart_money:     {inp.smart_money}")
        print(f"tenbagger:       {inp.tenbagger}")
        print(f"crisis_features: {inp.crisis_features}")
    if inp.portfolio is None:
        print("ERROR: portfolio_latest.csv not found. Run a pipeline first.", file=sys.stderr)
        return 2
    portfolio_df = pd.read_csv(inp.portfolio)
    scored_df = pd.read_csv(inp.scored_latest) if inp.scored_latest else None
    sm_df = pd.read_csv(inp.smart_money) if inp.smart_money else None
    tb_df = pd.read_csv(inp.tenbagger) if inp.tenbagger else None
    feat_df = pd.read_parquet(inp.crisis_features) if inp.crisis_features else None
    holdings = normalize_holdings(portfolio_df, scored_df)
    candidates = normalize_candidates(sm_df, tb_df)
    zone = infer_crisis_zone(feat_df, args.crisis_zone)
    if not args.quiet:
        print(f"\nholdings rows:   {len(holdings)}")
        print(f"candidates rows: {len(candidates)}")
        print(f"crisis_zone:     {zone}")
    decisions = evaluate_portfolio_holds_vs_replaces(
        holdings, candidates, crisis_zone=zone,
        concentrated_floor=args.concentrated_floor,
    )
    out_dir = inp.base_dir / "outputs" / "hold_vs_replace"
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = out_dir / "decisions.csv"
    audit_path = out_dir / "audit.json"
    decisions.to_csv(decisions_path, index=False)
    summary = decision_summary(decisions)
    summary["crisis_zone"] = zone
    summary["inputs"] = {k: str(v) if v else None for k, v in inp.__dict__.items()
                          if k != "base_dir"}
    audit_path.write_text(json.dumps(summary, indent=2, default=str))
    if not args.quiet:
        print(f"\ndecisions: {decisions_path.relative_to(ROOT)}")
        print(f"audit:     {audit_path.relative_to(ROOT)}")
        for k, v in summary.get("by_action", {}).items():
            print(f"  {k:10s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
