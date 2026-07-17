#!/usr/bin/env python3
"""Build an exact-accepted SEC debt/cash snapshot for the current universe.

Facts are selected from one latest Companyfacts-covered statement accession
per ticker.  Availability comes only from the SEC submissions index's exact
``accepted_at`` / ``available_from`` timestamp.  Filed-date fallback is
forbidden.  Amendments are visible only after their own acceptance time.

The sidecar is research-only. Missing debt facts are missing, never zero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = "run287-exact-debt-snapshot-v2"
STATEMENT_FORMS = {
    "10-Q", "10-Q/A", "10-K", "10-K/A",
    "20-F", "20-F/A", "40-F", "40-F/A", "6-K", "6-K/A",
}
ALIASES: dict[str, tuple[str, ...]] = {
    "assets_exact": ("Assets",),
    "cash_exact": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsAndShortTermInvestments",
        "CashAndCashEquivalents",
    ),
    "long_term_debt_exact": (
        "LongTermDebtNoncurrent",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
        "NoncurrentBorrowings",
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndFinanceLeaseObligations",
    ),
    "current_debt_exact": (
        "ShortTermBorrowings",
        "ShortTermDebtCurrent",
        "DebtCurrent",
        "LongTermDebtCurrent",
        "CurrentPortionOfLongTermDebt",
        "LongTermDebtAndFinanceLeaseObligationsCurrent",
        "CurrentBorrowings",
    ),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


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
        "path": str(path),
        "exists": True,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def clean_cik(value: Any) -> str:
    text = str(value or "").split(".", maxsplit=1)[0]
    digits = "".join(character for character in text if character.isdigit())
    return digits.zfill(10)[-10:] if digits else ""


def clean_accession(value: Any) -> str:
    return str(value or "").strip()


def truthy(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def prepare_prior_snapshot(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    prior = pd.read_csv(path, low_memory=False)
    required = {
        "ticker", "cik10", "accepted_at", "exact_acceptance",
        "exact_debt_component_coverage",
    }
    if not required.issubset(prior.columns):
        return {}
    prior["ticker"] = prior["ticker"].astype(str).str.upper().str.strip()
    prior["cik10"] = prior["cik10"].map(clean_cik)
    prior["accepted_prior"] = pd.to_datetime(prior["accepted_at"], errors="coerce", utc=True)
    prior["coverage_prior"] = pd.to_numeric(
        prior["exact_debt_component_coverage"], errors="coerce"
    )
    prior = prior.loc[
        prior["ticker"].ne("")
        & prior["accepted_prior"].notna()
        & prior["exact_acceptance"].map(truthy)
        & prior["coverage_prior"].eq(1.0)
    ].copy()
    return {
        str(row["ticker"]): row.drop(labels=["accepted_prior", "coverage_prior"]).to_dict()
        for _, row in prior.sort_values("accepted_prior").drop_duplicates("ticker", keep="last").iterrows()
    }


def may_reuse_prior(
    prior_row: Mapping[str, Any] | None,
    cik10: str,
    ticker_index: pd.DataFrame,
    decision_time: pd.Timestamp,
) -> bool:
    if not prior_row or clean_cik(prior_row.get("cik10")) != cik10 or ticker_index.empty:
        return False
    prior_accepted = pd.to_datetime(prior_row.get("accepted_at"), errors="coerce", utc=True)
    if pd.isna(prior_accepted) or prior_accepted > decision_time:
        return False
    latest_index_accepted = pd.to_datetime(
        ticker_index["accepted_exact"], errors="coerce", utc=True
    ).max()
    return bool(pd.notna(latest_index_accepted) and latest_index_accepted <= prior_accepted)


def prepare_index(sec_index: pd.DataFrame, decision_time: pd.Timestamp) -> pd.DataFrame:
    required = {
        "cik10", "accession_number", "form_type", "accepted_at", "available_from", "period_of_report"
    }
    missing = required - set(sec_index.columns)
    if missing:
        raise ValueError(f"SEC index missing columns: {sorted(missing)}")
    output = sec_index.copy()
    output["cik10"] = output["cik10"].map(clean_cik)
    output["accession_number"] = output["accession_number"].map(clean_accession)
    output["form_type"] = output["form_type"].astype(str).str.upper().str.strip()
    output["accepted_exact"] = pd.to_datetime(output["accepted_at"], errors="coerce", utc=True)
    output["available_exact"] = pd.to_datetime(output["available_from"], errors="coerce", utc=True)
    output["period_exact"] = pd.to_datetime(output["period_of_report"], errors="coerce").dt.normalize()
    output = output.loc[
        output["form_type"].isin(STATEMENT_FORMS)
        & output["accepted_exact"].notna()
        & output["available_exact"].notna()
        & output["period_exact"].notna()
        & output["accession_number"].ne("")
        & output["accepted_exact"].eq(output["available_exact"])
        & output["available_exact"].le(decision_time)
    ].copy()
    conflicts = output.groupby("accession_number")[
        ["cik10", "form_type", "accepted_exact", "period_exact"]
    ].nunique(dropna=False)
    if not conflicts.empty and bool(conflicts.gt(1).any(axis=1).any()):
        raise ValueError("SEC index accession conflicts detected")
    return (
        output.sort_values(["cik10", "accepted_exact", "accession_number"])
        .drop_duplicates(["cik10", "accession_number"], keep="last")
        .reset_index(drop=True)
    )


def companyfacts_accessions(payload: Mapping[str, Any]) -> set[str]:
    accessions: set[str] = set()
    for namespace in (payload.get("facts") or {}).values():
        if not isinstance(namespace, Mapping):
            continue
        for fact in namespace.values():
            if not isinstance(fact, Mapping):
                continue
            for values in (fact.get("units") or {}).values():
                if not isinstance(values, list):
                    continue
                accessions.update(
                    clean_accession(item.get("accn"))
                    for item in values
                    if isinstance(item, Mapping) and clean_accession(item.get("accn"))
                )
    return accessions


def latest_companyfacts_statement(
    payload: Mapping[str, Any], ticker_index: pd.DataFrame
) -> pd.Series | None:
    if ticker_index.empty:
        return None
    available_accessions = companyfacts_accessions(payload)
    eligible = ticker_index[ticker_index["accession_number"].isin(available_accessions)]
    if eligible.empty:
        return None
    return eligible.sort_values(["accepted_exact", "accession_number"]).iloc[-1]


def debt_scope(field_name: str, tag: str) -> str:
    if field_name == "long_term_debt_exact":
        if "Noncurrent" in tag or tag == "NoncurrentBorrowings":
            return "noncurrent"
        return "total_or_ambiguous"
    if field_name == "current_debt_exact":
        return "current"
    return "not_debt"


def extract_accession_fields(
    payload: Mapping[str, Any], statement: pd.Series
) -> pd.DataFrame:
    facts = payload.get("facts") or {}
    accession = clean_accession(statement["accession_number"])
    period = pd.Timestamp(statement["period_exact"]).normalize()
    form = str(statement["form_type"]).upper().strip()
    rows: list[dict[str, Any]] = []
    for field_name, aliases in ALIASES.items():
        for namespace_name in ("us-gaap", "ifrs-full"):
            namespace = facts.get(namespace_name) or {}
            if not isinstance(namespace, Mapping):
                continue
            for alias_priority, alias in enumerate(aliases):
                fact = namespace.get(alias)
                if not isinstance(fact, Mapping):
                    continue
                units = fact.get("units") or {}
                if not isinstance(units, Mapping):
                    continue
                for unit, values in units.items():
                    if not isinstance(values, list):
                        continue
                    for item in values:
                        if not isinstance(item, Mapping) or clean_accession(item.get("accn")) != accession:
                            continue
                        item_form = str(item.get("form") or "").upper().strip()
                        if item_form and item_form != form:
                            continue
                        end = pd.to_datetime(item.get("end"), errors="coerce")
                        if pd.isna(end) or pd.Timestamp(end).normalize() != period:
                            continue
                        value = pd.to_numeric(pd.Series([item.get("val")]), errors="coerce").iloc[0]
                        if pd.isna(value) or not np.isfinite(float(value)) or float(value) < 0.0:
                            continue
                        rows.append(
                            {
                                "field_name": field_name,
                                "value": float(value),
                                "unit": str(unit),
                                "namespace": namespace_name,
                                "source_tag": alias,
                                "alias_priority": alias_priority,
                                "debt_scope": debt_scope(field_name, alias),
                                "filed_diagnostic": item.get("filed"),
                                "filed_used_for_availability": False,
                            }
                        )
    if not rows:
        return pd.DataFrame()
    output = pd.DataFrame(rows)
    output["unit_priority"] = np.where(output["unit"].eq("USD"), 0, 1)
    return (
        output.sort_values(["field_name", "alias_priority", "unit_priority", "source_tag"])
        .drop_duplicates("field_name", keep="first")
        .reset_index(drop=True)
    )


def build_row(
    ticker: str,
    cik10: str,
    payload: Mapping[str, Any],
    ticker_index: pd.DataFrame,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ticker": ticker,
        "cik10": cik10,
        "accession_number": "",
        "form": "",
        "period_of_report": "",
        "accepted_at": "",
        "available_from": "",
        "exact_acceptance": False,
        "filed_fallback_used": False,
        "assets_exact": np.nan,
        "cash_exact": np.nan,
        "long_term_debt_exact": np.nan,
        "current_debt_exact": np.nan,
        "total_debt_exact": np.nan,
        "net_debt_exact": np.nan,
        "exact_debt_to_assets": np.nan,
        "exact_net_debt_to_assets": np.nan,
        "exact_debt_component_coverage": 0.0,
        "debt_scope_status": "NO_COMPANYFACTS_STATEMENT",
        "unit_consistent": False,
        "source_tags": "",
    }
    statement = latest_companyfacts_statement(payload, ticker_index)
    if statement is None:
        return row
    row.update(
        {
            "accession_number": clean_accession(statement["accession_number"]),
            "form": str(statement["form_type"]),
            "period_of_report": pd.Timestamp(statement["period_exact"]).date().isoformat(),
            "accepted_at": pd.Timestamp(statement["accepted_exact"]).isoformat(),
            "available_from": pd.Timestamp(statement["available_exact"]).isoformat(),
            "exact_acceptance": True,
        }
    )
    fields = extract_accession_fields(payload, statement)
    if fields.empty:
        row["debt_scope_status"] = "STATEMENT_WITHOUT_REQUIRED_DEBT_FACTS"
        return row
    field_map = fields.set_index("field_name").to_dict("index")
    for field_name in ALIASES:
        if field_name in field_map:
            row[field_name] = float(field_map[field_name]["value"])
    row["source_tags"] = "|".join(
        f"{name}:{values['namespace']}:{values['source_tag']}:{values['unit']}"
        for name, values in sorted(field_map.items())
    )
    debt_units = {
        str(field_map[name]["unit"])
        for name in ("assets_exact", "cash_exact", "long_term_debt_exact", "current_debt_exact")
        if name in field_map
    }
    row["unit_consistent"] = len(debt_units) == 1
    long_scope = str(field_map.get("long_term_debt_exact", {}).get("debt_scope", "missing"))
    long_debt = row["long_term_debt_exact"]
    current_debt = row["current_debt_exact"]
    if pd.notna(long_debt) and long_scope == "noncurrent" and pd.notna(current_debt):
        total_debt = float(long_debt) + float(current_debt)
        scope = "NONCURRENT_PLUS_CURRENT_COMPLETE"
    elif pd.notna(long_debt) and long_scope == "total_or_ambiguous":
        total_debt = float(long_debt)
        scope = "TOTAL_OR_AMBIGUOUS_LONG_TERM_TAG"
    elif pd.notna(long_debt):
        total_debt = float(long_debt)
        scope = "NONCURRENT_ONLY_CURRENT_MISSING"
    elif pd.notna(current_debt):
        total_debt = float(current_debt)
        scope = "CURRENT_ONLY_NONCURRENT_MISSING"
    else:
        total_debt = np.nan
        scope = "DEBT_FACT_MISSING_NOT_ZERO"
    row["total_debt_exact"] = total_debt
    cash = row["cash_exact"]
    assets = row["assets_exact"]
    if bool(row["unit_consistent"]) and pd.notna(total_debt) and pd.notna(cash):
        row["net_debt_exact"] = float(total_debt) - float(cash)
    if bool(row["unit_consistent"]) and pd.notna(total_debt) and pd.notna(assets) and float(assets) > 0.0:
        row["exact_debt_to_assets"] = float(total_debt) / float(assets)
        if pd.notna(row["net_debt_exact"]):
            row["exact_net_debt_to_assets"] = float(row["net_debt_exact"]) / float(assets)
    coverage = sum(pd.notna(row[name]) for name in ("assets_exact", "cash_exact", "total_debt_exact")) / 3.0
    row["exact_debt_component_coverage"] = coverage if bool(row["unit_consistent"]) else 0.0
    row["debt_scope_status"] = scope
    return row


def build(args: argparse.Namespace) -> dict[str, Any]:
    context_path = repo_path(args.selection_context)
    zip_path = repo_path(args.companyfacts_zip)
    index_path = repo_path(args.sec_index)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prior_raw = str(getattr(args, "prior_snapshot", "") or "").strip()
    prior_path = repo_path(prior_raw) if prior_raw else None
    prior_rows = prepare_prior_snapshot(prior_path)
    decision_time = pd.to_datetime(args.decision_time_utc, errors="raise", utc=True)
    context = pd.read_parquet(context_path, columns=["ticker", "cik10"])
    context["ticker"] = context["ticker"].astype(str).str.upper().str.strip()
    context["cik10"] = context["cik10"].map(clean_cik)
    context = context.drop_duplicates("ticker", keep="last")
    sec_index = prepare_index(pd.read_parquet(index_path), pd.Timestamp(decision_time))
    index_groups = {cik: group for cik, group in sec_index.groupby("cik10", sort=False)}
    rows: list[dict[str, Any]] = []
    reused_count = 0
    refreshed_count = 0
    missing_members = 0
    with zipfile.ZipFile(zip_path) as archive:
        member_map = {Path(name).name: name for name in archive.namelist()}
        for item in context.itertuples(index=False):
            ticker_index = index_groups.get(item.cik10, pd.DataFrame())
            prior_row = prior_rows.get(item.ticker)
            member = member_map.get(f"CIK{item.cik10}.json") if item.cik10 else None
            if member and may_reuse_prior(
                prior_row, item.cik10, ticker_index, pd.Timestamp(decision_time)
            ):
                reused = dict(prior_row or {})
                reused["ticker"] = item.ticker
                reused["cik10"] = item.cik10
                reused["snapshot_refresh_status"] = "REUSED_NO_NEW_ACCEPTED_STATEMENT"
                rows.append(reused)
                reused_count += 1
                continue
            refreshed_count += 1
            if not member:
                missing_members += 1
                row = build_row(item.ticker, item.cik10, {}, pd.DataFrame())
                row["snapshot_refresh_status"] = "REFRESHED_COMPANYFACTS_MEMBER_MISSING"
                rows.append(row)
                continue
            payload = json.loads(archive.read(member))
            row = build_row(
                item.ticker,
                item.cik10,
                payload,
                ticker_index,
            )
            row["snapshot_refresh_status"] = "REFRESHED"
            rows.append(row)
    snapshot = pd.DataFrame(rows).sort_values("ticker").reset_index(drop=True)
    future = pd.to_datetime(snapshot["available_from"], errors="coerce", utc=True).gt(decision_time)
    if bool(future.any()):
        raise ValueError("future exact-debt rows detected")
    snapshot.to_csv(output_dir / "exact_debt_snapshot.csv", index=False, lineterminator="\n")
    coverage = (
        snapshot.groupby(["form", "debt_scope_status"], dropna=False)
        .agg(ticker_count=("ticker", "nunique"), exact_complete=("exact_debt_component_coverage", lambda x: int(pd.to_numeric(x, errors="coerce").eq(1.0).sum())))
        .reset_index()
    )
    coverage.to_csv(output_dir / "coverage_summary.csv", index=False, lineterminator="\n")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "READY_RUN287_EXACT_DEBT_SNAPSHOT_REVIEW_ONLY",
        "decision_time_utc": pd.Timestamp(decision_time).isoformat(),
        "universe_count": int(snapshot["ticker"].nunique()),
        "exact_acceptance_count": int(snapshot["exact_acceptance"].sum()),
        "exact_debt_complete_count": int(snapshot["exact_debt_component_coverage"].eq(1.0).sum()),
        "exact_debt_partial_count": int(snapshot["exact_debt_component_coverage"].between(0.0, 1.0, inclusive="neither").sum()),
        "companyfacts_member_missing_count": int(missing_members),
        "prior_snapshot_reused_count": int(reused_count),
        "refreshed_ticker_count": int(refreshed_count),
        "future_row_count": int(future.sum()),
        "filed_fallback_used_count": int(snapshot["filed_fallback_used"].sum()),
        "source_inputs": {
            "selection_context": fingerprint(context_path),
            "companyfacts_zip": fingerprint(zip_path),
            "sec_index": fingerprint(index_path),
            "prior_snapshot": fingerprint(prior_path) if prior_path is not None else {
                "path": None, "exists": False, "bytes": 0, "sha256": None
            },
        },
        "outputs": {
            "exact_debt_snapshot": fingerprint(output_dir / "exact_debt_snapshot.csv"),
            "coverage_summary": fingerprint(output_dir / "coverage_summary.csv"),
        },
        "missing_debt_is_zero": False,
        "model_mutated": False,
        "score_mutated": False,
        "rank_mutated": False,
        "selector_mutated": False,
        "target_books_mutated": False,
        "cash_policy_mutated": False,
        "orders_generated": False,
        "backtest_executed": False,
        "fullrun_executed": False,
        "production_activation_allowed": False,
        "live_trading_enabled": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-context", required=True)
    parser.add_argument("--companyfacts-zip", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--sec-index", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument("--decision-time-utc", required=True)
    parser.add_argument(
        "--prior-snapshot",
        default="",
        help="Optional previous snapshot; exact-complete rows are reused only when no newer accepted statement exists.",
    )
    parser.add_argument("--output-dir", default="outputs/run287_exact_debt_snapshot")
    return parser.parse_args()


if __name__ == "__main__":
    result = build(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
