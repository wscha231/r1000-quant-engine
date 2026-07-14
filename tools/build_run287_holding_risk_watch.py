#!/usr/bin/env python3
"""Build a current, forward-only risk watch for each held security.

The watch is deliberately non-executable.  It measures exact-close, past-only
price damage and appends idempotent review rows without changing target books,
cash, paper orders, production state, or live trading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-holding-risk-watch-v1"
DEFAULT_CONTRACT = "docs/run287_holding_risk_watch_contract.json"
PORTFOLIO_RANK = {"main": 0, "concentrated": 1}
STATE_RANK = {"ALERT": 0, "WATCH": 1, "DATA_INSUFFICIENT": 2, "NORMAL": 3}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=json_default).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE", "CASH", "__CASH__"} else text


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def past_quantile(series: pd.Series, asof: pd.Timestamp, lookback: int, minimum: int, quantile: float) -> tuple[float | None, int]:
    clean = pd.to_numeric(series.loc[series.index < asof], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().tail(lookback)
    if len(clean) < minimum:
        return None, int(len(clean))
    return float(clean.quantile(quantile)), int(len(clean))


def value_at(series: pd.Series, asof: pd.Timestamp) -> float | None:
    if asof not in series.index:
        return None
    return finite(series.loc[asof])


def price_features(
    *,
    ticker: str,
    price_cache: Path,
    benchmark_returns: pd.Series,
    asof: pd.Timestamp,
    contract: dict[str, Any],
) -> dict[str, Any]:
    history = contract["history"]
    quantiles = contract["past_only_quantiles"]
    lookback = int(history["lookback_sessions"])
    minimum = int(history["minimum_return_observations"])
    trend_sessions = int(history["trend_return_sessions"])
    drawdown_sessions = int(history["drawdown_sessions"])
    short_vol_sessions = int(history["short_volatility_sessions"])
    long_vol_sessions = int(history["long_volatility_sessions"])

    raw = load_price_series(price_cache, ticker)
    future_rows = int((pd.DatetimeIndex(raw.index) > asof).sum()) if not raw.empty else 0
    px = raw[raw.index <= asof].copy() if not raw.empty else pd.DataFrame()
    if not px.empty:
        px = px.groupby(level=0).last().sort_index()
    exact = bool(not px.empty and pd.Timestamp(px.index[-1]).normalize() == asof)
    price_path = price_cache / px_cache_name(ticker)
    base: dict[str, Any] = {
        "ticker": ticker,
        "price_file": str(price_path),
        "price_file_sha256": sha256_file(price_path),
        "price_exact_asof": exact,
        "latest_price_date": pd.Timestamp(px.index[-1]).date().isoformat() if not px.empty else "",
        "future_price_rows_excluded": future_rows,
        "history_observations": 0,
        "close": None,
        "return_1d": None,
        "spy_return_1d": value_at(benchmark_returns, asof),
        "spy_excess_return_1d": None,
        "opening_gap_return": None,
        "return_21d": None,
        "spy_excess_return_21d": None,
        "drawdown_63d": None,
        "ma20": None,
        "ma50": None,
        "below_ma20": None,
        "below_ma50": None,
        "volatility_ratio_21d_126d": None,
        "absolute_return_shock_threshold": None,
        "spy_relative_return_shock_threshold": None,
        "opening_gap_shock_threshold": None,
        "trend_damage_threshold": None,
        "drawdown_damage_threshold": None,
        "volatility_spike_threshold": None,
        "idiosyncratic_shock": False,
        "opening_gap_shock": False,
        "trend_damage": False,
        "drawdown_damage": False,
        "volatility_spike": False,
    }
    if px.empty or "close" not in px.columns:
        base["data_reason"] = "price_history_missing"
        return base

    close = pd.to_numeric(px["close"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    returns = close.pct_change()
    benchmark = benchmark_returns.reindex(returns.index)
    excess = returns - benchmark
    ret21 = close.pct_change(trend_sessions)
    bench21 = (1.0 + benchmark_returns).rolling(trend_sessions).apply(np.prod, raw=True) - 1.0
    excess21 = ret21 - bench21.reindex(ret21.index)
    rolling_high = close.rolling(drawdown_sessions, min_periods=max(20, drawdown_sessions // 3)).max()
    drawdown = close / rolling_high - 1.0
    ma20 = close.rolling(20, min_periods=20).mean()
    ma50 = close.rolling(50, min_periods=50).mean()
    vol_short = returns.rolling(short_vol_sessions, min_periods=short_vol_sessions).std(ddof=0)
    vol_long = returns.rolling(long_vol_sessions, min_periods=long_vol_sessions).std(ddof=0).replace(0.0, np.nan)
    vol_ratio = vol_short / vol_long

    gap = pd.Series(index=close.index, dtype=float)
    if "open" in px.columns:
        adjusted_open = pd.to_numeric(px["open"], errors="coerce").reindex(close.index)
        gap = adjusted_open / close.shift(1) - 1.0

    abs_q, abs_n = past_quantile(returns, asof, lookback, minimum, float(quantiles["absolute_return_shock"]))
    rel_q, rel_n = past_quantile(excess, asof, lookback, minimum, float(quantiles["spy_relative_return_shock"]))
    gap_q, _ = past_quantile(gap, asof, lookback, minimum, float(quantiles["opening_gap_shock"]))
    trend_q, _ = past_quantile(excess21, asof, lookback, minimum, float(quantiles["trend_damage"]))
    dd_q, _ = past_quantile(drawdown, asof, lookback, minimum, float(quantiles["drawdown_damage"]))
    vol_q, _ = past_quantile(vol_ratio, asof, lookback, minimum, float(quantiles["volatility_ratio_spike"]))

    r1 = value_at(returns, asof)
    spy1 = value_at(benchmark_returns, asof)
    rel1 = None if r1 is None or spy1 is None else r1 - spy1
    gap1 = value_at(gap, asof)
    r21 = value_at(ret21, asof)
    rel21 = value_at(excess21, asof)
    dd63 = value_at(drawdown, asof)
    ma20_value = value_at(ma20, asof)
    ma50_value = value_at(ma50, asof)
    close_value = value_at(close, asof)
    vol_value = value_at(vol_ratio, asof)
    below20 = None if close_value is None or ma20_value is None else bool(close_value < ma20_value)
    below50 = None if close_value is None or ma50_value is None else bool(close_value < ma50_value)
    enough = min(abs_n, rel_n) >= minimum

    base.update(
        {
            "history_observations": int(min(abs_n, rel_n)),
            "close": close_value,
            "return_1d": r1,
            "spy_return_1d": spy1,
            "spy_excess_return_1d": rel1,
            "opening_gap_return": gap1,
            "return_21d": r21,
            "spy_excess_return_21d": rel21,
            "drawdown_63d": dd63,
            "ma20": ma20_value,
            "ma50": ma50_value,
            "below_ma20": below20,
            "below_ma50": below50,
            "volatility_ratio_21d_126d": vol_value,
            "absolute_return_shock_threshold": abs_q,
            "spy_relative_return_shock_threshold": rel_q,
            "opening_gap_shock_threshold": gap_q,
            "trend_damage_threshold": trend_q,
            "drawdown_damage_threshold": dd_q,
            "volatility_spike_threshold": vol_q,
            "idiosyncratic_shock": bool(enough and r1 is not None and rel1 is not None and abs_q is not None and rel_q is not None and r1 <= abs_q and rel1 <= rel_q),
            "opening_gap_shock": bool(enough and gap1 is not None and gap_q is not None and gap1 <= gap_q),
            "trend_damage": bool(enough and below20 is True and below50 is True and rel21 is not None and trend_q is not None and rel21 <= trend_q),
            "drawdown_damage": bool(enough and below50 is True and dd63 is not None and dd_q is not None and dd63 <= dd_q),
            "volatility_spike": bool(enough and vol_value is not None and vol_q is not None and vol_value >= vol_q),
            "data_reason": "" if exact and enough else ("exact_close_missing" if not exact else f"past_history_underpowered:{min(abs_n, rel_n)}<{minimum}"),
        }
    )
    return base


def classify(features: dict[str, Any]) -> tuple[str, str, str]:
    if features.get("data_reason"):
        return "DATA_INSUFFICIENT", "MISSING_NEUTRAL_NO_ACTION", str(features["data_reason"])
    signal_names = [
        name
        for name in ("idiosyncratic_shock", "opening_gap_shock", "trend_damage", "drawdown_damage", "volatility_spike")
        if features.get(name) is True
    ]
    signal_count = len(signal_names)
    gap_plus_damage = bool(features.get("opening_gap_shock") and (features.get("trend_damage") or features.get("drawdown_damage")))
    if features.get("idiosyncratic_shock") or signal_count >= 3 or gap_plus_damage:
        return "ALERT", "FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW", "|".join(signal_names)
    if signal_count:
        return "WATCH", "REVIEW_BEFORE_INCREMENTAL_BUY", "|".join(signal_names)
    return "NORMAL", "NO_CHANGE", "no_signal"


def load_account(path: Path, portfolio: str, asof: pd.Timestamp) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    account = read_json(path)
    if not account:
        raise FileNotFoundError(f"missing account for {portfolio}: {path}")
    account_portfolio = str(account.get("portfolio_kind") or portfolio).lower()
    if account_portfolio != portfolio:
        raise ValueError(f"account portfolio mismatch: {portfolio}!={account_portfolio}")
    account_date = pd.to_datetime(account.get("as_of_date"), errors="coerce")
    if pd.notna(account_date) and pd.Timestamp(account_date).normalize() > asof:
        raise ValueError(f"future account state for {portfolio}")
    positions = account.get("positions") if isinstance(account.get("positions"), list) else []
    clean: list[dict[str, Any]] = []
    for row in positions:
        if not isinstance(row, dict):
            continue
        ticker = clean_ticker(row.get("ticker"))
        shares = finite(row.get("shares"))
        if ticker and shares is not None and shares > 0:
            clean.append({"ticker": ticker, "shares": shares})
    return account, clean


def build_watch(
    *,
    account_paths: dict[str, Path],
    price_cache: Path,
    contract: dict[str, Any],
    contract_path: Path,
    asof: pd.Timestamp,
    available_from: str,
    require_exact_close: bool,
) -> tuple[dict[str, Any], pd.DataFrame]:
    asof = pd.Timestamp(asof).tz_localize(None).normalize()
    benchmark_ticker = clean_ticker(contract.get("benchmark")) or "SPY"
    benchmark_raw = load_price_series(price_cache, benchmark_ticker)
    benchmark_future_rows = int((pd.DatetimeIndex(benchmark_raw.index) > asof).sum()) if not benchmark_raw.empty else 0
    benchmark_px = benchmark_raw[benchmark_raw.index <= asof].copy() if not benchmark_raw.empty else pd.DataFrame()
    if not benchmark_px.empty:
        benchmark_px = benchmark_px.groupby(level=0).last().sort_index()
    benchmark_returns = benchmark_px["close"].pct_change() if "close" in benchmark_px.columns else pd.Series(dtype=float)
    benchmark_exact = bool(not benchmark_px.empty and pd.Timestamp(benchmark_px.index[-1]).normalize() == asof)

    feature_cache: dict[str, dict[str, Any]] = {}
    accounts: dict[str, dict[str, Any]] = {}
    positions_by_portfolio: dict[str, list[dict[str, Any]]] = {}
    for portfolio, account_path in account_paths.items():
        account, positions = load_account(account_path, portfolio, asof)
        accounts[portfolio] = account
        positions_by_portfolio[portfolio] = positions
        for position in positions:
            ticker = position["ticker"]
            if ticker not in feature_cache:
                feature_cache[ticker] = price_features(
                    ticker=ticker,
                    price_cache=price_cache,
                    benchmark_returns=benchmark_returns,
                    asof=asof,
                    contract=contract,
                )

    rows: list[dict[str, Any]] = []
    portfolio_summaries: dict[str, dict[str, Any]] = {}
    for portfolio, positions in positions_by_portfolio.items():
        account = accounts[portfolio]
        cash = finite(account.get("cash_usd")) or 0.0
        current_values: dict[str, float] = {}
        prior_values: dict[str, float] = {}
        for position in positions:
            ticker = position["ticker"]
            features = feature_cache[ticker]
            close = finite(features.get("close"))
            r1 = finite(features.get("return_1d"))
            current_value = float(position["shares"] * close) if close is not None else 0.0
            prior_value = current_value / (1.0 + r1) if r1 is not None and r1 > -0.999999 else current_value
            current_values[ticker] = current_value
            prior_values[ticker] = prior_value
        current_equity = cash + sum(current_values.values())
        prior_equity = cash + sum(prior_values.values())
        estimated_return = current_equity / prior_equity - 1.0 if prior_equity > 0 else None

        state_counts = {state: 0 for state in STATE_RANK}
        for position in positions:
            ticker = position["ticker"]
            features = dict(feature_cache[ticker])
            state, action, reasons = classify(features)
            state_counts[state] += 1
            prior_weight = prior_values[ticker] / prior_equity if prior_equity > 0 else None
            current_weight = current_values[ticker] / current_equity if current_equity > 0 else None
            r1 = finite(features.get("return_1d"))
            row = {
                "schema_version": SCHEMA_VERSION,
                "as_of_date": asof.date().isoformat(),
                "available_from": available_from,
                "portfolio_kind": portfolio,
                "account_as_of_date": str(account.get("as_of_date") or ""),
                "account_path": str(account_paths[portfolio]),
                "ticker": ticker,
                "shares": float(position["shares"]),
                "prior_weight_estimate": prior_weight,
                "current_weight": current_weight,
                "market_value_usd": current_values[ticker],
                "portfolio_return_contribution_1d": None if prior_weight is None or r1 is None else prior_weight * r1,
                "risk_state": state,
                "advisory_action": action,
                "reason_codes": reasons,
                **features,
                "forward_outcome_status": "UNRESOLVED",
                "forward_outcome_horizons_trading_days": "1|5|21|63|126",
                "missing_policy": "neutral_no_forced_trade",
                "orders_generated": False,
                "target_weight_changed": False,
                "cash_policy_changed": False,
                "production_activation_allowed": False,
                "live_trading_enabled": False,
            }
            row["event_id"] = canonical_hash(
                {"schema": SCHEMA_VERSION, "portfolio_kind": portfolio, "ticker": ticker, "as_of_date": row["as_of_date"]}
            )
            rows.append(row)
        portfolio_summaries[portfolio] = {
            "account_as_of_date": str(account.get("as_of_date") or ""),
            "position_count": len(positions),
            "cash_usd": cash,
            "estimated_prior_equity_usd": prior_equity,
            "estimated_current_equity_usd": current_equity,
            "estimated_portfolio_return_1d": estimated_return,
            "state_counts": state_counts,
        }

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["_portfolio_rank"] = frame["portfolio_kind"].map(PORTFOLIO_RANK).fillna(99)
        frame["_state_rank"] = frame["risk_state"].map(STATE_RANK).fillna(99)
        frame = frame.sort_values(
            ["_portfolio_rank", "_state_rank", "portfolio_return_contribution_1d", "ticker"],
            ascending=[True, True, True, True],
            na_position="last",
        ).drop(columns=["_portfolio_rank", "_state_rank"]).reset_index(drop=True)

    missing_exact: list[str] = []
    if not frame.empty:
        missing_mask = ~frame["price_exact_asof"].fillna(False).astype(bool)
        if bool(missing_mask.any()):
            missing_exact = (
                frame.loc[missing_mask, ["portfolio_kind", "ticker"]]
                .astype(str)
                .apply(lambda row: ":".join(row.tolist()), axis=1)
                .tolist()
            )
    if not benchmark_exact:
        status = "BLOCKED_EXACT_CLOSE"
    elif require_exact_close and missing_exact:
        status = "BLOCKED_EXACT_CLOSE"
    elif not frame.empty and (frame["risk_state"] == "DATA_INSUFFICIENT").any():
        status = "READY_REVIEW_ONLY_WITH_DATA_INSUFFICIENT"
    else:
        status = "READY_REVIEW_ONLY"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": status,
        "as_of_date": asof.date().isoformat(),
        "available_from": available_from,
        "benchmark": benchmark_ticker,
        "benchmark_exact_asof": benchmark_exact,
        "benchmark_latest_price_date": pd.Timestamp(benchmark_px.index[-1]).date().isoformat() if not benchmark_px.empty else "",
        "benchmark_future_rows_excluded": benchmark_future_rows,
        "held_row_count": int(len(frame)),
        "unique_ticker_count": int(frame["ticker"].nunique()) if not frame.empty else 0,
        "alert_count": int((frame["risk_state"] == "ALERT").sum()) if not frame.empty else 0,
        "watch_count": int((frame["risk_state"] == "WATCH").sum()) if not frame.empty else 0,
        "data_insufficient_count": int((frame["risk_state"] == "DATA_INSUFFICIENT").sum()) if not frame.empty else 0,
        "missing_exact_close_rows": missing_exact,
        "require_exact_close": bool(require_exact_close),
        "portfolio_summaries": portfolio_summaries,
        "input_paths": {
            "accounts": {key: str(value) for key, value in account_paths.items()},
            "price_cache": str(price_cache),
            "contract": str(contract_path),
        },
        "input_hashes": {
            "accounts": {key: sha256_file(value) for key, value in account_paths.items()},
            "contract": sha256_file(contract_path),
        },
        "research_registration": contract.get("research_registration", {}),
        "advisory_only": True,
        "orders_generated": False,
        "target_books_mutated": False,
        "cash_policy_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
    }
    return summary, frame


def archive_rows(path: Path, rows: pd.DataFrame) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            existing[str(payload["event_id"])] = payload
    new_rows: list[dict[str, Any]] = []
    for payload in rows.to_dict("records"):
        clean_payload = json.loads(json.dumps(payload, default=json_default))
        event_id = str(clean_payload["event_id"])
        if event_id in existing:
            if canonical_hash(existing[event_id]) != canonical_hash(clean_payload):
                raise ValueError(f"same-date holding risk event changed: {event_id}")
            continue
        existing[event_id] = clean_payload
        new_rows.append(clean_payload)
    if new_rows:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for payload in new_rows:
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=json_default) + "\n")
    return len(new_rows)


def render_report(summary: dict[str, Any], rows: pd.DataFrame) -> str:
    lines = [
        "# Run287 held-security risk watch",
        "",
        f"- status: `{summary['status']}`",
        f"- as_of_date: `{summary['as_of_date']}`",
        f"- held rows: `{summary['held_row_count']}`",
        f"- alerts / watches / insufficient: `{summary['alert_count']} / {summary['watch_count']} / {summary['data_insufficient_count']}`",
        "- advisory only; no target, cash, order, production, or live-trading mutation",
        "",
        "| Portfolio | Ticker | State | 1D | SPY excess | 1D contribution | 63D DD | Action | Reasons |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows.to_dict("records"):
        def pct(value: Any) -> str:
            number = finite(value)
            return "" if number is None else f"{number:.2%}"

        lines.append(
            f"| {row.get('portfolio_kind', '')} | {row.get('ticker', '')} | `{row.get('risk_state', '')}` | "
            f"{pct(row.get('return_1d'))} | {pct(row.get('spy_excess_return_1d'))} | "
            f"{pct(row.get('portfolio_return_contribution_1d'))} | {pct(row.get('drawdown_63d'))} | "
            f"`{row.get('advisory_action', '')}` | {row.get('reason_codes', '')} |"
        )
    lines.extend(
        [
            "",
            "`ALERT` and `WATCH` freeze nothing by themselves. They require human review and a separately preregistered broker-ledger A/B before any portfolio action.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(output_dir: Path, summary: dict[str, Any], rows: pd.DataFrame) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    history_path = output_dir / "risk_history.jsonl"
    appended = archive_rows(history_path, rows)
    current_path = output_dir / "holding_risk_watch.csv"
    rows.to_csv(current_path, index=False)
    summary = dict(summary)
    summary["history_appended_count"] = appended
    summary["history_event_count"] = sum(1 for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip())
    summary["output_hashes"] = {
        "holding_risk_watch_sha256": sha256_file(current_path),
        "risk_history_sha256": sha256_file(history_path),
    }
    write_json(output_dir / "summary.json", summary)
    (output_dir / "report.md").write_text(render_report(summary, rows), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-account", default="outputs/daily_simulated_fill_ledger/main/account_state_latest.json")
    parser.add_argument("--concentrated-account", default="outputs/daily_simulated_fill_ledger/concentrated/account_state_latest.json")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--available-from", default="")
    parser.add_argument("--output-dir", default="outputs/holding_risk_watch")
    parser.add_argument("--require-exact-close", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    asof = pd.Timestamp(args.as_of_date).normalize()
    contract_path = repo_path(args.contract)
    contract = read_json(contract_path)
    if not contract:
        print(json.dumps({"status": "BLOCKED_CONTRACT", "contract": str(contract_path)}, indent=2))
        return 2
    available_from = args.available_from or f"{asof.date().isoformat()}T23:59:59Z"
    summary, rows = build_watch(
        account_paths={
            "main": repo_path(args.main_account),
            "concentrated": repo_path(args.concentrated_account),
        },
        price_cache=repo_path(args.price_cache),
        contract=contract,
        contract_path=contract_path,
        asof=asof,
        available_from=available_from,
        require_exact_close=bool(args.require_exact_close),
    )
    persisted = write_outputs(repo_path(args.output_dir), summary, rows)
    print(json.dumps(persisted, indent=2, sort_keys=True, default=json_default))
    return 0 if persisted["status"].startswith("READY_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
