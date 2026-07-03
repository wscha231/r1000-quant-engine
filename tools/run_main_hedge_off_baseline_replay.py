#!/usr/bin/env python3
"""Measure Main baseline after removing the SH hedge sleeve.

This is a research-only fixed-book replay. It does not regenerate target books,
does not mutate production policy, and does not dispatch a fullrun.
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
    CASH_CARRY_MODE_RISK_FREE,
    replay as broker_replay,
    resolve_cash_carry_config,
)


DEFAULT_TARGET_BOOK = (
    "artifacts/fullrun_28436307420/official/outputs/alphaops_vnext/"
    "official_main_target_book.csv"
)
DEFAULT_OFFICIAL_METRICS = (
    "artifacts/fullrun_28436307420/official/outputs/account_evaluation/"
    "official_metrics.json"
)
DEFAULT_PRICE_CACHE = "artifacts/fullrun_28436307420/official/cache_prices"
DEFAULT_FALLBACK_PRICE_CACHE = "outputs/phase1_replay_goal_test/cache_prices"
DEFAULT_OUTPUT_DIR = "outputs/main_hedge_off_baseline"
DEFAULT_REPLAY_END_DATE = "2026-06-29"
DEFAULT_HEDGE_TICKER = "SH"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        if pd.isna(out):
            return default
        return out
    except Exception:
        return default


def main_portfolio_metrics(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if isinstance(data.get("portfolios"), dict):
        return dict(data["portfolios"].get("main") or {})
    if isinstance(data.get("main"), dict):
        return dict(data.get("main") or {})
    return dict(data)


def price_cache_file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file() and item.name != "replay_price_cache_manifest.json")


def resolve_price_cache(requested: Path, raw_arg: str) -> tuple[Path, dict[str, Any]]:
    fallback = repo_path(DEFAULT_FALLBACK_PRICE_CACHE)
    requested_count = price_cache_file_count(requested)
    fallback_count = price_cache_file_count(fallback)
    use_fallback = (
        str(raw_arg).replace("\\", "/").strip() == DEFAULT_PRICE_CACHE
        and requested_count == 0
        and fallback_count > 0
    )
    selected = fallback if use_fallback else requested
    return selected, {
        "requested_price_cache": str(requested),
        "selected_price_cache": str(selected),
        "requested_price_cache_file_count": int(requested_count),
        "fallback_price_cache": str(fallback),
        "fallback_price_cache_file_count": int(fallback_count),
        "price_cache_fallback_used": bool(use_fallback),
    }


def bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def build_hedge_off_book(
    *,
    target_book: Path,
    output_path: Path,
    hedge_ticker: str = DEFAULT_HEDGE_TICKER,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = pd.read_csv(target_book)
    if raw.empty:
        raise ValueError(f"target book is empty: {target_book}")
    if "rebalance_date" not in raw.columns or "ticker" not in raw.columns or "weight" not in raw.columns:
        raise ValueError("target book must include rebalance_date, ticker, and weight")

    frame = raw.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
    if "target_weight" in frame.columns:
        frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="coerce").fillna(frame["weight"])
    else:
        frame["target_weight"] = frame["weight"]

    hedge_ticker = hedge_ticker.upper().strip()
    hedge_mask = frame["ticker"].eq(hedge_ticker)
    removed = frame.loc[hedge_mask].copy()
    out = frame.loc[~hedge_mask].copy()
    if removed.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(output_path, index=False)
        return removed, {
            "hedge_ticker": hedge_ticker,
            "hedge_rows_removed": 0,
            "hedge_signal_date_count": 0,
            "hedge_weight_removed_sum": 0.0,
            "max_hedge_weight_removed": 0.0,
            "cash_replacement_policy": "none_no_hedge_rows",
        }

    cash_add = removed.groupby("rebalance_date")["weight"].sum().to_dict()
    for rebalance_date, hedge_weight in cash_add.items():
        date_mask = out["rebalance_date"].astype(str).eq(str(rebalance_date))
        cash_mask = date_mask & out["ticker"].isin({"CASH", "__CASH__"})
        if cash_mask.any():
            first_idx = out.index[cash_mask][0]
            out.loc[first_idx, "weight"] = safe_float(out.loc[first_idx, "weight"]) + float(hedge_weight)
            out.loc[first_idx, "target_weight"] = safe_float(out.loc[first_idx, "target_weight"]) + float(hedge_weight)
            if "selection_reason" in out.columns:
                reason = str(out.loc[first_idx, "selection_reason"] or "")
                suffix = "hedge_off_cash_replacement"
                out.loc[first_idx, "selection_reason"] = suffix if not reason else f"{reason}|{suffix}"
        else:
            template = out.loc[date_mask].iloc[0].to_dict() if date_mask.any() else {col: "" for col in out.columns}
            for col in out.columns:
                template.setdefault(col, "")
            template["rebalance_date"] = rebalance_date
            template["ticker"] = "CASH"
            template["weight"] = float(hedge_weight)
            template["target_weight"] = float(hedge_weight)
            if "Name" in out.columns:
                template["Name"] = "Cash"
            if "sector" in out.columns:
                template["sector"] = "Cash"
            if "industry_group" in out.columns:
                template["industry_group"] = "Cash"
            if "selection_reason" in out.columns:
                template["selection_reason"] = "hedge_off_cash_replacement"
            out = pd.concat([out, pd.DataFrame([template])], ignore_index=True)

    out = out.sort_values(["rebalance_date", "ticker"]).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    removed.to_csv(output_path.parent / "removed_hedge_rows.csv", index=False)
    stats = {
        "hedge_ticker": hedge_ticker,
        "hedge_rows_removed": int(len(removed)),
        "hedge_signal_date_count": int(removed["rebalance_date"].nunique()),
        "hedge_signal_dates": sorted(str(x) for x in removed["rebalance_date"].unique()),
        "hedge_weight_removed_sum": float(removed["weight"].sum()),
        "max_hedge_weight_removed": float(removed["weight"].max()),
        "cash_replacement_policy": "move_removed_hedge_weight_to_cash",
        "output_target_book": str(output_path),
    }
    return removed, stats


def metric_row(label: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "arm": label,
        "status": metrics.get("status", "completed" if "cagr" in metrics else ""),
        "metric_mode": metrics.get("metric_mode", ""),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd", metrics.get("max_drawdown"))),
        "sharpe": safe_float(metrics.get("sharpe")),
        "ending_capital_usd": safe_float(metrics.get("ending_capital_usd")),
        "trade_count": safe_float(metrics.get("trade_count")),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "latest_cash_weight": safe_float(metrics.get("latest_cash_weight")),
        "start_date": metrics.get("start_date", ""),
        "end_date": metrics.get("end_date", ""),
        "years": safe_float(metrics.get("years")),
        "end_date_matches_official": metrics.get("end_date_matches_official", ""),
        "cash_interest_accrued_usd": safe_float(metrics.get("cash_interest_accrued_usd")),
    }


def run_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    cash_carry_mode: str,
    cash_rate_path: Path | None,
    replay_end_date: str,
    starting_capital: float,
) -> dict[str, Any]:
    return broker_replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir,
        portfolio_kind="main",
        starting_capital=starting_capital,
        fill_mode="next_close",
        cost_bps=25.0,
        integer_shares=True,
        max_fill_lag_days=7,
        replay_end_date=replay_end_date,
        official_baseline_end_date=replay_end_date,
        cash_carry_config=resolve_cash_carry_config(
            mode=cash_carry_mode,
            rate_source="DGS3MO",
            rate_lag_days=1,
            haircut_bps=50.0,
            day_count=365,
            rate_path=cash_rate_path,
        ),
    )


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Main Hedge-OFF Baseline Replay",
        "",
        f"- Status: `{summary['status']}`",
        f"- Target book: `{summary['target_book']}`",
        f"- Hedge ticker removed: `{summary['hedge_stats']['hedge_ticker']}`",
        f"- Hedge rows removed: `{summary['hedge_stats']['hedge_rows_removed']}`",
        f"- Hedge signal dates: `{', '.join(summary['hedge_stats'].get('hedge_signal_dates', []))}`",
        f"- Replay end date: `{summary['replay_end_date']}`",
        "",
        "| Arm | CAGR | MaxDD | Sharpe | Ending capital |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['arm']} | {row['cagr']:.2%} | {row['max_dd']:.2%} | "
            f"{row['sharpe']:.3f} | {row['ending_capital_usd']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- quote_long_only_allowed: `{bool_text(summary['quote_long_only_allowed'])}`",
            f"- quote_main_solved_allowed: `{bool_text(summary['quote_main_solved_allowed'])}`",
            f"- main_cash_carry_target_pass: `{bool_text(summary['main_cash_carry_target_pass'])}`",
            f"- main_cash_carry_cagr_shortfall_pp: `{summary['main_cash_carry_cagr_shortfall_pp']:.4f}`",
            f"- main_cash_carry_mdd_margin_pp: `{summary['main_cash_carry_mdd_margin_pp']:.4f}`",
            f"- governance_reopen_required: `{bool_text(summary['governance_reopen_required'])}`",
            "",
            "This is a research-only fixed-book replay. It does not enable live trading or production promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_book = repo_path(args.target_book)
    official_metrics_path = repo_path(args.official_metrics)
    requested_price_cache = repo_path(args.price_cache)
    price_cache, price_cache_resolution = resolve_price_cache(requested_price_cache, args.price_cache)
    cash_rate_path = repo_path(args.cash_rate_path) if args.cash_rate_path else None
    replay_end_date = args.replay_end_date

    official_main = main_portfolio_metrics(official_metrics_path)
    hedge_off_book = output_dir / "main_target_book_hedge_off.csv"
    removed, hedge_stats = build_hedge_off_book(
        target_book=target_book,
        output_path=hedge_off_book,
        hedge_ticker=args.hedge_ticker,
    )

    hedge_on_zero = run_replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir / "hedge_on_zero_yield_replay",
        cash_carry_mode=CASH_CARRY_MODE_NONE,
        cash_rate_path=None,
        replay_end_date=replay_end_date,
        starting_capital=args.starting_capital,
    )
    hedge_off_zero = run_replay(
        target_book=hedge_off_book,
        price_cache=price_cache,
        output_dir=output_dir / "hedge_off_zero_yield_replay",
        cash_carry_mode=CASH_CARRY_MODE_NONE,
        cash_rate_path=None,
        replay_end_date=replay_end_date,
        starting_capital=args.starting_capital,
    )
    hedge_off_cash = run_replay(
        target_book=hedge_off_book,
        price_cache=price_cache,
        output_dir=output_dir / "hedge_off_cash_carry_replay",
        cash_carry_mode=CASH_CARRY_MODE_RISK_FREE,
        cash_rate_path=cash_rate_path,
        replay_end_date=replay_end_date,
        starting_capital=args.starting_capital,
    )
    hedge_on_cash = run_replay(
        target_book=target_book,
        price_cache=price_cache,
        output_dir=output_dir / "hedge_on_cash_carry_replay",
        cash_carry_mode=CASH_CARRY_MODE_RISK_FREE,
        cash_rate_path=cash_rate_path,
        replay_end_date=replay_end_date,
        starting_capital=args.starting_capital,
    )

    rows = [
        metric_row("official_hedge_on_zero", official_main),
        metric_row("hedge_on_zero_replay", hedge_on_zero),
        metric_row("hedge_on_cash_carry_replay", hedge_on_cash),
        metric_row("hedge_off_zero_yield", hedge_off_zero),
        metric_row("hedge_off_cash_carry", hedge_off_cash),
    ]
    pd.DataFrame(rows).to_csv(output_dir / "hedge_on_vs_off.csv", index=False)

    official_cagr = safe_float(official_main.get("cagr"))
    official_mdd = safe_float(official_main.get("max_dd", official_main.get("max_drawdown")))
    on_replay_cagr = safe_float(hedge_on_zero.get("cagr"))
    on_replay_mdd = safe_float(hedge_on_zero.get("max_dd", hedge_on_zero.get("max_drawdown")))
    off_cash_cagr = safe_float(hedge_off_cash.get("cagr"))
    off_cash_mdd = safe_float(hedge_off_cash.get("max_dd", hedge_off_cash.get("max_drawdown")))
    off_zero_cagr = safe_float(hedge_off_zero.get("cagr"))
    off_zero_mdd = safe_float(hedge_off_zero.get("max_dd", hedge_off_zero.get("max_drawdown")))
    valid_replays = all(m.get("status") == "completed" for m in [hedge_on_zero, hedge_off_zero, hedge_off_cash, hedge_on_cash])
    end_date_ok = all(bool(m.get("end_date_matches_official")) for m in [hedge_on_zero, hedge_off_zero, hedge_off_cash, hedge_on_cash])
    main_cash_carry_target_pass = bool(off_cash_cagr >= 0.35 and off_cash_mdd >= -0.25)
    cagr_shortfall_pp = max(0.0, 0.35 - off_cash_cagr) * 100.0
    mdd_margin_pp = (off_cash_mdd - (-0.25)) * 100.0
    governance_reopen_required = bool(off_cash_mdd < -0.25)
    status = (
        "governance_reopen_required"
        if governance_reopen_required
        else "main_long_only_research_pass"
        if main_cash_carry_target_pass
        else "main_long_only_research_fail"
    )
    payload = {
        "schema_version": "main-hedge-off-baseline-replay-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "target_book": str(target_book),
        "hedge_off_target_book": str(hedge_off_book),
        "official_metrics": str(official_metrics_path),
        "price_cache": str(price_cache),
        "price_cache_resolution": price_cache_resolution,
        "cash_rate_path": str(cash_rate_path) if cash_rate_path else "",
        "replay_end_date": replay_end_date,
        "hedge_stats": hedge_stats,
        "hedge_on_cagr": official_cagr,
        "hedge_on_max_dd": official_mdd,
        "hedge_on_replay_cagr": on_replay_cagr,
        "hedge_on_replay_max_dd": on_replay_mdd,
        "hedge_off_cagr": off_zero_cagr,
        "hedge_off_max_dd": off_zero_mdd,
        "hedge_off_cash_carry_cagr": off_cash_cagr,
        "hedge_off_cash_carry_max_dd": off_cash_mdd,
        "delta_cagr": off_cash_cagr - safe_float(hedge_on_cash.get("cagr")),
        "delta_max_dd": off_cash_mdd - safe_float(hedge_on_cash.get("max_dd", hedge_on_cash.get("max_drawdown"))),
        "official_vs_control_cagr_delta": on_replay_cagr - official_cagr,
        "official_vs_control_max_dd_delta": on_replay_mdd - official_mdd,
        "end_date_matches_official": bool(end_date_ok),
        "valid_replays": bool(valid_replays),
        "quote_long_only_allowed": bool(valid_replays and end_date_ok),
        "main_cash_carry_target_pass": main_cash_carry_target_pass,
        "main_cash_carry_cagr_shortfall_pp": float(cagr_shortfall_pp),
        "main_cash_carry_mdd_margin_pp": float(mdd_margin_pp),
        "quote_main_solved_allowed": bool(valid_replays and end_date_ok and main_cash_carry_target_pass),
        "governance_reopen_required": governance_reopen_required,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
        "research_only": True,
    }
    (output_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload, rows), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", default=DEFAULT_TARGET_BOOK)
    parser.add_argument("--official-metrics", default=DEFAULT_OFFICIAL_METRICS)
    parser.add_argument("--price-cache", default=DEFAULT_PRICE_CACHE)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--replay-end-date", default=DEFAULT_REPLAY_END_DATE)
    parser.add_argument("--cash-rate-path", default="cache_macro/fred_dgs3mo_DGS3MO.parquet")
    parser.add_argument("--hedge-ticker", default=DEFAULT_HEDGE_TICKER)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("valid_replays") else 2


if __name__ == "__main__":
    raise SystemExit(main())
