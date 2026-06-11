"""Smoke test for tools/build_data_catalog.py. Builds synthetic datasets in a
temp dir and verifies the inspector classifies missing / empty / stale / ok."""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bdc", str(REPO / "tools" / "build_data_catalog.py"))
bdc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bdc)


def test_missing_dataset() -> None:
    e = bdc.inspect_dataset({"name": "x", "path": "outputs/__nope__.csv", "kind": "csv",
                             "layer": "l", "owner_workflow": "w.yml", "cadence_days": 5})
    assert e["status"] == "missing" and e["exists"] is False, e
    assert "MISSING" in e["action"]
    print("PASS test_missing_dataset")


def test_empty_dataset(tmp: Path) -> None:
    p = tmp / "empty.csv"
    pd.DataFrame(columns=["ticker", "available_from"]).to_csv(p, index=False)
    e = bdc.inspect_dataset({"name": "e", "path": str(p), "kind": "csv", "ticker_col": "ticker",
                             "date_col": "available_from", "layer": "etf", "owner_workflow": "etf.yml", "cadence_days": 40})
    assert e["status"] == "empty", e
    assert e["row_count"] == 0 and "EMPTY" in e["action"]
    print("PASS test_empty_dataset")


def test_ok_dataset_with_dates(tmp: Path) -> None:
    p = tmp / "good.csv"
    pd.DataFrame({"ticker": ["AAA", "BBB", "AAA"], "available_from": ["2020-01-01", "2021-06-01", "2022-03-01"]}).to_csv(p, index=False)
    e = bdc.inspect_dataset({"name": "g", "path": str(p), "kind": "csv", "ticker_col": "ticker",
                             "date_col": "available_from", "layer": "13f", "owner_workflow": "x.yml", "cadence_days": 3650})
    assert e["status"] == "ok", e
    assert e["row_count"] == 3 and e["ticker_count"] == 2, e
    assert e["available_from_min"].startswith("2020-01-01") and e["available_from_max"].startswith("2022-03-01"), e
    assert e["freshness"] == "fresh", e  # cadence 3650d, just written
    print(f"PASS test_ok_dataset_with_dates  tickers={e['ticker_count']} range={e['available_from_min'][:10]}..{e['available_from_max'][:10]}")


def test_stale_dataset(tmp: Path) -> None:
    p = tmp / "stale.csv"
    pd.DataFrame({"ticker": ["AAA"], "available_from": ["2020-01-01"]}).to_csv(p, index=False)
    old = time.time() - 60 * 86400  # 60 days old
    os.utime(p, (old, old))
    e = bdc.inspect_dataset({"name": "s", "path": str(p), "kind": "csv", "ticker_col": "ticker",
                             "date_col": "available_from", "layer": "etf", "owner_workflow": "etf.yml", "cadence_days": 40})
    assert e["status"] == "ok" and e["freshness"] == "STALE", e
    assert e["age_days"] is not None and e["age_days"] > 40
    print(f"PASS test_stale_dataset  age={e['age_days']:.0f}d > cadence 40d -> STALE")


def test_build_catalog_runs() -> None:
    # Against the real (mostly-absent locally) registry — must not crash and
    # must classify everything as missing/ok without raising.
    cat = bdc.build_catalog()
    assert cat["n_datasets"] == len(bdc.DATASETS)
    assert cat["health"] in ("ok", "DEGRADED")
    assert isinstance(cat["layers"], dict) and "etf" in cat["layers"]
    print(f"PASS test_build_catalog_runs  health={cat['health']} datasets={cat['n_datasets']}")


def main() -> int:
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    tests = [
        (test_missing_dataset, ()),
        (test_empty_dataset, (tmp,)),
        (test_ok_dataset_with_dates, (tmp,)),
        (test_stale_dataset, (tmp,)),
        (test_build_catalog_runs, ()),
    ]
    failed = 0
    for t, args in tests:
        try:
            t(*args)
        except AssertionError as exc:
            print(f"FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:
            print(f"ERROR {t.__name__}: {exc!r}"); failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
