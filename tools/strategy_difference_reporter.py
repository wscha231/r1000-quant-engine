#!/usr/bin/env python3
"""Read-only comparison of two existing broker replay output directories.

This module never replays a strategy, recalculates NAV, or changes an evaluator.
It compares artifacts already emitted by run_broker_ledger_replay.py and marks
unavailable observations explicitly instead of synthesizing missing economics.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

NOT_AVAILABLE = "NOT_AVAILABLE"
EPS = 1e-12


class ComparisonInputError(ValueError):
    """Raised when an existing replay artifact is structurally ambiguous."""


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, low_memory=False)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ComparisonInputError(f"{path.name}: expected JSON object")
    return payload


def _parsed_dates(frame: pd.DataFrame, *, name: str, date_col: str = "date") -> pd.Series:
    if date_col not in frame.columns:
        raise ComparisonInputError(f"{name}: missing required {date_col!r}")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    if dates.isna().any():
        raise ComparisonInputError(f"{name}: invalid date")
    if not dates.is_monotonic_increasing:
        raise ComparisonInputError(f"{name}: time_order_inversion")
    return dates.dt.normalize()


def _normalize_holdings(frame: pd.DataFrame | None, *, name: str) -> pd.DataFrame | None:
    if frame is None:
        return None
    required = {"date", "ticker"}
    if not required.issubset(frame.columns):
        raise ComparisonInputError(f"{name}: missing holdings identity fields")
    out = frame.copy(deep=True)
    dates = _parsed_dates(out, name=name)
    tickers = out["ticker"].astype(str).str.upper().str.strip()
    if tickers.eq("").any():
        raise ComparisonInputError(f"{name}: empty ticker")
    key = pd.DataFrame({"date": dates, "ticker": tickers})
    if key.duplicated(["date", "ticker"]).any():
        raise ComparisonInputError(f"{name}: duplicate_session_asset")
    out["date"] = dates.dt.date.astype(str)
    out["ticker"] = tickers
    if "shares" in out.columns:
        active = pd.to_numeric(out["shares"], errors="coerce").abs() > EPS
    elif "weight" in out.columns:
        active = pd.to_numeric(out["weight"], errors="coerce").abs() > EPS
    else:
        raise ComparisonInputError(f"{name}: neither shares nor weight is available")
    return out.loc[active].reset_index(drop=True)


def _normalize_equity(frame: pd.DataFrame | None, *, name: str) -> pd.DataFrame | None:
    if frame is None:
        return None
    out = frame.copy(deep=True)
    dates = _parsed_dates(out, name=name)
    if dates.duplicated().any():
        raise ComparisonInputError(f"{name}: duplicate_session")
    out["date"] = dates.dt.date.astype(str)
    return out


def _normalize_trades(frame: pd.DataFrame | None, *, name: str) -> pd.DataFrame | None:
    if frame is None:
        return None
    out = frame.copy(deep=True)
    required = {"date", "ticker", "side"}
    if not required.issubset(out.columns):
        raise ComparisonInputError(f"{name}: missing trade identity fields")
    dates = _parsed_dates(out, name=name)
    out["date"] = dates.dt.date.astype(str)
    out["ticker"] = out["ticker"].astype(str).str.upper().str.strip()
    out["side"] = out["side"].astype(str).str.upper().str.strip()
    return out


def load_replay_bundle(path: str | Path, *, label: str) -> dict[str, Any]:
    replay_dir = Path(path)
    return {
        "replay_dir": replay_dir,
        "holdings": _normalize_holdings(_read_csv(replay_dir / "holdings_daily.csv"), name=f"{label}.holdings_daily"),
        "trades": _normalize_trades(_read_csv(replay_dir / "trades.csv"), name=f"{label}.trades"),
        "equity": _normalize_equity(_read_csv(replay_dir / "equity_curve.csv"), name=f"{label}.equity_curve"),
        "metrics": _read_json(replay_dir / "metrics.json"),
    }


def _holdings_map(frame: pd.DataFrame | None) -> dict[str, dict[str, dict[str, Any]]]:
    if frame is None:
        return {}
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for row in frame.to_dict("records"):
        result.setdefault(str(row["date"]), {})[str(row["ticker"])] = row
    return result


def _trade_reason_map(frame: pd.DataFrame | None) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = {}
    if frame is None:
        return result
    for row in frame.to_dict("records"):
        reason = str(row.get("reason") or "").strip()
        if reason:
            result.setdefault((str(row["date"]), str(row["ticker"])), []).append(reason)
    return result




def _trade_signature_map(frame: pd.DataFrame | None) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if frame is None:
        return result
    fields = ["side", "quantity", "fill_price", "gross_value", "fee_usd", "reason"]
    for row in frame.to_dict("records"):
        payload = {field: row.get(field) for field in fields if field in row}
        result.setdefault(str(row["date"]), {}).setdefault(str(row["ticker"]), []).append(payload)
    for by_asset in result.values():
        for asset, rows in by_asset.items():
            by_asset[asset] = sorted(rows, key=lambda rec: json.dumps(rec, sort_keys=True, default=str))
    return result


def _records_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    if len(left) != len(right):
        return False
    fields = {key for row in left + right for key in row}
    for lrow, rrow in zip(left, right):
        for field in fields:
            lv, rv = lrow.get(field), rrow.get(field)
            ln, rn = _numeric(lv), _numeric(rv)
            if ln is not None and rn is not None:
                if not math.isclose(ln, rn, rel_tol=1e-9, abs_tol=1e-10):
                    return False
            elif str(lv or "") != str(rv or ""):
                return False
    return True

def _nonzero(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and not math.isclose(float(value), 0.0, rel_tol=1e-12, abs_tol=1e-12)

def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_delta(control: dict[str, Any] | None, candidate: dict[str, Any] | None, key: str) -> float | str:
    if not control or not candidate:
        return NOT_AVAILABLE
    left = _numeric(control.get(key))
    right = _numeric(candidate.get(key))
    if left is None or right is None:
        return NOT_AVAILABLE
    return right - left


def _comparable_performance_delta(
    control: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    key: str,
) -> float | str:
    if not control or not candidate:
        return NOT_AVAILABLE
    allowed = {"completed", "research_completed", "COMPLETE"}
    if str(control.get("status")) not in allowed or str(candidate.get("status")) not in allowed:
        return NOT_AVAILABLE
    control_mode = str(control.get("metric_mode") or "")
    candidate_mode = str(candidate.get("metric_mode") or "")
    if not control_mode or control_mode != candidate_mode or control_mode == "DO_NOT_USE":
        return NOT_AVAILABLE
    return _metric_delta(control, candidate, key)


def _trade_count(bundle: dict[str, Any]) -> int | str:
    metrics = bundle.get("metrics") or {}
    metric_count = _numeric(metrics.get("trade_count"))
    if metric_count is not None:
        return int(metric_count)
    trades = bundle.get("trades")
    return int(len(trades)) if trades is not None else NOT_AVAILABLE


def _total_fee_cost(bundle: dict[str, Any]) -> float | str:
    """Use evaluator-emitted fee totals only; never rebuild fee economics."""

    metrics = bundle.get("metrics") or {}
    metric_fee = _numeric(metrics.get("total_fees_usd"))
    return metric_fee if metric_fee is not None else NOT_AVAILABLE


def _delta(left: Any, right: Any) -> float | str:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(right) - float(left)
    return NOT_AVAILABLE


def _latest_common_equity_delta(control: pd.DataFrame | None, candidate: pd.DataFrame | None) -> dict[str, Any]:
    result = {
        "latest_common_session": NOT_AVAILABLE,
        "nav_delta_usd": NOT_AVAILABLE,
        "cash_delta_usd": NOT_AVAILABLE,
        "cash_weight_delta": NOT_AVAILABLE,
    }
    if control is None or candidate is None:
        return result
    common = sorted(set(control["date"]) & set(candidate["date"]))
    if not common:
        return result
    session = common[-1]
    c = control.loc[control["date"].eq(session)].iloc[0]
    k = candidate.loc[candidate["date"].eq(session)].iloc[0]
    result["latest_common_session"] = session
    for key, out_key in [
        ("equity_usd", "nav_delta_usd"),
        ("cash_usd", "cash_delta_usd"),
        ("cash_weight", "cash_weight_delta"),
    ]:
        cv, kv = _numeric(c.get(key)), _numeric(k.get(key))
        if cv is not None and kv is not None:
            result[out_key] = kv - cv
    return result


def _session_delta_frame(control: pd.DataFrame | None, candidate: pd.DataFrame | None) -> pd.DataFrame:
    columns = ["session", "control_nav_usd", "candidate_nav_usd", "nav_delta_usd", "cash_delta_usd", "cash_weight_delta"]
    if control is None or candidate is None:
        return pd.DataFrame(columns=columns)
    c = control.set_index("date", drop=False)
    k = candidate.set_index("date", drop=False)
    rows: list[dict[str, Any]] = []
    for session in sorted(set(c.index) & set(k.index)):
        crow, krow = c.loc[session], k.loc[session]
        cn, kn = _numeric(crow.get("equity_usd")), _numeric(krow.get("equity_usd"))
        cc, kc = _numeric(crow.get("cash_usd")), _numeric(krow.get("cash_usd"))
        cw, kw = _numeric(crow.get("cash_weight")), _numeric(krow.get("cash_weight"))
        rows.append({
            "session": session,
            "control_nav_usd": cn,
            "candidate_nav_usd": kn,
            "nav_delta_usd": (kn - cn) if cn is not None and kn is not None else NOT_AVAILABLE,
            "cash_delta_usd": (kc - cc) if cc is not None and kc is not None else NOT_AVAILABLE,
            "cash_weight_delta": (kw - cw) if cw is not None and kw is not None else NOT_AVAILABLE,
        })
    return pd.DataFrame(rows, columns=columns)


def _reentry_events(frame: pd.DataFrame | None) -> list[dict[str, str]] | str:
    if frame is None:
        return NOT_AVAILABLE
    sold: set[str] = set()
    out: list[dict[str, str]] = []
    for row in frame.to_dict("records"):
        ticker, side = str(row["ticker"]), str(row["side"])
        if side == "SELL":
            sold.add(ticker)
        elif side == "BUY" and ticker in sold:
            out.append({"session": str(row["date"]), "ticker": ticker, "reason": str(row.get("reason") or "")})
            sold.remove(ticker)
    return out


def _comparison_identity(
    *,
    strategy_id: str = "",
    variant_id: str = "",
    parent_strategy_id: str = "",
    changed_module: str = "",
    changed_module_version: str = "",
    evaluation_ref: str = "",
    control_replay_ref: str = "",
    candidate_replay_ref: str = "",
    module_id: str = "",
    module_version: str = "",
    policy_id: str = "",
    hold_exit_policy_config: str = "",
    policy_audit_identity: str = "",
) -> dict[str, Any]:
    """Return provenance exactly as supplied; never interpret it economically."""

    return {
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "parent_strategy_id": parent_strategy_id,
        "changed_module": changed_module,
        "changed_module_version": changed_module_version,
        "evaluation_ref": evaluation_ref,
        "control_replay_ref": control_replay_ref,
        "candidate_replay_ref": candidate_replay_ref,
        "module_id": module_id,
        "module_version": module_version,
        "policy_id": policy_id,
        "hold_exit_policy_config": hold_exit_policy_config,
        "policy_audit_identity": policy_audit_identity,
        "identity_only_not_economic_input": True,
    }


def compare_replay_outputs(
    control: dict[str, Any],
    candidate: dict[str, Any],
    *,
    strategy_id: str = "",
    variant_id: str = "",
    parent_strategy_id: str = "",
    changed_module: str = "",
    changed_module_version: str = "",
    evaluation_ref: str = "",
    control_replay_ref: str = "",
    candidate_replay_ref: str = "",
    module_id: str = "",
    module_version: str = "",
    policy_id: str = "",
    hold_exit_policy_config: str = "",
    policy_audit_identity: str = "",
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    comparison_identity = _comparison_identity(
        strategy_id=strategy_id,
        variant_id=variant_id,
        parent_strategy_id=parent_strategy_id,
        changed_module=changed_module,
        changed_module_version=changed_module_version,
        evaluation_ref=evaluation_ref,
        control_replay_ref=control_replay_ref,
        candidate_replay_ref=candidate_replay_ref,
        module_id=module_id,
        module_version=module_version,
        policy_id=policy_id,
        hold_exit_policy_config=hold_exit_policy_config,
        policy_audit_identity=policy_audit_identity,
    )
    control_holdings = control.get("holdings")
    candidate_holdings = candidate.get("holdings")
    if control_holdings is None or candidate_holdings is None:
        report = {
            "schema_version": "strategy-difference-report-v1",
            "status": "insufficient_evidence",
            "research_only": True,
            "production_activation_allowed": False,
            "comparison_identity": comparison_identity,
            "first_divergence_session": NOT_AVAILABLE,
            "first_divergence_asset": NOT_AVAILABLE,
            "first_divergence_reason": NOT_AVAILABLE,
            "attribution": {
                "classification": "INSUFFICIENT_EVIDENCE",
                "observed_difference": False,
                "attributable_candidate": False,
                "insufficient_evidence": True,
                "post_first_divergence_state_path_may_chain": False,
            },
        }
        return report, pd.DataFrame(), _session_delta_frame(control.get("equity"), candidate.get("equity"))

    control_map = _holdings_map(control_holdings)
    candidate_map = _holdings_map(candidate_holdings)
    control_reasons = _trade_reason_map(control.get("trades"))
    candidate_reasons = _trade_reason_map(candidate.get("trades"))
    control_trade_map = _trade_signature_map(control.get("trades"))
    candidate_trade_map = _trade_signature_map(candidate.get("trades"))

    control_equity = control.get("equity")
    candidate_equity = candidate.get("equity")
    session_grid = set(control_map) | set(candidate_map)
    if control_equity is not None:
        session_grid |= set(control_equity["date"])
    if candidate_equity is not None:
        session_grid |= set(candidate_equity["date"])
    session_grid |= set(control_trade_map) | set(candidate_trade_map)
    sessions = sorted(session_grid)

    events: list[dict[str, Any]] = []
    entered_only: list[dict[str, Any]] = []
    exited_only: list[dict[str, Any]] = []
    retained_only: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    first: dict[str, Any] | None = None
    prev_control: set[str] = set()
    prev_candidate: set[str] = set()

    control_eq_sessions = set(control_equity["date"]) if control_equity is not None else set()
    candidate_eq_sessions = set(candidate_equity["date"]) if candidate_equity is not None else set()
    control_eq_map = control_equity.set_index("date", drop=False) if control_equity is not None else None
    candidate_eq_map = candidate_equity.set_index("date", drop=False) if candidate_equity is not None else None

    for session in sessions:
        control_assets = set(control_map.get(session, {}))
        candidate_assets = set(candidate_map.get(session, {}))
        if control_equity is not None and candidate_equity is not None and ((session in control_eq_sessions) != (session in candidate_eq_sessions)):
            event = {"session": session, "asset": NOT_AVAILABLE, "reason": "session_grid_mismatch"}
            events.append(event)
            first = first or event

        candidate_entries = candidate_assets - prev_candidate
        candidate_exits = prev_candidate - candidate_assets
        control_entries = control_assets - prev_control
        control_exits = prev_control - control_assets

        for asset in sorted(candidate_entries - control_assets):
            event = {
                "session": session,
                "asset": asset,
                "reason": "entered_only_in_candidate",
                "candidate_trade_reason": candidate_reasons.get((session, asset), []),
            }
            entered_only.append(event)
            events.append(event)
            first = first or event
        for asset in sorted((candidate_exits & control_assets) & prev_control):
            event = {
                "session": session,
                "asset": asset,
                "reason": "exited_only_in_candidate",
                "candidate_trade_reason": candidate_reasons.get((session, asset), []),
            }
            exited_only.append(event)
            events.append(event)
            first = first or event
        for asset in sorted((control_exits & candidate_assets) & prev_candidate):
            event = {
                "session": session,
                "asset": asset,
                "reason": "retained_only_in_candidate",
                "control_trade_reason": control_reasons.get((session, asset), []),
            }
            retained_only.append(event)
            events.append(event)
            first = first or event

        if (candidate_entries - control_entries) and (candidate_exits - control_exits):
            replacement = {
                "session": session,
                "entered_assets": sorted(candidate_entries - control_entries),
                "exited_assets": sorted(candidate_exits - control_exits),
                "reason": "candidate_transition_contains_entry_and_exit_not_mirrored_by_control",
            }
            replacements.append(replacement)
            events.append({"session": session, "asset": NOT_AVAILABLE, "reason": "replacement_event", **replacement})
            first = first or {"session": session, "asset": NOT_AVAILABLE, "reason": "replacement_event"}

        for asset in sorted(control_assets & candidate_assets):
            crow, krow = control_map[session][asset], candidate_map[session][asset]
            compared = False
            for field, reason in (("shares", "holding_share_delta"), ("weight", "holding_weight_delta")):
                cv, kv = _numeric(crow.get(field)), _numeric(krow.get(field))
                if cv is not None and kv is not None:
                    compared = True
                    if not math.isclose(cv, kv, rel_tol=1e-9, abs_tol=1e-10):
                        event = {"session": session, "asset": asset, "reason": reason, "control_value": cv, "candidate_value": kv}
                        events.append(event)
                        first = first or event
                        break
            if not compared:
                continue

        trade_assets = sorted(set(control_trade_map.get(session, {})) | set(candidate_trade_map.get(session, {})))
        for asset in trade_assets:
            left = control_trade_map.get(session, {}).get(asset, [])
            right = candidate_trade_map.get(session, {}).get(asset, [])
            if not _records_equal(left, right):
                event = {
                    "session": session,
                    "asset": asset,
                    "reason": "trade_event_delta",
                    "control_trades": left,
                    "candidate_trades": right,
                }
                events.append(event)
                first = first or event

        if control_eq_map is not None and candidate_eq_map is not None and session in control_eq_sessions and session in candidate_eq_sessions:
            crow = control_eq_map.loc[session]
            krow = candidate_eq_map.loc[session]
            for field, reason in (("equity_usd", "nav_delta"), ("cash_usd", "cash_delta"), ("cash_weight", "cash_weight_delta")):
                cv, kv = _numeric(crow.get(field)), _numeric(krow.get(field))
                if cv is not None and kv is not None and not math.isclose(cv, kv, rel_tol=1e-9, abs_tol=1e-10):
                    event = {
                        "session": session,
                        "asset": NOT_AVAILABLE,
                        "reason": reason,
                        "control_value": cv,
                        "candidate_value": kv,
                    }
                    events.append(event)
                    first = first or event
                    break

        prev_control, prev_candidate = control_assets, candidate_assets

    hold_delta: dict[str, int] = {}
    for asset in sorted(set(control_holdings["ticker"]) | set(candidate_holdings["ticker"])):
        ccount = int(control_holdings["ticker"].eq(asset).sum())
        kcount = int(candidate_holdings["ticker"].eq(asset).sum())
        if ccount != kcount:
            hold_delta[asset] = kcount - ccount

    control_trade_count = _trade_count(control)
    candidate_trade_count = _trade_count(candidate)
    control_fee = _total_fee_cost(control)
    candidate_fee = _total_fee_cost(candidate)
    latest = _latest_common_equity_delta(control_equity, candidate_equity)

    control_metrics = control.get("metrics")
    candidate_metrics = candidate.get("metrics")
    turnover_delta = _metric_delta(control_metrics, candidate_metrics, "turnover")
    cagr_delta = _comparable_performance_delta(control_metrics, candidate_metrics, "cagr")
    mdd_delta = _comparable_performance_delta(control_metrics, candidate_metrics, "max_dd")

    summary_differences = [
        _delta(control_trade_count, candidate_trade_count),
        turnover_delta,
        _delta(control_fee, candidate_fee),
        latest["cash_delta_usd"],
        latest["cash_weight_delta"],
        latest["nav_delta_usd"],
        cagr_delta,
        mdd_delta,
    ]
    observed = first is not None or any(_nonzero(value) for value in summary_differences)
    row_level_timing_available = first is not None
    direct_module_fields = {"changed_module", "decision_module", "module"}
    candidate_trades = candidate.get("trades")
    directly_attributable = False
    if row_level_timing_available and changed_module and candidate_trades is not None:
        rows = candidate_trades[candidate_trades["date"].astype(str).eq(str(first.get("session")))]
        if first.get("asset") not in {None, NOT_AVAILABLE}:
            rows = rows[rows["ticker"].astype(str).eq(str(first.get("asset")))]
        for field in direct_module_fields & set(rows.columns):
            if rows[field].astype(str).eq(changed_module).any():
                directly_attributable = True
                break
    insufficient = bool(observed and not row_level_timing_available)
    classification = (
        "ATTRIBUTABLE_CANDIDATE" if directly_attributable
        else "INSUFFICIENT_EVIDENCE" if insufficient
        else "OBSERVED_DIFFERENCE" if observed
        else "NO_OBSERVED_DIFFERENCE"
    )

    report = {
        "schema_version": "strategy-difference-report-v1",
        "status": "completed" if observed else "no_divergence",
        "research_only": True,
        "production_activation_allowed": False,
        "comparison_identity": comparison_identity,
        "first_divergence_session": first.get("session") if first else (NOT_AVAILABLE if observed else None),
        "first_divergence_asset": first.get("asset") if first else (NOT_AVAILABLE if observed else None),
        "first_divergence_reason": first.get("reason") if first else (NOT_AVAILABLE if observed else None),
        "entered_only_in_candidate": entered_only,
        "exited_only_in_candidate": exited_only,
        "retained_only_in_candidate": retained_only,
        "replacement_events": replacements,
        "holding_duration_delta_sessions": hold_delta,
        "trade_count_delta": _delta(control_trade_count, candidate_trade_count),
        "turnover_delta": turnover_delta,
        "fee_cost_delta_usd": _delta(control_fee, candidate_fee),
        "latest_common_session": latest["latest_common_session"],
        "cash_delta_usd": latest["cash_delta_usd"],
        "cash_weight_delta": latest["cash_weight_delta"],
        "nav_delta_usd": latest["nav_delta_usd"],
        "cagr_delta": cagr_delta,
        "max_dd_delta": mdd_delta,
        "reentry_events_candidate": _reentry_events(candidate.get("trades")),
        "early_exit_attribution": NOT_AVAILABLE,
        "winner_capture_attribution": NOT_AVAILABLE,
        "attribution": {
            "classification": classification,
            "observed_difference": observed,
            "attributable_candidate": directly_attributable,
            "insufficient_evidence": insufficient,
            "changed_module": changed_module or NOT_AVAILABLE,
            "post_first_divergence_state_path_may_chain": observed,
            "warning": (
                "After the first divergence, later differences may be path-dependent consequences; "
                "do not attribute them directly to changed_module without explicit row-level evidence."
                if observed
                else ""
            ),
        },
        "availability": {
            "turnover_delta": "AVAILABLE" if turnover_delta != NOT_AVAILABLE else NOT_AVAILABLE,
            "cagr_delta": "AVAILABLE" if cagr_delta != NOT_AVAILABLE else NOT_AVAILABLE,
            "max_dd_delta": "AVAILABLE" if mdd_delta != NOT_AVAILABLE else NOT_AVAILABLE,
            "early_exit_attribution": NOT_AVAILABLE,
            "winner_capture_attribution": NOT_AVAILABLE,
        },
    }
    return report, pd.DataFrame(events), _session_delta_frame(control_equity, candidate_equity)


def write_report(output_dir: str | Path, report: dict[str, Any], events: pd.DataFrame, session_deltas: pd.DataFrame) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "strategy_difference_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    events.to_csv(out / "strategy_difference_events.csv", index=False)
    session_deltas.to_csv(out / "strategy_difference_session_deltas.csv", index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-replay", required=True)
    parser.add_argument("--candidate-replay", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--strategy-id", default="")
    parser.add_argument("--variant-id", default="")
    parser.add_argument("--parent-strategy-id", default="")
    parser.add_argument("--changed-module", default="")
    parser.add_argument("--changed-module-version", default="")
    parser.add_argument("--evaluation-ref", default="")
    parser.add_argument("--control-replay-ref", default="")
    parser.add_argument("--candidate-replay-ref", default="")
    parser.add_argument("--module-id", default="")
    parser.add_argument("--module-version", default="")
    parser.add_argument("--policy-id", default="")
    parser.add_argument("--hold-exit-policy-config", default="")
    parser.add_argument("--policy-audit-identity", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        control = load_replay_bundle(args.control_replay, label="control")
        candidate = load_replay_bundle(args.candidate_replay, label="candidate")
        report, events, session_deltas = compare_replay_outputs(
            control,
            candidate,
            strategy_id=args.strategy_id,
            variant_id=args.variant_id,
            parent_strategy_id=args.parent_strategy_id,
            changed_module=args.changed_module,
            changed_module_version=args.changed_module_version,
            evaluation_ref=args.evaluation_ref,
            control_replay_ref=args.control_replay_ref,
            candidate_replay_ref=args.candidate_replay_ref,
            module_id=args.module_id,
            module_version=args.module_version,
            policy_id=args.policy_id,
            hold_exit_policy_config=args.hold_exit_policy_config,
            policy_audit_identity=args.policy_audit_identity,
        )
    except (ComparisonInputError, json.JSONDecodeError, pd.errors.ParserError) as exc:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "strategy-difference-report-v1",
            "status": "rejected",
            "reason": str(exc),
            "research_only": True,
            "production_activation_allowed": False,
        }
        (out / "strategy_difference_report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return 2
    write_report(args.output_dir, report, events, session_deltas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
