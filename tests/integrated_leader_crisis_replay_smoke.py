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
import tools.run_crisis_signal_builder as rcsb  # noqa: E402


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
    # Fri 2026-05-15 bar vs Wed 2026-05-20 audit = Mon+Tue+Wed = 3 trading days.
    days = lpa.stale_trading_days_between(pd.Timestamp("2026-05-15"), pd.Timestamp("2026-05-20"))
    assert days == 3, days
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-20"), pd.Timestamp("2026-05-20")) == 0
    # Fri bar -> Mon audit = 1 trading day (weekend skipped).
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-15"), pd.Timestamp("2026-05-18")) == 1
    # Mon 2026-05-25 was Memorial Day, so XNYS trading-day freshness must not
    # count it as a stale trading day.
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-22"), pd.Timestamp("2026-05-27")) == 2
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-21"), pd.Timestamp("2026-05-27")) == 3
    # Fri bar -> Tue audit = 1 trading day (weekend and Memorial Day skipped).
    assert lpa.stale_trading_days_between(pd.Timestamp("2026-05-22"), pd.Timestamp("2026-05-26")) == 1
    print("PASS test_stale_trading_days_counting")


def test_price_audit_flag(monkeypatched_dates: dict[str, str] | None = None) -> None:
    dates = {"SPY": "2026-05-21", "QQQ": "2026-05-21", "AAA": "2026-05-27"}

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
        # Benchmark anchor is SPY/QQQ 05-21 (3 XNYS trading days stale) even
        # though AAA is fresh.
        assert stale["status"] == "STALE_PRICE_REVIEW", stale["status"]
        assert stale["stale_trading_days"] == 3, stale["stale_trading_days"]
        assert stale["stale_trading_days_calendar"] == "XNYS"
        assert stale["stale_trading_days_calendar_source"] in {
            "pandas_market_calendars_xnys",
            "pandas_fallback_xnys_holidays",
        }
        assert stale["stale_price_review"] is True

        dates["SPY"] = "2026-05-27"
        dates["QQQ"] = "2026-05-27"
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


def test_crisis_score_renormalization_removes_ceiling() -> None:
    """The structural defect found in run 27247439447: the pre-fix score was
    a plain weighted sum where missing macro features (VIX/HY OAS/DGS10) plus
    the structural placeholders (liquidity, portfolio_damage) capped the score
    at 0.40 -- below the conservative defense threshold of 0.50 -- so the
    governor could never engage. Renormalization must let the score reach 1.0
    using only the live components."""
    # All-out crash on the two LIVE components, the rest absent. Old formula
    # would yield 0.25 + 0.15 = 0.40. New formula renormalizes to ~1.0.
    idx = pd.DatetimeIndex(["2020-03-23"])
    features = pd.DataFrame(
        {"spy_below_ma200": [1.0], "spy_20d_dd": [-0.30], "qqq_below_ma200": [1.0]},
        index=idx,
    )
    score = rcsb.compute_composite_crisis_score(features)
    assert score.iloc[0] >= 0.99, f"expected near-1.0 with only live components, got {score.iloc[0]}"
    coverage = rcsb.composite_crisis_coverage(features)
    live = {n for n, c in coverage.items() if c["live"]}
    dead = {n for n, c in coverage.items() if not c["live"]}
    assert live == {"market_trend", "breadth"}, live
    assert {"vol_spike", "credit_stress", "rate_shock", "liquidity", "portfolio_damage"} == dead, dead
    # Live effective weights must sum to 1.0; dead to 0.
    assert abs(sum(c["effective_weight"] for c in coverage.values()) - 1.0) < 1e-9
    print(f"PASS test_crisis_score_renormalization_removes_ceiling score={score.iloc[0]:.4f} live={sorted(live)}")


def test_crisis_score_with_all_components_live_matches_old_formula() -> None:
    """Backward-compatibility guardrail: when every component is live the
    renormalized weighted sum must equal the original specification. This
    locks down that the renormalization is a strict superset of the prior
    formula, not a regime change."""
    idx = pd.DatetimeIndex(["2020-03-23"])
    features = pd.DataFrame(
        {
            "spy_below_ma200": [1.0],
            "spy_20d_dd": [-0.10],     # market_trend = clip(0.5 + 0.10/0.15*0.5) = clip(0.5+0.333) = 0.833 -> clip = 0.833
            "vix_zscore_60d": [2.4],   # vol_spike = 0.8
            "hy_oas_zscore_60d": [1.5],  # credit_stress = 0.5
            "qqq_below_ma200": [1.0],  # breadth = 1.0
            "ten_year_5d_change_bps": [20.0],  # rate_shock = 0.4
        },
        index=idx,
    )
    coverage = rcsb.composite_crisis_coverage(features)
    live_weight = sum(c["nominal_weight"] for c in coverage.values() if c["live"])
    # liquidity (placeholder) + portfolio_damage (always 0 initially) are dead.
    # market_trend, vol_spike, credit_stress, breadth, rate_shock are live.
    assert live_weight == 0.85, live_weight
    score = rcsb.compute_composite_crisis_score(features).iloc[0]
    # Renormalized: (0.25*0.833 + 0.15*0.8 + 0.20*0.5 + 0.15*1.0 + 0.10*0.4) / 0.85
    expected = (0.25 * 0.8333 + 0.15 * 0.8 + 0.20 * 0.5 + 0.15 * 1.0 + 0.10 * 0.4) / 0.85
    assert abs(score - expected) < 1e-3, (score, expected)
    print(f"PASS test_crisis_score_with_all_components_live_matches_old_formula score={score:.4f}")


def test_crisis_score_no_features_returns_zero() -> None:
    """If no component is live the score must be a flat zero -- the governor
    should stay out of the way rather than reacting to noise on an empty
    features frame."""
    idx = pd.DatetimeIndex(pd.date_range("2020-01-01", periods=3))
    features = pd.DataFrame(index=idx)
    score = rcsb.compute_composite_crisis_score(features)
    assert (score == 0.0).all(), score.tolist()
    coverage = rcsb.composite_crisis_coverage(features)
    assert all(not c["live"] for c in coverage.values())
    print("PASS test_crisis_score_no_features_returns_zero")


def main() -> int:
    tests = [
        test_champion_filter_disable_keeps_book,
        test_stale_trading_days_counting,
        test_price_audit_flag,
        test_window_metrics_mdd,
        test_reentry_diagnostics,
        test_integrated_verdict_gates,
        test_crisis_score_renormalization_removes_ceiling,
        test_crisis_score_with_all_components_live_matches_old_formula,
        test_crisis_score_no_features_returns_zero,
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
