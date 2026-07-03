#!/usr/bin/env python3
"""Replay an official Main target book with its fast-crash hedge removed.

This is a research-only attribution tool. It keeps the official target book
fixed, removes the hedge ticker rows, moves the removed hedge weight to cash,
and replays both the original hedge-on book and the hedge-off counterfactual
through the broker ledger. It does not regenerate vNext target books.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_broker_ledger_replay import (  # noqa: E402
    CASH_CARRY_MODE_NONE,
    CASH_CARRY_MODE_RISK_FREE,
    CASH_TICKERS,
    CashCarryConfig,
    replay,
)


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def clean_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def weight_column(frame: pd.DataFrame) -> str:
    if "weight" in frame.columns:
        return "weight"
    if "target_weight" in frame.columns:
        return "target_weight"
    raise ValueError("target book must include weight or target_weight")


def normalize_book_weights(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    col = weight_column(out)
    out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
    if "target_weight" not in out.columns:
        out["target_weight"] = out[col]
    else:
        out["target_weight"] = pd.to_numeric(out["target_weight"], errors="coerce").fillna(out[col])
    if "weight" not in out.columns:
        out["weight"] = out["target_weight"]
    return out


def cash_row(template: pd.Series, rebalance_date: str, portfolio_kind: str, cash_weight: float) -> dict[str, Any]:
    row = template.to_dict()
    for key in row:
        if key not in {"rebalance_date", "ticker", "Name", "sector", "industry_group", "portfolio_kind", "variant_id"}:
            row[key] = ""
    row.update(
        {
            "rebalance_date": rebalance_date,
            "ticker": "CASH",
            "Name": "Cash",
            "sector": "Cash",
            "industry_group": "Cash",
            "portfolio_kind": portfolio_kind,
            "weight": float(cash_weight),
            "target_weight": float(cash_weight),
            "selection_reason": "hedge_off_cash_residual" if "selection_reason" in template.index else "",
        }
    )
    return row


def remove_hedge_to_cash(
    book: pd.DataFrame,
    *,
    hedge_ticker: str = "SH",
    portfolio_kind: str = "main",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if book.empty:
        return book.copy(), pd.DataFrame(), {
            "status": "blocked",
            "reason": "empty_target_book",
            "hedge_ticker": hedge_ticker,
            "removed_hedge_rows": 0,
        }
    if "rebalance_date" not in book.columns or "ticker" not in book.columns:
        return book.copy(), pd.DataFrame(), {
            "status": "blocked",
            "reason": "missing_rebalance_date_or_ticker",
            "hedge_ticker": hedge_ticker,
            "removed_hedge_rows": 0,
        }

    hedge = clean_ticker(hedge_ticker)
    base = normalize_book_weights(book)
    base["rebalance_date"] = pd.to_datetime(base["rebalance_date"], errors="coerce")
    base = base.dropna(subset=["rebalance_date"]).copy()
    base["ticker"] = base["ticker"].map(clean_ticker)
    rebuilt: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []

    for raw_dt in sorted(base["rebalance_date"].dropna().unique()):
        dt = pd.Timestamp(raw_dt).normalize()
        day = base[base["rebalance_date"].eq(raw_dt)].copy()
        before_total = float(pd.to_numeric(day["weight"], errors="coerce").fillna(0.0).sum())
        hedge_mask = day["ticker"].eq(hedge)
        hedge_weight = float(pd.to_numeric(day.loc[hedge_mask, "weight"], errors="coerce").fillna(0.0).sum())
        hedge_rows = int(hedge_mask.sum())
        day = day.loc[~hedge_mask].copy()
        cash_mask = day["ticker"].isin(CASH_TICKERS)
        existing_cash = float(pd.to_numeric(day.loc[cash_mask, "weight"], errors="coerce").fillna(0.0).sum())
        new_cash = max(0.0, existing_cash + hedge_weight)
        if cash_mask.any():
            cash_indices = list(day.index[cash_mask])
            day.loc[cash_mask, ["weight", "target_weight"]] = 0.0
            day.loc[cash_indices[0], "weight"] = new_cash
            day.loc[cash_indices[0], "target_weight"] = new_cash
        elif new_cash > 1e-12:
            template = day.iloc[0] if not day.empty else base.iloc[0]
            day = pd.concat([day, pd.DataFrame([cash_row(template, dt.date().isoformat(), portfolio_kind, new_cash)])], ignore_index=True)
        day["hedge_off_counterfactual"] = True
        rebuilt.append(day)
        after_total = float(pd.to_numeric(day["weight"], errors="coerce").fillna(0.0).sum())
        audit_rows.append(
            {
                "rebalance_date": dt.date().isoformat(),
                "hedge_ticker": hedge,
                "hedge_rows_removed": hedge_rows,
                "hedge_weight_removed": hedge_weight,
                "cash_weight_before": existing_cash,
                "cash_weight_after": new_cash,
                "total_weight_before": before_total,
                "total_weight_after": after_total,
            }
        )

    out = pd.concat(rebuilt, ignore_index=True) if rebuilt else base.loc[base["ticker"].ne(hedge)].copy()
    out["rebalance_date"] = pd.to_datetime(out["rebalance_date"], errors="coerce").dt.date.astype(str)
    out = out.sort_values(["rebalance_date", "weight"], ascending=[True, False]).reset_index(drop=True)
    audit = pd.DataFrame(audit_rows)
    summary = {
        "status": "completed",
        "portfolio_kind": portfolio_kind,
        "hedge_ticker": hedge,
        "removed_hedge_rows": int(audit["hedge_rows_removed"].sum()) if not audit.empty else 0,
        "hedge_signal_dates": int((audit["hedge_rows_removed"] > 0).sum()) if not audit.empty else 0,
        "max_removed_hedge_weight": float(audit["hedge_weight_removed"].max()) if not audit.empty else 0.0,
        "sum_removed_hedge_weight": float(audit["hedge_weight_removed"].sum()) if not audit.empty else 0.0,
        "cash_residual_policy": "move_removed_hedge_weight_to_cash",
        "research_only": True,
        "production_activation_allowed": False,
    }
    return out, audit, summary


def cash_carry_config(mode: str, *, rate_path: str = "", rate_source: str = "DGS3MO") -> CashCarryConfig:
    if mode == CASH_CARRY_MODE_RISK_FREE:
        return CashCarryConfig(
            mode=CASH_CARRY_MODE_RISK_FREE,
            rate_source=rate_source,
            rate_lag_days=1,
            haircut_bps=50.0,
            day_count=365,
            rate_path=repo_path(rate_path) if rate_path else None,
        )
    return CashCarryConfig(mode=CASH_CARRY_MODE_NONE)


def metric_row(label: str, mode: str, metrics: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "arm": label,
        "cash_carry_mode": mode,
        "status": metrics.get("status"),
        "reason": metrics.get("reason", ""),
        "metric_mode": metrics.get("metric_mode"),
        "cagr": metrics.get("cagr"),
        "max_dd": metrics.get("max_dd"),
        "sharpe": metrics.get("sharpe"),
        "years": metrics.get("years"),
        "avg_cash_weight": metrics.get("avg_cash_weight"),
        "trade_count": metrics.get("trade_count"),
        "total_fees_usd": metrics.get("total_fees_usd"),
        "end_date": metrics.get("end_date"),
        "end_date_matches_official": metrics.get("end_date_matches_official"),
        "replay_end_skipped_rebalance_count": metrics.get("replay_end_skipped_rebalance_count"),
    }
    if baseline:
        for key in ["cagr", "max_dd", "sharpe", "avg_cash_weight"]:
            try:
                row[f"delta_{key}_vs_hedge_on"] = float(row[key]) - float(baseline[key])
            except Exception:
                row[f"delta_{key}_vs_hedge_on"] = ""
    return row


def load_official_main_metrics(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = repo_path(path)
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if "portfolios" in payload and isinstance(payload["portfolios"], dict):
        return payload["portfolios"].get("main") or {}
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    target_book = repo_path(args.target_book)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    original = pd.read_csv(target_book)
    normalized = normalize_book_weights(original)
    hedge_off, audit, overlay_summary = remove_hedge_to_cash(
        normalized,
        hedge_ticker=args.hedge_ticker,
        portfolio_kind=args.portfolio_kind,
    )
    original_book = output_dir / "hedge_on_target_book.csv"
    hedge_off_book = output_dir / "hedge_off_target_book.csv"
    normalized.to_csv(original_book, index=False)
    hedge_off.to_csv(hedge_off_book, index=False)
    audit.to_csv(output_dir / "hedge_removal_audit.csv", index=False)
    write_json(output_dir / "hedge_removal_summary.json", overlay_summary)

    rows: list[dict[str, Any]] = []
    metrics_by_arm: dict[str, dict[str, Any]] = {}
    for mode in [CASH_CARRY_MODE_NONE, CASH_CARRY_MODE_RISK_FREE]:
        for label, book in [("hedge_on", original_book), ("hedge_off", hedge_off_book)]:
            arm_dir = output_dir / f"{label}_{mode}"
            metrics = replay(
                target_book=book,
                price_cache=price_cache,
                output_dir=arm_dir / "broker",
                portfolio_kind=args.portfolio_kind,
                fill_mode="next_close",
                cost_bps=args.cost_bps,
                integer_shares=True,
                max_fill_lag_days=args.max_fill_lag_days,
                replay_end_date=args.replay_end_date or None,
                official_baseline_end_date=args.official_baseline_end_date or args.replay_end_date or None,
                cash_carry_config=cash_carry_config(mode, rate_path=args.cash_rate_path, rate_source=args.cash_rate_source),
            )
            key = f"{label}_{mode}"
            metrics_by_arm[key] = metrics
            baseline = metrics_by_arm.get(f"hedge_on_{mode}") if label == "hedge_off" else None
            rows.append(metric_row(label, mode, metrics, baseline=baseline))

    rows_df = pd.DataFrame(rows)
    rows_df.to_csv(output_dir / "hedge_on_vs_off.csv", index=False)
    official = load_official_main_metrics(args.official_metrics)
    summary = {
        "status": "completed",
        "schema_version": "main-hedge-off-baseline-replay-v1",
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "portfolio_kind": args.portfolio_kind,
        "replay_end_date": args.replay_end_date,
        "official_baseline_end_date": args.official_baseline_end_date,
        "official_main_metrics": {
            key: official.get(key)
            for key in ["cagr", "max_dd", "sharpe", "years", "avg_cash_weight", "latest_cash_weight"]
            if key in official
        },
        "hedge_removal": overlay_summary,
        "research_only": True,
        "production_activation_allowed": False,
        "arms": rows,
    }
    write_json(output_dir / "summary.json", summary)
    lines = [
        "# Main Hedge-OFF Fixed-Book Replay",
        "",
        f"- target_book: `{target_book}`",
        f"- price_cache: `{price_cache}`",
        f"- replay_end_date: `{args.replay_end_date}`",
        f"- hedge_ticker_removed: `{args.hedge_ticker}`",
        f"- removed hedge rows: `{overlay_summary.get('removed_hedge_rows')}` across `{overlay_summary.get('hedge_signal_dates')}` dates",
        "",
        "| arm | cash carry | status | CAGR | MaxDD | Sharpe | avg cash | delta CAGR vs hedge-on | delta MaxDD vs hedge-on |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('arm')} | {row.get('cash_carry_mode')} | {row.get('status')} | "
            f"{row.get('cagr')} | {row.get('max_dd')} | {row.get('sharpe')} | {row.get('avg_cash_weight')} | "
            f"{row.get('delta_cagr_vs_hedge_on', '')} | {row.get('delta_max_dd_vs_hedge_on', '')} |"
        )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-book", required=True)
    parser.add_argument("--price-cache", required=True)
    parser.add_argument("--output-dir", default="outputs/main_hedge_off_baseline")
    parser.add_argument("--official-metrics", default="")
    parser.add_argument("--portfolio-kind", choices=["main"], default="main")
    parser.add_argument("--hedge-ticker", default="SH")
    parser.add_argument("--replay-end-date", default="")
    parser.add_argument("--official-baseline-end-date", default="")
    parser.add_argument("--cash-rate-path", default="")
    parser.add_argument("--cash-rate-source", default="DGS3MO")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, default=str))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
