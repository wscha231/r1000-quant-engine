#!/usr/bin/env python3
"""Build fail-closed paper targets that limit incremental buys in risk states.

The guard sits between the exact same-close selector and the review-only
forward paper ledger.  It never forces a crisis sale.  It only limits the
positive difference between the selector target and the exact marked account
weight, leaving selector-requested reductions and lifecycle exits intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-paper-buy-guard-targets-v1"
READY_STATUS = "READY_PAPER_BUY_GUARD_TARGETS"
BLOCKED_STATUS = "BLOCKED_PAPER_BUY_GUARD_TARGETS"
SOURCE_SCHEMA = "run287-same-close-target-books-v1"
SOURCE_STATUS = "READY_SAME_CLOSE_PAPER_TARGETS"
PORTFOLIOS = ("main", "concentrated")
RESERVE_TICKERS = {"CASH", "__CASH__", "BIL", "SGOV"}
RESERVE_REASONS = (
    "crisis_reserve",
    "capacity_unallocated",
    "reentry_pending",
    "data_block_reserve",
    "transaction_buffer",
    "residual_cash",
)
STATE_MULTIPLIERS = {
    "GREEN": 1.00,
    "WATCH": 0.00,
    "DEFENSE": 0.00,
    "CRISIS": 0.00,
    "REENTRY_STAGE_1": 0.25,
    "REENTRY_STAGE_2": 0.60,
    "REENTRY_STAGE_3": 1.00,
    "DEGRADED_DATA": 0.00,
}
DEFAULT_CONTRACT = REPO_ROOT / "docs/run287_paper_buy_guard_contract.json"


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
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def normalized_target_hash(frame: pd.DataFrame) -> str:
    rows = [
        {"ticker": str(row.ticker), "target_weight": round(float(row.weight), 12)}
        for row in frame[["ticker", "weight"]].sort_values("ticker").itertuples(index=False)
        if float(row.weight) > 1e-12
    ]
    return canonical_hash({"schema": "run287-forward-target-v1", "rows": rows})


def source_record_path(manifest_path: Path, record: Mapping[str, Any]) -> Path:
    raw = str(record.get("path") or "")
    direct = Path(raw)
    if direct.is_absolute():
        return direct
    local = manifest_path.parent / direct
    return local if local.exists() else repo_path(direct)


def verified_target(
    manifest_path: Path, manifest: Mapping[str, Any], portfolio: str
) -> tuple[Path, dict[str, Any]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, Mapping):
        raise ValueError("same-close outputs missing")
    record = outputs.get(f"{portfolio}_target_book")
    if not isinstance(record, Mapping):
        raise ValueError(f"same-close target record missing:{portfolio}")
    path = source_record_path(manifest_path, record)
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "").strip().lower()
    if audit.get("exists") is not True or not expected or audit.get("sha256") != expected:
        raise ValueError(f"same-close target hash mismatch:{portfolio}")
    return path, audit


def account_weights(path: Path, portfolio: str, valuation_date: str) -> tuple[dict[str, float], dict[str, Any]]:
    account = read_json(path)
    if (
        str(account.get("portfolio_kind") or "").strip().lower() != portfolio
        or str(account.get("as_of_date") or "") != valuation_date
        or account.get("review_only") is not True
        or account.get("live_trading_enabled") is not False
        or account.get("production_mutation_allowed") is not False
    ):
        raise ValueError(f"unsafe or mismatched marked paper account:{portfolio}")
    weights: dict[str, float] = {}
    positions = account.get("positions")
    if not isinstance(positions, list):
        raise ValueError(f"paper account positions missing:{portfolio}")
    for row in positions:
        if not isinstance(row, Mapping):
            raise ValueError(f"paper account position schema:{portfolio}")
        ticker = str(row.get("ticker") or "").upper().strip()
        weight = float(pd.to_numeric(row.get("weight"), errors="coerce"))
        if not ticker or not math.isfinite(weight) or weight < -1e-12:
            raise ValueError(f"paper account position invalid:{portfolio}")
        if ticker in weights:
            raise ValueError(f"paper account duplicate ticker:{portfolio}:{ticker}")
        weights[ticker] = max(weight, 0.0)
    cash_weight = float(pd.to_numeric(account.get("cash_weight"), errors="coerce"))
    if not math.isfinite(cash_weight) or cash_weight < -1e-12:
        raise ValueError(f"paper account cash invalid:{portfolio}")
    if not math.isclose(sum(weights.values()) + cash_weight, 1.0, abs_tol=1e-6):
        raise ValueError(f"paper account weights do not sum to one:{portfolio}")
    weights["CASH"] = max(cash_weight, 0.0)
    return weights, {"account": fingerprint(path), "marked_weight_sum": sum(weights.values())}


def reserve_reason_for_state(state: str) -> str:
    if state in {"DEFENSE", "CRISIS"}:
        return "crisis_reserve"
    if state.startswith("REENTRY_STAGE_"):
        return "reentry_pending"
    if state == "DEGRADED_DATA":
        return "data_block_reserve"
    return "transaction_buffer"


def reserve_reason_hash(frame: pd.DataFrame) -> str:
    cash = frame["ticker"].isin(RESERVE_TICKERS)
    reserve_weight = float(frame.loc[cash, "weight"].sum())
    reasons = {
        reason: float(pd.to_numeric(frame.loc[cash, reason], errors="coerce").fillna(0.0).sum())
        for reason in RESERVE_REASONS
    }
    if not math.isclose(sum(reasons.values()), reserve_weight, abs_tol=1e-9):
        raise ValueError("Reserve reason reconciliation failure")
    return canonical_hash(
        {
            "schema_version": "run287-reserve-reason-source-v1",
            "reserve_weight": round(reserve_weight, 12),
            "reason_weights": {
                reason: round(reasons[reason], 12) for reason in RESERVE_REASONS
            },
        }
    )


def guard_target(
    source: pd.DataFrame,
    *,
    marked_weights: Mapping[str, float],
    state: str,
    portfolio: str,
) -> tuple[pd.DataFrame, dict[str, Any], list[dict[str, Any]]]:
    required = {"ticker", "weight"}
    if not required.issubset(source.columns):
        raise ValueError(f"target columns missing:{portfolio}")
    out = source.copy()
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce")
    if (
        out["ticker"].eq("").any()
        or out["ticker"].duplicated().any()
        or out["weight"].isna().any()
        or (out["weight"] < -1e-12).any()
        or not math.isclose(float(out["weight"].sum()), 1.0, abs_tol=1e-9)
    ):
        raise ValueError(f"invalid source target:{portfolio}")
    if state not in STATE_MULTIPLIERS:
        raise ValueError(f"unsupported canonical crisis state:{state}")
    multiplier = STATE_MULTIPLIERS[state]
    actions: list[dict[str, Any]] = []
    released = 0.0
    reserve_mask = out["ticker"].isin(RESERVE_TICKERS)
    for index, row in out.loc[~reserve_mask].iterrows():
        ticker = str(row["ticker"])
        proposed = float(row["weight"])
        marked = max(float(marked_weights.get(ticker, 0.0)), 0.0)
        increase = max(proposed - marked, 0.0)
        allowed = proposed - increase * (1.0 - multiplier)
        released += proposed - allowed
        out.loc[index, "weight"] = allowed
        actions.append(
            {
                "portfolio_kind": portfolio,
                "ticker": ticker,
                "canonical_crisis_state": state,
                "marked_weight": marked,
                "selector_target_weight": proposed,
                "guarded_target_weight": allowed,
                "blocked_incremental_weight": proposed - allowed,
                "incremental_buy_multiplier": multiplier,
                "action": "LIMIT_INCREMENTAL_BUY" if proposed - allowed > 1e-12 else "UNCHANGED",
            }
        )
    cash_rows = out.index[out["ticker"].eq("CASH")].tolist()
    if len(cash_rows) != 1:
        raise ValueError(f"exactly one CASH row required:{portfolio}")
    cash_index = cash_rows[0]
    out.loc[cash_index, "weight"] = float(out.loc[cash_index, "weight"]) + released
    for reason in RESERVE_REASONS:
        if reason not in out.columns:
            out[reason] = 0.0
        out[reason] = pd.to_numeric(out[reason], errors="coerce").fillna(0.0)
    if released > 1e-12:
        out.loc[cash_index, reserve_reason_for_state(state)] += released
    if not math.isclose(float(out["weight"].sum()), 1.0, abs_tol=1e-9):
        raise ValueError(f"guarded target weights do not sum to one:{portfolio}")
    source_hash = reserve_reason_hash(out)
    out["reserve_reason_source_hash"] = source_hash
    out["paper_buy_guard_state"] = state
    out["paper_buy_guard_increment_multiplier"] = multiplier
    out["paper_buy_guard_applied"] = released > 1e-12
    guarded_hash = normalized_target_hash(out)
    if "same_close_target_hash" in out.columns:
        out["same_close_target_hash"] = guarded_hash
    summary = {
        "portfolio_kind": portfolio,
        "canonical_crisis_state": state,
        "incremental_buy_multiplier": multiplier,
        "blocked_incremental_weight": released,
        "limited_ticker_count": sum(
            float(row["blocked_incremental_weight"]) > 1e-12 for row in actions
        ),
        "forced_crisis_sale_weight": 0.0,
        "selector_requested_reductions_preserved": True,
        "guarded_target_hash": guarded_hash,
        "reserve_reason_source_hash": source_hash,
    }
    return out.sort_values(["weight", "ticker"], ascending=[False, True]), summary, actions


def blocked_payload(output_dir: Path, valuation_date: str, blockers: list[str]) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": BLOCKED_STATUS,
        "valuation_close_date": valuation_date,
        "blockers": sorted(set(blockers)),
        "target_book_file_written": False,
        "orders_generated": False,
        "paper_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
    }
    write_json(output_dir / "status.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    valuation_date = str(args.valuation_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    stale = [path for path in output_dir.iterdir() if path.name != ".gitkeep"]
    if stale:
        raise FileExistsError(f"paper buy guard output is not empty: {output_dir}")
    manifest_path = repo_path(args.same_close_status)
    blockers: list[str] = []
    try:
        contract_path = repo_path(getattr(args, "contract", DEFAULT_CONTRACT))
        contract = read_json(contract_path)
        contract_policy = contract.get("policy") or {}
        if contract.get("schema_version") != "run287-paper-buy-guard-contract-v1":
            blockers.append("paper_buy_guard_contract_schema")
        declared_multipliers = {
            state: float(contract_policy.get(state)) for state in STATE_MULTIPLIERS
        }
        if declared_multipliers != STATE_MULTIPLIERS:
            blockers.append("paper_buy_guard_contract_multiplier_mismatch")
        if contract_policy.get("forced_crisis_sales_allowed") is not False:
            blockers.append("paper_buy_guard_contract_forced_sale")
        source_manifest = read_json(manifest_path)
        if (
            source_manifest.get("schema_version") != SOURCE_SCHEMA
            or source_manifest.get("status") != SOURCE_STATUS
            or source_manifest.get("target_book_file_written") is not True
            or source_manifest.get("orders_generated") is not False
            or source_manifest.get("crisis_policy_applied_to_operating_target") is not False
            or source_manifest.get("crisis_policy_shadow_only") is not True
            or str(source_manifest.get("valuation_close_date") or "") != valuation_date
        ):
            blockers.append("same_close_manifest_contract")
        context = source_manifest.get("canonical_crisis_state")
        if not isinstance(context, Mapping):
            blockers.append("canonical_crisis_context_missing")
            context = {}
        state = str(context.get("state") or "").upper().strip()
        if state not in STATE_MULTIPLIERS:
            blockers.append("canonical_crisis_state_invalid")
        availability = context.get("component_availability")
        if not isinstance(availability, list) or not availability:
            blockers.append("crisis_component_availability_missing")
        source_targets = {
            portfolio: verified_target(manifest_path, source_manifest, portfolio)
            for portfolio in PORTFOLIOS
        }
        state_dir = repo_path(args.state_dir)
        accounts = {
            portfolio: account_weights(
                state_dir / portfolio / "account_state_latest.json",
                portfolio,
                valuation_date,
            )
            for portfolio in PORTFOLIOS
        }
    except Exception as exc:
        blockers.append(f"input_validation:{type(exc).__name__}:{exc}")
        return blocked_payload(output_dir, valuation_date, blockers)
    if blockers:
        return blocked_payload(output_dir, valuation_date, blockers)

    outputs: dict[str, Any] = {}
    summaries: dict[str, Any] = {}
    action_rows: list[dict[str, Any]] = []
    source_fingerprints = {
        "paper_buy_guard_contract": fingerprint(contract_path),
        "same_close_status": fingerprint(manifest_path),
        **{
            f"{portfolio}_source_target": record
            for portfolio, (_path, record) in source_targets.items()
        },
        **{
            f"{portfolio}_marked_account": audit["account"]
            for portfolio, (_weights, audit) in accounts.items()
        },
    }
    try:
        for portfolio in PORTFOLIOS:
            source_path, _record = source_targets[portfolio]
            marked, _audit = accounts[portfolio]
            guarded, summary, actions = guard_target(
                pd.read_csv(source_path, low_memory=False),
                marked_weights=marked,
                state=state,
                portfolio=portfolio,
            )
            target_path = output_dir / f"paper_buy_guard_{portfolio}_target_book.csv"
            guarded.to_csv(target_path, index=False, lineterminator="\n", float_format="%.12g")
            outputs[f"{portfolio}_target_book"] = fingerprint(target_path)
            summaries[portfolio] = summary
            action_rows.extend(actions)
        action_path = output_dir / "paper_buy_guard_audit.csv"
        pd.DataFrame(action_rows).to_csv(action_path, index=False, lineterminator="\n", float_format="%.12g")
        outputs["paper_buy_guard_audit"] = fingerprint(action_path)
        for label, before in source_fingerprints.items():
            path = Path(str(before.get("path") or ""))
            if fingerprint(path) != before:
                raise ValueError(f"input_changed_before_publish:{label}")
    except Exception as exc:
        for path in output_dir.glob("paper_buy_guard_*target_book.csv"):
            path.unlink()
        (output_dir / "paper_buy_guard_audit.csv").unlink(missing_ok=True)
        return blocked_payload(
            output_dir,
            valuation_date,
            [f"guard_build:{type(exc).__name__}:{exc}"],
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": READY_STATUS,
        "valuation_close_date": valuation_date,
        "canonical_crisis_state": state,
        "macro_crisis_inputs_bound": True,
        "source_same_close_manifest": fingerprint(manifest_path),
        "source_inputs": source_fingerprints,
        "policy": {
            "scope": "forward review-only paper orders",
            "state_incremental_buy_multipliers": STATE_MULTIPLIERS,
            "forced_crisis_sales_allowed": False,
            "selector_requested_reductions_preserved": True,
            "missing_or_invalid_state": "fail_closed_without_new_orders",
        },
        "portfolio_summaries": summaries,
        "outputs": outputs,
        "target_book_file_written": True,
        "orders_generated": False,
        "paper_only": True,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "fullrun_executed": False,
        "historical_performance_validated": False,
        "automatic_promotion_allowed": False,
    }
    write_json(output_dir / "status.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--same-close-status", required=True)
    parser.add_argument("--state-dir", default="outputs/daily_simulated_fill_ledger")
    parser.add_argument("--valuation-date", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") == READY_STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
