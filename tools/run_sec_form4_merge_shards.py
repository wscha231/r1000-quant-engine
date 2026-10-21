#!/usr/bin/env python3
"""Merge SEC Form 4 shard outputs into canonical PIT evidence files."""
from __future__ import annotations

import argparse
import json
import hashlib
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from r1000_helpers import normalize_cik10  # noqa: E402
from tools.run_sec_ownership_signals import build_form4_signal  # noqa: E402
from tools.run_sec_submissions_collector import atomic_json, content_hash, exact_utc, file_hash  # noqa: E402

DEFAULT_PIT_ROOT = "data_pit/sec"
DEFAULT_OUTPUT_DIR = "outputs/sec_ownership_signals"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def cik10(value: Any) -> str:
    return normalize_cik10(value) or ""


def issuer_identity(row: Any, *, cik_column: str, ticker_column: str) -> tuple[str, str] | None:
    ticker = row.get(ticker_column)
    issuer = cik10(row.get(cik_column))
    if not issuer or not isinstance(ticker, str) or not ticker.strip() or ticker.strip().upper() == "NAN":
        return None
    return issuer, ticker.strip().upper()


def read_many(paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        frame = read_table(path)
        if not frame.empty:
            frame["_source_file"] = path.relative_to(paths[0].parent).as_posix()
            frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def normalize_filings(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    d = frame.copy()
    if "cik10" in d.columns:
        d["cik10"] = d["cik10"].map(cik10)
    for col in ["ticker", "form_type"]:
        if col in d.columns:
            d[col] = d[col].astype(str).str.upper().str.strip()
    if "accession_number" in d.columns:
        d["accession_number"] = d["accession_number"].astype(str).str.strip()
    keys = [c for c in ["cik10", "accession_number", "form_type"] if c in d.columns]
    if keys:
        d = d.drop_duplicates(keys, keep="last")
    sort_cols = [c for c in ["ticker", "filing_date", "accession_number"] if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols, ascending=[True, False, False][: len(sort_cols)])
    return d.reset_index(drop=True)


def normalize_transactions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    d = frame.copy()
    # A complete v2 parse of an accession replaces lossy legacy rows of that
    # accession. It must not double-count both representations of one trade.
    if "parser_schema_version" in d:
        upgraded = d["parser_schema_version"].eq("sec-ownership-345-v2") & ~d["transaction_code"].eq("PARSE_ERROR")
        upgraded_accessions = set(zip(d.loc[upgraded, "issuer_cik10"].map(cik10), d.loc[upgraded, "accession_number"]))
        key = pd.Series(list(zip(d["issuer_cik10"].map(cik10), d["accession_number"])), index=d.index)
        d = d[upgraded | ~key.isin(upgraded_accessions)].copy()
    for col in ["issuer_cik10", "reporting_owner_cik"]:
        if col in d.columns:
            d[col] = d[col].map(cik10)
    if "issuer_ticker" in d.columns:
        d["issuer_ticker"] = d["issuer_ticker"].astype(str).str.upper().str.strip()
    for col in ["transaction_shares", "transaction_price", "transaction_value", "shares_owned_after"]:
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    if "transaction_id" in d:
        typed = d[d["transaction_id"].fillna("").ne("")].copy()
        legacy = d[d["transaction_id"].fillna("").eq("")].copy()
        typed = typed.drop_duplicates(["issuer_cik10", "accession_number", "transaction_id"], keep="last")
    else:
        typed, legacy = d.iloc[0:0].copy(), d.copy()
    keys = [
        col
        for col in [
            "accession_number",
            "reporting_owner_cik",
            "transaction_date",
            "transaction_code",
            "security_title",
            "transaction_shares",
            "transaction_price",
            "is_derivative", "direct_or_indirect", "shares_owned_after",
        ]
        if col in d.columns
    ]
    if keys:
        legacy = legacy.drop_duplicates(keys, keep="last")
    d = pd.concat([legacy, typed], ignore_index=True)
    sort_cols = [c for c in ["issuer_ticker", "available_from", "accession_number"] if c in d.columns]
    if sort_cols:
        d = d.sort_values(sort_cols)
    return d.reset_index(drop=True)


def read_as_of_dates(path: Path, column: str) -> list[str]:
    frame = read_table(path)
    if frame.empty or column not in frame.columns:
        return []
    dates = pd.to_datetime(frame[column], errors="coerce").dropna().dt.normalize().drop_duplicates().sort_values()
    return [(dt + pd.Timedelta(hours=23, minutes=59, seconds=59)).tz_localize("UTC").isoformat() for dt in dates]


def build_signals(tx: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if args.as_of_dates_csv:
        dates = read_as_of_dates(repo_path(args.as_of_dates_csv), args.as_of_date_column)
        parts = [build_form4_signal(tx, as_of=dt, lookback_days=args.window_days) for dt in dates]
        parts = [part.assign(as_of_date=dt) for part, dt in zip(parts, dates) if not part.empty]
        return pd.concat(parts, ignore_index=True, sort=False) if parts else build_form4_signal(tx.iloc[0:0])
    if getattr(args, "signal_mode", "current") == "current":
        decision = exact_utc(getattr(args, "decision_at", None) or datetime.now(timezone.utc).isoformat())
        return build_form4_signal(tx, as_of=decision.isoformat(), lookback_days=args.window_days)
    available = pd.to_datetime(tx.get("available_from"), errors="coerce", utc=True) if not tx.empty else pd.Series(dtype="datetime64[ns, UTC]")
    as_of = available.max().isoformat() if available.notna().any() else None
    return build_form4_signal(tx, as_of=as_of, lookback_days=args.window_days)


def run(args: argparse.Namespace) -> dict[str, Any]:
    pit_root = repo_path(args.pit_root)
    output_dir = repo_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    decision = exact_utc(getattr(args, "decision_at", None) or datetime.now(timezone.utc).isoformat())
    manifest_path = pit_root / "sec_form4_merge_manifest.json"
    atomic_json(manifest_path, {"status": "BUILDING", "decision_at": decision.isoformat(), "current_eligible": False})
    source_age = getattr(args, "max_source_age_hours", 36)
    try:
        max_source_age_hours = float(source_age)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_source_age_hours must be finite and positive") from exc
    if isinstance(source_age, bool) or not math.isfinite(max_source_age_hours) or max_source_age_hours <= 0:
        raise ValueError("max_source_age_hours must be finite and positive")

    filing_paths = [pit_root / "sec_filings_index.parquet"] + sorted((pit_root / "shards").glob("**/sec_filings_index.parquet"))
    tx_paths = [pit_root / "form4_transactions.parquet"] + sorted((pit_root / "shards").glob("**/form4_transactions.parquet"))

    filings = normalize_filings(read_many(filing_paths))
    tx = normalize_transactions(read_many(tx_paths))
    signals = build_signals(tx, args)

    source = {}
    current_index = pd.DataFrame()
    current_tx = tx.iloc[0:0].copy()
    current_source_keys: list[str] = []
    source_path = getattr(args, "source_check_summary", "")
    reasons: list[str] = []
    if source_path:
        source_file = repo_path(source_path)
        source = json.loads(source_file.read_text())
        if source.get("schema_version") != "sec-submissions-source-check-v2" or source.get("status") != "CHECKED":
            reasons.append("SOURCE_CHECK_INCOMPLETE")
        coverage = source.get("source_coverage", {})
        source_checks = source.get("source_checks", [])
        if not isinstance(source_checks, list):
            reasons.append("SOURCE_SCOPE_INCOMPLETE")
            source_checks = []
        if not isinstance(coverage, dict) or coverage.get("complete") is not True or type(coverage.get("requested")) is not int or coverage["requested"] <= 0 or coverage.get("checked") != coverage["requested"] or len(source_checks) != coverage["requested"]:
            reasons.append("SOURCE_SCOPE_INCOMPLETE")
        checked_identities: set[tuple[str, str]] = set()
        checked_tickers: dict[str, str] = {}
        for check in source_checks:
            identity = issuer_identity(check, cik_column="cik10", ticker_column="ticker") if isinstance(check, dict) else None
            if identity is None or identity in checked_identities or (identity[1] in checked_tickers and checked_tickers[identity[1]] != identity[0]):
                reasons.append("SOURCE_IDENTITY_SCOPE_CONFLICT")
            else:
                checked_identities.add(identity)
                checked_tickers[identity[1]] = identity[0]
            if not isinstance(check, dict) or not str(check.get("status", "")).startswith("CHECKED_") or not check.get("checked_at"):
                reasons.append("SOURCE_CHECK_RECORD_MISSING")
            else:
                individual_check = exact_utc(check["checked_at"])
                if individual_check > decision or (decision - individual_check).total_seconds() > max_source_age_hours * 3600:
                    reasons.append("SOURCE_CHECK_STALE_OR_FUTURE")
        if isinstance(coverage, dict) and "checked_ciks" in coverage:
            if type(coverage["checked_ciks"]) is not int or coverage["checked_ciks"] != len({identity[0] for identity in checked_identities}):
                reasons.append("SOURCE_IDENTITY_SCOPE_CONFLICT")
        checked_at = source.get("last_successful_source_check")
        if not checked_at:
            reasons.append("SOURCE_UNAVAILABLE_OR_NOT_CHECKED")
        else:
            checked = exact_utc(checked_at)
            if checked > decision or (decision - checked).total_seconds() > max_source_age_hours * 3600:
                reasons.append("SOURCE_CHECK_STALE_OR_FUTURE")
        local_index = source_file.parent / "sec_filings_index.parquet"
        if not local_index.exists() or source.get("output_sha256", {}).get("parquet") != file_hash(local_index):
            reasons.append("SOURCE_INDEX_HASH_CONFLICT")
        parser_file = source_file.parent / "form4_transactions_summary.json"
        parser_source = json.loads(parser_file.read_text()) if parser_file.exists() else {}
        parsed_table = source_file.parent / "form4_transactions.parquet"
        if parser_source.get("schema_version") != "sec-ownership-parser-receipt-v2":
            reasons.append("PARSER_RECEIPT_MISSING")
        if not parsed_table.is_file() or parser_source.get("output_sha256", {}).get("parquet") != file_hash(parsed_table):
            reasons.append("PARSER_OUTPUT_HASH_CONFLICT")
        else:
            current_tx = pd.read_parquet(parsed_table)
        if parser_source.get("parse_error_rows", 0):
            reasons.append("SOURCE_PARSE_INCOMPLETE")
        completed = parser_source.get("completed", {})
        if local_index.exists():
            requested = pd.read_parquet(local_index)
            current_index = requested
            index_identities = {issuer_identity(row, cik_column="cik10", ticker_column="ticker") for _, row in requested.iterrows()}
            if None in index_identities or not index_identities.issubset(checked_identities):
                reasons.append("SOURCE_IDENTITY_SCOPE_CONFLICT")
            times = pd.to_datetime(requested["available_from"], utc=True, errors="coerce")
            accepted = pd.to_datetime(requested["accepted_at"], utc=True, errors="coerce")
            ownership = requested["form_type"].isin({"3", "3/A", "4", "4/A", "5", "5/A"})
            if (ownership & (times.isna() | accepted.isna() | (accepted > times) | (accepted > decision))).any():
                reasons.append("SOURCE_FILING_CLOCK_CONFLICT")
            eligible = requested[times.between(decision - pd.Timedelta(days=args.window_days), decision) & requested["form_type"].isin({"3", "3/A", "4", "4/A", "5", "5/A"})]
            pending_keys = [":".join([cik10(r.get("cik10")), str(r["accession_number"]), str(r["form_type"])]) for _, r in eligible.iterrows()]
            current_source_keys = sorted(set(pending_keys))
            if any(not isinstance(completed.get(k), dict) or completed[k].get("status") not in {"PARSED", "PARSED_EMPTY"} or type(completed[k].get("row_count")) is not int or completed[k]["row_count"] < 0 for k in pending_keys):
                reasons.append("CURRENT_WINDOW_PARSER_BACKLOG")
            if not current_tx.empty:
                row_keys = current_tx.apply(lambda r: ":".join([cik10(r.get("issuer_cik10")), str(r["accession_number"]), str(r["form_type"])]), axis=1)
                counts = row_keys.value_counts()
                if any(k in completed and isinstance(completed[k], dict) and completed[k].get("row_count") != int(counts.get(k, 0)) for k in pending_keys):
                    reasons.append("PARSER_RECEIPT_ROW_COUNT_CONFLICT")
                current_tx = current_tx[row_keys.isin(pending_keys)].copy()
                expected_clocks = {":".join([cik10(r.get("cik10")), str(r["accession_number"]), str(r["form_type"])]):
                    (pd.to_datetime(r["accepted_at"], utc=True, errors="coerce"), pd.to_datetime(r["available_from"], utc=True, errors="coerce"))
                    for _, r in eligible.iterrows()}
                for _, row in current_tx.iterrows():
                    key = ":".join([cik10(row.get("issuer_cik10")), str(row["accession_number"]), str(row["form_type"])])
                    actual_clocks = tuple(pd.to_datetime(row.get(c), utc=True, errors="coerce") for c in ("accepted_at", "available_from"))
                    if any(pd.isna(t) for t in actual_clocks) or actual_clocks != expected_clocks[key]:
                        reasons.append("PARSER_FILING_CLOCK_CONFLICT")
                        break
                parsed_identities = {issuer_identity(row, cik_column="issuer_cik10", ticker_column="issuer_ticker") for _, row in current_tx.iterrows()}
                if None in parsed_identities or not parsed_identities.issubset(index_identities):
                    reasons.append("SOURCE_IDENTITY_SCOPE_CONFLICT")
            elif any(completed.get(k, {}).get("row_count", 0) != 0 for k in pending_keys if isinstance(completed.get(k), dict)):
                reasons.append("PARSER_RECEIPT_ROW_COUNT_CONFLICT")
    else:
        reasons.append("SOURCE_CHECK_RECEIPT_MISSING")
    is_current = not args.as_of_dates_csv and getattr(args, "signal_mode", "current") == "current"
    if is_current and reasons:
        signals = signals.iloc[0:0].copy()
    elif is_current:
        # Current scope is the freshly checked and hash-bound parser input.
        # The historical merged lake cannot add unverified current issuers.
        signals = build_signals(current_tx, args)

    write_table(filings, pit_root / "sec_filings_index.parquet")
    filings.to_csv(pit_root / "sec_filings_index.csv", index=False)
    write_table(tx, pit_root / "form4_transactions.parquet")
    tx.to_csv(pit_root / "form4_transactions.csv", index=False)
    write_table(signals, pit_root / "sec_ownership_signals.parquet")
    signals.to_csv(output_dir / "form4_latest.csv", index=False)
    signals.head(30).to_csv(output_dir / "ownership_signal_top30.csv", index=False)

    summary = {
        "status": ("BLOCKED" if reasons else "NO_CURRENT_EVENTS" if signals.empty else "completed") if is_current else "HISTORICAL_RESEARCH_ONLY",
        "schema_version": "sec-form4-merge-shards-v2",
        "research_only": True,
        "production_activation_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision_at": decision.isoformat(),
        "historical_as_of": pd.to_datetime(tx["available_from"], utc=True, errors="coerce").max().isoformat() if not tx.empty and pd.to_datetime(tx["available_from"], utc=True, errors="coerce").notna().any() else None,
        "last_successful_source_check": source.get("last_successful_source_check"),
        "latest_accepted_at": pd.to_datetime(current_index["accepted_at"], utc=True, errors="coerce").max().isoformat() if not current_index.empty and pd.to_datetime(current_index["accepted_at"], utc=True, errors="coerce").notna().any() else None,
        "historical_latest_accepted_at": pd.to_datetime(filings["accepted_at"], utc=True, errors="coerce").max().isoformat() if not filings.empty and pd.to_datetime(filings["accepted_at"], utc=True, errors="coerce").notna().any() else None,
        "signal_semantics": "LEGACY_P_CODE_RESEARCH_PROXY_NOT_VERIFIED_OPEN_MARKET",
        "current_scope": "CHECKED_BATCH_ONLY_NOT_WHOLE_UNIVERSE",
        "source_coverage": source.get("source_coverage"),
        "current_source_transaction_rows": int(len(current_tx)) if source else None,
        "current_source_keys": current_source_keys,
        "current_eligible": bool(is_current and not reasons), "blockers": reasons if is_current else [],
        "filing_source_files": len([p for p in filing_paths if p.exists()]),
        "transaction_source_files": len([p for p in tx_paths if p.exists()]),
        "filing_rows": int(len(filings)),
        "transaction_rows": int(len(tx)),
        "signal_rows": int(len(signals)),
        "historical_as_of_dates": int(signals["as_of_date"].nunique()) if not signals.empty and "as_of_date" in signals.columns else 0,
        "outputs": {
            "sec_filings_index": str(pit_root / "sec_filings_index.parquet"),
            "form4_transactions": str(pit_root / "form4_transactions.parquet"),
            "sec_ownership_signals": str(pit_root / "sec_ownership_signals.parquet"),
            "form4_latest": str(output_dir / "form4_latest.csv"),
        },
    }
    output_files = [pit_root / "sec_filings_index.parquet", pit_root / "sec_filings_index.csv", pit_root / "form4_transactions.parquet", pit_root / "form4_transactions.csv", pit_root / "sec_ownership_signals.parquet", output_dir / "form4_latest.csv", output_dir / "ownership_signal_top30.csv"]
    summary["output_sha256"] = {p.name: file_hash(p) for p in output_files}
    summary["code_sha256"] = {"merge": file_hash(Path(__file__)), "signals": file_hash(Path(sys.modules[build_form4_signal.__module__].__file__))}
    summary["config"] = {"window_days": args.window_days, "signal_mode": getattr(args, "signal_mode", "current"), "max_source_age_hours": max_source_age_hours}
    summary["generation_id"] = content_hash({"outputs": summary["output_sha256"], "decision_at": summary["decision_at"], "source": source.get("output_sha256"), "schema_version": summary["schema_version"], "code": summary["code_sha256"], "config": summary["config"]})
    for basename, row_count in [("sec_filings_index", len(filings)), ("form4_transactions", len(tx))]:
        atomic_json(pit_root / f"{basename}_summary.json", {"schema_version": "sec-merged-table-v2", "generation_id": summary["generation_id"], "row_count": row_count,
            "csv_sha256": file_hash(pit_root / f"{basename}.csv"), "parquet_sha256": file_hash(pit_root / f"{basename}.parquet")})
    write_json(output_dir / "ownership_signal_summary.json", summary)
    report = [
        "# SEC Form 4 Shard Merge",
        "",
        f"- status: {summary['status']}",
        f"- filing_rows: {summary['filing_rows']}",
        f"- transaction_rows: {summary['transaction_rows']}",
        f"- signal_rows: {summary['signal_rows']}",
        f"- transaction_source_files: {summary['transaction_source_files']}",
        "",
        "Canonical outputs are point-in-time evidence files. They remain shadow research inputs until broker-ledger validation passes.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    atomic_json(manifest_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-root", default=DEFAULT_PIT_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--as-of-dates-csv", default="", help="Optional CSV/parquet with historical evaluation dates.")
    parser.add_argument("--as-of-date-column", default="rebalance_date")
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--decision-at", default="")
    parser.add_argument("--signal-mode", choices=["current", "historical-data-anchor"], default="current")
    parser.add_argument("--source-check-summary", default="")
    parser.add_argument("--max-source-age-hours", type=float, default=36)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
