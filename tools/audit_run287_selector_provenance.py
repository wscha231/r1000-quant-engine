#!/usr/bin/env python3
"""Reconcile Run287 advisory, operating, and paper-account paths without writes.

The audit is a hash-pinned, single-date integrity check.  It explains the
entire selector/operating/paper union, reconstructs selector and bootstrap cash,
and records the causal reason for the preregistered five-name divergence.  It
never changes scores, ranks, selectors, target books, cash policy, or orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-selector-provenance-audit-v1"
READY_STATUS = "READY_SELECTOR_PROVENANCE_INTENTIONAL_PARALLEL_PATH"
BLOCKED_STATUS = "BLOCKED_SELECTOR_PROVENANCE_INTEGRITY"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": ""}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def parse_time(value: Any) -> pd.Timestamp:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        raise ValueError(f"invalid UTC timestamp: {value}")
    return stamp


def normalize_ticker(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NAN", "NONE"}:
        return ""
    return "CASH" if text in {"CASH", "__CASH__"} else text


def verified_source_files(
    contract: Mapping[str, Any], failures: list[str]
) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    paths: dict[str, Path] = {}
    audits: dict[str, dict[str, Any]] = {}
    for label, record in (contract.get("source_files") or {}).items():
        path = repo_path(str(record.get("path") or ""))
        expected = str(record.get("sha256") or "").lower()
        row = fingerprint(path)
        row.update(expected_sha256=expected, hash_matches=row["sha256"] == expected)
        paths[str(label)] = path
        audits[str(label)] = row
        if not row["exists"]:
            failures.append(f"source_missing:{label}")
        elif not expected or not row["hash_matches"]:
            failures.append(f"source_hash_mismatch:{label}")
    return paths, audits


def verified_output(
    manifest_path: Path, manifest: Mapping[str, Any], key: str
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get("outputs") or {}).get(key) or {}
    raw = str(record.get("path") or "")
    expected = str(record.get("sha256") or "").lower()
    candidates: list[Path] = []
    if raw:
        raw_path = Path(raw)
        candidates.append(raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path)
        candidates.append(manifest_path.parent / raw_path.name)
    for path in candidates:
        row = fingerprint(path)
        if row["exists"] and expected and row["sha256"] == expected:
            row.update(expected_sha256=expected, hash_matches=True, label=key)
            return path, row
    raise ValueError(f"verified manifest output unavailable: {key}")


def output_frame(path: Path, frame: pd.DataFrame, sort_by: list[str]) -> None:
    work = frame.sort_values(sort_by, kind="mergesort").reset_index(drop=True)
    work.to_csv(path, index=False, lineterminator="\n")


def selector_safety_failures(selector: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    required_false = (
        "execution_allowed",
        "target_book_generation_allowed",
        "target_book_file_written",
        "target_books_mutated",
        "orders_generated",
        "backtest_executed",
        "fullrun_executed",
        "production_activation_allowed",
        "live_trading_enabled",
    )
    for key in required_false:
        if bool(selector.get(key)):
            failures.append(f"selector_safety_flag_true:{key}")
    if not bool(selector.get("selector_no_write_passed")):
        failures.append("selector_no_write_not_passed")
    return failures


def load_operating_book(path: Path, as_of_date: str) -> pd.DataFrame:
    frame = pd.read_csv(path, usecols=["rebalance_date", "ticker", "weight"])
    frame["rebalance_date"] = pd.to_datetime(frame["rebalance_date"], errors="coerce").dt.date
    cutoff = pd.Timestamp(as_of_date).date()
    current = frame.loc[frame["rebalance_date"].eq(cutoff)].copy()
    if current.empty:
        raise ValueError(f"operating book has no exact date {as_of_date}: {path}")
    current["ticker"] = current["ticker"].map(normalize_ticker)
    current["operating_weight"] = pd.to_numeric(current["weight"], errors="coerce")
    if current["ticker"].eq("").any() or current["operating_weight"].isna().any():
        raise ValueError(f"invalid operating book rows: {path}")
    current = current.groupby("ticker", as_index=False)["operating_weight"].sum()
    return current.sort_values("ticker").reset_index(drop=True)


def paper_state(
    kind: str,
    paths: Mapping[str, Path],
    operating: pd.DataFrame,
    as_of_date: str,
    cash_tolerance: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = read_json(paths[f"{kind}_paper_manifest"])
    account = read_json(paths[f"{kind}_account_state"])
    positions = pd.read_csv(paths[f"{kind}_positions"])
    positions["ticker"] = positions["ticker"].map(normalize_ticker)
    positions["shares"] = pd.to_numeric(positions["shares"], errors="coerce")
    positions["price"] = pd.to_numeric(positions["price"], errors="coerce")
    positions["weight"] = pd.to_numeric(positions["weight"], errors="coerce")
    if positions[["shares", "price", "weight"]].isna().any().any():
        raise ValueError(f"invalid paper positions: {kind}")
    if str(manifest.get("as_of_date") or "") != as_of_date:
        raise ValueError(f"paper manifest date mismatch: {kind}")
    if str(account.get("as_of_date") or "") != as_of_date:
        raise ValueError(f"paper account date mismatch: {kind}")

    joined = operating.merge(
        positions[["ticker", "shares", "price", "weight"]], on="ticker", how="outer"
    )
    membership_exact = not joined[["operating_weight", "shares"]].isna().any().any()
    joined = joined.fillna(0.0)
    equity = finite(account.get("equity_usd"))
    joined["expected_bootstrap_shares"] = np.floor(
        (joined["operating_weight"] * equity + 1e-9) / joined["price"].replace(0.0, np.nan)
    ).fillna(0.0)
    joined["share_count_exact"] = joined["expected_bootstrap_shares"].eq(joined["shares"])
    expected_cash = equity - float((joined["shares"] * joined["price"]).sum())
    actual_cash = finite(account.get("cash_usd"))
    cash_error = actual_cash - expected_cash
    summary = {
        "portfolio_kind": kind,
        "as_of_date": as_of_date,
        "operating_position_count": int(len(operating)),
        "paper_position_count": int(len(positions)),
        "membership_exact": bool(membership_exact),
        "share_count_exact_count": int(joined["share_count_exact"].sum()),
        "share_count_expected_count": int(len(joined)),
        "share_count_exact": bool(joined["share_count_exact"].all()),
        "equity_usd": equity,
        "target_stock_weight": float(operating["operating_weight"].sum()),
        "target_cash_weight": 1.0 - float(operating["operating_weight"].sum()),
        "paper_cash_usd": actual_cash,
        "paper_cash_weight": finite(account.get("cash_weight")),
        "reconstructed_cash_usd": expected_cash,
        "cash_error_usd": cash_error,
        "cash_exact_to_tolerance": abs(cash_error) <= cash_tolerance,
        "target_sha256": str(manifest.get("target_sha256") or ""),
        "target_effective_date": str(manifest.get("target_effective_date") or ""),
        "seeded_this_run": bool(manifest.get("seeded_this_run")),
        "fill_count": int(manifest.get("fill_count") or 0),
        "pending_order_count": int(manifest.get("pending_order_count") or 0),
        "rejection_count": int(manifest.get("rejection_count") or 0),
        "event_sequence": int(manifest.get("event_sequence") or 0),
        "bootstrap_semantics": "BOOTSTRAP_TARGET_ASSUMED_APPLIED",
        "orders_generated": False,
        "target_books_mutated": False,
    }
    joined = joined.rename(columns={"weight": "paper_weight", "shares": "paper_shares"})
    return joined, summary


def availability_audit(
    selector: Mapping[str, Any], selector_path: Path, decision_time: str
) -> pd.DataFrame:
    inputs = selector.get("source_inputs") or {}
    decision = parse_time(decision_time)
    specifications = [
        ("decision_features", "decision_manifest", "feature_available_from"),
        ("score_stack", "score_stack_manifest", "feature_available_from"),
        ("latest_scores", "price_manifest", "score_available_from"),
        ("macro", "macro_manifest", "macro_available_from"),
        ("holding_risk", "holding_watch_summary", "available_from"),
        ("crisis_state", "crisis_manifest", "macro_available_from"),
    ]
    rows: list[dict[str, Any]] = []
    loaded: dict[str, dict[str, Any]] = {}
    for label, source_key, field in specifications:
        record = inputs.get(source_key) or {}
        path = Path(str(record.get("path") or ""))
        if not path.is_absolute():
            path = selector_path.parent / path
        payload = read_json(path)
        loaded[source_key] = payload
        available = parse_time(payload.get(field))
        rows.append(
            {
                "source_label": label,
                "source_key": source_key,
                "availability_field": field,
                "available_from": available.isoformat(),
                "decision_time_utc": decision.isoformat(),
                "availability_origin": "source_manifest_explicit",
                "available_by_decision": bool(available <= decision),
                "source_sha256": str(record.get("sha256") or ""),
            }
        )
    crisis_available = parse_time(loaded["crisis_manifest"].get("macro_available_from"))
    soxx_record = inputs.get("soxx_manifest") or {}
    soxx_path = Path(str(soxx_record.get("path") or ""))
    if not soxx_path.is_absolute():
        soxx_path = selector_path.parent / soxx_path
    soxx = read_json(soxx_path)
    if str(soxx.get("valuation_price_cutoff_date") or "") != str(
        selector.get("valuation_price_cutoff_date") or ""
    ):
        raise ValueError("benchmark exact-close date mismatch")
    rows.append(
        {
            "source_label": "benchmark_exact_close",
            "source_key": "soxx_manifest",
            "availability_field": "derived_exact_close_market_available_from",
            "available_from": crisis_available.isoformat(),
            "decision_time_utc": decision.isoformat(),
            "availability_origin": "same_session_exact_close_plus_market_close_contract",
            "available_by_decision": bool(crisis_available <= decision),
            "source_sha256": str(soxx_record.get("sha256") or ""),
        }
    )
    return pd.DataFrame(rows)


def archive_match_map(
    comparison: pd.DataFrame, archived: pd.DataFrame, tolerance: float
) -> tuple[dict[tuple[str, str, str], bool], float]:
    keys = ["portfolio_kind", "scenario", "ticker"]
    for frame in (comparison, archived):
        frame["ticker"] = frame["ticker"].map(normalize_ticker)
    if comparison.duplicated(keys).any() or archived.duplicated(keys).any():
        raise ValueError("duplicate selector/archive key")
    if set(map(tuple, comparison[keys].to_numpy())) != set(
        map(tuple, archived[keys].to_numpy())
    ):
        raise ValueError("selector/archive key set mismatch")
    joined = comparison.merge(archived, on=keys, suffixes=("_selector", "_archive"))
    numeric = [
        "marked_weight",
        "official_prior_weight",
        "advisory_weight",
        "delta_vs_marked",
        "delta_vs_official",
    ]
    max_error = 0.0
    matches = pd.Series(True, index=joined.index)
    for column in numeric:
        left = pd.to_numeric(joined[f"{column}_selector"], errors="coerce").fillna(0.0)
        right = pd.to_numeric(joined[f"{column}_archive"], errors="coerce").fillna(0.0)
        error = (left - right).abs()
        max_error = max(max_error, float(error.max()))
        matches &= error.le(tolerance)
    for column in ("action_vs_marked", "action_vs_official"):
        matches &= joined[f"{column}_selector"].fillna("").eq(
            joined[f"{column}_archive"].fillna("")
        )
    result = {
        (str(row.portfolio_kind), str(row.scenario), str(row.ticker)): bool(match)
        for row, match in zip(joined.itertuples(index=False), matches, strict=True)
    }
    return result, max_error


def selector_projection_error(
    comparison: pd.DataFrame, projection: pd.DataFrame
) -> tuple[dict[tuple[str, str, str], float], float, dict[str, float]]:
    projection = projection.copy()
    projection["ticker"] = projection["ticker"].map(normalize_ticker)
    errors: dict[tuple[str, str, str], float] = {}
    sums: dict[str, float] = {}
    max_error = 0.0
    for (kind, scenario), group in comparison.groupby(["portfolio_kind", "scenario"]):
        selected = projection.loc[
            projection["portfolio_kind"].eq(kind) & projection["scenario"].eq(scenario)
        ]
        weights = selected.groupby("ticker")["advisory_weight"].sum().to_dict()
        projected_sum = float(sum(finite(value) for value in weights.values()))
        for row in group.itertuples(index=False):
            expected = finite(weights.get(row.ticker))
            error = abs(finite(row.advisory_weight) - expected)
            errors[(str(kind), str(scenario), str(row.ticker))] = error
            max_error = max(max_error, error)
        sums[f"{kind}:{scenario}"] = projected_sum
    return errors, max_error, sums


def path_reason(advisory: float, operating: float, ticker: str) -> str:
    if ticker == "CASH":
        return "CASH_RECONCILED_SEPARATELY"
    if advisory > 1e-12 and operating <= 1e-12:
        return "ADVISORY_CREATED_AFTER_OPERATING_NO_WRITE"
    if advisory <= 1e-12 and operating > 1e-12:
        return "OPERATING_CREATED_BY_SEPARATE_EARLIER_SELECTOR"
    if advisory > 1e-12 and operating > 1e-12:
        return "PARALLEL_PATH_SELECTION_OVERLAP"
    return "NEITHER_CURRENT_PATH_SELECTED"


def build_cash_waterfall(
    stages: pd.DataFrame,
    comparison: pd.DataFrame,
    component_map: Mapping[str, str],
    paper_summaries: Mapping[str, Mapping[str, Any]],
    tolerance: float,
) -> tuple[pd.DataFrame, float]:
    rows: list[dict[str, Any]] = []
    max_error = 0.0
    for (kind, scenario), group in stages.groupby(["portfolio_kind", "scenario"], sort=True):
        cash = 1.0
        for (sequence, name), step in group.groupby(
            ["stage_sequence", "stage_name"], sort=True
        ):
            if str(name) not in component_map:
                raise ValueError(f"unregistered cash stage: {name}")
            cash_rows = step.loc[step["ticker"].map(normalize_ticker).eq("CASH")]
            stock_delta = float(
                pd.to_numeric(
                    step.loc[~step["ticker"].map(normalize_ticker).eq("CASH"), "weight_delta"],
                    errors="coerce",
                ).fillna(0.0).sum()
            )
            cash_delta = (
                float(pd.to_numeric(cash_rows["weight_delta"], errors="coerce").sum())
                if not cash_rows.empty
                else -stock_delta
            )
            before = cash
            after = before + cash_delta
            if not cash_rows.empty:
                declared_before = finite(cash_rows.iloc[-1]["before_weight"])
                declared_after = finite(cash_rows.iloc[-1]["after_weight"])
                max_error = max(max_error, abs(before - declared_before), abs(after - declared_after))
            rows.append(
                {
                    "path_kind": "advisory_selector",
                    "portfolio_kind": kind,
                    "scenario": scenario,
                    "stage_sequence": int(sequence),
                    "stage_name": name,
                    "cash_component": component_map[str(name)],
                    "cash_before_weight": before,
                    "cash_delta_weight": cash_delta,
                    "cash_after_weight": after,
                    "cash_usd": np.nan,
                    "explanation_complete": True,
                }
            )
            cash = after
        expected = finite(
            comparison.loc[
                comparison["portfolio_kind"].eq(kind)
                & comparison["scenario"].eq(scenario)
                & comparison["ticker"].map(normalize_ticker).eq("CASH"),
                "advisory_weight",
            ].sum()
        )
        max_error = max(max_error, abs(cash - expected))

    for kind, summary in paper_summaries.items():
        target_cash = finite(summary["target_cash_weight"])
        paper_cash = finite(summary["paper_cash_weight"])
        stages_out = [
            (1, "operating_target_allocation", "operating_target_cash", 1.0, target_cash),
            (
                2,
                "integer_share_bootstrap",
                "integer_share_rounding_residual",
                target_cash,
                paper_cash,
            ),
            (3, "transaction_cost_reserve", "transaction_cost_reserve", paper_cash, paper_cash),
            (
                4,
                "rejected_unresolved_orders",
                "rejected_unresolved_order_cash",
                paper_cash,
                paper_cash,
            ),
        ]
        for sequence, name, component, before, after in stages_out:
            rows.append(
                {
                    "path_kind": "operating_paper_bootstrap",
                    "portfolio_kind": kind,
                    "scenario": "operating_pipeline",
                    "stage_sequence": sequence,
                    "stage_name": name,
                    "cash_component": component,
                    "cash_before_weight": before,
                    "cash_delta_weight": after - before,
                    "cash_after_weight": after,
                    "cash_usd": finite(summary["paper_cash_usd"]) if sequence == 4 else np.nan,
                    "explanation_complete": True,
                }
            )
    return pd.DataFrame(rows), max_error


def blocked_manifest(
    output_dir: Path,
    contract_path: Path,
    source_audits: Mapping[str, Any],
    failures: list[str],
    started: float,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "contract_failures": sorted(set(failures)),
        "research_only": True,
        "review_only": True,
        "source_inputs": dict(source_audits),
        "contract": fingerprint(contract_path),
        "model_changed": False,
        "score_changed": False,
        "rank_changed": False,
        "selector_changed": False,
        "target_books_mutated": False,
        "cash_policy_changed": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def run_audit(contract_path: Path, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    if output_dir.exists():
        raise FileExistsError(f"append-only output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    contract = read_json(contract_path)
    failures: list[str] = []
    paths, source_audits = verified_source_files(contract, failures)
    if failures:
        return blocked_manifest(output_dir, contract_path, source_audits, failures, started)

    try:
        as_of_date = str(contract["as_of_date"])
        weight_tolerance = finite((contract.get("tolerances") or {}).get("selector_weight"), 1e-12)
        conservation_tolerance = finite(
            (contract.get("tolerances") or {}).get("weight_conservation"), 1e-12
        )
        cash_tolerance = finite((contract.get("tolerances") or {}).get("cash_usd"), 0.01)

        selector = read_json(paths["selector_manifest"])
        archive = read_json(paths["decision_archive_manifest"])
        funnel = read_json(paths["candidate_funnel_manifest"])
        operating_summary = read_json(paths["operating_summary"])
        paper_summary = read_json(paths["paper_summary"])
        failures.extend(selector_safety_failures(selector))
        if str(selector.get("status") or "") != "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED":
            failures.append("selector_status")
        if str(selector.get("valuation_price_cutoff_date") or "") != as_of_date:
            failures.append("selector_date")
        if str(selector.get("pinned_policy_commit") or "") != str(
            contract.get("pinned_policy_commit") or ""
        ):
            failures.append("pinned_policy_commit")
        if any(
            not bool(row.get("exists")) or not bool(row.get("hash_matches"))
            for row in (selector.get("source_inputs") or {}).values()
            if isinstance(row, dict)
        ):
            failures.append("selector_source_hash_contract")
        scenario_keys = sorted((selector.get("scenario_summary") or {}).keys())
        if scenario_keys != sorted(contract.get("expected_scenario_keys") or []):
            failures.append("scenario_keys")
        if str(archive.get("status") or "") != "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY":
            failures.append("archive_status")
        if int((archive.get("history_counts") or {}).get("position") or 0) != int(
            contract.get("expected_archived_row_count") or 0
        ):
            failures.append("archive_position_count")
        if str(funnel.get("status") or "") != "READY_RESEARCH_ONLY_CANDIDATE_EVALUATION":
            failures.append("candidate_funnel_status")
        if str(operating_summary.get("status") or "") != "completed":
            failures.append("operating_summary_status")
        if str(paper_summary.get("status") or "") != "completed":
            failures.append("paper_summary_status")

        comparison_path, comparison_audit = verified_output(
            paths["selector_manifest"], selector, "marked_official_advisory_comparison"
        )
        projection_path, projection_audit = verified_output(
            paths["selector_manifest"], selector, "advisory_policy_projection"
        )
        stages_path, stages_audit = verified_output(
            paths["selector_manifest"], selector, "advisory_policy_stage_audit"
        )
        archive_positions_path, archive_positions_audit = verified_output(
            paths["decision_archive_manifest"], archive, "latest_positions"
        )
        queue_path, queue_audit = verified_output(
            paths["candidate_funnel_manifest"], funnel, "selector_reconciliation_queue"
        )
        source_audits.update(
            selector_comparison=comparison_audit,
            selector_projection=projection_audit,
            selector_stages=stages_audit,
            archived_positions=archive_positions_audit,
            selector_reconciliation_queue=queue_audit,
        )

        comparison = pd.read_csv(comparison_path)
        projection = pd.read_csv(projection_path)
        stages = pd.read_csv(stages_path)
        archived_positions = pd.read_csv(archive_positions_path)
        queue = pd.read_csv(queue_path)
        for frame in (comparison, projection, stages, archived_positions, queue):
            if "ticker" in frame:
                frame["ticker"] = frame["ticker"].map(normalize_ticker)

        expected_archived = int(contract.get("expected_archived_row_count") or 0)
        if len(comparison) != expected_archived:
            failures.append("selector_comparison_row_count")
        match_map, archive_max_error = archive_match_map(
            comparison, archived_positions, weight_tolerance
        )
        projection_errors, projection_max_error, scenario_weight_sums = selector_projection_error(
            comparison, projection
        )
        if not all(match_map.values()):
            failures.append("archived_row_reproduction")
        if projection_max_error > weight_tolerance:
            failures.append("selector_weight_reproduction")
        if any(abs(value - 1.0) > conservation_tolerance for value in scenario_weight_sums.values()):
            failures.append("selector_weight_conservation")

        operating_generated = parse_time(operating_summary.get("generated_at_utc"))
        selector_generated = parse_time(selector.get("generated_at_utc"))
        if selector_generated <= operating_generated:
            failures.append("selector_does_not_postdate_operating_book")

        operating: dict[str, pd.DataFrame] = {}
        paper_positions: dict[str, pd.DataFrame] = {}
        execution_rows: list[dict[str, Any]] = []
        paper_summaries: dict[str, dict[str, Any]] = {}
        for kind in ("main", "concentrated"):
            book_key = f"{kind}_operating_book"
            operating[kind] = load_operating_book(paths[book_key], as_of_date)
            stock_sum = float(operating[kind]["operating_weight"].sum())
            if abs(stock_sum - 1.0) > conservation_tolerance:
                failures.append(f"operating_weight_conservation:{kind}")
            paper_frame, paper_row = paper_state(
                kind, paths, operating[kind], as_of_date, cash_tolerance
            )
            paper_positions[kind] = paper_frame
            paper_summaries[kind] = paper_row
            paper_row["operating_target_sha256"] = source_audits[book_key]["sha256"]
            paper_row["target_hash_matches_operating_book"] = bool(
                paper_row["target_sha256"] == source_audits[book_key]["sha256"]
            )
            paper_row["operating_generated_at_utc"] = operating_generated.isoformat()
            paper_row["paper_generated_at_utc"] = str(paper_summary.get("generated_at_utc") or "")
            execution_rows.append(paper_row)
            if not paper_row["membership_exact"]:
                failures.append(f"paper_membership:{kind}")
            if not paper_row["share_count_exact"]:
                failures.append(f"paper_share_count:{kind}")
            if not paper_row["cash_exact_to_tolerance"]:
                failures.append(f"paper_cash:{kind}")
            if not paper_row["target_hash_matches_operating_book"]:
                failures.append(f"paper_target_hash:{kind}")
            if any(
                int(paper_row[key]) != 0
                for key in ("fill_count", "pending_order_count", "rejection_count", "event_sequence")
            ):
                failures.append(f"paper_not_bootstrap_noop:{kind}")

        long_rows: list[dict[str, Any]] = []
        for scenario_key in scenario_keys:
            kind, scenario = scenario_key.split(":", 1)
            comp = comparison.loc[
                comparison["portfolio_kind"].eq(kind) & comparison["scenario"].eq(scenario)
            ].copy()
            comp_map = {row.ticker: row for row in comp.itertuples(index=False)}
            operating_map = dict(
                zip(
                    operating[kind]["ticker"],
                    operating[kind]["operating_weight"],
                    strict=True,
                )
            )
            paper_map = {
                row.ticker: row for row in paper_positions[kind].itertuples(index=False)
            }
            tickers = sorted(set(comp_map) | set(operating_map) | set(paper_map) | {"CASH"})
            account_cash = finite(paper_summaries[kind]["paper_cash_weight"])
            for ticker in tickers:
                prior = comp_map.get(ticker)
                marked_weight = finite(getattr(prior, "marked_weight", 0.0))
                official_weight = finite(getattr(prior, "official_prior_weight", 0.0))
                advisory_weight = finite(getattr(prior, "advisory_weight", 0.0))
                operating_weight = 1.0 - sum(operating_map.values()) if ticker == "CASH" else finite(
                    operating_map.get(ticker)
                )
                paper = paper_map.get(ticker)
                paper_weight = account_cash if ticker == "CASH" else finite(
                    getattr(paper, "paper_weight", 0.0)
                )
                paper_shares = 0.0 if ticker == "CASH" else finite(
                    getattr(paper, "paper_shares", 0.0)
                )
                expected_shares = 0.0 if ticker == "CASH" else finite(
                    getattr(paper, "expected_bootstrap_shares", 0.0)
                )
                key = (kind, scenario, ticker)
                reason = path_reason(advisory_weight, operating_weight, ticker)
                long_rows.append(
                    {
                        "as_of_date": as_of_date,
                        "portfolio_kind": kind,
                        "scenario": scenario,
                        "ticker": ticker,
                        "in_archived_selector_union": key in match_map,
                        "archived_row_exact": bool(match_map.get(key, True)),
                        "marked_weight": marked_weight,
                        "official_prior_weight": official_weight,
                        "advisory_weight": advisory_weight,
                        "advisory_weight_reproduction_error": finite(projection_errors.get(key)),
                        "operating_weight": operating_weight,
                        "paper_weight": paper_weight,
                        "paper_shares": paper_shares,
                        "expected_bootstrap_shares": expected_shares,
                        "share_count_exact": paper_shares == expected_shares,
                        "advisory_selected": advisory_weight > 1e-12,
                        "operating_selected": operating_weight > 1e-12 and ticker != "CASH",
                        "paper_selected": paper_weight > 1e-12 and ticker != "CASH",
                        "advisory_to_operating_delta": operating_weight - advisory_weight,
                        "operating_to_paper_delta": paper_weight - operating_weight,
                        "action_vs_marked": str(getattr(prior, "action_vs_marked", "")),
                        "action_vs_official": str(getattr(prior, "action_vs_official", "")),
                        "causal_reason_code": reason,
                        "explanation_complete": True,
                        "execution_allowed": False,
                    }
                )
        provenance = pd.DataFrame(long_rows)
        allowed_reasons = set(map(str, contract.get("reason_codes") or []))
        unknown_reason_count = int((~provenance["causal_reason_code"].isin(allowed_reasons)).sum())
        if unknown_reason_count:
            failures.append("unknown_reason_code")

        expected_divergences = sorted(map(str, contract.get("expected_divergence_tickers") or []))
        actual_queue = sorted(queue["ticker"].dropna().map(normalize_ticker).unique())
        if actual_queue != expected_divergences:
            failures.append("divergence_queue_identity")
        divergence_rows: list[dict[str, Any]] = []
        for ticker in expected_divergences:
            rows = provenance.loc[
                provenance["ticker"].eq(ticker) & provenance["advisory_selected"]
            ]
            if rows.empty or rows["operating_selected"].any():
                failures.append(f"divergence_not_reproduced:{ticker}")
            reasons = sorted(rows["causal_reason_code"].unique())
            expected_reason = str(contract.get("divergence_reason_code") or "")
            if reasons != [expected_reason]:
                failures.append(f"divergence_reason:{ticker}")
            divergence_rows.append(
                {
                    "as_of_date": as_of_date,
                    "ticker": ticker,
                    "advisory_scenarios": "|".join(
                        sorted(
                            f"{row.portfolio_kind}:{row.scenario}"
                            for row in rows.itertuples(index=False)
                        )
                    ),
                    "advisory_selected": True,
                    "operating_selected": False,
                    "paper_selected": False,
                    "causal_reason_code": expected_reason,
                    "operating_generated_at_utc": operating_generated.isoformat(),
                    "advisory_generated_at_utc": selector_generated.isoformat(),
                    "advisory_postdates_operating_seconds": float(
                        (selector_generated - operating_generated).total_seconds()
                    ),
                    "selector_no_write_passed": bool(selector.get("selector_no_write_passed")),
                    "target_book_generation_allowed": bool(
                        selector.get("target_book_generation_allowed")
                    ),
                    "recoverable_implementation_defect_found": False,
                    "historical_replay_allowed": False,
                    "reconciliation_status": "RECONCILED_INTENTIONAL_REVIEW_ONLY_PATH_SEPARATION",
                }
            )
        divergence = pd.DataFrame(divergence_rows)

        availability = availability_audit(
            selector, paths["selector_manifest"], str(contract["decision_time_utc"])
        )
        availability_violations = int((~availability["available_by_decision"]).sum())
        if availability_violations:
            failures.append("future_input_availability")

        cash_waterfall, cash_stage_max_error = build_cash_waterfall(
            stages,
            comparison,
            contract.get("cash_component_by_stage") or {},
            paper_summaries,
            weight_tolerance,
        )
        if cash_stage_max_error > weight_tolerance:
            failures.append("cash_stage_reproduction")
        if not bool(cash_waterfall["explanation_complete"].all()):
            failures.append("cash_explanation_incomplete")

        execution = pd.DataFrame(execution_rows)
        if failures:
            return blocked_manifest(
                output_dir, contract_path, source_audits, failures, started
            )

        provenance_path = output_dir / "selector_provenance_long.csv"
        divergence_path = output_dir / "divergence_reconciliation.csv"
        cash_path = output_dir / "cash_waterfall.csv"
        execution_path = output_dir / "execution_persistence_ledger.csv"
        availability_path = output_dir / "input_availability_audit.csv"
        output_frame(
            provenance_path,
            provenance,
            ["portfolio_kind", "scenario", "ticker"],
        )
        output_frame(divergence_path, divergence, ["ticker"])
        output_frame(
            cash_path,
            cash_waterfall,
            ["path_kind", "portfolio_kind", "scenario", "stage_sequence"],
        )
        output_frame(execution_path, execution, ["portfolio_kind"])
        output_frame(availability_path, availability, ["source_label"])

        output_paths = {
            "selector_provenance_long": provenance_path,
            "divergence_reconciliation": divergence_path,
            "cash_waterfall": cash_path,
            "execution_persistence_ledger": execution_path,
            "input_availability_audit": availability_path,
        }
        outputs = {key: fingerprint(path) for key, path in output_paths.items()}
        archived_explained = int(
            provenance.loc[provenance["in_archived_selector_union"], "explanation_complete"].sum()
        )
        share_exact = int(execution["share_count_exact_count"].sum())
        share_expected = int(execution["share_count_expected_count"].sum())
        max_cash_error = float(execution["cash_error_usd"].abs().max())
        payload = {
            "schema_version": SCHEMA_VERSION,
            "status": READY_STATUS,
            "research_only": True,
            "review_only": True,
            "as_of_date": as_of_date,
            "pinned_policy_commit": str(selector.get("pinned_policy_commit") or ""),
            "contract_failures": [],
            "p0_conclusion": "INTENTIONAL_PARALLEL_REVIEW_ONLY_PATH_NO_RECOVERABLE_DEFECT",
            "recoverable_implementation_leakage_count": 0,
            "selector_generated_after_operating_seconds": float(
                (selector_generated - operating_generated).total_seconds()
            ),
            "coverage": {
                "archived_selector_row_count": int(len(comparison)),
                "archived_selector_row_exact_count": int(sum(match_map.values())),
                "archived_selector_row_explained_count": archived_explained,
                "provenance_union_row_count": int(len(provenance)),
                "scenario_count": int(len(scenario_keys)),
                "scenario_weight_conservation_pass_count": int(
                    sum(abs(value - 1.0) <= conservation_tolerance for value in scenario_weight_sums.values())
                ),
                "selector_weight_max_abs_error": projection_max_error,
                "archive_weight_max_abs_error": archive_max_error,
                "divergence_expected_count": int(len(expected_divergences)),
                "divergence_reconciled_count": int(len(divergence)),
                "unknown_or_other_reason_count": unknown_reason_count,
                "availability_row_count": int(len(availability)),
                "availability_violation_count": availability_violations,
                "paper_share_exact_count": share_exact,
                "paper_share_expected_count": share_expected,
                "paper_cash_max_abs_error_usd": max_cash_error,
                "cash_stage_max_abs_error": cash_stage_max_error,
            },
            "interpretation": {
                "advisory_operating_divergence_is_new_alpha_evidence": False,
                "historical_cagr_mdd_evidence_changed": False,
                "operating_selector_causal_taxonomy_complete": False,
                "current_divergence_cause": "the operating book was created earlier by a separate selector path; the later advisory selector was explicitly no-write",
                "recommended_next_step": "do not replay; preserve this integrity result, continue the forward archive, and move the next bounded gate to PIT estimate/guidance sample validation",
            },
            "model_changed": False,
            "score_changed": False,
            "rank_changed": False,
            "selector_changed": False,
            "selector_executed": False,
            "target_books_mutated": False,
            "cash_policy_changed": False,
            "orders_generated": False,
            "backtest_executed": False,
            "fullrun_executed": False,
            "production_activation_allowed": False,
            "live_trading_enabled": False,
            "source_inputs": source_audits,
            "contract": fingerprint(contract_path),
            "outputs": outputs,
            "semantic_output_hashes": {
                key: record["sha256"] for key, record in outputs.items()
            },
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "performance": {"elapsed_seconds": time.perf_counter() - started},
            "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
        }
        report = [
            "# Run287 selector provenance audit",
            "",
            f"Status: `{READY_STATUS}`.",
            "",
            f"- archived selector rows reproduced: `{sum(match_map.values())}/{len(comparison)}`",
            f"- preregistered divergences reconciled: `{len(divergence)}/{len(expected_divergences)}`",
            f"- union rows explained: `{len(provenance)}`",
            f"- selector max weight error: `{projection_max_error:.3e}`",
            f"- paper share counts exact: `{share_exact}/{share_expected}`",
            f"- paper cash max error: `${max_cash_error:.6f}`",
            f"- future availability violations: `{availability_violations}`",
            "",
            "The five-name divergence is not a recovered alpha defect. The operating book was generated first by a separate selector path; the later advisory packet was review-only and contractually unable to write targets or orders.",
            "",
            "No model, score, rank, selector, target, cash policy, order, backtest, fullrun, production, or live-trading state changed.",
        ]
        (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        payload["outputs"]["report"] = fingerprint(output_dir / "report.md")
        write_json(output_dir / "manifest.json", payload)
        return payload
    except Exception as exc:
        failures.append(f"exception:{type(exc).__name__}:{exc}")
        return blocked_manifest(output_dir, contract_path, source_audits, failures, started)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        default="docs/run287_selector_provenance_audit_contract_v1.json",
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = repo_path(args.contract)
    output_dir = repo_path(args.output_dir)
    payload = run_audit(contract_path, output_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
