"""Smoke test for tools/data_coverage_gate.py. Pure-Python, no I/O deps."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("dcg", str(REPO / "tools" / "data_coverage_gate.py"))
dcg = importlib.util.module_from_spec(spec); spec.loader.exec_module(dcg)


def test_dead_etf_fails() -> None:
    # coverage_ratio 0.12 = Form4 v1 onset hit rate; floor for sec_v1_evidence is 0.20.
    sec = {"coverage_etf_ratio": 0.0, "coverage_ratio": 0.12, "coverage_13f_ratio": 0.78, "coverage_smart_money_ratio": 0.73, "coverage_top_manager_ratio": 0.10}
    r = dcg.evaluate(sec_enriched=sec, readiness={}, floors=dcg.DEFAULT_FLOORS, warn_only=set())
    assert r["verdict"] == "FAIL", r["verdict"]
    fails = {l["layer"] for l in r["layers"] if l["status"] == "FAIL"}
    # etf (0.0) below 0.30 and sec_v1_evidence (0.12) below 0.20 -> FAIL
    assert "etf" in fails and "sec_v1_evidence" in fails, fails
    # 13f (0.78) and smart_money (0.73) above 0.50 -> ok
    oks = {l["layer"] for l in r["layers"] if l["status"] == "ok"}
    assert "13f" in oks and "smart_money" in oks, oks
    print(f"PASS test_dead_etf_fails  fails={sorted(fails)}")


def test_warn_only_downgrades() -> None:
    sec = {"coverage_etf_ratio": 0.0, "coverage_ratio": 0.12, "coverage_13f_ratio": 0.78, "coverage_smart_money_ratio": 0.73, "coverage_top_manager_ratio": 0.10}
    r = dcg.evaluate(sec_enriched=sec, readiness={}, floors=dcg.DEFAULT_FLOORS, warn_only={"etf", "sec_v1_evidence"})
    # both dead layers downgraded to WARN -> overall WARN, not FAIL
    assert r["verdict"] == "WARN", r["verdict"]
    assert r["n_fail"] == 0 and r["n_warn"] == 2, r
    print("PASS test_warn_only_downgrades")


def test_all_healthy_passes() -> None:
    sec = {"coverage_etf_ratio": 0.55, "coverage_ratio": 0.60, "coverage_13f_ratio": 0.80, "coverage_smart_money_ratio": 0.75, "coverage_top_manager_ratio": 0.10}
    rdy = {"feature_source_coverage": {"books": {"concentrated": {"pit_available_from_check": {"rows_with_any_future_available_from": 0}}}}}
    r = dcg.evaluate(sec_enriched=sec, readiness=rdy, floors=dcg.DEFAULT_FLOORS, warn_only=set())
    assert r["verdict"] == "PASS", r["verdict"]
    print("PASS test_all_healthy_passes")


def test_future_available_from_hard_fails() -> None:
    sec = {"coverage_etf_ratio": 0.9, "coverage_ratio": 0.9, "coverage_13f_ratio": 0.9, "coverage_smart_money_ratio": 0.9, "coverage_top_manager_ratio": 0.9}
    rdy = {"feature_source_coverage": {"books": {"concentrated": {"pit_available_from_check": {"rows_with_any_future_available_from": 5}}}}}
    r = dcg.evaluate(sec_enriched=sec, readiness=rdy, floors=dcg.DEFAULT_FLOORS, warn_only=set())
    # even with all coverage high, a future-dated stamp (lookahead) hard-fails
    assert r["verdict"] == "FAIL", r["verdict"]
    assert any(l["layer"] == "pit_no_future_available_from" and l["status"] == "FAIL" for l in r["layers"])
    print("PASS test_future_available_from_hard_fails")


def test_missing_key_treated_as_below_floor() -> None:
    sec = {"coverage_13f_ratio": 0.8}  # etf, available_from, smart_money absent
    r = dcg.evaluate(sec_enriched=sec, readiness={}, floors=dcg.DEFAULT_FLOORS, warn_only=set())
    assert r["verdict"] == "FAIL"
    absent = {l["layer"] for l in r["layers"] if not l["present"] and l["status"] == "FAIL"}
    assert "etf" in absent and "sec_v1_evidence" in absent and "smart_money" in absent, absent
    print("PASS test_missing_key_treated_as_below_floor")


def main() -> int:
    tests = [test_dead_etf_fails, test_warn_only_downgrades, test_all_healthy_passes,
             test_future_available_from_hard_fails, test_missing_key_treated_as_below_floor]
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
