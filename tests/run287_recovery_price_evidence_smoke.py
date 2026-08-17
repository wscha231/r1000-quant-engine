#!/usr/bin/env python3
"""Smoke checks for the review-only Run287 recovery price evidence path."""
from __future__ import annotations

import json
import sys
import zipfile
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_recovery_price_evidence import (  # noqa: E402
    BLOCKED_STATUS,
    READY_STATUS,
    build,
    sha256_file,
)
from tools.run287_paper_ledger_integrity import (  # noqa: E402
    write_integrity_manifest,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


SESSION = "2026-07-27"
PAPER_AS_OF = "2026-07-24"
TICKERS = ["AAA", "BBB", "QQQ", "SMH", "SOXX", "SPY"]


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_contract(path: Path) -> None:
    source = json.loads(
        (ROOT / "docs/run287_recovery_price_evidence_contract.json").read_text(
            encoding="utf-8"
        )
    )
    source["after_close_anchor"]["minimum_operating_ticker_overlap_count"] = 1
    write_json(path, source)


def artifact_metadata(
    role: str, *, run_id: str, archive_sha256: str
) -> dict[str, object]:
    after_close = role == "after_close"
    artifact_name = (
        f"after-close-daily-{run_id}"
        if after_close
        else f"accepted-paper-catchup-{PAPER_AS_OF}-{run_id}"
    )
    return {
        "schema_version": "github-artifact-download-metadata-v3",
        "role": role,
        "run_id": run_id,
        "artifact_id": str(int(run_id) + 1),
        "artifact_name": artifact_name,
        "artifact_zip_sha256": archive_sha256,
        "artifact_api_digest": f"sha256:{archive_sha256}",
        "artifact_created_at_utc": "2026-07-28T02:00:00+00:00",
        "downloaded_at_utc": "2026-08-17T01:00:00+00:00",
        "workflow_id": "274285936" if after_close else "296748480",
        "workflow_path": (
            ".github/workflows/after_close_daily.yml"
            if after_close
            else ".github/workflows/daily_operating_selection_refresh.yml"
        ),
        "head_branch": "master",
        "head_sha": "b" * 40,
        "workflow_event": "schedule" if after_close else "workflow_dispatch",
        "workflow_status": "completed",
        "workflow_conclusion": "success",
        "workflow_created_at_utc": "2026-07-28T01:00:00+00:00",
        "workflow_updated_at_utc": "2026-07-28T02:30:00+00:00",
        "workflow_run_attempt": "1",
        "repository": "wscha231/r1000-quant-engine",
        "head_repository": "wscha231/r1000-quant-engine",
        "default_branch": "master",
        "current_default_head_sha": "c" * 40,
        "head_lineage_verified": True,
    }


def make_paper_state(root: Path) -> Path:
    state = root / "accepted/outputs/daily_simulated_fill_ledger"
    write_json(
        state / "summary.json",
        {
            "as_of_date": PAPER_AS_OF,
            "review_only": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        },
    )
    write_json(state / "genesis_identity.json", {"identity": "fixture"})
    for portfolio, ticker in (("main", "AAA"), ("concentrated", "BBB")):
        write_json(
            state / portfolio / "manifest.json",
            {
                "as_of_date": PAPER_AS_OF,
                "review_only": True,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
            },
        )
        write_json(
            state / portfolio / "account_state_latest.json",
            {
                "as_of_date": PAPER_AS_OF,
                "review_only": True,
                "production_mutation_allowed": False,
                "live_trading_enabled": False,
                "positions": [{"ticker": ticker, "shares": 10}],
            },
        )
        target = state / portfolio / "effective_target_latest.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [{"rebalance_date": PAPER_AS_OF, "ticker": ticker, "weight": 1.0}]
        ).to_csv(target, index=False)
        pd.DataFrame(columns=["ticker", "pending_status"]).to_csv(
            state / portfolio / "pending_orders.csv", index=False
        )
    write_integrity_manifest(state, as_of_date=PAPER_AS_OF)
    return state


def make_after_close(root: Path, *, mismatch: bool = False) -> Path:
    artifact = root / "after_close"
    out = artifact / "cloud_results/theme_leadership_tape"
    write_json(
        out / "summary.json",
        {
            "status": "completed",
            "research_only": True,
            "production_activation_allowed": False,
            "latest_price_date": SESSION,
        },
    )
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "price_status": "ok",
                "price_date": SESSION,
                "close": 111.0 if mismatch else 101.0,
                "volume": 1000.0,
            },
            {
                "ticker": "BBB",
                "price_status": "ok",
                "price_date": SESSION,
                "close": 101.0,
                "volume": 1000.0,
            },
        ]
    ).to_csv(out / "ticker_leadership.csv", index=False)
    return artifact


def make_price_cache(root: Path, *, omit: str = "") -> Path:
    cache = root / "fresh_price_cache"
    cache.mkdir(parents=True)
    records: dict[str, dict[str, object]] = {}
    for ticker in TICKERS:
        if ticker == omit:
            continue
        path = cache / px_cache_name(ticker)
        pd.DataFrame(
            {
                "Open": [100.0],
                "High": [103.0],
                "Low": [99.0],
                "Close": [101.0],
                "Adj Close": [101.0],
                "Volume": [1000.0],
            },
            index=pd.DatetimeIndex([pd.Timestamp(SESSION)], name="Date"),
        ).to_parquet(path)
        records[ticker] = {
            "file": path.name,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    write_json(
        cache / "replay_price_cache_manifest.json",
        {
            "schema_version": "run287-replay-price-cache-manifest-v2",
            "status": "completed",
            "review_only": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
            "exact_operating_universe": True,
            "refresh_through_exact_coverage": True,
            "refresh_through_date": SESSION,
            "common_coverage_end": SESSION,
            "end": SESSION,
            "cache_files": records,
        },
    )
    return cache


def zip_tree(source: Path, destination: Path) -> Path:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    return destination


def make_fixture(
    root: Path,
    *,
    omit_price: str = "",
    anchor_mismatch: bool = False,
) -> Namespace:
    contract = root / "contract.json"
    write_contract(contract)
    paper_state = make_paper_state(root)
    after_close = make_after_close(root, mismatch=anchor_mismatch)
    accepted_archive = zip_tree(root / "accepted", root / "accepted.zip")
    after_archive = zip_tree(after_close, root / "after_close.zip")
    accepted_metadata = root / "accepted_metadata.json"
    after_metadata = root / "after_metadata.json"
    write_json(
        accepted_metadata,
        artifact_metadata(
            "accepted_paper",
            run_id="30975268034",
            archive_sha256=sha256_file(accepted_archive),
        ),
    )
    write_json(
        after_metadata,
        artifact_metadata(
            "after_close",
            run_id="30408674839",
            archive_sha256=sha256_file(after_archive),
        ),
    )
    return Namespace(
        session_date=SESSION,
        contract=str(contract),
        accepted_paper_state=str(paper_state),
        accepted_paper_metadata=str(accepted_metadata),
        accepted_paper_archive=str(accepted_archive),
        after_close_root=str(after_close),
        after_close_metadata=str(after_metadata),
        after_close_archive=str(after_archive),
        price_cache=str(make_price_cache(root, omit=omit_price)),
        output_dir=str(root / "evidence"),
        output_status=str(root / "status.json"),
    )


def test_ready_evidence_binds_all_inputs_without_authorizing_consumption() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        payload = build(make_fixture(root))
        assert payload["status"] == READY_STATUS
        assert payload["exact_close_coverage"] == 1.0
        assert payload["required_ticker_count"] == len(TICKERS)
        assert payload["operating_ticker_count"] == 2
        assert payload["catchup_consumption_allowed"] is False
        assert payload["paper_ledger_mutated"] is False
        manifest = json.loads(
            (root / "evidence/manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["status"] == READY_STATUS
        assert manifest["accepted_paper_as_of_date"] == PAPER_AS_OF
        assert manifest["after_close_overlap"]["exact_anchor_overlap_ratio"] == 1.0
        assert manifest["requires_follow_up_consumption_review"] is True
        assert manifest["catchup_consumption_allowed"] is False
        assert len(manifest["materialized_price_files"]) == len(TICKERS)
        prices = pd.read_csv(root / "evidence/prices.csv")
        assert set(prices["ticker"]) == set(TICKERS)


def test_missing_exact_price_and_cross_source_mismatch_fail_closed() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "missing"
        payload = build(make_fixture(root, omit_price="BBB"))
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == ["price_cache_missing_required:BBB"]
        assert not (root / "evidence").exists()

    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "mismatch"
        payload = build(make_fixture(root, anchor_mismatch=True))
        assert payload["status"] == BLOCKED_STATUS
        assert payload["contract_failures"] == [
            "after_close_cross_source_mismatch:AAA"
        ]
        assert not (root / "evidence").exists()


def test_tampered_accepted_state_and_broadened_metadata_fail_closed() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "paper_tamper"
        args = make_fixture(root)
        account = Path(args.accepted_paper_state) / "main/account_state_latest.json"
        payload = json.loads(account.read_text(encoding="utf-8"))
        payload["positions"][0]["shares"] = 999
        write_json(account, payload)
        result = build(args)
        assert result["status"] == BLOCKED_STATUS
        assert result["contract_failures"] == [
            "accepted_paper_integrity:PaperLedgerIntegrityError"
        ]

    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "metadata"
        args = make_fixture(root)
        metadata_path = Path(args.after_close_metadata)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["untrusted_override"] = True
        write_json(metadata_path, metadata)
        result = build(args)
        assert result["status"] == BLOCKED_STATUS
        assert result["contract_failures"] == ["after_close_metadata_shape"]

    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "archive_binding"
        args = make_fixture(root)
        summary_path = (
            Path(args.after_close_root)
            / "cloud_results/theme_leadership_tape/summary.json"
        )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["unbound_mutation"] = True
        write_json(summary_path, summary)
        result = build(args)
        assert result["status"] == BLOCKED_STATUS
        assert result["contract_failures"] == [
            "after_close_summary_archive_member_hash"
        ]


def test_manual_workflow_is_evidence_only() -> None:
    workflow = (
        ROOT / ".github/workflows/run287_recovery_price_evidence_manual.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "permissions:\n  contents: read\n  actions: read" in workflow
    for required in (
        "after_close_run_id",
        "after_close_artifact_digest",
        "accepted_paper_run_id",
        "accepted_paper_artifact_digest",
        "build_run287_recovery_price_evidence.py",
        "build_replay_price_cache.py",
        "--exact-operating-universe",
        "--refresh-through-date",
        "run287-recovery-price-evidence-",
    ):
        assert required in workflow
    for forbidden in (
        "run_daily_simulated_fill_ledger.py",
        "rclone copy",
        "rclone sync",
        "git push",
        "--execute",
        "promotion",
    ):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_ready_evidence_binds_all_inputs_without_authorizing_consumption()
    test_missing_exact_price_and_cross_source_mismatch_fail_closed()
    test_tampered_accepted_state_and_broadened_metadata_fail_closed()
    test_manual_workflow_is_evidence_only()
    print("run287_recovery_price_evidence_smoke: PASS")
