#!/usr/bin/env python3
"""Static fail-closed checks for the sector-leadership research workflow."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
CHALLENGER = (
    ROOT / "tools" / "run_run287_sector_leadership_challenger.py"
)
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


def test_embedded_python_blocks_compile() -> None:
    steps = workflow_payload()["jobs"]["research"]["steps"]
    observed = 0
    pattern = re.compile(r"<<'PY'\n(.*?)\nPY(?:\n|$)", re.DOTALL)
    for step in steps:
        script = str(step.get("run") or "")
        for index, match in enumerate(pattern.finditer(script), start=1):
            observed += 1
            compile(
                match.group(1),
                f"{step.get('name')}:heredoc:{index}",
                "exec",
            )
    assert observed >= 10


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
    ) == 2
    assert "head_sha.lower() != expected_head_sha" in text
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


def test_blocked_diagnostics_are_verified_uploaded_and_fail_the_job() -> None:
    payload = workflow_payload()
    steps = payload["jobs"]["research"]["steps"]
    challenger = named_step(
        payload,
        "research",
        "Run research-only sector and subsector challenger",
    )
    ready = named_step(
        payload,
        "research",
        "Verify READY research output contract",
    )
    blocked = named_step(
        payload,
        "research",
        "Verify BLOCKED challenger diagnostic bundle",
    )
    upload = named_step(
        payload,
        "research",
        "Upload sector leadership research artifact",
    )
    fail = named_step(
        payload,
        "research",
        "Fail after publishing BLOCKED challenger diagnostics",
    )
    catchup = named_step(
        payload,
        "research",
        "Verify observable catch-up research skip",
    )
    assert challenger["id"] == "challenger"
    assert challenger["continue-on-error"] == "true"
    assert catchup["id"] == "verify_catchup"
    assert ready["id"] == "verify_ready"
    assert blocked["id"] == "verify_blocked"
    assert upload["id"] == "artifact_upload"
    assert "always()" in ready["if"]
    assert "!cancelled()" in ready["if"]
    assert "steps.challenger.outcome == 'success'" in ready["if"]
    assert "always()" in blocked["if"]
    assert "!cancelled()" in blocked["if"]
    assert "steps.challenger.outcome == 'failure'" in blocked["if"]

    blocked_run = blocked["run"]
    required_blocked = [
        "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER",
        "BLOCKED challenger diagnostic file contract mismatch",
        "BLOCKED challenger safety or source identity mismatch",
        "BLOCKED challenger contract failures are absent or invalid",
        "BLOCKED challenger artifact hash set mismatch",
        "BLOCKED challenger artifact hash mismatch",
        'health.get("status") != "BLOCKED"',
        'health.get("challenger_status") != blocked_status',
        'health.get("contract_failures") != failures',
        "failures != sorted(set(failures))",
        "any(gates.get(name) is not False for name in expected_gates)",
    ]
    for gate in (
        "accepted_publication_bound",
        "source_identity_bound",
        "scored_outputs_hash_bound",
        "benchmark_cache_hash_bound",
        "full_source_exact_close_coverage_100pct",
        "eligible_exact_close_coverage_100pct",
        "exact_stock_close_coverage_100pct",
        "taxonomy_coverage_at_least_98pct",
        "all_11_canonical_sectors_represented",
        "exact_spy_qqq_smh",
        "no_future_rows",
        "safe_to_review",
    ):
        required_blocked.append(f'"{gate}"')
    missing = [token for token in required_blocked if token not in blocked_run]
    assert not missing, f"BLOCKED diagnostic fragments missing: {missing}"

    upload_if = upload["if"]
    for token in (
        "always()",
        "!cancelled()",
        "steps.verify_catchup.outcome == 'success'",
        "steps.challenger.outcome == 'success'",
        "steps.verify_ready.outcome == 'success'",
        "steps.challenger.outcome == 'failure'",
        "steps.verify_blocked.outcome == 'success'",
    ):
        assert token in upload_if
    assert "success()" not in upload_if
    fail_if = fail["if"]
    for token in (
        "always()",
        "!cancelled()",
        "steps.challenger.outcome == 'failure'",
        "steps.verify_blocked.outcome == 'success'",
        "steps.artifact_upload.outcome == 'success'",
    ):
        assert token in fail_if
    assert "exit 1" in fail["run"]
    step_names = [step.get("name") for step in steps]
    assert step_names.index(
        "Verify BLOCKED challenger diagnostic bundle"
    ) < step_names.index("Upload sector leadership research artifact")
    assert step_names.index(
        "Upload sector leadership research artifact"
    ) < step_names.index(
        "Fail after publishing BLOCKED challenger diagnostics"
    )


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
        "commit_sha.lower() != prior_run_head_sha",
        "workflow_head_sha=${PRIOR_FIELDS[4]}",
        "run287-sector-leadership-research-[1-9][0-9]*",
        "prior artifact selection exceeded the bounded page",
        "prior artifact archive digest mismatch",
        "prior artifact exceeds bounded size",
        "BLOCKED: prior workflow run metadata invalid",
        "BLOCKED: prior artifact metadata invalid",
        "BLOCKED: prior artifact archive invalid",
        "BLOCKED: prior READY summary invalid",
        "prior challenger summary is missing",
        "PRIOR_RUN_ROWS_FILE",
        "PRIOR_FIELDS_FILE",
        "PRIOR_SUMMARY_FIELDS_FILE",
        'mapfile -t PRIOR_RUN_ROWS < "$PRIOR_RUN_ROWS_FILE"',
        'mapfile -t PRIOR_FIELDS < "$PRIOR_FIELDS_FILE"',
        'mapfile -t PRIOR_SUMMARY_FIELDS < "$PRIOR_SUMMARY_FIELDS_FILE"',
        "outputs/run287_sector_leadership_research/summary.json",
        "prior challenger summary is ambiguous",
        "has no research artifact; continue",
        "has no immediately preceding READY state; continue",
        "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY",
        "SKIPPED_CATCHUP_NO_PIT_SCORE_SNAPSHOT",
        "prior artifact hash set invalid",
        "prior output file contract invalid",
        "prior operation health invalid",
        'payload.get("contract_failures") != expected_failures',
        'health.get("contract_failures") != expected_failures',
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
    prior_run = named_step(
        workflow_payload(),
        "research",
        "Restore newest valid prior READY research artifact",
    )["run"]
    assert "readarray -t PRIOR" not in prior_run
    assert "< <(" not in prior_run
    assert prior_run.count("if ! python") == 4
    assert prior_run.count("mapfile -t PRIOR") == 3
    assert prior_run.count("raise SystemExit(0)") == 3
    assert "has an invalid archive; continue" not in prior_run
    assert "selected = max(candidates)" not in text
    assert "restore-keys:" not in text
    assert "actions/cache/save" not in text


def test_prior_api_and_status_parsers_are_strict() -> None:
    prior = named_step(
        workflow_payload(),
        "research",
        "Restore newest valid prior READY research artifact",
    )["run"]
    required_run_parser = [
        'if not isinstance(payload, dict):',
        'runs = payload.get("workflow_runs")',
        'total_count = payload.get("total_count")',
        "not isinstance(runs, list)",
        "type(total_count) is not int",
        "total_count < len(runs)",
        "if not isinstance(run, dict):",
        "type(run_id) is not int",
        "run_id in seen_run_ids",
        "type(run_attempt) is not int",
        "type(workflow_id) is not int",
        "not isinstance(path_value, str)",
        "not isinstance(created, str)",
        'not created.endswith("Z")',
        'r"[0-9a-fA-F]{40}", head_sha_value',
        "not isinstance(repository, dict)",
        "not isinstance(head_repository, dict)",
        'run["status"] != "completed"',
        'run["conclusion"] != "success"',
        'run["head_branch"] != os.environ["DEFAULT_BRANCH"]',
        "prior workflow run identity invalid",
        "if stamp < cutoff:",
    ]
    missing = [token for token in required_run_parser if token not in prior]
    assert not missing, f"strict prior run parser fragments missing: {missing}"
    assert "if not created:\n                  continue" not in prior

    required_artifact_parser = [
        "prior artifact response must be an object",
        'artifacts = payload.get("artifacts")',
        "not isinstance(artifacts, list)",
        "type(total_count) is not int",
        "total_count != len(artifacts)",
        "if not isinstance(item, dict):",
        "type(artifact_id) is not int",
        "artifact_id in seen_artifact_ids",
        "not isinstance(name, str)",
        "type(expired) is not bool",
        "type(size) is not int",
        "not isinstance(digest_value, str)",
        "not isinstance(artifact_run, dict)",
        "type(artifact_run_id) is not int",
        "type(repository_id) is not int",
        "type(head_repository_id) is not int",
        "repository_id != head_repository_id",
        "head_branch != expected_branch",
        "artifact_run_id != expected_run_id",
        "head_sha.lower() != expected_head_sha",
        'if artifact["expired"] is True:',
        "prior research artifact is ambiguous",
    ]
    missing = [
        token for token in required_artifact_parser if token not in prior
    ]
    assert not missing, f"strict prior artifact parser fragments missing: {missing}"
    assert 'payload.get("artifacts") or []' not in prior

    required_summary_parser = [
        'ready_status = "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY"',
        'catchup_status = "SKIPPED_CATCHUP_NO_PIT_SCORE_SNAPSHOT"',
        "status not in {ready_status, catchup_status}",
        "prior challenger summary status invalid",
        "not isinstance(identity, dict)",
        "commit_sha.lower() != prior_run_head_sha",
        'workflow != os.environ["CURRENT_SOURCE_WORKFLOW"]',
        '"run287-sector-leadership-research-"',
        '"taxonomy_bitemporal_vintage_complete"',
        '"historical_taxonomy_backfill_allowed"',
        'payload.get("review_required") is not True',
        'payload.get("champion_changed") is not False',
        'payload.get("portfolio_transition_allowed") is not False',
        "prior summary session is future",
        "prior artifact exact ten-file contract invalid",
        'if any(path.is_symlink() for path in root.rglob("*")):',
        "not isinstance(records, dict)",
        "not isinstance(record, dict)",
        "type(record.get(\"bytes\")) is not int",
        'else ["catchup_has_no_pit_score_snapshot"]',
        '"run287-sector-leadership-challenger-v1-operation-health"',
        'expected_health_status = (',
        "expected_gate_value = status == ready_status",
        "health.get(\"contract_failures\") != expected_failures",
        "gates.get(name) is not expected_gate_value",
        "if status == catchup_status or prior_date != previous_session:",
    ]
    missing = [
        token for token in required_summary_parser if token not in prior
    ]
    assert not missing, f"strict prior summary parser fragments missing: {missing}"
    assert (
        prior.index(
            "if status == catchup_status or prior_date != previous_session:"
        )
        > prior.index('raise SystemExit("prior operation health invalid")')
    )
    assert (
        'if payload.get("status") '
        '!= "READY_SECTOR_LEADERSHIP_RESEARCH_ONLY"'
        not in prior
    )


def test_prior_api_parsers_execute_fail_closed() -> None:
    prior = named_step(
        workflow_payload(),
        "research",
        "Restore newest valid prior READY research artifact",
    )["run"]
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", prior, re.DOTALL)
    assert len(blocks) == 4
    run_parser, artifact_parser = blocks[:2]
    repository = "wscha231/r1000-quant-engine"
    head_sha = "a" * 40
    environment = {
        **os.environ,
        "SOURCE_CREATED_AT": "2026-07-24T20:00:00Z",
        "DEFAULT_BRANCH": "master",
        "GITHUB_REPOSITORY": repository,
    }
    valid_run = {
        "id": 77,
        "run_attempt": 1,
        "workflow_id": 9,
        "path": ".github/workflows/run287_sector_leadership_research.yml",
        "created_at": "2026-07-23T20:00:00Z",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "success",
        "head_branch": "master",
        "repository": {"full_name": repository},
        "head_repository": {"full_name": repository},
    }
    with tempfile.TemporaryDirectory(
        prefix="run287-prior-api-parser-"
    ) as temporary:
        temporary_root = Path(temporary)
        run_json = temporary_root / "runs.json"
        run_json.write_text(
            json.dumps(
                {"total_count": 1, "workflow_runs": [valid_run]}
            ),
            encoding="utf-8",
        )
        accepted_run = subprocess.run(
            [sys.executable, "-c", run_parser, str(run_json)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert accepted_run.returncode == 0, accepted_run.stderr
        assert accepted_run.stdout == f"77\t{head_sha}\n"

        malformed_run = json.loads(json.dumps(valid_run))
        malformed_run["id"] = True
        run_json.write_text(
            json.dumps(
                {"total_count": 1, "workflow_runs": [malformed_run]}
            ),
            encoding="utf-8",
        )
        rejected_run = subprocess.run(
            [sys.executable, "-c", run_parser, str(run_json)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected_run.returncode != 0
        assert "prior workflow run record metadata invalid" in rejected_run.stderr

        artifact_json = temporary_root / "artifacts.json"
        valid_artifact = {
            "id": 11,
            "name": "run287-sector-leadership-research-123",
            "expired": False,
            "size_in_bytes": 1024,
            "digest": "sha256:" + "b" * 64,
            "workflow_run": {
                "id": 77,
                "repository_id": 1,
                "head_repository_id": 1,
                "head_branch": "master",
                "head_sha": head_sha,
            },
        }
        artifact_json.write_text(
            json.dumps({"total_count": 0, "artifacts": []}),
            encoding="utf-8",
        )
        empty = subprocess.run(
            [
                sys.executable,
                "-c",
                artifact_parser,
                str(artifact_json),
                "77",
                head_sha,
                "master",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert empty.returncode == 0 and empty.stdout == ""

        expired_artifact = json.loads(json.dumps(valid_artifact))
        expired_artifact["expired"] = True
        expired_artifact.pop("size_in_bytes")
        expired_artifact.pop("digest")
        artifact_json.write_text(
            json.dumps(
                {"total_count": 1, "artifacts": [expired_artifact]}
            ),
            encoding="utf-8",
        )
        expired = subprocess.run(
            [
                sys.executable,
                "-c",
                artifact_parser,
                str(artifact_json),
                "77",
                head_sha,
                "master",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert expired.returncode == 0 and expired.stdout == ""

        artifact_json.write_text(
            json.dumps(
                {"total_count": 1, "artifacts": [valid_artifact]}
            ),
            encoding="utf-8",
        )
        accepted_artifact = subprocess.run(
            [
                sys.executable,
                "-c",
                artifact_parser,
                str(artifact_json),
                "77",
                head_sha,
                "master",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert accepted_artifact.returncode == 0, accepted_artifact.stderr
        assert accepted_artifact.stdout.splitlines() == [
            "11",
            "sha256:" + "b" * 64,
            "run287-sector-leadership-research-123",
            "1024",
            head_sha,
        ]

        malformed_artifact = json.loads(json.dumps(valid_artifact))
        malformed_artifact["expired"] = "false"
        artifact_json.write_text(
            json.dumps(
                {"total_count": 1, "artifacts": [malformed_artifact]}
            ),
            encoding="utf-8",
        )
        rejected_artifact = subprocess.run(
            [
                sys.executable,
                "-c",
                artifact_parser,
                str(artifact_json),
                "77",
                head_sha,
                "master",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected_artifact.returncode != 0
        assert "prior artifact record metadata invalid" in rejected_artifact.stderr


def test_prior_summary_parser_accepts_only_verified_catchup_skip() -> None:
    prior = named_step(
        workflow_payload(),
        "research",
        "Restore newest valid prior READY research artifact",
    )["run"]
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", prior, re.DOTALL)
    assert len(blocks) == 4
    summary_parser = blocks[-1]
    commit_sha = "a" * 40
    workflow = (
        "wscha231/r1000-quant-engine/"
        ".github/workflows/daily_operating_selection_refresh.yml"
        "@refs/heads/master"
    )
    with tempfile.TemporaryDirectory(
        prefix="run287-prior-summary-parser-"
    ) as temporary:
        output = Path(temporary) / "artifact"
        emitted = subprocess.run(
            [
                sys.executable,
                str(CHALLENGER),
                "--emit-catchup-skip",
                "--source-run-id",
                "123",
                "--source-run-attempt",
                "1",
                "--source-commit-sha",
                commit_sha,
                "--source-session-date",
                "2026-07-23",
                "--source-workflow",
                workflow,
                "--output-dir",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert emitted.returncode == 0, emitted.stderr
        environment = {
            **os.environ,
            "GITHUB_REPOSITORY": "wscha231/r1000-quant-engine",
            "CURRENT_SESSION_DATE": "2026-07-24",
            "CURRENT_SOURCE_WORKFLOW": workflow,
        }
        accepted = subprocess.run(
            [
                sys.executable,
                "-c",
                summary_parser,
                str(output),
                "run287-sector-leadership-research-123",
                commit_sha,
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert accepted.returncode == 0, accepted.stderr
        assert accepted.stdout == ""

        summary_path = output / "summary.json"
        malformed = json.loads(summary_path.read_text(encoding="utf-8"))
        malformed["status"] = "BLOCKED_SECTOR_LEADERSHIP_CHALLENGER"
        summary_path.write_text(
            json.dumps(malformed, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rejected = subprocess.run(
            [
                sys.executable,
                "-c",
                summary_parser,
                str(output),
                "run287-sector-leadership-research-123",
                commit_sha,
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode != 0
        assert "prior challenger summary status invalid" in rejected.stderr


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
        "Verify READY research output contract",
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
    assert (
        'payload.get("contract_failures") != expected_failures'
        in prior
    )
    assert (
        'health.get("contract_failures") != expected_failures'
        in prior
    )
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
    test_embedded_python_blocks_compile()
    test_triggers_and_permissions_are_read_only()
    test_official_actions_are_sha_pinned()
    test_exact_source_and_artifact_contract_is_present()
    test_source_and_prior_archives_are_bounded_and_stream_hashed()
    test_source_cache_restore_version_matches_upstream_save_exactly()
    test_scored_manifest_false_fields_match_the_v4_producer()
    test_core_invocation_is_hash_pinned_and_research_only()
    test_catchup_emits_verified_observable_skip_artifact()
    test_blocked_diagnostics_are_verified_uploaded_and_fail_the_job()
    test_prior_state_is_bounded_optional_and_not_backfilled()
    test_prior_api_and_status_parsers_are_strict()
    test_prior_api_parsers_execute_fail_closed()
    test_prior_summary_parser_accepts_only_verified_catchup_skip()
    test_ready_and_skip_failure_contracts_are_exact()
    test_artifact_scope_and_output_files_are_exact()
    test_mutation_and_external_secret_surfaces_are_absent()
    print("run287_sector_leadership_workflow_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
