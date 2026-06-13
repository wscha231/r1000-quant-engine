#!/usr/bin/env python3
"""Leader-lifecycle audit (MASTER_PLAN W3 — measurement first, no production change).

Reads the broker_trade_journal round-trips already produced by every full
rebuild and answers the questions the user actually asks of the engine:

  * Are we riding leaders (long holds, monster-tier returns concentrated in a
    few names) or churning monthly?
  * Are we entering BEFORE the move (oversold/early-stage breakout) or AFTER
    extension (climax chase)?
  * When we exit, do the names we sold keep beating the names we bought, or
    is rotation adding value?
  * Do we recover prior leaders after a crisis (reentry_capture), or do we
    rotate away and miss the recovery?

Outputs an `audit_report.md`, a `summary.json` with five gate metrics, and
a `premature_exits.csv` table for inspection. The tool is research-only and
does not mutate target books, prod config, or live policy.

Wiring: the full rebuild operating_minimal sidecar profile runs this AFTER
broker_replay and broker_trade_journal produce their inputs. Missing inputs
make the tool write status=skipped with a reason — never block the pipeline.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CASH_TICKERS = {"CASH", "__CASH__", "BIL", "SGOV"}

# Forward-return horizons (calendar days) used for premature-sell counterfactual.
HORIZONS_DAYS = (30, 63, 126)

# Default gates per MASTER_PLAN W3. Tunable via CLI. Treated as informational
# the first time the tool runs — they do not block any pipeline.
DEFAULT_GATES = {
    "median_holding_days_min": 60,           # ride leaders for ≥60 trading days (median)
    "pct_held_180d_plus_min": 0.15,          # ≥15% of trades held past 180d
    "pct_held_365d_plus_min": 0.05,          # ≥5% of trades held past 365d (true compounders)
    "extension_chase_pct_max": 0.55,         # ≤55% of entries in late-climax tape
    "premature_sell_excess_return_126d_min": -0.02,  # negative = we sold winners; want ≥ -2pp
    "leader_capture_rate_min": 0.20,         # WIN+GOOD_EXIT with hold ≥90d / all WIN+GOOD_EXIT
    "reentry_capture_rate_min": 0.60,        # post-DEFENSE reentry of prior holdings within 2 months
}


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if math.isnan(out):
            return default
        return out
    except (TypeError, ValueError):
        return default


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    pd.DataFrame(rows).to_csv(path, index=False)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(pd.Series(values).quantile(q))


# ---------------------------------------------------------------------------
# Metric computations
# ---------------------------------------------------------------------------


def holding_period_stats(round_trips: pd.DataFrame) -> dict[str, Any]:
    if round_trips.empty:
        return {"status": "empty", "trade_count": 0}
    hd = pd.to_numeric(round_trips.get("holding_days"), errors="coerce").dropna()
    if hd.empty:
        return {"status": "no_holding_days", "trade_count": int(len(round_trips))}
    out = {
        "status": "ok",
        "trade_count": int(len(hd)),
        "median": float(hd.median()),
        "mean": float(hd.mean()),
        "p25": float(hd.quantile(0.25)),
        "p75": float(hd.quantile(0.75)),
        "p90": float(hd.quantile(0.90)),
        "max": float(hd.max()),
        "pct_held_30d_plus": float((hd >= 30).mean()),
        "pct_held_90d_plus": float((hd >= 90).mean()),
        "pct_held_180d_plus": float((hd >= 180).mean()),
        "pct_held_365d_plus": float((hd >= 365).mean()),
    }
    return out


def extension_chase_stats(round_trips: pd.DataFrame) -> dict[str, Any]:
    """How often did we enter at climax/extension?

    Uses the per-trade entry features the journal already records. A trade is
    counted as a 'climax chase' if AT ENTRY any of these were true:
      * entry_explosion_exit_score >= 0.50 (engine's own climax flag)
      * entry_stage2_overext_penalty >= 0.50 (Stage 2 extension penalty fired)
      * entry_rs_acceleration_score >= 1.5 AND entry_explosion_entry_score <= 0.0
        (extreme RS acceleration with no fresh breakout — late-stage chase)
    Conservative composite — a trade only counts when at least one fires.
    """
    if round_trips.empty:
        return {"status": "empty", "trade_count": 0}
    df = round_trips
    explosion_exit = pd.to_numeric(df.get("entry_explosion_exit_score", 0.0), errors="coerce").fillna(0.0)
    stage2 = pd.to_numeric(df.get("entry_stage2_overext_penalty", 0.0), errors="coerce").fillna(0.0)
    rs_acc = pd.to_numeric(df.get("entry_rs_acceleration_score", 0.0), errors="coerce").fillna(0.0)
    explosion_entry = pd.to_numeric(df.get("entry_explosion_entry_score", 0.0), errors="coerce").fillna(0.0)
    climax_mask = (
        (explosion_exit >= 0.50)
        | (stage2 >= 0.50)
        | ((rs_acc >= 1.5) & (explosion_entry <= 0.0))
    )
    total = int(len(df))
    fire = int(climax_mask.sum())
    return {
        "status": "ok",
        "trade_count": total,
        "extension_chase_count": fire,
        "extension_chase_pct": float(fire / total) if total else 0.0,
        "climax_signal_breakdown": {
            "explosion_exit_score_ge_050": int((explosion_exit >= 0.50).sum()),
            "stage2_overext_penalty_ge_050": int((stage2 >= 0.50).sum()),
            "rs_accel_ge_15_without_fresh_breakout": int(((rs_acc >= 1.5) & (explosion_entry <= 0.0)).sum()),
        },
    }


def leader_capture_stats(round_trips: pd.DataFrame) -> dict[str, Any]:
    """Of trades graded WIN or GOOD_EXIT, what fraction were held ≥90 days?

    Low capture = we sell winners early. High capture = we let runners run.
    """
    if round_trips.empty:
        return {"status": "empty", "trade_count": 0}
    df = round_trips
    hd = pd.to_numeric(df.get("holding_days"), errors="coerce").fillna(0)
    grade = df.get("grade_label", pd.Series(dtype=str)).astype(str).str.upper()
    winners = grade.isin({"WIN", "GOOD_EXIT"})
    winner_ct = int(winners.sum())
    if winner_ct == 0:
        return {"status": "no_winners", "trade_count": int(len(df))}
    long_winners = int(((winners) & (hd >= 90)).sum())
    very_long_winners = int(((winners) & (hd >= 180)).sum())
    return {
        "status": "ok",
        "trade_count": int(len(df)),
        "winner_count": winner_ct,
        "leader_capture_rate": float(long_winners / winner_ct),
        "leader_capture_rate_180d": float(very_long_winners / winner_ct),
        "winner_median_holding_days": float(pd.to_numeric(df.loc[winners, "holding_days"], errors="coerce").median() or 0.0),
        "winner_mean_return": float(pd.to_numeric(df.loc[winners, "realized_return"], errors="coerce").mean() or 0.0),
    }


def premature_sell_excess(trades: pd.DataFrame) -> dict[str, Any]:
    """For each SELL, compute the sold name's forward return over the next
    {30,63,126} calendar days using prices implied by later trades.csv rows
    (BUY or SELL of the same ticker). Compare to the average forward return
    of all BUY trades dated on the SAME signal_date.

    Positive premature_sell_excess = our same-date BUYs outperformed (good
    rotation). Negative = we sold names that kept beating our replacement
    (bad exit timing — money left on the table).
    """
    if trades.empty:
        return {"status": "empty"}
    df = trades.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["side"] = df["side"].astype(str).str.upper()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df["fill_price"] = pd.to_numeric(df["fill_price"], errors="coerce")
    df = df[~df["ticker"].isin(CASH_TICKERS) & df["fill_price"].gt(0)].sort_values("date")

    # Per-ticker price timeline reconstructed from fill_price observations.
    timelines: dict[str, list[tuple[pd.Timestamp, float]]] = defaultdict(list)
    for _, row in df.iterrows():
        timelines[row["ticker"]].append((row["date"], float(row["fill_price"])))

    def price_at_horizon(ticker: str, ref: pd.Timestamp, horizon_days: int, slack: int = 18) -> float | None:
        target = ref + pd.Timedelta(days=horizon_days)
        timeline = timelines.get(ticker, [])
        best = None
        best_dist = 10**9
        for date, price in timeline:
            if date <= ref:
                continue
            dist = abs((date - target).days)
            if dist <= slack and dist < best_dist:
                best = price
                best_dist = dist
        return best

    # All BUY trades grouped by signal_date for the redeploy baseline.
    df["signal_date"] = pd.to_datetime(df.get("signal_date"), errors="coerce")
    buys = df[df["side"] == "BUY"].copy()
    buy_groups = buys.groupby("date")

    rows: list[dict[str, Any]] = []
    by_horizon: dict[int, list[float]] = {h: [] for h in HORIZONS_DAYS}
    sold_returns: dict[int, list[float]] = {h: [] for h in HORIZONS_DAYS}
    bought_returns: dict[int, list[float]] = {h: [] for h in HORIZONS_DAYS}

    for _, row in df[df["side"] == "SELL"].iterrows():
        ticker = row["ticker"]
        date = row["date"]
        sell_px = float(row["fill_price"])
        for h in HORIZONS_DAYS:
            fwd_sold = price_at_horizon(ticker, date, h)
            if fwd_sold is None or sell_px <= 0:
                continue
            sold_ret = (fwd_sold / sell_px) - 1.0

            # Same-date BUYs forward return baseline.
            try:
                same_day_buys = buy_groups.get_group(date)
            except KeyError:
                same_day_buys = pd.DataFrame()
            if same_day_buys.empty:
                continue
            buy_rets: list[float] = []
            for _, b in same_day_buys.iterrows():
                bt = b["ticker"]
                bpx = float(b["fill_price"])
                fwd_buy = price_at_horizon(bt, date, h)
                if fwd_buy is None or bpx <= 0:
                    continue
                buy_rets.append((fwd_buy / bpx) - 1.0)
            if not buy_rets:
                continue
            avg_buy_ret = sum(buy_rets) / len(buy_rets)
            penalty = sold_ret - avg_buy_ret
            by_horizon[h].append(penalty)
            sold_returns[h].append(sold_ret)
            bought_returns[h].append(avg_buy_ret)
            if h == 126:
                rows.append(
                    {
                        "sell_date": date.date().isoformat(),
                        "ticker": ticker,
                        "sell_price": sell_px,
                        "forward_price_126d": fwd_sold,
                        "sold_fwd_return_126d": sold_ret,
                        "avg_replacement_fwd_return_126d": avg_buy_ret,
                        "premature_sell_excess_return_126d": penalty,
                        "matched_replacement_count": len(buy_rets),
                    }
                )

    summary: dict[str, Any] = {"status": "ok", "horizons": {}}
    for h in HORIZONS_DAYS:
        if not by_horizon[h]:
            summary["horizons"][f"{h}d"] = {"matched": 0}
            continue
        summary["horizons"][f"{h}d"] = {
            "matched": len(by_horizon[h]),
            "sold_fwd_return_mean": float(sum(sold_returns[h]) / len(sold_returns[h])),
            "replacement_fwd_return_mean": float(sum(bought_returns[h]) / len(bought_returns[h])),
            "premature_sell_excess_return_mean": float(sum(by_horizon[h]) / len(by_horizon[h])),
            "premature_sell_excess_return_median": float(pd.Series(by_horizon[h]).median()),
        }
    rows.sort(key=lambda r: r["sold_fwd_return_126d"], reverse=True)
    summary["worst_premature_exits_top10"] = rows[:10]
    return summary


def reentry_capture(round_trips: pd.DataFrame, daily_crisis: pd.DataFrame) -> dict[str, Any]:
    """Of names exited during a CRISIS_DEFENSE / DEFENSE_REVIEW window, what
    fraction did we re-acquire within ~63 calendar days after crisis clears?

    Crisis clears = first row whose crisis_state goes back to GREEN/WATCH
    after a defense block. We count an exit as 'captured' if the same ticker
    has a later BUY round_trip within 63 calendar days of the clear date.
    """
    if round_trips.empty:
        return {"status": "empty"}
    if daily_crisis is None or daily_crisis.empty or "crisis_state" not in daily_crisis.columns:
        return {"status": "no_crisis_state"}

    df = daily_crisis.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    DEFENSE = {"CRISIS_DEFENSE", "DEFENSE_REVIEW"}
    df["is_defense"] = df["crisis_state"].astype(str).str.upper().isin(DEFENSE)

    # Find defense windows: contiguous True runs.
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    in_window = False
    start: pd.Timestamp | None = None
    for _, row in df.iterrows():
        if row["is_defense"] and not in_window:
            in_window = True
            start = row["date"]
        elif not row["is_defense"] and in_window:
            in_window = False
            windows.append((start, row["date"]))
            start = None
    if in_window and start is not None:
        windows.append((start, df["date"].iloc[-1]))

    if not windows:
        return {"status": "no_defense_windows"}

    rt = round_trips.copy()
    rt["entry_date"] = pd.to_datetime(rt.get("entry_date"), errors="coerce")
    rt["exit_date"] = pd.to_datetime(rt.get("exit_date"), errors="coerce")
    rt = rt.dropna(subset=["entry_date"])
    rt["ticker"] = rt.get("ticker", pd.Series(dtype=str)).astype(str).str.upper()

    captured = 0
    total = 0
    detail: list[dict[str, Any]] = []
    for w_start, w_end in windows:
        # Names exited during the window.
        exits_in = rt[(rt["exit_date"].notna()) & (rt["exit_date"] >= w_start) & (rt["exit_date"] <= w_end)]
        exit_tickers = sorted(set(exits_in["ticker"].tolist()))
        # Reentry deadline: 63 calendar days after the window CLOSES.
        deadline = w_end + pd.Timedelta(days=63)
        for t in exit_tickers:
            total += 1
            reentries = rt[(rt["ticker"] == t) & (rt["entry_date"] > w_end) & (rt["entry_date"] <= deadline)]
            was_captured = not reentries.empty
            if was_captured:
                captured += 1
            detail.append(
                {
                    "ticker": t,
                    "window_start": w_start.date().isoformat(),
                    "window_end": w_end.date().isoformat(),
                    "reentry_deadline": deadline.date().isoformat(),
                    "captured": bool(was_captured),
                }
            )
    return {
        "status": "ok",
        "defense_windows": len(windows),
        "total_exited_during_defense": total,
        "reentries_within_63d": captured,
        "reentry_capture_rate": float(captured / total) if total else 0.0,
        "detail_sample": detail[:30],
    }


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def evaluate_portfolio(
    portfolio: str,
    round_trips: pd.DataFrame,
    trades: pd.DataFrame,
    daily_crisis: pd.DataFrame,
    gates: dict[str, float],
) -> dict[str, Any]:
    holding = holding_period_stats(round_trips)
    extension = extension_chase_stats(round_trips)
    capture = leader_capture_stats(round_trips)
    premature = premature_sell_excess(trades)
    reentry = reentry_capture(round_trips, daily_crisis)

    def gate_pass(key: str, value: float, direction: str) -> bool:
        threshold = float(gates.get(key, float("nan")))
        if math.isnan(threshold):
            return False
        if direction == ">=":
            return value >= threshold
        return value <= threshold

    gate_results: dict[str, dict[str, Any]] = {}
    if holding.get("status") == "ok":
        gate_results["median_holding_days_min"] = {
            "value": holding["median"],
            "threshold": gates["median_holding_days_min"],
            "pass": gate_pass("median_holding_days_min", holding["median"], ">="),
        }
        gate_results["pct_held_180d_plus_min"] = {
            "value": holding["pct_held_180d_plus"],
            "threshold": gates["pct_held_180d_plus_min"],
            "pass": gate_pass("pct_held_180d_plus_min", holding["pct_held_180d_plus"], ">="),
        }
        gate_results["pct_held_365d_plus_min"] = {
            "value": holding["pct_held_365d_plus"],
            "threshold": gates["pct_held_365d_plus_min"],
            "pass": gate_pass("pct_held_365d_plus_min", holding["pct_held_365d_plus"], ">="),
        }
    if extension.get("status") == "ok":
        gate_results["extension_chase_pct_max"] = {
            "value": extension["extension_chase_pct"],
            "threshold": gates["extension_chase_pct_max"],
            "pass": gate_pass("extension_chase_pct_max", extension["extension_chase_pct"], "<="),
        }
    if capture.get("status") == "ok":
        gate_results["leader_capture_rate_min"] = {
            "value": capture["leader_capture_rate"],
            "threshold": gates["leader_capture_rate_min"],
            "pass": gate_pass("leader_capture_rate_min", capture["leader_capture_rate"], ">="),
        }
    if premature.get("status") == "ok" and "126d" in premature.get("horizons", {}):
        psr = premature["horizons"]["126d"].get("premature_sell_excess_return_mean")
        if psr is not None:
            gate_results["premature_sell_excess_return_126d_min"] = {
                "value": psr,
                "threshold": gates["premature_sell_excess_return_126d_min"],
                "pass": gate_pass("premature_sell_excess_return_126d_min", psr, ">="),
            }
    if reentry.get("status") == "ok":
        gate_results["reentry_capture_rate_min"] = {
            "value": reentry["reentry_capture_rate"],
            "threshold": gates["reentry_capture_rate_min"],
            "pass": gate_pass("reentry_capture_rate_min", reentry["reentry_capture_rate"], ">="),
        }

    return {
        "portfolio": portfolio,
        "schema_version": "leader_lifecycle_audit_v1",
        "holding_period": holding,
        "extension_chase": extension,
        "leader_capture": capture,
        "premature_sell": premature,
        "reentry_capture": reentry,
        "gates": gate_results,
        "gates_passed": int(sum(1 for g in gate_results.values() if g.get("pass"))),
        "gates_total": int(len(gate_results)),
        "production_activation_allowed": False,
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = ["# Leader Lifecycle Audit", ""]
    lines.append("Research-only diagnostic. Measures how the live engine actually")
    lines.append("behaves on entry, hold, exit, and post-crisis reentry vs the")
    lines.append("'ride leaders, rotate cleanly' ideal. No production change.")
    lines.append("")
    for portfolio in ("main", "concentrated"):
        block = summary.get(portfolio)
        if not block:
            continue
        lines.append(f"## {portfolio}")
        lines.append("")
        gates = block.get("gates") or {}
        passed = block.get("gates_passed", 0)
        total = block.get("gates_total", 0)
        lines.append(f"- gates passed: **{passed}/{total}**")
        for name, payload in gates.items():
            mark = "✅" if payload.get("pass") else "❌"
            lines.append(
                f"  - {mark} `{name}`: {float(payload['value']):.4f} vs threshold {float(payload['threshold']):.4f}"
            )
        hp = block.get("holding_period") or {}
        if hp.get("status") == "ok":
            lines.append("")
            lines.append("### Holding period")
            lines.append(f"- trades: {hp['trade_count']}")
            lines.append(
                f"- median {hp['median']:.0f}d | p25 {hp['p25']:.0f}d | p75 {hp['p75']:.0f}d | p90 {hp['p90']:.0f}d | max {hp['max']:.0f}d"
            )
            lines.append(
                f"- held ≥30d {hp['pct_held_30d_plus']:.1%} | ≥90d {hp['pct_held_90d_plus']:.1%} | ≥180d {hp['pct_held_180d_plus']:.1%} | ≥365d {hp['pct_held_365d_plus']:.1%}"
            )
        ext = block.get("extension_chase") or {}
        if ext.get("status") == "ok":
            lines.append("")
            lines.append("### Climax / extension chase at entry")
            lines.append(
                f"- {ext['extension_chase_count']}/{ext['trade_count']} entries fired a climax flag ({ext['extension_chase_pct']:.1%})"
            )
            for k, v in (ext.get("climax_signal_breakdown") or {}).items():
                lines.append(f"  - {k}: {v}")
        cap = block.get("leader_capture") or {}
        if cap.get("status") == "ok":
            lines.append("")
            lines.append("### Leader capture (held WINs)")
            lines.append(
                f"- winner trades: {cap['winner_count']}/{cap['trade_count']} | median hold {cap['winner_median_holding_days']:.0f}d | mean return {cap['winner_mean_return']:.2%}"
            )
            lines.append(
                f"- capture ≥90d {cap['leader_capture_rate']:.1%} | capture ≥180d {cap['leader_capture_rate_180d']:.1%}"
            )
        prem = block.get("premature_sell") or {}
        if prem.get("status") == "ok":
            lines.append("")
            lines.append("### Premature-sell excess return (sold − bought, same date)")
            for h, payload in (prem.get("horizons") or {}).items():
                if not payload or payload.get("matched", 0) == 0:
                    continue
                lines.append(
                    f"- {h}: n={payload['matched']} | sold_fwd {payload['sold_fwd_return_mean']:+.2%} | "
                    f"replacement_fwd {payload['replacement_fwd_return_mean']:+.2%} | "
                    f"premature_sell_excess {payload['premature_sell_excess_return_mean']:+.2%}"
                )
            worst = prem.get("worst_premature_exits_top10") or []
            if worst:
                lines.append("")
                lines.append("Worst 10 premature exits at 126d horizon:")
                for w in worst[:10]:
                    lines.append(
                        f"  - {w['ticker']} sold {w['sell_date']}: forward 126d return {w['sold_fwd_return_126d']:+.1%}"
                    )
        reent = block.get("reentry_capture") or {}
        if reent.get("status") == "ok":
            lines.append("")
            lines.append("### Post-crisis reentry capture (within 63 calendar days)")
            lines.append(
                f"- defense windows: {reent['defense_windows']} | exited during defense: {reent['total_exited_during_defense']} | reentries: {reent['reentries_within_63d']} | capture rate {reent['reentry_capture_rate']:.1%}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def load_gates(path: Path | None) -> dict[str, float]:
    g = dict(DEFAULT_GATES)
    if path is not None and path.exists():
        try:
            override = json.loads(path.read_text(encoding="utf-8"))
            for k, v in override.items():
                g[k] = float(v)
        except Exception:
            pass
    return g


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--output-dir", default="outputs/leader_lifecycle_audit")
    parser.add_argument("--gates", default=None, help="optional JSON file with gate overrides")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest = repo_path(args.latest_run)
    out_dir = repo_path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    gates = load_gates(Path(args.gates)) if args.gates else dict(DEFAULT_GATES)

    daily_crisis = read_csv(latest / "alphaops_vnext" / "daily_crisis_state.csv")

    summary: dict[str, Any] = {
        "schema_version": "leader_lifecycle_audit_v1",
        "latest_run": str(latest),
        "gates_used": gates,
    }
    for portfolio in ("main", "concentrated"):
        rt = read_csv(latest / "broker_trade_journal" / portfolio / "round_trips.csv")
        trades = read_csv(latest / "broker_replay" / portfolio / "trades.csv")
        if rt.empty and trades.empty:
            summary[portfolio] = {"status": "missing_inputs", "portfolio": portfolio}
            continue
        block = evaluate_portfolio(portfolio, rt, trades, daily_crisis, gates)
        summary[portfolio] = block

        # Also persist a per-portfolio premature-exits CSV for inspection.
        worst = (block.get("premature_sell") or {}).get("worst_premature_exits_top10") or []
        if worst:
            write_csv(out_dir / portfolio / "premature_exits.csv", worst)

    write_json(out_dir / "summary.json", summary)
    write_text(out_dir / "audit_report.md", render_report(summary))
    print(f"[leader_lifecycle_audit] wrote {out_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
