#!/usr/bin/env python3
"""Fail-closed restore/persist continuity checks for Run287 paper snapshots."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run287_paper_ledger_integrity import (  # noqa: E402
    INTEGRITY_FILE,
    LEGACY_INTEGRITY_SCHEMA,
    PaperLedgerIntegrityError,
    canonical_hash,
    directory_hashes,
    install_verified_snapshot,
    require_state_descends_from,
    verify_integrity_manifest,
    write_integrity_manifest,
)
from tools.run_daily_simulated_fill_ledger import run as run_paper_ledger  # noqa: E402
from tests.run287_paper_ledger_transaction_smoke import (  # noqa: E402
    ledger_args,
    prepare,
    write_target,
)


def _new_snapshot(root: Path, as_of_date: str, value: str) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "genesis_identity.json").write_text(
        json.dumps({"ledger": "run287-test", "generation": 1}),
        encoding="utf-8",
    )
    for portfolio in ("main", "concentrated"):
        directory = root / portfolio
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "fills.csv").write_text(
            "event_id,value\n", encoding="utf-8"
        )
        (directory / "rejections.csv").write_text(
            "event_id,value\n", encoding="utf-8"
        )
        (directory / "equity_curve.csv").write_text(
            f"date,value\n{as_of_date},{value}\n", encoding="utf-8"
        )
    (root / "state.json").write_text(
        json.dumps({"as_of_date": as_of_date, "value": value}),
        encoding="utf-8",
    )
    return write_integrity_manifest(root, as_of_date=as_of_date)


def _advance_snapshot(root: Path, as_of_date: str, value: str) -> dict:
    prior = verify_integrity_manifest(root, require=True)
    for portfolio in ("main", "concentrated"):
        with (root / portfolio / "equity_curve.csv").open(
            "a", encoding="utf-8", newline=""
        ) as handle:
            handle.write(f"{as_of_date},{value}\n")
    (root / "state.json").write_text(
        json.dumps({"as_of_date": as_of_date, "value": value}),
        encoding="utf-8",
    )
    return write_integrity_manifest(
        root,
        as_of_date=as_of_date,
        previous_snapshot_hash=prior["snapshot_hash"],
    )


def _expect_continuity_block(callable_) -> None:
    try:
        callable_()
    except PaperLedgerIntegrityError as exc:
        assert exc.status == "BLOCKED_CONTINUITY", str(exc)
    else:
        raise AssertionError("unsafe snapshot continuity was accepted")


def test_restore_installs_only_a_proven_descendant_and_retains_stale_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        anchor = root / "anchor"
        source = root / "source"
        destination = root / "destination"
        first = _new_snapshot(anchor, "2026-07-20", "accepted-a")
        shutil.copytree(anchor, source)
        second = _advance_snapshot(source, "2026-07-21", "accepted-b")
        shutil.copytree(anchor, destination)

        installed = install_verified_snapshot(
            source, destination, require_continuity=True
        )
        assert installed["install_status"] == "INSTALLED_VERIFIED_DESCENDANT"
        assert installed["continuity_status"] == "CANDIDATE_DESCENDS_FROM_ANCHOR"
        assert verify_integrity_manifest(destination, require=True)["snapshot_hash"] == second[
            "snapshot_hash"
        ]

        before = directory_hashes(destination)
        retained = install_verified_snapshot(
            anchor, destination, require_continuity=True
        )
        assert retained["install_status"] == "RETAINED_NEWER_VERIFIED_DESTINATION"
        assert retained["snapshot_hash"] == second["snapshot_hash"]
        assert directory_hashes(destination) == before
        assert first["snapshot_hash"] in second["ancestor_snapshot_hashes"]


def test_restore_accepts_multi_session_descendant_via_cumulative_lineage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        anchor = root / "anchor"
        source = root / "source"
        destination = root / "destination"
        first = _new_snapshot(anchor, "2026-07-17", "accepted-a")
        shutil.copytree(anchor, source)
        _advance_snapshot(source, "2026-07-20", "accepted-b")
        third = _advance_snapshot(source, "2026-07-21", "accepted-c")
        shutil.copytree(anchor, destination)

        installed = install_verified_snapshot(
            source, destination, require_continuity=True
        )
        assert installed["install_status"] == "INSTALLED_VERIFIED_DESCENDANT"
        assert first["snapshot_hash"] in third["ancestor_snapshot_hashes"]
        assert verify_integrity_manifest(destination, require=True)["snapshot_hash"] == third[
            "snapshot_hash"
        ]


def test_restore_blocks_alternate_chain_and_missing_anchor_without_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        common = root / "common"
        destination = root / "destination"
        alternate = root / "alternate"
        _new_snapshot(common, "2026-07-20", "accepted-a")
        shutil.copytree(common, destination)
        shutil.copytree(common, alternate)
        _advance_snapshot(destination, "2026-07-21", "accepted-b")
        _advance_snapshot(alternate, "2026-07-21", "alternate-b")
        before = directory_hashes(destination)

        _expect_continuity_block(
            lambda: install_verified_snapshot(
                alternate, destination, require_continuity=True
            )
        )
        assert directory_hashes(destination) == before

        missing = root / "missing"
        _expect_continuity_block(
            lambda: install_verified_snapshot(
                alternate, missing, require_continuity=True
            )
        )
        assert not missing.exists()


def test_restore_blocks_same_date_resealed_descendant() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        anchor = root / "anchor"
        candidate = root / "candidate"
        destination = root / "destination"
        _new_snapshot(anchor, "2026-07-20", "accepted-a")
        shutil.copytree(anchor, candidate)
        _advance_snapshot(candidate, "2026-07-20", "rewritten-same-date")
        shutil.copytree(anchor, destination)
        before = directory_hashes(destination)
        _expect_continuity_block(
            lambda: install_verified_snapshot(
                candidate,
                destination,
                require_continuity=True,
            )
        )
        assert directory_hashes(destination) == before


def test_restore_accepts_same_session_mark_only_to_selected_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        as_of_date = "2026-04-01"
        anchor = root / "anchor"
        destination = root / "destination"
        prepare(root, [as_of_date])

        mark_only = run_paper_ledger(
            ledger_args(root, as_of_date, suppress_new_orders=True)
        )
        assert mark_only["new_order_generation_suppressed"] is True
        shutil.copytree(root / "paper", anchor)
        shutil.copytree(anchor, destination)
        anchor_integrity = verify_integrity_manifest(anchor, require=True)

        write_target(
            root / "targets" / "main.csv",
            "main",
            "AAA",
            as_of_date,
            stock_weight=0.60,
        )
        write_target(
            root / "targets" / "concentrated.csv",
            "concentrated",
            "BBB",
            as_of_date,
            stock_weight=0.60,
        )
        selected = run_paper_ledger(ledger_args(root, as_of_date))
        assert selected["new_order_generation_suppressed"] is False
        candidate_integrity = verify_integrity_manifest(
            root / "paper", require=True
        )
        assert candidate_integrity["as_of_date"] == anchor_integrity["as_of_date"]
        assert (
            candidate_integrity["previous_snapshot_hash"]
            == anchor_integrity["snapshot_hash"]
        )
        assert (
            candidate_integrity["snapshot_hash"]
            != anchor_integrity["snapshot_hash"]
        )

        checked = require_state_descends_from(root / "paper", anchor)
        assert checked["continuity_status"] == "CANDIDATE_DESCENDS_FROM_ANCHOR"
        installed = install_verified_snapshot(
            root / "paper",
            destination,
            require_continuity=True,
        )
        assert installed["install_status"] == "INSTALLED_VERIFIED_DESCENDANT"
        assert (
            verify_integrity_manifest(destination, require=True)["snapshot_hash"]
            == candidate_integrity["snapshot_hash"]
        )

        forged = root / "forged"
        forged_destination = root / "forged-destination"
        shutil.copytree(root / "paper", forged)
        shutil.copytree(anchor, forged_destination)
        publication_path = forged / "accepted_publication.json"
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        publication["portfolios"]["main"][
            "preview_mode_at_acceptance"
        ] = "NO_NEW_ORDER"
        publication_path.write_text(
            json.dumps(publication, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (forged / INTEGRITY_FILE).unlink()
        write_integrity_manifest(
            forged,
            as_of_date=as_of_date,
            previous_snapshot_hash=anchor_integrity["snapshot_hash"],
        )
        before = directory_hashes(forged_destination)
        _expect_continuity_block(
            lambda: install_verified_snapshot(
                forged,
                forged_destination,
                require_continuity=True,
            )
        )
        assert directory_hashes(forged_destination) == before

        retained = install_verified_snapshot(
            anchor,
            destination,
            require_continuity=True,
        )
        assert retained["install_status"] == "RETAINED_NEWER_VERIFIED_DESTINATION"
        assert (
            verify_integrity_manifest(destination, require=True)["snapshot_hash"]
            == candidate_integrity["snapshot_hash"]
        )


def test_persist_preflight_requires_local_state_to_descend_from_remote() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        remote = root / "remote"
        local = root / "local"
        _new_snapshot(remote, "2026-07-20", "accepted-a")
        shutil.copytree(remote, local)
        local_latest = _advance_snapshot(local, "2026-07-21", "accepted-b")

        checked = require_state_descends_from(local, remote)
        assert checked["continuity_status"] == "CANDIDATE_DESCENDS_FROM_ANCHOR"
        assert checked["snapshot_hash"] == local_latest["snapshot_hash"]
        _expect_continuity_block(lambda: require_state_descends_from(remote, local))


def test_v1_anchor_migrates_to_v2_lineage_without_losing_continuity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        legacy = root / "legacy"
        local = root / "local"
        payload = _new_snapshot(legacy, "2026-07-20", "accepted-a")
        payload["schema_version"] = LEGACY_INTEGRITY_SCHEMA
        payload.pop("ancestor_snapshot_hashes", None)
        payload["snapshot_hash"] = canonical_hash(
            {
                "schema_version": payload["schema_version"],
                "as_of_date": payload["as_of_date"],
                "files": payload["files"],
                "genesis_identity_sha256": payload["genesis_identity_sha256"],
                "previous_snapshot_hash": payload["previous_snapshot_hash"],
            }
        )
        (legacy / INTEGRITY_FILE).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        legacy_verified = verify_integrity_manifest(legacy, require=True)
        assert legacy_verified["schema_version"] == LEGACY_INTEGRITY_SCHEMA
        shutil.copytree(legacy, local)

        migrated = _advance_snapshot(local, "2026-07-21", "accepted-b")
        assert migrated["ancestor_snapshot_hashes"][0] == legacy_verified["snapshot_hash"]
        checked = require_state_descends_from(local, legacy)
        assert checked["continuity_status"] == "CANDIDATE_DESCENDS_FROM_ANCHOR"


def test_manifest_ancestry_tamper_and_noncanonical_date_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        snapshot = root / "snapshot"
        _new_snapshot(snapshot, "2026-07-20", "accepted-a")
        _advance_snapshot(snapshot, "2026-07-21", "accepted-b")
        manifest_path = snapshot / INTEGRITY_FILE
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["ancestor_snapshot_hashes"].append("f" * 64)
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            verify_integrity_manifest(snapshot, require=True)
        except PaperLedgerIntegrityError as exc:
            assert exc.status == "BLOCKED_INTEGRITY"
        else:
            raise AssertionError("tampered ancestry was accepted")

        invalid = root / "invalid-date"
        invalid.mkdir()
        (invalid / "state.json").write_text("{}", encoding="utf-8")
        try:
            write_integrity_manifest(invalid, as_of_date="2026-7-2")
        except PaperLedgerIntegrityError as exc:
            assert "ISO date" in str(exc)
        else:
            raise AssertionError("noncanonical snapshot date was accepted")


def test_self_asserted_ancestry_cannot_replace_unrelated_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        anchor = root / "anchor"
        unrelated = root / "unrelated"
        destination = root / "destination"
        anchor_manifest = _new_snapshot(
            anchor, "2026-07-20", "accepted-anchor"
        )
        _new_snapshot(unrelated, "2026-07-20", "unrelated-history")
        manifest_path = unrelated / INTEGRITY_FILE
        forged = json.loads(manifest_path.read_text(encoding="utf-8"))
        forged["previous_snapshot_hash"] = anchor_manifest["snapshot_hash"]
        forged["ancestor_snapshot_hashes"] = [
            anchor_manifest["snapshot_hash"]
        ]
        forged["snapshot_hash"] = canonical_hash(
            {
                "schema_version": forged["schema_version"],
                "as_of_date": forged["as_of_date"],
                "files": forged["files"],
                "genesis_identity_sha256": forged[
                    "genesis_identity_sha256"
                ],
                "previous_snapshot_hash": forged[
                    "previous_snapshot_hash"
                ],
                "ancestor_snapshot_hashes": forged[
                    "ancestor_snapshot_hashes"
                ],
            }
        )
        manifest_path.write_text(
            json.dumps(forged, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shutil.copytree(anchor, destination)
        before = directory_hashes(destination)
        _expect_continuity_block(
            lambda: install_verified_snapshot(
                unrelated, destination, require_continuity=True
            )
        )
        assert directory_hashes(destination) == before


def test_workflow_preserves_cache_anchor_and_checks_restore_and_persist_chains() -> None:
    text = (
        ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    ).read_text(encoding="utf-8")
    required = (
        'restore_dir outputs outputs "daily_simulated_fill_ledger/**"',
        "--require-install-continuity",
        "reconciled explicit latest_run ledger with immutable-cache anchor",
        "adopted checksum-verified explicit latest_run ledger as continuity anchor",
        "--require-state-descends-from \"$PAPER_REMOTE_PERSIST_ANCHOR\"",
        "run287_daily_simulated_fill_ledger_heads",
        'if [ "$VERIFIED_HEAD_HASH" != "$PAPER_HEAD_HASH" ]',
        "reconciled all immutable Drive heads; divergent heads fail closed",
        'if [ "$CAS_SNAPSHOT_HASH" != "$ANCHOR_SNAPSHOT_HASH" ]',
        'if [ "$POSTCHECK_SNAPSHOT_HASH" != "$LOCAL_SNAPSHOT_HASH" ]',
    )
    for fragment in required:
        assert fragment in text, fragment
    restore_index = text.index("--require-install-continuity")
    transaction_index = text.index(
        "- name: Run transactional paper ledger and same-close selector"
    )
    persist_index = text.index(
        "--require-state-descends-from \"$PAPER_REMOTE_PERSIST_ANCHOR\""
    )
    sync_index = text.index(
        "rclone sync outputs/daily_simulated_fill_ledger \"$CANONICAL/\""
    )
    immutable_head_index = text.index(
        'rclone copy outputs/daily_simulated_fill_ledger "$HEADS/$LOCAL_SNAPSHOT_HASH/"'
    )
    cas_index = text.index(
        'if [ "$CAS_SNAPSHOT_HASH" != "$ANCHOR_SNAPSHOT_HASH" ]'
    )
    postcheck_index = text.index(
        'if [ "$POSTCHECK_SNAPSHOT_HASH" != "$LOCAL_SNAPSHOT_HASH" ]'
    )
    assert restore_index < transaction_index
    assert persist_index < immutable_head_index < cas_index < sync_index < postcheck_index


def main() -> int:
    test_restore_installs_only_a_proven_descendant_and_retains_stale_source()
    test_restore_accepts_multi_session_descendant_via_cumulative_lineage()
    test_restore_blocks_alternate_chain_and_missing_anchor_without_mutation()
    test_restore_blocks_same_date_resealed_descendant()
    test_restore_accepts_same_session_mark_only_to_selected_target()
    test_persist_preflight_requires_local_state_to_descend_from_remote()
    test_v1_anchor_migrates_to_v2_lineage_without_losing_continuity()
    test_manifest_ancestry_tamper_and_noncanonical_date_fail_closed()
    test_self_asserted_ancestry_cannot_replace_unrelated_state()
    test_workflow_preserves_cache_anchor_and_checks_restore_and_persist_chains()
    print("run287_paper_snapshot_continuity_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
