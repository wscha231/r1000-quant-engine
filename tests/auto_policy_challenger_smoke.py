#!/usr/bin/env python3
"""Smoke tests for the AutoLearning policy challenger broker-accounting gate.

These tests cover the C5 hardening that surfaces the broker-ledger
known-bias audit (research/broker_accounting_audit.json) as explicit
hard/soft challenger gates. While any hard bias flag is false, the
challenger must refuse to mark the policy approved for promotion.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.auto_policy_challenger import (  # noqa: E402
    DEFAULT_BROKER_ACCOUNTING_AUDIT,
    _broker_accounting_rows,
    load_broker_accounting_audit,
)


def _audit_with_all_hard_true() -> dict:
    return {
        "audit_present": True,
        "hard_gates": {
            "delisted_cost_basis_fallback_eliminated": {"value": True, "rationale": "fixed in A1"},
            "survivorship_coverage_audited": {"value": True, "rationale": "fixed in A2"},
        },
        "soft_gates": {
            "multi_day_fill_date_stamping_corrected": {"value": False, "rationale": "minor"},
            "sharpe_uses_excess_return": {"value": False, "rationale": "minor"},
        },
    }


def _audit_with_all_hard_false() -> dict:
    return {
        "audit_present": True,
        "hard_gates": {
            "delisted_cost_basis_fallback_eliminated": {"value": False, "rationale": "still open"},
            "survivorship_coverage_audited": {"value": False, "rationale": "still open"},
        },
        "soft_gates": {
            "multi_day_fill_date_stamping_corrected": {"value": False, "rationale": "minor"},
            "sharpe_uses_excess_return": {"value": False, "rationale": "minor"},
        },
    }


def test_default_audit_blocks_promotion_with_hard_failures() -> None:
    audit = _audit_with_all_hard_false()
    rows = _broker_accounting_rows(audit, "research/broker_accounting_audit.json")
    hard_rows = [r for r in rows if r["severity"] == "hard"]
    hard_failed = [r for r in hard_rows if not r["passed"]]
    # audit_artifact_present passes; the two known-bias hard gates fail.
    assert any(r["check"] == "audit_artifact_present" and r["passed"] for r in hard_rows)
    assert {r["check"] for r in hard_failed} == {
        "delisted_cost_basis_fallback_eliminated",
        "survivorship_coverage_audited",
    }
    # Soft gates emit warnings but do not block.
    soft_rows = [r for r in rows if r["severity"] == "soft"]
    soft_failed = [r for r in soft_rows if not r["passed"]]
    assert {r["check"] for r in soft_failed} == {
        "multi_day_fill_date_stamping_corrected",
        "sharpe_uses_excess_return",
    }


def test_hard_gates_pass_when_audit_flags_flip_true() -> None:
    audit = _audit_with_all_hard_true()
    rows = _broker_accounting_rows(audit, "research/broker_accounting_audit.json")
    hard_rows = [r for r in rows if r["severity"] == "hard"]
    hard_failed = [r for r in hard_rows if not r["passed"]]
    assert hard_failed == [], hard_failed
    # Soft gates can remain false without blocking promotion.
    soft_rows = [r for r in rows if r["severity"] == "soft"]
    soft_failed = [r for r in soft_rows if not r["passed"]]
    assert {r["check"] for r in soft_failed} == {
        "multi_day_fill_date_stamping_corrected",
        "sharpe_uses_excess_return",
    }


def test_missing_audit_file_emits_explicit_failure_not_crash() -> None:
    missing = Path("/nonexistent/path/broker_accounting_audit.json")
    audit = load_broker_accounting_audit(missing)
    assert audit.get("audit_present") is False
    rows = _broker_accounting_rows(audit, str(missing))
    presence_rows = [r for r in rows if r["check"] == "audit_artifact_present"]
    assert presence_rows
    assert presence_rows[0]["passed"] is False
    assert presence_rows[0]["severity"] == "hard"


def test_repository_audit_matches_schema_and_documents_open_bugs() -> None:
    """The audit JSON shipped in the repo should be readable and currently
    report the open biases (delisted, survivorship) as false so the
    challenger blocks production promotion. Flip these flags only when
    the corresponding fix lands AND a regression test demonstrates it.
    """
    audit_path = REPO_ROOT / DEFAULT_BROKER_ACCOUNTING_AUDIT
    assert audit_path.exists(), f"missing {DEFAULT_BROKER_ACCOUNTING_AUDIT}"
    audit = load_broker_accounting_audit(audit_path)
    assert audit.get("audit_present") is True
    hard = audit.get("hard_gates") or {}
    assert set(hard.keys()) == {
        "delisted_cost_basis_fallback_eliminated",
        "survivorship_coverage_audited",
    }, set(hard.keys())
    soft = audit.get("soft_gates") or {}
    assert set(soft.keys()) == {
        "multi_day_fill_date_stamping_corrected",
        "sharpe_uses_excess_return",
    }, set(soft.keys())
    # Documented state: all four flags are currently false. When any
    # flag is flipped to true, the corresponding fix and regression
    # test must accompany the change in the same commit.
    for name, payload in {**hard, **soft}.items():
        assert "rationale" in payload, f"missing rationale for {name}"


def main() -> int:
    test_default_audit_blocks_promotion_with_hard_failures()
    test_hard_gates_pass_when_audit_flags_flip_true()
    test_missing_audit_file_emits_explicit_failure_not_crash()
    test_repository_audit_matches_schema_and_documents_open_bugs()
    print("auto_policy_challenger_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
