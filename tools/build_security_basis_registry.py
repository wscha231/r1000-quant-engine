#!/usr/bin/env python3
"""Build fail-closed COMMON/ADR security-basis evidence for Phase2A ER.

This adapter does not infer corporate-action or ADR share basis from a ticker,
provider name, or current price. Every admitted basis must be reviewed,
timestamped evidence available no later than the decision time. Missing
evidence preserves the security row and blocks only that row.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "run287-security-basis-registry-v1"
READY = "READY_SECURITY_BASIS_REGISTRY"
PARTIAL = "PARTIAL_BLOCKED_SECURITY_BASIS_REGISTRY"
ROW_READY = "READY_SECURITY_BASIS"
ROW_BLOCKED = "BLOCKED_SECURITY_BASIS"
ACCEPTED_INSTRUMENTS = {"COMMON", "ADR"}
ACCEPTED_CORPORATE_ACTION_BASES = {
    "SPLIT_AND_DIVIDEND_ADJUSTED_TOTAL_RETURN",
    "SPLIT_DIVIDEND_ADJUSTED_TOTAL_RETURN",
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]*$")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate_json_key:{key}")
        out[key] = value
    return out


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )


def utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_timestamp:{field}")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid_timestamp:{field}") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"naive_timestamp:{field}")
    return stamp.astimezone(timezone.utc)


def canonical_id(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not ID_RE.fullmatch(value)
    ):
        raise ValueError(f"invalid_identity:{field}")
    return value


def canonical_ticker(value: Any) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not TICKER_RE.fullmatch(value)
    ):
        raise ValueError("invalid_identity:ticker")
    return value


def finite_positive(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def load_identity_rows(value: Any) -> list[dict[str, Any]]:
    rows = value.get("securities") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not rows:
        raise ValueError("identity_registry_missing_rows")
    seen_ids: set[str] = set()
    seen_tickers: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("identity_registry_row_not_object")
        row = dict(raw)
        security_id = canonical_id(row.get("security_id"), "security_id")
        canonical_id(row.get("issuer_id"), "issuer_id")
        ticker = canonical_ticker(row.get("ticker"))
        utc(row.get("available_at"), "identity.available_at")
        if security_id in seen_ids:
            raise ValueError("identity_registry_duplicate_security_id")
        if ticker in seen_tickers and seen_tickers[ticker] != security_id:
            raise ValueError("identity_registry_ticker_not_one_to_one")
        seen_ids.add(security_id)
        seen_tickers[ticker] = security_id
        out.append(row)
    return out


def load_evidence_rows(value: Any) -> dict[str, dict[str, Any]]:
    rows = value.get("evidence") if isinstance(value, dict) else value
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise ValueError("basis_evidence_rows_invalid")
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("basis_evidence_row_not_object")
        security_id = canonical_id(
            raw.get("security_id"), "evidence.security_id"
        )
        if security_id in out:
            raise ValueError("basis_evidence_duplicate_security_id")
        out[security_id] = dict(raw)
    return out


def reviewed_evidence(
    value: Any,
    *,
    decision_at: datetime,
    label: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, dict):
        return None, [f"{label}_evidence_missing"]
    blockers: list[str] = []
    if value.get("verified") is not True:
        blockers.append(f"{label}_unverified")
    if value.get("review_status") != "approved":
        blockers.append(f"{label}_review_unapproved")
    if value.get("exact_available_from") is not True:
        blockers.append(f"{label}_availability_not_exact")
    try:
        available = utc(value.get("available_at"), f"{label}.available_at")
        if available > decision_at:
            blockers.append(f"{label}_future_availability")
    except ValueError as exc:
        blockers.append(str(exc))
        available = None
    source_url = value.get("source_url")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        blockers.append(f"{label}_source_url_invalid")
    source_sha = str(value.get("source_sha256") or "").lower()
    if not SHA_RE.fullmatch(source_sha):
        blockers.append(f"{label}_source_sha256_invalid")
    if blockers:
        return None, sorted(set(blockers))
    normalized = dict(value)
    normalized["available_at"] = (
        available.isoformat().replace("+00:00", "Z")
    )
    normalized["source_sha256"] = source_sha
    return normalized, []


def build_registry(
    identity_doc: Any,
    evidence_doc: Any,
    decision_at_value: Any,
) -> dict[str, Any]:
    decision_at = utc(decision_at_value, "decision_at")
    identities = load_identity_rows(identity_doc)
    evidence = load_evidence_rows(evidence_doc)
    identity_ids = {row["security_id"] for row in identities}
    unknown_evidence = sorted(set(evidence) - identity_ids)
    if unknown_evidence:
        raise ValueError(
            "basis_evidence_unknown_security_id:" + ",".join(unknown_evidence)
        )

    output_rows: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    ready_count = 0
    for identity in identities:
        security_id = identity["security_id"]
        instrument = str(identity.get("instrument") or "").upper()
        identity_available = utc(
            identity.get("available_at"), "identity.available_at"
        )
        causal_times = [identity_available]
        blockers: list[str] = []
        if identity.get("identity_verified") is not True:
            blockers.append("security_identity_unverified")
        if identity.get("research_eligible") is not True:
            blockers.append("research_eligibility_unverified")
        if identity_available > decision_at:
            blockers.append("future_identity_availability")
        if instrument not in ACCEPTED_INSTRUMENTS:
            blockers.append("unsupported_or_missing_share_basis")

        evidence_row = evidence.get(security_id, {})
        corporate, corporate_blockers = reviewed_evidence(
            evidence_row.get("corporate_action"),
            decision_at=decision_at,
            label="corporate_action",
        )
        blockers.extend(corporate_blockers)
        corporate_verified = False
        corporate_basis = None
        corporate_fields: dict[str, Any] = {}
        if corporate is not None:
            basis = corporate.get("basis")
            if basis not in ACCEPTED_CORPORATE_ACTION_BASES:
                blockers.append("corporate_action_basis_unverified")
            else:
                corporate_verified = True
                corporate_basis = basis
                causal_times.append(
                    utc(
                        corporate["available_at"],
                        "corporate_action.available_at",
                    )
                )
                corporate_fields = {
                    "corporate_action_evidence_available_at": corporate[
                        "available_at"
                    ],
                    "corporate_action_source_url": corporate["source_url"],
                    "corporate_action_source_sha256": corporate[
                        "source_sha256"
                    ],
                }

        adr_ratio = None
        adr_verified = False
        underlying_currency = None
        adr_fields: dict[str, Any] = {}
        if instrument == "ADR":
            adr, adr_blockers = reviewed_evidence(
                evidence_row.get("adr_share_basis"),
                decision_at=decision_at,
                label="adr_share_basis",
            )
            blockers.extend(adr_blockers)
            if adr is not None:
                ratio = finite_positive(adr.get("adr_ratio"))
                currency = str(
                    adr.get("underlying_currency") or ""
                ).upper()
                if ratio is None:
                    blockers.append("adr_ratio_invalid")
                if not CURRENCY_RE.fullmatch(currency):
                    blockers.append("adr_underlying_currency_invalid")
                if ratio is not None and CURRENCY_RE.fullmatch(currency):
                    adr_ratio = ratio
                    underlying_currency = currency
                    adr_verified = True
                    causal_times.append(
                        utc(
                            adr["available_at"],
                            "adr_share_basis.available_at",
                        )
                    )
                    adr_fields = {
                        "adr_ratio_available_at": adr["available_at"],
                        "adr_source_url": adr["source_url"],
                        "adr_source_sha256": adr["source_sha256"],
                    }

        blockers = sorted(set(blockers))
        for blocker in blockers:
            blocker_counts[blocker] = (
                blocker_counts.get(blocker, 0) + 1
            )
        if not blockers:
            ready_count += 1

        output_rows.append(
            {
                **identity,
                "instrument": instrument,
                "available_at": max(causal_times)
                .isoformat()
                .replace("+00:00", "Z"),
                "corporate_action_verified": corporate_verified,
                "corporate_action_basis": corporate_basis,
                "adr_share_basis_verified": (
                    adr_verified if instrument == "ADR" else None
                ),
                "adr_ratio": adr_ratio,
                "underlying_currency": underlying_currency,
                "basis_status": (
                    ROW_READY if not blockers else ROW_BLOCKED
                ),
                "basis_blockers": blockers,
                **corporate_fields,
                **adr_fields,
            }
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            READY if ready_count == len(output_rows) else PARTIAL
        ),
        "decision_at": decision_at.isoformat().replace("+00:00", "Z"),
        "requested_security_count": len(output_rows),
        "ready_security_count": ready_count,
        "blocked_security_count": len(output_rows) - ready_count,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "securities": output_rows,
        "research_only": True,
        "selector_eligible": False,
        "target_authority": False,
        "order_authority": False,
    }
    payload["artifact_sha256"] = sha256_bytes(canonical_bytes(payload))
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    identity_path = Path(args.identity_source)
    evidence_path = Path(args.basis_evidence)
    output = build_registry(
        read_json(identity_path),
        read_json(evidence_path),
        args.decision_at,
    )
    old_hash = output.pop("artifact_sha256")
    output["inputs"] = {
        "identity_source": fingerprint(identity_path),
        "basis_evidence": fingerprint(evidence_path),
    }
    output["pre_input_fingerprint_artifact_sha256"] = old_hash
    output["artifact_sha256"] = sha256_bytes(canonical_bytes(output))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-source", required=True)
    parser.add_argument("--basis-evidence", required=True)
    parser.add_argument("--decision-at", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    output = run(parse_args())
    print(
        json.dumps(
            {
                key: output[key]
                for key in (
                    "status",
                    "requested_security_count",
                    "ready_security_count",
                    "blocked_security_count",
                    "artifact_sha256",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
