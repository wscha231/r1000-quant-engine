#!/usr/bin/env python3
"""Extend the official Run287 crisis state to the current valuation close.

The extension is current-decision-only. It seeds hysteresis from the pinned
official daily state and builds long-crisis features with the pinned historical
feature implementation. State transition, availability, and re-entry use the
current canonical Run287 policy shared with replay and target construction.
Future label columns are physically removed before inference. No rank,
selector, target book, fullrun, or live-trading path is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run287_pinned_git_import import pinned_import_context  # noqa: E402
from tools import crisis_state_engine as canonical_engine  # noqa: E402
from tools.run287_crisis_policy import CANONICAL_STATES  # noqa: E402


SCHEMA_VERSION = "run287-current-crisis-state-sidecar-v2"
VALID_STATES = set(CANONICAL_STATES)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": bool(path.exists()),
        "bytes": int(path.stat().st_size) if path.exists() and path.is_file() else 0,
        "sha256": sha256(path) if path.exists() and path.is_file() else "",
    }


def expected_input(path: Path, expected: str, label: str) -> dict[str, Any]:
    audit = fingerprint(path)
    audit.update(
        {
            "label": label,
            "expected_sha256": expected,
            "hash_matches": bool(audit.get("sha256") == expected),
        }
    )
    return audit


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()


def verify_manifest_record(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    name: str,
) -> tuple[Path, dict[str, Any]]:
    record = (manifest.get(section) or {}).get(name) or {}
    raw_path = str(record.get("path") or "")
    path = Path(raw_path)
    if raw_path and not path.is_absolute():
        path = manifest_path.parent / path
    audit = fingerprint(path)
    expected = str(record.get("sha256") or "")
    audit.update(
        {
            "label": name,
            "expected_sha256": expected,
            "hash_matches": bool(expected and audit.get("sha256") == expected),
        }
    )
    if not audit["exists"] or not audit["hash_matches"]:
        raise ValueError(f"manifest record mismatch: {name}")
    return path, audit


def parquet_audit(path: Path, kind: str) -> dict[str, Any]:
    audit = fingerprint(path)
    audit.update({"kind": kind, "file": path.name, "row_count": 0, "date_min": "", "date_max": ""})
    try:
        frame = pd.read_parquet(path)
        audit["row_count"] = int(len(frame))
        if "date" in frame.columns or "Date" in frame.columns:
            date_column = "date" if "date" in frame.columns else "Date"
            dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
        else:
            dates = pd.to_datetime(frame.index, errors="coerce")
            dates = pd.Series(dates).dropna()
        if not dates.empty:
            audit["date_min"] = pd.Timestamp(dates.min()).date().isoformat()
            audit["date_max"] = pd.Timestamp(dates.max()).date().isoformat()
    except Exception as exc:
        audit["read_error"] = f"{type(exc).__name__}:{exc}"
    return audit


def source_files_unchanged(audits: list[dict[str, Any]]) -> bool:
    return all(
        fingerprint(Path(str(row.get("path") or ""))).get("sha256") == row.get("sha256")
        for row in audits
        if row.get("path") and row.get("exists")
    )


def trailing_count(values: pd.Series, target: str) -> int:
    count = 0
    for value in reversed(values.fillna("").astype(str).tolist()):
        if value != target:
            break
        count += 1
    return count


def extend_state(
    *,
    official: pd.DataFrame,
    valuation_date: pd.Timestamp,
    price_states: pd.DataFrame,
    observable_features: pd.DataFrame,
    thresholds: Mapping[str, Any],
    engine: Any,
    thresholds_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prior = official.sort_values("date").reset_index(drop=True)
    last = prior.iloc[-1]
    last_raw = str(last.get("raw_state") or "GREEN")
    last_state = str(last.get("crisis_state") or "GREEN")
    history = {
        "state": last_state,
        "raw_state": last_raw,
        "raw_state_streak": trailing_count(prior["raw_state"], last_raw),
    }
    cutoff = pd.Timestamp(prior["date"].max()).normalize()
    extension_dates = pd.bdate_range(cutoff + pd.Timedelta(days=1), valuation_date)
    price = price_states.copy()
    price["date"] = pd.to_datetime(price["date"], errors="coerce").dt.normalize()
    price = price.dropna(subset=["date"]).drop_duplicates("date", keep="last").set_index("date")
    rows: list[dict[str, Any]] = []
    for dt in extension_dates:
        if dt in price.index:
            price_row = price.loc[dt].to_dict()
        else:
            price_row = {
                "price_state": "GREEN",
                "price_crisis_score": 0.0,
                "price_trigger": "missing_price_state",
            }
        eligible = observable_features[observable_features.index <= dt]
        if eligible.empty:
            feature_row = pd.Series(dtype=float)
            feature_date = None
        else:
            feature_row = eligible.iloc[-1].copy()
            feature_date = pd.Timestamp(eligible.index[-1]).normalize()
        long_state, _reasons, meta = engine.infer_long_crisis_state_from_row(
            feature_row,
            dict(thresholds),
            asof_date=feature_date,
            features_path=None,
            thresholds_path=thresholds_path,
            allow_crisis_defense=True,
        )
        price_state = str(price_row.get("price_state") or "GREEN")
        raw_state = engine.stronger_state(price_state, long_state)
        observed = {**feature_row.to_dict(), **price_row}
        availability = engine.component_availability(
            observed,
            decision_time=dt,
            available_from=feature_date,
        )
        crisis_state, history = engine.apply_hysteresis(
            raw_state,
            history,
            values=observed,
            availability=availability,
        )
        reentry_stage = crisis_state if crisis_state.startswith("REENTRY_STAGE_") else ""
        reentry_trigger = str(
            history.get("transition_reason")
            or price_row.get("price_trigger")
            or meta.get("cash_gate_reason")
            or raw_state
        )
        price_score = float(price_row.get("price_crisis_score") or 0.0)
        long_score = float(meta.get("crisis_score") or 0.0)
        rows.append(
            {
                "date": dt.date().isoformat(),
                "price_state": price_state,
                "price_crisis_score": price_score,
                "price_trigger": str(price_row.get("price_trigger") or ""),
                "spy_drawdown": price_row.get("spy_drawdown", np.nan),
                "spy_ret_5d": price_row.get("spy_ret_5d", np.nan),
                "spy_above_ma20": price_row.get("spy_above_ma20", np.nan),
                "spy_above_ma50": price_row.get("spy_above_ma50", np.nan),
                "long_crisis_state": long_state,
                "long_crisis_score": long_score,
                "cash_gate_reason": str(meta.get("cash_gate_reason") or meta.get("reason") or ""),
                "cash_gate_allowed": bool(meta.get("cash_gate_allowed", False)),
                "liquidity_confirmation_score": float(meta.get("liquidity_confirmation_score") or 0.0),
                "market_trend_damage_score": float(meta.get("market_trend_damage_score") or 0.0),
                "credit_stress_score": float(meta.get("credit_stress_score") or 0.0),
                "volatility_stress_score": float(feature_row.get("volatility_stress_score") or 0.0),
                "rate_shock_score": float(feature_row.get("rate_shock_score") or 0.0),
                "qqq_close": feature_row.get("qqq_close", np.nan),
                "qqq_ma200": feature_row.get("qqq_ma200", np.nan),
                "qqq_below_ma200": feature_row.get("qqq_below_ma200", np.nan),
                "vix_zscore_252d": feature_row.get("vix_zscore_252d", np.nan),
                "hy_oas_zscore_252d": feature_row.get("hy_oas_zscore_252d", np.nan),
                "long_crisis_feature_date": feature_date.date().isoformat() if feature_date is not None else "",
                "future_labels_excluded": True,
                "raw_state": raw_state,
                "crisis_state": crisis_state,
                "crisis_score": max(price_score, long_score),
                "reentry_stage": reentry_stage,
                "reentry_trigger": reentry_trigger,
                "reentry_score": float(history.get("reentry_score") or 0.0),
                "reentry_multiplier": float(history.get("reentry_multiplier") or 1.0),
                "component_availability": json.dumps(
                    engine.availability_records(availability), sort_keys=True
                ),
                "missing_components": "|".join(history.get("missing_components") or []),
                "missing_critical_components": "|".join(
                    history.get("missing_critical_components") or []
                ),
                "state_source": (
                    "long_crisis"
                    if engine.STATE_RANK.get(long_state, 0)
                    > engine.STATE_RANK.get(price_state, 0)
                    else "price_or_combined"
                ),
            }
        )
    seed = {
        "official_cutoff_date": cutoff.date().isoformat(),
        "seed_crisis_state": last_state,
        "seed_raw_state": last_raw,
        "seed_raw_state_streak": int(history.get("raw_state_streak", 0)) if not rows else trailing_count(prior["raw_state"], last_raw),
        "extension_business_date_count": int(len(extension_dates)),
    }
    return pd.DataFrame(rows), seed


def blocked(
    output_dir: Path,
    *,
    failures: list[str],
    input_audits: Mapping[str, Any],
    started: float,
    valuation_date: str,
    crisis_state_function_executed: bool = False,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_CURRENT_CRISIS_STATE_SIDECAR",
        "crisis_state_sidecar_passed": False,
        "contract_failures": failures,
        "blockers": failures,
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "current_decision_only": True,
        "historical_backtest_acceptance_allowed": False,
        "crisis_state_function_executed": bool(crisis_state_function_executed),
        "score_sort_executed": False,
        "rank_assignment_executed": False,
        "top_n_executed": False,
        "selector_executed": False,
        "position_sizing_executed": False,
        "target_book_generation_allowed": False,
        "target_books_mutated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(input_audits),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "selector_contract_manifest": repo_path(args.selector_contract_manifest),
        "pinned_import_manifest": repo_path(args.pinned_import_manifest),
        "macro_manifest": repo_path(args.macro_manifest),
        "official_daily_crisis_state": repo_path(args.official_daily_crisis_state),
        "official_thresholds": repo_path(args.official_thresholds),
    }
    expected = {
        "selector_contract_manifest": args.expected_selector_contract_sha256,
        "pinned_import_manifest": args.expected_pinned_import_sha256,
        "macro_manifest": args.expected_macro_sha256,
        "official_daily_crisis_state": args.expected_daily_crisis_sha256,
        "official_thresholds": args.expected_thresholds_sha256,
    }
    input_audits = {
        name: expected_input(path, expected[name], name)
        for name, path in paths.items()
    }
    failures = [
        f"input_hash_mismatch:{name}"
        for name, row in input_audits.items()
        if not row.get("exists") or not row.get("hash_matches")
    ]
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
        )

    selector_contract = load_json(paths["selector_contract_manifest"])
    pinned_import = load_json(paths["pinned_import_manifest"])
    macro_manifest = load_json(paths["macro_manifest"])
    if selector_contract.get("status") != "READY_CURRENT_SELECTOR_CONTRACT_AUDIT_NONSELECTING":
        failures.append(f"selector_contract_status:{selector_contract.get('status')}")
    if pinned_import.get("status") != "READY_PINNED_POLICY_IMPORT_NONSELECTING":
        failures.append(f"pinned_import_status:{pinned_import.get('status')}")
    if macro_manifest.get("status") != "READY_CONSERVATIVE_MACRO_SIDECAR":
        failures.append(f"macro_status:{macro_manifest.get('status')}")
    pinned_commit = str(pinned_import.get("pinned_source_commit") or "")
    if pinned_commit != args.expected_policy_commit:
        failures.append(f"pinned_commit:{pinned_commit}!={args.expected_policy_commit}")
    if bool(macro_manifest.get("fred_vintage_clean")):
        failures.append("macro_manifest_unexpected_historical_vintage_claim")
    macro_current_path, macro_current_audit = verify_manifest_record(
        paths["macro_manifest"], macro_manifest, "outputs", "macro_current"
    )
    input_audits["macro_current"] = macro_current_audit

    cache_prices = repo_path(args.cache_prices)
    cache_macro = repo_path(args.cache_macro)
    price_files = sorted(cache_prices.glob("*.parquet"))
    macro_files = sorted(cache_macro.glob("*.parquet"))
    if len(price_files) != int(args.expected_price_file_count):
        failures.append(f"price_file_count:{len(price_files)}!={args.expected_price_file_count}")
    if len(macro_files) != int(args.expected_macro_file_count):
        failures.append(f"macro_file_count:{len(macro_files)}!={args.expected_macro_file_count}")
    source_component_rows = [parquet_audit(path, "price") for path in price_files]
    source_component_rows.extend(parquet_audit(path, "macro") for path in macro_files)
    if any(row.get("read_error") for row in source_component_rows):
        failures.append("source_component_read_error")
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
        )

    valuation = pd.Timestamp(args.valuation_date).normalize()
    official = pd.read_csv(paths["official_daily_crisis_state"], low_memory=False)
    official["date"] = pd.to_datetime(official["date"], errors="coerce").dt.normalize()
    official = official.dropna(subset=["date"]).sort_values("date")
    official_cutoff = pd.Timestamp(official["date"].max()).normalize()
    if official_cutoff >= valuation:
        failures.append("official_crisis_state_not_prior_to_valuation")

    try:
        with pinned_import_context(pinned_commit, REPO_ROOT) as loader:
            builder = importlib.import_module("tools.run_long_crisis_dataset_builder")
            engine = canonical_engine
            market = builder.load_price_close(cache_prices, "SPY")
            qqq = builder.load_price_close(cache_prices, "QQQ")
            macro: dict[str, pd.Series] = {}
            source_rows: dict[str, int] = {"SPY": int(len(market)), "QQQ": int(len(qqq))}
            for key, (name, series_id) in builder.FRED_SERIES.items():
                if key == "sp500":
                    continue
                series = builder.load_fred(cache_macro, name, series_id)
                if key == "reverse_repo_alt":
                    if macro.get("reverse_repo", pd.Series(dtype=float)).empty:
                        macro["reverse_repo"] = series
                        source_rows[f"{name}:{series_id}"] = int(len(series))
                    continue
                macro[name] = series
                source_rows[f"{name}:{series_id}"] = int(len(series))
            if market.empty or qqq.empty:
                raise ValueError("SPY and QQQ current price histories are required")
            feature_start = pd.Timestamp(market.index.min()).date().isoformat()
            long_features = builder.build_long_crisis_features(
                market,
                macro,
                qqq_close=qqq,
                start=feature_start,
                end=args.valuation_date,
                m2_lag_months=1,
            )
            future_columns = sorted(
                column
                for column in long_features.columns
                if str(column).startswith("future_")
                or str(column) in engine.FUTURE_LABEL_COLUMNS
            )
            observable_columns = [
                column for column in long_features.columns if column not in future_columns
            ]
            observable = long_features[observable_columns].copy()
            observable.index = pd.to_datetime(observable.index, errors="coerce")
            observable = observable[~observable.index.isna()].sort_index()
            price_states = engine.price_raw_state(
                cache_prices,
                pd.Timestamp(market.index.min()).normalize(),
                valuation,
            )
            thresholds = engine.load_long_crisis_thresholds(
                paths["official_thresholds"]
            )
            extension_a, seed = extend_state(
                official=official,
                valuation_date=valuation,
                price_states=price_states,
                observable_features=observable,
                thresholds=thresholds,
                engine=engine,
                thresholds_path=paths["official_thresholds"],
            )
            extension_b, _seed_b = extend_state(
                official=official,
                valuation_date=valuation,
                price_states=price_states,
                observable_features=observable,
                thresholds=thresholds,
                engine=engine,
                thresholds_path=paths["official_thresholds"],
            )
            runtime_modules = pd.DataFrame(loader.loaded)
    except Exception as exc:
        failures.append(f"pinned_crisis_runtime:{type(exc).__name__}:{exc}")
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
            crisis_state_function_executed=True,
        )

    if long_features.empty or pd.Timestamp(long_features.index.max()).normalize() != valuation:
        failures.append("long_crisis_feature_not_current")
    if pd.Timestamp(market.index.max()).normalize() != valuation:
        failures.append("spy_price_not_current")
    if pd.Timestamp(qqq.index.max()).normalize() != valuation:
        failures.append("qqq_price_not_current")
    if any(column in observable.columns for column in future_columns):
        failures.append("future_label_present_in_observable_frame")
    if extension_a.empty:
        failures.append("empty_crisis_state_extension")
    else:
        last_extension_date = pd.to_datetime(extension_a["date"], errors="coerce").max()
        if pd.Timestamp(last_extension_date).normalize() != valuation:
            failures.append("crisis_extension_not_current")
        if str(extension_a.iloc[-1]["crisis_state"]) not in VALID_STATES:
            failures.append("invalid_final_crisis_state")
        if not bool(extension_a["future_labels_excluded"].all()):
            failures.append("future_label_exclusion_flag_failure")
    try:
        pd.testing.assert_frame_equal(extension_a, extension_b, check_dtype=True)
        deterministic = True
    except AssertionError:
        deterministic = False
        failures.append("crisis_extension_nondeterministic")
    if failures:
        return blocked(
            output_dir,
            failures=failures,
            input_audits=input_audits,
            started=started,
            valuation_date=args.valuation_date,
            crisis_state_function_executed=True,
        )

    final_state = extension_a.tail(1).copy()
    extension_path = output_dir / "current_crisis_state_extension.csv"
    final_path = output_dir / "current_crisis_state.csv"
    source_path = output_dir / "source_component_audit.csv"
    runtime_path = output_dir / "pinned_crisis_runtime_module_audit.csv"
    extension_a.to_csv(extension_path, index=False)
    final_state.to_csv(final_path, index=False)
    pd.DataFrame(source_component_rows).to_csv(source_path, index=False)
    runtime_modules.to_csv(runtime_path, index=False)

    macro_current = pd.read_csv(macro_current_path, low_memory=False)
    final = final_state.iloc[0].to_dict()
    source_unchanged = source_files_unchanged(
        [*input_audits.values(), *source_component_rows]
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_CURRENT_CRISIS_STATE_NONSELECTING",
        "crisis_state_sidecar_passed": True,
        "contract_failures": [],
        "valuation_price_cutoff_date": args.valuation_date,
        "decision_time_utc": macro_manifest.get("decision_time_utc"),
        "macro_available_from": macro_manifest.get("macro_available_from"),
            "current_state": {
            "date": str(final.get("date") or ""),
            "crisis_state": str(final.get("crisis_state") or ""),
            "raw_state": str(final.get("raw_state") or ""),
            "price_state": str(final.get("price_state") or ""),
            "long_crisis_state": str(final.get("long_crisis_state") or ""),
            "crisis_score": float(final.get("crisis_score") or 0.0),
            "price_crisis_score": float(final.get("price_crisis_score") or 0.0),
            "long_crisis_score": float(final.get("long_crisis_score") or 0.0),
            "cash_gate_reason": str(final.get("cash_gate_reason") or ""),
            "cash_gate_allowed": bool(final.get("cash_gate_allowed")),
            "long_crisis_feature_date": str(final.get("long_crisis_feature_date") or ""),
            "reentry_score": float(final.get("reentry_score") or 0.0),
            "reentry_multiplier": float(final.get("reentry_multiplier") or 1.0),
            "missing_components": str(final.get("missing_components") or ""),
            "missing_critical_components": str(final.get("missing_critical_components") or ""),
        },
        "extension": {
            **seed,
            "official_history_preserved": True,
            "official_history_recomputed": False,
            "official_history_held_forward_as_fresh": False,
            "extension_deterministic": deterministic,
            "interim_state_counts": {
                str(key): int(value)
                for key, value in extension_a["crisis_state"].value_counts().to_dict().items()
            },
        },
        "feature_contract": {
            "feature_start_date": feature_start,
            "feature_end_date": pd.Timestamp(long_features.index.max()).date().isoformat(),
            "feature_row_count": int(len(long_features)),
            "observable_column_count": int(len(observable_columns)),
            "future_label_column_count_excluded": int(len(future_columns)),
            "future_label_columns_excluded": future_columns,
            "future_labels_used_for_state": False,
            "source_rows": source_rows,
        },
        "pinned_runtime": {
            "source_commit": pinned_commit,
            "loaded_module_count": int(len(runtime_modules)),
            "feature_modules_from_pinned_git_objects": bool(
                runtime_modules["source_mode"].eq("pinned_git_object").all()
                and runtime_modules["source_commit"].eq(pinned_commit).all()
            ),
            "canonical_state_engine_path": str(Path(canonical_engine.__file__).resolve()),
            "canonical_state_engine_sha256": sha256(Path(canonical_engine.__file__).resolve()),
            "crisis_functions_called": True,
            "selector_functions_called": False,
        },
        "fred_vintage_clean": False,
        "research_only": True,
        "current_decision_only": True,
        "historical_backtest_acceptance_allowed": False,
        "pit_universe_label_clean": False,
        "crisis_state_function_executed": True,
        "score_sort_executed": False,
        "rank_assignment_executed": False,
        "top_n_executed": False,
        "selector_executed": False,
        "position_sizing_executed": False,
        "target_book_generation_allowed": False,
        "target_books_mutated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "network_requests_executed": 0,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs_mutated": not source_unchanged,
        "source_inputs": dict(input_audits),
        "outputs": {
            "current_crisis_state_extension": fingerprint(extension_path),
            "current_crisis_state": fingerprint(final_path),
            "source_component_audit": fingerprint(source_path),
            "pinned_crisis_runtime_module_audit": fingerprint(runtime_path),
        },
        "recommended_next_step": "verify a single-date pinned-policy selector adapter with registered-eligible new entries, explicit Main prior-holding transition telemetry, and no target-book output",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    artifact = Path(
        r"H:\codex\tmp_r1000_grossfloor_20260625\outputs\run_28725350727_official_broker_artifact"
    )
    isolated = REPO_ROOT / "outputs/run287_macro_sidecar_20260711_commit_0d97c720/inputs/isolated_engine"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selector-contract-manifest",
        default="outputs/run287_current_selector_contract_audit_20260712_commit_0d07efea/manifest.json",
    )
    parser.add_argument(
        "--expected-selector-contract-sha256",
        default="647475ceaf2109d7dc7c7dfd18865679de86dc5afd102a090481e118bab4a02f",
    )
    parser.add_argument(
        "--pinned-import-manifest",
        default="outputs/run287_pinned_policy_import_audit_20260712_commit_e871541c/manifest.json",
    )
    parser.add_argument(
        "--expected-pinned-import-sha256",
        default="b59db75e6eea74989fd72946cb3b72af65a401dddb5738970ddd2b3d4febab6d",
    )
    parser.add_argument(
        "--macro-manifest",
        default="outputs/run287_macro_sidecar_20260711_commit_0d97c720/manifest.json",
    )
    parser.add_argument(
        "--expected-macro-sha256",
        default="f6d0ce92e0a7c5957f099741c9ede274fc484dc9a75e3e41d9377e298746c1f0",
    )
    parser.add_argument(
        "--official-daily-crisis-state",
        default=str(artifact / "outputs/alphaops_vnext/daily_crisis_state.csv"),
    )
    parser.add_argument(
        "--expected-daily-crisis-sha256",
        default="9516ea00fa9580aef9aa3d41c01d4b48f3ad1b14650dffdd500fa3ee5bf67a31",
    )
    parser.add_argument(
        "--official-thresholds",
        default=str(artifact / "outputs/long_crisis_learning/best_thresholds.json"),
    )
    parser.add_argument(
        "--expected-thresholds-sha256",
        default="d108c017e301f6929e1441827d5a19c02beb0d89727dbbff40f94f3e504d2da2",
    )
    parser.add_argument("--cache-prices", default=str(isolated / "cache_prices"))
    parser.add_argument("--cache-macro", default=str(isolated / "cache_macro"))
    parser.add_argument("--expected-price-file-count", type=int, default=9)
    parser.add_argument("--expected-macro-file-count", type=int, default=14)
    parser.add_argument(
        "--expected-policy-commit",
        default="15176b588d5bb0792bce1df6367758d795a8a33a",
    )
    parser.add_argument("--valuation-date", default="2026-07-10")
    parser.add_argument(
        "--output-dir", default="outputs/run287_current_crisis_state_20260712"
    )
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "crisis_state_sidecar_passed": payload.get(
                    "crisis_state_sidecar_passed"
                ),
                "current_state": payload.get("current_state", {}),
                "selector_executed": payload.get("selector_executed"),
            },
            sort_keys=True,
        )
    )
    return 0 if payload.get("crisis_state_sidecar_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
