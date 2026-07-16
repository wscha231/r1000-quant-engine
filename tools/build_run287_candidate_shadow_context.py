#!/usr/bin/env python3
"""Build a non-ranking shadow feature context for outside-universe candidates.

The builder computes exact-cutoff technical features, joins Companyfacts only
through exact SEC acceptance timestamps, and uses a same-session macro sidecar
only when its contract is ready. Missing evidence remains raw NaN and becomes
zero only through the frozen scaler. It never predicts, ranks, selects, writes
a target book, runs a backtest/fullrun, or changes the operating universe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO_ROOT))

from r1000_pipeline import apply_scaler, compute_daily_tech_table  # noqa: E402
from tools.build_run287_b002_fundamental_delta import (  # noqa: E402
    apply_current_valuation_overrides,
    build_exact_fundamental_panel,
    clean_accession,
    clean_cik,
    extract_exact_companyfacts_records,
    select_accession_field_records,
)
from tools.run_weekly_evaluation import px_cache_name  # noqa: E402


SCHEMA_VERSION = "run287-candidate-shadow-context-v1"
STATEMENT_FORMS = {
    "10-Q",
    "10-Q/A",
    "10-K",
    "10-K/A",
    "20-F",
    "20-F/A",
    "40-F",
    "40-F/A",
}


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
        raise ValueError(f"JSON input must be an object: {path}")
    return payload


def record_path(manifest_path: Path, record: Mapping[str, Any]) -> Path:
    path = Path(str(record.get("path") or ""))
    return path if path.is_absolute() else manifest_path.parent / path


def verify_record(manifest_path: Path, record: Mapping[str, Any]) -> Path:
    path = record_path(manifest_path, record)
    expected = str(record.get("sha256") or "")
    if not path.is_file() or not expected or sha256_file(path) != expected:
        raise ValueError(f"manifest output hash mismatch: {path}")
    return path


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def clean_ticker(value: Any) -> str:
    text = str(value or "").upper().strip()
    return "" if text in {"", "NAN", "NONE"} else text


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def prepare_statement_index(
    frame: pd.DataFrame,
    *,
    cik10: str,
    observed_at: pd.Timestamp,
) -> tuple[pd.DataFrame, list[str]]:
    required = {
        "cik10",
        "accession_number",
        "form_type",
        "accepted_at",
        "available_from",
        "period_of_report",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        return pd.DataFrame(), ["sec_index_missing_columns:" + ",".join(missing)]
    out = frame.copy()
    out["cik10"] = out["cik10"].map(clean_cik)
    out["accession_number"] = out["accession_number"].map(clean_accession)
    out["form_type"] = out["form_type"].astype(str).str.upper().str.strip()
    out = out.loc[
        out["cik10"].eq(cik10) & out["form_type"].isin(STATEMENT_FORMS)
    ].copy()
    out["accepted_exact"] = pd.to_datetime(out["accepted_at"], errors="coerce", utc=True)
    out["available_exact"] = pd.to_datetime(out["available_from"], errors="coerce", utc=True)
    out["period_exact"] = pd.to_datetime(out["period_of_report"], errors="coerce")
    invalid = out[
        out["accepted_exact"].isna()
        | out["available_exact"].isna()
        | out["period_exact"].isna()
        | out["accession_number"].eq("")
        | ~out["accepted_exact"].eq(out["available_exact"])
    ]
    failures = [f"invalid_or_nonexact_statement_rows:{len(invalid)}"] if len(invalid) else []
    out = out.drop(index=invalid.index)
    out = out.loc[out["available_exact"].le(observed_at)].copy()
    conflicts = 0
    for _, group in out.groupby("accession_number", sort=False):
        conflicts += int(
            len(
                group[
                    ["form_type", "accepted_exact", "available_exact", "period_exact"]
                ].drop_duplicates()
            )
            > 1
        )
    if conflicts:
        failures.append(f"accession_index_conflicts:{conflicts}")
    out = (
        out.sort_values(["accession_number", "accepted_exact"])
        .drop_duplicates("accession_number", keep="last")
        .reset_index(drop=True)
    )
    return out, failures


def load_sec_indexes(paths: Iterable[Path]) -> pd.DataFrame:
    frames = [pd.read_parquet(path) for path in paths]
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def companyfacts_file_map(manifest_paths: Iterable[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for manifest_path in manifest_paths:
        manifest = read_json(manifest_path)
        if manifest.get("status") != "READY_RESEARCH_ONLY_COMPANYFACTS_HISTORY":
            raise ValueError(f"Companyfacts manifest not ready: {manifest_path}")
        for record in manifest.get("companyfacts_files") or []:
            path = Path(str(record.get("path") or ""))
            if not path.is_absolute():
                path = manifest_path.parent / path
            if not path.is_file() or sha256_file(path) != str(record.get("sha256") or ""):
                raise ValueError(f"Companyfacts file hash mismatch: {path}")
            result[clean_cik(record.get("cik10"))] = path
    return result


def macro_values(
    manifest_path: Path,
    *,
    valuation_date: str,
    observed_at: pd.Timestamp,
    model_features: list[str],
) -> tuple[dict[str, float], list[str], dict[str, Any]]:
    manifest = read_json(manifest_path)
    blockers = list(manifest.get("blockers") or [])
    ready = bool(
        manifest.get("status") == "READY_CONSERVATIVE_MACRO_SIDECAR"
        and manifest.get("macro_merge_allowed") is True
        and str(manifest.get("valuation_close_date") or "") == valuation_date
    )
    available = pd.to_datetime(manifest.get("macro_available_from"), errors="coerce", utc=True)
    if pd.isna(available) or pd.Timestamp(available) > observed_at:
        ready = False
        blockers.append("macro_available_after_observed_at_or_missing")
    values: dict[str, float] = {}
    if ready:
        row_path = verify_record(
            manifest_path, (manifest.get("outputs") or {}).get("macro_current") or {}
        )
        frame = pd.read_csv(row_path, low_memory=False)
        if len(frame) != 1:
            blockers.append(f"macro_current_row_count:{len(frame)}")
        else:
            row = frame.iloc[0]
            for column in model_features:
                value = pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
                if pd.notna(value) and np.isfinite(float(value)):
                    values[column] = float(value)
    return values, sorted(set(str(item) for item in blockers)), manifest


def build(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"append-only output already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    queue_path = repo_path(args.research_context_queue)
    price_root = repo_path(args.price_root)
    price_manifest_path = price_root / "replay_price_cache_manifest.json"
    decision_manifest_path = repo_path(args.current_decision_manifest)
    macro_manifest_path = repo_path(args.macro_manifest)
    sec_paths = [repo_path(path) for path in args.sec_index]
    companyfacts_manifest_paths = [repo_path(path) for path in args.companyfacts_manifest]
    observed_at = pd.Timestamp(pd.to_datetime(args.observed_at_utc, utc=True))
    valuation_date = pd.Timestamp(args.valuation_close_date).date().isoformat()
    valuation_ts = pd.Timestamp(valuation_date)

    queue = pd.read_csv(queue_path, low_memory=False)
    queue["ticker"] = queue["ticker"].map(clean_ticker)
    failures: list[str] = []
    if len(queue) != int(args.expected_ticker_count):
        failures.append(f"queue_count:{len(queue)}!={args.expected_ticker_count}")
    if queue["ticker"].duplicated().any() or queue["ticker"].eq("").any():
        failures.append("queue_ticker_identity_invalid")
    if queue.get("in_frozen_universe", False).map(boolish).any():
        failures.append("queue_contains_operating_universe_name")
    if queue.get("operating_universe_append_allowed", False).map(boolish).any():
        failures.append("queue_allows_operating_universe_append")

    price_manifest = read_json(price_manifest_path)
    if (
        price_manifest.get("status") != "completed"
        or int(price_manifest.get("failed_count") or 0) != 0
        or str(price_manifest.get("end") or "") != valuation_date
    ):
        failures.append("settled_price_manifest_contract")

    decision_manifest = read_json(decision_manifest_path)
    if decision_manifest.get("status") != "READY_COMPLETE_CURRENT_DECISION_FRAME":
        failures.append("current_decision_manifest_not_ready")
    model_record = (decision_manifest.get("source_inputs") or {}).get("model_meta") or {}
    model_meta_path = verify_record(decision_manifest_path, model_record)
    model_meta = read_json(model_meta_path)
    model_features = [str(value) for value in model_meta.get("model_features") or []]
    scaler = model_meta.get("scaler") or {}
    if len(model_features) != int(args.expected_model_feature_count):
        failures.append(
            f"model_feature_count:{len(model_features)}!={args.expected_model_feature_count}"
        )
    if set(model_features) != set(scaler):
        failures.append("model_scaler_schema_mismatch")

    sec_index = load_sec_indexes(sec_paths)
    companyfacts_paths = companyfacts_file_map(companyfacts_manifest_paths)
    macro, macro_blockers, macro_manifest = macro_values(
        macro_manifest_path,
        valuation_date=valuation_date,
        observed_at=observed_at,
        model_features=model_features,
    )

    context_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    fundamental_audits: list[dict[str, Any]] = []
    technical_columns: set[str] = set()
    fundamental_columns: set[str] = set()
    future_price_rows = 0
    future_fundamental_rows = 0

    for intake in queue.to_dict("records"):
        ticker = clean_ticker(intake.get("ticker"))
        price_path = price_root / px_cache_name(ticker)
        if not price_path.is_file():
            failures.append(f"price_file_missing:{ticker}")
            continue
        prices = pd.read_parquet(price_path)
        prices.index = pd.to_datetime(prices.index, errors="coerce").tz_localize(None).normalize()
        future_count = int((prices.index > valuation_ts).sum())
        future_price_rows += future_count
        prices = prices.loc[prices.index <= valuation_ts].copy()
        technical = compute_daily_tech_table(prices)
        technical.index = pd.to_datetime(technical.index, errors="coerce").normalize()
        if technical.empty or valuation_ts not in technical.index:
            failures.append(f"technical_exact_close_missing:{ticker}")
            continue
        latest_technical = technical.loc[valuation_ts]
        technical_columns.update(str(column) for column in technical.columns)
        row: dict[str, Any] = {
            "ticker": ticker,
            "issuer_key": intake.get("issuer_key", ticker),
            "valuation_price_cutoff_date": valuation_date,
            "feature_available_from": observed_at.isoformat(),
            "identity_cik10": clean_cik(intake.get("identity_cik10"))
            or clean_cik(intake.get("universe_cik10")),
            "issuer_sec_proxy_ticker": clean_ticker(intake.get("issuer_sec_proxy_ticker")),
            "canonical_7y_price_eligible": boolish(
                intake.get("canonical_7y_price_eligible")
            ),
            "research_only": True,
            "decision_ranking_allowed": False,
            "operating_universe_append_allowed": False,
        }
        for column, value in latest_technical.items():
            row[str(column)] = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        row["persistence_trend_24m"] = float(
            pd.notna(row.get("mom_12m"))
            and pd.notna(row.get("mom_24m"))
            and pd.notna(row.get("mom_36m"))
            and float(row["mom_12m"]) > 0.15
            and float(row["mom_24m"]) > 0.30
            and float(row["mom_36m"]) > 0.50
        )
        for column, value in macro.items():
            row[column] = value

        cik10 = str(row["identity_cik10"] or "")
        facts_path = companyfacts_paths.get(cik10)
        panel = pd.DataFrame()
        exact_records = pd.DataFrame()
        selected_records = pd.DataFrame()
        index_failures: list[str] = []
        counters: dict[str, int] = {}
        statement_index = pd.DataFrame()
        if cik10 and facts_path is not None:
            statement_index, index_failures = prepare_statement_index(
                sec_index, cik10=cik10, observed_at=observed_at
            )
            facts_payload = read_json(facts_path)
            exact_records, counters = extract_exact_companyfacts_records(
                facts_payload,
                cik10=cik10,
                ticker=ticker,
                statement_index=statement_index,
                decision_time=observed_at,
            )
            selected_records = select_accession_field_records(exact_records)
            panel = build_exact_fundamental_panel(selected_records)
        if not panel.empty:
            accepted = pd.to_datetime(panel.get("accepted"), errors="coerce", utc=True)
            future_fundamental_rows += int(accepted.gt(observed_at).sum())
            panel = panel.loc[accepted.le(observed_at)].copy()
        latest_fundamental = pd.Series(dtype=object)
        if not panel.empty:
            latest_fundamental = (
                panel.sort_values(["period", "accepted"], na_position="last").iloc[-1]
            )
            latest_fundamental = apply_current_valuation_overrides(
                latest_fundamental,
                technical_price=float(row.get("px")),
            )
            for column, value in latest_fundamental.items():
                if column in row and column not in {"dividend_yield_ttm"}:
                    continue
                row[str(column)] = value
                fundamental_columns.add(str(column))

        raw_values = {
            column: pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
            for column in model_features
        }
        context_rows.append({**row, **raw_values})
        core_fields = ("assets", "liabilities", "shares", "revenues", "op_income", "net_income", "ocf")
        core_count = int(sum(pd.notna(latest_fundamental.get(field)) for field in core_fields))
        if not cik10:
            context_status = "TECHNICAL_ONLY_HOME_MARKET_FILING_BLOCKED"
        elif panel.empty:
            context_status = "TECHNICAL_ONLY_STATEMENT_PENDING"
        else:
            context_status = "PARTIAL_TECHNICAL_FUNDAMENTAL_CONTEXT_READY"
        finite_raw = int(sum(pd.notna(value) and np.isfinite(float(value)) for value in raw_values.values()))
        coverage_rows.append(
            {
                "ticker": ticker,
                "context_status": context_status,
                "price_rows": int(len(prices)),
                "price_start": prices.index.min().date().isoformat(),
                "price_end": prices.index.max().date().isoformat(),
                "future_price_row_count": future_count,
                "technical_model_feature_finite_count": int(
                    sum(
                        column in technical_columns
                        and pd.notna(raw_values.get(column))
                        for column in model_features
                    )
                ),
                "statement_index_rows": int(len(statement_index)),
                "exact_companyfacts_record_count": int(len(exact_records)),
                "selected_companyfacts_record_count": int(len(selected_records)),
                "fundamental_panel_rows": int(len(panel)),
                "fundamental_core_field_count": core_count,
                "latest_fundamental_period": (
                    str(pd.Timestamp(latest_fundamental.get("period")).date())
                    if pd.notna(latest_fundamental.get("period"))
                    else ""
                ),
                "raw_model_feature_finite_count": finite_raw,
                "raw_model_feature_missing_neutral_count": len(model_features) - finite_raw,
                "macro_model_feature_count": len(macro),
                "canonical_7y_price_eligible": row["canonical_7y_price_eligible"],
                "decision_ranking_allowed": False,
            }
        )
        fundamental_audits.append(
            {
                "ticker": ticker,
                "cik10": cik10,
                "companyfacts_file_available": facts_path is not None,
                "statement_index_failures": "|".join(index_failures),
                **counters,
                "panel_rows": int(len(panel)),
                "future_panel_rows": int(
                    pd.to_datetime(panel.get("accepted"), errors="coerce", utc=True)
                    .gt(observed_at)
                    .sum()
                )
                if not panel.empty
                else 0,
            }
        )

    context = pd.DataFrame(context_rows)
    coverage = pd.DataFrame(coverage_rows)
    if len(context) != int(args.expected_ticker_count):
        failures.append(f"assembled_context_count:{len(context)}!={args.expected_ticker_count}")
    raw_model = context.reindex(columns=model_features).apply(pd.to_numeric, errors="coerce")
    scaled_matrix = apply_scaler(raw_model, scaler, model_features) if len(context) else np.empty((0, len(model_features)))
    missing_mask = raw_model.isna().to_numpy()
    missing_neutral_violations = int(
        (np.abs(scaled_matrix[missing_mask]) > float(args.missing_neutral_tolerance)).sum()
    ) if len(context) else 0
    if not np.isfinite(scaled_matrix).all():
        failures.append("scaled_model_input_nonfinite")
    if missing_neutral_violations:
        failures.append(f"scaled_missing_neutral_violations:{missing_neutral_violations}")
    if future_price_rows or future_fundamental_rows:
        failures.append(
            f"future_rows:price={future_price_rows},fundamental={future_fundamental_rows}"
        )

    scaled = pd.DataFrame(scaled_matrix, columns=model_features)
    scaled.insert(0, "ticker", context.get("ticker", pd.Series(dtype=str)).values)
    metadata_columns = [
        "ticker",
        "issuer_key",
        "identity_cik10",
        "issuer_sec_proxy_ticker",
        "valuation_price_cutoff_date",
        "feature_available_from",
        "canonical_7y_price_eligible",
        "research_only",
        "decision_ranking_allowed",
        "operating_universe_append_allowed",
    ]
    feature_context = pd.concat(
        [context.reindex(columns=metadata_columns), raw_model], axis=1
    )
    provenance = pd.DataFrame(
        {
            "model_feature_order": range(len(model_features)),
            "column": model_features,
            "lane": [
                "technical"
                if column in technical_columns or column == "persistence_trend_24m"
                else "macro"
                if column in macro
                else "fundamental_or_derived"
                if column in fundamental_columns
                else "missing_neutral"
                for column in model_features
            ],
            "raw_nonmissing_count": [int(raw_model[column].notna().sum()) for column in model_features],
            "raw_missing_neutral_count": [int(raw_model[column].isna().sum()) for column in model_features],
            "scaled_finite_count": [int(np.isfinite(scaled_matrix[:, index]).sum()) for index in range(len(model_features))],
            "scaler_missing_neutral_value": 0.0,
        }
    )

    context_path = output_dir / "shadow_feature_context.parquet"
    raw_path = output_dir / "shadow_raw_model_input.parquet"
    scaled_path = output_dir / "shadow_scaled_model_input.parquet"
    coverage_path = output_dir / "ticker_feature_coverage.csv"
    fundamental_path = output_dir / "fundamental_join_audit.csv"
    provenance_path = output_dir / "model_feature_provenance.csv"
    feature_context.to_parquet(context_path, index=False)
    raw_model.insert(0, "ticker", context.get("ticker", pd.Series(dtype=str)).values)
    raw_model.to_parquet(raw_path, index=False)
    scaled.to_parquet(scaled_path, index=False)
    coverage.to_csv(coverage_path, index=False)
    pd.DataFrame(fundamental_audits).to_csv(fundamental_path, index=False)
    provenance.to_csv(provenance_path, index=False)

    status = (
        "BLOCKED_CANDIDATE_SHADOW_CONTEXT"
        if failures
        else "READY_PARTIAL_CANDIDATE_SHADOW_CONTEXT_NONRANKING"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": failures,
        "component_blockers": {"macro": macro_blockers},
        "valuation_price_cutoff_date": valuation_date,
        "observed_at_utc": observed_at.isoformat(),
        "research_only": True,
        "partial_context": True,
        "context_complete_for_ranking": False,
        "decision_ranking_allowed": False,
        "model_scoring_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "orders_generated": False,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "operating_universe_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "pit_universe_label_clean": False,
        "coverage": {
            "candidate_count": int(len(context)),
            "expected_candidate_count": int(args.expected_ticker_count),
            "model_feature_count": len(model_features),
            "technical_exact_close_count": int(len(context)),
            "fundamental_panel_ready_count": int(coverage["fundamental_panel_rows"].gt(0).sum()) if len(coverage) else 0,
            "technical_only_count": int(coverage["fundamental_panel_rows"].eq(0).sum()) if len(coverage) else 0,
            "macro_model_feature_count": len(macro),
            "raw_model_feature_finite_ratio": float(
                raw_model.drop(columns=["ticker"]).notna().to_numpy().mean()
            )
            if len(raw_model)
            else 0.0,
            "scaled_model_feature_finite_ratio": float(np.isfinite(scaled_matrix).mean()) if scaled_matrix.size else 0.0,
            "scaled_missing_neutral_violation_count": missing_neutral_violations,
            "future_price_row_count": future_price_rows,
            "future_fundamental_row_count": future_fundamental_rows,
        },
        "source_inputs": {
            "research_context_queue": fingerprint(queue_path),
            "settled_price_manifest": fingerprint(price_manifest_path),
            "current_decision_manifest": fingerprint(decision_manifest_path),
            "model_meta": fingerprint(model_meta_path),
            "macro_manifest": fingerprint(macro_manifest_path),
            "macro_status": macro_manifest.get("status"),
            "sec_indexes": [fingerprint(path) for path in sec_paths],
            "companyfacts_manifests": [fingerprint(path) for path in companyfacts_manifest_paths],
        },
        "outputs": {
            "shadow_feature_context": fingerprint(context_path),
            "shadow_raw_model_input": fingerprint(raw_path),
            "shadow_scaled_model_input": fingerprint(scaled_path),
            "ticker_feature_coverage": fingerprint(coverage_path),
            "fundamental_join_audit": fingerprint(fundamental_path),
            "model_feature_provenance": fingerprint(provenance_path),
        },
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Run287 outside-candidate shadow context",
        "",
        f"Status: `{status}`.",
        "",
        f"- candidates: `{len(context)}`",
        f"- exact-close technical rows: `{payload['coverage']['technical_exact_close_count']}`",
        f"- exact accepted-time fundamental panels: `{payload['coverage']['fundamental_panel_ready_count']}`",
        f"- technical-only rows: `{payload['coverage']['technical_only_count']}`",
        f"- same-session macro model features: `{payload['coverage']['macro_model_feature_count']}`",
        f"- raw frozen-model feature coverage: `{payload['coverage']['raw_model_feature_finite_ratio']:.1%}`",
        f"- scaled finite coverage: `{payload['coverage']['scaled_model_feature_finite_ratio']:.1%}`",
        "",
        "This package is deliberately partial and non-ranking. Missing inputs are neutralized only by the frozen scaler. It cannot be passed to model prediction, selection, portfolio A/B, fullrun, production, or live trading.",
        "",
        "## Per-ticker route",
        "",
        "| ticker | status | technical model fields | fundamental panel rows | core fields |",
        "|---|---|---:|---:|---:|",
    ]
    for record in coverage.to_dict("records"):
        lines.append(
            f"| {record['ticker']} | `{record['context_status']}` | "
            f"{record['technical_model_feature_finite_count']} | "
            f"{record['fundamental_panel_rows']} | {record['fundamental_core_field_count']} |"
        )
    if macro_blockers:
        lines.extend(["", "## Macro blockers", "", *[f"- `{item}`" for item in macro_blockers]])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-context-queue", required=True)
    parser.add_argument("--price-root", required=True)
    parser.add_argument("--current-decision-manifest", required=True)
    parser.add_argument("--macro-manifest", required=True)
    parser.add_argument("--sec-index", nargs="+", required=True)
    parser.add_argument("--companyfacts-manifest", nargs="+", required=True)
    parser.add_argument("--valuation-close-date", required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--expected-ticker-count", type=int, default=14)
    parser.add_argument("--expected-model-feature-count", type=int, default=238)
    parser.add_argument("--missing-neutral-tolerance", type=float, default=1e-12)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] in {
        "READY_PARTIAL_CANDIDATE_SHADOW_CONTEXT_NONRANKING",
        "BLOCKED_CANDIDATE_SHADOW_CONTEXT",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
