#!/usr/bin/env python3
"""Restore replay-only target books from a pinned Run287 workflow artifact.

The artifact download and GitHub provenance are verified by the calling
workflow.  This tool independently revalidates that closed metadata contract,
then requires each source target book to match the target SHA and normalized
target hash recorded by the accepted legacy paper ledger.  The corresponding
order-preview target must describe the same allocation.

No target is recomputed.  The original target-book bytes are copied into a
separate replay-only directory for chronological catch-up.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_catchup_price_evidence import (  # noqa: E402
    ContractError,
    fingerprint,
    parse_session_date,
    read_json_object,
    sha256_file,
    validate_metadata,
    write_json_atomic,
)
from tools.run_daily_simulated_fill_ledger import (  # noqa: E402
    normalized_target,
    target_hash,
)


SCHEMA_VERSION = "run287-catchup-target-evidence-v1"
MANIFEST_SCHEMA_VERSION = "run287-catchup-target-evidence-manifest-v1"
READY_STATUS = "READY_RUN287_CATCHUP_TARGET_EVIDENCE_REPLAY_ONLY"
BLOCKED_STATUS = "BLOCKED_RUN287_CATCHUP_TARGET_EVIDENCE"
LEDGER_SUMMARY = Path("outputs/daily_simulated_fill_ledger/summary.json")
TARGET_SPECS = {
    "main": {
        "source": Path("outputs/reports/operating_main_target_book.csv"),
        "preview": Path("outputs/account_ledger_preview/main/target_weights.csv"),
        "preview_metrics": Path(
            "outputs/account_ledger_preview/main/preview_metrics.json"
        ),
        "order_manifest": Path(
            "outputs/account_ledger_preview/main/order_batch_manifest.json"
        ),
        "output": "operating_main_target_book.csv",
    },
    "concentrated": {
        "source": Path(
            "outputs/reports/operating_concentrated_target_book.csv"
        ),
        "preview": Path(
            "outputs/account_ledger_preview/concentrated/target_weights.csv"
        ),
        "preview_metrics": Path(
            "outputs/account_ledger_preview/concentrated/preview_metrics.json"
        ),
        "order_manifest": Path(
            "outputs/account_ledger_preview/concentrated/order_batch_manifest.json"
        ),
        "output": "operating_concentrated_target_book.csv",
    },
}


def fail(code: str) -> None:
    raise ContractError(code)


def strict_false(value: Any, code: str) -> None:
    if value is not False:
        fail(code)


def close_number(left: Any, right: Any, code: str, *, tolerance: float = 1e-10) -> None:
    try:
        left_number = float(left)
        right_number = float(right)
    except Exception:
        fail(code)
    if (
        not math.isfinite(left_number)
        or not math.isfinite(right_number)
        or abs(left_number - right_number) > tolerance
    ):
        fail(code)


def safe_source(artifact_root: Path, relative: Path, code: str) -> Path:
    path = artifact_root / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or artifact_root not in path.resolve().parents
    ):
        fail(code)
    return path


def validate_summary(
    summary: dict[str, Any],
    *,
    selected_date: pd.Timestamp,
) -> dict[str, dict[str, Any]]:
    selected_text = selected_date.date().isoformat()
    if (
        summary.get("schema_version")
        != "daily-simulated-fill-ledger-summary-v1"
        or summary.get("status") != "completed"
        or str(summary.get("as_of_date") or "") != selected_text
        or summary.get("review_only") is not True
        or summary.get("simulated") is not True
    ):
        fail("legacy_ledger_summary_contract")
    strict_false(
        summary.get("production_mutation_allowed"),
        "legacy_ledger_summary_production_flag",
    )
    strict_false(
        summary.get("live_trading_enabled"),
        "legacy_ledger_summary_live_flag",
    )
    portfolios = summary.get("portfolios")
    if not isinstance(portfolios, dict):
        fail("legacy_ledger_portfolios_invalid")
    validated: dict[str, dict[str, Any]] = {}
    for portfolio in TARGET_SPECS:
        value = portfolios.get(portfolio)
        if not isinstance(value, dict):
            fail(f"legacy_ledger_portfolio_missing:{portfolio}")
        if (
            value.get("schema_version")
            != "daily-simulated-fill-ledger-manifest-v1"
            or value.get("portfolio_kind") != portfolio
            or str(value.get("as_of_date") or "") != selected_text
            or str(value.get("target_effective_date") or "") != selected_text
            or value.get("review_only") is not True
            or value.get("simulated") is not True
        ):
            fail(f"legacy_ledger_portfolio_contract:{portfolio}")
        strict_false(
            value.get("production_mutation_allowed"),
            f"legacy_ledger_portfolio_production_flag:{portfolio}",
        )
        strict_false(
            value.get("live_trading_enabled"),
            f"legacy_ledger_portfolio_live_flag:{portfolio}",
        )
        target_sha = str(value.get("target_sha256") or "").lower()
        normalized_hash = str(value.get("target_hash") or "").lower()
        if len(target_sha) != 64 or any(c not in "0123456789abcdef" for c in target_sha):
            fail(f"legacy_ledger_target_sha_invalid:{portfolio}")
        if len(normalized_hash) != 64 or any(
            c not in "0123456789abcdef" for c in normalized_hash
        ):
            fail(f"legacy_ledger_target_hash_invalid:{portfolio}")
        validated[portfolio] = value
    return validated


def validate_target(
    *,
    artifact_root: Path,
    portfolio: str,
    spec: dict[str, Any],
    ledger: dict[str, Any],
    selected_date: pd.Timestamp,
) -> tuple[Path, dict[str, Any]]:
    selected_text = selected_date.date().isoformat()
    source = safe_source(
        artifact_root,
        spec["source"],
        f"source_target_missing_or_unsafe:{portfolio}",
    )
    preview = safe_source(
        artifact_root,
        spec["preview"],
        f"preview_target_missing_or_unsafe:{portfolio}",
    )
    metrics_path = safe_source(
        artifact_root,
        spec["preview_metrics"],
        f"preview_metrics_missing_or_unsafe:{portfolio}",
    )
    order_manifest_path = safe_source(
        artifact_root,
        spec["order_manifest"],
        f"order_manifest_missing_or_unsafe:{portfolio}",
    )
    if sha256_file(source) != str(ledger["target_sha256"]).lower():
        fail(f"source_target_sha_mismatch:{portfolio}")

    try:
        source_frame = pd.read_csv(source, low_memory=False)
    except Exception:
        fail(f"source_target_csv_invalid:{portfolio}")
    if source_frame.empty or not {"rebalance_date", "ticker"} <= set(
        source_frame.columns
    ):
        fail(f"source_target_shape_invalid:{portfolio}")
    dates = pd.to_datetime(source_frame["rebalance_date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        fail(f"source_target_date_invalid:{portfolio}")
    if (dates > selected_date).any():
        fail(f"source_target_future_rows:{portfolio}")
    exact_rows = int(dates.eq(selected_date).sum())
    if exact_rows <= 0 or dates.max() != selected_date:
        fail(f"source_target_exact_snapshot_missing:{portfolio}")

    normalized = normalized_target(source, portfolio, selected_date)
    if normalized.empty:
        fail(f"source_target_normalized_empty:{portfolio}")
    if normalized["ticker"].duplicated().any():
        fail(f"source_target_duplicate_ticker:{portfolio}")
    normalized_hash = target_hash(normalized)
    if normalized_hash != str(ledger["target_hash"]).lower():
        fail(f"source_target_normalized_hash_mismatch:{portfolio}")
    close_number(
        normalized["target_weight"].sum(),
        1.0,
        f"source_target_weight_sum_invalid:{portfolio}",
        tolerance=1e-8,
    )

    preview_normalized = normalized_target(preview, portfolio, selected_date)
    if target_hash(preview_normalized) != normalized_hash:
        fail(f"preview_target_normalized_hash_mismatch:{portfolio}")

    metrics = read_json_object(
        metrics_path,
        f"preview_metrics:{portfolio}",
    )
    if (
        metrics.get("schema_version") != "account-ledger-preview-v1"
        or metrics.get("status") != "completed"
        or metrics.get("portfolio_kind") != portfolio
        or str(metrics.get("as_of_date") or "") != selected_text
        or str(metrics.get("account_state_as_of_date") or "") != selected_text
        or int(metrics.get("target_count", -1)) != len(normalized)
    ):
        fail(f"preview_metrics_contract:{portfolio}")
    close_number(
        metrics.get("target_stock_weight"),
        normalized.loc[
            ~normalized["ticker"].isin({"CASH", "__CASH__"}), "target_weight"
        ].sum(),
        f"preview_metrics_stock_weight_mismatch:{portfolio}",
        tolerance=1e-8,
    )
    close_number(
        metrics.get("target_cash_weight"),
        normalized.loc[
            normalized["ticker"].isin({"CASH", "__CASH__"}), "target_weight"
        ].sum(),
        f"preview_metrics_cash_weight_mismatch:{portfolio}",
        tolerance=1e-8,
    )

    order_manifest = read_json_object(
        order_manifest_path,
        f"order_manifest:{portfolio}",
    )
    if (
        order_manifest.get("schema_version")
        != "account-ledger-preview-order-batch-v1"
        or order_manifest.get("portfolio_kind") != portfolio
        or str(order_manifest.get("as_of_date") or "") != selected_text
    ):
        fail(f"order_manifest_contract:{portfolio}")

    return source, {
        "portfolio_kind": portfolio,
        "selected_session_date": selected_text,
        "source_target": fingerprint(
            source,
            label=f"{portfolio}_source_target",
            relative_path=str(spec["source"]),
        ),
        "preview_target": fingerprint(
            preview,
            label=f"{portfolio}_preview_target",
            relative_path=str(spec["preview"]),
        ),
        "preview_metrics": fingerprint(
            metrics_path,
            label=f"{portfolio}_preview_metrics",
            relative_path=str(spec["preview_metrics"]),
        ),
        "order_manifest": fingerprint(
            order_manifest_path,
            label=f"{portfolio}_order_manifest",
            relative_path=str(spec["order_manifest"]),
        ),
        "source_row_count": int(len(source_frame)),
        "exact_snapshot_row_count": exact_rows,
        "normalized_target_count": int(len(normalized)),
        "normalized_target_weight_sum": float(normalized["target_weight"].sum()),
        "normalized_target_hash": normalized_hash,
        "ledger_target_sha256": str(ledger["target_sha256"]).lower(),
        "ledger_target_hash": str(ledger["target_hash"]).lower(),
        "ledger_binding_verified": True,
        "preview_binding_verified": True,
    }


def base_evidence(
    *,
    artifact_root: Path,
    metadata_path: Path,
    selected_text: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": [],
        "selected_session_date": selected_text,
        "artifact_root_name": artifact_root.name,
        "artifact_metadata_file": metadata_path.name,
        "replay_only": True,
        "forward_promotion_eligible": False,
        "orders_generated": False,
        "targets_recomputed": False,
        "production_mutation_allowed": False,
        "live_trading_enabled": False,
        "target_evidence_materialized": False,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    artifact_root = Path(args.artifact_root).resolve()
    metadata_path = Path(args.artifact_metadata).resolve()
    output_dir = Path(args.output_target_dir).resolve()
    output_evidence = Path(args.output_evidence).resolve()
    selected_text = str(args.session_date or "").strip()
    evidence = base_evidence(
        artifact_root=artifact_root,
        metadata_path=metadata_path,
        selected_text=selected_text,
    )
    stage: Path | None = None
    try:
        if not artifact_root.is_dir():
            fail("artifact_root_missing")
        if output_dir == artifact_root or artifact_root in output_dir.parents:
            fail("output_target_dir_inside_artifact_root")
        if output_evidence == artifact_root or artifact_root in output_evidence.parents:
            fail("output_evidence_inside_artifact_root")
        if output_evidence == output_dir or output_dir in output_evidence.parents:
            fail("output_evidence_inside_output_target_dir")
        if output_dir.exists() and (
            not output_dir.is_dir() or any(output_dir.iterdir())
        ):
            fail("output_target_dir_not_empty")

        selected_date = parse_session_date(
            selected_text,
            "selected_session_date_invalid",
        )
        metadata = read_json_object(metadata_path, "artifact_metadata")
        artifact_identity, _captured_at = validate_metadata(
            metadata,
            artifact_root=artifact_root,
        )
        summary_path = safe_source(
            artifact_root,
            LEDGER_SUMMARY,
            "legacy_ledger_summary_missing_or_unsafe",
        )
        summary = read_json_object(summary_path, "legacy_ledger_summary")
        ledger_portfolios = validate_summary(summary, selected_date=selected_date)

        source_targets: dict[str, Path] = {}
        target_evidence: dict[str, dict[str, Any]] = {}
        for portfolio, spec in TARGET_SPECS.items():
            source, details = validate_target(
                artifact_root=artifact_root,
                portfolio=portfolio,
                spec=spec,
                ledger=ledger_portfolios[portfolio],
                selected_date=selected_date,
            )
            source_targets[portfolio] = source
            target_evidence[portfolio] = details

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            output_dir.rmdir()
        stage = Path(
            tempfile.mkdtemp(
                prefix=f".{output_dir.name}.",
                dir=str(output_dir.parent),
            )
        )
        for portfolio, source in source_targets.items():
            destination = stage / str(TARGET_SPECS[portfolio]["output"])
            shutil.copyfile(source, destination)
            if sha256_file(destination) != sha256_file(source):
                fail(f"materialized_target_sha_mismatch:{portfolio}")
            target_evidence[portfolio]["materialized_target"] = fingerprint(
                destination,
                label=f"{portfolio}_materialized_target",
                relative_path=destination.name,
            )

        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "status": READY_STATUS,
            "selected_session_date": selected_text,
            "artifact": artifact_identity,
            "legacy_ledger_summary": fingerprint(
                summary_path,
                label="legacy_ledger_summary",
                relative_path=str(LEDGER_SUMMARY),
            ),
            "targets": target_evidence,
            "replay_only": True,
            "forward_promotion_eligible": False,
            "orders_generated": False,
            "targets_recomputed": False,
            "original_source_bytes_preserved": True,
            "production_mutation_allowed": False,
            "live_trading_enabled": False,
        }
        write_json_atomic(stage / "manifest.json", manifest)
        os.replace(stage, output_dir)
        stage = None
        evidence.update(
            {
                "status": READY_STATUS,
                "artifact": artifact_identity,
                "target_manifest": fingerprint(
                    output_dir / "manifest.json",
                    label="target_manifest",
                    relative_path="manifest.json",
                ),
                "target_evidence_materialized": True,
                "target_count": len(target_evidence),
            }
        )
    except ContractError as exc:
        evidence["contract_failures"] = [str(exc)]
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        if output_dir.exists() and output_dir.is_dir() and not any(output_dir.iterdir()):
            output_dir.rmdir()
    except Exception as exc:
        evidence["contract_failures"] = [f"unexpected:{type(exc).__name__}"]
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        if output_dir.exists() and output_dir.is_dir() and not any(output_dir.iterdir()):
            output_dir.rmdir()

    write_json_atomic(output_evidence, evidence)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--artifact-metadata", required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--output-target-dir", required=True)
    parser.add_argument("--output-evidence", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
