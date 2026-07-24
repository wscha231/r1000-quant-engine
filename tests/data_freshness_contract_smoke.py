"""Smoke tests for tools/run_data_freshness_contract.py."""
from __future__ import annotations

import importlib.util
import csv
import json
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("dfc", str(REPO / "tools" / "run_data_freshness_contract.py"))
dfc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dfc)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def core_candidate_row(ticker: str = "AAA", **overrides) -> dict:
    row = {
        "ticker": ticker,
        "px": 100.0,
        "score_total": 1.0,
        "mom_1m": 0.01,
        "mom_3m": 0.03,
        "mom_6m": 0.06,
        "mom_12m": 0.12,
        "relative_strength_composite": 0.50,
        "valuation_price_cutoff_date": "2026-06-15",
        "feature_available_from": "2026-06-16T01:00:00Z",
    }
    row.update(overrides)
    return row


def base_fixture(tmp: Path) -> tuple[Path, Path]:
    dfc.REPO_ROOT = tmp
    latest = tmp / "outputs"
    price = tmp / "cache_prices"
    write_json(
        latest / "data_readiness" / "summary.json",
        {
            "status": "ok",
            "ready_for_policy_replay": True,
            "ready_for_fullrun": True,
            "latest_target_date": "2026-06-15",
            "latest_observable_close_date": "2026-06-15",
            "effective_latest_target_date": "2026-06-15",
            "blockers": [],
            "warnings": [],
            "feature_source_coverage": {"overall": {"pit_future_available_from_rows": 0}},
        },
    )
    write_json(
        price / "replay_price_cache_manifest.json",
        {
            "start": "2018-06-01",
            "end": "2026-06-15",
            "ticker_count": 3,
            "failed_count": 0,
            "status": "already_cached",
        },
    )
    (tmp / "data_pit" / "macro").mkdir(parents=True, exist_ok=True)
    (tmp / "data_pit" / "macro" / "latest.json").write_text("{}", encoding="utf-8")
    write_json(
        latest / "reports" / "operating_target_books_summary.json",
        {
            "status": "completed",
            "books": [
                {"portfolio": "main", "operating_book_current": True},
                {"portfolio": "concentrated", "operating_book_current": True},
            ],
        },
    )
    write_csv(
        latest / "reports" / "operating_main_target_book.csv",
        [{"rebalance_date": "2026-06-15", "ticker": "AAA", "weight": 0.5}],
    )
    write_csv(
        latest / "reports" / "operating_concentrated_target_book.csv",
        [{"rebalance_date": "2026-06-15", "ticker": "AAA", "weight": 0.5}],
    )
    write_csv(latest / "scored_latest.csv", [core_candidate_row()])
    write_json(
        latest / "sec_enriched_candidate_replay" / "summary.json",
        {
            "status": "ok",
            "row_count": 10,
            "coverage_etf_ratio": 0.0,
            "coverage_ratio": 0.12,
            "coverage_13f_ratio": 0.80,
            "coverage_smart_money_ratio": 0.70,
            "coverage_top_manager_ratio": 0.10,
        },
    )
    return latest, price


def args(tmp: Path, latest: Path, price: Path, **overrides):
    values = {
        "latest_run": str(latest),
        "price_cache": str(price),
        "output_dir": str(tmp / "contract"),
        "asof_date": "2026-06-16",
        "require_current_operating_books": True,
        "require_coverage_layers": "",
        "warn_only_coverage_layers": "etf,sec_v1_evidence,13f,smart_money,top_manager",
        "minimum_core_candidate_coverage": 0.98,
        "strict_selection": False,
        "strict_promotion": False,
        "source_run_id": "123",
        "source_commit_sha": "abc",
        "source_branch": "test",
        "source_artifact_name": "artifact",
        "source_context": "unit_test",
        "freshness_contract_non_fatal": False,
        "max_prices_stale_days": 3,
        "max_macro_stale_days": 3,
        "max_sec_companyfacts_stale_days": 7,
        "max_form4_transactions_stale_days": 5,
        "max_institutional_13f_holdings_stale_days": 100,
        "max_etf_holdings_stale_days": 40,
        "max_free_data_manifest_stale_days": 3,
        "max_daily_market_snapshot_stale_days": 3,
    }
    values.update(overrides)
    return type("Args", (), values)()


def test_healthy_core_allows_selection(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    payload = dfc.build_payload(args(tmp, latest, price))
    assert payload["selection_allowed"] is True, payload["blockers"]
    assert payload["promotion_allowed"] is False, "ETF/sec_v1 coverage warnings should keep promotion conservative"
    assert payload["source_context"] == "unit_test"
    assert payload["freshness_contract_non_fatal"] is False
    assert payload["core_candidate_coverage"]["passed"] is True
    assert payload["core_candidate_coverage"]["coverage_ratio"] == 1.0
    assert any(w["source_name"] == "prices" for w in payload["watermarks"])
    macro_sources = [w for w in payload["watermarks"] if w["source_name"] == "macro"]
    assert macro_sources and macro_sources[0]["freshness_basis"] == "directory_mtime_proxy", macro_sources
    assert any("macro freshness uses directory_mtime_proxy" in w for w in payload["warnings"]), payload["warnings"]
    print("PASS test_healthy_core_allows_selection")


def test_stale_price_blocks_selection(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    write_json(price / "replay_price_cache_manifest.json", {"start": "2018-01-01", "end": "2026-05-01"})
    payload = dfc.build_payload(args(tmp, latest, price))
    assert payload["selection_allowed"] is False
    assert any("prices is stale" in b for b in payload["blockers"]), payload["blockers"]
    print("PASS test_stale_price_blocks_selection")


def test_future_available_from_blocks_selection(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    summary = json.loads((latest / "data_readiness" / "summary.json").read_text(encoding="utf-8"))
    summary["feature_source_coverage"]["overall"]["pit_future_available_from_rows"] = 2
    write_json(latest / "data_readiness" / "summary.json", summary)
    payload = dfc.build_payload(args(tmp, latest, price))
    assert payload["selection_allowed"] is False
    assert any("future available_from" in b for b in payload["blockers"])
    print("PASS test_future_available_from_blocks_selection")


def test_latest_run_price_manifest_fallback(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    (price / "replay_price_cache_manifest.json").unlink()
    write_json(
        latest / "manifests" / "replay_price_cache_manifest.json",
        {
            "start": "2018-06-01",
            "end": "2026-06-15",
            "ticker_count": 3,
            "failed_count": 0,
            "status": "already_cached",
        },
    )
    payload = dfc.build_payload(args(tmp, latest, price))
    assert payload["selection_allowed"] is True, payload["blockers"]
    price_sources = [w for w in payload["watermarks"] if w["source_name"] == "prices"]
    assert price_sources and "latest_run_price_manifest_fallback" not in payload["blockers"]
    assert "manifests" in price_sources[0]["resolved_path"], price_sources[0]
    print("PASS test_latest_run_price_manifest_fallback")


def test_noncurrent_operating_book_blocks_when_required(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    write_json(
        latest / "reports" / "operating_target_books_summary.json",
        {"status": "completed", "books": [{"portfolio": "main", "operating_book_current": False}]},
    )
    payload = dfc.build_payload(args(tmp, latest, price))
    assert payload["selection_allowed"] is False
    assert any("not current" in b for b in payload["blockers"])
    print("PASS test_noncurrent_operating_book_blocks_when_required")


def test_source_context_non_fatal_metadata(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    payload = dfc.build_payload(
        args(
            tmp,
            latest,
            price,
            source_context="full_rebuild_sidecar",
            freshness_contract_non_fatal=True,
        )
    )
    assert payload["source_context"] == "full_rebuild_sidecar"
    assert payload["freshness_contract_non_fatal"] is True
    assert payload["data_snapshot_manifest"]["freshness_contract_non_fatal"] is True
    print("PASS test_source_context_non_fatal_metadata")


def test_core_candidate_coverage_floor_is_fail_closed(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    rows = [core_candidate_row(f"T{i:03d}") for i in range(100)]
    rows[0]["mom_12m"] = ""
    rows[1]["mom_12m"] = ""
    write_csv(latest / "scored_latest.csv", rows)
    boundary = dfc.build_payload(args(tmp, latest, price))
    assert boundary["selection_allowed"] is True, boundary["blockers"]
    assert boundary["core_candidate_coverage"]["coverage_ratio"] == 0.98

    rows[2]["mom_12m"] = ""
    write_csv(latest / "scored_latest.csv", rows)
    blocked = dfc.build_payload(args(tmp, latest, price))
    assert blocked["selection_allowed"] is False
    assert blocked["core_candidate_coverage"]["coverage_ratio"] == 0.97
    assert any("core candidate coverage 0.970000 < required 0.980000" in item for item in blocked["blockers"])
    print("PASS test_core_candidate_coverage_floor_is_fail_closed")


def test_core_candidate_identity_and_temporal_contract(tmp: Path) -> None:
    path = tmp / "scored_latest.csv"
    rows = [core_candidate_row(f"T{i:03d}") for i in range(100)]
    expected_hash = dfc.core_candidate_ticker_set_sha256(
        [row["ticker"] for row in rows]
    )
    write_csv(path, rows)
    valid, failures = dfc.core_candidate_coverage_for_path(
        path,
        minimum_ratio=0.98,
        expected_row_count=100,
        expected_valuation_date="2026-06-15",
        decision_time_utc="2026-06-16T01:00:00Z",
        expected_ticker_set_sha256=expected_hash,
    )
    assert not failures, failures
    assert valid["passed"] is True
    assert valid["ticker_set_matches_expected"] is True
    assert valid["source_sha256"] == dfc.sha256_file(path, max_bytes=None)

    rows[0]["ticker"] = "REPLACEMENT"
    write_csv(path, rows)
    substituted, failures = dfc.core_candidate_coverage_for_path(
        path,
        minimum_ratio=0.98,
        expected_row_count=100,
        expected_valuation_date="2026-06-15",
        decision_time_utc="2026-06-16T01:00:00Z",
        expected_ticker_set_sha256=expected_hash,
    )
    assert substituted["passed"] is False
    assert substituted["ticker_set_matches_expected"] is False
    assert any("ticker set" in item for item in failures)

    rows = [core_candidate_row(f"T{i:03d}") for i in range(100)]
    rows[0]["feature_available_from"] = "2026-06-16T01:00:01Z"
    write_csv(path, rows)
    future, failures = dfc.core_candidate_coverage_for_path(
        path,
        minimum_ratio=0.98,
        expected_row_count=100,
        expected_valuation_date="2026-06-15",
        decision_time_utc="2026-06-16T01:00:00Z",
        expected_ticker_set_sha256=expected_hash,
    )
    assert future["coverage_ratio"] == 0.99
    assert future["passed"] is False
    assert any(
        "hard integrity violation in feature_available_from" in item
        for item in failures
    )

    rows = [core_candidate_row(f"T{i:03d}") for i in range(100)]
    rows[0]["px"] = 0.0
    write_csv(path, rows)
    nonpositive_price, failures = dfc.core_candidate_coverage_for_path(
        path,
        minimum_ratio=0.98,
        expected_row_count=100,
        expected_valuation_date="2026-06-15",
        decision_time_utc="2026-06-16T01:00:00Z",
        expected_ticker_set_sha256=expected_hash,
    )
    assert nonpositive_price["coverage_ratio"] == 0.99
    assert nonpositive_price["passed"] is False
    assert any(
        "hard integrity violation in px" in item
        for item in failures
    )

    rows = [core_candidate_row(f"T{i:03d}") for i in range(100)]
    rows[0]["ticker"] = "NAN"
    rows[1]["valuation_price_cutoff_date"] = "2026-06-14"
    rows[2]["feature_available_from"] = "2026-06-16T01:00:01Z"
    write_csv(path, rows)
    invalid, failures = dfc.core_candidate_coverage_for_path(
        path,
        minimum_ratio=0.98,
        expected_row_count=100,
        expected_valuation_date="2026-06-15",
        decision_time_utc="2026-06-16T01:00:00Z",
        expected_ticker_set_sha256=expected_hash,
    )
    assert invalid["passed"] is False
    assert invalid["coverage_ratio"] == 0.97
    assert invalid["invalid_by_column"]["ticker"] == 1
    assert invalid["invalid_by_column"]["valuation_price_cutoff_date"] == 1
    assert invalid["invalid_by_column"]["feature_available_from"] == 1
    print("PASS test_core_candidate_identity_and_temporal_contract")


def test_pre_refresh_core_coverage_can_be_diagnostic(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    (latest / "scored_latest.csv").unlink()
    payload = dfc.build_payload(
        args(tmp, latest, price, minimum_core_candidate_coverage=0.0)
    )
    assert payload["selection_allowed"] is True, payload["blockers"]
    coverage = payload["core_candidate_coverage"]
    assert coverage["required_for_target_mutation"] is False
    assert coverage["passed"] is False
    print("PASS test_pre_refresh_core_coverage_can_be_diagnostic")


def test_main_removes_stale_ready_marker_before_parse_failure(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    output = tmp / "contract"
    write_json(output / "status.json", {"status": "pass", "selection_allowed": True})
    (latest / "scored_latest.csv").write_bytes(b"\xff")
    parsed = args(tmp, latest, price)
    original_parse_args = dfc.parse_args
    dfc.parse_args = lambda: parsed
    try:
        try:
            dfc.main()
        except UnicodeDecodeError:
            pass
        else:
            raise AssertionError("invalid UTF-8 scored file unexpectedly parsed")
    finally:
        dfc.parse_args = original_parse_args
    assert not (output / "status.json").exists()
    print("PASS test_main_removes_stale_ready_marker_before_parse_failure")


def test_strict_main_returns_nonzero_for_blocked_selection(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    write_json(
        price / "replay_price_cache_manifest.json",
        {"start": "2018-01-01", "end": "2026-05-01"},
    )
    parsed = args(tmp, latest, price, strict_selection=True)
    original_parse_args = dfc.parse_args
    dfc.parse_args = lambda: parsed
    try:
        assert dfc.main() == 2
    finally:
        dfc.parse_args = original_parse_args
    status = json.loads((Path(parsed.output_dir) / "status.json").read_text(encoding="utf-8"))
    assert status["selection_allowed"] is False
    print("PASS test_strict_main_returns_nonzero_for_blocked_selection")


def test_mutation_snapshot_stream_hashes_files_above_diagnostic_limit(tmp: Path) -> None:
    large = tmp / "candidate_replay_book.csv"
    with large.open("wb") as handle:
        handle.seek(50_000_000)
        handle.write(b"x")
    diagnostic = dfc.path_stats(large)
    mutation_bound = dfc.path_stats(large, hash_max_bytes=None)
    assert diagnostic["bytes"] == 50_000_001
    assert diagnostic["sha256"] == ""
    assert len(mutation_bound["sha256"]) == 64
    print("PASS test_mutation_snapshot_stream_hashes_files_above_diagnostic_limit")


def test_main_writes_contract_files(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    parsed = args(tmp, latest, price)
    payload = dfc.build_payload(parsed)
    out = Path(parsed.output_dir)
    dfc.write_json(out / "status.json", {k: v for k, v in payload.items() if k != "data_snapshot_manifest"})
    dfc.write_json(out / "data_watermarks.json", {"schema_version": "data-watermarks-v1", "watermarks": payload["watermarks"]})
    dfc.write_json(out / "data_snapshot_manifest.json", payload["data_snapshot_manifest"])
    (out / "report.md").write_text(dfc.render_report(payload), encoding="utf-8")
    for name in ["status.json", "data_watermarks.json", "data_snapshot_manifest.json", "report.md"]:
        assert (out / name).exists(), name
    print("PASS test_main_writes_contract_files")


def main() -> int:
    failed = 0
    tests = [
        test_healthy_core_allows_selection,
        test_stale_price_blocks_selection,
        test_future_available_from_blocks_selection,
        test_latest_run_price_manifest_fallback,
        test_noncurrent_operating_book_blocks_when_required,
        test_source_context_non_fatal_metadata,
        test_core_candidate_coverage_floor_is_fail_closed,
        test_core_candidate_identity_and_temporal_contract,
        test_pre_refresh_core_coverage_can_be_diagnostic,
        test_main_removes_stale_ready_marker_before_parse_failure,
        test_strict_main_returns_nonzero_for_blocked_selection,
        test_mutation_snapshot_stream_hashes_files_above_diagnostic_limit,
        test_main_writes_contract_files,
    ]
    tmp = Path(tempfile.mkdtemp())
    for test in tests:
        case = tmp / test.__name__
        case.mkdir(parents=True, exist_ok=True)
        try:
            test(case)
        except AssertionError as exc:
            print(f"FAIL {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR {test.__name__}: {exc!r}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
