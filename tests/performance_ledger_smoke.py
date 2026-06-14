#!/usr/bin/env python3
"""Smoke for tools/run_performance_ledger.py — the cumulative evaluation memory.

Locks the self-sustaining loop's core semantics:
  - append-only accumulation with run_id dedup
  - IS-CAGR (not full CAGR) is the trended KPI
  - IMPROVING / FLAT / REGRESSING classification with the 0.5pp flat band
  - best-IS-CAGR tracking + new_best flag
  - dominant_open_leak surfaces the recommended next focus
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.run_performance_ledger import (  # noqa: E402
    build_run_row,
    compute_verdict,
    _read_ledger,
    run,
)
import argparse  # noqa: E402


def _account_eval(main_full=0.34, conc_full=0.44, main_is=0.21, conc_is=0.21):
    return {
        "official_metric_mode": "broker_ledger_next_close",
        "production_target_pass": False,
        "strengthened_pass": False,
        "portfolios": {
            "main": {"cagr": main_full, "is_cagr": main_is, "oos_cagr": 0.75, "max_dd": -0.26, "sharpe": 1.27, "avg_cash_weight": 0.27, "target_pass": False, "strengthened_pass": False, "tier2_failing": ["is_cagr_min"]},
            "concentrated": {"cagr": conc_full, "is_cagr": conc_is, "oos_cagr": 1.29, "max_dd": -0.26, "sharpe": 1.40, "avg_cash_weight": 0.42, "target_pass": False, "strengthened_pass": False, "tier2_failing": ["is_cagr_min", "oos_is_cagr_ratio_max"]},
        },
    }


def _is_attribution(conc_under=(2021, 2023)):
    return {
        "main": {"is_cagr": 0.21, "oos_cagr": 0.75, "structural_underinvestment_bull_years": [], "leak_year_tags": {"2021": "mixed", "2022": "over_defense_bear_ok"}},
        "concentrated": {"is_cagr": 0.21, "oos_cagr": 1.29, "structural_underinvestment_bull_years": list(conc_under), "leak_year_tags": {str(y): "structural_underinvestment_bull" for y in conc_under}},
    }


def test_build_run_row_prefers_is_cagr_and_captures_leaks() -> None:
    row = build_run_row(_account_eval(), _is_attribution(), run_id="r1", commit="abc", universe="g")
    assert row["portfolios"]["concentrated"]["is_cagr"] == 0.21
    assert row["portfolios"]["concentrated"]["underinvestment_bull_years"] == [2021, 2023]
    assert row["run_id"] == "r1"


def test_first_run_is_flagged_and_new_best() -> None:
    row = build_run_row(_account_eval(), _is_attribution(), run_id="r1", commit="abc", universe="g")
    v = compute_verdict(row, [row])
    assert v["overall"] == "FIRST_RUN"
    assert v["per_portfolio"]["main"]["state"] == "FIRST_RUN"
    assert v["per_portfolio"]["main"]["new_best"] is True


def test_regressing_on_is_cagr_drop() -> None:
    r1 = build_run_row(_account_eval(main_is=0.22, conc_is=0.22), _is_attribution(), run_id="r1", commit="a", universe="g")
    r2 = build_run_row(_account_eval(main_is=0.21, conc_is=0.215), _is_attribution(), run_id="r2", commit="b", universe="g")
    v = compute_verdict(r2, [r1, r2])
    # main dropped 1pp -> REGRESSING; conc dropped 0.5pp -> at the band edge -> FLAT
    assert v["per_portfolio"]["main"]["state"] == "REGRESSING"
    assert v["overall"] == "REGRESSING"
    assert v["per_portfolio"]["main"]["delta_vs_prev_pp"] == -1.0


def test_improving_and_new_best() -> None:
    r1 = build_run_row(_account_eval(main_is=0.21, conc_is=0.21), _is_attribution(), run_id="r1", commit="a", universe="g")
    r2 = build_run_row(_account_eval(main_is=0.30, conc_is=0.35), _is_attribution(), run_id="r2", commit="b", universe="g")
    v = compute_verdict(r2, [r1, r2])
    assert v["per_portfolio"]["main"]["state"] == "IMPROVING"
    assert v["per_portfolio"]["concentrated"]["state"] == "IMPROVING"
    assert v["overall"] == "IMPROVING"
    assert v["per_portfolio"]["main"]["new_best"] is True
    assert v["per_portfolio"]["main"]["delta_vs_best_pp"] == 9.0


def test_flat_within_band() -> None:
    r1 = build_run_row(_account_eval(main_is=0.250), _is_attribution(), run_id="r1", commit="a", universe="g")
    r2 = build_run_row(_account_eval(main_is=0.252), _is_attribution(), run_id="r2", commit="b", universe="g")
    v = compute_verdict(r2, [r1, r2])
    assert v["per_portfolio"]["main"]["state"] == "FLAT"


def test_dominant_open_leak_surfaces_conc_underinvestment() -> None:
    row = build_run_row(_account_eval(), _is_attribution(conc_under=(2021, 2023)), run_id="r1", commit="a", universe="g")
    v = compute_verdict(row, [row])
    assert v["dominant_open_leak"] == "concentrated:structural_underinvestment_bull"


def test_end_to_end_appends_and_dedups() -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        latest = td / "outputs"
        (latest / "account_evaluation").mkdir(parents=True)
        (latest / "is_attribution").mkdir(parents=True)
        (latest / "account_evaluation" / "official_metrics.json").write_text(json.dumps(_account_eval()))
        (latest / "is_attribution" / "summary.json").write_text(json.dumps(_is_attribution()))
        ledger_dir = td / "ledger"

        def _args(run_id):
            return argparse.Namespace(latest_run=str(latest), ledger_dir=str(ledger_dir), account_eval="", is_attribution="", run_id=run_id, commit="c1", universe="g")

        run(_args("runA"))
        run(_args("runB"))
        run(_args("runB"))  # re-run same id -> dedup, not a third row
        rows = _read_ledger(ledger_dir / "ledger.jsonl")
        assert len(rows) == 2, f"expected dedup to 2 rows, got {len(rows)}"
        assert {r["run_id"] for r in rows} == {"runA", "runB"}
        assert (ledger_dir / "ledger_summary.md").exists()
        assert (ledger_dir / "latest_verdict.json").exists()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(tests)}/{len(tests)} passed")
