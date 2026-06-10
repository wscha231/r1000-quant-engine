"""Smoke tests for P0/P1.1/P3 of the leader+crisis hardening plan.

Covers (pure pandas; no parquet engine or price cache required):
  1. P1.1 broker replay champion-filter disable: a research book with its own
     N policy must NOT be coerced when the flag is set.
  2. P0 latest-price-date audit: stale trading-day counting + STALE_PRICE_REVIEW
     flag logic (price loader monkeypatched with synthetic frames).
  3. P3 integrated replay helpers: stress-window metrics, re-entry diagnostics,
     and the report-only verdict gates.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.run_broker_ledger_replay as blr  # noqa: E402
import tools.run_latest_price_date_audit as lpa  # noqa: E402
import tools.run_integrated_leader_crisis_replay as ilc  # noqa: E402


def _research_book() -> pd.DataFrame:
    # N=5 research book whose target_stock_names column would trip the
    # production champion filter (which coerces to target_stock_names=3).
    rows = []
    for ticker in ["AAA", "BBB", "CCC", "DDD", "EEE"]:
        rows.append(
            {
                "rebalance_date": "2024-01-31",
                "ticker": ticker,
                "weight": 0.2,
                "target_stock_names": 5,
                "weighting_mode": "leader_score",
            }
        )
    return pd.DataFrame(rows)


def test_champion_filter_disable_keeps_book() -> None:
    book = _research_book()
    # Default path: champion filter coerces using target_stock_names=3 -> no row
    # matches -> filter keeps all only because no mask matches... verify both paths.
    filtered = blr.normalize_targets(
        book, "concentrated", {"target_stock_names": 3, "weighting_mode": "score_power"}
    )
    disabled = blr.normalize_targets(
        book, "concentrated", {"target_stock_names": 3, "weighting_mode": "score_power"},
        disable_champion_filter=True,
    )
    assert len(disabled) == 5, f"disabled path must keep all 5 rows, got {len(disabled)}"
    # The filtered path must never KEEP MORE than the disabled path; and when a
    # coercive filter partially matches, it rewrites the book (the bug we bypass).
    assert len(filtered) <= len(disabled)
    mixed = pd.concat(
        [book, book.assign(ticker=["FFF", "GGG", "HHH", "III", "JJJ"], target_stock_names=3)],
        ignore_index=True,
    )
    coerced = blr.normalize_targets(mixed, "concentrated", {"target_stock_names": 3})
    raw = blr.normalize_targets(mixed, "concentrated", {"target_stock_names": 3}, disable_champion_filter=True)
    assert len(coerced) == 5 and len(raw) == 10, (len(coerced), len(raw))
    print(f"PASS test_champion_filter_disable_keeps_book coerced={len(coerced)} raw={len(raw)}")


def test_stale_trading_days_counting() -> None:
    # Fri 2026-05-22 bar vs Wed 2026-05-27 audit = Mon+Tue+Wed = 3 business days.
    days = lpa.stale_trading_days_between(pd.Timestamp("2026-05-22"), pd.Timestamp("2026-05-27"))
    assert days == 3, days
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-27"), pd.Timestamp("2026-05-27")) == 0
    # Fri bar -> Mon audit = 1 business day (weekend skipped).
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-22"), pd.Timestamp("2026-05-25")) == 1
    print("PASS test_stale_trading_days_counting")


def test_price_audit_flag(monkeypatched_dates: dict[str, str] | None = None) -> None:
    dates = {"SPY": "2026-05-22", "QQQ": "2026-05-22", "AAA": "2026-05-27"}

    def fake_loader(price_cache, ticker):
        iso = dates.get(str(ticker).upper())
        if not iso:
            return pd.DataFrame()
        idx = pd.DatetimeIndex([pd.Timestamp(iso)])
        return pd.DataFrame({"close": [100.0]}, index=idx)

    original = lpa.load_price_series
    lpa.load_price_series = fake_loader
    try:
        stale = lpa.run_audit(
            price_cache=Path("/nonexistent"),
            latest_run=Path("/nonexistent"),
            audit_date=pd.Timestamp("2026-05-27"),
            stale_threshold=2,
            max_book_tickers=0,
        )
        # Benchmark anchor is SPY/QQQ 05-22 (3 bdays stale) even though AAA is fresh.
        assert stale["status"] == "STALE_PRICE_REVIEW", stale["status"]
        assert stale["stale_trading_days"] == 3, stale["stale_trading_days"]
        assert stale["stale_price_review"] is True

        dates["SPY"] = "2026-05-27"
        fresh = lpa.run_audit(
            price_cache=Path("/nonexistent"),
            latest_run=Path("/nonexistent"),
            audit_date=pd.Timestamp("2026-05-27"),
            stale_threshold=2,
            max_book_tickers=0,
        )
        assert fresh["status"] == "ok", fresh["status"]
    finally:
        lpa.load_price_series = original
    print("PASS test_price_audit_flag")


def _equity(dates: list[str], values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.to_datetime(dates), "equity_usd": values})


def test_window_metrics_mdd() -> None:
    eq = _equity(
        ["2020-02-01", "2020-02-19", "2020-03-23", "2020-05-31", "2020-12-31"],
        [100.0, 110.0, 66.0, 99.0, 130.0],
    )
    win = ilc.window_metrics(eq, "2020-02-19", "2020-05-31")
    # Peak 110 -> trough 66 = -40% inside the window; window return 99/110-1 = -10%.
    assert abs(win["window_max_dd"] - (-0.40)) < 1e-9, win["window_max_dd"]
    assert abs(win["window_return"] - (99.0 / 110.0 - 1.0)) < 1e-9
    empty = ilc.window_metrics(eq, "2030-01-01", "2030-02-01")
    assert empty["observations"] == 0 and pd.isna(empty["window_max_dd"])
    print(f"PASS test_window_metrics_mdd mdd={win['window_max_dd']:.2%}")


def test_reentry_diagnostics() -> None:
    audit = pd.DataFrame(
        {
            "snapshot_date": [
                "2020-02-28", "2020-03-15", "2020-04-10", "2020-04-20", "2020-05-05",
            ],
            "crisis_zone": ["defense", "crisis", "normal", "normal", "normal"],
            "cash_weight": [0.30, 0.50, 0.30, 0.08, 0.05],
        }
    )
    diag = ilc.reentry_diagnostics(audit)
    assert diag["defense_episode_count"] == 1, diag
    assert abs(diag["max_cash_weight"] - 0.50) < 1e-9
    # Zone normalized 04-10 with cash still 30% (trap snapshot); cash back under
    # 10% on 04-20 -> lag = 10 days.
    assert diag["avg_reentry_lag_days"] == 10.0, diag
    assert diag["cash_trap_snapshot_count"] >= 1, diag
    assert diag["defense_snapshot_count"] == 2
    empty = ilc.reentry_diagnostics(pd.DataFrame())
    assert empty["defense_episode_count"] == 0
    print(f"PASS test_reentry_diagnostics lag={diag['avg_reentry_lag_days']}d")


def test_integrated_verdict_gates() -> None:
    base = {"cagr": 0.2055, "max_dd": -0.3182}
    good = {"cagr": 0.2030, "max_dd": -0.24}  # -0.25pp CAGR, +7.8pp MDD
    bad_mdd = {"cagr": 0.21, "max_dd": -0.30}  # only +1.8pp MDD
    bad_cagr = {"cagr": 0.19, "max_dd": -0.22}  # -1.55pp CAGR > 0.5pp loss
    v_good = ilc.integrated_verdict(base, good, "main")
    v_bad_mdd = ilc.integrated_verdict(base, bad_mdd, "main")
    v_bad_cagr = ilc.integrated_verdict(base, bad_cagr, "main")
    assert v_good["gates_pass"] is True, v_good
    assert v_bad_mdd["gates_pass"] is False
    assert v_bad_cagr["gates_pass"] is False
    assert v_good["promotion_allowed"] is False  # promotion forbidden always
    # Concentrated tolerates 3pp CAGR loss but demands +8pp MDD.
    conc = ilc.integrated_verdict(
        {"cagr": 0.3274, "max_dd": -0.3958}, {"cagr": 0.3000, "max_dd": -0.30}, "concentrated"
    )
    assert conc["gates_pass"] is True, conc
    print("PASS test_integrated_verdict_gates")


def main() -> int:
    tests = [
        test_champion_filter_disable_keeps_book,
        test_stale_trading_days_counting,
        test_price_audit_flag,
        test_window_metrics_mdd,
        test_reentry_diagnostics,
        test_integrated_verdict_gates,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            print(f"FAIL {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {test.__name__}: {exc!r}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
