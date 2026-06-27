"""Broker-ledger A/B for Concentrated score-sizing reweight arms.

This tool reuses an existing target book and price cache. It does not run the
full policy replay or mutate operating outputs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.concentrated_score_sizing_reweight import (  # noqa: E402
    CASH_TICKERS,
    DEFAULT_SINGLE_CAP,
    clean_ticker,
    reweight_concentrated_records,
    safe_float,
)

SCHEMA_VERSION = "concentrated-score-sizing-broker-ab-v1"
DEFAULT_OUTPUT_DIR = "outputs/concentrated_score_sizing_broker_ab"
ARMS = [
    {
        "arm": "baseline",
        "signal": "alphaops_vnext_score",
        "blend": 0.0,
        "rank_power": 1.0,
        "cap_mode": "baseline",
        "policy_candidate": True,
    },
    {
        "arm": "blend75_rank_power1_5_uncapped",
        "signal": "alphaops_vnext_score",
        "blend": 0.75,
        "rank_power": 1.5,
        "cap_mode": "telemetry_only",
        "policy_candidate": False,
    },
    {
        "arm": "blend75_rank_power1_5_cap30",
        "signal": "alphaops_vnext_score",
        "blend": 0.75,
        "rank_power": 1.5,
        "cap_mode": "cap30_waterfill",
        "policy_candidate": True,
    },
    {
        "arm": "blend50_rank_power1_5_cap30",
        "signal": "alphaops_vnext_score",
        "blend": 0.50,
        "rank_power": 1.5,
        "cap_mode": "cap30_waterfill",
        "policy_candidate": True,
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def resolve_target_book(latest_run: Path, explicit: str | None = None) -> Path:
    if explicit:
        path = repo_path(explicit)
        if not path.exists():
            raise FileNotFoundError(f"target book not found: {path}")
        return path
    candidates = [
        latest_run / "reports" / "operating_concentrated_target_book.csv",
        latest_run / "alphaops_vnext" / "official_concentrated_target_book.csv",
        latest_run / "market_leader_challenger" / "concentrated_target_book.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("no Concentrated target book found under latest-run")


def resolve_price_cache(latest_run: Path, price_cache: str) -> Path:
    path = repo_path(price_cache)
    if path.exists():
        return path
    fallback = latest_run.parent / "cache_prices"
    if fallback.exists():
        return fallback
    return path


def is_cash_row(row: pd.Series | dict[str, Any]) -> bool:
    return clean_ticker(row.get("ticker")) in CASH_TICKERS


def hhi(weights: list[float]) -> float:
    return float(sum(max(0.0, weight) ** 2 for weight in weights))


def baseline_date_telemetry(date_text: str, stocks: pd.DataFrame, cash: pd.DataFrame) -> dict[str, Any]:
    weights = [
        max(0.0, safe_float(row.get("target_weight"), safe_float(row.get("weight"))))
        for _, row in stocks.iterrows()
    ]
    cash_weight = float(
        sum(max(0.0, safe_float(row.get("target_weight"), safe_float(row.get("weight")))) for _, row in cash.iterrows())
    )
    return {
        "rebalance_date": date_text,
        "status": "baseline",
        "stock_gross_before": float(sum(weights)),
        "stock_gross_after": float(sum(weights)),
        "cash_weight_before": cash_weight,
        "cash_weight_after": cash_weight,
        "max_weight_before": float(max(weights)) if weights else 0.0,
        "max_weight_after": float(max(weights)) if weights else 0.0,
        "hhi_before": hhi(weights),
        "hhi_after": hhi(weights),
        "total_abs_weight_delta": 0.0,
        "cap_breach_count": int(sum(1 for weight in weights if weight > DEFAULT_SINGLE_CAP + 1e-10)),
        "cap_breach_excess_weight": float(sum(max(0.0, weight - DEFAULT_SINGLE_CAP) for weight in weights)),
        "gross_preservation_status": "baseline",
        "cash_residual_weight": 0.0,
    }


def apply_cash_residual(
    cash_rows: list[dict[str, Any]],
    *,
    residual: float,
    template: dict[str, Any],
    date_text: str,
) -> list[dict[str, Any]]:
    if residual <= 1e-12:
        return cash_rows
    if cash_rows:
        out = [dict(row) for row in cash_rows]
        old_weight = safe_float(out[0].get("weight"))
        old_target = safe_float(out[0].get("target_weight"), old_weight)
        out[0]["weight"] = old_weight + residual
        out[0]["target_weight"] = old_target + residual
        return out
    row = {key: "" for key in template.keys()}
    row.update(
        {
            "rebalance_date": date_text,
            "ticker": "CASH",
            "Name": "Cash",
            "sector": "Cash",
            "weight": residual,
            "target_weight": residual,
            "portfolio_kind": "concentrated",
            "selection_reason": "concentrated_score_sizing_reweight_cash_residual",
        }
    )
    return [row]


def generate_arm_book(
    book: pd.DataFrame,
    arm: dict[str, Any],
    *,
    single_cap: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if arm["arm"] == "baseline":
        date_rows = []
        stock_rows = []
        for date_text, group in book.groupby("rebalance_date", sort=True):
            cash_mask = group.apply(is_cash_row, axis=1)
            stocks = group.loc[~cash_mask].copy()
            cash = group.loc[cash_mask].copy()
            date_rows.append({"arm": arm["arm"], **baseline_date_telemetry(str(date_text), stocks, cash)})
            for _, row in stocks.iterrows():
                stock_rows.append(
                    {
                        "arm": arm["arm"],
                        "rebalance_date": date_text,
                        "ticker": clean_ticker(row.get("ticker")),
                        "pre_concentrated_score_sizing_reweight_weight": safe_float(row.get("target_weight"), safe_float(row.get("weight"))),
                        "concentrated_score_sizing_reweight_weight": safe_float(row.get("target_weight"), safe_float(row.get("weight"))),
                        "concentrated_score_sizing_reweight_delta": 0.0,
                        "concentrated_score_sizing_reweight_status": "baseline",
                    }
                )
        return book.copy(), pd.DataFrame(date_rows), pd.DataFrame(stock_rows)

    out_groups: list[pd.DataFrame] = []
    date_rows: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []
    for date_text, group in book.groupby("rebalance_date", sort=True):
        cash_mask = group.apply(is_cash_row, axis=1)
        stocks = group.loc[~cash_mask].copy()
        cash = group.loc[cash_mask].copy()
        before_cash = float(
            sum(max(0.0, safe_float(row.get("target_weight"), safe_float(row.get("weight")))) for _, row in cash.iterrows())
        )
        records = stocks.to_dict(orient="records")
        reweighted, telemetry = reweight_concentrated_records(
            records,
            signal=str(arm["signal"]),
            blend=float(arm["blend"]),
            rank_power=float(arm["rank_power"]),
            cap_mode=str(arm["cap_mode"]),
            single_cap=single_cap,
        )
        residual = safe_float(telemetry.get("cash_residual_weight"))
        cash_records = apply_cash_residual(
            cash.to_dict(orient="records"),
            residual=residual,
            template=group.iloc[0].to_dict() if not group.empty else {},
            date_text=str(date_text),
        )
        after_cash = float(
            sum(max(0.0, safe_float(row.get("target_weight"), safe_float(row.get("weight")))) for row in cash_records)
        )
        date_rows.append(
            {
                "arm": arm["arm"],
                "rebalance_date": date_text,
                **telemetry,
                "cash_weight_before": before_cash,
                "cash_weight_after": after_cash,
            }
        )
        for row in reweighted:
            stock_rows.append({"arm": arm["arm"], "rebalance_date": date_text, **row})
        out_groups.append(pd.DataFrame(reweighted + cash_records))
    return pd.concat(out_groups, ignore_index=True) if out_groups else book.copy(), pd.DataFrame(date_rows), pd.DataFrame(stock_rows)


def run_broker_replay(
    *,
    target_book: Path,
    price_cache: Path,
    output_dir: Path,
    cost_bps: float,
    max_fill_lag_days: int,
    starting_capital: float,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "run_broker_ledger_replay.py"),
        "--target-book",
        str(target_book),
        "--price-cache",
        str(price_cache),
        "--portfolio-kind",
        "concentrated",
        "--output-dir",
        str(output_dir),
        "--fill-mode",
        "next_close",
        "--cost-bps",
        str(cost_bps),
        "--max-fill-lag-days",
        str(max_fill_lag_days),
        "--starting-capital",
        str(starting_capital),
        "--disable-concentrated-champion-filter",
    ]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    metrics_path = output_dir / "metrics.json"
    if not metrics_path.exists():
        return {"status": "missing_metrics", "broker_metrics_path": str(metrics_path)}
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["broker_metrics_path"] = str(metrics_path)
    return payload


def window_metric(metrics: dict[str, Any], window: str, key: str) -> float | None:
    block = (metrics.get("windows") or {}).get(window)
    if not isinstance(block, dict):
        return None
    if key not in block:
        return None
    return safe_float(block.get(key), float("nan"))


def arm_metric_row(
    arm: dict[str, Any],
    metrics: dict[str, Any],
    date_telemetry: pd.DataFrame,
    target_book_path: Path,
) -> dict[str, Any]:
    totals = {
        "cap_breach_count": int(pd.to_numeric(date_telemetry.get("cap_breach_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not date_telemetry.empty else 0,
        "cap_breach_excess_weight": float(pd.to_numeric(date_telemetry.get("cap_breach_excess_weight", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not date_telemetry.empty else 0.0,
        "total_abs_weight_delta": float(pd.to_numeric(date_telemetry.get("total_abs_weight_delta", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not date_telemetry.empty else 0.0,
    }
    max_weight_after = (
        float(pd.to_numeric(date_telemetry.get("max_weight_after", pd.Series(dtype=float)), errors="coerce").fillna(0.0).max())
        if not date_telemetry.empty
        else 0.0
    )
    hhi_after = (
        float(pd.to_numeric(date_telemetry.get("hhi_after", pd.Series(dtype=float)), errors="coerce").fillna(0.0).max())
        if not date_telemetry.empty
        else 0.0
    )
    statuses = sorted(set(str(value) for value in date_telemetry.get("gross_preservation_status", pd.Series(dtype=str)).dropna().tolist())) if not date_telemetry.empty else []
    row = {
        "arm": arm["arm"],
        "status": metrics.get("status", "unknown"),
        "metric_mode": metrics.get("metric_mode", ""),
        "cagr": safe_float(metrics.get("cagr")),
        "max_dd": safe_float(metrics.get("max_dd")),
        "sharpe": safe_float(metrics.get("sharpe")),
        "years": safe_float(metrics.get("years")),
        "start_date": metrics.get("start_date", ""),
        "end_date": metrics.get("end_date", ""),
        "avg_cash_weight": safe_float(metrics.get("avg_cash_weight")),
        "trade_count": int(safe_float(metrics.get("trade_count"))),
        "total_fees_usd": safe_float(metrics.get("total_fees_usd")),
        "gross_traded_usd": safe_float(metrics.get("gross_traded_usd")),
        "max_weight_after": max_weight_after,
        "hhi_after": hhi_after,
        "gross_preservation_status": ",".join(statuses),
        "target_book_path": str(target_book_path),
        "broker_metrics_path": str(metrics.get("broker_metrics_path", "")),
        **totals,
    }
    for window in ("is", "oos", "oos2"):
        for key in ("cagr", "max_dd"):
            value = window_metric(metrics, window, key)
            row[f"windows.{window}.{key}"] = value
    return row


def add_deltas(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next((row for row in rows if row["arm"] == "baseline"), None)
    if not baseline:
        return rows
    for row in rows:
        row["delta_cagr_pp"] = (safe_float(row.get("cagr")) - safe_float(baseline.get("cagr"))) * 100.0
        row["delta_max_dd_pp"] = (safe_float(row.get("max_dd")) - safe_float(baseline.get("max_dd"))) * 100.0
        row["delta_sharpe"] = safe_float(row.get("sharpe")) - safe_float(baseline.get("sharpe"))
        row["delta_avg_cash_weight_pp"] = (safe_float(row.get("avg_cash_weight")) - safe_float(baseline.get("avg_cash_weight"))) * 100.0
        row["delta_trade_count"] = int(safe_float(row.get("trade_count")) - safe_float(baseline.get("trade_count")))
        row["delta_total_fees_usd"] = safe_float(row.get("total_fees_usd")) - safe_float(baseline.get("total_fees_usd"))
        row["delta_gross_traded_usd"] = safe_float(row.get("gross_traded_usd")) - safe_float(baseline.get("gross_traded_usd"))
        for window in ("is", "oos", "oos2"):
            for key in ("cagr", "max_dd"):
                base_key = f"windows.{window}.{key}"
                if row.get(base_key) is not None and baseline.get(base_key) is not None:
                    row[f"delta_{base_key}_pp"] = (safe_float(row.get(base_key)) - safe_float(baseline.get(base_key))) * 100.0
                else:
                    row[f"delta_{base_key}_pp"] = None
    return rows


def classify(row: dict[str, Any], baseline: dict[str, Any]) -> str:
    if row["arm"] == "baseline":
        return "baseline"
    if row.get("metric_mode") != "broker_ledger_next_close":
        return "blocked_invalid_metric_mode"
    if abs(safe_float(row.get("years")) - safe_float(baseline.get("years"))) > 0.03:
        return "blocked_window_mismatch"
    if safe_float(row.get("total_abs_weight_delta")) <= 1e-10:
        return "blocked_no_signal"
    if safe_float(row.get("delta_cagr_pp")) <= 0.0:
        return "reject_no_cagr_edge"
    if safe_float(row.get("delta_max_dd_pp")) < -1e-9:
        return "reject_mdd_worse"
    if safe_float(row.get("cap_breach_count")) > 0:
        return "research_pass_uncapped_only"
    oos_delta = row.get("delta_windows.oos.cagr_pp")
    oos_mdd_delta = row.get("delta_windows.oos.max_dd_pp")
    if oos_delta is not None and safe_float(oos_delta) < -1e-9:
        return "reject_oos_cagr_worse"
    if oos_mdd_delta is not None and safe_float(oos_mdd_delta) < -0.50:
        return "reject_oos_mdd_worse"
    if abs(safe_float(row.get("delta_avg_cash_weight_pp"))) > 0.10:
        return "reject_cash_changed"
    if safe_float(row.get("delta_cagr_pp")) >= 0.50:
        return "research_pass_policy_candidate"
    return "reject_cagr_edge_too_small"


def render_report(rows: list[dict[str, Any]], *, target_book: Path, price_cache: Path) -> str:
    lines = [
        "# Concentrated Score Sizing Broker A/B",
        "",
        f"- target book: `{target_book}`",
        f"- price cache: `{price_cache}`",
        "- metric source: broker_ledger_next_close",
        "- production promotion: blocked unless PIT universe evidence is clean",
        "",
        "| arm | verdict | CAGR | MaxDD | Sharpe | dCAGR pp | dMDD pp | cap breaches | max weight |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {arm} | `{verdict}` | {cagr:.2%} | {mdd:.2%} | {sharpe:.3f} | {dc:+.2f} | {dm:+.2f} | {cap} | {mw:.2%} |".format(
                arm=row.get("arm"),
                verdict=row.get("ab_verdict"),
                cagr=safe_float(row.get("cagr")),
                mdd=safe_float(row.get("max_dd")),
                sharpe=safe_float(row.get("sharpe")),
                dc=safe_float(row.get("delta_cagr_pp")),
                dm=safe_float(row.get("delta_max_dd_pp")),
                cap=int(safe_float(row.get("cap_breach_count"))),
                mw=safe_float(row.get("max_weight_after")),
            )
        )
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    target_book = resolve_target_book(latest_run, args.target_book)
    price_cache = resolve_price_cache(latest_run, args.price_cache)
    book = pd.read_csv(target_book)
    if "rebalance_date" not in book.columns or "ticker" not in book.columns:
        raise ValueError("target book must include rebalance_date and ticker")
    book["rebalance_date"] = pd.to_datetime(book["rebalance_date"], errors="coerce").dt.date.astype(str)

    rows: list[dict[str, Any]] = []
    for arm in ARMS:
        arm_dir = output_dir / arm["arm"]
        arm_book, date_telemetry, stock_telemetry = generate_arm_book(book, arm, single_cap=float(args.single_cap))
        arm_book_path = arm_dir / "target_book.csv"
        write_csv(arm_book_path, arm_book)
        write_csv(arm_dir / "reweight_date_telemetry.csv", date_telemetry)
        write_csv(arm_dir / "reweight_stock_telemetry.csv", stock_telemetry)
        metrics = run_broker_replay(
            target_book=arm_book_path,
            price_cache=price_cache,
            output_dir=arm_dir / "broker",
            cost_bps=float(args.cost_bps),
            max_fill_lag_days=int(args.max_fill_lag_days),
            starting_capital=float(args.starting_capital),
        )
        rows.append(arm_metric_row(arm, metrics, date_telemetry, arm_book_path))

    rows = add_deltas(rows)
    baseline = next(row for row in rows if row["arm"] == "baseline")
    for row in rows:
        row["ab_verdict"] = classify(row, baseline)
    table = pd.DataFrame(rows)
    write_csv(output_dir / "arm_metrics.csv", table)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "latest_run": str(latest_run),
        "target_book": str(target_book),
        "price_cache": str(price_cache),
        "arms": rows,
        "policy_candidates": [row for row in rows if row.get("ab_verdict") == "research_pass_policy_candidate"],
        "production_promotion_allowed": False,
        "production_promotion_blocker": "pit_universe_label_clean_required",
    }
    write_json(output_dir / "summary.json", payload)
    write_text(output_dir / "report.md", render_report(rows, target_book=target_book, price_cache=price_cache))
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--target-book", default="")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--max-fill-lag-days", type=int, default=7)
    parser.add_argument("--starting-capital", type=float, default=100000.0)
    parser.add_argument("--single-cap", type=float, default=0.30)
    return parser.parse_args()


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
