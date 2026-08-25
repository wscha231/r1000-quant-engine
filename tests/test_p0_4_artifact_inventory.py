from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "run287_p0_4_artifact_inventory"
SOURCE = INVENTORY / "source_inventory_snapshot.json"
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


def tree_rows(prefix: str) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for line in git("ls-tree", "-r", "-l", "HEAD", prefix).splitlines():
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
        "artifacts": 11,
        "artifact_registry_rows": 37,
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
    assert len(expected) == 37
    frame = pd.read_parquet(INVENTORY / "artifact_registry.parquet")
    assert REQUIRED_COLUMNS == set(frame.columns)
    assert set(frame["object_id"]) == expected
    assert frame["object_id"].is_unique
    assert frame["market"].eq("US").all()
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
        "HEAD:cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv",
        binary=True,
    )
    immutable_blob = git(
        "show",
        "HEAD:cloud_results/full_rebuild/20260624_28074476465_global_alpha_universe/scored_latest.csv",
        binary=True,
    )
    assert hashlib.sha256(current_blob).hexdigest() == "4fe7860960518240e55e6d61492bf823067928b37984ae88022f3bb3d166e25f"
    assert hashlib.sha256(immutable_blob).hexdigest() == "04f79def5db1032ccf228910d62b7f689545be700b13837fc4ee73026f56ed06"


def test_latest_r1000_adr_alias_is_exact_tree_match() -> None:
    assert relative_tree("cloud_results/full_rebuild/latest_r1000+adr") == relative_tree(
        "cloud_results/full_rebuild/20260428_r1000+adr"
    )


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


def test_authority_aligns_with_p0_3_census() -> None:
    census = yaml.safe_load(
        (ROOT / "docs" / "run287_p0_3_authority_census" / "workflow_registry.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert census["official_authority"]["us_target_writer_workflow"] == (
        "daily_operating_selection_refresh.yml"
    )
    assert census["official_authority"]["paper_ledger_consumer_workflow"] == (
        "daily_operating_selection_refresh.yml"
    )
    assert census["official_authority"]["live_broker_writer_workflow"] is None


def test_failed_source_run_grants_price_replay_only() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "daily_operating_selection_refresh.yml"
    ).read_text(encoding="utf-8")
    builder = (ROOT / "tools" / "build_run287_catchup_price_evidence.py").read_text(
        encoding="utf-8"
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
    engine = (ROOT / "tools" / "crisis_state_engine.py").read_text(encoding="utf-8")
    policy = (ROOT / "tools" / "run287_crisis_policy.py").read_text(encoding="utf-8")
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


def test_invalid_or_incomplete_sources_fail_closed(tmp_path: Path) -> None:
    from tools.build_p0_4_artifact_inventory import InventoryError, build

    payload = source()
    payload["datasets"][0]["mapping_status"] = "VERIFIED_IMMUTABLE"
    payload["datasets"][0]["immutable_location"] = ""
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(InventoryError, match="mutable_alias_not_bound_or_blocked"):
        build(invalid, tmp_path / "output")


def main() -> int:
    return int(pytest.main([str(Path(__file__).resolve()), "-q"]))


if __name__ == "__main__":
    raise SystemExit(main())
