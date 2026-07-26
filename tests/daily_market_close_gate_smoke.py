#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.run_daily_market_session_gate import evaluate_market_session  # noqa: E402
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402
from tools.validate_daily_close_prices import (  # noqa: E402
    collect_required_tickers,
    evaluate_close_coverage,
)


def write_price(cache: Path, ticker: str, dates: list[str], closes: list[float]) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {"Close": closes, "Adj Close": closes, "Open": closes},
        index=pd.to_datetime(dates),
    )
    frame.to_parquet(cache / px_cache_name(ticker))


def test_session_gate_handles_regular_holiday_weekend_and_early_close() -> None:
    regular = evaluate_market_session(now_utc="2026-07-14T01:15:00Z")
    assert regular["ready"] is True
    assert regular["status"] == "READY_COMPLETED_SESSION"
    assert regular["session_date"] == "2026-07-13"

    too_soon = evaluate_market_session(now_utc="2026-07-13T20:30:00Z")
    assert too_soon["ready"] is False
    assert too_soon["status"] == "SKIP_CLOSE_SETTLEMENT_BUFFER"

    holiday = evaluate_market_session(now_utc="2026-07-04T01:15:00Z")
    assert holiday["ready"] is False
    assert holiday["status"] == "SKIP_STALE_SESSION"
    assert holiday["session_date"] == "2026-07-02"

    weekend = evaluate_market_session(now_utc="2026-07-05T01:15:00Z")
    assert weekend["ready"] is False
    assert weekend["status"] == "SKIP_STALE_SESSION"

    early_close = evaluate_market_session(now_utc="2026-11-28T01:15:00Z")
    assert early_close["ready"] is True
    assert early_close["session_date"] == "2026-11-27"
    assert early_close["early_close_aware"] is True


def test_session_gate_selects_only_explicit_completed_catchup_sessions() -> None:
    catchup = evaluate_market_session(
        now_utc="2026-07-24T01:00:00Z",
        force=True,
        session_date="2026-07-17",
    )
    assert catchup["ready"] is True
    assert catchup["status"] == "READY_FORCED_CATCHUP_SESSION"
    assert catchup["session_date"] == "2026-07-17"
    assert catchup["latest_completed_session_date"] == "2026-07-23"
    assert catchup["catchup_mode"] is True

    for kwargs, message in (
        (
            {
                "now_utc": "2026-07-24T01:00:00Z",
                "session_date": "2026-07-17",
            },
            "--session-date requires --force",
        ),
        (
            {
                "now_utc": "2026-07-24T01:00:00Z",
                "force": True,
                "session_date": "2026-07-18",
            },
            "--session-date must be an NYSE session",
        ),
        (
            {
                "now_utc": "2026-07-23T18:00:00Z",
                "force": True,
                "session_date": "2026-07-23",
            },
            "--session-date must be a completed NYSE session",
        ),
        (
            {
                "now_utc": "2026-07-24T01:00:00Z",
                "force": True,
                "session_date": "2026-07-17T00:00:00",
            },
            "--session-date must use canonical YYYY-MM-DD",
        ),
    ):
        try:
            evaluate_market_session(**kwargs)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"unsafe selected session was accepted: {kwargs}")


def test_exact_close_coverage_includes_targets_accounts_pending_and_benchmarks() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = root / "cache"
        session = pd.Timestamp("2026-07-13")
        target = root / "main_target.csv"
        pd.DataFrame(
            [
                {"rebalance_date": "2026-07-10", "ticker": "OLD", "weight": 1.0},
                {"rebalance_date": "2026-07-13", "ticker": "AAA", "weight": 1.0},
            ]
        ).to_csv(target, index=False)
        account = root / "account.json"
        account.write_text(
            json.dumps({"positions": [{"ticker": "BBB", "shares": 10}]}),
            encoding="utf-8",
        )
        state = root / "state"
        pending = state / "main" / "pending_orders.csv"
        pending.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [{"ticker": "CCC", "pending_status": "PENDING_NEXT_CLOSE"}]
        ).to_csv(pending, index=False)

        tickers, sources = collect_required_tickers(
            targets=[target],
            accounts=[account],
            state_dir=state,
            required_tickers=["SPY"],
            session_date=session,
        )
        assert tickers == {"AAA", "BBB", "CCC", "SPY"}
        assert "OLD" not in tickers
        assert sources["pending_orders"] == ["CCC"]

        for ticker in ["AAA", "CCC", "SPY"]:
            write_price(cache, ticker, ["2026-07-13"], [100.0])
        write_price(cache, "BBB", ["2026-07-10"], [90.0])
        blocked = evaluate_close_coverage(price_cache=cache, session_date=session, tickers=tickers)
        assert blocked["status"] == "BLOCKED_MISSING_EXACT_CLOSE"
        assert blocked["missing_tickers"] == ["BBB"]
        assert blocked["prior_session_fallback_allowed"] is False

        write_price(cache, "BBB", ["2026-07-10", "2026-07-13"], [90.0, 91.0])
        passed = evaluate_close_coverage(price_cache=cache, session_date=session, tickers=tickers)
        assert passed["status"] == "PASS"
        assert passed["exact_close_coverage"] is True
        assert passed["missing_ticker_count"] == 0


def test_exact_close_universe_excludes_future_only_target() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "future_target.csv"
        pd.DataFrame(
            [
                {
                    "rebalance_date": "2026-07-14",
                    "ticker": "FUT",
                    "weight": 1.0,
                }
            ]
        ).to_csv(target, index=False)
        tickers, sources = collect_required_tickers(
            targets=[target],
            accounts=[],
            state_dir=root / "state",
            required_tickers=["SPY"],
            session_date=pd.Timestamp("2026-07-13"),
        )
        assert tickers == {"SPY"}
        assert "target:future_target.csv" not in sources


def main() -> int:
    test_session_gate_handles_regular_holiday_weekend_and_early_close()
    test_session_gate_selects_only_explicit_completed_catchup_sessions()
    test_exact_close_coverage_includes_targets_accounts_pending_and_benchmarks()
    test_exact_close_universe_excludes_future_only_target()
    print("daily_market_close_gate_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
