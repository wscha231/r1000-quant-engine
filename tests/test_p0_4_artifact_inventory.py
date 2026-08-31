from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
INVENTORY = ROOT / "docs" / "run287_p0_4_artifact_inventory"
SOURCE = INVENTORY / "source_inventory_snapshot.json"
FROZEN_PROTECTED_PUBLICATION_COMMIT = "6fad35cd390d844a4f656f0d03d4395af0c996fe"
FROZEN_FULL_REBUILD_TREE_SHA1 = "af900d05a16402361ddd03d3d228f67f91ed8c60"
OUTPUT_FILES = (
    "README.md",
    "summary.json",
    "dataset_registry.yaml",
    "model_registry.yaml",
    "artifact_registry.parquet",
    "durable_state_registry.yaml",
    "latest_to_immutable_map.yaml",
    "migration_map.md",
)
REQUIRED_COLUMNS = {
    "object_id",
    "schema_version",
    "market",
    "object_class",
    "logical_role",
    "producer",
    "provider",
    "storage_kind",
    "exact_location",
    "immutable_location",
    "mutable_alias",
    "as_of",
    "available_from",
    "created_at",
    "decision_time_cutoff",
    "code_sha",
    "config_hash",
    "data_hash",
    "universe_hash",
    "source_artifact_hashes",
    "size_bytes",
    "row_count",
    "file_count",
    "content_sha256",
    "manifest_sha256",
    "writer_workflow",
    "writer_job",
    "write_authority",
    "pit_classification",
    "survivorship_classification",
    "corporate_action_classification",
    "license_classification",
    "secret_pii_classification",
    "retention_classification",
    "downstream_consumers",
    "rollback_restore",
    "mapping_status",
    "discovery_status",
    "blockers",
    "observed_at_utc",
    "baseline_code_sha",
    "source_snapshot_sha256",
    "source_publication_commit",
}


def source() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def git(*args: str, binary: bool = False):
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=not binary,
        encoding=None if binary else "utf-8",
    )


def baseline_sha() -> str:
    return source()["baseline_code_sha"]


def baseline_text(path: str) -> str:
    return git("show", f"{baseline_sha()}:{path}")


def tree_rows(prefix: str, *, ref: str | None = None) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for line in git(
        "ls-tree", "-r", "-l", ref or baseline_sha(), prefix
    ).splitlines():
        meta, path = line.split("\t", 1)
        _mode, _kind, sha, size = meta.split()
        rows.append((path, sha, int(size)))
    return rows


def relative_tree(prefix: str) -> dict[str, tuple[str, int]]:
    base = prefix.rstrip("/") + "/"
    return {path[len(base) :]: (sha, size) for path, sha, size in tree_rows(prefix)}


def test_tracked_bundle_exists_and_has_expected_counts() -> None:
    for name in OUTPUT_FILES + ("source_inventory_snapshot.json", "requirements.txt"):
        assert (INVENTORY / name).is_file(), name
    summary = json.loads((INVENTORY / "summary.json").read_text(encoding="utf-8"))
    assert summary["counts"] == {
        "datasets": 24,
        "models": 4,
        "durable_states": 8,
        "artifacts": 41,
        "artifact_registry_rows": 77,
    }
    assert summary["safety"]["mutations_performed"] == []
    assert summary["safety"]["live_trading_enabled"] is False
    assert summary["safety"]["target_order_ledger_mutation"] is False


def test_generator_is_byte_stable(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "build_p0_4_artifact_inventory.py"),
            "--source",
            str(SOURCE),
            "--output-dir",
            str(tmp_path),
            "--verify-live-head",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            "generator subprocess failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    for name in OUTPUT_FILES:
        assert (tmp_path / name).read_bytes() == (INVENTORY / name).read_bytes(), name


def test_registries_and_parquet_cover_every_object_once() -> None:
    payload = source()
    expected = {
        row["object_id"]
        for key in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[key]
    }
    assert len(expected) == 77
    frame = pd.read_parquet(INVENTORY / "artifact_registry.parquet")
    assert REQUIRED_COLUMNS == set(frame.columns)
    assert set(frame["object_id"]) == expected
    assert frame["object_id"].is_unique
    assert frame["market"].eq("US").all()
    assert frame["baseline_code_sha"].eq(payload["baseline_code_sha"]).all()
    assert frame["source_snapshot_sha256"].eq(
        "3c28008b10e2c3e2d0ce7f603300a544d437474062d86d307369ca31c610e096"
    ).all()
    assert frame["source_publication_commit"].eq(
        "302516e5229760477bc9d5b5ddc618bf0b493185"
    ).all()
    assert frame["exact_location"].astype(str).str.strip().ne("").all()
    assert frame["rollback_restore"].astype(str).str.strip().ne("").all()
    assert frame["provider"].astype(str).str.strip().ne("").all()
    assert frame["provider"].ne("UNRESOLVED").all()
    providers = frame.set_index("object_id")["provider"].to_dict()
    assert providers["artifact.github.accepted-paper-transaction-publication"] == (
        "github_actions_artifact"
    )
    assert providers["artifact.github.daily-operating-evidence-publication"] == (
        "github_actions_artifact"
    )
    assert providers["artifact.drive.accepted-paper-transaction-publication"] == (
        "google_drive"
    )
    assert providers["artifact.drive.daily-operating-evidence-publication"] == (
        "google_drive"
    )
    assert set(frame["object_class"]) == {"dataset", "model", "durable_state", "artifact"}
    for registry, key in (
        ("dataset_registry.yaml", "datasets"),
        ("model_registry.yaml", "models"),
        ("durable_state_registry.yaml", "durable_states"),
    ):
        document = yaml.safe_load((INVENTORY / registry).read_text(encoding="utf-8"))
        assert document["market"] == "US"
        assert document["baseline_code_sha"] == payload["baseline_code_sha"]
        assert {row["object_id"] for row in document[key]} == {
            row["object_id"] for row in payload[key]
        }


def test_every_mutable_alias_is_verified_or_explicitly_blocked() -> None:
    payload = source()
    objects = {
        row["object_id"]: row
        for key in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[key]
    }
    mappings = yaml.safe_load(
        (INVENTORY / "latest_to_immutable_map.yaml").read_text(encoding="utf-8")
    )["mappings"]
    mapped_ids = {row["object_id"] for row in mappings}
    for object_id, row in objects.items():
        if row.get("mutable_alias"):
            assert object_id in mapped_ids, object_id
            assert ";" not in row["mutable_alias"], object_id
            assert not any(
                token in row["mutable_alias"] for token in ("*", "?", "[", "]")
            ), object_id
    aliases = [row["mutable_alias"] for row in mappings]
    assert len(aliases) == len(set(aliases))
    for row in mappings:
        status = row["status"]
        assert status == "VERIFIED_IMMUTABLE" or status.startswith("BLOCKED_")
        if status == "VERIFIED_IMMUTABLE":
            assert row["immutable_source"]
            assert row["immutable_source"] == objects[row["object_id"]][
                "immutable_location"
            ]
            assert not row["blockers"]
        else:
            assert row["blockers"]
    required_targets = {
        "artifact.drive.operating-main-target-book": (
            "outputs/reports/operating_main_target_book.csv"
        ),
        "artifact.drive.operating-concentrated-target-book": (
            "outputs/reports/operating_concentrated_target_book.csv"
        ),
        "artifact.drive.portfolio-latest": "outputs/portfolio_latest.csv",
        "artifact.drive.concentrated-portfolio-latest": (
            "outputs/concentrated_portfolio_latest.csv"
        ),
    }
    mapped = {row["object_id"]: row for row in mappings}
    for object_id, alias in required_targets.items():
        assert objects[object_id]["mutable_alias"] == alias
        assert mapped[object_id]["mutable_alias"] == alias
        assert mapped[object_id]["status"].startswith("BLOCKED_")
    required_archives = {
        "artifact.drive.paper-holding-risk-watch-archive": (
            "paper_archive/run287_holding_risk_watch/"
        ),
        "artifact.drive.paper-decision-observation-archive": (
            "paper_archive/run287_decision_observation_archive/"
        ),
        "artifact.drive.paper-risk-outcome-archive": (
            "paper_archive/run287_risk_outcome_archive/"
        ),
        "artifact.drive.paper-risk-outcome-price-cache": (
            "paper_archive/run287_risk_outcome_price_cache/"
        ),
    }
    baseline_daily = baseline_text(
        ".github/workflows/daily_operating_selection_refresh.yml"
    )
    for object_id, alias in required_archives.items():
        assert objects[object_id]["mutable_alias"] == alias
        assert mapped[object_id]["mutable_alias"] == alias
        assert mapped[object_id]["status"].startswith("BLOCKED_")
        assert alias in baseline_daily
    required_durable_aliases = {
        "state.us.paper.immutable-head": (
            "paper_archive/run287_daily_simulated_fill_ledger/"
        ),
        "state.us.risk-outcome.accepted-heads": (
            "paper_archive/run287_risk_outcome_accepted_heads/"
        ),
    }
    for object_id, alias in required_durable_aliases.items():
        assert objects[object_id]["mutable_alias"] == alias
        assert mapped[object_id]["mutable_alias"] == alias
        assert alias.removeprefix("paper_archive/") in baseline_daily
    macro_cache_id = "ds.us.macro.operational-cache"
    assert objects[macro_cache_id]["mutable_alias"] == "cache_macro"
    assert objects[macro_cache_id]["file_count"] == 15
    assert objects[macro_cache_id]["size_bytes"] == 634224
    assert objects[macro_cache_id]["producer"] == "UNRESOLVED_LEGACY_DRIVE_WRITER"
    assert objects[macro_cache_id]["writer_workflow"] == (
        "UNRESOLVED_LEGACY_DRIVE_WRITER"
    )
    assert objects[macro_cache_id]["write_authority"] == (
        "DRIVE_WRITER_UNRESOLVED; DAILY_WORKFLOW_READ_ONLY_RESTORE"
    )
    assert mapped[macro_cache_id]["mutable_alias"] == "cache_macro"
    assert mapped[macro_cache_id]["status"] == "BLOCKED_NO_IMMUTABLE_SOURCE"
    assert "cache_macro" in baseline_daily
    actions_cache_id = "artifact.github.daily-operating-macro-actions-cache"
    assert objects[actions_cache_id]["storage_kind"] == "github_actions_cache"
    assert objects[actions_cache_id]["write_authority"] == (
        "GITHUB_ACTIONS_CACHE_ONLY_NOT_DRIVE_WRITER"
    )
    actions_location = objects[actions_cache_id]["exact_location"]
    expected_actions_paths = (
        "cache_prices",
        "cache_macro",
        "models",
        "feature_store/scored_oos_latest.parquet",
        "data_raw/free",
        "data_pit/free",
        "data_pit/sec",
        "data_pit/etf_holdings",
        "data_pit/macro",
        "manifests/free_data",
    )
    assert all(path in actions_location for path in expected_actions_paths)
    assert "cache_crisis" not in objects[actions_cache_id]["exact_location"]
    assert "actions/cache/save" in baseline_daily
    recovery_id = "artifact.drive.paper-ledger-recovery-publications"
    assert objects[recovery_id]["exact_location"] == (
        "gdrive-root:1qcRMJCxDXsca5SmHFUu30yMAZdRLaxPA/paper_archive/"
        "recovery/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
    )
    assert objects[recovery_id]["mapping_status"] == "NOT_APPLICABLE"
    assert (
        "paper_archive/recovery/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
        "run287_daily_simulated_fill_ledger"
    ) in baseline_daily
    assert (
        "paper_archive/recovery/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
        "untrusted_mutable_canonical/"
    ) in baseline_daily
    paper_caches = {
        "artifact.github.daily-paper-ledger-actions-cache": (
            "daily-paper-ledger-${{ runner.os }}-${{ github.run_id }}-"
            "${{ github.run_attempt }}",
            (
                "outputs/holding_risk_watch",
                "outputs/run287_exact_packet_upstream",
                "outputs/run287_exact_packet_input_sources",
                "outputs/run287_exact_packet_input_registry",
                "outputs/run287_decision_observation_archive",
                "outputs/run287_accepted_publication",
                "outputs/run287_risk_outcome_accepted_head_bundles",
                "outputs/run287_risk_outcome_accepted_head_manifests",
                "outputs/run287_risk_outcome_archive",
                "outputs/run287_risk_outcome_price_cache",
            ),
        ),
        "artifact.github.daily-paper-continuity-actions-cache": (
            "daily-paper-continuity-v1-${{ runner.os }}-${{ github.run_id }}-"
            "${{ github.run_attempt }}",
            (
                "outputs/daily_simulated_fill_ledger",
                "outputs/run287_paper_immutable_head_bundles",
            ),
        ),
    }
    for object_id, (key, paths) in paper_caches.items():
        assert objects[object_id]["storage_kind"] == "github_actions_cache"
        assert objects[object_id]["mapping_status"] == "NOT_APPLICABLE"
        assert key in objects[object_id]["exact_location"]
        assert all(path in objects[object_id]["exact_location"] for path in paths)
        assert key in baseline_daily
        assert all(path in baseline_daily for path in paths)
    accepted_id = "artifact.drive.accepted-paper-transaction-publication"
    assert objects[accepted_id]["exact_location"] == (
        "gdrive-root:1qcRMJCxDXsca5SmHFUu30yMAZdRLaxPA/research_runs/"
        "${SAFE_BRANCH}/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
        "accepted_paper_transaction/"
    )
    assert objects[accepted_id]["mapping_status"] == "NOT_APPLICABLE"
    assert "accepted_paper_transaction" in baseline_daily
    assert "Publish the verified manifest last as the remote acceptance marker" in (
        baseline_daily
    )
    feature_aliases = {
        f"feature_store/{name}"
        for name in (
            "candidate_universe_latest.parquet",
            "latest_recommendations.parquet",
            "scored_oos_partial.parquet",
            "scored_oos_latest.parquet",
            "feature_store_latest.parquet",
            "universe_monthly_latest.parquet",
            "macro_regime_latest.parquet",
            "live_event_alert_latest.parquet",
            "fund_panel_latest.parquet",
        )
    }
    assert feature_aliases <= set(aliases)
    assert not any(alias.startswith("feature_store/") and "*" in alias for alias in aliases)
    folder_manifests = payload["folder_child_manifests"]
    assert len(folder_manifests["feature_store"]["children"]) == 9
    assert folder_manifests["feature_store"]["manifest_sha256"] == (
        "c478b3dc09c4a9b8a3f2eb940fd83af965bae5a051ce780df3d7f4ae8bce59d4"
    )
    assert len(folder_manifests["cache_macro"]["children"]) == 15
    assert sum(
        child["size_bytes"] for child in folder_manifests["cache_macro"]["children"]
    ) == 634224
    assert folder_manifests["cache_macro"]["manifest_sha256"] == (
        "96db5506b8b3f5b5eeebf5c49ce5ceff39a53b91e84710901cc82adaa24d92d1"
    )


def test_distinct_provider_publications_are_complete() -> None:
    from tools import build_p0_4_artifact_inventory as builder

    payload = builder.parse_source(SOURCE.read_bytes())
    builder.validate_source(payload)
    objects = {row["object_id"]: row for row in payload["artifacts"]}
    workflow = builder.baseline_workflow_text(payload["baseline_code_sha"])
    builder.validate_provider_publications(objects, workflow)
    builder.validate_full_rebuild_publications(
        objects,
        builder.baseline_text_file(
            payload["baseline_code_sha"], builder.FULL_REBUILD_WORKFLOW
        ),
    )
    archive = objects["artifact.input.run287-research-static-archive"]
    assert archive["content_sha256"] == builder.RESEARCH_STATIC_SHA256
    assert archive["exact_location"] == builder.RESEARCH_STATIC_PATH
    assert objects["artifact.drive.run287-research-static-archive"][
        "exact_location"
    ] == builder.RESEARCH_STATIC_DRIVE_LOCATION
    cache = objects["artifact.github.run287-research-static-actions-cache"]
    assert cache["provider"] == "github_actions_cache"
    assert cache["cache_key"] == builder.RESEARCH_STATIC_CACHE_KEY
    assert cache["provider_paths"] == [builder.RESEARCH_STATIC_PATH]
    accepted = objects["artifact.github.accepted-paper-transaction-publication"]
    assert accepted["provider"] == "github_actions_artifact"
    assert accepted["retention_days"] == 45
    assert "outputs/run287_accepted_publication/" in accepted["provider_paths"]
    assert "NO_DRIVE_OR_LEDGER_AUTHORITY" in accepted["write_authority"]
    for outcome, expected in builder.REQUIRED_CATCHUP_ARTIFACT_OBJECTS.items():
        catchup = objects[expected["object_id"]]
        assert catchup["provider"] == "github_actions_artifact"
        assert catchup["artifact_name"] == expected["artifact_name"]
        assert catchup["publication_condition"] == expected["condition"]
        assert catchup["retention_days"] == 45
        assert catchup["if_no_files_found"] == expected["if_no_files_found"]
        assert catchup["mapping_status"] == "NOT_APPLICABLE"
        assert catchup["write_authority"] == expected["write_authority"]
        assert "${{ runner.temp }}/run287_durable_scope_initial.json" in catchup[
            "provider_paths"
        ]
        if outcome == "accepted":
            assert "outputs/daily_simulated_fill_ledger/" in catchup[
                "provider_paths"
            ]
        else:
            assert any("partial" in item.lower() for item in catchup["blockers"])
    daily_github = objects["artifact.github.daily-operating-evidence-publication"]
    daily_drive = objects["artifact.drive.daily-operating-evidence-publication"]
    assert daily_github["provider"] == "github_actions_artifact"
    assert daily_drive["provider"] == "google_drive"
    assert daily_github["retention_days"] == 45
    assert "outputs/daily_market_snapshot/" in daily_github["provider_paths"]
    assert daily_drive["exact_location"] == (
        builder.OFFICIAL_DAILY_OPERATING_DRIVE_LOCATION
    )
    assert "cache_prices/replay_price_cache_manifest.json" in daily_drive[
        "provider_files"
    ]
    assert any("partial" in item.lower() for item in daily_drive["blockers"])
    for object_id, step_name in builder.REQUIRED_FULL_REBUILD_ARTIFACTS.items():
        publication = objects[object_id]
        assert publication["provider"] == "github_actions_artifact"
        assert publication["writer_workflow"] == "full_rebuild_manual.yml"
        assert publication["provider_paths"]
        assert publication["retention_days"] in (30, 365)
        assert step_name in publication["writer_job"]
    for object_id, expected in builder.REQUIRED_FULL_REBUILD_CACHES.items():
        publication = objects[object_id]
        assert publication["provider"] == "github_actions_cache"
        assert publication["cache_key"] == expected["cache_key"]
        assert publication["restore_keys"] == expected["restore_keys"]
        assert publication["provider_paths"]
        assert "EPHEMERAL_PROVIDER_CACHE" in publication[
            "retention_classification"
        ]
    for (
        object_id,
        expected,
    ) in builder.REQUIRED_FULL_REBUILD_DRIVE_PUBLICATIONS.items():
        publication = objects[object_id]
        assert publication["provider"] == "google_drive"
        assert publication["storage_kind"] == expected["storage_kind"]
        assert publication["destination_templates"] == expected[
            "destination_templates"
        ]
        assert publication["manifest_published_last"] is True
        assert publication["acceptance_manifest"] == (
            "outputs/gdrive_sync_manifest.json"
        )
    production = objects[
        "artifact.drive.full-rebuild-production-valid-publication"
    ]
    assert production["mutable_alias"] == "gdrive:outputs"
    assert production["mapping_status"] == "BLOCKED_NO_IMMUTABLE_SOURCE"


def test_paper_heads_use_the_baseline_writer_namespace() -> None:
    payload = source()
    objects = {
        row["object_id"]: row
        for key in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[key]
    }
    paper_ids = {
        "state.us.paper.immutable-head",
        "state.us.paper.accepted-publication",
        "state.us.paper.main-account",
        "state.us.paper.concentrated-account",
        "state.us.paper.main-ledger-manifest",
        "state.us.paper.concentrated-ledger-manifest",
    }
    root = "paper_archive/run287_daily_simulated_fill_ledger_heads/"
    assert root.rstrip("/") in baseline_text(
        ".github/workflows/daily_operating_selection_refresh.yml"
    )
    paper_heads = set()
    expected_suffixes = {
        "state.us.paper.immutable-head": "",
        "state.us.paper.accepted-publication": "accepted_publication.json",
        "state.us.paper.main-account": "main/account_state_latest.json",
        "state.us.paper.concentrated-account": "concentrated/account_state_latest.json",
        "state.us.paper.main-ledger-manifest": "main/manifest.json",
        "state.us.paper.concentrated-ledger-manifest": "concentrated/manifest.json",
    }
    for object_id in paper_ids:
        row = objects[object_id]
        assert row["immutable_location"].startswith(root)
        relative = row["immutable_location"][len(root) :]
        head, separator, suffix = relative.partition("/")
        assert re.fullmatch(r"[0-9a-f]{64}", head)
        assert suffix == expected_suffixes[object_id]
        assert bool(separator) == bool(expected_suffixes[object_id])
        assert row["mutable_alias"] == (
            "paper_archive/run287_daily_simulated_fill_ledger/"
            + expected_suffixes[object_id]
        )
        paper_heads.add(head)
        assert row["writer_workflow"] == "daily_operating_selection_refresh.yml"
    assert paper_heads == {objects["state.us.paper.immutable-head"]["data_hash"]}


def test_frozen_repository_inventory_matches_baseline_tree() -> None:
    payload = source()["repository_inventory"]
    tree_sha = git(
        "rev-parse",
        f"{baseline_sha()}:cloud_results/full_rebuild",
    ).strip()
    paths = git(
        "ls-tree",
        "-r",
        "--name-only",
        baseline_sha(),
        "cloud_results/full_rebuild",
    ).splitlines()
    # The recursive Git tree SHA authenticates every path, mode, child tree,
    # and blob identity without forcing a blob-size lookup.  `ls-tree -l`
    # lazily downloaded the 6.8 GB frozen history in CI's blobless checkout
    # merely to reproduce redundant byte counts, exhausting the 90-minute
    # Tier-1 budget.  Keep the published size/inventory facts pinned while
    # using the stronger native tree commitment for live identity.
    assert tree_sha == FROZEN_FULL_REBUILD_TREE_SHA1
    assert len(paths) == payload["cloud_results_full_rebuild_file_count"] == 10460
    assert payload["cloud_results_full_rebuild_blob_bytes"] == 6806634607
    assert payload["cloud_results_full_rebuild_inventory_sha256"] == (
        "d6628a71d3e1066afc5afbb92a3368c1ed9b0aaca076cc91459bb3afd06b1ac1"
    )


def test_latest_global_alias_diverges_in_exactly_scored_file() -> None:
    current = relative_tree("cloud_results/full_rebuild/latest_global_alpha_universe")
    immutable = relative_tree(
        "cloud_results/full_rebuild/20260624_28074476465_global_alpha_universe"
    )
    differing = sorted(
        path for path in set(current) | set(immutable) if current.get(path) != immutable.get(path)
    )
    assert differing == ["scored_latest.csv"]
    current_blob = git(
        "show",
        f"{baseline_sha()}:cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv",
        binary=True,
    )
    immutable_blob = git(
        "show",
        f"{baseline_sha()}:cloud_results/full_rebuild/20260624_28074476465_global_alpha_universe/scored_latest.csv",
        binary=True,
    )
    assert hashlib.sha256(current_blob).hexdigest() == "4fe7860960518240e55e6d61492bf823067928b37984ae88022f3bb3d166e25f"
    assert hashlib.sha256(immutable_blob).hexdigest() == "04f79def5db1032ccf228910d62b7f689545be700b13837fc4ee73026f56ed06"


def test_latest_r1000_adr_alias_is_exact_tree_match() -> None:
    current = relative_tree("cloud_results/full_rebuild/latest_r1000+adr")
    assert current == relative_tree("cloud_results/full_rebuild/20260428_r1000+adr")
    canonical = "\n".join(
        f"{path}\t{sha}\t{size}"
        for path, (sha, size) in sorted(current.items())
    )
    manifest_sha256 = hashlib.sha256(canonical.encode()).hexdigest()
    assert manifest_sha256 == "a8e75bc778087efdfbb3dd7d84cfbafde2efaf216e3c3503ca2a9bca497db9da"
    frame = pd.read_parquet(INVENTORY / "artifact_registry.parquet").set_index(
        "object_id"
    )
    assert frame.loc[
        "artifact.repo.latest-r1000-adr-alias", "manifest_sha256"
    ] == manifest_sha256


def test_pipeline_blocker_is_bound_to_exact_github_runs() -> None:
    health = source()["pipeline_health"]
    assert health["daily_operating_recent_run_ids"] == [
        32801137546,
        32545955145,
        32440400556,
    ]
    assert health["daily_operating_recent_conclusions"] == ["failure"] * 3
    assert health["daily_operating_failed_step"] == "Restore verified risk-outcome accepted head"
    assert health["latest_failure_terminal_reason"] == (
        "legacy outcome parent requires explicit one-time workflow_dispatch authorization"
    )
    assert health["latest_failure_live_trading_enabled"] is False
    evidence = health["daily_operating_failure_evidence"]
    assert [row["run_id"] for row in evidence] == health[
        "daily_operating_recent_run_ids"
    ]
    assert [row["job_id"] for row in evidence] == [
        97662011776,
        96964279012,
        96649802798,
    ]
    for row in evidence:
        excerpt = ("\n".join(row["terminal_excerpt_lines"]) + "\n").encode()
        assert hashlib.sha256(excerpt).hexdigest() == row[
            "terminal_excerpt_sha256"
        ]
        assert row["failed_step_number"] == 19
        assert row["exit_code"] == 2
        assert {
            (item["step_number"], item["name"], item["conclusion"])
            for item in row["downstream_skipped_steps"]
        } == {
            (26, "Build operating target books", "skipped"),
            (34, "Run transactional paper ledger and same-close selector", "skipped"),
            (46, "Persist validated forward paper ledger state", "skipped"),
        }


def test_authority_aligns_with_p0_3_census() -> None:
    census = yaml.safe_load(
        baseline_text("docs/run287_p0_3_authority_census/workflow_registry.yaml")
    )
    assert census["official_authority"]["us_target_writer_workflow"] == (
        "daily_operating_selection_refresh.yml"
    )
    assert census["official_authority"]["paper_ledger_consumer_workflow"] == (
        "daily_operating_selection_refresh.yml"
    )
    assert census["official_authority"]["live_broker_writer_workflow"] is None

    daily = baseline_text(
        ".github/workflows/daily_operating_selection_refresh.yml"
    )
    full = baseline_text(".github/workflows/full_rebuild_manual.yml")
    recommendations = {
        row["object_id"]: row
        for row in source()["artifacts"]
        if row["object_id"]
        in {
            "artifact.drive.portfolio-latest",
            "artifact.drive.concentrated-portfolio-latest",
        }
    }
    assert set(recommendations) == {
        "artifact.drive.portfolio-latest",
        "artifact.drive.concentrated-portfolio-latest",
    }
    for row in recommendations.values():
        assert row["writer_workflow"] == "full_rebuild_manual.yml"
        assert row["write_authority"] == (
            "MANUAL_FULL_REBUILD_PERSISTED_MUTABLE_RECOMMENDATION"
        )
        assert "daily_operating_selection_refresh.yml consumes" in row["blockers"][-2]
    assert 'cp outputs/portfolio_latest.csv "$DEST/"' in full
    assert 'cp outputs/concentrated_portfolio_latest.csv "$DEST/"' in full
    assert "Sync outputs to user's Google Drive" in full
    assert "outputs/portfolio_latest.csv" in daily
    assert "outputs/concentrated_portfolio_latest.csv" in daily
    assert "rclone copyto outputs/portfolio_latest.csv" not in daily
    assert "rclone copyto outputs/concentrated_portfolio_latest.csv" not in daily


def test_failed_source_run_grants_price_replay_only() -> None:
    workflow = baseline_text(
        ".github/workflows/daily_operating_selection_refresh.yml"
    )
    builder = baseline_text(
        "tools/build_run287_catchup_price_evidence.py"
    )
    assert 'fields["conclusion"] not in {"success", "failure"}' in workflow
    assert '"price_usage_scope": (' in builder
    assert '"target_books_mutated": False' in builder
    assert '"production_mutation_allowed": False' in builder
    artifact = next(
        row for row in source()["artifacts"] if row["object_id"] == "artifact.drive.paper-price-evidence"
    )
    assert "no target or ledger authority" in artifact["blockers"][0]


def test_macro_freshness_gap_is_evidence_backed() -> None:
    engine = baseline_text("tools/crisis_state_engine.py")
    policy = baseline_text("tools/run287_crisis_policy.py")
    assert "decision_time=latest_date" in engine
    assert "available_from=latest_date" in engine
    assert "fresh = available and not explicitly_stale" in policy
    assert "max_age" not in policy
    dataset = next(
        row for row in source()["datasets"] if row["object_id"] == "ds.us.macro.long-crisis-features"
    )
    assert dataset["content_sha256"] == "5b460618944303c65b97caa20323f498a266fe97005b6733ec75efd8acb3c519"
    assert dataset["mapping_status"] == "BLOCKED_NO_IMMUTABLE_SOURCE"


def test_incomplete_drive_views_fail_closed() -> None:
    payload = source()
    price = next(row for row in payload["datasets"] if row["object_id"] == "ds.us.prices.replay-cache")
    assert price["file_count"] == 1048
    assert price["discovery_status"] == "INCOMPLETE_100_OF_MANIFEST_1048_DIRECT_CHILDREN"
    assert price["mapping_status"] == "BLOCKED_NO_IMMUTABLE_SOURCE"
    assert any("100" in item and "1048" in item for item in payload["discovery_limits"])


def test_no_secret_values_are_embedded() -> None:
    payload = source()
    forbidden_keys = {
        "token",
        "api_key",
        "password",
        "private_key",
        "service_account_key",
        "secret_value",
        "credential_value",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert str(key).lower() not in forbidden_keys
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
        elif isinstance(value, str):
            yield value

    strings = list(walk(payload))
    secret_pattern = re.compile(r"(?:^|[^A-Za-z0-9])(?:ghp_|github_pat_|sk-)[A-Za-z0-9_-]+")
    assert not any(secret_pattern.search(value) for value in strings)
    assert payload["safety"]["mutations_performed"] == []


def test_rebuild_uses_the_pinned_dependency_contract() -> None:
    requirements = (INVENTORY / "requirements.txt").read_text(encoding="utf-8")
    for requirement in (
        "PyYAML==6.0.3",
        "numpy==2.3.3",
        "pandas==2.3.3",
        "pyarrow==23.0.1",
        "python-dateutil==2.9.0.post0",
        "pytz==2025.2",
        "six==1.17.0",
        "tzdata==2025.2",
    ):
        assert requirement in requirements
    assert "--only-binary=:all:" in requirements
    assert requirements.count("--hash=sha256:") == 12
    readme = (INVENTORY / "README.md").read_text(encoding="utf-8")
    assert readme.count("python -m venv --clear .venv-p0-4") == 2
    assert readme.index("set -euo pipefail") < readme.index(
        "git diff --quiet -- docs/run287_p0_4_artifact_inventory/requirements.txt"
    )
    assert (
        "merge this PR only with an expected-head merge commit; squash and rebase "
        "are prohibited"
    ) in readme
    assert 'P0_4_REQUIREMENTS="$(mktemp)"' in readme
    assert 'pathlib.Path(sys.argv[1]).write_bytes(c)' in readme
    assert '--require-hashes --requirement "$P0_4_REQUIREMENTS"' in readme
    assert (
        "--requirement docs/run287_p0_4_artifact_inventory/requirements.txt"
        not in readme
    )
    assert "tests/test_p0_4_artifact_inventory.py" in readme
    assert "git diff --cached --quiet -- docs/run287_p0_4_artifact_inventory/requirements.txt" in readme
    assert "ffc0231ec1e3cb19bd17fdee4d8314c3698b457531ede701381f640c78eb06db" in readme
    assert readme.index("write_bytes(c)") < readme.index("pip install")
    assert readme.index("if [ -L .venv-p0-4 ]; then") < readme.index(
        "python -m venv --clear .venv-p0-4"
    )
    assert "refusing symlinked .venv-p0-4" in readme
    assert "```powershell" in readme
    assert "$P0_4RequirementsTemp = New-TemporaryFile" in readme
    assert "$P0_4Python = '.\\.venv-p0-4\\Scripts\\python.exe'" in readme
    assert "& $P0_4Python -m pip install --require-hashes --requirement $P0_4RequirementsTemp" in readme
    assert "Python 3.12 required" in readme
    assert "Linux x86-64 CPython required" in readme
    assert "sysconfig.get_platform() != 'linux-x86_64'" in readme
    assert "Windows x64 CPython required" in readme
    assert "sysconfig.get_platform() != 'win-amd64'" in readme
    assert "macOS, ARM, and other interpreter platforms fail the preflight" in readme
    assert readme.index("Linux x86-64 CPython required") < readme.index(
        ".venv-p0-4/bin/python -m pip install"
    )
    assert readme.index("Windows x64 CPython required") < readme.index(
        "& $P0_4Python -m pip install"
    )
    assert readme.index(
        "git diff --exit-code -- docs/run287_p0_4_artifact_inventory"
    ) < readme.index("tests/test_p0_4_artifact_inventory.py")
    assert "canonical bundle differs from reviewed worktree bytes" in readme
    assert "canonical bundle differs from reviewed index bytes" in readme
    assert "[System.IO.FileAttributes]::ReparsePoint" in readme
    assert readme.index("refusing linked .venv-p0-4") < readme.rindex(
        "python -m venv --clear .venv-p0-4"
    )
    for failure in (
        "authenticated requirements capture failed",
        "virtual environment creation failed",
        "pinned dependency installation failed",
        "artifact inventory regeneration failed",
        "artifact inventory smoke failed",
    ):
        assert f"if ($LASTEXITCODE -ne 0) {{ throw '{failure}' }}" in readme
    assert "Remove-Item -LiteralPath $P0_4RequirementsTemp" in readme


def test_requirements_publication_is_authenticated(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    repo = tmp_path / "requirements-repo"
    requirements = repo / builder.REQUIREMENTS_PATH
    requirements.parent.mkdir(parents=True)
    expected = git("show", f"HEAD:{builder.REQUIREMENTS_PATH}", binary=True)
    requirements.write_bytes(expected)
    commands = (
        ["git", "init"],
        ["git", "config", "user.name", "P0-4 Test"],
        ["git", "config", "user.email", "p0-4@example.invalid"],
        ["git", "config", "core.autocrlf", "false"],
        ["git", "add", builder.REQUIREMENTS_PATH],
        ["git", "commit", "-m", "fixture"],
    )
    for command in commands:
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    with mock.patch.object(builder, "ROOT", repo):
        assert builder.read_clean_pinned_requirements() == expected
        requirements.write_bytes(expected + b"unreviewed==1\n")
        try:
            builder.read_clean_pinned_requirements()
        except builder.InventoryError as exc:
            assert str(exc) == (
                f"tracked_path_dirty:worktree:{builder.REQUIREMENTS_PATH}"
            )
        else:
            raise AssertionError("dirty dependency contract was accepted")
        subprocess.run(
            ["git", "add", builder.REQUIREMENTS_PATH],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "unreviewed dependency"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        try:
            builder.read_clean_pinned_requirements()
        except builder.InventoryError as exc:
            assert str(exc) == "requirements_publication_sha256_mismatch"
        else:
            raise AssertionError("unreviewed dependency bytes were accepted")


def test_source_snapshot_is_bound_to_publication_commit(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder
    from tools.build_p0_4_artifact_inventory import (
        FROZEN_SOURCE_GIT_BLOB_SHA1,
        FROZEN_SOURCE_PUBLICATION_COMMIT,
        FROZEN_SOURCE_SHA256,
        InventoryError,
        build,
        verify_frozen_source_publication,
    )

    relative = "docs/run287_p0_4_artifact_inventory/source_inventory_snapshot.json"
    assert FROZEN_SOURCE_PUBLICATION_COMMIT == (
        "302516e5229760477bc9d5b5ddc618bf0b493185"
    )
    assert git("rev-parse", f"{FROZEN_SOURCE_PUBLICATION_COMMIT}:{relative}").strip() == (
        FROZEN_SOURCE_GIT_BLOB_SHA1
    )
    publication = git(
        "show", f"{FROZEN_SOURCE_PUBLICATION_COMMIT}:{relative}", binary=True
    )
    assert hashlib.sha256(publication).hexdigest() == FROZEN_SOURCE_SHA256
    verify_frozen_source_publication(SOURCE.read_bytes())
    try:
        verify_frozen_source_publication(publication + b"\n")
    except InventoryError as exc:
        assert str(exc) == "canonical_source_differs_from_frozen_publication"
    else:
        raise AssertionError("replacement source was not rejected")
    with mock.patch.object(
        builder,
        "verify_live_publication_lineage",
        side_effect=InventoryError("canonical-source-lineage-checked"),
    ):
        try:
            builder.build(SOURCE, tmp_path / "canonical-source-export")
        except InventoryError as exc:
            assert str(exc) == "canonical-source-lineage-checked"
        else:
            raise AssertionError("canonical-source export skipped renderer lineage")
    custom = tmp_path / "custom-source.json"
    custom.write_bytes(publication)
    custom_output = tmp_path / "custom-output-unbound"
    build(custom, custom_output)
    assert (custom_output / "source_inventory_snapshot.json").read_bytes() == publication
    assert (custom_output / "requirements.txt").read_bytes() == (
        INVENTORY / "requirements.txt"
    ).read_bytes()
    custom_frame = pd.read_parquet(custom_output / "artifact_registry.parquet")
    assert custom_frame["source_publication_commit"].eq(
        "UNBOUND_CUSTOM_SOURCE"
    ).all()
    try:
        build(custom, tmp_path / "custom-output", verify_live_head=True)
    except InventoryError as exc:
        assert str(exc) == "verify_live_head_requires_canonical_source"
    else:
        raise AssertionError("live-head verification accepted a custom source")
    canonical_before = {
        name: (INVENTORY / name).read_bytes() for name in OUTPUT_FILES
    }
    try:
        build(custom, INVENTORY)
    except InventoryError as exc:
        assert str(exc) == "canonical_output_requires_canonical_source"
    else:
        raise AssertionError("custom source replaced the canonical bundle")
    assert canonical_before == {
        name: (INVENTORY / name).read_bytes() for name in OUTPUT_FILES
    }


def test_build_parses_only_the_authenticated_source_bytes(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import build

    custom = tmp_path / "captured-source.json"
    publication = SOURCE.read_bytes()
    custom.write_bytes(publication)
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text
    source_byte_reads = 0

    def guarded_read_bytes(path: Path) -> bytes:
        nonlocal source_byte_reads
        if path == custom:
            source_byte_reads += 1
            if source_byte_reads > 1:
                raise AssertionError("source bytes were reopened after authentication")
        return original_read_bytes(path)

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == custom:
            raise AssertionError("source path was reopened after authentication")
        return original_read_text(path, *args, **kwargs)

    with mock.patch.object(Path, "read_bytes", new=guarded_read_bytes), mock.patch.object(
        Path, "read_text", new=guarded_read_text
    ):
        output = tmp_path / "captured-output"
        build(custom, output)

    assert source_byte_reads == 1
    assert (output / "source_inventory_snapshot.json").read_bytes() == publication


def test_pr_validation_checkout_supports_pinned_lineage_checks() -> None:
    from tools.build_p0_4_artifact_inventory import (
        FROZEN_PUBLICATION_COMMIT,
        PINNED_PUBLICATION_FILE_SHA256,
        canonical_source_bytes,
        verify_live_publication_lineage,
    )

    relative = ".github/workflows/pr_validation.yml"
    workflow = ROOT / relative
    text = workflow.read_text(encoding="utf-8")
    assert "fetch-depth: 1" in text
    assert 'git fetch --no-tags --filter=blob:none --deepen=64 origin "$GITHUB_REF"' in text
    assert 'while true; do' in text
    assert 'git rev-parse --is-shallow-repository' in text
    assert 'git merge-base --is-ancestor "${frozen[0]}" "${frozen[2]}"' in text
    assert "0f34de9a2747059b7bb808cb070a86261e119f95" in text
    assert 'git fetch --no-tags --depth=1 origin "${{ github.event.pull_request.base.sha }}"' not in text
    assert 'git merge-base --is-ancestor "$base_sha" HEAD' in text
    assert FROZEN_PUBLICATION_COMMIT == (
        "f7fadfa4e7814c6453bf96ebf3a1ff4d39eadfae"
    )
    publication_workflow = git(
        "show", f"{FROZEN_PUBLICATION_COMMIT}:{relative}", binary=True
    )
    assert hashlib.sha256(
        canonical_source_bytes(publication_workflow)
    ).hexdigest() == PINNED_PUBLICATION_FILE_SHA256[relative]
    assert subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            source()["baseline_code_sha"],
            FROZEN_PUBLICATION_COMMIT,
        ],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", FROZEN_PUBLICATION_COMMIT, "HEAD"],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    from tools.build_p0_4_artifact_inventory import (
        FROZEN_PROTECTED_PUBLICATION_COMMIT as verifier_publication,
    )

    assert verifier_publication == FROZEN_PROTECTED_PUBLICATION_COMMIT
    verify_live_publication_lineage(
        source()["baseline_code_sha"],
        protected_commit=FROZEN_PROTECTED_PUBLICATION_COMMIT,
    )


def test_dirty_generator_is_rejected(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    repo = tmp_path / "generator-repo"
    generator = repo / builder.GENERATOR_PATH
    generator.parent.mkdir(parents=True)
    generator.write_text("print('reviewed')\n", encoding="utf-8", newline="\n")
    commands = (
        ["git", "init"],
        ["git", "config", "user.name", "P0-4 Test"],
        ["git", "config", "user.email", "p0-4@example.invalid"],
        ["git", "config", "core.autocrlf", "false"],
        ["git", "add", builder.GENERATOR_PATH],
        ["git", "commit", "-m", "fixture"],
    )
    for command in commands:
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    with mock.patch.object(builder, "ROOT", repo):
        builder.require_clean_tracked_path(builder.GENERATOR_PATH)
        generator.write_text("print('dirty')\n", encoding="utf-8", newline="\n")
        try:
            builder.require_clean_tracked_path(builder.GENERATOR_PATH)
        except builder.InventoryError as exc:
            assert str(exc) == (
                f"tracked_path_dirty:worktree:{builder.GENERATOR_PATH}"
            )
        else:
            raise AssertionError("dirty generator worktree was not rejected")
        subprocess.run(
            ["git", "add", builder.GENERATOR_PATH],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        try:
            builder.require_clean_tracked_path(builder.GENERATOR_PATH)
        except builder.InventoryError as exc:
            assert str(exc) == f"tracked_path_dirty:index:{builder.GENERATOR_PATH}"
        else:
            raise AssertionError("dirty generator index was not rejected")


def test_post_publication_protected_changes_are_rejected(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    repo = tmp_path / "protected-publication-repo"
    repo.mkdir()
    commands = (
        ["git", "init"],
        ["git", "config", "user.name", "P0-4 Test"],
        ["git", "config", "user.email", "p0-4@example.invalid"],
        ["git", "config", "core.autocrlf", "false"],
    )
    for command in commands:
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    protected = repo / "protected.txt"
    protected.write_text("reviewed\n", encoding="utf-8", newline="\n")
    generator = repo / builder.GENERATOR_PATH
    generator.parent.mkdir(parents=True)
    generator.write_text(
        'FROZEN_PROTECTED_PUBLICATION_COMMIT = "0000000000000000000000000000000000000000"\n',
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(
        ["git", "add", "protected.txt", builder.GENERATOR_PATH],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "protected publication"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    publication = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    (repo / "unrelated.txt").write_text(
        "later\n", encoding="utf-8", newline="\n"
    )
    subprocess.run(
        ["git", "add", "unrelated.txt"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "unrelated descendant"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    with mock.patch.object(builder, "ROOT", repo), mock.patch.object(
        builder, "PROTECTED_PUBLICATION_PATHS", ("protected.txt",)
    ):
        builder.verify_protected_publication_lineage(publication)
        protected.write_text("changed\n", encoding="utf-8", newline="\n")
        subprocess.run(
            ["git", "add", "protected.txt"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "change protected path"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        try:
            builder.verify_protected_publication_lineage(publication)
        except builder.InventoryError as exc:
            assert str(exc) == "post_publication_protected_delta:protected.txt"
        else:
            raise AssertionError("post-publication protected change was accepted")


def test_protected_generator_allows_only_pin_delta(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    repo = tmp_path / "protected-generator-repo"
    repo.mkdir()
    for command in (
        ["git", "init"],
        ["git", "config", "user.name", "P0-4 Test"],
        ["git", "config", "user.email", "p0-4@example.invalid"],
        ["git", "config", "core.autocrlf", "false"],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    protected = repo / "protected.txt"
    protected.write_text("reviewed\n", encoding="utf-8", newline="\n")
    generator = repo / builder.GENERATOR_PATH
    generator.parent.mkdir(parents=True)
    generator.write_text(
        'FROZEN_PROTECTED_PUBLICATION_COMMIT = "0000000000000000000000000000000000000000"\n'
        "print('reviewed')\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(
        ["git", "add", "protected.txt", builder.GENERATOR_PATH],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "protected generator"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    publication = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    generator.write_text(
        'FROZEN_PROTECTED_PUBLICATION_COMMIT = "1111111111111111111111111111111111111111"\n'
        "print('reviewed')\n",
        encoding="utf-8",
        newline="\n",
    )
    subprocess.run(
        ["git", "add", builder.GENERATOR_PATH],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "advance pin only"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    with mock.patch.object(builder, "ROOT", repo), mock.patch.object(
        builder, "PROTECTED_PUBLICATION_PATHS", ("protected.txt",)
    ):
        builder.verify_protected_publication_lineage(publication)
        generator.write_text(
            generator.read_text(encoding="utf-8") + "print('unreviewed')\n",
            encoding="utf-8",
            newline="\n",
        )
        subprocess.run(
            ["git", "add", builder.GENERATOR_PATH],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "change renderer"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        try:
            builder.verify_protected_publication_lineage(publication)
        except builder.InventoryError as exc:
            assert str(exc) == "post_publication_protected_generator_delta"
        else:
            raise AssertionError("post-publication renderer change was accepted")


def test_failed_render_keeps_the_existing_bundle_intact(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    output = tmp_path / "bundle"
    builder.build(SOURCE, output)
    before = {name: (output / name).read_bytes() for name in builder.BUNDLE_FILENAMES}
    with mock.patch.object(
        builder.pd.DataFrame,
        "to_parquet",
        side_effect=RuntimeError("injected parquet failure"),
    ):
        try:
            builder.build(SOURCE, output)
        except RuntimeError as exc:
            assert "injected parquet failure" in str(exc)
        else:
            raise AssertionError("injected render failure was not propagated")
    assert before == {
        name: (output / name).read_bytes() for name in builder.BUNDLE_FILENAMES
    }
    assert not list(tmp_path.glob(".bundle.stage-*"))
    assert not list(tmp_path.glob(".bundle.backup-*"))


def test_successful_rebuild_replaces_an_authenticated_bundle(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    output = tmp_path / "authenticated-bundle"
    builder.build(SOURCE, output)
    stale = output / "README.md"
    stale.write_bytes(b"reviewed-old-bundle\n")
    builder.build(SOURCE, output)
    assert stale.read_bytes() != b"reviewed-old-bundle\n"
    assert {path.name for path in output.iterdir()} == builder.BUNDLE_FILENAMES


def test_post_commit_backup_cleanup_failure_is_reported(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    output = tmp_path / "cleanup-bundle"
    builder.build(SOURCE, output)
    (output / "README.md").write_bytes(b"reviewed-old-bundle\n")
    real_rmtree = builder.shutil.rmtree

    def fail_backup_cleanup(path, *args, **kwargs):
        if ".backup-" in Path(path).name:
            raise OSError("injected backup cleanup hold")
        return real_rmtree(path, *args, **kwargs)

    warning = io.StringIO()
    with mock.patch.object(
        builder.shutil, "rmtree", side_effect=fail_backup_cleanup
    ), contextlib.redirect_stderr(warning):
        builder.build(SOURCE, output)
    assert (output / "summary.json").is_file()
    assert "publication succeeded but backup cleanup failed" in warning.getvalue()
    backups = list(tmp_path.glob(".cleanup-bundle.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "README.md").read_bytes() == b"reviewed-old-bundle\n"
    real_rmtree(backups[0])


def test_generated_destination_symlink_is_rejected(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    output = tmp_path / "symlink-bundle"
    build(SOURCE, output)
    external = tmp_path / "external.txt"
    external.write_bytes(b"outside-must-not-change\n")
    try:
        (output / "README.md").unlink()
        (output / "README.md").symlink_to(external)
    except OSError:
        return
    try:
        build(SOURCE, output)
    except InventoryError as exc:
        assert str(exc) == "staged_bundle_symlink:README.md"
    else:
        raise AssertionError("generated destination symlink was accepted")
    assert external.read_bytes() == b"outside-must-not-change\n"


def test_cli_output_directory_symlink_is_rejected(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    external = tmp_path / "external-bundle"
    external.mkdir()
    sentinel = external / "README.md"
    sentinel.write_bytes(b"outside-must-not-change\n")
    output = tmp_path / "symlink-bundle"
    try:
        output.symlink_to(external, target_is_directory=True)
    except OSError:
        return
    with mock.patch.object(
        sys,
        "argv",
        [
            "build_p0_4_artifact_inventory.py",
            "--source",
            str(SOURCE),
            "--output-dir",
            str(output),
        ],
    ):
        try:
            builder.main()
        except builder.InventoryError as exc:
            assert str(exc) == "output_directory_symlink_rejected"
        else:
            raise AssertionError("CLI output-directory symlink was accepted")
    assert sentinel.read_bytes() == b"outside-must-not-change\n"
    assert sorted(path.name for path in external.iterdir()) == ["README.md"]


def test_output_destination_cannot_contain_repository() -> None:
    from tools import build_p0_4_artifact_inventory as builder

    for output in (ROOT, ROOT.parent):
        try:
            builder.build(SOURCE, output)
        except builder.InventoryError as exc:
            assert str(exc) == "output_contains_repository"
        else:
            raise AssertionError(f"repository-containing output was accepted: {output}")
    for output in (ROOT / "docs", ROOT / "tools", ROOT / "new-p0-4-bundle"):
        try:
            builder.validate_output_destination(output)
        except builder.InventoryError as exc:
            assert str(exc) == "in_repository_output_not_canonical"
        else:
            raise AssertionError(f"unrelated in-repository output was accepted: {output}")
    builder.validate_output_destination(INVENTORY)
    try:
        builder.build(SOURCE, INVENTORY)
    except builder.InventoryError as exc:
        assert str(exc) == "canonical_output_requires_live_head_verification"
    else:
        raise AssertionError("canonical bundle rebuild skipped live-head verification")


def test_canonical_output_preserves_untracked_entries(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    repo = tmp_path / "repo"
    output = repo / "docs" / "run287_p0_4_artifact_inventory"
    output.mkdir(parents=True)
    for name in builder.BUNDLE_FILENAMES:
        (output / name).write_bytes(b"fixture\n")
    sentinel = output / "user-notes.txt"
    sentinel.write_bytes(b"user-owned-untracked-bytes\n")
    with (
        mock.patch.object(builder, "ROOT", repo),
        mock.patch.object(builder, "DEFAULT_OUTPUT", output),
    ):
        try:
            builder.validate_output_destination(output)
        except builder.InventoryError as exc:
            assert str(exc) == "canonical_output_not_dedicated:user-notes.txt"
        else:
            raise AssertionError("canonical output accepted an untracked user file")
    assert sentinel.read_bytes() == b"user-owned-untracked-bytes\n"
    assert {path.name for path in output.iterdir()} == (
        builder.BUNDLE_FILENAMES | {"user-notes.txt"}
    )


def test_existing_external_output_must_be_a_dedicated_bundle(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    output = tmp_path / "unrelated-directory"
    output.mkdir()
    sentinel = output / "unrelated.txt"
    sentinel.write_bytes(b"outside-must-not-change\n")
    try:
        builder.build(SOURCE, output)
    except builder.InventoryError as exc:
        assert str(exc) == "external_output_not_dedicated:unrelated.txt"
    else:
        raise AssertionError("existing external non-bundle directory was accepted")
    assert sentinel.read_bytes() == b"outside-must-not-change\n"
    assert sorted(path.name for path in output.iterdir()) == ["unrelated.txt"]
    assert not list(tmp_path.glob(".unrelated-directory.stage-*"))
    assert not list(tmp_path.glob(".unrelated-directory.backup-*"))

    malformed = tmp_path / "malformed-bundle"
    builder.build(SOURCE, malformed)
    (malformed / "README.md").unlink()
    (malformed / "README.md").mkdir()
    try:
        builder.validate_output_destination(malformed)
    except builder.InventoryError as exc:
        assert str(exc) == "external_output_has_non_file_entries:README.md"
    else:
        raise AssertionError("external bundle with a directory entry was accepted")

    partial = tmp_path / "partial-bundle"
    partial.mkdir()
    partial_sentinel = partial / "README.md"
    partial_sentinel.write_bytes(b"another-project\n")
    try:
        builder.validate_output_destination(partial)
    except builder.InventoryError as exc:
        assert str(exc).startswith("external_output_bundle_incomplete:")
    else:
        raise AssertionError("partial name-only bundle was accepted")
    assert partial_sentinel.read_bytes() == b"another-project\n"

    unauthenticated = tmp_path / "unauthenticated-bundle"
    builder.build(SOURCE, unauthenticated)
    summary = json.loads((unauthenticated / "summary.json").read_text(encoding="utf-8"))
    summary["source_snapshot_sha256"] = "0" * 64
    (unauthenticated / "summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )
    try:
        builder.validate_output_destination(unauthenticated)
    except builder.InventoryError as exc:
        assert str(exc) == "external_output_bundle_authentication_failed"
    else:
        raise AssertionError("unauthenticated complete bundle was accepted")


def test_safety_authority_flags_fail_closed(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    for field in (
        "live_trading_enabled",
        "production_activation_allowed",
        "target_order_ledger_mutation",
        "model_promotion",
    ):
        payload = source()
        payload["safety"][field] = True
        invalid = tmp_path / f"invalid-{field}.json"
        invalid.write_text(json.dumps(payload), encoding="utf-8")
        try:
            build(invalid, tmp_path / f"output-{field}")
        except InventoryError as exc:
            assert str(exc) == f"source_claims_authority:{field}"
        else:
            raise AssertionError(f"unsafe authority flag was not rejected: {field}")


def test_required_fixed_target_aliases_cannot_be_omitted(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    object_id = "artifact.drive.operating-main-target-book"
    payload = source()
    payload["artifacts"] = [
        row for row in payload["artifacts"] if row["object_id"] != object_id
    ]
    payload["latest_to_immutable"] = [
        row for row in payload["latest_to_immutable"] if row["object_id"] != object_id
    ]
    invalid = tmp_path / "missing-target.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(invalid, tmp_path / "output")
    except InventoryError as exc:
        assert str(exc) == f"required_fixed_alias_object_missing:{object_id}"
    else:
        raise AssertionError("missing official target alias was not rejected")

    archive_id = "artifact.drive.paper-risk-outcome-archive"
    payload = source()
    payload["artifacts"] = [
        row for row in payload["artifacts"] if row["object_id"] != archive_id
    ]
    payload["latest_to_immutable"] = [
        row
        for row in payload["latest_to_immutable"]
        if row["object_id"] != archive_id
    ]
    missing_archive = tmp_path / "missing-archive.json"
    missing_archive.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_archive, tmp_path / "missing-archive-output")
    except InventoryError as exc:
        assert str(exc) == f"required_mutable_archive_missing:{archive_id}"
    else:
        raise AssertionError("missing official paper archive was not rejected")

    feature_id = "ds.us.features.latest-recommendations"
    payload = source()
    payload["datasets"] = [
        row for row in payload["datasets"] if row["object_id"] != feature_id
    ]
    payload["latest_to_immutable"] = [
        row
        for row in payload["latest_to_immutable"]
        if row["object_id"] != feature_id
    ]
    missing_feature = tmp_path / "missing-feature.json"
    missing_feature.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_feature, tmp_path / "missing-feature-output")
    except InventoryError as exc:
        assert str(exc) == f"required_feature_alias_missing:{feature_id}"
    else:
        raise AssertionError("missing censused feature file was not rejected")

    macro_cache_id = "ds.us.macro.operational-cache"
    payload = source()
    payload["datasets"] = [
        row for row in payload["datasets"] if row["object_id"] != macro_cache_id
    ]
    payload["latest_to_immutable"] = [
        row
        for row in payload["latest_to_immutable"]
        if row["object_id"] != macro_cache_id
    ]
    missing_macro_cache = tmp_path / "missing-macro-cache.json"
    missing_macro_cache.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_macro_cache, tmp_path / "missing-macro-cache-output")
    except InventoryError as exc:
        assert str(exc) == f"required_operational_cache_missing:{macro_cache_id}"
    else:
        raise AssertionError("missing operational macro cache was not rejected")

    price_cache_ids = {
        "ds.us.prices.replay-cache",
        "ds.us.prices.replay-cache-manifest",
    }
    payload = source()
    payload["datasets"] = [
        row for row in payload["datasets"] if row["object_id"] not in price_cache_ids
    ]
    payload["latest_to_immutable"] = [
        row
        for row in payload["latest_to_immutable"]
        if row["object_id"] not in price_cache_ids
    ]
    missing_price_cache = tmp_path / "missing-price-cache.json"
    missing_price_cache.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_price_cache, tmp_path / "missing-price-cache-output")
    except InventoryError as exc:
        assert str(exc) == (
            "required_operational_cache_missing:ds.us.prices.replay-cache"
        )
    else:
        raise AssertionError("missing operational price cache was not rejected")

    actions_cache_id = "artifact.github.daily-operating-macro-actions-cache"
    payload = source()
    payload["artifacts"] = [
        row for row in payload["artifacts"] if row["object_id"] != actions_cache_id
    ]
    missing_actions_cache = tmp_path / "missing-actions-cache.json"
    missing_actions_cache.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_actions_cache, tmp_path / "missing-actions-cache-output")
    except InventoryError as exc:
        assert str(exc) == "github_actions_macro_cache_object_missing"
    else:
        raise AssertionError("missing GitHub Actions macro cache was not rejected")

    recovery_id = "artifact.drive.paper-ledger-recovery-publications"
    payload = source()
    payload["artifacts"] = [
        row for row in payload["artifacts"] if row["object_id"] != recovery_id
    ]
    missing_recovery = tmp_path / "missing-paper-ledger-recovery.json"
    missing_recovery.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_recovery, tmp_path / "missing-paper-ledger-recovery-output")
    except InventoryError as exc:
        assert str(exc) == "paper_ledger_recovery_object_missing"
    else:
        raise AssertionError("missing paper-ledger recovery census was not rejected")

    for object_id in (
        "artifact.github.daily-paper-ledger-actions-cache",
        "artifact.github.daily-paper-continuity-actions-cache",
    ):
        payload = source()
        payload["artifacts"] = [
            row for row in payload["artifacts"] if row["object_id"] != object_id
        ]
        missing_cache = tmp_path / f"missing-{object_id}.json"
        missing_cache.write_text(json.dumps(payload), encoding="utf-8")
        try:
            build(missing_cache, tmp_path / f"missing-{object_id}-output")
        except InventoryError as exc:
            assert str(exc) == f"paper_actions_cache_object_missing:{object_id}"
        else:
            raise AssertionError(f"missing paper cache census was accepted: {object_id}")

    accepted_id = "artifact.drive.accepted-paper-transaction-publication"
    payload = source()
    payload["artifacts"] = [
        row for row in payload["artifacts"] if row["object_id"] != accepted_id
    ]
    missing_accepted = tmp_path / "missing-accepted-paper-transaction.json"
    missing_accepted.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(missing_accepted, tmp_path / "missing-accepted-paper-transaction-output")
    except InventoryError as exc:
        assert str(exc) == "accepted_paper_transaction_object_missing"
    else:
        raise AssertionError("missing accepted paper transaction was not rejected")

    required_provider_objects = {
        "artifact.input.run287-research-static-archive": (
            "research_static_provider_objects_missing"
        ),
        "artifact.github.accepted-paper-transaction-publication": (
            "accepted_github_transaction_object_missing"
        ),
        "artifact.github.accepted-paper-catchup-publication": (
            "catchup_provider_object_missing:accepted"
        ),
        "artifact.github.blocked-paper-catchup-publication": (
            "catchup_provider_object_missing:blocked"
        ),
        "artifact.drive.daily-operating-evidence-publication": (
            "daily_operating_evidence_provider_objects_missing"
        ),
    }
    for object_id, expected_error in required_provider_objects.items():
        payload = source()
        payload["artifacts"] = [
            row for row in payload["artifacts"] if row["object_id"] != object_id
        ]
        missing_provider = tmp_path / f"missing-{object_id}.json"
        missing_provider.write_text(json.dumps(payload), encoding="utf-8")
        try:
            build(missing_provider, tmp_path / f"missing-{object_id}-output")
        except InventoryError as exc:
            assert str(exc) == expected_error
        else:
            raise AssertionError(f"missing provider object was accepted: {object_id}")


def test_alias_map_must_match_object_status_and_evidence(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    payload = source()
    blocked_id = "artifact.drive.operating-main-target-book"
    blocked_map = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == blocked_id
    )
    blocked_map["status"] = "VERIFIED_IMMUTABLE"
    blocked_map["immutable_source"] = ""
    blocked_map["blockers"] = []
    invalid_status = tmp_path / "invalid-map-status.json"
    invalid_status.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(invalid_status, tmp_path / "invalid-map-status-output")
    except InventoryError as exc:
        assert str(exc) == f"latest_map_object_status_mismatch:{blocked_id}"
    else:
        raise AssertionError("map/object status mismatch was not rejected")

    payload = source()
    verified_id = "artifact.repo.latest-r1000-adr-alias"
    verified_map = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == verified_id
    )
    verified_map["immutable_source"] = ""
    invalid_evidence = tmp_path / "invalid-map-evidence.json"
    invalid_evidence.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(invalid_evidence, tmp_path / "invalid-map-evidence-output")
    except InventoryError as exc:
        assert str(exc) == f"latest_map_verified_without_immutable_source:{verified_id}"
    else:
        raise AssertionError("verified map without immutable evidence was not rejected")

    payload = source()
    verified_id = "state.us.paper.main-account"
    verified_map = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == verified_id
    )
    verified_map["immutable_source"] = "invented/noncanonical/head.json"
    mismatched_evidence = tmp_path / "mismatched-map-evidence.json"
    mismatched_evidence.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(mismatched_evidence, tmp_path / "mismatched-map-evidence-output")
    except InventoryError as exc:
        assert str(exc) == f"latest_map_verified_source_mismatch:{verified_id}"
    else:
        raise AssertionError("verified map/object immutable locations were not bound")

    payload = source()
    nonmutable_id = "ds.us.universe.monthly-snapshots"
    nonmutable = next(
        row for row in payload["datasets"] if row["object_id"] == nonmutable_id
    )
    nonmutable["mapping_status"] = "BLOCKED_NO_IMMUTABLE_SOURCE"
    nonmutable["blockers"] = ["not a mutable alias"]
    payload["latest_to_immutable"].append(
        {
            "object_id": nonmutable_id,
            "mutable_alias": "",
            "immutable_source": "",
            "status": "BLOCKED_NO_IMMUTABLE_SOURCE",
            "verification": "invalid synthetic alias",
            "blockers": ["not a mutable alias"],
        }
    )
    nonmutable_map = tmp_path / "nonmutable-map-row.json"
    nonmutable_map.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(nonmutable_map, tmp_path / "nonmutable-map-row-output")
    except InventoryError as exc:
        assert str(exc) == f"latest_map_nonmutable_object:{nonmutable_id}"
    else:
        raise AssertionError("nonmutable object was accepted as a latest alias")

    payload = source()
    mutable_id = "artifact.drive.operating-main-target-book"
    mutable_object = next(
        row for row in payload["artifacts"] if row["object_id"] == mutable_id
    )
    mutable_map = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == mutable_id
    )
    mutable_object["immutable_location"] = "invented/immutable.csv"
    mutable_object["mapping_status"] = "NOT_APPLICABLE"
    mutable_object["blockers"] = []
    mutable_map["status"] = "NOT_APPLICABLE"
    mutable_map["immutable_source"] = "invented/immutable.csv"
    mutable_map["blockers"] = []
    invalid_not_applicable = tmp_path / "invalid-map-not-applicable.json"
    invalid_not_applicable.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(
            invalid_not_applicable,
            tmp_path / "invalid-map-not-applicable-output",
        )
    except InventoryError as exc:
        assert str(exc) == f"mutable_alias_not_applicable:{mutable_id}"
    else:
        raise AssertionError("mutable alias marked not-applicable was not rejected")


def test_compound_aliases_and_wrong_paper_head_namespaces_fail_closed(
    tmp_path: Path,
) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    payload = source()
    object_id = "ds.us.prices.replay-cache"
    row = next(row for row in payload["datasets"] if row["object_id"] == object_id)
    mapping = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == object_id
    )
    row["mutable_alias"] = "cache_prices; cache_prices/replay_price_cache_manifest.json"
    mapping["mutable_alias"] = row["mutable_alias"]
    compound = tmp_path / "compound-alias.json"
    compound.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(compound, tmp_path / "compound-alias-output")
    except InventoryError as exc:
        assert str(exc) == f"mutable_alias_not_atomic:{object_id}"
    else:
        raise AssertionError("compound mutable alias was not rejected")

    payload = source()
    object_id = "ds.us.features.candidate-universe-latest"
    row = next(row for row in payload["datasets"] if row["object_id"] == object_id)
    mapping = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == object_id
    )
    row["mutable_alias"] = "feature_store/*latest*.parquet"
    mapping["mutable_alias"] = row["mutable_alias"]
    wildcard = tmp_path / "wildcard-alias.json"
    wildcard.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wildcard, tmp_path / "wildcard-alias-output")
    except InventoryError as exc:
        assert str(exc) == f"mutable_alias_not_atomic:{object_id}"
    else:
        raise AssertionError("wildcard mutable alias was not rejected")

    payload = source()
    object_id = "ds.us.features.latest-recommendations"
    row = next(row for row in payload["datasets"] if row["object_id"] == object_id)
    mapping = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == object_id
    )
    duplicate = "feature_store/candidate_universe_latest.parquet"
    row["mutable_alias"] = duplicate
    mapping["mutable_alias"] = duplicate
    duplicate_source = tmp_path / "duplicate-alias.json"
    duplicate_source.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(duplicate_source, tmp_path / "duplicate-alias-output")
    except InventoryError as exc:
        assert str(exc) == (
            "duplicate_mutable_alias:feature_store/candidate_universe_latest.parquet:"
            "ds.us.features.candidate-universe-latest:"
            "ds.us.features.latest-recommendations"
        )
    else:
        raise AssertionError("duplicate mutable alias was not rejected")

    payload = source()
    object_id = "state.us.paper.immutable-head"
    row = next(
        row for row in payload["durable_states"] if row["object_id"] == object_id
    )
    row["immutable_location"] = row["immutable_location"].replace(
        "run287_daily_simulated_fill_ledger_heads",
        "run287_daily_simulated_fill_ledger_immutable",
    )
    mapping = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == object_id
    )
    mapping["immutable_source"] = row["immutable_location"]
    wrong_namespace = tmp_path / "wrong-paper-head-namespace.json"
    wrong_namespace.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wrong_namespace, tmp_path / "wrong-paper-head-namespace-output")
    except InventoryError as exc:
        assert str(exc) == f"paper_head_writer_namespace_mismatch:{object_id}"
    else:
        raise AssertionError("paper head writer namespace drift was not rejected")

    payload = source()
    object_id = "state.us.paper.main-account"
    row = next(
        row for row in payload["durable_states"] if row["object_id"] == object_id
    )
    mapping = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == object_id
    )
    mixed_head = "a" * 64
    row["immutable_location"] = re.sub(
        r"(?<=run287_daily_simulated_fill_ledger_heads/)[0-9a-f]{64}",
        mixed_head,
        row["immutable_location"],
    )
    mapping["immutable_source"] = row["immutable_location"]
    mixed = tmp_path / "mixed-paper-heads.json"
    mixed.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(mixed, tmp_path / "mixed-paper-heads-output")
    except InventoryError as exc:
        assert str(exc) == "paper_head_mixed_snapshots"
    else:
        raise AssertionError("mixed paper-head snapshots were not rejected")

    payload = source()
    object_id = "state.us.paper.main-account"
    row = next(
        row for row in payload["durable_states"] if row["object_id"] == object_id
    )
    mapping = next(
        row for row in payload["latest_to_immutable"] if row["object_id"] == object_id
    )
    row["mutable_alias"] = "paper_archive/unrelated/account.json"
    mapping["mutable_alias"] = row["mutable_alias"]
    wrong_alias = tmp_path / "wrong-paper-alias.json"
    wrong_alias.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wrong_alias, tmp_path / "wrong-paper-alias-output")
    except InventoryError as exc:
        assert str(exc) == f"paper_head_mutable_alias_mismatch:{object_id}"
    else:
        raise AssertionError("paper head mutable alias drift was not rejected")


def test_folder_child_manifests_are_pinned_and_bound(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    payload = source()
    object_id = "ds.us.features.latest-recommendations"
    row = next(row for row in payload["datasets"] if row["object_id"] == object_id)
    row["exact_location"] = "gdrive-id:unrelated-file"
    wrong_location = tmp_path / "wrong-feature-location.json"
    wrong_location.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wrong_location, tmp_path / "wrong-feature-location-output")
    except InventoryError as exc:
        assert str(exc) == f"feature_drive_child_location_mismatch:{object_id}"
    else:
        raise AssertionError("feature child outside its censused Drive folder was accepted")

    payload = source()
    row = next(row for row in payload["datasets"] if row["object_id"] == object_id)
    row["file_count"] = 999
    wrong_count = tmp_path / "wrong-feature-file-count.json"
    wrong_count.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wrong_count, tmp_path / "wrong-feature-file-count-output")
    except InventoryError as exc:
        assert str(exc) == f"feature_drive_child_file_count:{object_id}"
    else:
        raise AssertionError("non-file feature child count was accepted")

    payload = source()
    payload["folder_child_manifests"]["cache_macro"]["children"][0][
        "size_bytes"
    ] += 1
    changed_manifest = tmp_path / "changed-macro-manifest.json"
    changed_manifest.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(changed_manifest, tmp_path / "changed-macro-manifest-output")
    except InventoryError as exc:
        assert str(exc) == "folder_child_manifest_sha256_mismatch:cache_macro"
    else:
        raise AssertionError("changed macro child manifest was accepted")

    payload = source()
    macro_id = "ds.us.macro.operational-cache"
    row = next(row for row in payload["datasets"] if row["object_id"] == macro_id)
    row["exact_location"] = "gdrive-id:unrelated-folder"
    wrong_parent = tmp_path / "wrong-macro-parent.json"
    wrong_parent.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wrong_parent, tmp_path / "wrong-macro-parent-output")
    except InventoryError as exc:
        assert str(exc) == "macro_cache_manifest_parent_mismatch"
    else:
        raise AssertionError("macro cache outside its censused Drive folder was accepted")

    payload = source()
    row = next(row for row in payload["datasets"] if row["object_id"] == macro_id)
    row["writer_workflow"] = "daily_operating_selection_refresh.yml"
    false_writer = tmp_path / "false-macro-drive-writer.json"
    false_writer.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(false_writer, tmp_path / "false-macro-drive-writer-output")
    except InventoryError as exc:
        assert str(exc) == "macro_cache_drive_writer_must_be_unresolved"
    else:
        raise AssertionError("restore-only workflow was accepted as Drive writer")

    payload = source()
    actions_cache_id = "artifact.github.daily-operating-macro-actions-cache"
    row = next(
        row for row in payload["artifacts"] if row["object_id"] == actions_cache_id
    )
    row["exact_location"] += " and cache_crisis"
    false_actions_path = tmp_path / "false-actions-cache-path.json"
    false_actions_path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(false_actions_path, tmp_path / "false-actions-cache-path-output")
    except InventoryError as exc:
        assert str(exc) == "github_actions_macro_cache_location_mismatch"
    else:
        raise AssertionError("nonexistent Actions cache path was accepted")


def test_invalid_or_incomplete_sources_fail_closed(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    for field, replacement in (
        ("publication_condition", "always()"),
        ("provider_paths", ["outputs/incomplete-catchup-evidence/"]),
        ("if_no_files_found", "ignore"),
    ):
        payload = source()
        catchup = next(
            row
            for row in payload["artifacts"]
            if row["object_id"]
            == "artifact.github.accepted-paper-catchup-publication"
        )
        catchup[field] = replacement
        drift = tmp_path / f"catchup-{field}-drift.json"
        drift.write_text(json.dumps(payload), encoding="utf-8")
        try:
            build(drift, tmp_path / f"catchup-{field}-drift-output")
        except InventoryError as exc:
            assert str(exc) == "catchup_provider_evidence_mismatch:accepted"
        else:
            raise AssertionError(f"catch-up {field} drift was accepted")

    payload = source()
    full_id = "artifact.github.full-rebuild-official-broker-ledger-publication"
    full_publication = next(
        row for row in payload["artifacts"] if row["object_id"] == full_id
    )
    full_publication["provider_paths"] = full_publication["provider_paths"][:-1]
    incomplete_full = tmp_path / "incomplete-full-rebuild-publication.json"
    incomplete_full.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(incomplete_full, tmp_path / "incomplete-full-rebuild-output")
    except InventoryError as exc:
        assert str(exc) == f"full_rebuild_provider_evidence_mismatch:{full_id}"
    else:
        raise AssertionError("incomplete full-rebuild publication was accepted")

    payload = source()
    payload["datasets"][0]["mapping_status"] = "VERIFIED_IMMUTABLE"
    payload["datasets"][0]["immutable_location"] = ""
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(invalid, tmp_path / "output")
    except InventoryError as exc:
        assert str(exc) == (
            "verified_without_immutable_location:ds.us.universe.historical-auto"
        )
    else:
        raise AssertionError("invalid mutable alias mapping was not rejected")

    for field in ("size_bytes", "row_count", "file_count"):
        for label, invalid_value in (
            ("negative", -1),
            ("fractional", 1.5),
            ("boolean", True),
        ):
            payload = source()
            object_id = payload["datasets"][0]["object_id"]
            payload["datasets"][0][field] = invalid_value
            invalid_count = tmp_path / f"{label}-{field}.json"
            invalid_count.write_text(json.dumps(payload), encoding="utf-8")
            try:
                build(invalid_count, tmp_path / f"{label}-{field}-output")
            except InventoryError as exc:
                assert str(exc) == (
                    f"object_nonnegative_integer_required:{object_id}:{field}"
                )
            else:
                raise AssertionError(f"invalid {field} value was not rejected")

    payload = source()
    unaliased = next(
        row for row in payload["artifacts"] if not row.get("mutable_alias")
    )
    object_id = unaliased["object_id"]
    unaliased["mapping_status"] = "VERIFIED_IMMUTABLE"
    unaliased["immutable_location"] = ""
    for field in ("content_sha256", "manifest_sha256", "data_hash"):
        unaliased[field] = ""
    unbound_verified = tmp_path / "unbound-verified.json"
    unbound_verified.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(unbound_verified, tmp_path / "unbound-verified-output")
    except InventoryError as exc:
        assert str(exc) == f"verified_without_immutable_location:{object_id}"
    else:
        raise AssertionError("unbound VERIFIED_IMMUTABLE object was accepted")

    unaliased["immutable_location"] = "immutable://reviewed-fixture"
    unhashed_verified = tmp_path / "unhashed-verified.json"
    unhashed_verified.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(unhashed_verified, tmp_path / "unhashed-verified-output")
    except InventoryError as exc:
        assert str(exc) == f"verified_without_authenticated_hash:{object_id}"
    else:
        raise AssertionError("unhashed VERIFIED_IMMUTABLE object was accepted")

    payload = source()
    object_id = "state.us.paper.immutable-head"
    provider_drift = next(
        row for row in payload["durable_states"] if row["object_id"] == object_id
    )
    provider_drift["provider"] = "local_unverified"
    wrong_provider = tmp_path / "wrong-verified-provider.json"
    wrong_provider.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(wrong_provider, tmp_path / "wrong-verified-provider-output")
    except InventoryError as exc:
        assert str(exc) == f"provider_storage_kind_mismatch:{object_id}"
    else:
        raise AssertionError("verified object with conflicting provider was accepted")

    payload = source()
    object_id = "ds.us.universe.historical-auto"
    known_storage = next(
        row for row in payload["datasets"] if row["object_id"] == object_id
    )
    known_storage["provider"] = "UNRESOLVED"
    conflicting_provider = tmp_path / "conflicting-known-provider.json"
    conflicting_provider.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(conflicting_provider, tmp_path / "conflicting-known-provider-output")
    except InventoryError as exc:
        assert str(exc) == f"provider_storage_kind_mismatch:{object_id}"
    else:
        raise AssertionError("known storage kind accepted a conflicting provider")

    payload = source()
    object_id = "artifact.github.full-rebuild-collector-actions-cache"
    cache = next(
        row for row in payload["artifacts"] if row["object_id"] == object_id
    )
    cache["provider_paths"] = cache["provider_paths"][:-1]
    incomplete_cache = tmp_path / "incomplete-full-rebuild-cache.json"
    incomplete_cache.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(incomplete_cache, tmp_path / "incomplete-full-rebuild-cache-output")
    except InventoryError as exc:
        assert str(exc) == f"full_rebuild_cache_evidence_mismatch:{object_id}"
    else:
        raise AssertionError("incomplete full-rebuild cache publication was accepted")

    payload = source()
    object_id = "artifact.drive.full-rebuild-research-valid-publication"
    drive_publication = next(
        row for row in payload["artifacts"] if row["object_id"] == object_id
    )
    drive_publication["manifest_published_last"] = False
    incomplete_drive = tmp_path / "incomplete-full-rebuild-drive.json"
    incomplete_drive.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(incomplete_drive, tmp_path / "incomplete-full-rebuild-drive-output")
    except InventoryError as exc:
        assert str(exc) == f"full_rebuild_drive_evidence_mismatch:{object_id}"
    else:
        raise AssertionError("non-transactional full-rebuild Drive publication was accepted")

    payload = source()
    object_id = "ds.us.universe.monthly-snapshots"
    invented = next(
        row for row in payload["datasets"] if row["object_id"] == object_id
    )
    invented["mapping_status"] = "VERIFIED_IMMUTABLE"
    invented["immutable_location"] = "invented://provider/object"
    invented["data_hash"] = "0" * 64
    forged_verified = tmp_path / "forged-provider-evidence.json"
    forged_verified.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(forged_verified, tmp_path / "forged-provider-evidence-output")
    except InventoryError as exc:
        assert str(exc) == f"verified_object_not_registered:{object_id}"
    else:
        raise AssertionError("syntactic digest without provider evidence was accepted")


def main() -> int:
    test_tracked_bundle_exists_and_has_expected_counts()
    with tempfile.TemporaryDirectory() as temp_dir:
        test_generator_is_byte_stable(Path(temp_dir))
    test_registries_and_parquet_cover_every_object_once()
    test_every_mutable_alias_is_verified_or_explicitly_blocked()
    test_distinct_provider_publications_are_complete()
    test_paper_heads_use_the_baseline_writer_namespace()
    test_frozen_repository_inventory_matches_baseline_tree()
    test_latest_global_alias_diverges_in_exactly_scored_file()
    test_latest_r1000_adr_alias_is_exact_tree_match()
    test_pipeline_blocker_is_bound_to_exact_github_runs()
    test_authority_aligns_with_p0_3_census()
    test_failed_source_run_grants_price_replay_only()
    test_macro_freshness_gap_is_evidence_backed()
    test_incomplete_drive_views_fail_closed()
    test_no_secret_values_are_embedded()
    test_rebuild_uses_the_pinned_dependency_contract()
    with tempfile.TemporaryDirectory() as temp_dir:
        test_requirements_publication_is_authenticated(Path(temp_dir))
    test_pr_validation_checkout_supports_pinned_lineage_checks()
    test_output_destination_cannot_contain_repository()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_source_snapshot_is_bound_to_publication_commit(temp_path)
        test_build_parses_only_the_authenticated_source_bytes(temp_path)
        test_dirty_generator_is_rejected(temp_path)
        test_post_publication_protected_changes_are_rejected(temp_path)
        test_protected_generator_allows_only_pin_delta(temp_path)
        test_failed_render_keeps_the_existing_bundle_intact(temp_path)
        test_successful_rebuild_replaces_an_authenticated_bundle(temp_path)
        test_post_commit_backup_cleanup_failure_is_reported(temp_path)
        test_generated_destination_symlink_is_rejected(temp_path)
        test_cli_output_directory_symlink_is_rejected(temp_path)
        test_canonical_output_preserves_untracked_entries(temp_path)
        test_existing_external_output_must_be_a_dedicated_bundle(temp_path)
        test_safety_authority_flags_fail_closed(temp_path)
        test_required_fixed_target_aliases_cannot_be_omitted(temp_path)
        test_alias_map_must_match_object_status_and_evidence(temp_path)
        test_compound_aliases_and_wrong_paper_head_namespaces_fail_closed(temp_path)
        test_folder_child_manifests_are_pinned_and_bound(temp_path)
        test_invalid_or_incomplete_sources_fail_closed(temp_path)
    print("P0-4 artifact inventory smoke: 37 passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
