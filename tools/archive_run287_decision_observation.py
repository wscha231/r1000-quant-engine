#!/usr/bin/env python3
"""Archive exact-close Run287 selector and proposed-candidate risk observations.

This tool never creates a selector packet.  It accepts only already validated,
no-write selector and candidate-risk packets for the same completed close,
normalizes their decision semantics, and appends idempotent JSONL observations.
It cannot alter books, cash, orders, historical evidence, or production state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.build_run287_candidate_risk_watch import candidate_metadata  # noqa: E402
from tools.build_run287_holding_risk_watch import (  # noqa: E402
    canonical_hash,
    json_default,
    read_json,
    sha256_file,
    write_json,
)


SCHEMA_VERSION = "run287-decision-observation-archive-v1"
READY_STATUS = "READY_DECISION_OBSERVATION_ARCHIVE_REVIEW_ONLY"
SKIPPED_STATUS = "SKIPPED_NO_EXACT_SELECTOR_RISK_PACKET"
BLOCKED_STATUS = "BLOCKED_DECISION_OBSERVATION_ARCHIVE"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": bool(path.exists()),
        "bytes": int(path.stat().st_size) if path.exists() and path.is_file() else 0,
        "sha256": sha256_file(path) if path.exists() and path.is_file() else "",
    }


def normalize_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    if text in {"", "NAN", "NONE"}:
        return ""
    return "CASH" if text in {"CASH", "__CASH__"} else text


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def boolean_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    return series.map(
        lambda value: str(value).strip().lower() in {"1", "true", "yes", "y"}
    )


def portable_output(
    owner_path: Path, owner: Mapping[str, Any], key: str
) -> tuple[Path, dict[str, Any]]:
    record = (owner.get("outputs") or {}).get(key) or {}
    raw = str(record.get("path") or "")
    expected = str(record.get("sha256") or "")
    original = Path(raw) if raw else Path()
    candidates: list[Path] = []
    if raw:
        candidates.append(original if original.is_absolute() else owner_path.parent / original)
        candidates.append(owner_path.parent / original.name)
    seen: set[str] = set()
    for path in candidates:
        token = str(path)
        if token in seen:
            continue
        seen.add(token)
        if path.exists() and path.is_file() and expected and sha256_file(path) == expected:
            row = fingerprint(path)
            row.update(label=key, expected_sha256=expected, hash_matches=True)
            return path, row
    raise ValueError(f"verified output unavailable or changed: {key}")


def is_risk_intersection_selector(manifest: Mapping[str, Any]) -> bool:
    scenarios = manifest.get("scenario_summary") or {}
    if not isinstance(scenarios, dict) or not scenarios:
        return False
    required = {
        "risk_watch_promotion_allowed",
        "proposed_new_entry_without_risk_watch_count",
        "incremental_buy_risk_review_conflict_count",
    }
    return all(required.issubset(set(row)) for row in scenarios.values() if isinstance(row, dict))


def discover_packet(
    root: Path, valuation_date: str
) -> tuple[Path | None, Path | None, list[str]]:
    selector_matches: list[Path] = []
    risk_matches: list[Path] = []
    if root.exists():
        for path in root.glob("run287_current_selector_no_write*/manifest.json"):
            payload = read_json(path)
            if (
                payload.get("status") == "READY_CURRENT_SELECTOR_NO_WRITE_REVIEW_REQUIRED"
                and str(payload.get("valuation_price_cutoff_date") or "") == valuation_date
                and is_risk_intersection_selector(payload)
            ):
                selector_matches.append(path)
        for path in root.glob("run287_candidate_risk_watch*/summary.json"):
            payload = read_json(path)
            if (
                str(payload.get("status") or "").startswith("READY_CANDIDATE_RISK_REVIEW_ONLY")
                and str(payload.get("as_of_date") or "") == valuation_date
            ):
                risk_matches.append(path)
    failures: list[str] = []
    if len(selector_matches) != 1:
        failures.append(f"selector_discovery_count:{len(selector_matches)}")
    if len(risk_matches) != 1:
        failures.append(f"candidate_risk_discovery_count:{len(risk_matches)}")
    return (
        selector_matches[0] if len(selector_matches) == 1 else None,
        risk_matches[0] if len(risk_matches) == 1 else None,
        failures,
    )


def contract_identity(
    selector: Mapping[str, Any], risk: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, Any]:
    frozen = contract["frozen_identity"]
    selector_contract = (selector.get("source_inputs") or {}).get(
        "selector_contract_manifest", {}
    )
    risk_inputs = risk.get("source_inputs") or {}
    return {
        "pinned_policy_commit": str(selector.get("pinned_policy_commit") or ""),
        "selector_contract_manifest_sha256": str(selector_contract.get("sha256") or ""),
        "holding_risk_contract_sha256": str(
            (risk_inputs.get("base_contract") or {}).get("sha256") or ""
        ),
        "candidate_risk_contract_sha256": str(
            (risk_inputs.get("candidate_contract") or {}).get("sha256") or ""
        ),
        "scenario_keys": sorted((selector.get("scenario_summary") or {}).keys()),
        "expected": {
            "pinned_policy_commit": str(frozen["pinned_policy_commit"]),
            "selector_contract_manifest_sha256": str(
                frozen["selector_contract_manifest_sha256"]
            ),
            "holding_risk_contract_sha256": str(frozen["holding_risk_contract_sha256"]),
            "candidate_risk_contract_sha256": str(
                frozen["candidate_risk_contract_sha256"]
            ),
            "scenario_keys": sorted(frozen["scenario_keys"]),
        },
    }


def identity_failures(identity: Mapping[str, Any]) -> list[str]:
    expected = identity["expected"]
    return [
        f"frozen_identity:{key}"
        for key in (
            "pinned_policy_commit",
            "selector_contract_manifest_sha256",
            "holding_risk_contract_sha256",
            "candidate_risk_contract_sha256",
            "scenario_keys",
        )
        if identity.get(key) != expected.get(key)
    ]


def safety_failures(selector: Mapping[str, Any], risk: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    selector_false = (
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
    risk_false = (
        "orders_generated",
        "target_books_mutated",
        "selector_weights_changed",
        "cash_policy_changed",
        "historical_cagr_mdd_evidence_changed",
        "backtest_executed",
        "fullrun_executed",
        "production_activation_allowed",
        "live_trading_enabled",
    )
    failures.extend(f"selector_safety:{key}" for key in selector_false if bool(selector.get(key)))
    failures.extend(f"risk_safety:{key}" for key in risk_false if bool(risk.get(key)))
    if bool((selector.get("review_gate") or {}).get("portfolio_transition_promotion_allowed")):
        failures.append("selector_promotion_allowed")
    if bool((risk.get("interpretation") or {}).get("portfolio_transition_allowed")):
        failures.append("candidate_risk_transition_allowed")
    return failures


def event_id(kind: str, as_of_date: str, dimensions: Mapping[str, Any]) -> str:
    return canonical_hash(
        {
            "schema": SCHEMA_VERSION,
            "kind": kind,
            "as_of_date": as_of_date,
            **dict(dimensions),
        }
    )


def build_records(
    *,
    selector: Mapping[str, Any],
    risk: Mapping[str, Any],
    comparison: pd.DataFrame,
    candidate_risk: pd.DataFrame,
    contract: Mapping[str, Any],
    contract_sha256: str,
    as_of_date: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    failures: list[str] = []
    required_comparison = {
        "ticker",
        "portfolio_kind",
        "scenario",
        "marked_weight",
        "official_prior_weight",
        "advisory_weight",
        "delta_vs_marked",
        "delta_vs_official",
        "action_vs_marked",
        "action_vs_official",
        "execution_allowed",
        "held_risk_state",
        "held_risk_advisory_action",
        "held_risk_reason_codes",
    }
    required_risk = {
        "ticker",
        "as_of_date",
        "risk_state",
        "advisory_action",
        "reason_codes",
        "price_exact_asof",
        "normal_state_is_not_alpha_evidence",
        "portfolio_transition_allowed",
        "orders_generated",
        "target_books_mutated",
        "selector_weights_changed",
        "cash_policy_changed",
        "production_activation_allowed",
        "live_trading_enabled",
    }
    missing_comparison = sorted(required_comparison - set(comparison.columns))
    missing_risk = sorted(required_risk - set(candidate_risk.columns))
    if missing_comparison:
        failures.append(f"comparison_columns:{','.join(missing_comparison)}")
    if missing_risk:
        failures.append(f"risk_columns:{','.join(missing_risk)}")
    if failures:
        return {}, failures

    comparison = comparison.copy()
    comparison["ticker"] = comparison["ticker"].map(normalize_ticker)
    comparison["portfolio_kind"] = comparison["portfolio_kind"].astype(str).str.lower().str.strip()
    comparison["scenario"] = comparison["scenario"].astype(str).str.strip()
    for column in (
        "marked_weight",
        "official_prior_weight",
        "advisory_weight",
        "delta_vs_marked",
        "delta_vs_official",
    ):
        comparison[column] = pd.to_numeric(comparison[column], errors="coerce")
    if comparison[list(required_comparison & set(comparison.columns))].empty:
        failures.append("comparison_empty")
    if comparison["ticker"].eq("").any():
        failures.append("comparison_blank_ticker")
    if comparison.duplicated(["portfolio_kind", "scenario", "ticker"]).any():
        failures.append("comparison_duplicate_key")
    comparison_scenarios = sorted(
        {
            f"{portfolio}:{scenario}"
            for portfolio, scenario in comparison[
                ["portfolio_kind", "scenario"]
            ].itertuples(index=False, name=None)
        }
    )
    expected_scenarios = sorted(contract["frozen_identity"]["scenario_keys"])
    if comparison_scenarios != expected_scenarios:
        failures.append(
            f"comparison_scenarios:{','.join(comparison_scenarios)}"
        )
    if boolean_series(comparison["execution_allowed"]).any():
        failures.append("comparison_execution_allowed")
    for key, group in comparison.groupby(["portfolio_kind", "scenario"], sort=True):
        total = float(group["advisory_weight"].sum())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            failures.append(f"advisory_weight_sum:{key}:{total}")

    candidates = candidate_metadata(comparison)
    candidate_set = set(candidates["ticker"]) if not candidates.empty else set()
    candidate_risk = candidate_risk.copy()
    candidate_risk["ticker"] = candidate_risk["ticker"].map(normalize_ticker)
    risk_set = set(candidate_risk["ticker"])
    if candidate_set != risk_set:
        failures.append(
            f"candidate_set:{','.join(sorted(candidate_set))}!={','.join(sorted(risk_set))}"
        )
    if candidate_risk["ticker"].eq("").any() or candidate_risk["ticker"].eq("CASH").any():
        failures.append("candidate_risk_invalid_ticker")
    if candidate_risk["ticker"].duplicated().any():
        failures.append("candidate_risk_duplicate_ticker")
    if int(risk.get("candidate_count", -1)) != len(candidate_risk):
        failures.append(
            f"candidate_risk_count:{len(candidate_risk)}!={risk.get('candidate_count')}"
        )
    allowed_states = {"ALERT", "WATCH", "NORMAL", "DATA_INSUFFICIENT"}
    observed_states = set(candidate_risk["risk_state"].astype(str))
    if not observed_states.issubset(allowed_states):
        failures.append(
            f"candidate_risk_states:{','.join(sorted(observed_states - allowed_states))}"
        )
    if not candidate_risk["as_of_date"].astype(str).eq(as_of_date).all():
        failures.append("candidate_risk_date_mismatch")
    if not boolean_series(candidate_risk["price_exact_asof"]).all():
        failures.append("candidate_risk_nonexact_close")
    for column in (
        "portfolio_transition_allowed",
        "orders_generated",
        "target_books_mutated",
        "selector_weights_changed",
        "cash_policy_changed",
        "production_activation_allowed",
        "live_trading_enabled",
    ):
        if boolean_series(candidate_risk[column]).any():
            failures.append(f"candidate_risk_row_safety:{column}")
    if failures:
        return {}, failures

    iso = pd.Timestamp(as_of_date).isocalendar()
    iso_week = f"{int(iso.year):04d}-W{int(iso.week):02d}"
    common = {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": as_of_date,
        "iso_decision_week": iso_week,
        "archive_contract_sha256": contract_sha256,
        "pinned_policy_commit": str(selector.get("pinned_policy_commit") or ""),
        "review_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "historical_cagr_mdd_evidence_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }

    risk_map = candidate_risk.set_index("ticker")
    position_rows: list[dict[str, Any]] = []
    for source in comparison.sort_values(["portfolio_kind", "scenario", "ticker"]).to_dict(
        "records"
    ):
        ticker = str(source["ticker"])
        is_new = bool(
            ticker != "CASH"
            and finite(source.get("advisory_weight")) > 1e-12
            and finite(source.get("marked_weight")) <= 1e-12
        )
        candidate_row = risk_map.loc[ticker] if is_new else None
        row = {
            **common,
            "record_kind": "selector_position",
            "portfolio_kind": str(source["portfolio_kind"]),
            "scenario": str(source["scenario"]),
            "ticker": ticker,
            "marked_weight": finite(source.get("marked_weight")),
            "official_prior_weight": finite(source.get("official_prior_weight")),
            "advisory_weight": finite(source.get("advisory_weight")),
            "delta_vs_marked": finite(source.get("delta_vs_marked")),
            "delta_vs_official": finite(source.get("delta_vs_official")),
            "action_vs_marked": str(source.get("action_vs_marked") or ""),
            "action_vs_official": str(source.get("action_vs_official") or ""),
            "held_risk_state": str(source.get("held_risk_state") or ""),
            "held_risk_advisory_action": str(source.get("held_risk_advisory_action") or ""),
            "held_risk_reason_codes": str(source.get("held_risk_reason_codes") or ""),
            "proposed_new_entry": is_new,
            "candidate_risk_state": str(candidate_row.get("risk_state") or "")
            if candidate_row is not None
            else "",
            "candidate_risk_advisory_action": str(candidate_row.get("advisory_action") or "")
            if candidate_row is not None
            else "",
            "candidate_risk_reason_codes": str(candidate_row.get("reason_codes") or "")
            if candidate_row is not None
            else "",
            "selector_weight_changed_by_archive": False,
        }
        row["event_id"] = event_id(
            "selector_position",
            as_of_date,
            {
                "portfolio_kind": row["portfolio_kind"],
                "scenario": row["scenario"],
                "ticker": ticker,
            },
        )
        position_rows.append(row)

    scenario_rows: list[dict[str, Any]] = []
    for key in sorted((selector.get("scenario_summary") or {})):
        portfolio, scenario = key.split(":", 1)
        metrics = selector["scenario_summary"][key]
        row = {
            **common,
            "record_kind": "selector_scenario",
            "portfolio_kind": portfolio,
            "scenario": scenario,
            **{
                name: value
                for name, value in metrics.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            },
        }
        row["event_id"] = event_id(
            "selector_scenario",
            as_of_date,
            {"portfolio_kind": portfolio, "scenario": scenario},
        )
        scenario_rows.append(row)

    candidate_rows: list[dict[str, Any]] = []
    keep = (
        "ticker",
        "risk_state",
        "advisory_action",
        "reason_codes",
        "history_observations",
        "return_1d",
        "spy_excess_return_1d",
        "return_21d",
        "spy_excess_return_21d",
        "drawdown_63d",
        "volatility_ratio_21d_126d",
        "idiosyncratic_shock",
        "opening_gap_shock",
        "trend_damage",
        "drawdown_damage",
        "volatility_spike",
        "data_reason",
        "forward_outcome_status",
    )
    for source in candidate_risk.sort_values("ticker").to_dict("records"):
        row = {
            **common,
            "record_kind": "candidate_risk",
            **{name: source.get(name) for name in keep},
            "normal_state_is_not_alpha_evidence": True,
            "risk_state_may_authorize_buy": False,
            "selector_weight_changed_by_archive": False,
        }
        row["event_id"] = event_id(
            "candidate_risk", as_of_date, {"ticker": str(source["ticker"])}
        )
        candidate_rows.append(row)

    normalized_hashes = {
        "position_set_sha256": canonical_hash({"rows": position_rows}),
        "scenario_set_sha256": canonical_hash({"rows": scenario_rows}),
        "candidate_risk_set_sha256": canonical_hash({"rows": candidate_rows}),
    }
    decision_row = {
        **common,
        "record_kind": "decision_close",
        "scenario_count": len(scenario_rows),
        "position_row_count": len(position_rows),
        "candidate_count": len(candidate_rows),
        "alert_count": int(candidate_risk["risk_state"].eq("ALERT").sum()),
        "watch_count": int(candidate_risk["risk_state"].eq("WATCH").sum()),
        "data_insufficient_count": int(
            candidate_risk["risk_state"].eq("DATA_INSUFFICIENT").sum()
        ),
        "normal_count": int(candidate_risk["risk_state"].eq("NORMAL").sum()),
        **normalized_hashes,
        "archive_may_promote": False,
        "resolved_forward_outcomes_required": bool(
            contract["review_gates"]["resolved_forward_outcomes_required"]
        ),
    }
    decision_row["event_id"] = event_id("decision_close", as_of_date, {})
    return {
        "decision": [decision_row],
        "scenario": scenario_rows,
        "position": position_rows,
        "candidate_risk": candidate_rows,
    }, []


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict) or not payload.get("event_id"):
            raise ValueError(f"invalid archive row: {path}:{line_number}")
        rows.append(payload)
    return rows


def prepare_append(
    path: Path, rows: Iterable[Mapping[str, Any]], as_of_date: str, contract_sha256: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing = load_history(path)
    existing_map: dict[str, dict[str, Any]] = {}
    for payload in existing:
        event = str(payload["event_id"])
        if event in existing_map and canonical_hash(existing_map[event]) != canonical_hash(payload):
            raise ValueError(f"existing archive duplicate changed: {event}")
        existing_map[event] = payload
        if str(payload.get("archive_contract_sha256") or "") != contract_sha256:
            raise ValueError("archive contract drift")
    existing_dates = [str(row.get("as_of_date") or "") for row in existing if row.get("as_of_date")]
    if existing_dates and as_of_date < max(existing_dates):
        raise ValueError(f"out-of-order observation:{as_of_date}<{max(existing_dates)}")
    new_rows: list[dict[str, Any]] = []
    for raw in rows:
        payload = json.loads(json.dumps(dict(raw), default=json_default))
        event = str(payload["event_id"])
        if event in existing_map:
            if canonical_hash(existing_map[event]) != canonical_hash(payload):
                raise ValueError(f"same-date decision observation changed: {event}")
            continue
        existing_map[event] = payload
        new_rows.append(payload)
    return existing, new_rows


def append_rows(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    payloads = list(rows)
    if not payloads:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for payload in payloads:
            handle.write(
                json.dumps(
                    dict(payload), sort_keys=True, separators=(",", ":"), default=json_default
                )
                + "\n"
            )
    return len(payloads)


def blocked(
    output_dir: Path,
    failures: list[str],
    sources: Mapping[str, Any],
    started: float,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "archive_passed": False,
        "contract_failures": failures,
        "review_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "historical_cagr_mdd_evidence_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(sources),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def skipped(output_dir: Path, failures: list[str], started: float) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": SKIPPED_STATUS,
        "archive_passed": False,
        "contract_failures": failures,
        "review_only": True,
        "portfolio_transition_allowed": False,
        "orders_generated": False,
        "target_books_mutated": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "last_ingestion.json", payload)
    return payload


def sources_unchanged(sources: Mapping[str, Mapping[str, Any]]) -> bool:
    for row in sources.values():
        raw = str(row.get("path") or "")
        baseline = str(row.get("sha256") or "")
        if not raw or not baseline:
            return False
        path = Path(raw)
        if not path.exists() or sha256_file(path) != baseline:
            return False
    return True


def render_report(payload: Mapping[str, Any], decision: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# Run287 decision observation archive",
            "",
            f"- status: `{payload['status']}`",
            f"- latest completed close: `{payload['latest_as_of_date']}`",
            f"- decision dates / ISO weeks: `{payload['distinct_decision_date_count']} / {payload['distinct_decision_week_count']}`",
            f"- current candidate ALERT / WATCH / INSUFFICIENT / NORMAL: `{decision['alert_count']} / {decision['watch_count']} / {decision['data_insufficient_count']} / {decision['normal_count']}`",
            f"- early 4-week review ready: `{str(payload['early_stability_review_ready']).lower()}`",
            f"- 12-week minimum gate met: `{str(payload['minimum_week_gate_met']).lower()}`",
            "- review-only archive; NORMAL is not buy evidence and the archive cannot promote",
            "- no selector weight, target book, cash, order, backtest, fullrun, production, or live-trading mutation",
            "",
        ]
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = repo_path(args.contract)
    contract = read_json(contract_path)
    sources: dict[str, Any] = {"archive_contract": fingerprint(contract_path)}
    failures: list[str] = []
    if contract.get("schema_version") != "run287-decision-observation-archive-contract-v1":
        failures.append("archive_contract_schema")
    contract_sha256 = sha256_file(contract_path)
    if args.expected_contract_sha256 and contract_sha256 != args.expected_contract_sha256:
        failures.append("archive_contract_hash")
    if failures:
        return blocked(output_dir, failures, sources, started)

    selector_path = repo_path(args.selector_manifest) if args.selector_manifest else None
    risk_path = repo_path(args.candidate_risk_summary) if args.candidate_risk_summary else None
    if selector_path is None or risk_path is None:
        selector_path, risk_path, discovery_failures = discover_packet(
            repo_path(args.discover_root), args.valuation_date
        )
        if discovery_failures:
            if args.allow_missing:
                return skipped(output_dir, discovery_failures, started)
            return blocked(output_dir, discovery_failures, sources, started)
    assert selector_path is not None and risk_path is not None
    sources["selector_manifest"] = fingerprint(selector_path)
    sources["candidate_risk_summary"] = fingerprint(risk_path)
    if args.expected_selector_sha256 and sources["selector_manifest"]["sha256"] != args.expected_selector_sha256:
        failures.append("selector_manifest_hash")
    if args.expected_candidate_risk_sha256 and sources["candidate_risk_summary"]["sha256"] != args.expected_candidate_risk_sha256:
        failures.append("candidate_risk_summary_hash")
    if failures:
        return blocked(output_dir, failures, sources, started)

    selector = read_json(selector_path)
    risk = read_json(risk_path)
    required = contract["required_statuses"]
    if selector.get("status") != required["selector"]:
        failures.append(f"selector_status:{selector.get('status')}")
    if risk.get("status") not in set(required["candidate_risk"]):
        failures.append(f"candidate_risk_status:{risk.get('status')}")
    if str(selector.get("valuation_price_cutoff_date") or "") != args.valuation_date:
        failures.append("selector_date")
    if str(risk.get("as_of_date") or "") != args.valuation_date:
        failures.append("candidate_risk_date")
    failures.extend(safety_failures(selector, risk))
    identity = contract_identity(selector, risk, contract)
    failures.extend(identity_failures(identity))
    if any(
        not isinstance(value, dict)
        for value in (selector.get("scenario_summary") or {}).values()
    ):
        failures.append("selector_scenario_summary_shape")
    if failures:
        return blocked(output_dir, failures, sources, started)

    try:
        comparison_path, sources["selector_comparison"] = portable_output(
            selector_path, selector, "marked_official_advisory_comparison"
        )
        candidate_path, sources["candidate_risk_watch"] = portable_output(
            risk_path, risk, "candidate_risk_watch"
        )
    except Exception as exc:
        failures.append(f"source_output:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, sources, started)
    comparison = pd.read_csv(comparison_path, low_memory=False)
    candidate_risk = pd.read_csv(candidate_path, low_memory=False)
    records, record_failures = build_records(
        selector=selector,
        risk=risk,
        comparison=comparison,
        candidate_risk=candidate_risk,
        contract=contract,
        contract_sha256=contract_sha256,
        as_of_date=args.valuation_date,
    )
    failures.extend(record_failures)
    if not sources_unchanged(sources):
        failures.append("source_inputs_mutated_during_normalization")
    if failures:
        return blocked(output_dir, failures, sources, started)

    paths = {
        "decision": output_dir / "decision_history.jsonl",
        "scenario": output_dir / "scenario_history.jsonl",
        "position": output_dir / "position_history.jsonl",
        "candidate_risk": output_dir / "candidate_risk_history.jsonl",
    }
    prepared: dict[str, list[dict[str, Any]]] = {}
    existing: dict[str, list[dict[str, Any]]] = {}
    try:
        for kind, path in paths.items():
            old, new = prepare_append(
                path, records[kind], args.valuation_date, contract_sha256
            )
            existing[kind] = old
            prepared[kind] = new
    except Exception as exc:
        failures.append(f"append_preflight:{type(exc).__name__}:{exc}")
        return blocked(output_dir, failures, sources, started)

    appended = {kind: append_rows(paths[kind], rows) for kind, rows in prepared.items()}
    all_decisions = existing["decision"] + prepared["decision"]
    dates = sorted({str(row["as_of_date"]) for row in all_decisions})
    weeks = sorted({str(row["iso_decision_week"]) for row in all_decisions})
    latest_decision = max(all_decisions, key=lambda row: str(row["as_of_date"]))
    gates = contract["review_gates"]
    early_ready = len(weeks) >= int(gates["early_stability_review_distinct_weeks"])
    minimum_weeks = len(weeks) >= int(
        gates["minimum_distinct_weeks_before_any_promotion_review"]
    )

    latest_positions = pd.DataFrame(records["position"])
    latest_scenarios = pd.DataFrame(records["scenario"])
    latest_candidates = pd.DataFrame(records["candidate_risk"])
    latest_positions.to_csv(output_dir / "latest_positions.csv", index=False)
    latest_scenarios.to_csv(output_dir / "latest_scenarios.csv", index=False)
    latest_candidates.to_csv(output_dir / "latest_candidate_risk.csv", index=False)
    if not sources_unchanged(sources):
        failures.append("source_inputs_mutated_during_archive_write")
        return blocked(output_dir, failures, sources, started)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "archive_passed": True,
        "contract_failures": [],
        "latest_as_of_date": dates[-1],
        "latest_iso_decision_week": str(latest_decision["iso_decision_week"]),
        "distinct_decision_date_count": len(dates),
        "distinct_decision_week_count": len(weeks),
        "decision_dates": dates,
        "decision_weeks": weeks,
        "appended_counts": appended,
        "history_counts": {
            kind: len(existing[kind]) + len(prepared[kind]) for kind in paths
        },
        "current_candidate_state_counts": {
            "ALERT": int(latest_decision["alert_count"]),
            "WATCH": int(latest_decision["watch_count"]),
            "DATA_INSUFFICIENT": int(latest_decision["data_insufficient_count"]),
            "NORMAL": int(latest_decision["normal_count"]),
        },
        "early_stability_review_ready": early_ready,
        "minimum_week_gate_met": minimum_weeks,
        "resolved_forward_outcomes_gate_met": False,
        "archive_may_promote": False,
        "interpretation": {
            "normal_state_is_not_alpha_evidence": True,
            "portfolio_transition_allowed": False,
            "historical_cagr_mdd_evidence_changed": False,
        },
        "review_only": True,
        "orders_generated": False,
        "target_books_mutated": False,
        "selector_weights_changed": False,
        "cash_policy_changed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "frozen_identity": identity,
        "source_inputs": sources,
        "outputs": {
            **{f"{kind}_history": fingerprint(path) for kind, path in paths.items()},
            "latest_positions": fingerprint(output_dir / "latest_positions.csv"),
            "latest_scenarios": fingerprint(output_dir / "latest_scenarios.csv"),
            "latest_candidate_risk": fingerprint(output_dir / "latest_candidate_risk.csv"),
        },
        "recommended_next_step": "append unchanged exact-close packets; review stability after four distinct ISO weeks and never promote before twelve weeks plus resolved forward outcomes",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    (output_dir / "report.md").write_text(
        render_report(payload, latest_decision), encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector-manifest")
    parser.add_argument("--expected-selector-sha256", default="")
    parser.add_argument("--candidate-risk-summary")
    parser.add_argument("--expected-candidate-risk-sha256", default="")
    parser.add_argument("--discover-root", default="outputs")
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument(
        "--contract", default="docs/run287_decision_observation_archive_contract.json"
    )
    parser.add_argument("--expected-contract-sha256", default="")
    parser.add_argument(
        "--output-dir", default="outputs/run287_decision_observation_archive"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build(args)
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "latest_as_of_date": payload.get("latest_as_of_date"),
                "distinct_decision_week_count": payload.get(
                    "distinct_decision_week_count", 0
                ),
                "appended_counts": payload.get("appended_counts", {}),
                "archive_may_promote": payload.get("archive_may_promote", False),
            },
            sort_keys=True,
        )
    )
    return 0 if payload.get("status") in {READY_STATUS, SKIPPED_STATUS} else 2


if __name__ == "__main__":
    raise SystemExit(main())
