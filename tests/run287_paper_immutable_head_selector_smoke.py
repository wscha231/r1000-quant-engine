#!/usr/bin/env python3
"""Focused smoke coverage for immutable Run287 paper-head selection."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from tools.run287_paper_ledger_integrity import (  # noqa: E402
    PaperLedgerIntegrityError,
    _linear_immutable_paper_head_chain,
    install_unique_verified_immutable_paper_head,
    reconcile_immutable_paper_head_cache,
    select_verified_immutable_paper_head,
    verify_integrity_manifest,
    write_integrity_manifest,
)
from tools.run_daily_simulated_fill_ledger import run as run_paper_ledger  # noqa: E402
from tests.run287_paper_ledger_transaction_smoke import (  # noqa: E402
    ledger_args,
    prepare,
)


def _write_synthetic_head(
    heads: Path,
    work: Path,
    *,
    as_of_date: str,
    value: str,
    previous_snapshot_hash: str = "",
) -> tuple[Path, dict]:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "genesis_identity.json").write_text('{"genesis":"one"}\n', encoding="utf-8")
    (work / "state.json").write_text(value + "\n", encoding="utf-8")
    manifest = write_integrity_manifest(
        work,
        as_of_date=as_of_date,
        previous_snapshot_hash=previous_snapshot_hash,
    )
    target = heads / manifest["snapshot_hash"]
    shutil.copytree(work, target)
    return target, manifest


def _expect_blocked(fragment: str, callback: object) -> None:
    try:
        callback()  # type: ignore[operator]
    except PaperLedgerIntegrityError as exc:
        assert exc.status in {"BLOCKED_INTEGRITY", "BLOCKED_CONTINUITY"}
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected blocked integrity error containing {fragment!r}")


def test_selects_terminal_ignores_uncommitted_and_installs() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        heads.mkdir()
        dates = ["2026-04-08", "2026-04-09", "2026-04-10"]
        prepare(root, dates)
        run_paper_ledger(
            ledger_args(root, dates[0], suppress_new_orders=True)
        )
        first_manifest = verify_integrity_manifest(root / "paper", require=True)
        first = heads / first_manifest["snapshot_hash"]
        shutil.copytree(root / "paper", first)
        run_paper_ledger(
            ledger_args(root, dates[1], suppress_new_orders=True)
        )
        second_manifest = verify_integrity_manifest(root / "paper", require=True)
        second = heads / second_manifest["snapshot_hash"]
        shutil.copytree(root / "paper", second)
        # The protocol writes the marker last, so a partial upload is ignored.
        (heads / "partial-upload").mkdir()
        selection = select_verified_immutable_paper_head(heads)
        assert selection["terminal_snapshot_hash"] == second_manifest["snapshot_hash"]
        assert selection["selected_head_dir"] == str(second.resolve())
        installed = install_unique_verified_immutable_paper_head(heads, root / "installed")
        assert installed["install_status"] == "INSTALLED_VERIFIED_SNAPSHOT"
        assert verify_integrity_manifest(root / "installed")["snapshot_hash"] == second_manifest["snapshot_hash"]
        assert first.is_dir()
        cache = root / "head_cache"
        reconciled = reconcile_immutable_paper_head_cache(
            cache,
            merge_heads_roots=[heads],
            expected_terminal_hash=second_manifest["snapshot_hash"],
        )
        assert (
            reconciled["cache_status"]
            == "RECONCILED_IMMUTABLE_PAPER_HEAD_CACHE"
        )
        assert reconciled["immutable_head_count"] == 2
        assert reconciled["heads_root"] == str(cache.resolve())
        assert reconciled["selected_head_dir"].startswith(
            str(cache.resolve())
        )
        assert (
            select_verified_immutable_paper_head(cache)[
                "selected_snapshot_hash"
            ]
            == second_manifest["snapshot_hash"]
        )
        run_paper_ledger(
            ledger_args(
                root,
                dates[2],
                suppress_new_orders=True,
            )
        )
        third_manifest = verify_integrity_manifest(
            root / "paper",
            require=True,
        )
        reconciled = reconcile_immutable_paper_head_cache(
            cache,
            add_head_sources=[root / "paper"],
            expected_terminal_hash=third_manifest["snapshot_hash"],
        )
        assert reconciled["immutable_head_count"] == 3


def test_orphan_fork_and_multiple_roots_fail_closed() -> None:
    genesis = "f" * 64
    root_hash = "1" * 64
    child_a = "2" * 64
    child_b = "3" * 64
    base = {
        "genesis_identity_sha256": genesis,
        "as_of_date": "2026-07-20",
    }
    orphan = {
        child_a: {
            **base,
            "previous_snapshot_hash": root_hash,
            "ancestor_snapshot_hashes": [root_hash],
        }
    }
    _expect_blocked(
        "parent is missing",
        lambda: _linear_immutable_paper_head_chain(orphan),
    )
    fork = {
        root_hash: {
            **base,
            "previous_snapshot_hash": "",
            "ancestor_snapshot_hashes": [],
        },
        child_a: {
            **base,
            "previous_snapshot_hash": root_hash,
            "ancestor_snapshot_hashes": [root_hash],
        },
        child_b: {
            **base,
            "previous_snapshot_hash": root_hash,
            "ancestor_snapshot_hashes": [root_hash],
        },
    }
    _expect_blocked(
        "fork detected",
        lambda: _linear_immutable_paper_head_chain(fork),
    )
    roots = {
        root_hash: {
            **base,
            "previous_snapshot_hash": "",
            "ancestor_snapshot_hashes": [],
        },
        child_a: {
            **base,
            "previous_snapshot_hash": "",
            "ancestor_snapshot_hashes": [],
        },
    }
    _expect_blocked(
        "root count is invalid",
        lambda: _linear_immutable_paper_head_chain(roots),
    )


def test_hash_valid_non_paper_bundle_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        heads = root / "heads"
        heads.mkdir()
        _write_synthetic_head(
            heads,
            root / "synthetic",
            as_of_date="2026-07-20",
            value=json.dumps({"not": "a paper ledger"}),
        )
        _expect_blocked(
            "complete two-portfolio ledger",
            lambda: select_verified_immutable_paper_head(heads),
        )


def test_cycle_detection_and_large_linear_chain_are_iterative() -> None:
    cycle_nodes = {
        "a" * 64: {"previous_snapshot_hash": "b" * 64, "ancestor_snapshot_hashes": []},
        "b" * 64: {"previous_snapshot_hash": "a" * 64, "ancestor_snapshot_hashes": []},
    }
    _expect_blocked("cycle detected", lambda: _linear_immutable_paper_head_chain(cycle_nodes))

    # Exercise a chain longer than Python's usual recursion limit without
    # building large on-disk snapshot payloads; graph traversal is the unit
    # under test here and must remain iterative.
    count = 1_205
    hashes = [f"{index:064x}" for index in range(count)]
    nodes = {}
    ancestors: list[str] = []
    for index, snapshot_hash in enumerate(hashes):
        nodes[snapshot_hash] = {
            "previous_snapshot_hash": hashes[index - 1] if index else "",
            "ancestor_snapshot_hashes": list(ancestors),
            "genesis_identity_sha256": "c" * 64,
            "as_of_date": "2026-07-20",
        }
        ancestors.insert(0, snapshot_hash)
    root_hash, terminal_hash, chain = _linear_immutable_paper_head_chain(nodes)
    assert root_hash == hashes[0]
    assert terminal_hash == hashes[-1]
    assert chain == hashes


def main() -> int:
    test_selects_terminal_ignores_uncommitted_and_installs()
    test_orphan_fork_and_multiple_roots_fail_closed()
    test_hash_valid_non_paper_bundle_is_rejected()
    test_cycle_detection_and_large_linear_chain_are_iterative()
    print("run287_paper_immutable_head_selector_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
