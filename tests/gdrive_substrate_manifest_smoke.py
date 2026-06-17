#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_gdrive_sync_manifest import build_manifest  # noqa: E402


SUBSTRATE_EVIDENCE_FILES = [
    "universe_recovery_candidate/summary.json",
    "universe_recovery_candidate/report.md",
    "universe_recovery_candidate_readiness/summary.json",
    "universe_recovery_candidate_readiness/report.md",
    "proxy_10y_universe_substrate/summary.json",
    "proxy_10y_universe_substrate/report.md",
    "proxy_10y_universe_substrate/proxy_universe_membership_by_month.csv",
]
EVIDENCE_TIER_REVIEW_FILES = [
    "clean_7y_research_readiness/summary.json",
    "clean_7y_research_readiness/report.md",
    "proxy_10y_robustness/summary.json",
    "proxy_10y_robustness/report.md",
]
SUBSTRATE_RESEARCH_FILES = [
    "universe_recovery_candidate/candidate_universe_recovery.csv",
    "universe_recovery_candidate_readiness/missing_price_tickers.csv",
]
DAILY_USER_CURRENT_FILES = [
    "02_target_weights.csv",
    "03_order_preview.csv",
    "08_rebalance_decision.json",
    "09_daily_output_contract_summary.json",
    "DAILY_REVIEW_ONLY.md",
]


def write(path: Path, text: str = "{}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_args(root: Path, *, mode: str) -> argparse.Namespace:
    return argparse.Namespace(
        latest_run=str(root / "latest_run"),
        mode=mode,
        run_id="123456",
        run_attempt="1",
        head_sha="abc123",
        branch_name="codex/test",
        safe_branch="codex_test",
        auth="",
        dest="",
        portfolio_system_guard_hard_errors="",
        output=str(root / f"manifest_{mode}.json"),
        tsv=str(root / f"files_{mode}.tsv"),
        copy_status="",
        strict_primary=False,
    )


def seed_latest_run(root: Path) -> Path:
    latest = root / "latest_run"
    write(
        latest / "account_evaluation" / "official_metrics.json",
        json.dumps({"official_metric_mode": "broker_ledger_next_close"}) + "\n",
    )
    for rel in SUBSTRATE_EVIDENCE_FILES:
        if rel.endswith(".csv"):
            write(latest / rel, "ticker,date\nAAA,2026-06-15\n")
        elif rel.endswith(".md"):
            write(latest / rel, "# Review-only substrate evidence\n")
        else:
            write(latest / rel, json.dumps({"production_mutation_allowed": False}) + "\n")
    for rel in EVIDENCE_TIER_REVIEW_FILES:
        if rel.endswith(".md"):
            write(latest / rel, "# Evidence tier review\n")
        else:
            write(latest / rel, json.dumps({"promotion_allowed": False}) + "\n")
    for rel in SUBSTRATE_RESEARCH_FILES:
        write(latest / rel, "ticker\nAAA\n")
    for rel in DAILY_USER_CURRENT_FILES:
        if rel.endswith(".csv"):
            write(latest / "user_current" / rel, "portfolio,ticker\nmain,AAA\n")
        elif rel.endswith(".md"):
            write(latest / "user_current" / rel, "# Review-only daily output\n")
        else:
            write(latest / "user_current" / rel, json.dumps({"review_only": True}) + "\n")
    return latest


def by_source(payload: dict) -> dict[str, dict]:
    return {str(row["relative_source"]): row for row in payload["entries"]}


def test_minimal_manifest_includes_review_only_substrate_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_latest_run(root)
        payload = build_manifest(build_args(root, mode="minimal"))
        entries = by_source(payload)

        for rel in SUBSTRATE_EVIDENCE_FILES:
            row = entries[rel]
            assert row["exists"] is True
            assert row["semantic_type"] == "substrate_evidence_review"
            assert row["production_valid"] is False
            assert row["destination"].startswith("substrate_evidence/123456/")
        for rel in EVIDENCE_TIER_REVIEW_FILES:
            row = entries[rel]
            assert row["exists"] is True
            assert row["semantic_type"] == "evidence_tier_review"
            assert row["production_valid"] is False
            assert row["destination"].startswith("evidence_review/123456/")
        for rel in SUBSTRATE_RESEARCH_FILES:
            assert rel not in entries


def test_manifest_includes_daily_user_current_contract_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_latest_run(root)
        payload = build_manifest(build_args(root, mode="minimal"))
        entries = by_source(payload)

        for rel in DAILY_USER_CURRENT_FILES:
            row = entries[f"user_current/{rel}"]
            assert row["exists"] is True
            assert row["destination"] == f"user_current/{rel}"
            assert row["semantic_type"] == "daily_review_only"
            assert row["production_valid"] is False


def test_research_manifest_includes_supporting_substrate_csvs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_latest_run(root)
        payload = build_manifest(build_args(root, mode="research"))
        entries = by_source(payload)

        for rel in SUBSTRATE_EVIDENCE_FILES:
            row = entries[rel]
            assert row["semantic_type"] == "substrate_evidence_review"
            assert row["production_valid"] is False
            assert row["metric_mode"] == ""
        for rel in EVIDENCE_TIER_REVIEW_FILES:
            row = entries[rel]
            assert row["semantic_type"] == "evidence_tier_review"
            assert row["production_valid"] is False
            assert row["metric_mode"] == ""
        for rel in SUBSTRATE_RESEARCH_FILES:
            row = entries[rel]
            assert row["exists"] is True
            assert row["semantic_type"] == "substrate_research"
            assert row["production_valid"] is False
            assert row["destination"].startswith("research_runs/codex_test/123456/research_full/")


if __name__ == "__main__":
    test_minimal_manifest_includes_review_only_substrate_evidence()
    test_manifest_includes_daily_user_current_contract_files()
    test_research_manifest_includes_supporting_substrate_csvs()
    print("gdrive_substrate_manifest_smoke: PASS")
