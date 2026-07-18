#!/usr/bin/env python3
"""Build the append-only Run287 decision/outcome causal ledger.

The producer joins already-created research artifacts.  It does not score,
rank, select, trade, mutate a target book, or dispatch a backtest/fullrun.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(REPO_ROOT))

from tools.run_free_data_forward_paper_ledger import (  # noqa: E402
    _max_drawdown,
    load_cached_prices,
    load_nyse_sessions,
)


SCHEMA_VERSION = "run287-decision-outcome-ledger-v1"
DECISION_LOG = "decision_events.jsonl"
OUTCOME_LOG = "outcome_events.jsonl"
READY_STATUS = "READY_RUN287_DECISION_OUTCOME_LEDGER_REVIEW_ONLY"
BLOCKED_STATUS = "BLOCKED_RUN287_DECISION_OUTCOME_LEDGER"
HEAD_COLUMNS = (
    "pred_lin_ret",
    "pred_lin_p",
    "pred_future_winner_ret",
    "pred_future_winner_p",
    "pred_cat_ret",
    "pred_cat_p",
)
FALSE_SAFETY_FLAGS = (
    "target_books_mutated",
    "target_book_file_written",
    "orders_generated",
    "backtest_executed",
    "fullrun_executed",
    "production_activation_allowed",
    "live_trading_enabled",
    "execution_allowed",
)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if pd.notna(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def clean_text(value: Any) -> str:
    scalar = json_scalar(value)
    if scalar is None:
        return ""
    text = str(scalar).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def normalize_ticker(value: Any) -> str:
    text = clean_text(value).upper()
    return "" if text in {"", "CASH", "__CASH__"} else text


def truthy(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return clean_text(value).lower() in {"1", "true", "yes", "y"}


def finite(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        event_id = clean_text(row.get("event_id"))
        if not event_id or event_id in seen:
            raise ValueError(f"invalid or duplicate event_id at {path}:{line_number}")
        seen.add(event_id)
        rows.append(row)
    return rows


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    needs_newline = path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if needs_newline:
            handle.write("\n")
        for row in rows:
            handle.write(canonical_json(row) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path),
    }


def ensure_unique_tickers(frame: pd.DataFrame, label: str, expected: int, blockers: list[str]) -> pd.DataFrame:
    if "ticker" not in frame.columns:
        raise ValueError(f"ticker column missing: {label}")
    out = frame.copy()
    out["ticker"] = out["ticker"].map(normalize_ticker)
    duplicates = int(out["ticker"].duplicated(keep=False).sum())
    if duplicates:
        blockers.append(f"duplicate_ticker:{label}:{duplicates}")
    if out["ticker"].eq("").any():
        blockers.append(f"blank_ticker:{label}")
    if len(out) != expected:
        blockers.append(f"ticker_count:{label}:{len(out)}!={expected}")
    return out.set_index("ticker", drop=False).sort_index()


def safety_blockers(manifest: Mapping[str, Any], label: str) -> list[str]:
    failures: list[str] = []
    for flag in FALSE_SAFETY_FLAGS:
        if truthy(manifest.get(flag)):
            failures.append(f"unsafe_source_flag:{label}:{flag}")
    return failures


def load_operating_book(path: Path, decision_date: str) -> dict[str, float]:
    frame = pd.read_csv(path, usecols=["rebalance_date", "ticker", "weight"], low_memory=False)
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame = frame.loc[frame["rebalance_date"].eq(decision_date)].copy()
    if frame.empty:
        raise ValueError(f"operating book has no exact decision date {decision_date}: {path}")
    frame["ticker"] = frame["ticker"].map(normalize_ticker)
    frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce")
    if frame["ticker"].eq("").any() or frame["weight"].isna().any():
        raise ValueError(f"invalid operating rows: {path}")
    return frame.groupby("ticker")["weight"].sum().astype(float).to_dict()


def load_paper_state(root: Path, portfolio: str, decision_date: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    positions_path = root / portfolio / "positions_latest.csv"
    account_path = root / portfolio / "account_state_latest.json"
    positions = pd.read_csv(positions_path, low_memory=False)
    positions["as_of_date"] = pd.to_datetime(positions["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if not positions["as_of_date"].eq(decision_date).all():
        raise ValueError(f"paper positions are not exact-date {decision_date}: {positions_path}")
    positions["ticker"] = positions["ticker"].map(normalize_ticker)
    by_ticker = {row["ticker"]: {key: json_scalar(value) for key, value in row.items()} for row in positions.to_dict("records")}
    account = read_json(account_path)
    if clean_text(account.get("as_of_date")) != decision_date:
        raise ValueError(f"paper account is not exact-date {decision_date}: {account_path}")
    if not truthy(account.get("simulated_broker_ledger")) or truthy(account.get("live_trading_enabled")):
        raise ValueError(f"paper account safety contract failed: {account_path}")
    return by_ticker, account


def selector_maps(
    projection: pd.DataFrame,
    rejections: pd.DataFrame,
    stages: pd.DataFrame,
) -> tuple[list[tuple[str, str]], dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str, str], list[str]], dict[tuple[str, str, str], str]]:
    for frame in (projection, rejections, stages):
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
    scenarios = sorted(
        {
            (clean_text(row.portfolio_kind), clean_text(row.scenario))
            for frame in (projection, rejections, stages)
            for row in frame[["portfolio_kind", "scenario"]].drop_duplicates().itertuples(index=False)
        }
    )
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in projection.loc[projection["ticker"].ne("")].to_dict("records"):
        key = (clean_text(row.get("portfolio_kind")), clean_text(row.get("scenario")), normalize_ticker(row.get("ticker")))
        if key in selected:
            raise ValueError(f"duplicate selector projection: {key}")
        selected[key] = row
    rejected: dict[tuple[str, str, str], list[str]] = {}
    for row in rejections.to_dict("records"):
        key = (clean_text(row.get("portfolio_kind")), clean_text(row.get("scenario")), normalize_ticker(row.get("ticker")))
        reason = clean_text(row.get("rejection_reason"))
        if key[2] and reason:
            rejected.setdefault(key, []).append(reason)
    removed: dict[tuple[str, str, str], str] = {}
    if not stages.empty:
        work = stages.copy()
        work["stage_sequence"] = pd.to_numeric(work["stage_sequence"], errors="coerce").fillna(-1)
        work = work.loc[work["transition"].astype(str).str.lower().eq("removed")].sort_values("stage_sequence")
        for row in work.to_dict("records"):
            key = (clean_text(row.get("portfolio_kind")), clean_text(row.get("scenario")), normalize_ticker(row.get("ticker")))
            if key[2]:
                removed[key] = clean_text(row.get("stage_name")) or "unnamed_stage"
    return scenarios, selected, rejected, removed


def scenario_cash_map(summary: pd.DataFrame) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for row in summary.to_dict("records"):
        key = (clean_text(row.get("portfolio_kind")), clean_text(row.get("scenario")))
        value = finite(row.get("advisory_cash_weight"))
        if value is None:
            value = finite(row.get("cash_weight"))
        if value is not None:
            result[key] = value
    return result


def feature_snapshot(row: pd.Series, columns: Iterable[str]) -> dict[str, Any]:
    return {column: json_scalar(row.get(column)) for column in columns}


def propose_decisions(args: argparse.Namespace, contract: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    blockers: list[str] = []
    expected = int(contract.get("expected_universe_count", 989))
    feature_expected = int(contract.get("expected_model_feature_count", 238))
    decision_manifest_path = repo_path(args.decision_frame_manifest)
    score_manifest_path = repo_path(args.score_stack_manifest)
    scored_manifest_path = repo_path(args.scored_latest_manifest)
    selector_manifest_path = repo_path(args.selector_manifest)
    manifests = {
        "decision_frame": read_json(decision_manifest_path),
        "score_stack": read_json(score_manifest_path),
        "scored_latest": read_json(scored_manifest_path),
        "selector": read_json(selector_manifest_path),
    }
    for label, manifest in manifests.items():
        blockers.extend(safety_blockers(manifest, label))
    decision_date = args.decision_date or clean_text(manifests["decision_frame"].get("valuation_price_cutoff_date"))
    if not decision_date:
        raise ValueError("decision date is unavailable")
    decision_time = clean_text(manifests["decision_frame"].get("decision_time_utc"))
    context_path = repo_path(args.decision_context)
    scaled_path = repo_path(args.scaled_model_input)
    stack_path = repo_path(args.score_stack)
    scored_path = repo_path(args.scored_latest)
    projection_path = repo_path(args.selector_projection)
    rejection_path = repo_path(args.selector_rejections)
    stages_path = repo_path(args.selector_stages)
    scenario_path = repo_path(args.selector_scenarios)
    source_paths = {
        "contract": repo_path(args.contract),
        "decision_frame_manifest": decision_manifest_path,
        "decision_context": context_path,
        "scaled_model_input": scaled_path,
        "score_stack_manifest": score_manifest_path,
        "score_stack": stack_path,
        "adaptive_ensemble": repo_path(args.adaptive_ensemble),
        "scored_latest_manifest": scored_manifest_path,
        "scored_latest": scored_path,
        "selector_manifest": selector_manifest_path,
        "selector_projection": projection_path,
        "selector_rejections": rejection_path,
        "selector_stages": stages_path,
        "selector_scenarios": scenario_path,
        "operating_main": repo_path(args.operating_main),
        "operating_concentrated": repo_path(args.operating_concentrated),
        "paper_main_positions": repo_path(args.paper_root) / "main" / "positions_latest.csv",
        "paper_main_account": repo_path(args.paper_root) / "main" / "account_state_latest.json",
        "paper_concentrated_positions": repo_path(args.paper_root) / "concentrated" / "positions_latest.csv",
        "paper_concentrated_account": repo_path(args.paper_root) / "concentrated" / "account_state_latest.json",
    }
    missing_sources = [label for label, path in source_paths.items() if not path.is_file()]
    blockers.extend(f"source_missing:{label}" for label in missing_sources)
    if missing_sources:
        return [], {"blockers": blockers, "decision_date": decision_date, "source_inputs": {k: fingerprint(v) for k, v in source_paths.items()}}
    context = ensure_unique_tickers(pd.read_parquet(context_path), "decision_context", expected, blockers)
    scaled = ensure_unique_tickers(pd.read_parquet(scaled_path), "scaled_model_input", expected, blockers)
    stack = ensure_unique_tickers(pd.read_csv(stack_path, low_memory=False), "score_stack", expected, blockers)
    scored = ensure_unique_tickers(pd.read_csv(scored_path, low_memory=False), "scored_latest", expected, blockers)
    feature_columns = [column for column in scaled.columns if column != "ticker"]
    if len(feature_columns) != feature_expected:
        blockers.append(f"model_feature_count:{len(feature_columns)}!={feature_expected}")
    missing_context_features = sorted(set(feature_columns) - set(context.columns))
    if missing_context_features:
        blockers.append(f"raw_model_features_missing:{len(missing_context_features)}")
    for head in contract.get("prediction_heads", HEAD_COLUMNS):
        if head not in stack.columns or head not in scored.columns:
            blockers.append(f"prediction_head_missing:{head}")
    ticker_sets = {"context": set(context.index), "scaled": set(scaled.index), "stack": set(stack.index), "scored": set(scored.index)}
    if len({frozenset(values) for values in ticker_sets.values()}) != 1:
        blockers.append("ticker_set_mismatch_across_decision_inputs")
    future_rows = int((manifests["decision_frame"].get("coverage") or {}).get("future_feature_row_count", 0) or 0)
    if future_rows:
        blockers.append(f"future_feature_rows:{future_rows}")
    projection = pd.read_csv(projection_path, low_memory=False)
    rejections = pd.read_csv(rejection_path, low_memory=False)
    stages = pd.read_csv(stages_path, low_memory=False)
    scenario_summary = pd.read_csv(scenario_path, low_memory=False)
    scenarios, selected, rejected, removed = selector_maps(projection, rejections, stages)
    if not scenarios:
        blockers.append("selector_scenarios_missing")
    selector_cash = scenario_cash_map(scenario_summary)
    operating = {
        "main": load_operating_book(repo_path(args.operating_main), decision_date),
        "concentrated": load_operating_book(repo_path(args.operating_concentrated), decision_date),
    }
    paper: dict[str, dict[str, Any]] = {}
    accounts: dict[str, dict[str, Any]] = {}
    operating_share_mismatch_count = 0
    for portfolio in ("main", "concentrated"):
        paper[portfolio], accounts[portfolio] = load_paper_state(repo_path(args.paper_root), portfolio, decision_date)
        equity = float(accounts[portfolio].get("equity_usd") or 0.0)
        for ticker, target_weight in operating[portfolio].items():
            fill = paper[portfolio].get(ticker)
            price = finite((fill or {}).get("price"))
            observed_shares = finite((fill or {}).get("shares"))
            if fill is None or price is None or price <= 0 or observed_shares is None:
                operating_share_mismatch_count += 1
                blockers.append(f"operating_share_unverifiable:{portfolio}:{ticker}")
                continue
            expected_shares = math.floor((equity * float(target_weight)) / price + 1e-12)
            if abs(observed_shares - expected_shares) > 1e-9:
                operating_share_mismatch_count += 1
                blockers.append(
                    f"operating_share_mismatch:{portfolio}:{ticker}:{observed_shares}!={expected_shares}"
                )
        extra_fills = sorted(set(paper[portfolio]) - set(operating[portfolio]))
        if extra_fills:
            operating_share_mismatch_count += len(extra_fills)
            blockers.append(f"operating_share_extra_fill_count:{portfolio}:{len(extra_fills)}")
    exact_weights = pd.read_csv(repo_path(args.adaptive_ensemble), low_memory=False).iloc[0].to_dict()
    source_fingerprints = {label: fingerprint(path) for label, path in source_paths.items()}
    source_bundle_sha256 = canonical_hash({label: row["sha256"] for label, row in source_fingerprints.items()})
    missing_reason_count = 0
    decision_rows: list[dict[str, Any]] = []
    for portfolio, scenario in scenarios:
        if portfolio not in operating:
            blockers.append(f"unknown_portfolio:{portfolio}")
            continue
        account = accounts[portfolio]
        fill_weight_sum = sum(float(row.get("weight") or 0.0) for row in paper[portfolio].values())
        account_cash_weight = float(account.get("cash_weight") or 0.0)
        account_equity = float(account.get("equity_usd") or 0.0)
        account_cash_error_usd = abs((fill_weight_sum + account_cash_weight - 1.0) * account_equity)
        if account_cash_error_usd > float((contract.get("decision_gates") or {}).get("cash_reconciliation_tolerance_usd", 0.01)):
            blockers.append(f"paper_cash_reconciliation:{portfolio}:{account_cash_error_usd:.6f}")
        for ticker in context.index:
            key = (portfolio, scenario, ticker)
            context_row = context.loc[ticker]
            scaled_row = scaled.loc[ticker]
            stack_row = stack.loc[ticker]
            scored_row = scored.loc[ticker]
            projection_row = selected.get(key)
            rejection_reasons = sorted(set(rejected.get(key, [])))
            stage_removed = removed.get(key, "")
            registered_eligible = truthy(stack_row.get("registered_ranking_eligible"))
            is_selected = projection_row is not None and float(finite(projection_row.get("advisory_weight"), 0.0) or 0.0) > 0
            reason_source = ""
            reason_code = ""
            if is_selected:
                reason_source = "selected_projection"
                reason_code = "SELECTED:" + (clean_text(projection_row.get("selection_reason")) or "selector_projection")
            elif rejection_reasons:
                reason_source = "explicit_rejection_audit"
                reason_code = "REJECTED:" + "|".join(rejection_reasons)
            elif stage_removed:
                reason_source = "terminal_removed_stage"
                reason_code = "REJECTED_STAGE_REMOVED:" + stage_removed
            elif not registered_eligible:
                reason_source = "registered_model_ineligible"
                reason_code = "REJECTED_REGISTERED_INELIGIBLE:" + (
                    clean_text(stack_row.get("portfolio_candidate_gate_label")) or "model_gate"
                )
            else:
                reason_source = "missing"
                reason_code = "MISSING_SELECTOR_REASON_REVIEW_REQUIRED"
                missing_reason_count += 1
            raw_features = feature_snapshot(context_row, feature_columns)
            scaled_features = feature_snapshot(scaled_row, feature_columns)
            raw_finite = sum(value is not None for value in raw_features.values())
            fill = paper[portfolio].get(ticker, {})
            advisory_weight = float(finite((projection_row or {}).get("advisory_weight"), 0.0) or 0.0)
            prior_weight = float(finite((projection_row or {}).get("prior_weight"), 0.0) or 0.0)
            operating_weight = float(operating[portfolio].get(ticker, 0.0))
            fill_weight = float(finite(fill.get("weight"), 0.0) or 0.0)
            selector_score = finite((projection_row or {}).get("alphaops_vnext_score"))
            if selector_score is None:
                matching_rejections = rejections.loc[
                    rejections["portfolio_kind"].astype(str).eq(portfolio)
                    & rejections["scenario"].astype(str).eq(scenario)
                    & rejections["ticker"].eq(ticker)
                ]
                selector_score = finite(matching_rejections["candidate_score"].dropna().iloc[-1]) if not matching_rejections["candidate_score"].dropna().empty else None
            snapshot: dict[str, Any] = {
                "decision_date": decision_date,
                "decision_time_utc": decision_time,
                "ticker": ticker,
                "portfolio_kind": portfolio,
                "scenario": scenario,
                "sector": clean_text(context_row.get("sector")),
                "industry": clean_text(context_row.get("industry")),
                "mktcap": finite(context_row.get("mktcap")),
                "vol_252d": finite(context_row.get("vol_252d")),
                "model_feature_count": len(feature_columns),
                "raw_model_feature_finite_count": raw_finite,
                "raw_model_feature_finite_ratio": raw_finite / max(len(feature_columns), 1),
                "raw_model_input_sha256": canonical_hash(raw_features),
                "scaled_model_input_sha256": canonical_hash(scaled_features),
                "raw_model_features_json": canonical_json(raw_features),
                "scaled_model_features_json": canonical_json(scaled_features),
                "source_bundle_sha256": source_bundle_sha256,
                "registered_score": finite(stack_row.get("score")),
                "registered_score_core": finite(stack_row.get("score_core")),
                "registered_ranking_eligible": registered_eligible,
                "published_score": finite(scored_row.get("score")),
                "published_score_total": finite(scored_row.get("score_total")),
                "published_rank": finite(scored_row.get("score_rank")),
                "published_ranking_eligible": truthy(scored_row.get("ranking_eligible")),
                "selector_score": selector_score,
                "final_score_source": "selector_when_evaluated_else_published_scored_latest",
                "final_score": selector_score if selector_score is not None else finite(scored_row.get("score")),
                "final_rank_source": "published_scored_latest",
                "final_rank": finite(scored_row.get("score_rank")),
                "ensemble_weight_linear": finite(exact_weights.get("linear_weight")),
                "ensemble_weight_catboost": finite(exact_weights.get("catboost_weight")),
                "ensemble_weight_ranker": finite(exact_weights.get("ranker_weight")),
                "ensemble_history_months": finite(exact_weights.get("history_months")),
                "selector_selected": is_selected,
                "selector_reason_code": reason_code,
                "selector_reason_source": reason_source,
                "selector_preselection_rejection_reasons": "|".join(rejection_reasons),
                "prior_holding": truthy((projection_row or {}).get("prior_holding")),
                "holding_state": clean_text((projection_row or {}).get("holding_state")),
                "hold_replace_decision": clean_text((projection_row or {}).get("hold_replace_decision")),
                "holding_state_reason": clean_text((projection_row or {}).get("holding_state_reason")),
                "advisory_weight": advisory_weight,
                "prior_weight": prior_weight,
                "advisory_cash_weight": float(selector_cash.get((portfolio, scenario), 0.0)),
                "operating_target_weight": operating_weight,
                "simulated_fill_weight": fill_weight,
                "simulated_fill_shares": finite(fill.get("shares"), 0.0),
                "simulated_fill_price": finite(fill.get("price")),
                "simulated_fill_market_value_usd": finite(fill.get("market_value_usd"), 0.0),
                "simulated_account_cash_weight": account_cash_weight,
                "simulated_account_cash_usd": finite(account.get("cash_usd"), 0.0),
                "simulated_account_equity_usd": account_equity,
                "simulated_account_cost_bps": finite(account.get("cost_bps_per_side")),
                "simulated_account_integer_shares": truthy(account.get("integer_shares")),
                "operating_to_fill_weight_delta": fill_weight - operating_weight,
                "advisory_to_operating_weight_delta": operating_weight - advisory_weight,
                "paper_cash_reconciliation_error_usd": account_cash_error_usd,
                "path_reconciliation_status": args.path_reconciliation_status,
                "outcome_identity_status": "PENDING_PIT_DELISTED_CORPORATE_ACTION_COMPLETION",
                "review_only": True,
                "model_mutated": False,
                "score_mutated": False,
                "rank_mutated": False,
                "selector_mutated": False,
                "target_books_mutated": False,
                "orders_generated": False,
                "backtest_executed": False,
                "fullrun_executed": False,
                "production_activation_allowed": False,
                "live_trading_enabled": False,
            }
            for head in contract.get("prediction_heads", HEAD_COLUMNS):
                snapshot[f"registered_{head}"] = finite(stack_row.get(head))
                snapshot[f"published_{head}"] = finite(scored_row.get(head))
            snapshot_sha256 = canonical_hash(snapshot)
            observation_key = f"{SCHEMA_VERSION}|{decision_date}|{ticker}|{portfolio}|{scenario}"
            observation_id = hashlib.sha256(observation_key.encode("utf-8")).hexdigest()[:24]
            decision_rows.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_type": "decision_observed",
                    "event_id": canonical_hash({"event_type": "decision_observed", "observation_id": observation_id}),
                    "observation_id": observation_id,
                    "recorded_at_utc": args.recorded_at_utc,
                    "decision_snapshot_sha256": snapshot_sha256,
                    "decision_snapshot": snapshot,
                }
            )
    if missing_reason_count:
        blockers.append(f"missing_selector_reason_count:{missing_reason_count}")
    primary_keys = [
        (
            row["decision_snapshot"]["decision_date"],
            row["decision_snapshot"]["ticker"],
            row["decision_snapshot"]["portfolio_kind"],
            row["decision_snapshot"]["scenario"],
        )
        for row in decision_rows
    ]
    duplicates = len(primary_keys) - len(set(primary_keys))
    if duplicates:
        blockers.append(f"duplicate_primary_key_count:{duplicates}")
    audit = {
        "blockers": sorted(set(blockers)),
        "decision_date": decision_date,
        "decision_time_utc": decision_time,
        "expected_universe_count": expected,
        "decision_ticker_count": int(len(context)),
        "scenario_count": len(scenarios),
        "proposed_decision_event_count": len(decision_rows),
        "model_feature_count": len(feature_columns),
        "prediction_head_count": len(contract.get("prediction_heads", HEAD_COLUMNS)),
        "future_row_count": future_rows,
        "missing_selector_reason_count": missing_reason_count,
        "duplicate_primary_key_count": duplicates,
        "operating_share_mismatch_count": operating_share_mismatch_count,
        "source_bundle_sha256": source_bundle_sha256,
        "source_inputs": source_fingerprints,
    }
    return decision_rows, audit


def compare_events(existing: list[dict[str, Any]], proposed: list[dict[str, Any]], hash_field: str) -> tuple[list[dict[str, Any]], int, list[str]]:
    by_id = {clean_text(row.get("event_id")): row for row in existing}
    novel: list[dict[str, Any]] = []
    duplicates = 0
    conflicts: list[str] = []
    for row in proposed:
        prior = by_id.get(row["event_id"])
        if prior is None:
            novel.append(row)
        elif clean_text(prior.get(hash_field)) == clean_text(row.get(hash_field)):
            duplicates += 1
        else:
            conflicts.append(row["event_id"])
    return novel, duplicates, conflicts


def exact_price(frame: pd.DataFrame, date: pd.Timestamp) -> float | None:
    if frame.empty or date not in frame.index:
        return None
    value = frame.loc[date, "close"]
    if isinstance(value, pd.Series):
        value = value.iloc[-1]
    return finite(value)


def outcome_snapshot(
    decision: Mapping[str, Any],
    horizon: int,
    sessions: pd.DatetimeIndex,
    as_of_date: pd.Timestamp,
    price_cache: Path,
    price_frames: dict[str, tuple[pd.DataFrame, str]],
    contract: Mapping[str, Any],
) -> dict[str, Any] | None:
    snapshot = decision["decision_snapshot"]
    decision_date = pd.Timestamp(snapshot["decision_date"]).normalize()
    after = sessions[sessions > decision_date]
    if len(after) <= horizon:
        return None
    entry_date = pd.Timestamp(after[0]).normalize()
    outcome_date = pd.Timestamp(after[horizon]).normalize()
    if outcome_date > as_of_date:
        return None

    def load(ticker: str) -> tuple[pd.DataFrame, str]:
        if ticker not in price_frames:
            price_frames[ticker] = load_cached_prices(price_cache, ticker)
        return price_frames[ticker]

    ticker = snapshot["ticker"]
    ticker_prices, ticker_basis = load(ticker)
    entry = exact_price(ticker_prices, entry_date)
    end = exact_price(ticker_prices, outcome_date)
    if entry is None or end is None:
        return None
    path = ticker_prices.loc[(ticker_prices.index >= entry_date) & (ticker_prices.index <= outcome_date), "close"].dropna()
    if path.empty:
        return None
    ticker_return = end / entry - 1.0
    mae = float(path.min() / entry - 1.0)
    mfe = float(path.max() / entry - 1.0)
    trough = float(path.min())
    recovery = float(end / trough - 1.0) if trough > 0 else None
    benchmarks: dict[str, Any] = {}
    requested = list(contract.get("benchmark_tickers", ["SPY", "QQQ"]))
    sector_etf = clean_text((contract.get("sector_etf_map") or {}).get(snapshot.get("sector")))
    if sector_etf:
        requested.append(sector_etf)
    for benchmark in requested:
        prices, basis = load(benchmark)
        b_entry = exact_price(prices, entry_date)
        b_end = exact_price(prices, outcome_date)
        total = b_end / b_entry - 1.0 if b_entry is not None and b_end is not None else None
        benchmarks[benchmark] = {
            "price_basis": basis,
            "total_return": total,
            "excess_total_return": ticker_return - total if total is not None else None,
        }
    result = {
        "observation_id": decision["observation_id"],
        "decision_event_id": decision["event_id"],
        "decision_date": snapshot["decision_date"],
        "ticker": ticker,
        "portfolio_kind": snapshot["portfolio_kind"],
        "scenario": snapshot["scenario"],
        "horizon_sessions": int(horizon),
        "entry_date": entry_date.date().isoformat(),
        "outcome_date": outcome_date.date().isoformat(),
        "ticker_price_basis": ticker_basis,
        "ticker_total_return": ticker_return,
        "ticker_mae": mae,
        "ticker_mfe": mfe,
        "ticker_max_drawdown": _max_drawdown(path),
        "ticker_recovery_from_trough": recovery,
        "benchmarks": benchmarks,
        "identity_outcome_status": snapshot.get("outcome_identity_status"),
    }
    return result


def propose_outcomes(
    decisions: list[dict[str, Any]],
    contract: Mapping[str, Any],
    price_cache: Path | None,
    as_of_date: str,
    recorded_at_utc: str,
) -> list[dict[str, Any]]:
    if price_cache is None or not price_cache.is_dir():
        return []
    start = min(pd.Timestamp(row["decision_snapshot"]["decision_date"]) for row in decisions)
    end = pd.Timestamp(as_of_date).normalize()
    sessions = load_nyse_sessions(start, end + pd.Timedelta(days=10))
    if sessions is None or len(sessions) == 0:
        return []
    frames: dict[str, tuple[pd.DataFrame, str]] = {}
    proposed: list[dict[str, Any]] = []
    for decision in decisions:
        for horizon in contract.get("outcome_horizons_sessions", [1, 5, 21, 63, 126, 252]):
            snapshot = outcome_snapshot(decision, int(horizon), sessions, end, price_cache, frames, contract)
            if snapshot is None:
                continue
            outcome_hash = canonical_hash(snapshot)
            proposed.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_type": "forward_outcome_observed",
                    "event_id": canonical_hash(
                        {
                            "event_type": "forward_outcome_observed",
                            "observation_id": decision["observation_id"],
                            "horizon_sessions": int(horizon),
                        }
                    ),
                    "observation_id": decision["observation_id"],
                    "recorded_at_utc": recorded_at_utc,
                    "outcome_snapshot_sha256": outcome_hash,
                    "outcome_snapshot": snapshot,
                }
            )
    return proposed


def rebuild_current_status(
    decisions: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    contract: Mapping[str, Any],
    as_of_date: str,
) -> pd.DataFrame:
    outcome_map = {
        (row["observation_id"], int(row["outcome_snapshot"]["horizon_sessions"])): row["outcome_snapshot"]
        for row in outcomes
    }
    rows: list[dict[str, Any]] = []
    for event in decisions:
        row = dict(event["decision_snapshot"])
        row.update(
            observation_id=event["observation_id"],
            decision_event_id=event["event_id"],
            decision_snapshot_sha256=event["decision_snapshot_sha256"],
        )
        for horizon in contract.get("outcome_horizons_sessions", [1, 5, 21, 63, 126, 252]):
            prefix = f"outcome_{int(horizon)}d_"
            outcome = outcome_map.get((event["observation_id"], int(horizon)))
            if outcome is None:
                row[prefix + "status"] = "pending_not_elapsed_or_price_unavailable"
                continue
            row[prefix + "status"] = "completed"
            for key in (
                "entry_date",
                "outcome_date",
                "ticker_total_return",
                "ticker_mae",
                "ticker_mfe",
                "ticker_max_drawdown",
                "ticker_recovery_from_trough",
            ):
                row[prefix + key] = outcome.get(key)
            for benchmark in contract.get("benchmark_tickers", ["SPY", "QQQ"]):
                bench = (outcome.get("benchmarks") or {}).get(benchmark) or {}
                row[prefix + benchmark.lower() + "_total_return"] = bench.get("total_return")
                row[prefix + benchmark.lower() + "_excess_total_return"] = bench.get("excess_total_return")
            sector_etf = clean_text((contract.get("sector_etf_map") or {}).get(row.get("sector")))
            sector = (outcome.get("benchmarks") or {}).get(sector_etf) or {}
            row[prefix + "sector_etf"] = sector_etf
            row[prefix + "sector_excess_total_return"] = sector.get("excess_total_return")
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["decision_date", "portfolio_kind", "scenario", "ticker"], kind="mergesort")


def ensure_attribution_placeholders(output_dir: Path) -> None:
    schemas = {
        "selection_attribution.csv": ["status", "decision_date", "portfolio_kind", "scenario", "horizon_sessions"],
        "entry_timing_attribution.csv": ["status", "decision_date", "portfolio_kind", "scenario", "horizon_sessions"],
        "hold_exit_attribution.csv": ["status", "decision_date", "portfolio_kind", "scenario", "horizon_sessions"],
        "sizing_cash_attribution.csv": ["status", "decision_date", "portfolio_kind", "scenario", "horizon_sessions"],
        "execution_attribution.csv": ["status", "decision_date", "portfolio_kind", "scenario"],
    }
    for name, columns in schemas.items():
        path = output_dir / name
        if not path.exists():
            pd.DataFrame(columns=columns).to_csv(path, index=False, lineterminator="\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    contract = read_json(repo_path(args.contract))
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    args.recorded_at_utc = args.recorded_at_utc or utc_now()
    decisions_path = output_dir / DECISION_LOG
    outcomes_path = output_dir / OUTCOME_LOG
    existing_decisions = read_jsonl(decisions_path)
    existing_outcomes = read_jsonl(outcomes_path)
    proposed_decisions, audit = propose_decisions(args, contract)
    novel_decisions, duplicate_decisions, decision_conflicts = compare_events(
        existing_decisions, proposed_decisions, "decision_snapshot_sha256"
    )
    blockers = list(audit.get("blockers", []))
    if decision_conflicts:
        blockers.append(f"immutable_decision_conflict_count:{len(decision_conflicts)}")
    all_decisions_for_outcomes = existing_decisions + ([] if blockers else novel_decisions)
    as_of_date = args.as_of_date or audit.get("decision_date") or ""
    proposed_outcomes = propose_outcomes(
        all_decisions_for_outcomes,
        contract,
        repo_path(args.price_cache) if args.price_cache else None,
        as_of_date,
        args.recorded_at_utc,
    )
    novel_outcomes, duplicate_outcomes, outcome_conflicts = compare_events(
        existing_outcomes, proposed_outcomes, "outcome_snapshot_sha256"
    )
    if outcome_conflicts:
        blockers.append(f"immutable_outcome_conflict_count:{len(outcome_conflicts)}")
    if not blockers:
        if not decisions_path.exists():
            decisions_path.touch()
        if not outcomes_path.exists():
            outcomes_path.touch()
        append_jsonl(decisions_path, novel_decisions)
        append_jsonl(outcomes_path, novel_outcomes)
    elif not decisions_path.exists():
        decisions_path.write_text("", encoding="utf-8")
        outcomes_path.write_text("", encoding="utf-8")
    decisions = read_jsonl(decisions_path)
    outcomes = read_jsonl(outcomes_path)
    current = rebuild_current_status(decisions, outcomes, contract, as_of_date) if decisions else pd.DataFrame()
    current_path = output_dir / "current_status.parquet"
    current.to_parquet(current_path, index=False)
    reconciliation_columns = [
        "decision_date",
        "ticker",
        "portfolio_kind",
        "scenario",
        "selector_selected",
        "selector_reason_code",
        "selector_reason_source",
        "prior_weight",
        "advisory_weight",
        "operating_target_weight",
        "simulated_fill_weight",
        "simulated_fill_shares",
        "advisory_to_operating_weight_delta",
        "operating_to_fill_weight_delta",
        "advisory_cash_weight",
        "simulated_account_cash_weight",
        "paper_cash_reconciliation_error_usd",
        "path_reconciliation_status",
    ]
    reconciliation_path = output_dir / "selector_operating_fill_reconciliation.csv"
    current.reindex(columns=reconciliation_columns).to_csv(reconciliation_path, index=False, lineterminator="\n")
    ensure_attribution_placeholders(output_dir)
    completed_63d = int(current.get("outcome_63d_status", pd.Series(dtype=str)).eq("completed").sum()) if not current.empty else 0
    status = BLOCKED_STATUS if blockers else READY_STATUS
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at_utc": args.recorded_at_utc,
        "git_head": git_head(),
        "decision_date": audit.get("decision_date"),
        "as_of_date": as_of_date,
        "blockers": sorted(set(blockers)),
        "capture_audit": audit,
        "event_counts": dict(Counter(row.get("event_type") for row in decisions + outcomes)),
        "appended_event_counts": {
            "decision_observed": len(novel_decisions) if not blockers else 0,
            "forward_outcome_observed": len(novel_outcomes) if not blockers else 0,
        },
        "duplicate_event_counts": {
            "decision_observed": duplicate_decisions,
            "forward_outcome_observed": duplicate_outcomes,
        },
        "current_status_row_count": int(len(current)),
        "unique_decision_ticker_count": int(current["ticker"].nunique()) if not current.empty else 0,
        "completed_63d_row_count": completed_63d,
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "outputs": {
            "decision_events": fingerprint(decisions_path),
            "outcome_events": fingerprint(outcomes_path),
            "current_status": fingerprint(current_path),
            "reconciliation": fingerprint(reconciliation_path),
        },
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default="docs/run287_continuous_learning_contract_v1.json")
    parser.add_argument("--decision-frame-manifest", default="outputs/run287_current_decision_frame_20260714_close_20260713_v4/manifest.json")
    parser.add_argument("--decision-context", default="outputs/run287_current_decision_frame_20260714_close_20260713_v4/selection_context.parquet")
    parser.add_argument("--scaled-model-input", default="outputs/run287_current_decision_frame_20260714_close_20260713_v4/scaled_model_input.parquet")
    parser.add_argument("--score-stack-manifest", default="outputs/run287_current_decision_score_stack_20260714_close_20260713/manifest.json")
    parser.add_argument("--score-stack", default="outputs/run287_current_decision_score_stack_20260714_close_20260713/ticker_order_score_stack.csv")
    parser.add_argument("--adaptive-ensemble", default="outputs/run287_current_decision_score_stack_20260714_close_20260713/adaptive_ensemble_audit.csv")
    parser.add_argument("--scored-latest-manifest", default="outputs/run287_scored_latest_refresh_20260714_close_20260713_v2/manifest.json")
    parser.add_argument("--scored-latest", default="outputs/run287_scored_latest_refresh_20260714_close_20260713_v2/scored_latest.csv")
    parser.add_argument("--selector-manifest", default="outputs/run287_current_selector_no_write_exact_close_20260713/manifest.json")
    parser.add_argument("--selector-projection", default="outputs/run287_current_selector_no_write_exact_close_20260713/advisory_policy_projection.csv")
    parser.add_argument("--selector-rejections", default="outputs/run287_current_selector_no_write_exact_close_20260713/advisory_rejection_audit.csv")
    parser.add_argument("--selector-stages", default="outputs/run287_current_selector_no_write_exact_close_20260713/advisory_policy_stage_audit.csv")
    parser.add_argument("--selector-scenarios", default="outputs/run287_current_selector_no_write_exact_close_20260713/advisory_scenario_summary.csv")
    parser.add_argument("--operating-main", default="outputs/daily_operating_selection_refresh_29305572139/outputs/reports/operating_main_target_book.csv")
    parser.add_argument("--operating-concentrated", default="outputs/daily_operating_selection_refresh_29305572139/outputs/reports/operating_concentrated_target_book.csv")
    parser.add_argument("--paper-root", default="outputs/run287_daily_pipeline_replay_29305572139/daily_simulated_fill_ledger")
    parser.add_argument("--decision-date", default="")
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--recorded-at-utc", default="")
    parser.add_argument("--price-cache", default="")
    parser.add_argument("--path-reconciliation-status", default="INTENTIONAL_PARALLEL_PATH_SELECTOR_AFTER_OPERATING_NO_WRITE")
    parser.add_argument("--output-dir", default="outputs/run287_decision_outcome_ledger")
    return parser.parse_args()


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
