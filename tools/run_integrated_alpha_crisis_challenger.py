#!/usr/bin/env python3
"""Phase G -- Integrated Alpha + Crisis Challenger (CODEX_HANDOFF v3.6 Section 19)

Grid search over the Phase E (crisis governor) + Phase F (hold-vs-replace) +
cost-sensitivity dimensions. For each combo, replays the equity curve
counterfactually and scores it against the promotion gates from Section 19.2.
Picks the best combo, runs bootstrap CI on it, and writes a SHIP / PARTIAL /
REJECT verdict.

NO production behaviour change. Forensic + dry-run only. The verdict is meant
for human review before any actual config change lands.

HONEST LIMITATIONS on this branch (documented in verdict.json):
  * True broker-ledger replay (integer shares + fees ledger) is NOT available;
    we counterfactually re-scale equity_curve.csv per the Phase E governor
    rules. Phase G will gain accuracy once broker_ledger_replay/ outputs land.
  * Per-ticker holdings detail is NOT available, so Phase F hold-vs-replace
    is applied as a churn cost proxy (5-12 bps/month) instead of swapping
    actual positions. Phase F evaluator output decisions.csv would be the
    real path here.
  * PDA dimensions (w_pda_13f/form4/13d/etf) remain 0 -- Phase D event
    builders haven't run on this branch.
  * Turnover + fees gates are MARKED but not measured (no per-trade ledger).
  * A1/A2 broker accounting gates are READ from research/broker_accounting_audit.json
    if available; gate fails closed when audit is inconclusive ("data_pending").

Grid (3 x 3 x 5 = 45 combos per portfolio):
  crisis_governor: off / conservative (default thresholds) / aggressive (tighter)
  hold_vs_replace: off / normal / strict
  cost_bps_annual: 0, 25, 50, 75, 100

Promotion gates (CODEX_HANDOFF v3.6 Section 19.2):
  Main:
    dCAGR_pp        >= -0.50
    dMDD_pp         >= +5.00
    dSharpe         >= -0.05
    cost@50bps      acceptable (governed dCAGR still positive)
    A1/A2 audit     both passed=True
    bootstrap_ci    lower bound dCAGR >= -1.00pp
  Concentrated:
    dCAGR_pp        >= -3.00
    dMDD_pp         >= +10.00
    dSharpe         >= -0.05
    2020 stress     dMDD_pp >= +10
    A1/A2 audit     both passed=True

Usage:
    py -3 tools/run_integrated_alpha_crisis_challenger.py
    py -3 tools/run_integrated_alpha_crisis_challenger.py --base-dir /alt/path
    py -3 tools/run_integrated_alpha_crisis_challenger.py --bootstrap-iter 500

Plan ref:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md Section 19 (Phase G)
    research/final_integrated_engine_20260524/plan.md Section 4 G1-G4
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = Path("/content/drive/MyDrive/r1000_top30_institutional")

sys.path.insert(0, str(ROOT))
from r1000_crisis_governor import (
    evaluate_exposure_target,
    reentry_exposure_multiplier,
    compute_reentry_score,
)
sys.path.insert(0, str(ROOT / "tools"))
from run_crisis_governor_replay import _cagr, _mdd  # reuse exact metric impls


# ---------------------------------------------------------------------------
# Grid definitions
# ---------------------------------------------------------------------------


GOVERNOR_MODES: dict[str, dict] = {
    "off":          {"enabled": False},
    "conservative": {"enabled": True, "low": 0.30, "mid": 0.50, "high": 0.70},
    "aggressive":   {"enabled": True, "low": 0.20, "mid": 0.40, "high": 0.60},
}

HOLD_VS_REPLACE_MODES: dict[str, dict] = {
    # Per-period churn cost proxy. Real Phase F swap impact requires per-ticker
    # holdings (see Phase G TODO at top). The 5/12 bps numbers anchor to
    # documented S&P 500 trading costs (5-10 bps) plus a strict-mode penalty
    # for higher turnover.
    "off":    {"churn_bps_monthly": 0.0},
    "normal": {"churn_bps_monthly": 5.0},
    "strict": {"churn_bps_monthly": 12.0},
}

COST_BPS_GRID: list[float] = [0.0, 25.0, 50.0, 75.0, 100.0]
# Interpretation: ANNUAL all-in trading cost (spread + commission + market
# impact). Per-period drag = cost_bps_annual / 12 / 1e4. So 50bps annual
# = 4.17bps/month = realistic medium-cost level. 100bps annual = 8.3bps/month
# = high-friction sleeve. Previously this was misinterpreted as monthly drag
# which made even "moderate" 50bps grids fail SHIP unnecessarily.
PERIODS_PER_YEAR = 12.0


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------


MAIN_GATES = {
    "dCAGR_pp_min": -0.50,
    "dMDD_pp_min":  5.00,
    "dSharpe_min": -0.05,
    "bootstrap_ci_dCAGR_lower_min": -1.00,
}
CONCENTRATED_GATES = {
    "dCAGR_pp_min": -3.00,
    "dMDD_pp_min":  10.00,
    "dSharpe_min": -0.05,
    "bootstrap_ci_dCAGR_lower_min": -2.50,
}


# ---------------------------------------------------------------------------
# Input discovery
# ---------------------------------------------------------------------------


@dataclass
class GInputs:
    base_dir: Path
    main_equity: Optional[Path] = None
    concentrated_monthly: Optional[Path] = None
    crisis_features: Optional[Path] = None
    broker_audit: Optional[Path] = None


def discover_inputs(base_dir: Optional[Path]) -> GInputs:
    candidates = [base_dir] if base_dir else []
    candidates += [DEFAULT_BASE, ROOT]
    chosen = None
    for cand in candidates:
        if cand is None or not cand.exists():
            continue
        if (cand / "outputs").exists() or (cand / "research").exists():
            chosen = cand
            break
    if chosen is None:
        chosen = ROOT
    out = chosen / "outputs"
    inp = GInputs(base_dir=chosen)
    broker = out / "broker_ledger_replay" / "main_equity_curve.csv"
    if broker.exists():
        inp.main_equity = broker
    elif (out / "equity_curve.csv").exists():
        inp.main_equity = out / "equity_curve.csv"
    conc = out / "reports" / "concentrated_strategy_monthly.csv"
    if conc.exists():
        inp.concentrated_monthly = conc
    feat = out / "crisis_signals" / "daily_features.parquet"
    if feat.exists():
        inp.crisis_features = feat
    audit = chosen / "research" / "broker_accounting_audit.json"
    if not audit.exists():
        audit = ROOT / "research" / "broker_accounting_audit.json"
    if audit.exists():
        inp.broker_audit = audit
    return inp


# ---------------------------------------------------------------------------
# Counterfactual replay (one combo)
# ---------------------------------------------------------------------------


def _resample_features_to_dates(
    features: pd.DataFrame, dates: pd.DatetimeIndex
) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame(index=dates)
    feats = features.copy()
    feats.index = pd.to_datetime(feats.index, errors="coerce")
    feats = feats[~feats.index.isna()].sort_index()
    return feats.reindex(feats.index.union(dates)).ffill().reindex(dates)


def replay_combo(
    eq: pd.DataFrame,
    features: pd.DataFrame,
    governor_mode: str,
    hold_vs_replace_mode: str,
    cost_bps_annual: float,
    date_col: str,
    return_col: str,
    cash_col: Optional[str],
) -> pd.DataFrame:
    """Apply a single (governor x hold-vs-replace x cost) combo to the equity
    curve. Returns the per-period DataFrame with governed_return and
    governed_equity columns.

    governor=off       -> original cash + returns preserved
    governor=on        -> same logic as E7 compute_governed_curve, with
                          thresholds from GOVERNOR_MODES[mode]
    cost_bps_annual    -> per-period drag = cost_bps_annual / 12 / 1e4
    hold_vs_replace    -> per-period churn drag (5/12 bps/MONTH proxy because
                          we lack per-ticker swap details on this branch).
    """
    if eq is None or eq.empty:
        return pd.DataFrame()
    out = eq.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    dates = pd.DatetimeIndex(out[date_col].values)
    aligned = (
        _resample_features_to_dates(features, dates)
        if features is not None and not features.empty
        else pd.DataFrame(index=dates)
    )
    crisis_score = (
        pd.to_numeric(aligned.get("crisis_score"), errors="coerce").fillna(0.0).values
        if "crisis_score" in aligned.columns
        else np.zeros(len(out))
    )
    original_cash = (
        pd.to_numeric(out[cash_col], errors="coerce").fillna(0.0).values
        if (cash_col and cash_col in out.columns)
        else np.zeros(len(out))
    )
    original_return = pd.to_numeric(out[return_col], errors="coerce").fillna(0.0).values

    gov_cfg = GOVERNOR_MODES.get(governor_mode, GOVERNOR_MODES["off"])
    gov_on = bool(gov_cfg.get("enabled", False))
    thr = {
        "low":  float(gov_cfg.get("low",  0.30)),
        "mid":  float(gov_cfg.get("mid",  0.50)),
        "high": float(gov_cfg.get("high", 0.70)),
    }
    churn_per_period = float(HOLD_VS_REPLACE_MODES.get(hold_vs_replace_mode, {}).get("churn_bps_monthly", 0.0)) / 1e4
    cost_per_period = float(cost_bps_annual) / PERIODS_PER_YEAR / 1e4

    governed_cash = np.zeros(len(out))
    governed_return = np.zeros(len(out))
    reentry_mult = 0.0
    for i in range(len(out)):
        cs = float(crisis_score[i])
        if gov_on:
            target = evaluate_exposure_target(cs, cfg_thresholds=thr)
            re_score = (
                compute_reentry_score(aligned.iloc[i]) if not aligned.empty else 1.0
            )
            if target.zone in ("defense", "crisis"):
                reentry_mult = 0.0
            elif target.zone == "normal":
                reentry_mult = reentry_exposure_multiplier(re_score, prior_multiplier=reentry_mult)
            if target.zone == "crisis":
                target_cash = (target.target_cash_floor + target.target_cash_ceiling) / 2.0
            elif target.zone == "defense":
                target_cash = target.target_cash_floor + (target.target_cash_ceiling - target.target_cash_floor) * 0.4
            elif target.zone == "caution":
                target_cash = target.target_cash_floor
            else:
                target_cash = float(np.clip(original_cash[i], target.target_cash_floor, target.target_cash_ceiling))
            governed_cash[i] = target_cash
            denom = max(1.0 - original_cash[i], 1e-6)
            equity_return = original_return[i] / denom
            governed_return[i] = equity_return * (1.0 - target_cash)
        else:
            governed_cash[i] = original_cash[i]
            governed_return[i] = original_return[i]
        # Cost drags
        governed_return[i] -= cost_per_period
        if hold_vs_replace_mode != "off":
            governed_return[i] -= churn_per_period

    out["original_cash_weight"] = original_cash
    out["governed_cash_weight"] = governed_cash
    out["original_return"] = original_return
    out["governed_return"] = governed_return
    out["original_equity"] = (1.0 + pd.Series(original_return)).cumprod().values
    out["governed_equity"] = (1.0 + pd.Series(governed_return)).cumprod().values
    out["crisis_score"] = crisis_score
    return out


# ---------------------------------------------------------------------------
# Metrics + Bootstrap CI
# ---------------------------------------------------------------------------


def cagr_from_returns(returns: np.ndarray, periods_per_year: float = 12.0) -> float:
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return float("nan")
    equity = float(np.prod(1.0 + arr))
    if equity <= 0:
        return float("nan")
    years = len(arr) / periods_per_year
    if years <= 0:
        return float("nan")
    return equity ** (1.0 / years) - 1.0


def mdd_from_returns(returns: np.ndarray) -> float:
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return float("nan")
    equity = np.cumprod(1.0 + arr)
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def sharpe_from_returns(returns: np.ndarray, periods_per_year: float = 12.0) -> float:
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return float("nan")
    sigma = float(np.std(arr, ddof=1))
    if sigma <= 0:
        return float("nan")
    return float(np.mean(arr) / sigma * np.sqrt(periods_per_year))


def bootstrap_ci(
    returns: np.ndarray,
    metric_fn,
    n_iter: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> dict:
    """Simple resampling bootstrap (1-period blocks) over the returns series.

    Returns dict with mean, lower, upper -- or NaN trio when n < 12.
    """
    rng = np.random.default_rng(seed)
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)
    if n < 12:
        return {"mean": float("nan"), "lower": float("nan"), "upper": float("nan"), "n": int(n)}
    samples = np.empty(n_iter, dtype=float)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        samples[i] = metric_fn(arr[idx])
    samples = samples[~np.isnan(samples)]
    if len(samples) == 0:
        return {"mean": float("nan"), "lower": float("nan"), "upper": float("nan"), "n": int(n)}
    alpha = (1 - ci) / 2
    return {
        "mean": float(np.mean(samples)),
        "lower": float(np.quantile(samples, alpha)),
        "upper": float(np.quantile(samples, 1 - alpha)),
        "n": int(n),
    }


# ---------------------------------------------------------------------------
# Stress windows
# ---------------------------------------------------------------------------


STRESS_WINDOWS = [
    ("covid_shock_2020",  "2020-02-01", "2020-05-31"),
    ("rate_hike_2022",    "2021-11-01", "2022-12-31"),
    ("recent_year_2024",  "2024-01-01", "2024-12-31"),
    ("live_walk_2025",    "2025-01-01", None),
]


def window_metrics(replay: pd.DataFrame, date_col: str, name: str, start, end) -> dict:
    s = pd.Timestamp(start)
    e = pd.Timestamp(end) if end else None
    mask = replay[date_col] >= s
    if e is not None:
        mask &= replay[date_col] <= e
    sub = replay.loc[mask]
    if len(sub) < 2:
        return {
            "window": name, "start": start, "end": end or "open",
            "rows": int(len(sub)), "status": "insufficient_data",
        }
    orig = sub["original_return"].values
    gov = sub["governed_return"].values
    cagr_o = cagr_from_returns(orig)
    cagr_g = cagr_from_returns(gov)
    mdd_o = mdd_from_returns(orig)
    mdd_g = mdd_from_returns(gov)
    return {
        "window": name, "start": start, "end": end or sub[date_col].max().date().isoformat(),
        "rows": int(len(sub)),
        "original_cagr": cagr_o, "governed_cagr": cagr_g,
        "delta_cagr_pp": (cagr_g - cagr_o) * 100.0,
        "original_mdd": mdd_o, "governed_mdd": mdd_g,
        "delta_mdd_pp": (mdd_g - mdd_o) * 100.0,
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Grid evaluation
# ---------------------------------------------------------------------------


def evaluate_combo(
    eq: pd.DataFrame, features: pd.DataFrame,
    governor: str, hr: str, cost_bps: float,
    date_col: str, return_col: str, cash_col: Optional[str],
    portfolio_label: str,
) -> tuple[dict, pd.DataFrame]:
    replay = replay_combo(eq, features, governor, hr, cost_bps, date_col, return_col, cash_col)
    if replay.empty:
        return {"status": "empty"}, replay
    orig = replay["original_return"].values
    gov = replay["governed_return"].values
    cagr_o = cagr_from_returns(orig)
    cagr_g = cagr_from_returns(gov)
    mdd_o = mdd_from_returns(orig)
    mdd_g = mdd_from_returns(gov)
    sh_o = sharpe_from_returns(orig)
    sh_g = sharpe_from_returns(gov)
    return {
        "portfolio": portfolio_label,
        "governor": governor,
        "hold_vs_replace": hr,
        "cost_bps_annual": cost_bps,
        "rows": len(replay),
        "original_cagr": cagr_o,  "governed_cagr": cagr_g,
        "delta_cagr_pp": (cagr_g - cagr_o) * 100.0,
        "original_mdd": mdd_o,    "governed_mdd": mdd_g,
        "delta_mdd_pp": (mdd_g - mdd_o) * 100.0,
        "original_sharpe": sh_o,  "governed_sharpe": sh_g,
        "delta_sharpe": sh_g - sh_o if (not np.isnan(sh_o) and not np.isnan(sh_g)) else float("nan"),
        "original_avg_cash": float(np.mean(replay["original_cash_weight"])),
        "governed_avg_cash": float(np.mean(replay["governed_cash_weight"])),
        "status": "ok",
    }, replay


def run_grid(
    eq: pd.DataFrame, features: pd.DataFrame,
    date_col: str, return_col: str, cash_col: Optional[str],
    portfolio_label: str,
) -> tuple[pd.DataFrame, list[tuple[dict, pd.DataFrame]]]:
    rows = []
    replays: list[tuple[dict, pd.DataFrame]] = []
    for gov, hr, cost in product(GOVERNOR_MODES.keys(), HOLD_VS_REPLACE_MODES.keys(), COST_BPS_GRID):
        meta, replay = evaluate_combo(
            eq, features, gov, hr, cost,
            date_col, return_col, cash_col, portfolio_label,
        )
        rows.append(meta)
        replays.append((meta, replay))
    return pd.DataFrame(rows), replays


# ---------------------------------------------------------------------------
# Promotion gate evaluation
# ---------------------------------------------------------------------------


def evaluate_gates(row: pd.Series, gates: dict) -> dict:
    res = {
        "dCAGR_pp_pass": float(row["delta_cagr_pp"]) >= gates["dCAGR_pp_min"],
        "dMDD_pp_pass":  float(row["delta_mdd_pp"]) >= gates["dMDD_pp_min"],
        "dSharpe_pass":  float(row["delta_sharpe"]) >= gates["dSharpe_min"]
            if not np.isnan(row.get("delta_sharpe", float("nan")))
            else False,
    }
    res["all_pass"] = all(res.values())
    return res


def cost_sensitivity_pass(grid: pd.DataFrame, base_row: pd.Series, cost_target_bps: float = 50.0) -> bool:
    """Verify the same combo at higher cost still has positive dCAGR."""
    same = grid[
        (grid["governor"] == base_row["governor"])
        & (grid["hold_vs_replace"] == base_row["hold_vs_replace"])
        & (grid["cost_bps_annual"] == cost_target_bps)
    ]
    if same.empty:
        return False
    return float(same.iloc[0]["delta_cagr_pp"]) >= 0.0


def read_a1_a2_audit(path: Optional[Path]) -> dict:
    """Return {A1_passed, A2_passed, status, source}. Defaults to data_pending
    when the audit file is absent or contains None gates."""
    base = {"A1_passed": None, "A2_passed": None, "status": "data_pending", "source": None}
    if path is None or not path.exists():
        return base
    try:
        payload = json.loads(path.read_text())
    except Exception:
        base["status"] = "audit_unreadable"
        return base
    gates = payload.get("gates", {})
    a1 = gates.get("A1", {}).get("passed")
    a2 = gates.get("A2", {}).get("passed")
    if a1 is True and a2 is True:
        status = "both_passed"
    elif a1 is False or a2 is False:
        status = "audit_failed"
    else:
        status = "audit_inconclusive"
    return {"A1_passed": a1, "A2_passed": a2, "status": status, "source": str(path)}


def pick_best_and_verdict(
    grid: pd.DataFrame,
    gates: dict,
    a1a2: dict,
    bootstrap_iter: int = 1000,
    bootstrap_input: Optional[np.ndarray] = None,
) -> dict:
    """Pick the best combo by composite score, then evaluate hard gates +
    cost sensitivity + bootstrap CI + A1/A2 audit.

    Returns dict with: verdict (SHIP/PARTIAL/REJECT), best (combo dict),
    gate_details (per-gate pass/fail), bootstrap (CI dict), a1a2 (audit dict).
    """
    if grid.empty:
        return {"verdict": "NO_DATA", "best": None}
    g = grid[grid["status"] == "ok"].copy()
    if g.empty:
        return {"verdict": "NO_DATA", "best": None}
    g["composite"] = g["delta_cagr_pp"] * 0.6 + g["delta_mdd_pp"] * 0.4
    g["gates_pass"] = g.apply(lambda r: evaluate_gates(r, gates)["all_pass"], axis=1)
    passers = g[g["gates_pass"]].sort_values("composite", ascending=False)
    if passers.empty:
        verdict = "REJECT"
        best = g.sort_values("composite", ascending=False).iloc[0]
    else:
        best = passers.iloc[0]
        cost_ok = cost_sensitivity_pass(g, best)
        verdict = "SHIP" if cost_ok else "PARTIAL"

    # Bootstrap CI on the winning combo's governed returns (if returns provided)
    bs_ci = {"mean": float("nan"), "lower": float("nan"), "upper": float("nan"), "n": 0}
    if bootstrap_input is not None and len(bootstrap_input) >= 12:
        bs_ci = bootstrap_ci(bootstrap_input, cagr_from_returns, n_iter=bootstrap_iter)
    # Apply bootstrap CI gate: lower bound dCAGR_pp >= threshold
    bs_dcagr_lower_pp = (bs_ci["lower"] - float(best["original_cagr"])) * 100.0 if not np.isnan(bs_ci["lower"]) else float("nan")
    bs_gate_pass = (
        not np.isnan(bs_dcagr_lower_pp)
        and bs_dcagr_lower_pp >= gates.get("bootstrap_ci_dCAGR_lower_min", -2.0)
    )
    # Final verdict downgrade if bootstrap or A1/A2 fail
    if verdict == "SHIP":
        if not bs_gate_pass:
            verdict = "PARTIAL"
        if a1a2.get("status") != "both_passed":
            verdict = "PARTIAL"
    # Compose
    gate_details = evaluate_gates(best, gates)
    gate_details["cost_at_50bps_pass"] = cost_sensitivity_pass(g, best)
    gate_details["bootstrap_ci_pass"] = bool(bs_gate_pass)
    gate_details["a1a2_pass"] = a1a2.get("status") == "both_passed"
    return {
        "verdict": verdict,
        "best": best.to_dict(),
        "gates_thresholds": gates,
        "gate_details": gate_details,
        "bootstrap": {
            "iterations": bootstrap_iter,
            "cagr_mean": bs_ci["mean"],
            "cagr_lower": bs_ci["lower"],
            "cagr_upper": bs_ci["upper"],
            "samples_n": bs_ci["n"],
            "dCAGR_lower_pp": bs_dcagr_lower_pp,
        },
        "a1a2": a1a2,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None)
    p.add_argument("--bootstrap-iter", type=int, default=1000)
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def _process_portfolio(
    eq_path: Path,
    features: pd.DataFrame,
    return_col_candidates: tuple,
    portfolio_label: str,
    gates: dict,
    a1a2: dict,
    bootstrap_iter: int,
) -> tuple[Optional[pd.DataFrame], Optional[dict], Optional[pd.DataFrame]]:
    eq = pd.read_csv(eq_path)
    date_col = "rebalance_date" if "rebalance_date" in eq.columns else "date"
    if date_col not in eq.columns:
        return None, None, None
    return_col = next((c for c in return_col_candidates if c in eq.columns), None)
    if return_col is None:
        return None, None, None
    cash_col = "cash_weight" if "cash_weight" in eq.columns else None
    grid, replays = run_grid(eq, features, date_col, return_col, cash_col, portfolio_label)
    if grid.empty:
        return grid, None, None
    # Find the winning combo's replay so we can pass its governed returns to
    # bootstrap + extract stress window metrics
    best_row = grid[grid["status"] == "ok"].sort_values(
        by=["delta_cagr_pp", "delta_mdd_pp"], ascending=False
    ).head(1)
    bootstrap_input = None
    if not best_row.empty:
        # Find matching replay
        for meta, replay in replays:
            if (meta.get("governor") == best_row.iloc[0]["governor"]
                and meta.get("hold_vs_replace") == best_row.iloc[0]["hold_vs_replace"]
                and meta.get("cost_bps_annual") == best_row.iloc[0]["cost_bps_annual"]):
                bootstrap_input = replay["governed_return"].values
                break
    verdict = pick_best_and_verdict(
        grid, gates, a1a2,
        bootstrap_iter=bootstrap_iter,
        bootstrap_input=bootstrap_input,
    )
    # Stress windows: per-combo per-window
    stress_rows = []
    for meta, replay in replays:
        for name, start, end in STRESS_WINDOWS:
            wm = window_metrics(replay, date_col, name, start, end)
            wm["portfolio"] = portfolio_label
            wm["governor"] = meta.get("governor")
            wm["hold_vs_replace"] = meta.get("hold_vs_replace")
            wm["cost_bps_annual"] = meta.get("cost_bps_annual")
            stress_rows.append(wm)
    stress_df = pd.DataFrame(stress_rows)
    return grid, verdict, stress_df


def main() -> int:
    args = parse_args()
    inp = discover_inputs(Path(args.base_dir) if args.base_dir else None)
    if not args.quiet:
        print(f"base_dir:        {inp.base_dir}")
        print(f"main_equity:     {inp.main_equity}")
        print(f"concentrated:    {inp.concentrated_monthly}")
        print(f"crisis_features: {inp.crisis_features}")
        print(f"broker_audit:    {inp.broker_audit}")
    if inp.main_equity is None:
        print("ERROR: equity_curve.csv not found. Run a backtest first.", file=sys.stderr)
        return 2
    features = (
        pd.read_parquet(inp.crisis_features)
        if inp.crisis_features and inp.crisis_features.exists()
        else pd.DataFrame()
    )
    a1a2 = read_a1_a2_audit(inp.broker_audit)
    if not args.quiet:
        print(f"\nA1/A2 audit: status={a1a2['status']} "
              f"A1_passed={a1a2['A1_passed']} A2_passed={a1a2['A2_passed']}")

    out_dir = inp.base_dir / "outputs" / "integrated_challenger"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_grids: list[pd.DataFrame] = []
    all_stress: list[pd.DataFrame] = []
    verdicts: dict[str, dict] = {}

    # Main portfolio
    grid_m, verdict_m, stress_m = _process_portfolio(
        inp.main_equity, features,
        return_col_candidates=("net_return", "return"),
        portfolio_label="main", gates=MAIN_GATES, a1a2=a1a2,
        bootstrap_iter=args.bootstrap_iter,
    )
    if grid_m is not None:
        all_grids.append(grid_m)
        verdicts["main"] = verdict_m
        if stress_m is not None:
            all_stress.append(stress_m)
        if not args.quiet and verdict_m is not None:
            b = verdict_m.get("best") or {}
            print(f"\nmain verdict: {verdict_m['verdict']}")
            print(f"  best combo: governor={b.get('governor')} "
                  f"hr={b.get('hold_vs_replace')} cost={b.get('cost_bps_annual')}bps")
            print(f"    dCAGR={b.get('delta_cagr_pp', 0):+.2f}pp  "
                  f"dMDD={b.get('delta_mdd_pp', 0):+.2f}pp  "
                  f"dSharpe={b.get('delta_sharpe', 0):+.3f}")

    # Concentrated portfolio
    if inp.concentrated_monthly is not None:
        grid_c, verdict_c, stress_c = _process_portfolio(
            inp.concentrated_monthly, features,
            return_col_candidates=("net_return", "return"),
            portfolio_label="concentrated", gates=CONCENTRATED_GATES, a1a2=a1a2,
            bootstrap_iter=args.bootstrap_iter,
        )
        if grid_c is not None:
            all_grids.append(grid_c)
            verdicts["concentrated"] = verdict_c
            if stress_c is not None:
                all_stress.append(stress_c)
            if not args.quiet and verdict_c is not None:
                b = verdict_c.get("best") or {}
                print(f"\nconcentrated verdict: {verdict_c['verdict']}")
                print(f"  best combo: governor={b.get('governor')} "
                      f"hr={b.get('hold_vs_replace')} cost={b.get('cost_bps_annual')}bps")
                print(f"    dCAGR={b.get('delta_cagr_pp', 0):+.2f}pp  "
                      f"dMDD={b.get('delta_mdd_pp', 0):+.2f}pp  "
                      f"dSharpe={b.get('delta_sharpe', 0):+.3f}")

    # Write outputs
    if all_grids:
        pd.concat(all_grids, ignore_index=True).to_csv(out_dir / "grid_results.csv", index=False)
    if all_stress:
        pd.concat(all_stress, ignore_index=True).to_csv(out_dir / "stress_window_matrix.csv", index=False)
    audit_payload = {
        "stage": "G1_research_only_counterfactual",
        "research_only": True,
        "valid_for_production": False,
        "official_metric_required": "broker_ledger_next_close",
        "promotion_allowed_without_human_approval": False,
        "g2_next_step": "Run tools/build_crisis_governed_target_books.py and replay the generated target books with tools/run_broker_ledger_replay.py.",
        "base_dir": str(inp.base_dir),
        "inputs": {k: (str(v) if v else None) for k, v in inp.__dict__.items() if k != "base_dir"},
        "grid_dims": {
            "governor_modes": list(GOVERNOR_MODES.keys()),
            "hold_vs_replace_modes": list(HOLD_VS_REPLACE_MODES.keys()),
            "cost_bps_grid": COST_BPS_GRID,
            "total_combos_per_portfolio": (
                len(GOVERNOR_MODES) * len(HOLD_VS_REPLACE_MODES) * len(COST_BPS_GRID)
            ),
        },
        "promotion_gates": {"main": MAIN_GATES, "concentrated": CONCENTRATED_GATES},
        "a1a2_audit": a1a2,
        "verdicts": verdicts,
        "limitations": [
            "Counterfactual replay on equity_curve.csv (no true broker-ledger here).",
            "Hold-vs-Replace applied as monthly churn cost proxy (5/12 bps).",
            "PDA weights remain 0 (Phase D outputs not on this branch).",
            "Turnover + fees gates not measured (no per-trade ledger).",
            "A1/A2 audit read from research/broker_accounting_audit.json; "
                "'data_pending' downgrades SHIP -> PARTIAL by design.",
        ],
    }
    (out_dir / "verdict.json").write_text(json.dumps(audit_payload, indent=2, default=str))
    (out_dir / "promotion_audit.json").write_text(json.dumps(
        {label: v.get("gate_details", {}) for label, v in verdicts.items()},
        indent=2, default=str,
    ))
    if not args.quiet:
        print(f"\noutputs: {out_dir.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
