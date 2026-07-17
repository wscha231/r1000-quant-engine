#!/usr/bin/env python3
"""Build a no-order risk packet for proposed current selector new entries.

The candidate set is derived from a hash-pinned no-write selector comparison.
Long history is taken from the immutable selector price map and extended only
with verified current provider rows.  Risk features and classifications reuse
the held-security watch implementation exactly.  No selector weight, target
book, cash policy, order, backtest, fullrun, or production state is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_holding_risk_watch import (  # noqa: E402
    archive_rows,
    canonical_hash,
    classify,
    clean_ticker,
    json_default,
    price_features,
    read_json,
    sha256_file,
    write_json,
)
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-candidate-risk-watch-v1"
READY_STATUS = "READY_CANDIDATE_RISK_REVIEW_ONLY"
READY_INSUFFICIENT_STATUS = "READY_CANDIDATE_RISK_REVIEW_ONLY_WITH_DATA_INSUFFICIENT"
BLOCKED_STATUS = "BLOCKED_CANDIDATE_RISK_WATCH"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": bool(path.exists()),
        "bytes": int(path.stat().st_size) if path.exists() and path.is_file() else 0,
        "sha256": sha256_file(path) if path.exists() and path.is_file() else "",
    }


def input_audit(path: Path, expected: str, label: str) -> dict[str, Any]:
    row = fingerprint(path)
    row.update(
        label=label,
        expected_sha256=str(expected),
        hash_matches=bool(expected and row.get("sha256") == expected),
    )
    return row


def verified_output(
    manifest_path: Path, manifest: Mapping[str, Any], key: str
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get("outputs") or {}).get(key) or {}
    raw = str(record.get("path") or "")
    path = Path(raw)
    if raw and not path.is_absolute():
        path = manifest_path.parent / path
    row = input_audit(path, str(record.get("sha256") or ""), key)
    if not row["exists"] or not row["hash_matches"]:
        raise ValueError(f"manifest output mismatch: {key}")
    return path, row


def blocked(
    output_dir: Path,
    failures: list[str],
    audits: Mapping[str, Any],
    started: float,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "candidate_risk_watch_passed": False,
        "contract_failures": failures,
        "advisory_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "summary.json", payload)
    return payload


def clean_raw_price(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    if "Date" in work.columns:
        dates = pd.to_datetime(work.pop("Date"), errors="coerce", utc=True)
    else:
        dates = pd.to_datetime(work.index, errors="coerce", utc=True)
    work.index = pd.DatetimeIndex(dates).tz_convert(None)
    work = work[work.index.notna()].sort_index()
    if isinstance(work.columns, pd.MultiIndex):
        work.columns = work.columns.get_level_values(0)
    return work.groupby(level=0).last()


def close_series(frame: pd.DataFrame) -> pd.Series:
    column = "Adj Close" if "Adj Close" in frame.columns else "Close"
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def candidate_metadata(comparison: pd.DataFrame) -> pd.DataFrame:
    work = comparison.copy()
    work["ticker"] = work["ticker"].map(clean_ticker)
    for column in ("advisory_weight", "marked_weight", "delta_vs_marked"):
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0.0)
    work = work.loc[
        work["ticker"].ne("")
        & work["advisory_weight"].gt(1e-12)
        & work["marked_weight"].le(1e-12)
    ].copy()
    if work.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for ticker, group in work.groupby("ticker", sort=True):
        rows.append(
            {
                "ticker": ticker,
                "scenario_count": int(group["scenario"].nunique()),
                "scenarios": "|".join(sorted(set(group["scenario"].astype(str)))),
                "portfolios": "|".join(sorted(set(group["portfolio_kind"].astype(str)))),
                "maximum_advisory_weight": float(group["advisory_weight"].max()),
                "maximum_delta_vs_marked": float(group["delta_vs_marked"].max()),
            }
        )
    return pd.DataFrame(rows)


def build_isolated_cache(
    *,
    candidates: pd.DataFrame,
    price_map: pd.DataFrame,
    provider: pd.DataFrame,
    macro_cache: Path,
    expected_spy_sha256: str,
    isolated_cache: Path,
    valuation: pd.Timestamp,
    minimum_overlap: int,
    maximum_relative_error: float,
) -> tuple[pd.DataFrame, list[str]]:
    isolated_cache.mkdir(parents=True, exist_ok=True)
    provider = provider.copy()
    provider["ticker"] = provider["ticker"].astype(str).str.upper().str.strip()
    provider["Date"] = pd.to_datetime(provider["Date"], errors="coerce", utc=True).dt.tz_convert(None)
    failures: list[str] = []
    audits: list[dict[str, Any]] = []
    price_map = price_map.copy()
    price_map["ticker"] = price_map["ticker"].map(clean_ticker)
    source_map = price_map.set_index("ticker", drop=False)
    for ticker in candidates["ticker"]:
        if ticker not in source_map.index:
            failures.append(f"price_map_missing:{ticker}")
            continue
        record = source_map.loc[ticker]
        if isinstance(record, pd.DataFrame):
            failures.append(f"duplicate_price_map:{ticker}")
            continue
        source_path = Path(str(record.get("path") or ""))
        expected_source_hash = str(record.get("sha256") or "")
        if not source_path.exists():
            failures.append(f"source_price_missing:{ticker}")
            continue
        actual_source_hash = sha256_file(source_path)
        if actual_source_hash != expected_source_hash:
            failures.append(f"source_price_hash:{ticker}")
            continue
        raw_base = clean_raw_price(pd.read_parquet(source_path))
        raw_current = clean_raw_price(provider.loc[provider["ticker"].eq(ticker)].copy())
        base_future_rows = int((raw_base.index > valuation).sum())
        provider_future_rows = int((raw_current.index > valuation).sum())
        base = raw_base.loc[raw_base.index <= valuation].copy()
        current = raw_current.loc[raw_current.index <= valuation].copy()
        common = base.index.intersection(current.index)
        # Raw closes are the stable identity contract. Adjusted-close history
        # can be legitimately restated when a dividend becomes known between
        # snapshots, so comparing Adj Close here creates false source breaks.
        # We still preserve total-return continuity below by replacing the
        # provider overlap and rebasing only the older frozen history.
        base_close = (
            pd.to_numeric(base["Close"], errors="coerce").reindex(common)
            if "Close" in base
            else pd.Series(np.nan, index=common, dtype=float)
        )
        current_close = (
            pd.to_numeric(current["Close"], errors="coerce").reindex(common)
            if "Close" in current
            else pd.Series(np.nan, index=common, dtype=float)
        )
        relative = (
            (base_close - current_close).abs()
            / current_close.abs().replace(0.0, np.nan)
        ).replace([np.inf, -np.inf], np.nan).dropna()
        overlap_max = float(relative.max()) if not relative.empty else math.inf
        if len(relative) < minimum_overlap:
            failures.append(f"overlap_underpowered:{ticker}:{len(relative)}")
        if not math.isfinite(overlap_max) or overlap_max > maximum_relative_error:
            failures.append(f"overlap_mismatch:{ticker}:{overlap_max}")
        base_max = pd.Timestamp(base.index.max()).normalize() if not base.empty else pd.NaT
        adjusted_relative = pd.Series(dtype=float)
        adjustment_rebase_factor = 1.0
        if "Adj Close" in base and "Adj Close" in current and len(common):
            base_adjusted = pd.to_numeric(
                base["Adj Close"], errors="coerce"
            ).reindex(common)
            current_adjusted = pd.to_numeric(
                current["Adj Close"], errors="coerce"
            ).reindex(common)
            adjusted_relative = (
                (base_adjusted - current_adjusted).abs()
                / current_adjusted.abs().replace(0.0, np.nan)
            ).replace([np.inf, -np.inf], np.nan).dropna()
            valid_ratio = (
                current_adjusted / base_adjusted.replace(0.0, np.nan)
            ).replace([np.inf, -np.inf], np.nan).dropna()
            if valid_ratio.empty:
                failures.append(f"adjustment_rebase_unavailable:{ticker}")
            else:
                adjustment_rebase_factor = float(valid_ratio.iloc[0])
        provider_start = (
            pd.Timestamp(current.index.min()).normalize() if not current.empty else pd.NaT
        )
        historical = (
            base.loc[base.index < provider_start].copy()
            if pd.notna(provider_start)
            else base.copy()
        )
        if "Adj Close" in historical:
            historical["Adj Close"] = (
                pd.to_numeric(historical["Adj Close"], errors="coerce")
                * adjustment_rebase_factor
            )
        provider_replacement = current.copy()
        combined = (
            pd.concat([historical, provider_replacement], axis=0)
            .sort_index()
            .groupby(level=0)
            .last()
        )
        combined = combined.loc[combined.index <= valuation].copy()
        destination = isolated_cache / px_cache_name(ticker)
        combined.to_parquet(destination)
        latest = pd.Timestamp(combined.index.max()).normalize() if not combined.empty else pd.NaT
        if pd.isna(latest) or latest != valuation:
            failures.append(f"combined_not_current:{ticker}")
        audits.append(
            {
                "ticker": ticker,
                "role": "proposed_new_entry",
                "source_path": str(source_path),
                "source_sha256": actual_source_hash,
                "source_row_count": int(len(base)),
                "source_date_max": base_max.date().isoformat() if pd.notna(base_max) else "",
                "source_future_rows_excluded": base_future_rows,
                "provider_overlap_count": int(len(relative)),
                "provider_overlap_max_relative_error": overlap_max,
                "provider_adjusted_overlap_max_relative_error": (
                    float(adjusted_relative.max())
                    if not adjusted_relative.empty
                    else math.inf
                ),
                "historical_adjustment_rebase_factor": adjustment_rebase_factor,
                "provider_future_rows_excluded": provider_future_rows,
                "increment_row_count": (
                    int((current.index > base_max).sum())
                    if pd.notna(base_max)
                    else int(len(current))
                ),
                "provider_history_replacement_count": int(len(provider_replacement)),
                "provider_replacement_date_min": (
                    provider_start.date().isoformat() if pd.notna(provider_start) else ""
                ),
                "isolated_path": str(destination),
                "isolated_sha256": sha256_file(destination),
                "isolated_row_count": int(len(combined)),
                "isolated_date_max": latest.date().isoformat() if pd.notna(latest) else "",
            }
        )

    spy_source = macro_cache / px_cache_name("SPY")
    if not spy_source.exists():
        failures.append("spy_source_missing")
    else:
        actual_spy_hash = sha256_file(spy_source)
        if not expected_spy_sha256 or actual_spy_hash != expected_spy_sha256:
            failures.append("spy_source_hash")
        spy = clean_raw_price(pd.read_parquet(spy_source))
        spy_future_rows = int((spy.index > valuation).sum())
        spy = spy.loc[spy.index <= valuation].copy()
        destination = isolated_cache / px_cache_name("SPY")
        spy.to_parquet(destination)
        latest = pd.Timestamp(spy.index.max()).normalize() if not spy.empty else pd.NaT
        if pd.isna(latest) or latest != valuation:
            failures.append("spy_not_current")
        audits.append(
            {
                "ticker": "SPY",
                "role": "benchmark",
                "source_path": str(spy_source),
                "source_sha256": actual_spy_hash,
                "source_row_count": int(len(spy)),
                "source_date_max": latest.date().isoformat() if pd.notna(latest) else "",
                "source_future_rows_excluded": spy_future_rows,
                "provider_overlap_count": 0,
                "provider_overlap_max_relative_error": 0.0,
                "increment_row_count": 0,
                "isolated_path": str(destination),
                "isolated_sha256": sha256_file(destination),
                "isolated_row_count": int(len(spy)),
                "isolated_date_max": latest.date().isoformat() if pd.notna(latest) else "",
            }
        )
    return pd.DataFrame(audits), failures


def source_audits_unchanged(audits: Mapping[str, Mapping[str, Any]]) -> bool:
    for row in audits.values():
        raw_path = str(row.get("path") or "")
        baseline = str(row.get("sha256") or "")
        if not raw_path or not baseline:
            return False
        path = Path(raw_path)
        if not path.exists() or sha256_file(path) != baseline:
            return False
    return True


def evaluate_candidates(
    candidates: pd.DataFrame,
    isolated_cache: Path,
    base_contract: dict[str, Any],
    candidate_contract: dict[str, Any],
    valuation: pd.Timestamp,
    available_from: str,
) -> pd.DataFrame:
    spy = load_price_series(isolated_cache, "SPY")
    benchmark_returns = spy["close"].pct_change() if "close" in spy.columns else pd.Series(dtype=float)
    rows: list[dict[str, Any]] = []
    for record in candidates.to_dict("records"):
        ticker = str(record["ticker"])
        features = price_features(
            ticker=ticker,
            price_cache=isolated_cache,
            benchmark_returns=benchmark_returns,
            asof=valuation,
            contract=base_contract,
        )
        state, action, reasons = classify(features)
        row = {
            "schema_version": SCHEMA_VERSION,
            "as_of_date": valuation.date().isoformat(),
            "available_from": available_from,
            **record,
            "risk_state": state,
            "advisory_action": action,
            "reason_codes": reasons,
            **features,
            "forward_outcome_status": "UNRESOLVED",
            "forward_outcome_horizons_trading_days": "1|5|21|63|126",
            "missing_policy": "neutral_no_forced_trade",
            "normal_state_is_not_alpha_evidence": True,
            "portfolio_transition_allowed": False,
            "orders_generated": False,
            "target_books_mutated": False,
            "selector_weights_changed": False,
            "cash_policy_changed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
        }
        row["event_id"] = canonical_hash(
            {
                "schema": SCHEMA_VERSION,
                "ticker": ticker,
                "as_of_date": row["as_of_date"],
                "selector_source": candidate_contract["candidate_derivation"]["source"],
            }
        )
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        rank = {"ALERT": 0, "WATCH": 1, "DATA_INSUFFICIENT": 2, "NORMAL": 3}
        frame["_rank"] = frame["risk_state"].map(rank).fillna(99)
        frame = frame.sort_values(["_rank", "ticker"]).drop(columns="_rank").reset_index(drop=True)
    return frame


def deterministic_rows(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    columns = sorted(set(left.columns) | set(right.columns))
    a = left.reindex(columns=columns).sort_values("ticker").reset_index(drop=True)
    b = right.reindex(columns=columns).sort_values("ticker").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(a, b, check_dtype=True, check_exact=True)
        return True
    except AssertionError:
        return False


def render_report(summary: Mapping[str, Any], rows: pd.DataFrame) -> str:
    lines = [
        "# Run287 proposed-candidate risk watch",
        "",
        f"- status: `{summary['status']}`",
        f"- as_of_date: `{summary['as_of_date']}`",
        f"- candidates: `{summary['candidate_count']}`",
        f"- alerts / watches / insufficient / normal: `{summary['alert_count']} / {summary['watch_count']} / {summary['data_insufficient_count']} / {summary['normal_count']}`",
        "- advisory pretrade review only; a NORMAL state is not buy or alpha evidence",
        "- no selector weight, target book, cash, order, fullrun, production, or live-trading mutation",
        "",
        "| Ticker | Portfolios | Scenarios | Max weight | State | 1D | SPY excess | 21D excess | 63D DD | Action | Reasons |",
        "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows.to_dict("records"):
        def pct(value: Any) -> str:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return ""
            return "" if not math.isfinite(number) else f"{number:.2%}"

        def table_text(value: Any) -> str:
            return str(value or "").replace("|", "<br>")

        lines.append(
            f"| {table_text(row.get('ticker'))} | {table_text(row.get('portfolios'))} | "
            f"{table_text(row.get('scenarios'))} | "
            f"{pct(row.get('maximum_advisory_weight'))} | `{row.get('risk_state', '')}` | "
            f"{pct(row.get('return_1d'))} | {pct(row.get('spy_excess_return_1d'))} | "
            f"{pct(row.get('spy_excess_return_21d'))} | {pct(row.get('drawdown_63d'))} | "
            f"`{row.get('advisory_action', '')}` | {table_text(row.get('reason_codes'))} |"
        )
    lines.extend(
        [
            "",
            "`ALERT` and `WATCH` require review. `NORMAL` only means that this frozen price-damage contract did not fire; it does not authorize an entry.",
            "",
        ]
    )
    return "\n".join(lines)


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "selector_manifest": repo_path(args.selector_manifest),
        "price_map_manifest": repo_path(args.price_map_manifest),
        "price_manifest": repo_path(args.price_manifest),
        "macro_manifest": repo_path(args.macro_manifest),
        "holding_watch_summary": repo_path(args.holding_watch_summary),
        "base_contract": repo_path(args.base_contract),
        "candidate_contract": repo_path(args.candidate_contract),
    }
    expected = {
        "selector_manifest": args.expected_selector_sha256,
        "price_map_manifest": args.expected_price_map_sha256,
        "price_manifest": args.expected_price_sha256,
        "macro_manifest": args.expected_macro_sha256,
        "holding_watch_summary": args.expected_holding_watch_summary_sha256,
        "base_contract": args.expected_base_contract_sha256,
        "candidate_contract": args.expected_candidate_contract_sha256,
    }
    audits = {name: input_audit(path, expected[name], name) for name, path in paths.items()}
    failures = [
        f"input_hash_mismatch:{name}"
        for name, row in audits.items()
        if not row.get("exists") or not row.get("hash_matches")
    ]
    if failures:
        return blocked(output_dir, failures, audits, started)

    manifests = {
        name: read_json(paths[name])
        for name in (
            "selector_manifest",
            "price_map_manifest",
            "price_manifest",
            "macro_manifest",
            "holding_watch_summary",
        )
    }
    base_contract = read_json(paths["base_contract"])
    candidate_contract = read_json(paths["candidate_contract"])
    required_statuses = {
        "selector_manifest": "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED",
        "price_map_manifest": "READY_CURRENT_SELECTOR_PRICE_MAP_NONSELECTING",
        "price_manifest": "READY_RESEARCH_SCORED_LATEST",
        "macro_manifest": "READY_CONSERVATIVE_MACRO_SIDECAR",
        "holding_watch_summary": "READY_REVIEW_ONLY",
    }
    for name, required in required_statuses.items():
        actual = manifests[name].get("status")
        if actual != required:
            failures.append(f"status:{name}:{actual}!={required}")
    if candidate_contract.get("schema_version") != "run287-candidate-risk-watch-contract-v1":
        failures.append("candidate_contract_schema")
    if candidate_contract.get("base_holding_risk_contract") != args.base_contract:
        failures.append("base_contract_reference_mismatch")
    selector = manifests["selector_manifest"]
    if bool(selector.get("execution_allowed")) or bool(selector.get("target_book_file_written")):
        failures.append("selector_not_no_write")
    valuation = pd.Timestamp(args.valuation_date).normalize()
    if str(selector.get("valuation_price_cutoff_date") or "") != args.valuation_date:
        failures.append("selector_valuation_mismatch")
    holding_summary = manifests["holding_watch_summary"]
    if str(holding_summary.get("as_of_date") or "") != args.valuation_date:
        failures.append("holding_watch_valuation_mismatch")
    if failures:
        return blocked(output_dir, failures, audits, started)

    try:
        comparison_path, audits["selector_comparison"] = verified_output(
            paths["selector_manifest"], selector, "marked_official_advisory_comparison"
        )
        price_map_path, audits["selector_price_map"] = verified_output(
            paths["price_map_manifest"], manifests["price_map_manifest"], "selector_price_map"
        )
        provider_path, audits["provider_price_overlap"] = verified_output(
            paths["price_manifest"], manifests["price_manifest"], "provider_price_overlap.parquet"
        )
        market_audit_path, audits["market_component_audit"] = verified_output(
            paths["macro_manifest"], manifests["macro_manifest"], "market_component_audit"
        )
    except Exception as exc:
        failures.append(f"manifest_output:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, audits, started)

    comparison = pd.read_csv(comparison_path, low_memory=False)
    candidates = candidate_metadata(comparison)
    expected_tickers = {
        clean_ticker(value) for value in args.expected_tickers.split(",") if clean_ticker(value)
    }
    actual_tickers = set(candidates["ticker"]) if not candidates.empty else set()
    if actual_tickers != expected_tickers:
        failures.append(
            f"candidate_set:{','.join(sorted(actual_tickers))}!={','.join(sorted(expected_tickers))}"
        )
    if len(candidates) != int(args.expected_candidate_count):
        failures.append(f"candidate_count:{len(candidates)}!={args.expected_candidate_count}")
    if failures:
        return blocked(output_dir, failures, audits, started)

    price_map = pd.read_csv(price_map_path, low_memory=False)
    provider = pd.read_parquet(provider_path)
    market_audit = pd.read_csv(market_audit_path, low_memory=False)
    market_audit["ticker"] = market_audit["ticker"].map(clean_ticker)
    spy_audit = market_audit.loc[market_audit["ticker"].eq("SPY")]
    if len(spy_audit) != 1:
        failures.append(f"spy_market_audit_count:{len(spy_audit)}")
        return blocked(output_dir, failures, audits, started)
    expected_spy_sha256 = str(spy_audit.iloc[0].get("isolated_sha256") or "")
    macro_cache = repo_path(args.macro_price_cache)
    expected_spy_path = macro_cache / px_cache_name("SPY")
    audited_spy_path = Path(str(spy_audit.iloc[0].get("isolated_path") or ""))
    try:
        spy_path_matches = audited_spy_path.resolve() == expected_spy_path.resolve()
    except OSError:
        spy_path_matches = False
    if not spy_path_matches:
        failures.append("spy_market_audit_path_mismatch")
        return blocked(output_dir, failures, audits, started)
    isolated_cache = output_dir / "inputs/isolated_price_cache"
    price_audit, cache_failures = build_isolated_cache(
        candidates=candidates,
        price_map=price_map,
        provider=provider,
        macro_cache=macro_cache,
        expected_spy_sha256=expected_spy_sha256,
        isolated_cache=isolated_cache,
        valuation=valuation,
        minimum_overlap=int(candidate_contract["price_contract"]["minimum_overlap_rows"]),
        maximum_relative_error=float(
            candidate_contract["price_contract"]["maximum_overlap_relative_error"]
        ),
    )
    failures.extend(cache_failures)
    for record in price_audit.to_dict("records"):
        ticker = clean_ticker(record.get("ticker"))
        audits[f"price_source:{ticker}"] = {
            "path": str(record.get("source_path") or ""),
            "exists": True,
            "sha256": str(record.get("source_sha256") or ""),
            "label": f"price_source:{ticker}",
        }
    if failures:
        return blocked(output_dir, failures, audits, started)

    available_from = str(holding_summary.get("available_from") or "")
    rows_a = evaluate_candidates(
        candidates, isolated_cache, base_contract, candidate_contract, valuation, available_from
    )
    rows_b = evaluate_candidates(
        candidates, isolated_cache, base_contract, candidate_contract, valuation, available_from
    )
    deterministic = deterministic_rows(rows_a, rows_b)
    if not deterministic:
        failures.append("candidate_risk_nondeterministic")
    if not bool(rows_a["price_exact_asof"].fillna(False).astype(bool).all()):
        failures.append("candidate_exact_close_failure")
    if bool(rows_a["ticker"].eq("DD").any()):
        failures.append("quarantined_dd_candidate")
    if not source_audits_unchanged(audits):
        failures.append("source_inputs_mutated_during_evaluation")
    if failures:
        return blocked(output_dir, failures, audits, started)

    rows_path = output_dir / "candidate_risk_watch.csv"
    price_audit_path = output_dir / "price_source_audit.csv"
    history_path = output_dir / "risk_history.jsonl"
    rows_a.to_csv(rows_path, index=False)
    price_audit.to_csv(price_audit_path, index=False)
    appended = archive_rows(history_path, rows_a)
    if not source_audits_unchanged(audits):
        failures.append("source_inputs_mutated_during_output_write")
        return blocked(output_dir, failures, audits, started)
    insufficient = int(rows_a["risk_state"].eq("DATA_INSUFFICIENT").sum())
    status = READY_INSUFFICIENT_STATUS if insufficient else READY_STATUS
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "candidate_risk_watch_passed": True,
        "contract_failures": [],
        "as_of_date": args.valuation_date,
        "available_from": available_from,
        "candidate_count": int(len(rows_a)),
        "candidate_tickers": sorted(set(rows_a["ticker"])),
        "alert_count": int(rows_a["risk_state"].eq("ALERT").sum()),
        "watch_count": int(rows_a["risk_state"].eq("WATCH").sum()),
        "data_insufficient_count": insufficient,
        "normal_count": int(rows_a["risk_state"].eq("NORMAL").sum()),
        "determinism": {"exact_rerun_match": deterministic},
        "history_appended_count": int(appended),
        "history_event_count": int(
            sum(1 for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip())
        ),
        "research_registration": candidate_contract.get("research_registration", {}),
        "interpretation": {
            "normal_state_is_not_alpha_evidence": True,
            "risk_state_may_authorize_buy": False,
            "portfolio_transition_allowed": False,
        },
        "advisory_only": True,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(audits),
        "outputs": {
            "candidate_risk_watch": fingerprint(rows_path),
            "price_source_audit": fingerprint(price_audit_path),
            "risk_history": fingerprint(history_path),
        },
        "recommended_next_step": "review ALERT/WATCH candidates and append the unchanged selector/risk contracts across future decision weeks; do not promote from one date",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "report.md").write_text(render_report(payload, rows_a), encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector-manifest", required=True)
    parser.add_argument("--expected-selector-sha256", required=True)
    parser.add_argument("--price-map-manifest", required=True)
    parser.add_argument("--expected-price-map-sha256", required=True)
    parser.add_argument("--price-manifest", required=True)
    parser.add_argument("--expected-price-sha256", required=True)
    parser.add_argument("--macro-manifest", required=True)
    parser.add_argument("--expected-macro-sha256", required=True)
    parser.add_argument("--holding-watch-summary", required=True)
    parser.add_argument("--expected-holding-watch-summary-sha256", required=True)
    parser.add_argument("--macro-price-cache", required=True)
    parser.add_argument(
        "--base-contract", default="docs/run287_holding_risk_watch_contract.json"
    )
    parser.add_argument("--expected-base-contract-sha256", required=True)
    parser.add_argument(
        "--candidate-contract", default="docs/run287_candidate_risk_watch_contract.json"
    )
    parser.add_argument("--expected-candidate-contract-sha256", required=True)
    parser.add_argument("--valuation-date", default="2026-07-13")
    parser.add_argument("--expected-candidate-count", type=int, default=7)
    parser.add_argument(
        "--expected-tickers", default="AMAT,ARM,COHU,DELL,FTNT,PANW,STX"
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_candidate_risk_watch_20260714_close_20260713",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build(args)
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "candidate_tickers": payload.get("candidate_tickers", []),
                "alert_count": payload.get("alert_count"),
                "watch_count": payload.get("watch_count"),
                "data_insufficient_count": payload.get("data_insufficient_count"),
                "normal_count": payload.get("normal_count"),
                "portfolio_transition_allowed": payload.get(
                    "interpretation", {}
                ).get("portfolio_transition_allowed", False),
            },
            sort_keys=True,
        )
    )
    return 0 if payload.get("candidate_risk_watch_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
