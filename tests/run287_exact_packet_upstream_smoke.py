#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_run287_exact_packet_producer import resolve_portable_path, sha256_file
from tools.run_run287_exact_packet_upstream import (
    BLOCKED_STATUS,
    PLAN_SCHEMA,
    PLAN_STATUS,
    PREFLIGHT_STATUS,
    REUSED_STATUS,
    SKIPPED_STATUS,
    build,
    existing_bundle_records,
    nyse_sec_index_dates,
)
from tools.security_lifecycle import REQUIRED_COLUMNS
from tools.run_weekly_evaluation import px_cache_name
from tools.run287_code_identity import current_code_identity, identity_sha256


PATH_LABELS = (
    "universe",
    "base_selection_context",
    "base_score_stack",
    "frozen_score_stack_manifest",
    "model_classification",
    "model_regression",
    "model_bundle",
    "model_meta",
    "scored_oos",
    "company_tickers",
    "sec_identity_index",
    "benchmark_seed",
    "selector_contract_manifest",
    "pinned_import_manifest",
    "price_map_manifest",
    "main_prior_book",
    "concentrated_prior_book",
    "target_generation_manifest",
    "official_daily_crisis_state",
    "official_crisis_thresholds",
    "security_lifecycle_events",
)


def arguments(root: Path, plan: Path, attempt: str) -> argparse.Namespace:
    return argparse.Namespace(
        valuation_date="2026-07-13",
        decision_time_utc="2026-07-14T05:00:00Z",
        attempt_id=attempt,
        plan=str(plan),
        path_override=[],
        directory_override=[],
        allow_network=False,
        preflight_only=True,
        producer_contract="docs/run287_exact_packet_producer_contract.json",
        output_root=str(root / "attempts"),
        source_bundle_output=str(root / "bundles"),
    )


def make_plan(root: Path) -> Path:
    paths = {}
    for label in PATH_LABELS:
        path = root / "inputs" / label
        path.parent.mkdir(parents=True, exist_ok=True)
        if label == "universe":
            pd.DataFrame(
                {
                    "ticker": ["AAPL", "CASH"],
                    "is_equity_issuer": [True, False],
                }
            ).to_csv(path, index=False)
        elif label == "base_selection_context":
            pd.DataFrame({"ticker": ["AAPL"]}).to_parquet(path, index=False)
        elif label == "security_lifecycle_events":
            pd.DataFrame(columns=sorted(REQUIRED_COLUMNS)).to_csv(
                path, index=False
            )
        else:
            path.write_text(f"{label}\n", encoding="utf-8")
        paths[label] = {"path": str(path), "sha256": sha256_file(path)}
    for name in ("prices", "models", "macro"):
        (root / name).mkdir()
    payload = {
        "schema_version": PLAN_SCHEMA,
        "status": PLAN_STATUS,
        "paths": paths,
        "directories": {
            "price_cache": str(root / "prices"),
            "model_root": str(root / "models"),
            "source_macro_dirs": [str(root / "macro")],
        },
        "network_budgets": {
            "scored_latest_provider_batches": 1,
            "maximum_total_recorded_requests": 1,
        },
        "runtime": {"price_batch_size": 40, "expected_context_count": 1},
        "safety": {
            "research_only": True,
            "backtest_allowed": False,
            "fullrun_allowed": False,
            "orders_allowed": False,
            "target_book_write_allowed": False,
            "production_activation_allowed": False,
            "live_trading_allowed": False,
            "premium_provider_allowed": False,
        },
    }
    plan = root / "plan.json"
    plan.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return plan


def replace_universe(plan: Path, frame: pd.DataFrame) -> None:
    payload = json.loads(plan.read_text(encoding="utf-8"))
    path = Path(payload["paths"]["universe"]["path"])
    frame.to_csv(path, index=False)
    payload["paths"]["universe"]["sha256"] = sha256_file(path)
    plan.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class UpstreamSmoke(unittest.TestCase):
    def test_cli_returns_nonzero_for_skipped_prerequisites(self) -> None:
        from tools import run_run287_exact_packet_upstream as upstream

        with patch.object(
            upstream, "parse_args", return_value=object()
        ), patch.object(
            upstream,
            "build",
            return_value={"status": SKIPPED_STATUS},
        ), patch("builtins.print"):
            self.assertEqual(upstream.main(), 2)
        with patch.object(
            upstream, "parse_args", return_value=object()
        ), patch.object(
            upstream,
            "build",
            return_value={"status": PREFLIGHT_STATUS},
        ), patch("builtins.print"):
            self.assertEqual(upstream.main(), 0)

    def test_nyse_dates_are_weekend_aware(self) -> None:
        self.assertEqual(
            nyse_sec_index_dates("2026-07-13"), ["20260710", "20260713"]
        )

    def test_preflight_ready_and_missing_input_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            ready = build(arguments(root, plan, "ready"))
            self.assertEqual(ready["status"], PREFLIGHT_STATUS)
            self.assertEqual(ready["preflight"]["estimated_scored_latest_provider_batches"], 1)
            self.assertEqual(
                ready["preflight"]["ticker_identity"][
                    "pre_lifecycle_context_count"
                ],
                1,
            )
            self.assertEqual(
                ready["preflight"]["ticker_identity"]["universe_count"], 1
            )
            self.assertEqual(
                ready["preflight"]["ticker_identity"][
                    "universe_source_row_count"
                ],
                2,
            )
            self.assertEqual(
                ready["preflight"]["ticker_identity"][
                    "universe_non_equity_placeholder_ticker"
                ],
                "CASH",
            )
            self.assertFalse(ready["network_execution_authorized"])
            self.assertEqual(
                len(ready["preflight"]["code_identity"]["identity_sha256"]),
                64,
            )

            payload = json.loads(plan.read_text(encoding="utf-8"))
            Path(payload["paths"]["model_meta"]["path"]).unlink()
            skipped = build(arguments(root, plan, "missing"))
            self.assertEqual(skipped["status"], SKIPPED_STATUS)
            self.assertIn("missing_path:model_meta", skipped["skip_reasons"])

    def test_preflight_rejects_arbitrary_blank_non_equity_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            replace_universe(
                plan,
                pd.DataFrame(
                    {
                        "ticker": ["AAPL", ""],
                        "is_equity_issuer": [True, False],
                    }
                ),
            )
            skipped = build(arguments(root, plan, "blank-placeholder"))
            self.assertEqual(skipped["status"], SKIPPED_STATUS)
            self.assertTrue(
                any(
                    "universe_blank_ticker_invalid" in reason
                    for reason in skipped["skip_reasons"]
                ),
                skipped["skip_reasons"],
            )

    def test_preflight_requires_exactly_one_declared_cash_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            replace_universe(
                plan,
                pd.DataFrame(
                    {
                        "ticker": ["AAPL", "CASH", "__CASH__"],
                        "is_equity_issuer": [True, False, False],
                    }
                ),
            )
            skipped = build(arguments(root, plan, "duplicate-placeholder"))
            self.assertEqual(skipped["status"], SKIPPED_STATUS)
            self.assertTrue(
                any(
                    "universe_non_equity_placeholder_count_invalid:2" in reason
                    for reason in skipped["skip_reasons"]
                ),
                skipped["skip_reasons"],
            )

    def test_preflight_rejects_false_flag_on_an_equity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            replace_universe(
                plan,
                pd.DataFrame(
                    {
                        "ticker": ["AAPL", "MSFT"],
                        "is_equity_issuer": [True, False],
                    }
                ),
            )
            skipped = build(arguments(root, plan, "equity-placeholder"))
            self.assertEqual(skipped["status"], SKIPPED_STATUS)
            self.assertTrue(
                any(
                    "universe_non_equity_placeholder_ticker_invalid" in reason
                    for reason in skipped["skip_reasons"]
                ),
                skipped["skip_reasons"],
            )

    def test_portable_resolution_stays_inside_verified_restore_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run287_research_static"
            owner = root / "outputs" / "owner" / "manifest.json"
            source = root / "outputs" / "source" / "exact.parquet"
            owner.parent.mkdir(parents=True)
            source.parent.mkdir(parents=True)
            owner.write_text("{}\n", encoding="utf-8")
            source.write_bytes(b"exact-source")

            resolved = resolve_portable_path(
                r"Z:\unavailable\outputs\source\exact.parquet", owner=owner
            )
            self.assertEqual(resolved, source.resolve())

    def test_existing_dated_bundle_records_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dated = root / "by_date" / "2026-07-13" / "source_bundle.json"
            dated.parent.mkdir(parents=True)
            dated.write_text(
                json.dumps(
                    {
                        "valuation_price_cutoff_date": "2026-07-13",
                        "inputs": {"decision_manifest": {"path": "exact.json"}},
                    }
                ),
                encoding="utf-8",
            )
            result = existing_bundle_records(root, "2026-07-13")
            self.assertIsNotNone(result)
            self.assertEqual(result[1], {"decision_manifest": "exact.json"})

    def test_network_retry_reuses_validated_same_date_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            args = arguments(root, plan, "reuse")
            args.allow_network = True
            args.preflight_only = False
            dated = (
                Path(args.source_bundle_output)
                / "by_date"
                / "2026-07-13"
                / "source_bundle.json"
            )
            dated.parent.mkdir(parents=True)
            dated.write_text(
                json.dumps(
                    {
                        "valuation_price_cutoff_date": "2026-07-13",
                        "inputs": {"decision_manifest": {"path": "exact.json"}},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"SEC_USER_AGENT": "research test@example.com"}), patch(
                "tools.run_run287_exact_packet_upstream.publish_bundle",
                return_value={
                    "status": "READY_EXISTING_EXACT_PACKET_INPUT_SOURCE_BUNDLE_REVIEW_ONLY",
                    "current_source_bundle": {"path": str(dated), "sha256": "abc"},
                },
            ) as publisher:
                result = build(args)
            self.assertEqual(result["status"], REUSED_STATUS)
            self.assertEqual(result["network_requests_executed"], 0)
            self.assertFalse(result["network_execution_authorized"])
            publisher.assert_called_once()
            self.assertEqual(
                publisher.call_args.kwargs["expected_code_identity"],
                result["preflight"]["code_identity"],
            )

    def test_code_identity_change_before_bundle_reuse_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            args = arguments(root, plan, "reuse-code-change")
            args.allow_network = True
            args.preflight_only = False
            dated = (
                Path(args.source_bundle_output)
                / "by_date"
                / "2026-07-13"
                / "source_bundle.json"
            )
            dated.parent.mkdir(parents=True)
            dated.write_text(
                json.dumps(
                    {
                        "valuation_price_cutoff_date": "2026-07-13",
                        "inputs": {
                            "decision_manifest": {"path": "exact.json"}
                        },
                    }
                ),
                encoding="utf-8",
            )
            stable = current_code_identity()
            changed = json.loads(json.dumps(stable))
            changed["source_commit_sha"] = "f" * 40
            changed["source_tree_sha"] = "e" * 40
            changed["identity_sha256"] = identity_sha256(changed)
            with patch.dict(
                "os.environ",
                {"SEC_USER_AGENT": "research test@example.com"},
            ), patch(
                "tools.run_run287_exact_packet_upstream.current_code_identity",
                side_effect=[stable, changed],
            ), patch(
                "tools.run_run287_exact_packet_upstream.publish_bundle"
            ) as publisher:
                blocked = build(args)
            self.assertEqual(blocked["status"], BLOCKED_STATUS, blocked)
            self.assertIn(
                "code_identity:current_mismatch",
                blocked["stage_audit"][-1]["failures"],
            )
            publisher.assert_not_called()

    def test_preflight_input_mutation_before_reused_ready_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = make_plan(root)
            args = arguments(root, plan, "reuse-mutation")
            args.allow_network = True
            args.preflight_only = False
            dated = (
                Path(args.source_bundle_output)
                / "by_date"
                / "2026-07-13"
                / "source_bundle.json"
            )
            dated.parent.mkdir(parents=True)
            dated.write_text(
                json.dumps(
                    {
                        "valuation_price_cutoff_date": "2026-07-13",
                        "inputs": {
                            "decision_manifest": {"path": "exact.json"}
                        },
                    }
                ),
                encoding="utf-8",
            )
            plan_payload = json.loads(plan.read_text(encoding="utf-8"))
            model_meta = Path(
                plan_payload["paths"]["model_meta"]["path"]
            )

            def mutate_after_preflight(**_: object) -> dict[str, object]:
                model_meta.write_text("model_meta:mutated\n", encoding="utf-8")
                (root / "prices" / px_cache_name("AAPL")).write_bytes(
                    b"late-price-cache"
                )
                return {
                    "status": (
                        "READY_EXISTING_EXACT_PACKET_INPUT_SOURCE_BUNDLE_REVIEW_ONLY"
                    ),
                    "current_source_bundle": {
                        "path": str(dated),
                        "sha256": "abc",
                    },
                }

            with patch.dict(
                "os.environ",
                {"SEC_USER_AGENT": "research test@example.com"},
            ), patch(
                "tools.run_run287_exact_packet_upstream.publish_bundle",
                side_effect=mutate_after_preflight,
            ):
                result = build(args)
            self.assertEqual(result["status"], BLOCKED_STATUS)
            self.assertEqual(result["failed_stage"], "preflight_input_rehash")
            self.assertIn(
                "preflight_input_changed:model_meta",
                result["stage_audit"][-1]["failures"],
            )
            self.assertIn(
                "preflight_price_cache_changed:AAPL",
                result["stage_audit"][-1]["failures"],
            )


if __name__ == "__main__":
    unittest.main()
