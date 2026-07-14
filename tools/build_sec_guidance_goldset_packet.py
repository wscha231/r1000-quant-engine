#!/usr/bin/env python3
"""Freeze a dual-review packet for the bounded SEC guidance scout.

The packet contains all bounded filings, including heuristic-negative filings,
so precision and recall can both be measured. It does not infer labels, join
returns, build a signal, or mutate a portfolio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_sec_management_guidance_scout import (
    plain_text,
    raw_acceptance_utc,
    sgml_documents,
    timestamps_equal,
)


DEFAULT_CONTRACT = "docs/run287_sec_guidance_goldset_contract.json"
DEFAULT_SCOUT_CONTRACT = "docs/run287_sec_management_guidance_scout_contract.json"
DEFAULT_SCOUT_OUTPUT = "outputs/run287_sec_management_guidance_scout_20260714_hardened_v3"
DEFAULT_OUTPUT = "outputs/run287_sec_guidance_goldset_packet_20260714"


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def joined_tokens(values: pd.Series) -> str:
    tokens: set[str] = set()
    for value in values.dropna().astype(str):
        tokens.update(token for token in value.split("|") if token)
    return "|".join(sorted(tokens))


def candidate_summary(candidates: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    if candidates.empty:
        return {}
    grouped = candidates.groupby(["ticker", "accession_number"], sort=True, as_index=False).agg(
        heuristic_candidate_passage_count=("candidate_id", "size"),
        heuristic_metrics=("metrics", joined_tokens),
        heuristic_document_types=("document_type", joined_tokens),
        heuristic_source_sha256=("source_sha256", "first"),
    )
    return {
        (str(row["ticker"]), str(row["accession_number"])): row.to_dict()
        for _, row in grouped.iterrows()
    }


def candidate_snippets(candidates: pd.DataFrame) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    if candidates.empty:
        return out
    for key, frame in candidates.groupby(["ticker", "accession_number"], sort=True):
        snippets = []
        seen: set[str] = set()
        for value in frame["snippet"].fillna("").astype(str):
            normalized = re.sub(r"\s+", " ", value).strip()
            if normalized and normalized not in seen:
                snippets.append(normalized)
                seen.add(normalized)
        out[(str(key[0]), str(key[1]))] = snippets
    return out


def review_text(
    *,
    metadata: dict[str, Any],
    raw: bytes,
    allowed_document_types: set[str],
    snippets: list[str],
) -> str:
    decoded = raw.decode("utf-8", errors="replace")
    sections: list[str] = []
    for document_type, document in sgml_documents(decoded):
        if document_type not in allowed_document_types:
            continue
        text = plain_text(document)
        if text:
            sections.append(f"## DOCUMENT {document_type}\n\n{text}")
    if not sections:
        sections.append("## DOCUMENT NONE\n\nNo allowed review document text was extracted.")
    candidate_block = "\n\n".join(f"[{idx}] {value}" for idx, value in enumerate(snippets, start=1))
    candidate_block = candidate_block or "No heuristic candidate passage. Review the full text for false negatives."
    header = [
        "# SEC guidance gold-set review packet",
        "",
        f"- review_row_id: `{metadata['review_row_id']}`",
        f"- ticker: `{metadata['ticker']}`",
        f"- accession_number: `{metadata['accession_number']}`",
        f"- form_type: `{metadata['form_type']}`",
        f"- accepted_at: `{metadata['accepted_at']}`",
        f"- source_sha256: `{metadata['source_sha256']}`",
        f"- heuristic_candidate_detected: `{metadata['heuristic_candidate_detected']}`",
        "",
        "## Heuristic passages",
        "",
        candidate_block,
        "",
        "## Full allowed document text",
        "",
    ]
    return "\n".join(header + sections) + "\n"


def validate_source(
    *,
    contract: dict[str, Any],
    scout_contract: dict[str, Any],
    summary: dict[str, Any],
    downloads: pd.DataFrame,
) -> int:
    expected = int(contract["expected_filing_count"])
    gates = contract["required_source_gates"]
    blockers: list[str] = []
    if summary.get("schema_version") != contract["source_scout_schema_version"]:
        blockers.append("scout_schema_version_mismatch")
    if summary.get("status") != gates["scout_status"]:
        blockers.append("scout_status_not_ready")
    for field in ("exact_acceptance_ratio", "raw_header_acceptance_match_ratio"):
        if float(summary.get(field, 0.0)) != float(gates[field]):
            blockers.append(f"{field}_mismatch")
    for field in ("quarantined_missing_acceptance_count", "raw_header_acceptance_mismatch_count"):
        if int(summary.get(field, -1)) != int(gates[field]):
            blockers.append(f"{field}_nonzero")
    if len(downloads) != expected:
        blockers.append(f"download_row_count:{len(downloads)}!=expected:{expected}")
    if downloads.duplicated(["ticker", "accession_number"]).any():
        blockers.append("duplicate_ticker_accession")
    if not downloads.empty and not downloads["download_success"].map(bool_value).all():
        blockers.append("download_failure_present")
    if not downloads.empty and not downloads["raw_header_exact_match"].map(bool_value).all():
        blockers.append("raw_header_acceptance_mismatch_present")
    if scout_contract.get("source", {}).get("filed_date_fallback_allowed") is not False:
        blockers.append("filed_date_fallback_not_false")
    for field in ("return_join_allowed", "portfolio_ab_allowed", "portfolio_mutation_allowed", "fullrun_allowed", "production_allowed", "live_trading_allowed"):
        if summary.get(field) is not False:
            blockers.append(f"unsafe_summary_flag:{field}")
    if blockers:
        raise ValueError("BLOCKED_GOLDSET_SOURCE:" + "|".join(blockers))
    return expected


def empty_component_template(reviewer_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "review_row_id",
            "reviewer_id",
            "component_id",
            "metric",
            "value_kind",
            "period_type",
            "fiscal_period",
            "period_start",
            "period_end",
            "low_value",
            "high_value",
            "midpoint_value",
            "currency",
            "unit",
            "gaap_basis",
            "share_basis",
            "accepted_text_span",
            "prior_guidance_accession",
            "comparison_status",
            "notes",
        ]
    ).assign(reviewer_id=reviewer_id)


def build_packet(
    *,
    contract_path: str | Path,
    scout_contract_path: str | Path,
    scout_output: str | Path,
    cache_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    contract_file = repo_path(contract_path)
    scout_contract_file = repo_path(scout_contract_path)
    scout_dir = repo_path(scout_output)
    cache_root = repo_path(cache_dir)
    output = repo_path(output_dir)
    contract = read_json(contract_file)
    scout_contract = read_json(scout_contract_file)
    summary_path = scout_dir / "summary.json"
    downloads_path = scout_dir / "download_log.csv"
    candidates_path = scout_dir / "guidance_candidates.csv"
    summary = read_json(summary_path)
    downloads = pd.read_csv(downloads_path, low_memory=False).fillna("")
    candidates = pd.read_csv(candidates_path, low_memory=False).fillna("")
    expected = validate_source(
        contract=contract,
        scout_contract=scout_contract,
        summary=summary,
        downloads=downloads,
    )
    allowed_doc_types = {str(value).upper() for value in scout_contract["source"]["allowed_document_types"]}
    candidate_map = candidate_summary(candidates)
    snippet_map = candidate_snippets(candidates)
    output.mkdir(parents=True, exist_ok=True)
    text_dir = output / "review_text"
    text_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    for _, source in downloads.sort_values(["ticker", "accepted_at", "accession_number"], kind="stable").iterrows():
        ticker = str(source["ticker"]).upper().strip()
        accession = str(source["accession_number"]).strip()
        cache_path = Path(str(source.get("cache_path") or ""))
        if not cache_path.is_absolute():
            cache_path = cache_root / ticker / f"{accession.replace('-', '')}.txt"
        if not cache_path.exists():
            raise ValueError(f"BLOCKED_GOLDSET_SOURCE:missing_cache:{ticker}:{accession}")
        raw = cache_path.read_bytes()
        source_hash = sha256_bytes(raw)
        logged_hash = str(source.get("source_sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", logged_hash) or logged_hash != source_hash:
            raise ValueError(f"BLOCKED_GOLDSET_SOURCE:source_hash_mismatch:{ticker}:{accession}")
        raw_header = raw_acceptance_utc(raw)
        if not timestamps_equal(raw_header, source.get("accepted_at", "")):
            raise ValueError(f"BLOCKED_GOLDSET_SOURCE:raw_acceptance_mismatch:{ticker}:{accession}")
        key = (ticker, accession)
        candidate = candidate_map.get(key, {})
        row_id = hashlib.sha256(
            f"{contract['schema_version']}|{ticker}|{accession}|{source_hash}".encode("utf-8")
        ).hexdigest()[:24]
        row = {
            "review_row_id": row_id,
            "ticker": ticker,
            "cik10": str(source.get("cik10") or ""),
            "accession_number": accession,
            "form_type": str(source.get("form_type") or ""),
            "filing_date": str(source.get("filing_date") or ""),
            "accepted_at": str(source.get("accepted_at") or ""),
            "raw_header_accepted_at": raw_header,
            "acceptance_exact": True,
            "source_url": str(source.get("source_url") or ""),
            "source_cache_path": display_path(cache_path),
            "source_sha256": source_hash,
            "heuristic_candidate_detected": bool(candidate),
            "heuristic_candidate_passage_count": int(candidate.get("heuristic_candidate_passage_count", 0)),
            "heuristic_metrics": str(candidate.get("heuristic_metrics", "")),
            "heuristic_document_types": str(candidate.get("heuristic_document_types", "")),
        }
        text = review_text(
            metadata=row,
            raw=raw,
            allowed_document_types=allowed_doc_types,
            snippets=snippet_map.get(key, []),
        )
        text_path = text_dir / f"{row_id}.md"
        text_path.write_text(text, encoding="utf-8")
        row["review_text_path"] = display_path(text_path)
        row["review_text_sha256"] = sha256_file(text_path)
        manifest_rows.append(row)

    manifest = pd.DataFrame(manifest_rows).sort_values(
        ["ticker", "accepted_at", "accession_number"], kind="stable"
    ).reset_index(drop=True)
    if len(manifest) != expected or not manifest["acceptance_exact"].all():
        raise ValueError("BLOCKED_GOLDSET_SOURCE:manifest_integrity")
    manifest_path = output / "review_manifest.csv"
    manifest.to_csv(manifest_path, index=False)

    filing_label_columns = [
        "review_row_id",
        "ticker",
        "accession_number",
        "reviewer_id",
        "filing_class",
        "precision_label",
        "exclusion_reason",
        "semantic_event_id",
        "republication_of_review_row_id",
        "reviewed_at_utc",
        "notes",
    ]
    template_paths: list[Path] = []
    for reviewer_id in contract["reviewer_ids"]:
        labels = manifest[["review_row_id", "ticker", "accession_number"]].copy()
        labels["reviewer_id"] = reviewer_id
        for column in filing_label_columns[4:]:
            labels[column] = ""
        filing_path = output / f"filing_labels_{reviewer_id}.csv"
        labels[filing_label_columns].to_csv(filing_path, index=False)
        component_path = output / f"component_labels_{reviewer_id}.csv"
        empty_component_template(reviewer_id).to_csv(component_path, index=False)
        template_paths.extend([filing_path, component_path])

    summary_out = {
        "schema_version": contract["schema_version"],
        "status": "READY_FOR_DUAL_REVIEW",
        "filing_count": int(len(manifest)),
        "ticker_count": int(manifest["ticker"].nunique()),
        "heuristic_candidate_filing_count": int(manifest["heuristic_candidate_detected"].sum()),
        "heuristic_negative_filing_count": int((~manifest["heuristic_candidate_detected"]).sum()),
        "reviewer_ids": contract["reviewer_ids"],
        "input_hashes": {
            "contract_sha256": sha256_file(contract_file),
            "scout_contract_sha256": sha256_file(scout_contract_file),
            "scout_summary_sha256": sha256_file(summary_path),
            "download_log_sha256": sha256_file(downloads_path),
            "guidance_candidates_sha256": sha256_file(candidates_path),
        },
        "output_hashes": {
            "review_manifest_sha256": sha256_file(manifest_path),
            **{display_path(path): sha256_file(path) for path in template_paths},
        },
        "return_join_allowed": False,
        "portfolio_ab_allowed": False,
        "portfolio_mutation_allowed": False,
        "fullrun_allowed": False,
        "production_allowed": False,
        "live_trading_allowed": False,
    }
    summary_file = output / "summary.json"
    summary_file.write_text(json.dumps(summary_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = [
        "# SEC guidance gold-set review packet",
        "",
        f"- status: `{summary_out['status']}`",
        f"- filings: `{summary_out['filing_count']}` across `{summary_out['ticker_count']}` tickers",
        f"- heuristic candidate / negative: `{summary_out['heuristic_candidate_filing_count']} / {summary_out['heuristic_negative_filing_count']}`",
        f"- reviewers: `{', '.join(summary_out['reviewer_ids'])}`",
        "",
        "Both reviewers receive identical source evidence but separate blank label files. Candidate-negative filings must be reviewed for false negatives.",
        "No returns, portfolio state, or other outcome labels are included.",
    ]
    (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary_out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=DEFAULT_CONTRACT)
    parser.add_argument("--scout-contract", default=DEFAULT_SCOUT_CONTRACT)
    parser.add_argument("--scout-output", default=DEFAULT_SCOUT_OUTPUT)
    parser.add_argument("--cache-dir", default="data_raw/sec/guidance_scout")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        contract_path=args.contract,
        scout_contract_path=args.scout_contract,
        scout_output=args.scout_output,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
