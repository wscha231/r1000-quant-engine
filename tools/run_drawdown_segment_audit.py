#!/usr/bin/env python3
"""Phase E1 — Drawdown Segment Audit (CODEX_HANDOFF v3.6 §17.2)

Read-only truth-finding tool. For each portfolio (main + concentrated), it
walks the equity curve, identifies every drawdown >= 10%, and records what
the engine was doing during each segment (cash %, position count, DD breaker
state, SPY drawdown for context).

This audit is BLOCKING input for Phase E2-E7 design (crisis governor):
- If 2022 main DD was mostly "held losers without trimming" → Phase F
  (hold-vs-replace) is the highest-leverage fix.
- If 2022 main DD was mostly "late new-buy throttle" → Phase E5 (exposure
  ladder) is the highest-leverage fix.
- If 2020 concentrated DD was mostly "no exposure cut at all" → Phase E
  governor itself is the priority.

The tool is FORWARD-COMPATIBLE: when a broker-ledger equity curve lands
under `outputs/broker_ledger_replay/`, the script auto-detects and prefers
it over the legacy `equity_curve.csv`. Until then, it analyses the legacy
research output (acknowledged in the report).

Usage:
    py -3 tools/run_drawdown_segment_audit.py
    py -3 tools/run_drawdown_segment_audit.py --base-dir /path/to/outputs
    py -3 tools/run_drawdown_segment_audit.py --threshold 0.05  # 5% DDs

Outputs:
    outputs/drawdown_segments/main.csv
    outputs/drawdown_segments/concentrated.csv
    outputs/drawdown_segments/report.md

Plan reference:
    CODEX_HANDOFF_PLAN_C_V3_5_20260520.md §17.2
    research/final_integrated_engine_20260524/plan.md §2 E1
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
DEFAULT_OUTPUTS = ROOT / "outputs"
DEFAULT_SEGMENT_DIR = DEFAULT_OUTPUTS / "drawdown_segments"


# ---------------------------------------------------------------------------
# Equity curve discovery (forward-compatible with future broker-ledger output)
# ---------------------------------------------------------------------------


@dataclass
class EquitySource:
    label: str          # "main" / "concentrated"
    path: Path
    is_broker_ledger: bool
    date_col: str
    equity_col: str
    return_col: Optional[str] = None
    benchmark_col: Optional[str] = None
    cash_weight_col: Optional[str] = None
    breaker_col: Optional[str] = None


def _discover_main_equity(outputs_dir: Path) -> Optional[EquitySource]:
    """Prefer broker-ledger output when it exists; fall back to legacy."""
    broker = outputs_dir / "broker_ledger_replay" / "main_equity_curve.csv"
    if broker.exists():
        return EquitySource(
            label="main",
            path=broker,
            is_broker_ledger=True,
            date_col="date",
            equity_col="equity",
            return_col="net_return",
            benchmark_col="benchmark_equity",
            cash_weight_col="cash_weight",
            breaker_col="dd_breaker_level",
        )
    legacy = outputs_dir / "equity_curve.csv"
    if legacy.exists():
        return EquitySource(
            label="main",
            path=legacy,
            is_broker_ledger=False,
            date_col="rebalance_date",
            equity_col="equity",
            return_col="net_return",
            benchmark_col="benchmark_equity",
            cash_weight_col="cash_weight",
            breaker_col="dd_breaker_level",
        )
    return None


def _discover_concentrated_equity(outputs_dir: Path) -> Optional[EquitySource]:
    broker = outputs_dir / "broker_ledger_replay" / "concentrated_equity_curve.csv"
    if broker.exists():
        return EquitySource(
            label="concentrated",
            path=broker,
            is_broker_ledger=True,
            date_col="date",
            equity_col="equity",
            return_col="net_return",
            benchmark_col="benchmark_equity",
            cash_weight_col="cash_weight",
        )
    monthly = outputs_dir / "reports" / "concentrated_strategy_monthly.csv"
    if monthly.exists():
        return EquitySource(
            label="concentrated",
            path=monthly,
            is_broker_ledger=False,
            date_col="rebalance_date",
            equity_col="equity",
            return_col="net_return",
            benchmark_col="benchmark_equity",
        )
    return None


# ---------------------------------------------------------------------------
# Drawdown segment computation
# ---------------------------------------------------------------------------


def _ensure_sorted_datetime(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    return out


def compute_segments(
    df: pd.DataFrame, src: EquitySource, threshold: float = 0.10
) -> pd.DataFrame:
    """Identify peak-to-trough drawdown segments deeper than `threshold`.

    Each segment runs from a NEW all-time peak to the trough that follows
    (or the latest available date if recovery has not yet happened).
    """
    if df.empty or src.equity_col not in df.columns:
        return pd.DataFrame()
    df = _ensure_sorted_datetime(df, src.date_col)
    eq = pd.to_numeric(df[src.equity_col], errors="coerce")
    if eq.dropna().empty:
        return pd.DataFrame()
    running_peak = eq.cummax()
    drawdown = (eq / running_peak) - 1.0
    df = df.assign(_equity=eq, _running_peak=running_peak, _drawdown=drawdown)

    # Walk forward: collect (peak_date, trough_date, recovery_date) tuples.
    segments: list[dict] = []
    in_dd = False
    peak_idx = 0
    trough_idx = 0
    for i in range(len(df)):
        dd = df["_drawdown"].iloc[i]
        if not in_dd:
            if pd.notna(dd) and dd <= -threshold:
                in_dd = True
                # Peak = LATEST index j < i where eq == running_peak.
                # (`first_valid_index` would return the earliest time that
                # peak level was first hit, which mis-attributes drawdowns
                # that occur after a flat recovery to the wrong peak date.)
                peak_val = df["_running_peak"].iloc[i]
                eq_eq_peak = df["_equity"] == peak_val
                idx_before = eq_eq_peak.iloc[:i + 1]
                peak_idx = int(idx_before[idx_before].index[-1]) if idx_before.any() else 0
                trough_idx = i
        else:
            if dd < df["_drawdown"].iloc[trough_idx]:
                trough_idx = i
            if pd.notna(dd) and dd >= -1e-6:
                # Recovered (equity reclaimed peak)
                segments.append(
                    _build_segment_row(df, src, peak_idx, trough_idx, recovery_idx=i)
                )
                in_dd = False
                peak_idx = trough_idx = 0
    # Open drawdown at the end
    if in_dd:
        segments.append(
            _build_segment_row(df, src, peak_idx, trough_idx, recovery_idx=None)
        )
    return pd.DataFrame(segments)


def _build_segment_row(
    df: pd.DataFrame,
    src: EquitySource,
    peak_idx: int,
    trough_idx: int,
    recovery_idx: Optional[int],
) -> dict:
    peak_row = df.iloc[peak_idx]
    trough_row = df.iloc[trough_idx]
    out: dict = {
        "peak_date": peak_row[src.date_col].date().isoformat(),
        "peak_equity": float(peak_row["_equity"]),
        "trough_date": trough_row[src.date_col].date().isoformat(),
        "trough_equity": float(trough_row["_equity"]),
        "drawdown_pct": float(trough_row["_drawdown"]),
        "days_peak_to_trough": int(
            (trough_row[src.date_col] - peak_row[src.date_col]).days
        ),
    }
    # Find first crossings of -10/-20/-30
    segment = df.iloc[peak_idx : trough_idx + 1]
    for thr in (0.10, 0.20, 0.30):
        below = segment[segment["_drawdown"] <= -thr]
        if not below.empty:
            first_date = below[src.date_col].iloc[0]
            out[f"first_below_{int(thr*100)}pct_date"] = first_date.date().isoformat()
            out[f"days_peak_to_below_{int(thr*100)}pct"] = int(
                (first_date - peak_row[src.date_col]).days
            )
        else:
            out[f"first_below_{int(thr*100)}pct_date"] = None
            out[f"days_peak_to_below_{int(thr*100)}pct"] = None
    # Recovery
    if recovery_idx is not None:
        rec_row = df.iloc[recovery_idx]
        out["recovery_date"] = rec_row[src.date_col].date().isoformat()
        out["days_trough_to_recovery"] = int(
            (rec_row[src.date_col] - trough_row[src.date_col]).days
        )
    else:
        out["recovery_date"] = None
        out["days_trough_to_recovery"] = None
    # Cash weight + DD breaker diagnostics (if available)
    if src.cash_weight_col and src.cash_weight_col in df.columns:
        cw = pd.to_numeric(df[src.cash_weight_col], errors="coerce")
        out["cash_weight_at_peak"] = _safe(cw.iloc[peak_idx])
        out["cash_weight_at_trough"] = _safe(cw.iloc[trough_idx])
        out["cash_weight_avg_during_dd"] = _safe(cw.iloc[peak_idx : trough_idx + 1].mean())
        out["cash_weight_max_during_dd"] = _safe(cw.iloc[peak_idx : trough_idx + 1].max())
    else:
        out["cash_weight_at_peak"] = None
        out["cash_weight_at_trough"] = None
        out["cash_weight_avg_during_dd"] = None
        out["cash_weight_max_during_dd"] = None
    if src.breaker_col and src.breaker_col in df.columns:
        levels = pd.to_numeric(df[src.breaker_col], errors="coerce").fillna(0)
        out["max_dd_breaker_level"] = int(levels.iloc[peak_idx : trough_idx + 1].max())
        out["breaker_activations_during_dd"] = int(
            (levels.iloc[peak_idx : trough_idx + 1].diff().fillna(0) > 0).sum()
        )
    else:
        out["max_dd_breaker_level"] = None
        out["breaker_activations_during_dd"] = None
    # Benchmark comparison
    if src.benchmark_col and src.benchmark_col in df.columns:
        bench = pd.to_numeric(df[src.benchmark_col], errors="coerce")
        if pd.notna(bench.iloc[peak_idx]) and bench.iloc[peak_idx] > 0:
            bench_seg = bench.iloc[peak_idx : trough_idx + 1]
            bench_peak = bench_seg.max()
            bench_trough = bench_seg.min()
            if pd.notna(bench_peak) and bench_peak > 0:
                out["spy_drawdown_same_window"] = float(
                    (bench_trough / bench_peak) - 1.0
                )
            else:
                out["spy_drawdown_same_window"] = None
        else:
            out["spy_drawdown_same_window"] = None
    else:
        out["spy_drawdown_same_window"] = None
    # Crisis archetype classification (rule-of-thumb only; refined by Phase E3).
    # Anchor: 2020 COVID (~30d peak->trough, -34%) is shock_crash;
    # 2022 rate hike (~330d peak->trough, -25%) is slow_bear.
    dd = out["drawdown_pct"]
    dpt = out["days_peak_to_trough"]
    if dd >= -0.15:
        out["likely_archetype"] = "normal_pullback"
    elif dpt <= 45:
        out["likely_archetype"] = "shock_crash"
    elif dpt > 45 and dd <= -0.20:
        out["likely_archetype"] = "slow_bear"
    else:
        out["likely_archetype"] = "mixed"
    return out


def _safe(x) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if np.isnan(v):
            return None
        return round(v, 6)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_report(
    main_src: Optional[EquitySource],
    main_segments: pd.DataFrame,
    conc_src: Optional[EquitySource],
    conc_segments: pd.DataFrame,
    threshold: float,
) -> str:
    lines: list[str] = []
    lines.append("# Phase E1 — Drawdown Segment Audit Report")
    lines.append("")
    lines.append(
        "Truth-finding audit for the CAGR-preserving crisis governor. "
        "Each segment = a peak-to-trough drawdown deeper than the threshold."
    )
    lines.append("")
    lines.append(f"- Threshold: **{threshold * 100:.0f}%**")
    lines.append("")
    lines.append("## 1. Data sources")
    lines.append("")
    if main_src is not None:
        flavor = "broker-ledger" if main_src.is_broker_ledger else "legacy research backtest"
        lines.append(f"- **main**: `{main_src.path.relative_to(ROOT)}` ({flavor})")
    else:
        lines.append("- **main**: NOT FOUND (run a pipeline first to produce equity_curve.csv)")
    if conc_src is not None:
        flavor = "broker-ledger" if conc_src.is_broker_ledger else "legacy research output"
        lines.append(f"- **concentrated**: `{conc_src.path.relative_to(ROOT)}` ({flavor})")
    else:
        lines.append("- **concentrated**: NOT FOUND (concentrated_strategy_monthly.csv missing)")
    lines.append("")
    if main_src and not main_src.is_broker_ledger:
        lines.append(
            "> WARNING: main is using the legacy research backtest, not the "
            "broker-ledger replay. The 33% main MDD baseline cited in plan "
            "docs comes from broker-ledger output. When `outputs/broker_ledger_replay/`"
            " is populated, this script will auto-switch."
        )
        lines.append("")
    lines.append("## 2. Summary statistics")
    lines.append("")
    lines.append("| Portfolio | Segments | Worst DD | Mean DD | Median days peak-to-trough |")
    lines.append("|---|---:|---:|---:|---:|")
    lines.append(_summary_row("main", main_segments))
    lines.append(_summary_row("concentrated", conc_segments))
    lines.append("")
    lines.append("## 3. Main portfolio segments")
    lines.append("")
    lines.append(_render_segment_table(main_segments))
    lines.append("")
    lines.append("## 4. Concentrated portfolio segments")
    lines.append("")
    lines.append(_render_segment_table(conc_segments))
    lines.append("")
    lines.append("## 5. Key diagnostic questions (Phase E design)")
    lines.append("")
    lines.append(_diagnostic_questions(main_segments, conc_segments))
    lines.append("")
    lines.append("## 6. Next steps")
    lines.append("")
    lines.append(
        "1. If `cash_weight_avg_during_dd` is < 10% in deep drawdowns, the "
        "engine NEVER raised cash → Phase E5 (exposure ladder) is high "
        "leverage."
    )
    lines.append(
        "2. If `cash_weight_max_during_dd` > 30% but recovery_date is far "
        "after trough_date, the engine raised cash too slowly to re-enter "
        "→ Phase E6 (re-entry ladder) needed."
    )
    lines.append(
        "3. If `breaker_activations_during_dd` >= 2 and `cash_weight_avg_during_dd` "
        "is still high after recovery, breaker is too sticky → Phase E5 hysteresis."
    )
    lines.append(
        "4. If `likely_archetype` distinguishes 2020 (shock_crash) from 2022 "
        "(slow_bear), Phase E3 classifier is on the right track."
    )
    lines.append("")
    return "\n".join(lines)


def _summary_row(label: str, df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return f"| {label} | 0 | — | — | — |"
    worst = df["drawdown_pct"].min()
    mean = df["drawdown_pct"].mean()
    median_days = int(df["days_peak_to_trough"].median())
    return f"| {label} | {len(df)} | {worst*100:.2f}% | {mean*100:.2f}% | {median_days} |"


def _render_segment_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_(no segments — DataFrame empty)_"
    cols = [
        "peak_date",
        "trough_date",
        "drawdown_pct",
        "days_peak_to_trough",
        "days_peak_to_below_10pct",
        "cash_weight_at_peak",
        "cash_weight_at_trough",
        "cash_weight_max_during_dd",
        "max_dd_breaker_level",
        "spy_drawdown_same_window",
        "likely_archetype",
    ]
    cols = [c for c in cols if c in df.columns]
    fmt = df[cols].copy()
    if "drawdown_pct" in fmt.columns:
        fmt["drawdown_pct"] = fmt["drawdown_pct"].apply(
            lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—"
        )
    if "spy_drawdown_same_window" in fmt.columns:
        fmt["spy_drawdown_same_window"] = fmt["spy_drawdown_same_window"].apply(
            lambda x: f"{x*100:.2f}%" if pd.notna(x) else "—"
        )
    for c in ("cash_weight_at_peak", "cash_weight_at_trough", "cash_weight_max_during_dd"):
        if c in fmt.columns:
            fmt[c] = fmt[c].apply(
                lambda x: f"{x*100:.1f}%" if pd.notna(x) and x is not None else "—"
            )
    return fmt.to_markdown(index=False)


def _diagnostic_questions(main: pd.DataFrame, conc: pd.DataFrame) -> str:
    lines: list[str] = []
    if main is not None and not main.empty:
        worst = main.loc[main["drawdown_pct"].idxmin()]
        lines.append(
            f"- **Main worst DD**: {worst['drawdown_pct']*100:.2f}% from "
            f"{worst['peak_date']} to {worst['trough_date']} "
            f"({worst.get('likely_archetype', '?')})."
        )
        if worst.get("cash_weight_max_during_dd") is not None:
            lines.append(
                f"  - Max cash during DD: {worst['cash_weight_max_during_dd']*100:.1f}%"
            )
        if worst.get("max_dd_breaker_level") is not None:
            lines.append(
                f"  - Max DD breaker level reached: {int(worst['max_dd_breaker_level'])}"
            )
    if conc is not None and not conc.empty:
        worst = conc.loc[conc["drawdown_pct"].idxmin()]
        lines.append(
            f"- **Concentrated worst DD**: {worst['drawdown_pct']*100:.2f}% from "
            f"{worst['peak_date']} to {worst['trough_date']} "
            f"({worst.get('likely_archetype', '?')})."
        )
    if not lines:
        lines.append("- No segments found. Run a backtest first.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-dir", type=str, default=None, help="Override outputs directory")
    p.add_argument("--threshold", type=float, default=0.10, help="Min DD to report (default 0.10)")
    p.add_argument("--quiet", action="store_true", help="Suppress per-segment console output")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    outputs_dir = Path(args.base_dir) if args.base_dir else DEFAULT_OUTPUTS
    out_dir = outputs_dir / "drawdown_segments"
    out_dir.mkdir(parents=True, exist_ok=True)
    main_src = _discover_main_equity(outputs_dir)
    conc_src = _discover_concentrated_equity(outputs_dir)
    if main_src is None and conc_src is None:
        print(
            "ERROR: no equity curve found under "
            f"{outputs_dir}. Run a backtest first.",
            file=sys.stderr,
        )
        return 2
    main_segments = pd.DataFrame()
    conc_segments = pd.DataFrame()
    if main_src is not None:
        df_main = pd.read_csv(main_src.path)
        main_segments = compute_segments(df_main, main_src, threshold=args.threshold)
        out_path = out_dir / "main.csv"
        main_segments.to_csv(out_path, index=False)
        if not args.quiet:
            print(f"main:         {len(main_segments)} segments  -> {out_path.relative_to(ROOT)}")
    if conc_src is not None:
        df_conc = pd.read_csv(conc_src.path)
        conc_segments = compute_segments(df_conc, conc_src, threshold=args.threshold)
        out_path = out_dir / "concentrated.csv"
        conc_segments.to_csv(out_path, index=False)
        if not args.quiet:
            print(f"concentrated: {len(conc_segments)} segments  -> {out_path.relative_to(ROOT)}")
    report = render_report(main_src, main_segments, conc_src, conc_segments, args.threshold)
    report_path = out_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    if not args.quiet:
        print(f"report:       {report_path.relative_to(ROOT)}")
    # Compact summary JSON for programmatic consumers
    summary = {
        "threshold": args.threshold,
        "main": {
            "source": str(main_src.path.relative_to(ROOT)) if main_src else None,
            "is_broker_ledger": main_src.is_broker_ledger if main_src else None,
            "segments": len(main_segments) if main_src else 0,
            "worst_drawdown_pct": float(main_segments["drawdown_pct"].min())
            if not main_segments.empty
            else None,
        },
        "concentrated": {
            "source": str(conc_src.path.relative_to(ROOT)) if conc_src else None,
            "is_broker_ledger": conc_src.is_broker_ledger if conc_src else None,
            "segments": len(conc_segments) if conc_src else 0,
            "worst_drawdown_pct": float(conc_segments["drawdown_pct"].min())
            if not conc_segments.empty
            else None,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
