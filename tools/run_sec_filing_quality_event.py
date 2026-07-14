#!/usr/bin/env python3
"""Build a research-only SEC accepted-time filing quality event sidecar.

The SEC Companyfacts feed identifies the filing that disclosed each fact by
``accn`` but only carries a filed date.  This tool deliberately does *not* use
that date as point-in-time availability.  Instead, it joins ``accn`` to an
offline SEC submissions index and only permits exact ``accepted_at`` rows to
participate in a signal.

The event is predeclared and intentionally small:

* change in year-over-year revenue growth,
* change in year-over-year operating-income growth,
* change in year-over-year operating-cash-flow growth, and
* change in the year-over-year operating-margin delta.

At least three observed components must improve for ``positive`` or worsen for
``negative``.  Everything else is neutral.  No network access, model fitting,
percentile tuning, or portfolio/fullrun behavior is implemented here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import numpy as np
import pandas as pd

try:
    import pandas_market_calendars as mcal
except ImportError:  # pragma: no cover - required by research environment
    mcal = None

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_helpers import normalize_cik10  # noqa: E402
from tools.run_weekly_evaluation import load_price_series, px_cache_name  # noqa: E402


RESEARCH_FORMS = frozenset({"10-Q", "10-Q/A", "10-K", "10-K/A", "8-K", "8-K/A"})
FLOW_TAG_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomer",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueServicesNet",
        "SalesRevenueGoodsNet",
        "SalesRevenueGoodsGross",
        "OperatingRevenue",
        "NetSales",
        "RevenueFromContractWithCustomerExcludingTax",
    ),
    "op_income": (
        "OperatingIncomeLoss",
        "OperatingIncome",
        "OperatingProfitLoss",
        "IncomeFromOperations",
        "IncomeLossFromOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromOperationsBeforeIncomeTaxesMinorityInterest",
        "ProfitLossFromOperatingActivities",
        "OperatingEarningsLoss",
    ),
    "ocf": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "NetCashProvidedByUsedInContinuingOperations",
    ),
}
COMPONENT_COLUMNS = (
    "revenue_growth_change",
    "op_income_growth_change",
    "ocf_growth_change",
    "operating_margin_yoy_change_change",
)
EVENT_KEY = ["ticker", "cik10", "accession_number", "accepted_at"]
EVENT_COLUMNS = [
    "ticker",
    "cik10",
    "accession_number",
    "form",
    "fiscal_period",
    "fiscal_year",
    "fiscal_quarter",
    "period",
    "duration_bucket",
    "duration_days",
    "accepted_at",
    "available_from",
    "exact_acceptance",
    "sec_filing_quality_event",
    "event_score",
    "component_coverage",
    "improving_component_count",
    "worsening_component_count",
    *COMPONENT_COLUMNS,
    "revenue_yoy_growth",
    "op_income_yoy_growth",
    "ocf_yoy_growth",
    "operating_margin_yoy_change",
    "source_hashes",
    "pit_caveats",
]
PIT_CAVEATS = (
    "research_only",
    "pit_universe_label_clean=false",
    "exact_sec_acceptance_required",
    "filed_date_fallback_forbidden",
    "missing_components_are_neutral",
    "current_identity_mapping_not_historical_membership",
    "multi_share_class_issuer_events_are_replicated_per_current_ticker_and_source_screen_collapses_to_unique_cik_accession",
)
DEFAULT_OOS_START = "2024-07-01"
DEFAULT_OOS2_START = "2023-01-01"
DURATION_MATCH_TOLERANCE_DAYS = 7.0


class DataContractError(ValueError):
    """Raised when continuing would violate the point-in-time contract."""


@dataclass(frozen=True)
class CompanyfactsPayload:
    cik10: str
    payload: dict[str, Any]
    sha256: str
    source_member: str


def repo_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def cik10(value: Any) -> str:
    return normalize_cik10(value) or ""


def accession_key(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


SOURCE_SCREEN_PRODUCER_FILES = (
    REPO_ROOT / "tools" / "run_sec_filing_quality_event.py",
    REPO_ROOT / "tools" / "run_weekly_evaluation.py",
    REPO_ROOT / "r1000_helpers.py",
)


def fingerprint_path(path: Path) -> dict[str, Any]:
    absolute = path.resolve(strict=False)
    if path.is_file():
        return {
            "path": str(absolute),
            "sha256": sha256_file(path),
            "file_count": 1,
            "total_bytes": int(path.stat().st_size),
        }
    if path.is_dir():
        digest = hashlib.sha256()
        files = sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.relative_to(path).as_posix())
        total_bytes = 0
        for item in files:
            relative = item.relative_to(path).as_posix()
            size = item.stat().st_size
            total_bytes += size
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(size).encode("ascii"))
            digest.update(b"\0")
            digest.update(sha256_file(item).encode("ascii"))
            digest.update(b"\n")
        return {
            "path": str(absolute),
            "sha256": digest.hexdigest(),
            "file_count": len(files),
            "total_bytes": int(total_bytes),
        }
    return {"path": str(absolute), "sha256": "", "file_count": 0, "total_bytes": 0}


def source_screen_producer_fingerprint() -> tuple[str, dict[str, str]]:
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    for path in SOURCE_SCREEN_PRODUCER_FILES:
        relative = path.relative_to(REPO_ROOT).as_posix()
        file_hash = sha256_file(path) if path.is_file() else ""
        files[relative] = file_hash
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), files


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def read_table(path_like: str | Path) -> pd.DataFrame:
    path = repo_path(path_like)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in {".json", ".jsonl"}:
        if path.suffix.lower() == ".jsonl":
            return pd.read_json(path, lines=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return pd.DataFrame(payload if isinstance(payload, list) else payload.get("rows", []))
    return pd.read_csv(path, low_memory=False)


def _payload_cik(payload: dict[str, Any], fallback: str = "") -> str:
    return cik10(payload.get("cik")) or cik10(fallback)


def iter_companyfacts_payloads(
    path_like: str | Path,
    *,
    wanted_ciks: Iterable[str] | None = None,
) -> Iterator[CompanyfactsPayload]:
    """Yield exact Companyfacts JSON bytes from a zip, directory, or file."""
    path = repo_path(path_like)
    if not path.exists():
        raise FileNotFoundError(path)
    wanted = {cik10(value) for value in (wanted_ciks or []) if cik10(value)}

    def decoded(raw: bytes, member: str, fallback: str = "") -> CompanyfactsPayload | None:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        norm = _payload_cik(payload, fallback)
        if not norm or (wanted and norm not in wanted):
            return None
        return CompanyfactsPayload(norm, payload, sha256_bytes(raw), member)

    if path.is_file() and path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            for member in sorted(archive.namelist()):
                if not member.lower().endswith(".json"):
                    continue
                fallback = Path(member).stem.replace("CIK", "").replace("cik", "")
                if wanted and cik10(fallback) and cik10(fallback) not in wanted:
                    continue
                row = decoded(archive.read(member), member, fallback)
                if row is not None:
                    yield row
        return
    if path.is_dir():
        for item in sorted(path.rglob("*.json")):
            fallback = item.stem.replace("CIK", "").replace("cik", "")
            if wanted and cik10(fallback) and cik10(fallback) not in wanted:
                continue
            row = decoded(item.read_bytes(), str(item), fallback)
            if row is not None:
                yield row
        return
    row = decoded(path.read_bytes(), str(path), path.stem.replace("CIK", ""))
    if row is not None:
        yield row


def parse_utc(value: Any) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        return pd.NaT
    return pd.to_datetime(value, errors="coerce", utc=True)


def iso_utc(value: Any) -> str:
    parsed = parse_utc(value)
    return "" if pd.isna(parsed) else parsed.isoformat()


def nyse_market_close_map(date_values: Iterable[Any]) -> dict[str, pd.Timestamp]:
    """Return actual NYSE close timestamps, including scheduled half days."""
    dates = pd.to_datetime(list(date_values), errors="coerce", utc=True)
    valid = pd.DatetimeIndex(dates[~pd.isna(dates)]).tz_convert(None).normalize()
    if valid.empty:
        return {}
    if mcal is None:
        raise DataContractError("pandas_market_calendars is required for exact SEC event-time labels")
    schedule = mcal.get_calendar("NYSE").schedule(start_date=valid.min(), end_date=valid.max())
    if schedule.empty or "market_close" not in schedule.columns:
        raise DataContractError("NYSE market-close schedule unavailable")
    return {
        pd.Timestamp(index).date().isoformat(): pd.Timestamp(close).tz_convert("UTC")
        for index, close in schedule["market_close"].items()
    }


def duration_days(start: Any, end: Any) -> float:
    start_ts = pd.to_datetime(start, errors="coerce")
    end_ts = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        return np.nan
    return float((end_ts - start_ts).days + 1)


def duration_bucket(days: Any) -> str:
    value = pd.to_numeric(days, errors="coerce")
    if pd.isna(value):
        return "unknown"
    value = float(value)
    if 60 <= value <= 130:
        return "quarter"
    if 131 <= value <= 230:
        return "half_ytd"
    if 231 <= value <= 320:
        return "nine_month_ytd"
    if 321 <= value <= 410:
        return "annual"
    return "other"


def _unit_keys(units: dict[str, Any]) -> list[str]:
    keys = [str(key) for key, values in units.items() if isinstance(values, list)]
    usd = [key for key in keys if key.upper() == "USD"]
    return usd or sorted(keys)


def extract_companyfacts_flow_records(item: CompanyfactsPayload) -> pd.DataFrame:
    """Extract accession-preserving flow facts; never interprets ``filed`` as PIT."""
    facts = item.payload.get("facts") or {}
    rows: list[dict[str, Any]] = []
    for field_name, aliases in FLOW_TAG_ALIASES.items():
        for namespace in ("us-gaap", "ifrs-full"):
            namespace_facts = facts.get(namespace) or {}
            if not isinstance(namespace_facts, dict):
                continue
            for alias_rank, alias in enumerate(aliases):
                fact = namespace_facts.get(alias)
                if not isinstance(fact, dict):
                    continue
                units = fact.get("units") or {}
                if not isinstance(units, dict):
                    continue
                for unit in _unit_keys(units):
                    for raw in units.get(unit) or []:
                        if not isinstance(raw, dict):
                            continue
                        form = str(raw.get("form") or "").upper().strip()
                        accn = str(raw.get("accn") or "").strip()
                        accn_key = accession_key(accn)
                        end = pd.to_datetime(str(raw.get("end") or ""), errors="coerce")
                        value = pd.to_numeric(raw.get("val"), errors="coerce")
                        if form not in RESEARCH_FORMS or not accn_key or pd.isna(end) or not np.isfinite(value):
                            continue
                        days = duration_days(raw.get("start"), raw.get("end"))
                        rows.append(
                            {
                                "cik10": item.cik10,
                                "accession_number": accn,
                                "accession_key": accn_key,
                                "form": form,
                                "fiscal_year": raw.get("fy"),
                                "fiscal_quarter": str(raw.get("fp") or "").upper().strip(),
                                "frame": str(raw.get("frame") or ""),
                                "start": pd.to_datetime(str(raw.get("start") or ""), errors="coerce"),
                                "period": end,
                                "duration_days": days,
                                "duration_bucket": duration_bucket(days),
                                "field_name": field_name,
                                "source_tag": alias,
                                "alias_rank": int(alias_rank),
                                "unit": str(unit),
                                "value": float(value),
                                "companyfacts_sha256": item.sha256,
                                "companyfacts_member": item.source_member,
                            }
                        )
                # SEC aliases frequently duplicate the same economic fact.  We
                # retain lower-priority aliases only as a fallback during the
                # accession/period selection step.
    return pd.DataFrame(rows)


def load_companyfacts_records(
    path_like: str | Path,
    *,
    wanted_ciks: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    frames: list[pd.DataFrame] = []
    sources: dict[str, dict[str, str]] = {}
    for payload in iter_companyfacts_payloads(path_like, wanted_ciks=wanted_ciks):
        sources[payload.cik10] = {
            "companyfacts_sha256": payload.sha256,
            "companyfacts_member": payload.source_member,
        }
        frame = extract_companyfacts_flow_records(payload)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(), sources
    return pd.concat(frames, ignore_index=True), sources


def prepare_filings(filings: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    required = {"ticker", "cik10", "accession_number", "accepted_at"}
    missing = required - set(filings.columns)
    if missing:
        raise DataContractError(f"submissions index missing required columns: {sorted(missing)}")
    d = filings.copy()
    if "form" not in d.columns and "form_type" in d.columns:
        d = d.rename(columns={"form_type": "form"})
    if "form" not in d.columns:
        raise DataContractError("submissions index needs form or form_type")
    if "period" not in d.columns and "period_of_report" in d.columns:
        d = d.rename(columns={"period_of_report": "period"})
    if "period" not in d.columns:
        d["period"] = pd.NaT
    d["ticker"] = d["ticker"].fillna("").astype(str).str.upper().str.strip()
    d["cik10"] = d["cik10"].map(cik10)
    d["accession_number"] = d["accession_number"].fillna("").astype(str).str.strip()
    d["accession_key"] = d["accession_number"].map(accession_key)
    d["form"] = d["form"].fillna("").astype(str).str.upper().str.strip()
    d = d[d["form"].isin(RESEARCH_FORMS)].copy()
    accepted_text = d["accepted_at"].fillna("").astype(str).str.strip()
    d["accepted_ts"] = pd.to_datetime(accepted_text, errors="coerce", utc=True)
    d["period"] = pd.to_datetime(d["period"], errors="coerce")
    has_exact_time = accepted_text.str.contains(r"[T ]\d{2}:\d{2}", regex=True)
    exact = d["accepted_ts"].notna() & has_exact_time & d["accession_key"].ne("") & d["cik10"].ne("")
    diagnostics = {
        "eligible_filing_count": int(len(d)),
        "missing_exact_acceptance_count": int((~exact).sum()),
        "exact_acceptance_filing_count": int(exact.sum()),
    }
    d = d[exact].copy()
    d["accepted_at"] = d["accepted_ts"].map(lambda value: value.isoformat())
    d["available_from"] = d["accepted_at"]
    d["exact_acceptance"] = True
    d["submissions_row_sha256"] = d.apply(
        lambda row: sha256_bytes(
            canonical_json(
                {
                    "ticker": row["ticker"],
                    "cik10": row["cik10"],
                    "accession_number": row["accession_number"],
                    "form": row["form"],
                    "period": row["period"],
                    "accepted_at": row["accepted_at"],
                }
            ).encode("utf-8")
        ),
        axis=1,
    )
    d = d.sort_values(["ticker", "cik10", "accepted_ts", "accession_key"]).drop_duplicates(
        ["ticker", "cik10", "accession_key"], keep="last"
    )
    return d, diagnostics


def _preferred_bucket(form: str, candidates: pd.DataFrame) -> str:
    if candidates.empty:
        return "unknown"
    counts = candidates.groupby("duration_bucket")["field_name"].nunique().to_dict()
    if form.startswith("10-K") and counts.get("annual", 0):
        return "annual"
    if form.startswith("10-Q") and counts.get("quarter", 0):
        return "quarter"
    max_count = max(counts.values())
    tied = {bucket for bucket, count in counts.items() if count == max_count}
    preference = ("quarter", "annual", "nine_month_ytd", "half_ytd", "other", "unknown")
    return next((bucket for bucket in preference if bucket in tied), sorted(tied)[0])


def _select_current_facts(
    filing: pd.Series,
    facts: pd.DataFrame,
    accession_index: Mapping[tuple[str, str, str], Any] | None = None,
) -> pd.DataFrame:
    if accession_index is None:
        same = facts[
            facts["cik10"].eq(filing["cik10"])
            & facts["accession_key"].eq(filing["accession_key"])
        ].copy()
    else:
        positions = accession_index.get(
            (str(filing["ticker"]), str(filing["cik10"]), str(filing["accession_key"]))
        )
        same = facts.iloc[positions].copy() if positions is not None else facts.iloc[0:0].copy()
    if same.empty:
        return same
    report_period = filing.get("period")
    if pd.notna(report_period):
        exact_period = same[same["period"].eq(pd.Timestamp(report_period))].copy()
        if exact_period.empty:
            return same.iloc[0:0].copy()
        same = exact_period
    else:
        same = same[same["period"].eq(same["period"].max())].copy()
    bucket = _preferred_bucket(str(filing["form"]), same)
    same = same[same["duration_bucket"].eq(bucket)].copy()
    if same.empty:
        return same
    fp_coverage = same.groupby("fiscal_quarter", dropna=False)["field_name"].nunique().sort_values(ascending=False)
    if not fp_coverage.empty:
        if bucket == "annual" and "FY" in fp_coverage.index:
            selected_fp = "FY"
        else:
            selected_fp = fp_coverage.index[0]
        same = same[same["fiscal_quarter"].eq(selected_fp)].copy()
    # A lower alias rank is the canonical tag.  Prefer a USD row and then the
    # observation closest to the bucket's conventional duration.
    target_days = {"quarter": 91.0, "half_ytd": 182.0, "nine_month_ytd": 273.0, "annual": 365.0}.get(bucket, 0.0)
    same["unit_rank"] = np.where(same["unit"].astype(str).str.upper().eq("USD"), 0, 1)
    same["duration_distance"] = (pd.to_numeric(same["duration_days"], errors="coerce") - target_days).abs()
    return same.sort_values(
        ["field_name", "alias_rank", "unit_rank", "duration_distance", "source_tag"]
    ).drop_duplicates("field_name", keep="first")


def _latest_prior_year_fact(
    facts: pd.DataFrame,
    *,
    cik: str,
    ticker: str,
    field_name: str,
    unit: str,
    bucket: str,
    fiscal_quarter: str,
    current_duration_days: Any,
    current_period: pd.Timestamp,
    accepted_ts: pd.Timestamp,
    prior_base_index: Mapping[tuple[str, str, str, str, str], Any] | None = None,
    prior_fp_index: Mapping[tuple[str, str, str, str, str, str], Any] | None = None,
) -> pd.Series | None:
    indexed_lookup = False
    if fiscal_quarter and prior_fp_index is not None:
        indexed_lookup = True
        positions = prior_fp_index.get((ticker, cik, field_name, unit, bucket, fiscal_quarter))
    elif prior_base_index is not None:
        indexed_lookup = True
        positions = prior_base_index.get((ticker, cik, field_name, unit, bucket))
    else:
        positions = None
    if indexed_lookup and positions is None:
        return None
    if positions is not None:
        candidates = facts.iloc[positions].copy()
    else:
        candidates = facts[
            facts["cik10"].eq(cik)
            & facts["field_name"].eq(field_name)
            & facts["unit"].eq(unit)
            & facts["duration_bucket"].eq(bucket)
        ].copy()
        if fiscal_quarter:
            candidates = candidates[candidates["fiscal_quarter"].eq(fiscal_quarter)].copy()
    age = (current_period - candidates["period"]).dt.days
    candidates = candidates[candidates["accepted_ts"].le(accepted_ts) & age.between(330, 400)].copy()
    current_duration = pd.to_numeric(current_duration_days, errors="coerce")
    if pd.notna(current_duration):
        candidate_duration = pd.to_numeric(candidates["duration_days"], errors="coerce")
        candidates = candidates[
            candidate_duration.notna()
            & candidate_duration.sub(float(current_duration)).abs().le(DURATION_MATCH_TOLERANCE_DAYS)
        ].copy()
    if candidates.empty:
        return None
    candidates["year_distance"] = ((current_period - candidates["period"]).dt.days - 365).abs()
    return candidates.sort_values(
        ["year_distance", "accepted_ts", "alias_rank"],
        ascending=[True, False, True],
    ).iloc[0]


def signed_growth(current: Any, prior: Any) -> float:
    current_value = pd.to_numeric(current, errors="coerce")
    prior_value = pd.to_numeric(prior, errors="coerce")
    if pd.isna(current_value) or pd.isna(prior_value) or float(prior_value) == 0.0:
        return np.nan
    # abs(prior) keeps economic direction intuitive across sign changes while
    # retaining the familiar percent-change scale.
    return float((float(current_value) - float(prior_value)) / abs(float(prior_value)))


def exact_boolean_true(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value) == 1
    return str(value or "").strip().lower() == "true"


def facts_share_period(left: pd.Series | None, right: pd.Series | None) -> bool:
    if left is None or right is None:
        return False
    left_start = pd.to_datetime(left.get("start"), errors="coerce")
    right_start = pd.to_datetime(right.get("start"), errors="coerce")
    left_end = pd.to_datetime(left.get("period"), errors="coerce")
    right_end = pd.to_datetime(right.get("period"), errors="coerce")
    left_duration = pd.to_numeric(left.get("duration_days"), errors="coerce")
    right_duration = pd.to_numeric(right.get("duration_days"), errors="coerce")
    return bool(
        pd.notna(left_start)
        and pd.notna(right_start)
        and left_start == right_start
        and pd.notna(left_end)
        and pd.notna(right_end)
        and left_end == right_end
        and pd.notna(left_duration)
        and pd.notna(right_duration)
        and abs(float(left_duration) - float(right_duration)) <= DURATION_MATCH_TOLERANCE_DAYS
    )


def _raw_event_rows(filings: pd.DataFrame, facts: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    accession_index = facts.groupby(["ticker", "cik10", "accession_key"], sort=False, dropna=False).indices
    prior_base_index = facts.groupby(
        ["ticker", "cik10", "field_name", "unit", "duration_bucket"], sort=False, dropna=False
    ).indices
    prior_fp_index = facts.groupby(
        ["ticker", "cik10", "field_name", "unit", "duration_bucket", "fiscal_quarter"], sort=False, dropna=False
    ).indices
    for _, filing in filings.sort_values(["cik10", "accepted_ts", "accession_key"]).iterrows():
        selected = _select_current_facts(filing, facts, accession_index)
        selected_by_field = {str(row["field_name"]): row for _, row in selected.iterrows()}
        base: dict[str, Any] = {
            "ticker": filing["ticker"],
            "cik10": filing["cik10"],
            "accession_number": filing["accession_number"],
            "accession_key": filing["accession_key"],
            "form": filing["form"],
            "accepted_ts": filing["accepted_ts"],
            "accepted_at": filing["accepted_at"],
            "available_from": filing["accepted_at"],
            "exact_acceptance": True,
            "submissions_row_sha256": filing["submissions_row_sha256"],
        }
        current_period = selected["period"].max() if not selected.empty else filing.get("period")
        bucket = str(selected["duration_bucket"].iloc[0]) if not selected.empty else "unknown"
        fiscal_quarter = ""
        fiscal_year: Any = ""
        duration_value = np.nan
        if not selected.empty:
            fp_values = selected["fiscal_quarter"].replace("", pd.NA).dropna()
            fy_values = selected["fiscal_year"].dropna()
            fiscal_quarter = str(fp_values.mode().iloc[0]) if not fp_values.empty else ""
            fiscal_year = fy_values.mode().iloc[0] if not fy_values.empty else ""
            duration_value = pd.to_numeric(selected["duration_days"], errors="coerce").median()
        base.update(
            {
                "period": pd.Timestamp(current_period).date().isoformat() if pd.notna(current_period) else "",
                "duration_bucket": bucket,
                "duration_days": float(duration_value) if pd.notna(duration_value) else np.nan,
                "fiscal_year": fiscal_year,
                "fiscal_quarter": fiscal_quarter,
                "fiscal_period": f"{fiscal_year}:{fiscal_quarter}:{bucket}",
            }
        )
        prior_by_field: dict[str, pd.Series] = {}
        for field_name in FLOW_TAG_ALIASES:
            current = selected_by_field.get(field_name)
            base[f"{field_name}_value"] = np.nan
            base[f"{field_name}_unit"] = ""
            base[f"{field_name}_yoy_growth"] = np.nan
            base[f"{field_name}_prior_value"] = np.nan
            if current is None or pd.isna(current_period):
                continue
            prior = _latest_prior_year_fact(
                facts,
                cik=str(filing["cik10"]),
                ticker=str(filing["ticker"]),
                field_name=field_name,
                unit=str(current["unit"]),
                bucket=str(current["duration_bucket"]),
                fiscal_quarter=str(current["fiscal_quarter"]),
                current_duration_days=current["duration_days"],
                current_period=pd.Timestamp(current_period),
                accepted_ts=filing["accepted_ts"],
                prior_base_index=prior_base_index,
                prior_fp_index=prior_fp_index,
            )
            base[f"{field_name}_value"] = float(current["value"])
            base[f"{field_name}_unit"] = str(current["unit"])
            if prior is not None:
                prior_by_field[field_name] = prior
                base[f"{field_name}_prior_value"] = float(prior["value"])
                base[f"{field_name}_yoy_growth"] = signed_growth(current["value"], prior["value"])

        revenue = base.get("revenue_value")
        op_income = base.get("op_income_value")
        revenue_prior = base.get("revenue_prior_value")
        op_income_prior = base.get("op_income_prior_value")
        units_match = bool(base.get("revenue_unit")) and base.get("revenue_unit") == base.get("op_income_unit")
        current_periods_match = facts_share_period(
            selected_by_field.get("revenue"), selected_by_field.get("op_income")
        )
        prior_periods_match = facts_share_period(
            prior_by_field.get("revenue"), prior_by_field.get("op_income")
        )
        if (
            units_match
            and current_periods_match
            and prior_periods_match
            and pd.notna(revenue)
            and pd.notna(op_income)
            and pd.notna(revenue_prior)
            and pd.notna(op_income_prior)
            and float(revenue) != 0.0
            and float(revenue_prior) != 0.0
        ):
            base["operating_margin"] = float(op_income) / float(revenue)
            base["operating_margin_yoy_change"] = (
                float(op_income) / float(revenue) - float(op_income_prior) / float(revenue_prior)
            )
        else:
            base["operating_margin"] = np.nan
            base["operating_margin_yoy_change"] = np.nan
        rows.append(base)
    return pd.DataFrame(rows)


def _add_predeclared_event(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)
    d = raw.sort_values(["ticker", "cik10", "accepted_ts", "accession_key"]).copy()
    grouped = d.groupby(["ticker", "cik10", "duration_bucket"], sort=False, dropna=False)
    for field_name in ("revenue", "op_income", "ocf"):
        yoy = f"{field_name}_yoy_growth"
        output = f"{field_name}_growth_change"
        d[output] = grouped[yoy].transform(lambda series: series - series.ffill().shift(1))
    margin = "operating_margin_yoy_change"
    d["operating_margin_yoy_change_change"] = grouped[margin].transform(
        lambda series: series - series.ffill().shift(1)
    )
    component_frame = d[list(COMPONENT_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    d["component_coverage"] = component_frame.notna().sum(axis=1).astype(int)
    d["improving_component_count"] = component_frame.gt(0.0).sum(axis=1).astype(int)
    d["worsening_component_count"] = component_frame.lt(0.0).sum(axis=1).astype(int)
    positive = d["component_coverage"].ge(3) & d["improving_component_count"].ge(3)
    negative = d["component_coverage"].ge(3) & d["worsening_component_count"].ge(3)
    d["sec_filing_quality_event"] = np.select([positive, negative], ["positive", "negative"], default="neutral")
    d["event_score"] = np.select([positive, negative], [1, -1], default=0).astype(int)
    return d


def assert_event_contract(events: pd.DataFrame) -> None:
    missing = set(EVENT_COLUMNS) - set(events.columns)
    if missing:
        raise DataContractError(f"event sidecar missing columns: {sorted(missing)}")
    if events.empty:
        return
    accepted = pd.to_datetime(events["accepted_at"], errors="coerce", utc=True)
    available = pd.to_datetime(events["available_from"], errors="coerce", utc=True)
    fired = events["sec_filing_quality_event"].isin(["positive", "negative"])
    violations = (
        accepted.isna()
        | available.isna()
        | accepted.ne(available)
        | ~events["exact_acceptance"].map(exact_boolean_true)
        | events["accession_number"].fillna("").astype(str).str.strip().eq("")
    )
    if violations.any():
        sample = events.loc[violations, EVENT_KEY].head(5).to_dict(orient="records")
        raise DataContractError(f"exact-acceptance contract violation: {sample}")
    if fired.any() and events.loc[fired, "component_coverage"].lt(3).any():
        raise DataContractError("fired event has fewer than three observed components")


def normalize_event_dtypes(events: pd.DataFrame) -> pd.DataFrame:
    """Return a stable Arrow-safe schema for append-only event persistence."""
    out = events.copy()
    string_columns = (
        "ticker",
        "cik10",
        "accession_number",
        "form",
        "fiscal_period",
        "fiscal_year",
        "fiscal_quarter",
        "period",
        "duration_bucket",
        "accepted_at",
        "available_from",
        "sec_filing_quality_event",
        "source_hashes",
        "pit_caveats",
    )
    integer_columns = (
        "event_score",
        "component_coverage",
        "improving_component_count",
        "worsening_component_count",
    )
    float_columns = (
        "duration_days",
        *COMPONENT_COLUMNS,
        "revenue_yoy_growth",
        "op_income_yoy_growth",
        "ocf_yoy_growth",
        "operating_margin_yoy_change",
    )
    for column in string_columns:
        out[column] = out[column].fillna("").astype(str)
    out["exact_acceptance"] = out["exact_acceptance"].map(exact_boolean_true).astype(bool)
    for column in integer_columns:
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("Int64")
    for column in float_columns:
        out[column] = pd.to_numeric(out[column], errors="coerce").astype(float)
    return out[EVENT_COLUMNS]


def build_filing_quality_events(
    companyfacts: pd.DataFrame,
    filings: pd.DataFrame,
    *,
    companyfacts_sources: dict[str, dict[str, str]] | None = None,
    submissions_sha256: str = "",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared, diagnostics = prepare_filings(filings)
    facts = companyfacts.copy()
    if not facts.empty:
        facts["cik10"] = facts["cik10"].map(cik10)
        facts["accession_key"] = facts["accession_number"].map(accession_key)
        for column in ("field_name", "unit", "duration_bucket", "fiscal_quarter"):
            facts[column] = facts[column].fillna("").astype(str)
        acceptance = prepared[["ticker", "cik10", "accession_key", "accepted_ts"]].drop_duplicates(
            ["ticker", "cik10", "accession_key"], keep="last"
        )
        facts = facts.merge(acceptance, on=["cik10", "accession_key"], how="left", validate="many_to_many")
        # Facts without an exact accepted-time join are unavailable, not filed-date
        # fallbacks.  Excluding them is the fail-closed behavior.
        unjoined_count = int(facts["accepted_ts"].isna().sum())
        facts = facts[facts["accepted_ts"].notna()].copy()
        facts["ticker"] = facts["ticker"].fillna("").astype(str).str.upper().str.strip()
    else:
        unjoined_count = 0
    raw = _raw_event_rows(prepared, facts) if not prepared.empty else pd.DataFrame()
    events = _add_predeclared_event(raw)
    sources = companyfacts_sources or {}
    if not events.empty:
        events["source_hashes"] = events.apply(
            lambda row: canonical_json(
                {
                    **sources.get(str(row["cik10"]), {}),
                    "submissions_index_sha256": submissions_sha256,
                    "submissions_row_sha256": str(row.get("submissions_row_sha256") or ""),
                }
            ),
            axis=1,
        )
        events["pit_caveats"] = canonical_json(list(PIT_CAVEATS))
        for column in EVENT_COLUMNS:
            if column not in events.columns:
                events[column] = np.nan
        events = normalize_event_dtypes(events[EVENT_COLUMNS]).sort_values(
            ["accepted_at", "ticker", "accession_number"]
        ).reset_index(drop=True)
    else:
        events = pd.DataFrame(columns=EVENT_COLUMNS)
    assert_event_contract(events)
    diagnostics.update(
        {
            "companyfacts_row_count": int(len(companyfacts)),
            "companyfacts_rows_without_exact_acceptance": unjoined_count,
            "event_count": int(len(events)),
            "multi_ticker_issuer_cik_count": int(
                prepared.groupby("cik10")["ticker"].nunique().gt(1).sum()
            ) if not prepared.empty else 0,
            "source_screen_issuer_independence": True,
            "positive_event_count": int(events["sec_filing_quality_event"].eq("positive").sum()),
            "negative_event_count": int(events["sec_filing_quality_event"].eq("negative").sum()),
            "neutral_event_count": int(events["sec_filing_quality_event"].eq("neutral").sum()),
            "fired_exact_acceptance_ratio": 1.0
            if events["sec_filing_quality_event"].isin(["positive", "negative"]).any()
            else None,
            "filed_date_fallback_used": False,
            "pit_universe_label_clean": False,
            "research_only": True,
            "submissions_index_sha256": submissions_sha256,
        }
    )
    return events, diagnostics


def assert_no_future_availability(
    frame: pd.DataFrame,
    *,
    decision_column: str = "decision_time",
) -> None:
    if decision_column not in frame.columns or "available_from" not in frame.columns:
        raise DataContractError(f"PIT check needs available_from and {decision_column}")
    available = pd.to_datetime(frame["available_from"], errors="coerce", utc=True)
    decision = pd.to_datetime(frame[decision_column], errors="coerce", utc=True)
    invalid = available.isna() | decision.isna() | available.gt(decision)
    if invalid.any():
        sample_columns = [column for column in ["ticker", "accession_number", "available_from", decision_column] if column in frame]
        raise DataContractError(
            f"future or missing availability detected: {frame.loc[invalid, sample_columns].head(5).to_dict(orient='records')}"
        )


def _normalize_prices(prices: pd.DataFrame) -> pd.DataFrame:
    d = prices.copy()
    aliases = {str(column).lower().replace(" ", "_"): column for column in d.columns}
    ticker_col = aliases.get("ticker") or aliases.get("symbol")
    date_col = aliases.get("date") or aliases.get("datetime") or aliases.get("timestamp")
    close_col = next(
        (aliases.get(name) for name in ("adjusted_close", "adj_close", "adjclose") if aliases.get(name)),
        None,
    )
    if ticker_col is None or date_col is None or close_col is None:
        raise DataContractError("price input needs ticker, date, and an adjusted-close column")
    out = d[[ticker_col, date_col, close_col]].rename(
        columns={ticker_col: "ticker", date_col: "date", close_col: "adjusted_close"}
    )
    out["ticker"] = out["ticker"].fillna("").astype(str).str.upper().str.strip()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["adjusted_close"] = pd.to_numeric(out["adjusted_close"], errors="coerce")
    return out.dropna(subset=["date", "adjusted_close"]).sort_values(["ticker", "date"]).drop_duplicates(
        ["ticker", "date"], keep="last"
    )


def load_prices(
    path_like: str | Path,
    *,
    wanted_tickers: Iterable[str] | None = None,
) -> pd.DataFrame:
    path = repo_path(path_like)
    if path.is_file():
        return _normalize_prices(read_table(path))
    if not path.is_dir():
        raise FileNotFoundError(path)
    wanted = sorted({str(value or "").upper().strip() for value in (wanted_tickers or []) if str(value or "").strip()})
    if wanted:
        frames: list[pd.DataFrame] = []
        for ticker in wanted:
            cache_file = path / px_cache_name(ticker)
            if not cache_file.is_file():
                continue
            try:
                raw_columns = pd.read_parquet(cache_file).columns
                flat_columns = raw_columns.get_level_values(0) if isinstance(raw_columns, pd.MultiIndex) else raw_columns
            except Exception:
                continue
            if "Adj Close" not in flat_columns:
                continue
            cached = load_price_series(path, ticker)
            if cached.empty or "close" not in cached.columns:
                continue
            frames.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "date": pd.DatetimeIndex(cached.index).tz_localize(None),
                        "adjusted_close": pd.to_numeric(cached["close"], errors="coerce").to_numpy(),
                    }
                )
            )
        return (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["ticker", "date", "adjusted_close"])
        )
    frames: list[pd.DataFrame] = []
    for item in sorted([*path.glob("*.parquet"), *path.glob("*.csv")]):
        raw = read_table(item)
        if "ticker" not in {str(column).lower() for column in raw.columns}:
            if re.fullmatch(r"[0-9a-fA-F]{16}", item.stem):
                raise DataContractError(
                    "hashed price cache requires wanted_tickers so ticker identity can be resolved safely"
                )
            raw = raw.copy()
            raw["ticker"] = item.stem.upper()
        frames.append(_normalize_prices(raw))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["ticker", "date", "adjusted_close"])


def label_forward_returns(events: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Add labels strictly after availability; labels never enter the sidecar."""
    rows: list[dict[str, Any]] = []
    normalized = _normalize_prices(prices)
    # Build the exchange-session grid over both event availability and price
    # history.  Using price dates alone can silently move an old event's entry
    # to the first cached price, rather than leaving the label missing when the
    # true first tradable close is unavailable.
    schedule_dates = normalized["date"].tolist()
    if "available_from" in events.columns:
        schedule_dates.extend(events["available_from"].tolist())
    close_map = nyse_market_close_map(schedule_dates)
    price_groups = {
        ticker: group.set_index("date")["adjusted_close"]
        for ticker, group in normalized.groupby("ticker", sort=False)
    }
    sessions = sorted((pd.Timestamp(date), close) for date, close in close_map.items())
    session_dates = [date.normalize() for date, _ in sessions]
    session_close_ns = np.asarray([int(close.value) for _, close in sessions], dtype=np.int64)
    for event in events.itertuples(index=False):
        row = event._asdict()
        accepted = parse_utc(row.get("available_from"))
        prices_by_date = price_groups.get(str(row.get("ticker") or "").upper())
        row["entry_date"] = ""
        for horizon in (21, 63, 126):
            row[f"forward_return_{horizon}d"] = np.nan
        if prices_by_date is not None and pd.notna(accepted):
            entry_session_pos = int(np.searchsorted(session_close_ns, int(accepted.value), side="right"))
            if entry_session_pos < len(session_dates):
                entry_date = session_dates[entry_session_pos]
                if entry_date in prices_by_date.index:
                    entry_price = float(prices_by_date.loc[entry_date])
                    row["entry_date"] = entry_date.date().isoformat()
                    if entry_price > 0:
                        for horizon in (21, 63, 126):
                            exit_session_pos = entry_session_pos + horizon
                            if exit_session_pos >= len(sessions):
                                continue
                            exit_date = session_dates[exit_session_pos]
                            if exit_date not in prices_by_date.index:
                                continue
                            row[f"forward_return_{horizon}d"] = float(
                                float(prices_by_date.loc[exit_date]) / entry_price - 1.0
                            )
        rows.append(row)
    return pd.DataFrame(rows)


def filing_week(value: Any) -> str:
    ts = parse_utc(value)
    if pd.isna(ts):
        return ""
    naive = ts.tz_convert(None).normalize()
    return naive.to_period("W-SUN").start_time.date().isoformat()


def cluster_bootstrap_spread(
    frame: pd.DataFrame,
    return_column: str,
    *,
    iterations: int = 2000,
    seed: int = 287,
) -> tuple[float, float]:
    usable = frame[
        frame["sec_filing_quality_event"].isin(["positive", "negative"])
        & pd.to_numeric(frame[return_column], errors="coerce").notna()
    ].copy()
    if usable.empty or usable["filing_week"].nunique() < 2:
        return np.nan, np.nan
    weekly = (
        usable.groupby(["filing_week", "sec_filing_quality_event"], sort=True)[return_column]
        .agg(["sum", "count"])
        .unstack(fill_value=0)
    )
    week_count = int(len(weekly))
    if week_count < 2:
        return np.nan, np.nan

    def values(metric: str, event: str) -> np.ndarray:
        key = (metric, event)
        if key not in weekly.columns:
            return np.zeros(week_count, dtype=float)
        return pd.to_numeric(weekly[key], errors="coerce").fillna(0.0).to_numpy(dtype=float)

    positive_sum = values("sum", "positive")
    positive_count = values("count", "positive")
    negative_sum = values("sum", "negative")
    negative_count = values("count", "negative")
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, week_count, size=(max(int(iterations), 1), week_count))
    pos_counts = positive_count[sampled].sum(axis=1)
    neg_counts = negative_count[sampled].sum(axis=1)
    valid = (pos_counts > 0) & (neg_counts > 0)
    if not valid.any():
        return np.nan, np.nan
    spreads = (
        positive_sum[sampled].sum(axis=1)[valid] / pos_counts[valid]
        - negative_sum[sampled].sum(axis=1)[valid] / neg_counts[valid]
    )
    return float(np.quantile(spreads, 0.025)), float(np.quantile(spreads, 0.975))


def classify_source_screen(metrics: dict[str, Any]) -> str:
    if "oos" not in metrics or "oos2" not in metrics:
        return "BLOCKED_SPLIT_DATES"
    primary = [metrics[name]["horizon_63"] for name in ("oos", "oos2")]
    powered = all(
        item.get("positive_count", 0) >= 100
        and item.get("negative_count", 0) >= 100
        and item.get("filing_week_count", 0) >= 12
        for item in primary
    )
    if not powered:
        return "UNDERPOWERED"
    spreads = [metrics[name]["horizon_63"].get("positive_minus_negative") for name in ("full", "oos", "oos2")]
    lowers = [metrics[name]["horizon_63"].get("filing_week_cluster_bootstrap_95_lower") for name in ("oos", "oos2")]
    if all(value is not None and value > 0 for value in spreads) and all(
        value is not None and value >= 0 for value in lowers
    ):
        return "PASS_SOURCE_SCREEN"
    return "REJECT_SOURCE_SCREEN"


def issuer_independent_source_rows(labeled: pd.DataFrame) -> pd.DataFrame:
    """Collapse current-ticker share classes to one accession-level source event."""
    if labeled.empty:
        return labeled.copy()
    keys = ["cik10", "accession_number", "accepted_at"]
    conflicts = labeled.groupby(keys, dropna=False)["sec_filing_quality_event"].nunique(dropna=False)
    if conflicts.gt(1).any():
        raise DataContractError("share-class rows disagree on the filing-quality event for one accession")
    entry_conflicts = labeled.groupby(keys, dropna=False)["entry_date"].nunique(dropna=False)
    if entry_conflicts.gt(1).any():
        raise DataContractError("share-class rows disagree on the exact source-screen entry session")
    aggregations: dict[str, Any] = {
        "available_from": "first",
        "sec_filing_quality_event": "first",
        "filing_week": "first",
        "entry_date": "first",
        "ticker": lambda values: ",".join(sorted(set(str(value) for value in values))),
    }
    for horizon in (21, 63, 126):
        aggregations[f"forward_return_{horizon}d"] = "mean"
    collapsed = labeled.groupby(keys, as_index=False, dropna=False).agg(aggregations)
    collapsed["share_class_ticker_count"] = collapsed["ticker"].str.count(",") + 1
    return collapsed


def source_screen(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    oos_start: str = DEFAULT_OOS_START,
    oos2_start: str = DEFAULT_OOS2_START,
    bootstrap_iterations: int = 2000,
    seed: int = 287,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    labeled = label_forward_returns(events, prices)
    labeled["filing_week"] = labeled["available_from"].map(filing_week)
    screen_rows = issuer_independent_source_rows(labeled)
    accepted = pd.to_datetime(screen_rows["accepted_at"], errors="coerce", utc=True)
    oos = parse_utc(oos_start)
    oos2 = parse_utc(oos2_start)
    segments: dict[str, pd.Series] = {"full": pd.Series(True, index=screen_rows.index)}
    if pd.notna(oos):
        segments["oos"] = accepted.ge(oos)
    if pd.notna(oos2):
        segments["oos2"] = accepted.ge(oos2)
    metrics: dict[str, Any] = {}
    for segment, mask in segments.items():
        scoped = screen_rows[mask].copy()
        segment_metrics: dict[str, Any] = {
            "event_count": int(len(scoped)),
            "filing_week_count": int(scoped["filing_week"].replace("", pd.NA).nunique()),
        }
        for horizon in (21, 63, 126):
            column = f"forward_return_{horizon}d"
            positive = pd.to_numeric(
                scoped.loc[scoped["sec_filing_quality_event"].eq("positive"), column], errors="coerce"
            ).dropna()
            negative = pd.to_numeric(
                scoped.loc[scoped["sec_filing_quality_event"].eq("negative"), column], errors="coerce"
            ).dropna()
            spread = float(positive.mean() - negative.mean()) if not positive.empty and not negative.empty else np.nan
            lower, upper = cluster_bootstrap_spread(
                scoped,
                column,
                iterations=bootstrap_iterations,
                seed=seed + horizon,
            )
            segment_metrics[f"horizon_{horizon}"] = {
                "positive_count": int(len(positive)),
                "negative_count": int(len(negative)),
                "filing_week_count": int(
                    scoped.loc[
                        scoped["sec_filing_quality_event"].isin(["positive", "negative"])
                        & pd.to_numeric(scoped[column], errors="coerce").notna(),
                        "filing_week",
                    ].replace("", pd.NA).nunique()
                ),
                "positive_mean": float(positive.mean()) if not positive.empty else None,
                "negative_mean": float(negative.mean()) if not negative.empty else None,
                "positive_minus_negative": spread if np.isfinite(spread) else None,
                "filing_week_cluster_bootstrap_95_lower": lower if np.isfinite(lower) else None,
                "filing_week_cluster_bootstrap_95_upper": upper if np.isfinite(upper) else None,
            }
        metrics[segment] = segment_metrics
    verdict = classify_source_screen(metrics)
    summary = {
        "verdict": verdict,
        "oos_start": oos.date().isoformat() if pd.notna(oos) else "",
        "oos2_start": oos2.date().isoformat() if pd.notna(oos2) else "",
        "primary_horizon_sessions": 63,
        "secondary_horizons_sessions": [21, 126],
        "entry_rule": "first adjusted market close strictly after exact accepted_at timestamp",
        "bootstrap": {
            "cluster": "filing_week",
            "iterations": int(bootstrap_iterations),
            "seed": int(seed),
        },
        "power_gate": {
            "minimum_positive_events_per_oos_segment": 100,
            "minimum_negative_events_per_oos_segment": 100,
            "minimum_filing_weeks_per_oos_segment": 12,
        },
        "segments": metrics,
        "source_screen_event_unit": "unique_cik10_accession_number",
        "raw_ticker_event_row_count": int(len(labeled)),
        "independent_issuer_event_count": int(len(screen_rows)),
        "multi_share_class_accession_count": int(screen_rows["share_class_ticker_count"].gt(1).sum()),
        "labels_are_not_features": True,
        "research_only": True,
    }
    return screen_rows, summary


def merge_append_only(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        return normalize_event_dtypes(new)
    missing = set(EVENT_COLUMNS) - set(existing.columns)
    if missing:
        raise DataContractError(f"existing sidecar schema mismatch: missing {sorted(missing)}")
    left = existing[EVENT_COLUMNS].copy()
    right = new[EVENT_COLUMNS].copy()
    overlap = left.merge(right, on=EVENT_KEY, how="inner", suffixes=("_old", "_new"))
    for _, row in overlap.iterrows():
        for column in EVENT_COLUMNS:
            if column in EVENT_KEY:
                continue
            old = row.get(f"{column}_old")
            current = row.get(f"{column}_new")
            if pd.isna(old) and pd.isna(current):
                continue
            if str(old) != str(current):
                key = {column_name: row[column_name] for column_name in EVENT_KEY}
                raise DataContractError(f"append-only conflict for {key}: column={column}")
    existing_keys = set(map(tuple, left[EVENT_KEY].astype(str).to_numpy()))
    additions = right[
        ~right[EVENT_KEY].astype(str).apply(tuple, axis=1).isin(existing_keys)
    ]
    return normalize_event_dtypes(pd.concat([left, additions], ignore_index=True)).sort_values(
        ["accepted_at", "ticker", "accession_number"]
    ).reset_index(drop=True)


def write_outputs(
    events: pd.DataFrame,
    diagnostics: dict[str, Any],
    output_dir: Path,
    *,
    labeled: pd.DataFrame | None = None,
    screen_summary: dict[str, Any] | None = None,
    screen_provenance: dict[str, Any] | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "sec_filing_quality_events.parquet"
    csv_path = output_dir / "sec_filing_quality_events.csv"
    existing = pd.read_parquet(parquet_path) if parquet_path.exists() else pd.DataFrame()
    combined = merge_append_only(existing, events)
    assert_event_contract(combined)
    combined.to_parquet(parquet_path, index=False)
    combined.to_csv(csv_path, index=False)
    paths = {"events_parquet": str(parquet_path), "events_csv": str(csv_path)}
    summary = {**diagnostics, "append_only_row_count": int(len(combined)), "schema": EVENT_COLUMNS, "paths": paths}
    if labeled is not None and screen_summary is not None:
        labels_path = output_dir / "source_screen_event_returns.csv"
        screen_path = output_dir / "source_screen_summary.json"
        labeled.to_csv(labels_path, index=False)
        producer_sha256, producer_files = source_screen_producer_fingerprint()
        screen_summary = {
            **screen_summary,
            **(screen_provenance or {}),
            "event_features_path": str(parquet_path),
            "event_features_sha256": sha256_file(parquet_path),
            "source_screen_rows_path": str(labels_path),
            "source_screen_rows_sha256": sha256_file(labels_path),
            "source_screen_producer_sha256": producer_sha256,
            "source_screen_producer_files": producer_files,
        }
        screen_path.write_text(json.dumps(screen_summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        paths.update({"source_screen_rows": str(labels_path), "source_screen_summary": str(screen_path)})
        summary["source_screen_verdict"] = screen_summary.get("verdict")
    summary_path = output_dir / "summary.json"
    summary["paths"] = paths
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    paths["summary"] = str(summary_path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companyfacts", default="data_raw/free/sec/companyfacts.zip")
    parser.add_argument("--submissions", default="data_pit/sec/sec_filings_index.parquet")
    parser.add_argument("--output-dir", default="outputs/sec_filing_quality_event")
    parser.add_argument("--prices", default="", help="Optional offline long price table or per-ticker cache directory.")
    parser.add_argument(
        "--reuse-event-features",
        default="",
        help="Optional existing exact event sidecar to re-run only the source screen and provenance attestation.",
    )
    parser.add_argument("--oos-start", default=DEFAULT_OOS_START)
    parser.add_argument("--oos2-start", default=DEFAULT_OOS2_START)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=287)
    args = parser.parse_args()

    reuse_path = repo_path(args.reuse_event_features) if str(args.reuse_event_features or "").strip() else None
    if reuse_path is not None:
        events = read_table(reuse_path)
        assert_event_contract(events)
        diagnostics = {
            "status": "reused_exact_event_sidecar_for_source_screen",
            "reused_event_features_path": str(reuse_path.resolve()),
            "reused_event_features_sha256": sha256_file(reuse_path),
            "research_only": True,
        }
    else:
        submissions_path = repo_path(args.submissions)
        filings = read_table(submissions_path)
        if "cik10" not in filings.columns:
            raise DataContractError("submissions index needs cik10")
        wanted_ciks = sorted({cik10(value) for value in filings["cik10"] if cik10(value)})
        facts, sources = load_companyfacts_records(args.companyfacts, wanted_ciks=wanted_ciks)
        events, diagnostics = build_filing_quality_events(
            facts,
            filings,
            companyfacts_sources=sources,
            submissions_sha256=sha256_file(submissions_path),
        )
    labeled: pd.DataFrame | None = None
    screen_summary: dict[str, Any] | None = None
    screen_provenance: dict[str, Any] | None = None
    if str(args.prices or "").strip():
        prices_path = repo_path(args.prices)
        price_fingerprint = fingerprint_path(prices_path)
        prices = load_prices(prices_path, wanted_tickers=events["ticker"].tolist())
        labeled, screen_summary = source_screen(
            events,
            prices,
            oos_start=args.oos_start,
            oos2_start=args.oos2_start,
            bootstrap_iterations=max(int(args.bootstrap_iterations), 1),
            seed=int(args.seed),
        )
        screen_provenance = {
            "price_input_path": price_fingerprint["path"],
            "price_input_sha256": price_fingerprint["sha256"],
            "price_input_file_count": price_fingerprint["file_count"],
            "price_input_total_bytes": price_fingerprint["total_bytes"],
        }
    paths = write_outputs(
        events,
        diagnostics,
        repo_path(args.output_dir),
        labeled=labeled,
        screen_summary=screen_summary,
        screen_provenance=screen_provenance,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "research_only": True,
                "event_count": int(len(events)),
                "source_screen_verdict": (screen_summary or {}).get("verdict", "NOT_RUN"),
                **paths,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
