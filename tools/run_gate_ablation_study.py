"""Gate Ablation Study — measure each cap gate's CAGR cost vs MDD benefit.

For a single FROZEN base artifact (full-rebuild ``outputs/`` dir), evaluate
N+2 broker-ledger replays:

  baseline    — the unmodified operating target book.
  per-gate    — for each pre_<gate>_weight column found in the book, restore
                that single gate only; everything else stays as the engine cut.
  all-restore — restore EVERY pre_*_weight (upper-bound: "no regulation").

We rank gates by (CAGR_lift_pp, MDD_change_pp, sharpe_lift) vs the baseline
and label each one:

  PURE_DRAG       — CAGR_lift > +0.5pp AND MDD_change >= -1.5pp   (strip OK)
  EARNED          — CAGR_lift > 0     AND MDD_change <= -3.0pp    (keep, real protection)
  NEUTRAL         — small effect both axes                         (cosmetic)
  MIXED           — strong on both axes                            (judgment call)
  CAGR_DRAG_HEAVY — CAGR_lift > +1.0pp AND MDD_change >= -1.0pp    (definitely strip)
  PROTECTION      — CAGR drops but MDD improves                    (keep)

This gives a concrete, broker-daily attribution: which 규제 are pure drag
(strip them, lift CAGR with no MDD cost) versus which earn their CAGR cost
through real MDD protection.

Research-only. Never mutates the base artifact, target books, live policy.
Writes outputs/gate_ablation_study/gate_ablation_summary.json,
gate_ablation_ranking.csv, gate_ablation_report.md.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = REPO_ROOT / "tools"

STRESS_WINDOWS = {
    "covid_2020": ("2020-02-19", "2020-05-31"),
    "bear_2022": ("2022-01-03", "2022-10-14"),
}


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    tail = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, tail[-2000:]


def discover_gates(base_book: Path) -> list[str]:
    """List every gate name present as pre_<gate>_weight in the input book."""
    header = pd.read_csv(base_book, nrows=0).columns.tolist()
    return sorted(
        c[len("pre_"):-len("_weight")]
        for c in header
        if c.startswith("pre_") and c.endswith("_weight")
    )


def apply_gate_filter(restore_gates: list[str], base_book: Path, work_dir: Path) -> Optional[Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    out_book = work_dir / "ablated_book.csv"
    diag = work_dir / "ablation_diag.json"
    cmd = [
        sys.executable, str(TOOLS / "run_gate_ablation_filter.py"),
        "--input-book", str(base_book), "--output-book", str(out_book),
        "--diagnostics", str(diag),
        "--restore-gates", *restore_gates,
    ]
    rc, tail = _run(cmd)
    if rc != 0 or not out_book.exists():
        print(f"[ablation] FAIL apply restore_gates={restore_gates}: rc={rc} tail={tail}", file=sys.stderr)
        return None
    return out_book


def run_broker_replay(
    target_book: Path,
    price_cache: Path,
    portfolio_kind: str,
    out_dir: Path,
    cost_bps: float,
    # Concentrated champion override — pass through to broker replay.
    conc_n: int = 0,
    conc_weighting: str = "",
    conc_rebal: int = 0,
) -> tuple[Optional[dict[str, Any]], Optional[pd.DataFrame]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, str(TOOLS / "run_broker_ledger_replay.py"),
        "--target-book", str(target_book),
        "--price-cache", str(price_cache),
        "--portfolio-kind", portfolio_kind,
        "--fill-mode", "next_close",
        "--cost-bps", str(cost_bps),
        "--output-dir", str(out_dir),
    ]
    if portfolio_kind == "concentrated" and conc_n > 0:
        cmd += [
            "--concentrated-target-stock-n", str(conc_n),
            "--concentrated-weighting-mode", conc_weighting,
            "--concentrated-rebalance-interval-months", str(conc_rebal),
        ]
    rc, tail = _run(cmd)
    metrics_path = out_dir / "metrics.json"
    if rc != 0 or not metrics_path.exists():
        print(f"[ablation] broker_replay FAIL on {target_book.name}: rc={rc} tail={tail}", file=sys.stderr)
        return None, None
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    equity_path = out_dir / "equity_curve.csv"
    equity = pd.read_csv(equity_path) if equity_path.exists() else None
    return metrics, equity


def stress_mdd(equity: pd.DataFrame, start: str, end: str) -> Optional[float]:
    if equity is None or equity.empty or "date" not in equity.columns or "equity_usd" not in equity.columns:
        return None
    eq = equity.copy()
    eq["date"] = pd.to_datetime(eq["date"], errors="coerce")
    eq = eq.dropna(subset=["date"]).sort_values("date")
    win = eq.loc[(eq["date"] >= pd.Timestamp(start)) & (eq["date"] <= pd.Timestamp(end)), "equity_usd"].astype(float)
    if win.empty or len(win) < 2:
        return None
    return float((win / win.cummax() - 1.0).min())


def classify(cagr_lift_pp: float, mdd_change_pp: float) -> str:
    """Label a gate's ablation effect. Thresholds are intentionally conservative."""
    if cagr_lift_pp > 1.0 and mdd_change_pp >= -1.0:
        return "CAGR_DRAG_HEAVY"
    if cagr_lift_pp > 0.5 and mdd_change_pp >= -1.5:
        return "PURE_DRAG"
    if cagr_lift_pp > 0.0 and mdd_change_pp <= -3.0:
        return "EARNED"
    if cagr_lift_pp <= 0.0 and mdd_change_pp <= -1.0:
        return "PROTECTION"
    if abs(cagr_lift_pp) > 1.0 and abs(mdd_change_pp) > 3.0:
        return "MIXED"
    return "NEUTRAL"


def evaluate_variant(args: tuple) -> dict[str, Any]:
    label, restore_gates, base_book_str, price_cache_str, portfolio_kind, work_root_str, cost_bps, champion = args
    base_book = Path(base_book_str)
    price_cache = Path(price_cache_str)
    work_root = Path(work_root_str)
    work_dir = work_root / f"variant_{label}"
    if not restore_gates:
        # Baseline — replay the base book as-is.
        target = base_book
    else:
        target = apply_gate_filter(restore_gates, base_book, work_dir / "filter")
        if target is None:
            return {"label": label, "status": "filter_failed"}
    replay_dir = work_dir / "replay"
    metrics, equity = run_broker_replay(
        target, price_cache, portfolio_kind, replay_dir, cost_bps,
        conc_n=champion.get("n", 0),
        conc_weighting=champion.get("weighting", ""),
        conc_rebal=champion.get("rebal", 0),
    )
    if metrics is None:
        return {"label": label, "status": "replay_failed"}
    row = {
        "label": label,
        "restored_gates": restore_gates,
        "status": metrics.get("status"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "trade_count": metrics.get("trade_count"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "ending_capital_usd": metrics.get("ending_capital_usd"),
        "max_dd_peak_date": metrics.get("max_dd_peak_date"),
        "max_dd_trough_date": metrics.get("max_dd_trough_date"),
    }
    for name, (a, b) in STRESS_WINDOWS.items():
        row[f"stress_{name}_mdd"] = stress_mdd(equity, a, b)
    return row


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-artifact", required=True, help="Path to a downloaded full-rebuild outputs/ dir.")
    p.add_argument("--price-cache", default="cache_prices")
    p.add_argument("--output-dir", default="outputs/gate_ablation_study")
    p.add_argument("--portfolio-kind", choices=["main", "concentrated"], default="concentrated")
    p.add_argument("--cost-bps", type=float, default=25.0)
    p.add_argument("--workers", type=int, default=3)
    # Pass-through concentrated champion knobs (broker replay's own filter is
    # otherwise driven by concentrated_strategy_comparison.csv's row 0).
    p.add_argument("--concentrated-target-stock-n", type=int, default=0)
    p.add_argument("--concentrated-weighting-mode", default="")
    p.add_argument("--concentrated-rebalance-interval-months", type=int, default=0)
    p.add_argument("--include-all-restore", action="store_true",
                   help="Add a single 'ALL_RESTORE' variant restoring every pre_*_weight (upper bound).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    base = Path(args.base_artifact)
    if not base.exists():
        print(f"[ablation] ERROR: base artifact not found: {base}", file=sys.stderr)
        return 2
    book_path = base / "reports" / f"operating_{args.portfolio_kind}_target_book.csv"
    if not book_path.exists():
        print(f"[ablation] ERROR: missing {book_path}", file=sys.stderr)
        return 3
    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    work_root = out_dir / "work"; work_root.mkdir(exist_ok=True)
    champion = {
        "n": int(args.concentrated_target_stock_n),
        "weighting": args.concentrated_weighting_mode,
        "rebal": int(args.concentrated_rebalance_interval_months),
    }

    gates = discover_gates(book_path)
    print(f"[ablation] base={base}  kind={args.portfolio_kind}  gates_found={len(gates)}")
    for g in gates:
        print(f"    {g}")

    # Build the variant queue.
    variants: list[tuple] = []
    variants.append(("BASELINE", [], str(book_path), str(args.price_cache), args.portfolio_kind,
                     str(work_root), float(args.cost_bps), champion))
    for g in gates:
        label = f"restore__{g}"
        variants.append((label, [g], str(book_path), str(args.price_cache), args.portfolio_kind,
                         str(work_root), float(args.cost_bps), champion))
    if args.include_all_restore:
        variants.append(("ALL_RESTORE", ["ALL"], str(book_path), str(args.price_cache), args.portfolio_kind,
                         str(work_root), float(args.cost_bps), champion))

    print(f"[ablation] running {len(variants)} broker-replays with {args.workers} workers")
    if args.workers > 1:
        with mp.Pool(processes=max(1, args.workers)) as pool:
            rows = pool.map(evaluate_variant, variants)
    else:
        rows = [evaluate_variant(v) for v in variants]

    by_label = {r["label"]: r for r in rows if isinstance(r, dict)}
    baseline = by_label.get("BASELINE")
    if not baseline or baseline.get("status") != "completed":
        print("[ablation] ERROR: baseline replay did not complete; aborting attribution.", file=sys.stderr)
        (out_dir / "gate_ablation_summary.json").write_text(json.dumps({
            "status": "blocked",
            "reason": "baseline_failed",
            "rows": rows,
        }, indent=2, default=str), encoding="utf-8")
        return 4

    # Compute lifts vs baseline.
    bcagr = float(baseline.get("cagr") or 0.0)
    bmdd = float(baseline.get("max_dd") or 0.0)
    bsharpe = float(baseline.get("sharpe") or 0.0)
    for r in rows:
        if r.get("status") != "completed":
            r["classification"] = "FAILED"; continue
        if r["label"] == "BASELINE":
            r["classification"] = "BASELINE"; continue
        cagr_lift_pp = (float(r["cagr"]) - bcagr) * 100.0
        mdd_change_pp = (float(r["max_dd"]) - bmdd) * 100.0  # >0 = MDD got LESS bad (i.e., -29% -> -25% = +4pp)
        sharpe_lift = float(r["sharpe"]) - bsharpe
        r["cagr_lift_pp"] = round(cagr_lift_pp, 3)
        r["mdd_change_pp"] = round(mdd_change_pp, 3)
        r["sharpe_lift"] = round(sharpe_lift, 4)
        r["classification"] = classify(cagr_lift_pp, mdd_change_pp)

    # Persist outputs.
    rank_df = pd.DataFrame(rows)
    rank_df = rank_df.sort_values(["classification", "cagr_lift_pp"], ascending=[True, False])
    rank_df.to_csv(out_dir / "gate_ablation_ranking.csv", index=False)
    summary = {
        "base_artifact": str(base),
        "portfolio_kind": args.portfolio_kind,
        "cost_bps": args.cost_bps,
        "baseline": baseline,
        "gates_evaluated": len(gates),
        "rows": rows,
    }
    (out_dir / "gate_ablation_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # Markdown report — focused, table-only.
    lines = [
        f"# Gate Ablation Study — {args.portfolio_kind}",
        "",
        f"Base: `{base}` · cost {args.cost_bps}bps",
        "",
        f"Baseline broker-daily: CAGR **{bcagr:.2%}** · MDD **{bmdd:.2%}** · Sharpe {bsharpe:.4f}",
        "",
        "| Gate (restored) | CAGR | ΔCAGR pp | MDD | ΔMDD pp | Sharpe | Class |",
        "|---|---:|---:|---:|---:|---:|:---|",
    ]
    for r in rows:
        if r.get("status") != "completed" or r["label"] == "BASELINE":
            continue
        lines.append(
            f"| {r['label']} | {float(r['cagr']):.2%} | {r['cagr_lift_pp']:+.2f} | "
            f"{float(r['max_dd']):.2%} | {r['mdd_change_pp']:+.2f} | "
            f"{float(r['sharpe']):.3f} | **{r['classification']}** |"
        )
    if args.include_all_restore and "ALL_RESTORE" in by_label:
        ar = by_label["ALL_RESTORE"]
        lines += [
            "",
            f"**Upper bound (every pre_*_weight restored):** CAGR {float(ar['cagr']):.2%}  "
            f"MDD {float(ar['max_dd']):.2%}  Sharpe {float(ar['sharpe']):.3f}",
        ]
    (out_dir / "gate_ablation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Print top action items.
    def pp(c): return [r for r in rows if r.get("classification") == c]
    print("\n=== gate classification ===")
    for cls in ("CAGR_DRAG_HEAVY", "PURE_DRAG", "EARNED", "PROTECTION", "MIXED", "NEUTRAL"):
        hits = pp(cls)
        if not hits: continue
        print(f"  {cls}: {len(hits)}")
        for r in hits[:5]:
            print(f"    {r['label']:60s}  ΔCAGR {r.get('cagr_lift_pp', 0):+.2f}pp  ΔMDD {r.get('mdd_change_pp', 0):+.2f}pp")
    print(f"\n[ablation] DONE. wrote {out_dir}/gate_ablation_report.md + ranking csv + summary json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
