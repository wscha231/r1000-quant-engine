#!/usr/bin/env python3
"""Build a research-only forward-service snapshot from official broker artifacts.

This does not change target books, live orders, scoring, or production gates. It
turns the latest broker-ledger state into a hash-stamped snapshot that can seed a
paper forward ledger and a review-only website/API view.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = "outputs/forward_service"
PORTFOLIOS = ("main", "concentrated")
SCHEMA_VERSION = "forward-service-snapshot-v1"


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def pct(value: Any) -> str:
    return f"{safe_float(value) * 100:.2f}%"


def stable_hash(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_outputs_dir(latest_run: Path) -> Path:
    candidates = [
        latest_run,
        latest_run / "official" / "outputs",
        latest_run / "outputs",
    ]
    for candidate in candidates:
        if (candidate / "broker_replay").exists() and (candidate / "account_evaluation").exists():
            return candidate
    raise FileNotFoundError(
        f"could not find official outputs under {latest_run}; expected broker_replay/ and account_evaluation/"
    )


def portfolio_metric(official_metrics: dict[str, Any], portfolio: str, state: dict[str, Any]) -> dict[str, Any]:
    official = (official_metrics.get("portfolios") or {}).get(portfolio) or {}
    state_metrics = state.get("metrics") or {}
    return {
        "metric_mode": official_metrics.get("official_metric_mode") or state_metrics.get("metric_mode", ""),
        "cagr": official.get("cagr", state_metrics.get("cagr")),
        "max_dd": official.get("max_dd", state_metrics.get("max_dd")),
        "sharpe": official.get("sharpe", state_metrics.get("sharpe")),
        "years": official.get("years", state_metrics.get("years")),
        "start_date": official.get("start_date", state_metrics.get("start_date")),
        "end_date": official.get("end_date", state_metrics.get("end_date")),
        "latest_equity_usd": official.get("latest_equity_usd", state.get("equity_usd")),
        "latest_cash_weight": official.get("latest_cash_weight", state.get("cash_weight")),
        "avg_cash_weight": official.get("avg_cash_weight", state_metrics.get("avg_cash_weight")),
        "pit_universe_label_clean": bool(official.get("pit_universe_label_clean", False)),
        "production_promotion_allowed": bool(official.get("production_promotion_allowed", False)),
        "strengthened_pass": bool(official.get("strengthened_pass", False)),
    }


def load_portfolio(outputs_dir: Path, portfolio: str, official_metrics: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    replay_dir = outputs_dir / "broker_replay" / portfolio
    state_path = replay_dir / "account_state_latest.json"
    positions_path = replay_dir / "positions_latest.csv"
    state = read_json(state_path)
    positions = read_csv_rows(positions_path)
    metric = portfolio_metric(official_metrics, portfolio, state)

    equity = safe_float(state.get("equity_usd", metric.get("latest_equity_usd")))
    cash_usd = safe_float(state.get("cash_usd"))
    cash_weight = safe_float(state.get("cash_weight", metric.get("latest_cash_weight")))
    as_of_date = str(state.get("as_of_date") or (positions[0].get("as_of_date") if positions else "") or "")

    rows: list[dict[str, Any]] = []
    has_cash = False
    for pos in positions:
        ticker = str(pos.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        if ticker in {"CASH", "USD"}:
            has_cash = True
        rows.append(
            {
                "freeze_date": as_of_date,
                "portfolio_kind": portfolio,
                "ticker": ticker,
                "weight": safe_float(pos.get("weight")),
                "market_value_usd": safe_float(pos.get("market_value_usd")),
                "shares": safe_float(pos.get("shares")),
                "price": safe_float(pos.get("price")),
                "source": "broker_ledger_simulated",
                "display_status": "review_only",
            }
        )
    if cash_weight > 0 and not has_cash:
        rows.append(
            {
                "freeze_date": as_of_date,
                "portfolio_kind": portfolio,
                "ticker": "CASH",
                "weight": cash_weight,
                "market_value_usd": cash_usd if cash_usd > 0 else equity * cash_weight,
                "shares": "",
                "price": "",
                "source": "broker_ledger_simulated",
                "display_status": "review_only",
            }
        )

    rows.sort(key=lambda row: (row["portfolio_kind"], row["ticker"] == "CASH", -safe_float(row["weight"]), row["ticker"]))
    payload = {
        "portfolio_kind": portfolio,
        "as_of_date": as_of_date,
        "equity_usd": equity,
        "cash_usd": cash_usd,
        "cash_weight": cash_weight,
        "position_count": int(state.get("position_count", len([r for r in rows if r["ticker"] != "CASH"])) or 0),
        "metrics": metric,
        "source_files": {
            "account_state_latest": str(state_path),
            "positions_latest": str(positions_path),
            "account_state_latest_sha256": file_hash(state_path),
            "positions_latest_sha256": file_hash(positions_path),
        },
    }
    return payload, rows


def build_report(snapshot: dict[str, Any], holdings: list[dict[str, Any]], readiness: dict[str, Any]) -> str:
    lines = [
        "# Forward Service Snapshot",
        "",
        "This artifact is a research-only seed for forward tracking. It is not a trade instruction,",
        "not production promotion, and not a promise that current holdings will achieve historical CAGR/MDD targets.",
        "",
        f"- Snapshot hash: `{snapshot['snapshot_hash']}`",
        f"- Freeze date: `{snapshot['freeze_date']}`",
        f"- Public display allowed: `{readiness['public_display_allowed']}`",
        f"- Production activation allowed: `{snapshot['production_activation_allowed']}`",
        "",
        "## Portfolio Metrics",
        "",
        "| Portfolio | CAGR | MaxDD | Sharpe | Cash | Metric mode |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for portfolio in snapshot["portfolios"]:
        m = portfolio["metrics"]
        lines.append(
            f"| {portfolio['portfolio_kind']} | {pct(m.get('cagr'))} | {pct(m.get('max_dd'))} | "
            f"{safe_float(m.get('sharpe')):.3f} | {pct(portfolio.get('cash_weight'))} | {m.get('metric_mode', '')} |"
        )
    lines.extend(["", "## Current Simulated Holdings", ""])
    for portfolio in snapshot["portfolios"]:
        rows = [row for row in holdings if row["portfolio_kind"] == portfolio["portfolio_kind"]]
        lines.extend(
            [
                f"### {portfolio['portfolio_kind']}",
                "",
                "| Ticker | Weight | Market Value |",
                "| --- | ---: | ---: |",
            ]
        )
        for row in sorted(rows, key=lambda r: safe_float(r["weight"]), reverse=True):
            lines.append(f"| {row['ticker']} | {pct(row['weight'])} | {safe_float(row['market_value_usd']):.2f} |")
        lines.append("")
    lines.extend(["## Blockers", ""])
    for blocker in readiness["blockers"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Required Before Public Service", ""])
    for item in readiness["required_before_public_service"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    outputs_dir = resolve_outputs_dir(repo_path(args.latest_run))
    out_dir = repo_path(args.output_dir)
    official_metrics_path = outputs_dir / "account_evaluation" / "official_metrics.json"
    official_metrics = read_json(official_metrics_path)

    portfolios: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    for portfolio in PORTFOLIOS:
        payload, rows = load_portfolio(outputs_dir, portfolio, official_metrics)
        portfolios.append(payload)
        holdings.extend(rows)

    freeze_dates = sorted({p["as_of_date"] for p in portfolios if p.get("as_of_date")})
    freeze_date = args.freeze_date or (freeze_dates[-1] if freeze_dates else date.today().isoformat())
    pit_clean = all(bool(p["metrics"].get("pit_universe_label_clean")) for p in portfolios)
    production_allowed = pit_clean and all(bool(p["metrics"].get("production_promotion_allowed")) for p in portfolios)
    metric_modes = sorted({str(p["metrics"].get("metric_mode", "")) for p in portfolios})
    cash_carry_mode = "cash_carry" if any("cash_carry" in mode for mode in metric_modes) else "zero_yield_or_unspecified"

    base_snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source_outputs_dir": str(outputs_dir),
        "freeze_date": freeze_date,
        "research_only": True,
        "review_only": True,
        "public_display_allowed": False,
        "production_activation_allowed": bool(production_allowed),
        "pit_universe_label_clean": bool(pit_clean),
        "cash_carry_accounting_status": cash_carry_mode,
        "metric_modes": metric_modes,
        "portfolios": portfolios,
        "official_metrics_sha256": file_hash(official_metrics_path),
        "service_notice": {
            "not_investment_advice": True,
            "historical_simulation_not_future_guarantee": True,
            "current_holdings_are_process_output_not_cagr_promise": True,
        },
    }
    snapshot_hash = stable_hash({"snapshot": base_snapshot, "holdings": holdings})
    snapshot = {**base_snapshot, "snapshot_hash": snapshot_hash}

    blockers = [
        "live_forward_tracking_record_has_zero_elapsed_days_from_this_snapshot",
        "expectation_bands_not_yet_materialized",
        "alpha_decay_and_kill_switch_rules_not_yet_materialized",
        "commercial_data_license_review_required_before_public_site",
        "regulatory_and_disclosure_review_required_before_public_site",
    ]
    if not pit_clean:
        blockers.append("pit_universe_label_clean_false_blocks_production_promotion")
    if cash_carry_mode != "cash_carry":
        blockers.append("cash_carry_contract_not_active_in_this_snapshot")
    readiness = {
        "schema_version": "forward-service-readiness-v1",
        "snapshot_hash": snapshot_hash,
        "public_display_allowed": False,
        "production_activation_allowed": bool(production_allowed),
        "forward_ledger_seed_created": True,
        "blockers": blockers,
        "required_before_public_service": [
            "accumulate_live_forward_paper_ledger_after_freeze_date",
            "publish_percentile_expectation_bands_instead_of_point_return_promises",
            "define_alpha_decay_regime_alarm_and_kill_switch",
            "fix_and monitor scheduled refresh/fullrun completion paths",
            "archive every public snapshot hash and source file hash",
            "complete data vendor license review",
            "complete investment-advisory/regulatory disclosure review",
        ],
    }

    holdings_fields = [
        "freeze_date",
        "portfolio_kind",
        "ticker",
        "weight",
        "market_value_usd",
        "shares",
        "price",
        "source",
        "display_status",
    ]
    ledger_rows = [
        {
            "freeze_date": freeze_date,
            "portfolio_kind": p["portfolio_kind"],
            "starting_nav_usd": p["equity_usd"],
            "snapshot_hash": snapshot_hash,
            "source_metric_mode": p["metrics"].get("metric_mode", ""),
            "research_only": True,
            "review_only": True,
        }
        for p in portfolios
    ]

    write_json(out_dir / "current_public_snapshot.json", snapshot)
    write_json(out_dir / "service_readiness.json", readiness)
    write_csv(out_dir / "public_holdings.csv", holdings, holdings_fields)
    write_csv(
        out_dir / "forward_ledger_seed.csv",
        ledger_rows,
        ["freeze_date", "portfolio_kind", "starting_nav_usd", "snapshot_hash", "source_metric_mode", "research_only", "review_only"],
    )
    (out_dir / "report.md").write_text(build_report(snapshot, holdings, readiness), encoding="utf-8")
    return {
        "status": "completed",
        "output_dir": str(out_dir),
        "snapshot_hash": snapshot_hash,
        "freeze_date": freeze_date,
        "portfolio_count": len(portfolios),
        "holding_row_count": len(holdings),
        "public_display_allowed": False,
        "production_activation_allowed": bool(production_allowed),
        "pit_universe_label_clean": bool(pit_clean),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", required=True, help="Path to official outputs or run root containing official/outputs.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--freeze-date", default="", help="Optional explicit freeze date for the forward ledger seed.")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
