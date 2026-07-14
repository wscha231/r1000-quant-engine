#!/usr/bin/env python3
"""Build the bounded B002 exact-accepted SEC fundamental delta.

This sidecar resolves statement blockers left by the B002 technical pilot. It
streams only the required Companyfacts members, joins every used fact by SEC
accession number to the local submissions index, and uses the index's exact
``accepted_at`` as ``available_from``. The Companyfacts ``filed`` field is kept
for diagnostics only and is never a time fallback.

Only facts whose ``end`` matches the filing's SEC ``period_of_report`` enter
the panel. For Q1-Q3, a direct-quarter fact is preferred over a cumulative YTD
fact from the same accession; annual filings use the annual cumulative fact.
Amendments replace prior values only from the amendment acceptance timestamp.

The output is research-only and non-ranking. It does not download data, score
or select securities, run a backtest/fullrun, mutate source caches, or touch a
target book.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_config import (  # noqa: E402
    CORE_FUNDAMENTAL_MINIMUM_FIELDS,
    FSDS_TAG_ALIASES,
)
from r1000_features import recompute_fund_panel_derived_columns  # noqa: E402
from r1000_pipeline import (  # noqa: E402
    companyfacts_duration_days,
    companyfacts_quarterly_flows,
    preferred_companyfacts_unit_keys,
)


SCHEMA_VERSION = "run287-b002-exact-fundamental-delta-v1"
DEFAULT_TECHNICAL = (
    "outputs/run287_b002_technical_delta_20260712_commit_b3e9c885/manifest.json"
)
DEFAULT_EVENT = (
    "outputs/run287_b002_8k_event_sidecar_20260712_commit_1b12d8a6/manifest.json"
)
DEFAULT_COMPANYFACTS = "data_raw/free/sec/companyfacts.zip"
DEFAULT_SEC_INDEX = "data_pit/sec/sec_filings_index.parquet"
DEFAULT_OUTPUT = "outputs/run287_b002_fundamental_delta_20260712"

STATEMENT_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}
BALANCE_FIELDS = ("assets", "liabilities", "shares")
AUXILIARY_BALANCE_FACT_ALIASES = {
    "liabilities_and_equity": ("LiabilitiesAndStockholdersEquity",),
    "stockholders_equity_for_liabilities": (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ),
}
AUXILIARY_BALANCE_FIELDS = tuple(AUXILIARY_BALANCE_FACT_ALIASES)
FLOW_FIELDS = (
    "revenues",
    "cost_of_revenue",
    "gross_profit",
    "op_income",
    "net_income",
    "ocf",
    "capex",
)
PANEL_FIELDS = BALANCE_FIELDS + FLOW_FIELDS
FACT_FIELDS = PANEL_FIELDS + AUXILIARY_BALANCE_FIELDS
VALUATION_OVERRIDE_COLUMNS = (
    "mktcap",
    "market_cap_live",
    "current_price_live",
    "ep_ttm",
    "sp_ttm",
    "fcfy_ttm",
    "roa_proxy",
    "asset_turnover_ttm",
    "roe_proxy",
    "return_on_equity_effective",
    "book_to_market_proxy",
    "gross_margins",
    "operating_margins",
    "shares_effective",
    "fund_panel_ttm_ready",
)
STABLE_CONDITIONAL_DERIVED_COLUMNS = (
    "fcf_margin",
    "net_margin",
    "gross_margin_ttm",
    "op_margin_calc_ttm",
    "rule_of_40",
    "sbc_to_revenue",
    "rd_intensity",
    "roic_approx",
    "interest_coverage",
    "dilution_penalty",
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
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "bytes": int(stat.st_size),
        "sha256": sha256_file(path),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return loaded


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def clean_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def clean_cik(value: Any) -> str:
    text = str(value or "").split(".", maxsplit=1)[0]
    digits = "".join(character for character in text if character.isdigit())
    return digits.zfill(10)[-10:] if digits else ""


def clean_accession(value: Any) -> str:
    return str(value or "").strip()


def clean_date(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def utc_timestamp(value: Any) -> pd.Timestamp:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid UTC timestamp: {value}")
    return pd.Timestamp(parsed)


def split_tickers(value: Any) -> set[str]:
    return {
        clean_ticker(item)
        for item in str(value or "").replace(";", ",").split(",")
        if clean_ticker(item)
    }


def parse_partial_core_missing_neutral(values: Any) -> dict[str, set[str]]:
    mappings: dict[str, set[str]] = {}
    for raw in list(values or []):
        ticker, separator, field_text = str(raw).partition("=")
        ticker = clean_ticker(ticker)
        fields = {
            item.strip()
            for item in field_text.replace(",", "|").split("|")
            if item.strip()
        }
        if not separator or not ticker or not fields:
            raise ValueError(f"expected TICKER=core_field[|core_field], got {raw!r}")
        if ticker in mappings:
            raise ValueError(f"duplicate partial-core ticker: {ticker}")
        unknown = fields - set(CORE_FUNDAMENTAL_MINIMUM_FIELDS)
        if unknown:
            raise ValueError(
                f"unknown partial-core fields for {ticker}: {','.join(sorted(unknown))}"
            )
        mappings[ticker] = fields
    return mappings


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def manifest_record_path(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    key: str,
) -> Path:
    record = (manifest.get(section) or {}).get(key) or {}
    raw = str(record.get("path") or "")
    if not raw:
        raise ValueError(f"manifest missing {section}.{key}.path")
    path = Path(raw)
    return path if path.is_absolute() else manifest_path.parent / path


def verify_manifest_file(
    manifest_path: Path,
    manifest: Mapping[str, Any],
    section: str,
    key: str,
) -> tuple[Path, dict[str, Any]]:
    path = manifest_record_path(manifest_path, manifest, section, key)
    actual = fingerprint(path)
    expected = (manifest.get(section) or {}).get(key) or {}
    actual["expected_sha256"] = expected.get("sha256")
    actual["hash_matches"] = bool(
        actual.get("exists")
        and expected.get("sha256")
        and actual.get("sha256") == expected.get("sha256")
    )
    return path, actual


def companyfacts_member_name(zf: zipfile.ZipFile, cik10: str) -> str:
    expected = f"CIK{cik10}.json"
    direct = [name for name in zf.namelist() if Path(name).name == expected]
    if len(direct) != 1:
        raise ValueError(f"companyfacts member count for {cik10}: {len(direct)}")
    return direct[0]


def accession_fact_count(payload: Mapping[str, Any], accession: str) -> int:
    """Count every raw Companyfacts unit row for one exact accession."""

    count = 0
    for namespace_facts in (payload.get("facts") or {}).values():
        if not isinstance(namespace_facts, Mapping):
            continue
        for fact in namespace_facts.values():
            if not isinstance(fact, Mapping):
                continue
            for values in (fact.get("units") or {}).values():
                if not isinstance(values, list):
                    continue
                count += sum(
                    1
                    for item in values
                    if isinstance(item, Mapping)
                    and clean_accession(item.get("accn")) == accession
                )
    return count


def prepare_statement_index(sec_index: pd.DataFrame, cik10: str) -> tuple[pd.DataFrame, list[str]]:
    failures: list[str] = []
    required = {
        "cik10",
        "accession_number",
        "form_type",
        "accepted_at",
        "available_from",
        "period_of_report",
    }
    missing = sorted(required - set(sec_index.columns))
    if missing:
        return pd.DataFrame(), ["sec_index_missing_columns:" + ",".join(missing)]
    output = sec_index.copy()
    output["cik10"] = output["cik10"].map(clean_cik)
    output["accession_number"] = output["accession_number"].map(clean_accession)
    output["form_type"] = output["form_type"].astype(str).str.upper().str.strip()
    output = output.loc[
        output["cik10"].eq(cik10) & output["form_type"].isin(STATEMENT_FORMS)
    ].copy()
    output["accepted_exact"] = pd.to_datetime(
        output["accepted_at"], errors="coerce", utc=True
    )
    output["available_exact"] = pd.to_datetime(
        output["available_from"], errors="coerce", utc=True
    )
    output["period_exact"] = pd.to_datetime(
        output["period_of_report"], errors="coerce"
    )
    invalid = output[
        output["accepted_exact"].isna()
        | output["available_exact"].isna()
        | output["period_exact"].isna()
        | output["accession_number"].eq("")
    ]
    if not invalid.empty:
        failures.append(f"invalid_statement_index_rows:{len(invalid)}")
    available_mismatch = output[
        output["accepted_exact"].notna()
        & output["available_exact"].notna()
        & ~output["accepted_exact"].eq(output["available_exact"])
    ]
    if not available_mismatch.empty:
        failures.append(
            f"accepted_available_mismatch_rows:{len(available_mismatch)}"
        )
    duplicate_conflicts = 0
    for _, group in output.groupby("accession_number", sort=False):
        signature = group[
            ["form_type", "accepted_exact", "available_exact", "period_exact"]
        ].drop_duplicates()
        duplicate_conflicts += int(len(signature) > 1)
    if duplicate_conflicts:
        failures.append(f"accession_index_conflicts:{duplicate_conflicts}")
    output = (
        output.sort_values(["accession_number", "accepted_exact"])
        .drop_duplicates("accession_number", keep="last")
        .reset_index(drop=True)
    )
    return output, failures


def select_latest_new_statement(
    statement_index: pd.DataFrame,
    *,
    frozen_feature_date: Any,
    decision_time: pd.Timestamp,
) -> tuple[pd.DataFrame, int, list[str]]:
    """Select the latest exact statement filing inside the decision-time window.

    The technical audit's generic ``latest_new_accession_number`` may point to
    a later 8-K when a ticker has both event and statement filings.  Statement
    recomputation therefore derives its accession from the statement-only SEC
    index, bounded by the ticker's frozen feature date and decision time.
    """

    failures: list[str] = []
    required = {"accepted_exact", "accession_number"}
    missing = sorted(required - set(statement_index.columns))
    if missing:
        return (
            pd.DataFrame(),
            0,
            ["statement_index_selection_missing_columns:" + ",".join(missing)],
        )
    frozen = pd.to_datetime(frozen_feature_date, errors="coerce", utc=True)
    if pd.isna(frozen):
        return pd.DataFrame(), 0, ["invalid_frozen_feature_date"]
    eligible = statement_index[
        statement_index["accepted_exact"].notna()
        & statement_index["accepted_exact"].gt(pd.Timestamp(frozen))
        & statement_index["accepted_exact"].le(decision_time)
    ].copy()
    if eligible.empty:
        return eligible, 0, ["new_statement_index_count:0"]
    latest = (
        eligible.sort_values(["accepted_exact", "accession_number"])
        .tail(1)
        .reset_index(drop=True)
    )
    return latest, int(len(eligible)), failures


def fact_semantics(field_name: str, fp: Any, form: Any, duration_days: Any) -> tuple[str, int]:
    if field_name in BALANCE_FIELDS or field_name in AUXILIARY_BALANCE_FIELDS:
        return "instant", 0
    duration = pd.to_numeric(pd.Series([duration_days]), errors="coerce").iloc[0]
    fiscal_period = str(fp or "").upper().strip()
    form_type = str(form or "").upper().strip()
    if fiscal_period == "FY" or form_type.startswith("10-K"):
        return ("annual", 0) if pd.notna(duration) and duration >= 300 else ("nonannual_fy", 2)
    if fiscal_period in {"Q1", "Q2", "Q3"}:
        if pd.notna(duration) and 70 <= duration <= 120:
            return "direct_quarter", 0
        if pd.notna(duration) and 121 <= duration <= 300:
            return "cumulative_ytd", 1
    return "unclassified_duration", 2


def extract_exact_companyfacts_records(
    payload: Mapping[str, Any],
    *,
    cik10: str,
    ticker: str,
    statement_index: pd.DataFrame,
    decision_time: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, int]]:
    counters = {
        "candidate_fact_count": 0,
        "exact_joined_fact_count": 0,
        "unmatched_accession_fact_count": 0,
        "future_available_fact_count": 0,
        "period_mismatch_fact_count": 0,
        "form_mismatch_fact_count": 0,
        "invalid_value_fact_count": 0,
        "filed_fallback_used_count": 0,
    }
    index_map = statement_index.set_index("accession_number").to_dict("index")
    facts = payload.get("facts") or {}
    rows: list[dict[str, Any]] = []
    for field_name in FACT_FIELDS:
        aliases = (
            AUXILIARY_BALANCE_FACT_ALIASES.get(field_name)
            or FSDS_TAG_ALIASES.get(field_name)
            or []
        )
        for namespace in ("us-gaap", "dei", "ifrs-full"):
            namespace_facts = facts.get(namespace) or {}
            if not isinstance(namespace_facts, Mapping):
                continue
            for alias_priority, alias in enumerate(aliases):
                fact = namespace_facts.get(alias)
                if not isinstance(fact, Mapping):
                    continue
                units = fact.get("units") or {}
                if not isinstance(units, Mapping):
                    continue
                for unit in preferred_companyfacts_unit_keys(field_name, units.keys()):
                    values = units.get(unit) or []
                    if not isinstance(values, list):
                        continue
                    for item in values:
                        if not isinstance(item, Mapping):
                            continue
                        counters["candidate_fact_count"] += 1
                        accession = clean_accession(item.get("accn"))
                        index_row = index_map.get(accession)
                        if not accession or index_row is None:
                            counters["unmatched_accession_fact_count"] += 1
                            continue
                        accepted = pd.Timestamp(index_row["accepted_exact"])
                        if accepted > decision_time:
                            counters["future_available_fact_count"] += 1
                            continue
                        item_form = str(item.get("form") or "").upper().strip()
                        index_form = str(index_row.get("form_type") or "").upper().strip()
                        if item_form and item_form != index_form:
                            counters["form_mismatch_fact_count"] += 1
                            continue
                        end = pd.to_datetime(str(item.get("end") or ""), errors="coerce")
                        report_period = pd.to_datetime(
                            index_row.get("period_exact"), errors="coerce"
                        )
                        if (
                            pd.isna(end)
                            or pd.isna(report_period)
                            or pd.Timestamp(end).normalize()
                            != pd.Timestamp(report_period).normalize()
                        ):
                            counters["period_mismatch_fact_count"] += 1
                            continue
                        value = pd.to_numeric(
                            pd.Series([item.get("val")]), errors="coerce"
                        ).iloc[0]
                        if pd.isna(value) or not np.isfinite(float(value)):
                            counters["invalid_value_fact_count"] += 1
                            continue
                        duration_days = companyfacts_duration_days(
                            item.get("start"), item.get("end")
                        )
                        semantics, semantic_rank = fact_semantics(
                            field_name,
                            item.get("fp"),
                            index_form,
                            duration_days,
                        )
                        rows.append(
                            {
                                "ticker": ticker,
                                "cik": cik10,
                                "cik10": cik10,
                                "accession_number": accession,
                                "form": index_form,
                                "fiscal_period": item.get("fp"),
                                "period": pd.Timestamp(end),
                                "period_of_report": pd.Timestamp(report_period),
                                "accepted": accepted,
                                "accepted_at": accepted,
                                "available_from": accepted,
                                "exact_acceptance": True,
                                "fy": item.get("fy"),
                                "fp": item.get("fp"),
                                "frame": item.get("frame"),
                                "start": pd.to_datetime(item.get("start"), errors="coerce"),
                                "duration_days": duration_days,
                                "field_name": field_name,
                                "source_namespace": namespace,
                                "source_tag": alias,
                                "alias_priority": alias_priority,
                                "fact_semantics": semantics,
                                "semantic_rank": semantic_rank,
                                "unit": str(unit),
                                "value": float(value),
                                "filed_diagnostic": item.get("filed"),
                                "filed_used_for_availability": False,
                                "period_matches_sec_report": True,
                            }
                        )
                        counters["exact_joined_fact_count"] += 1
    return pd.DataFrame(rows), counters


def select_accession_field_records(records: pd.DataFrame) -> pd.DataFrame:
    if records is None or records.empty:
        return pd.DataFrame() if records is None else records.copy()
    selected = records.copy()
    selected["duration_days"] = pd.to_numeric(
        selected.get("duration_days"), errors="coerce"
    )
    selected = selected.sort_values(
        [
            "ticker",
            "accession_number",
            "field_name",
            "semantic_rank",
            "alias_priority",
            "duration_days",
            "source_tag",
        ],
        ascending=[True, True, True, True, True, True, True],
        na_position="last",
    ).drop_duplicates(
        ["ticker", "accession_number", "field_name"], keep="first"
    )
    selected["used_for_panel"] = True
    return selected.reset_index(drop=True)


def _pivot_panel(frame: pd.DataFrame, value_column: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["cik", "period"])
    output = frame.pivot_table(
        index=["cik", "period"],
        columns="field_name",
        values=value_column,
        aggfunc="last",
    ).reset_index()
    output.columns = [column if isinstance(column, str) else str(column) for column in output.columns]
    return output


def build_exact_fundamental_panel(selected: pd.DataFrame) -> pd.DataFrame:
    if selected is None or selected.empty:
        return pd.DataFrame()
    balance = selected[
        selected["field_name"].isin(BALANCE_FIELDS + AUXILIARY_BALANCE_FIELDS)
    ].copy()
    balance = (
        balance.sort_values(["cik", "period", "accepted"])
        .drop_duplicates(["cik", "period", "field_name"], keep="last")
    )
    flow_frames: list[pd.DataFrame] = []
    cumulative_frames: list[pd.DataFrame] = []
    quarter_frames: list[pd.DataFrame] = []
    for field_name in FLOW_FIELDS:
        quarterly = companyfacts_quarterly_flows(
            selected[selected["field_name"].eq(field_name)]
        )
        if quarterly.empty:
            continue
        flow_frames.append(
            quarterly[["cik", "period", "accepted", "field_name", "flow"]]
        )
        cumulative = quarterly[
            ["cik", "period", "accepted", "field_name", "cum_value"]
        ].copy()
        cumulative["field_name"] = cumulative["field_name"].astype(str) + "_cum_value"
        cumulative = cumulative.rename(columns={"cum_value": "value"})
        cumulative_frames.append(cumulative)
        quarter_frames.append(
            quarterly[["cik", "period", "accepted", "q_idx"]].rename(
                columns={"q_idx": "quarter_index"}
            )
        )
    flow = pd.concat(flow_frames, ignore_index=True) if flow_frames else pd.DataFrame()
    cumulative = (
        pd.concat(cumulative_frames, ignore_index=True)
        if cumulative_frames
        else pd.DataFrame()
    )
    quarter_meta = (
        pd.concat(quarter_frames, ignore_index=True)
        if quarter_frames
        else pd.DataFrame()
    )
    if balance.empty and flow.empty:
        return pd.DataFrame()
    accepted_frames = []
    for frame in (balance, flow, cumulative):
        if frame is not None and not frame.empty:
            accepted_frames.append(frame[["cik", "period", "accepted"]])
    accepted = (
        pd.concat(accepted_frames, ignore_index=True)
        .sort_values(["cik", "period", "accepted"])
        .drop_duplicates(["cik", "period"], keep="last")
    )
    panel = _pivot_panel(balance, "value").merge(
        _pivot_panel(flow, "flow"), on=["cik", "period"], how="outer"
    )
    if not cumulative.empty:
        panel = panel.merge(
            _pivot_panel(cumulative, "value"),
            on=["cik", "period"],
            how="outer",
        )
    panel = panel.merge(accepted, on=["cik", "period"], how="left")
    if not quarter_meta.empty:
        quarter_meta = (
            quarter_meta.sort_values(["cik", "period", "accepted"])
            .drop_duplicates(["cik", "period"], keep="last")
            .drop(columns=["accepted"], errors="ignore")
        )
        panel = panel.merge(quarter_meta, on=["cik", "period"], how="left")
    period_meta = (
        selected.sort_values(["cik", "period", "accepted"])
        .drop_duplicates(["cik", "period"], keep="last")
        [["cik", "period", "accession_number", "form", "fiscal_period"]]
    )
    panel = panel.merge(period_meta, on=["cik", "period"], how="left")
    # The engine derivator expects every canonical panel field to be a Series.
    # Keep absent components explicitly missing rather than letting DataFrame.get
    # return a scalar NaN in downstream arithmetic.
    for field_name in PANEL_FIELDS:
        if field_name not in panel.columns:
            panel[field_name] = np.nan
    liabilities_direct = pd.to_numeric(panel["liabilities"], errors="coerce")
    liabilities_and_equity = pd.to_numeric(
        panel.get("liabilities_and_equity", pd.Series(np.nan, index=panel.index)),
        errors="coerce",
    )
    stockholders_equity = pd.to_numeric(
        panel.get(
            "stockholders_equity_for_liabilities",
            pd.Series(np.nan, index=panel.index),
        ),
        errors="coerce",
    )
    derived_liabilities = liabilities_and_equity - stockholders_equity
    liability_derivation_mask = (
        liabilities_direct.isna()
        & liabilities_and_equity.notna()
        & stockholders_equity.notna()
        & liabilities_and_equity.ge(stockholders_equity)
        & stockholders_equity.ge(0.0)
    )
    panel.loc[liability_derivation_mask, "liabilities"] = derived_liabilities.loc[
        liability_derivation_mask
    ]
    panel["liabilities_derivation_applied"] = liability_derivation_mask
    panel["liabilities_derivation_source"] = np.where(
        liability_derivation_mask,
        "exact_liabilities_and_equity_minus_stockholders_equity",
        "direct_liabilities_or_missing",
    )
    for field_name in FLOW_FIELDS:
        cumulative_name = f"{field_name}_cum_value"
        if cumulative_name not in panel.columns:
            panel[cumulative_name] = np.nan
    panel["asof_quarter"] = "companyfacts_exact_acceptance"
    panel["source"] = "companyfacts_exact_acceptance"
    output = recompute_fund_panel_derived_columns(
        panel,
        ffill_quarters=2,
        balance_ffill_quarters=4,
    )
    # The shared derivator emits these columns only when its inputs contain at
    # least one finite observation.  A one-ticker missing-neutral refresh can
    # therefore lose a column even though the frozen override contract has not
    # changed.  Preserve the canonical schema and represent absent evidence as
    # NaN; downstream consumers still fail closed on any genuine schema drift.
    for column in STABLE_CONDITIONAL_DERIVED_COLUMNS:
        if column not in output.columns:
            output[column] = np.nan
    output["fund_accepted"] = output["accepted"]
    output["fund_effective_accepted"] = output["accepted"]
    output["fund_latest_accepted_overall"] = output.groupby("cik")[
        "accepted"
    ].transform("max")
    output["fund_panel_ttm_ready"] = (
        output[list(CORE_FUNDAMENTAL_MINIMUM_FIELDS)].notna().all(axis=1).astype(float)
    )
    output["fund_join_status"] = np.where(
        output["fund_panel_ttm_ready"].eq(1.0),
        "matched_with_ttm",
        "matched_no_ttm",
    )
    return output


def apply_current_valuation_overrides(
    latest: pd.Series,
    *,
    technical_price: float,
) -> pd.Series:
    output = latest.copy()
    shares = pd.to_numeric(pd.Series([output.get("shares")]), errors="coerce").iloc[0]
    price = pd.to_numeric(pd.Series([technical_price]), errors="coerce").iloc[0]
    market_cap = shares * price if pd.notna(shares) and pd.notna(price) else np.nan
    revenues = pd.to_numeric(pd.Series([output.get("revenues_ttm")]), errors="coerce").iloc[0]
    net_income = pd.to_numeric(pd.Series([output.get("net_income_ttm")]), errors="coerce").iloc[0]
    fcf = pd.to_numeric(pd.Series([output.get("fcf_ttm")]), errors="coerce").iloc[0]
    assets = pd.to_numeric(pd.Series([output.get("assets")]), errors="coerce").iloc[0]
    liabilities = pd.to_numeric(pd.Series([output.get("liabilities")]), errors="coerce").iloc[0]
    gross_profit = pd.to_numeric(
        pd.Series([output.get("gross_profit_ttm")]), errors="coerce"
    ).iloc[0]
    op_income = pd.to_numeric(
        pd.Series([output.get("op_income_ttm")]), errors="coerce"
    ).iloc[0]
    equity = assets - liabilities if pd.notna(assets) and pd.notna(liabilities) else np.nan

    def ratio(numerator: Any, denominator: Any) -> float:
        if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0.0:
            return np.nan
        return float(numerator) / float(denominator)

    output["mktcap"] = market_cap
    output["market_cap_live"] = market_cap
    output["current_price_live"] = price
    output["valuation_px"] = price
    output["ep_ttm"] = ratio(net_income, market_cap)
    output["sp_ttm"] = ratio(revenues, market_cap)
    output["fcfy_ttm"] = ratio(fcf, market_cap)
    output["roa_proxy"] = ratio(net_income, assets)
    output["asset_turnover_ttm"] = ratio(revenues, assets)
    output["roe_proxy"] = ratio(net_income, equity)
    output["return_on_equity_effective"] = output["roe_proxy"]
    output["book_to_market_proxy"] = ratio(equity, market_cap)
    output["gross_margins"] = ratio(gross_profit, revenues)
    output["operating_margins"] = ratio(op_income, revenues)
    output["shares_effective"] = shares
    return output


def values_differ(left: Any, right: Any) -> bool:
    left_num = pd.to_numeric(pd.Series([left]), errors="coerce").iloc[0]
    right_num = pd.to_numeric(pd.Series([right]), errors="coerce").iloc[0]
    if pd.isna(left_num) and pd.isna(right_num):
        return False
    if pd.isna(left_num) != pd.isna(right_num):
        return True
    return not bool(np.isclose(float(left_num), float(right_num), rtol=1e-10, atol=1e-12))


def blocked_payload(
    output_dir: Path,
    *,
    status: str,
    blockers: list[str],
    decision_time: pd.Timestamp,
    source_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": blockers,
        "decision_time_utc": decision_time.isoformat(),
        "research_only": True,
        "fundamental_refresh_gate_resolved": False,
        "technical_context_promotion_allowed": False,
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "model_scoring_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "backtest_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": False,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "source_inputs": dict(source_inputs or {}),
    }
    write_json(output_dir / "manifest.json", payload)
    return payload


def build(args: argparse.Namespace, *, observed_at_utc: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    technical_path = repo_path(args.technical_manifest)
    event_path = repo_path(args.event_manifest)
    companyfacts_path = repo_path(args.companyfacts_zip)
    sec_index_path = repo_path(args.sec_index)
    universe_snapshot_raw = str(
        getattr(args, "universe_snapshot", "") or ""
    ).strip()
    universe_snapshot_path = (
        repo_path(universe_snapshot_raw) if universe_snapshot_raw else None
    )
    output_dir = repo_path(args.output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    decision_time = utc_timestamp(
        observed_at_utc
        or getattr(args, "decision_time_utc", "")
        or datetime.now(timezone.utc).isoformat()
    )
    required_paths = [technical_path, event_path, companyfacts_path, sec_index_path]
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        return blocked_payload(
            output_dir,
            status="BLOCKED_B002_FUNDAMENTAL_INPUT_MISSING",
            blockers=[f"required_input_missing:{path}" for path in missing],
            decision_time=decision_time,
        )

    technical = read_json(technical_path)
    event = read_json(event_path)
    source_inputs: dict[str, Any] = {
        "technical_manifest": fingerprint(technical_path),
        "event_manifest": fingerprint(event_path),
        "companyfacts_zip": fingerprint(companyfacts_path),
        "sec_submissions_index": fingerprint(sec_index_path),
    }
    if universe_snapshot_path is not None:
        universe_snapshot_input = fingerprint(universe_snapshot_path)
        expected_universe_sha = str(
            getattr(args, "expected_universe_snapshot_sha256", "") or ""
        ).strip().lower()
        universe_snapshot_input["expected_sha256"] = expected_universe_sha
        universe_snapshot_input["hash_matches"] = bool(
            universe_snapshot_input.get("exists")
            and expected_universe_sha
            and universe_snapshot_input.get("sha256") == expected_universe_sha
        )
        source_inputs["universe_snapshot"] = universe_snapshot_input
    blockers: list[str] = []
    if technical.get("status") != "TECHNICAL_PARITY_READY_MACRO_FUNDAMENTAL_BLOCKED":
        blockers.append("technical_status_not_ready")
    if event.get("status") != "READY_8K_FROZEN_SCHEMA_NOOP_SIDECAR":
        blockers.append("event_status_not_ready")
    safety_checks = {
        "technical_no_ranking": technical.get("decision_ranking_allowed") is False,
        "technical_no_network": technical.get("network_requests_executed") == 0,
        "technical_no_mutation": technical.get("source_inputs_mutated") is False,
        "technical_no_fullrun": technical.get("fullrun_executed") is False,
        "event_gate_resolved": event.get("event_actual_refresh_gate_resolved") is True,
        "event_no_network": event.get("network_requests_executed") == 0,
        "event_no_mutation": event.get("source_inputs_mutated") is False,
        "event_no_fullrun": event.get("fullrun_executed") is False,
    }
    blockers.extend(
        f"upstream_safety_check:{name}"
        for name, passed in safety_checks.items()
        if not passed
    )

    try:
        delta_audit_path, delta_audit_input = verify_manifest_file(
            technical_path, technical, "outputs", "delta_ticker_audit"
        )
        delta_latest_path, delta_latest_input = verify_manifest_file(
            technical_path, technical, "outputs", "delta_latest_technical_features"
        )
        ranked_path, ranked_input = verify_manifest_file(
            technical_path, technical, "source_inputs", "ranked_universe"
        )
        event_audit_path, event_audit_input = verify_manifest_file(
            event_path, event, "outputs", "event_actual_audit"
        )
    except ValueError as exc:
        blockers.append(f"manifest_contract:{exc}")
        return blocked_payload(
            output_dir,
            status="BLOCKED_B002_FUNDAMENTAL_MANIFEST_CONTRACT",
            blockers=blockers,
            decision_time=decision_time,
            source_inputs=source_inputs,
        )
    source_inputs.update(
        {
            "delta_ticker_audit": delta_audit_input,
            "delta_latest_technical_features": delta_latest_input,
            "ranked_universe": ranked_input,
            "event_actual_audit": event_audit_input,
        }
    )
    for name, audit in source_inputs.items():
        if isinstance(audit, Mapping) and "hash_matches" in audit:
            if audit.get("hash_matches") is not True:
                blockers.append(f"input_hash_mismatch:{name}")

    model_meta_raw = str(getattr(args, "model_meta", "") or "").strip()
    if model_meta_raw:
        model_meta_path = repo_path(model_meta_raw)
    else:
        model_meta_path = Path(
            str(((event.get("source_inputs") or {}).get("model_meta") or {}).get("path") or "")
        )
    if not model_meta_path.is_file():
        blockers.append(f"model_meta_missing:{model_meta_path}")
        model_features: list[str] = []
    else:
        source_inputs["model_meta"] = fingerprint(model_meta_path)
        model_features = [
            str(value) for value in (read_json(model_meta_path).get("model_features") or [])
        ]
        if not model_features:
            blockers.append("model_feature_schema_empty")

    if blockers:
        return blocked_payload(
            output_dir,
            status="BLOCKED_B002_FUNDAMENTAL_INPUT_CONTRACT",
            blockers=blockers,
            decision_time=decision_time,
            source_inputs=source_inputs,
        )

    delta_audit = pd.read_csv(delta_audit_path, low_memory=False)
    delta_latest = pd.read_csv(delta_latest_path, low_memory=False)
    ranked = pd.read_csv(ranked_path, low_memory=False)
    event_audit = pd.read_csv(event_audit_path, low_memory=False)
    universe_snapshot = (
        pd.read_csv(universe_snapshot_path, low_memory=False)
        if universe_snapshot_path is not None
        and source_inputs.get("universe_snapshot", {}).get("hash_matches") is True
        else pd.DataFrame()
    )
    for frame in (delta_audit, delta_latest, ranked, event_audit):
        frame["ticker"] = frame["ticker"].map(clean_ticker)
    if not universe_snapshot.empty:
        universe_snapshot["ticker"] = universe_snapshot["ticker"].map(clean_ticker)
        if universe_snapshot["ticker"].duplicated().any():
            blockers.append("universe_snapshot_duplicate_tickers")
    statement_targets = delta_audit[
        delta_audit["fundamental_recompute_required"].map(boolish)
    ].copy()
    expected_statement_tickers = split_tickers(args.expected_statement_tickers)
    actual_statement_tickers = set(statement_targets["ticker"])
    try:
        partial_core_missing_neutral = parse_partial_core_missing_neutral(
            getattr(args, "expected_partial_core_missing_neutral", None)
        )
    except ValueError as exc:
        blockers.append(f"partial_core_missing_neutral_contract:{exc}")
        partial_core_missing_neutral = {}
    if not set(partial_core_missing_neutral).issubset(expected_statement_tickers):
        blockers.append("partial_core_missing_neutral_ticker_outside_statement_set")
    if actual_statement_tickers != expected_statement_tickers:
        blockers.append(
            "statement_target_set:"
            + ",".join(sorted(actual_statement_tickers))
            + "!="
            + ",".join(sorted(expected_statement_tickers))
        )
    if statement_targets.empty:
        blockers.append("no_statement_targets")
    if statement_targets["ticker"].duplicated().any():
        blockers.append("duplicate_statement_target_ticker")
    if set(delta_latest["ticker"]) != set(delta_audit["ticker"]):
        blockers.append("delta_latest_audit_ticker_set_mismatch")
    event_tickers = set(event_audit["ticker"])
    expected_event_tickers = set(
        delta_audit.loc[
            delta_audit["event_actual_recompute_required"].map(boolish), "ticker"
        ]
    )
    if not expected_event_tickers.issubset(event_tickers):
        blockers.append(
            "event_gate_tickers_missing:"
            + ",".join(sorted(expected_event_tickers - event_tickers))
        )
    valuation_date = clean_date(technical.get("valuation_price_cutoff_date"))
    if not valuation_date or valuation_date != clean_date(event.get("valuation_price_cutoff_date")):
        blockers.append("valuation_date_mismatch")
    if blockers:
        return blocked_payload(
            output_dir,
            status="BLOCKED_B002_FUNDAMENTAL_TARGET_CONTRACT",
            blockers=blockers,
            decision_time=decision_time,
            source_inputs=source_inputs,
        )

    sec_index = pd.read_parquet(sec_index_path)
    exact_frames: list[pd.DataFrame] = []
    selected_frames: list[pd.DataFrame] = []
    panel_frames: list[pd.DataFrame] = []
    override_rows: list[pd.Series] = []
    delta_rows: list[dict[str, Any]] = []
    ticker_audit_rows: list[dict[str, Any]] = []
    resolved_fundamental_tickers: set[str] = set()
    allow_empty_expected_accession_neutral = bool(
        getattr(args, "allow_empty_expected_accession_neutral", False)
    )
    declared_no_frozen_reference_tickers = {
        clean_ticker(ticker)
        for ticker in (
            (technical.get("delta_eligibility") or {}).get(
                "no_frozen_reference_tickers"
            )
            or []
        )
    }
    source_hash_json = json.dumps(
        {
            "companyfacts_zip_sha256": source_inputs["companyfacts_zip"]["sha256"],
            "sec_submissions_index_sha256": source_inputs["sec_submissions_index"]["sha256"],
        },
        sort_keys=True,
    )
    with zipfile.ZipFile(companyfacts_path) as zf:
        for target in statement_targets.itertuples(index=False):
            ticker = clean_ticker(getattr(target, "ticker"))
            frozen_rows = ranked[ranked["ticker"].eq(ticker)]
            technical_rows = delta_latest[delta_latest["ticker"].eq(ticker)]
            ticker_blockers: list[str] = []
            current_only_flags = bool(
                not boolish(getattr(target, "frozen_reference_available", True))
                and not boolish(getattr(target, "parity_applicable", True))
            )
            current_only_declared = ticker in declared_no_frozen_reference_tickers
            current_only = current_only_flags and current_only_declared
            if current_only_flags != current_only_declared:
                ticker_blockers.append("current_only_declaration_mismatch")
            identity_source = ""
            reference_row = pd.Series(np.nan, index=ranked.columns, dtype=object)
            if len(frozen_rows) == 1:
                reference_row = frozen_rows.iloc[0].copy()
                identity_source = "frozen_ranked_context"
            elif len(frozen_rows) == 0 and current_only:
                identity_rows = universe_snapshot[
                    universe_snapshot.get(
                        "ticker", pd.Series(dtype=str)
                    ).eq(ticker)
                ]
                if len(identity_rows) != 1:
                    ticker_blockers.append(
                        f"universe_identity_row_count:{len(identity_rows)}"
                    )
                else:
                    identity = identity_rows.iloc[0]
                    if "is_equity_issuer" in identity.index and not boolish(
                        identity.get("is_equity_issuer")
                    ):
                        ticker_blockers.append("universe_identity_not_equity")
                    for column in (
                        "ticker",
                        "cik",
                        "cik10",
                        "name",
                        "company_name",
                        "exchange",
                        "sector",
                        "industry",
                        "sub_industry",
                        "universe_source",
                        "cik_mapping_status",
                        "is_equity_issuer",
                    ):
                        if column in identity.index:
                            reference_row[column] = identity.get(column)
                    identity_source = "universe_snapshot_identity_only"
            else:
                ticker_blockers.append(f"frozen_context_row_count:{len(frozen_rows)}")
            cik10 = clean_cik(
                reference_row.get("cik10")
                if pd.notna(reference_row.get("cik10"))
                else reference_row.get("cik")
            )
            if current_only and identity_source != "universe_snapshot_identity_only":
                ticker_blockers.append("current_only_identity_not_verified")
            baseline_feature_date = clean_date(
                getattr(target, "frozen_feature_date", "")
            )
            baseline_feature_date_source = (
                "frozen_feature_date" if baseline_feature_date else ""
            )
            if not baseline_feature_date:
                baseline_feature_date = clean_date(
                    getattr(target, "sec_baseline_feature_date", "")
                )
                if baseline_feature_date:
                    baseline_feature_date_source = "sec_baseline_feature_date"
            if not baseline_feature_date:
                ticker_blockers.append("missing_frozen_or_sec_baseline_feature_date")
            if len(technical_rows) != 1:
                ticker_blockers.append(f"technical_delta_row_count:{len(technical_rows)}")
            if not cik10:
                ticker_blockers.append("missing_cik")
            statement_index, index_failures = prepare_statement_index(sec_index, cik10)
            ticker_blockers.extend(index_failures)
            (
                expected_index,
                statement_window_count,
                selection_failures,
            ) = select_latest_new_statement(
                statement_index,
                frozen_feature_date=baseline_feature_date,
                decision_time=decision_time,
            )
            ticker_blockers.extend(selection_failures)
            expected_accession = (
                clean_accession(expected_index.iloc[0]["accession_number"])
                if len(expected_index) == 1
                else ""
            )
            if len(expected_index) != 1:
                ticker_blockers.append(
                    f"expected_accession_index_count:{expected_accession}:{len(expected_index)}"
                )
            declared_statement_count = pd.to_numeric(
                pd.Series(
                    [getattr(target, "new_statement_filing_count", np.nan)]
                ),
                errors="coerce",
            ).iloc[0]
            if pd.notna(declared_statement_count) and statement_window_count != int(
                declared_statement_count
            ):
                ticker_blockers.append(
                    "statement_window_count:"
                    f"{statement_window_count}!={int(declared_statement_count)}"
                )
            try:
                member = companyfacts_member_name(zf, cik10)
                payload = json.loads(zf.read(member))
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                ticker_blockers.append(f"companyfacts_member:{exc}")
                payload = {}
                member = ""
            expected_accession_raw_fact_count = accession_fact_count(
                payload, expected_accession
            )
            missing_neutral_override = bool(
                allow_empty_expected_accession_neutral
                and len(expected_index) == 1
                and expected_accession
                and expected_accession_raw_fact_count == 0
            )
            exact, counters = extract_exact_companyfacts_records(
                payload,
                cik10=cik10,
                ticker=ticker,
                statement_index=statement_index,
                decision_time=decision_time,
            )
            selected = select_accession_field_records(exact)
            panel = build_exact_fundamental_panel(selected)
            if exact.empty:
                ticker_blockers.append("exact_companyfacts_records_empty")
            if selected.empty:
                ticker_blockers.append("selected_companyfacts_records_empty")
            if panel.empty:
                ticker_blockers.append("fundamental_panel_empty")
            expected_selected = selected[
                selected.get("accession_number", pd.Series(dtype=str)).eq(expected_accession)
            ]
            if expected_selected.empty and not missing_neutral_override:
                ticker_blockers.append("expected_accession_has_no_selected_components")
            latest = pd.Series(dtype=object)
            core_coverage = 0
            missing_core_fields: set[str] = set()
            partial_core_missing_neutral_applied = False
            latest_accession = ""
            latest_accepted = pd.NaT
            latest_period = pd.NaT
            technical_price = np.nan
            liabilities_derivation_applied = False
            liabilities_derivation_source = ""
            if not panel.empty:
                panel = panel.copy()
                panel["ticker"] = ticker
                panel["cik10"] = cik10
                panel["source_hashes"] = source_hash_json
                panel["exact_acceptance"] = True
                panel["pit_universe_label_clean"] = False
                panel["pit_caveats"] = (
                    "current identity snapshot; missing neutral; filed date not used"
                )
                expected_panel = panel[
                    panel["accession_number"].astype(str).eq(expected_accession)
                ]
                if len(expected_panel) != 1:
                    latest = panel.sort_values(["period", "accepted"]).iloc[-1].copy()
                    if missing_neutral_override:
                        latest.loc[:] = np.nan
                        expected_index_row = expected_index.iloc[0]
                        latest["period"] = expected_index_row["period_exact"]
                        latest["accepted"] = expected_index_row["accepted_exact"]
                        latest["accession_number"] = expected_accession
                        latest["form"] = expected_index_row["form_type"]
                        latest["source"] = (
                            "companyfacts_expected_accession_missing_neutral"
                        )
                        latest["asof_quarter"] = (
                            "companyfacts_expected_accession_missing_neutral"
                        )
                        latest["fund_join_status"] = (
                            "missing_neutral_exact_accession"
                        )
                    else:
                        ticker_blockers.append(
                            f"expected_accession_panel_row_count:{len(expected_panel)}"
                        )
                else:
                    latest = expected_panel.iloc[0].copy()
                latest_accession = clean_accession(latest.get("accession_number"))
                latest_accepted = pd.to_datetime(
                    latest.get("accepted"), errors="coerce", utc=True
                )
                latest_period = pd.to_datetime(latest.get("period"), errors="coerce")
                if pd.isna(latest_accepted) or latest_accepted > decision_time:
                    ticker_blockers.append("latest_panel_available_after_decision")
                core_coverage = int(
                    latest[list(CORE_FUNDAMENTAL_MINIMUM_FIELDS)].notna().sum()
                )
                missing_core_fields = {
                    field
                    for field in CORE_FUNDAMENTAL_MINIMUM_FIELDS
                    if pd.isna(latest.get(field))
                }
                declared_partial_fields = partial_core_missing_neutral.get(ticker)
                partial_core_missing_neutral_applied = bool(
                    declared_partial_fields
                    and missing_core_fields == declared_partial_fields
                    and len(missing_core_fields) == 1
                    and core_coverage == len(CORE_FUNDAMENTAL_MINIMUM_FIELDS) - 1
                    and not expected_selected.empty
                    and expected_accession_raw_fact_count > 0
                )
                if (
                    declared_partial_fields is not None
                    and not partial_core_missing_neutral_applied
                ):
                    ticker_blockers.append(
                        "partial_core_missing_neutral_mismatch:expected="
                        + ",".join(sorted(declared_partial_fields))
                        + ":actual="
                        + ",".join(sorted(missing_core_fields))
                    )
                liabilities_derivation_applied = boolish(
                    latest.get("liabilities_derivation_applied", False)
                )
                liabilities_derivation_source = str(
                    latest.get("liabilities_derivation_source", "") or ""
                )
                if (
                    not missing_neutral_override
                    and not partial_core_missing_neutral_applied
                    and core_coverage != len(CORE_FUNDAMENTAL_MINIMUM_FIELDS)
                ):
                    ticker_blockers.append(
                        f"core_component_coverage:{core_coverage}/"
                        f"{len(CORE_FUNDAMENTAL_MINIMUM_FIELDS)}"
                    )
                exact_coverage = float(
                    selected.get("exact_acceptance", pd.Series(dtype=bool))
                    .map(boolish)
                    .mean()
                )
                if not np.isclose(exact_coverage, 1.0):
                    ticker_blockers.append(f"exact_acceptance_coverage:{exact_coverage}")
                future_used = int(
                    (
                        pd.to_datetime(selected["available_from"], errors="coerce", utc=True)
                        > decision_time
                    ).sum()
                )
                if future_used:
                    ticker_blockers.append(f"future_selected_rows:{future_used}")
                technical_price = pd.to_numeric(
                    technical_rows.get("technical_px", pd.Series(dtype=float)),
                    errors="coerce",
                ).iloc[0]
                frozen = reference_row
                latest = apply_current_valuation_overrides(
                    latest, technical_price=float(technical_price)
                )
                if missing_neutral_override:
                    frozen_px = pd.to_numeric(
                        pd.Series([frozen.get("px")]), errors="coerce"
                    ).iloc[0]
                    frozen_mktcap = pd.to_numeric(
                        pd.Series([frozen.get("mktcap")]), errors="coerce"
                    ).iloc[0]
                    frozen_price_unit_factor = pd.to_numeric(
                        pd.Series(
                            [
                                getattr(
                                    target,
                                    "frozen_price_adjustment_factor",
                                    1.0,
                                )
                            ]
                        ),
                        errors="coerce",
                    ).iloc[0]
                    current_market_cap = (
                        float(frozen_mktcap)
                        * float(technical_price)
                        * float(frozen_price_unit_factor)
                        / float(frozen_px)
                        if pd.notna(frozen_mktcap)
                        and pd.notna(frozen_px)
                        and float(frozen_px) != 0.0
                        and pd.notna(technical_price)
                        and pd.notna(frozen_price_unit_factor)
                        else np.nan
                    )
                    latest["mktcap"] = current_market_cap
                    latest["market_cap_live"] = current_market_cap
                latest["ticker"] = ticker
                latest["cik10"] = cik10
                latest["accession_number"] = latest_accession
                latest["accepted_at"] = latest_accepted
                latest["available_from"] = latest_accepted
                latest["exact_acceptance"] = True
                latest["component_coverage"] = core_coverage
                latest["source_hashes"] = source_hash_json
                latest["pit_universe_label_clean"] = False
                latest["pit_caveats"] = (
                    "current identity snapshot; missing neutral; filed date not used"
                )
                latest["valuation_price_cutoff_date"] = valuation_date
                latest["missing_evidence_policy"] = "neutral"
                latest["filed_fallback_used"] = False
                latest["used_forward_return"] = False
                if missing_neutral_override:
                    latest["accepted"] = latest_accepted
                    latest["fund_accepted"] = latest_accepted
                    latest["fund_effective_accepted"] = latest_accepted
                    latest["fund_latest_accepted_overall"] = latest_accepted
                latest = latest.drop(
                    labels=[
                        *AUXILIARY_BALANCE_FIELDS,
                        "liabilities_derivation_applied",
                        "liabilities_derivation_source",
                    ],
                    errors="ignore",
                )
                override_rows.append(latest)

                candidate_columns = sorted(
                    {
                        *[column for column in latest.index if column in frozen.index],
                        *[column for column in latest.index if column in model_features],
                        *VALUATION_OVERRIDE_COLUMNS,
                    }
                    - {
                        "ticker",
                        "cik",
                        "cik10",
                        "period",
                        "accepted",
                        "accepted_at",
                        "available_from",
                    }
                )
                for column in candidate_columns:
                    refreshed_value = latest.get(column)
                    frozen_value = frozen.get(column, np.nan)
                    delta_rows.append(
                        {
                            "ticker": ticker,
                            "column": column,
                            "model_feature": column in model_features,
                            "frozen_value": frozen_value,
                            "refreshed_value": refreshed_value,
                            "changed": values_differ(frozen_value, refreshed_value),
                            "missing_is_neutral": pd.isna(refreshed_value),
                        }
                    )
            if not ticker_blockers:
                resolved_fundamental_tickers.add(ticker)
            ticker_audit_rows.append(
                {
                    "ticker": ticker,
                    "cik10": cik10,
                    "identity_source": identity_source,
                    "current_only_no_frozen_reference": current_only,
                    "baseline_feature_date": baseline_feature_date,
                    "baseline_feature_date_source": baseline_feature_date_source,
                    "companyfacts_member": member,
                    "technical_latest_new_form": getattr(
                        target, "latest_new_form", ""
                    ),
                    "technical_latest_new_accession_number": clean_accession(
                        getattr(target, "latest_new_accession_number", "")
                    ),
                    "statement_window_count": statement_window_count,
                    "expected_accession_companyfacts_fact_count": (
                        expected_accession_raw_fact_count
                    ),
                    "missing_neutral_override_applied": missing_neutral_override,
                    "partial_core_missing_neutral_applied": (
                        partial_core_missing_neutral_applied
                    ),
                    "partial_core_missing_fields": "|".join(
                        sorted(missing_core_fields)
                    ),
                    "expected_accession_number": expected_accession,
                    "latest_accession_number": latest_accession,
                    "latest_period": clean_date(latest_period),
                    "latest_accepted_at": (
                        "" if pd.isna(latest_accepted) else latest_accepted.isoformat()
                    ),
                    "technical_price": technical_price,
                    "core_component_coverage": core_coverage,
                    "liabilities_derivation_applied": liabilities_derivation_applied,
                    "liabilities_derivation_source": liabilities_derivation_source,
                    "required_core_component_count": len(CORE_FUNDAMENTAL_MINIMUM_FIELDS),
                    "exact_joined_row_count": int(len(exact)),
                    "selected_row_count": int(len(selected)),
                    "panel_row_count": int(len(panel)),
                    **counters,
                    "period_filter_policy": "fact_end_equals_sec_period_of_report",
                    "filed_availability_fallback_allowed": False,
                    "missing_evidence_policy": "neutral",
                    "fundamental_refresh_gate_resolved": not ticker_blockers,
                    "ticker_blockers": "|".join(ticker_blockers),
                }
            )
            blockers.extend(f"{ticker}:{item}" for item in ticker_blockers)
            if not exact.empty:
                exact_frames.append(exact)
            if not selected.empty:
                selected_frames.append(selected)
            if not panel.empty:
                panel_frames.append(panel)

    exact_records = (
        pd.concat(exact_frames, ignore_index=True, sort=False)
        if exact_frames
        else pd.DataFrame()
    )
    selected_records = (
        pd.concat(selected_frames, ignore_index=True, sort=False)
        if selected_frames
        else pd.DataFrame()
    )
    panels = (
        pd.concat(panel_frames, ignore_index=True, sort=False)
        if panel_frames
        else pd.DataFrame()
    )
    overrides = pd.DataFrame(override_rows)
    value_delta = pd.DataFrame(delta_rows)
    ticker_audit = pd.DataFrame(ticker_audit_rows)

    promotion_rows: list[dict[str, Any]] = []
    blocked_delta = delta_audit[
        ~delta_audit["composite_technical_eligible"].map(boolish)
    ].copy()
    for row in blocked_delta.itertuples(index=False):
        ticker = clean_ticker(getattr(row, "ticker"))
        parity_resolved = boolish(getattr(row, "ticker_parity_pass", False))
        event_required = boolish(getattr(row, "event_actual_recompute_required", False))
        fundamental_required = boolish(
            getattr(row, "fundamental_recompute_required", False)
        )
        event_resolved = (not event_required) or ticker in event_tickers
        fundamental_resolved = (
            not fundamental_required
        ) or ticker in resolved_fundamental_tickers
        promotion_allowed = parity_resolved and event_resolved and fundamental_resolved
        promotion_rows.append(
            {
                "ticker": ticker,
                "technical_parity_resolved": parity_resolved,
                "event_gate_required": event_required,
                "event_gate_resolved": event_resolved,
                "fundamental_gate_required": fundamental_required,
                "fundamental_gate_resolved": fundamental_resolved,
                "technical_context_promotion_allowed": promotion_allowed,
                "decision_ranking_allowed": False,
            }
        )
    promotion_audit = pd.DataFrame(promotion_rows)
    promoted_tickers = set(
        promotion_audit.loc[
            promotion_audit["technical_context_promotion_allowed"].map(boolish),
            "ticker",
        ]
    )
    expected_promotion_tickers = split_tickers(args.expected_promotion_tickers)
    if promoted_tickers != expected_promotion_tickers:
        blockers.append(
            "promotion_ticker_set:"
            + ",".join(sorted(promoted_tickers))
            + "!="
            + ",".join(sorted(expected_promotion_tickers))
        )

    source_hashes_after = {
        "companyfacts_zip": sha256_file(companyfacts_path),
        "sec_submissions_index": sha256_file(sec_index_path),
        "ranked_universe": sha256_file(ranked_path),
        "delta_ticker_audit": sha256_file(delta_audit_path),
        "delta_latest_technical_features": sha256_file(delta_latest_path),
        "event_actual_audit": sha256_file(event_audit_path),
    }
    if universe_snapshot_path is not None:
        source_hashes_after["universe_snapshot"] = sha256_file(
            universe_snapshot_path
        )
    source_files_unchanged = all(
        source_hashes_after[name] == source_inputs[name]["sha256"]
        for name in source_hashes_after
    )
    if not source_files_unchanged:
        blockers.append("verified_source_file_mutated")

    frames = {
        "exact_joined_companyfacts_records": (exact_records, "parquet"),
        "selected_fundamental_records": (selected_records, "parquet"),
        "fundamental_panel": (panels, "parquet"),
        "latest_fundamental_overrides": (overrides, "csv"),
        "fundamental_value_delta": (value_delta, "csv"),
        "ticker_fundamental_audit": (ticker_audit, "csv"),
        "promotion_audit": (promotion_audit, "csv"),
    }
    outputs: dict[str, Any] = {}
    for name, (frame, suffix) in frames.items():
        path = output_dir / f"{name}.{suffix}"
        if suffix == "parquet":
            frame.to_parquet(path, index=False)
        else:
            frame.to_csv(path, index=False)
        outputs[name] = {**fingerprint(path), "row_count": int(len(frame))}

    base_context_count = int(
        (technical.get("delta_eligibility") or {}).get("composite_context_ticker_count")
        or 0
    )
    post_gate_context_count = base_context_count + len(promoted_tickers)
    status = (
        "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE"
        if not blockers
        else "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA"
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blockers": blockers,
        "decision_time_utc": decision_time.isoformat(),
        "valuation_price_cutoff_date": valuation_date,
        "research_only": True,
        "current_decision_only": True,
        "fundamental_refresh_gate_resolved": not blockers,
        "technical_context_promotion_allowed": not blockers,
        "promotion_action": "nonranking_context_only",
        "decision_feature_complete": False,
        "decision_ranking_allowed": False,
        "model_scoring_allowed": False,
        "target_book_generation_allowed": False,
        "historical_backtest_acceptance_allowed": False,
        "fullrun_executed": False,
        "selector_executed": False,
        "model_scoring_executed": False,
        "backtest_executed": False,
        "network_requests_executed": 0,
        "source_inputs_mutated": not source_files_unchanged,
        "target_books_mutated": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
        "availability_contract": {
            "join_key": "accession_number",
            "available_from": "sec_submissions_index.accepted_at",
            "filed_fallback_allowed": False,
            "period_match": "companyfacts.end == sec_index.period_of_report",
            "amendment_policy": "latest exact accepted accession at decision time",
            "missing_evidence_policy": "neutral",
            "empty_expected_accession_policy": (
                "neutral_override_when_exact_index_count_1_and_raw_fact_count_0"
                if allow_empty_expected_accession_neutral
                else "fail_closed"
            ),
            "partial_core_missing_policy": (
                "explicit_exact_one_of_five_missing_neutral"
                if partial_core_missing_neutral
                else "fail_closed"
            ),
            "partial_core_missing_neutral_contract": {
                ticker: sorted(fields)
                for ticker, fields in sorted(partial_core_missing_neutral.items())
            },
            "pit_universe_label_clean": False,
        },
        "coverage": {
            "statement_target_count": int(len(statement_targets)),
            "resolved_statement_ticker_count": int(len(resolved_fundamental_tickers)),
            "exact_joined_record_count": int(len(exact_records)),
            "selected_record_count": int(len(selected_records)),
            "fundamental_panel_row_count": int(len(panels)),
            "latest_override_row_count": int(len(overrides)),
            "future_selected_row_count": int(
                (
                    pd.to_datetime(
                        selected_records.get("available_from"), errors="coerce", utc=True
                    )
                    > decision_time
                ).sum()
                if not selected_records.empty
                else 0
            ),
            "filed_fallback_used_count": int(
                ticker_audit.get(
                    "filed_fallback_used_count", pd.Series(dtype=int)
                ).sum()
            ),
            "missing_neutral_override_count": int(
                ticker_audit.get(
                    "missing_neutral_override_applied", pd.Series(dtype=bool)
                ).map(boolish).sum()
            ),
            "partial_core_missing_neutral_count": int(
                ticker_audit.get(
                    "partial_core_missing_neutral_applied", pd.Series(dtype=bool)
                )
                .map(boolish)
                .sum()
            ),
            "current_only_identity_ticker_count": int(
                ticker_audit.get(
                    "current_only_no_frozen_reference", pd.Series(dtype=bool)
                ).map(boolish).sum()
            ),
            "liabilities_derivation_ticker_count": int(
                ticker_audit.get(
                    "liabilities_derivation_applied", pd.Series(dtype=bool)
                ).map(boolish).sum()
            ),
            "changed_value_count": int(
                value_delta.get("changed", pd.Series(dtype=bool)).map(boolish).sum()
            ),
            "changed_model_feature_count": int(
                (
                    value_delta.get("changed", pd.Series(dtype=bool)).map(boolish)
                    & value_delta.get("model_feature", pd.Series(dtype=bool)).map(boolish)
                ).sum()
            ),
        },
        "promotion": {
            "base_context_ticker_count": base_context_count,
            "newly_promoted_ticker_count": int(len(promoted_tickers)),
            "newly_promoted_tickers": sorted(promoted_tickers),
            "post_gate_context_ticker_count": post_gate_context_count,
            "expected_post_gate_context_ticker_count": int(
                args.expected_post_gate_context_count
            ),
        },
        "source_inputs": source_inputs,
        "source_immutability": {
            "verified_source_files_unchanged": source_files_unchanged,
        },
        "outputs": outputs,
        "performance": {"elapsed_seconds": time.perf_counter() - started},
        "recommended_next_step": (
            "assemble the frozen 238-column non-ranking context with "
            f"{len(promoted_tickers)} resolved SEC-gated tickers and "
            f"{len(overrides)} exact statement override row(s); checkpoint before the "
            "next bounded price batch and do not score or rank"
        ),
        "code": {"git_head": git_head(), "builder": fingerprint(Path(__file__))},
    }
    if post_gate_context_count != int(args.expected_post_gate_context_count):
        payload["blockers"].append(
            f"post_gate_context_count:{post_gate_context_count}!="
            f"{int(args.expected_post_gate_context_count)}"
        )
        payload["status"] = "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA"
        payload["fundamental_refresh_gate_resolved"] = False
        payload["technical_context_promotion_allowed"] = False
    write_json(output_dir / "manifest.json", payload)
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    return payload


def render_report(payload: Mapping[str, Any]) -> str:
    coverage = payload.get("coverage") or {}
    promotion = payload.get("promotion") or {}
    lines = [
        "# Run287 B002 exact-accepted fundamental delta",
        "",
        f"- status: `{payload.get('status')}`",
        f"- statement targets / resolved: `{coverage.get('statement_target_count')}` / "
        f"`{coverage.get('resolved_statement_ticker_count')}`",
        f"- exact selected facts / panel rows: `{coverage.get('selected_record_count')}` / "
        f"`{coverage.get('fundamental_panel_row_count')}`",
        f"- future selected rows / filed fallbacks: "
        f"`{coverage.get('future_selected_row_count')}` / "
        f"`{coverage.get('filed_fallback_used_count')}`",
        f"- context promotion: `{promotion.get('base_context_ticker_count')}` -> "
        f"`{promotion.get('post_gate_context_ticker_count')}` "
        f"({', '.join(promotion.get('newly_promoted_tickers') or [])})",
        "",
        "## Decision",
        "",
        "The output may be merged only into the bounded non-ranking feature context.",
        "It is not a new SEC alpha, a selector result, or a historical backtest input.",
        "Missing facts remain neutral and the current ticker/CIK map remains a non-PIT",
        "identity snapshot.",
        "",
    ]
    if payload.get("blockers"):
        lines.extend(
            ["## Blockers", "", *[f"- `{item}`" for item in payload["blockers"]], ""]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--technical-manifest", default=DEFAULT_TECHNICAL)
    parser.add_argument("--event-manifest", default=DEFAULT_EVENT)
    parser.add_argument("--companyfacts-zip", default=DEFAULT_COMPANYFACTS)
    parser.add_argument("--sec-index", default=DEFAULT_SEC_INDEX)
    parser.add_argument("--model-meta", default="")
    parser.add_argument(
        "--universe-snapshot",
        default="",
        help=(
            "Pinned current universe identity snapshot, required only for "
            "statement targets with no frozen ranked reference."
        ),
    )
    parser.add_argument(
        "--expected-universe-snapshot-sha256",
        default="",
        help="Required exact SHA-256 when --universe-snapshot is supplied.",
    )
    parser.add_argument("--expected-statement-tickers", default="MU")
    parser.add_argument("--expected-promotion-tickers", default="MRVL,MU")
    parser.add_argument("--expected-post-gate-context-count", type=int, default=80)
    parser.add_argument(
        "--allow-empty-expected-accession-neutral",
        action="store_true",
        help=(
            "Allow a missing-neutral override only when the exact expected SEC "
            "accession has zero raw Companyfacts facts."
        ),
    )
    parser.add_argument(
        "--expected-partial-core-missing-neutral",
        action="append",
        default=[],
        help=(
            "Repeat as TICKER=core_field; permits exactly one declared missing "
            "core field when the exact accession otherwise supplies four of five."
        ),
    )
    parser.add_argument("--decision-time-utc", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    payload = build(parse_args())
    print(json.dumps(payload, indent=2, sort_keys=True, default=json_default))
    return 0 if payload.get("status") in {
        "READY_B002_EXACT_FUNDAMENTAL_PROMOTION_GATE",
        "BLOCKED_B002_EXACT_FUNDAMENTAL_DELTA",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
