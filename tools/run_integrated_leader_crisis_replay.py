#!/usr/bin/env python3
"""P3 — Integrated Market-Leader + Crisis-Governor broker-ledger replay.

Answers the question the standalone sidecars cannot: **how much did crisis
defense cut COVID/2022 losses on the LEADER book, and did it re-enter fast?**

Composition (all building blocks already exist; this tool only orchestrates):
  1. Market Leader challenger book (monthly leader targets,
     tools/run_market_leader_challenger.py output) is replayed AS-IS through the
     broker-ledger next-close engine (champion filter disabled — the leader book
     carries its own N/cap policy).
  2. The same book is overlaid with the daily crisis governor
     (tools/build_crisis_governed_target_books.build_governed_book: GREEN hold /
     ladder cash up in confirmed crisis / monotonic re-entry) and replayed again.
  3. Both equity curves are compared overall + inside stress windows
     (COVID 2020-02-19..2020-05-31, 2022 bear 2021-11-01..2022-12-31), plus
     re-entry lag, cash-trap days, and defense-day diagnostics from the governor
     audit schedule.

Research-only. Promotion FORBIDDEN: passing gates yields a research candidate
for human review; production target books, scores, and defaults are untouched.
PIT discipline is inherited from the inputs (leader signals at T close, fills
T+1 close; crisis features carry no future labels).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_crisis_governed_target_books import build_governed_book  # noqa: E402
from tools.run_broker_ledger_replay import replay, safe_float  # noqa: E402
from tools.run_crisis_signal_builder import composite_crisis_coverage  # noqa: E402


DEFAULT_LEADER_DIR = "outputs/market_leader_challenger"
DEFAULT_CRISIS_FEATURES = "outputs/crisis_signals/daily_features.parquet"
DEFAULT_OUTPUT_DIR = "outputs/integrated_leader_crisis_replay"

STRESS_WINDOWS: list[tuple[str, str, str]] = [
    ("covid_2020", "2020-02-19", "2020-05-31"),
    ("bear_2022", "2021-11-01", "2022-12-31"),
]

# Re-entry diagnostics thresholds (audit-schedule based, not equity based).
REENTRY_CASH_NORMAL = 0.10   # cash back under this = re-entered
CASH_TRAP_LEVEL = 0.25       # cash at/above this while zone is normal = trapped


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_equity_curve(replay_dir: Path) -> pd.DataFrame:
    path = replay_dir / "equity_curve.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if frame.empty or "date" not in frame.columns or "equity_usd" not in frame.columns:
        return pd.DataFrame()
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["equity_usd"] = pd.to_numeric(frame["equity_usd"], errors="coerce")
    return frame.dropna(subset=["date", "equity_usd"]).sort_values("date").reset_index(drop=True)


def window_metrics(equity: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    """Max drawdown + total return of the equity curve inside [start, end]."""
    if equity.empty:
        return {"window_return": float("nan"), "window_max_dd": float("nan"), "observations": 0}
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    window = equity[(equity["date"] >= start_ts) & (equity["date"] <= end_ts)]
    if len(window) < 2:
        return {"window_return": float("nan"), "window_max_dd": float("nan"), "observations": int(len(window))}
    eq = window["equity_usd"].astype(float)
    running_max = eq.cummax()
    drawdown = eq / running_max - 1.0
    return {
        "window_return": float(eq.iloc[-1] / eq.iloc[0] - 1.0),
        "window_max_dd": float(drawdown.min()),
        "observations": int(len(window)),
    }


def reentry_diagnostics(audit: pd.DataFrame) -> dict[str, Any]:
    """Defense/re-entry behavior from the governor's audit schedule.

    The audit has one row per emitted governed snapshot:
    snapshot_date, crisis_zone, cash_weight, event_reason.
    """
    if audit.empty or "snapshot_date" not in audit.columns:
        return {
            "defense_episode_count": 0,
            "max_cash_weight": 0.0,
            "avg_reentry_lag_days": float("nan"),
            "max_reentry_lag_days": float("nan"),
            "cash_trap_snapshot_count": 0,
            "defense_snapshot_count": 0,
        }
    d = audit.copy()
    d["snapshot_date"] = pd.to_datetime(d["snapshot_date"], errors="coerce")
    d = d.dropna(subset=["snapshot_date"]).sort_values("snapshot_date").reset_index(drop=True)
    d["cash_weight"] = pd.to_numeric(d.get("cash_weight", 0.0), errors="coerce").fillna(0.0)
    d["crisis_zone"] = d.get("crisis_zone", "normal").astype(str)

    in_defense = False
    defense_episodes = 0
    reentry_lags: list[float] = []
    zone_exit_date: pd.Timestamp | None = None
    cash_trap_snapshots = 0
    defense_snapshots = 0
    for row in d.itertuples(index=False):
        zone = str(row.crisis_zone)
        cash = float(row.cash_weight)
        defending = zone != "normal"
        if defending:
            defense_snapshots += 1
        if defending and not in_defense:
            defense_episodes += 1
            in_defense = True
            zone_exit_date = None
        elif not defending and in_defense:
            # Zone returned to normal; lag clock starts here until cash normalizes.
            if zone_exit_date is None:
                zone_exit_date = pd.Timestamp(row.snapshot_date)
            if cash <= REENTRY_CASH_NORMAL:
                reentry_lags.append(float((pd.Timestamp(row.snapshot_date) - zone_exit_date).days))
                in_defense = False
                zone_exit_date = None
            elif cash >= CASH_TRAP_LEVEL:
                cash_trap_snapshots += 1
        elif not defending and not in_defense and cash >= CASH_TRAP_LEVEL:
            cash_trap_snapshots += 1

    lag_series = pd.Series(reentry_lags, dtype=float)
    return {
        "defense_episode_count": int(defense_episodes),
        "max_cash_weight": float(d["cash_weight"].max()) if not d.empty else 0.0,
        "avg_reentry_lag_days": float(lag_series.mean()) if not lag_series.empty else float("nan"),
        "max_reentry_lag_days": float(lag_series.max()) if not lag_series.empty else float("nan"),
        "cash_trap_snapshot_count": int(cash_trap_snapshots),
        "defense_snapshot_count": int(defense_snapshots),
    }


def integrated_verdict(base: dict[str, Any], governed: dict[str, Any], portfolio_kind: str) -> dict[str, Any]:
    """Report-only gate check vs the plan's promotion thresholds. NOT a promotion."""
    base_cagr = safe_float(base.get("cagr"))
    gov_cagr = safe_float(governed.get("cagr"))
    base_mdd = safe_float(base.get("max_dd"))
    gov_mdd = safe_float(governed.get("max_dd"))
    cagr_delta_pp = (gov_cagr - base_cagr) * 100.0
    mdd_delta_pp = (gov_mdd - base_mdd) * 100.0  # positive = governed lost less
    max_cagr_loss_pp = 3.0 if portfolio_kind == "concentrated" else 0.5
    mdd_improvement_required_pp = 8.0 if portfolio_kind == "concentrated" else 5.0
    passes = (cagr_delta_pp >= -max_cagr_loss_pp) and (mdd_delta_pp >= mdd_improvement_required_pp)
    return {
        "portfolio_kind": portfolio_kind,
        "base_cagr": base_cagr,
        "governed_cagr": gov_cagr,
        "cagr_delta_pp": cagr_delta_pp,
        "base_max_dd": base_mdd,
        "governed_max_dd": gov_mdd,
        "mdd_delta_pp": mdd_delta_pp,
        "gate_max_cagr_loss_pp": max_cagr_loss_pp,
        "gate_mdd_improvement_pp": mdd_improvement_required_pp,
        "gates_pass": bool(passes),
        "promotion_allowed": False,
        "note": "research candidate only; human review + official baseline comparison required",
    }


def resolve_book(leader_dir: Path, explicit: str, portfolio_kind: str) -> Path:
    if explicit:
        return repo_path(explicit)
    return leader_dir / f"{portfolio_kind}_target_book.csv"


def run_leg(
    *,
    portfolio_kind: str,
    target_book: Path,
    crisis_features: Path,
    thresholds_json: Path | None,
    governor_mode: str,
    price_cache: Path,
    output_dir: Path,
    cost_bps: float,
    max_fill_lag_days: int,
) -> dict[str, Any]:
    leg_dir = output_dir / portfolio_kind
    leg_dir.mkdir(parents=True, exist_ok=True)
    leg: dict[str, Any] = {
        "portfolio_kind": portfolio_kind,
        "target_book": str(target_book),
        "status": "blocked",
    }
    if not target_book.exists():
        leg["reason"] = f"leader target book missing: {target_book}"
        return leg

    base_metrics = replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=leg_dir / "base",
        portfolio_kind=portfolio_kind,
        fill_mode="next_close",
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
        disable_concentrated_champion_filter=True,
    )
    leg["base"] = base_metrics
    if base_metrics.get("status") != "completed":
        leg["reason"] = "base leader replay blocked: " + str(base_metrics.get("reason", "unknown"))
        return leg

    if not crisis_features.exists():
        leg["reason"] = f"crisis features missing: {crisis_features} (base leg completed; governed skipped)"
        leg["status"] = "base_only"
        return leg

    book, audit, gov_summary = build_governed_book(
        target_book=target_book,
        crisis_features=crisis_features,
        portfolio_kind=portfolio_kind,
        mode=governor_mode,
        thresholds_json=thresholds_json,
    )
    leg["governor_summary"] = gov_summary
    if book.empty:
        leg["reason"] = "governed book empty: " + str(gov_summary.get("reason", "unknown"))
        leg["status"] = "base_only"
        return leg
    governed_book_path = leg_dir / "crisis_governed_leader_target_book.csv"
    book.to_csv(governed_book_path, index=False)
    audit_path = leg_dir / "governor_schedule_audit.csv"
    audit.to_csv(audit_path, index=False)

    governed_metrics = replay(
        target_book=governed_book_path,
        price_cache=price_cache,
        output_dir=leg_dir / "governed",
        portfolio_kind=portfolio_kind,
        fill_mode="next_close",
        cost_bps=cost_bps,
        max_fill_lag_days=max_fill_lag_days,
        disable_concentrated_champion_filter=True,
    )
    leg["governed"] = governed_metrics
    if governed_metrics.get("status") != "completed":
        leg["reason"] = "governed replay blocked: " + str(governed_metrics.get("reason", "unknown"))
        leg["status"] = "base_only"
        return leg

    base_eq = read_equity_curve(leg_dir / "base")
    gov_eq = read_equity_curve(leg_dir / "governed")
    stress_rows: list[dict[str, Any]] = []
    for window_id, start, end in STRESS_WINDOWS:
        base_win = window_metrics(base_eq, start, end)
        gov_win = window_metrics(gov_eq, start, end)
        stress_rows.append(
            {
                "portfolio_kind": portfolio_kind,
                "window_id": window_id,
                "window_start": start,
                "window_end": end,
                "base_window_max_dd": base_win["window_max_dd"],
                "governed_window_max_dd": gov_win["window_max_dd"],
                "window_mdd_delta_pp": (gov_win["window_max_dd"] - base_win["window_max_dd"]) * 100.0
                if pd.notna(gov_win["window_max_dd"]) and pd.notna(base_win["window_max_dd"])
                else float("nan"),
                "base_window_return": base_win["window_return"],
                "governed_window_return": gov_win["window_return"],
                "base_observations": base_win["observations"],
                "governed_observations": gov_win["observations"],
            }
        )
    leg["stress_windows"] = stress_rows
    leg["reentry"] = reentry_diagnostics(audit)
    leg["verdict"] = integrated_verdict(base_metrics, governed_metrics, portfolio_kind)
    leg["fees_delta_usd"] = safe_float(governed_metrics.get("total_fees_usd")) - safe_float(base_metrics.get("total_fees_usd"))
    leg["status"] = "completed"
    return leg


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Integrated Market-Leader + Crisis-Governor Replay",
        "",
        "Research-only. Broker-ledger next-close, integer shares, fees, cash ledger.",
        "Promotion FORBIDDEN — gates passing yields a research candidate only.",
        "",
    ]
    for leg in payload.get("legs", []):
        kind = leg.get("portfolio_kind", "?")
        lines.append(f"## {kind}")
        lines.append(f"- status: `{leg.get('status')}`")
        if leg.get("reason"):
            lines.append(f"- reason: {leg['reason']}")
        verdict = leg.get("verdict") or {}
        if verdict:
            lines.append(
                f"- base CAGR {verdict.get('base_cagr', 0):.2%} / MDD {verdict.get('base_max_dd', 0):.2%}"
                f" -> governed CAGR {verdict.get('governed_cagr', 0):.2%} / MDD {verdict.get('governed_max_dd', 0):.2%}"
            )
            lines.append(
                f"- deltas: CAGR {verdict.get('cagr_delta_pp', 0):+.2f}pp, MDD {verdict.get('mdd_delta_pp', 0):+.2f}pp"
                f" (gates: CAGR loss <= {verdict.get('gate_max_cagr_loss_pp')}pp, MDD >= +{verdict.get('gate_mdd_improvement_pp')}pp)"
                f" -> gates_pass={verdict.get('gates_pass')}"
            )
        for row in leg.get("stress_windows", []) or []:
            lines.append(
                f"- {row['window_id']}: base MDD {row['base_window_max_dd']:.2%}"
                f" -> governed {row['governed_window_max_dd']:.2%}"
                f" ({row['window_mdd_delta_pp']:+.2f}pp)"
            )
        reentry = leg.get("reentry") or {}
        if reentry:
            lines.append(
                f"- defense episodes: {reentry.get('defense_episode_count')}, max cash {reentry.get('max_cash_weight', 0):.1%},"
                f" avg reentry lag {reentry.get('avg_reentry_lag_days')}d, cash-trap snapshots {reentry.get('cash_trap_snapshot_count')}"
            )
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--leader-dir", default=DEFAULT_LEADER_DIR)
    parser.add_argument("--main-target-book", default="")
    parser.add_argument("--concentrated-target-book", default="")
    parser.add_argument("--crisis-features", default=DEFAULT_CRISIS_FEATURES)
    parser.add_argument("--thresholds-json", default="")
    parser.add_argument("--governor-mode", default="conservative")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--portfolio-kind", choices=["main", "concentrated", "both"], default="both")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def crisis_score_diagnostics(crisis_features_path: Path) -> dict[str, Any]:
    """Read the crisis features parquet and emit governor-relevant diagnostics:
    component coverage (which sub-scores have live data), pre-renormalization
    weight ceiling, and the actual score distribution. Without this the
    governor's silence (every leg's mdd_delta ~= 0) is indistinguishable from
    "no crisis happened" vs "the score could never reach the defense zone
    because half its inputs were absent on this runner"."""
    if not crisis_features_path.exists():
        return {"status": "missing", "path": str(crisis_features_path)}
    try:
        features = pd.read_parquet(crisis_features_path)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable", "path": str(crisis_features_path), "error": repr(exc)}
    score = features.get("crisis_score")
    coverage = composite_crisis_coverage(features)
    live = sorted(name for name, info in coverage.items() if info["live"])
    dead = sorted(name for name, info in coverage.items() if not info["live"])
    nominal_live_weight = sum(info["nominal_weight"] for name, info in coverage.items() if info["live"])
    stats: dict[str, Any] = {}
    if score is not None and len(score):
        s = pd.to_numeric(score, errors="coerce").dropna()
        if len(s):
            stats = {
                "max": float(s.max()),
                "p99": float(s.quantile(0.99)),
                "p95": float(s.quantile(0.95)),
                "p90": float(s.quantile(0.90)),
                "mean": float(s.mean()),
                "days_in_caution_default": int((s >= 0.30).sum()),
                "days_in_defense_default": int((s >= 0.50).sum()),
                "days_in_crisis_default": int((s >= 0.70).sum()),
            }
    return {
        "status": "ok",
        "path": str(crisis_features_path),
        "live_components": live,
        "dead_components": dead,
        "pre_renorm_ceiling": float(nominal_live_weight),
        "renormalization_active": bool(dead and nominal_live_weight < 1.0),
        "component_coverage": coverage,
        "score_stats": stats,
    }


def main() -> int:
    args = parse_args()
    leader_dir = repo_path(args.leader_dir)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    kinds = ["main", "concentrated"] if args.portfolio_kind == "both" else [args.portfolio_kind]
    explicit = {"main": args.main_target_book, "concentrated": args.concentrated_target_book}

    legs: list[dict[str, Any]] = []
    stress_rows: list[dict[str, Any]] = []
    crisis_diag = crisis_score_diagnostics(repo_path(args.crisis_features))
    for kind in kinds:
        leg = run_leg(
            portfolio_kind=kind,
            target_book=resolve_book(leader_dir, explicit[kind], kind),
            crisis_features=repo_path(args.crisis_features),
            thresholds_json=repo_path(args.thresholds_json) if args.thresholds_json else None,
            governor_mode=args.governor_mode,
            price_cache=repo_path(args.price_cache),
            output_dir=output_dir,
            cost_bps=args.cost_bps,
            max_fill_lag_days=args.max_fill_lag_days,
        )
        legs.append(leg)
        stress_rows.extend(leg.get("stress_windows", []) or [])

    payload = {
        "status": "completed" if any(l.get("status") == "completed" for l in legs) else "blocked",
        "research_only": True,
        "valid_for_production": False,
        "promotion_allowed_without_human_approval": False,
        "official_metric_mode": "broker_ledger_next_close",
        "governor_mode": args.governor_mode,
        "crisis_features": str(repo_path(args.crisis_features)),
        "crisis_score_diagnostics": crisis_diag,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "legs": legs,
    }
    if stress_rows:
        pd.DataFrame(stress_rows).to_csv(output_dir / "stress_window_metrics.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    dead = crisis_diag.get("dead_components") or []
    if dead:
        print(
            f"[integrated] crisis_score_dead_components={dead}"
            f" pre_renorm_ceiling={crisis_diag.get('pre_renorm_ceiling')}"
            f" score_max={crisis_diag.get('score_stats', {}).get('max')}"
            f" days_in_defense={crisis_diag.get('score_stats', {}).get('days_in_defense_default')}"
        )
    for leg in legs:
        verdict = leg.get("verdict") or {}
        print(
            f"[integrated] {leg.get('portfolio_kind')}: status={leg.get('status')}"
            + (
                f" cagr_delta={verdict.get('cagr_delta_pp', float('nan')):+.2f}pp"
                f" mdd_delta={verdict.get('mdd_delta_pp', float('nan')):+.2f}pp gates_pass={verdict.get('gates_pass')}"
                if verdict
                else ""
            )
        )
    return 0 if payload["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
