#!/usr/bin/env python3
"""Smoke tests for the report-only Chameleon forward/PIT archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import collect_run287_chameleon_forward_archive as archive  # noqa: E402


COLLECTED_AT = "2026-08-30T12:00:00Z"


def contract() -> dict:
    return json.loads(archive.DEFAULT_CONTRACT.read_text(encoding="utf-8"))


def fred_payload(series_id: str, vintage: str, *, duplicate: bool = False) -> str:
    observation_start = archive.subtract_years(
        datetime.fromisoformat(vintage).date(), 7
    ).isoformat()
    observations = [
        {
            "realtime_start": vintage,
            "realtime_end": vintage,
            "date": "2026-08-27",
            "value": "-0.25" if series_id == "NFCI" else "1.25",
        },
        {
            "realtime_start": vintage,
            "realtime_end": vintage,
            "date": "2026-08-28",
            "value": ".",
        },
    ]
    if duplicate:
        observations.append(dict(observations[0]))
    return json.dumps(
        {
            "realtime_start": vintage,
            "realtime_end": vintage,
            "observation_start": observation_start,
            "observation_end": vintage,
            "limit": 100000,
            "offset": 0,
            "sort_order": "asc",
            "count": len(observations),
            "observations": observations,
        },
        sort_keys=True,
    )


def build_source_bundle(
    root: Path,
    *,
    vintage: str = "2026-08-30",
    include_cross_asset: bool = True,
    duplicate_fred: str = "",
) -> Path:
    spec = contract()
    bundle = root / "source_bundle"
    fred_dir = bundle / "fred"
    cboe_dir = bundle / "cboe"
    cross_dir = bundle / "cross_asset"
    fred_dir.mkdir(parents=True)
    cboe_dir.mkdir(parents=True)
    cross_dir.mkdir(parents=True)

    for series_id in spec["fred"]["series"].values():
        (fred_dir / f"{series_id}.json").write_text(
            fred_payload(
                series_id,
                vintage,
                duplicate=series_id == duplicate_fred,
            ),
            encoding="utf-8",
        )
    index_history = "\n".join(
        [
            "DATE,OPEN,HIGH,LOW,CLOSE",
            "08/27/2026,12.0,14.0,11.0,13.0",
            "08/28/2026,13.0,15.0,12.0,14.0",
            "",
        ]
    )
    for name in ("vix", "vix3m"):
        (cboe_dir / f"{name}.csv").write_text(index_history, encoding="utf-8")
    (cboe_dir / "vvix.csv").write_text(
        "DATE,VVIX\n08/27/2026,90.0\n08/28/2026,91.0\n",
        encoding="utf-8",
    )
    (cboe_dir / "daily_put_call.html").write_text(
        r"""<html><script>self.__next_f.push([1,"data:{\"optionsData\":{\"ratios\":[{\"name\":\"INDEX PUT/CALL RATIO\",\"value\":\"1.00\"},{\"name\":\"EQUITY PUT/CALL RATIO\",\"value\":\"0.50\"}],\"INDEX OPTIONS\":[{\"name\":\"VOLUME\",\"call\":200,\"put\":200,\"total\":400}],\"EQUITY OPTIONS\":[{\"name\":\"VOLUME\",\"call\":1200,\"put\":600,\"total\":1800}]},\"selectedDate\":\"2026-08-28\",\"prevTradingDay\":\"2026-08-28\"}"])</script></html>""",
        encoding="utf-8",
    )
    if include_cross_asset:
        lines = [
            "ticker,observation_date,close,price_basis,provider,source_url"
        ]
        for offset, ticker in enumerate(spec["cross_asset"]["required_tickers"], 1):
            lines.append(
                f"{ticker},2026-08-28,{100 + offset},"
                "split_and_dividend_adjusted_close,fixture-provider,"
                f"https://example.test/{ticker}"
            )
        (cross_dir / "daily.csv").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    return bundle


def args(
    archive_root: Path,
    bundle: Path | None,
    *,
    collected_at: str = COLLECTED_AT,
    fixture_mode: bool = True,
    allow_network: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        archive_root=str(archive_root),
        contract=str(archive.DEFAULT_CONTRACT),
        source_bundle="" if bundle is None else str(bundle),
        fixture_mode=fixture_mode,
        collected_at=collected_at,
        allow_network=allow_network,
    )


def index_rows(archive_root: Path) -> list[dict]:
    path = archive_root / "archive_index.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def normalized_rows(archive_root: Path, manifest: dict) -> list[dict]:
    rows: list[dict] = []
    for source in manifest["sources"]:
        relative = source.get("normalized_object")
        if not relative:
            continue
        path = archive_root / relative
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


def test_complete_fixture_is_free_proxy_and_nonexecuting() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        payload = archive.build(args(archive_root, bundle))
        assert payload["status"] == archive.READY_STATUS
        assert payload["source_expected_count"] == 18
        assert payload["source_captured_count"] == 18
        assert payload["source_missing_count"] == 0
        assert payload["source_partial_count"] == 0
        assert payload["source_truth_class_counts"] == {"FREE_PROXY": 18}
        assert payload["pit_verified_emitted"] is False
        assert payload["historical_ab_allowed"] is False
        assert payload["report_only"] is True
        assert payload["selector_executed"] is False
        assert payload["target_books_mutated"] is False
        assert payload["trade_intents_written"] is False
        assert payload["orders_generated"] is False
        assert payload["portfolio_ledger_mutated"] is False
        assert payload["accepted_head_mutated"] is False
        assert payload["historical_backtest_executed"] is False
        assert payload["fullrun_executed"] is False
        assert payload["workflow_dispatched"] is False
        assert payload["production_activation_allowed"] is False
        assert payload["live_trading_enabled"] is False
        assert payload["automatic_promotion_allowed"] is False
        assert len(index_rows(archive_root)) == 1
        rows = normalized_rows(archive_root, payload)
        assert rows
        assert {row["truth_class"] for row in rows} == {"FREE_PROXY"}
        assert {row["available_from"] for row in rows} == {COLLECTED_AT}
        assert {row["collected_at_utc"] for row in rows} == {COLLECTED_AT}
        assert all(row["historical_ab_allowed"] is False for row in rows)
        nfci = [
            row
            for row in rows
            if row["source_id"] == "fred.nfci"
            and row["source_observation_date"] == "2026-08-27"
        ]
        assert len(nfci) == 1 and nfci[0]["value"] == -0.25


def test_identical_same_time_is_idempotent_and_changed_payload_blocks() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        first = archive.build(args(archive_root, bundle))
        second = archive.build(args(archive_root, bundle))
        assert first["status"] == archive.READY_STATUS
        assert second["status"] == archive.READY_STATUS
        assert second["idempotent_reuse"] is True
        assert second["snapshot_id"] == first["snapshot_id"]
        assert second["snapshot_manifest_sha256"] == first["snapshot_manifest_sha256"]
        assert second["archive_index_entry_sha256"] == first[
            "archive_index_entry_sha256"
        ]
        assert len(index_rows(archive_root)) == 1

        target = bundle / "fred" / "DGS2.json"
        mutated = json.loads(target.read_text(encoding="utf-8"))
        mutated["observations"][0]["value"] = "9.99"
        target.write_text(json.dumps(mutated, sort_keys=True), encoding="utf-8")
        blocked = archive.build(args(archive_root, bundle))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "same_collection_time_payload_conflict" in blocked["blockers"][0]
        assert len(index_rows(archive_root)) == 1


def test_out_of_order_collection_blocks_without_append() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root, vintage="2026-08-30")
        archive_root = root / "archive"
        first = archive.build(
            args(
                archive_root,
                bundle,
                collected_at="2026-08-30T23:00:00Z",
            )
        )
        assert first["status"] == archive.READY_STATUS
        older_bundle = build_source_bundle(root / "older", vintage="2026-08-30")
        blocked = archive.build(
            args(
                archive_root,
                older_bundle,
                collected_at="2026-08-30T18:00:00Z",
            )
        )
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "out_of_order_collection" in blocked["blockers"][0]
        assert len(index_rows(archive_root)) == 1


def test_fixture_cannot_claim_forward_pit_and_network_time_cannot_be_injected() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        fixture_payload = archive.build(args(root / "fixture_archive", bundle))
        assert fixture_payload["source_truth_class_counts"] == {"FREE_PROXY": 18}
        assert "FORWARD_PIT" not in fixture_payload["source_truth_class_counts"]

        blocked = archive.build(
            args(
                root / "network_archive",
                None,
                fixture_mode=False,
                allow_network=True,
                collected_at=COLLECTED_AT,
            )
        )
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "caller_timestamp_forbidden_outside_fixture" in blocked["blockers"][0]


def test_official_network_capture_is_forward_only_and_secret_free() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixture_bundle = build_source_bundle(root)
        fixed_time = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
        original_fetch = archive.network_fetch
        original_now = archive.utc_now
        original_key = os.environ.get("FRED_API_KEY")
        secret = "secret-value-that-must-never-be-persisted"

        def fake_fetch(
            *,
            url: str,
            params: dict | None,
            timeout_seconds: int,
            maximum_bytes: int,
            maximum_redirect_hops: int,
        ) -> tuple[bytes | None, str, datetime | None, str]:
            del timeout_seconds, maximum_bytes
            assert maximum_redirect_hops == 5
            if "stlouisfed.org" in url:
                assert params is not None
                assert params["api_key"] == secret
                raw = (
                    fixture_bundle
                    / "fred"
                    / f"{params['series_id']}.json"
                ).read_bytes()
                return raw, "", fixed_time, url
            path_by_url = {
                item["url"]: item["fixture_path"]
                for item in contract()["cboe"]["sources"].values()
            }
            return (
                (fixture_bundle / path_by_url[url]).read_bytes(),
                "",
                fixed_time,
                url,
            )

        try:
            os.environ["FRED_API_KEY"] = secret
            archive.network_fetch = fake_fetch
            archive.utc_now = lambda: fixed_time
            archive_root = root / "archive"
            payload = archive.build(
                args(
                    archive_root,
                    None,
                    fixture_mode=False,
                    allow_network=True,
                    collected_at="",
                )
            )
        finally:
            archive.network_fetch = original_fetch
            archive.utc_now = original_now
            if original_key is None:
                os.environ.pop("FRED_API_KEY", None)
            else:
                os.environ["FRED_API_KEY"] = original_key

        assert payload["status"] == archive.READY_PARTIAL_STATUS
        assert payload["source_captured_count"] == 17
        assert payload["source_missing_count"] == 1
        assert payload["source_truth_class_counts"] == {"FORWARD_PIT": 17}
        rows = normalized_rows(archive_root, payload)
        assert rows
        assert {row["truth_class"] for row in rows} == {"FORWARD_PIT"}
        assert {row["available_from"] for row in rows} == {COLLECTED_AT}
        persisted = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (
                archive_root / "last_attempt.json",
                archive_root / "archive_index.jsonl",
                archive_root
                / "snapshots"
                / payload["snapshot_id"]
                / "manifest.json",
            )
        )
        assert secret not in persisted
        assert "api_key" not in persisted.lower()


def test_invalid_fred_vintage_and_duplicate_observation_block_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        wrong = build_source_bundle(root / "wrong", vintage="2026-08-29")
        blocked = archive.build(args(root / "archive_wrong", wrong))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "realtime_start_mismatch" in blocked["blockers"][0]
        assert index_rows(root / "archive_wrong") == []

        duplicate = build_source_bundle(
            root / "duplicate",
            duplicate_fred="DGS2",
        )
        blocked = archive.build(args(root / "archive_duplicate", duplicate))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "duplicate_observation_date" in blocked["blockers"][0]
        assert index_rows(root / "archive_duplicate") == []

        paginated = build_source_bundle(root / "paginated")
        target = paginated / "fred" / "DGS2.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        payload["offset"] = 1
        target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        blocked = archive.build(args(root / "archive_paginated", paginated))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "unexpected_pagination" in blocked["blockers"][0]
        assert index_rows(root / "archive_paginated") == []

        for case, invalid_count in (("boolean", True), ("fractional", 2.9)):
            invalid = build_source_bundle(root / f"count_{case}")
            target = invalid / "fred" / "DGS2.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["count"] = invalid_count
            target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            archive_root = root / f"archive_count_{case}"
            blocked = archive.build(args(archive_root, invalid))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert "count_invalid" in blocked["blockers"][0]
            assert index_rows(archive_root) == []

        duplicate_key = build_source_bundle(root / "duplicate_key")
        target = duplicate_key / "fred" / "DGS2.json"
        raw = target.read_text(encoding="utf-8")
        raw = raw.replace(
            '"observation_end": "2026-08-30"',
            '"observation_end": "1900-01-01", '
            '"observation_end": "2026-08-30"',
            1,
        )
        target.write_text(raw, encoding="utf-8")
        blocked = archive.build(args(root / "archive_duplicate_key", duplicate_key))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "duplicate_json_key" in blocked["blockers"][0]
        assert index_rows(root / "archive_duplicate_key") == []

        for case, value, expected in (
            ("constant", "NaN", "nonstandard_json_constant"),
            ("overflow", "1e999", "nonfinite_json_number"),
        ):
            nonfinite = build_source_bundle(root / f"nonfinite_{case}")
            target = nonfinite / "fred" / "DGS2.json"
            raw = target.read_text(encoding="utf-8")
            raw = raw.replace("{", f'{{"ignored": {value},', 1)
            target.write_text(raw, encoding="utf-8")
            archive_root = root / f"archive_nonfinite_{case}"
            blocked = archive.build(args(archive_root, nonfinite))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert expected in blocked["blockers"][0]
            assert index_rows(archive_root) == []


def test_fred_observations_must_stay_inside_requested_window_and_order() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for case, mutate, expected in (
            (
                "before",
                lambda payload: payload["observations"][0].update(
                    {"date": "2019-08-29"}
                ),
                "observation_outside_requested_window",
            ),
            (
                "after",
                lambda payload: payload["observations"][-1].update(
                    {"date": "2026-08-31"}
                ),
                "observation_outside_requested_window",
            ),
            (
                "unordered",
                lambda payload: payload["observations"].reverse(),
                "observation_order_mismatch",
            ),
        ):
            bundle = build_source_bundle(root / case)
            target = bundle / "fred" / "DGS2.json"
            payload = json.loads(target.read_text(encoding="utf-8"))
            mutate(payload)
            target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            archive_root = root / f"archive_{case}"
            blocked = archive.build(args(archive_root, bundle))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert expected in blocked["blockers"][0]
            assert index_rows(archive_root) == []


def test_csv_sources_reject_malformed_utf8() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for case, relative in (
            ("cboe", Path("cboe/vix.csv")),
            ("cross_asset", Path("cross_asset/daily.csv")),
        ):
            bundle = build_source_bundle(root / case)
            target = bundle / relative
            target.write_bytes(target.read_bytes() + b"\xff")
            archive_root = root / f"archive_{case}"
            blocked = archive.build(args(archive_root, bundle))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert "csv_unreadable" in blocked["blockers"][0]
            assert index_rows(archive_root) == []


def test_csv_sources_reject_malformed_quoting() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for case, relative, suffix in (
            ("cboe_unterminated", Path("cboe/vix.csv"), b',"unterminated'),
            ("cross_unterminated", Path("cross_asset/daily.csv"), b',"unterminated'),
            ("cboe_bare", Path("cboe/vix.csv"), b',bare"quote'),
            ("cross_bare", Path("cross_asset/daily.csv"), b',bare"quote'),
        ):
            bundle = build_source_bundle(root / case)
            target = bundle / relative
            target.write_bytes(target.read_bytes() + suffix)
            archive_root = root / f"archive_{case}"
            blocked = archive.build(args(archive_root, bundle))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert "csv_quote_structure_invalid" in blocked["blockers"][0]
            assert index_rows(archive_root) == []


def test_csv_sources_reject_unicode_controls() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for case, relative, suffix in (
            ("cboe_del", Path("cboe/vix.csv"), b",unused\x7fcontrol\n"),
            (
                "cross_format",
                Path("cross_asset/daily.csv"),
                ",unused\u200bformat\n".encode("utf-8"),
            ),
        ):
            bundle = build_source_bundle(root / case)
            target = bundle / relative
            target.write_bytes(target.read_bytes() + suffix)
            archive_root = root / f"archive_{case}"
            blocked = archive.build(args(archive_root, bundle))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert "csv_control_character_invalid" in blocked["blockers"][0]
            assert index_rows(archive_root) == []


def test_official_network_requires_builder_bytes_from_recorded_head() -> None:
    original_git_blob_bytes = archive.git_blob_bytes
    try:
        archive.git_blob_bytes = lambda head, relative: b"different-builder-bytes"
        try:
            archive.builder_identity(require_head_match=True)
            raise AssertionError("dirty network builder was accepted")
        except archive.ArchiveContractError as exc:
            assert "builder_source_differs_from_git_head" in str(exc)
        identity = archive.builder_identity(require_head_match=False)
        assert identity["builder_sha256"] != identity["builder_git_blob_sha256"]
    finally:
        archive.git_blob_bytes = original_git_blob_bytes


def test_equity_and_index_put_call_are_not_substitutable() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        daily = bundle / "cboe" / "daily_put_call.html"
        daily.write_text(
            daily.read_text(encoding="utf-8").replace(
                "EQUITY PUT/CALL RATIO", "TOTAL PUT/CALL RATIO"
            ),
            encoding="utf-8",
        )
        blocked = archive.build(args(root / "archive", bundle))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "cboe.daily_put_call_equity_ratio_match_count:0" in blocked["blockers"][0]
        assert index_rows(root / "archive") == []


def test_missing_cross_asset_stays_missing_without_carry_or_imputation() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root, include_cross_asset=False)
        archive_root = root / "archive"
        payload = archive.build(args(archive_root, bundle))
        assert payload["status"] == archive.READY_PARTIAL_STATUS
        assert payload["source_captured_count"] == 17
        assert payload["source_missing_count"] == 1
        cross = [
            item
            for item in payload["sources"]
            if item["source_id"] == "cross_asset.daily_close"
        ]
        assert len(cross) == 1
        assert cross[0]["status"] == "missing_or_unavailable"
        assert cross[0]["normalized_row_count"] == 0
        assert not any(
            row["source_id"] == "cross_asset.daily_close"
            for row in normalized_rows(archive_root, payload)
        )


def test_existing_content_tamper_is_detected_before_new_capture() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        first = archive.build(args(archive_root, bundle))
        assert first["status"] == archive.READY_STATUS
        raw_object = next(
            item["raw_object"]
            for item in first["sources"]
            if item.get("raw_object")
        )
        with (archive_root / raw_object).open("ab") as handle:
            handle.write(b"tamper")
        later_bundle = build_source_bundle(root / "later", vintage="2026-08-30")
        blocked = archive.build(
            args(
                archive_root,
                later_bundle,
                collected_at="2026-08-30T18:00:00Z",
            )
        )
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "object_hash_mismatch" in blocked["blockers"][0]
        assert len(index_rows(archive_root)) == 1


def test_cross_asset_provenance_rejects_credentials_before_persistence() -> None:
    for replacement, expected_error in (
        (
            "https://user:password@example.test/SPY",
            "credential_bearing_or_nonpublic_url",
        ),
        (
            "https://example.test/SPY?token=secret",
            "credential_bearing_or_nonpublic_url",
        ),
        ("https://example.test/SP Y", "invalid_url"),
        ("https://example.test/SP\tY", "invalid_url"),
        ("https://example.test/SP\u007fY", "csv_control_character_invalid"),
        (" https://example.test/SPY", "invalid_url"),
        ("https://example.test/SPY ", "invalid_url"),
        ("https://127.0.0.1/SPY", "credential_bearing_or_nonpublic_url"),
        ("https://10.0.0.1/SPY", "credential_bearing_or_nonpublic_url"),
        ("https://localhost/SPY", "credential_bearing_or_nonpublic_url"),
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = build_source_bundle(root)
            target = bundle / "cross_asset" / "daily.csv"
            text = target.read_text(encoding="utf-8")
            target.write_text(
                text.replace("https://example.test/SPY", replacement),
                encoding="utf-8",
            )
            archive_root = root / "archive"
            blocked = archive.build(args(archive_root, bundle))
            assert blocked["status"] == archive.BLOCKED_STATUS
            assert expected_error in blocked["blockers"][0]
            assert index_rows(archive_root) == []
            assert not list((archive_root / "objects" / "raw").glob("*"))


def test_present_source_with_no_rows_blocks_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        (bundle / "cboe" / "vix.csv").write_text(
            "DATE,OPEN,HIGH,LOW,CLOSE\n", encoding="utf-8"
        )
        archive_root = root / "archive"
        blocked = archive.build(args(archive_root, bundle))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "cboe.vix_no_usable_observations" in blocked["blockers"][0]
        assert index_rows(archive_root) == []


def test_verified_snapshot_is_recovered_after_index_interruption() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        original_write_index = archive.write_index
        original_git_blob_bytes = archive.git_blob_bytes
        calls = 0

        def fail_first_index(path: Path, entries: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated_index_interruption")
            original_write_index(path, entries)

        try:
            archive.write_index = fail_first_index
            archive.git_blob_bytes = lambda head, relative: b"dirty-fixture-head-blob"
            first = archive.build(args(archive_root, bundle))
        finally:
            archive.write_index = original_write_index
        assert first["status"] == archive.BLOCKED_STATUS
        assert not (archive_root / "archive_index.jsonl").exists()
        assert len(list((archive_root / "snapshots").iterdir())) == 1

        try:
            archive.git_blob_bytes = lambda head, relative: b"dirty-fixture-head-blob"
            recovered = archive.build(args(archive_root, bundle))
        finally:
            archive.git_blob_bytes = original_git_blob_bytes
        assert recovered["status"] == archive.READY_STATUS
        assert recovered["idempotent_reuse"] is True
        assert len(index_rows(archive_root)) == 1


def test_orphan_recovery_requires_the_canonical_source_contract() -> None:
    spec = contract()
    definitions = archive.canonical_source_definitions(spec)
    sources = []
    for source_id, definition in definitions.items():
        is_cross_asset = source_id == "cross_asset.daily_close"
        sources.append(
            {
                "source_id": source_id,
                "provider": (
                    "UNCONFIGURED"
                    if is_cross_asset
                    else next(iter(definition["providers"]))
                ),
                "source_kind": definition["source_kind"],
                "public_url": definition["public_url"],
                "status": "missing_or_unavailable" if is_cross_asset else "ready",
            }
        )
    archive.validate_orphan_source_contract(
        sources,
        contract=spec,
        snapshot_id="canonical-fixture",
    )
    try:
        archive.validate_orphan_source_contract(
            sources[:-1],
            contract=spec,
            snapshot_id="missing-source-fixture",
        )
        raise AssertionError("incomplete orphan source set was accepted")
    except archive.ArchiveContractError as exc:
        assert "source_set_mismatch" in str(exc)
    sources[0]["provider"] = "ARBITRARY_PROVIDER"
    try:
        archive.validate_orphan_source_contract(
            sources,
            contract=spec,
            snapshot_id="wrong-definition-fixture",
        )
        raise AssertionError("orphan source definition drift was accepted")
    except archive.ArchiveContractError as exc:
        assert "source_definition_mismatch" in str(exc)


def test_recovery_revalidates_normalized_jsonl_contents() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        payload = archive.build(args(archive_root, bundle))
        source = next(item for item in payload["sources"] if item["status"] == "ready")
        forged = dict(source)
        empty_sha = hashlib.sha256(b"").hexdigest()
        empty_path = archive_root / "objects" / "normalized" / f"{empty_sha}.jsonl"
        empty_path.write_bytes(b"")
        forged["normalized_sha256"] = empty_sha
        forged["normalized_object"] = (
            f"objects/normalized/{empty_sha}.jsonl"
        )
        forged["normalized_row_count"] = 1
        try:
            archive.validate_normalized_object_rows(
                archive_root,
                forged,
                snapshot_id="self-consistent-forgery",
            )
            raise AssertionError("empty normalized object was accepted as one row")
        except archive.ArchiveContractError as exc:
            assert "normalized_jsonl_invalid" in str(exc)


def test_abandoned_pre_rename_staging_is_recovered_under_lock() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        staging = archive_root / "snapshots" / f".staging-{'a' * 32}"
        staging.mkdir(parents=True)
        (staging / "partial-manifest.json").write_text("{", encoding="utf-8")
        recovered = archive.build(args(archive_root, bundle))
        assert recovered["status"] == archive.READY_STATUS
        assert not staging.exists()
        assert len(index_rows(archive_root)) == 1

        unsafe_root = root / "unsafe_archive"
        unsafe = unsafe_root / "snapshots" / ".staging-not-an-exact-id"
        unsafe.mkdir(parents=True)
        blocked = archive.build(args(unsafe_root, bundle))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "unsafe_abandoned_snapshot_staging" in blocked["blockers"][0]
        assert unsafe.exists()

        mounted_root = root / "mounted_archive"
        mounted = mounted_root / "snapshots" / f".staging-{'b' * 32}"
        mounted.mkdir(parents=True)
        (mounted / "external-data").write_text("must survive", encoding="utf-8")
        original_mount_points = archive.linux_mount_points
        try:
            archive.linux_mount_points = lambda: {mounted.absolute()}
            mount_blocked = archive.build(args(mounted_root, bundle))
        finally:
            archive.linux_mount_points = original_mount_points
        assert mount_blocked["status"] == archive.BLOCKED_STATUS
        assert "unsafe_abandoned_snapshot_staging" in mount_blocked["blockers"][0]
        assert (mounted / "external-data").read_text(encoding="utf-8") == "must survive"


def test_network_fetch_is_bounded_and_restricts_redirect_origins() -> None:
    original_get = archive.requests.get

    class FakeResponse:
        def __init__(
            self,
            *,
            url: str,
            chunks: list[bytes],
            content_length: str = "",
            history: list[str] | None = None,
            status_code: int = 200,
            location: str = "",
        ) -> None:
            self.url = url
            self._chunks = chunks
            self.headers = {"Content-Length": content_length} if content_length else {}
            if location:
                self.headers["Location"] = location
            self.history = [SimpleNamespace(url=item) for item in (history or [])]
            self.status_code = status_code

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, *, chunk_size: int) -> list[bytes]:
            assert chunk_size == 1024 * 1024
            return self._chunks

    requested = "https://api.stlouisfed.org/fred/series/observations"
    try:
        archive.requests.get = lambda *_args, **_kwargs: FakeResponse(
            url=requested,
            chunks=[b"partial"],
            status_code=206,
        )
        try:
            archive.network_fetch(
                url=requested, params=None, timeout_seconds=1, maximum_bytes=100
            )
            raise AssertionError("partial HTTP response was accepted")
        except archive.ArchiveContractError as exc:
            assert "official_network_http_status_invalid:206" in str(exc)

        archive.requests.get = lambda *_args, **_kwargs: FakeResponse(
            url=requested,
            chunks=[b"small"],
            content_length="1000",
        )
        try:
            archive.network_fetch(
                url=requested, params=None, timeout_seconds=1, maximum_bytes=5
            )
            raise AssertionError("oversized Content-Length was accepted")
        except archive.ArchiveContractError as exc:
            assert "official_network_response_too_large" in str(exc)

        archive.requests.get = lambda *_args, **_kwargs: FakeResponse(
            url=requested,
            chunks=[b"123", b"456"],
        )
        try:
            archive.network_fetch(
                url=requested, params=None, timeout_seconds=1, maximum_bytes=5
            )
            raise AssertionError("oversized streamed response was accepted")
        except archive.ArchiveContractError as exc:
            assert "official_network_response_too_large" in str(exc)

        redirect_calls: list[str] = []

        def cross_origin_redirect(url: str, **kwargs: object) -> FakeResponse:
            assert kwargs["allow_redirects"] is False
            redirect_calls.append(url)
            return FakeResponse(
                url=requested,
                status_code=302,
                location="https://evil.example/payload?api_key=must-not-leak",
                chunks=[],
            )

        archive.requests.get = cross_origin_redirect
        try:
            archive.network_fetch(
                url=requested, params=None, timeout_seconds=1, maximum_bytes=100
            )
            raise AssertionError("cross-origin redirect was accepted")
        except archive.ArchiveContractError as exc:
            assert "network_redirect_origin_mismatch" in str(exc)
        assert redirect_calls == [requested]

        same_origin_calls: list[str] = []

        def same_origin_redirect(url: str, **kwargs: object) -> FakeResponse:
            assert kwargs["allow_redirects"] is False
            same_origin_calls.append(url)
            if len(same_origin_calls) == 1:
                return FakeResponse(
                    url=requested,
                    status_code=302,
                    location="/fred/final",
                    chunks=[],
                )
            return FakeResponse(url=url, chunks=[b"redirected-payload"])

        archive.requests.get = same_origin_redirect
        redirected_raw, error, captured_at, resolved_url = archive.network_fetch(
            url=requested, params=None, timeout_seconds=1, maximum_bytes=100
        )
        assert redirected_raw == b"redirected-payload" and error == ""
        assert captured_at is not None
        assert resolved_url == "https://api.stlouisfed.org/fred/final"
        assert same_origin_calls == [
            requested,
            "https://api.stlouisfed.org/fred/final",
        ]

        archive.requests.get = lambda *_args, **_kwargs: FakeResponse(
            url=requested + "?api_key=must-not-persist",
            chunks=[b"payload"],
        )
        raw, error, captured_at, resolved_url = archive.network_fetch(
            url=requested, params=None, timeout_seconds=1, maximum_bytes=100
        )
        assert raw == b"payload" and error == "" and captured_at is not None
        assert resolved_url == requested
        assert "api_key" not in resolved_url
    finally:
        archive.requests.get = original_get


def test_runtime_clock_preserves_subsecond_capture_time() -> None:
    fractional = datetime(2026, 8, 30, 12, 0, 0, 654321, tzinfo=timezone.utc)
    original_datetime = archive.datetime

    class FractionalDateTime:
        @classmethod
        def now(cls, tz: object) -> datetime:
            assert tz is timezone.utc
            return fractional

    try:
        archive.datetime = FractionalDateTime
        assert archive.utc_now() == fractional
        assert archive.utc_iso(archive.utc_now()) == "2026-08-30T12:00:00.654321Z"
    finally:
        archive.datetime = original_datetime


def test_archive_writer_lock_rejects_a_concurrent_writer() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "archive"
        archive.validate_archive_root(root)
        first = archive.acquire_archive_writer_lock(root, 0.1)
        try:
            try:
                archive.acquire_archive_writer_lock(root, 0.05)
                raise AssertionError("concurrent archive writer acquired the lock")
            except archive.ArchiveContractError as exc:
                assert "archive_writer_lock_timeout" in str(exc)
        finally:
            archive.release_archive_writer_lock(first)


def test_fred_response_echoing_api_key_is_rejected_before_archive_write() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixture_bundle = build_source_bundle(root)
        fixed_time = datetime(2026, 8, 30, 12, 0, 0, 123456, tzinfo=timezone.utc)
        original_fetch = archive.network_fetch
        original_now = archive.utc_now
        original_key = os.environ.get("FRED_API_KEY")
        secret = "echoed-secret-that-must-not-be-archived"
        nested_percent = "".join(f"%{byte:02x}" for byte in secret.encode("utf-8"))
        for _ in range(3):
            nested_percent = nested_percent.replace("%", "%25")
        encoded_variants = {
            "json_escape": "".join(
                f"\\u{ord(character):04x}" for character in secret
            ),
            "percent_escape": f"%{ord(secret[0]):02x}{secret[1:]}",
            "percent_nested_four": nested_percent,
        }

        try:
            os.environ["FRED_API_KEY"] = secret
            archive.utc_now = lambda: fixed_time
            for case, encoded_secret in encoded_variants.items():
                def fake_fetch(
                    *,
                    url: str,
                    params: dict | None,
                    timeout_seconds: int,
                    maximum_bytes: int,
                    maximum_redirect_hops: int,
                ) -> tuple[bytes | None, str, datetime | None, str]:
                    del timeout_seconds, maximum_bytes
                    assert maximum_redirect_hops == 5
                    if "stlouisfed.org" in url:
                        assert params is not None
                        payload = json.loads(
                            (
                                fixture_bundle
                                / "fred"
                                / f"{params['series_id']}.json"
                            ).read_text(encoding="utf-8")
                        )
                        payload["request_url"] = f"{url}?api_key={secret}"
                        serialized = json.dumps(payload)
                        assert secret in serialized
                        return (
                            serialized.replace(secret, encoded_secret).encode("utf-8"),
                            "",
                            fixed_time,
                            url,
                        )
                    raise AssertionError(
                        "Cboe should not be reached after FRED secret echo"
                    )

                archive.network_fetch = fake_fetch
                archive_root = root / f"archive_{case}"
                blocked = archive.build(
                    args(
                        archive_root,
                        None,
                        fixture_mode=False,
                        allow_network=True,
                        collected_at="",
                    )
                )
                assert blocked["status"] == archive.BLOCKED_STATUS
                assert "raw_response_contains_api_key" in blocked["blockers"][0]
                assert secret not in json.dumps(blocked)
                assert not list((archive_root / "objects" / "raw").glob("*"))
        finally:
            archive.network_fetch = original_fetch
            archive.utc_now = original_now
            if original_key is None:
                os.environ.pop("FRED_API_KEY", None)
            else:
                os.environ["FRED_API_KEY"] = original_key


def test_stale_daily_options_session_blocks_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        daily = bundle / "cboe" / "daily_put_call.html"
        daily.write_text(
            daily.read_text(encoding="utf-8").replace(
                'selectedDate\\\":\\\"2026-08-28',
                'selectedDate\\\":\\\"2026-08-25',
            ),
            encoding="utf-8",
        )
        blocked = archive.build(args(root / "archive", bundle))
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "stale_selected_date" in blocked["blockers"][0]


def test_cboe_current_date_close_requires_completed_session() -> None:
    raw = b"DATE,CLOSE\n08/27/2026,13.0\n08/28/2026,14.0\n"
    before_close = datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc)
    after_close = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
    try:
        archive.normalize_cboe_index(
            raw,
            source_id="cboe.vix",
            symbol="vix",
            captured_at=before_close,
            maximum_completed_session_lag=1,
        )
        raise AssertionError("in-session Cboe close was accepted")
    except archive.ArchiveContractError as exc:
        assert "current_date_close_session_incomplete" in str(exc)
    rows, excluded = archive.normalize_cboe_index(
        raw,
        source_id="cboe.vix",
        symbol="vix",
        captured_at=after_close,
        maximum_completed_session_lag=1,
    )
    assert rows[-1]["source_observation_date"] == "2026-08-28"
    assert excluded == []


def test_cboe_index_history_requires_a_fresh_completed_session() -> None:
    stale = b"DATE,CLOSE\n08/25/2026,13.0\n08/26/2026,14.0\n"
    captured_at = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
    try:
        archive.normalize_cboe_index(
            stale,
            source_id="cboe.vix",
            symbol="vix",
            captured_at=captured_at,
            maximum_completed_session_lag=1,
        )
        raise AssertionError("stale Cboe index history was accepted")
    except archive.ArchiveContractError as exc:
        assert "stale_index_history" in str(exc)


def test_every_cboe_index_date_must_be_an_exchange_session() -> None:
    malformed = b"DATE,CLOSE\n08/23/2026,13.0\n08/28/2026,14.0\n"
    captured_at = datetime(2026, 8, 28, 21, 0, tzinfo=timezone.utc)
    rows, excluded = archive.normalize_cboe_index(
        malformed,
        source_id="cboe.vix",
        symbol="vix",
        captured_at=captured_at,
        maximum_completed_session_lag=1,
    )
    assert [row["source_observation_date"] for row in rows] == ["2026-08-28"]
    assert excluded == ["2026-08-23"]

    weekend_latest = b"DATE,CLOSE\n08/28/2026,14.0\n08/30/2026,14.0\n"
    weekend_rows, weekend_excluded = archive.normalize_cboe_index(
        weekend_latest,
        source_id="cboe.vix",
        symbol="vix",
        captured_at=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
        maximum_completed_session_lag=1,
    )
    assert [row["source_observation_date"] for row in weekend_rows] == [
        "2026-08-28"
    ]
    assert weekend_excluded == ["2026-08-30"]


def test_fixture_collection_time_cannot_be_in_the_future() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        original_now = archive.utc_now
        try:
            archive.utc_now = lambda: datetime(
                2026, 8, 30, 12, 0, tzinfo=timezone.utc
            )
            blocked = archive.build(
                args(
                    root / "archive",
                    bundle,
                    collected_at="2026-08-30T12:00:00.000001Z",
                )
            )
        finally:
            archive.utc_now = original_now
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "fixture_collected_at_in_future" in blocked["blockers"][0]


def test_verified_commit_survives_last_attempt_receipt_failure() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root)
        archive_root = root / "archive"
        original_atomic_write_json = archive.atomic_write_json

        def fail_receipt(path: Path, payload: dict) -> None:
            if path.name == "last_attempt.json":
                raise OSError("simulated_receipt_failure")
            original_atomic_write_json(path, payload)

        try:
            archive.atomic_write_json = fail_receipt
            published = archive.build(args(archive_root, bundle))
        finally:
            archive.atomic_write_json = original_atomic_write_json
        assert published["status"] == archive.READY_STATUS
        assert published["archive_passed"] is True
        assert published["last_attempt_receipt_written"] is False
        assert "simulated_receipt_failure" in published["last_attempt_receipt_error"]
        assert len(index_rows(archive_root)) == 1

        retried = archive.build(args(archive_root, bundle))
        assert retried["status"] == archive.READY_STATUS
        assert retried["idempotent_reuse"] is True
        assert retried["last_attempt_receipt_written"] is True
        assert len(index_rows(archive_root)) == 1


def test_prelaunch_collection_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bundle = build_source_bundle(root, vintage="2026-08-29")
        blocked = archive.build(
            args(
                root / "archive",
                bundle,
                collected_at="2026-08-29T23:59:59Z",
            )
        )
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "collection_precedes_archive_launch" in blocked["blockers"][0]
        assert index_rows(root / "archive") == []


if __name__ == "__main__":
    test_complete_fixture_is_free_proxy_and_nonexecuting()
    test_identical_same_time_is_idempotent_and_changed_payload_blocks()
    test_out_of_order_collection_blocks_without_append()
    test_fixture_cannot_claim_forward_pit_and_network_time_cannot_be_injected()
    test_official_network_capture_is_forward_only_and_secret_free()
    test_invalid_fred_vintage_and_duplicate_observation_block_snapshot()
    test_fred_observations_must_stay_inside_requested_window_and_order()
    test_csv_sources_reject_malformed_utf8()
    test_csv_sources_reject_malformed_quoting()
    test_csv_sources_reject_unicode_controls()
    test_official_network_requires_builder_bytes_from_recorded_head()
    test_equity_and_index_put_call_are_not_substitutable()
    test_missing_cross_asset_stays_missing_without_carry_or_imputation()
    test_existing_content_tamper_is_detected_before_new_capture()
    test_cross_asset_provenance_rejects_credentials_before_persistence()
    test_present_source_with_no_rows_blocks_snapshot()
    test_verified_snapshot_is_recovered_after_index_interruption()
    test_orphan_recovery_requires_the_canonical_source_contract()
    test_recovery_revalidates_normalized_jsonl_contents()
    test_abandoned_pre_rename_staging_is_recovered_under_lock()
    test_network_fetch_is_bounded_and_restricts_redirect_origins()
    test_runtime_clock_preserves_subsecond_capture_time()
    test_archive_writer_lock_rejects_a_concurrent_writer()
    test_fred_response_echoing_api_key_is_rejected_before_archive_write()
    test_stale_daily_options_session_blocks_snapshot()
    test_cboe_current_date_close_requires_completed_session()
    test_cboe_index_history_requires_a_fresh_completed_session()
    test_every_cboe_index_date_must_be_an_exchange_session()
    test_fixture_collection_time_cannot_be_in_the_future()
    test_verified_commit_survives_last_attempt_receipt_failure()
    test_prelaunch_collection_is_rejected()
    print("run287_chameleon_forward_archive_smoke: PASS")
