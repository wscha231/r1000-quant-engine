#!/usr/bin/env python3
"""Build the frozen, read-only Run287 P0-4 artifact inventory.

The collector inputs are intentionally frozen in the repository.  This tool
does not contact GitHub or Google Drive.  It renders to an ephemeral sibling
directory and swaps the complete requested bundle only after every output has
been written.  Live enumeration is a separate, bounded evidence-gathering step;
incomplete provider views must be recorded as blocked in the source snapshot
rather than silently refreshed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "run287_p0_4_artifact_inventory" / "source_inventory_snapshot.json"
DEFAULT_OUTPUT = ROOT / "docs" / "run287_p0_4_artifact_inventory"
SCHEMA_VERSION = "run287-p0-4-inventory-source-v1"
REGISTRY_SCHEMA_VERSION = "run287-p0-4-registry-v1"
FROZEN_SOURCE_PUBLICATION_COMMIT = "302516e5229760477bc9d5b5ddc618bf0b493185"
FROZEN_SOURCE_GIT_BLOB_SHA1 = "c75bde800400b230329f057b0f9b5b2103d5184c"
FROZEN_SOURCE_SHA256 = "3c28008b10e2c3e2d0ce7f603300a544d437474062d86d307369ca31c610e096"
FROZEN_PUBLICATION_COMMIT = "f7fadfa4e7814c6453bf96ebf3a1ff4d39eadfae"
FROZEN_PROTECTED_PUBLICATION_COMMIT = "9c44d1c01457c094d12bf08d386cd73b24c7ca5d"
GENERATOR_PATH = "tools/build_p0_4_artifact_inventory.py"
REQUIREMENTS_PATH = "docs/run287_p0_4_artifact_inventory/requirements.txt"
FROZEN_REQUIREMENTS_SHA256 = (
    "ffc0231ec1e3cb19bd17fdee4d8314c3698b457531ede701381f640c78eb06db"
)
PROTECTED_PUBLICATION_PATHS = (
    ".github/workflows/pr_validation.yml",
    "docs/run287_p0_4_artifact_inventory",
    "tools/run_pr_validation.py",
)
UNBOUND_SOURCE_PUBLICATION = "UNBOUND_CUSTOM_SOURCE"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
PROTECTED_GENERATOR_PIN_RE = re.compile(
    rb'FROZEN_PROTECTED_PUBLICATION_COMMIT = "[0-9a-f]{40}"'
)
OBJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]+$")
ALIAS_STATUSES = {
    "VERIFIED_IMMUTABLE",
    "BLOCKED_DIVERGENT",
    "BLOCKED_NO_IMMUTABLE_SOURCE",
    "BLOCKED_MULTIPLE_WRITERS",
    "NOT_APPLICABLE",
}
PROVIDER_BY_STORAGE_KIND = {
    "external_runtime_dependency": "rclone_google_drive_runtime",
    "frozen_github_actions_run_job_metadata_and_log_excerpts": "github_actions",
    "git_blob": "git_repository",
    "git_tree": "git_repository",
    "github_actions_artifact": "github_actions_artifact",
    "github_actions_artifact_plus_drive_publication": "github_actions_and_google_drive",
    "github_actions_cache": "github_actions_cache",
    "github_actions_metadata": "github_actions",
    "google_drive_expected_folder": "google_drive",
    "google_drive_file": "google_drive",
    "google_drive_file_in_folder": "google_drive",
    "google_drive_file_in_head": "google_drive",
    "google_drive_file_path_reference": "google_drive",
    "google_drive_files": "google_drive",
    "google_drive_folder": "google_drive",
    "google_drive_folder_and_file": "google_drive",
    "google_drive_folder_and_workflow_cache": "google_drive_and_github_actions_cache",
    "google_drive_manifest_last_mutable_publication": "google_drive",
    "google_drive_manifest_last_run_addressed_publication": "google_drive",
    "google_drive_mutable_directory": "google_drive",
    "google_drive_mutable_output": "google_drive",
    "google_drive_run_addressed_accepted_publication": "google_drive",
    "google_drive_run_addressed_best_effort_diagnostics": "google_drive",
    "google_drive_run_addressed_recovery_namespace": "google_drive",
    "local_worktree": "local_filesystem",
    "sha256_pinned_zip_input": "provider_independent_hash_pinned_input",
    "workflow_output_and_google_drive_file": "github_actions_and_google_drive",
}
PROVIDER_OVERRIDES_BY_STORAGE_KIND = {
    "git_tree": {"git_tree_at_baseline"},
    "github_actions_artifact_plus_drive_publication": {
        "github_artifact_plus_drive_accepted_head"
    },
    "google_drive_file": {"google_drive_file"},
    "google_drive_file_in_head": {"google_drive_accepted_head_child"},
    "google_drive_folder": {"google_drive_accepted_head"},
}
GENERATED_FILENAMES = {
    "README.md",
    "summary.json",
    "dataset_registry.yaml",
    "model_registry.yaml",
    "artifact_registry.parquet",
    "durable_state_registry.yaml",
    "latest_to_immutable_map.yaml",
    "migration_map.md",
}
BUNDLE_FILENAMES = GENERATED_FILENAMES | {
    "source_inventory_snapshot.json",
    "requirements.txt",
}
VERIFIED_OBJECT_EVIDENCE = {
    "state.us.paper.immutable-head": {
        "provider": "google_drive_accepted_head",
        "storage_kind": "google_drive_folder",
        "exact_location": "gdrive-id:1ZBfSgjBFl0oRtQkS-eSleEOT2podcXz1",
        "immutable_location": (
            "paper_archive/run287_daily_simulated_fill_ledger_heads/"
            "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7"
        ),
        "hash_field": "data_hash",
        "hash_value": "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7",
    },
    "state.us.paper.accepted-publication": {
        "provider": "google_drive_file",
        "storage_kind": "google_drive_file",
        "exact_location": "gdrive-id:1MiAcwCj_TAYBa16Q8bN2hCmny6VqXnnr",
        "immutable_location": (
            "paper_archive/run287_daily_simulated_fill_ledger_heads/"
            "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7/"
            "accepted_publication.json"
        ),
        "hash_field": "content_sha256",
        "hash_value": "1f2941e71e4590bf1e0fc5912d65ce54d364a379f0d5bf2370e54276d8a07b5d",
    },
    "state.us.paper.main-account": {
        "provider": "google_drive_accepted_head_child",
        "storage_kind": "google_drive_file_in_head",
        "exact_location": (
            "paper_archive/run287_daily_simulated_fill_ledger/main/"
            "account_state_latest.json"
        ),
        "immutable_location": (
            "paper_archive/run287_daily_simulated_fill_ledger_heads/"
            "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7/"
            "main/account_state_latest.json"
        ),
        "hash_field": "data_hash",
        "hash_value": "f959556ef266765b21380c025831de9df020ad9d411a4284d7afa95cc678e6d8",
    },
    "state.us.paper.concentrated-account": {
        "provider": "google_drive_accepted_head_child",
        "storage_kind": "google_drive_file_in_head",
        "exact_location": (
            "paper_archive/run287_daily_simulated_fill_ledger/concentrated/"
            "account_state_latest.json"
        ),
        "immutable_location": (
            "paper_archive/run287_daily_simulated_fill_ledger_heads/"
            "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7/"
            "concentrated/account_state_latest.json"
        ),
        "hash_field": "data_hash",
        "hash_value": "8253abe8b949be5d7e1d4e304c07cc1459b6e7fb2b6c20a95daf70af6bcc1ff6",
    },
    "state.us.paper.main-ledger-manifest": {
        "provider": "google_drive_accepted_head_child",
        "storage_kind": "google_drive_file_in_head",
        "exact_location": "paper_archive/run287_daily_simulated_fill_ledger/main/manifest.json",
        "immutable_location": (
            "paper_archive/run287_daily_simulated_fill_ledger_heads/"
            "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7/"
            "main/manifest.json"
        ),
        "hash_field": "manifest_sha256",
        "hash_value": "43f348b7a44c2f0212865cc318225e4b75b4cef9b76ccc0ff52fe19cd15f41a1",
    },
    "state.us.paper.concentrated-ledger-manifest": {
        "provider": "google_drive_accepted_head_child",
        "storage_kind": "google_drive_file_in_head",
        "exact_location": (
            "paper_archive/run287_daily_simulated_fill_ledger/concentrated/manifest.json"
        ),
        "immutable_location": (
            "paper_archive/run287_daily_simulated_fill_ledger_heads/"
            "65fa6f5b4b12729811b72a90661fc744320826dfe868ec6da2632768b1ec02a7/"
            "concentrated/manifest.json"
        ),
        "hash_field": "manifest_sha256",
        "hash_value": "78fc4887bc50c0782f1b1935bb033e588f4f9e65c0f5a37686e3f086c188f453",
    },
    "artifact.repo.full-rebuild-history": {
        "provider": "git_tree_at_baseline",
        "storage_kind": "git_tree",
        "exact_location": "cloud_results/full_rebuild",
        "immutable_location": "Git commit 0f34de9a2747059b7bb808cb070a86261e119f95",
        "hash_field": "manifest_sha256",
        "hash_value": "d6628a71d3e1066afc5afbb92a3368c1ed9b0aaca076cc91459bb3afd06b1ac1",
    },
    "artifact.repo.latest-r1000-adr-alias": {
        "provider": "git_tree_at_baseline",
        "storage_kind": "git_tree",
        "exact_location": "cloud_results/full_rebuild/latest_r1000+adr",
        "immutable_location": "cloud_results/full_rebuild/20260428_r1000+adr",
        "hash_field": "manifest_sha256",
        "hash_value": "a8e75bc778087efdfbb3dd7d84cfbafde2efaf216e3c3503ca2a9bca497db9da",
    },
    "artifact.drive.paper-price-evidence": {
        "provider": "github_artifact_plus_drive_accepted_head",
        "storage_kind": "github_actions_artifact_plus_drive_publication",
        "exact_location": "github-run:30146363501/artifact:8616372163",
        "immutable_location": (
            "paper immutable head replay_price_evidence/2026-07-24 plus pinned "
            "GitHub artifact digest"
        ),
        "hash_field": "content_sha256",
        "hash_value": "fb04a523cdcb38110ed4ebf2a8d61c05506e95109bf77da77e5d98f70226eba7",
        "source_artifact_hash": (
            "fb04a523cdcb38110ed4ebf2a8d61c05506e95109bf77da77e5d98f70226eba7"
        ),
    },
}
SAFETY_FALSE_FIELDS = (
    "live_trading_enabled",
    "production_activation_allowed",
    "target_order_ledger_mutation",
    "model_promotion",
)
REQUIRED_FIXED_ALIAS_OBJECTS = {
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
REQUIRED_MUTABLE_ARCHIVE_OBJECTS = {
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
REQUIRED_DURABLE_ALIAS_OBJECTS = {
    "state.us.paper.immutable-head": (
        "paper_archive/run287_daily_simulated_fill_ledger/"
    ),
    "state.us.risk-outcome.accepted-heads": (
        "paper_archive/run287_risk_outcome_accepted_heads/"
    ),
}
REQUIRED_OPERATIONAL_CACHE_ALIAS_OBJECTS = {
    "ds.us.prices.replay-cache": "cache_prices",
    "ds.us.prices.replay-cache-manifest": (
        "cache_prices/replay_price_cache_manifest.json"
    ),
    "ds.us.macro.operational-cache": "cache_macro",
}
REQUIRED_FEATURE_ALIAS_OBJECTS = {
    "ds.us.features.candidate-universe-latest": (
        "feature_store/candidate_universe_latest.parquet"
    ),
    "ds.us.features.latest-recommendations": (
        "feature_store/latest_recommendations.parquet"
    ),
    "ds.us.features.scored-oos-partial": "feature_store/scored_oos_partial.parquet",
    "ds.us.features.scored-oos-latest": "feature_store/scored_oos_latest.parquet",
    "ds.us.features.feature-store-latest": (
        "feature_store/feature_store_latest.parquet"
    ),
    "ds.us.features.universe-monthly-latest": (
        "feature_store/universe_monthly_latest.parquet"
    ),
    "ds.us.features.macro-regime-latest": (
        "feature_store/macro_regime_latest.parquet"
    ),
    "ds.us.features.live-event-alert-latest": (
        "feature_store/live_event_alert_latest.parquet"
    ),
    "ds.us.features.fund-panel-latest": "feature_store/fund_panel_latest.parquet",
}
FEATURE_DRIVE_CENSUS_OBJECT = "ds.us.features.drive-latest-family"
PINNED_FOLDER_CHILD_MANIFEST_SHA256 = {
    "feature_store": (
        "c478b3dc09c4a9b8a3f2eb940fd83af965bae5a051ce780df3d7f4ae8bce59d4"
    ),
    "cache_macro": (
        "96db5506b8b3f5b5eeebf5c49ce5ceff39a53b91e84710901cc82adaa24d92d1"
    ),
}
REQUIRED_GITHUB_ACTIONS_CACHE_OBJECT = (
    "artifact.github.daily-operating-macro-actions-cache"
)
OFFICIAL_GITHUB_ACTIONS_CACHE_PATHS = (
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
OFFICIAL_GITHUB_ACTIONS_CACHE_LOCATION = (
    ".github/workflows/daily_operating_selection_refresh.yml Save refreshed "
    "GitHub cache actions/cache/save@v4 paths: "
    + "; ".join(OFFICIAL_GITHUB_ACTIONS_CACHE_PATHS)
)
REQUIRED_LEDGER_RECOVERY_OBJECT = (
    "artifact.drive.paper-ledger-recovery-publications"
)
OFFICIAL_LEDGER_RECOVERY_LOCATION = (
    "gdrive-root:1qcRMJCxDXsca5SmHFUu30yMAZdRLaxPA/paper_archive/recovery/"
    "${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
)
OFFICIAL_DAILY_PAPER_LEDGER_CACHE_PATHS = (
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
)
OFFICIAL_DAILY_PAPER_LEDGER_CACHE_LOCATION = (
    ".github/workflows/daily_operating_selection_refresh.yml Save validated "
    "forward paper state cache actions/cache/save@v4 key daily-paper-ledger-"
    "${{ runner.os }}-${{ github.run_id }}-${{ github.run_attempt }} paths: "
    + "; ".join(OFFICIAL_DAILY_PAPER_LEDGER_CACHE_PATHS)
)
OFFICIAL_DAILY_PAPER_CONTINUITY_CACHE_PATHS = (
    "outputs/daily_simulated_fill_ledger",
    "outputs/run287_paper_immutable_head_bundles",
)
OFFICIAL_DAILY_PAPER_CONTINUITY_CACHE_LOCATION = (
    ".github/workflows/daily_operating_selection_refresh.yml Save validated "
    "cross-mode paper continuity cache actions/cache/save@v4 key "
    "daily-paper-continuity-v1-${{ runner.os }}-${{ github.run_id }}-"
    "${{ github.run_attempt }} paths: "
    + "; ".join(OFFICIAL_DAILY_PAPER_CONTINUITY_CACHE_PATHS)
)
REQUIRED_PAPER_ACTIONS_CACHE_OBJECTS = {
    "artifact.github.daily-paper-ledger-actions-cache": (
        OFFICIAL_DAILY_PAPER_LEDGER_CACHE_LOCATION,
        OFFICIAL_DAILY_PAPER_LEDGER_CACHE_PATHS,
        "daily-paper-ledger-${{ runner.os }}-${{ github.run_id }}-"
        "${{ github.run_attempt }}",
    ),
    "artifact.github.daily-paper-continuity-actions-cache": (
        OFFICIAL_DAILY_PAPER_CONTINUITY_CACHE_LOCATION,
        OFFICIAL_DAILY_PAPER_CONTINUITY_CACHE_PATHS,
        "daily-paper-continuity-v1-${{ runner.os }}-${{ github.run_id }}-"
        "${{ github.run_attempt }}",
    ),
}
REQUIRED_ACCEPTED_PAPER_TRANSACTION_OBJECT = (
    "artifact.drive.accepted-paper-transaction-publication"
)
RESEARCH_STATIC_SHA256 = (
    "66ca4b6a6a61cb7e9a3a47e2f6d26aa42f30a9b96a25d07699c6cdeb8faf1d84"
)
RESEARCH_STATIC_PATH = "run287_static_archive/run287_exact_static_archive_v1.zip"
RESEARCH_STATIC_CACHE_KEY = (
    "run287-research-static-${{ runner.os }}-66ca4b6a6a61cb7e-v1"
)
RESEARCH_STATIC_DRIVE_LOCATION = (
    "gdrive-root:1qcRMJCxDXsca5SmHFUu30yMAZdRLaxPA/"
    "research_static/run287_exact_static_archive_v1.zip"
)
REQUIRED_RESEARCH_STATIC_OBJECTS = {
    "archive": "artifact.input.run287-research-static-archive",
    "drive": "artifact.drive.run287-research-static-archive",
    "cache": "artifact.github.run287-research-static-actions-cache",
}
REQUIRED_ACCEPTED_GITHUB_TRANSACTION_OBJECT = (
    "artifact.github.accepted-paper-transaction-publication"
)
REQUIRED_DAILY_OPERATING_EVIDENCE_OBJECTS = {
    "github": "artifact.github.daily-operating-evidence-publication",
    "drive": "artifact.drive.daily-operating-evidence-publication",
}
REQUIRED_CATCHUP_ARTIFACT_OBJECTS = {
    "accepted": {
        "object_id": "artifact.github.accepted-paper-catchup-publication",
        "step_name": "Upload accepted chronological catch-up artifact",
        "artifact_name": (
            "accepted-paper-catchup-${{ env.LAST_NYSE_SESSION_DATE }}-"
            "${{ github.run_id }}"
        ),
        "condition": (
            "success() && steps.market.outputs.ready == 'yes' && "
            "steps.market.outputs.catchup_mode == 'yes' && "
            "steps.paper_transaction.outcome == 'success' && "
            "steps.paper_integrity.outcome == 'success' && "
            "steps.paper_persist.outcome == 'success' && "
            "steps.default_head_publication_gate.outcome == 'success'"
        ),
        "if_no_files_found": "error",
        "write_authority": (
            "GITHUB_ARTIFACT_NONCANONICAL_CATCHUP_EVIDENCE_"
            "NO_DRIVE_LEDGER_OR_ACCEPTANCE_AUTHORITY"
        ),
    },
    "blocked": {
        "object_id": "artifact.github.blocked-paper-catchup-publication",
        "step_name": "Upload chronological catch-up diagnostics",
        "artifact_name": (
            "blocked-paper-catchup-${{ env.LAST_NYSE_SESSION_DATE }}-"
            "${{ github.run_id }}"
        ),
        "condition": (
            "always() && steps.market.outputs.ready == 'yes' && "
            "steps.market.outputs.catchup_mode == 'yes' && "
            "(steps.paper_persist.outcome != 'success' || "
            "steps.default_head_publication_gate.outcome != 'success')"
        ),
        "if_no_files_found": "warn",
        "write_authority": (
            "GITHUB_ARTIFACT_BLOCKED_CATCHUP_DIAGNOSTICS_ONLY_"
            "NO_DRIVE_LEDGER_OR_ACCEPTANCE_AUTHORITY"
        ),
    },
}
OFFICIAL_DAILY_OPERATING_DRIVE_LOCATION = (
    "gdrive-root:1qcRMJCxDXsca5SmHFUu30yMAZdRLaxPA/research_runs/"
    "${SAFE_BRANCH}/${GITHUB_RUN_ID}/daily_operating_selection_refresh/"
)
OFFICIAL_ACCEPTED_PAPER_TRANSACTION_LOCATION = (
    "gdrive-root:1qcRMJCxDXsca5SmHFUu30yMAZdRLaxPA/research_runs/"
    "${SAFE_BRANCH}/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
    "accepted_paper_transaction/"
)
OFFICIAL_TARGET_WORKFLOW = ".github/workflows/daily_operating_selection_refresh.yml"
OFFICIAL_PAPER_HEAD_ROOT = (
    "paper_archive/run287_daily_simulated_fill_ledger_heads"
)
OFFICIAL_PAPER_MUTABLE_ROOT = "paper_archive/run287_daily_simulated_fill_ledger/"
PAPER_HEAD_EXPECTED_SUFFIXES = {
    "state.us.paper.immutable-head": "",
    "state.us.paper.accepted-publication": "accepted_publication.json",
    "state.us.paper.main-account": "main/account_state_latest.json",
    "state.us.paper.concentrated-account": "concentrated/account_state_latest.json",
    "state.us.paper.main-ledger-manifest": "main/manifest.json",
    "state.us.paper.concentrated-ledger-manifest": "concentrated/manifest.json",
}
PAPER_HEAD_BOUND_OBJECTS = set(PAPER_HEAD_EXPECTED_SUFFIXES)
PINNED_PUBLICATION_FILE_SHA256 = {
    ".github/workflows/pr_validation.yml": (
        "cbefba4c7362b3ca7c14e058d1e95831ff06c18fb85341e24245ae61c61bd17f"
    )
}
RISK_OUTCOME_FAILED_STEP = "Restore verified risk-outcome accepted head"
RISK_OUTCOME_SKIPPED_STEPS = {
    26: "Build operating target books",
    34: "Run transactional paper ledger and same-close selector",
    46: "Persist validated forward paper ledger state",
}
FULL_REBUILD_WORKFLOW = ".github/workflows/full_rebuild_manual.yml"
REQUIRED_FULL_REBUILD_ARTIFACTS = {
    "artifact.github.full-rebuild-user-operating-minimal-publication": (
        "Upload artifact (user operating minimal)"
    ),
    "artifact.github.full-rebuild-official-broker-ledger-publication": (
        "Upload artifact (official broker-ledger evidence)"
    ),
    "artifact.github.full-rebuild-research-full-publication": (
        "Upload artifact (research full diagnostics)"
    ),
}
REQUIRED_FULL_REBUILD_CACHES = {
    "artifact.github.full-rebuild-collector-actions-cache": {
        "step_name": "Restore collector cache",
        "cache_key": (
            "collector-cache-${{ inputs.cache_key_suffix }}-"
            "${{ runner.os }}-${{ github.run_id }}"
        ),
        "restore_keys": [
            "collector-cache-${{ inputs.cache_key_suffix }}-${{ runner.os }}-",
            "collector-cache-${{ runner.os }}-",
        ],
        "write_authority": (
            "GITHUB_ACTIONS_CACHE_ONLY_NOT_CANONICAL_INPUT_OUTPUT_OR_"
            "ACCEPTED_STATE_AUTHORITY"
        ),
    },
    "artifact.github.full-rebuild-engine-actions-cache": {
        "step_name": "Restore engine cache",
        "cache_key": (
            "engine-cache-${{ inputs.cache_key_suffix }}-"
            "${{ runner.os }}-${{ github.run_id }}"
        ),
        "restore_keys": [
            "engine-cache-${{ inputs.cache_key_suffix }}-${{ runner.os }}-",
            "engine-cache-${{ runner.os }}-",
        ],
        "write_authority": (
            "GITHUB_ACTIONS_CACHE_ONLY_NOT_CANONICAL_MODEL_OUTPUT_OR_"
            "ACCEPTED_STATE_AUTHORITY"
        ),
    },
}
REQUIRED_FULL_REBUILD_DRIVE_PUBLICATIONS = {
    "artifact.drive.full-rebuild-production-valid-publication": {
        "storage_kind": "google_drive_manifest_last_mutable_publication",
        "exact_location": "gdrive:outputs or gdrive:${GDRIVE_FOLDER_NAME}/outputs",
        "destination_templates": [
            "gdrive:outputs",
            "gdrive:${GDRIVE_FOLDER_NAME}/outputs",
        ],
        "publication_condition": (
            "BRANCH_NAME == master && VALID_PRIMARY_OUTPUTS == yes && "
            "gdrive_sync_mode != off"
        ),
        "write_authority": (
            "VALID_MASTER_FULL_REBUILD_OUTPUTS_ONLY_NOT_DAILY_TARGET_LEDGER_"
            "ACCEPTANCE_OR_LIVE_AUTHORITY"
        ),
        "mapping_status": "BLOCKED_NO_IMMUTABLE_SOURCE",
    },
    "artifact.drive.full-rebuild-research-valid-publication": {
        "storage_kind": "google_drive_manifest_last_run_addressed_publication",
        "exact_location": (
            "gdrive:research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/outputs or "
            "gdrive:${GDRIVE_FOLDER_NAME}/research_runs/${SAFE_BRANCH}/"
            "${GITHUB_RUN_ID}/outputs"
        ),
        "destination_templates": [
            "gdrive:research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}/outputs",
            (
                "gdrive:${GDRIVE_FOLDER_NAME}/research_runs/${SAFE_BRANCH}/"
                "${GITHUB_RUN_ID}/outputs"
            ),
        ],
        "publication_condition": (
            "BRANCH_NAME != master && VALID_PRIMARY_OUTPUTS == yes && "
            "gdrive_sync_mode != off"
        ),
        "write_authority": (
            "RUN_ADDRESSED_RESEARCH_EVIDENCE_ONLY_NO_PRODUCTION_ACCEPTANCE_"
            "PROMOTION_OR_LIVE_AUTHORITY"
        ),
        "mapping_status": "NOT_APPLICABLE",
    },
    "artifact.drive.full-rebuild-production-failed-publication": {
        "storage_kind": "google_drive_manifest_last_run_addressed_publication",
        "exact_location": (
            "gdrive:failed_runs/${GITHUB_RUN_ID}/outputs or "
            "gdrive:${GDRIVE_FOLDER_NAME}/failed_runs/${GITHUB_RUN_ID}/outputs"
        ),
        "destination_templates": [
            "gdrive:failed_runs/${GITHUB_RUN_ID}/outputs",
            "gdrive:${GDRIVE_FOLDER_NAME}/failed_runs/${GITHUB_RUN_ID}/outputs",
        ],
        "publication_condition": (
            "BRANCH_NAME == master && VALID_PRIMARY_OUTPUTS == no && "
            "gdrive_sync_mode != off"
        ),
        "write_authority": (
            "FAILED_RUN_DIAGNOSTICS_ONLY_NO_CANONICAL_OUTPUT_ACCEPTANCE_"
            "TARGET_LEDGER_OR_LIVE_AUTHORITY"
        ),
        "mapping_status": "NOT_APPLICABLE",
    },
    "artifact.drive.full-rebuild-research-failed-publication": {
        "storage_kind": "google_drive_manifest_last_run_addressed_publication",
        "exact_location": (
            "gdrive:research_runs/${SAFE_BRANCH}/failed_runs/${GITHUB_RUN_ID}/"
            "outputs or gdrive:${GDRIVE_FOLDER_NAME}/research_runs/"
            "${SAFE_BRANCH}/failed_runs/${GITHUB_RUN_ID}/outputs"
        ),
        "destination_templates": [
            (
                "gdrive:research_runs/${SAFE_BRANCH}/failed_runs/"
                "${GITHUB_RUN_ID}/outputs"
            ),
            (
                "gdrive:${GDRIVE_FOLDER_NAME}/research_runs/${SAFE_BRANCH}/"
                "failed_runs/${GITHUB_RUN_ID}/outputs"
            ),
        ],
        "publication_condition": (
            "BRANCH_NAME != master && VALID_PRIMARY_OUTPUTS == no && "
            "gdrive_sync_mode != off"
        ),
        "write_authority": (
            "FAILED_RESEARCH_DIAGNOSTICS_ONLY_NO_PRODUCTION_ACCEPTANCE_"
            "PROMOTION_OR_LIVE_AUTHORITY"
        ),
        "mapping_status": "NOT_APPLICABLE",
    },
}
REQUIRED_OBJECT_FIELDS = {
    "object_id",
    "schema_version",
    "market",
    "logical_role",
    "producer",
    "provider",
    "storage_kind",
    "exact_location",
    "immutable_location",
    "mutable_alias",
    "as_of",
    "available_from",
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
}
ARTIFACT_COLUMNS = [
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
]


class InventoryError(ValueError):
    """Stable fail-closed inventory validation error."""


def canonical_source_bytes(value: bytes) -> bytes:
    return value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def verify_frozen_source_publication(source_bytes: bytes) -> None:
    relative_source = DEFAULT_SOURCE.relative_to(ROOT).as_posix()
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            FROZEN_SOURCE_PUBLICATION_COMMIT,
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise InventoryError("frozen_source_publication_is_not_head_ancestor")
    try:
        blob_sha = subprocess.check_output(
            [
                "git",
                "rev-parse",
                f"{FROZEN_SOURCE_PUBLICATION_COMMIT}:{relative_source}",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        ).strip()
        publication_bytes = subprocess.check_output(
            [
                "git",
                "show",
                f"{FROZEN_SOURCE_PUBLICATION_COMMIT}:{relative_source}",
            ],
            cwd=ROOT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError("frozen_source_publication_unavailable") from exc
    if blob_sha != FROZEN_SOURCE_GIT_BLOB_SHA1:
        raise InventoryError("frozen_source_publication_blob_mismatch")
    if hashlib.sha256(publication_bytes).hexdigest() != FROZEN_SOURCE_SHA256:
        raise InventoryError("frozen_source_publication_sha256_mismatch")
    if canonical_source_bytes(source_bytes) != publication_bytes:
        raise InventoryError("canonical_source_differs_from_frozen_publication")


def parse_source(source_bytes: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_bytes)
    except Exception as exc:
        raise InventoryError(f"source_invalid_json:{type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise InventoryError("source_not_object")
    return payload


def nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def canonical_folder_child_manifest(
    name: str, manifest: Any
) -> tuple[bytes, list[dict[str, Any]]]:
    if not isinstance(manifest, dict):
        raise InventoryError(f"folder_child_manifest_missing:{name}")
    parent = manifest.get("parent_exact_location")
    children = manifest.get("children")
    if not nonblank(parent) or not isinstance(children, list) or not children:
        raise InventoryError(f"folder_child_manifest_invalid:{name}")
    normalized: list[dict[str, Any]] = []
    titles: set[str] = set()
    ids: set[str] = set()
    for child in children:
        if not isinstance(child, dict):
            raise InventoryError(f"folder_child_manifest_child_invalid:{name}")
        normalized_child = {
            "title": child.get("title"),
            "id": child.get("id"),
            "size_bytes": child.get("size_bytes"),
            "modified_time": child.get("modified_time"),
        }
        if not all(
            nonblank(normalized_child[field])
            for field in ("title", "id", "modified_time")
        ) or not isinstance(normalized_child["size_bytes"], int):
            raise InventoryError(f"folder_child_manifest_child_invalid:{name}")
        if normalized_child["size_bytes"] < 0:
            raise InventoryError(f"folder_child_manifest_child_invalid:{name}")
        if normalized_child["title"] in titles or normalized_child["id"] in ids:
            raise InventoryError(f"folder_child_manifest_duplicate:{name}")
        titles.add(normalized_child["title"])
        ids.add(normalized_child["id"])
        normalized.append(normalized_child)
    normalized.sort(key=lambda row: row["title"])
    canonical = json.dumps(
        {"parent_exact_location": parent, "children": normalized},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return canonical, normalized


def validate_hash(value: Any, *, field: str, allow_blank: bool = True) -> None:
    if value in (None, "") and allow_blank:
        return
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise InventoryError(f"invalid_sha256:{field}")


def validate_object(row: dict[str, Any], *, object_class: str) -> None:
    missing = sorted(REQUIRED_OBJECT_FIELDS - set(row))
    if missing:
        raise InventoryError(
            f"object_missing_fields:{object_class}:{row.get('object_id')}:{','.join(missing)}"
        )
    object_id = str(row.get("object_id") or "")
    if not OBJECT_ID_RE.fullmatch(object_id):
        raise InventoryError(f"object_id_invalid:{object_id}")
    if row.get("market") != "US":
        raise InventoryError(f"market_not_us:{object_id}")
    for field in (
        "schema_version",
        "logical_role",
        "producer",
        "provider",
        "storage_kind",
        "exact_location",
        "write_authority",
        "pit_classification",
        "survivorship_classification",
        "corporate_action_classification",
        "license_classification",
        "secret_pii_classification",
        "retention_classification",
        "rollback_restore",
        "mapping_status",
        "discovery_status",
    ):
        if not nonblank(row.get(field)):
            raise InventoryError(f"object_blank_field:{object_id}:{field}")
    for field in (
        "config_hash",
        "data_hash",
        "universe_hash",
        "content_sha256",
        "manifest_sha256",
    ):
        validate_hash(row.get(field), field=f"{object_id}.{field}")
    for field in ("size_bytes", "row_count", "file_count"):
        value = row.get(field)
        if value in (None, ""):
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise InventoryError(
                f"object_nonnegative_integer_required:{object_id}:{field}"
            )
    code_sha = row.get("code_sha")
    if code_sha not in (None, "") and (
        not isinstance(code_sha, str) or not SHA1_RE.fullmatch(code_sha)
    ):
        raise InventoryError(f"invalid_code_sha:{object_id}")
    source_hashes = row.get("source_artifact_hashes")
    if not isinstance(source_hashes, list):
        raise InventoryError(f"source_hashes_not_list:{object_id}")
    for index, value in enumerate(source_hashes):
        text = str(value)
        candidate = text.split(":", 1)[1] if text.startswith("sha256:") else text
        if not SHA256_RE.fullmatch(candidate):
            raise InventoryError(f"source_hash_invalid:{object_id}:{index}")
    for field in ("downstream_consumers", "blockers"):
        if not isinstance(row.get(field), list):
            raise InventoryError(f"object_field_not_list:{object_id}:{field}")
    if row.get("mapping_status") not in ALIAS_STATUSES:
        raise InventoryError(f"mapping_status_invalid:{object_id}")
    if row.get("mapping_status") == "VERIFIED_IMMUTABLE":
        if not nonblank(row.get("immutable_location")):
            raise InventoryError(f"verified_without_immutable_location:{object_id}")
        if not any(
            nonblank(row.get(field))
            for field in ("content_sha256", "manifest_sha256", "data_hash")
        ):
            raise InventoryError(f"verified_without_authenticated_hash:{object_id}")
    mutable_alias = row.get("mutable_alias")
    if mutable_alias and (
        not isinstance(mutable_alias, str)
        or ";" in mutable_alias
        or "\n" in mutable_alias
        or "\r" in mutable_alias
        or any(token in mutable_alias for token in ("*", "?", "[", "]"))
    ):
        raise InventoryError(f"mutable_alias_not_atomic:{object_id}")
    if row.get("mutable_alias") and row.get("mapping_status") == "NOT_APPLICABLE":
        raise InventoryError(f"mutable_alias_not_applicable:{object_id}")
    blocked = str(row.get("mapping_status")).startswith("BLOCKED_")
    if blocked and not row.get("blockers"):
        raise InventoryError(f"blocked_without_reason:{object_id}")
    if row.get("mutable_alias") and not (
        row.get("immutable_location") or blocked
    ):
        raise InventoryError(f"mutable_alias_not_bound_or_blocked:{object_id}")
    if (
        row.get("mapping_status") == "VERIFIED_IMMUTABLE"
        and row.get("storage_kind") == "git_tree"
        and row.get("mutable_alias")
        and not row.get("manifest_sha256")
    ):
        raise InventoryError(f"verified_git_tree_without_manifest_sha256:{object_id}")


def validate_registered_verified_evidence(
    object_index: dict[str, dict[str, Any]],
) -> None:
    verified_ids = {
        object_id
        for object_id, row in object_index.items()
        if row.get("mapping_status") == "VERIFIED_IMMUTABLE"
    }
    registered_ids = set(VERIFIED_OBJECT_EVIDENCE)
    unexpected = sorted(verified_ids - registered_ids)
    if unexpected:
        raise InventoryError("verified_object_not_registered:" + ",".join(unexpected))
    missing = sorted(registered_ids - verified_ids)
    if missing:
        raise InventoryError("registered_verified_object_missing:" + ",".join(missing))
    for object_id, evidence in VERIFIED_OBJECT_EVIDENCE.items():
        row = object_index[object_id]
        for field in (
            "provider",
            "storage_kind",
            "exact_location",
            "immutable_location",
        ):
            if row.get(field) != evidence[field]:
                raise InventoryError(
                    f"verified_provider_evidence_mismatch:{object_id}:{field}"
                )
        hash_field = str(evidence["hash_field"])
        if row.get(hash_field) != evidence["hash_value"]:
            raise InventoryError(
                f"verified_provider_evidence_mismatch:{object_id}:{hash_field}"
            )
        source_hash = evidence.get("source_artifact_hash")
        if source_hash is not None and source_hash not in row.get(
            "source_artifact_hashes", []
        ):
            raise InventoryError(
                f"verified_provider_evidence_mismatch:{object_id}:source_artifact_hashes"
            )


def baseline_workflow_text(baseline: str) -> str:
    return baseline_text_file(baseline, OFFICIAL_TARGET_WORKFLOW)


def baseline_text_file(baseline: str, path: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "show", f"{baseline}:{path}"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError("official_target_workflow_not_available_at_baseline") from exc


def baseline_workflow_step(workflow_text: str, name: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(workflow_text)
        steps = [
            step
            for job in document["jobs"].values()
            for step in job.get("steps", [])
        ]
    except Exception as exc:
        raise InventoryError("official_target_workflow_steps_invalid") from exc
    matches = [step for step in steps if isinstance(step, dict) and step.get("name") == name]
    if len(matches) != 1:
        raise InventoryError(f"official_target_workflow_step_count:{name}:{len(matches)}")
    return matches[0]


def workflow_multiline_paths(step: dict[str, Any]) -> list[str]:
    value = step.get("with", {}).get("path")
    if not isinstance(value, str):
        raise InventoryError(f"official_target_workflow_step_paths:{step.get('name')}")
    return [line.strip() for line in value.splitlines() if line.strip()]


def validate_provider_publications(
    object_index: dict[str, dict[str, Any]], workflow_text: str
) -> None:
    archive = object_index.get(REQUIRED_RESEARCH_STATIC_OBJECTS["archive"])
    drive_archive = object_index.get(REQUIRED_RESEARCH_STATIC_OBJECTS["drive"])
    cache_archive = object_index.get(REQUIRED_RESEARCH_STATIC_OBJECTS["cache"])
    if archive is None or drive_archive is None or cache_archive is None:
        raise InventoryError("research_static_provider_objects_missing")
    if (
        archive.get("exact_location") != RESEARCH_STATIC_PATH
        or archive.get("immutable_location") != f"sha256:{RESEARCH_STATIC_SHA256}"
        or archive.get("content_sha256") != RESEARCH_STATIC_SHA256
        or archive.get("mapping_status") != "NOT_APPLICABLE"
    ):
        raise InventoryError("research_static_archive_evidence_mismatch")
    if (
        drive_archive.get("exact_location") != RESEARCH_STATIC_DRIVE_LOCATION
        or drive_archive.get("provider") != "google_drive"
        or drive_archive.get("source_artifact_hashes") != [RESEARCH_STATIC_SHA256]
        or drive_archive.get("write_authority")
        != "DRIVE_WRITER_UNRESOLVED_DAILY_WORKFLOW_READ_ONLY_RESTORE"
    ):
        raise InventoryError("research_static_drive_evidence_mismatch")
    restore_cache = baseline_workflow_step(
        workflow_text, "Restore Run287 research-static archive cache"
    )
    save_cache = baseline_workflow_step(
        workflow_text, "Save Run287 research-static archive cache"
    )
    for step in (restore_cache, save_cache):
        if (
            workflow_multiline_paths(step) != [RESEARCH_STATIC_PATH]
            or step.get("with", {}).get("key") != RESEARCH_STATIC_CACHE_KEY
        ):
            raise InventoryError("research_static_cache_not_in_baseline_workflow")
    if (
        cache_archive.get("provider") != "github_actions_cache"
        or
        cache_archive.get("cache_key") != RESEARCH_STATIC_CACHE_KEY
        or cache_archive.get("provider_paths") != [RESEARCH_STATIC_PATH]
        or cache_archive.get("source_artifact_hashes") != [RESEARCH_STATIC_SHA256]
        or cache_archive.get("write_authority")
        != "GITHUB_ACTIONS_CACHE_ONLY_NOT_CANONICAL_DRIVE_OR_RESEARCH_AUTHORITY"
    ):
        raise InventoryError("research_static_cache_evidence_mismatch")
    for token in (
        "research_static/run287_exact_static_archive_v1.zip",
        f"--expected-archive-sha256 {RESEARCH_STATIC_SHA256}",
    ):
        if token not in workflow_text:
            raise InventoryError("research_static_drive_or_hash_not_in_baseline")

    accepted_github = object_index.get(REQUIRED_ACCEPTED_GITHUB_TRANSACTION_OBJECT)
    if accepted_github is None:
        raise InventoryError("accepted_github_transaction_object_missing")
    accepted_step = baseline_workflow_step(
        workflow_text, "Upload accepted paper transaction artifact"
    )
    accepted_with = accepted_step.get("with", {})
    accepted_paths = workflow_multiline_paths(accepted_step)
    if (
        accepted_with.get("name") != "accepted-paper-transaction-${{ github.run_id }}"
        or accepted_with.get("retention-days") != 45
        or accepted_github.get("provider") != "github_actions_artifact"
        or accepted_github.get("artifact_name") != accepted_with.get("name")
        or accepted_github.get("retention_days") != accepted_with.get("retention-days")
        or accepted_github.get("provider_paths") != accepted_paths
        or accepted_github.get("write_authority")
        != "GITHUB_ARTIFACT_NONCANONICAL_TRANSACTION_EVIDENCE_NO_DRIVE_OR_LEDGER_AUTHORITY"
    ):
        raise InventoryError("accepted_github_transaction_evidence_mismatch")

    for outcome, expected in REQUIRED_CATCHUP_ARTIFACT_OBJECTS.items():
        catchup_object = object_index.get(str(expected["object_id"]))
        if catchup_object is None:
            raise InventoryError(f"catchup_provider_object_missing:{outcome}")
        catchup_step = baseline_workflow_step(
            workflow_text, str(expected["step_name"])
        )
        catchup_with = catchup_step.get("with", {})
        artifact_name = str(expected["artifact_name"])
        if (
            catchup_step.get("if") != expected["condition"]
            or catchup_with.get("name") != artifact_name
            or catchup_with.get("retention-days") != 45
            or catchup_with.get("if-no-files-found")
            != expected["if_no_files_found"]
            or catchup_object.get("provider") != "github_actions_artifact"
            or catchup_object.get("storage_kind") != "github_actions_artifact"
            or catchup_object.get("exact_location")
            != f"github-actions-artifact:{artifact_name}"
            or catchup_object.get("artifact_name") != artifact_name
            or catchup_object.get("publication_condition")
            != expected["condition"]
            or catchup_object.get("retention_days") != 45
            or catchup_object.get("if_no_files_found")
            != expected["if_no_files_found"]
            or catchup_object.get("provider_paths")
            != workflow_multiline_paths(catchup_step)
            or catchup_object.get("write_authority")
            != expected["write_authority"]
            or catchup_object.get("mapping_status") != "NOT_APPLICABLE"
        ):
            raise InventoryError(f"catchup_provider_evidence_mismatch:{outcome}")

    daily_github = object_index.get(REQUIRED_DAILY_OPERATING_EVIDENCE_OBJECTS["github"])
    daily_drive = object_index.get(REQUIRED_DAILY_OPERATING_EVIDENCE_OBJECTS["drive"])
    if daily_github is None or daily_drive is None:
        raise InventoryError("daily_operating_evidence_provider_objects_missing")
    daily_step = baseline_workflow_step(
        workflow_text, "Upload daily operating evidence artifact"
    )
    daily_with = daily_step.get("with", {})
    if (
        daily_with.get("name") != "daily-operating-selection-refresh-${{ github.run_id }}"
        or daily_with.get("retention-days") != 45
        or daily_github.get("provider") != "github_actions_artifact"
        or daily_github.get("artifact_name") != daily_with.get("name")
        or daily_github.get("retention_days") != daily_with.get("retention-days")
        or daily_github.get("provider_paths") != workflow_multiline_paths(daily_step)
        or daily_github.get("write_authority")
        != "DIAGNOSTIC_GITHUB_ARTIFACT_ONLY_NO_TARGET_LEDGER_DRIVE_OR_ACCEPTANCE_AUTHORITY"
    ):
        raise InventoryError("daily_operating_github_evidence_mismatch")
    drive_step = baseline_workflow_step(
        workflow_text, "Sync daily operating artifact to Google Drive"
    )
    drive_script = drive_step.get("run")
    if not isinstance(drive_script, str):
        raise InventoryError("daily_operating_drive_step_script_missing")
    directory_match = re.search(r"^\s*for d in (.+); do\s*$", drive_script, re.MULTILINE)
    file_match = re.search(
        r"^\s*for f in \\\n(?P<body>.*?)^\s*if \[ -s \"\$f\" \]; then\s*$",
        drive_script,
        re.MULTILINE | re.DOTALL,
    )
    if directory_match is None or file_match is None:
        raise InventoryError("daily_operating_drive_path_loop_missing")
    expected_directories = shlex.split(directory_match.group(1))
    file_body = file_match.group("body").replace("\\\n", " ")
    file_body = re.sub(r";\s*do\s*$", "", file_body)
    expected_files = shlex.split(file_body)
    expected_files.append("cache_prices/replay_price_cache_manifest.json")
    if (
        daily_drive.get("exact_location") != OFFICIAL_DAILY_OPERATING_DRIVE_LOCATION
        or daily_drive.get("provider") != "google_drive"
        or daily_drive.get("provider_directories") != expected_directories
        or daily_drive.get("provider_files") != expected_files
        or daily_drive.get("write_authority")
        != "BEST_EFFORT_DIAGNOSTIC_DRIVE_COPY_ONLY_NO_ACCEPTED_TRANSACTION_OR_LEDGER_AUTHORITY"
        or "|| true" not in drive_script
    ):
        raise InventoryError("daily_operating_drive_evidence_mismatch")


def validate_full_rebuild_publications(
    object_index: dict[str, dict[str, Any]], workflow_text: str
) -> None:
    for object_id, step_name in REQUIRED_FULL_REBUILD_ARTIFACTS.items():
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"full_rebuild_provider_object_missing:{object_id}")
        step = baseline_workflow_step(workflow_text, step_name)
        values = step.get("with", {})
        if (
            row.get("provider") != "github_actions_artifact"
            or row.get("storage_kind") != "github_actions_artifact"
            or row.get("artifact_name") != values.get("name")
            or row.get("exact_location")
            != f"github-actions-artifact:{values.get('name')}"
            or row.get("publication_condition") != step.get("if")
            or row.get("retention_days") != values.get("retention-days")
            or row.get("if_no_files_found")
            != values.get("if-no-files-found", "provider_default_warn")
            or row.get("provider_paths") != workflow_multiline_paths(step)
            or row.get("mapping_status") != "NOT_APPLICABLE"
        ):
            raise InventoryError(f"full_rebuild_provider_evidence_mismatch:{object_id}")

    for object_id, expected in REQUIRED_FULL_REBUILD_CACHES.items():
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"full_rebuild_cache_object_missing:{object_id}")
        step = baseline_workflow_step(workflow_text, str(expected["step_name"]))
        values = step.get("with", {})
        restore_keys = values.get("restore-keys")
        if not isinstance(restore_keys, str):
            raise InventoryError(f"full_rebuild_cache_restore_keys_missing:{object_id}")
        normalized_restore_keys = [
            line.strip() for line in restore_keys.splitlines() if line.strip()
        ]
        cache_key = str(expected["cache_key"])
        if (
            step.get("uses") != "actions/cache@v4"
            or values.get("key") != cache_key
            or normalized_restore_keys != expected["restore_keys"]
            or row.get("provider") != "github_actions_cache"
            or row.get("storage_kind") != "github_actions_cache"
            or row.get("exact_location") != f"github-actions-cache:{cache_key}"
            or row.get("cache_key") != cache_key
            or row.get("restore_keys") != expected["restore_keys"]
            or row.get("provider_paths") != workflow_multiline_paths(step)
            or row.get("write_authority") != expected["write_authority"]
            or row.get("mapping_status") != "NOT_APPLICABLE"
        ):
            raise InventoryError(f"full_rebuild_cache_evidence_mismatch:{object_id}")

    sync_step = baseline_workflow_step(
        workflow_text,
        "Sync outputs to user's Google Drive (OAuth preferred, Service Account fallback)",
    )
    sync_script = sync_step.get("run")
    if sync_step.get("if") != "success()" or not isinstance(sync_script, str):
        raise InventoryError("full_rebuild_drive_sync_step_mismatch")
    required_script_tokens = (
        'if [ "$BRANCH_NAME" = "master" ]; then',
        'VALID_PRIMARY_OUTPUTS="no"',
        'VALID_PRIMARY_OUTPUTS="yes"',
        'if [ "$SYNC_MODE" = "off" ]; then',
        "done < outputs/gdrive_sync_files.tsv",
        "--copy-status outputs/gdrive_copy_status.jsonl",
        'rclone copyto outputs/gdrive_sync_manifest.json "$DEST/gdrive_sync_manifest.json"',
    )
    if any(token not in sync_script for token in required_script_tokens):
        raise InventoryError("full_rebuild_drive_sync_script_incomplete")
    if sync_script.count("python tools/build_gdrive_sync_manifest.py") != 2:
        raise InventoryError("full_rebuild_drive_manifest_build_count")
    copy_loop_end = sync_script.index("done < outputs/gdrive_sync_files.tsv")
    manifest_copy = sync_script.index(
        'rclone copyto outputs/gdrive_sync_manifest.json "$DEST/gdrive_sync_manifest.json"'
    )
    if copy_loop_end >= manifest_copy:
        raise InventoryError("full_rebuild_drive_manifest_not_published_last")
    for object_id, expected in REQUIRED_FULL_REBUILD_DRIVE_PUBLICATIONS.items():
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"full_rebuild_drive_object_missing:{object_id}")
        destinations = expected["destination_templates"]
        if any(str(destination) not in sync_script for destination in destinations):
            raise InventoryError(f"full_rebuild_drive_destination_missing:{object_id}")
        if (
            row.get("provider") != "google_drive"
            or row.get("storage_kind") != expected["storage_kind"]
            or row.get("exact_location") != expected["exact_location"]
            or row.get("destination_templates") != destinations
            or row.get("publication_condition") != expected["publication_condition"]
            or row.get("provider_paths_manifest") != "outputs/gdrive_sync_files.tsv"
            or row.get("acceptance_manifest") != "outputs/gdrive_sync_manifest.json"
            or row.get("manifest_published_last") is not True
            or row.get("write_authority") != expected["write_authority"]
            or row.get("mapping_status") != expected["mapping_status"]
        ):
            raise InventoryError(f"full_rebuild_drive_evidence_mismatch:{object_id}")


def validate_failure_evidence(payload: dict[str, Any]) -> None:
    health = payload.get("pipeline_health")
    if not isinstance(health, dict):
        raise InventoryError("pipeline_health_missing")
    run_ids = health.get("daily_operating_recent_run_ids")
    evidence = health.get("daily_operating_failure_evidence")
    if not isinstance(run_ids, list) or not isinstance(evidence, list):
        raise InventoryError("risk_outcome_failure_evidence_missing")
    if [row.get("run_id") for row in evidence if isinstance(row, dict)] != run_ids:
        raise InventoryError("risk_outcome_failure_evidence_run_order")
    if len(evidence) != 3 or len(set(run_ids)) != 3:
        raise InventoryError("risk_outcome_failure_evidence_count")
    for row in evidence:
        if not isinstance(row, dict):
            raise InventoryError("risk_outcome_failure_evidence_not_object")
        run_id = row.get("run_id")
        if not isinstance(run_id, int) or run_id <= 0:
            raise InventoryError("risk_outcome_failure_evidence_run_id")
        if not isinstance(row.get("job_id"), int) or row["job_id"] <= 0:
            raise InventoryError(f"risk_outcome_failure_evidence_job_id:{run_id}")
        if row.get("event") != "schedule" or row.get("conclusion") != "failure":
            raise InventoryError(f"risk_outcome_failure_evidence_run_state:{run_id}")
        if row.get("failed_step") != RISK_OUTCOME_FAILED_STEP:
            raise InventoryError(f"risk_outcome_failure_evidence_step:{run_id}")
        if row.get("failed_step_number") != 19 or row.get("exit_code") != 2:
            raise InventoryError(f"risk_outcome_failure_evidence_exit:{run_id}")
        head_sha = str(row.get("head_sha") or "")
        if not SHA1_RE.fullmatch(head_sha):
            raise InventoryError(f"risk_outcome_failure_evidence_head:{run_id}")
        excerpt = row.get("terminal_excerpt_lines")
        if (
            not isinstance(excerpt, list)
            or len(excerpt) != 2
            or not all(nonblank(line) for line in excerpt)
        ):
            raise InventoryError(f"risk_outcome_failure_evidence_excerpt:{run_id}")
        canonical = ("\n".join(excerpt) + "\n").encode("utf-8")
        if hashlib.sha256(canonical).hexdigest() != row.get(
            "terminal_excerpt_sha256"
        ):
            raise InventoryError(f"risk_outcome_failure_evidence_excerpt_hash:{run_id}")
        skipped = row.get("downstream_skipped_steps")
        if not isinstance(skipped, list):
            raise InventoryError(f"risk_outcome_failure_evidence_skips:{run_id}")
        normalized = {
            item.get("step_number"): (item.get("name"), item.get("conclusion"))
            for item in skipped
            if isinstance(item, dict)
        }
        expected = {
            number: (name, "skipped")
            for number, name in RISK_OUTCOME_SKIPPED_STEPS.items()
        }
        if normalized != expected:
            raise InventoryError(f"risk_outcome_failure_evidence_skips:{run_id}")


def validate_source(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError("source_schema_version")
    if payload.get("market") != "US":
        raise InventoryError("source_market")
    baseline = str(payload.get("baseline_code_sha") or "")
    if not SHA1_RE.fullmatch(baseline):
        raise InventoryError("baseline_code_sha")
    safety = payload.get("safety")
    if not isinstance(safety, dict):
        raise InventoryError("source_safety_missing")
    if safety.get("mutations_performed") != []:
        raise InventoryError("source_claims_mutations")
    for field in SAFETY_FALSE_FIELDS:
        if safety.get(field) is not False:
            raise InventoryError(f"source_claims_authority:{field}")
    defaults = payload.get("object_defaults")
    if not isinstance(defaults, dict):
        raise InventoryError("object_defaults_missing")
    objects_seen: set[str] = set()
    for collection, object_class in (
        ("datasets", "dataset"),
        ("models", "model"),
        ("durable_states", "durable_state"),
        ("artifacts", "artifact"),
    ):
        rows = payload.get(collection)
        if not isinstance(rows, list) or not rows:
            raise InventoryError(f"source_collection_empty:{collection}")
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise InventoryError(f"source_row_not_object:{collection}")
            normalized = {**defaults, **row}
            storage_kind = str(normalized.get("storage_kind") or "")
            canonical_provider = PROVIDER_BY_STORAGE_KIND.get(storage_kind)
            if canonical_provider is not None:
                allowed_providers = {canonical_provider} | (
                    PROVIDER_OVERRIDES_BY_STORAGE_KIND.get(storage_kind, set())
                )
                if "provider" not in row:
                    normalized["provider"] = canonical_provider
                elif row.get("provider") not in allowed_providers:
                    raise InventoryError(
                        f"provider_storage_kind_mismatch:{row.get('object_id')}"
                    )
            validate_object(normalized, object_class=object_class)
            object_id = normalized["object_id"]
            if object_id in objects_seen:
                raise InventoryError(f"duplicate_object_id:{object_id}")
            objects_seen.add(object_id)
            normalized_rows.append(normalized)
        payload[collection] = normalized_rows
    aliases_seen: dict[str, str] = {}
    for collection in ("datasets", "models", "durable_states", "artifacts"):
        for row in payload[collection]:
            alias = str(row.get("mutable_alias") or "")
            if not alias:
                continue
            if alias in aliases_seen:
                raise InventoryError(
                    f"duplicate_mutable_alias:{alias}:{aliases_seen[alias]}:{row['object_id']}"
                )
            aliases_seen[alias] = row["object_id"]
    object_index = {
        row["object_id"]: row
        for collection in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[collection]
    }
    folder_manifests = payload.get("folder_child_manifests")
    if not isinstance(folder_manifests, dict):
        raise InventoryError("folder_child_manifests_missing")
    verified_folder_children: dict[str, list[dict[str, Any]]] = {}
    for name, expected_sha256 in PINNED_FOLDER_CHILD_MANIFEST_SHA256.items():
        manifest = folder_manifests.get(name)
        canonical, children = canonical_folder_child_manifest(name, manifest)
        actual_sha256 = hashlib.sha256(canonical).hexdigest()
        if manifest.get("manifest_sha256") != actual_sha256:
            raise InventoryError(f"folder_child_manifest_sha256_mismatch:{name}")
        if actual_sha256 != expected_sha256:
            raise InventoryError(f"folder_child_manifest_not_pinned:{name}")
        verified_folder_children[name] = children
    aliases = payload.get("latest_to_immutable")
    if not isinstance(aliases, list) or not aliases:
        raise InventoryError("latest_map_empty")
    alias_ids: set[str] = set()
    for row in aliases:
        if not isinstance(row, dict):
            raise InventoryError("latest_map_row_not_object")
        object_id = str(row.get("object_id") or "")
        if object_id not in objects_seen:
            raise InventoryError(f"latest_map_unknown_object:{object_id}")
        if object_id in alias_ids:
            raise InventoryError(f"latest_map_duplicate:{object_id}")
        alias_ids.add(object_id)
        status = row.get("status")
        if status not in ALIAS_STATUSES:
            raise InventoryError(f"latest_map_status:{object_id}")
        if status == "NOT_APPLICABLE":
            raise InventoryError(f"latest_map_mutable_alias_not_applicable:{object_id}")
        object_row = object_index[object_id]
        if not nonblank(object_row.get("mutable_alias")) or not nonblank(
            row.get("mutable_alias")
        ):
            raise InventoryError(f"latest_map_nonmutable_object:{object_id}")
        if row.get("mutable_alias") != object_row.get("mutable_alias"):
            raise InventoryError(f"latest_map_alias_mismatch:{object_id}")
        if status != object_row.get("mapping_status"):
            raise InventoryError(f"latest_map_object_status_mismatch:{object_id}")
        blockers = row.get("blockers")
        if not isinstance(blockers, list):
            raise InventoryError(f"latest_map_blockers_not_list:{object_id}")
        if str(status).startswith("BLOCKED_") and not blockers:
            raise InventoryError(f"latest_map_blocked_without_reason:{object_id}")
        if status == "VERIFIED_IMMUTABLE":
            if not nonblank(row.get("immutable_source")):
                raise InventoryError(
                    f"latest_map_verified_without_immutable_source:{object_id}"
                )
            if row.get("immutable_source") != object_row.get(
                "immutable_location"
            ):
                raise InventoryError(
                    f"latest_map_verified_source_mismatch:{object_id}"
                )
            if blockers:
                raise InventoryError(f"latest_map_verified_with_blockers:{object_id}")
    mutable_ids = {
        row["object_id"]
        for collection in ("datasets", "models", "durable_states", "artifacts")
        for row in payload[collection]
        if row.get("mutable_alias")
    }
    missing_aliases = sorted(mutable_ids - alias_ids)
    if missing_aliases:
        raise InventoryError("latest_map_missing_aliases:" + ",".join(missing_aliases))
    workflow_text = baseline_workflow_text(baseline)
    validate_provider_publications(object_index, workflow_text)
    validate_full_rebuild_publications(
        object_index, baseline_text_file(baseline, FULL_REBUILD_WORKFLOW)
    )
    if OFFICIAL_PAPER_HEAD_ROOT not in workflow_text:
        raise InventoryError("official_paper_head_root_not_in_baseline_workflow")
    paper_heads: set[str] = set()
    paper_prefix = OFFICIAL_PAPER_HEAD_ROOT + "/"
    for object_id, expected_suffix in PAPER_HEAD_EXPECTED_SUFFIXES.items():
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"paper_head_object_missing:{object_id}")
        immutable_location = str(row.get("immutable_location") or "")
        if not immutable_location.startswith(paper_prefix):
            raise InventoryError(f"paper_head_writer_namespace_mismatch:{object_id}")
        relative = immutable_location[len(paper_prefix) :]
        head_sha, separator, suffix = relative.partition("/")
        if not SHA256_RE.fullmatch(head_sha):
            raise InventoryError(f"paper_head_invalid_sha256:{object_id}")
        if (separator and suffix != expected_suffix) or (
            not separator and expected_suffix
        ):
            raise InventoryError(f"paper_head_object_path_mismatch:{object_id}")
        expected_alias = OFFICIAL_PAPER_MUTABLE_ROOT + expected_suffix
        if row.get("mutable_alias") != expected_alias:
            raise InventoryError(f"paper_head_mutable_alias_mismatch:{object_id}")
        paper_heads.add(head_sha)
        if row.get("writer_workflow") != "daily_operating_selection_refresh.yml":
            raise InventoryError(f"paper_head_writer_workflow_mismatch:{object_id}")
    if len(paper_heads) != 1:
        raise InventoryError("paper_head_mixed_snapshots")
    paper_head = next(iter(paper_heads))
    if object_index["state.us.paper.immutable-head"].get("data_hash") != paper_head:
        raise InventoryError("paper_head_root_data_hash_mismatch")
    for object_id, alias in REQUIRED_FIXED_ALIAS_OBJECTS.items():
        if alias not in workflow_text:
            raise InventoryError(f"fixed_alias_not_in_baseline_workflow:{alias}")
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_fixed_alias_object_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_fixed_alias_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_fixed_alias_map_missing:{object_id}")
    for object_id, alias in REQUIRED_MUTABLE_ARCHIVE_OBJECTS.items():
        if alias not in workflow_text:
            raise InventoryError(f"mutable_archive_not_in_baseline_workflow:{alias}")
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_mutable_archive_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_mutable_archive_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_mutable_archive_map_missing:{object_id}")
    for object_id, alias in REQUIRED_DURABLE_ALIAS_OBJECTS.items():
        workflow_archive_entry = alias.removeprefix("paper_archive/")
        if workflow_archive_entry not in workflow_text:
            raise InventoryError(f"durable_alias_not_in_baseline_workflow:{alias}")
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_durable_alias_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_durable_alias_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_durable_alias_map_missing:{object_id}")
    for object_id, alias in REQUIRED_OPERATIONAL_CACHE_ALIAS_OBJECTS.items():
        if alias not in workflow_text:
            raise InventoryError(f"operational_cache_not_in_baseline_workflow:{alias}")
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_operational_cache_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_operational_cache_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_operational_cache_map_missing:{object_id}")
    macro_cache = object_index["ds.us.macro.operational-cache"]
    macro_manifest = folder_manifests["cache_macro"]
    macro_children = verified_folder_children["cache_macro"]
    if macro_cache.get("exact_location") != macro_manifest.get(
        "parent_exact_location"
    ):
        raise InventoryError("macro_cache_manifest_parent_mismatch")
    if macro_cache.get("file_count") != len(macro_children):
        raise InventoryError("macro_cache_manifest_file_count_mismatch")
    if macro_cache.get("size_bytes") != sum(
        row["size_bytes"] for row in macro_children
    ):
        raise InventoryError("macro_cache_manifest_size_mismatch")
    if macro_cache.get("manifest_sha256") != macro_manifest.get("manifest_sha256"):
        raise InventoryError("macro_cache_manifest_object_hash_mismatch")
    if macro_cache.get("writer_workflow") != "UNRESOLVED_LEGACY_DRIVE_WRITER":
        raise InventoryError("macro_cache_drive_writer_must_be_unresolved")
    if macro_cache.get("write_authority") != (
        "DRIVE_WRITER_UNRESOLVED; DAILY_WORKFLOW_READ_ONLY_RESTORE"
    ):
        raise InventoryError("macro_cache_drive_write_authority_mismatch")
    actions_cache = object_index.get(REQUIRED_GITHUB_ACTIONS_CACHE_OBJECT)
    if actions_cache is None:
        raise InventoryError("github_actions_macro_cache_object_missing")
    if actions_cache.get("storage_kind") != "github_actions_cache":
        raise InventoryError("github_actions_macro_cache_storage_mismatch")
    if actions_cache.get("exact_location") != OFFICIAL_GITHUB_ACTIONS_CACHE_LOCATION:
        raise InventoryError("github_actions_macro_cache_location_mismatch")
    if actions_cache.get("writer_workflow") != (
        "daily_operating_selection_refresh.yml"
    ) or actions_cache.get("write_authority") != (
        "GITHUB_ACTIONS_CACHE_ONLY_NOT_DRIVE_WRITER"
    ):
        raise InventoryError("github_actions_macro_cache_authority_mismatch")
    if "actions/cache/save@v4" not in workflow_text or any(
        path not in workflow_text for path in OFFICIAL_GITHUB_ACTIONS_CACHE_PATHS
    ):
        raise InventoryError("github_actions_macro_cache_not_in_baseline_workflow")
    ledger_recovery = object_index.get(REQUIRED_LEDGER_RECOVERY_OBJECT)
    if ledger_recovery is None:
        raise InventoryError("paper_ledger_recovery_object_missing")
    if ledger_recovery.get("exact_location") != OFFICIAL_LEDGER_RECOVERY_LOCATION:
        raise InventoryError("paper_ledger_recovery_location_mismatch")
    if ledger_recovery.get("writer_workflow") != (
        "daily_operating_selection_refresh.yml"
    ) or ledger_recovery.get("mapping_status") != "NOT_APPLICABLE":
        raise InventoryError("paper_ledger_recovery_authority_mismatch")
    for required_path in (
        "paper_archive/recovery/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
        "run287_daily_simulated_fill_ledger",
        "paper_archive/recovery/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/"
        "untrusted_mutable_canonical/",
    ):
        if required_path not in workflow_text:
            raise InventoryError("paper_ledger_recovery_not_in_baseline_workflow")
    for object_id, (
        expected_location,
        expected_paths,
        expected_key,
    ) in REQUIRED_PAPER_ACTIONS_CACHE_OBJECTS.items():
        paper_cache = object_index.get(object_id)
        if paper_cache is None:
            raise InventoryError(f"paper_actions_cache_object_missing:{object_id}")
        if paper_cache.get("storage_kind") != "github_actions_cache":
            raise InventoryError(f"paper_actions_cache_storage_mismatch:{object_id}")
        if paper_cache.get("exact_location") != expected_location:
            raise InventoryError(f"paper_actions_cache_location_mismatch:{object_id}")
        if paper_cache.get("mapping_status") != "NOT_APPLICABLE" or (
            paper_cache.get("write_authority")
            != "GITHUB_ACTIONS_CACHE_ONLY_NOT_CANONICAL_DRIVE_OR_LEDGER_AUTHORITY"
        ):
            raise InventoryError(f"paper_actions_cache_authority_mismatch:{object_id}")
        if expected_key not in workflow_text or any(
            path not in workflow_text for path in expected_paths
        ):
            raise InventoryError(f"paper_actions_cache_not_in_baseline:{object_id}")
    accepted_transaction = object_index.get(
        REQUIRED_ACCEPTED_PAPER_TRANSACTION_OBJECT
    )
    if accepted_transaction is None:
        raise InventoryError("accepted_paper_transaction_object_missing")
    if accepted_transaction.get("exact_location") != (
        OFFICIAL_ACCEPTED_PAPER_TRANSACTION_LOCATION
    ):
        raise InventoryError("accepted_paper_transaction_location_mismatch")
    if accepted_transaction.get("writer_job") != (
        "refresh / Sync accepted paper transaction to Google Drive"
    ) or accepted_transaction.get("mapping_status") != "NOT_APPLICABLE":
        raise InventoryError("accepted_paper_transaction_authority_mismatch")
    accepted_destination = (
        'research_runs/${SAFE_BRANCH}/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}/'
        'accepted_paper_transaction'
    )
    manifest_last_marker = (
        "# Publish the verified manifest last as the remote acceptance marker."
    )
    manifest_copy = (
        'rclone copy outputs/run287_accepted_publication '
        '"$DEST/outputs/run287_accepted_publication/"'
    )
    if not all(
        token in workflow_text
        for token in (accepted_destination, manifest_last_marker, manifest_copy)
    ) or workflow_text.index(manifest_last_marker) > workflow_text.index(
        manifest_copy
    ):
        raise InventoryError("accepted_paper_transaction_not_in_baseline_workflow")
    feature_rows: list[dict[str, Any]] = []
    for object_id, alias in REQUIRED_FEATURE_ALIAS_OBJECTS.items():
        row = object_index.get(object_id)
        if row is None:
            raise InventoryError(f"required_feature_alias_missing:{object_id}")
        if row.get("mutable_alias") != alias:
            raise InventoryError(f"required_feature_alias_mismatch:{object_id}")
        if object_id not in alias_ids:
            raise InventoryError(f"required_feature_alias_map_missing:{object_id}")
        feature_rows.append(row)
    feature_census = object_index.get(FEATURE_DRIVE_CENSUS_OBJECT)
    if feature_census is None:
        raise InventoryError("feature_drive_census_missing")
    feature_manifest = folder_manifests["feature_store"]
    feature_children = verified_folder_children["feature_store"]
    if feature_census.get("exact_location") != feature_manifest.get(
        "parent_exact_location"
    ):
        raise InventoryError("feature_drive_census_parent_mismatch")
    if feature_census.get("file_count") != len(feature_children):
        raise InventoryError("feature_drive_census_file_count_mismatch")
    if len(feature_rows) != len(feature_children):
        raise InventoryError("feature_drive_census_child_count_mismatch")
    child_by_title = {row["title"]: row for row in feature_children}
    for row in feature_rows:
        title = str(row["mutable_alias"]).rsplit("/", 1)[-1]
        child = child_by_title.get(title)
        if child is None:
            raise InventoryError(f"feature_drive_child_missing:{row['object_id']}")
        if row.get("exact_location") != f"gdrive-id:{child['id']}":
            raise InventoryError(
                f"feature_drive_child_location_mismatch:{row['object_id']}"
            )
        if row.get("file_count") != 1:
            raise InventoryError(f"feature_drive_child_file_count:{row['object_id']}")
        if row.get("size_bytes") != child["size_bytes"]:
            raise InventoryError(f"feature_drive_child_size_mismatch:{row['object_id']}")
        if row.get("available_from") != child["modified_time"]:
            raise InventoryError(
                f"feature_drive_child_modified_time_mismatch:{row['object_id']}"
            )
    feature_size = sum(row["size_bytes"] for row in feature_children)
    if feature_census.get("size_bytes") != feature_size:
        raise InventoryError("feature_drive_census_size_mismatch")
    if feature_census.get("manifest_sha256") != feature_manifest.get(
        "manifest_sha256"
    ):
        raise InventoryError("feature_drive_census_manifest_hash_mismatch")
    validate_registered_verified_evidence(object_index)
    validate_failure_evidence(payload)
    if not isinstance(payload.get("migration_items"), list) or not payload["migration_items"]:
        raise InventoryError("migration_items_empty")
    if not isinstance(payload.get("findings"), list) or not payload["findings"]:
        raise InventoryError("findings_empty")


def registry_document(payload: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "source_schema_version": payload["schema_version"],
        "market": "US",
        "baseline_code_sha": payload["baseline_code_sha"],
        "observed_at_utc": payload["observed_at_utc"],
        "source_snapshot_sha256": payload["_source_sha256"],
        "discovery_limits": payload["discovery_limits"],
        key: payload[key],
    }


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    text = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def serialise_cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def artifact_rows(
    payload: dict[str, Any], *, source_publication_commit: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    observed = payload["observed_at_utc"]
    for collection, object_class in (
        ("datasets", "dataset"),
        ("models", "model"),
        ("durable_states", "durable_state"),
        ("artifacts", "artifact"),
    ):
        for source in payload[collection]:
            row = {column: source.get(column, "") for column in ARTIFACT_COLUMNS}
            row["object_class"] = object_class
            row["observed_at_utc"] = observed
            row["baseline_code_sha"] = payload["baseline_code_sha"]
            row["source_snapshot_sha256"] = payload["_source_sha256"]
            row["source_publication_commit"] = source_publication_commit
            rows.append({key: serialise_cell(value) for key, value in row.items()})
    return sorted(rows, key=lambda item: item["object_id"])


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(rows, columns=ARTIFACT_COLUMNS)
    for field in ("size_bytes", "row_count", "file_count"):
        frame[field] = pd.array(frame[field], dtype="Int64")
    frame.to_parquet(
        path,
        index=False,
        engine="pyarrow",
        compression="zstd",
        version="2.6",
    )


def render_migration(payload: dict[str, Any]) -> str:
    lines = [
        "# Run287 P0-4 migration map",
        "",
        f"Frozen at `{payload['observed_at_utc']}` on `{payload['baseline_code_sha']}`.",
        "This is a read-only remediation plan; it grants no workflow dispatch, target/ledger write, promotion, production, or live authority.",
        "",
    ]
    priorities = ("P0", "P1", "P2")
    for priority in priorities:
        lines.extend([f"## {priority}", ""])
        for item in payload["migration_items"]:
            if item.get("priority") != priority:
                continue
            lines.extend(
                [
                    f"### {item['item_id']} — {item['title']}",
                    "",
                    f"- Current state: {item['current_state']}",
                    f"- Required change: {item['required_change']}",
                    f"- Acceptance evidence: {item['acceptance_evidence']}",
                    f"- Safety boundary: {item['safety_boundary']}",
                    f"- Depends on: {', '.join(item.get('depends_on') or ['none'])}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def render_latest_map(payload: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for row in payload["latest_to_immutable"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "schema_version": "run287-p0-4-latest-map-v1",
        "market": "US",
        "baseline_code_sha": payload["baseline_code_sha"],
        "observed_at_utc": payload["observed_at_utc"],
        "source_snapshot_sha256": payload["_source_sha256"],
        "status_counts": dict(sorted(counts.items())),
        "mappings": payload["latest_to_immutable"],
    }


def render_readme(payload: dict[str, Any], row_count: int) -> str:
    health = payload["pipeline_health"]
    lines = [
        "# Run287 P0-4 artifact inventory",
        "",
        f"This is the read-only inventory required by Issue #372, frozen at `{payload['observed_at_utc']}` and bound to `master` `{payload['baseline_code_sha']}`.",
        "",
        "## Outcome",
        "",
        f"- Dataset classes: `{len(payload['datasets'])}`",
        f"- Model objects: `{len(payload['models'])}`",
        f"- Durable-state objects: `{len(payload['durable_states'])}`",
        f"- Infrastructure/artifact objects: `{len(payload['artifacts'])}`",
        f"- Total normalized Parquet rows: `{row_count}`",
        f"- Latest aliases verified: `{sum(1 for row in payload['latest_to_immutable'] if row['status'] == 'VERIFIED_IMMUTABLE')}`",
        f"- Latest aliases blocked: `{sum(1 for row in payload['latest_to_immutable'] if str(row['status']).startswith('BLOCKED_'))}`",
        "",
        "## Current pipeline connection",
        "",
        "```text",
        "SEC / earnings / free prices / macro collectors",
        "                    |",
        "                    v",
        "       Drive caches + mutable manifests",
        "                    |",
        "                    v",
        "         Data Readiness Preflight (green)",
        "                    |",
        "                    v",
        " Daily Operating Selection Refresh (BLOCKED)",
        "                    |",
        "       missing verified risk-outcome parent",
        "                    X",
        "  market snapshot -> target -> paper ledger -> accepted head",
        "```",
        "",
        f"The latest three operating runs `{', '.join(str(x) for x in health['daily_operating_recent_run_ids'])}` all failed at the same step: `{health['daily_operating_failed_step']}`. Collection, readiness, SEC, smart-money, crisis-monitor, and autolearning jobs were green in the latest observed runs; green sidecars do not clear this state-lineage blocker.",
        "",
        "## Highest-impact findings",
        "",
    ]
    for finding in payload["findings"]:
        lines.append(
            f"- **{finding['severity']} {finding['finding_id']}** — {finding['summary']}"
        )
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `dataset_registry.yaml`: data and feature classes, producer/consumer/PIT/hash contracts",
            "- `model_registry.yaml`: model binaries and metadata, including immutable-binding blockers",
            "- `artifact_registry.parquet`: normalized row for every registered object",
            "- `durable_state_registry.yaml`: accepted paper state, ledgers, state chains, and recovery procedures",
            "- `latest_to_immutable_map.yaml`: every discovered mutable alias is either verified or blocked",
            "- `migration_map.md`: ordered remediation without any mutation authority",
            "- `source_inventory_snapshot.json`: frozen GitHub/Drive/local evidence used for deterministic regeneration",
            "",
            "## Fail-closed limits",
            "",
        ]
    )
    for item in payload["discovery_limits"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "- No Drive upload/move/delete, local cleanup, workflow dispatch, fullrun, target/order/ledger mutation, champion change, production enablement, or live trading occurred.",
            "- Known storage kinds use the canonical provider map; `UNRESOLVED` is reserved for storage whose provider is actually unknown.",
            "- A blank hash means it was not available from the bounded provider view; it is never interpreted as verified.",
            "",
            "## Rebuild",
            "",
            "Publication merge contract: merge this PR only with an expected-head merge commit; squash and rebase are prohibited because the pinned source and protected-publication commits must remain ancestors.",
            "The hashed dependency contract supports CPython 3.12 on Linux x86-64 and Windows x64 only; macOS, ARM, and other interpreter platforms fail the preflight before installation.",
            "",
            "```bash",
            "set -euo pipefail",
            "python -c \"import sys,sysconfig; sys.exit('Linux x86-64 CPython required') if sysconfig.get_platform() != 'linux-x86_64' else None\"",
            "python -c \"import sys; sys.exit('Python 3.12 required') if sys.version_info[:2] != (3, 12) else None\"",
            "git diff --quiet -- docs/run287_p0_4_artifact_inventory/requirements.txt",
            "git diff --cached --quiet -- docs/run287_p0_4_artifact_inventory/requirements.txt",
            'P0_4_REQUIREMENTS="$(mktemp)"',
            'trap \'rm -f "$P0_4_REQUIREMENTS"\' EXIT',
            (
                "python -c \"import hashlib,pathlib,subprocess,sys; "
                "p='docs/run287_p0_4_artifact_inventory/requirements.txt'; "
                "c=subprocess.check_output(['git','show','HEAD:'+p]); "
                "w=pathlib.Path(p).read_bytes().replace(b'\\r\\n',b'\\n'); "
                "sys.exit('unreviewed requirements.txt') if w != c or "
                f"hashlib.sha256(c).hexdigest() != '{FROZEN_REQUIREMENTS_SHA256}' "
                "else pathlib.Path(sys.argv[1]).write_bytes(c)\" "
                '"$P0_4_REQUIREMENTS"'
            ),
            "if [ -L .venv-p0-4 ]; then",
            "  echo 'refusing symlinked .venv-p0-4' >&2",
            "  exit 1",
            "fi",
            "python -m venv --clear .venv-p0-4",
            '.venv-p0-4/bin/python -m pip install --require-hashes --requirement "$P0_4_REQUIREMENTS"',
            ".venv-p0-4/bin/python tools/build_p0_4_artifact_inventory.py --verify-live-head",
            "git diff --exit-code -- docs/run287_p0_4_artifact_inventory",
            "git diff --cached --exit-code -- docs/run287_p0_4_artifact_inventory",
            ".venv-p0-4/bin/python tests/test_p0_4_artifact_inventory.py",
            "```",
            "",
            "PowerShell rebuild (the dependency bytes are captured from the authenticated Git blob before installation):",
            "",
            "```powershell",
            "$P0_4RequirementsPath = 'docs/run287_p0_4_artifact_inventory/requirements.txt'",
            "python -c \"import sys,sysconfig; sys.exit('Windows x64 CPython required') if sysconfig.get_platform() != 'win-amd64' else None\"",
            "if ($LASTEXITCODE -ne 0) { throw 'Windows x64 CPython is required' }",
            "python -c \"import sys; sys.exit('Python 3.12 required') if sys.version_info[:2] != (3, 12) else None\"",
            "if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required' }",
            "git diff --quiet -- $P0_4RequirementsPath",
            "if ($LASTEXITCODE -ne 0) { throw 'unreviewed requirements.txt worktree bytes' }",
            "git diff --cached --quiet -- $P0_4RequirementsPath",
            "if ($LASTEXITCODE -ne 0) { throw 'unreviewed requirements.txt index bytes' }",
            "$P0_4RequirementsTemp = New-TemporaryFile",
            "try {",
            (
                "  python -c \"import hashlib,pathlib,subprocess,sys; "
                "p='docs/run287_p0_4_artifact_inventory/requirements.txt'; "
                "c=subprocess.check_output(['git','show','HEAD:'+p]); "
                "w=pathlib.Path(p).read_bytes().replace(b'\\r\\n',b'\\n'); "
                "sys.exit('unreviewed requirements.txt') if w != c or "
                f"hashlib.sha256(c).hexdigest() != '{FROZEN_REQUIREMENTS_SHA256}' "
                "else pathlib.Path(sys.argv[1]).write_bytes(c)\" "
                "$P0_4RequirementsTemp"
            ),
            "  if ($LASTEXITCODE -ne 0) { throw 'authenticated requirements capture failed' }",
            "  if (Test-Path -LiteralPath '.venv-p0-4') {",
            "    $P0_4VenvItem = Get-Item -LiteralPath '.venv-p0-4' -Force",
            "    if (($P0_4VenvItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'refusing linked .venv-p0-4' }",
            "  }",
            "  python -m venv --clear .venv-p0-4",
            "  if ($LASTEXITCODE -ne 0) { throw 'virtual environment creation failed' }",
            "  $P0_4Python = '.\\.venv-p0-4\\Scripts\\python.exe'",
            "  & $P0_4Python -m pip install --require-hashes --requirement $P0_4RequirementsTemp",
            "  if ($LASTEXITCODE -ne 0) { throw 'pinned dependency installation failed' }",
            "  & $P0_4Python tools/build_p0_4_artifact_inventory.py --verify-live-head",
            "  if ($LASTEXITCODE -ne 0) { throw 'artifact inventory regeneration failed' }",
            "  git diff --exit-code -- docs/run287_p0_4_artifact_inventory",
            "  if ($LASTEXITCODE -ne 0) { throw 'canonical bundle differs from reviewed worktree bytes' }",
            "  git diff --cached --exit-code -- docs/run287_p0_4_artifact_inventory",
            "  if ($LASTEXITCODE -ne 0) { throw 'canonical bundle differs from reviewed index bytes' }",
            "  & $P0_4Python tests/test_p0_4_artifact_inventory.py",
            "  if ($LASTEXITCODE -ne 0) { throw 'artifact inventory smoke failed' }",
            "} finally {",
            "  Remove-Item -LiteralPath $P0_4RequirementsTemp -Force -ErrorAction SilentlyContinue",
            "}",
            "```",
            "",
            "The protected-publication constant is verifier code: advancing it requires an explicit verifier diff and a new external exact-head Codex review plus the repository review-complete gate; regeneration alone grants no trust.",
            "",
        ]
    )
    return "\n".join(lines)


def render_summary(payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    mapping_counts: dict[str, int] = {}
    discovery_counts: dict[str, int] = {}
    for row in rows:
        mapping_counts[str(row["mapping_status"])] = mapping_counts.get(str(row["mapping_status"]), 0) + 1
        discovery_counts[str(row["discovery_status"])] = discovery_counts.get(str(row["discovery_status"]), 0) + 1
    return {
        "schema_version": "run287-p0-4-inventory-summary-v1",
        "market": "US",
        "baseline_code_sha": payload["baseline_code_sha"],
        "observed_at_utc": payload["observed_at_utc"],
        "source_snapshot_sha256": payload["_source_sha256"],
        "counts": {
            "datasets": len(payload["datasets"]),
            "models": len(payload["models"]),
            "durable_states": len(payload["durable_states"]),
            "artifacts": len(payload["artifacts"]),
            "artifact_registry_rows": len(rows),
        },
        "mapping_status_counts": dict(sorted(mapping_counts.items())),
        "discovery_status_counts": dict(sorted(discovery_counts.items())),
        "finding_ids": [row["finding_id"] for row in payload["findings"]],
        "pipeline_health": payload["pipeline_health"],
        "safety": payload["safety"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def normalized_protected_generator_bytes(value: bytes) -> bytes:
    normalized, count = PROTECTED_GENERATOR_PIN_RE.subn(
        b'FROZEN_PROTECTED_PUBLICATION_COMMIT = "<REVIEWED_PIN>"',
        canonical_source_bytes(value),
    )
    if count != 1:
        raise InventoryError("protected_generator_pin_count")
    return normalized


def verify_protected_publication_lineage(protected_commit: str) -> None:
    if not SHA1_RE.fullmatch(protected_commit):
        raise InventoryError("protected_publication_commit_invalid")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", protected_commit, "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if ancestor.returncode != 0:
        raise InventoryError("protected_publication_is_not_live_head_ancestor")
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            f"{protected_commit}..HEAD",
            "--",
            *PROTECTED_PUBLICATION_PATHS,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()
    if changed:
        raise InventoryError(
            "post_publication_protected_delta:" + ",".join(sorted(changed))
        )
    try:
        protected_generator = subprocess.check_output(
            ["git", "show", f"{protected_commit}:{GENERATOR_PATH}"],
            cwd=ROOT,
        )
        head_generator = subprocess.check_output(
            ["git", "show", f"HEAD:{GENERATOR_PATH}"],
            cwd=ROOT,
        )
    except subprocess.CalledProcessError as exc:
        raise InventoryError("protected_generator_unavailable") from exc
    if normalized_protected_generator_bytes(
        protected_generator
    ) != normalized_protected_generator_bytes(head_generator):
        raise InventoryError("post_publication_protected_generator_delta")


def verify_live_publication_lineage(
    baseline: str, *, protected_commit: str | None = None
) -> None:
    baseline_ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            baseline,
            FROZEN_PUBLICATION_COMMIT,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if baseline_ancestor.returncode != 0:
        raise InventoryError("frozen_baseline_is_not_publication_ancestor")
    publication_ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            FROZEN_PUBLICATION_COMMIT,
            "HEAD",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if publication_ancestor.returncode != 0:
        raise InventoryError("frozen_publication_is_not_live_head_ancestor")
    changed = subprocess.check_output(
        [
            "git",
            "diff",
            "--name-only",
            f"{baseline}..{FROZEN_PUBLICATION_COMMIT}",
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).splitlines()
    allowed_exact = {
        ".github/workflows/pr_validation.yml",
        "docs/AGENT_SHARED_LESSONS_LEDGER.md",
        "tests/test_p0_4_artifact_inventory.py",
        "tools/build_p0_4_artifact_inventory.py",
        "tools/run_pr_validation.py",
    }
    unexpected = sorted(
        path
        for path in changed
        if not path.startswith("docs/run287_p0_4_artifact_inventory/")
        and path not in allowed_exact
    )
    if unexpected:
        raise InventoryError(
            "live_head_has_nonpublication_delta:" + ",".join(unexpected)
        )
    for path, expected_sha256 in PINNED_PUBLICATION_FILE_SHA256.items():
        if path not in changed:
            continue
        actual = canonical_source_bytes(
            subprocess.check_output(
                ["git", "show", f"{FROZEN_PUBLICATION_COMMIT}:{path}"],
                cwd=ROOT,
            )
        )
        if hashlib.sha256(actual).hexdigest() != expected_sha256:
            raise InventoryError(f"pinned_publication_file_mismatch:{path}")
    if protected_commit is None:
        protected_commit = FROZEN_PROTECTED_PUBLICATION_COMMIT
    verify_protected_publication_lineage(protected_commit)
    require_clean_tracked_path(GENERATOR_PATH)


def require_clean_tracked_path(path: str) -> None:
    for cached, label in ((False, "worktree"), (True, "index")):
        command = ["git", "diff", "--quiet"]
        if cached:
            command.append("--cached")
        command.extend(["--", path])
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            raise InventoryError(f"tracked_path_dirty:{label}:{path}")
    try:
        head_bytes = subprocess.check_output(
            ["git", "show", f"HEAD:{path}"],
            cwd=ROOT,
        )
        worktree_bytes = (ROOT / path).read_bytes()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError(f"tracked_path_unavailable:{path}") from exc
    if canonical_source_bytes(worktree_bytes) != head_bytes:
        raise InventoryError(f"tracked_path_differs_from_head:{path}")


def read_clean_pinned_requirements() -> bytes:
    require_clean_tracked_path(REQUIREMENTS_PATH)
    try:
        requirements_bytes = canonical_source_bytes(
            subprocess.check_output(
                ["git", "show", f"HEAD:{REQUIREMENTS_PATH}"],
                cwd=ROOT,
            )
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryError("requirements_publication_unavailable") from exc
    if hashlib.sha256(requirements_bytes).hexdigest() != FROZEN_REQUIREMENTS_SHA256:
        raise InventoryError("requirements_publication_sha256_mismatch")
    return requirements_bytes


def render_bundle(
    staging: Path,
    payload: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    source_bytes: bytes,
    requirements_bytes: bytes,
) -> None:
    (staging / "source_inventory_snapshot.json").write_bytes(source_bytes)
    (staging / "requirements.txt").write_bytes(requirements_bytes)
    write_yaml(staging / "dataset_registry.yaml", registry_document(payload, "datasets"))
    write_yaml(staging / "model_registry.yaml", registry_document(payload, "models"))
    write_yaml(
        staging / "durable_state_registry.yaml",
        registry_document(payload, "durable_states"),
    )
    write_yaml(staging / "latest_to_immutable_map.yaml", render_latest_map(payload))
    write_parquet(staging / "artifact_registry.parquet", rows)
    (staging / "migration_map.md").write_text(
        render_migration(payload), encoding="utf-8", newline="\n"
    )
    (staging / "README.md").write_text(
        render_readme(payload, len(rows)), encoding="utf-8", newline="\n"
    )
    write_json(staging / "summary.json", render_summary(payload, rows))


def validate_output_destination(output: Path) -> None:
    if output.is_symlink():
        raise InventoryError("output_directory_symlink_rejected")
    resolved_output = output.resolve()
    resolved_root = ROOT.resolve()
    if resolved_output == resolved_root or resolved_root.is_relative_to(
        resolved_output
    ):
        raise InventoryError("output_contains_repository")
    if (
        resolved_output.is_relative_to(resolved_root)
        and resolved_output != DEFAULT_OUTPUT.resolve()
    ):
        raise InventoryError("in_repository_output_not_canonical")
    if not output.exists():
        return
    if not output.is_dir():
        raise InventoryError("output_path_not_directory")
    if resolved_output == DEFAULT_OUTPUT.resolve():
        entries = list(output.iterdir())
        observed = {entry.name for entry in entries}
        unexpected = sorted(observed - BUNDLE_FILENAMES)
        if unexpected:
            raise InventoryError(
                "canonical_output_not_dedicated:" + ",".join(unexpected)
            )
        missing = sorted(BUNDLE_FILENAMES - observed)
        if missing:
            raise InventoryError(
                "canonical_output_bundle_incomplete:" + ",".join(missing)
            )
        linked = sorted(entry.name for entry in entries if entry.is_symlink())
        if linked:
            raise InventoryError(
                "canonical_output_has_linked_entries:" + ",".join(linked)
            )
        non_files = sorted(entry.name for entry in entries if not entry.is_file())
        if non_files:
            raise InventoryError(
                "canonical_output_has_non_file_entries:" + ",".join(non_files)
            )
        return
    entries = list(output.iterdir())
    if not entries:
        return
    observed = {entry.name for entry in entries}
    unexpected = sorted(observed - BUNDLE_FILENAMES)
    if unexpected:
        raise InventoryError(
            "external_output_not_dedicated:" + ",".join(unexpected)
        )
    missing = sorted(BUNDLE_FILENAMES - observed)
    if missing:
        raise InventoryError(
            "external_output_bundle_incomplete:" + ",".join(missing)
        )
    linked = sorted(entry.name for entry in entries if entry.is_symlink())
    if linked:
        raise InventoryError("staged_bundle_symlink:" + ",".join(linked))
    non_files = sorted(
        entry.name for entry in entries if not entry.is_file()
    )
    if non_files:
        raise InventoryError(
            "external_output_has_non_file_entries:" + ",".join(non_files)
        )
    try:
        source_bytes = canonical_source_bytes(
            (output / "source_inventory_snapshot.json").read_bytes()
        )
        source_payload = json.loads(source_bytes)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        requirements_bytes = canonical_source_bytes(
            (output / "requirements.txt").read_bytes()
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryError("external_output_bundle_authentication_failed") from exc
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if (
        not isinstance(source_payload, dict)
        or source_payload.get("schema_version") != SCHEMA_VERSION
        or not isinstance(summary, dict)
        or summary.get("schema_version") != "run287-p0-4-inventory-summary-v1"
        or summary.get("source_snapshot_sha256") != source_sha256
        or hashlib.sha256(requirements_bytes).hexdigest()
        != FROZEN_REQUIREMENTS_SHA256
    ):
        raise InventoryError("external_output_bundle_authentication_failed")


def publish_bundle_atomically(output: Path, render) -> None:
    validate_output_destination(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    linked = sorted(
        name for name in BUNDLE_FILENAMES if output.exists() and (output / name).is_symlink()
    )
    if linked:
        raise InventoryError("staged_bundle_symlink:" + ",".join(linked))
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=str(output.parent))
    )
    backup: Path | None = None
    try:
        render(staging)
        missing = sorted(name for name in BUNDLE_FILENAMES if not (staging / name).is_file())
        if missing:
            raise InventoryError("staged_bundle_incomplete:" + ",".join(missing))
        if output.exists():
            backup = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except Exception:
            if backup is not None and backup.exists() and not output.exists():
                os.replace(backup, output)
                backup = None
            raise
        if backup is not None:
            committed_backup = backup
            backup = None
            try:
                shutil.rmtree(committed_backup)
            except OSError as exc:
                print(
                    "[p0-4-inventory] WARNING: publication succeeded but "
                    f"backup cleanup failed and was retained at {committed_backup} "
                    f"({type(exc).__name__})",
                    file=sys.stderr,
                )
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup is not None and backup.exists() and not output.exists():
            os.replace(backup, output)


def build(source: Path, output: Path, *, verify_live_head: bool = False) -> None:
    validate_output_destination(output)
    source_bytes = canonical_source_bytes(source.read_bytes())
    is_canonical_source = source.resolve() == DEFAULT_SOURCE.resolve()
    is_canonical_output = output.resolve() == DEFAULT_OUTPUT.resolve()
    if is_canonical_output and not is_canonical_source:
        raise InventoryError("canonical_output_requires_canonical_source")
    if is_canonical_output and not verify_live_head:
        raise InventoryError("canonical_output_requires_live_head_verification")
    if is_canonical_source:
        verify_frozen_source_publication(source_bytes)
    elif verify_live_head:
        raise InventoryError("verify_live_head_requires_canonical_source")
    payload = parse_source(source_bytes)
    payload["_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    validate_source(payload)
    if is_canonical_source:
        verify_live_publication_lineage(payload["baseline_code_sha"])
    rows = artifact_rows(
        payload,
        source_publication_commit=(
            FROZEN_SOURCE_PUBLICATION_COMMIT
            if is_canonical_source
            else UNBOUND_SOURCE_PUBLICATION
        ),
    )
    requirements_bytes = read_clean_pinned_requirements()
    publish_bundle_atomically(
        output,
        lambda staging: render_bundle(
            staging,
            payload,
            rows,
            source_bytes=source_bytes,
            requirements_bytes=requirements_bytes,
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-live-head", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # Keep the caller-supplied output path unresolved so the publisher can
    # reject a symlink at that exact boundary before writing any bundle file.
    build(args.source.resolve(), args.output_dir, verify_live_head=args.verify_live_head)
    print(f"[p0-4-inventory] wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
