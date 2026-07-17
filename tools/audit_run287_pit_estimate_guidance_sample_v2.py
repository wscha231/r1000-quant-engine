#!/usr/bin/env python3
"""Audit the strict Run287 50-security/200-event PIT sample contract.

The gate validates procurement evidence only. It never computes returns or
alpha, authorizes a purchase, changes a universe/book/order, or starts a
fullrun. A separate local-inventory mode records why the existing forward-only
snapshot is not historical PIT evidence without converting or fabricating it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-pit-estimate-guidance-sample-audit-v2"
DEFAULT_CONTRACT = "docs/run287_pit_estimate_guidance_sample_contract_v2.json"
DEFAULT_OUTPUT = "outputs/run287_pit_estimate_guidance_sample_audit_v2"
EXACT_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$"
)
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def clean_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def text_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].fillna("").astype(str).str.strip()


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    observed: Any,
    required: Any,
    category: str,
    detail: str,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "category": category,
            "observed": observed,
            "required": required,
            "detail": detail,
        }
    )


def selection_hash(seed: str, row: pd.Series) -> str:
    fields = [
        row["security_id"],
        row["event_type"],
        row["metric"],
        row["fiscal_period_end"],
        row["fiscal_period_type"],
        row["decision_time"],
    ]
    return hashlib.sha256((seed + "|" + "|".join(str(value) for value in fields)).encode("utf-8")).hexdigest()


def blank_audits() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
    )


def audit_sample(
    *,
    security_master: pd.DataFrame,
    events: pd.DataFrame,
    asof_queries: pd.DataFrame,
    rights: dict[str, Any],
    contract: dict[str, Any],
    input_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    checks: list[dict[str, Any]] = []
    master_required = set(contract["security_master_required_columns"])
    event_required = set(contract["event_required_columns"])
    query_required = set(contract["asof_query_required_columns"])
    rights_required = set(contract["rights_required_fields"])
    missing_master = sorted(master_required - set(security_master.columns))
    missing_events = sorted(event_required - set(events.columns))
    missing_queries = sorted(query_required - set(asof_queries.columns))
    missing_rights = sorted(rights_required - set(rights))
    add_check(checks, "security_master_schema", not missing_master, missing_master, [], "schema", "required security-master columns")
    add_check(checks, "event_schema", not missing_events, missing_events, [], "schema", "required long-event columns")
    add_check(checks, "asof_query_schema", not missing_queries, missing_queries, [], "schema", "required deterministic query columns")
    add_check(checks, "rights_schema", not missing_rights, missing_rights, [], "rights", "required license and retention declarations")

    security_audit, event_audit, asof_audit, strata, rights_audit = blank_audits()
    if missing_master or missing_events or missing_queries or missing_rights:
        return _package(contract, checks, security_master, events, input_hashes), pd.DataFrame(checks), security_audit, event_audit, asof_audit, strata, rights_audit

    master = security_master.copy()
    events = events.copy()
    queries = asof_queries.copy()
    for column in master_required:
        master[column] = text_series(master, column)
    for column in event_required:
        events[column] = text_series(events, column)
    for column in query_required:
        queries[column] = text_series(queries, column)

    bool_delisted = master["is_delisted"].map(clean_bool)
    bool_adr = master["is_adr"].map(clean_bool)
    strata_expected = {str(k): int(v) for k, v in contract["sample_strata_exact_counts"].items()}
    strata_observed = master["sample_stratum"].value_counts().to_dict()
    strata = pd.DataFrame(
        [
            {
                "sample_stratum": name,
                "observed_security_count": int(strata_observed.get(name, 0)),
                "required_security_count": count,
                "status": "PASS" if int(strata_observed.get(name, 0)) == count else "FAIL",
            }
            for name, count in strata_expected.items()
        ]
    )
    mins = contract["minimums"]
    unique_security_count = int(master["security_id"].nunique())
    stable_mask = (
        master["issuer_id"].ne("")
        & master["security_id"].ne("")
        & master["listing_id"].ne("")
        & master["identity_source_hash"].str.match(SHA256_RE, na=False)
    )
    delisted_mask = master["sample_stratum"].eq("delisted")
    delisted_outcome = (
        delisted_mask
        & bool_delisted.eq(True)
        & master["delisted_outcome_type"].isin(contract["allowed_values"]["delisted_outcome_type"])
        & master["delisted_outcome_value"].map(finite_number)
    )
    adr_mask = master["sample_stratum"].eq("adr_home")
    adr_bridge = (
        adr_mask
        & bool_adr.eq(True)
        & master["home_security_id"].ne("")
        & master["home_listing_id"].ne("")
        & master["home_security_id"].ne(master["security_id"])
        & master["home_listing_id"].ne(master["listing_id"])
    )
    predecessor_mask = master["sample_stratum"].eq("predecessor_corporate_action")
    predecessor_bridge = (
        predecessor_mask
        & master["predecessor_security_id"].ne("")
        & master["predecessor_security_id"].ne(master["security_id"])
        & master["corporate_action_type"].isin(contract["allowed_values"]["corporate_action_type"])
    )
    active_flags = master.loc[master["sample_stratum"].eq("active_us"), "is_delisted"].map(clean_bool).eq(False).all()
    master_unique = bool(
        master["security_id"].ne("").all()
        and not master["security_id"].duplicated().any()
        and master["listing_id"].ne("").all()
        and not master["listing_id"].duplicated().any()
    )
    add_check(checks, "unique_security_count", unique_security_count == int(mins["unique_security_count"]), unique_security_count, int(mins["unique_security_count"]), "coverage", "50 unique securities, not 50 arbitrary rows")
    add_check(checks, "master_identity_unique", master_unique, bool(master_unique), True, "identity", "security and listing IDs are unique primary keys")
    add_check(checks, "stable_identity_count", int(stable_mask.sum()) == int(mins["stable_identity_count"]), int(stable_mask.sum()), int(mins["stable_identity_count"]), "identity", "issuer/security/listing IDs plus identity hash")
    add_check(checks, "valid_identity_flags", bool(bool_delisted.notna().all() and bool_adr.notna().all() and active_flags), int(bool_delisted.isna().sum() + bool_adr.isna().sum()), 0, "identity", "boolean flags and active-US non-delisted state")
    add_check(checks, "exact_stratum_counts", bool(strata["status"].eq("PASS").all()), strata_observed, strata_expected, "coverage", "four mutually exclusive preregistered strata")
    add_check(checks, "delisted_outcomes", int(delisted_outcome.sum()) == int(mins["delisted_outcome_count"]), int(delisted_outcome.sum()), int(mins["delisted_outcome_count"]), "identity", "verified delisting return or cash outcome")
    add_check(checks, "adr_home_bridges", int(adr_bridge.sum()) == int(mins["adr_home_bridge_count"]), int(adr_bridge.sum()), int(mins["adr_home_bridge_count"]), "identity", "ADR and home security/listing remain distinct")
    add_check(checks, "predecessor_continuity", int(predecessor_bridge.sum()) == int(mins["predecessor_continuity_count"]), int(predecessor_bridge.sum()), int(mins["predecessor_continuity_count"]), "identity", "typed predecessor/corporate-action chain")

    security_audit = master[["issuer_id", "security_id", "listing_id", "ticker", "sample_stratum"]].copy()
    security_audit["stable_identity"] = stable_mask
    security_audit["delisted_outcome_ready"] = delisted_outcome
    security_audit["adr_home_bridge_ready"] = adr_bridge
    security_audit["predecessor_continuity_ready"] = predecessor_bridge

    exact_observed = events["observed_at"].str.match(EXACT_TIMESTAMP_RE, na=False)
    exact_available = events["available_from"].str.match(EXACT_TIMESTAMP_RE, na=False)
    observed_ts = pd.to_datetime(events["observed_at"], errors="coerce", utc=True)
    available_ts = pd.to_datetime(events["available_from"], errors="coerce", utc=True)
    window_start = pd.Timestamp(contract["window_start"], tz="UTC")
    window_end = pd.Timestamp(contract["window_end"], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    numeric_values = pd.to_numeric(events["value"], errors="coerce")
    nonempty_count = sum(int(events[column].eq("").sum()) for column in contract["event_required_nonempty_columns"])
    hashes_ok = events["source_hash"].str.match(SHA256_RE, na=False)
    event_ids_unique = bool(events["event_id"].ne("").all() and not events["event_id"].duplicated().any())
    master_by_security = master.set_index("security_id", drop=False)
    event_in_master = events["security_id"].isin(master_by_security.index)
    identity_match = pd.Series(False, index=events.index)
    if event_in_master.any():
        joined = events.loc[event_in_master, ["security_id", "issuer_id", "listing_id"]].join(
            master_by_security[["issuer_id", "listing_id"]], on="security_id", rsuffix="_master"
        )
        identity_match.loc[joined.index] = (
            joined["issuer_id"].eq(joined["issuer_id_master"])
            & joined["listing_id"].eq(joined["listing_id_master"])
        )
    allowed = contract["allowed_values"]
    enums_ok = (
        events["event_type"].isin(allowed["event_type"])
        & events["metric"].isin(allowed["metric"])
        & events["fiscal_period_type"].isin(allowed["fiscal_period_type"])
        & events["value_role"].isin(allowed["value_role"])
    )
    role_ok = (
        (events["event_type"].eq("consensus_estimate") & events["value_role"].eq("consensus_mean"))
        | (events["event_type"].eq("company_guidance") & events["value_role"].str.startswith("guidance_"))
    )
    fiscal_ok = pd.to_datetime(events["fiscal_period_end"], errors="coerce").notna()
    time_ok = observed_ts.notna() & available_ts.notna()
    chronology_ok = time_ok & available_ts.ge(observed_ts)
    in_window = time_ok & available_ts.ge(window_start) & available_ts.le(window_end)
    add_check(checks, "event_count", len(events) >= int(mins["event_count"]), len(events), f">={int(mins['event_count'])}", "coverage", "long event rows")
    add_check(checks, "event_ids_unique", event_ids_unique, int(events["event_id"].duplicated().sum()), 0, "pit", "append-only unique event IDs")
    add_check(checks, "event_required_missing", nonempty_count == 0, nonempty_count, 0, "schema", "required event fields are nonempty")
    add_check(checks, "event_values_finite", bool(numeric_values.notna().all() and numeric_values.map(math.isfinite).all()), int(numeric_values.isna().sum()), 0, "schema", "finite values")
    add_check(checks, "event_enums_and_roles", bool((enums_ok & role_ok & fiscal_ok).all()), int((~(enums_ok & role_ok & fiscal_ok)).sum()), 0, "schema", "registered event semantics")
    add_check(checks, "event_identity_match", bool(identity_match.all()), int((~identity_match).sum()), 0, "identity", "event issuer/security/listing matches master")
    add_check(checks, "exact_timestamp_timezone", bool((exact_observed & exact_available).all()), int((~(exact_observed & exact_available)).sum()), 0, "pit", "date-only and fetch-date substitutes fail")
    add_check(checks, "availability_chronology", bool(chronology_ok.all()), int((~chronology_ok).sum()), 0, "pit", "available_from >= observed_at")
    add_check(checks, "future_rows", bool(in_window.all()), int((~in_window).sum()), 0, "pit", "2019-06-03 through frozen endpoint only")
    add_check(checks, "event_source_hashes", bool(hashes_ok.all()), int((~hashes_ok).sum()), 0, "pit", "SHA-256 lineage on every event")

    events["available_from_ts"] = available_ts
    event_lookup = events.set_index("event_id", drop=False)
    revision_link_ok = pd.Series(True, index=events.index)
    nonempty_revision = events["revision_of_event_id"].ne("")
    for idx, row in events.loc[nonempty_revision].iterrows():
        parent_id = row["revision_of_event_id"]
        if parent_id not in event_lookup.index:
            revision_link_ok.loc[idx] = False
            continue
        parent = event_lookup.loc[parent_id]
        if isinstance(parent, pd.DataFrame):
            revision_link_ok.loc[idx] = False
            continue
        same_state = all(
            str(parent[column]) == str(row[column])
            for column in ["security_id", "event_type", "metric", "fiscal_period_end", "fiscal_period_type"]
        )
        earlier = bool(parent["available_from_ts"] < row["available_from_ts"])
        revision_link_ok.loc[idx] = bool(same_state and earlier)
    revision_ready_ids: set[str] = set()
    consensus = events[events["event_type"].eq("consensus_estimate") & chronology_ok & in_window]
    for _, group in consensus.groupby(["security_id", "metric", "fiscal_period_end", "fiscal_period_type"]):
        if group["available_from"].nunique() < 2:
            continue
        linked = group["revision_of_event_id"].ne("") & revision_link_ok.loc[group.index]
        if linked.any():
            revision_ready_ids.add(str(group.iloc[0]["security_id"]))
    revision_security = len(revision_ready_ids)
    guidance_count = int(events["event_type"].eq("company_guidance").sum())
    add_check(checks, "revision_links", bool(revision_link_ok.all()), int((~revision_link_ok).sum()), 0, "pit", "revision pointers stay within the same state and point backward in availability time")
    add_check(checks, "revision_pair_security_count", revision_security >= int(mins["revision_pair_security_count"]), revision_security, f">={int(mins['revision_pair_security_count'])}", "coverage", "same fiscal period with at least two exact-time consensus states")
    add_check(checks, "explicit_guidance_event_count", guidance_count >= int(mins["explicit_guidance_event_count"]), guidance_count, f">={int(mins['explicit_guidance_event_count'])}", "coverage", "explicit company-guidance events")
    event_audit = events[["event_id", "security_id", "event_type", "metric", "fiscal_period_end", "available_from"]].copy()
    event_audit["exact_timestamp"] = exact_observed & exact_available
    event_audit["chronology_ok"] = chronology_ok
    event_audit["in_frozen_window"] = in_window
    event_audit["identity_match"] = identity_match
    event_audit["source_hash_ok"] = hashes_ok
    event_audit["revision_link_ok"] = revision_link_ok

    query_exact = queries["decision_time"].str.match(EXACT_TIMESTAMP_RE, na=False)
    query_ts = pd.to_datetime(queries["decision_time"], errors="coerce", utc=True)
    query_hash_ok = queries.apply(lambda row: selection_hash(str(contract["sample_selection_seed"]), row), axis=1).eq(queries["selection_hash"])
    query_unique = bool(queries["query_id"].ne("").all() and not queries["query_id"].duplicated().any())
    query_rows: list[dict[str, Any]] = []
    for idx, row in queries.iterrows():
        decision_time = query_ts.loc[idx]
        eligible = events[
            events["security_id"].eq(row["security_id"])
            & events["event_type"].eq(row["event_type"])
            & events["metric"].eq(row["metric"])
            & events["fiscal_period_end"].eq(row["fiscal_period_end"])
            & events["fiscal_period_type"].eq(row["fiscal_period_type"])
        ].copy()
        if pd.notna(decision_time):
            eligible = eligible[eligible["available_from_ts"].le(decision_time)]
        else:
            eligible = eligible.iloc[0:0]
        eligible = eligible.sort_values(["available_from_ts", "event_id"], kind="stable")
        reproduced = str(eligible.iloc[-1]["event_id"]) if not eligible.empty else ""
        query_rows.append(
            {
                "query_id": row["query_id"],
                "decision_time": row["decision_time"],
                "security_id": row["security_id"],
                "expected_event_id": row["expected_event_id"],
                "reproduced_event_id": reproduced,
                "selection_hash_ok": bool(query_hash_ok.loc[idx]),
                "decision_time_exact": bool(query_exact.loc[idx]),
                "reproduced": bool(reproduced and reproduced == row["expected_event_id"]),
            }
        )
    asof_audit = pd.DataFrame(query_rows)
    reproduction_count = int(asof_audit["reproduced"].sum()) if not asof_audit.empty else 0
    query_target = int(mins["asof_query_count"])
    add_check(checks, "asof_query_count", len(queries) == query_target and query_unique, len(queries), query_target, "reproduction", "exactly ten unique preregistered queries")
    add_check(checks, "asof_query_timestamps", bool(query_exact.all() and query_ts.notna().all()), int((~query_exact).sum()), 0, "reproduction", "exact decision timestamps")
    add_check(checks, "asof_selection_hashes", bool(query_hash_ok.all()), int((~query_hash_ok).sum()), 0, "reproduction", "frozen-seed query hashes")
    add_check(checks, "asof_reproduction", reproduction_count == int(mins["asof_reproduction_count"]), reproduction_count, int(mins["asof_reproduction_count"]), "reproduction", "latest available event at decision time")

    required_true = [
        "point_in_time_history_claimed",
        "exact_availability_semantics_documented",
        "timezone_semantics_documented",
        "revision_supersession_policy_documented",
        "stable_identity_history_included",
        "delisted_history_included",
        "adr_home_bridge_included",
        "predecessor_history_included",
        "sample_storage_allowed",
        "internal_research_reproduction_allowed",
        "derived_results_retention_allowed",
    ]
    rights_true = all(rights.get(field) is True for field in required_true)
    rights_text = all(str(rights.get(field, "")).strip() for field in ["provider", "export_id", "raw_redistribution_policy"])
    rights_hash = bool(SHA256_RE.match(str(rights.get("rights_source_hash", ""))))
    quote_ok = finite_number(rights.get("sample_quote_amount_usd")) and 0 <= float(rights["sample_quote_amount_usd"]) <= float(contract["approved_sample_cost_hard_cap_usd"])
    one_provider = bool(events["provider"].eq(str(rights.get("provider", ""))).all())
    rights_audit = pd.DataFrame(
        [
            {"rights_check": "required_true_declarations", "status": "PASS" if rights_true else "FAIL"},
            {"rights_check": "required_text_declarations", "status": "PASS" if rights_text else "FAIL"},
            {"rights_check": "rights_source_hash", "status": "PASS" if rights_hash else "FAIL"},
            {"rights_check": "sample_cost_hard_cap", "status": "PASS" if quote_ok else "FAIL"},
            {"rights_check": "single_provider_match", "status": "PASS" if one_provider else "FAIL"},
        ]
    )
    add_check(checks, "rights_and_retention", bool(rights_true and rights_text and rights_hash), bool(rights_true and rights_text and rights_hash), True, "rights", "storage, internal reproduction, retention, and policy declaration")
    add_check(checks, "sample_cost_hard_cap", quote_ok, rights.get("sample_quote_amount_usd"), f"0..{contract['approved_sample_cost_hard_cap_usd']} USD", "rights", "validation never authorizes payment")
    add_check(checks, "single_provider_match", one_provider, rights.get("provider", ""), "all event rows", "rights", "single-source sample")

    summary = _package(contract, checks, master, events, input_hashes)
    summary["observed"] = {
        "unique_security_count": unique_security_count,
        "event_count": int(len(events)),
        "revision_pair_security_count": revision_security,
        "explicit_guidance_event_count": guidance_count,
        "delisted_outcome_count": int(delisted_outcome.sum()),
        "adr_home_bridge_count": int(adr_bridge.sum()),
        "predecessor_continuity_count": int(predecessor_bridge.sum()),
        "stable_identity_count": int(stable_mask.sum()),
        "asof_reproduction_count": reproduction_count,
    }
    return summary, pd.DataFrame(checks), security_audit, event_audit, asof_audit, strata, rights_audit


def _package(
    contract: dict[str, Any],
    checks: list[dict[str, Any]],
    master: pd.DataFrame,
    events: pd.DataFrame,
    input_hashes: dict[str, str] | None,
) -> dict[str, Any]:
    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": contract["pass_status"] if not failed else contract["blocked_status"],
        "failed_checks": failed,
        "failed_categories": sorted({row["category"] for row in checks if row["status"] == "FAIL"}),
        "security_rows": int(len(master)),
        "event_rows": int(len(events)),
        "input_hashes": input_hashes or {},
        "contract_hash": "",
        "research_only": True,
        "schema_pit_procurement_pass_only": True,
        "alpha_screen_allowed": False,
        "portfolio_arm_allowed": False,
        "purchase_authorized": False,
        "returns_joined": False,
        "score_rank_selector_changed": False,
        "portfolio_weights_changed": False,
        "universe_membership_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
        "missing_policy": "neutral",
    }


def audit_local_forward_snapshot(
    *, snapshot: pd.DataFrame,
    request: pd.DataFrame,
    source_summary: dict[str, Any],
    contract: dict[str, Any],
    input_hashes: dict[str, str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    qualifying = int(pd.to_numeric(snapshot.get("has_forward_estimate", pd.Series(dtype=float)), errors="coerce").fillna(0).eq(1).sum())
    actual_request_ids = int(request.get("security_id", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum())
    request_tickers = int(request.get("ticker", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum())
    fetch_date_only = bool(source_summary.get("feature_summary", {}).get("available_from_is_fetch_date", False))
    rows = [
        ("unique_security_count", actual_request_ids, int(contract["minimums"]["unique_security_count"]), "stable provider security IDs"),
        ("named_request_security_count", request_tickers, int(contract["minimums"]["unique_security_count"]), "old request has provider placeholders"),
        ("historical_pit_event_count", 0, int(contract["minimums"]["event_count"]), "current snapshot rows are not historical observations"),
        ("current_forward_estimate_rows", qualifying, int(contract["minimums"]["event_count"]), "diagnostic only; does not satisfy the historical event gate"),
        ("revision_pair_security_count", 0, int(contract["minimums"]["revision_pair_security_count"]), "one fetch-date snapshot cannot prove a revision pair"),
        ("explicit_guidance_event_count", 0, int(contract["minimums"]["explicit_guidance_event_count"]), "no explicit guidance event lineage"),
        ("exact_provider_availability_rows", 0 if fetch_date_only else qualifying, int(contract["minimums"]["event_count"]), "available_from is fetch date, not original exact availability"),
        ("delisted_outcome_count", 0, int(contract["minimums"]["delisted_outcome_count"]), "no delisted result package"),
        ("adr_home_bridge_count", 0, int(contract["minimums"]["adr_home_bridge_count"]), "ticker snapshot has no security/listing bridge"),
        ("predecessor_continuity_count", 0, int(contract["minimums"]["predecessor_continuity_count"]), "no corporate-action lineage"),
        ("asof_reproduction_count", 0, int(contract["minimums"]["asof_reproduction_count"]), "no historical as-of query package"),
        ("rights_manifest_count", 0, 1, "no sample storage/reproduction rights manifest"),
    ]
    gap = pd.DataFrame(
        [
            {
                "gate": gate,
                "observed": observed,
                "required": required,
                "status": "PASS" if observed >= required else "FAIL",
                "reason": reason,
            }
            for gate, observed, required, reason in rows
        ]
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": "BLOCKED_PIT_SAMPLE_CONTRACT_LOCAL_FORWARD_ONLY",
        "failed_checks": gap.loc[gap["status"].eq("FAIL"), "gate"].tolist(),
        "local_snapshot_rows": int(len(snapshot)),
        "local_forward_estimate_rows": qualifying,
        "available_from_is_fetch_date": fetch_date_only,
        "input_hashes": input_hashes,
        "research_only": True,
        "schema_pit_procurement_pass_only": True,
        "local_rows_promoted_to_historical_pit": 0,
        "alpha_screen_allowed": False,
        "portfolio_arm_allowed": False,
        "purchase_authorized": False,
        "returns_joined": False,
        "score_rank_selector_changed": False,
        "portfolio_weights_changed": False,
        "universe_membership_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
    }
    return summary, gap


def write_outputs(
    output_dir: Path,
    summary: dict[str, Any],
    checks: pd.DataFrame,
    security_audit: pd.DataFrame | None = None,
    event_audit: pd.DataFrame | None = None,
    asof_audit: pd.DataFrame | None = None,
    strata: pd.DataFrame | None = None,
    rights_audit: pd.DataFrame | None = None,
    local_gap: pd.DataFrame | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "checks.csv": checks,
        "security_master_audit.csv": security_audit if security_audit is not None else pd.DataFrame(),
        "event_audit.csv": event_audit if event_audit is not None else pd.DataFrame(),
        "asof_reproduction_audit.csv": asof_audit if asof_audit is not None else pd.DataFrame(),
        "stratum_coverage.csv": strata if strata is not None else pd.DataFrame(),
        "license_rights_audit.csv": rights_audit if rights_audit is not None else pd.DataFrame(),
    }
    if local_gap is not None:
        artifacts["local_material_gap.csv"] = local_gap
    output_hashes: dict[str, str] = {}
    for name, frame in artifacts.items():
        path = output_dir / name
        frame.to_csv(path, index=False)
        output_hashes[name] = sha256_file(path)
    summary["output_hashes"] = output_hashes
    report = [
        "# Run287 PIT estimate/guidance sample v2 audit",
        "",
        f"- Status: `{summary['status']}`",
        f"- Failed checks: `{len(summary.get('failed_checks', []))}`",
        "- This is a schema/PIT/identity/rights gate only; it is not an alpha pass.",
        "- No returns, scores, ranks, selectors, portfolio weights, orders, production paths, or fullrun were used.",
        "",
        "## Failed checks",
        "",
    ]
    report.extend([f"- `{item}`" for item in summary.get("failed_checks", [])] or ["- None"])
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    summary["output_hashes"]["report.md"] = sha256_file(output_dir / "report.md")
    (output_dir / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--security-master")
    parser.add_argument("--events")
    parser.add_argument("--asof-queries")
    parser.add_argument("--rights")
    parser.add_argument("--local-forward-snapshot")
    parser.add_argument("--legacy-request")
    parser.add_argument("--source-summary")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    parser.add_argument("--report-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract_path = repo_path(args.contract)
    output_dir = repo_path(args.output_dir)
    contract = read_json(contract_path)
    if args.local_forward_snapshot:
        required = [args.local_forward_snapshot, args.legacy_request, args.source_summary]
        if any(not value for value in required):
            raise SystemExit("local mode requires --local-forward-snapshot, --legacy-request, and --source-summary")
        snapshot_path, request_path, source_path = [repo_path(value) for value in required]
        summary, gap = audit_local_forward_snapshot(
            snapshot=read_table(snapshot_path),
            request=read_table(request_path),
            source_summary=read_json(source_path),
            contract=contract,
            input_hashes={
                "tool": sha256_file(Path(__file__).resolve()),
                "contract": sha256_file(contract_path),
                "local_forward_snapshot": sha256_file(snapshot_path),
                "legacy_request": sha256_file(request_path),
                "source_summary": sha256_file(source_path),
            },
        )
        write_outputs(output_dir, summary, gap, local_gap=gap)
        print(json.dumps({"status": summary["status"], "output_dir": str(output_dir)}, indent=2))
        return 0 if args.report_only else 2

    required_values = [args.security_master, args.events, args.asof_queries, args.rights]
    if any(not value for value in required_values):
        raise SystemExit("provider mode requires --security-master, --events, --asof-queries, and --rights")
    master_path, event_path, query_path, rights_path = [repo_path(value) for value in required_values]
    summary, checks, master_audit, event_audit, asof_audit, strata, rights_audit = audit_sample(
        security_master=read_table(master_path),
        events=read_table(event_path),
        asof_queries=read_table(query_path),
        rights=read_json(rights_path),
        contract=contract,
        input_hashes={
            "tool": sha256_file(Path(__file__).resolve()),
            "contract": sha256_file(contract_path),
            "security_master": sha256_file(master_path),
            "events": sha256_file(event_path),
            "asof_queries": sha256_file(query_path),
            "rights": sha256_file(rights_path),
        },
    )
    summary["contract_hash"] = sha256_file(contract_path)
    write_outputs(output_dir, summary, checks, master_audit, event_audit, asof_audit, strata, rights_audit)
    print(json.dumps({"status": summary["status"], "failed_checks": summary["failed_checks"], "output_dir": str(output_dir)}, indent=2))
    return 0 if summary["status"] == contract["pass_status"] or args.report_only else 2


if __name__ == "__main__":
    sys.exit(main())
