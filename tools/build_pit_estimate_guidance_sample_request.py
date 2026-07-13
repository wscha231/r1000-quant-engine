#!/usr/bin/env python3
"""Build a deterministic, provider-neutral PIT estimate/guidance sample request.

The request is procurement preparation only.  It does not call a provider,
join returns, authorize a purchase, mutate a universe, or run a backtest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-pit-estimate-guidance-sample-request-v1"
DEFAULT_OUTCOME_CONTRACT = "docs/run287_pit_estimate_guidance_outcome_contract.json"
DEFAULT_OUTPUT_DIR = "outputs/run287_pit_estimate_guidance_sample_request"
DEFAULT_SEED = "run287-pit-estimate-guidance-sample-v1"
REQUIRED_CURRENT_COLUMNS = {"ticker", "sector", "is_equity_issuer", "is_adr_global_listing"}
REQUEST_COLUMNS = [
    "request_row_id",
    "security_id",
    "ticker",
    "name",
    "sector",
    "is_delisted",
    "is_adr_global_listing",
    "sample_role",
    "selection_method",
    "selection_hash",
    "stable_id_status",
    "provider_action",
    "history_start",
    "history_end",
    "required_record_types",
    "required_metrics",
    "required_horizons_trading_days",
]


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def clean_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def clean_text(value: Any, default: str = "") -> str:
    if value is None or pd.isna(value):
        return default
    text = str(value).strip()
    return text if text else default


def selection_hash(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}|{value}".encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_current(frame: pd.DataFrame, seed: str) -> tuple[pd.DataFrame, list[str]]:
    missing = sorted(REQUIRED_CURRENT_COLUMNS - set(frame.columns))
    if missing:
        return pd.DataFrame(), missing
    d = frame.copy()
    d["ticker"] = d["ticker"].fillna("").astype(str).str.upper().str.strip()
    d["sector"] = d["sector"].fillna("Unknown").astype(str).str.strip().replace("", "Unknown")
    d["is_equity_issuer"] = d["is_equity_issuer"].map(clean_bool)
    d["is_adr_global_listing"] = d["is_adr_global_listing"].map(clean_bool)
    d = d[d["is_equity_issuer"] & d["ticker"].ne("") & d["ticker"].ne("CASH")].copy()
    d = d.drop_duplicates("ticker", keep="first")
    d["selection_hash"] = d["ticker"].map(lambda value: selection_hash(seed, value))
    return d.sort_values(["selection_hash", "ticker"], kind="stable").reset_index(drop=True), []


def select_round_robin_by_sector(frame: pd.DataFrame, count: int) -> pd.DataFrame:
    if count <= 0 or frame.empty:
        return frame.iloc[0:0].copy()
    groups = {
        str(sector): group.sort_values(["selection_hash", "ticker"], kind="stable").reset_index(drop=True)
        for sector, group in frame.groupby("sector", sort=True)
    }
    positions = {sector: 0 for sector in groups}
    selected: list[pd.Series] = []
    while len(selected) < count:
        progressed = False
        for sector in sorted(groups):
            pos = positions[sector]
            group = groups[sector]
            if pos < len(group):
                selected.append(group.iloc[pos])
                positions[sector] = pos + 1
                progressed = True
                if len(selected) >= count:
                    break
        if not progressed:
            break
    return pd.DataFrame(selected).reset_index(drop=True) if selected else frame.iloc[0:0].copy()


def select_active_sample(frame: pd.DataFrame, active_count: int, min_adr: int) -> tuple[pd.DataFrame, list[str]]:
    blockers: list[str] = []
    if len(frame) < active_count:
        blockers.append(f"current_equity_count_below_required:{len(frame)}<{active_count}")
    adr = frame[frame["is_adr_global_listing"]].sort_values(["selection_hash", "ticker"], kind="stable")
    if len(adr) < min_adr:
        blockers.append(f"adr_count_below_required:{len(adr)}<{min_adr}")
    adr_selected = adr.head(min(min_adr, active_count)).copy()
    remaining = frame[
        ~frame["ticker"].isin(adr_selected["ticker"]) & ~frame["is_adr_global_listing"]
    ].copy()
    rest = select_round_robin_by_sector(remaining, max(0, active_count - len(adr_selected)))
    selected = pd.concat([adr_selected, rest], ignore_index=True)
    if len(selected) < active_count:
        extra_adr = adr[~adr["ticker"].isin(selected["ticker"])].head(active_count - len(selected))
        selected = pd.concat([selected, extra_adr], ignore_index=True)
    selected = selected.drop_duplicates("ticker", keep="first").head(active_count)
    if len(selected) < active_count:
        blockers.append(f"active_sample_count_below_required:{len(selected)}<{active_count}")
    return selected.reset_index(drop=True), blockers


def normalize_delisted(frame: pd.DataFrame, seed: str) -> pd.DataFrame:
    required = {"security_id", "ticker", "is_delisted"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=["security_id", "ticker", "name", "sector", "is_delisted", "is_adr_global_listing", "selection_hash"])
    d = frame.copy()
    d["security_id"] = d["security_id"].fillna("").astype(str).str.strip()
    d["ticker"] = d["ticker"].fillna("").astype(str).str.upper().str.strip()
    d["is_delisted"] = d["is_delisted"].map(clean_bool)
    d["is_adr_global_listing"] = d.get("is_adr_global_listing", False)
    d["is_adr_global_listing"] = d["is_adr_global_listing"].map(clean_bool)
    d["name"] = d.get("name", "")
    d["sector"] = d.get("sector", "Unknown")
    d = d[d["is_delisted"] & d["security_id"].ne("") & d["ticker"].ne("")].copy()
    d = d.drop_duplicates("security_id", keep="first")
    d["selection_hash"] = d["security_id"].map(lambda value: selection_hash(seed, value))
    return d.sort_values(["selection_hash", "security_id"], kind="stable").reset_index(drop=True)


def request_row(
    *,
    row_id: str,
    security_id: str,
    ticker: str,
    name: str,
    sector: str,
    is_delisted: bool,
    is_adr: bool,
    sample_role: str,
    method: str,
    row_hash: str,
    stable_id_status: str,
    provider_action: str,
    horizons: list[int],
) -> dict[str, Any]:
    return {
        "request_row_id": row_id,
        "security_id": security_id,
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "is_delisted": bool(is_delisted),
        "is_adr_global_listing": bool(is_adr),
        "sample_role": sample_role,
        "selection_method": method,
        "selection_hash": row_hash,
        "stable_id_status": stable_id_status,
        "provider_action": provider_action,
        "history_start": "2019-06-03",
        "history_end": "2026-07-10",
        "required_record_types": "consensus_estimate|company_guidance",
        "required_metrics": "eps|revenue",
        "required_horizons_trading_days": "|".join(str(value) for value in horizons),
    }


def build_request(
    *,
    current_universe: pd.DataFrame,
    delisted_candidates: pd.DataFrame,
    outcome_contract: dict[str, Any],
    sample_size: int = 50,
    delisted_count: int = 5,
    min_adr: int = 5,
    seed: str = DEFAULT_SEED,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    horizons = [int(row["trading_days"]) for row in outcome_contract.get("horizons", [])]
    current, schema_missing = normalize_current(current_universe, seed)
    active_count = sample_size - delisted_count
    blockers = [f"missing_current_column:{column}" for column in schema_missing]
    active, active_blockers = select_active_sample(current, max(0, active_count), min_adr)
    blockers.extend(active_blockers)
    delisted = normalize_delisted(delisted_candidates, seed).head(delisted_count)

    rows: list[dict[str, Any]] = []
    for index, record in enumerate(active.to_dict("records"), start=1):
        security_id = str(record.get("security_id") or "").strip()
        rows.append(
            request_row(
                row_id=f"ACTIVE_{index:03d}",
                security_id=security_id,
                ticker=str(record.get("ticker", "")),
                name=clean_text(record.get("Name", record.get("name", ""))),
                sector=str(record.get("sector", "Unknown")),
                is_delisted=False,
                is_adr=bool(record.get("is_adr_global_listing", False)),
                sample_role="active_stratified",
                method="adr_minimum_then_sector_round_robin_sha256",
                row_hash=str(record.get("selection_hash", "")),
                stable_id_status="provided" if security_id else "provider_required",
                provider_action="resolve_permanent_security_id_and_full_symbol_history",
                horizons=horizons,
            )
        )
    for index, record in enumerate(delisted.to_dict("records"), start=1):
        rows.append(
            request_row(
                row_id=f"DELISTED_{index:03d}",
                security_id=str(record.get("security_id", "")),
                ticker=str(record.get("ticker", "")),
                name=clean_text(record.get("name", "")),
                sector=clean_text(record.get("sector", "Unknown"), "Unknown"),
                is_delisted=True,
                is_adr=bool(record.get("is_adr_global_listing", False)),
                sample_role="historical_delisted",
                method="sha256_permanent_security_id",
                row_hash=str(record.get("selection_hash", "")),
                stable_id_status="provided",
                provider_action="return_pit_history_delisting_return_and_symbol_chain",
                horizons=horizons,
            )
        )
    missing_delisted = max(0, delisted_count - len(delisted))
    for slot in range(missing_delisted):
        slot_id = len(delisted) + slot + 1
        rows.append(
            request_row(
                row_id=f"DELISTED_SLOT_{slot_id:03d}",
                security_id="",
                ticker="",
                name="",
                sector="provider_historical_pool",
                is_delisted=True,
                is_adr=False,
                sample_role="historical_delisted_provider_query",
                method="sha256_provider_permanent_id_first_n",
                row_hash=selection_hash(seed, f"delisted-slot-{slot_id}"),
                stable_id_status="provider_required",
                provider_action=(
                    "from_all_2019-06-03_to_2026-07-10_eligible_then_delisted_securities_"
                    f"sort_sha256('{seed}'|provider_permanent_id)_and_return_rank_{slot_id}"
                ),
                horizons=horizons,
            )
        )

    sample = pd.DataFrame(rows, columns=REQUEST_COLUMNS)
    if missing_delisted:
        blockers.append(f"local_delisted_candidate_shortfall:{len(delisted)}<{delisted_count};provider_query_required")
    if not horizons or not {21, 63, 126, 252, 504}.issubset(set(horizons)):
        blockers.append("outcome_contract_missing_required_horizons")
    if len(sample) != sample_size:
        blockers.append(f"sample_row_count_mismatch:{len(sample)}!={sample_size}")

    full_rows: list[dict[str, Any]] = []
    for record in current.to_dict("records"):
        full_rows.append(
            {
                "security_id": str(record.get("security_id") or ""),
                "ticker": str(record.get("ticker", "")),
                "name": clean_text(record.get("Name", record.get("name", ""))),
                "sector": str(record.get("sector", "Unknown")),
                "is_adr_global_listing": bool(record.get("is_adr_global_listing", False)),
                "scope": "current_snapshot_reference_not_pit_membership",
                "provider_action": "resolve_permanent_id_then_add_all_historical_eligible_and_delisted_securities",
                "history_start": "2019-06-03",
                "history_end": "2026-07-10",
                "required_horizons_trading_days": "|".join(str(value) for value in horizons),
            }
        )
    full_request = pd.DataFrame(full_rows)

    hard_blockers = [item for item in blockers if not item.startswith("local_delisted_candidate_shortfall")]
    if hard_blockers:
        status = "BLOCKED_REQUEST_CONTRACT"
    elif missing_delisted:
        status = "READY_ZERO_COST_SCHEMA_REQUEST_WITH_PROVIDER_DELISTED_QUERY"
    else:
        status = "READY_ZERO_COST_SCHEMA_REQUEST"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": status,
        "research_only": True,
        "sample_size": sample_size,
        "active_sample_count": int((sample["sample_role"] == "active_stratified").sum()) if not sample.empty else 0,
        "delisted_sample_count": int(sample["is_delisted"].sum()) if not sample.empty else 0,
        "local_delisted_candidate_count": int(len(delisted)),
        "provider_delisted_query_slots": int(missing_delisted),
        "adr_sample_count": int(sample["is_adr_global_listing"].sum()) if not sample.empty else 0,
        "current_equity_reference_count": int(len(current)),
        "historical_union_security_count": None,
        "historical_union_scope": "all decision-time eligible securities including delisted and symbol predecessors",
        "selection_seed": seed,
        "selection_uses_return_labels": False,
        "required_return_horizons_trading_days": horizons,
        "long_horizon_roles": {"252": "promotion_confirmation_when_powered", "504": "directional_sensitivity_when_powered"},
        "blockers": blockers,
        "missing_policy": "neutral",
        "purchase_authorized": False,
        "provider_request_dispatched": False,
        "backtest_executed": False,
        "returns_joined": False,
        "portfolio_weights_changed": False,
        "universe_membership_changed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_dispatched": False,
    }
    return summary, sample, full_request


def write_outputs(output_dir: Path, summary: dict[str, Any], sample: pd.DataFrame, full_request: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    sample_path = output_dir / "sample_request.csv"
    full_path = output_dir / "current_universe_reference_request.csv"
    sample.to_csv(sample_path, index=False)
    full_request.to_csv(full_path, index=False)
    summary["output_hashes"] = {
        "sample_request_sha256": sha256_file(sample_path),
        "current_universe_reference_request_sha256": sha256_file(full_path),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Run287 PIT estimate/guidance sample request",
        "",
        f"- Status: `{summary['status']}`",
        f"- Sample: {summary['sample_size']} ({summary['active_sample_count']} active, {summary['delisted_sample_count']} delisted)",
        f"- ADR/global sample: {summary['adr_sample_count']}",
        f"- Current equity reference: {summary['current_equity_reference_count']}",
        f"- Return horizons: {summary['required_return_horizons_trading_days']}",
        "- Historical union count: unknown until PIT membership and delisted history are supplied",
        "- Purchase, provider dispatch, returns join, backtest, portfolio mutation, production, and fullrun: not authorized",
        "",
        "## Blockers and provider work",
        "",
    ]
    if summary["blockers"]:
        lines.extend(f"- `{item}`" for item in summary["blockers"])
    else:
        lines.append("- None for a zero-cost schema request. The delivered export must still pass the source gate.")
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-universe", required=True, help="Current 993-style research queue CSV/Parquet")
    parser.add_argument("--delisted-candidates", default="", help="Optional historical delisted candidates with stable IDs")
    parser.add_argument("--outcome-contract", default=DEFAULT_OUTCOME_CONTRACT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--delisted-count", type=int, default=5)
    parser.add_argument("--min-adr", type=int, default=5)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    current_path = repo_path(args.current_universe)
    outcome_path = repo_path(args.outcome_contract)
    if not current_path.exists() or not outcome_path.exists():
        print(json.dumps({"status": "BLOCKED_REQUEST_CONTRACT", "missing": [str(path) for path in [current_path, outcome_path] if not path.exists()]}, indent=2))
        return 2
    delisted = read_table(repo_path(args.delisted_candidates)) if args.delisted_candidates else pd.DataFrame()
    summary, sample, full_request = build_request(
        current_universe=read_table(current_path),
        delisted_candidates=delisted,
        outcome_contract=json.loads(outcome_path.read_text(encoding="utf-8")),
        sample_size=args.sample_size,
        delisted_count=args.delisted_count,
        min_adr=args.min_adr,
        seed=args.seed,
    )
    delisted_path = repo_path(args.delisted_candidates) if args.delisted_candidates else None
    summary["input_paths"] = {
        "current_universe": str(current_path),
        "delisted_candidates": str(delisted_path) if delisted_path else "",
        "outcome_contract": str(outcome_path),
    }
    summary["input_hashes"] = {
        "current_universe_sha256": sha256_file(current_path),
        "delisted_candidates_sha256": sha256_file(delisted_path) if delisted_path and delisted_path.exists() else "",
        "outcome_contract_sha256": sha256_file(outcome_path),
    }
    write_outputs(repo_path(args.output_dir), summary, sample, full_request)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"].startswith("READY_") else 2


if __name__ == "__main__":
    sys.exit(main())
