#!/usr/bin/env python3
"""Static fail-closed checks for the sector-leadership research workflow."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "run287_sector_leadership_research.yml"
)
SCORER = ROOT / "tools" / "run_run287_scored_latest_refresh.py"
DAILY_WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "daily_operating_selection_refresh.yml"
)
CHECKOUT_ACTION = (
    "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
)
SETUP_PYTHON_ACTION = (
    "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"
)
CACHE_RESTORE_ACTION = (
    "actions/cache/restore@0057852bfaa89a56745cba8c7296529d2fc39830"
)
UPLOAD_ARTIFACT_ACTION = (
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
)


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def workflow_payload() -> dict[str, object]:
    payload = yaml.load(workflow_text(), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def daily_workflow_payload() -> dict[str, object]:
    payload = yaml.load(
        DAILY_WORKFLOW.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert isinstance(payload, dict)
    return payload


def named_step(payload: dict[str, object], job: str, name: str) -> dict[str, object]:
    steps = payload["jobs"][job]["steps"]
    matches = [step for step in steps if step.get("name") == name]
    assert len(matches) == 1, (job, name)
    return matches[0]


def bash_executable() -> str:
    discovered = shutil.which("bash")
    if discovered:
        return discovered
    for candidate in (
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise AssertionError("bash executable is required for workflow syntax smoke")


def test_shell_blocks_parse() -> None:
    steps = workflow_payload()["jobs"]["research"]["steps"]
    for step in steps:
        script = step.get("run")
        if not script:
            continue
        checked = subprocess.run(
            [bash_executable(), "-n"],
            input=str(script) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        assert checked.returncode == 0, (
            f"invalid shell in step {step.get('name')}: {checked.stderr}"
        )


def test_triggers_and_permissions_are_read_only() -> None:
    payload = workflow_payload()
    trigger = payload.get("on")
    assert isinstance(trigger, dict)
    assert set(trigger) == {"workflow_run", "workflow_dispatch"}
    workflow_run = trigger["workflow_run"]
    assert workflow_run["workflows"] == ["Daily Operating Selection Refresh"]
    assert workflow_run["types"] == ["completed"]
    assert workflow_run["branches"] == ["master"]
    dispatch = trigger["workflow_dispatch"]
    source = dispatch["inputs"]["source_run_id"]
    assert source["required"] == "true"
    assert source["type"] == "string"
    assert payload.get("permissions") == {
        "contents": "read",
        "actions": "read",
    }
    jobs = payload.get("jobs")
    assert isinstance(jobs, dict) and set(jobs) == {"research"}
    research = jobs["research"]
    assert "environment" not in research


def test_official_actions_are_sha_pinned() -> None:
    payload = workflow_payload()
    expected = {
        "Checkout research implementation": CHECKOUT_ACTION,
        "Set up Python": SETUP_PYTHON_ACTION,
        "Restore exact source price cache": CACHE_RESTORE_ACTION,
        "Upload sector leadership research artifact": UPLOAD_ARTIFACT_ACTION,
    }
    for name, action in expected.items():
        step = named_step(payload, "research", name)
        assert step["uses"] == action
    text = workflow_text()
    for line in (
        f"uses: {CHECKOUT_ACTION} # v4",
        f"uses: {SETUP_PYTHON_ACTION} # v5",
        f"uses: {CACHE_RESTORE_ACTION} # v4",
        f"uses: {UPLOAD_ARTIFACT_ACTION} # v4",
    ):
        assert line in text
    for floating in (
        "actions/checkout@v",
        "actions/setup-python@v",
        "actions/cache/restore@v",
        "actions/upload-artifact@v",
    ):
        assert floating not in text


def test_exact_source_and_artifact_contract_is_present() -> None:
    text = workflow_text()
    required = [
        "github.event.workflow_run.conclusion == 'success'",
        "^[1-9][0-9]*$",
        "daily_operating_selection_refresh.yml",
        'default_branch != "master"',
        "research_workflow_default_branch",
        "research_execution_sha_mismatch",
        "ref: ${{ steps.source.outputs.head_sha }}",
        'run.get("status") != "completed"',
        'run.get("conclusion") != "success"',
        "run_head_repository",
        "workflow_run_event_identity",
        'f"daily-operating-selection-refresh-{run_id}"',
        'f"accepted-paper-transaction-{run_id}"',
        "accepted-paper-catchup-",
        "chronological_catchup_has_no_normal_artifacts",
        "source artifact selection exceeded the bounded page",
        "SOURCE_HEAD_SHA: ${{ steps.source.outputs.head_sha }}",
        'artifact_run.get("head_sha")',
        "max_source_archive_bytes = 64 * 1024**2",
        "GitHub artifact archive size mismatch",
        "GitHub artifact archive digest mismatch",
        "unsafe artifact archive member",
        "daily-operating-selection-${{ runner.os }}-${{ steps.source.outputs.run_id }}",
        "fail-on-cache-miss: true",
        "daily_operating_price_cache_refresh_attempt.json",
        'attempt.get("phase") != "final_operating_universe"',
        'attempt.get("manifest_sha256") != evidence_sha',
        "sha256(restored_manifest_path) != evidence_sha",
        "run287_exact_packet_input_sources/source_bundle.json",
        "run287_exact_packet_upstream/attempts",
        "run287-exact-packet-upstream-orchestrator-v3",
        "READY_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
        "READY_EXISTING_EXACT_PACKET_UPSTREAM_SOURCE_BUNDLE_REVIEW_ONLY",
        "run287-exact-packet-input-source-bundle-v1",
        "READY_EXACT_PACKET_INPUT_SOURCE_PATHS_REVIEW_ONLY",
        "run287-scored-latest-refresh-v4",
        "READY_RESEARCH_SCORED_LATEST",
        "scored_latest/manifest\\.json",
        "scored_latest.csv",
        "provider_price_overlap.parquet",
        "ticker_refresh_audit.csv",
        "build_run287_accepted_publication_manifest.py",
        "--verify-manifest",
        "READY_ACCEPTED_PUBLICATION_REVIEW_ONLY",
        '@refs/heads/master"',
        "accepted_workflow != expected_workflow",
        "--source-workflow \"${{ steps.inputs.outputs.source_workflow }}\"",
        "daily_accepted_manifest",
        "accepted transaction is not a safe normal paper source",
    ]
    missing = [token for token in required if token not in text]
    assert not missing, f"source contract fragments missing: {missing}"
    assert "READY_ACCEPTED_RUN287_PUBLICATION_REVIEW_ONLY" not in text


def test_source_and_prior_archives_are_bounded_and_stream_hashed() -> None:
    text = workflow_text()
    required = [
        'size = artifact.get("size_in_bytes")',
        "size > max_source_archive_bytes",
        '"size_in_bytes": size',
        "archive_size != expected_size",
        'with archive.open("rb") as handle:',
        "handle.read(1024 * 1024)",
        "512 * 1024**2",
        "max_member_bytes = 512 * 1024**2",
        "max_member_bytes = 256 * 1024**2",
        "max_prior_archive_bytes = 16 * 1024**2",
        "size > max_prior_archive_bytes",
        "max_member_bytes = 32 * 1024**2",
        "prior artifact archive size mismatch",
        "len(infos) > 100",
        "64 * 1024**2",
        "info.flag_bits & 1",
        "duplicate normalized artifact archive member",
        "duplicate normalized prior artifact archive member",
        "artifact archive file-directory collision",
        "prior artifact archive file-directory collision",
        'or "\\\\" in info.filename',
        "info.file_size > max_member_bytes",
        "(is_directory and info.file_size != 0)",
    ]
    missing = [token for token in required if token not in text]
    assert not missing, f"archive bound/streaming fragments missing: {missing}"
    assert text.count("size > max_source_archive_bytes") == 2
    assert text.count(
        'str(artifact_run.get("head_sha") or "").lower()'
    ) == 3
    assert text.count('with archive.open("rb") as handle:') == 2
    assert text.count("archive_size != expected_size") == 2
    assert text.count("info.flag_bits & 1") == 2
    assert text.count("info.file_size > max_member_bytes") == 2
    assert text.count("(is_directory and info.file_size != 0)") == 2
    assert "hashlib.sha256(archive.read_bytes())" not in text
    assert "8 * 1024**3" not in text


def test_source_cache_restore_version_matches_upstream_save_exactly() -> None:
    upstream = named_step(
        daily_workflow_payload(),
        "refresh",
        "Save refreshed GitHub cache",
    )
    downstream = named_step(
        workflow_payload(),
        "research",
        "Restore exact source price cache",
    )
    expected = [
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
    ]
    upstream_paths = upstream["with"]["path"].splitlines()
    downstream_paths = downstream["with"]["path"].splitlines()
    assert upstream_paths == expected
    assert downstream_paths == upstream_paths
    assert upstream["with"]["key"] == (
        "daily-operating-selection-${{ runner.os }}-${{ github.run_id }}"
    )
    assert downstream["with"]["key"] == (
        "daily-operating-selection-${{ runner.os }}-"
        "${{ steps.source.outputs.run_id }}"
    )
    assert downstream["with"]["fail-on-cache-miss"] == "true"
    assert "restore-keys" not in downstream["with"]


def test_scored_manifest_false_fields_match_the_v4_producer() -> None:
    text = workflow_text()
    scorer = SCORER.read_text(encoding="utf-8")
    expected_false = (
        "backtest_executed",
        "fullrun_executed",
        "selector_executed",
        "target_book_generation_executed",
        "target_books_mutated",
        "production_activation_allowed",
        "live_trading_enabled",
        "source_cache_mutated",
    )
    scored_start = text.index("scored_false = (")
    scored_end = text.index("if (", scored_start)
    scored_contract = text[scored_start:scored_end]
    for field in expected_false:
        assert f'"{field}"' in scored_contract
        assert f'"{field}": False' in scorer
    assert '"orders_generated"' not in scored_contract
    assert '"orders_generated"' not in scorer


def test_core_invocation_is_hash_pinned_and_research_only() -> None:
    text = workflow_text()
    required = [
        "tools/run_run287_sector_leadership_challenger.py",
        "--accepted-publication-manifest",
        "--expected-accepted-publication-sha256",
        "--scored-latest-manifest",
        "--expected-scored-latest-manifest-sha256",
        "--scored-latest-csv",
        "--expected-scored-latest-csv-sha256",
        "--provider-price-overlap",
        "--expected-provider-price-overlap-sha256",
        "--ticker-refresh-audit",
        "--expected-ticker-refresh-audit-sha256",
        "--benchmark-cache-dir cache_prices",
        "--benchmark-cache-manifest",
        "--expected-benchmark-cache-manifest-sha256",
        "--source-run-id",
        "--source-run-attempt",
        "--source-commit-sha",
        "--source-session-date",
        "--source-workflow",
        "--prior-challenger-artifact",
        "--expected-prior-challenger-sha256",
        "--output-dir outputs/run287_sector_leadership_research",
        "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY",
        'health.get("status") != "READY"',
        "research summary artifact hash set mismatch",
        "research output hash mismatch",
        "full_source_exact_close_coverage_100pct",
        "eligible_exact_close_coverage_100pct",
        "exact_stock_close_coverage_100pct",
        "taxonomy_coverage_at_least_98pct",
        "all_11_canonical_sectors_represented",
        "production_activation_allowed",
        "live_trading_enabled",
        "target_books_mutated",
        "orders_generated",
    ]
    missing = [token for token in required if token not in text]
    assert not missing, f"challenger invocation fragments missing: {missing}"


def test_catchup_emits_verified_observable_skip_artifact() -> None:
    payload = workflow_payload()
    emit = named_step(
        payload,
        "research",
        "Emit observable catch-up research skip",
    )
    verify = named_step(
        payload,
        "research",
        "Verify observable catch-up research skip",
    )
    restore = named_step(payload, "research", "Restore exact source price cache")
    normal = named_step(
        payload,
        "research",
        "Run research-only sector and subsector challenger",
    )
    upload = named_step(
        payload,
        "research",
        "Upload sector leadership research artifact",
    )
    assert emit["if"] == "steps.artifacts.outputs.catchup == 'yes'"
    assert verify["if"] == "steps.artifacts.outputs.catchup == 'yes'"
    assert restore["if"] == "steps.artifacts.outputs.eligible == 'yes'"
    assert normal["if"] == "steps.artifacts.outputs.eligible == 'yes'"
    emit_run = emit["run"]
    for token in (
        "--emit-catchup-skip",
        '--source-run-id "${{ steps.source.outputs.run_id }}"',
        '--source-run-attempt "${{ steps.source.outputs.run_attempt }}"',
        '--source-commit-sha "${{ steps.source.outputs.head_sha }}"',
        "--source-session-date "
        '"${{ steps.artifacts.outputs.catchup_session_date }}"',
        '--source-workflow "${{ steps.source.outputs.workflow_identity }}"',
        "--output-dir outputs/run287_sector_leadership_research",
    ):
        assert token in emit_run
    assert "--accepted-publication-manifest" not in emit_run
    assert "--scored-latest-manifest" not in emit_run
    verify_run = verify["run"]
    for token in (
        "SKIPPED_CATCHUP_NO_PIT_SCORE_SNAPSHOT",
        'health.get("status") != "SKIPPED"',
        'health.get("challenger_status") != status',
        "catchup_has_no_pit_score_snapshot",
        "catch-up research skip artifact hash set mismatch",
        "catch-up research skip safety or source identity mismatch",
        'summary.get("contract_failures")',
        'health.get("contract_failures")',
    ):
        assert token in verify_run
    upload_if = upload["if"]
    assert "steps.artifacts.outputs.eligible == 'yes'" in upload_if
    assert "steps.artifacts.outputs.catchup == 'yes'" in upload_if


def test_prior_state_is_bounded_optional_and_not_backfilled() -> None:
    text = workflow_text()
    required = [
        "Restore newest valid prior READY research artifact",
        "status=success&branch=${DEFAULT_BRANCH}&per_page=100",
        'stamp < cutoff',
        'for PRIOR_RUN_ROW in "${PRIOR_RUN_ROWS[@]}"; do',
        "PRIOR_RUN_HEAD_SHA",
        'artifact_run.get("head_sha")',
        "prior_run_head_sha = sys.argv[3]",
        'str(identity.get("commit_sha") or "").lower()',
        "!= prior_run_head_sha",
        "workflow_head_sha=${PRIOR_FIELDS[4]}",
        "run287-sector-leadership-research-[1-9][0-9]*",
        "prior artifact selection exceeded the bounded page",
        "prior artifact archive digest mismatch",
        "prior artifact exceeds bounded size",
        "has an invalid archive; continue",
        "outputs/run287_sector_leadership_research/summary.json",
        "prior challenger summary is ambiguous",
        "has no research artifact; continue",
        "is not READY; continue",
        "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY",
        "prior READY artifact hash set invalid",
        "prior READY output file contract invalid",
        "prior READY operation health invalid",
        'payload.get("contract_failures") != []',
        'health.get("contract_failures") != []',
        "pandas_market_calendars as mcal",
        "previous NYSE session is unavailable",
        "prior_date != previous_session",
        "CURRENT_SOURCE_WORKFLOW",
        'workflow != os.environ["CURRENT_SOURCE_WORKFLOW"]',
        "PRIOR_FOUND=yes",
        "break",
        'echo "available=no"',
    ]
    missing = [token for token in required if token not in text]
    assert not missing, f"prior-state contract fragments missing: {missing}"
    assert "selected = max(candidates)" not in text
    assert "restore-keys:" not in text
    assert "actions/cache/save" not in text


def test_ready_and_skip_failure_contracts_are_exact() -> None:
    payload = workflow_payload()
    catchup = named_step(
        payload,
        "research",
        "Verify observable catch-up research skip",
    )["run"]
    prior = named_step(
        payload,
        "research",
        "Restore newest valid prior READY research artifact",
    )["run"]
    normal = named_step(
        payload,
        "research",
        "Verify research output contract",
    )["run"]
    catchup_compact = " ".join(catchup.split())
    assert (
        'summary.get("contract_failures") '
        '!= ["catchup_has_no_pit_score_snapshot"]'
    ) in catchup_compact
    assert (
        'health.get("contract_failures") '
        '!= ["catchup_has_no_pit_score_snapshot"]'
    ) in catchup_compact
    assert 'payload.get("contract_failures") != []' in prior
    assert 'health.get("contract_failures") != []' in prior
    assert 'summary.get("contract_failures") != []' in normal
    assert 'health.get("contract_failures") != []' in normal


def test_artifact_scope_and_output_files_are_exact() -> None:
    payload = workflow_payload()
    steps = payload["jobs"]["research"]["steps"]
    uploads = [
        step
        for step in steps
        if step.get("uses") == UPLOAD_ARTIFACT_ACTION
    ]
    assert len(uploads) == 1
    upload = uploads[0]["with"]
    assert upload["name"] == (
        "run287-sector-leadership-research-${{ steps.source.outputs.run_id }}"
    )
    assert upload["path"] == "outputs/run287_sector_leadership_research"
    assert upload["if-no-files-found"] == "error"
    text = workflow_text()
    for filename in (
        "source_manifest.json",
        "feature_manifest.json",
        "experiment_ledger.json",
        "sector_leadership.csv",
        "subsector_leadership.csv",
        "leadership_transitions.csv",
        "candidate_ranking.csv",
        "operation_health.json",
        "summary.json",
        "report.md",
    ):
        assert f'"{filename}"' in text


def test_mutation_and_external_secret_surfaces_are_absent() -> None:
    text = workflow_text().lower()
    banned = [
        "secrets.",
        "environment:",
        "rclone",
        "gdrive",
        "google_service_account",
        "actions/cache/save",
        "git push",
        "gh pr ",
        "gh issue ",
        "repository_dispatch",
        "workflow_call",
        "schedule:",
        "cron:",
        "run_daily_simulated_fill_ledger.py",
        "run287_paper_ledger_integrity.py",
        "build_run287_same_close_target_books.py",
        "build_operating_target_books.py",
        "run_account_order_preview.py",
        "run_broker_trade_journal.py",
        "run_live_trading",
        "fullrun.py",
        "run_full_rebuild",
        "actions/cache/restore@v3",
        "actions/upload-artifact@v3",
    ]
    present = [token for token in banned if token in text]
    assert not present, f"forbidden workflow surfaces present: {present}"


def main() -> int:
    test_shell_blocks_parse()
    test_triggers_and_permissions_are_read_only()
    test_official_actions_are_sha_pinned()
    test_exact_source_and_artifact_contract_is_present()
    test_source_and_prior_archives_are_bounded_and_stream_hashed()
    test_source_cache_restore_version_matches_upstream_save_exactly()
    test_scored_manifest_false_fields_match_the_v4_producer()
    test_core_invocation_is_hash_pinned_and_research_only()
    test_catchup_emits_verified_observable_skip_artifact()
    test_prior_state_is_bounded_optional_and_not_backfilled()
    test_ready_and_skip_failure_contracts_are_exact()
    test_artifact_scope_and_output_files_are_exact()
    test_mutation_and_external_secret_surfaces_are_absent()
    print("run287_sector_leadership_workflow_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
