#!/usr/bin/env python3
"""Smoke checks for replay price-cache freshness detection."""
from __future__ import annotations

import json
import os
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_replay_price_cache import (  # noqa: E402
    begin_price_cache_transaction,
    exit_code_for_payload,
    has_valid_exact_close,
    install_price_cache_transaction,
    mark_price_cache_transaction_committed,
    publish_price_cache_manifest_transaction,
    recover_price_cache_transaction,
    run,
    settle_price_cache_transaction,
    write_price_frames_atomically,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.write_run287_price_refresh_attempt import (  # noqa: E402
    build_payload as build_price_refresh_attempt,
    write_json_atomic as write_price_refresh_attempt,
)


def price_frame(date: str, close: float = 10.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [close],
            "Close": [close],
            "Adj Close": [close],
            "Volume": [1_000_000],
        },
        index=pd.DatetimeIndex([pd.Timestamp(date)]),
    )


def write_price(
    cache: Path,
    ticker: str,
    date: str,
    close: float = 10.0,
) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    price_frame(date, close).to_parquet(cache / px_cache_name(ticker))


def test_replay_price_cache_marks_stale_existing_tickers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 0.5},
                {"rebalance_date": "2026-01-31", "ticker": "BBB", "weight": 0.5},
                {"rebalance_date": "2026-01-31", "ticker": "CCC", "weight": 0.5},
            ]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2000-01-03")
        write_price(cache, "BBB", pd.Timestamp.utcnow().date().isoformat())

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="",
                end="",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=2,
                refresh_through_date="",
                dry_run=True,
            )
        )
        assert payload["status"] == "dry_run"
        assert payload["missing_before"] == 1
        assert payload["stale_before"] == 1
        assert payload["download_target_count"] == 2
        assert payload["requested_end"] > payload["end"]
        assert payload["end"] == pd.Timestamp.utcnow().date().isoformat()
        assert payload["actual_cached_ticker_count"] == 2
        assert payload["manifest_end_source"] == "actual_cached_bars"


def test_replay_price_cache_always_includes_required_tickers() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame([{"rebalance_date": "2026-01-31", "ticker": "AAA", "weight": 1.0}]).to_csv(book, index=False)
        cache = root / "cache_prices"
        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="",
                end="",
                batch_size=40,
                max_tickers=1,
                required_tickers=["SPY", "QQQ"],
                refresh_stale_days=-1,
                refresh_through_date="",
                dry_run=True,
            )
        )
        assert payload["required_tickers"] == ["QQQ", "SPY"]
        assert payload["ticker_count"] == 3
        assert payload["download_target_count"] == 3


def test_replay_price_cache_uses_exact_gate_operating_union() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-07-23",
                    "ticker": "OLD",
                    "weight": 1.0,
                },
                {
                    "rebalance_date": "2026-07-24",
                    "ticker": "AAA",
                    "weight": 1.0,
                },
            ]
        ).to_csv(book, index=False)
        account = root / "bootstrap_account.json"
        account.write_text(
            json.dumps(
                {
                    "positions": [
                        {"ticker": "HELD", "shares": 10},
                        {"ticker": "ZERO", "shares": 0},
                    ]
                }
            ),
            encoding="utf-8",
        )
        state_dir = root / "state"
        lane = state_dir / "main"
        lane.mkdir(parents=True)
        (lane / "account_state_latest.json").write_text(
            json.dumps(
                {"positions": [{"ticker": "STATE", "quantity": 5}]}
            ),
            encoding="utf-8",
        )
        pd.DataFrame(
            [
                {"ticker": "PEND", "pending_status": "PENDING_NEXT_CLOSE"},
                {"ticker": "DONE", "pending_status": "FILLED"},
            ]
        ).to_csv(lane / "pending_orders.csv", index=False)
        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(root / "cache_prices"),
                start="",
                end="",
                batch_size=40,
                max_tickers=0,
                required_tickers=["SPY"],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=True,
                accounts=[str(account)],
                state_dir=str(state_dir),
                exact_operating_universe=True,
            )
        )
        assert payload["ticker_count"] == 5
        assert payload["book_ticker_count"] == 1
        assert payload["operating_required_ticker_count"] == 5
        assert payload["download_target_count"] == 5
        assert payload["operating_ticker_sources"] == {
            "account:bootstrap_account.json": ["HELD"],
            "pending_orders": ["PEND"],
            "required": ["SPY"],
            "state_account:main": ["STATE"],
            "target:book.csv": ["AAA"],
        }


def test_replay_price_cache_refreshes_through_required_session() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame([{"rebalance_date": "2026-07-17", "ticker": "AAA", "weight": 1.0}]).to_csv(
            book, index=False
        )
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-17")
        write_price(cache, "SOXX", "2026-07-16")

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="",
                end="",
                batch_size=40,
                max_tickers=0,
                required_tickers=["SOXX"],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-17",
                dry_run=True,
            )
        )
        assert payload["refresh_through_date"] == "2026-07-17"
        assert payload["behind_refresh_through_before"] == 1
        assert payload["download_target_count"] == 1


def test_replay_price_cache_rejects_stale_batch_without_partial_write() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-07-24", "ticker": "AAA", "weight": 0.5},
                {"rebalance_date": "2026-07-24", "ticker": "BBB", "weight": 0.5},
            ]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=10.0)
        write_price(cache, "BBB", "2026-07-23", close=11.0)
        calls: list[list[str]] = []

        def stale_download(
            tickers: list[str],
            _start: str,
            _end: str,
        ) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
            calls.append(list(tickers))
            frames = {
                ticker: price_frame(
                    "2026-07-24" if ticker == "AAA" else "2026-07-23",
                    close=20.0 if ticker == "AAA" else 21.0,
                )
                for ticker in tickers
            }
            return frames, {"provider": "fixture"}

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="2026-07-20",
                end="2026-07-26",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=False,
            ),
            download_fn=stale_download,
        )
        assert calls == [["AAA", "BBB"], ["BBB"], ["BBB"]]
        assert payload["status"] == "blocked_missing_required_through_date"
        assert payload["download_attempt_count"] == 3
        assert payload["download_retry_count"] == 2
        assert payload["written"] == 0
        assert payload["required_through_write_aborted"] is True
        assert payload["existing_cache_preserved_on_block"] is True
        assert payload["failed"] == ["BBB"]
        assert payload["download_failure_reasons"] == {
            "BBB": "missing_exact_required_date"
        }
        assert payload["behind_refresh_through_after"] == 2
        assert payload["refresh_through_exact_ticker_count"] == 0
        assert payload["refresh_through_exact_coverage"] is False
        assert payload["common_coverage_end"] == "2026-07-23"
        for ticker, expected_close in (("AAA", 10.0), ("BBB", 11.0)):
            preserved = pd.read_parquet(cache / px_cache_name(ticker))
            assert pd.Timestamp(preserved.index.max()).date().isoformat() == "2026-07-23"
            assert float(preserved.iloc[-1]["Close"]) == expected_close


def test_replay_price_cache_commits_after_exact_retry() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-07-24", "ticker": "AAA", "weight": 0.5},
                {"rebalance_date": "2026-07-24", "ticker": "BBB", "weight": 0.5},
            ]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        cache.mkdir(parents=True, exist_ok=True)
        for ticker in ("AAA", "BBB"):
            history = pd.concat(
                [
                    price_frame("2026-07-18", close=8.0),
                    price_frame("2026-07-23", close=10.0),
                ]
            )
            history["Legacy"] = [1.0, 2.0]
            history.to_parquet(cache / px_cache_name(ticker))
        calls: list[list[str]] = []

        def retry_download(
            tickers: list[str],
            _start: str,
            _end: str,
        ) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
            calls.append(list(tickers))
            frames: dict[str, pd.DataFrame] = {}
            for ticker in tickers:
                exact = ticker == "AAA" or len(calls) > 1
                frames[ticker] = price_frame(
                    "2026-07-24" if exact else "2026-07-23",
                    close=30.0 if ticker == "AAA" else 31.0,
                )
            return frames, {"provider": "fixture"}

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="2026-07-20",
                end="2026-07-26",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=False,
            ),
            download_fn=retry_download,
        )
        assert calls == [["AAA", "BBB"], ["BBB"]]
        assert payload["status"] == "completed"
        assert payload["download_attempt_count"] == 2
        assert payload["written"] == 2
        assert payload["written_tickers"] == ["AAA", "BBB"]
        assert payload["failed_count"] == 0
        assert payload["behind_refresh_through_after"] == 0
        assert payload["refresh_through_exact_ticker_count"] == 2
        assert payload["refresh_through_exact_coverage"] is True
        assert payload["common_coverage_end"] == "2026-07-24"
        for ticker in ("AAA", "BBB"):
            refreshed = pd.read_parquet(cache / px_cache_name(ticker))
            assert pd.Timestamp(refreshed.index.max()).date().isoformat() == "2026-07-24"
            assert [
                pd.Timestamp(value).date().isoformat()
                for value in refreshed.index
            ] == ["2026-07-18", "2026-07-23", "2026-07-24"]
            assert list(refreshed["Legacy"].dropna()) == [1.0, 2.0]


def test_replay_price_cache_retries_download_exceptions() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [{"rebalance_date": "2026-07-24", "ticker": "AAA", "weight": 1.0}]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=10.0)
        call_count = 0

        def flaky_download(
            tickers: list[str],
            _start: str,
            _end: str,
        ) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TimeoutError("fixture_provider_timeout")
            return {
                ticker: price_frame("2026-07-24", close=20.0)
                for ticker in tickers
            }, {"provider": "fixture"}

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="2026-07-20",
                end="2026-07-26",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=False,
            ),
            download_fn=flaky_download,
        )
        assert call_count == 3
        assert payload["status"] == "completed"
        assert payload["download_attempt_count"] == 3
        assert payload["download_retry_count"] == 2
        assert [
            audit["error"]
            for audit in payload["download_batch_audits"][:2]
        ] == [
            "TimeoutError:fixture_provider_timeout",
            "TimeoutError:fixture_provider_timeout",
        ]


def test_replay_price_cache_global_max_does_not_hide_missing_close() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-07-24", "ticker": "AAA", "weight": 0.5},
                {"rebalance_date": "2026-07-24", "ticker": "BBB", "weight": 0.5},
            ]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-24")
        write_price(cache, "BBB", "2026-07-23")

        def stale_download(
            tickers: list[str],
            _start: str,
            _end: str,
        ) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
            return {
                ticker: price_frame("2026-07-23") for ticker in tickers
            }, {"provider": "fixture"}

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="2026-07-20",
                end="2026-07-26",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=False,
            ),
            download_fn=stale_download,
        )
        assert payload["status"] == "blocked_missing_required_through_date"
        assert payload["end"] == "2026-07-24"
        assert payload["common_coverage_end"] == "2026-07-23"
        assert payload["behind_refresh_through_after"] == 1
        assert payload["refresh_through_exact_ticker_count"] == 1
        assert payload["refresh_through_exact_coverage"] is False


def test_replay_price_cache_rejects_nan_exact_close() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [{"rebalance_date": "2026-07-24", "ticker": "AAA", "weight": 1.0}]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=10.0)

        def nan_download(
            tickers: list[str],
            _start: str,
            _end: str,
        ) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
            frame = price_frame("2026-07-24", close=20.0)
            frame.loc[:, "Adj Close"] = float("nan")
            return {ticker: frame.copy() for ticker in tickers}, {
                "provider": "fixture"
            }

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="2026-07-20",
                end="2026-07-26",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=False,
            ),
            download_fn=nan_download,
        )
        assert payload["status"] == "blocked_missing_required_through_date"
        assert payload["written"] == 0
        assert payload["download_failure_reasons"] == {
            "AAA": "invalid_exact_required_close"
        }
        preserved = pd.read_parquet(cache / px_cache_name("AAA"))
        assert pd.Timestamp(preserved.index.max()).date().isoformat() == "2026-07-23"


def test_replay_price_cache_rolls_back_replace_failure() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        write_price(cache, "BBB", "2026-07-23", close=2.0)
        real_replace = os.replace
        install_count = 0
        failed_once = False

        def fail_second_install(source: str | Path, destination: str | Path) -> Any:
            nonlocal install_count, failed_once
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.suffix == ".tmp"
                and destination_path.suffix == ".parquet"
            ):
                install_count += 1
                if install_count == 2 and not failed_once:
                    failed_once = True
                    raise OSError("fixture_replace_failure")
            return real_replace(source, destination)

        try:
            write_price_frames_atomically(
                {
                    "AAA": price_frame("2026-07-24", close=10.0),
                    "BBB": price_frame("2026-07-24", close=20.0),
                },
                cache,
                replace_fn=fail_second_install,
            )
        except OSError as exc:
            assert str(exc) == "fixture_replace_failure"
        else:
            raise AssertionError("replace failure must propagate")
        for ticker, expected_close in (("AAA", 1.0), ("BBB", 2.0)):
            preserved = pd.read_parquet(cache / px_cache_name(ticker))
            assert pd.Timestamp(preserved.index.max()).date().isoformat() == "2026-07-23"
            assert float(preserved.iloc[-1]["Close"]) == expected_close
        assert not list(cache.glob(".*.tmp"))
        assert not list(cache.glob(".*.bak"))


def test_replay_price_cache_removes_new_ticker_on_replace_failure() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        real_replace = os.replace
        install_count = 0
        failed_once = False

        def fail_new_ticker_install(
            source: str | Path,
            destination: str | Path,
        ) -> Any:
            nonlocal install_count, failed_once
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                source_path.suffix == ".tmp"
                and destination_path.suffix == ".parquet"
            ):
                install_count += 1
                if install_count == 2 and not failed_once:
                    failed_once = True
                    raise OSError("fixture_new_ticker_failure")
            return real_replace(source, destination)

        try:
            write_price_frames_atomically(
                {
                    "AAA": price_frame("2026-07-24", close=10.0),
                    "BBB": price_frame("2026-07-24", close=20.0),
                },
                cache,
                replace_fn=fail_new_ticker_install,
            )
        except OSError as exc:
            assert str(exc) == "fixture_new_ticker_failure"
        else:
            raise AssertionError("new ticker replace failure must propagate")
        preserved = pd.read_parquet(cache / px_cache_name("AAA"))
        assert float(preserved.iloc[-1]["Close"]) == 1.0
        assert not (cache / px_cache_name("BBB")).exists()


def test_replay_price_cache_recovers_interrupted_prepared_transaction() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        transaction = begin_price_cache_transaction(
            {
                "AAA": price_frame("2026-07-24", close=10.0),
                "BBB": price_frame("2026-07-24", close=20.0),
            },
            cache,
        )
        install_price_cache_transaction(transaction)
        assert float(
            pd.read_parquet(cache / px_cache_name("AAA")).iloc[-1]["Close"]
        ) == 10.0
        assert (cache / px_cache_name("BBB")).is_file()

        recovery = recover_price_cache_transaction(cache)
        assert recovery == "rolled_back_prepared"
        preserved = pd.read_parquet(cache / px_cache_name("AAA"))
        assert float(preserved.iloc[-1]["Close"]) == 1.0
        assert not (cache / px_cache_name("BBB")).exists()
        assert not (cache / "replay_price_cache_transaction.json").exists()


def test_replay_price_cache_manifest_failure_rolls_back_prices() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        manifest = cache / "replay_price_cache_manifest.json"
        manifest.write_text('{"generation":"old"}\n', encoding="utf-8")
        transaction = begin_price_cache_transaction(
            {"AAA": price_frame("2026-07-24", close=10.0)},
            cache,
        )
        install_price_cache_transaction(transaction)
        real_replace = os.replace
        failed_once = False

        def fail_manifest_install(
            source: str | Path,
            destination: str | Path,
        ) -> Any:
            nonlocal failed_once
            source_path = Path(source)
            destination_path = Path(destination)
            if (
                destination_path == manifest
                and source_path.suffix == ".tmp"
                and not failed_once
            ):
                failed_once = True
                raise OSError("fixture_manifest_failure")
            return real_replace(source, destination)

        try:
            publish_price_cache_manifest_transaction(
                transaction,
                manifest,
                {"generation": "new"},
                replace_fn=fail_manifest_install,
            )
        except OSError as exc:
            assert str(exc) == "fixture_manifest_failure"
            settle_price_cache_transaction(
                transaction,
                replace_fn=fail_manifest_install,
            )
        else:
            raise AssertionError("manifest replace failure must propagate")
        preserved = pd.read_parquet(cache / px_cache_name("AAA"))
        assert float(preserved.iloc[-1]["Close"]) == 1.0
        assert manifest.read_text(encoding="utf-8") == '{"generation":"old"}\n'


def test_replay_price_cache_rejects_manifest_ticker_file_mismatch() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        transaction = begin_price_cache_transaction(
            {"AAA": price_frame("2026-07-24", close=10.0)},
            cache,
        )
        install_price_cache_transaction(transaction)
        price_record = transaction["records"][0]
        payload = {
            "schema_version": "run287-replay-price-cache-manifest-v2",
            "status": "completed",
            "refresh_through_date": "2026-07-24",
            "refresh_through_exact_coverage": True,
            "refresh_through_missing_tickers": [],
            "refresh_through_exact_ticker_count": 1,
            "refresh_through_ticker_count": 1,
            "ticker_count": 1,
            "cache_files": {
                "ZZZ": {
                    "file": price_record["destination"],
                    "sha256": price_record["staged_sha256"],
                    "bytes": price_record["staged_bytes"],
                }
            },
        }
        try:
            publish_price_cache_manifest_transaction(
                transaction,
                cache / "replay_price_cache_manifest.json",
                payload,
            )
        except ValueError as exc:
            assert str(exc) == "price_cache_manifest_cache_entry_invalid"
            settle_price_cache_transaction(transaction)
        else:
            raise AssertionError("ticker/file manifest mismatch must fail closed")
        preserved = pd.read_parquet(cache / px_cache_name("AAA"))
        assert float(preserved.iloc[-1]["Close"]) == 1.0
        assert not (cache / "replay_price_cache_manifest.json").exists()


def test_replay_price_cache_recomputes_exact_manifest_contract() -> None:
    for staged_date, ticker_count, expected_error in (
        (
            "2026-07-24",
            999,
            "price_cache_manifest_exact_count_parity_invalid",
        ),
        (
            "2026-07-23",
            1,
            "price_cache_manifest_exact_close_missing:AAA",
        ),
    ):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache_prices"
            write_price(cache, "AAA", "2026-07-22", close=1.0)
            transaction = begin_price_cache_transaction(
                {"AAA": price_frame(staged_date, close=10.0)},
                cache,
            )
            install_price_cache_transaction(transaction)
            record = transaction["records"][0]
            payload = {
                "schema_version": "run287-replay-price-cache-manifest-v2",
                "status": "completed",
                "refresh_through_date": "2026-07-24",
                "refresh_through_exact_coverage": True,
                "refresh_through_missing_tickers": [],
                "refresh_through_exact_ticker_count": 1,
                "refresh_through_ticker_count": 1,
                "ticker_count": ticker_count,
                "cache_files": {
                    "AAA": {
                        "file": record["destination"],
                        "sha256": record["staged_sha256"],
                        "bytes": record["staged_bytes"],
                    }
                },
            }
            try:
                publish_price_cache_manifest_transaction(
                    transaction,
                    cache / "replay_price_cache_manifest.json",
                    payload,
                )
            except ValueError as exc:
                assert str(exc) == expected_error
                settle_price_cache_transaction(transaction)
            else:
                raise AssertionError(
                    "self-reported exact manifest must be recomputed"
                )
            preserved = pd.read_parquet(cache / px_cache_name("AAA"))
            assert float(preserved.iloc[-1]["Close"]) == 1.0


def test_replay_price_cache_rejects_invalid_journal_before_recovery() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        write_price(cache, "BBB", "2026-07-23", close=2.0)
        transaction = begin_price_cache_transaction(
            {
                "AAA": price_frame("2026-07-24", close=10.0),
                "BBB": price_frame("2026-07-24", close=20.0),
            },
            cache,
        )
        install_price_cache_transaction(transaction)
        journal = cache / "replay_price_cache_transaction.json"
        payload = json.loads(journal.read_text(encoding="utf-8"))
        payload["records"][1]["kind"] = "arbitrary_file"
        journal.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        try:
            recover_price_cache_transaction(cache)
        except ValueError as exc:
            assert str(exc) == "price_cache_transaction_kind_invalid"
        else:
            raise AssertionError("invalid recovery journal must fail closed")
        assert float(
            pd.read_parquet(cache / px_cache_name("AAA")).iloc[-1]["Close"]
        ) == 10.0
        assert float(
            pd.read_parquet(cache / px_cache_name("BBB")).iloc[-1]["Close"]
        ) == 20.0
        assert journal.is_file()


def test_replay_price_cache_keeps_backups_on_corrupt_committed_state() -> None:
    with TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache_prices"
        write_price(cache, "AAA", "2026-07-23", close=1.0)
        transaction = begin_price_cache_transaction(
            {"AAA": price_frame("2026-07-24", close=10.0)},
            cache,
        )
        install_price_cache_transaction(transaction)
        mark_price_cache_transaction_committed(transaction)
        destination = cache / px_cache_name("AAA")
        destination.write_bytes(b"corrupt")

        try:
            recover_price_cache_transaction(cache)
        except ValueError as exc:
            assert "price_cache_committed_file_identity_mismatch" in str(exc)
        else:
            raise AssertionError("corrupt committed state must fail closed")
        record = transaction["records"][0]
        assert (cache / record["backup"]).is_file()
        assert (cache / "replay_price_cache_transaction.json").is_file()


def test_replay_price_cache_fills_exact_gap_without_losing_later_row() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [{"rebalance_date": "2026-07-24", "ticker": "AAA", "weight": 1.0}]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        cache.mkdir(parents=True, exist_ok=True)
        pd.concat(
            [
                price_frame("2026-07-23", close=10.0),
                price_frame("2026-07-25", close=12.0),
            ]
        ).to_parquet(cache / px_cache_name("AAA"))

        def gap_download(
            tickers: list[str],
            _start: str,
            _end: str,
        ) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
            frame = pd.concat(
                [
                    price_frame("2026-07-23", close=20.0),
                    price_frame("2026-07-24", close=21.0),
                ]
            )
            return {ticker: frame.copy() for ticker in tickers}, {
                "provider": "fixture"
            }

        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="2026-07-20",
                end="2026-07-26",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-07-24",
                dry_run=False,
            ),
            download_fn=gap_download,
        )
        assert payload["status"] == "completed"
        assert payload["refresh_through_exact_coverage"] is True
        refreshed = pd.read_parquet(cache / px_cache_name("AAA"))
        assert [
            pd.Timestamp(value).date().isoformat() for value in refreshed.index
        ] == ["2026-07-23", "2026-07-24", "2026-07-25"]
        assert float(refreshed.loc[pd.Timestamp("2026-07-23"), "Close"]) == 10.0
        assert float(refreshed.loc[pd.Timestamp("2026-07-24"), "Close"]) == 21.0
        assert float(refreshed.loc[pd.Timestamp("2026-07-25"), "Close"]) == 12.0


def test_replay_price_cache_accepts_new_york_and_mixed_dst_indexes() -> None:
    required = pd.Timestamp("2026-03-09")
    new_york = price_frame("2026-03-09", close=10.0)
    new_york.index = new_york.index.tz_localize("America/New_York")
    assert has_valid_exact_close(new_york, required)

    mixed_dst = pd.concat(
        [
            price_frame("2026-03-06", close=9.0),
            price_frame("2026-03-09", close=10.0),
        ]
    )
    mixed_dst.index = pd.Index(
        [
            "2026-03-06 00:00:00-05:00",
            "2026-03-09 00:00:00-04:00",
        ],
        dtype="object",
    )
    assert has_valid_exact_close(mixed_dst, required)

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = root / "book.csv"
        pd.DataFrame(
            [{"rebalance_date": "2026-03-09", "ticker": "AAA", "weight": 1.0}]
        ).to_csv(book, index=False)
        cache = root / "cache_prices"
        cache.mkdir(parents=True, exist_ok=True)
        new_york.to_parquet(cache / px_cache_name("AAA"))
        payload = run(
            Namespace(
                books=[str(book)],
                scored="",
                max_scored=0,
                output_dir=str(cache),
                start="",
                end="",
                batch_size=40,
                max_tickers=0,
                required_tickers=[],
                refresh_stale_days=-1,
                refresh_through_date="2026-03-09T00:00:00-04:00",
                dry_run=True,
            )
        )
        assert payload["behind_refresh_through_before"] == 0
        assert payload["behind_refresh_through_after"] == 0
        assert payload["refresh_through_exact_coverage"] is True
        assert payload["refresh_through_date"] == "2026-03-09"


def test_replay_price_cache_cli_exit_contract() -> None:
    assert (
        exit_code_for_payload(
            {
                "status": "blocked_missing_required_through_date",
                "failed_count": 1,
            }
        )
        == 2
    )
    assert (
        exit_code_for_payload(
            {
                "status": "completed",
                "failed_count": 1,
            }
        )
        == 0
    )
    assert exit_code_for_payload({"status": "future_unknown_status"}) == 1


def test_replay_price_refresh_attempt_binds_final_manifest() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        manifest = root / "replay_price_cache_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": (
                        "run287-replay-price-cache-manifest-v2"
                    ),
                    "status": "completed",
                    "refresh_through_date": "2026-07-24",
                    "refresh_through_exact_coverage": True,
                    "refresh_through_ticker_count": 24,
                    "refresh_through_exact_ticker_count": 24,
                }
            ),
            encoding="utf-8",
        )
        prior = root / "prior.json"
        prior.write_text('{"status":"prior"}\n', encoding="utf-8")
        payload = build_price_refresh_attempt(
            Namespace(
                exit_code=0,
                status="completed",
                phase="final_operating_universe",
                output=str(root / "attempt.json"),
                manifest=str(manifest),
                prior_manifest=str(prior),
                required_through_date="2026-07-24",
                source_commit_sha="a" * 40,
                workflow_identity="workflow@refs/heads/test",
                run_id="123",
                run_attempt="1",
            )
        )
        assert payload["manifest_current_attempt"] is True
        assert payload["phase"] == "final_operating_universe"
        assert payload["manifest_sha256"]
        assert payload["prior_manifest_sha256"]
        assert payload["manifest_contract"]["refresh_through_date"] == (
            "2026-07-24"
        )
        output = root / "attempt.json"
        write_price_refresh_attempt(output, payload)
        assert json.loads(output.read_text(encoding="utf-8")) == payload


if __name__ == "__main__":
    test_replay_price_cache_marks_stale_existing_tickers()
    test_replay_price_cache_always_includes_required_tickers()
    test_replay_price_cache_uses_exact_gate_operating_union()
    test_replay_price_cache_refreshes_through_required_session()
    test_replay_price_cache_rejects_stale_batch_without_partial_write()
    test_replay_price_cache_commits_after_exact_retry()
    test_replay_price_cache_retries_download_exceptions()
    test_replay_price_cache_global_max_does_not_hide_missing_close()
    test_replay_price_cache_rejects_nan_exact_close()
    test_replay_price_cache_rolls_back_replace_failure()
    test_replay_price_cache_removes_new_ticker_on_replace_failure()
    test_replay_price_cache_recovers_interrupted_prepared_transaction()
    test_replay_price_cache_manifest_failure_rolls_back_prices()
    test_replay_price_cache_rejects_manifest_ticker_file_mismatch()
    test_replay_price_cache_recomputes_exact_manifest_contract()
    test_replay_price_cache_rejects_invalid_journal_before_recovery()
    test_replay_price_cache_keeps_backups_on_corrupt_committed_state()
    test_replay_price_cache_fills_exact_gap_without_losing_later_row()
    test_replay_price_cache_accepts_new_york_and_mixed_dst_indexes()
    test_replay_price_cache_cli_exit_contract()
    test_replay_price_refresh_attempt_binds_final_manifest()
    print("replay_price_cache_smoke: PASS")
