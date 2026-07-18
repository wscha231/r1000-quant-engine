#!/usr/bin/env python3
"""Append the Run287 causal ledger from one completed-close exact packet.

This orchestrator discovers immutable inputs from the exact-packet producer,
then runs the decision/outcome ledger and review-only attribution audits.  It
never scores, selects, mutates a target book, or creates an order.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import audit_run287_model_health as model_health  # noqa: E402
from tools import audit_run287_policy_attribution as policy_attribution  # noqa: E402
from tools import build_run287_decision_outcome_ledger as ledger  # noqa: E402


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_path(status: dict[str, Any], label: str) -> Path:
    item = (status.get("source_inputs") or {}).get(label) or {}
    value = str(item.get("path") or "").strip()
    return repo_path(value) if value else Path()


def sibling(manifest: Path, name: str) -> Path:
    return manifest.parent / name


def skipped_payload(args: argparse.Namespace, reason: str, producer_status: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "run287-continuous-learning-daily-v1",
        "status": "SKIPPED_RUN287_CONTINUOUS_LEARNING_EXACT_PACKET_NOT_READY",
        "generated_at_utc": args.recorded_at_utc,
        "as_of_date": args.as_of_date,
        "reason": reason,
        "producer_status": (producer_status or {}).get("status", "missing"),
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
    }


def write_price_collection_queue(
    output_dir: Path,
    price_cache: Path,
    as_of_date: str,
    contract_path: Path,
    max_queue: int,
) -> tuple[int, int, str]:
    current_path = output_dir / "current_status.parquet"
    if not current_path.is_file():
        return 0, 0, ""
    current = pd.read_parquet(
        current_path,
        columns=[
            "decision_date", "ticker", "selector_selected", "operating_target_weight",
            "simulated_fill_weight", "published_ranking_eligible", "published_rank",
        ],
    )
    contract = read_json(contract_path)
    tickers = set(current["ticker"].dropna().astype(str).str.upper().str.strip())
    tickers.update(str(x).upper() for x in contract.get("benchmark_tickers", ["SPY", "QQQ"]))
    tickers.update(str(x).upper() for x in (contract.get("sector_etf_map") or {}).values())
    tickers.discard("")
    ticker_state = current.groupby("ticker", sort=True).agg(
        selector_selected=("selector_selected", "max"),
        operating_target_weight=("operating_target_weight", "max"),
        simulated_fill_weight=("simulated_fill_weight", "max"),
        published_ranking_eligible=("published_ranking_eligible", "max"),
        published_rank=("published_rank", "min"),
    )
    critical = sorted(
        ticker for ticker, row in ticker_state.iterrows()
        if bool(row["selector_selected"])
        or float(row["operating_target_weight"] or 0.0) > 0
        or float(row["simulated_fill_weight"] or 0.0) > 0
    )
    remainder = sorted(
        (ticker for ticker in tickers if ticker not in set(critical)),
        key=lambda ticker: (
            not bool(ticker_state.loc[ticker, "published_ranking_eligible"]) if ticker in ticker_state.index else True,
            float(ticker_state.loc[ticker, "published_rank"]) if ticker in ticker_state.index and pd.notna(ticker_state.loc[ticker, "published_rank"]) else float("inf"),
            ticker,
        ),
    )
    ordered = critical + remainder
    earliest = str(pd.to_datetime(current["decision_date"], errors="coerce").min().date())
    universe = pd.DataFrame({"ticker": ordered, "rebalance_date": earliest})
    universe.to_csv(output_dir / "price_universe.csv", index=False, lineterminator="\n")
    batch_size = max(1, int(max_queue))
    as_of = pd.Timestamp(as_of_date).normalize()
    missing_cache: dict[str, bool] = {}

    def is_missing(ticker: str) -> bool:
        if ticker in missing_cache:
            return missing_cache[ticker]
        prices, _ = ledger.load_cached_prices(price_cache, ticker)
        missing_cache[ticker] = bool(prices.empty or as_of not in prices.index)
        return missing_cache[ticker]

    critical_missing = [ticker for ticker in critical if is_missing(ticker)]
    critical_batch = critical_missing[:batch_size]
    remainder_capacity = batch_size - len(critical_batch)
    remainder_batch: list[str] = []
    if remainder_capacity > 0 and remainder:
        batch_count = max(1, (len(remainder) + remainder_capacity - 1) // remainder_capacity)
        batch_index = pd.Timestamp(as_of_date).toordinal() % batch_count
        candidates = remainder[
            batch_index * remainder_capacity : (batch_index + 1) * remainder_capacity
        ]
        remainder_batch = [ticker for ticker in candidates if is_missing(ticker)]
    missing = critical_batch + remainder_batch
    queue = pd.DataFrame({"ticker": missing, "rebalance_date": earliest})
    queue.to_csv(output_dir / "price_collection_queue.csv", index=False, lineterminator="\n")
    return len(ordered), len(missing), earliest


def run(args: argparse.Namespace) -> dict[str, Any]:
    producer_status_path = repo_path(args.producer_status)
    output_dir = repo_path(args.output_dir)
    daily_manifest = output_dir / "daily_refresh_manifest.json"
    if not producer_status_path.is_file():
        payload = skipped_payload(args, f"producer_status_missing:{producer_status_path}")
        write_json(daily_manifest, payload)
        return payload
    producer = read_json(producer_status_path)
    if producer.get("exact_packet_ready") is not True:
        payload = skipped_payload(args, "exact_packet_ready_is_not_true", producer)
        write_json(daily_manifest, payload)
        return payload

    decision_manifest = source_path(producer, "decision_manifest")
    score_manifest = source_path(producer, "score_stack_manifest")
    scored_manifest = source_path(producer, "price_manifest")
    selector_manifest_item = producer.get("selector_manifest") or {}
    selector_manifest = repo_path(str(selector_manifest_item.get("path") or ""))
    paths = {
        "decision_manifest": decision_manifest,
        "decision_context": sibling(decision_manifest, "selection_context.parquet"),
        "scaled_model_input": sibling(decision_manifest, "scaled_model_input.parquet"),
        "score_manifest": score_manifest,
        "score_stack": sibling(score_manifest, "ticker_order_score_stack.csv"),
        "adaptive_ensemble": sibling(score_manifest, "adaptive_ensemble_audit.csv"),
        "scored_manifest": scored_manifest,
        "scored_latest": sibling(scored_manifest, "scored_latest.csv"),
        "selector_manifest": selector_manifest,
        "selector_projection": sibling(selector_manifest, "advisory_policy_projection.csv"),
        "selector_rejections": sibling(selector_manifest, "advisory_rejection_audit.csv"),
        "selector_stages": sibling(selector_manifest, "advisory_policy_stage_audit.csv"),
        "selector_scenarios": sibling(selector_manifest, "advisory_scenario_summary.csv"),
        "operating_main": repo_path(args.operating_main),
        "operating_concentrated": repo_path(args.operating_concentrated),
        "paper_root": repo_path(args.paper_root),
        "contract": repo_path(args.contract),
    }
    missing = sorted(label for label, path in paths.items() if label != "paper_root" and not path.is_file())
    for portfolio in ("main", "concentrated"):
        for name in ("positions_latest.csv", "account_state_latest.json"):
            if not (paths["paper_root"] / portfolio / name).is_file():
                missing.append(f"paper_{portfolio}_{name}")
    if missing:
        payload = skipped_payload(args, "required_input_missing:" + "|".join(missing), producer)
        payload["status"] = "BLOCKED_RUN287_CONTINUOUS_LEARNING_INPUTS"
        write_json(daily_manifest, payload)
        return payload

    decision_date = str(producer.get("valuation_price_cutoff_date") or args.decision_date or "").strip()
    if not decision_date:
        payload = skipped_payload(args, "decision_date_missing", producer)
        payload["status"] = "BLOCKED_RUN287_CONTINUOUS_LEARNING_INPUTS"
        write_json(daily_manifest, payload)
        return payload
    ledger_args = SimpleNamespace(
        contract=str(paths["contract"]),
        decision_frame_manifest=str(paths["decision_manifest"]),
        decision_context=str(paths["decision_context"]),
        scaled_model_input=str(paths["scaled_model_input"]),
        score_stack_manifest=str(paths["score_manifest"]),
        score_stack=str(paths["score_stack"]),
        adaptive_ensemble=str(paths["adaptive_ensemble"]),
        scored_latest_manifest=str(paths["scored_manifest"]),
        scored_latest=str(paths["scored_latest"]),
        selector_manifest=str(paths["selector_manifest"]),
        selector_projection=str(paths["selector_projection"]),
        selector_rejections=str(paths["selector_rejections"]),
        selector_stages=str(paths["selector_stages"]),
        selector_scenarios=str(paths["selector_scenarios"]),
        operating_main=str(paths["operating_main"]),
        operating_concentrated=str(paths["operating_concentrated"]),
        paper_root=str(paths["paper_root"]),
        decision_date=decision_date,
        as_of_date=args.as_of_date or decision_date,
        recorded_at_utc=args.recorded_at_utc,
        price_cache=args.price_cache,
        path_reconciliation_status="INTENTIONAL_PARALLEL_PATH_SELECTOR_AFTER_OPERATING_NO_WRITE",
        output_dir=str(output_dir),
    )
    ledger_result = ledger.run(ledger_args)
    policy_result: dict[str, Any] = {}
    health_result: dict[str, Any] = {}
    universe_count = 0
    queue_count = 0
    collection_start = ""
    if ledger_result.get("status") == ledger.READY_STATUS:
        universe_count, queue_count, collection_start = write_price_collection_queue(
            output_dir,
            repo_path(args.price_cache),
            args.as_of_date or decision_date,
            paths["contract"],
            args.max_price_queue,
        )
        policy_result = policy_attribution.run(
            SimpleNamespace(
                ledger_dir=str(output_dir), current_status=None, output_dir=str(output_dir),
                generated_at_utc=args.recorded_at_utc,
            )
        )
        health_result = model_health.run(
            SimpleNamespace(
                ledger_dir=str(output_dir), current_status=None, output_dir=str(output_dir),
                generated_at_utc=args.recorded_at_utc,
            )
        )
    status = (
        "READY_RUN287_CONTINUOUS_LEARNING_DAILY_REVIEW_ONLY"
        if ledger_result.get("status") == ledger.READY_STATUS
        else "BLOCKED_RUN287_CONTINUOUS_LEARNING_DAILY"
    )
    payload = {
        "schema_version": "run287-continuous-learning-daily-v1",
        "status": status,
        "generated_at_utc": args.recorded_at_utc,
        "decision_date": decision_date,
        "as_of_date": args.as_of_date or decision_date,
        "ledger_status": ledger_result.get("status"),
        "ledger_blockers": ledger_result.get("blockers", []),
        "decision_event_count": int((ledger_result.get("event_counts") or {}).get("decision_observed", 0)),
        "forward_outcome_event_count": int((ledger_result.get("event_counts") or {}).get("forward_outcome_observed", 0)),
        "appended_event_counts": ledger_result.get("appended_event_counts", {}),
        "price_universe_count": universe_count,
        "price_collection_queue_count": queue_count,
        "price_collection_start_date": collection_start,
        "policy_attribution_status": policy_result.get("status", "NOT_RUN"),
        "model_health_status": health_result.get("status", "NOT_RUN"),
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
    }
    write_json(daily_manifest, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer-status", default="outputs/run287_exact_packet_producer/status.json")
    parser.add_argument("--contract", default="docs/run287_continuous_learning_contract_v1.json")
    parser.add_argument("--operating-main", default="outputs/reports/operating_main_target_book.csv")
    parser.add_argument("--operating-concentrated", default="outputs/reports/operating_concentrated_target_book.csv")
    parser.add_argument("--paper-root", default="outputs/daily_simulated_fill_ledger")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--max-price-queue", type=int, default=150)
    parser.add_argument("--decision-date", default="")
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--recorded-at-utc", required=True)
    parser.add_argument("--output-dir", default="outputs/run287_decision_outcome_ledger")
    return parser.parse_args()


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(2 if result["status"].startswith("BLOCKED") else 0)
