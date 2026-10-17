#!/usr/bin/env python3
"""Convert daily crisis paper actions into approval-required order previews.

This bridge is paper-only. It does not place broker orders, does not mutate the
operating target books, and does not override the daily monitor's
auto_trade_allowed=false contract.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import io
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_account_order_preview import normalize_target, select_target_snapshot, run as run_order_preview  # noqa: E402
from tools.run287_crisis_policy import CANONICAL_STATES, adapt_crisis_state  # noqa: E402
from tools.reserve_asset_policy import (  # noqa: E402
    RESERVE_REASONS, RESERVE_REASON_SOURCE_HASH_FIELD,
    reserve_reason_reconciliation, resolve_reserve_asset_policy,
)


PORTFOLIOS = ("main", "concentrated")
ALLOWED_ACTION_TYPES = {"raise_cash", "trim_position", "block_new_buys", "reentry_watch", "no_op"}
# This work package authorizes code/fixture preparation, not actual preview
# activation. No CLI flag or input file can turn this gate on. A separately
# reviewed real-input/activation change is required; test stubs may patch it.
ACTUAL_PREVIEW_ACTIVATED = False


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if pd.notna(out) else default
    except Exception:
        return default


def strict_number(value: Any) -> float:
    if type(value) not in (float, int):
        raise ValueError("ECONOMIC_NUMBER_INVALID")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ValueError("ECONOMIC_NUMBER_INVALID") from None
    if not math.isfinite(number):
        raise ValueError("ECONOMIC_NUMBER_INVALID")
    return number


def strict_ticker(value: Any) -> str:
    if type(value) is not str or value != value.upper().strip() or value in {"NAN", "NONE", "NULL"} or \
            re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,20}", value) is None:
        raise ValueError("EXACT_BOOK_IDENTITY_REQUIRED")
    return value


def session_target(source: pd.DataFrame, report_session: str | None) -> pd.DataFrame:
    """Select a dated book at the pinned session before identity/economics checks."""
    if "rebalance_date" not in source:
        return source.copy()
    if not isinstance(report_session, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_session) is None:
        raise ValueError("DATED_TARGET_SESSION_REQUIRED")
    dates = pd.to_datetime(source.rebalance_date, errors="coerce")
    if dates.isna().any():
        raise ValueError("TARGET_SNAPSHOT_DATE_REQUIRED")
    selected = select_target_snapshot(source, target_date=report_session)
    if selected.empty:
        raise ValueError("TARGET_SNAPSHOT_UNAVAILABLE_AT_SESSION")
    return selected


PREVIEW_FILES = ("orders_preview.csv", "positions_current.csv", "target_weights.csv",
                 "projected_positions_after_orders.csv", "order_batch_manifest.json",
                 "preview_metrics.json", "preview_report.md")


def invalidate_previews(output: Path) -> None:
    """Only derived bridge outputs; never recurse or touch an accepted book."""
    paths = [output / "summary.json", output / "summary.md"]
    for portfolio in PORTFOLIOS:
        paths.extend(output / portfolio / name for name in
                     ("paper_action_target_book.csv", "paper_orders_preview.csv", "summary.json", "account_state.bound.json"))
        paths.extend(output / portfolio / "account_order_preview" / name for name in PREVIEW_FILES)
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()) or \
                any(p.is_symlink() for p in path.parents if p != output.parent):
            raise ValueError("DERIVED_OUTPUT_PATH_REFUSED")
        if path.exists() and not path.is_file():
            raise ValueError("DERIVED_OUTPUT_PATH_REFUSED")
    for path in paths:
        if path.exists():
            path.unlink()


def checked_inputs(args: argparse.Namespace, latest: Path, monitor_raw: bytes) -> dict[str, Any]:
    """Prepare-only input contract. Pins do not supply absent real approvals.

    No existing producer satisfies all these actual-input prerequisites yet.
    Tests use synthetic actual-shaped evidence with the preview call stubbed.
    """
    from tools import daily_crisis_report_clock as clock
    monitor = json.loads(monitor_raw)
    if not isinstance(monitor, dict) or monitor.get("schema_version") != "daily-crisis-monitor-v2" or \
            monitor.get("current_report_status") != "CURRENT_LEGACY_DIAGNOSTIC" or \
            monitor.get("data_health") != "DATE_CURRENT_DIAGNOSTIC" or \
            any(type(monitor.get(key)) is not str or monitor[key] not in CANONICAL_STATES
                for key in ("state", "raw_state")) or monitor.get("state") == "DEGRADED_DATA":
        raise ValueError("CURRENT_TYPED_MONITOR_REQUIRED")
    if monitor.get("source_clock_authenticated") is not True or monitor.get("canonical_regime_authorized") is not True or \
            monitor.get("auto_trade_allowed") is not False or monitor.get("paper_actions_only") is not True:
        raise ValueError("REAL_INPUT_WAIT")
    now = clock.trusted_now()
    session = monitor.get("risk_as_of_session")
    times = clock.session_times(session)
    if times is None or session != now.astimezone(clock.NY).date().isoformat() or \
            not times["AFTER_CLOSE"] <= clock.stamp(monitor.get("generated_at_utc")) <= now:
        raise ValueError("CURRENT_MONITOR_CLOCK_REQUIRED")
    proof_path = getattr(args, "evidence_manifest", None)
    pin = getattr(args, "expected_evidence_sha256", None)
    if not proof_path or not isinstance(pin, str) or re.fullmatch(r"[0-9a-f]{64}", pin) is None:
        raise ValueError("ECONOMIC_EVIDENCE_PIN_REQUIRED")
    proof_raw = clock.bounded(repo_path(proof_path), 1024*1024)
    if len(proof_raw) > 1024*1024 or hashlib.sha256(proof_raw).hexdigest() != pin:
        raise ValueError("ECONOMIC_EVIDENCE_PIN_MISMATCH")
    proof = json.loads(proof_raw)
    if proof.get("schema") != "crisis-paper-bridge-evidence-v1" or proof.get("report_session") != session or \
            proof.get("monitor_sha256") != hashlib.sha256(monitor_raw).hexdigest() or \
            proof.get("policy_sha256") != hashlib.sha256((REPO_ROOT/"tools/run287_crisis_policy.py").read_bytes()).hexdigest():
        raise ValueError("ECONOMIC_EVIDENCE_BINDING")
    prepared = {}
    for portfolio in PORTFOLIOS:
        entry = proof["portfolios"][portfolio]
        target = (latest/"reports"/f"operating_{portfolio}_target_book.csv").read_bytes()
        account = (latest/"broker_replay"/portfolio/"account_state_latest.json").read_bytes()
        if entry.get("target_sha256") != hashlib.sha256(target).hexdigest() or \
                entry.get("account_sha256") != hashlib.sha256(account).hexdigest() or \
                entry.get("book_session") != session or not isinstance(entry.get("accepted_book_receipt_sha256"), str) or \
                re.fullmatch(r"[0-9a-f]{64}", entry["accepted_book_receipt_sha256"]) is None:
            raise ValueError("ACCEPTED_BOOK_BINDING_REQUIRED")
        target_frame = session_target(pd.read_csv(io.BytesIO(target)), session)
        if target_frame.empty or "ticker" not in target_frame or target_frame.ticker.duplicated().any():
            raise ValueError("ACCEPTED_BOOK_BINDING_REQUIRED")
        target_names = [strict_ticker(ticker) for ticker in target_frame.ticker]
        account_json = json.loads(account)
        if account_json.get("as_of_date") != session or strict_number(account_json.get("cash_usd")) < 0:
            raise ValueError("ACCEPTED_BOOK_SESSION_REQUIRED")
        held = account_json.get("positions")
        if not isinstance(held, list):
            raise ValueError("ACCEPTED_BOOK_BINDING_REQUIRED")
        held_names = []
        for row in held:
            if not isinstance(row, dict) or not isinstance(row.get("ticker"), str) or strict_number(row.get("shares")) < 0:
                raise ValueError("ACCEPTED_BOOK_BINDING_REQUIRED")
            held_names.append(strict_ticker(row["ticker"]))
        if len(held_names) != len(set(held_names)) or not all(held_names):
            raise ValueError("ACCEPTED_BOOK_BINDING_REQUIRED")
        for ticker in set(target_names) | set(held_names):
            if str(ticker).upper() == "CASH":
                continue
            facts = entry["economics"][str(ticker).upper()]
            for field in ("net_er", "downside", "cost_bps", "liquidity_usd"):
                value = strict_number(facts[field])
                if field in ("downside", "cost_bps") and value < 0 or field == "liquidity_usd" and value <= 0:
                    raise ValueError("ECONOMIC_EVIDENCE_REQUIRED")
            if strict_number(facts["cost_bps"]) != strict_number(args.cost_bps):
                raise ValueError("COST_EVIDENCE_MISMATCH")
            if not isinstance(facts.get("receipt_sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", facts["receipt_sha256"]) is None:
                raise ValueError("ECONOMIC_EVIDENCE_REQUIRED")
        prepared[portfolio] = dict(target=target_frame, account=account)
    return dict(monitor=monitor, portfolios=prepared, report_session=session, evidence_sha256=pin)


def action_plan(monitor: dict[str, Any], portfolio: str) -> dict[str, Any]:
    if portfolio not in PORTFOLIOS:
        raise ValueError("PORTFOLIO_ACTION_SCOPE_REQUIRED")
    actions = monitor.get("paper_action_candidates")
    if not isinstance(actions, list) or any(not isinstance(a, dict) or a.get("action_type") not in ALLOWED_ACTION_TYPES for a in actions):
        raise ValueError("TYPED_ACTIONS_REQUIRED")
    for action in actions:
        scope = action.get("portfolio_kind")
        if scope is not None and scope not in PORTFOLIOS or \
                action["action_type"] in {"raise_cash", "trim_position"} and scope not in PORTFOLIOS:
            raise ValueError("PORTFOLIO_ACTION_SCOPE_REQUIRED")
    actions = [a for a in actions if a.get("portfolio_kind") in (None, portfolio)]
    raise_cash_targets = [strict_number(a.get("target_cash_weight")) for a in actions if a.get("action_type") == "raise_cash"]
    trim_tickers = {}
    for action in actions:
        if action.get("action_type") != "trim_position":
            continue
        ticker = strict_ticker(action.get("ticker"))
        if not ticker or ticker == "CASH" or ticker in trim_tickers:
            raise ValueError("TRIM_IDENTITY_OR_DUPLICATE")
        current, trim = strict_number(action.get("current_weight")), strict_number(action.get("trim_weight"))
        if not 0 <= trim <= current <= 1:
            raise ValueError("TRIM_WEIGHT_INVALID")
        trim_tickers[ticker] = dict(current_weight=current, trim_weight=trim)
    return {
        "state": adapt_crisis_state(
            monitor.get("state"), monitor.get("reentry_stage")
        ),
        "raw_state": adapt_crisis_state(
            monitor.get("raw_state"), monitor.get("reentry_stage")
        ),
        "auto_trade_allowed": bool(monitor.get("auto_trade_allowed")),
        "paper_actions_only": bool(monitor.get("paper_actions_only", True)),
        "actions": actions,
        "action_types": sorted({str(a.get("action_type")) for a in actions}),
        "target_cash_weight": max(raise_cash_targets) if raise_cash_targets else None,
        "block_new_buys": any(a.get("action_type") == "block_new_buys" for a in actions),
        "trim_tickers": trim_tickers,
        "portfolio_kind": portfolio,
    }


def derive_target_book(source: pd.DataFrame, portfolio: str, plan: dict[str, Any],
                       report_session: str | None = None) -> pd.DataFrame:
    """Pure fixture-capable parity calculation, not an accepted target write."""
    if plan.get("portfolio_kind") != portfolio:
        raise ValueError("PORTFOLIO_ACTION_SCOPE_REQUIRED")
    source = session_target(source, report_session)
    if "ticker" not in source or source.ticker.duplicated().any():
        raise ValueError("TARGET_IDENTITY_REQUIRED")
    for ticker in source.ticker:
        strict_ticker(ticker)
    weight_col = "target_weight" if "target_weight" in source else "weight"
    if weight_col not in source or not all(0 <= strict_number(x) <= 1 for x in source[weight_col]):
        raise ValueError("TARGET_WEIGHT_REQUIRED")
    target = normalize_target(source, portfolio, target_date=report_session or "")
    if target.empty:
        raise ValueError("TARGET_BOOK_REQUIRED")
    out = target.copy()
    policy = resolve_reserve_asset_policy(context="current_paper")
    reserve_reason_reconciliation(out, policy=policy, weight_col="target_weight")
    if not math.isclose(float(out.target_weight.sum()), 1.0, abs_tol=1e-9):
        raise ValueError("TARGET_WEIGHT_CONSERVATION")
    cash_mask = out.ticker.eq("CASH")
    base_cash = float(out.loc[cash_mask, "target_weight"].sum())
    incremental = 0.0
    for ticker, trim in (plan.get("trim_tickers") or {}).items():
        mask = out.ticker.eq(ticker)
        if int(mask.sum()) != 1:
            raise ValueError("TRIM_BOOK_IDENTITY_MISMATCH")
        old = float(out.loc[mask, "target_weight"].sum())
        current, amount = strict_number(trim["current_weight"]), strict_number(trim["trim_weight"])
        if not 0 <= amount <= current <= 1 or not math.isclose(old, current, abs_tol=1e-9):
            raise ValueError("TRIM_BOOK_WEIGHT_MISMATCH")
        out.loc[mask, "target_weight"] = old - amount
        incremental += amount
    final_cash = base_cash + incremental
    requested = plan.get("target_cash_weight")
    if requested is not None and not 0 <= strict_number(requested) <= final_cash + 1e-9:
        raise ValueError("CASH_TARGET_UNSUPPORTED_BY_CANONICAL_TRIMS")
    for reason in RESERVE_REASONS:
        if reason not in out:
            out[reason] = 0.0
        out[reason] = pd.to_numeric(out[reason], errors="raise")
        if not out[reason].map(lambda x: math.isfinite(x) and x >= 0).all():
            raise ValueError("RESERVE_REASON_INVALID")
    prior_reasons = float(sum(out[reason].sum() for reason in RESERVE_REASONS))
    if prior_reasons and not math.isclose(prior_reasons, base_cash, abs_tol=1e-9):
        raise ValueError("RESERVE_REASON_RECONCILIATION")
    if not cash_mask.any():
        out = pd.concat([out, pd.DataFrame([dict(ticker="CASH", target_weight=0.0,
            **{reason:0.0 for reason in RESERVE_REASONS})])], ignore_index=True)
    index = out.index[out.ticker.eq("CASH")][0]
    out.loc[index, "target_weight"] = final_cash
    if not prior_reasons:
        out.loc[index, "capacity_unallocated"] = base_cash
    reason = "data_block_reserve" if plan.get("state") == "DEGRADED_DATA" else "reentry_pending" if str(plan.get("state", "")).startswith("REENTRY_STAGE_") else "crisis_reserve"
    out.loc[index, reason] += incremental
    if not math.isclose(float(sum(out[x].sum() for x in RESERVE_REASONS)), final_cash, abs_tol=1e-9):
        raise ValueError("RESERVE_REASON_RECONCILIATION")
    # The source hash describes the accepted pre-trim reserve. Verify it above,
    # then issue the canonical derived hash for the changed cash/reason values.
    out = out.drop(columns=[RESERVE_REASON_SOURCE_HASH_FIELD], errors="ignore")
    derived = reserve_reason_reconciliation(out, policy=policy, weight_col="target_weight")
    out[RESERVE_REASON_SOURCE_HASH_FIELD] = derived[RESERVE_REASON_SOURCE_HASH_FIELD]
    out["bridge_reason"] = ",".join(plan.get("action_types") or [])
    return out.sort_values("target_weight", ascending=False).reset_index(drop=True)


def held_tickers(account_state: dict[str, Any]) -> set[str]:
    rows = account_state.get("positions") or []
    out: set[str] = set()
    if isinstance(rows, list):
        for row in rows:
            ticker = str((row or {}).get("ticker") or "").upper().strip()
            if ticker and safe_float((row or {}).get("shares"), 0.0) > 0:
                out.add(ticker)
    return out


class PreviewArgs:
    pass


def run_preview_for_portfolio(
    *,
    latest_run: Path,
    price_cache: Path,
    output_dir: Path,
    portfolio: str,
    plan: dict[str, Any],
    cost_bps: float,
    prepared: dict[str, Any],
    report_session: str,
) -> dict[str, Any]:
    if not ACTUAL_PREVIEW_ACTIVATED:
        raise ValueError("ACTUAL_PREVIEW_NOT_ACTIVATED")
    portfolio_out = output_dir / portfolio
    portfolio_out.mkdir(parents=True, exist_ok=True)
    target = derive_target_book(prepared["target"], portfolio, plan, report_session)
    derived_target = portfolio_out / "paper_action_target_book.csv"
    target.to_csv(derived_target, index=False)

    args = PreviewArgs()
    # Consume the exact accepted input bytes rather than rereading a mutable
    # restored account after the preflight hash check.
    bound_account = portfolio_out / "account_state.bound.json"
    bound_account.write_bytes(prepared["account"])
    args.account_state = str(bound_account)
    args.target = str(derived_target)
    args.price_cache = str(price_cache)
    args.portfolio_kind = portfolio
    args.output_dir = str(portfolio_out / "account_order_preview")
    args.as_of_date = report_session
    args.target_date = report_session
    args.cost_bps = float(cost_bps)
    args.limit_margin_pct = 0.25
    args.min_trade_usd = 25.0
    args.fractional_shares = False
    payload = run_order_preview(args)

    orders_path = portfolio_out / "account_order_preview" / "orders_preview.csv"
    orders = read_csv(orders_path)
    account = json.loads(prepared["account"])
    existing = held_tickers(account)
    if not orders.empty:
        orders["auto_trade_allowed"] = False
        orders["paper_only"] = True
        orders["approval_required"] = True
        orders["crisis_state"] = str(plan.get("state") or "")
        orders["paper_action_types"] = ",".join(plan.get("action_types") or [])
        orders["approval_status"] = "pending_user_approval"
        if plan.get("block_new_buys"):
            new_buy = orders["side"].astype(str).str.upper().eq("BUY") & ~orders["ticker"].astype(str).str.upper().isin(existing)
            orders.loc[new_buy, "status"] = "blocked_new_buy_pending_approval"
            orders.loc[new_buy, "approval_status"] = "blocked_new_buy_pending_user_approval"
    orders.to_csv(portfolio_out / "paper_orders_preview.csv", index=False)
    summary = {
        "portfolio": portfolio,
        "status": payload.get("status"),
        "auto_trade_allowed": False,
        "paper_only": True,
        "approval_required": True,
        "paper_action_types": plan.get("action_types") or [],
        "target_cash_weight": plan.get("target_cash_weight"),
        "derived_target": str(derived_target),
        "order_count": int(len(orders)),
        "blocked_new_buy_count": int((orders.get("status", pd.Series(dtype=str)).astype(str) == "blocked_new_buy_pending_approval").sum()) if not orders.empty else 0,
        "preview_metrics": payload,
    }
    write_json(portfolio_out / "summary.json", summary)
    return summary


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Crisis Paper Order Bridge",
        "",
        f"- status: `{payload.get('status')}`",
        f"- data health: `{payload.get('data_health', 'FIXTURE_OR_SEPARATELY_APPROVED_INPUT')}`",
        "- auto_trade_allowed: `false`",
        "- paper_only: `true`",
        "- approval_required: `true`",
        f"- monitor_state: `{payload.get('monitor_state')}`",
        f"- action_types: `{','.join(payload.get('paper_action_types') or [])}`",
        "",
        "| Portfolio | Status | Orders | Blocked New Buys | Target Cash |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload.get("portfolios") or []:
        target_cash = row.get("target_cash_weight")
        target_cash_s = "" if target_cash is None else f"{safe_float(target_cash):.2%}"
        lines.append(
            f"| {row.get('portfolio')} | {row.get('status')} | {row.get('order_count')} | {row.get('blocked_new_buy_count')} | {target_cash_s} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    latest_run = repo_path(args.latest_run)
    price_cache = repo_path(args.price_cache)
    output_dir = repo_path(args.output_dir)
    protected = [latest_run/"daily_crisis_monitor/summary.json", price_cache,
                 REPO_ROOT/"tools/run_crisis_paper_order_bridge.py"]
    protected.extend(latest_run/"reports"/f"operating_{p}_target_book.csv" for p in PORTFOLIOS)
    protected.extend(latest_run/"broker_replay"/p/"account_state_latest.json" for p in PORTFOLIOS)
    if getattr(args, "evidence_manifest", None):
        protected.append(repo_path(args.evidence_manifest))
    if output_dir.is_symlink() or any(p.resolve().is_relative_to(output_dir.resolve()) for p in protected) or \
            output_dir.resolve().is_relative_to(price_cache.resolve()):
        raise ValueError("BRIDGE_INPUT_OUTPUT_OVERLAP")
    output_dir.mkdir(parents=True, exist_ok=True)
    invalidate_previews(output_dir)
    blocked = dict(schema_version="crisis-paper-order-bridge-v1", status="blocked",
                   data_health="REAL_INPUT_WAIT", auto_trade_allowed=False, paper_only=True,
                   approval_required=True, paper_action_types=[], portfolios=[],
                   monitor_state=None, monitor_raw_state=None)
    # Replace the previous successful publication before any inference/preview.
    write_json(output_dir/"summary.json", blocked)
    (output_dir/"summary.md").write_text(render_report(blocked), encoding="utf-8")
    try:
        monitor_raw = (latest_run/"daily_crisis_monitor/summary.json").read_bytes()
        inputs = checked_inputs(args, latest_run, monitor_raw)
        if not ACTUAL_PREVIEW_ACTIVATED:
            raise ValueError("ACTUAL_PREVIEW_NOT_ACTIVATED")
        monitor = inputs["monitor"]
        plans = {p: action_plan(monitor, p) for p in PORTFOLIOS}
        portfolio_summaries = [
            run_preview_for_portfolio(latest_run=latest_run, price_cache=price_cache,
                output_dir=output_dir, portfolio=p, plan=plans[p],
                cost_bps=strict_number(args.cost_bps), prepared=inputs["portfolios"][p],
                report_session=inputs["report_session"])
            for p in PORTFOLIOS]
        if any(row.get("status") != "completed" for row in portfolio_summaries):
            raise ValueError("PREVIEW_PREREQUISITE_REFUSED")
    except Exception:
        invalidate_previews(output_dir)
        blocked["blocker"] = "CURRENT_MONITOR_OR_ECONOMIC_PROOF_REQUIRED"
        write_json(output_dir/"summary.json", blocked)
        (output_dir/"summary.md").write_text(render_report(blocked), encoding="utf-8")
        return blocked
    payload = {
        "schema_version": "crisis-paper-order-bridge-v1",
        "status": "completed",
        "evidence_sha256": inputs["evidence_sha256"],
        "report_session": inputs["report_session"],
        "auto_trade_allowed": False,
        "paper_only": True,
        "approval_required": True,
        "monitor_state": monitor["state"],
        "monitor_raw_state": monitor["raw_state"],
        "paper_action_types": sorted({action for plan in plans.values() for action in plan["action_types"]}),
        "portfolios": portfolio_summaries,
    }
    write_json(output_dir / "summary.json", payload)
    (output_dir / "summary.md").write_text(render_report(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "portfolios": len(portfolio_summaries)}, indent=2))
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-run", default="outputs")
    parser.add_argument("--price-cache", default="cache_prices")
    parser.add_argument("--output-dir", default="outputs/crisis_paper_order_bridge")
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument("--evidence-manifest", help="Externally accepted book/economic input receipt bundle; missing stays REAL_INPUT_WAIT")
    parser.add_argument("--expected-evidence-sha256")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    payload = run(parse_args(argv))
    return 0 if payload.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
