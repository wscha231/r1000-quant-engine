#!/usr/bin/env python3
"""Longitudinal performance ledger: the self-sustaining evaluation memory.

Every full rebuild appends ONE row to a persistent append-only JSONL ledger
that survives the per-date `cloud_results/full_rebuild/<date>` rotation. The
ledger is the system's cumulative memory: it lets any future run (or agent)
answer "is the engine actually improving run-over-run, and on which KPI?"
without re-deriving it from scattered per-date directories.

Each row captures, per portfolio (main + concentrated):
  - Tier-1 headline:  full_cagr, max_dd, sharpe, avg_cash, target_pass
  - Tier-2 honest:    is_cagr, oos_cagr, oos_is_ratio, strengthened_pass,
                      tier2_failing
  - Leak attribution: leak tags by year, structural_underinvestment_bull years

It then computes, against the existing ledger:
  - delta vs the immediately previous run
  - delta vs the best IS-CAGR ever recorded (the real KPI; see Tier-2 work)
  - a trend verdict per portfolio: IMPROVING / FLAT / REGRESSING on IS-CAGR
  - the dominant next-action (the most common leak tag still open)

Outputs:
  <ledger_dir>/ledger.jsonl        append-only, one row per run (persistent)
  <ledger_dir>/ledger_summary.md   human-readable trajectory of last N runs
  <ledger_dir>/latest_verdict.json the machine verdict for the current run

The IS-CAGR KPI is deliberately the headline the ledger trends on, because the
27498401423 evaluation proved full-period CAGR is OOS-inflated and misleading.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PORTFOLIOS = ("main", "concentrated")
# A move on IS-CAGR smaller than this (in CAGR fraction) is noise, not a trend.
IS_CAGR_FLAT_BAND = 0.005  # 0.5pp


def repo_path(p: str | Path) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (REPO / pp)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        return v if v == v else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _read_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_run_row(
    account_eval: dict[str, Any],
    is_attribution: dict[str, Any],
    *,
    run_id: str,
    commit: str,
    universe: str,
) -> dict[str, Any]:
    portfolios = account_eval.get("portfolios") or {}
    row: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": str(run_id),
        "commit": str(commit),
        "universe": str(universe),
        "official_metric_mode": account_eval.get("official_metric_mode") or "broker_ledger_next_close",
        "production_target_pass": bool(account_eval.get("production_target_pass")),
        "strengthened_pass": bool(account_eval.get("strengthened_pass")),
        "portfolios": {},
    }
    for kind in PORTFOLIOS:
        p = portfolios.get(kind) or {}
        attrib = (is_attribution.get(kind) or {}) if isinstance(is_attribution, dict) else {}
        row["portfolios"][kind] = {
            "full_cagr": _safe_float(p.get("cagr")),
            "is_cagr": _safe_float(p.get("is_cagr") if p.get("is_cagr") is not None else attrib.get("is_cagr")),
            "oos_cagr": _safe_float(p.get("oos_cagr") if p.get("oos_cagr") is not None else attrib.get("oos_cagr")),
            "max_dd": _safe_float(p.get("max_dd")),
            "sharpe": _safe_float(p.get("sharpe")),
            "avg_cash_weight": _safe_float(p.get("avg_cash_weight")),
            "target_pass": bool(p.get("target_pass")),
            "strengthened_pass": bool(p.get("strengthened_pass")),
            "tier2_failing": list(p.get("tier2_failing") or []),
            "underinvestment_bull_years": list(attrib.get("structural_underinvestment_bull_years") or []),
            "leak_year_tags": dict(attrib.get("leak_year_tags") or {}),
        }
    return row


def _is_cagr(row: dict[str, Any], kind: str) -> float | None:
    return _safe_float(((row.get("portfolios") or {}).get(kind) or {}).get("is_cagr"))


def compute_verdict(
    current: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    """Trend the ledger on IS-CAGR (the honest KPI) per portfolio."""
    prior = [r for r in history if r.get("run_id") != current.get("run_id")]
    prev = prior[-1] if prior else None
    verdict: dict[str, Any] = {"per_portfolio": {}, "overall": "FIRST_RUN" if not prior else None}
    overall_states: list[str] = []
    for kind in PORTFOLIOS:
        cur_is = _is_cagr(current, kind)
        prev_is = _is_cagr(prev, kind) if prev else None
        # best IS-CAGR ever recorded (excluding current)
        best_is = None
        best_run = None
        for r in prior:
            v = _is_cagr(r, kind)
            if v is not None and (best_is is None or v > best_is):
                best_is = v
                best_run = r.get("run_id")
        delta_prev = (cur_is - prev_is) if (cur_is is not None and prev_is is not None) else None
        delta_best = (cur_is - best_is) if (cur_is is not None and best_is is not None) else None
        if delta_prev is None:
            state = "FIRST_RUN"
        elif delta_prev > IS_CAGR_FLAT_BAND:
            state = "IMPROVING"
        elif delta_prev < -IS_CAGR_FLAT_BAND:
            state = "REGRESSING"
        else:
            state = "FLAT"
        new_best = bool(cur_is is not None and (best_is is None or cur_is > best_is))
        overall_states.append(state)
        verdict["per_portfolio"][kind] = {
            "is_cagr": cur_is,
            "prev_is_cagr": prev_is,
            "best_is_cagr": best_is,
            "best_is_run": best_run,
            "delta_vs_prev_pp": None if delta_prev is None else round(delta_prev * 100, 4),
            "delta_vs_best_pp": None if delta_best is None else round(delta_best * 100, 4),
            "state": state,
            "new_best": new_best,
        }
    if verdict["overall"] is None:
        if "REGRESSING" in overall_states:
            verdict["overall"] = "REGRESSING"
        elif "IMPROVING" in overall_states:
            verdict["overall"] = "IMPROVING"
        else:
            verdict["overall"] = "FLAT"
    # dominant open leak across both books = the system's recommended next focus
    leak_counts: dict[str, int] = {}
    for kind in PORTFOLIOS:
        for tag in ((current.get("portfolios") or {}).get(kind) or {}).get("leak_year_tags", {}).values():
            if tag in ("structural_underinvestment_bull", "flat_alpha_invested"):
                leak_counts[f"{kind}:{tag}"] = leak_counts.get(f"{kind}:{tag}", 0) + 1
    verdict["dominant_open_leak"] = max(leak_counts, key=leak_counts.get) if leak_counts else None
    verdict["open_leak_counts"] = leak_counts
    return verdict


def _render_summary(history: list[dict[str, Any]], verdict: dict[str, Any], last_n: int = 12) -> str:
    lines = ["# Performance Ledger IS-CAGR Trajectory", ""]
    lines.append(f"- Overall trend this run: **{verdict.get('overall')}**")
    dl = verdict.get("dominant_open_leak")
    lines.append(f"- Dominant open leak (recommended next focus): `{dl or 'none'}`")
    lines.append("")
    for kind in PORTFOLIOS:
        pv = verdict["per_portfolio"].get(kind, {})
        lines.append(f"## {kind.title()}")
        is_c = pv.get("is_cagr")
        best = pv.get("best_is_cagr")
        dprev = pv.get("delta_vs_prev_pp")
        lines.append(
            f"- IS-CAGR `{(is_c*100 if is_c is not None else float('nan')):.2f}%` "
            f"| state **{pv.get('state')}** "
            f"| delta prev `{('%+.2fpp' % dprev) if dprev is not None else 'n/a'}` "
            f"| best `{(best*100 if best is not None else float('nan')):.2f}%`"
            f"{'  NEW BEST' if pv.get('new_best') else ''}"
        )
    lines.append("")
    lines.append(f"## Last {last_n} runs")
    lines.append("")
    lines.append("| Run | Commit | Main IS | Main full | Conc IS | Conc full | Strengthened |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | :---: |")
    for r in history[-last_n:]:
        mp = (r.get("portfolios") or {}).get("main") or {}
        cp = (r.get("portfolios") or {}).get("concentrated") or {}
        def pct(x):
            v = _safe_float(x)
            return f"{v*100:.2f}%" if v is not None else "n/a"
        lines.append(
            f"| {str(r.get('run_id'))[:12]} | {str(r.get('commit'))[:8]} | "
            f"{pct(mp.get('is_cagr'))} | {pct(mp.get('full_cagr'))} | "
            f"{pct(cp.get('is_cagr'))} | {pct(cp.get('full_cagr'))} | "
            f"{'OK' if r.get('strengthened_pass') else 'no'} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    account_eval = _read_json(latest_run / "account_evaluation" / "official_metrics.json")
    if not account_eval:
        account_eval = _read_json(repo_path(args.account_eval)) if args.account_eval else {}
    is_attribution = _read_json(latest_run / "is_attribution" / "summary.json")
    if not is_attribution and args.is_attribution:
        is_attribution = _read_json(repo_path(args.is_attribution))

    ledger_dir = repo_path(args.ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "ledger.jsonl"
    history = _read_ledger(ledger_path)

    row = build_run_row(
        account_eval, is_attribution,
        run_id=args.run_id, commit=args.commit, universe=args.universe,
    )
    # dedup by run_id: re-running the ledger for the same run replaces its row
    history = [r for r in history if r.get("run_id") != row.get("run_id")]
    full_history = history + [row]

    verdict = compute_verdict(row, full_history)

    # persist (append-only semantics, but rewrite to honor the dedup)
    with ledger_path.open("w", encoding="utf-8") as fh:
        for r in full_history:
            fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    (ledger_dir / "ledger_summary.md").write_text(_render_summary(full_history, verdict), encoding="utf-8")
    (ledger_dir / "latest_verdict.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")

    print(f"[ledger] rows={len(full_history)} overall={verdict['overall']} next_focus={verdict.get('dominant_open_leak')}")
    for kind in PORTFOLIOS:
        pv = verdict["per_portfolio"][kind]
        dprev = pv.get("delta_vs_prev_pp")
        print(f"  {kind:13} IS-CAGR {('%.2f%%' % (pv['is_cagr']*100)) if pv['is_cagr'] is not None else 'n/a':>8}  "
              f"state={pv['state']:<10} dprev={('%+.2fpp' % dprev) if dprev is not None else 'n/a':>9}"
              f"{'  NEW BEST' if pv['new_best'] else ''}")
    return verdict


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--latest-run", default="outputs")
    p.add_argument("--ledger-dir", default="cloud_results/performance_ledger")
    p.add_argument("--account-eval", default="")
    p.add_argument("--is-attribution", default="")
    p.add_argument("--run-id", default="local")
    p.add_argument("--commit", default="unknown")
    p.add_argument("--universe", default="global_alpha_universe")
    args = p.parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
