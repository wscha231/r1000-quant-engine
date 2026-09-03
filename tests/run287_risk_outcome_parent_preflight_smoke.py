#!/usr/bin/env python3
"""Smoke tests for the read-only risk-outcome parent preflight receipt."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_run287_risk_outcome_parent_preflight import (  # noqa: E402
    FALSE_SAFETY_FLAGS,
    build_receipt,
    sha256_bytes,
    write_receipt,
)
from tools.run287_paper_ledger_integrity import (  # noqa: E402
    INTEGRITY_FILE,
    PAPER_IMMUTABLE_HEAD_SELECTION_SCHEMA,
    PAPER_IMMUTABLE_HEAD_SELECTION_STATUS,
    PaperLedgerIntegrityError,
    build_integrity_verifier_receipt,
    copy_diagnostic_file_exact,
    select_verified_immutable_paper_head,
    verify_integrity_manifest,
    write_integrity_manifest,
    write_integrity_verifier_receipt,
)
from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    run as run_paper_ledger,
)
from tests.run287_paper_ledger_transaction_smoke import (  # noqa: E402
    ledger_args,
    prepare,
)


KNOWN_LEGACY_SUMMARY_SHA256 = (
    "5a57e4becef19668dce45803eb77185bc"
    "6c60bcf9b58522df939e9a48a56654c"
)
AUDITED_MASTER_SHA = "2056dcc13687dff55a9c71bea23c74ec47032ad9"
PAPER_DATES = (
    "2026-07-17",
    "2026-07-20",
    "2026-07-21",
    "2026-07-22",
    "2026-07-23",
    "2026-07-24",
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )


def write_known_legacy_summary(path: Path) -> None:
    payload = {
        "as_of_date": "2026-07-17",
        "blockers": [],
        "distinct_decision_week_count": 0,
        "fullrun_executed": False,
        "historical_cagr_mdd_evidence_changed": False,
        "live_trading_enabled": False,
        "mechanism_review_gate": {
            "normal_63d_count": 0,
            "warning_63d_count": 0,
        },
        "mechanism_review_ready": False,
        "orders_generated": False,
        "portfolio_transition_allowed": False,
        "price_universe_unique_ticker_count": 1,
        "production_activation_allowed": False,
        "review_only": True,
        "schema_version": "run287-risk-outcome-archive-v1",
        "signal_observation_count": 0,
        "status": "SKIPPED_NO_DECISION_OBSERVATIONS",
        "target_books_mutated": False,
    }
    write_json(path, payload)
    assert sha256_bytes(path.read_bytes()) == KNOWN_LEGACY_SUMMARY_SHA256
    assert len(path.read_bytes()) == 668


def write_real_paper_fixture(root: Path) -> dict[str, object]:
    """Write six complete accepted-ledger heads over 243 tracked files."""
    paper = root / "paper"
    heads = root / "heads"
    heads.mkdir(parents=True)
    prepare(root, list(PAPER_DATES))
    first_result = run_paper_ledger(
        ledger_args(
            root,
            PAPER_DATES[0],
            suppress_new_orders=True,
        )
    )
    assert first_result["status"] == "completed"
    initial = verify_integrity_manifest(paper, require=True)
    assert initial["file_count"] < 243
    for index in range(243 - initial["file_count"]):
        write_json(
            paper / "h1_fixture" / f"file_{index:03d}.json",
            {"fixture_file": index, "tamper_evident": True},
        )

    manifests: list[dict] = []
    manifest = write_integrity_manifest(
        paper,
        as_of_date=PAPER_DATES[0],
        previous_snapshot_hash="",
    )
    assert manifest["file_count"] == 243
    assert "status" not in manifest
    manifests.append(manifest)
    shutil.copytree(paper, heads / manifest["snapshot_hash"])
    for as_of_date in PAPER_DATES[1:]:
        result = run_paper_ledger(
            ledger_args(root, as_of_date, suppress_new_orders=True)
        )
        assert result["status"] == "completed"
        verified = verify_integrity_manifest(
            paper,
            require=True,
        )
        assert verified["file_count"] == 243
        assert verified["status"] == "VERIFIED"
        raw_manifest = json.loads(
            (paper / INTEGRITY_FILE).read_text(encoding="utf-8")
        )
        assert "status" not in raw_manifest
        manifests.append(raw_manifest)
        shutil.copytree(paper, heads / raw_manifest["snapshot_hash"])

    terminal = manifests[-1]
    chain = [manifest["snapshot_hash"] for manifest in manifests]
    selection_path = root / "evidence" / "paper_head_selection.json"
    selection = select_verified_immutable_paper_head(heads)
    assert selection["schema_version"] == (
        PAPER_IMMUTABLE_HEAD_SELECTION_SCHEMA
    )
    assert selection["status"] == PAPER_IMMUTABLE_HEAD_SELECTION_STATUS
    assert selection["chain_snapshot_hashes"] == chain
    assert selection["selected_as_of_date"] == terminal["as_of_date"]
    write_json(selection_path, selection)
    verifier_payload = build_integrity_verifier_receipt(
        paper,
        immutable_head_selection=selection_path,
    )
    verifier_path = root / "evidence" / "paper_verifier_receipt.json"
    write_integrity_verifier_receipt(verifier_path, verifier_payload)
    return {
        "paper": paper,
        "heads": heads,
        "selection": selection_path,
        "verifier": verifier_path,
        "manifests": manifests,
    }


def base_kwargs(root: Path) -> dict:
    summary = root / "outcome" / "summary.json"
    write_known_legacy_summary(summary)
    fixture = write_real_paper_fixture(root)
    paper = Path(fixture["paper"])
    return {
        "event_name": "schedule",
        "source_commit_sha": AUDITED_MASTER_SHA,
        "source_run_id": "33476672130",
        "source_run_attempt": "1",
        "source_job_key": "refresh",
        "session_date": "2026-08-31",
        "remote_head_discovery_confirmed": True,
        "remote_committed_head_count": 0,
        "remote_legacy_outcome_state": "PRESENT_FETCHED",
        "legacy_summary_path": summary,
        "legacy_event_log_path": root / "outcome" / "events.jsonl",
        "paper_integrity_path": paper / INTEGRITY_FILE,
        "paper_integrity_verifier_receipt_path": fixture["verifier"],
        "paper_immutable_head_selection_path": fixture["selection"],
        "allow_risk_outcome_genesis_bootstrap": False,
        "allow_quarantined_legacy_outcome_parent": False,
        "generated_at_utc": "2026-09-02T00:00:00Z",
    }


def assert_safe(receipt: dict) -> None:
    assert receipt["review_only"] is True
    for field in FALSE_SAFETY_FLAGS:
        assert receipt[field] is False


def expect_value_error(kwargs: dict, fragment: str) -> None:
    try:
        build_receipt(**kwargs)
    except ValueError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected ValueError containing {fragment!r}")


def test_real_243_file_six_head_fixture_reaches_next_blocker() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        raw_manifest = json.loads(
            Path(kwargs["paper_integrity_path"]).read_text(
                encoding="utf-8"
            )
        )
        assert raw_manifest["file_count"] == 243
        assert len(raw_manifest["ancestor_snapshot_hashes"]) == 5
        assert "status" not in raw_manifest
        fixture_heads = sorted(
            path.name
            for path in Path(kwargs["paper_immutable_head_selection_path"])
            .parent.parent.joinpath("heads")
            .iterdir()
        )
        assert fixture_heads == sorted(
            [
                raw_manifest["snapshot_hash"],
                *raw_manifest["ancestor_snapshot_hashes"],
            ]
        )
        assert all(
            (
                Path(kwargs["paper_immutable_head_selection_path"])
                .parent.parent
                / "heads"
                / snapshot_hash
                / INTEGRITY_FILE
            ).is_file()
            for snapshot_hash in fixture_heads
        )

        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_ONE_TIME_LEGACY_QUARANTINE_"
            "AUTHORIZATION_REQUIRED"
        )
        observed = receipt["observed_state"]
        paper = observed["paper_ledger"]
        assert paper["status"] == "VERIFIED"
        assert paper["file_count"] == 243
        assert paper["immutable_head_count"] == 6
        assert paper["ancestor_snapshot_count"] == 5
        assert (
            paper["snapshot_hash"]
            == paper["immutable_terminal_snapshot_hash"]
        )
        assert observed["remote_committed_accepted_head_count"] == 0
        assert observed[
            "remote_committed_accepted_head_absence_proven"
        ] is True
        legacy = observed["legacy_parent"]
        assert legacy["summary_sha256"] == KNOWN_LEGACY_SUMMARY_SHA256
        assert legacy["summary_bytes"] == 668
        assert legacy["byte_exact_allowlist_match"] is True
        assert receipt["authorization"]["satisfied"] is False
        assert receipt["blockers"] == [
            "explicit_workflow_dispatch_authorization_required"
        ]
        assert_safe(receipt)


def test_raw_manifest_status_is_forbidden_and_missing_status_is_valid() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        manifest_path = Path(kwargs["paper_integrity_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "status" not in manifest
        build_receipt(**kwargs)

        manifest["status"] = "VERIFIED"
        write_json(manifest_path, manifest)
        expect_value_error(
            kwargs,
            "paper_integrity_verification_failed:BLOCKED_INTEGRITY:"
            "integrity manifest keys mismatch",
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        manifest_path = Path(kwargs["paper_integrity_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = "unreviewed-paper-schema"
        write_json(manifest_path, manifest)
        expect_value_error(kwargs, "integrity manifest schema mismatch")


def test_verifier_receipt_missing_forged_and_hash_mismatch_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        Path(kwargs["paper_integrity_verifier_receipt_path"]).unlink()
        expect_value_error(
            kwargs, "paper_integrity_verifier_receipt_missing"
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        receipt_path = Path(
            kwargs["paper_integrity_verifier_receipt_path"]
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["forged_authority"] = True
        write_json(receipt_path, receipt)
        expect_value_error(
            kwargs, "paper_integrity_verifier_receipt_mismatch"
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        receipt_path = Path(
            kwargs["paper_integrity_verifier_receipt_path"]
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        expect_value_error(
            kwargs, "paper_integrity_verifier_receipt_mismatch"
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        receipt_path = Path(
            kwargs["paper_integrity_verifier_receipt_path"]
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["raw_manifest"]["sha256"] = "0" * 64
        write_json(receipt_path, receipt)
        expect_value_error(
            kwargs, "paper_integrity_verifier_receipt_mismatch"
        )


def test_missing_extra_and_changed_files_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        paper = Path(kwargs["paper_integrity_path"]).parent
        (paper / "h1_fixture" / "file_000.json").unlink()
        expect_value_error(kwargs, "snapshot checksum mismatch missing=")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        paper = Path(kwargs["paper_integrity_path"]).parent
        write_json(paper / "unexpected.json", {"unexpected": True})
        expect_value_error(kwargs, "snapshot checksum mismatch missing=[]")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        paper = Path(kwargs["paper_integrity_path"]).parent
        write_json(
            paper / "h1_fixture" / "file_001.json",
            {"fixture_file": 1, "tampered": True},
        )
        expect_value_error(kwargs, "snapshot checksum mismatch missing=[]")


def test_parent_terminal_and_six_head_chain_mismatches_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        manifest_path = Path(kwargs["paper_integrity_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["previous_snapshot_hash"] = "f" * 64
        write_json(manifest_path, manifest)
        expect_value_error(kwargs, "ancestor snapshot chain is invalid")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        selection_path = Path(
            kwargs["paper_immutable_head_selection_path"]
        )
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selection["terminal_snapshot_hash"] = "f" * 64
        write_json(selection_path, selection)
        expect_value_error(
            kwargs,
            "immutable paper head selection receipt does not match",
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        selection = json.loads(
            Path(kwargs["paper_immutable_head_selection_path"]).read_text(
                encoding="utf-8"
            )
        )
        shutil.rmtree(Path(selection["selected_head_dir"]))
        expect_value_error(
            kwargs,
            "immutable paper head selection receipt does not match the "
            "reverified on-disk immutable head chain",
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        selection = json.loads(
            Path(kwargs["paper_immutable_head_selection_path"]).read_text(
                encoding="utf-8"
            )
        )
        heads = Path(selection["heads_root"])
        shutil.rmtree(heads)
        heads.mkdir()
        expect_value_error(
            kwargs,
            "immutable paper heads contain no committed head",
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        selection_path = Path(
            kwargs["paper_immutable_head_selection_path"]
        )
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selection["immutable_head_count"] = 5
        write_json(selection_path, selection)
        expect_value_error(
            kwargs,
            "immutable paper head selection receipt does not match",
        )


def test_symlink_backed_state_and_head_files_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        paper_file = (
            Path(kwargs["paper_integrity_path"]).parent
            / "h1_fixture"
            / "file_000.json"
        )
        external = root / "external-identical.json"
        external.write_bytes(paper_file.read_bytes())
        paper_file.unlink()
        paper_file.symlink_to(external)
        expect_value_error(kwargs, "paper snapshot contains a symlink")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        selection = json.loads(
            Path(kwargs["paper_immutable_head_selection_path"]).read_text(
                encoding="utf-8"
            )
        )
        head_file = (
            Path(selection["selected_head_dir"])
            / "h1_fixture"
            / "file_000.json"
        )
        external = root / "external-head-identical.json"
        external.write_bytes(head_file.read_bytes())
        head_file.unlink()
        head_file.symlink_to(external)
        expect_value_error(
            kwargs,
            "immutable paper head bundle symlink is forbidden",
        )


def test_verifier_receipt_hash_is_deterministic_for_same_input() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        first = build_integrity_verifier_receipt(
            Path(kwargs["paper_integrity_path"]).parent,
            immutable_head_selection=Path(
                kwargs["paper_immutable_head_selection_path"]
            ),
        )
        second = build_integrity_verifier_receipt(
            Path(kwargs["paper_integrity_path"]).parent,
            immutable_head_selection=Path(
                kwargs["paper_immutable_head_selection_path"]
            ),
        )
        assert first == second
        first_path = root / "receipts" / "first.json"
        second_path = root / "receipts" / "second.json"
        write_integrity_verifier_receipt(first_path, first)
        write_integrity_verifier_receipt(second_path, second)
        assert first_path.read_bytes() == second_path.read_bytes()
        assert sha256_bytes(first_path.read_bytes()) == sha256_bytes(
            second_path.read_bytes()
        )


def test_verifier_receipt_cli_rebuilds_exact_expected_bytes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        output = root / "receipts" / "cli.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run287_paper_ledger_integrity.py"),
                "--state-dir",
                str(Path(kwargs["paper_integrity_path"]).parent),
                "--require-integrity",
                "--immutable-head-selection",
                str(kwargs["paper_immutable_head_selection_path"]),
                "--verifier-receipt-output",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        assert output.read_bytes() == Path(
            kwargs["paper_integrity_verifier_receipt_path"]
        ).read_bytes()


def test_verifier_receipt_output_cannot_mutate_state_or_follow_temp_symlink() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        paper = Path(kwargs["paper_integrity_path"]).parent
        forbidden_output = paper / "verifier_receipt.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run287_paper_ledger_integrity.py"),
                "--state-dir",
                str(paper),
                "--require-integrity",
                "--immutable-head-selection",
                str(kwargs["paper_immutable_head_selection_path"]),
                "--verifier-receipt-output",
                str(forbidden_output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "must be outside the accepted paper state" in (
            result.stdout + result.stderr
        )
        assert not forbidden_output.exists()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        payload = build_integrity_verifier_receipt(
            Path(kwargs["paper_integrity_path"]).parent,
            immutable_head_selection=Path(
                kwargs["paper_immutable_head_selection_path"]
            ),
        )
        output = root / "receipts" / "receipt.json"
        output.parent.mkdir()
        victim = root / "victim.txt"
        victim.write_text("do-not-overwrite\n", encoding="utf-8")
        legacy_fixed_temp = output.with_name(f".{output.name}.tmp")
        legacy_fixed_temp.symlink_to(victim)
        write_integrity_verifier_receipt(output, payload)
        assert victim.read_text(encoding="utf-8") == "do-not-overwrite\n"
        assert legacy_fixed_temp.is_symlink()
        assert output.is_file() and not output.is_symlink()

        unsafe_output = root / "unsafe-receipt.json"
        unsafe_output.symlink_to(victim)
        try:
            write_integrity_verifier_receipt(unsafe_output, payload)
        except PaperLedgerIntegrityError as exc:
            assert "contains a symlink component" in str(exc)
        else:
            raise AssertionError("symlink verifier receipt output was accepted")


def test_diagnostic_copy_rejects_source_symlink_and_fixed_temp_attack() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        source = Path(kwargs["paper_integrity_path"])
        output = root / "diagnostic" / "snapshot_integrity.json"
        victim = root / "victim.txt"
        victim.write_text("do-not-overwrite\n", encoding="utf-8")
        output.parent.mkdir()
        legacy_fixed_temp = output.with_name(f".{output.name}.tmp")
        legacy_fixed_temp.symlink_to(victim)

        result = copy_diagnostic_file_exact(source, output)
        assert result["status"] == "COPIED_BYTE_EXACT_NO_SYMLINKS"
        assert output.read_bytes() == source.read_bytes()
        assert victim.read_text(encoding="utf-8") == "do-not-overwrite\n"
        assert legacy_fixed_temp.is_symlink()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        source = Path(kwargs["paper_integrity_path"])
        external = root / "external-manifest.json"
        external.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(external)
        output = root / "diagnostic" / "snapshot_integrity.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run287_paper_ledger_integrity.py"),
                "--state-dir",
                str(source.parent),
                "--safe-diagnostic-copy-source",
                str(source),
                "--safe-diagnostic-copy-output",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "contains a symlink component" in (
            result.stdout + result.stderr
        )
        assert not output.exists()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        source = Path(kwargs["paper_integrity_path"])
        output = source.parent / "diagnostic-copy.json"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "run287_paper_ledger_integrity.py"),
                "--state-dir",
                str(source.parent),
                "--safe-diagnostic-copy-source",
                str(source),
                "--safe-diagnostic-copy-output",
                str(output),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert "must be outside the accepted paper state" in (
            result.stdout + result.stderr
        )
        assert not output.exists()


def test_separate_migration_consumer_can_open_only_existing_boundary() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_quarantined_legacy_outcome_parent"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 0
        assert receipt["status"] == "READY_ONE_TIME_LEGACY_QUARANTINE"
        assert receipt["authorization"]["satisfied"] is True
        assert receipt["next_action"] == (
            "continue_to_existing_one_time_parent_anchor_boundary"
        )
        assert receipt["accepted_head_created"] is False
        assert receipt["parent_anchor_created"] is False
        assert_safe(receipt)


def test_unknown_legacy_bytes_never_receive_authority() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_quarantined_legacy_outcome_parent"] = True
        summary = Path(kwargs["legacy_summary_path"])
        summary.write_bytes(summary.read_bytes().rstrip(b"\n"))
        expect_value_error(kwargs, "legacy_summary_sha256_not_allowlisted")


def test_remote_absence_and_paper_integrity_are_mandatory() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["remote_head_discovery_confirmed"] = False
        expect_value_error(
            kwargs, "remote_accepted_head_discovery_not_confirmed"
        )

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["remote_committed_head_count"] = 1
        expect_value_error(kwargs, "remote_accepted_head_absence_not_proven")

    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        Path(kwargs["paper_integrity_path"]).unlink()
        expect_value_error(kwargs, "paper_integrity_missing")


def test_genesis_requires_exact_absence_and_separate_migration_consumer() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        Path(kwargs["legacy_summary_path"]).unlink()
        kwargs["remote_legacy_outcome_state"] = "PROVEN_ABSENT"
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_ONE_TIME_GENESIS_AUTHORIZATION_REQUIRED"
        )

        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_risk_outcome_genesis_bootstrap"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 0
        assert receipt["status"] == "READY_ONE_TIME_GENESIS"
        assert receipt["observed_state"]["legacy_parent"]["state"] == (
            "PROVEN_ABSENT"
        )
        assert_safe(receipt)


def test_mismatched_and_mutually_exclusive_authorizations_block() -> None:
    with tempfile.TemporaryDirectory() as td:
        kwargs = base_kwargs(Path(td))
        kwargs["event_name"] = "workflow_dispatch"
        kwargs["allow_risk_outcome_genesis_bootstrap"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_PARENT_MODE_AUTHORIZATION_MISMATCH"
        )

        kwargs["allow_quarantined_legacy_outcome_parent"] = True
        receipt, exit_code = build_receipt(**kwargs)
        assert exit_code == 2
        assert receipt["status"] == (
            "BLOCKED_MUTUALLY_EXCLUSIVE_BOOTSTRAP_AUTHORIZATIONS"
        )
        assert_safe(receipt)


def test_receipt_write_is_complete_and_replayable() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        kwargs = base_kwargs(root)
        receipt, _ = build_receipt(**kwargs)
        output = root / "receipt" / "receipt.json"
        write_receipt(output, receipt)
        assert json.loads(output.read_text(encoding="utf-8")) == receipt
        assert not output.with_name(".receipt.json.tmp").exists()


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(
        "run287_risk_outcome_parent_preflight_smoke: "
        f"{len(tests)} passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
