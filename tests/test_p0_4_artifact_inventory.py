from __future__ import annotations

import hashlib
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
FROZEN_PROTECTED_PUBLICATION_COMMIT = "8ebe4a1b9c65b8a2c176d1ee7f63f1c05d2cb97a"
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
        "datasets": 14,
        "models": 4,
        "durable_states": 8,
        "artifacts": 19,
        "artifact_registry_rows": 45,
    }
    assert summary["safety"]["mutations_performed"] == []
    assert summary["safety"]["live_trading_enabled"] is False
    assert summary["safety"]["target_order_ledger_mutation"] is False


def test_generator_is_byte_stable(tmp_path: Path) -> None:
    subprocess.run(
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
        check=True,
        capture_output=True,
        text=True,
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
    assert len(expected) == 45
    frame = pd.read_parquet(INVENTORY / "artifact_registry.parquet")
    assert REQUIRED_COLUMNS == set(frame.columns)
    assert set(frame["object_id"]) == expected
    assert frame["object_id"].is_unique
    assert frame["market"].eq("US").all()
    assert frame["baseline_code_sha"].eq(payload["baseline_code_sha"]).all()
    assert frame["source_snapshot_sha256"].eq(
        "d13b1cc3c3dc46026257fb116f5e4180d0c5bd4165aec9e920d0e9da596279f3"
    ).all()
    assert frame["source_publication_commit"].eq(
        "5b6748fa4bd0ad5454eb2af4986324d724496bf8"
    ).all()
    assert frame["exact_location"].astype(str).str.strip().ne("").all()
    assert frame["rollback_restore"].astype(str).str.strip().ne("").all()
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
    for row in mappings:
        status = row["status"]
        assert status == "VERIFIED_IMMUTABLE" or status.startswith("BLOCKED_")
        if status == "VERIFIED_IMMUTABLE":
            assert row["immutable_source"]
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


def test_frozen_repository_inventory_matches_baseline_tree() -> None:
    payload = source()["repository_inventory"]
    rows = tree_rows("cloud_results/full_rebuild")
    canonical = "\n".join(f"{path}\t{sha}\t{size}" for path, sha, size in rows)
    assert len(rows) == payload["cloud_results_full_rebuild_file_count"] == 10460
    assert sum(size for _path, _sha, size in rows) == payload["cloud_results_full_rebuild_blob_bytes"]
    assert hashlib.sha256(canonical.encode()).hexdigest() == payload[
        "cloud_results_full_rebuild_inventory_sha256"
    ]


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
    assert requirements.splitlines() == [
        "PyYAML==6.0.3",
        "pandas==2.3.3",
        "pyarrow==23.0.1",
    ]
    readme = (INVENTORY / "README.md").read_text(encoding="utf-8")
    assert "python -m venv .venv-p0-4" in readme
    assert "--requirement docs/run287_p0_4_artifact_inventory/requirements.txt" in readme
    assert "tests/test_p0_4_artifact_inventory.py" in readme


def test_source_snapshot_is_bound_to_publication_commit(tmp_path: Path) -> None:
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
        "5b6748fa4bd0ad5454eb2af4986324d724496bf8"
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
    subprocess.run(
        ["git", "add", "protected.txt"], cwd=repo, check=True, capture_output=True
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


def test_failed_render_keeps_the_existing_bundle_intact(tmp_path: Path) -> None:
    from tools import build_p0_4_artifact_inventory as builder

    output = tmp_path / "bundle"
    output.mkdir()
    sentinel = output / "existing.txt"
    sentinel.write_bytes(b"reviewed-old-bundle\n")
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
    assert sentinel.read_bytes() == b"reviewed-old-bundle\n"
    assert sorted(path.name for path in output.iterdir()) == ["existing.txt"]
    assert not list(tmp_path.glob(".bundle.stage-*"))
    assert not list(tmp_path.glob(".bundle.backup-*"))


def test_generated_destination_symlink_is_rejected(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    output = tmp_path / "symlink-bundle"
    output.mkdir()
    external = tmp_path / "external.txt"
    external.write_bytes(b"outside-must-not-change\n")
    try:
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


def test_invalid_or_incomplete_sources_fail_closed(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    payload = source()
    payload["datasets"][0]["mapping_status"] = "VERIFIED_IMMUTABLE"
    payload["datasets"][0]["immutable_location"] = ""
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    try:
        build(invalid, tmp_path / "output")
    except InventoryError as exc:
        assert "mutable_alias_not_bound_or_blocked" in str(exc)
    else:
        raise AssertionError("invalid mutable alias mapping was not rejected")


def main() -> int:
    test_tracked_bundle_exists_and_has_expected_counts()
    with tempfile.TemporaryDirectory() as temp_dir:
        test_generator_is_byte_stable(Path(temp_dir))
    test_registries_and_parquet_cover_every_object_once()
    test_every_mutable_alias_is_verified_or_explicitly_blocked()
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
    test_pr_validation_checkout_supports_pinned_lineage_checks()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_source_snapshot_is_bound_to_publication_commit(temp_path)
        test_dirty_generator_is_rejected(temp_path)
        test_post_publication_protected_changes_are_rejected(temp_path)
        test_failed_render_keeps_the_existing_bundle_intact(temp_path)
        test_generated_destination_symlink_is_rejected(temp_path)
        test_safety_authority_flags_fail_closed(temp_path)
        test_required_fixed_target_aliases_cannot_be_omitted(temp_path)
        test_alias_map_must_match_object_status_and_evidence(temp_path)
        test_invalid_or_incomplete_sources_fail_closed(temp_path)
    print("P0-4 artifact inventory smoke: 24 passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
