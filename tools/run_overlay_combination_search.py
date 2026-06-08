"""Overlay Combination Search — broker-daily ranked champion picker.

Given a single FROZEN base artifact (a downloaded full-rebuild ``outputs/`` dir),
sweep the replay-overlay knob grid (concentrated champion N/weighting/rebalance,
neutral-regime churn, macro circuit breaker, regime capacity multipliers, cost
basis), evaluate every combination on the official ``run_broker_ledger_replay``
next-close broker-daily metric, then rank under stress + cost + stability gates.

Two passes:
  1. Primary screen — every combo gets one broker replay at the primary cost
     band; we capture full broker metrics PLUS COVID-2020 and 2022-bear stress
     MDDs sliced from ``equity_curve.csv`` (free, no extra runs).
  2. Confirmation — the top-K from pass 1 get a cost sweep (25/50/75/100 bps)
     and a top-k neighbourhood-median stability score.

Champion is the combo whose primary pass + stress + cost + stability all clear
their gates. We DELIBERATELY rank by neighbourhood-median, not by best-row —
the existing ``run_broker_ledger_replay.resolve_concentrated_champion_filters``
picks "first row best CAGR" of ``concentrated_strategy_comparison.csv``, which
is exactly the best-only overfit we are designing around.

This tool is research-only: it never mutates the base artifact, never touches
``portfolio_latest.csv`` / production target books, never alters live policy.
It writes a self-contained ``champion.json`` with the exact CLI invocations to
reproduce the winning replay.
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "tools"

DEFAULT_GRID: dict[str, Any] = {
    "concentrated_champion": {
        "target_stock_names": [3, 4, 5],
        "weighting_mode": ["score_power", "conviction_curve"],
        "rebalance_interval_months": [1, 2, 3],
    },
    "main_champion": {
        # Main has no champion-filter override (no comparison_csv used);
        # we still need a single entry so the cartesian product works.
        "_passthrough": [True],
    },
    "churn": {
        "enabled": [False, True],
        "swap_threshold": [2],
        "window_months": [6],
    },
    "macro_circuit": {
        "enabled": [False, True],
        "ma_window": [200],
        "confirm_days": [3],
        "halve_factor": [0.5],
    },
    "regime_capacity": {
        "enabled": [False, True],
        "bear_mult": [0.5],
        "deep_bear_mult": [0.25],
        "neutral_mult_main": [1.0],
        "neutral_mult_concentrated": [0.85],
    },
    "main_top_n": {
        # Post-hoc concentration of the main book. 0 = passthrough (~18 names);
        # 6/8/10 = keep only top-N by weight per rebalance, residual -> CASH.
        # Sweeps only main; concentrated ignores this knob.
        "values": [0, 6, 8, 10],
        "keep_cash_floor": True,
    },
    "redeploy": {
        # Crisis-aware residual-cash redeploy: on NORMAL dates push idle cash
        # into the held leaders up to caps (CAGR), on DEFENSE dates preserve the
        # governor's cash (MDD). False vs True so the broker replay A/Bs it.
        "values": [False, True],
        "min_cash_floor": 0.0,
    },
    "primary_cost_bps": 25.0,
    "cost_sweep_bps": [25, 50, 75, 100],
    "stress_windows": {
        # Inclusive date ranges sliced from equity_curve.csv to score crisis MDD.
        "covid_2020": ["2020-02-19", "2020-05-31"],
        "bear_2022": ["2022-01-03", "2022-10-14"],
    },
    # Intermediate, ACHIEVABLE gates. r1000_config target (main 30/-15, conc
    # 50/-18) sits above broker reality so goal_search returns blocked_both
    # for everything; these gates let the challenger actually rank progress.
    "intermediate_targets": {
        "main": {"cagr": 0.33, "max_dd": -0.25},
        "concentrated": {"cagr": 0.40, "max_dd": -0.28},
    },
    "stress_gates": {
        "main": {"covid_2020_mdd": -0.25, "bear_2022_mdd": -0.22},
        "concentrated": {"covid_2020_mdd": -0.30, "bear_2022_mdd": -0.28},
    },
    "cost_gate": {
        # Strategy must remain net-positive CAGR at this cost level.
        "min_positive_cagr_bps": 75,
    },
    "top_k_primary": 20,        # how many advance to pass 2
    "stability_neighbours": 5,  # top-k for the neighbourhood-median score
    "max_combos": 800,          # safety cap on the cartesian product
}


# ---------------------------------------------------------------------------
# Combination expansion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Combo:
    """A single overlay configuration to evaluate."""
    idx: int
    portfolio_kind: str  # "main" or "concentrated"
    conc_n: int          # concentrated_target_stock_n (0 = passthrough for main)
    conc_weighting: str  # "" (= use default) when not concentrated
    conc_rebal: int      # 0 = passthrough
    churn_enabled: bool
    churn_swap_threshold: int
    churn_window_months: int
    macro_enabled: bool
    macro_ma_window: int
    macro_confirm_days: int
    macro_halve_factor: float
    regime_enabled: bool
    regime_bear_mult: float
    regime_deep_bear_mult: float
    regime_neutral_mult: float
    main_top_n: int     # 0 = passthrough (main only; concentrated stays 0)
    redeploy: bool      # crisis-aware residual-cash redeploy on normal dates
    cost_bps: float

    def signature(self) -> str:
        bits = [self.portfolio_kind]
        if self.portfolio_kind == "concentrated":
            bits.append(f"N{self.conc_n}_{self.conc_weighting}_r{self.conc_rebal}m")
        bits.append(f"churn{int(self.churn_enabled)}_st{self.churn_swap_threshold}_w{self.churn_window_months}")
        bits.append(f"macro{int(self.macro_enabled)}_ma{self.macro_ma_window}_c{self.macro_confirm_days}_h{self.macro_halve_factor}")
        bits.append(f"regcap{int(self.regime_enabled)}_b{self.regime_bear_mult}_db{self.regime_deep_bear_mult}_n{self.regime_neutral_mult}")
        if self.portfolio_kind == "main" and self.main_top_n > 0:
            bits.append(f"topN{self.main_top_n}")
        bits.append(f"redeploy{int(self.redeploy)}")
        bits.append(f"cost{int(self.cost_bps)}bp")
        return "__".join(bits)


def expand_grid(grid: dict[str, Any], portfolio_kind: str, max_combos: int) -> list[Combo]:
    cc = grid["concentrated_champion"]
    ch = grid["churn"]
    mc = grid["macro_circuit"]
    rc = grid["regime_capacity"]
    primary_cost = float(grid.get("primary_cost_bps", 25.0))

    if portfolio_kind == "concentrated":
        champion_choices = [
            (int(n), str(w), int(r))
            for n in cc["target_stock_names"]
            for w in cc["weighting_mode"]
            for r in cc["rebalance_interval_months"]
        ]
    else:
        champion_choices = [(0, "", 0)]

    mt = grid.get("main_top_n", {"values": [0]})
    main_top_n_choices = list(mt.get("values", [0])) if portfolio_kind == "main" else [0]
    rdp = grid.get("redeploy", {"values": [False]})
    redeploy_choices = list(rdp.get("values", [False]))

    combos: list[Combo] = []
    idx = 0
    for (n, w, r) in champion_choices:
        for ce in ch["enabled"]:
            for st in (ch["swap_threshold"] if ce else [0]):
                for wm in (ch["window_months"] if ce else [0]):
                    for me in mc["enabled"]:
                        for ma in (mc["ma_window"] if me else [0]):
                            for cd in (mc["confirm_days"] if me else [0]):
                                for hf in (mc["halve_factor"] if me else [0.0]):
                                    for re_ in rc["enabled"]:
                                        for bm in (rc["bear_mult"] if re_ else [1.0]):
                                            for dbm in (rc["deep_bear_mult"] if re_ else [1.0]):
                                                neutral_key = "neutral_mult_concentrated" if portfolio_kind == "concentrated" else "neutral_mult_main"
                                                nm_default = rc.get(neutral_key, [1.0])[0]
                                                for nm in (rc.get(neutral_key, [nm_default]) if re_ else [1.0]):
                                                    for tn in main_top_n_choices:
                                                        for rd in redeploy_choices:
                                                            combos.append(Combo(
                                                                idx=idx,
                                                                portfolio_kind=portfolio_kind,
                                                                conc_n=n,
                                                                conc_weighting=w,
                                                                conc_rebal=r,
                                                                churn_enabled=bool(ce),
                                                                churn_swap_threshold=int(st),
                                                                churn_window_months=int(wm),
                                                                macro_enabled=bool(me),
                                                                macro_ma_window=int(ma),
                                                                macro_confirm_days=int(cd),
                                                                macro_halve_factor=float(hf),
                                                                regime_enabled=bool(re_),
                                                                regime_bear_mult=float(bm),
                                                                regime_deep_bear_mult=float(dbm),
                                                                regime_neutral_mult=float(nm),
                                                                main_top_n=int(tn),
                                                                redeploy=bool(rd),
                                                                cost_bps=primary_cost,
                                                            ))
                                                            idx += 1
                                                            if idx >= max_combos:
                                                                return combos
    return combos


# ---------------------------------------------------------------------------
# Filter chain + broker replay (subprocess to the existing tools)
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run a subprocess; return (returncode, tail_of_combined_output)."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    tail = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, tail[-2000:]


def apply_filter_chain(combo: Combo, base_book: Path, work_dir: Path, price_cache: Path) -> tuple[Path, list[str]]:
    """Apply enabled filters in order and return the path to the final book.
    Each filter writes a new book; non-enabled filters are skipped.

    Order matters: top-N concentration runs FIRST when the kind is main, then
    redeploy fills idle cash on normal dates, then the regime/churn/macro
    filters reshape the result. Redeploy before the capacity filters so those
    still get the final say on defense-date exposure."""
    cur = base_book
    log: list[str] = []
    work_dir.mkdir(parents=True, exist_ok=True)

    if combo.portfolio_kind == "main" and combo.main_top_n > 0:
        nxt = work_dir / "book_after_topn.csv"
        diag = work_dir / "topn_diag.json"
        cmd = [
            sys.executable, str(TOOLS / "run_main_top_n_concentration_filter.py"),
            "--input-book", str(cur), "--output-book", str(nxt),
            "--diagnostics", str(diag),
            "--top-n", str(combo.main_top_n),
        ]
        if DEFAULT_GRID["main_top_n"].get("keep_cash_floor"):
            cmd.append("--keep-cash-floor")
        rc, tail = _run(cmd, cwd=REPO_ROOT)
        log.append(f"topn rc={rc}")
        if rc != 0 or not nxt.exists():
            return cur, log + [f"topn FAILED, kept previous book; tail={tail}"]
        cur = nxt

    if combo.redeploy:
        nxt = work_dir / "book_after_redeploy.csv"
        diag = work_dir / "redeploy_diag.json"
        rc, tail = _run([
            sys.executable, str(TOOLS / "run_residual_cash_redeploy_filter.py"),
            "--input-book", str(cur), "--output-book", str(nxt),
            "--diagnostics", str(diag),
            "--portfolio-kind", combo.portfolio_kind,
            "--min-cash-floor", str(DEFAULT_GRID["redeploy"].get("min_cash_floor", 0.0)),
        ], cwd=REPO_ROOT)
        log.append(f"redeploy rc={rc}")
        if rc != 0 or not nxt.exists():
            return cur, log + [f"redeploy FAILED, kept previous book; tail={tail}"]
        cur = nxt

    if combo.churn_enabled:
        nxt = work_dir / "book_after_churn.csv"
        diag = work_dir / "churn_diag.json"
        rc, tail = _run([
            sys.executable, str(TOOLS / "run_neutral_regime_churn_filter.py"),
            "--input-book", str(cur), "--output-book", str(nxt),
            "--diagnostics", str(diag),
            "--swap-threshold", str(combo.churn_swap_threshold),
            "--window-months", str(combo.churn_window_months),
            "--target-regimes", "neutral",
        ], cwd=REPO_ROOT)
        log.append(f"churn rc={rc}")
        if rc != 0 or not nxt.exists():
            return cur, log + [f"churn FAILED, kept previous book; tail={tail}"]
        cur = nxt

    if combo.macro_enabled:
        nxt = work_dir / "book_after_macro.csv"
        diag = work_dir / "macro_diag.json"
        rc, tail = _run([
            sys.executable, str(TOOLS / "run_macro_circuit_breaker_filter.py"),
            "--input-book", str(cur), "--output-book", str(nxt),
            "--diagnostics", str(diag), "--price-cache", str(price_cache),
            "--ma-window", str(combo.macro_ma_window),
            "--confirm-days", str(combo.macro_confirm_days),
            "--halve-factor", str(combo.macro_halve_factor),
        ], cwd=REPO_ROOT)
        log.append(f"macro rc={rc}")
        if rc != 0 or not nxt.exists():
            return cur, log + [f"macro FAILED; tail={tail}"]
        cur = nxt

    if combo.regime_enabled:
        nxt = work_dir / "book_after_regime.csv"
        diag = work_dir / "regime_diag.json"
        mults = (
            f"bear={combo.regime_bear_mult},"
            f"deep_bear={combo.regime_deep_bear_mult},"
            f"neutral={combo.regime_neutral_mult}"
        )
        rc, tail = _run([
            sys.executable, str(TOOLS / "run_regime_capacity_filter.py"),
            "--input-book", str(cur), "--output-book", str(nxt),
            "--diagnostics", str(diag), "--multipliers", mults,
        ], cwd=REPO_ROOT)
        log.append(f"regime rc={rc}")
        if rc != 0 or not nxt.exists():
            return cur, log + [f"regime FAILED; tail={tail}"]
        cur = nxt

    return cur, log


def run_broker_replay(combo: Combo, target_book: Path, price_cache: Path, out_dir: Path, cost_bps: float) -> tuple[dict[str, Any], Optional[pd.DataFrame]]:
    """Invoke run_broker_ledger_replay.py for one combo + cost band.
    Returns (metrics_dict, equity_curve_df_or_None)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(TOOLS / "run_broker_ledger_replay.py"),
        "--target-book", str(target_book),
        "--price-cache", str(price_cache),
        "--portfolio-kind", combo.portfolio_kind,
        "--fill-mode", "next_close",
        "--cost-bps", str(cost_bps),
        "--output-dir", str(out_dir),
    ]
    if combo.portfolio_kind == "concentrated" and combo.conc_n > 0:
        cmd += [
            "--concentrated-target-stock-n", str(combo.conc_n),
            "--concentrated-weighting-mode", combo.conc_weighting,
            "--concentrated-rebalance-interval-months", str(combo.conc_rebal),
        ]
    rc, tail = _run(cmd, cwd=REPO_ROOT)
    metrics_path = out_dir / "metrics.json"
    if rc != 0 or not metrics_path.exists():
        return {"status": "blocked", "reason": f"broker_replay rc={rc}; tail={tail}"}, None
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    equity_path = out_dir / "equity_curve.csv"
    equity = pd.read_csv(equity_path) if equity_path.exists() else None
    return metrics, equity


# ---------------------------------------------------------------------------
# Stress-window MDD + ranking helpers
# ---------------------------------------------------------------------------

def stress_window_mdd(equity: pd.DataFrame, start: str, end: str) -> Optional[float]:
    """Max drawdown of the equity curve inside [start, end] (inclusive)."""
    if equity is None or equity.empty or "date" not in equity.columns or "equity_usd" not in equity.columns:
        return None
    eq = equity.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date")
    mask = (eq["date"] >= pd.Timestamp(start)) & (eq["date"] <= pd.Timestamp(end))
    win = eq.loc[mask, "equity_usd"].astype(float)
    if win.empty or len(win) < 2:
        return None
    running_max = win.cummax()
    dd = (win / running_max - 1.0).min()
    return float(dd)


def composite_primary_score(target_pass: bool, cagr: float, mdd: float, sharpe: float, stress_pass: bool) -> float:
    """Single-number primary screen score: gate-driven, with magnitude tiebreaker.
    Mirrors run_portfolio_goal_search.py spirit: pass gates get a big lift, then
    reward = cagr*100 + sharpe*2 - |mdd|*30."""
    gate = (1000.0 if target_pass else 0.0) + (300.0 if stress_pass else 0.0)
    reward = cagr * 100.0 + sharpe * 2.0 - abs(mdd) * 30.0
    return gate + reward


# ---------------------------------------------------------------------------
# Worker (evaluate one combo, primary pass)
# ---------------------------------------------------------------------------

def evaluate_combo_primary(args: tuple[Combo, str, str, str, dict[str, Any]]) -> dict[str, Any]:
    combo, base_book_str, price_cache_str, work_root_str, grid = args
    base_book = Path(base_book_str)
    price_cache = Path(price_cache_str)
    work_root = Path(work_root_str)
    combo_dir = work_root / f"combo_{combo.idx:04d}_{combo.portfolio_kind}"
    combo_dir.mkdir(parents=True, exist_ok=True)
    filter_dir = combo_dir / "filters"
    replay_dir = combo_dir / "broker_replay"
    final_book, filter_log = apply_filter_chain(combo, base_book, filter_dir, price_cache)
    metrics, equity = run_broker_replay(combo, final_book, price_cache, replay_dir, combo.cost_bps)

    row: dict[str, Any] = {
        "idx": combo.idx,
        "portfolio_kind": combo.portfolio_kind,
        "signature": combo.signature(),
        "filter_log": "; ".join(filter_log),
        "broker_status": metrics.get("status"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "trade_count": metrics.get("trade_count"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "valid_for_production": metrics.get("valid_for_production"),
        **{f"combo_{k}": v for k, v in asdict(combo).items() if k != "idx"},
    }

    targets = grid["intermediate_targets"].get(combo.portfolio_kind, {})
    cagr = row["cagr"] or 0.0
    mdd = row["max_dd"] or 0.0
    sharpe = row["sharpe"] or 0.0
    row["target_cagr"] = targets.get("cagr")
    row["target_max_dd"] = targets.get("max_dd")
    row["target_pass"] = bool(
        cagr >= (targets.get("cagr") or 0.0)
        and mdd >= (targets.get("max_dd") or -1.0)
    )

    sw = grid.get("stress_windows", {})
    for name, (start, end) in sw.items():
        row[f"stress_{name}_mdd"] = stress_window_mdd(equity, start, end) if equity is not None else None

    stress_gates = grid.get("stress_gates", {}).get(combo.portfolio_kind, {})
    stress_pass = True
    for name in sw:
        gate_key = f"{name}_mdd"
        gate = stress_gates.get(gate_key)
        val = row.get(f"stress_{name}_mdd")
        if gate is not None and val is not None and val < gate:
            stress_pass = False
            break
    row["stress_pass"] = stress_pass
    row["primary_score"] = composite_primary_score(
        target_pass=row["target_pass"],
        cagr=cagr, mdd=mdd, sharpe=sharpe,
        stress_pass=stress_pass,
    )
    return row


# ---------------------------------------------------------------------------
# Pass 2: cost sweep + stability neighbourhood-median
# ---------------------------------------------------------------------------

def evaluate_cost_sweep(combo: Combo, base_book: Path, price_cache: Path, work_root: Path, cost_bps_list: list[float]) -> dict[str, Any]:
    """Re-run broker replay across cost bands and report breakeven."""
    combo_dir = work_root / f"combo_{combo.idx:04d}_{combo.portfolio_kind}"
    filter_dir = combo_dir / "filters"
    final_book = max(
        [p for p in filter_dir.glob("book_after_*.csv")] + [base_book],
        key=lambda p: p.stat().st_mtime,
    )
    levels: list[dict[str, Any]] = []
    last_positive_bps = None
    for bps in cost_bps_list:
        cs_dir = combo_dir / f"cost_{int(bps)}"
        metrics, _ = run_broker_replay(combo, final_book, price_cache, cs_dir, float(bps))
        cagr = metrics.get("cagr")
        levels.append({
            "cost_bps": float(bps),
            "cagr": cagr,
            "max_dd": metrics.get("max_dd"),
            "sharpe": metrics.get("sharpe"),
        })
        if cagr is not None and cagr > 0:
            last_positive_bps = float(bps)
    return {"levels": levels, "max_positive_cagr_bps": last_positive_bps}


def neighbourhood_median_score(row: dict[str, Any], all_rows: list[dict[str, Any]], k: int) -> float:
    """Median primary_score across the k nearest neighbours of this combo in
    the grid (Hamming distance on the discrete knobs). Defeats single-row picks."""
    knob_keys = [
        "combo_conc_n", "combo_conc_weighting", "combo_conc_rebal",
        "combo_churn_enabled", "combo_churn_swap_threshold",
        "combo_macro_enabled", "combo_macro_confirm_days",
        "combo_regime_enabled", "combo_regime_bear_mult",
    ]

    def hamming(a: dict[str, Any], b: dict[str, Any]) -> int:
        return sum(1 for k_ in knob_keys if a.get(k_) != b.get(k_))

    same_kind = [r for r in all_rows if r["portfolio_kind"] == row["portfolio_kind"] and r["idx"] != row["idx"]]
    if not same_kind:
        return float(row.get("primary_score") or 0.0)
    ranked = sorted(same_kind, key=lambda r: hamming(row, r))[:max(1, k)]
    scores = [float(r.get("primary_score") or 0.0) for r in ranked]
    return float(pd.Series(scores).median())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-artifact", required=True,
                   help="Path to a downloaded full-rebuild outputs/ dir (must contain reports/operating_main_target_book.csv and reports/operating_concentrated_target_book.csv).")
    p.add_argument("--price-cache", default="cache_prices")
    p.add_argument("--output-dir", default="outputs/overlay_combination_search")
    p.add_argument("--grid", default="",
                   help="Optional JSON file overriding the default grid.")
    p.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-combos", type=int, default=None)
    return p.parse_args()


def load_grid(path: str) -> dict[str, Any]:
    if not path:
        return DEFAULT_GRID
    overrides = json.loads(Path(path).read_text(encoding="utf-8"))
    merged = json.loads(json.dumps(DEFAULT_GRID))  # deep copy
    merged.update(overrides)
    return merged


def main() -> int:
    args = parse_args()
    base = Path(args.base_artifact)
    if not base.exists():
        print(f"[overlay-search] ERROR: base artifact not found: {base}", file=sys.stderr)
        return 2

    price_cache = Path(args.price_cache)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root = out_dir / "work"
    work_root.mkdir(exist_ok=True)
    grid = load_grid(args.grid)
    if args.max_combos:
        grid["max_combos"] = args.max_combos

    kinds = ["main", "concentrated"] if args.portfolio_kind == "both" else [args.portfolio_kind]
    base_books = {
        "main": base / "reports" / "operating_main_target_book.csv",
        "concentrated": base / "reports" / "operating_concentrated_target_book.csv",
    }
    for k in kinds:
        if not base_books[k].exists():
            print(f"[overlay-search] ERROR: missing {base_books[k]}", file=sys.stderr)
            return 3

    print(f"[overlay-search] base={base}  kinds={kinds}  workers={args.workers}")
    all_combos: list[Combo] = []
    for k in kinds:
        combos = expand_grid(grid, k, grid["max_combos"])
        print(f"[overlay-search] {k}: {len(combos)} combos")
        all_combos.extend(combos)

    # ---------- Pass 1: primary screen, parallel across combos ----------
    worker_args = [
        (c, str(base_books[c.portfolio_kind]), str(price_cache), str(work_root), grid)
        for c in all_combos
    ]
    with mp.Pool(processes=max(1, args.workers)) as pool:
        rows = pool.map(evaluate_combo_primary, worker_args)

    # Attach neighbourhood-median stability (cheap, post-hoc on the rows we have).
    for r in rows:
        r["stability_median_score"] = neighbourhood_median_score(r, rows, grid["stability_neighbours"])

    # ---------- Pass 2: cost sweep on top-K (per portfolio kind) ----------
    K = int(grid["top_k_primary"])
    cost_results: dict[int, dict[str, Any]] = {}
    by_idx = {c.idx: c for c in all_combos}
    for k in kinds:
        kind_rows = [r for r in rows if r["portfolio_kind"] == k]
        kind_rows.sort(key=lambda r: (r["target_pass"], r["stress_pass"], r["primary_score"], r["stability_median_score"]), reverse=True)
        for r in kind_rows[:K]:
            c = by_idx[r["idx"]]
            sweep = evaluate_cost_sweep(c, base_books[k], price_cache, work_root, grid["cost_sweep_bps"])
            cost_results[r["idx"]] = sweep
            r["cost_sweep_levels"] = sweep["levels"]
            r["cost_max_positive_bps"] = sweep["max_positive_cagr_bps"]
            r["cost_pass"] = (sweep["max_positive_cagr_bps"] or 0) >= grid["cost_gate"]["min_positive_cagr_bps"]

    # ---------- Rank + champion per kind ----------
    summary: dict[str, Any] = {
        "base_artifact": str(base),
        "grid_used": grid,
        "n_combos_total": len(all_combos),
        "kinds": {},
    }
    for k in kinds:
        kind_rows = [r for r in rows if r["portfolio_kind"] == k]
        # Final ranking: hard gates first, then neighbourhood-median stability,
        # then raw primary score. cost_pass only defined for the top-K from
        # pass 2 — others stay None and sort below.
        def key(r: dict[str, Any]) -> tuple:
            return (
                bool(r.get("target_pass")),
                bool(r.get("stress_pass")),
                bool(r.get("cost_pass")) if r.get("cost_pass") is not None else False,
                float(r.get("stability_median_score") or -1e9),
                float(r.get("primary_score") or -1e9),
            )
        kind_rows.sort(key=key, reverse=True)
        champion = kind_rows[0] if kind_rows else None
        summary["kinds"][k] = {
            "n_combos": len(kind_rows),
            "champion": champion,
            "top_10": kind_rows[:10],
        }
        if champion is not None:
            c = by_idx[champion["idx"]]
            repro = [
                f"# Reproduce {k} champion:",
                f"python tools/run_broker_ledger_replay.py \\",
                f"  --target-book <FINAL_FILTERED_BOOK> \\",
                f"  --price-cache {args.price_cache} \\",
                f"  --portfolio-kind {k} \\",
                f"  --fill-mode next_close --cost-bps {c.cost_bps} \\",
            ]
            if k == "concentrated":
                repro.append(f"  --concentrated-target-stock-n {c.conc_n} \\")
                repro.append(f"  --concentrated-weighting-mode {c.conc_weighting} \\")
                repro.append(f"  --concentrated-rebalance-interval-months {c.conc_rebal}")
            summary["kinds"][k]["repro"] = "\n".join(repro)

    # ---------- Persist outputs ----------
    rank_df = pd.DataFrame(rows)
    rank_df.to_csv(out_dir / "overlay_search_ranking.csv", index=False)
    (out_dir / "overlay_search_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    champions = {k: summary["kinds"][k].get("champion") for k in kinds}
    (out_dir / "champion.json").write_text(
        json.dumps({"base_artifact": str(base), "champions": champions}, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[overlay-search] DONE. wrote {out_dir}/champion.json + ranking csv + summary json")
    for k in kinds:
        ch = summary["kinds"][k].get("champion")
        if ch is None:
            continue
        print(f"  {k} champion idx={ch['idx']} signature={ch['signature']} "
              f"cagr={ch.get('cagr')} mdd={ch.get('max_dd')} "
              f"target_pass={ch.get('target_pass')} stress_pass={ch.get('stress_pass')} "
              f"cost_pass={ch.get('cost_pass')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
