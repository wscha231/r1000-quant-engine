#!/usr/bin/env python3
"""Smoke tests for proxy 10Y robustness gate."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_proxy_10y_robustness import classify_proxy_10y_robustness, write_outputs  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seed_proxy_run(
    root: Path,
    *,
    acceptance_pass: bool = True,
    label: str = "proxy_10y",
    official_r1000: bool = False,
    metric_mode: str = "broker_ledger_next_close",
    main_cagr: float = 0.36,
    conc_cagr: float = 0.51,
    max_dd: float = -0.22,
    is_cagr: float = 0.24,
    ratio: float = 2.4,
    cash_trap_rows: int = 0,
) -> None:
    write_json(
        root / "ten_year_backtest_readiness" / "summary.json",
        {
            "schema_version": "backtest-window-readiness-v2",
            "status": "proxy_10y_price_ready",
            "evidence_label": label,
            "official_russell_1000": official_r1000,
            "proxy_10y_acceptance": {"pass": acceptance_pass},
            "future_available_from": {"future_available_from_rows": 0},
            "benchmark_coverage": {"pass": True},
        },
    )
    portfolios = {}
    for name, cagr in (("main", main_cagr), ("concentrated", conc_cagr)):
        row = {
            "status": "completed",
            "official_metric_mode": metric_mode,
            "years": 10.02,
            "cagr": cagr,
            "max_dd": max_dd,
            "is_cagr": is_cagr,
            "oos_is_cagr_ratio": ratio,
        }
        portfolios[name] = row
        write_json(root / "broker_replay" / name / "metrics.json", row)
    write_json(
        root / "account_evaluation" / "official_metrics.json",
        {
            "official_metric_mode": metric_mode,
            "portfolios": portfolios,
        },
    )
    write_json(
        root / "proxy_10y_universe_substrate" / "summary.json",
        {
            "schema_version": "proxy-10y-universe-substrate-v1",
            "status": "proxy_10y_universe_ready",
            "pit_label": "pit_proxy_universe",
            "evidence_label": "proxy_10y",
            "official_russell_1000": False,
            "review_only": True,
            "canonical_production_sync": False,
            "promotion_allowed": False,
            "production_promotion_allowed": False,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
            "human_approval_required": True,
            "ready_for_proxy_10y_rebuild_review": True,
            "candidate_row_count": 500,
            "min_membership_count": 400,
            "month_count": 119,
            "failed_month_count": 0,
            "benchmark_coverage": {"pass": True, "missing": []},
            "blockers": [],
        },
    )
    write_json(
        root / "cash_reentry_quality" / "summary.json",
        {
            "status": "completed",
            "cash_trap_flag": cash_trap_rows > 0,
            "cash_trap_rows": cash_trap_rows,
        },
    )


def test_proxy_10y_robustness_passes_without_official_promotion() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root)
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is True, payload
        assert payload["status"] == "proxy_10y_robustness_pass", payload
        assert payload["evidence_label"] == "proxy_10y", payload
        assert payload["official_russell_1000"] is False, payload
        assert payload["promotion_allowed"] is False, payload
        assert payload["production_promotion_allowed"] is False, payload
        assert "official_promotion" in payload["blocked_uses"], payload


def test_proxy_10y_robustness_blocks_official_label_confusion() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root, label="official_pit_r1000", official_r1000=True)
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is False, payload
        assert "readiness_label_is_proxy_10y" in payload["blockers"], payload
        assert "official_russell_1000_false" in payload["blockers"], payload


def test_proxy_10y_robustness_requires_proxy_universe_substrate() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root)
        write_json(root / "proxy_10y_universe_substrate" / "summary.json", {"status": "not_ready"})
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is False, payload
        assert "proxy_10y_universe_substrate_pass" in payload["blockers"], payload


def test_proxy_10y_robustness_requires_universe_safety_metadata() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root)
        substrate = json.loads((root / "proxy_10y_universe_substrate" / "summary.json").read_text(encoding="utf-8"))
        substrate["canonical_production_sync"] = True
        substrate["promotion_allowed"] = True
        substrate["production_promotion_allowed"] = True
        substrate["live_trading_enabled"] = True
        substrate["human_approval_required"] = False
        write_json(root / "proxy_10y_universe_substrate" / "summary.json", substrate)
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is False, payload
        assert "proxy_10y_universe_canonical_sync_disabled" in payload["blockers"], payload
        assert "proxy_10y_universe_promotion_disabled" in payload["blockers"], payload
        assert "proxy_10y_universe_production_promotion_disabled" in payload["blockers"], payload
        assert "proxy_10y_universe_live_trading_disabled" in payload["blockers"], payload
        assert "proxy_10y_universe_human_approval_required" in payload["blockers"], payload


def test_proxy_10y_robustness_rejects_minimal_universe_substrate() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root)
        write_json(
            root / "proxy_10y_universe_substrate" / "summary.json",
            {
                "status": "proxy_10y_universe_ready",
                "pit_label": "pit_proxy_universe",
                "official_russell_1000": False,
            },
        )
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is False, payload
        assert "proxy_10y_universe_schema" in payload["blockers"], payload
        assert "proxy_10y_universe_ready_flag" in payload["blockers"], payload
        assert "proxy_10y_universe_month_count_pass" in payload["blockers"], payload


def test_proxy_10y_robustness_requires_readiness_schema() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root)
        readiness = json.loads((root / "ten_year_backtest_readiness" / "summary.json").read_text(encoding="utf-8"))
        readiness.pop("schema_version")
        write_json(root / "ten_year_backtest_readiness" / "summary.json", readiness)
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is False, payload
        assert "ten_year_readiness_schema" in payload["blockers"], payload


def test_proxy_10y_robustness_blocks_weak_metrics_and_cash_trap() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root, main_cagr=0.20, conc_cagr=0.30, max_dd=-0.31, ratio=5.0, cash_trap_rows=7)
        payload = classify_proxy_10y_robustness(root)
        assert payload["proxy_10y_robustness_pass"] is False, payload
        assert "main.cagr_pass=false" in payload["blockers"], payload
        assert "concentrated.cagr_pass=false" in payload["blockers"], payload
        assert "cash_trap_false" in payload["blockers"], payload
        assert "cash_trap_rows=7" in payload["blockers"], payload


def test_proxy_10y_robustness_writes_evidence_policy_copy() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_proxy_run(root)
        payload = classify_proxy_10y_robustness(root)
        out = root / "out"
        write_outputs(payload, out)
        assert (out / "summary.json").exists()
        assert "Proxy 10Y Robustness" in (out / "report.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    test_proxy_10y_robustness_passes_without_official_promotion()
    test_proxy_10y_robustness_blocks_official_label_confusion()
    test_proxy_10y_robustness_requires_proxy_universe_substrate()
    test_proxy_10y_robustness_requires_universe_safety_metadata()
    test_proxy_10y_robustness_rejects_minimal_universe_substrate()
    test_proxy_10y_robustness_requires_readiness_schema()
    test_proxy_10y_robustness_blocks_weak_metrics_and_cash_trap()
    test_proxy_10y_robustness_writes_evidence_policy_copy()
    print("proxy_10y_robustness_smoke: PASS")
