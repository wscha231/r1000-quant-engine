#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import run_run287_current_selector_no_write as selector


VALUATION_DATE = "2026-07-13"
DECISION_TIME = "2026-07-13T21:00:00+00:00"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def output_record(manifest_path: Path, output_path: Path) -> dict[str, str]:
    return {
        "path": output_path.relative_to(manifest_path.parent).as_posix(),
        "sha256": selector.sha256(output_path),
    }


def manifest_args(
    root: Path,
    *,
    context_ticker: str = "AAA",
    scored_ticker: str = "AAA",
    score_available_from: str = DECISION_TIME,
) -> tuple[argparse.Namespace, Path]:
    manifest_root = root / "relocated" / "manifests"

    decision_manifest = manifest_root / "decision" / "manifest.json"
    context_path = decision_manifest.parent / "payload" / "selection_context.parquet"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": [context_ticker]}).to_parquet(context_path, index=False)
    write_json(
        decision_manifest,
        {
            "status": "READY_COMPLETE_CURRENT_DECISION_FRAME",
            "valuation_price_cutoff_date": VALUATION_DATE,
            "feature_available_from": "2026-07-13T20:30:00+00:00",
            "decision_time_utc": DECISION_TIME,
            "outputs": {
                "selection_context": output_record(decision_manifest, context_path)
            },
        },
    )

    score_stack_manifest = manifest_root / "score" / "manifest.json"
    score_stack_path = (
        score_stack_manifest.parent / "payload" / "ticker_order_score_stack.csv"
    )
    score_stack_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ticker": [context_ticker],
            "registered_ranking_eligible": [True],
        }
    ).to_csv(score_stack_path, index=False)
    write_json(
        score_stack_manifest,
        {
            "status": "READY_CURRENT_DECISION_SCORE_STACK_ELIGIBILITY_AUDIT_NONRANKING",
            "valuation_price_cutoff_date": VALUATION_DATE,
            "outputs": {
                "ticker_order_score_stack": output_record(
                    score_stack_manifest, score_stack_path
                )
            },
        },
    )

    crisis_manifest = manifest_root / "crisis" / "manifest.json"
    crisis_path = crisis_manifest.parent / "payload" / "current_crisis_state.csv"
    crisis_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": [VALUATION_DATE], "state": ["NORMAL"]}).to_csv(
        crisis_path, index=False
    )
    write_json(
        crisis_manifest,
        {
            "status": "READY_CURRENT_CRISIS_STATE_NONSELECTING",
            "valuation_price_cutoff_date": VALUATION_DATE,
            "outputs": {
                "current_crisis_state": output_record(crisis_manifest, crisis_path)
            },
        },
    )

    price_manifest = manifest_root / "price" / "manifest.json"
    price_payload = price_manifest.parent / "payload"
    price_payload.mkdir(parents=True, exist_ok=True)
    provider_path = price_payload / "provider_price_overlap.parquet"
    pd.DataFrame(
        {
            "ticker": [scored_ticker],
            "Date": [VALUATION_DATE],
            "Close": [100.0],
        }
    ).to_parquet(provider_path, index=False)
    scored_path = price_payload / "scored_latest.csv"
    pd.DataFrame(
        {
            "ticker": [scored_ticker],
            "px": [100.0],
            "score_total": [1.0],
            "mom_1m": [0.01],
            "mom_3m": [0.02],
            "mom_6m": [0.03],
            "mom_12m": [0.04],
            "relative_strength_composite": [0.05],
            "valuation_price_cutoff_date": [VALUATION_DATE],
            "feature_available_from": ["2026-07-13T20:30:00+00:00"],
        }
    ).to_csv(scored_path, index=False)
    ticker_set_sha256 = selector.core_candidate_ticker_set_sha256([scored_ticker])
    core_coverage, coverage_failures = selector.core_candidate_coverage_for_path(
        scored_path,
        minimum_ratio=0.98,
        expected_row_count=1,
        expected_valuation_date=VALUATION_DATE,
        decision_time_utc=DECISION_TIME,
        expected_ticker_set_sha256=ticker_set_sha256,
    )
    assert coverage_failures == []
    assert core_coverage["passed"] is True
    write_json(
        price_manifest,
        {
            "schema_version": "run287-scored-latest-refresh-v4",
            "status": "READY_RESEARCH_SCORED_LATEST",
            "session_date": VALUATION_DATE,
            "score_available_from": score_available_from,
            "coverage": {
                "pre_lifecycle_context_count": 1,
                "post_lifecycle_context_count": 1,
                "lifecycle_excluded_count": 0,
                "current_context_count": 1,
                "exact_session_close_count": 1,
            },
            "core_candidate_coverage": core_coverage,
            "outputs": {
                "provider_price_overlap.parquet": output_record(
                    price_manifest, provider_path
                ),
                "scored_latest.csv": output_record(price_manifest, scored_path),
            },
        },
    )

    macro_manifest = manifest_root / "macro" / "manifest.json"
    write_json(
        macro_manifest,
        {
            "status": "READY_CONSERVATIVE_MACRO_SIDECAR",
            "valuation_close_date": VALUATION_DATE,
        },
    )

    soxx_manifest = manifest_root / "soxx" / "manifest.json"
    soxx_path = soxx_manifest.parent / "payload" / "soxx.csv"
    soxx_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": [VALUATION_DATE], "close": [100.0]}).to_csv(
        soxx_path, index=False
    )
    write_json(
        soxx_manifest,
        {
            "status": "READY_SELECTOR_BENCHMARK_PRICE_NONSELECTING",
            "valuation_price_cutoff_date": VALUATION_DATE,
            "outputs": {"price_file": output_record(soxx_manifest, soxx_path)},
        },
    )

    selector_contract_manifest = manifest_root / "selector_contract.json"
    write_json(
        selector_contract_manifest,
        {"status": "READY_CURRENT_SELECTOR_CONTRACT_AUDIT_NONSELECTING"},
    )
    pinned_import_manifest = manifest_root / "pinned_import.json"
    write_json(
        pinned_import_manifest,
        {
            "status": "READY_PINNED_POLICY_IMPORT_NONSELECTING",
            "pinned_source_commit": selector.POLICY_COMMIT,
        },
    )
    target_generation_manifest = manifest_root / "target_generation.json"
    write_json(
        target_generation_manifest,
        {"code": {"github_sha": selector.POLICY_COMMIT}, "env": {}},
    )

    main_prior_book = root / "prior" / "main.csv"
    concentrated_prior_book = root / "prior" / "concentrated.csv"
    main_prior_book.parent.mkdir(parents=True, exist_ok=True)
    prior = pd.DataFrame(
        {
            "rebalance_date": [VALUATION_DATE],
            "ticker": ["CASH"],
            "weight": [1.0],
        }
    )
    prior.to_csv(main_prior_book, index=False)
    prior.to_csv(concentrated_prior_book, index=False)

    holding_watch_csv = root / "holding" / "watch.csv"
    holding_watch_csv.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": [context_ticker]}).to_csv(
        holding_watch_csv, index=False
    )
    holding_watch_summary = root / "holding" / "summary.json"
    write_json(
        holding_watch_summary,
        {
            "status": "READY_REVIEW_ONLY",
            "as_of_date": VALUATION_DATE,
            "available_from": DECISION_TIME,
            "output_hashes": {
                "holding_risk_watch_sha256": selector.sha256(holding_watch_csv)
            },
        },
    )

    macro_price_cache = root / "macro_cache"
    macro_price_cache.mkdir()
    args = argparse.Namespace(
        decision_manifest=str(decision_manifest),
        expected_decision_sha256=selector.sha256(decision_manifest),
        score_stack_manifest=str(score_stack_manifest),
        expected_score_stack_sha256=selector.sha256(score_stack_manifest),
        crisis_manifest=str(crisis_manifest),
        expected_crisis_sha256=selector.sha256(crisis_manifest),
        price_manifest=str(price_manifest),
        expected_price_sha256=selector.sha256(price_manifest),
        macro_manifest=str(macro_manifest),
        expected_macro_sha256=selector.sha256(macro_manifest),
        soxx_manifest=str(soxx_manifest),
        expected_soxx_sha256=selector.sha256(soxx_manifest),
        selector_contract_manifest=str(selector_contract_manifest),
        expected_selector_contract_sha256=selector.sha256(
            selector_contract_manifest
        ),
        pinned_import_manifest=str(pinned_import_manifest),
        expected_pinned_import_sha256=selector.sha256(pinned_import_manifest),
        target_generation_manifest=str(target_generation_manifest),
        expected_target_generation_sha256=selector.sha256(
            target_generation_manifest
        ),
        main_prior_book=str(main_prior_book),
        expected_main_prior_book_sha256=selector.sha256(main_prior_book),
        concentrated_prior_book=str(concentrated_prior_book),
        expected_concentrated_prior_book_sha256=selector.sha256(
            concentrated_prior_book
        ),
        holding_watch_summary=str(holding_watch_summary),
        expected_holding_watch_summary_sha256=selector.sha256(
            holding_watch_summary
        ),
        holding_watch_csv=str(holding_watch_csv),
        expected_holding_watch_csv_sha256=selector.sha256(holding_watch_csv),
        macro_price_cache=str(macro_price_cache),
        expected_policy_commit=selector.POLICY_COMMIT,
        valuation_date=VALUATION_DATE,
        expected_context_count=1,
        expected_eligible_count=1,
        output_dir=str(root / "output"),
    )
    return args, scored_path


def test_provider_prices_are_normalized_for_pinned_policy() -> None:
    source = pd.DataFrame(
        {
            "ticker": ["aaa", "AAA"],
            "Date": ["2026-07-10", "2026-07-13"],
            "Open": [99.0, 101.0],
            "Close": [100.0, 102.0],
            "Adj Close": [50.0, 51.0],
        }
    )
    prices = selector.normalized_provider_prices(source)
    assert set(prices) == {"AAA"}
    frame = prices["AAA"]
    assert list(frame.columns) == ["close", "open"]
    assert frame.index.max() == pd.Timestamp("2026-07-13")
    assert float(frame.loc[pd.Timestamp("2026-07-13"), "close"]) == 51.0
    assert float(frame.loc[pd.Timestamp("2026-07-13"), "open"]) == 50.5


def test_marked_weight_contract_uses_exact_close_and_cash() -> None:
    watch = pd.DataFrame(
        {
            "as_of_date": ["2026-07-13", "2026-07-13"],
            "portfolio_kind": ["main", "concentrated"],
            "ticker": ["AAA", "BBB"],
            "current_weight": [0.8, 0.7],
            "price_exact_asof": [True, True],
        }
    )
    summary = {
        "portfolio_summaries": {
            "main": {"estimated_current_equity_usd": 100.0, "cash_usd": 20.0},
            "concentrated": {
                "estimated_current_equity_usd": 100.0,
                "cash_usd": 30.0,
            },
        }
    }
    frames = selector.marked_weight_frames(
        watch, summary, pd.Timestamp("2026-07-13")
    )
    for frame in frames.values():
        assert abs(float(frame["weight"].sum()) - 1.0) <= 1e-12
        assert "CASH" in set(frame["ticker"])


def test_noop_turnover_and_cost_are_zero() -> None:
    projection = pd.DataFrame(
        {
            "portfolio_kind": ["main", "main"],
            "scenario": ["noop", "noop"],
            "ticker": ["AAA", "CASH"],
            "advisory_weight": [0.8, 0.2],
        }
    )
    prior = pd.DataFrame({"ticker": ["AAA", "CASH"], "weight": [0.8, 0.2]})
    detail, summary = selector.comparison_rows(
        projection,
        {"main": prior},
        {"main": prior},
        {"main": 100000.0},
    )
    row = summary.iloc[0]
    assert float(row["one_way_turnover_vs_marked"]) == 0.0
    assert float(row["estimated_cost_usd_25bps"]) == 0.0
    assert float(row["estimated_cost_usd_100bps"]) == 0.0
    assert bool(detail["execution_allowed"].eq(False).all())


def test_asset_cost_excludes_cash_but_turnover_includes_it() -> None:
    projection = pd.DataFrame(
        {
            "portfolio_kind": ["main", "main"],
            "scenario": ["cash_raise", "cash_raise"],
            "ticker": ["AAA", "CASH"],
            "advisory_weight": [0.6, 0.4],
        }
    )
    marked = pd.DataFrame({"ticker": ["AAA", "CASH"], "weight": [0.8, 0.2]})
    _detail, summary = selector.comparison_rows(
        projection,
        {"main": marked},
        {"main": marked},
        {"main": 100000.0},
    )
    row = summary.iloc[0]
    assert abs(float(row["one_way_turnover_vs_marked"]) - 0.2) <= 1e-12
    assert abs(float(row["asset_absolute_trade_weight"]) - 0.2) <= 1e-12
    assert abs(float(row["estimated_cost_usd_25bps"]) - 50.0) <= 1e-12


def test_holding_risk_conflicts_are_diagnostic_only() -> None:
    projection = pd.DataFrame(
        {
            "portfolio_kind": ["main", "main", "main"],
            "scenario": ["risk", "risk", "risk"],
            "ticker": ["AAA", "NEW", "CASH"],
            "advisory_weight": [0.5, 0.3, 0.2],
        }
    )
    marked = pd.DataFrame(
        {"ticker": ["AAA", "CASH"], "weight": [0.4, 0.6]}
    )
    detail, summary = selector.comparison_rows(
        projection,
        {"main": marked},
        {"main": marked},
        {"main": 100000.0},
    )
    watch = pd.DataFrame(
        {
            "portfolio_kind": ["main"],
            "ticker": ["AAA"],
            "risk_state": ["ALERT"],
            "advisory_action": ["FREEZE_INCREMENTAL_BUY_AND_MANUAL_REVIEW"],
            "reason_codes": ["shock"],
        }
    )
    detail, summary = selector.attach_holding_risk_diagnostics(
        detail, summary, watch
    )
    row = summary.iloc[0]
    assert int(row["incremental_buy_risk_review_conflict_count"]) == 1
    assert int(row["incremental_buy_freeze_conflict_count"]) == 1
    assert int(row["proposed_new_entry_without_risk_watch_count"]) == 1
    assert bool(row["risk_watch_promotion_allowed"]) is False
    assert bool(detail["execution_allowed"].eq(False).all())


def test_build_accepts_relocated_scored_output_then_blocks_future_score() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        args, scored_path = manifest_args(
            Path(temporary),
            score_available_from="2099-01-01T00:00:00+00:00",
        )
        payload = selector.build(args)

    assert payload["status"] == selector.BLOCKED_STATUS
    assert payload["contract_failures"] == ["score_available_from_future"]
    score_audit = payload["source_inputs"]["current_scored_latest"]
    assert Path(score_audit["path"]) == scored_path
    assert score_audit["hash_matches"] is True
    assert payload["source_inputs"]["core_candidate_coverage"]["passed"] is True


def test_build_blocks_invalid_or_future_holding_availability() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for case, available_from, expected_failure in (
            ("invalid", "", "holding_available_from_invalid"),
            (
                "future",
                "2099-01-01T00:00:00+00:00",
                "holding_available_from_future",
            ),
        ):
            case_root = root / case
            case_root.mkdir()
            args, _scored_path = manifest_args(case_root)
            summary_path = Path(args.holding_watch_summary)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["available_from"] = available_from
            write_json(summary_path, summary)
            args.expected_holding_watch_summary_sha256 = selector.sha256(
                summary_path
            )
            payload = selector.build(args)
            assert payload["status"] == selector.BLOCKED_STATUS
            assert expected_failure in payload["contract_failures"]


def test_build_blocks_self_consistent_scored_ticker_substitution() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        args, _scored_path = manifest_args(
            Path(temporary),
            context_ticker="AAA",
            scored_ticker="BBB",
        )
        payload = selector.build(args)

    assert payload["status"] == selector.BLOCKED_STATUS
    assert payload["contract_failures"] == [
        "core_candidate_decision_ticker_set_mismatch"
    ]
    coverage_audit = payload["source_inputs"]["core_candidate_coverage"]
    assert coverage_audit["passed"] is True
    assert (
        coverage_audit["recomputed"]["ticker_set_sha256"]
        != coverage_audit["decision_context_ticker_set_sha256"]
    )


def test_input_revalidation_detects_post_hash_change() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "input.csv"
        path.write_text("ticker,value\nAAA,1\n", encoding="utf-8")
        audit = selector.fingerprint(path)
        path.write_text("ticker,value\nAAA,2\n", encoding="utf-8")
        assert selector.changed_input_failures({"selection_context": audit}) == [
            "input_changed_before_selector_publish:selection_context"
        ]


def main() -> int:
    test_provider_prices_are_normalized_for_pinned_policy()
    test_marked_weight_contract_uses_exact_close_and_cash()
    test_noop_turnover_and_cost_are_zero()
    test_asset_cost_excludes_cash_but_turnover_includes_it()
    test_holding_risk_conflicts_are_diagnostic_only()
    test_build_accepts_relocated_scored_output_then_blocks_future_score()
    test_build_blocks_invalid_or_future_holding_availability()
    test_build_blocks_self_consistent_scored_ticker_substitution()
    test_input_revalidation_detects_post_hash_change()
    print("run287_current_selector_no_write_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
