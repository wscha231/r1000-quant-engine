"""Read-only, frozen-universe coverage audit. Never collect or publish data.

Legacy nonzero fields are observation evidence, not certified consensus.
V2 admission delegates to the existing H1 validator; this tool cannot grant
H2 admission or invent missing fiscal/security metadata.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    from tools import earnings_consensus_h1 as H1
except ImportError:
    H1 = None

V2 = "earnings-consensus-source-v2"
CASH = {"CASH", "__CASH__"}
STRICT = ("fresh_eps_fy1", "fresh_revenue_fy1", "fresh_both_fy1",
          "fresh_eps_fy2", "fresh_revenue_fy2", "fresh_eps_next_quarter",
          "fresh_revenue_next_quarter", "source_v2_eligible",
          "revision_30d_eligible", "revision_90d_eligible",
          "eps_revision_30d_eligible", "eps_revision_90d_eligible",
          "revenue_revision_30d_eligible", "revenue_revision_90d_eligible",
          "research_consumer_eligible")
FUTURE_QUARTER = ("fresh_eps_future_quarter", "fresh_revenue_future_quarter")
ADMISSION_FIELDS = (*STRICT, *FUTURE_QUARTER)
COUNT_FIELDS = ("attempted", "ever_seen", "ever_estimate_positive", "legacy_latest_positive",
                "legacy_fresh_positive", "legacy_fresh_eps_nonzero_evidence",
                "legacy_fresh_revenue_nonzero_evidence", "legacy_fresh_eps_fy2_nonzero_evidence",
                *ADMISSION_FIELDS)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_universe(values: list[str]) -> list[str]:
    symbols = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("nonempty_frozen_security_required")
        symbols.append(value.strip().upper())
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("unique_normalized_frozen_universe_required")
    return symbols


def numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def exact_time(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def row_clock(row: dict) -> datetime | None:
    if row.get("source_contract") == V2:
        times = [exact_time(row.get(k)) for k in
                 ("observed_at", "first_seen_at", "collected_at",
                  "strategy_available_at", "provider_published_at")]
        return max((t for t in times if t), default=None)
    # Date precision is retained as a legacy diagnostic; never V2 admission.
    value = row.get("available_from")
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return (ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")).to_pydatetime()
    except (TypeError, ValueError):
        return None


def finite_flag(row: dict) -> bool:
    value = numeric(row.get("has_forward_estimate"))
    return value is not None and value > 0


def stable_row(row: dict) -> str:
    return json.dumps(row, sort_keys=True, default=str)


def metric_values(row: dict, metric: str, cutoff: datetime, h1: Any) -> list[dict]:
    records = h1.consensus_records(row)
    return [r for r in records if h1.identity_complete(r.get("identity"))
            and r["identity"].get("metric") == metric
            and r["identity"].get("period_type") in {"ANNUAL", "QUARTERLY"}
            and str(r["identity"].get("fiscal_period_end")) >= cutoff.date().isoformat()
            and numeric(r.get("value")) is not None
            and sum(x.get("identity") == r.get("identity") for x in records) == 1]


def audit_rows(universe: list[str], rows: list[dict], *, as_of: str,
               stale_after_days: int = 7, h1: Any = H1,
               snapshot_inputs_available: bool = True) -> tuple[list[dict], dict]:
    cutoff = exact_time(as_of)
    if cutoff is None or stale_after_days <= 0:
        raise ValueError("exact_as_of_and_positive_freshness_required")
    universe = normalized_universe(universe)
    grouped = {t: [] for t in universe}
    for row in rows:
        key = row.get("ticker")
        if isinstance(key, str) and key.strip().upper() in grouped:
            grouped[key.strip().upper()].append(row)
    result = []
    for ticker, history in grouped.items():
        dated = [(row_clock(r), r) for r in history]
        known = [(t, r) for t, r in dated if t is not None and t <= cutoff]
        unknown = [r for t, r in dated if t is None]
        future = [r for t, r in dated if t is not None and t > cutoff]
        out = {"ticker": ticker, "eligible_equity": ticker not in CASH,
               "attempted": bool(known), "ever_seen": bool(known),
               "ever_estimate_positive": any(finite_flag(r) for _, r in known),
               "future_timestamp_rows": len(future), "unknown_timestamp_rows": len(unknown),
               "legacy_latest_positive": False, "legacy_fresh_positive": False,
               "legacy_fresh_eps_nonzero_evidence": False,
               "legacy_fresh_revenue_nonzero_evidence": False,
               "legacy_fresh_eps_fy2_nonzero_evidence": False,
               "latest_available_at": "", "source_state": "NEVER_ATTEMPTED",
               "frozen_pre_event_usable": None, "next_action": "COLLECT_WHEN_ENTITLED"}
        out.update({key: False for key in ADMISSION_FIELDS})
        if ticker in CASH:
            out.update(source_state="NON_APPLICABLE", next_action="EXCLUDE_FROM_VENDOR_ONLY")
            result.append(out)
            continue
        if not snapshot_inputs_available:
            out.update({key: None for key in COUNT_FIELDS})
            out.update(future_timestamp_rows=None, unknown_timestamp_rows=None,
                       latest_available_at=None, source_state="UNKNOWN_NO_SNAPSHOT_INPUT",
                       next_action="VERIFY_SNAPSHOT_INPUT")
            result.append(out)
            continue
        # Validate version/content before any stored timestamp decides admission.
        if h1 is not None and any(r.get("source_contract") == V2
                                  and not h1.persisted_v2_snapshot_is_valid(r) for r in history):
            out.update(source_state="QUARANTINED_INTEGRITY", next_action="VERIFY_ARCHIVE_INTEGRITY")
            result.append(out)
            continue
        if unknown:
            out.update(source_state="UNKNOWN_TIME", next_action="VERIFY_SOURCE_CLOCKS")
            result.append(out)
            continue
        if not known:
            if future:
                out.update(source_state="QUARANTINED_FUTURE", next_action="VERIFY_SOURCE_CLOCKS")
            result.append(out)
            continue
        latest_time = max(t for t, _ in known)
        latest = [r for t, r in known if t == latest_time]
        out["latest_available_at"] = latest_time.isoformat().replace("+00:00", "Z")
        if len({stable_row(r) for r in latest}) != 1:
            out.update(source_state="QUARANTINED_CONFLICT", next_action="VERIFY_LATEST_VERSIONS")
            result.append(out)
            continue
        row = latest[0]
        fresh = cutoff - latest_time < timedelta(days=stale_after_days)
        contract = row.get("source_contract")
        if contract != V2:
            out["source_state"] = "LEGACY_UNCERTIFIED" if contract in {None, "", "forward-earnings-estimates-v1"} else "UNKNOWN_CONTRACT"
            out["next_action"] = "REFRESH_WITH_ACCEPTED_H1_SOURCE"
            out["legacy_latest_positive"] = finite_flag(row)
            out["legacy_fresh_positive"] = fresh and finite_flag(row)
            for field, key in [("est_eps_fy1", "legacy_fresh_eps_nonzero_evidence"),
                               ("est_rev_fy1", "legacy_fresh_revenue_nonzero_evidence"),
                               ("est_eps_fy2", "legacy_fresh_eps_fy2_nonzero_evidence")]:
                value = numeric(row.get(field))
                out[key] = out["legacy_fresh_positive"] and value is not None and value != 0
            result.append(out)
            continue
        if h1 is None:
            out.update({key: None for key in ADMISSION_FIELDS if key != "research_consumer_eligible"})
            out.update(source_state="BLOCKED_H1_DEPENDENCY", next_action="VERIFY_ACCEPTED_H1_ARTIFACT")
            result.append(out)
            continue
        # Damaged older V2 rows also block this security; no older-value rescue.
        if any(r.get("source_contract") == V2 and not h1.persisted_v2_snapshot_is_valid(r)
               for _, r in known):
            out.update(source_state="QUARANTINED_INTEGRITY", next_action="VERIFY_ARCHIVE_INTEGRITY")
            result.append(out)
            continue
        available = exact_time(h1.availability(row))
        if available is None or available > cutoff:
            out.update(source_state="BLOCKED_AVAILABILITY", next_action="VERIFY_SOURCE_CLOCKS")
            result.append(out)
            continue
        # Finnhub's documented average includes proprietary estimates. An H1
        # structural validation alone cannot certify pure analyst consensus.
        eps_basis_blocked = row.get("fetch_source") == "finnhub"
        out["eps_consensus_basis_state"] = "BLOCKED_PROPRIETARY_BLEND" if eps_basis_blocked else "H1_SOURCE_REFERENCE"
        identities = [r.get("identity") for r in h1.consensus_records(row)]
        core_fields = ("issuer_id", "security_id", "accounting_basis", "currency", "share_or_ADR_unit")
        cores = {tuple(identity.get(k) for k in core_fields) for identity in identities
                 if h1.identity_complete(identity)}
        if len(cores) > 1:
            out.update(source_state="BLOCKED_IDENTITY_CONFLICT", next_action="VERIFY_SECURITY_BASIS_CURRENCY_UNIT")
            result.append(out)
            continue
        eps = [] if eps_basis_blocked else metric_values(row, "EPS", cutoff, h1)
        rev = metric_values(row, "REVENUE", cutoff, h1)
        for values, prefix in [(eps, "eps"), (rev, "revenue")]:
            quarterly = [r for r in values if r["identity"]["period_type"] == "QUARTERLY"]
            for index in (1, 2):
                view_prefix = f"{'eps' if prefix == 'eps' else 'rev'}_fy{index}"
                identity = json.loads(row[view_prefix + "_identity"])
                matches = [r for r in values if r["identity"] == identity
                           and r["identity"]["period_type"] == "ANNUAL"
                           and numeric(r["value"]) == numeric(row.get("est_" + view_prefix))]
                out[f"fresh_{prefix}_fy{index}"] = fresh and len(matches) == 1
            out[f"fresh_{prefix}_future_quarter"] = fresh and bool(quarterly)
            # QUARTERLY identity proves a period, not that it immediately follows
            # the issuer's current fiscal quarter. H1 has no verified calendar
            # anchor; do not infer calendar quarters or bless a distant period.
            out[f"fresh_{prefix}_next_quarter"] = None if fresh and quarterly else False
        out["next_quarter_admission_status"] = "UNKNOWN_NO_VERIFIED_FISCAL_CALENDAR"
        out["fresh_both_fy1"] = out["fresh_eps_fy1"] and out["fresh_revenue_fy1"]
        if out["fresh_both_fy1"]:
            eps_identity = json.loads(row["eps_fy1_identity"])
            rev_identity = json.loads(row["rev_fy1_identity"])
            if any(eps_identity[k] != rev_identity[k]
                   for k in (*core_fields, "fiscal_period_end", "period_type")):
                for key in ADMISSION_FIELDS:
                    out[key] = False
                out.update(source_state="BLOCKED_PERIOD_CONFLICT", next_action="VERIFY_EPS_REVENUE_FISCAL_PERIOD")
                result.append(out)
                continue
        out["source_v2_eligible"] = fresh and bool(eps or rev) and row.get("identity_status") != "AMBIGUOUS"
        if row.get("identity_status") == "AMBIGUOUS":
            for key in ADMISSION_FIELDS:
                out[key] = False
        for days in (30, 90):
            prior = [(t, r) for t, r in known if t <= available - timedelta(days=days)]
            if prior and out["source_v2_eligible"]:
                prior_time = max(t for t, _ in prior)
                boundary = [r for t, r in prior if t == prior_time]
                if len({stable_row(r) for r in boundary}) == 1:
                    out[f"eps_revision_{days}d_eligible"] = out["fresh_eps_fy1"] and h1.same_period_revision(row, boundary[0]) is not None
                    out[f"revenue_revision_{days}d_eligible"] = out["fresh_revenue_fy1"] and h1.same_period_revision(row, boundary[0], prefix="rev_fy1") is not None
                    out[f"revision_{days}d_eligible"] = out[f"eps_revision_{days}d_eligible"] or out[f"revenue_revision_{days}d_eligible"]
        out["source_state"] = "SOURCE_ONLY_FRESH" if out["source_v2_eligible"] else "STALE" if not fresh else "BLOCKED_IDENTITY_OR_MISSING"
        if eps_basis_blocked:
            out["source_state"] = "SOURCE_ONLY_REVENUE_EPS_BASIS_BLOCKED" if out["source_v2_eligible"] else "BLOCKED_CONSENSUS_BASIS"
        out["next_action"] = "WAIT_SEPARATE_CONSUMER_ADMISSION" if out["source_v2_eligible"] else "REFRESH_OR_VERIFY_METADATA"
        result.append(out)
    equities = [r for r in result if r["eligible_equity"]]
    counts = {key: {"count": sum(r[key] is True for r in equities),
                    "unknown": sum(r[key] is None for r in equities),
                    "denominator": len(equities)} for key in COUNT_FIELDS}
    if not snapshot_inputs_available:
        for item in counts.values():
            item["count"] = None
    summary = {"schema_version": "earnings-estimate-coverage-audit-v1", "as_of": as_of,
               "stale_after_days": stale_after_days, "universe_count": len(universe),
               "eligible_equities": len(equities), "non_applicable_assets": len(result)-len(equities),
               "counts": counts, "source_state_counts": dict(Counter(r["source_state"] for r in result)),
               "h1_validator_available": h1 is not None, "frozen_pre_event_usable": "NOT_EVALUATED_NO_EVENT_INPUT",
               "source_only": True, "research_only": True, "historical_pit_certified": False,
               "consumer_admission_status": "BLOCKED_SEPARATE_H2_AUTHORITY",
               "provider_http_requests": 0, "operational_writes": 0}
    summary["next_quarter_contract_status"] = "BLOCKED_NO_VERIFIED_FISCAL_CALENDAR"
    return result, summary


def audit_files(*, universe_path: Path, snapshot_dir: Path, output_dir: Path,
                as_of: str, universe_sha256: str, expected_equities: int,
                stale_after_days: int = 7) -> dict:
    universe_bytes = universe_path.read_bytes()
    if hashlib.sha256(universe_bytes).hexdigest() != universe_sha256:
        raise ValueError("frozen_universe_hash_mismatch")
    universe_frame = pd.read_csv(BytesIO(universe_bytes), dtype=str, keep_default_na=False,
                                 skip_blank_lines=False)
    if "ticker" not in universe_frame:
        raise ValueError("frozen_universe_missing_security_key")
    universe = normalized_universe(universe_frame["ticker"].tolist())
    if sum(t not in CASH for t in universe) != expected_equities:
        raise ValueError("frozen_universe_count_mismatch")
    if output_dir.resolve().is_relative_to(snapshot_dir.resolve()):
        raise ValueError("audit_output_must_be_isolated_from_source")
    snapshot_paths = sorted(snapshot_dir.glob("estimates_*.parquet"))
    for name in ("coverage_by_security.csv", "summary.json"):
        target = output_dir / name
        if target.is_symlink():
            raise ValueError("audit_output_must_not_alias_source")
        for source in [universe_path, *snapshot_paths]:
            if (target.resolve() == source.resolve()
                    or target.exists() and target.samefile(source)):
                raise ValueError("audit_output_must_not_overwrite_frozen_universe_or_snapshot")
    sources, rows = [], []
    for path in snapshot_paths:
        snapshot_bytes = path.read_bytes()
        frame = pd.read_parquet(BytesIO(snapshot_bytes))
        if "ticker" not in frame:
            raise ValueError("snapshot_missing_security_key")
        rows.extend(frame.to_dict("records"))
        sources.append({"path": str(path), "sha256": hashlib.sha256(snapshot_bytes).hexdigest(), "rows": len(frame)})
    by_security, summary = audit_rows(universe, rows, as_of=as_of, stale_after_days=stale_after_days,
                                     snapshot_inputs_available=bool(sources))
    if not sources:
        summary["status"] = "BLOCKED_NO_SNAPSHOT_INPUT"
    else:
        summary["status"] = "AUDITED_LOCAL_INPUT_BYTES"
    summary["inputs"] = {"universe_path": str(universe_path), "universe_sha256": universe_sha256,
                         "snapshot_files": sources}
    output_dir.mkdir(parents=True, exist_ok=True)
    # Replace output directory entries atomically; never open an existing
    # output inode for truncation if a concurrent alias appears after checks.
    for name, content in (("coverage_by_security.csv", pd.DataFrame(by_security).to_csv(index=False)),
                          ("summary.json", json.dumps(summary, indent=2, sort_keys=True)+"\n")):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=output_dir,
                                         prefix=".coverage-audit-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        try:
            temporary.replace(output_dir / name)
        finally:
            temporary.unlink(missing_ok=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, required=True)
    parser.add_argument("--universe-sha256", required=True)
    parser.add_argument("--expected-equities", type=int, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--stale-after-days", type=int, default=7)
    args = parser.parse_args()
    summary = audit_files(universe_path=args.universe, snapshot_dir=args.snapshot_dir,
                          output_dir=args.output_dir, as_of=args.as_of, universe_sha256=args.universe_sha256,
                          expected_equities=args.expected_equities, stale_after_days=args.stale_after_days)
    print(json.dumps({key: summary[key] for key in ("status", "eligible_equities", "counts", "source_state_counts")}))
    return 0 if summary["status"] == "AUDITED_LOCAL_INPUT_BYTES" else 2


if __name__ == "__main__":
    raise SystemExit(main())
