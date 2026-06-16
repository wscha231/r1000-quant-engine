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
    write_csv(latest / "scored_latest.csv", [{"ticker": "AAA", "score_total": 1.0}])
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
        "strict_selection": False,
        "strict_promotion": False,
        "source_run_id": "123",
        "source_commit_sha": "abc",
        "source_branch": "test",
        "source_artifact_name": "artifact",
        "max_prices_stale_days": 3,
        "max_macro_stale_days": 3,
        "max_sec_companyfacts_stale_days": 7,
        "max_form4_transactions_stale_days": 5,
        "max_institutional_13f_holdings_stale_days": 100,
        "max_etf_holdings_stale_days": 40,
        "max_free_data_manifest_stale_days": 3,
    }
    values.update(overrides)
    return type("Args", (), values)()


def test_healthy_core_allows_selection(tmp: Path) -> None:
    latest, price = base_fixture(tmp)
    payload = dfc.build_payload(args(tmp, latest, price))
    assert payload["selection_allowed"] is True, payload["blockers"]
    assert payload["promotion_allowed"] is False, "ETF/sec_v1 coverage warnings should keep promotion conservative"
    assert any(w["source_name"] == "prices" for w in payload["watermarks"])
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
