from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from strategy_difference_reporter import (  # noqa: E402
    NOT_AVAILABLE,
    ComparisonInputError,
    compare_replay_outputs,
    load_replay_bundle,
)


def _check(condition, message: str = "check failed") -> None:
    if not condition:
        raise AssertionError(message)


def _fail(message: str) -> None:
    raise AssertionError(message)


def _write_replay(root: Path, name: str, holdings, trades=None, equity=None, metrics=None) -> Path:
    d = root / name
    d.mkdir()
    pd.DataFrame(holdings).to_csv(d / "holdings_daily.csv", index=False)
    if trades is not None:
        pd.DataFrame(trades).to_csv(d / "trades.csv", index=False)
    if equity is not None:
        pd.DataFrame(equity).to_csv(d / "equity_curve.csv", index=False)
    if metrics is not None:
        (d / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return d


def _base_holdings():
    return [
        {"date": "2026-01-02", "ticker": "AAA", "shares": 10, "weight": 0.5},
        {"date": "2026-01-05", "ticker": "AAA", "shares": 10, "weight": 0.5},
        {"date": "2026-01-06", "ticker": "AAA", "shares": 10, "weight": 0.5},
    ]


def _equity():
    return [
        {"date": "2026-01-02", "equity_usd": 100.0, "cash_usd": 50.0, "cash_weight": 0.5},
        {"date": "2026-01-05", "equity_usd": 101.0, "cash_usd": 50.0, "cash_weight": 50/101},
        {"date": "2026-01-06", "equity_usd": 102.0, "cash_usd": 50.0, "cash_weight": 50/102},
    ]


def _metrics(trades=0, fees=0.0, turnover=None):
    out = {"status": "completed", "metric_mode": "broker_ledger_next_close", "trade_count": trades, "total_fees_usd": fees, "cagr": 0.2, "max_dd": -0.1}
    if turnover is not None:
        out["turnover"] = turnover
    return out


def test_identical_results_have_no_divergence():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", _base_holdings(), equity=_equity(), metrics=_metrics())
        report, events, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["status"] == "no_divergence")
        _check(report["first_divergence_session"] is None)
        _check(events.empty)


def test_first_holding_difference_exact_session():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cand = _base_holdings() + [{"date": "2026-01-05", "ticker": "BBB", "shares": 2, "weight": 0.1}, {"date": "2026-01-06", "ticker": "BBB", "shares": 2, "weight": 0.1}]
        cand = sorted(cand, key=lambda x: (x["date"], x["ticker"]))
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", cand, equity=_equity(), metrics=_metrics())
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["first_divergence_session"] == "2026-01-05")
        _check(report["first_divergence_asset"] == "BBB")
        _check(report["first_divergence_reason"] == "entered_only_in_candidate")


def test_exit_timing_difference():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        control = _base_holdings()
        candidate = control[:2]
        c = _write_replay(root, "c", control, equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", candidate, trades=[{"date":"2026-01-06","ticker":"AAA","side":"SELL","reason":"target_exit","fee_usd":1.0}], equity=_equity(), metrics=_metrics(1,1.0))
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["first_divergence_session"] == "2026-01-06")
        _check(report["first_divergence_reason"] == "exited_only_in_candidate")


def test_replacement_difference():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        control = _base_holdings()
        candidate = [
            {"date":"2026-01-02","ticker":"AAA","shares":10,"weight":0.5},
            {"date":"2026-01-05","ticker":"BBB","shares":5,"weight":0.5},
            {"date":"2026-01-06","ticker":"BBB","shares":5,"weight":0.5},
        ]
        c = _write_replay(root, "c", control, equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", candidate, equity=_equity(), metrics=_metrics())
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(bool(report["replacement_events"]))
        _check(report["replacement_events"][0]["session"] == "2026-01-05")
        _check(report["replacement_events"][0]["entered_assets"] == ["BBB"])
        _check(report["replacement_events"][0]["exited_assets"] == ["AAA"])


def test_fee_cost_difference_uses_existing_output():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics(2, 3.0))
        k = _write_replay(root, "k", _base_holdings(), equity=_equity(), metrics=_metrics(3, 5.5))
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["trade_count_delta"] == 1.0)
        _check(report["fee_cost_delta_usd"] == 2.5)


def test_missing_optional_field_is_not_available():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", _base_holdings(), equity=_equity(), metrics=_metrics())
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["turnover_delta"] == NOT_AVAILABLE)
        _check(report["availability"]["turnover_delta"] == NOT_AVAILABLE)


def test_duplicate_session_asset_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = sorted(_base_holdings() + [{"date":"2026-01-05","ticker":"AAA","shares":1,"weight":0.1}], key=lambda x: (x["date"], x["ticker"]))
        path = _write_replay(root, "bad", bad, equity=_equity(), metrics=_metrics())
        try:
            load_replay_bundle(path, label="bad")
            _fail("expected rejection")
        except ComparisonInputError as exc:
            _check("duplicate_session_asset" in str(exc))


def test_time_order_inversion_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = [_base_holdings()[1], _base_holdings()[0], _base_holdings()[2]]
        path = _write_replay(root, "bad", bad, equity=_equity(), metrics=_metrics())
        try:
            load_replay_bundle(path, label="bad")
            _fail("expected rejection")
        except ComparisonInputError as exc:
            _check("time_order_inversion" in str(exc))


def test_input_files_not_mutated():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", _base_holdings(), equity=_equity(), metrics=_metrics())
        paths = sorted([*c.iterdir(), *k.iterdir()])
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        _check(before == after)


def test_turnover_only_when_explicitly_available():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics(turnover=0.2))
        k = _write_replay(root, "k", _base_holdings(), equity=_equity(), metrics=_metrics(turnover=0.35))
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(abs(report["turnover_delta"] - 0.15) < 1e-12)



def test_nav_only_difference_is_observed_at_session():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate_equity = _equity()
        candidate_equity[1] = dict(candidate_equity[1], equity_usd=100.5, cash_usd=49.5)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", _base_holdings(), equity=candidate_equity, metrics=_metrics())
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["status"] == "completed")
        _check(report["first_divergence_session"] == "2026-01-05")
        _check(report["first_divergence_reason"] in {"nav_delta", "cash_delta"})




def test_fee_is_not_recomputed_from_trade_rows_when_evaluator_total_is_missing():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        trades = [{"date":"2026-01-05","ticker":"AAA","side":"BUY","fee_usd":9.0}]
        control_metrics = {"status":"completed","metric_mode":"broker_ledger_next_close","trade_count":1,"cagr":0.2,"max_dd":-0.1}
        candidate_metrics = {"status":"completed","metric_mode":"broker_ledger_next_close","trade_count":1,"cagr":0.2,"max_dd":-0.1}
        c = _write_replay(root, "c", _base_holdings(), trades=trades, equity=_equity(), metrics=control_metrics)
        k = _write_replay(root, "k", _base_holdings(), trades=trades, equity=_equity(), metrics=candidate_metrics)
        report, _, _ = compare_replay_outputs(load_replay_bundle(c, label="c"), load_replay_bundle(k, label="k"))
        _check(report["fee_cost_delta_usd"] == NOT_AVAILABLE)


def test_explicit_row_level_module_evidence_can_mark_attributable_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        control = _write_replay(root, "c", _base_holdings(), trades=None, equity=_equity(), metrics=_metrics(0, 0.0))
        candidate_trades = [{
            "date":"2026-01-05", "ticker":"AAA", "side":"BUY", "quantity":1,
            "fill_price":10.0, "gross_value":10.0, "fee_usd":0.1,
            "reason":"target_rebalance", "changed_module":"hold_exit",
        }]
        candidate = _write_replay(root, "k", _base_holdings(), trades=candidate_trades, equity=_equity(), metrics=_metrics(1, 0.1))
        report, _, _ = compare_replay_outputs(
            load_replay_bundle(control, label="c"),
            load_replay_bundle(candidate, label="k"),
            changed_module="hold_exit",
        )
        _check(report["attribution"]["classification"] == "ATTRIBUTABLE_CANDIDATE")
        _check(report["attribution"]["attributable_candidate"] is True)


def test_g1_g2_provenance_fields_are_preserved_but_not_used_as_economics():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        c = _write_replay(root, "c", _base_holdings(), equity=_equity(), metrics=_metrics())
        k = _write_replay(root, "k", _base_holdings(), equity=_equity(), metrics=_metrics())
        provenance = {
            "strategy_id": "alphaops-control-plus-g2",
            "variant_id": "g2-min-gap-default",
            "parent_strategy_id": "alphaops-control-legacy",
            "changed_module": "hold_exit",
            "changed_module_version": "1",
            "evaluation_ref": "eval:broker-ledger-next-close",
            "control_replay_ref": "artifact:control",
            "candidate_replay_ref": "artifact:candidate",
            "module_id": "run287_hold_exit_replacement_policy",
            "module_version": "1",
            "policy_id": "leadership_persistence_v2_strict",
            "hold_exit_policy_config": '{"module_id":"opaque-preserved"}',
            "policy_audit_identity": "a" * 64,
        }
        report, events, _ = compare_replay_outputs(
            load_replay_bundle(c, label="c"),
            load_replay_bundle(k, label="k"),
            **provenance,
        )
        identity = report["comparison_identity"]
        for key, value in provenance.items():
            _check(identity[key] == value, key)
        _check(identity["identity_only_not_economic_input"] is True)
        _check(report["status"] == "no_divergence")
        _check(events.empty)

def test_backward_compat_output_namespace_does_not_collide_with_strategy_logic_ledger():
    existing = {
        "strategy_logic_ledger.csv",
        "logic_family_summary.csv",
        "strategy_outcome_matrix.csv",
        "best_logic_by_regime.csv",
        "summary.json",
        "report.md",
    }
    g3 = {
        "strategy_difference_report.json",
        "strategy_difference_events.csv",
        "strategy_difference_session_deltas.csv",
    }
    _check(existing.isdisjoint(g3))


def main():
    tests = [value for key, value in globals().items() if key.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"strategy_difference_reporter: PASS ({len(tests)} tests)")


if __name__ == "__main__":
    main()
