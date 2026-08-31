#!/usr/bin/env python3
"""Smoke tests for the report-only Chameleon forward/PIT archive."""
from __future__ import annotations

import argparse
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
        bundle = build_source_bundle(root, vintage="2026-08-31")
        archive_root = root / "archive"
        first = archive.build(
            args(
                archive_root,
                bundle,
                collected_at="2026-08-31T12:00:00Z",
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
        ) -> tuple[bytes | None, str, datetime | None, str]:
            del timeout_seconds, maximum_bytes
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
        later_bundle = build_source_bundle(root / "later", vintage="2026-08-31")
        blocked = archive.build(
            args(
                archive_root,
                later_bundle,
                collected_at="2026-08-31T12:00:00Z",
            )
        )
        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "object_hash_mismatch" in blocked["blockers"][0]
        assert len(index_rows(archive_root)) == 1


def test_cross_asset_provenance_rejects_credentials_before_persistence() -> None:
    for replacement in (
        "https://user:password@example.test/SPY",
        "https://example.test/SPY?token=secret",
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
            assert "credential_bearing_or_nonpublic_url" in blocked["blockers"][0]
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
        calls = 0

        def fail_first_index(path: Path, entries: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated_index_interruption")
            original_write_index(path, entries)

        try:
            archive.write_index = fail_first_index
            first = archive.build(args(archive_root, bundle))
        finally:
            archive.write_index = original_write_index
        assert first["status"] == archive.BLOCKED_STATUS
        assert not (archive_root / "archive_index.jsonl").exists()
        assert len(list((archive_root / "snapshots").iterdir())) == 1

        recovered = archive.build(args(archive_root, bundle))
        assert recovered["status"] == archive.READY_STATUS
        assert recovered["idempotent_reuse"] is True
        assert len(index_rows(archive_root)) == 1


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
        ) -> None:
            self.url = url
            self._chunks = chunks
            self.headers = {"Content-Length": content_length} if content_length else {}
            self.history = [SimpleNamespace(url=item) for item in (history or [])]

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

        archive.requests.get = lambda *_args, **_kwargs: FakeResponse(
            url="https://evil.example/payload",
            history=[requested],
            chunks=[b"payload"],
        )
        try:
            archive.network_fetch(
                url=requested, params=None, timeout_seconds=1, maximum_bytes=100
            )
            raise AssertionError("cross-origin redirect was accepted")
        except archive.ArchiveContractError as exc:
            assert "network_redirect_origin_mismatch" in str(exc)

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

        def fake_fetch(
            *,
            url: str,
            params: dict | None,
            timeout_seconds: int,
            maximum_bytes: int,
        ) -> tuple[bytes | None, str, datetime | None, str]:
            del timeout_seconds, maximum_bytes
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
                return json.dumps(payload).encode("utf-8"), "", fixed_time, url
            raise AssertionError("Cboe should not be reached after FRED secret echo")

        try:
            os.environ["FRED_API_KEY"] = secret
            archive.network_fetch = fake_fetch
            archive.utc_now = lambda: fixed_time
            archive_root = root / "archive"
            blocked = archive.build(
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

        assert blocked["status"] == archive.BLOCKED_STATUS
        assert "raw_response_contains_api_key" in blocked["blockers"][0]
        assert secret not in json.dumps(blocked)
        assert not list((archive_root / "objects" / "raw").glob("*"))


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
    test_equity_and_index_put_call_are_not_substitutable()
    test_missing_cross_asset_stays_missing_without_carry_or_imputation()
    test_existing_content_tamper_is_detected_before_new_capture()
    test_cross_asset_provenance_rejects_credentials_before_persistence()
    test_present_source_with_no_rows_blocks_snapshot()
    test_verified_snapshot_is_recovered_after_index_interruption()
    test_network_fetch_is_bounded_and_restricts_redirect_origins()
    test_runtime_clock_preserves_subsecond_capture_time()
    test_archive_writer_lock_rejects_a_concurrent_writer()
    test_fred_response_echoing_api_key_is_rejected_before_archive_write()
    test_stale_daily_options_session_blocks_snapshot()
    test_prelaunch_collection_is_rejected()
    print("run287_chameleon_forward_archive_smoke: PASS")
