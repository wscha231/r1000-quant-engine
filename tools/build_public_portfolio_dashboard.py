#!/usr/bin/env python3
"""Build the privacy-safe JSON consumed by the Run287 public dashboard.

The producer accepts either a broker replay directory (``replays/main`` and
``replays/concentrated``) or the review-only ``user_current`` bundle emitted by
``daily_operating_selection_refresh.yml``.  It deliberately publishes weights
and market prices, but never account dollar values, share quantities, cost
basis, P&L, fees, API credentials, or local paths.

Daily ``user_current`` artifacts do not contain an executed trade ledger.  In
that case ``--base-json`` retains the previously reviewed trade history while
current holdings, target weights, and review-only order previews are refreshed.
Order previews are always labelled as proposals and never as executions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PORTFOLIOS = ("main", "concentrated")
PORTFOLIO_LABELS = {"main": "Main", "concentrated": "Concentrated"}
FORBIDDEN_PUBLIC_KEYS = {
    "shares",
    "quantity",
    "current_shares",
    "shares_after",
    "market_value_usd",
    "cash_usd",
    "cash_after",
    "cash_delta",
    "equity_usd",
    "stock_value_usd",
    "gross_value",
    "gross_traded_usd",
    "fee_usd",
    "total_fees_usd",
    "cost_basis",
    "unrealized_pnl_usd",
    "realized_pnl_usd",
    "starting_capital_usd",
    "ending_capital_usd",
    "target_book",
    "price_cache",
    "cash_rate_path",
    "latest_run",
    "output_dir",
}
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:\\|/home/runner/|/Users/)")
SECRET_TEXT = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|gh[opusr]_[A-Za-z0-9]{12,}|apikey=|api_key=|api-secret)",
    re.IGNORECASE,
)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clean_text(value: Any, *, max_length: int = 240) -> str:
    text = str(value or "").replace("\x00", "").strip()
    if ABSOLUTE_PATH.search(text) or SECRET_TEXT.search(text):
        return "redacted"
    return text[:max_length]


def clean_ticker(value: Any) -> str:
    ticker = clean_text(value, max_length=24).upper()
    return "" if ticker in {"", "NAN", "NONE"} else ticker


def first_value(row: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def last_nonempty(rows: Iterable[dict[str, Any]], key: str) -> Any:
    value: Any = None
    for row in rows:
        if row.get(key) not in (None, ""):
            value = row.get(key)
    return value


def metric_view(raw: dict[str, Any]) -> dict[str, Any]:
    windows = raw.get("windows") if isinstance(raw.get("windows"), dict) else {}
    oos = windows.get("oos") if isinstance(windows.get("oos"), dict) else {}
    oos2 = windows.get("oos2") if isinstance(windows.get("oos2"), dict) else {}
    return {
        "cagr": safe_float(raw.get("cagr")),
        "max_drawdown": safe_float(raw.get("max_dd")),
        "sharpe": safe_float(raw.get("sharpe")),
        "average_cash_weight": safe_float(raw.get("avg_cash_weight")),
        "trade_count": int(safe_float(raw.get("trade_count"), 0) or 0),
        "start_date": clean_text(raw.get("start_date"), max_length=16),
        "end_date": clean_text(raw.get("end_date"), max_length=16),
        "oos_cagr": safe_float(oos.get("cagr")),
        "oos_max_drawdown": safe_float(oos.get("max_dd")),
        "oos2_cagr": safe_float(oos2.get("cagr")),
        "oos2_max_drawdown": safe_float(oos2.get("max_dd")),
        "metric_mode": clean_text(raw.get("metric_mode"), max_length=80),
        "fill_mode": clean_text(raw.get("fill_mode"), max_length=32),
        "cost_bps_per_side": safe_float(raw.get("cost_bps_per_side")),
        "valid_for_production": bool(raw.get("valid_for_production", False)),
    }


def replay_dir(source: Path, portfolio: str) -> Path | None:
    candidates = [
        source / "replays" / portfolio,
        source / "broker_replay" / portfolio,
        source / "outputs" / "broker_replay" / portfolio,
    ]
    if source.name.lower() == portfolio:
        candidates.insert(0, source)
    for candidate in candidates:
        if (candidate / "positions_latest.csv").exists() or (candidate / "metrics.json").exists():
            return candidate
    return None


def downsample_curve(rows: list[dict[str, str]], limit: int = 180) -> list[dict[str, Any]]:
    clean: list[tuple[str, float]] = []
    for row in rows:
        date = clean_text(row.get("date"), max_length=16)
        value = safe_float(row.get("equity_usd"))
        if date and value is not None and value > 0:
            clean.append((date, value))
    if not clean:
        return []
    if len(clean) > limit:
        indexes = {round(index * (len(clean) - 1) / (limit - 1)) for index in range(limit)}
        clean = [row for index, row in enumerate(clean) if index in indexes]
    base = clean[0][1]
    return [{"date": date, "index": round(value / base * 100.0, 4)} for date, value in clean]


def replay_holdings(rows: list[dict[str, str]], targets: dict[str, float] | None = None) -> tuple[list[dict[str, Any]], float, str]:
    targets = targets or {}
    holdings: list[dict[str, Any]] = []
    weight_total = 0.0
    as_of = ""
    for row in rows:
        ticker = clean_ticker(row.get("ticker"))
        weight = safe_float(row.get("weight"))
        if not ticker or ticker == "CASH" or weight is None or weight < 0:
            continue
        weight_total += weight
        as_of = max(as_of, clean_text(row.get("as_of_date"), max_length=16))
        target = targets.get(ticker)
        holdings.append(
            {
                "ticker": ticker,
                "weight": round(weight, 10),
                "target_weight": round(target, 10) if target is not None else None,
                "price": safe_float(first_value(row, "price", "current_price", "reference_price")),
            }
        )
    if weight_total > 1.000001:
        raise ValueError(f"equity weights exceed 100%: {weight_total:.8f}")
    cash_weight = max(0.0, 1.0 - weight_total)
    holdings.sort(key=lambda item: (-float(item["weight"]), item["ticker"]))
    return holdings, cash_weight, as_of


def replay_trades(rows: list[dict[str, str]], limit: int = 240) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for row in rows:
        ticker = clean_ticker(row.get("ticker"))
        side = clean_text(row.get("side"), max_length=12).upper()
        if not ticker or side not in {"BUY", "SELL"}:
            continue
        trades.append(
            {
                "date": clean_text(row.get("date"), max_length=16),
                "signal_date": clean_text(row.get("signal_date"), max_length=16),
                "ticker": ticker,
                "side": side,
                "fill_price": safe_float(row.get("fill_price")),
                "target_weight": safe_float(row.get("target_weight")),
                "reason": clean_text(row.get("reason"), max_length=80),
                "fill_mode": clean_text(row.get("fill_mode"), max_length=32),
            }
        )
    trades.sort(key=lambda item: (item["date"], item["ticker"], item["side"]), reverse=True)
    return trades[:limit]


def empty_dashboard() -> dict[str, Any]:
    return {
        "schema_version": "run287-public-dashboard-v1",
        "generated_at_utc": "",
        "as_of_close": "",
        "status": {
            "review_only": True,
            "simulated_broker_ledger": True,
            "live_trading_enabled": False,
            "production_ready": False,
            "decision": "RESEARCH_ONLY",
        },
        "privacy": {
            "weights_published": True,
            "market_prices_published": True,
            "share_quantities_published": False,
            "account_dollar_values_published": False,
            "cost_basis_and_pnl_published": False,
        },
        "source": {
            "mode": "missing",
            "label": "No validated public source",
            "run_id": "",
            "commit": "",
            "trade_history_status": "missing",
        },
        "portfolios": {},
        "order_previews": [],
        "changes": [],
        "methodology": {
            "valuation_basis": "latest completed US trading close",
            "execution_assumption": "integer shares, next close, 25 bps per side",
            "cash_basis": "actual simulated cash ledger with research cash carry",
            "public_data_delay": "published after daily review artifact completes",
        },
    }


def build_replay_snapshot(source: Path) -> dict[str, Any]:
    dashboard = empty_dashboard()
    as_of_dates: list[str] = []
    for portfolio in PORTFOLIOS:
        directory = replay_dir(source, portfolio)
        if directory is None:
            continue
        positions = read_csv(directory / "positions_latest.csv")
        equity_rows = read_csv(directory / "equity_curve.csv")
        holdings, cash_weight, as_of = replay_holdings(positions)
        equity_cash = safe_float(last_nonempty(equity_rows, "cash_weight"), cash_weight)
        metrics = metric_view(read_json(directory / "metrics.json"))
        metric_end = clean_text(metrics.get("end_date"), max_length=16)
        if as_of:
            as_of_dates.append(as_of)
        if metric_end:
            as_of_dates.append(metric_end)
        dashboard["portfolios"][portfolio] = {
            "label": PORTFOLIO_LABELS[portfolio],
            "metrics": metrics,
            "holdings": holdings,
            "holding_count": len(holdings),
            "cash_weight": round(float(equity_cash if equity_cash is not None else cash_weight), 10),
            "target_cash_weight": None,
            "equity_curve": downsample_curve(equity_rows),
            "trades": replay_trades(read_csv(directory / "trades.csv")),
        }
    if not dashboard["portfolios"]:
        raise FileNotFoundError(f"no broker replay found under {source}")
    dashboard["as_of_close"] = max(as_of_dates, default="")
    dashboard["source"].update(
        {
            "mode": "broker_replay_snapshot",
            "label": "Run287 validated broker-ledger replay",
            "trade_history_status": "included_from_replay",
        }
    )
    return dashboard


def user_current_dir(source: Path) -> Path | None:
    candidates = [source / "user_current", source / "outputs" / "user_current", source]
    for candidate in candidates:
        if (candidate / "01_current_holdings.csv").exists():
            return candidate
    return None


def public_target_maps(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    targets = {portfolio: {} for portfolio in PORTFOLIOS}
    cash_targets: dict[str, float] = {}
    for row in rows:
        portfolio = clean_text(first_value(row, "portfolio_kind", "portfolio"), max_length=24).lower()
        ticker = clean_ticker(row.get("ticker"))
        target = safe_float(first_value(row, "target_weight", "recommended_weight"))
        if portfolio not in targets or not ticker or target is None:
            continue
        if ticker == "CASH":
            cash_targets[portfolio] = target
        else:
            targets[portfolio][ticker] = target
    return targets, cash_targets


def current_holdings_by_portfolio(
    rows: list[dict[str, str]], targets: dict[str, dict[str, float]]
) -> tuple[dict[str, tuple[list[dict[str, Any]], float]], list[str]]:
    grouped = {portfolio: [] for portfolio in PORTFOLIOS}
    explicit_cash: dict[str, float] = {}
    dates: list[str] = []
    for row in rows:
        portfolio = clean_text(first_value(row, "portfolio_kind", "portfolio"), max_length=24).lower()
        if portfolio not in grouped:
            continue
        ticker = clean_ticker(row.get("ticker"))
        row_type = clean_text(row.get("row_type"), max_length=20).lower()
        weight = safe_float(first_value(row, "current_weight", "weight"))
        date = clean_text(first_value(row, "as_of_date", "valuation_as_of_date", "reference_price_date"), max_length=16)
        if date:
            dates.append(date)
        if weight is None or weight < 0:
            continue
        if row_type == "cash" or ticker == "CASH":
            explicit_cash[portfolio] = weight
            continue
        if not ticker:
            continue
        grouped[portfolio].append(
            {
                "ticker": ticker,
                "weight": round(weight, 10),
                "target_weight": round(targets[portfolio][ticker], 10) if ticker in targets[portfolio] else None,
                "price": safe_float(first_value(row, "current_price", "price", "reference_price")),
            }
        )
    result: dict[str, tuple[list[dict[str, Any]], float]] = {}
    for portfolio, holdings in grouped.items():
        holdings.sort(key=lambda item: (-float(item["weight"]), item["ticker"]))
        total = sum(float(item["weight"]) for item in holdings)
        if total > 1.000001:
            raise ValueError(f"{portfolio} current equity weights exceed 100%: {total:.8f}")
        cash = explicit_cash.get(portfolio, max(0.0, 1.0 - total))
        result[portfolio] = (holdings, cash)
    return result, dates


def metrics_by_portfolio(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: dict[str, Any] = raw.get("portfolios") if isinstance(raw.get("portfolios"), dict) else raw
    result: dict[str, dict[str, Any]] = {}
    for portfolio in PORTFOLIOS:
        item = candidates.get(portfolio) if isinstance(candidates, dict) else None
        if isinstance(item, dict):
            result[portfolio] = metric_view(item)
    if not result and clean_text(raw.get("portfolio_kind"), max_length=24).lower() in PORTFOLIOS:
        portfolio = clean_text(raw.get("portfolio_kind"), max_length=24).lower()
        result[portfolio] = metric_view(raw)
    return result


def public_order_previews(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for row in rows:
        portfolio = clean_text(first_value(row, "portfolio_kind", "portfolio"), max_length=24).lower()
        ticker = clean_ticker(row.get("ticker"))
        if portfolio not in PORTFOLIOS or not ticker:
            continue
        previews.append(
            {
                "portfolio": portfolio,
                "ticker": ticker,
                "action": clean_text(first_value(row, "action", "suggested_action"), max_length=48),
                "current_weight": safe_float(row.get("current_weight")),
                "target_weight": safe_float(row.get("target_weight")),
                "delta_weight": safe_float(row.get("delta_weight")),
                "reference_price": safe_float(first_value(row, "reference_price", "current_price")),
                "review_required": True,
                "executed": False,
            }
        )
    previews.sort(key=lambda item: (abs(float(item["delta_weight"] or 0.0)), item["ticker"]), reverse=True)
    return previews[:120]


def overlay_user_current(source: Path, base: dict[str, Any]) -> dict[str, Any]:
    current_dir = user_current_dir(source)
    if current_dir is None:
        raise FileNotFoundError(f"daily artifact has no user_current holdings under {source}")
    summary = read_json(current_dir / "summary.json")
    if not summary.get("review_only"):
        raise ValueError("daily user_current artifact is not explicitly review_only")
    if summary.get("live_trading_enabled") is not False or summary.get("production_mutation_allowed") is not False:
        raise ValueError("daily user_current safety flags are not fail-closed")

    dashboard = deepcopy(base)
    target_rows = read_csv(current_dir / "02_target_weights.csv")
    targets, target_cash = public_target_maps(target_rows)
    current, dates = current_holdings_by_portfolio(read_csv(current_dir / "01_current_holdings.csv"), targets)
    if not any(current[portfolio][0] for portfolio in PORTFOLIOS):
        raise ValueError("daily user_current artifact contains no public equity holdings")
    official_metrics = metrics_by_portfolio(read_json(current_dir / "04_official_metrics.json"))

    for portfolio in PORTFOLIOS:
        holdings, cash = current[portfolio]
        prior = dashboard.get("portfolios", {}).get(portfolio, {})
        if not holdings and not prior:
            continue
        dashboard.setdefault("portfolios", {})[portfolio] = {
            "label": PORTFOLIO_LABELS[portfolio],
            "metrics": official_metrics.get(portfolio, prior.get("metrics", {})),
            "holdings": holdings or prior.get("holdings", []),
            "holding_count": len(holdings or prior.get("holdings", [])),
            "cash_weight": round(float(cash), 10) if holdings else prior.get("cash_weight"),
            "target_cash_weight": target_cash.get(portfolio),
            "equity_curve": prior.get("equity_curve", []),
            "trades": prior.get("trades", []),
        }

    decision = read_json(current_dir / "08_rebalance_decision.json")
    dashboard["order_previews"] = public_order_previews(read_csv(current_dir / "03_order_preview.csv"))
    dashboard["as_of_close"] = max(dates, default=dashboard.get("as_of_close", ""))
    dashboard["status"].update(
        {
            "review_only": True,
            "simulated_broker_ledger": True,
            "live_trading_enabled": False,
            "production_ready": False,
            "decision": clean_text(decision.get("decision") or summary.get("action_status") or "REVIEW_REQUIRED", max_length=48),
        }
    )
    dashboard["source"].update(
        {
            "mode": "daily_operating_review_artifact",
            "label": "Daily operating selection review artifact",
            "run_id": clean_text(summary.get("source_run_id"), max_length=40),
            "commit": clean_text(summary.get("source_commit_sha"), max_length=64),
            "trade_history_status": "retained_from_last_validated_replay",
        }
    )
    return dashboard


def git_changes(repo_root: Path, limit: int = 12) -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "log",
                "--date=short",
                "--pretty=format:%h%x1f%ad%x1f%s",
                "-60",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    changes: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commit, date, subject = parts
        lowered = subject.lower()
        if "chore(bot)" in lowered or "[skip ci]" in lowered or lowered.startswith("merge pull request"):
            continue
        changes.append(
            {
                "date": clean_text(date, max_length=16),
                "commit": clean_text(commit, max_length=12),
                "summary": clean_text(subject, max_length=160),
            }
        )
        if len(changes) >= limit:
            break
    return changes


def validate_public_payload(payload: Any, path: str = "root") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"forbidden public field at {path}.{key}")
            validate_public_payload(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            validate_public_payload(value, f"{path}[{index}]")
    elif isinstance(payload, str):
        if ABSOLUTE_PATH.search(payload):
            raise ValueError(f"absolute local path leaked at {path}")
        if SECRET_TEXT.search(payload):
            raise ValueError(f"secret-like text leaked at {path}")


def build_dashboard(source: Path, base_json: Path | None = None, repo_root: Path | None = None) -> dict[str, Any]:
    base = read_json(base_json) if base_json and base_json.exists() else {}
    if user_current_dir(source) is not None:
        if not base:
            base = empty_dashboard()
        dashboard = overlay_user_current(source, base)
    else:
        dashboard = build_replay_snapshot(source)
    dashboard["generated_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if repo_root is not None:
        changes = git_changes(repo_root)
        if changes:
            dashboard["changes"] = changes
    validate_public_payload(dashboard)
    return dashboard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Replay root or downloaded daily artifact root")
    parser.add_argument("--base-json", default="", help="Previous public JSON used when daily artifacts omit history")
    parser.add_argument("--output", default="docs/public/data/dashboard.json")
    parser.add_argument("--repo-root", default=".")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.source).resolve()
    base_json = Path(args.base_json).resolve() if args.base_json else None
    output = Path(args.output).resolve()
    dashboard = build_dashboard(source, base_json=base_json, repo_root=Path(args.repo_root).resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "completed",
                "output": str(output),
                "as_of_close": dashboard.get("as_of_close"),
                "source_mode": dashboard.get("source", {}).get("mode"),
                "portfolios": sorted(dashboard.get("portfolios", {})),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
