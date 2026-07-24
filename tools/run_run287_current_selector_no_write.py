#!/usr/bin/env python3
"""Run the pinned Run287 selector on the current close without executable writes.

The adapter consumes immutable current-decision, score-stack, crisis, price,
and marked-account inputs.  It calls the exact official selector functions at
the pinned policy commit, then writes only advisory projections and diagnostic
turnover/cost comparisons.  It never writes a target book or an order file.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_pinned_git_import import pinned_import_context
from tools.run_data_freshness_contract import (
    core_candidate_coverage_for_path,
    core_candidate_coverage_semantic_view,
    core_candidate_ticker_set_sha256,
)
from tools.run_run287_current_advisory_selector import (
    FORBIDDEN_COLUMNS,
    SCENARIOS,
    clean_tickers,
    current_prior_book,
    deterministic_projection,
    enrich_relative_strength_from_map,
    exact_environment,
    fingerprint,
    git_head,
    load_json,
    merge_stack_precedence,
    run_core_selector,
    sha256,
    write_json,
)


SCHEMA_VERSION = "run287-current-selector-no-write-v1"
READY_STATUS = "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED"
BLOCKED_STATUS = "BLOCKED_CURRENT_SELECTOR_NO_WRITE"
POLICY_COMMIT = "15176b588d5bb0792bce1df6367758d795a8a33a"
CURRENT_SCORE_SCHEMA_VERSION = "run287-scored-latest-refresh-v4"


def next_nyse_session(valuation_date: str) -> str:
    valuation = pd.Timestamp(valuation_date).normalize()
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=valuation, end_date=valuation + pd.Timedelta(days=10)
    )
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    future = sessions[sessions > valuation]
    if future.empty:
        raise ValueError("next NYSE session unavailable")
    return pd.Timestamp(future[0]).date().isoformat()


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def input_audit(path: Path, expected: str, label: str) -> dict[str, Any]:
    row = fingerprint(path)
    row.update(
        label=label,
        expected_sha256=str(expected),
        hash_matches=bool(expected and row.get("sha256") == expected),
    )
    return row


def changed_input_failures(audits: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for label, expected in audits.items():
        if not isinstance(expected, Mapping) or not expected.get("path"):
            continue
        current = fingerprint(Path(str(expected.get("path") or "")))
        if any(
            current.get(field) != expected.get(field)
            for field in ("exists", "bytes", "sha256")
        ):
            failures.append(f"input_changed_before_selector_publish:{label}")
    return failures


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
    *,
    selector_executed: bool = False,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "selector_no_write_passed": False,
        "contract_failures": failures,
        "research_only": True,
        "advisory_only": True,
        "execution_allowed": False,
        "target_book_file_written": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "selector_executed": bool(selector_executed),
        "source_inputs": dict(audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def normalized_provider_prices(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    required = {"ticker", "Date", "Close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"provider price columns missing: {sorted(required-set(frame.columns))}")
    work = frame.copy()
    work["ticker"] = clean_tickers(work["ticker"])
    work["Date"] = pd.to_datetime(work["Date"], errors="coerce").dt.tz_localize(None)
    work = work.dropna(subset=["Date"])
    result: dict[str, pd.DataFrame] = {}
    for ticker, group in work.groupby("ticker", sort=True):
        group = group.sort_values("Date").drop_duplicates("Date", keep="last")
        close_column = "Adj Close" if "Adj Close" in group.columns else "Close"
        out = pd.DataFrame(index=pd.DatetimeIndex(group["Date"]))
        out["close"] = pd.to_numeric(group[close_column], errors="coerce").to_numpy()
        if "Open" in group.columns:
            open_values = pd.to_numeric(group["Open"], errors="coerce")
            if close_column == "Adj Close":
                raw_close = pd.to_numeric(group["Close"], errors="coerce").replace(0, np.nan)
                open_values = open_values * (
                    pd.to_numeric(group["Adj Close"], errors="coerce") / raw_close
                )
            out["open"] = open_values.to_numpy()
        else:
            out["open"] = out["close"]
        result[str(ticker)] = out.dropna(how="all")
    return result


def latest_official_weight_frame(book: pd.DataFrame) -> pd.DataFrame:
    work = book.copy()
    dates = pd.to_datetime(work["rebalance_date"], errors="coerce")
    work = work.loc[dates.eq(dates.max())].copy()
    work["ticker"] = clean_tickers(work["ticker"])
    work["weight"] = pd.to_numeric(work["weight"], errors="coerce").fillna(0.0)
    stocks = work.loc[~work["ticker"].isin({"CASH", "__CASH__"})]
    result = stocks.groupby("ticker", as_index=False)["weight"].sum()
    cash_rows = work.loc[work["ticker"].isin({"CASH", "__CASH__"}), "weight"]
    cash = float(cash_rows.sum()) if not cash_rows.empty else 1.0 - float(result["weight"].sum())
    return pd.concat(
        [result, pd.DataFrame([{"ticker": "CASH", "weight": max(0.0, cash)}])],
        ignore_index=True,
    )


def marked_weight_frames(
    holding_watch: pd.DataFrame,
    watch_summary: Mapping[str, Any],
    valuation: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    work = holding_watch.copy()
    work["ticker"] = clean_tickers(work["ticker"])
    work["as_of_date"] = pd.to_datetime(work["as_of_date"], errors="coerce").dt.normalize()
    if not bool(work["as_of_date"].eq(valuation).all()):
        raise ValueError("holding watch is not exact valuation close")
    if not bool(work["price_exact_asof"].fillna(False).astype(bool).all()):
        raise ValueError("holding watch has non-exact close rows")
    result: dict[str, pd.DataFrame] = {}
    summaries = watch_summary.get("portfolio_summaries") or {}
    for kind in ("main", "concentrated"):
        group = work.loc[work["portfolio_kind"].eq(kind)].copy()
        group["weight"] = pd.to_numeric(group["current_weight"], errors="coerce").fillna(0.0)
        frame = group.groupby("ticker", as_index=False)["weight"].sum()
        summary = summaries.get(kind) or {}
        equity = float(summary.get("estimated_current_equity_usd") or 0.0)
        cash_usd = float(summary.get("cash_usd") or 0.0)
        if equity <= 0:
            raise ValueError(f"invalid marked equity: {kind}")
        cash = cash_usd / equity
        if not math.isclose(float(frame["weight"].sum()) + cash, 1.0, abs_tol=2e-9):
            raise ValueError(f"marked weight conservation failure: {kind}")
        result[kind] = pd.concat(
            [frame, pd.DataFrame([{"ticker": "CASH", "weight": cash}])],
            ignore_index=True,
        )
    return result


def comparison_rows(
    projection: pd.DataFrame,
    marked: Mapping[str, pd.DataFrame],
    official: Mapping[str, pd.DataFrame],
    equity_by_kind: Mapping[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    keys = projection[["portfolio_kind", "scenario"]].drop_duplicates().to_dict("records")
    for key in keys:
        kind = str(key["portfolio_kind"])
        scenario = str(key["scenario"])
        advisory = projection.loc[
            projection["portfolio_kind"].eq(kind) & projection["scenario"].eq(scenario),
            ["ticker", "advisory_weight"],
        ].copy()
        marked_frame = marked[kind].rename(columns={"weight": "marked_weight"})
        official_frame = official[kind].rename(columns={"weight": "official_prior_weight"})
        merged = marked_frame.merge(official_frame, on="ticker", how="outer")
        merged = merged.merge(advisory, on="ticker", how="outer").fillna(0.0)
        for column in ("marked_weight", "official_prior_weight", "advisory_weight"):
            merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)
        merged["delta_vs_marked"] = merged["advisory_weight"] - merged["marked_weight"]
        merged["delta_vs_official"] = merged["advisory_weight"] - merged["official_prior_weight"]
        merged["action_vs_marked"] = np.where(
            merged["delta_vs_marked"].gt(1e-12),
            "BUY",
            np.where(merged["delta_vs_marked"].lt(-1e-12), "SELL", "HOLD"),
        )
        merged["action_vs_official"] = np.where(
            merged["delta_vs_official"].gt(1e-12),
            "BUY",
            np.where(merged["delta_vs_official"].lt(-1e-12), "SELL", "HOLD"),
        )
        merged["portfolio_kind"] = kind
        merged["scenario"] = scenario
        merged["estimated_trade_notional_usd_vs_marked"] = (
            merged["delta_vs_marked"].abs() * float(equity_by_kind[kind])
        )
        merged["execution_allowed"] = False
        detail_rows.extend(merged.to_dict("records"))

        assets = merged["ticker"].ne("CASH")
        asset_abs = float(merged.loc[assets, "delta_vs_marked"].abs().sum())
        one_way = 0.5 * float(merged["delta_vs_marked"].abs().sum())
        official_one_way = 0.5 * float(merged["delta_vs_official"].abs().sum())
        advisory_assets = merged.loc[assets, "advisory_weight"].sort_values(ascending=False)
        row = {
            "portfolio_kind": kind,
            "scenario": scenario,
            "marked_cash_weight": float(merged.loc[~assets, "marked_weight"].sum()),
            "official_prior_cash_weight": float(
                merged.loc[~assets, "official_prior_weight"].sum()
            ),
            "advisory_cash_weight": float(merged.loc[~assets, "advisory_weight"].sum()),
            "cash_delta_vs_marked": float(merged.loc[~assets, "delta_vs_marked"].sum()),
            "one_way_turnover_vs_marked": one_way,
            "one_way_turnover_vs_official": official_one_way,
            "asset_absolute_trade_weight": asset_abs,
            "estimated_asset_trade_notional_usd": asset_abs * float(equity_by_kind[kind]),
            "buy_count_vs_marked": int((assets & merged["action_vs_marked"].eq("BUY")).sum()),
            "sell_count_vs_marked": int((assets & merged["action_vs_marked"].eq("SELL")).sum()),
            "unchanged_count_vs_marked": int((assets & merged["action_vs_marked"].eq("HOLD")).sum()),
            "selected_stock_count": int((assets & merged["advisory_weight"].gt(1e-12)).sum()),
            "top1_weight": float(advisory_assets.head(1).sum()),
            "top3_weight": float(advisory_assets.head(3).sum()),
            "stock_weight_hhi": float(np.square(advisory_assets.to_numpy(dtype=float)).sum()),
            "execution_allowed": False,
        }
        for bps in (25, 50, 100):
            row[f"estimated_cost_drag_fraction_{bps}bps"] = asset_abs * bps / 10000.0
            row[f"estimated_cost_usd_{bps}bps"] = (
                asset_abs * float(equity_by_kind[kind]) * bps / 10000.0
            )
        summary_rows.append(row)
    return pd.DataFrame(detail_rows), pd.DataFrame(summary_rows)


def attach_holding_risk_diagnostics(
    comparison: pd.DataFrame,
    scenario_cost: pd.DataFrame,
    holding_watch: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    risk = holding_watch[
        ["portfolio_kind", "ticker", "risk_state", "advisory_action", "reason_codes"]
    ].copy()
    risk["ticker"] = clean_tickers(risk["ticker"])
    if risk.duplicated(["portfolio_kind", "ticker"]).any():
        raise ValueError("duplicate holding-risk rows")
    risk = risk.rename(
        columns={
            "risk_state": "held_risk_state",
            "advisory_action": "held_risk_advisory_action",
            "reason_codes": "held_risk_reason_codes",
        }
    )
    detail = comparison.merge(
        risk, on=["portfolio_kind", "ticker"], how="left", validate="many_to_one"
    )
    summaries = scenario_cost.copy()
    for index, row in summaries.iterrows():
        group = detail.loc[
            detail["portfolio_kind"].eq(row["portfolio_kind"])
            & detail["scenario"].eq(row["scenario"])
            & detail["ticker"].ne("CASH")
        ]
        buys = group["delta_vs_marked"].gt(1e-12)
        held_risk = group["held_risk_state"].isin({"ALERT", "WATCH"})
        freeze = group["held_risk_advisory_action"].fillna("").str.contains(
            "FREEZE_INCREMENTAL_BUY", regex=False
        )
        new_unassessed = (
            group["marked_weight"].le(1e-12)
            & group["advisory_weight"].gt(1e-12)
            & group["held_risk_state"].isna()
        )
        summaries.loc[index, "incremental_buy_risk_review_conflict_count"] = int(
            (buys & held_risk).sum()
        )
        summaries.loc[index, "incremental_buy_freeze_conflict_count"] = int(
            (buys & freeze).sum()
        )
        summaries.loc[index, "proposed_new_entry_without_risk_watch_count"] = int(
            new_unassessed.sum()
        )
        summaries.loc[index, "risk_watch_promotion_allowed"] = False
    return detail, summaries


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "decision_manifest": repo_path(args.decision_manifest),
        "score_stack_manifest": repo_path(args.score_stack_manifest),
        "crisis_manifest": repo_path(args.crisis_manifest),
        "price_manifest": repo_path(args.price_manifest),
        "macro_manifest": repo_path(args.macro_manifest),
        "soxx_manifest": repo_path(args.soxx_manifest),
        "selector_contract_manifest": repo_path(args.selector_contract_manifest),
        "pinned_import_manifest": repo_path(args.pinned_import_manifest),
        "target_generation_manifest": repo_path(args.target_generation_manifest),
        "main_prior_book": repo_path(args.main_prior_book),
        "concentrated_prior_book": repo_path(args.concentrated_prior_book),
        "holding_watch_summary": repo_path(args.holding_watch_summary),
        "holding_watch_csv": repo_path(args.holding_watch_csv),
    }
    expected = {
        "decision_manifest": args.expected_decision_sha256,
        "score_stack_manifest": args.expected_score_stack_sha256,
        "crisis_manifest": args.expected_crisis_sha256,
        "price_manifest": args.expected_price_sha256,
        "macro_manifest": args.expected_macro_sha256,
        "soxx_manifest": args.expected_soxx_sha256,
        "selector_contract_manifest": args.expected_selector_contract_sha256,
        "pinned_import_manifest": args.expected_pinned_import_sha256,
        "target_generation_manifest": args.expected_target_generation_sha256,
        "main_prior_book": args.expected_main_prior_book_sha256,
        "concentrated_prior_book": args.expected_concentrated_prior_book_sha256,
        "holding_watch_summary": args.expected_holding_watch_summary_sha256,
        "holding_watch_csv": args.expected_holding_watch_csv_sha256,
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
        key: load_json(paths[key])
        for key in (
            "decision_manifest",
            "score_stack_manifest",
            "crisis_manifest",
            "price_manifest",
            "macro_manifest",
            "soxx_manifest",
            "selector_contract_manifest",
            "pinned_import_manifest",
            "target_generation_manifest",
            "holding_watch_summary",
        )
    }
    required_statuses = {
        "decision_manifest": "READY_COMPLETE_CURRENT_DECISION_FRAME",
        "score_stack_manifest": "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
        "crisis_manifest": "READY_CURRENT_CRISIS_STATE_NONSELECTING",
        "price_manifest": "READY_RESEARCH_SCORED_LATEST",
        "macro_manifest": "READY_CONSERVATIVE_MACRO_SIDECAR",
        "soxx_manifest": "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING",
        "selector_contract_manifest": "READY_CURRENT_SELECTOR_CONTRACT_AUDIT_NONSELECTING",
        "pinned_import_manifest": "READY_PINNED_POLICY_IMPORT_NONSELECTING",
        "holding_watch_summary": "READY_REVIEW_ONLY",
    }
    for name, required in required_statuses.items():
        actual = manifests[name].get("status")
        if actual != required:
            failures.append(f"status:{name}:{actual}!={required}")
    pinned_commit = str(manifests["pinned_import_manifest"].get("pinned_source_commit") or "")
    if pinned_commit != args.expected_policy_commit:
        failures.append(f"pinned_commit:{pinned_commit}!={args.expected_policy_commit}")
    if manifests["target_generation_manifest"].get("code", {}).get("github_sha") != pinned_commit:
        failures.append("target_generation_policy_commit_mismatch")
    valuation = pd.Timestamp(args.valuation_date).normalize()

    try:
        context_path, audits["selection_context"] = verified_output(
            paths["decision_manifest"], manifests["decision_manifest"], "selection_context"
        )
        stack_path, audits["ticker_order_score_stack"] = verified_output(
            paths["score_stack_manifest"], manifests["score_stack_manifest"], "ticker_order_score_stack"
        )
        crisis_path, audits["current_crisis_state"] = verified_output(
            paths["crisis_manifest"], manifests["crisis_manifest"], "current_crisis_state"
        )
        provider_path, audits["provider_price_overlap"] = verified_output(
            paths["price_manifest"], manifests["price_manifest"], "provider_price_overlap.parquet"
        )
        current_scored_path, audits["current_scored_latest"] = verified_output(
            paths["price_manifest"], manifests["price_manifest"], "scored_latest.csv"
        )
        soxx_path, audits["soxx_price_file"] = verified_output(
            paths["soxx_manifest"], manifests["soxx_manifest"], "price_file"
        )
    except Exception as exc:
        failures.append(f"manifest_output:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, audits, started)

    holding_summary = manifests["holding_watch_summary"]
    if sha256(paths["holding_watch_csv"]) != str(
        (holding_summary.get("output_hashes") or {}).get("holding_risk_watch_sha256") or ""
    ):
        failures.append("holding_watch_summary_output_hash_mismatch")
    if str(holding_summary.get("as_of_date") or "") != args.valuation_date:
        failures.append("holding_watch_not_current")

    date_contract = {
        "decision_manifest": ("valuation_price_cutoff_date", args.valuation_date),
        "score_stack_manifest": ("valuation_price_cutoff_date", args.valuation_date),
        "crisis_manifest": ("valuation_price_cutoff_date", args.valuation_date),
        "price_manifest": ("session_date", args.valuation_date),
        "macro_manifest": ("valuation_close_date", args.valuation_date),
        "soxx_manifest": ("valuation_price_cutoff_date", args.valuation_date),
    }
    for name, (field, expected_date) in date_contract.items():
        if str(manifests[name].get(field) or "") != expected_date:
            failures.append(f"date:{name}:{field}")
    feature_available = pd.to_datetime(
        manifests["decision_manifest"].get("feature_available_from"),
        errors="coerce",
        utc=True,
    )
    decision_time = pd.to_datetime(
        manifests["decision_manifest"].get("decision_time_utc"),
        errors="coerce",
        utc=True,
    )
    holding_available = pd.to_datetime(
        holding_summary.get("available_from"), errors="coerce", utc=True
    )
    if pd.isna(feature_available) or pd.isna(decision_time):
        failures.append("decision_timestamp_invalid")
    elif feature_available > decision_time:
        failures.append("future_feature_available_from")
    if pd.isna(holding_available):
        failures.append("holding_available_from_invalid")
    elif holding_available > pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=5):
        failures.append("holding_available_from_future")
    price_manifest = manifests["price_manifest"]
    if price_manifest.get("schema_version") != CURRENT_SCORE_SCHEMA_VERSION:
        failures.append("price_manifest_schema")
    price_coverage = price_manifest.get("coverage") or {}
    try:
        pre_lifecycle_rows = int(
            price_coverage.get("pre_lifecycle_context_count")
        )
        expected_core_rows = int(
            price_coverage.get("post_lifecycle_context_count")
        )
        lifecycle_excluded_rows = int(
            price_coverage.get("lifecycle_excluded_count")
        )
        current_context_rows = int(price_coverage.get("current_context_count"))
        exact_close_rows = int(price_coverage.get("exact_session_close_count"))
    except (TypeError, ValueError):
        pre_lifecycle_rows = 0
        expected_core_rows = 0
        lifecycle_excluded_rows = 0
        current_context_rows = 0
        exact_close_rows = 0
        failures.append("core_candidate_expected_row_count_invalid")
    if pre_lifecycle_rows != expected_core_rows + lifecycle_excluded_rows:
        failures.append("core_candidate_lifecycle_count_reconciliation")
    if current_context_rows != expected_core_rows:
        failures.append("core_candidate_current_context_count_mismatch")
    if exact_close_rows != expected_core_rows:
        failures.append("core_candidate_exact_close_count_mismatch")
    recomputed_core_coverage, core_coverage_failures = (
        core_candidate_coverage_for_path(
            current_scored_path,
            minimum_ratio=0.98,
            expected_row_count=expected_core_rows,
            expected_valuation_date=args.valuation_date,
            decision_time_utc=(
                pd.Timestamp(decision_time).isoformat()
                if pd.notna(decision_time)
                else ""
            ),
            expected_ticker_set_sha256=str(
                (price_manifest.get("core_candidate_coverage") or {}).get(
                    "expected_ticker_set_sha256"
                )
                or ""
            ),
        )
    )
    declared_core_coverage = price_manifest.get("core_candidate_coverage") or {}
    declared_expected_ticker_hash = str(
        declared_core_coverage.get("expected_ticker_set_sha256") or ""
    ).lower()
    if (
        declared_core_coverage.get("schema_version")
        != "run287-core-candidate-coverage-v1"
    ):
        failures.append("core_candidate_coverage_schema")
    if (
        len(declared_expected_ticker_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in declared_expected_ticker_hash
        )
        or declared_core_coverage.get("ticker_set_matches_expected") is not True
        or str(declared_core_coverage.get("ticker_set_sha256") or "").lower()
        != declared_expected_ticker_hash
    ):
        failures.append("core_candidate_expected_ticker_set_contract")
    declared_core_semantic = core_candidate_coverage_semantic_view(
        declared_core_coverage
    )
    recomputed_core_semantic = core_candidate_coverage_semantic_view(
        recomputed_core_coverage
    )
    if declared_core_semantic != recomputed_core_semantic:
        failures.append("core_candidate_coverage_manifest_mismatch")
    failures.extend(
        f"core_candidate_coverage:{item}" for item in core_coverage_failures
    )
    if declared_core_coverage.get("passed") is not True:
        failures.append("core_candidate_coverage_not_passed")
    score_available = pd.to_datetime(
        price_manifest.get("score_available_from"), errors="coerce", utc=True
    )
    if pd.isna(score_available):
        failures.append("score_available_from_invalid")
    elif pd.notna(decision_time) and score_available < decision_time:
        failures.append("score_available_before_decision_cutoff")
    elif score_available > pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=5):
        failures.append("score_available_from_future")
    audits["core_candidate_coverage"] = {
        "declared": declared_core_coverage,
        "recomputed": recomputed_core_coverage,
        "passed": not core_coverage_failures
        and declared_core_semantic == recomputed_core_semantic,
    }
    selector_times = [
        value
        for value in (decision_time, holding_available, score_available)
        if pd.notna(value)
    ]
    if not selector_times:
        failures.append("selector_decision_time_unavailable")
        selector_decision_time = pd.Timestamp(
            f"{args.valuation_date}T23:59:59Z"
        )
    else:
        selector_decision_time = max(selector_times)
    timestamp_contract = {
        "signal_source_date": args.valuation_date,
        "feature_as_of_date": args.valuation_date,
        "valuation_close_date": args.valuation_date,
        "selector_decision_time_utc": selector_decision_time.isoformat(),
        "target_effective_date": args.valuation_date,
        "order_eligible_close_date": next_nyse_session(args.valuation_date),
        "same_close_selector_recomputed": True,
    }

    context = pd.read_parquet(context_path)
    stack = pd.read_csv(stack_path, low_memory=False)
    candidate = merge_stack_precedence(context, stack)
    candidate["rebalance_date"] = valuation
    candidate["ticker"] = clean_tickers(candidate["ticker"])
    candidate_ticker_set_sha256 = core_candidate_ticker_set_sha256(
        candidate["ticker"].tolist()
    )
    if expected_core_rows != int(args.expected_context_count):
        failures.append("core_candidate_decision_context_count_mismatch")
    if candidate_ticker_set_sha256 != str(
        recomputed_core_coverage.get("ticker_set_sha256") or ""
    ):
        failures.append("core_candidate_decision_ticker_set_mismatch")
    audits["core_candidate_coverage"]["decision_context_ticker_set_sha256"] = (
        candidate_ticker_set_sha256
    )
    forbidden = sorted(FORBIDDEN_COLUMNS & set(candidate.columns))
    if forbidden:
        failures.append(f"forbidden_future_columns:{','.join(forbidden)}")
    registered_mask = candidate["registered_ranking_eligible"].fillna(False).astype(bool)
    registered = set(candidate.loc[registered_mask, "ticker"])
    if len(candidate) != args.expected_context_count:
        failures.append(f"context_count:{len(candidate)}!={args.expected_context_count}")
    if len(registered) != args.expected_eligible_count:
        failures.append(f"eligible_count:{len(registered)}!={args.expected_eligible_count}")
    if "DD" in registered:
        failures.append("quarantined_dd_in_registered_set")
    if failures:
        return blocked(output_dir, failures, audits, started)

    main_book = pd.read_csv(paths["main_prior_book"], low_memory=False)
    concentrated_book = pd.read_csv(paths["concentrated_prior_book"], low_memory=False)
    official_prior = {
        "main": latest_official_weight_frame(main_book),
        "concentrated": latest_official_weight_frame(concentrated_book),
    }
    policy_prior = {
        "main": current_prior_book(main_book),
        "concentrated": current_prior_book(concentrated_book),
    }
    prior_ineligible = {
        ticker
        for frame in policy_prior.values()
        for ticker in set(frame["ticker"])
        if ticker not in registered
    }
    crisis_states = pd.read_csv(crisis_path, low_memory=False)
    holding_watch = pd.read_csv(paths["holding_watch_csv"], low_memory=False)
    try:
        marked = marked_weight_frames(holding_watch, holding_summary, valuation)
    except Exception as exc:
        failures.append(f"marked_weights:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, audits, started)

    environment = manifests["target_generation_manifest"].get("env") or {}
    macro_cache = repo_path(args.macro_price_cache)
    soxx_cache = soxx_path.parent
    provider = pd.read_parquet(provider_path)
    provider_ticker_count = int(provider["ticker"].astype(str).str.upper().nunique())
    provider_max = pd.to_datetime(provider["Date"], errors="coerce").max()
    if provider_ticker_count != args.expected_context_count:
        failures.append(
            f"provider_ticker_count:{provider_ticker_count}!={args.expected_context_count}"
        )
    if pd.Timestamp(provider_max).normalize() != valuation:
        failures.append("provider_prices_not_current")
    if failures:
        return blocked(output_dir, failures, audits, started)

    projections_a: list[pd.DataFrame] = []
    projections_b: list[pd.DataFrame] = []
    transitions: list[pd.DataFrame] = []
    rejections: list[pd.DataFrame] = []
    telemetry_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    pit_rows: list[pd.DataFrame] = []
    benchmark_rows: list[dict[str, Any]] = []
    runtime_modules = pd.DataFrame()
    try:
        with exact_environment(environment):
            with pinned_import_context(pinned_commit, REPO_ROOT) as loader:
                policy = importlib.import_module("tools.run_alphaops_vnext_policy_replay")
                prices = normalized_provider_prices(provider)
                for ticker in policy.BENCHMARKS:
                    cache = soxx_cache if ticker == "SOXX" else macro_cache
                    frame = policy.load_price_series(cache, ticker)
                    if frame.empty:
                        raise ValueError(f"missing benchmark price: {ticker}")
                    latest = pd.Timestamp(frame.index.max()).normalize()
                    if latest != valuation:
                        raise ValueError(f"benchmark not current: {ticker}:{latest.date()}")
                    prices[ticker] = frame
                    benchmark_rows.append(
                        {
                            "ticker": ticker,
                            "row_count": int(len(frame)),
                            "date_min": pd.Timestamp(frame.index.min()).date().isoformat(),
                            "date_max": latest.date().isoformat(),
                            "source_cache": str(cache),
                        }
                    )
                candidate_pit, pit_audit = policy.enforce_pit_available(candidate)
                if not pit_audit.empty:
                    pit_rows.append(pit_audit)
                candidate_rs = enrich_relative_strength_from_map(policy, candidate_pit, prices)
                eligible_frame = candidate_rs[candidate_rs["ticker"].isin(registered)].copy()
                bridge_frame = candidate_rs[
                    candidate_rs["ticker"].isin(registered | prior_ineligible)
                ].copy()
                for kind, scenario, target_n, bridge in SCENARIOS:
                    month = bridge_frame if bridge else eligible_frame
                    projection_a, transition, rejection, telemetry = run_core_selector(
                        policy,
                        month_input=month,
                        prior_book=policy_prior[kind],
                        portfolio_kind=kind,
                        scenario=scenario,
                        target_n=target_n,
                        crisis_states=crisis_states,
                        prices=prices,
                        registered_eligible=registered,
                        apply_postbook=True,
                        stage_audit_sink=stage_rows,
                    )
                    projection_b, _t, _r, _m = run_core_selector(
                        policy,
                        month_input=month,
                        prior_book=policy_prior[kind],
                        portfolio_kind=kind,
                        scenario=scenario,
                        target_n=target_n,
                        crisis_states=crisis_states,
                        prices=prices,
                        registered_eligible=registered,
                        apply_postbook=True,
                    )
                    projections_a.append(projection_a)
                    projections_b.append(projection_b)
                    transitions.append(transition)
                    rejections.append(rejection)
                    telemetry_rows.append(telemetry)
                runtime_modules = pd.DataFrame(loader.loaded)
    except Exception as exc:
        failures.append(f"pinned_selector_runtime:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, audits, started, selector_executed=True)

    projection = pd.concat(projections_a, ignore_index=True)
    repeat = pd.concat(projections_b, ignore_index=True)
    deterministic = deterministic_projection(projection, repeat)
    if not deterministic:
        failures.append("advisory_projection_nondeterministic")
    totals = projection.groupby(["scenario", "portfolio_kind"])["advisory_weight"].sum()
    if not bool(np.isclose(totals.to_numpy(dtype=float), 1.0, atol=1e-9).all()):
        failures.append("advisory_weight_conservation_failure")
    invalid_new = projection.loc[
        projection["ticker"].ne("CASH")
        & ~projection["registered_eligible"]
        & ~projection["prior_holding"]
    ]
    if not invalid_new.empty:
        failures.append(f"ineligible_new_entry_count:{len(invalid_new)}")
    if projection["ticker"].eq("DD").any():
        failures.append("quarantined_dd_selected")
    if failures:
        return blocked(output_dir, failures, audits, started, selector_executed=True)

    equity_by_kind = {
        kind: float(row.get("estimated_current_equity_usd") or 0.0)
        for kind, row in (holding_summary.get("portfolio_summaries") or {}).items()
    }
    comparison, scenario_cost = comparison_rows(
        projection, marked, official_prior, equity_by_kind
    )
    try:
        comparison, scenario_cost = attach_holding_risk_diagnostics(
            comparison, scenario_cost, holding_watch
        )
    except Exception as exc:
        failures.append(f"holding_risk_diagnostics:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, audits, started, selector_executed=True)
    projection = projection.sort_values(
        ["portfolio_kind", "scenario", "advisory_weight"],
        ascending=[True, True, False],
    ).reset_index(drop=True)
    for field, value in timestamp_contract.items():
        projection[field] = value
    transition = pd.concat(transitions, ignore_index=True)
    rejection = pd.concat(rejections, ignore_index=True)
    telemetry = pd.DataFrame(telemetry_rows)
    stage_audit = pd.DataFrame(stage_rows)
    pit_audit = pd.concat(pit_rows, ignore_index=True) if pit_rows else pd.DataFrame()
    failures.extend(changed_input_failures(audits))
    if failures:
        return blocked(
            output_dir,
            sorted(set(failures)),
            audits,
            started,
            selector_executed=True,
        )
    outputs = {
        "advisory_policy_projection": projection,
        "advisory_transition_audit": transition,
        "advisory_rejection_audit": rejection,
        "advisory_scenario_summary": telemetry,
        "advisory_policy_stage_audit": stage_audit,
        "marked_official_advisory_comparison": comparison,
        "turnover_cost_summary": scenario_cost,
        "benchmark_price_audit": pd.DataFrame(benchmark_rows),
        "pit_evidence_audit": pit_audit,
        "pinned_selector_runtime_module_audit": runtime_modules,
    }
    output_records: dict[str, Any] = {}
    for name, frame in outputs.items():
        path = output_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        output_records[name] = fingerprint(path)

    def summary_value(key: str, value: Any) -> Any:
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if key.endswith("_count"):
            return int(value)
        return float(value)

    scenario_summary = {
        f"{row['portfolio_kind']}:{row['scenario']}": {
            key: summary_value(key, value)
            for key, value in row.items()
            if key not in {"portfolio_kind", "scenario", "execution_allowed"}
        }
        for row in scenario_cost.to_dict("records")
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "selector_no_write_passed": True,
        "contract_failures": [],
        "valuation_price_cutoff_date": args.valuation_date,
        "timestamp_contract": timestamp_contract,
        "same_close_selector_recomputed": True,
        "decision_basis": "latest completed US trading close",
        "pinned_policy_commit": pinned_commit,
        "registered_new_entry_pool_count": int(len(registered)),
        "prior_ineligible_count": int(len(prior_ineligible)),
        "prior_ineligible_tickers": sorted(prior_ineligible),
        "scenario_summary": scenario_summary,
        "determinism": {"projection_rerun_match": deterministic, "tolerance": 1e-12},
        "comparison_contract": {
            "selector_prior_semantics": "official frozen target book latest rebalance",
            "turnover_baseline": "2026-07-13 exact-close marked account weights",
            "cash_included_in_one_way_turnover": True,
            "cash_excluded_from_fee_estimate": True,
            "fee_sensitivities_bps_per_asset_transaction": [25, 50, 100],
            "holding_risk_watch_is_advisory_not_a_weight_override": True,
            "incremental_buy_conflicts_are_reported_not_executed": True,
        },
        "review_gate": {
            "portfolio_transition_promotion_allowed": False,
            "reason": "single-date turnover is material and proposed buys require holding-risk conflict or new-entry risk review",
        },
        "interpretation_limits": {
            "historical_cagr_mdd_evidence_changed": False,
            "cagr_mdd_improvement_claim_allowed": False,
            "single_current_date_only": True,
            "history_dependent_churn_interpretation": "diagnostic_no_prior_policy_sequence",
        },
        "research_only": True,
        "advisory_only": True,
        "execution_allowed": False,
        "score_sort_executed": True,
        "top_n_executed": True,
        "selector_executed": True,
        "position_sizing_executed": True,
        "target_book_generation_allowed": False,
        "target_book_file_written": False,
        "target_books_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "source_inputs": dict(audits),
        "outputs": output_records,
        "recommended_next_step": "review strict versus Main prior-hold bridge turnover, cost, cash, and replacement reasons; do not mutate books without a separate approval gate",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    artifact = Path(
        r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact"
    )
    alphaops = artifact / "outputs/alphaops_vnext"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-manifest", required=True)
    parser.add_argument("--expected-decision-sha256", required=True)
    parser.add_argument("--score-stack-manifest", required=True)
    parser.add_argument("--expected-score-stack-sha256", required=True)
    parser.add_argument("--crisis-manifest", required=True)
    parser.add_argument("--expected-crisis-sha256", required=True)
    parser.add_argument("--price-manifest", required=True)
    parser.add_argument("--expected-price-sha256", required=True)
    parser.add_argument("--macro-manifest", required=True)
    parser.add_argument("--expected-macro-sha256", required=True)
    parser.add_argument("--soxx-manifest", required=True)
    parser.add_argument("--expected-soxx-sha256", required=True)
    parser.add_argument(
        "--selector-contract-manifest",
        default="outputs/run287_current_selector_contract_audit_20260712_commit_0d07efea/manifest.json",
    )
    parser.add_argument(
        "--expected-selector-contract-sha256",
        default="647475ceaf2109d7dc7c7dfd18865679de86dc5afd102a090481e118bab4a02f",
    )
    parser.add_argument(
        "--pinned-import-manifest",
        default="outputs/run287_pinned_policy_import_audit_20260712_commit_e871541c/manifest.json",
    )
    parser.add_argument(
        "--expected-pinned-import-sha256",
        default="b59db75e6eea74989fd72946cb3b72af65a401dddb5738970ddd2b3d4febab6d",
    )
    parser.add_argument(
        "--target-generation-manifest",
        default=str(alphaops / "target_generation_input_manifest.json"),
    )
    parser.add_argument(
        "--expected-target-generation-sha256",
        default="7451166d8132c7e3fbd3eb75f7ecdd095e86e482b9202c2e0e0a2b1189ba6ff7",
    )
    parser.add_argument("--main-prior-book", default=str(alphaops / "official_main_target_book.csv"))
    parser.add_argument(
        "--expected-main-prior-book-sha256",
        default="3e863068e118af3f832b9490defc38baa9f4b0718e024e2870f44bd27a979f22",
    )
    parser.add_argument(
        "--concentrated-prior-book",
        default=str(alphaops / "official_concentrated_target_book.csv"),
    )
    parser.add_argument(
        "--expected-concentrated-prior-book-sha256",
        default="3fa0f6fa0aa41aa3ec830f476dae5e94882527a7f520531b80390bfbddb26a78",
    )
    parser.add_argument("--holding-watch-summary", required=True)
    parser.add_argument("--expected-holding-watch-summary-sha256", required=True)
    parser.add_argument("--holding-watch-csv", required=True)
    parser.add_argument("--expected-holding-watch-csv-sha256", required=True)
    parser.add_argument("--macro-price-cache", required=True)
    parser.add_argument("--expected-policy-commit", default=POLICY_COMMIT)
    parser.add_argument("--valuation-date", default="2026-07-13")
    parser.add_argument("--expected-context-count", type=int, default=989)
    parser.add_argument("--expected-eligible-count", type=int, default=347)
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_current_selector_no_write_20260714_close_20260713",
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "selector_no_write_passed": payload.get("selector_no_write_passed"),
                "scenario_summary": payload.get("scenario_summary", {}),
                "target_book_file_written": payload.get("target_book_file_written"),
                "orders_generated": payload.get("orders_generated"),
            },
            sort_keys=True,
        )
    )
    return 0 if payload.get("selector_no_write_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
