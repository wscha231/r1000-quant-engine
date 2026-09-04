#!/usr/bin/env python3
"""Smoke checks for the read-only multi-session catch-up price capture."""
from __future__ import annotations

import hashlib
import json
import tempfile
from argparse import Namespace
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.run287_risk_outcome_parent_preflight_smoke import (  # noqa: E402
    write_real_paper_fixture,
)
from tools.build_run287_catchup_price_capture import (  # noqa: E402
    CAPTURE_STATUS,
    CaptureError,
    build_capture,
    plan_payload,
    sha256_file,
    validate_source_identity,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


THROUGH = "2026-07-28"


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def prepare_plan(root: Path) -> tuple[dict, dict[str, object], Path]:
    fixture = write_real_paper_fixture(root)
    capture_root = root / "capture"
    capture_root.mkdir()
    plan = plan_payload(
        Namespace(
            state_dir=str(fixture["paper"]),
            heads_root=str(fixture["heads"]),
            through_session_date=THROUGH,
            selection_output=str(capture_root / "paper_selection.json"),
            ticker_book=str(capture_root / "ticker_union.csv"),
            plan_output=str(capture_root / "plan.json"),
            generated_at_utc="2026-07-29T00:00:00Z",
        )
    )
    return plan, fixture, capture_root


def write_price_cache(root: Path, tickers: list[str], *, stale: str = "") -> Path:
    cache = root / "price_cache"
    cache.mkdir()
    cache_files: dict[str, dict[str, object]] = {}
    dates = pd.to_datetime(["2026-07-27", "2026-07-28", "2026-07-29"])
    for index, ticker in enumerate(tickers):
        selected_dates = dates[1:] if ticker == stale else dates
        base = 100.0 + index
        values = [base + offset for offset in range(len(selected_dates))]
        frame = pd.DataFrame(
            {
                "Open": values,
                "High": [value + 2.0 for value in values],
                "Low": [value - 2.0 for value in values],
                "Close": [value + 1.0 for value in values],
                "Adj Close": [value + 1.0 for value in values],
                "Volume": [1_000_000.0] * len(values),
            },
            index=selected_dates,
        )
        path = cache / px_cache_name(ticker)
        frame.to_parquet(path)
        cache_files[ticker] = {
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    manifest = {
        "schema_version": "run287-replay-price-cache-manifest-v2",
        "status": "completed",
        "exact_operating_universe": True,
        "refresh_through_date": THROUGH,
        "refresh_through_exact_coverage": True,
        "refresh_through_ticker_count": len(tickers),
        "refresh_through_exact_ticker_count": len(tickers),
        "cache_files": cache_files,
        "review_only": True,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
    }
    (cache / "replay_price_cache_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return cache


def build_args(
    fixture: dict[str, object], capture_root: Path, price_cache: Path
) -> Namespace:
    return Namespace(
        state_dir=str(fixture["paper"]),
        heads_root=str(fixture["heads"]),
        selection=str(capture_root / "paper_selection.json"),
        plan=str(capture_root / "plan.json"),
        ticker_book=str(capture_root / "ticker_union.csv"),
        price_cache=str(price_cache),
        output_root=str(capture_root),
        artifact_root_marker=str(
            capture_root.parent
            / "run287_catchup_price_capture_artifact_root.json"
        ),
        repository="wscha231/r1000-quant-engine",
        source_sha="a" * 40,
        run_id="33860000000",
        run_attempt="1",
        event_name="workflow_dispatch",
        job_key="capture_catchup_evidence",
        generated_at_utc="",
    )


def test_capture_binds_both_target_books_and_excludes_future_rows() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, fixture, capture_root = prepare_plan(root)
        assert plan["pending_sessions"] == ["2026-07-27", "2026-07-28"]
        assert plan["ticker_union"] == ["AAA", "BBB", "QQQ", "SMH", "SOXX", "SPY"]
        assert plan["ticker_sources"] == {
            "target:concentrated/effective_target_latest.csv": ["BBB"],
            "target:main/effective_target_latest.csv": ["AAA"],
            "state_account:concentrated": ["BBB"],
            "state_account:main": ["AAA"],
            "required": ["QQQ", "SMH", "SOXX", "SPY"],
        }
        state_before = tree_hashes(Path(fixture["paper"]))
        heads_before = tree_hashes(Path(fixture["heads"]))
        cache = write_price_cache(root, plan["ticker_union"])
        payload = build_capture(build_args(fixture, capture_root, cache))
        assert payload["status"] == CAPTURE_STATUS
        assert payload["pending_session_count"] == 2
        assert payload["drive_mutated"] is False
        assert payload["ledger_mutated"] is False
        assert payload["orders_generated"] is False
        assert tree_hashes(Path(fixture["paper"])) == state_before
        assert tree_hashes(Path(fixture["heads"])) == heads_before

        first = pd.read_csv(
            capture_root
            / "sessions/2026-07-27/outputs/daily_market_snapshot/market_snapshot.csv"
        )
        assert set(first["latest_price_date"]) == {"2026-07-27"}
        assert set(first["price_cache_path"]) == {
            f"source_price_cache/{px_cache_name(ticker)}"
            for ticker in plan["ticker_union"]
        }
        aaa = first[first["ticker"].eq("AAA")].iloc[0]
        assert float(aaa["previous_close"]) == 101.0
        for record in payload["sessions"]:
            summary_path = (
                capture_root
                / "sessions"
                / record["session_date"]
                / "outputs/daily_market_snapshot/summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            expected_output = (
                "outputs/run287_catchup_price_capture/sessions/"
                f"{record['session_date']}/outputs/daily_market_snapshot"
            )
            assert summary["output_dir"] == expected_output
            assert summary["generated_at_utc"] == payload["generated_at_utc"]
            for file_record in record["files"].values():
                relative = Path(file_record["path"]).relative_to(
                    "outputs/run287_catchup_price_capture"
                )
                path = capture_root / relative
                assert path.is_file()
                assert sha256_file(path) == file_record["sha256"]


def test_capture_fails_closed_on_missing_intermediate_close() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, fixture, capture_root = prepare_plan(root)
        cache = write_price_cache(root, plan["ticker_union"], stale="BBB")
        try:
            build_capture(build_args(fixture, capture_root, cache))
        except CaptureError as exc:
            assert "exact_session_price_coverage:2026-07-27:BBB" in str(exc)
        else:
            raise AssertionError("missing intermediate exact close was accepted")
        assert not (capture_root / "manifest.json").exists()


def test_capture_fails_closed_on_price_or_paper_tamper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, fixture, capture_root = prepare_plan(root)
        cache = write_price_cache(root, plan["ticker_union"])
        path = cache / px_cache_name("AAA")
        path.write_bytes(path.read_bytes() + b"tamper")
        try:
            build_capture(build_args(fixture, capture_root, cache))
        except CaptureError as exc:
            assert str(exc) == "price_cache_file_hash:AAA"
        else:
            raise AssertionError("tampered price cache was accepted")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        plan, fixture, capture_root = prepare_plan(root)
        cache = write_price_cache(root, plan["ticker_union"])
        account = Path(fixture["paper"]) / "main/account_state_latest.json"
        account.write_bytes(account.read_bytes() + b" ")
        try:
            build_capture(build_args(fixture, capture_root, cache))
        except Exception as exc:
            assert "snapshot checksum mismatch" in str(exc)
        else:
            raise AssertionError("tampered canonical paper state was accepted")


def test_capture_rejects_workflow_rerun_identity() -> None:
    args = Namespace(
        repository="wscha231/r1000-quant-engine",
        source_sha="a" * 40,
        run_id="33860000000",
        run_attempt="2",
        event_name="workflow_dispatch",
        job_key="capture_catchup_evidence",
    )
    try:
        validate_source_identity(args)
    except CaptureError as exc:
        assert str(exc) == "source_identity_invalid"
    else:
        raise AssertionError("a rerun capture identity was accepted")


if __name__ == "__main__":
    test_capture_binds_both_target_books_and_excludes_future_rows()
    test_capture_fails_closed_on_missing_intermediate_close()
    test_capture_fails_closed_on_price_or_paper_tamper()
    test_capture_rejects_workflow_rerun_identity()
    print("run287_catchup_price_capture_smoke: PASS")
