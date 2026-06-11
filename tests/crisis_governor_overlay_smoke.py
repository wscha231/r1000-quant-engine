"""Smoke test for tools/run_crisis_governor_overlay.py.

Pure-Python, no Phase E features file required. Covers the paths that don't
need a live crisis_features parquet: mode=off passthrough, missing-features
passthrough, and missing-input block. The 'completed' governed path is
exercised by build_crisis_governed_target_books' own tests + the broker replay,
not duplicated here.

Run: python3 tests/crisis_governor_overlay_smoke.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cgo", str(REPO / "tools" / "run_crisis_governor_overlay.py"))
cgo = importlib.util.module_from_spec(spec); spec.loader.exec_module(cgo)


def _book(path: Path) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rebalance_date", "ticker", "weight"])
        w.writerow(["2024-01-31", "AAA", "0.6"])
        w.writerow(["2024-01-31", "CASH", "0.4"])


def test_mode_off_is_byte_identical_passthrough() -> None:
    d = Path(tempfile.mkdtemp())
    inp, out, diag = d / "b.csv", d / "o.csv", d / "d.json"
    _book(inp)
    r = cgo.run(input_book=inp, output_book=out, diagnostics_path=diag,
                crisis_features=Path("/nonexistent.parquet"), portfolio_kind="concentrated",
                mode="off", allow_normal_cash_deploy=False, cash_hard_gate=False, thresholds_json=None)
    assert r["status"] == "passthrough" and r["passthrough_reason"] == "mode=off", r
    assert out.read_text() == inp.read_text(), "mode=off must copy byte-for-byte"
    print("PASS test_mode_off_is_byte_identical_passthrough")


def test_missing_features_passthrough() -> None:
    d = Path(tempfile.mkdtemp())
    inp, out, diag = d / "b.csv", d / "o.csv", d / "d.json"
    _book(inp)
    r = cgo.run(input_book=inp, output_book=out, diagnostics_path=diag,
                crisis_features=Path("/nonexistent.parquet"), portfolio_kind="concentrated",
                mode="conservative", allow_normal_cash_deploy=False, cash_hard_gate=False, thresholds_json=None)
    assert r["status"] == "passthrough" and "missing" in r["passthrough_reason"], r
    assert out.read_text() == inp.read_text()
    print("PASS test_missing_features_passthrough")


def test_missing_input_blocks() -> None:
    d = Path(tempfile.mkdtemp())
    out, diag = d / "o.csv", d / "d.json"
    r = cgo.run(input_book=d / "nope.csv", output_book=out, diagnostics_path=diag,
                crisis_features=Path("/nonexistent.parquet"), portfolio_kind="concentrated",
                mode="conservative", allow_normal_cash_deploy=False, cash_hard_gate=False, thresholds_json=None)
    assert r["status"] == "blocked", r
    assert json.loads(diag.read_text())["status"] == "blocked"
    print("PASS test_missing_input_blocks")


def main() -> int:
    tests = [test_mode_off_is_byte_identical_passthrough, test_missing_features_passthrough, test_missing_input_blocks]
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
