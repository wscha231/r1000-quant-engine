"""Smoke test for tools/build_top_manager_discovery_signals.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("btmds", str(REPO / "tools" / "build_top_manager_discovery_signals.py"))
btmds = importlib.util.module_from_spec(spec); spec.loader.exec_module(btmds)


def _events() -> pd.DataFrame:
    # AAA: 2 top3 managers + 1 top7 manager bought before the rebalance date.
    # BBB: 1 top10 manager only.
    # CCC: a buy that is AFTER the rebalance date -> must be excluded (PIT).
    return pd.DataFrame({
        "ticker": ["AAA", "AAA", "AAA", "BBB", "CCC", "DDD"],
        "manager_cik": ["1", "2", "3", "9", "5", "6"],
        "cohort_rank_bucket": ["top3", "top3", "top7", "top10", "top3", "top3"],
        "available_from_ts": pd.to_datetime([
            "2023-01-10", "2023-02-15", "2023-03-01",  # AAA before 2023-06-01
            "2023-04-01",                                # BBB before
            "2023-09-01",                                # CCC AFTER -> excluded
            "2023-06-01T22:00:00Z",                      # DDD after NYSE close -> excluded
        ], utc=True, format="mixed"),
    })


def test_pit_window_and_counts() -> None:
    events = btmds.load_follow_events_frame(_events()) if hasattr(btmds, "load_follow_events_frame") else _normalize(_events())
    dates = [pd.Timestamp("2023-06-01")]
    out = btmds.aggregate_per_date(events, dates, lookback_days=365)
    by_ticker = {r["ticker"]: r for r in out.to_dict("records")}
    assert "AAA" in by_ticker, by_ticker
    aaa = by_ticker["AAA"]
    # 2 distinct top3 managers, 3 distinct top7-or-better (top3 ∪ top7), 3 top10-or-better
    assert aaa["top3_manager_count"] == 2, aaa
    assert aaa["top7_manager_count"] == 3, aaa
    assert aaa["top10_manager_count"] == 3, aaa
    assert 0.0 < aaa["top7_discovery_score"] <= 1.0, aaa
    # CCC's only buy is after the rebalance date -> no PIT leak
    assert "CCC" not in by_ticker, "future-dated buy leaked into PIT window"
    assert "DDD" not in by_ticker, "after-close buy leaked into same-session PIT window"
    print(f"PASS test_pit_window_and_counts  AAA top3={aaa['top3_manager_count']} top7={aaa['top7_manager_count']} score={aaa['top7_discovery_score']:.3f}")


def test_lookback_excludes_old_events() -> None:
    events = _normalize(_events())
    dates = [pd.Timestamp("2023-06-01")]
    # 70-day lookback from 2023-06-01 floors at ~2023-03-23. All AAA events
    # (latest 2023-03-01) fall outside -> AAA excluded. Only BBB's 2023-04-01 qualifies.
    out = btmds.aggregate_per_date(events, dates, lookback_days=70)
    by_ticker = {r["ticker"]: r for r in out.to_dict("records")}
    assert "AAA" not in by_ticker, f"AAA events all >70d old but leaked: {by_ticker.get('AAA')}"
    bbb = by_ticker.get("BBB", {})
    assert bbb.get("top10_manager_count") == 1, bbb
    assert bbb.get("top7_manager_count") == 0, bbb  # BBB manager is top10 bucket, not top7-or-better
    print(f"PASS test_lookback_excludes_old_events  AAA excluded, BBB top10={bbb.get('top10_manager_count')}")


def test_empty_inputs() -> None:
    out = btmds.aggregate_per_date(pd.DataFrame(), [pd.Timestamp("2023-06-01")], lookback_days=252)
    assert out.empty and "top7_discovery_score" in out.columns, out.columns.tolist()
    print("PASS test_empty_inputs")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["available_from_ts"] = pd.to_datetime(df["available_from_ts"], errors="coerce", utc=True).dt.tz_convert(None)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["manager_cik"] = df["manager_cik"].astype(str).str.strip()
    df["cohort_rank_bucket"] = df["cohort_rank_bucket"].astype(str)
    return df


def main() -> int:
    tests = [test_pit_window_and_counts, test_lookback_excludes_old_events, test_empty_inputs]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:
            print(f"ERROR {t.__name__}: {exc!r}"); failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
