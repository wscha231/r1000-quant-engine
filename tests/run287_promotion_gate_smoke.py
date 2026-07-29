#!/usr/bin/env python3
"""P9 single promotion/rollback gate regression tests."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from run287_promotion_gate import (  # noqa: E402
    DECISION_ARCHIVE_CONTRACT_SHA256,
    DEFAULT_CONTRACT,
    DEFAULT_EVIDENCE,
    DEFAULT_STATE,
    RISK_OUTCOME_CONTRACT_SHA256,
    evaluate_gate,
    gate_for_consumer,
    overlay_latest_run_evidence,
    read_json,
    sha256_file,
    _jsonl_rows,
)
from run287_paper_ledger_integrity import write_integrity_manifest  # noqa: E402
from run_daily_simulated_fill_ledger import (  # noqa: E402
    canonical_hash as paper_event_hash,
    event_payload_for_hash,
    preview_identity,
)
from archive_run287_decision_observation import (  # noqa: E402
    canonical_hash as archive_canonical_hash,
    event_id as archive_event_id,
)
from resolve_run287_risk_outcomes import (  # noqa: E402
    build_current_status,
    build_observations,
    capture_signal_events,
    load_cached_prices,
    load_nyse_sessions,
    outcome_event,
    write_price_universe,
)
from run_weekly_evaluation import px_cache_name  # noqa: E402
from build_run287_operating_scorecard import build_scorecard  # noqa: E402
from tests.run287_paper_ledger_transaction_smoke import (  # noqa: E402
    write_prices,
    write_replay_price_manifest,
)


def _inputs() -> tuple[dict, dict, dict]:
    return read_json(DEFAULT_CONTRACT), read_json(DEFAULT_STATE), read_json(DEFAULT_EVIDENCE)


def _passing_evidence(contract: dict, evidence: dict) -> dict:
    payload = copy.deepcopy(evidence)
    payload["candidate_id"] = "single-shadow-challenger"
    for field in contract["required_historical_checks"]:
        payload["historical"][field] = True
    thresholds = contract["forward_thresholds"]
    forward = payload["forward_paper"]
    forward.update(
        {
            "completed_market_sessions": thresholds["minimum_completed_market_sessions"],
            "distinct_decision_weeks": thresholds["minimum_distinct_decision_weeks"],
            "resolved_21d_outcomes": thresholds["minimum_resolved_21d_outcomes"],
            "resolved_63d_outcomes": thresholds["minimum_resolved_63d_outcomes"],
            "resolved_126d_outcomes": thresholds["minimum_resolved_126d_outcomes"],
            "selection_evaluable": True,
            "exit_evaluable": True,
            "defense_evaluable": True,
            "reentry_evaluable": True,
        }
    )
    forward["integrity_availability"] = {
        field: "VERIFIED" for field in contract["required_zero_integrity_fields"]
    }
    champion = payload["accounts"]["champion"]
    challenger = copy.deepcopy(champion)
    challenger["account_id"] = "run287-challenger-paper"
    challenger["ledger_root"] = "paper_archive/challenger/single-shadow-challenger"
    payload["accounts"]["challenger"] = challenger
    payload["accounts"]["paired_decision_date_count"] = 60
    payload["accounts"]["runtime_pair_verified"] = True
    return payload


def _write_valid_paper_portfolio(
    paper: Path,
    portfolio: str,
    *,
    dates_and_cash: list[tuple[str, float]],
    effective_target_distinct: bool = False,
) -> None:
    directory = paper / portfolio
    directory.mkdir(parents=True)
    latest = paper.parent
    as_of_date = dates_and_cash[-1][0]
    chain_hash = "0" * 64
    target_name = (
        "operating_main_target_book.csv"
        if portfolio == "main"
        else "operating_concentrated_target_book.csv"
    )
    source_name = (
        "same_close_main_target_book.csv"
        if portfolio == "main"
        else "same_close_concentrated_target_book.csv"
    )
    target_path = latest / "reports" / target_name
    source_path = latest / "run287_same_close_decision" / source_name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    target_text = (
        "rebalance_date,ticker,weight,portfolio_kind,target_effective_date,"
        "order_eligible_close_date\n"
        f"{as_of_date},CASH,1.0,{portfolio},{as_of_date},{as_of_date}\n"
    )
    target_path.write_text(target_text, encoding="utf-8")
    source_path.write_text(target_text, encoding="utf-8")
    effective_target_text = target_text
    if effective_target_distinct:
        effective_target_text = (
            "rebalance_date,ticker,weight,portfolio_kind,target_effective_date,"
            "order_eligible_close_date\n"
            f"{as_of_date},AAA,0.5,{portfolio},{as_of_date},{as_of_date}\n"
            f"{as_of_date},CASH,0.5,{portfolio},{as_of_date},{as_of_date}\n"
        )
    effective_target_path = directory / "effective_target_latest.csv"
    effective_target_path.write_text(
        effective_target_text, encoding="utf-8"
    )
    bootstrap_path = paper / "bootstrap" / f"{portfolio}_account.json"
    bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
    bootstrap_path.write_text(
        json.dumps(
            {
                "schema_version": "daily-simulated-account-bootstrap-v1",
                "portfolio_kind": portfolio,
                "as_of_date": dates_and_cash[0][0],
                "equity_usd": 100.0,
                "cash_usd": float(dates_and_cash[0][1]),
                "positions": [],
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    seed_hash = sha256_file(bootstrap_path)
    target_sha256 = sha256_file(effective_target_path)
    lifecycle_source = ("c" if portfolio == "main" else "d") * 64
    lifecycle_snapshot = ("e" if portfolio == "main" else "f") * 64
    directory.joinpath("account_state_latest.json").write_text(
        json.dumps(
            {
                "schema_version": "daily-simulated-account-v1",
                "portfolio_kind": portfolio,
                "as_of_date": as_of_date,
                "seed_as_of_date": dates_and_cash[0][0],
                "seed_equity_usd": 100.0,
                "seed_account_sha256": seed_hash,
                "starting_capital_usd": 100.0,
                "equity_usd": 100.0,
                "cash_usd": float(dates_and_cash[-1][1]),
                "cash_weight": float(dates_and_cash[-1][1]) / 100.0,
                "stock_value_usd": 100.0 - float(dates_and_cash[-1][1]),
                "reserve_asset_value_usd": 0.0,
                "reserve_value_usd": float(dates_and_cash[-1][1]),
                "reserve_weight": float(dates_and_cash[-1][1]) / 100.0,
                "position_count": 0,
                "position_count_total": 0,
                "equity_position_count": 0,
                "reserve_position_count": 0,
                "positions": [],
                "pending_order_count": 0,
                "total_fees_usd": 0.0,
                "forward_fill_count": 0,
                "realized_pnl_by_ticker": {},
                "total_realized_pnl_usd": 0.0,
                "fill_mode": "next_close",
                "cost_bps_per_side": 25.0,
                "integer_shares": True,
                "review_only": True,
                "simulated_broker_ledger": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "human_approval_required_for_live_orders": True,
            }
        ),
        encoding="utf-8",
    )
    directory.joinpath("positions_latest.csv").write_text(
        "ticker,shares\n", encoding="utf-8"
    )
    directory.joinpath("pending_orders.csv").write_text(
        "client_order_id,signal_date\n", encoding="utf-8"
    )
    directory.joinpath("fills.csv").write_text(
        "client_order_id,event_sequence,event_id,previous_event_hash,event_hash,date,signal_date\n",
        encoding="utf-8",
    )
    directory.joinpath("rejections.csv").write_text(
        "client_order_id,event_sequence,event_id,previous_event_hash,event_hash,date,signal_date\n",
        encoding="utf-8",
    )
    with directory.joinpath("equity_curve.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "date",
                "equity_usd",
                "cash_usd",
                "stock_value_usd",
                "record_type",
            ],
        )
        writer.writeheader()
        for row_date, cash in dates_and_cash:
            writer.writerow(
                {
                    "date": row_date,
                    "equity_usd": 100.0,
                    "cash_usd": cash,
                    "stock_value_usd": 100.0 - cash,
                    "record_type": "FORWARD_MARK",
                }
            )
    common = {
        "schema_version": "daily-simulated-fill-ledger-state-v2",
        "portfolio_kind": portfolio,
        "as_of_date": as_of_date,
        "pending_order_count": 0,
        "fill_count": 0,
        "rejection_count": 0,
        "event_sequence": 0,
        "event_chain_hash": chain_hash,
        "security_lifecycle_snapshot_hash": lifecycle_snapshot,
        "review_only": True,
        "live_trading_enabled": False,
        "production_mutation_allowed": False,
    }
    directory.joinpath("state_meta.json").write_text(
        json.dumps(common), encoding="utf-8"
    )
    manifest = {
        **common,
        "schema_version": "daily-simulated-fill-ledger-manifest-v2",
        "seeded_this_run": False,
        "fill_mode": "next_close",
        "cost_bps_per_side": 25.0,
        "integer_shares": True,
        "max_fill_lag_days": 7,
        "target_hash": ("1" if portfolio == "main" else "2") * 64,
        "target_effective_date": as_of_date,
        "target_sha256": target_sha256,
        "source_target_sha256": sha256_file(source_path),
        "seed_account_sha256": seed_hash,
        "security_lifecycle_schema_version": "run287-security-lifecycle-v1",
        "security_lifecycle_source_sha256": lifecycle_source,
        "security_lifecycle_snapshot_hash": lifecycle_snapshot,
        "security_lifecycle_terminal_tickers": [],
        "security_lifecycle_actions": {
            "settled_positions": 0,
            "cancelled_pending_orders": 0,
        },
        "resolved_fills_this_run": 0,
        "resolved_rejections_this_run": 0,
        "enqueued_this_run": 0,
        "forward_metrics": {
            "eligibility_rule": (
                "FORWARD_MARK_AND_NOT_DURABLE_REPLAY_SESSION"
            ),
            "observations": len(dates_and_cash),
            "excluded_replay_observations": 0,
            "start_date": dates_and_cash[0][0],
            "end_date": dates_and_cash[-1][0],
            "cagr_status": "UNDERPOWERED",
            "forward_cagr": None,
            "historical_metric_replacement_allowed": False,
        },
        "new_order_generation_suppressed": False,
        "simulated": True,
        "historical_cagr_mdd_replacement_allowed": False,
        "result_status": "RESTORED_CONTINUATION",
    }
    directory.joinpath("manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    preview_dir = latest / "account_ledger_preview" / portfolio
    preview_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.joinpath("orders_preview.csv").write_text(
        "ticker,side,status,client_order_id\n", encoding="utf-8"
    )
    preview_dir.joinpath("target_weights.csv").write_text(
        "ticker,target_weight\nCASH,1.0\n", encoding="utf-8"
    )
    identity = preview_identity(
        preview_dir=preview_dir,
        account_path=directory / "account_state_latest.json",
        effective_target_path=directory / "effective_target_latest.csv",
        source_target_path=source_path,
        portfolio=portfolio,
        as_of_date=pd.Timestamp(as_of_date),
        preview_mode="EXECUTABLE_CANDIDATE",
    )
    preview_dir.joinpath("order_batch_manifest.json").write_text(
        json.dumps(
            {
                **identity,
                "schema_version": "account-ledger-preview-order-batch-v2",
                "portfolio_kind": portfolio,
                "as_of_date": as_of_date,
                "order_count": 0,
                "ready_order_count": 0,
                "client_order_ids": [],
                "new_order_generation_suppressed": False,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
            }
        ),
        encoding="utf-8",
    )


def _finalize_valid_paper(paper: Path) -> dict:
    latest = paper.parent
    manifests = {
        portfolio: json.loads(
            paper.joinpath(portfolio, "manifest.json").read_text(encoding="utf-8")
        )
        for portfolio in ("main", "concentrated")
    }
    as_of_date = manifests["main"]["as_of_date"]
    assert manifests["concentrated"]["as_of_date"] == as_of_date
    accepted_portfolios: dict[str, dict[str, str]] = {}
    for portfolio in ("main", "concentrated"):
        target_name = (
            "operating_main_target_book.csv"
            if portfolio == "main"
            else "operating_concentrated_target_book.csv"
        )
        source_name = (
            "same_close_main_target_book.csv"
            if portfolio == "main"
            else "same_close_concentrated_target_book.csv"
        )
        target = latest / "reports" / target_name
        source = latest / "run287_same_close_decision" / source_name
        account = paper / portfolio / "account_state_latest.json"
        ledger_manifest = paper / portfolio / "manifest.json"
        preview_manifest = json.loads(
            latest.joinpath(
                "account_ledger_preview", portfolio, "order_batch_manifest.json"
            ).read_text(encoding="utf-8")
        )
        accepted_portfolios[portfolio] = {
            "source_target_path": str(source.resolve()),
            "source_target_sha256": sha256_file(source),
            "published_target_path": str(target.resolve()),
            "published_target_sha256": sha256_file(target),
            "account_state_sha256": sha256_file(account),
            "ledger_manifest_sha256": sha256_file(ledger_manifest),
            "preview_identity_at_acceptance": preview_manifest[
                "preview_identity_hash"
            ],
            "preview_mode_at_acceptance": preview_manifest["preview_mode"],
        }
    paper.joinpath("accepted_publication.json").write_text(
        json.dumps(
            {
                "schema_version": "run287-paper-accepted-publication-v1",
                "status": "ACCEPTED_ATOMIC_PUBLICATION",
                "as_of_date": as_of_date,
                "transaction_mode": "SELECTED_TARGET",
                "portfolios": accepted_portfolios,
                "review_only": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    paper.joinpath("summary.json").write_text(
        json.dumps(
            {
                "schema_version": "daily-simulated-fill-ledger-summary-v1",
                "status": "completed",
                "result_status": "RESTORED_CONTINUATION",
                "as_of_date": as_of_date,
                "portfolios": manifests,
                "new_order_generation_suppressed": False,
                "review_only": True,
                "simulated": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "historical_cagr_mdd_replacement_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    return write_integrity_manifest(paper, as_of_date=as_of_date)


def _write_valid_outcome_fixture(
    root: Path,
    *,
    as_of_date: str,
    decision_week_count: int = 13,
    late_signal_backfill: bool = False,
) -> Path:
    archive = root / "run287_decision_observation_archive"
    archive.mkdir()
    paper_date = pd.Timestamp(as_of_date).normalize()
    calendar = mcal.get_calendar("NYSE")
    selection_schedule = calendar.schedule(
        start_date=paper_date - pd.Timedelta(days=500),
        end_date=paper_date - pd.Timedelta(days=300),
    )
    selected_dates: list[str] = []
    seen_weeks: set[str] = set()
    for stamp in selection_schedule.index:
        parsed = stamp.date()
        iso = parsed.isocalendar()
        week = f"{iso.year:04d}-W{iso.week:02d}"
        if week not in seen_weeks:
            selected_dates.append(parsed.isoformat())
            seen_weeks.add(week)
        if len(selected_dates) == decision_week_count:
            break
    assert len(selected_dates) == decision_week_count
    archive_contract = ROOT / "docs" / "run287_decision_observation_archive_contract.json"
    archive_contract_sha256 = DECISION_ARCHIVE_CONTRACT_SHA256
    safety = {
        "schema_version": "run287-decision-observation-archive-v1",
        "archive_contract_sha256": archive_contract_sha256,
        "pinned_policy_commit": "15176b588d5bb0792bce1df6367758d795a8a33a",
        "review_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "historical_cagr_mdd_evidence_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    decision_rows: list[dict] = []
    candidate_rows: list[dict] = []
    for decision_date in selected_dates:
        parsed = date.fromisoformat(decision_date)
        iso_week = f"{parsed.isocalendar().year:04d}-W{parsed.isocalendar().week:02d}"
        candidate_row = {
            **safety,
            "as_of_date": decision_date,
            "iso_decision_week": iso_week,
            "record_kind": "candidate_risk",
            "ticker": "AAA",
            "risk_state": "NORMAL",
            "advisory_action": "observe",
            "reason_codes": "synthetic_valid_fixture",
            "history_observations": 252,
            "return_1d": 0.01,
            "spy_excess_return_1d": 0.0,
            "return_21d": 0.05,
            "spy_excess_return_21d": 0.01,
            "drawdown_63d": -0.10,
            "normal_state_is_not_alpha_evidence": True,
            "risk_state_may_authorize_buy": False,
            "selector_weight_changed_by_archive": False,
            "event_id": archive_event_id(
                "candidate_risk", decision_date, {"ticker": "AAA"}
            ),
        }
        candidate_rows.append(candidate_row)
        decision_rows.append(
            {
                **safety,
                "as_of_date": decision_date,
                "iso_decision_week": iso_week,
                "record_kind": "decision_close",
                "scenario_count": 0,
                "position_row_count": 0,
                "candidate_count": 1,
                "alert_count": 0,
                "watch_count": 0,
                "data_insufficient_count": 0,
                "normal_count": 1,
                "scenario_set_sha256": archive_canonical_hash({"rows": []}),
                "position_set_sha256": archive_canonical_hash({"rows": []}),
                "candidate_risk_set_sha256": archive_canonical_hash(
                    {"rows": [candidate_row]}
                ),
                "archive_may_promote": False,
                "resolved_forward_outcomes_required": True,
                "event_id": archive_event_id("decision_close", decision_date, {}),
            }
        )

    histories = {
        "decision": decision_rows,
        "scenario": [],
        "position": [],
        "candidate_risk": candidate_rows,
    }
    history_paths: dict[str, Path] = {}
    for kind, rows in histories.items():
        path = archive / f"{kind}_history.jsonl"
        path.write_text(
            "".join(
                json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        history_paths[kind] = path

    def fingerprint(path: Path) -> dict:
        return {
            "path": str(path),
            "exists": True,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    decision_weeks = sorted(
        {
            f"{date.fromisoformat(value).isocalendar().year:04d}-W"
            f"{date.fromisoformat(value).isocalendar().week:02d}"
            for value in selected_dates
        }
    )
    archive_manifest = {
        "schema_version": "run287-decision-observation-archive-v1",
        "status": "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY",
        "archive_passed": True,
        "contract_failures": [],
        "latest_as_of_date": selected_dates[-1],
        "latest_iso_decision_week": decision_weeks[-1],
        "distinct_decision_date_count": len(selected_dates),
        "distinct_decision_week_count": len(decision_weeks),
        "decision_dates": selected_dates,
        "decision_weeks": decision_weeks,
        "history_counts": {
            kind: len(rows) for kind, rows in histories.items()
        },
        "archive_may_promote": False,
        "interpretation": {
            "normal_state_is_not_alpha_evidence": True,
            "portfolio_transition_allowed": False,
            "historical_cagr_mdd_evidence_changed": False,
        },
        "review_only": True,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "source_inputs_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": {
            "archive_contract": {
                **fingerprint(archive_contract),
                "sha256": DECISION_ARCHIVE_CONTRACT_SHA256,
            }
        },
        "outputs": {
            f"{kind}_history": fingerprint(path)
            for kind, path in history_paths.items()
        },
    }
    archive.joinpath("manifest.json").write_text(
        json.dumps(archive_manifest), encoding="utf-8"
    )

    outcome_dir = root / "run287_risk_outcome_archive"
    outcome_dir.mkdir()
    price_cache = root / "run287_risk_outcome_price_cache"
    price_cache.mkdir()
    sessions = load_nyse_sessions(pd.Timestamp(selected_dates[0]), paper_date)
    assert sessions is not None and len(sessions) > 126
    for ticker, base, step in (("AAA", 100.0, 0.10), ("SPY", 400.0, 0.05)):
        closes = [base + index * step for index in range(len(sessions))]
        pd.DataFrame(
            {
                "Open": closes,
                "Close": closes,
                "Adj Close": closes,
                "Volume": [1_000_000] * len(sessions),
            },
            index=sessions,
        ).to_parquet(price_cache / px_cache_name(ticker))
    observations, failures = build_observations(candidate_rows, [])
    assert not failures
    recorded_at = f"{as_of_date}T23:00:00Z"
    signals: list[dict] = []
    for observation in observations:
        signal_schedule = calendar.schedule(
            start_date=observation["decision_date"],
            end_date=(
                pd.Timestamp(observation["decision_date"])
                + pd.Timedelta(days=3)
            ),
        )
        assert not signal_schedule.empty
        signal_recorded_at = (
            f"{as_of_date}T23:00:00Z"
            if late_signal_backfill
            else (
                signal_schedule.iloc[0]["market_close"]
                + pd.Timedelta(hours=1)
            ).isoformat()
        )
        new_signals, signal_failures = capture_signal_events(
            [observation], signals, signal_recorded_at
        )
        assert not signal_failures
        signals.extend(new_signals)
    all_events = list(signals)
    evaluations: dict[str, dict[int, str]] = {}
    horizons = (1, 5, 21, 63, 126)
    ticker_frame, ticker_basis = load_cached_prices(price_cache, "AAA")
    benchmark_frame, benchmark_basis = load_cached_prices(price_cache, "SPY")
    assert ticker_basis == benchmark_basis == "adjusted_close"
    ticker_hash = sha256_file(price_cache / px_cache_name("AAA"))
    benchmark_hash = sha256_file(price_cache / px_cache_name("SPY"))
    for signal in signals:
        observation_id = str(signal["observation_id"])
        evaluations[observation_id] = {}
        for horizon in horizons:
            event, status = outcome_event(
                signal,
                horizon,
                ticker_frame,
                benchmark_frame,
                sessions,
                as_of_date=paper_date,
                recorded_at=recorded_at,
                ticker_hash=ticker_hash,
                benchmark_hash=benchmark_hash,
            )
            assert event is not None and status == "completed"
            all_events.append(event)
            evaluations[observation_id][horizon] = status
    status = build_current_status(all_events, evaluations, horizons)
    status_path = outcome_dir / "current_status.csv"
    status.to_csv(status_path, index=False)
    event_log = outcome_dir / "risk_outcome_events.jsonl"
    event_log.write_text(
        "\n".join(
            json.dumps(event, sort_keys=True, separators=(",", ":"))
            for event in all_events
        )
        + "\n",
        encoding="utf-8",
    )
    universe = outcome_dir / "price_universe.csv"
    universe_frame = write_price_universe(status, universe, horizons, "SPY")
    price_cache_manifest = price_cache / "replay_price_cache_manifest.json"
    price_cache_manifest.write_text(
        json.dumps(
            {
                "schema_version": "run287-replay-price-cache-manifest-v2",
                "book_inputs": [
                    {
                        "path": str(universe.resolve()),
                        "sha256": sha256_file(universe),
                        "bytes": universe.stat().st_size,
                    }
                ],
                "cache_files": {
                    ticker: {
                        "file": px_cache_name(ticker),
                        "sha256": sha256_file(
                            price_cache / px_cache_name(ticker)
                        ),
                        "bytes": (
                            price_cache / px_cache_name(ticker)
                        ).stat().st_size,
                    }
                    for ticker in ("AAA", "SPY")
                },
                "review_only": True,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    horizon_counts = {
        f"{horizon}d": {
            str(key): int(value)
            for key, value in status[
                f"outcome_{horizon}d_status"
            ].value_counts().to_dict().items()
        }
        for horizon in horizons
    }
    summary = {
        "schema_version": "run287-risk-outcome-archive-v1",
        "status": "READY_RISK_OUTCOME_ARCHIVE_REVIEW_ONLY",
        "as_of_date": as_of_date,
        "blockers": [],
        "distinct_decision_week_count": decision_week_count,
        "signal_observation_count": len(signals),
        "forward_outcome_event_count": len(all_events) - len(signals),
        "price_universe_unique_ticker_count": len(universe_frame),
        "horizon_status_counts": horizon_counts,
        "source_inputs": {
            "decision_archive_manifest_sha256": sha256_file(archive / "manifest.json"),
            "candidate_risk_history_sha256": sha256_file(
                archive / "candidate_risk_history.jsonl"
            ),
            "position_history_sha256": sha256_file(archive / "position_history.jsonl"),
            "contract_sha256": RISK_OUTCOME_CONTRACT_SHA256,
            "price_cache_manifest_sha256": sha256_file(
                price_cache_manifest
            ),
        },
        "outputs": {
            "event_log_sha256": sha256_file(event_log),
            "current_status_sha256": sha256_file(status_path),
            "price_universe_sha256": sha256_file(universe),
        },
        "review_only": True,
        "mechanism_promotion_allowed": False,
        "threshold_tuning_allowed": False,
        "stop_or_exit_rule_created": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    empty_sha256 = hashlib.sha256(b"").hexdigest()
    summary["outcome_chain"] = {
        "schema_version": "run287-risk-outcome-chain-v1",
        "status": "VERIFIED_APPEND_ONLY",
        "parent_anchor_sha256": "1" * 64,
        "parent_anchor_status": "GENESIS_EMPTY",
        "parent_summary_sha256": "",
        "parent_summary_bytes": 0,
        "parent_event_log_sha256": empty_sha256,
        "parent_event_log_bytes": 0,
        "parent_event_count": 0,
        "parent_as_of_date": "",
        "carried_quarantined_prefix_event_count": 0,
        "parent_acceptance_status": "NO_PRIOR_STATE",
        "parent_accepted_manifest_sha256": "",
        "parent_accepted_manifest_bytes": 0,
        "parent_accepted_manifest_as_of_date": "",
        "current_event_log_sha256": sha256_file(event_log),
        "current_event_log_bytes": event_log.stat().st_size,
        "current_event_count": len(all_events),
        "current_as_of_date": as_of_date,
        "exact_parent_prefix_verified": True,
        "append_only_verified": True,
        "trusted_event_count": len(all_events),
    }
    outcome_dir.joinpath("summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    parent_summary_path = outcome_dir / "summary.json"
    parent_manifest = {
        "schema_version": "run287-accepted-publication-manifest-v1",
        "status": "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY",
        "as_of_date": as_of_date,
        "outcome_status": summary["status"],
        "outcome_chain": copy.deepcopy(summary["outcome_chain"]),
        "files": {
            "risk_outcome_summary": {
                "path": "run287_risk_outcome_archive/summary.json",
                "sha256": sha256_file(parent_summary_path),
                "bytes": parent_summary_path.stat().st_size,
            },
            "risk_outcome_event_log": {
                "path": (
                    "run287_risk_outcome_archive/"
                    "risk_outcome_events.jsonl"
                ),
                "sha256": sha256_file(event_log),
            },
        },
        "review_only": True,
        "automatic_champion_replacement_allowed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }
    parent_manifest_path = (
        root
        / "run287_risk_outcome_parent_accepted"
        / "manifest.json"
    )
    parent_manifest_path.parent.mkdir()
    parent_manifest_path.write_text(
        json.dumps(parent_manifest), encoding="utf-8"
    )
    parent_anchor = {
        "schema_version": "run287-risk-outcome-parent-anchor-v1",
        "status": "VERIFIED_PARENT",
        "generated_at_utc": "2027-06-30T23:30:00Z",
        "parent_summary_sha256": sha256_file(parent_summary_path),
        "parent_summary_bytes": parent_summary_path.stat().st_size,
        "parent_event_log_sha256": sha256_file(event_log),
        "parent_event_log_bytes": event_log.stat().st_size,
        "parent_event_count": len(all_events),
        "parent_as_of_date": as_of_date,
        "carried_quarantined_prefix_event_count": 0,
        "parent_acceptance_status": "VERIFIED_ACCEPTED_HEAD",
        "parent_accepted_manifest_sha256": sha256_file(
            parent_manifest_path
        ),
        "parent_accepted_manifest_bytes": parent_manifest_path.stat().st_size,
        "parent_accepted_manifest_as_of_date": as_of_date,
        "review_only": True,
        "mechanism_promotion_allowed": False,
        "threshold_tuning_allowed": False,
        "stop_or_exit_rule_created": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    anchor_path = (
        root / "run287_risk_outcome_parent_anchor" / "anchor.json"
    )
    anchor_path.parent.mkdir()
    anchor_path.write_text(json.dumps(parent_anchor), encoding="utf-8")
    summary["outcome_chain"] = {
        "schema_version": "run287-risk-outcome-chain-v1",
        "status": "VERIFIED_APPEND_ONLY",
        "parent_anchor_sha256": sha256_file(anchor_path),
        "parent_anchor_status": parent_anchor["status"],
        **{
            field: parent_anchor[field]
            for field in (
                "parent_summary_sha256",
                "parent_summary_bytes",
                "parent_event_log_sha256",
                "parent_event_log_bytes",
                "parent_event_count",
                "parent_as_of_date",
                "carried_quarantined_prefix_event_count",
                "parent_acceptance_status",
                "parent_accepted_manifest_sha256",
                "parent_accepted_manifest_bytes",
                "parent_accepted_manifest_as_of_date",
            )
        },
        "current_event_log_sha256": sha256_file(event_log),
        "current_event_log_bytes": event_log.stat().st_size,
        "current_event_count": len(all_events),
        "current_as_of_date": as_of_date,
        "exact_parent_prefix_verified": True,
        "append_only_verified": True,
        "trusted_event_count": len(all_events),
    }
    parent_summary_path.write_text(
        json.dumps(summary), encoding="utf-8"
    )
    return outcome_dir


def test_current_packet_remains_research_only_and_underpowered() -> None:
    contract, state, evidence = _inputs()
    gate = evaluate_gate(contract, state, evidence, source_hashes={"evidence_sha256": "current"})
    assert gate["canonical_promotion_state"] == "RESEARCH_ONLY"
    assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
    assert gate["maximum_evidence_supported_state"] == "RESEARCH_ONLY"
    assert gate["forward_paper_gate"]["resolved_63d_status"] == "UNDERPOWERED"
    assert gate["automatic_forward_transition_performed"] is False
    assert gate["production_activation_allowed"] is False
    assert gate["live_trading_enabled"] is False


def test_all_evidence_only_sets_maximum_and_never_auto_advances() -> None:
    contract, state, evidence = _inputs()
    gate = evaluate_gate(contract, state, _passing_evidence(contract, evidence))
    assert (
        gate["maximum_evidence_supported_state"]
        == "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED"
    )
    assert gate["forward_paper_gate"]["status"] == "REVIEW_READY"
    assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
    assert gate["canonical_state_unchanged"] is True


def test_manual_transition_is_candidate_only_and_requires_exact_authorization() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    approval = {
        "approved": True,
        "approved_by": "user",
        "approved_at_utc": "2026-07-20T00:00:00Z",
        "approved_scope": "shadow-state-pointer-review",
        "requested_state": "SHADOW_OPERATION_READY",
        "evidence_sha256": "evidence-hash",
    }
    gate = evaluate_gate(
        contract,
        state,
        passing,
        source_hashes={"evidence_sha256": "evidence-hash"},
        requested_state="SHADOW_OPERATION_READY",
        transition_authorization=approval,
    )
    transition = gate["transition_request"]
    assert transition["status"] == "REVIEWED_STATE_CHANGE_PR_REQUIRED", transition
    assert transition["canonical_state_changed"] is False
    assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
    bad = copy.deepcopy(approval)
    bad["evidence_sha256"] = "wrong"
    blocked = evaluate_gate(
        contract,
        state,
        passing,
        source_hashes={"evidence_sha256": "evidence-hash"},
        requested_state="SHADOW_OPERATION_READY",
        transition_authorization=bad,
    )
    assert blocked["transition_request"]["status"] == "TRANSITION_REQUEST_BLOCKED"


def test_champion_and_challenger_cannot_share_ledger_or_contract() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    passing["accounts"]["challenger"]["ledger_root"] = passing["accounts"]["champion"]["ledger_root"]
    passing["accounts"]["challenger"]["cost_contract_sha256"] = "different-cost"
    gate = evaluate_gate(contract, state, passing)
    assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
    assert gate["rollback"]["triggered"] is True
    assert gate["rollback"]["canonical_champion_preserved"] is True
    assert gate["rollback"]["paper_history_preserved"] is True


def test_rollback_trigger_deescalates_but_preserves_forward_history() -> None:
    contract, state, evidence = _inputs()
    state = copy.deepcopy(state)
    state["promotion_state"] = "FORWARD_PAPER_VALIDATING"
    passing = _passing_evidence(contract, evidence)
    passing["rollback"]["stress_mdd_degradation"] = True
    gate = evaluate_gate(contract, state, passing)
    assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
    assert "stress_mdd_degradation" in gate["rollback"]["triggers"]
    assert gate["rollback"]["policy_pointer_action"] == "RESTORE_CANONICAL_CHAMPION"
    assert gate["rollback"]["paper_history_preserved"] is True


def test_runner_emits_one_consistent_state_and_noneligible_approval_packet() -> None:
    with TemporaryDirectory() as tmp:
        out = Path(tmp) / "gate"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run_run287_promotion_gate.py"),
                "--output-dir",
                str(out),
            ],
            cwd=ROOT,
            check=True,
        )
        gate = json.loads((out / "promotion_gate.json").read_text(encoding="utf-8"))
        packet = json.loads((out / "user_approval_packet.json").read_text(encoding="utf-8"))
        assert gate["effective_promotion_state"] == "RESEARCH_ONLY"
        assert packet["status"] == "NOT_ELIGIBLE"
        assert packet["production_activation_allowed"] is False
        consumer = gate_for_consumer(out.parent, explicit=out / "promotion_gate.json")
        assert consumer["promotion_state"] == "RESEARCH_ONLY"
        assert consumer["source_path"].endswith("promotion_gate.json")


def test_lower_signal_frequency_never_changes_fixed_thresholds() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    passing["forward_paper"]["resolved_63d_outcomes"] = contract["forward_thresholds"]["minimum_resolved_63d_outcomes"] - 1
    gate = evaluate_gate(contract, state, passing)
    assert gate["forward_paper_gate"]["status"] == "UNDERPOWERED"
    assert gate["forward_paper_gate"]["resolved_63d_status"] == "UNDERPOWERED"
    assert gate["forward_paper_gate"]["thresholds"] == contract["forward_thresholds"]


def test_governance_contract_thresholds_and_field_sets_are_immutable() -> None:
    contract, state, evidence = _inputs()
    mutations = (
        (
            lambda payload: payload["forward_thresholds"].update(
                {"minimum_completed_market_sessions": 59}
            ),
            "contract:contract_forward_thresholds_not_canonical",
        ),
        (
            lambda payload: payload["required_zero_integrity_fields"].pop(),
            "contract:contract_zero_integrity_fields_not_canonical",
        ),
        (
            lambda payload: payload["rules"].update(
                {"automatic_forward_transition_allowed": True}
            ),
            "contract:contract_rules_not_canonical",
        ),
    )
    for mutate, expected_trigger in mutations:
        changed = copy.deepcopy(contract)
        mutate(changed)
        gate = evaluate_gate(changed, state, evidence)
        assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
        assert expected_trigger in gate["rollback"]["triggers"]


def test_malformed_governance_contract_returns_structured_rollback() -> None:
    contract, state, evidence = _inputs()
    for field in ("forward_thresholds", "states"):
        malformed = copy.deepcopy(contract)
        malformed.pop(field)
        gate = evaluate_gate(
            malformed,
            state,
            evidence,
            requested_state="SHADOW_OPERATION_READY",
            transition_authorization=None,
        )
        assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
        assert gate["rollback"]["triggered"] is True
        assert any(
            trigger.startswith("contract:")
            for trigger in gate["rollback"]["triggers"]
        )
        assert gate["transition_request"]["status"] == "TRANSITION_REQUEST_BLOCKED"


def test_review_ready_can_request_and_preserve_production_candidate_state() -> None:
    contract, state, evidence = _inputs()
    passing = _passing_evidence(contract, evidence)
    review_ready = copy.deepcopy(state)
    review_ready["promotion_state"] = "FORWARD_PAPER_REVIEW_READY"
    approval = {
        "approved": True,
        "approved_by": "user",
        "approved_at_utc": "2026-07-23T00:00:00Z",
        "approved_scope": "production-candidate-state-pointer-review",
        "requested_state": "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED",
        "evidence_sha256": "evidence-hash",
    }
    requested = evaluate_gate(
        contract,
        review_ready,
        passing,
        source_hashes={"evidence_sha256": "evidence-hash"},
        requested_state="PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED",
        transition_authorization=approval,
    )
    assert (
        requested["maximum_evidence_supported_state"]
        == "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED"
    )
    assert (
        requested["transition_request"]["status"]
        == "REVIEWED_STATE_CHANGE_PR_REQUIRED"
    )
    assert requested["automatic_forward_transition_performed"] is False

    production_candidate = copy.deepcopy(state)
    production_candidate["promotion_state"] = (
        "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED"
    )
    persisted = evaluate_gate(contract, production_candidate, passing)
    assert persisted["rollback"]["triggered"] is False
    assert (
        persisted["effective_promotion_state"]
        == "PRODUCTION_CANDIDATE_USER_APPROVAL_REQUIRED"
    )


def test_advanced_canonical_state_rolls_back_when_forward_evidence_regresses() -> None:
    contract, state, evidence = _inputs()
    advanced = copy.deepcopy(state)
    advanced["promotion_state"] = "FORWARD_PAPER_REVIEW_READY"
    regressed = _passing_evidence(contract, evidence)
    regressed["forward_paper"]["resolved_126d_outcomes"] = (
        contract["forward_thresholds"]["minimum_resolved_126d_outcomes"] - 1
    )
    gate = evaluate_gate(contract, advanced, regressed)
    assert gate["maximum_evidence_supported_state"] == "FORWARD_PAPER_VALIDATING"
    assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
    assert "advanced_state_evidence_gate_regression" in gate["rollback"]["triggers"]
    assert gate["rollback"]["canonical_champion_preserved"] is True
    assert gate["rollback"]["paper_history_preserved"] is True


def test_canonical_consumers_and_workflows_use_the_single_gate() -> None:
    for rel in (
        "tools/build_run287_operating_scorecard.py",
        "tools/build_public_portfolio_dashboard.py",
        "tools/run_user_current_report.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "gate_for_consumer" in text, rel
    daily = (ROOT / ".github/workflows/daily_operating_selection_refresh.yml").read_text(encoding="utf-8")
    for token in (
        "python tools/run_run287_promotion_gate.py",
        "--state data_static/run287_promotion_state.json",
        "outputs/run287_promotion_gate/",
        "daily_run287_promotion_gate.log",
    ):
        assert token in daily, token
    pages = (ROOT / ".github/workflows/pages_deploy.yml").read_text(encoding="utf-8")
    assert "tools/run287_promotion_gate.py" in pages
    assert "data_static/run287_promotion_state.json" in pages
    public = json.loads((ROOT / "docs/public/data/dashboard.json").read_text(encoding="utf-8"))
    assert public["status"]["promotion_state"] == "RESEARCH_ONLY"
    assert public["status"]["rollback_triggered"] is False
    app = (ROOT / "docs/public/app.js").read_text(encoding="utf-8")
    assert "data.status?.promotion_state || data.status?.decision" in app


def test_runtime_overlay_negative_cash_snapshot_fails_closed() -> None:
    contract, state, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    ("2026-07-13", 100.0),
                    ("2026-07-14", -1.0),
                    ("2026-07-15", 100.0),
                ],
            )
        _finalize_valid_paper(paper)
        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 0
        assert overlaid["forward_paper"]["negative_cash_count"] == 0
        assert (
            overlaid["forward_paper"]["integrity_availability"][
                "negative_cash_count"
            ]
            == "UNAVAILABLE"
        )
        assert overlaid["forward_paper"]["duplicate_client_order_id_count"] == 0
        assert overlaid["forward_paper"]["duplicate_fill_count"] == 0
        assert overlaid["historical"]["scorecard_trusted"] is False
        for field, value in evidence["historical"].items():
            if field != "scorecard_trusted":
                assert overlaid["historical"][field] == value
        gate = evaluate_gate(contract, state, overlaid)
        assert gate["effective_promotion_state"] == "BLOCKED_OR_ROLLED_BACK"
        assert "integrity_error" in gate["rollback"]["triggers"]


def test_runtime_overlay_missing_paper_clears_tracked_runtime_evidence() -> None:
    contract, _, evidence = _inputs()
    stale = _passing_evidence(contract, evidence)
    with TemporaryDirectory() as tmp:
        overlaid = overlay_latest_run_evidence(stale, Path(tmp))
    assert overlaid["historical"]["scorecard_trusted"] is False
    for field in (
        "completed_market_sessions",
        "distinct_decision_weeks",
        "resolved_21d_outcomes",
        "resolved_63d_outcomes",
        "resolved_126d_outcomes",
    ):
        assert overlaid["forward_paper"][field] == 0
    for field in (
        "selection_evaluable",
        "exit_evaluable",
        "defense_evaluable",
        "reentry_evaluable",
    ):
        assert overlaid["forward_paper"][field] is False
    for field in (
        "future_close_count",
        "stale_substituted_close_count",
        "hash_chain_break_count",
        "lifecycle_silent_deletion_count",
    ):
        assert overlaid["forward_paper"][field] == 0
        assert (
            overlaid["forward_paper"]["integrity_availability"][field]
            == "UNAVAILABLE"
        )
    assert overlaid["candidate_id"] == "single-shadow-challenger"
    assert overlaid["accounts"]["challenger"] is not None
    assert overlaid["accounts"]["paired_decision_date_count"] == 0
    assert overlaid["accounts"]["runtime_pair_verified"] is False
    assert "runtime_paper_snapshot_missing" in overlaid["runtime_limitations"]
    gate = evaluate_gate(contract, read_json(DEFAULT_STATE), overlaid)
    assert gate["forward_paper_gate"]["review_ready"] is False
    assert gate["rollback"]["triggered"] is False
    assert all(
        value is False
        for value in gate["forward_paper_gate"]["zero_integrity_checks"].values()
    )


def test_equity_mark_weeks_cannot_inflate_verified_decision_weeks() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        mark_dates = [
            (stamp.date().isoformat(), 100.0)
            for stamp in mcal.get_calendar("NYSE").schedule(
                start_date="2027-06-14", end_date="2027-06-30"
            ).index
        ]
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper, portfolio, dates_and_cash=mark_dates
            )
        _finalize_valid_paper(paper)
        _write_valid_outcome_fixture(
            root,
            as_of_date=mark_dates[-1][0],
            decision_week_count=1,
        )
        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["latest_run_observation"]["distinct_decision_weeks"] > 1
        assert overlaid["forward_paper"]["distinct_decision_weeks"] == 1


def test_weekend_equity_row_cannot_count_as_a_market_session() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-26", 100.0)],
            )
        _finalize_valid_paper(paper)
        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 0
        assert overlaid["rollback"]["integrity_error"] is True
        assert any(
            "runtime_paper_missing_or_extra_nyse_session" in value
            or "runtime_paper_non_nyse_equity_date" in value
            or "not a valid NYSE session" in value
            for value in overlaid["runtime_limitations"]
        )


def test_missed_daily_mark_does_not_invalidate_later_paper_snapshot() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        schedule = [
            stamp.date().isoformat()
            for stamp in mcal.get_calendar("NYSE").schedule(
                start_date="2027-06-28", end_date="2027-06-30"
            ).index
        ]
        assert len(schedule) == 3
        persisted_marks = [(schedule[0], 100.0), (schedule[-1], 100.0)]
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=persisted_marks,
            )
        _finalize_valid_paper(paper)

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 2
        assert overlaid["rollback"]["integrity_error"] is False
        assert not any(
            "runtime_paper_missing_or_extra_nyse_session" in value
            for value in overlaid["runtime_limitations"]
        )


def test_materialized_effective_target_may_differ_from_published_source() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    ("2027-06-29", 100.0),
                    ("2027-06-30", 100.0),
                ],
                effective_target_distinct=True,
            )
        _finalize_valid_paper(paper)

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["rollback"]["integrity_error"] is False
        assert overlaid["forward_paper"]["completed_market_sessions"] == 2
        availability = overlaid["forward_paper"][
            "integrity_availability"
        ]
        assert all(
            availability[field] == "VERIFIED"
            for field in availability
            if field != "lifecycle_silent_deletion_count"
        )
        assert not any(
            "runtime_paper_manifest_publication_target_mismatch" in value
            for value in overlaid["runtime_limitations"]
        )


def test_skipped_outcome_still_observes_runtime_parent_anchor() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    ("2027-06-29", 100.0),
                    ("2027-06-30", 100.0),
                ],
            )
        _finalize_valid_paper(paper)

        anchor_path = (
            root / "run287_risk_outcome_parent_anchor" / "anchor.json"
        )
        anchor_path.parent.mkdir()
        anchor_path.write_text(
            json.dumps(
                {
                    "schema_version":
                        "run287-risk-outcome-parent-anchor-v1",
                    "status": "VERIFIED_EMPTY_PARENT",
                    "review_only": True,
                }
            ),
            encoding="utf-8",
        )
        outcome_path = (
            root / "run287_risk_outcome_archive" / "summary.json"
        )
        outcome_path.parent.mkdir()
        outcome_path.write_text(
            json.dumps(
                {
                    "schema_version":
                        "run287-risk-outcome-archive-v1",
                    "status": "SKIPPED_NO_DECISION_OBSERVATIONS",
                    "as_of_date": "2027-06-30",
                    "blockers": [],
                    "review_only": True,
                }
            ),
            encoding="utf-8",
        )

        anchor_sha256 = sha256_file(anchor_path)
        overlaid = overlay_latest_run_evidence(
            evidence,
            root,
            expected_risk_outcome_parent_anchor_sha256=anchor_sha256,
        )
        observed = overlaid["latest_run_observation"][
            "observed_file_hashes"
        ]
        assert observed[
            "run287_risk_outcome_parent_anchor/anchor.json"
        ] == anchor_sha256
        assert (
            overlaid["rollback"]["integrity_error"] is False
        )
        assert (
            "runtime_risk_outcome_validation_failed:"
            "runtime_risk_outcome_summary_not_ready"
            in overlaid["runtime_limitations"]
        )


def test_durable_replay_marks_never_count_as_forward_sessions() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        sessions = [
            "2026-04-06",
            "2026-04-07",
            "2026-04-08",
            "2026-04-09",
        ]
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    (session, 100.0) for session in sessions
                ],
            )
        write_prices(
            root / "prices",
            "AAA",
            sessions,
            [100.0, 101.0, 102.0, 103.0],
        )
        write_prices(
            root / "prices",
            "BBB",
            sessions,
            [100.0, 101.0, 102.0, 103.0],
        )
        write_replay_price_manifest(root, "2026-04-08")
        durable = (
            paper
            / "replay_price_evidence"
            / "2026-04-08"
        )
        shutil.copytree(root / "prices", durable)
        _finalize_valid_paper(paper)

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert (
            overlaid["forward_paper"]["completed_market_sessions"]
            == 3
        )
        observation = overlaid["latest_run_observation"]
        assert observation["raw_common_equity_dates"] == 4
        assert observation["replay_sessions_excluded"] == 1
        assert observation["completed_market_sessions"] == 3

        (durable / next(
            path.name
            for path in durable.iterdir()
            if path.name != "manifest.json"
        )).unlink()
        (paper / "snapshot_integrity.json").unlink()
        write_integrity_manifest(
            paper,
            as_of_date=sessions[-1],
        )
        blocked = overlay_latest_run_evidence(evidence, root)
        assert (
            blocked["forward_paper"]["completed_market_sessions"]
            == 0
        )
        assert blocked["rollback"]["integrity_error"] is True


def test_root_and_portfolio_integrity_counts_must_reconcile() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)

        manifests: dict[str, dict] = {}
        for portfolio in ("main", "concentrated"):
            path = paper / portfolio / "manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["integrity"] = {"negative_cash_count": 0}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            manifests[portfolio] = manifest

        accepted_path = paper / "accepted_publication.json"
        accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
        for portfolio in ("main", "concentrated"):
            accepted["portfolios"][portfolio]["ledger_manifest_sha256"] = (
                sha256_file(paper / portfolio / "manifest.json")
            )
        accepted_path.write_text(json.dumps(accepted), encoding="utf-8")

        summary_path = paper / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["portfolios"] = manifests
        summary["integrity"] = {"negative_cash_count": 1}
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        write_integrity_manifest(paper, as_of_date="2027-06-30")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["negative_cash_count"] == 0
        assert (
            overlaid["forward_paper"]["integrity_availability"][
                "negative_cash_count"
            ]
            == "UNAVAILABLE"
        )
        assert any(
            "runtime_integrity_manifest_summary_mismatch:negative_cash_count"
            in value
            for value in overlaid["runtime_limitations"]
        )


def test_partial_portfolio_integrity_reporting_is_rejected() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)

        main_manifest_path = paper / "main" / "manifest.json"
        main_manifest = json.loads(
            main_manifest_path.read_text(encoding="utf-8")
        )
        main_manifest["integrity"] = {"negative_cash_count": 1}
        main_manifest_path.write_text(
            json.dumps(main_manifest), encoding="utf-8"
        )
        concentrated_manifest = json.loads(
            paper.joinpath(
                "concentrated", "manifest.json"
            ).read_text(encoding="utf-8")
        )

        accepted_path = paper / "accepted_publication.json"
        accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
        accepted["portfolios"]["main"]["ledger_manifest_sha256"] = sha256_file(
            main_manifest_path
        )
        accepted_path.write_text(json.dumps(accepted), encoding="utf-8")

        summary_path = paper / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["portfolios"] = {
            "main": main_manifest,
            "concentrated": concentrated_manifest,
        }
        summary["integrity"] = {"negative_cash_count": 0}
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        write_integrity_manifest(paper, as_of_date="2027-06-30")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["rollback"]["integrity_error"] is True
        assert (
            overlaid["forward_paper"]["integrity_availability"][
                "negative_cash_count"
            ]
            == "UNAVAILABLE"
        )
        assert any(
            "runtime_integrity_manifest_partial_reporting:negative_cash_count"
            in value
            for value in overlaid["runtime_limitations"]
        )


def test_cross_portfolio_client_order_id_collision_is_detected() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        dates = [("2027-06-29", 100.0), ("2027-06-30", 100.0)]
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=dates,
            )
        _finalize_valid_paper(paper)

        manifests: dict[str, dict] = {}
        for portfolio in ("main", "concentrated"):
            event = {
                "portfolio_kind": portfolio,
                "date": "2027-06-30",
                "signal_date": "2027-06-29",
                "ticker": "AAA",
                "execution_ticker": "AAA",
                "side": "BUY",
                "requested_quantity": 1.0,
                "target_weight": 0.0,
                "sell_taxonomy": "NOT_APPLICABLE",
                "sell_taxonomy_reason": "",
                "fill_mode": "next_close",
                "cost_bps_per_side": 25.0,
                "client_order_id": "shared-cross-portfolio-client-id",
                "idempotency_key": "shared-idempotency-key",
                "order_batch_id": "batch",
                "target_hash": "1" * 64,
                "execution_status": "SIMULATED_REJECTED",
                "review_only": True,
                "simulated": True,
                "live_trading_enabled": False,
                "production_mutation_allowed": False,
                "event_sequence": 1,
                "event_id": "shared-event-id",
                "previous_event_hash": "0" * 64,
                "event_type": "REJECTION",
                "event_date": "2027-06-30",
                "event_reason": "insufficient_cash_or_position",
            }
            event["event_hash"] = paper_event_hash(
                event_payload_for_hash(event)
            )
            event_path = paper / portfolio / "rejections.csv"
            pd.DataFrame([event]).to_csv(event_path, index=False)
            round_tripped = pd.read_csv(event_path).iloc[0].to_dict()
            round_tripped["previous_event_hash"] = "0" * 64
            event["event_hash"] = paper_event_hash(
                event_payload_for_hash(round_tripped)
            )
            pd.DataFrame([event]).to_csv(event_path, index=False)
            for name in ("state_meta.json", "manifest.json"):
                path = paper / portfolio / name
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload.update(
                    {
                        "rejection_count": 1,
                        "event_sequence": 1,
                        "event_chain_hash": event["event_hash"],
                    }
                )
                path.write_text(json.dumps(payload), encoding="utf-8")
                if name == "manifest.json":
                    manifests[portfolio] = payload

        accepted_path = paper / "accepted_publication.json"
        accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
        for portfolio in ("main", "concentrated"):
            accepted["portfolios"][portfolio]["ledger_manifest_sha256"] = (
                sha256_file(paper / portfolio / "manifest.json")
            )
        accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
        summary_path = paper / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["portfolios"] = manifests
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        write_integrity_manifest(paper, as_of_date="2027-06-30")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert (
            overlaid["forward_paper"]["duplicate_client_order_id_count"] == 1
        )
        assert (
            overlaid["forward_paper"]["integrity_availability"][
                "duplicate_client_order_id_count"
            ]
            == "VERIFIED"
        )
        gate = evaluate_gate(
            read_json(DEFAULT_CONTRACT),
            read_json(DEFAULT_STATE),
            overlaid,
        )
        assert (
            "forward_integrity:duplicate_client_order_id_count"
            in gate["rollback"]["triggers"]
        )


def test_late_backfilled_risk_signals_do_not_count_for_promotion() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    ("2027-06-29", 100.0),
                    ("2027-06-30", 100.0),
                ],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(
            root,
            as_of_date="2027-06-30",
            late_signal_backfill=True,
        )

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["distinct_decision_weeks"] == 0
        assert overlaid["forward_paper"]["resolved_21d_outcomes"] == 0
        assert overlaid["forward_paper"]["resolved_63d_outcomes"] == 0
        assert overlaid["forward_paper"]["resolved_126d_outcomes"] == 0
        assert any(
            value
            == "runtime_risk_outcome_late_signal_backfill_excluded:13"
            for value in overlaid["runtime_limitations"]
        )


def test_equity_history_cannot_be_prefix_truncated_and_resealed() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        dates = [
            (stamp.date().isoformat(), 100.0)
            for stamp in mcal.get_calendar("NYSE").schedule(
                start_date="2027-06-28", end_date="2027-06-30"
            ).index
        ]
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=dates,
            )
        _finalize_valid_paper(paper)
        for portfolio in ("main", "concentrated"):
            curve_path = paper / portfolio / "equity_curve.csv"
            curve = pd.read_csv(curve_path)
            curve.iloc[1:].to_csv(curve_path, index=False)
        write_integrity_manifest(paper, as_of_date=dates[-1][0])

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 0
        assert overlaid["rollback"]["integrity_error"] is True
        assert any(
            "runtime_paper_duplicate_equity_date" in value
            for value in overlaid["runtime_limitations"]
        )


def test_unsafe_paper_summary_is_not_accepted_as_runtime_evidence() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        summary_path = paper / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["live_trading_enabled"] = True
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        write_integrity_manifest(paper, as_of_date="2027-06-30")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 0
        assert overlaid["rollback"]["integrity_error"] is True
        assert any(
            "runtime_paper_summary_contract_invalid" in value
            for value in overlaid["runtime_limitations"]
        )


def test_unsafe_accepted_transaction_mode_is_rejected() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        accepted_path = paper / "accepted_publication.json"
        accepted = json.loads(accepted_path.read_text(encoding="utf-8"))
        accepted["transaction_mode"] = "LIVE_EXECUTION"
        accepted_path.write_text(json.dumps(accepted), encoding="utf-8")
        write_integrity_manifest(paper, as_of_date="2027-06-30")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["completed_market_sessions"] == 0
        assert overlaid["rollback"]["integrity_error"] is True
        assert any(
            "accepted publication contract invalid" in value
            for value in overlaid["runtime_limitations"]
        )


def test_self_asserted_minimal_scorecard_never_becomes_trusted() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        scorecard_dir = root / "run287_operating_scorecard"
        scorecard_dir.mkdir()
        scorecard_dir.joinpath("operating_scorecard.json").write_text(
            json.dumps(
                {
                    "schema_version": "run287-operating-scorecard-v1",
                    "scorecard_trusted": True,
                    "scorecard_trust_blockers": [],
                    "integrity_errors": [],
                }
            ),
            encoding="utf-8",
        )
        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["historical"]["scorecard_trusted"] is False
        assert any(
            "runtime_scorecard_validation_failed:"
            "runtime_scorecard_contract_invalid" in value
            for value in overlaid["runtime_limitations"]
        )


def test_ready_outcome_without_schema_is_ignored() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(root, as_of_date="2027-06-30")
        outcome = json.loads(
            outcome_dir.joinpath("summary.json").read_text(encoding="utf-8")
        )
        outcome.pop("schema_version")
        outcome_dir.joinpath("summary.json").write_text(
            json.dumps(outcome), encoding="utf-8"
        )
        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["resolved_21d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_schema_invalid" in value
            for value in overlaid["runtime_limitations"]
        )


def test_decision_archive_manifest_must_match_its_histories() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(root, as_of_date="2027-06-30")

        archive_manifest_path = (
            root / "run287_decision_observation_archive" / "manifest.json"
        )
        archive_manifest = json.loads(
            archive_manifest_path.read_text(encoding="utf-8")
        )
        archive_manifest["decision_dates"] = []
        archive_manifest_path.write_text(
            json.dumps(archive_manifest), encoding="utf-8"
        )
        outcome_path = outcome_dir / "summary.json"
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["source_inputs"]["decision_archive_manifest_sha256"] = sha256_file(
            archive_manifest_path
        )
        outcome_path.write_text(json.dumps(outcome), encoding="utf-8")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["resolved_126d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_decision_archive_index_mismatch" in value
            for value in overlaid["runtime_limitations"]
        )


def test_decision_archive_child_counts_and_set_hashes_are_recomputed() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(root, as_of_date="2027-06-30")

        archive = root / "run287_decision_observation_archive"
        decision_path = archive / "decision_history.jsonl"
        decision_rows = [
            json.loads(line)
            for line in decision_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        decision_rows[0]["candidate_count"] = 2
        decision_path.write_text(
            "\n".join(
                json.dumps(row, sort_keys=True, separators=(",", ":"))
                for row in decision_rows
            )
            + "\n",
            encoding="utf-8",
        )
        archive_manifest_path = archive / "manifest.json"
        archive_manifest = json.loads(
            archive_manifest_path.read_text(encoding="utf-8")
        )
        archive_manifest["outputs"]["decision_history"].update(
            {
                "bytes": decision_path.stat().st_size,
                "sha256": sha256_file(decision_path),
            }
        )
        archive_manifest_path.write_text(
            json.dumps(archive_manifest), encoding="utf-8"
        )
        outcome_path = outcome_dir / "summary.json"
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["source_inputs"]["decision_archive_manifest_sha256"] = (
            sha256_file(archive_manifest_path)
        )
        outcome_path.write_text(json.dumps(outcome), encoding="utf-8")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["resolved_21d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_decision_archive_aggregate_mismatch:"
            "candidate_count" in value
            for value in overlaid["runtime_limitations"]
        )


def test_completed_outcome_before_horizon_elapsed_is_rejected() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(root, as_of_date="2027-06-30")

        event_path = outcome_dir / "risk_outcome_events.jsonl"
        events = [
            json.loads(line)
            for line in event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        changed = False
        for event in events:
            if (
                event.get("event_type") == "forward_outcome_observed"
                and event.get("horizon_trading_days") == 126
            ):
                event["evaluated_as_of_date"] = event["decision_date"]
                changed = True
                break
        assert changed
        event_path.write_text(
            "\n".join(
                json.dumps(event, sort_keys=True, separators=(",", ":"))
                for event in events
            )
            + "\n",
            encoding="utf-8",
        )
        outcome_path = outcome_dir / "summary.json"
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["outputs"]["event_log_sha256"] = sha256_file(event_path)
        outcome_path.write_text(json.dumps(outcome), encoding="utf-8")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["resolved_126d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_completed_event_not_reproducible:126d"
            in value
            for value in overlaid["runtime_limitations"]
        )


def test_outcome_economics_are_recomputed_from_hash_bound_price_cache() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        _write_valid_outcome_fixture(root, as_of_date="2027-06-30")

        cache_path = (
            root
            / "run287_risk_outcome_price_cache"
            / px_cache_name("AAA")
        )
        prices = pd.read_parquet(cache_path)
        prices.loc[prices.index[0], "Adj Close"] += 1.0
        prices.to_parquet(cache_path)

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["resolved_21d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_price_cache_manifest_mismatch:AAA" in value
            for value in overlaid["runtime_limitations"]
        )


def test_completed_outcomes_survive_append_only_cache_growth_but_not_revision() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(
            root,
            as_of_date="2027-06-30",
        )
        cache_root = root / "run287_risk_outcome_price_cache"
        manifest_path = cache_root / "replay_price_cache_manifest.json"
        summary_path = outcome_dir / "summary.json"

        def reseal_cache() -> None:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            for ticker in ("AAA", "SPY"):
                path = cache_root / px_cache_name(ticker)
                manifest["cache_files"][ticker]["sha256"] = sha256_file(path)
                manifest["cache_files"][ticker]["bytes"] = path.stat().st_size
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            summary = json.loads(
                summary_path.read_text(encoding="utf-8")
            )
            summary["source_inputs"]["price_cache_manifest_sha256"] = (
                sha256_file(manifest_path)
            )
            summary_path.write_text(json.dumps(summary), encoding="utf-8")

        for ticker in ("AAA", "SPY"):
            path = cache_root / px_cache_name(ticker)
            frame = pd.read_parquet(path)
            next_index = pd.Timestamp(frame.index[-1]) + pd.Timedelta(days=1)
            extra = frame.iloc[[-1]].copy()
            extra.index = pd.DatetimeIndex([next_index])
            extra["Open"] = extra["Open"] + 0.1
            extra["Close"] = extra["Close"] + 0.1
            extra["Adj Close"] = extra["Adj Close"] + 0.1
            pd.concat([frame, extra]).to_parquet(path)
        reseal_cache()

        appended = overlay_latest_run_evidence(evidence, root)
        assert appended["forward_paper"]["resolved_21d_outcomes"] == 13
        assert appended["forward_paper"]["resolved_63d_outcomes"] == 13
        assert appended["forward_paper"]["resolved_126d_outcomes"] == 13

        revised_path = cache_root / px_cache_name("AAA")
        revised = pd.read_parquet(revised_path)
        revised.iloc[0, revised.columns.get_loc("Adj Close")] += 1.0
        revised.to_parquet(revised_path)
        reseal_cache()
        revised_evidence = overlay_latest_run_evidence(evidence, root)
        assert revised_evidence["forward_paper"]["resolved_21d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_completed_event:" in value
            for value in revised_evidence["runtime_limitations"]
        )


def test_coordinated_outcome_reseal_cannot_rewrite_accepted_event_prefix() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[("2027-06-30", 100.0)],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(
            root,
            as_of_date="2027-06-30",
        )
        cache_root = root / "run287_risk_outcome_price_cache"
        event_path = outcome_dir / "risk_outcome_events.jsonl"
        manifest_path = cache_root / "replay_price_cache_manifest.json"
        summary_path = outcome_dir / "summary.json"

        revised_path = cache_root / px_cache_name("AAA")
        revised = pd.read_parquet(revised_path)
        revised.iloc[0, revised.columns.get_loc("Adj Close")] += 1.0
        revised.to_parquet(revised_path)

        original_events = [
            json.loads(line)
            for line in event_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        signals = {
            str(event["observation_id"]): event
            for event in original_events
            if event.get("event_type") == "risk_signal_observed"
        }
        ticker_frame, _ = load_cached_prices(cache_root, "AAA")
        benchmark_frame, _ = load_cached_prices(cache_root, "SPY")
        sessions = load_nyse_sessions(
            pd.Timestamp(
                min(str(signal["decision_date"]) for signal in signals.values())
            ),
            pd.Timestamp("2027-06-30"),
        )
        assert sessions is not None
        ticker_hash = sha256_file(revised_path)
        benchmark_hash = sha256_file(cache_root / px_cache_name("SPY"))
        regenerated: list[dict] = []
        evaluations: dict[str, dict[int, str]] = {
            observation_id: {} for observation_id in signals
        }
        for event in original_events:
            if event.get("event_type") != "forward_outcome_observed":
                regenerated.append(event)
                continue
            observation_id = str(event["observation_id"])
            horizon = int(event["horizon_trading_days"])
            replacement, status = outcome_event(
                signals[observation_id],
                horizon,
                ticker_frame,
                benchmark_frame,
                sessions,
                as_of_date=pd.Timestamp(event["evaluated_as_of_date"]),
                recorded_at=str(event["recorded_at_utc"]),
                ticker_hash=ticker_hash,
                benchmark_hash=benchmark_hash,
            )
            assert replacement is not None and status == "completed"
            regenerated.append(replacement)
            evaluations[observation_id][horizon] = status
        event_path.write_text(
            "\n".join(
                json.dumps(event, sort_keys=True, separators=(",", ":"))
                for event in regenerated
            )
            + "\n",
            encoding="utf-8",
        )
        build_current_status(
            regenerated,
            evaluations,
            (1, 5, 21, 63, 126),
        ).to_csv(outcome_dir / "current_status.csv", index=False)

        cache_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        for ticker in ("AAA", "SPY"):
            path = cache_root / px_cache_name(ticker)
            cache_manifest["cache_files"][ticker].update(
                {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            )
        manifest_path.write_text(
            json.dumps(cache_manifest), encoding="utf-8"
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["source_inputs"]["price_cache_manifest_sha256"] = (
            sha256_file(manifest_path)
        )
        summary["outputs"]["event_log_sha256"] = sha256_file(event_path)
        summary["outputs"]["current_status_sha256"] = sha256_file(
            outcome_dir / "current_status.csv"
        )
        summary["outcome_chain"].update(
            {
                "current_event_log_sha256": sha256_file(event_path),
                "current_event_log_bytes": event_path.stat().st_size,
                "current_event_count": len(regenerated),
                "trusted_event_count": len(regenerated),
            }
        )
        summary_path.write_text(json.dumps(summary), encoding="utf-8")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["forward_paper"]["resolved_21d_outcomes"] == 0
        assert overlaid["forward_paper"]["resolved_63d_outcomes"] == 0
        assert overlaid["forward_paper"]["resolved_126d_outcomes"] == 0
        assert overlaid["rollback"]["integrity_error"] is True
        assert any(
            "runtime_risk_outcome_event_prefix_rewrite" in value
            for value in overlaid["runtime_limitations"]
        )


def test_runtime_overlay_binds_scorecard_and_all_forward_horizons() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    ("2027-06-29", 100.0),
                    ("2027-06-30", 100.0),
                ],
            )
        paper_manifest = _finalize_valid_paper(paper)

        scorecard_dir = root / "run287_operating_scorecard"
        scorecard_dir.mkdir()
        scorecard_path = scorecard_dir / "operating_scorecard.json"
        source_registry = read_json(
            ROOT / "docs" / "run287_operating_scorecard_sources.json"
        )
        runtime_registry = copy.deepcopy(source_registry)
        for source in runtime_registry["sources"]:
            if source["id"] == "current_paper_summary":
                source["path"] = str(paper / "summary.json")
            elif source["id"] == "current_paper_integrity":
                source["path"] = str(paper / "snapshot_integrity.json")
        scorecard = build_scorecard(
            runtime_registry,
            source_registry_path=(
                ROOT / "docs" / "run287_operating_scorecard_sources.json"
            ),
            promotion_state_path=DEFAULT_STATE,
        )
        scorecard_path.write_text(
            json.dumps(scorecard, allow_nan=False),
            encoding="utf-8",
        )

        outcome_dir = _write_valid_outcome_fixture(root, as_of_date="2027-06-30")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert overlaid["historical"]["scorecard_trusted"] is True
        assert overlaid["forward_paper"]["resolved_21d_outcomes"] == 13
        assert overlaid["forward_paper"]["resolved_63d_outcomes"] == 13
        assert overlaid["forward_paper"]["resolved_126d_outcomes"] == 13
        assert overlaid["forward_paper"]["distinct_decision_weeks"] == 13
        assert overlaid["accounts"]["challenger"] is None
        assert overlaid["accounts"]["paired_decision_date_count"] == 0
        assert overlaid["accounts"]["runtime_pair_verified"] is False
        assert overlaid["forward_paper"]["selection_evaluable"] is False

        original_scorecard = scorecard_path.read_text(encoding="utf-8")
        pruned_scorecard = json.loads(original_scorecard)
        pruned_scorecard["metrics"] = [pruned_scorecard["metrics"][0]]
        pruned_scorecard["metrics"][0]["value"] = 999999
        first_headline = sorted(pruned_scorecard["headline_performance"])[0]
        pruned_scorecard["headline_performance"] = {
            first_headline: pruned_scorecard["headline_performance"][
                first_headline
            ]
        }
        pruned_scorecard["headline_performance"][first_headline]["cagr"] = (
            999999
        )
        scorecard_path.write_text(
            json.dumps(pruned_scorecard), encoding="utf-8"
        )
        pruned = overlay_latest_run_evidence(evidence, root)
        assert pruned["historical"]["scorecard_trusted"] is False
        assert any(
            "runtime_scorecard_rebuild_mismatch" in value
            for value in pruned["runtime_limitations"]
        )
        scorecard_path.write_text(original_scorecard, encoding="utf-8")

        forged_provenance = json.loads(original_scorecard)
        latest_metric = next(
            row
            for row in forged_provenance["metrics"]
            if row["metric_id"] == "latest_close_operating_return"
        )
        latest_metric["provenance"]["source_sha256"] = "0" * 64
        scorecard_path.write_text(
            json.dumps(forged_provenance),
            encoding="utf-8",
        )
        provenance_blocked = overlay_latest_run_evidence(
            evidence,
            root,
        )
        assert provenance_blocked["historical"][
            "scorecard_trusted"
        ] is False
        assert any(
            "runtime_scorecard_metric_provenance_invalid:"
            "latest_close_operating_return"
            in value
            for value in provenance_blocked["runtime_limitations"]
        )
        scorecard_path.write_text(original_scorecard, encoding="utf-8")

        forged_outcome = json.loads(
            outcome_dir.joinpath("summary.json").read_text(encoding="utf-8")
        )
        forged_outcome["horizon_status_counts"]["21d"]["completed"] = 999
        outcome_dir.joinpath("summary.json").write_text(
            json.dumps(forged_outcome), encoding="utf-8"
        )
        forged_counts = overlay_latest_run_evidence(evidence, root)
        assert forged_counts["forward_paper"]["resolved_21d_outcomes"] == 0
        assert any(
            "runtime_risk_outcome_summary_counts_mismatch:21d" in value
            for value in forged_counts["runtime_limitations"]
        )

        # Restore the attested summary, then mutate a hashed output.
        forged_outcome["horizon_status_counts"]["21d"]["completed"] = 13
        outcome_dir.joinpath("summary.json").write_text(
            json.dumps(forged_outcome), encoding="utf-8"
        )
        outcome_dir.joinpath("current_status.csv").write_text(
            outcome_dir.joinpath("current_status.csv").read_text(encoding="utf-8")
            + "forged,2026-07-14,2026-W29,completed,completed,completed\n",
            encoding="utf-8",
        )
        forged_hash = overlay_latest_run_evidence(evidence, root)
        assert forged_hash["forward_paper"]["resolved_21d_outcomes"] == 0
        assert any(
            "risk_outcome_current_status_sha256_mismatch" in value
            for value in forged_hash["runtime_limitations"]
        )

        forged = json.loads(scorecard_path.read_text(encoding="utf-8"))
        forged["runtime_trust_manifest"]["paper_snapshot"]["snapshot_hash"] = "wrong"
        scorecard_path.write_text(json.dumps(forged), encoding="utf-8")
        blocked = overlay_latest_run_evidence(evidence, root)
        assert blocked["historical"]["scorecard_trusted"] is False
        assert any(
            value.startswith("runtime_scorecard_validation_failed:")
            for value in blocked["runtime_limitations"]
        )


def test_runtime_jsonl_duplicate_keys_fail_closed() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "events.jsonl"
        path.write_text(
            (
                '{"event_id":"first","event_id":"second",'
                '"event_type":"risk_signal_observed"}\n'
            ),
            encoding="utf-8",
        )
        try:
            _jsonl_rows(path)
        except ValueError as exc:
            assert "duplicate_json_key:event_id" in str(exc), str(exc)
        else:
            raise AssertionError("promotion parser accepted duplicate JSON key")


def test_legacy_parent_quarantine_is_exposed_to_consumers() -> None:
    _, _, evidence = _inputs()
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        paper = root / "daily_simulated_fill_ledger"
        for portfolio in ("main", "concentrated"):
            _write_valid_paper_portfolio(
                paper,
                portfolio,
                dates_and_cash=[
                    ("2027-06-29", 100.0),
                    ("2027-06-30", 100.0),
                ],
            )
        _finalize_valid_paper(paper)
        outcome_dir = _write_valid_outcome_fixture(
            root,
            as_of_date="2027-06-30",
        )
        event_path = outcome_dir / "risk_outcome_events.jsonl"
        event_count = len(event_path.read_text(encoding="utf-8").splitlines())
        anchor_path = (
            root / "run287_risk_outcome_parent_anchor" / "anchor.json"
        )
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor.update(
            {
                "parent_acceptance_status": "QUARANTINED_LEGACY",
                "parent_accepted_manifest_sha256": "",
                "parent_accepted_manifest_bytes": 0,
                "parent_accepted_manifest_as_of_date": "",
                "carried_quarantined_prefix_event_count": event_count,
            }
        )
        anchor_path.write_text(json.dumps(anchor), encoding="utf-8")
        summary_path = outcome_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["outcome_chain"].update(
            {
                "parent_anchor_sha256": sha256_file(anchor_path),
                "parent_acceptance_status": "QUARANTINED_LEGACY",
                "parent_accepted_manifest_sha256": "",
                "parent_accepted_manifest_bytes": 0,
                "parent_accepted_manifest_as_of_date": "",
                "carried_quarantined_prefix_event_count": event_count,
                "trusted_event_count": 0,
            }
        )
        summary_path.write_text(json.dumps(summary), encoding="utf-8")

        overlaid = overlay_latest_run_evidence(evidence, root)
        assert (
            "runtime_risk_outcome_parent_legacy_quarantined"
            in overlaid["runtime_limitations"]
        )


if __name__ == "__main__":
    tests = [value for key, value in sorted(globals().items()) if key.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"run287_promotion_gate_smoke: {len(tests)} passed")
