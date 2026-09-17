#!/usr/bin/env python3
"""Audit readiness for the research-only scientific weighting protocol.

The auditor validates the frozen method contract and the point-in-time data
needed by a future preregistered challenger.  It deliberately does not fit a
model, select a stock, write a target book, or mutate an operating ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "run287-scientific-weighting-readiness-v1"
CONTRACT_SCHEMA = "run287-scientific-selection-allocation-contract-v1"
READY_STATUS = "READY_FOR_PREREGISTRATION"
BLOCKED_STATUS = "BLOCKED_DATA_READINESS"
INVALID_STATUS = "INVALID_METHOD_CONTRACT"
DEFAULT_CONTRACT = ROOT / "docs" / "run287_scientific_selection_allocation_contract.json"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_ALPHA_RE = re.compile(
    r"(^|_)(future|forward|label|target|outcome|realized)(_|$)", re.IGNORECASE
)
NYSE = mcal.get_calendar("NYSE")


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key:{key}")
        out[key] = value
    return out


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "bytes": 0, "sha256": ""}
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "bytes": int(path.stat().st_size) if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )


def load_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"unsupported table format:{suffix}")


def unique(values: list[str]) -> list[str]:
    return sorted(set(values))


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    normalized = series.astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes"})


def nyse_close_by_session(dates: pd.Series) -> pd.Series:
    normalized = pd.to_datetime(dates, errors="coerce").dt.normalize()
    valid = normalized.dropna()
    if valid.empty:
        return pd.Series(pd.NaT, index=dates.index, dtype="datetime64[ns, UTC]")
    schedule = NYSE.schedule(
        start_date=valid.min().date(),
        end_date=valid.max().date(),
    )
    close_map = {
        pd.Timestamp(session).normalize(): pd.Timestamp(close).tz_convert("UTC")
        for session, close in schedule["market_close"].items()
    }
    values = [close_map.get(pd.Timestamp(value).normalize()) if pd.notna(value) else pd.NaT for value in normalized]
    return pd.Series(pd.to_datetime(values, errors="coerce", utc=True), index=dates.index)


def validate_contract(contract: Any) -> list[str]:
    failures: list[str] = []
    if not isinstance(contract, dict):
        return ["contract_not_object"]
    if contract.get("schema_version") != CONTRACT_SCHEMA:
        failures.append("contract_schema_mismatch")

    layers = contract.get("decision_layers") or {}
    stock_alpha = layers.get("stock_alpha") or {}
    allocation = layers.get("portfolio_allocation") or {}
    macro = layers.get("macro_risk_router") or {}
    if stock_alpha.get("macro_inputs_allowed") is not False:
        failures.append("macro_allowed_in_stock_alpha")
    if stock_alpha.get("portfolio_risk_inputs_allowed") is not False:
        failures.append("portfolio_risk_allowed_in_stock_alpha")
    if allocation.get("may_change_stock_order") is not False:
        failures.append("allocation_may_change_stock_order")
    if macro.get("direct_stock_alpha_points_allowed") is not False:
        failures.append("macro_direct_stock_alpha_points_allowed")
    if macro.get("role") != "accepted_equity_budget_cash_and_risk_constraints_only":
        failures.append("macro_role_not_separated")

    component_model = contract.get("component_model") or {}
    inputs = component_model.get("inputs") or {}
    required_components = {
        "quality_moat",
        "valuation",
        "growth_revisions",
        "leadership_momentum",
        "event_actuals",
        "manager_13f_flow",
    }
    if set(inputs) != required_components:
        failures.append("component_set_mismatch")
    columns: list[str] = []
    for name, spec in inputs.items():
        if not isinstance(spec, dict):
            failures.append(f"component_spec_invalid:{name}")
            continue
        column = str(spec.get("column") or "")
        available = str(spec.get("available_from_column") or "")
        observed = str(spec.get("observed_column") or "")
        if not column or not available or not observed:
            failures.append(f"component_provenance_columns_missing:{name}")
        if column in columns:
            failures.append(f"component_column_duplicate:{column}")
        columns.append(column)
        if FORBIDDEN_ALPHA_RE.search(column):
            failures.append(f"future_or_label_component_forbidden:{name}:{column}")
        if spec.get("coefficient_constraint") != "nonnegative":
            failures.append(f"component_coefficient_not_nonnegative:{name}")

    institutional = inputs.get("manager_13f_flow") or {}
    prior = institutional.get("shadow_prior_weight")
    cap = institutional.get("maximum_learned_weight")
    if not isinstance(prior, (int, float)) or isinstance(prior, bool):
        failures.append("13f_prior_weight_invalid")
    if not isinstance(cap, (int, float)) or isinstance(cap, bool):
        failures.append("13f_maximum_weight_invalid")
    if isinstance(prior, (int, float)) and isinstance(cap, (int, float)):
        if prior < 0.0 or cap < prior or cap > 0.10 + 1e-12:
            failures.append("13f_weight_boundary_invalid")
    if institutional.get("quantity_change_measure") != "split_adjusted_share_change_primary":
        failures.append("13f_price_clean_quantity_measure_missing")
    if institutional.get("market_value_change_role") != "diagnostic_only_due_to_price_contamination":
        failures.append("13f_market_value_delta_not_diagnostic_only")

    if component_model.get("estimator") != "nonnegative_simplex_ridge_anchored_to_preregistered_prior":
        failures.append("component_estimator_mismatch")
    grid = component_model.get("ridge_grid_inner_only")
    if not isinstance(grid, list) or len(grid) < 2 or any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
        for value in (grid or [])
    ):
        failures.append("inner_ridge_grid_invalid")
    if component_model.get("outer_primary_metric") != "mean_decision_date_spearman_ic_63d_benchmark_excess":
        failures.append("primary_metric_mismatch")
    if component_model.get("timing_horizon") != "21d_warning_only_not_selection_weight":
        failures.append("timing_horizon_can_affect_selection")

    manager = contract.get("manager_13f_policy") or {}
    if manager.get("minimum_selected_managers", 0) < 10:
        failures.append("manager_minimum_below_ten")
    if manager.get("manager_reselection_cadence") != "semiannual":
        failures.append("manager_reselection_not_semiannual")
    if manager.get("filing_signal_refresh_cadence") != "quarterly_after_official_filing_availability":
        failures.append("13f_refresh_not_availability_ordered_quarterly")
    if manager.get("manager_performance_measure") != (
        "copyable_long_only_post_filing_portfolio_excess_return_not_reported_total_fund_return"
    ):
        failures.append("manager_performance_measure_not_copyable")

    readiness = contract.get("data_readiness") or {}
    if readiness.get("exchange_calendar") != "NYSE":
        failures.append("decision_exchange_calendar_not_nyse")
    if readiness.get("decision_time_must_be_on_or_after_scheduled_close") is not True:
        failures.append("scheduled_close_decision_boundary_not_required")

    validation = contract.get("validation") or {}
    if validation.get("outer_method") != "anchored_expanding_walk_forward":
        failures.append("outer_validation_not_anchored_walk_forward")
    if validation.get("inner_method") != "anchored_expanding_walk_forward":
        failures.append("inner_validation_not_anchored_walk_forward")
    if validation.get("label_must_be_available_strictly_before_fit_decision") is not True:
        failures.append("strict_label_availability_not_required")
    if validation.get("embargo_nyse_sessions") != 126:
        failures.append("embargo_not_126_nyse_sessions")
    if validation.get("outer_test_may_be_opened_once") is not True:
        failures.append("outer_test_reuse_not_prohibited")
    if validation.get("all_candidate_variants_count_toward_multiplicity") is not True:
        failures.append("multiplicity_population_incomplete")

    portfolio = contract.get("portfolio_allocation") or {}
    anchors = set(portfolio.get("baseline_anchors") or [])
    if anchors != {"equal_weight_selected_names", "accepted_operating_champion"}:
        failures.append("portfolio_baseline_anchors_incomplete")
    if portfolio.get("covariance_estimator") != "ledoit_wolf_shrinkage_on_PIT_daily_returns":
        failures.append("covariance_estimator_not_shrunk")
    if portfolio.get("proposal_only") is not True:
        failures.append("portfolio_layer_not_proposal_only")
    if portfolio.get("evaluation") != "broker_ledger_next_close_after_costs_only_no_weight_level_CAGR_claim":
        failures.append("portfolio_evaluation_not_broker_after_cost")

    acceptance = contract.get("acceptance") or {}
    required_gates = {
        "deflated_sharpe_ratio",
        "probability_of_backtest_overfitting",
        "white_reality_check",
        "canonical_U0_trial_count_binding",
    }
    if set(acceptance.get("multiple_testing_gate_required") or []) != required_gates:
        failures.append("multiple_testing_gates_incomplete")
    if acceptance.get("single_backtest_or_single_market_regime_can_pass") is not False:
        failures.append("single_backtest_can_pass")

    cadence = contract.get("sustainable_operation") or {}
    for key in ("daily", "monthly", "quarterly", "semiannual"):
        if not isinstance(cadence.get(key), list) or not cadence[key]:
            failures.append(f"sustainable_cadence_missing:{key}")

    safety = contract.get("safety") or {}
    expected_safety = {
        "research_only": True,
        "automatic_promotion_allowed": False,
        "champion_change_allowed": False,
        "portfolio_mutation_allowed": False,
        "target_books_written": False,
        "orders_generated": False,
        "operating_ledger_mutated": False,
        "production_or_live_trading_enabled": False,
        "fullrun_executed": False,
    }
    for key, expected in expected_safety.items():
        if safety.get(key) is not expected:
            failures.append(f"safety_mismatch:{key}")
    return unique(failures)


def audit_component_frame(
    frame: pd.DataFrame,
    contract: Mapping[str, Any],
    as_of: pd.Timestamp,
) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    required = set(contract["data_readiness"]["component_frame_required_columns"])
    inputs = contract["component_model"]["inputs"]
    for spec in inputs.values():
        required.update(
            {
                spec["column"],
                spec["available_from_column"],
                spec["observed_column"],
            }
        )
    missing = sorted(required - set(frame.columns))
    if missing:
        return ["component_frame_missing_columns:" + ",".join(missing)], {
            "rows": len(frame),
            "missing_columns": missing,
        }
    if frame.empty:
        return ["component_frame_empty"], {"rows": 0}

    d = frame.copy()
    feature_date = pd.to_datetime(d["feature_date"], errors="coerce").dt.normalize()
    rebalance_date = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    decision_time = pd.to_datetime(d["decision_time_utc"], errors="coerce", utc=True)
    if feature_date.isna().any() or rebalance_date.isna().any() or decision_time.isna().any():
        blockers.append("component_frame_invalid_decision_dates")
    if not feature_date.eq(rebalance_date).all():
        blockers.append("component_frame_feature_rebalance_date_mismatch")
    if decision_time.gt(as_of).any():
        blockers.append("component_frame_future_decision_time")
    scheduled_close = nyse_close_by_session(feature_date)
    if scheduled_close.isna().any():
        blockers.append("component_frame_feature_date_not_nyse_session")
    if (decision_time < scheduled_close).fillna(False).any():
        blockers.append("component_frame_decision_before_scheduled_close")
    ticker = d["ticker"].astype(str).str.upper().str.strip()
    stable_id = d["stable_security_id"].astype(str).str.strip()
    sector = d["sector"].astype(str).str.strip()
    if ticker.eq("").any() or stable_id.eq("").any() or sector.eq("").any():
        blockers.append("component_frame_blank_identity")
    if pd.DataFrame({"date": feature_date, "ticker": ticker}).duplicated().any():
        blockers.append("component_frame_duplicate_date_ticker")
    if not as_bool(d["pit_universe_label_clean"]).all():
        blockers.append("component_frame_pit_universe_not_clean")

    minimum_coverage = float(contract["validation"]["minimum_component_coverage"])
    component_coverage: dict[str, float] = {}
    for name, spec in inputs.items():
        observed = as_bool(d[spec["observed_column"]])
        available = pd.to_datetime(d[spec["available_from_column"]], errors="coerce", utc=True)
        finite = np.isfinite(pd.to_numeric(d[spec["column"]], errors="coerce").to_numpy(dtype=float))
        usable = observed.to_numpy(dtype=bool) & finite & available.notna().to_numpy(dtype=bool)
        coverage = float(usable.mean()) if len(d) else 0.0
        component_coverage[name] = coverage
        if coverage + 1e-12 < minimum_coverage:
            blockers.append(f"component_coverage_below_minimum:{name}:{coverage:.6f}")
        future_mask = observed & available.notna() & available.gt(decision_time)
        if future_mask.any():
            blockers.append(f"component_available_after_decision:{name}")

    label_summary: dict[str, Any] = {}
    complete_masks: list[pd.Series] = []
    for horizon in (63, 126):
        value_col = f"realized_benchmark_excess_{horizon}d"
        available_col = f"label_available_at_{horizon}d"
        values = pd.to_numeric(d[value_col], errors="coerce")
        available = pd.to_datetime(d[available_col], errors="coerce", utc=True)
        finite = pd.Series(np.isfinite(values.to_numpy(dtype=float)), index=d.index)
        if (finite & available.isna()).any():
            blockers.append(f"finite_label_missing_available_from:{horizon}d")
        if (finite & available.le(decision_time)).any():
            blockers.append(f"label_available_not_after_decision:{horizon}d")
        if (finite & available.gt(as_of)).any():
            blockers.append(f"future_label_materialized:{horizon}d")
        complete = finite & available.notna() & available.le(as_of)
        complete_masks.append(complete)
        label_summary[str(horizon)] = {
            "finite_rows": int(finite.sum()),
            "matured_rows": int(complete.sum()),
        }

    minimum_rows = int(contract["validation"]["minimum_cross_section_rows_per_decision"])
    counts = pd.Series(ticker).groupby(feature_date).size()
    if counts.empty or int(counts.min()) < minimum_rows:
        blockers.append("component_frame_cross_section_below_minimum")
    complete_both = complete_masks[0] & complete_masks[1]
    complete_counts = complete_both.groupby(feature_date).sum()
    mature_dates = int(complete_counts.ge(minimum_rows).sum())
    minimum_dates = int(contract["validation"]["minimum_training_decision_dates"]) + int(
        contract["validation"]["minimum_outer_test_decision_dates"]
    )
    if mature_dates < minimum_dates:
        blockers.append(f"mature_decision_dates_below_minimum:{mature_dates}<{minimum_dates}")

    return unique(blockers), {
        "rows": len(d),
        "tickers": int(ticker.nunique()),
        "decision_dates": int(feature_date.nunique()),
        "mature_decision_dates": mature_dates,
        "minimum_cross_section_rows_observed": int(counts.min()) if not counts.empty else 0,
        "component_coverage": component_coverage,
        "labels": label_summary,
        "latest_decision_time_utc": decision_time.max().isoformat() if decision_time.notna().any() else None,
    }


def audit_daily_returns(
    frame: pd.DataFrame,
    contract: Mapping[str, Any],
    as_of: pd.Timestamp,
) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    required = set(contract["data_readiness"]["daily_returns_required_columns"])
    missing = sorted(required - set(frame.columns))
    if missing:
        return ["daily_returns_missing_columns:" + ",".join(missing)], {
            "rows": len(frame),
            "missing_columns": missing,
        }
    if frame.empty:
        return ["daily_returns_empty"], {"rows": 0}
    d = frame.copy()
    dates = pd.to_datetime(d["date"], errors="coerce").dt.normalize()
    available = pd.to_datetime(d["available_from"], errors="coerce", utc=True)
    ticker = d["ticker"].astype(str).str.upper().str.strip()
    stable_id = d["stable_security_id"].astype(str).str.strip()
    returns = pd.to_numeric(d["return"], errors="coerce")
    if dates.isna().any() or available.isna().any():
        blockers.append("daily_returns_invalid_dates")
    if ticker.eq("").any() or stable_id.eq("").any():
        blockers.append("daily_returns_blank_identity")
    if pd.DataFrame({"date": dates, "stable_id": stable_id}).duplicated().any():
        blockers.append("daily_returns_duplicate_date_security")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        blockers.append("daily_returns_nonfinite")
    if returns.lt(-1.0 - 1e-12).any():
        blockers.append("daily_returns_below_total_loss")
    if available.gt(as_of).any():
        blockers.append("daily_returns_future_available_from")
    scheduled_close = nyse_close_by_session(dates)
    if scheduled_close.isna().any():
        blockers.append("daily_returns_date_not_nyse_session")
    if (available < scheduled_close).fillna(False).any():
        blockers.append("daily_returns_available_before_scheduled_close")
    if not as_bool(d["pit_universe_label_clean"]).all():
        blockers.append("daily_returns_pit_universe_not_clean")
    if d["pit_lifecycle_state"].astype(str).str.strip().eq("").any():
        blockers.append("daily_returns_blank_lifecycle_state")

    minimum_sessions = int(contract["portfolio_allocation"]["minimum_daily_return_sessions"])
    counts = pd.Series(dates).groupby(stable_id).nunique()
    adequate = int(counts.ge(minimum_sessions).sum())
    required_tickers = int(contract["data_readiness"]["minimum_prior_weight_tickers"])
    if adequate < required_tickers:
        blockers.append(f"daily_return_history_tickers_below_minimum:{adequate}<{required_tickers}")
    return unique(blockers), {
        "rows": len(d),
        "tickers": int(ticker.nunique()),
        "stable_security_ids": int(stable_id.nunique()),
        "sessions": int(dates.nunique()),
        "tickers_with_minimum_sessions": adequate,
        "minimum_sessions_required": minimum_sessions,
    }


def audit_prior_weights(
    frame: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    blockers: list[str] = []
    required = set(contract["data_readiness"]["prior_weights_required_columns"])
    missing = sorted(required - set(frame.columns))
    if missing:
        return ["prior_weights_missing_columns:" + ",".join(missing)], {
            "rows": len(frame),
            "missing_columns": missing,
        }
    if frame.empty:
        return ["prior_weights_empty"], {"rows": 0}
    d = frame.copy()
    dates = pd.to_datetime(d["rebalance_date"], errors="coerce").dt.normalize()
    ticker = d["ticker"].astype(str).str.upper().str.strip()
    weights = pd.to_numeric(d["weight"], errors="coerce")
    if dates.isna().any() or ticker.eq("").any():
        blockers.append("prior_weights_invalid_identity")
    if not np.isfinite(weights.to_numpy(dtype=float)).all() or weights.lt(-1e-12).any():
        blockers.append("prior_weights_invalid_weight")
    hashes = d["source_sha256"].astype(str).str.lower().str.strip()
    if not hashes.map(lambda value: bool(SHA256_RE.fullmatch(value))).all():
        blockers.append("prior_weights_invalid_source_sha256")
    latest = dates.max()
    latest_mask = dates.eq(latest)
    latest_rows = d.loc[latest_mask].copy()
    latest_tickers = ticker.loc[latest_mask]
    latest_weights = weights.loc[latest_mask]
    if latest_tickers.duplicated().any():
        blockers.append("prior_weights_duplicate_latest_ticker")
    total = float(latest_weights.sum()) if len(latest_weights) else 0.0
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        blockers.append(f"prior_weights_latest_sum_not_one:{total:.12f}")
    minimum = int(contract["data_readiness"]["minimum_prior_weight_tickers"])
    invested = int((latest_weights > 1e-12).sum())
    if invested < minimum:
        blockers.append(f"prior_weights_tickers_below_minimum:{invested}<{minimum}")
    return unique(blockers), {
        "rows": len(d),
        "latest_rebalance_date": latest.date().isoformat() if pd.notna(latest) else None,
        "latest_rows": len(latest_rows),
        "latest_invested_tickers": invested,
        "latest_weight_sum": total,
        "source_hash_count": int(hashes.nunique()),
    }


def render_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Run287 scientific selection and allocation readiness",
        "",
        f"- status: `{payload['status']}`",
        f"- method contract valid: `{payload['contract_valid']}`",
        f"- data ready: `{payload['data_ready']}`",
        "- research fit executed: `false`",
        "- stock selection or portfolio weights produced: `false`",
        "",
        "## Contract failures",
        "",
    ]
    failures = payload.get("contract_failures") or []
    lines.extend([f"- `{item}`" for item in failures] or ["- none"])
    lines.extend(["", "## Data blockers", ""])
    blockers = payload.get("data_blockers") or []
    lines.extend([f"- `{item}`" for item in blockers] or ["- none"])
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit only decides whether a separately preregistered challenger may be prepared. ",
            "It does not open the outer test, run a historical fit, alter the champion, write targets, create orders, or mutate a ledger.",
            "",
        ]
    )
    return "\n".join(lines)


def audit(
    *,
    contract_path: Path,
    component_frame_path: Path | None,
    daily_returns_path: Path | None,
    prior_weights_path: Path | None,
    output_dir: Path,
    as_of_time: str | None = None,
) -> dict[str, Any]:
    contract: Any = {}
    contract_failures: list[str] = []
    if not contract_path.is_file():
        contract_failures.append("contract_missing")
    else:
        try:
            contract = read_json(contract_path)
            contract_failures.extend(validate_contract(contract))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            contract_failures.append(f"contract_unreadable:{type(exc).__name__}:{exc}")

    if as_of_time:
        as_of = pd.to_datetime(as_of_time, errors="coerce", utc=True)
        if pd.isna(as_of):
            contract_failures.append("as_of_time_invalid")
            as_of = pd.Timestamp.now(tz="UTC")
    else:
        as_of = pd.Timestamp.now(tz="UTC")

    data_blockers: list[str] = []
    diagnostics: dict[str, Any] = {}
    paths = {
        "component_frame": component_frame_path,
        "daily_returns": daily_returns_path,
        "prior_weights": prior_weights_path,
    }
    if not contract_failures:
        for label, path in paths.items():
            if path is None or not path.is_file():
                data_blockers.append(f"{label}_missing")
                diagnostics[label] = {"rows": 0}
                continue
            try:
                frame = load_table(path)
                if label == "component_frame":
                    blockers, detail = audit_component_frame(frame, contract, as_of)
                elif label == "daily_returns":
                    blockers, detail = audit_daily_returns(frame, contract, as_of)
                else:
                    blockers, detail = audit_prior_weights(frame, contract)
                data_blockers.extend(blockers)
                diagnostics[label] = detail
            except (OSError, ValueError, KeyError, ImportError) as exc:
                data_blockers.append(f"{label}_unreadable:{type(exc).__name__}:{exc}")
                diagnostics[label] = {"rows": 0, "error": f"{type(exc).__name__}:{exc}"}

    contract_failures = unique(contract_failures)
    data_blockers = unique(data_blockers)
    contract_valid = not contract_failures
    data_ready = contract_valid and not data_blockers
    status = READY_STATUS if data_ready else (INVALID_STATUS if not contract_valid else BLOCKED_STATUS)
    safety = {
        "research_only": True,
        "research_fit_executed": False,
        "outer_test_opened": False,
        "stock_selection_produced": False,
        "portfolio_weights_produced": False,
        "champion_changed": False,
        "target_books_written": False,
        "orders_generated": False,
        "operating_ledger_mutated": False,
        "production_or_live_trading_enabled": False,
        "fullrun_executed": False,
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "contract_valid": contract_valid,
        "data_ready": data_ready,
        "as_of_time_utc": as_of.isoformat(),
        "contract_failures": contract_failures,
        "data_blockers": data_blockers,
        "inputs": {
            "contract": fingerprint(contract_path),
            **{label: fingerprint(path) for label, path in paths.items()},
        },
        "diagnostics": diagnostics,
        "method_boundary": {
            "next_status_if_ready": "PREREGISTER_ONE_CAUSAL_CHALLENGER_BEFORE_ANY_REAL_FIT",
            "real_fit_authorized": False,
            "portfolio_replay_authorized": False,
        },
        "safety": safety,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "contract_audit.json",
        {
            "schema_version": SCHEMA_VERSION,
            "contract_valid": contract_valid,
            "contract_failures": contract_failures,
            "contract": fingerprint(contract_path),
            "safety": safety,
        },
    )
    write_json(output_dir / "data_readiness.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def optional_path(value: str) -> Path | None:
    return Path(value).resolve() if str(value or "").strip() else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--component-frame", default="")
    parser.add_argument("--daily-returns", default="")
    parser.add_argument("--prior-weights", default="")
    parser.add_argument("--as-of-time", default="")
    parser.add_argument(
        "--output-dir",
        default="outputs/run287_scientific_weighting_readiness",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = audit(
        contract_path=Path(args.contract).resolve(),
        component_frame_path=optional_path(args.component_frame),
        daily_returns_path=optional_path(args.daily_returns),
        prior_weights_path=optional_path(args.prior_weights),
        output_dir=Path(args.output_dir).resolve(),
        as_of_time=str(args.as_of_time or "") or None,
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "contract_valid": payload["contract_valid"],
                "data_ready": payload["data_ready"],
                "contract_failures": payload["contract_failures"],
                "data_blockers": payload["data_blockers"],
                "research_fit_executed": False,
                "portfolio_weights_produced": False,
                "output_dir": str(Path(args.output_dir).resolve()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
