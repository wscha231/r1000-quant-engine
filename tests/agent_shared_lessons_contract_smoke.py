#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def assert_no_unredacted_query_keys(text: str, rel: str) -> None:
    offenders = []
    for pattern in [r"token=(?!\*\*\*)[A-Za-z0-9._:-]+", r"apikey=(?!\*\*\*)[A-Za-z0-9._:-]+"]:
        offenders.extend(re.findall(pattern, text))
    assert not offenders, f"{rel} contains unredacted query key fragments: {offenders[:3]}"


def test_shared_lessons_ledger_exists_and_has_update_contract() -> None:
    text = read("docs/AGENT_SHARED_LESSONS_LEDGER.md")
    required = [
        "Entry Template",
        "Standing Rules For Agents",
        "Current API Access Surface",
        "Forward estimate feed made usable with free vendor fallback",
        "Vendor error messages can leak API keys",
        "Do-not-repeat",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, missing
    assert "Do not paste secrets" in text
    assert_no_unredacted_query_keys(text, "docs/AGENT_SHARED_LESSONS_LEDGER.md")


def test_agent_api_access_contract_is_secret_name_only() -> None:
    text = read("docs/AGENT_API_ACCESS_CONTRACT.md")
    required = [
        "FINNHUB_API_KEY",
        "ALPHAVANTAGE_API_KEY",
        "FMP_API_KEY",
        "Safe Smoke For Estimate Feed",
        "What This Does Not Authorize",
        "Required Sharing Discipline",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, missing
    assert "Do not commit `.env` files" in text
    assert_no_unredacted_query_keys(text, "docs/AGENT_API_ACCESS_CONTRACT.md")


def test_secrets_setup_does_not_store_values() -> None:
    text = read(".github/SECRETS_SETUP.md")
    assert "| Name | Value |" not in text
    assert "GitHub's encrypted secret field" in text
    assert "Current Secret Names" in text
    assert "ALPHAVANTAGE_API_KEY" in text
    assert "FMP_API_KEY" in text
    assert_no_unredacted_query_keys(text, ".github/SECRETS_SETUP.md")


def test_pr_template_requires_lessons_and_credential_checks() -> None:
    text = read(".github/PULL_REQUEST_TEMPLATE.md")
    required = [
        "Shared Lessons / Mistake Notebook",
        "docs/AGENT_SHARED_LESSONS_LEDGER.md",
        "Research / Production Boundary",
        "Credential Safety",
        "No fullrun was dispatched",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, missing


if __name__ == "__main__":
    test_shared_lessons_ledger_exists_and_has_update_contract()
    test_agent_api_access_contract_is_secret_name_only()
    test_secrets_setup_does_not_store_values()
    test_pr_template_requires_lessons_and_credential_checks()
    print("agent_shared_lessons_contract_smoke: PASS")
