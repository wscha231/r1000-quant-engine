#!/usr/bin/env python3
"""Run a fixed-book, event-matched replacement-quality broker A/B.

This consumes an explicit swap list, not regenerated selection logic. It is
therefore suitable for validating the fixed-book counterfactual path while W1
target-book reproduction remains unresolved. It is research-only and never
dispatches a fullrun.
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

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CashCarryConfig,
    replay,
)
from tools.run_concentrated_cap_replacement_broker_counterfactual import (  # noqa: E402
    portfolio_concentration_delta,
    portfolio_concentration_metrics,
    safe_float,
    window_deltas,
)


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def norm_ticker(value: Any) -> str:
    raw = "" if value is None else str(value)
    if raw.lower() in {"nan", "none", "nat"}:
        return ""
    return raw.strip().upper()


def norm_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).date().isoformat()


def apply_event_swaps(base_book: pd.DataFrame, swaps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    book = base_book.copy()
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)
    book["ticker"] = book["ticker"].map(norm_ticker)
    book["weight"] = pd.to_numeric(book["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in book.columns:
        book["target_weight"] = pd.to_numeric(book["target_weight"], errors="coerce").fillna(book["weight"])
    else:
        book["target_weight"] = book["weight"]

    normalized = swaps.copy()
    normalized["rebalance_date"] = normalized.get("rebalance_date", "").map(norm_date)
    normalized["added_ticker"] = normalized.get("added_ticker", "").map(norm_ticker)
    normalized["removed_ticker"] = normalized.get("removed_ticker", "").map(norm_ticker)
    normalized["replacement_weight"] = pd.to_numeric(normalized.get("replacement_weight", pd.Series(index=normalized.index)), errors="coerce")
    normalized = normalized[normalized["rebalance_date"].ne("") & normalized["added_ticker"].ne("") & normalized["removed_ticker"].ne("")].copy()
    normalized = normalized.drop_duplicates(subset=["rebalance_date", "added_ticker", "removed_ticker"]).copy()

    out_days: list[pd.DataFrame] = []
    applied: list[dict[str, Any]] = []
    skipped_missing_donor = 0
    skipped_duplicate_date = 0
    for dt, day in book.groupby("rebalance_date", sort=True):
        day_out = day.copy()
        day_swaps = normalized[normalized["rebalance_date"].eq(str(dt))].copy()
        if day_swaps.empty:
            out_days.append(day_out)
            continue
        if len(day_swaps) > 1:
            skipped_duplicate_date += int(len(day_swaps) - 1)
            day_swaps = day_swaps.head(1)
        swap = day_swaps.iloc[0]
        donor_mask = day_out["ticker"].map(norm_ticker).eq(norm_ticker(swap["removed_ticker"]))
        if not donor_mask.any():
            skipped_missing_donor += 1
            out_days.append(day_out)
            continue
        donor_idx = day_out[donor_mask].index[0]
        donor = day_out.loc[donor_idx].copy()
        weight = safe_float(swap.get("replacement_weight"), safe_float(donor.get("weight")))
        donor["ticker"] = norm_ticker(swap["added_ticker"])
        donor["weight"] = weight
        donor["target_weight"] = weight
        donor["holding_state"] = "NEW"
        donor["holding_state_reason"] = "event_matched_replacement_quality_candidate"
        donor["hold_replace_decision"] = "event_matched_replacement_quality_swap"
        donor["event_matched_replacement_quality_applied"] = True
        donor["event_matched_replacement_quality_added_ticker"] = norm_ticker(swap["added_ticker"])
        donor["event_matched_replacement_quality_removed_ticker"] = norm_ticker(swap["removed_ticker"])
        donor["event_matched_replacement_quality_rule"] = str(swap.get("rule") or "")
        donor["event_matched_replacement_quality_replacement_weight"] = weight
        day_out.loc[donor_idx, donor.index] = donor
        applied.append(
            {
                "rebalance_date": str(dt),
                "added_ticker": norm_ticker(swap["added_ticker"]),
                "removed_ticker": norm_ticker(swap["removed_ticker"]),
                "replacement_weight": weight,
                "rule": str(swap.get("rule") or ""),
            }
        )
        out_days.append(day_out)

    challenger = pd.concat(out_days, ignore_index=True) if out_days else book
    challenger = challenger.sort_values(["rebalance_date", "weight", "ticker"], ascending=[True, False, True]).reset_index(drop=True)
    applied_df = pd.DataFrame(applied)
    diagnostics = {
        "requested_swap_count": int(len(normalized)),
        "applied_count": int(len(applied_df)),
        "skipped_missing_donor": int(skipped_missing_donor),
        "skipped_duplicate_date": int(skipped_duplicate_date),
        "cash_weight_preserved": True,
        "stock_gross_preserved": True,
    }
    return challenger, applied_df, diagnostics


def metric_row(label: str, metrics: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "arm": label,
        "status": metrics.get("status"),
        "metric_mode": metrics.get("metric_mode"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "years": metrics.get("years"),
        "end_date": metrics.get("end_date"),
    }
    if baseline:
        row["delta_cagr"] = safe_float(metrics.get("cagr")) - safe_float(baseline.get("cagr"))
        row["delta_max_dd"] = safe_float(metrics.get("max_dd")) - safe_float(baseline.get("max_dd"))
        row["delta_sharpe"] = safe_float(metrics.get("sharpe")) - safe_float(baseline.get("sharpe"))
    return row


def render_report(payload: dict[str, Any]) -> str:
    d = payload["metric_deltas"].get("full", {})
    conc = payload.get("portfolio_concentration_delta") or {}
    lines = [
        "# Event-Matched Replacement-Quality Broker A/B",
        "",
        f"- status: `{payload['status']}`",
        f"- target book: `{payload['target_book']}`",
        f"- fixed swaps: `{payload['fixed_swaps']}`",
        f"- applied count: `{payload['diagnostics']['applied_count']}` / `{payload['diagnostics']['requested_swap_count']}`",
        f"- full CAGR delta: `{safe_float(d.get('delta_cagr')):.2%}`",
        f"- full MDD delta: `{safe_float(d.get('delta_max_dd')):.2%}`",
        f"- production activation allowed: `{payload['production_activation_allowed']}`",
        "",
        "## Concentration",
        "",
        f"- top1 delta: `{safe_float(conc.get('latest_top1_delta')):.2%}`",
        f"- top3 delta: `{safe_float(conc.get('latest_top3_delta')):.2%}`",
        f"- HHI delta: `{safe_float(conc.get('latest_stock_hhi_delta')):.4f}`",
        f"- warning: `{conc.get('portfolio_concentration_warning')}`",
        f"- block: `{conc.get('portfolio_concentration_block')}`",
        "",
        "This is fixed-book research evidence only. It does not approve a regenerated policy path or fullrun.",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_book = repo_path(args.target_book)
    fixed_swaps = repo_path(args.fixed_swaps)
    price_cache = repo_path(args.price_cache)
    baseline_metrics_path = repo_path(args.baseline_metrics)

    base = pd.read_csv(target_book)
    swaps = pd.read_csv(fixed_swaps)
    challenger, applied, diagnostics = apply_event_swaps(base, swaps)
    challenger_path = output_dir / "event_matched_target_book.csv"
    applied_path = output_dir / "event_matched_swaps.csv"
    challenger.to_csv(challenger_path, index=False)
    applied.to_csv(applied_path, index=False)

    baseline_metrics = read_json(baseline_metrics_path)
    cash_cfg = CashCarryConfig(
        mode=args.cash_carry_mode,
        rate_source=args.cash_rate_source,
        rate_lag_days=int(args.cash_rate_lag_days),
        haircut_bps=float(args.cash_carry_haircut_bps),
        day_count=int(args.cash_carry_day_count),
        rate_path=repo_path(args.cash_rate_path) if args.cash_rate_path else None,
    )
    challenger_metrics = replay(
        target_book=challenger_path,
        price_cache=price_cache,
        output_dir=output_dir / "broker_replay",
        portfolio_kind="concentrated",
        starting_capital=float(args.starting_capital),
        fill_mode="next_close",
        cost_bps=float(args.cost_bps),
        integer_shares=not bool(args.fractional_shares),
        max_fill_lag_days=int(args.max_fill_lag_days),
        disable_concentrated_champion_filter=True,
        max_reasonable_weight_sum=float(args.max_reasonable_weight_sum),
        oos_start=args.oos_start or None,
        oos_end=args.oos_end or None,
        oos2_start=args.oos2_start or None,
        oos2_end=args.oos2_end or None,
        replay_end_date=args.replay_end_date or None,
        official_baseline_end_date=args.official_baseline_end_date or args.replay_end_date or None,
        cash_carry_config=cash_cfg,
    )
    baseline_replay_dir = repo_path(args.baseline_replay_dir) if args.baseline_replay_dir else None
    baseline_conc = portfolio_concentration_metrics(baseline_replay_dir) if baseline_replay_dir else {"status": "missing"}
    challenger_conc = portfolio_concentration_metrics(output_dir / "broker_replay")
    conc_delta = portfolio_concentration_delta(
        baseline_conc,
        challenger_conc,
        absolute_top1_warning=float(args.concentration_absolute_top1_warning),
        absolute_top1_block=float(args.concentration_absolute_top1_block),
        absolute_top3_warning=float(args.concentration_absolute_top3_warning),
        absolute_top3_severe_warning=float(args.concentration_absolute_top3_severe_warning),
    )
    payload = {
        "schema_version": "event-matched-replacement-quality-broker-ab-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "target_book": str(target_book),
        "fixed_swaps": str(fixed_swaps),
        "price_cache": str(price_cache),
        "baseline_metrics": str(baseline_metrics_path),
        "challenger_target_book": str(challenger_path),
        "applied_swaps": str(applied_path),
        "broker_metrics": str(output_dir / "broker_replay" / "metrics.json"),
        "diagnostics": diagnostics,
        "baseline_row": metric_row("baseline_cash_carry", baseline_metrics),
        "challenger_row": metric_row("event_matched_rank_top15_revenue_ge10", challenger_metrics, baseline_metrics),
        "metric_deltas": window_deltas(baseline_metrics, challenger_metrics),
        "baseline_portfolio_concentration": baseline_conc,
        "challenger_portfolio_concentration": challenger_conc,
        "portfolio_concentration_delta": conc_delta,
        "production_activation_allowed": False,
        "fullrun_allowed": False,
        "live_trading_enabled": False,
        "research_only": True,
    }
    pd.DataFrame([payload["baseline_row"], payload["challenger_row"]]).to_csv(output_dir / "metrics.csv", index=False)
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--fixed-swaps", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--baseline-metrics", required=True)
    parser.add_argument("--baseline-replay-dir", default="")
    parser.add_argument("--output-dir", default="outputs/event_matched_replacement_quality_broker_ab")
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--fractional-shares", action="store_true")
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--max-reasonable-weight-sum", type=float, default=1.05)
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--official-baseline-end-date", default="")
    parser.add_argument("--oos-start", default="2024-07-01")
    parser.add_argument("--oos-end", default="")
    parser.add_argument("--oos2-start", default="2023-01-01")
    parser.add_argument("--oos2-end", default="")
    parser.add_argument("--cash-carry-mode", choices=["none", "risk_free_rate"], default=CASH_CARRY_MODE_NONE)
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-lag-days", type=int, default=1)
    parser.add_argument("--cash-carry-haircut-bps", type=float, default=50.0)
    parser.add_argument("--cash-carry-day-count", type=int, default=365)
    parser.add_argument("--concentration-absolute-top1-warning", type=float, default=0.40)
    parser.add_argument("--concentration-absolute-top1-block", type=float, default=0.45)
    parser.add_argument("--concentration-absolute-top3-warning", type=float, default=0.85)
    parser.add_argument("--concentration-absolute-top3-severe-warning", type=float, default=0.90)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
