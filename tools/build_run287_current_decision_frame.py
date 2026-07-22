#!/usr/bin/env python3
"""Assemble and verify a full current Run287 decision feature frame.

This bounded builder starts from the exact-close scored-latest selection
context, applies only hash-pinned current macro/benchmark sidecars and exact
accepted statement deltas, then regenerates the frozen 238-feature scaled
matrix. It does not score, rank, select, backtest, run fullrun, or mutate a
portfolio target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import EngineConfig  # noqa: E402
from r1000_pipeline import apply_scaler  # noqa: E402
from tools.build_run287_b002_fundamental_delta import (  # noqa: E402
    CORE_FUNDAMENTAL_MINIMUM_FIELDS,
    apply_current_valuation_overrides,
    build_exact_fundamental_panel,
    extract_exact_companyfacts_records,
    prepare_statement_index,
    select_accession_field_records,
)
from tools.build_run287_feature_frame_pilot import (  # noqa: E402
    recompute_long_momentum_columns,
    transform_feature_context,
)


SCHEMA_VERSION = "run287-current-decision-frame-v1"
P6_CRITICAL_SELECTION_FIELDS = (
    "mom_3m",
    "rs_benchmark_3m",
    "rs_sector_3m",
    "price_above_ma200",
    "dollar_vol_20d",
    "industry_group_strength_score",
    "sector_adjusted_quality_score",
    "capital_efficiency_score",
    "fundamental_reliability_score",
)


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
        return {"path": str(path), "exists": False, "bytes": 0, "sha256": None}
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON object required: {path}")
    return loaded


def output_path(manifest_path: Path, manifest: Mapping[str, Any], key: str) -> Path:
    record = (manifest.get("outputs") or {}).get(key) or {}
    path = Path(str(record.get("path") or ""))
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file() or sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"manifest output hash mismatch: {key}")
    return path


def source_path(manifest_path: Path, manifest: Mapping[str, Any], key: str) -> Path:
    record = (manifest.get("source_inputs") or {}).get(key) or {}
    path = Path(str(record.get("path") or ""))
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file() or sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"manifest source hash mismatch: {key}")
    return path


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def values_differ(left: Any, right: Any) -> bool:
    left_number = pd.to_numeric(pd.Series([left]), errors="coerce").iloc[0]
    right_number = pd.to_numeric(pd.Series([right]), errors="coerce").iloc[0]
    if pd.isna(left_number) and pd.isna(right_number):
        return False
    if pd.isna(left_number) != pd.isna(right_number):
        return True
    if pd.notna(left_number) and pd.notna(right_number):
        return not bool(np.isclose(float(left_number), float(right_number), rtol=1e-10, atol=1e-12))
    return str(left) != str(right)


def normalize_acceptance_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in (
        "accepted", "fund_accepted", "fund_effective_accepted",
        "fund_latest_accepted_overall", "fund_ttm_fallback_accepted",
    ):
        if column in output.columns:
            output[column] = pd.to_datetime(
                output[column], errors="coerce", utc=True
            ).dt.tz_localize(None)
    return output


def normalize_period_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in (
        "fund_period", "fund_effective_period", "fund_latest_period_overall"
    ):
        if column in output.columns:
            parsed = pd.to_datetime(output[column], errors="coerce")
            output[column] = parsed.dt.strftime("%Y-%m-%d").where(
                parsed.notna(), ""
            )
    return output


def build(args: argparse.Namespace) -> dict[str, Any]:
    latest_path = repo_path(args.scored_latest_manifest)
    macro_path = repo_path(args.macro_manifest)
    benchmark_path = repo_path(args.benchmark_manifest)
    sec_path = repo_path(args.sec_delta_manifest)
    companyfacts_path = repo_path(args.companyfacts_manifest)
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    decision_time = pd.to_datetime(args.decision_time_utc, errors="coerce", utc=True)
    if pd.isna(decision_time):
        raise ValueError("valid decision_time_utc is required")
    valuation_date = pd.Timestamp(args.valuation_close_date).date().isoformat()

    latest_manifest = read_json(latest_path)
    macro_manifest = read_json(macro_path)
    benchmark_manifest = read_json(benchmark_path)
    sec_manifest = read_json(sec_path)
    companyfacts_manifest = read_json(companyfacts_path)
    expected_status = {
        "scored_latest": latest_manifest.get("status") == "READY_RESEARCH_SCORED_LATEST",
        "macro": macro_manifest.get("status") == "READY_CONSERVATIVE_MACRO_SIDECAR",
        "benchmark": benchmark_manifest.get("status") == "READY_CONSERVATIVE_BENCHMARK_EVENT_SIDECAR",
        "sec_delta": sec_manifest.get("status") == "READY_RECENT_SEC_ACCEPTED_DELTA",
        "companyfacts": companyfacts_manifest.get("status") == "READY_RECENT_COMPANYFACTS_DELTA",
    }
    blockers = [f"upstream_status:{key}" for key, value in expected_status.items() if not value]
    manifest_dates = {
        str(latest_manifest.get("session_date") or ""),
        str(macro_manifest.get("valuation_close_date") or ""),
        str(benchmark_manifest.get("valuation_close_date") or ""),
        str(sec_manifest.get("valuation_price_cutoff_date") or ""),
        valuation_date,
    }
    if manifest_dates != {valuation_date}:
        blockers.append("valuation_date_mismatch:" + ",".join(sorted(manifest_dates)))
    if blockers:
        raise ValueError(";".join(blockers))

    context_path = output_path(latest_path, latest_manifest, "selection_context.parquet")
    macro_current_path = output_path(macro_path, macro_manifest, "macro_current")
    benchmark_current_path = output_path(benchmark_path, benchmark_manifest, "benchmark_current")
    live_event_path = output_path(benchmark_path, benchmark_manifest, "live_event_current")
    sec_delta_path = output_path(sec_path, sec_manifest, "accepted_time_delta")
    combined_index_path = output_path(
        companyfacts_path, companyfacts_manifest, "combined_sec_filings_index"
    )
    model_meta_path = source_path(latest_path, latest_manifest, "model_meta")
    context = pd.read_parquet(context_path)
    context["ticker"] = context["ticker"].astype(str).str.upper().str.strip()
    lifecycle_coverage = latest_manifest.get("coverage") or {}
    pre_lifecycle_count = int(
        lifecycle_coverage.get("pre_lifecycle_context_count")
        or lifecycle_coverage.get("base_context_count")
        or 0
    )
    lifecycle_excluded_count = int(
        lifecycle_coverage.get("lifecycle_excluded_count")
        or lifecycle_coverage.get("security_lifecycle_terminal_exclusion_count")
        or 0
    )
    post_lifecycle_count = int(
        lifecycle_coverage.get("post_lifecycle_context_count")
        or lifecycle_coverage.get("current_context_count")
        or 0
    )
    if (
        pre_lifecycle_count <= 0
        or post_lifecycle_count <= 0
        or pre_lifecycle_count != lifecycle_excluded_count + post_lifecycle_count
    ):
        blockers.append("upstream_lifecycle_dynamic_count_contract")
    if len(context) != post_lifecycle_count or context["ticker"].duplicated().any():
        blockers.append("selection_context_dynamic_unique_contract")
    model_meta = read_json(model_meta_path)
    model_features = [str(value) for value in model_meta.get("model_features") or []]
    if len(model_features) != 238 or set(model_features) != set(model_meta.get("scaler") or {}):
        blockers.append("frozen_model_238_scaler_contract")

    macro_current = pd.read_csv(macro_current_path, low_memory=False)
    benchmark_current = pd.read_csv(benchmark_current_path, low_memory=False)
    live_event = pd.read_csv(live_event_path, low_memory=False)
    if any(len(frame) != 1 for frame in (macro_current, benchmark_current, live_event)):
        blockers.append("global_sidecar_single_row_contract")
    macro_available = pd.to_datetime(macro_manifest.get("macro_available_from"), errors="coerce", utc=True)
    benchmark_available = pd.to_datetime(
        benchmark_manifest.get("benchmark_event_available_from"), errors="coerce", utc=True
    )
    if pd.isna(macro_available) or macro_available > decision_time:
        blockers.append("macro_available_after_decision")
    if pd.isna(benchmark_available) or benchmark_available > decision_time:
        blockers.append("benchmark_available_after_decision")

    sec_delta = pd.read_parquet(sec_delta_path)
    sec_available = pd.to_datetime(sec_delta["available_from"], errors="coerce", utc=True)
    if sec_available.isna().any() or sec_available.gt(decision_time).any():
        blockers.append("sec_delta_available_after_decision")
    if not sec_delta["exact_acceptance"].astype(bool).all():
        blockers.append("sec_delta_exact_acceptance_not_100pct")
    statements = sec_delta[
        sec_delta["form"].astype(str).str.match(r"^(10-Q|10-K|20-F|40-F)(/A)?$")
    ].copy()
    combined_index = pd.read_parquet(combined_index_path)
    companyfacts_files = {
        str(record.get("cik10")): Path(str(record.get("path")))
        for record in (companyfacts_manifest.get("outputs") or {}).get("companyfacts_files") or []
    }
    fundamental_rows: list[pd.Series] = []
    fundamental_audits: list[dict[str, Any]] = []
    changed_rows: list[dict[str, Any]] = []
    for statement in statements.itertuples(index=False):
        ticker = str(statement.ticker).upper().strip()
        cik = str(statement.cik10).zfill(10)
        accession = str(statement.accession_number)
        matches = context.index[context["ticker"].eq(ticker)].tolist()
        ticker_blockers: list[str] = []
        if len(matches) != 1:
            ticker_blockers.append(f"context_row_count:{len(matches)}")
            fundamental_audits.append({"ticker": ticker, "accession_number": accession, "blockers": "|".join(ticker_blockers)})
            blockers.extend(f"{ticker}:{value}" for value in ticker_blockers)
            continue
        context_index = matches[0]
        base_row = context.loc[context_index].copy()
        statement_index, index_failures = prepare_statement_index(combined_index, cik)
        ticker_blockers.extend(index_failures)
        facts_file = companyfacts_files.get(cik, Path(""))
        if not facts_file.is_file():
            ticker_blockers.append("companyfacts_file_missing")
            payload = {}
        else:
            expected_hash = next(
                (str(record.get("sha256")) for record in (companyfacts_manifest.get("outputs") or {}).get("companyfacts_files") or [] if str(record.get("cik10")) == cik),
                "",
            )
            if sha256_file(facts_file) != expected_hash:
                ticker_blockers.append("companyfacts_hash_mismatch")
            payload = read_json(facts_file)
        exact, counters = extract_exact_companyfacts_records(
            payload, cik10=cik, ticker=ticker,
            statement_index=statement_index, decision_time=pd.Timestamp(decision_time),
        )
        selected = select_accession_field_records(exact)
        panel = build_exact_fundamental_panel(selected)
        expected_panel = panel[panel.get("accession_number", pd.Series(dtype=str)).astype(str).eq(accession)] if not panel.empty else pd.DataFrame()
        if len(expected_panel) != 1:
            ticker_blockers.append(f"expected_accession_panel_count:{len(expected_panel)}")
        if ticker_blockers:
            latest_fundamental = pd.Series(dtype=object)
        else:
            latest_fundamental = expected_panel.iloc[0].copy()
            latest_available = pd.to_datetime(latest_fundamental.get("accepted"), errors="coerce", utc=True)
            if pd.isna(latest_available) or latest_available > decision_time:
                ticker_blockers.append("fundamental_available_after_decision")
            core_coverage = int(latest_fundamental[list(CORE_FUNDAMENTAL_MINIMUM_FIELDS)].notna().sum())
            if core_coverage != len(CORE_FUNDAMENTAL_MINIMUM_FIELDS):
                ticker_blockers.append(
                    f"core_component_coverage:{core_coverage}/{len(CORE_FUNDAMENTAL_MINIMUM_FIELDS)}"
                )
            if not selected.empty and not selected["exact_acceptance"].astype(bool).all():
                ticker_blockers.append("selected_exact_acceptance_not_100pct")
            if not selected.empty and pd.to_datetime(selected["available_from"], errors="coerce", utc=True).gt(decision_time).any():
                ticker_blockers.append("future_selected_companyfacts_row")
        if not ticker_blockers:
            price = float(pd.to_numeric(pd.Series([base_row.get("current_price_live", base_row.get("px"))]), errors="coerce").iloc[0])
            latest_fundamental = apply_current_valuation_overrides(
                latest_fundamental, technical_price=price
            )
            latest_fundamental["ticker"] = ticker
            latest_fundamental["accepted_at"] = latest_fundamental["accepted"]
            latest_fundamental["available_from"] = latest_fundamental["accepted"]
            latest_fundamental["fund_period"] = latest_fundamental["period"]
            latest_fundamental["fund_effective_period"] = latest_fundamental["period"]
            latest_fundamental["fundamental_override_applied"] = True
            latest_fundamental["valuation_price_cutoff_date"] = valuation_date
            excluded = {
                "ticker", "cik", "cik10", "accession_number", "form", "fiscal_period",
                "period", "period_of_report", "source", "source_hashes", "pit_caveats",
                "pit_universe_label_clean", "exact_acceptance", "component_coverage",
                "missing_evidence_policy", "filed_fallback_used", "used_forward_return",
                "valuation_price_cutoff_date", "valuation_px", "available_from", "accepted_at",
            }
            override_columns = sorted(
                column for column in latest_fundamental.index
                if column not in excluded and (column in context.columns or column in model_features)
            )
            change_count = 0
            for column in override_columns:
                old = base_row.get(column, np.nan)
                new = latest_fundamental.get(column, np.nan)
                changed = values_differ(old, new)
                change_count += int(changed)
                if column not in context.columns:
                    context[column] = np.nan
                context.at[context_index, column] = new
                changed_rows.append({
                    "ticker": ticker, "column": column, "old_value": old,
                    "new_value": new, "changed": changed, "model_feature": column in model_features,
                })
            if "fundamental_value_change_count" in context.columns:
                context.at[context_index, "fundamental_value_change_count"] = change_count
            fundamental_rows.append(latest_fundamental)
        blockers.extend(f"{ticker}:{value}" for value in ticker_blockers)
        fundamental_audits.append({
            "ticker": ticker, "cik10": cik, "accession_number": accession,
            "exact_record_count": int(len(exact)), "selected_record_count": int(len(selected)),
            "panel_row_count": int(len(panel)), "candidate_fact_count": counters.get("candidate_fact_count", 0),
            "future_available_fact_count": counters.get("future_available_fact_count", 0),
            "blockers": "|".join(ticker_blockers),
        })

    macro_row = macro_current.iloc[0]
    for column, value in macro_row.items():
        if column in context.columns or column in model_features:
            context[column] = value
    for column, value in benchmark_current.iloc[0].items():
        if str(column).startswith("bench_"):
            context[column] = value
    for column, value in live_event.iloc[0].items():
        if str(column).startswith("live_event_"):
            context[column] = value
    context["feature_date"] = pd.Timestamp(valuation_date)
    context["rebalance_date"] = pd.Timestamp(valuation_date)
    for horizon in (1, 3, 6, 12):
        context[f"rs_benchmark_{horizon}m"] = pd.to_numeric(
            context.get(f"mom_{horizon}m"), errors="coerce"
        ) - pd.to_numeric(context.get(f"bench_ret_{horizon}m"), errors="coerce")
    context["dd_gap_benchmark"] = pd.to_numeric(
        context.get("bench_dd_1y"), errors="coerce"
    ) - pd.to_numeric(context.get("dd_1y"), errors="coerce")
    context = recompute_long_momentum_columns(context)
    # Exact SEC acceptance rows are UTC-aware while the frozen context stores
    # the same timestamps as tz-naive UTC values. Normalize the representation
    # before calling the frozen feature formulas; the underlying instant is
    # unchanged and later leakage checks parse the values back as UTC.
    context = normalize_acceptance_columns(context)
    context = transform_feature_context(context, EngineConfig())
    context = normalize_period_columns(context)
    for column in model_features:
        if column not in context.columns:
            context[column] = np.nan
    context = context.sort_values("ticker").reset_index(drop=True)
    raw_model = context.reindex(columns=model_features).apply(pd.to_numeric, errors="coerce")
    scaled_matrix = apply_scaler(context, model_meta.get("scaler") or {}, model_features)
    if scaled_matrix.shape != (len(context), len(model_features)) or not np.isfinite(scaled_matrix).all():
        blockers.append("scaled_model_matrix_contract")
    scaled = pd.DataFrame(scaled_matrix, columns=model_features)
    scaled.insert(0, "ticker", context["ticker"])
    missing_mask = raw_model.isna().to_numpy()
    missing_neutral_violations = int(
        (np.abs(scaled_matrix[missing_mask]) > float(args.missing_neutral_tolerance)).sum()
    )
    if missing_neutral_violations:
        blockers.append(f"scaled_missing_neutral_violations:{missing_neutral_violations}")
    future_columns = [
        column for column in (
            "accepted", "fund_accepted", "fund_effective_accepted",
            "fund_latest_accepted_overall", "fund_ttm_fallback_accepted",
        ) if column in context.columns
    ]
    future_feature_rows = 0
    for column in future_columns:
        future_feature_rows += int(
            pd.to_datetime(context[column], errors="coerce", utc=True).gt(decision_time).sum()
        )
    if future_feature_rows:
        blockers.append(f"future_feature_rows:{future_feature_rows}")
    if len(fundamental_audits) != len(statements):
        blockers.append("fundamental_candidate_audit_count_mismatch")

    context_path_out = output_dir / "selection_context.parquet"
    scaled_path = output_dir / "scaled_model_input.parquet"
    coverage_path = output_dir / "ticker_feature_coverage.csv"
    provenance_path = output_dir / "feature_provenance.csv"
    audit_path = output_dir / "fundamental_refresh_audit.csv"
    delta_values_path = output_dir / "fundamental_value_delta.csv"
    overrides_path = output_dir / "fundamental_overrides.parquet"
    context.to_parquet(context_path_out, index=False)
    scaled.to_parquet(scaled_path, index=False)
    pd.DataFrame(fundamental_audits).to_csv(audit_path, index=False)
    pd.DataFrame(changed_rows).to_csv(delta_values_path, index=False)
    pd.DataFrame(fundamental_rows).to_parquet(overrides_path, index=False)
    critical_numeric = context.reindex(columns=P6_CRITICAL_SELECTION_FIELDS).apply(
        pd.to_numeric, errors="coerce"
    )
    critical_missing = critical_numeric.isna()
    critical_missing_fields = critical_missing.apply(
        lambda row: "|".join(
            column for column, missing in row.items() if bool(missing)
        ),
        axis=1,
    )
    neutralized_feature_count = raw_model.isna().sum(axis=1).astype(int)
    coverage = pd.DataFrame({
        "ticker": context["ticker"],
        "raw_model_feature_finite_count": raw_model.notna().sum(axis=1),
        "scaled_model_feature_finite_count": np.isfinite(scaled_matrix).sum(axis=1),
        "neutralized_feature_count": neutralized_feature_count,
        "critical_missing_fields": critical_missing_fields,
        "critical_data_complete": critical_missing_fields.eq(""),
        "data_complete": critical_missing_fields.eq("") & neutralized_feature_count.eq(0),
        "decision_feature_complete": False,
    })
    coverage.to_csv(coverage_path, index=False)
    provenance = pd.DataFrame({
        "model_feature_order": range(len(model_features)),
        "column": model_features,
        "raw_finite_count": raw_model.notna().sum(axis=0).values,
        "scaled_finite_count": np.isfinite(scaled_matrix).sum(axis=0),
        "scaler_missing_neutral_value": 0.0,
    })
    provenance.to_csv(provenance_path, index=False)

    ready = not blockers
    feature_available_from = max(
        pd.Timestamp(macro_available), pd.Timestamp(benchmark_available),
        pd.Timestamp(sec_available.max()) if len(sec_available) else pd.Timestamp(benchmark_available),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_COMPLETE_CURRENT_DECISION_FRAME" if ready else "BLOCKED_CURRENT_DECISION_FRAME",
        "blockers": blockers,
        "valuation_price_cutoff_date": valuation_date,
        "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
        "feature_available_from": feature_available_from.isoformat(),
        "current_decision_data_complete": ready,
        "research_model_scoring_prerequisite_passed": ready,
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "research_only": True,
        "coverage": {
            "decision_ticker_count": int(len(context)),
            "pre_lifecycle_context_count": pre_lifecycle_count,
            "lifecycle_excluded_count": lifecycle_excluded_count,
            "post_lifecycle_context_count": post_lifecycle_count,
            "model_feature_count": len(model_features),
            "selection_context_column_count": int(len(context.columns)),
            "raw_model_feature_finite_ratio": float(raw_model.notna().to_numpy().mean()),
            "scaled_model_feature_finite_ratio": float(np.isfinite(scaled_matrix).mean()),
            "data_complete_ticker_count": int(coverage["data_complete"].sum()),
            "neutralized_ticker_count": int(
                coverage["neutralized_feature_count"].gt(0).sum()
            ),
            "critical_missing_ticker_count": int(
                coverage["critical_missing_fields"].ne("").sum()
            ),
            "scaled_missing_neutral_violation_count": missing_neutral_violations,
            "future_feature_row_count": future_feature_rows,
            "sec_exact_acceptance_count": int(sec_delta["exact_acceptance"].astype(bool).sum()),
            "sec_candidate_count": int(len(sec_delta)),
            "fundamental_refresh_candidate_count": int(len(statements)),
            "fundamental_refresh_resolved_count": int(sum(not row.get("blockers") for row in fundamental_audits)),
        },
        "source_inputs": {
            "scored_latest_manifest": fingerprint(latest_path),
            "base_selection_context": fingerprint(context_path),
            "macro_manifest": fingerprint(macro_path),
            "benchmark_manifest": fingerprint(benchmark_path),
            "sec_delta_manifest": fingerprint(sec_path),
            "companyfacts_manifest": fingerprint(companyfacts_path),
            "model_meta": fingerprint(model_meta_path),
        },
        "outputs": {
            "selection_context": fingerprint(context_path_out),
            "scaled_model_input": fingerprint(scaled_path),
            "ticker_feature_coverage": fingerprint(coverage_path),
            "feature_provenance": fingerprint(provenance_path),
            "fundamental_refresh_audit": fingerprint(audit_path),
            "fundamental_value_delta": fingerprint(delta_values_path),
            "fundamental_overrides": fingerprint(overrides_path),
        },
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored-latest-manifest", required=True)
    parser.add_argument("--macro-manifest", required=True)
    parser.add_argument("--benchmark-manifest", required=True)
    parser.add_argument("--sec-delta-manifest", required=True)
    parser.add_argument("--companyfacts-manifest", required=True)
    parser.add_argument("--valuation-close-date", required=True)
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument("--missing-neutral-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] in {"READY_COMPLETE_CURRENT_DECISION_FRAME", "BLOCKED_CURRENT_DECISION_FRAME"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
