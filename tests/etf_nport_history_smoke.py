"""Smoke test for tools/build_etf_nport_history.py — parser + PIT + merge."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("benh", str(REPO / "tools" / "build_etf_nport_history.py"))
benh = importlib.util.module_from_spec(spec); spec.loader.exec_module(benh)


# Realistic namespaced N-PORT primary_doc.xml fragment with two holdings,
# one duplicated across two lots (must collapse), one with no ticker (must drop).
NPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <formData>
    <genInfo><repPdEnd>2023-03-31</repPdEnd></genInfo>
    <invstOrSecs>
      <invstOrSec>
        <name>NVIDIA CORP</name>
        <pctVal>12.50</pctVal>
        <identifiers><ticker value="NVDA"/></identifiers>
      </invstOrSec>
      <invstOrSec>
        <name>ADVANCED MICRO DEVICES</name>
        <pctVal>5.00</pctVal>
        <identifiers><ticker value="AMD"/></identifiers>
      </invstOrSec>
      <invstOrSec>
        <name>ADVANCED MICRO DEVICES</name>
        <pctVal>1.50</pctVal>
        <identifiers><ticker value="AMD"/></identifiers>
      </invstOrSec>
      <invstOrSec>
        <name>SOME CASH SWEEP</name>
        <pctVal>0.30</pctVal>
        <identifiers><ticker value="N/A"/></identifiers>
      </invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>"""

SPEC = {"etf_ticker": "SMH", "etf_label": "VanEck Semiconductor ETF", "theme": "semiconductors"}


def test_parse_pit_and_schema() -> None:
    out = benh.parse_nport_holdings(NPORT_XML, spec=SPEC, accepted_ts="2023-05-30T17:02:00.000-04:00")
    assert list(out.columns) == benh.OUTPUT_COLUMNS, out.columns.tolist()
    tickers = set(out["holding_ticker"])
    assert tickers == {"NVDA", "AMD"}, f"expected NVDA+AMD (N/A dropped), got {tickers}"
    # AMD's two lots collapse: 5.00% + 1.50% = 6.50% -> 0.065 fraction
    amd = out[out.holding_ticker.eq("AMD")].iloc[0]
    assert abs(amd["holding_weight"] - 0.065) < 1e-9, amd["holding_weight"]
    nvda = out[out.holding_ticker.eq("NVDA")].iloc[0]
    assert abs(nvda["holding_weight"] - 0.125) < 1e-9, nvda["holding_weight"]
    # PIT: available_from is the accepted timestamp, as_of_date is the period end
    assert out["available_from"].iloc[0].startswith("2023-05-30"), out["available_from"].iloc[0]
    assert (out["as_of_date"] == "2023-03-31").all(), out["as_of_date"].tolist()
    assert (out["source"] == "sec_nport").all()
    # sorted by weight desc -> NVDA first
    assert out.iloc[0]["holding_ticker"] == "NVDA"
    print(f"PASS test_parse_pit_and_schema  NVDA={nvda['holding_weight']} AMD={amd['holding_weight']} avail={out['available_from'].iloc[0][:10]}")


def test_parse_empty_and_malformed() -> None:
    assert benh.parse_nport_holdings("", spec=SPEC, accepted_ts="x").empty
    assert benh.parse_nport_holdings("<not><closed>", spec=SPEC, accepted_ts="x").empty
    # well-formed but no holdings
    empty = benh.parse_nport_holdings(
        '<edgarSubmission xmlns="http://www.sec.gov/edgar/nport"><formData></formData></edgarSubmission>',
        spec=SPEC, accepted_ts="x")
    assert empty.empty and list(empty.columns) == benh.OUTPUT_COLUMNS
    print("PASS test_parse_empty_and_malformed")


def _has_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception:
        try:
            import fastparquet  # noqa: F401
            return True
        except Exception:
            return False


def test_merge_pit_dedup() -> None:
    if not _has_parquet():
        print("SKIP test_merge_pit_dedup (no parquet engine in this env; covered in CI)")
        return
    tmp = Path(tempfile.mkdtemp())
    existing_path = tmp / "etf_holdings.parquet"
    # Existing single today-stamped snapshot row (the old broken behaviour).
    pd.DataFrame([{
        "etf_ticker": "SMH", "etf_label": "x", "theme": "semiconductors",
        "holding_ticker": "NVDA", "holding_name": "NVIDIA", "holding_weight": 0.13,
        "source": "yfinance", "as_of_date": "2026-06-01", "available_from": "2026-06-01",
    }]).to_parquet(existing_path, index=False)
    history = benh.parse_nport_holdings(NPORT_XML, spec=SPEC, accepted_ts="2023-05-30T17:02:00-04:00")
    merged = benh.merge_with_existing(history, existing_path)
    # The historical 2023 rows are added alongside the 2026 snapshot -> distinct
    # available_from values, so NVDA now has TWO PIT rows (2023 + 2026).
    nvda_rows = merged[merged.holding_ticker.eq("NVDA")]
    avail = set(pd.to_datetime(nvda_rows["available_from"], utc=True).dt.year)
    assert avail == {2023, 2026}, f"expected both PIT years, got {avail}"
    assert len(merged) == 3, f"NVDA(2023)+AMD(2023)+NVDA(2026)=3, got {len(merged)}"
    print(f"PASS test_merge_pit_dedup  rows={len(merged)} nvda_years={sorted(avail)}")


def main() -> int:
    tests = [test_parse_pit_and_schema, test_parse_empty_and_malformed, test_merge_pit_dedup]
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
