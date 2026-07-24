#!/usr/bin/env python3
"""Fail closed unless a Run287 catch-up can use durable Google Drive state."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ENVIRONMENT_CONTRACT_PATH = (
    ROOT / "data_static" / "run287_durable_environment_contract.json"
)
ENVIRONMENT_CONTRACT_SCHEMA = "run287-durable-environment-contract-v2"
ENVIRONMENT_CREDENTIAL_NAMES = {
    "GOOGLE_SERVICE_ACCOUNT_KEY": (
        "RUN287_DURABLE_GOOGLE_SERVICE_ACCOUNT_KEY"
    ),
    "RCLONE_CONFIG_GDRIVE": "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE",
}
VALID_RESTORE_MODE_STATES = {
    "IMMUTABLE_HEAD": {
        "PROVEN_PRESENT",
        "PROVEN_ABSENT",
        "REPAIR_FROM_IMMUTABLE",
    },
    "VERIFIED_CANONICAL": {"PROVEN_PRESENT"},
    "VERIFIED_LEGACY_MIGRATION_SOURCE": {"PROVEN_PRESENT"},
}
TRUE_VALUES = {"1", "true", "yes"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RCLONE_ENVIRONMENT_MARKER_RE = re.compile(
    r"(?m)^# run287_environment_binding=[A-Za-z0-9+/]{32}$"
)


def as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in TRUE_VALUES


def load_environment_contract(
    path: Path | None = None,
) -> dict[str, Any]:
    path = path or ENVIRONMENT_CONTRACT_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != ENVIRONMENT_CONTRACT_SCHEMA:
        raise ValueError("durable environment contract schema is unsupported")
    if payload.get("environment") != "run287-paper-durable":
        raise ValueError("durable environment contract name is invalid")
    attestation = payload.get("attestation")
    if not isinstance(attestation, dict):
        raise ValueError("durable environment attestation contract is missing")
    if (
        attestation.get("secret_name")
        != "RUN287_DURABLE_ENVIRONMENT_ATTESTATION"
    ):
        raise ValueError("durable environment attestation secret name is invalid")
    expected_hash = str(attestation.get("sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(expected_hash):
        raise ValueError("durable environment attestation hash is invalid")
    credential_bindings = payload.get("credential_hmac_sha256")
    if not isinstance(credential_bindings, dict):
        raise ValueError("durable environment credential bindings are missing")
    expected_secret_names = set(ENVIRONMENT_CREDENTIAL_NAMES.values())
    if set(credential_bindings) != expected_secret_names:
        raise ValueError("durable environment credential names are invalid")
    configured_bindings = [
        name
        for name, value in credential_bindings.items()
        if SHA256_RE.fullmatch(str(value or "").strip().lower())
    ]
    if len(configured_bindings) != 1:
        raise ValueError(
            "exactly one durable environment credential binding is required"
        )
    if configured_bindings[0] != "RUN287_DURABLE_RCLONE_CONFIG_GDRIVE":
        raise ValueError(
            "this contract version requires the marker-bound rclone credential"
        )
    for name, value in credential_bindings.items():
        if name not in configured_bindings and value is not None:
            raise ValueError(
                "unconfigured durable credential binding must be null"
            )
    if payload.get("repository_scope_allowed") is not False:
        raise ValueError("repository-scoped durable secrets must be prohibited")
    if payload.get("credential_binding_marker_required") is not True:
        raise ValueError("durable credential binding marker must be required")
    return payload


def verify_environment_attestation(
    *,
    contract: dict[str, Any],
    environment_name: str,
    attestation_value: str,
) -> bool:
    expected_environment = str(contract.get("environment") or "").strip()
    expected_hash = str(
        (contract.get("attestation") or {}).get("sha256") or ""
    ).strip().lower()
    supplied_environment = str(environment_name or "").strip()
    supplied_attestation = str(attestation_value or "")
    if (
        supplied_environment != expected_environment
        or not supplied_attestation
        or not SHA256_RE.fullmatch(expected_hash)
    ):
        return False
    actual_hash = hashlib.sha256(
        supplied_attestation.encode("utf-8")
    ).hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)


def verify_environment_credential_binding(
    *,
    contract: dict[str, Any],
    attestation_value: str,
    credentials: dict[str, str],
) -> bool:
    supplied = {
        variable_name: str(credentials.get(variable_name) or "")
        for variable_name in ENVIRONMENT_CREDENTIAL_NAMES
        if str(credentials.get(variable_name) or "").strip()
    }
    if len(supplied) != 1 or not str(attestation_value or ""):
        return False
    variable_name, credential_value = next(iter(supplied.items()))
    if (
        variable_name == "RCLONE_CONFIG_GDRIVE"
        and not RCLONE_ENVIRONMENT_MARKER_RE.search(credential_value)
    ):
        return False
    secret_name = ENVIRONMENT_CREDENTIAL_NAMES[variable_name]
    expected_hmac = str(
        (contract.get("credential_hmac_sha256") or {}).get(secret_name) or ""
    ).strip().lower()
    if not SHA256_RE.fullmatch(expected_hmac):
        return False
    actual_hmac = hmac.new(
        str(attestation_value).encode("utf-8"),
        credential_value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(actual_hmac, expected_hmac)


def credential_binding_diagnostics(
    *,
    attestation_value: str,
    credentials: dict[str, str],
) -> dict[str, Any]:
    """Return non-secret fingerprints needed to diagnose a fail-closed bind."""

    supplied = {
        variable_name: str(credentials.get(variable_name) or "")
        for variable_name in ENVIRONMENT_CREDENTIAL_NAMES
        if str(credentials.get(variable_name) or "").strip()
    }
    credential_name = next(iter(supplied)) if len(supplied) == 1 else None
    credential_value = supplied.get(credential_name or "", "")
    attestation_sha256 = (
        hashlib.sha256(attestation_value.encode("utf-8")).hexdigest()
        if attestation_value
        else None
    )
    credential_hmac_sha256 = (
        hmac.new(
            attestation_value.encode("utf-8"),
            credential_value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if attestation_value and credential_value
        else None
    )
    return {
        "credential_name": credential_name,
        "credential_count": len(supplied),
        "credential_utf8_bytes": len(credential_value.encode("utf-8")),
        "carriage_return_count": credential_value.count("\r"),
        "line_feed_count": credential_value.count("\n"),
        "trailing_newline": credential_value.endswith(("\r", "\n")),
        "marker_present": bool(
            RCLONE_ENVIRONMENT_MARKER_RE.search(credential_value)
        ),
        "attestation_sha256": attestation_sha256,
        "credential_hmac_sha256": credential_hmac_sha256,
    }


def evaluate_readiness(
    *,
    phase: str,
    catchup_mode: bool,
    auth_configured: bool,
    secret_scope_verified: bool,
    environment_attested: bool,
    credential_attested: bool,
    gdrive_ready: bool,
    rclone_available: bool,
    canonical_state: str,
    durable_restore_mode: str,
    scope_consumed: bool = False,
    scope_reverified: bool = False,
    consumption_reverified: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": "run287-catchup-drive-readiness-v5",
        "phase": phase,
        "catchup_mode": bool(catchup_mode),
        "allowed": True,
        "status": "",
        "message": "",
        "github_env_updates": {},
    }
    if phase == "authentication":
        if catchup_mode and not secret_scope_verified:
            result.update(
                {
                    "allowed": False,
                    "status": "BLOCKED_DURABLE_SECRET_SCOPE",
                    "message": (
                        "[paper-catchup] BLOCKED: durable secret scope "
                        "attestation "
                        "was not verified"
                    ),
                }
            )
        elif auth_configured and not environment_attested:
            result.update(
                {
                    "allowed": False,
                    "status": "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION",
                    "message": (
                        "[paper-catchup] BLOCKED: durable Drive credentials "
                        "lack the environment-scoped attestation"
                    ),
                }
            )
        elif auth_configured and not credential_attested:
            result.update(
                {
                    "allowed": False,
                    "status": "BLOCKED_DURABLE_CREDENTIAL_BINDING",
                    "message": (
                        "[paper-catchup] BLOCKED: durable Drive credential "
                        "does not match the environment-bound contract"
                    ),
                }
            )
        elif auth_configured:
            result["status"] = "READY_AUTH_CONFIGURED_AND_ATTESTED"
        elif catchup_mode:
            result.update(
                {
                    "allowed": False,
                    "status": "BLOCKED_DURABLE_DRIVE_AUTH",
                    "message": (
                        "[paper-catchup] BLOCKED: durable Drive authentication "
                        "is required"
                    ),
                }
            )
        else:
            result["status"] = "READY_NON_CATCHUP_CACHE_ONLY"
            result["github_env_updates"] = {"GDRIVE_READY": "no"}
        return result

    if phase not in {"restored", "mutation"}:
        raise ValueError(f"unsupported phase: {phase}")
    if not catchup_mode:
        result["status"] = "READY_NOT_CATCHUP"
        return result
    if not secret_scope_verified:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_SECRET_SCOPE",
                "message": (
                    "[paper-catchup] BLOCKED: durable restore secret scope "
                    "attestation was not verified"
                ),
            }
        )
        return result
    if not environment_attested:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_ENVIRONMENT_ATTESTATION",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive restore lacks the "
                    "environment-scoped attestation"
                ),
            }
        )
        return result
    if not credential_attested:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_CREDENTIAL_BINDING",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive restore credential "
                    "does not match the environment-bound contract"
                ),
            }
        )
        return result
    if not gdrive_ready or not rclone_available:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_DRIVE_RESTORE",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive restore is unavailable"
                ),
            }
        )
        return result
    normalized_state = str(canonical_state or "").strip().upper()
    normalized_mode = str(durable_restore_mode or "").strip().upper()
    if normalized_mode not in VALID_RESTORE_MODE_STATES:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_DRIVE_ANCHOR",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive restore did not "
                    "produce a verified remote anchor"
                ),
            }
        )
        return result
    if normalized_state not in VALID_RESTORE_MODE_STATES[normalized_mode]:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_DURABLE_DRIVE_STATE",
                "message": (
                    "[paper-catchup] BLOCKED: durable Drive canonical state was "
                    "not classified"
                ),
            }
        )
        return result
    if phase == "mutation" and not scope_consumed:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_SCOPE_ATTESTATION_NOT_CONSUMED",
                "message": (
                    "[paper-catchup] BLOCKED: owner scope attestation was not "
                    "consumed exactly once"
                ),
            }
        )
        return result
    if phase == "mutation" and not scope_reverified:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_SCOPE_ATTESTATION_NOT_REVERIFIED",
                "message": (
                    "[paper-catchup] BLOCKED: owner scope attestation was not "
                    "reverified immediately before mutation"
                ),
            }
        )
        return result
    if phase == "mutation" and not consumption_reverified:
        result.update(
            {
                "allowed": False,
                "status": "BLOCKED_SCOPE_CONSUMPTION_NOT_REVERIFIED",
                "message": (
                    "[paper-catchup] BLOCKED: one-time consumption record was "
                    "not reverified immediately before mutation"
                ),
            }
        )
        return result
    result["status"] = "READY_DURABLE_DRIVE"
    result["canonical_state"] = normalized_state
    result["durable_restore_mode"] = normalized_mode
    return result


def append_github_env(path_value: str, updates: dict[str, str]) -> None:
    if not updates or not str(path_value or "").strip():
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in updates.items():
            handle.write(f"{key}={value}\n")


def evaluate_environment(
    phase: str,
    *,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    contract = load_environment_contract(contract_path)
    attestation_value = os.environ.get(
        "RUN287_DURABLE_ENVIRONMENT_ATTESTATION", ""
    )
    environment_attested = verify_environment_attestation(
        contract=contract,
        environment_name=os.environ.get(
            "RUN287_DURABLE_ENVIRONMENT_NAME", ""
        ),
        attestation_value=attestation_value,
    )
    credentials = {
        variable_name: os.environ.get(variable_name, "")
        for variable_name in ENVIRONMENT_CREDENTIAL_NAMES
    }
    credential_attested = verify_environment_credential_binding(
        contract=contract,
        attestation_value=attestation_value,
        credentials=credentials,
    )
    result = evaluate_readiness(
        phase=phase,
        catchup_mode=as_bool(os.environ.get("PAPER_CATCHUP_MODE")),
        auth_configured=bool(
            str(os.environ.get("RCLONE_CONFIG_GDRIVE") or "").strip()
            or str(os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY") or "").strip()
        ),
        secret_scope_verified=as_bool(
            os.environ.get("RUN287_DURABLE_SCOPE_VERIFIED")
        ),
        scope_consumed=as_bool(
            os.environ.get("RUN287_DURABLE_SCOPE_CONSUMED")
        ),
        scope_reverified=as_bool(
            os.environ.get("RUN287_DURABLE_SCOPE_REVERIFIED")
        ),
        consumption_reverified=as_bool(
            os.environ.get(
                "RUN287_DURABLE_SCOPE_CONSUMPTION_REVERIFIED"
            )
        ),
        environment_attested=environment_attested,
        credential_attested=credential_attested,
        gdrive_ready=as_bool(os.environ.get("GDRIVE_READY")),
        rclone_available=shutil.which("rclone") is not None,
        canonical_state=str(
            os.environ.get("PAPER_CANONICAL_REMOTE_STATE") or ""
        ),
        durable_restore_mode=str(
            os.environ.get("PAPER_DURABLE_RESTORE_MODE") or ""
        ),
    )
    if (
        phase == "authentication"
        and environment_attested
        and not credential_attested
    ):
        result["credential_binding_diagnostics"] = (
            credential_binding_diagnostics(
                attestation_value=attestation_value,
                credentials=credentials,
            )
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=("authentication", "restored", "mutation"),
    )
    args = parser.parse_args()
    result = evaluate_environment(args.phase)
    append_github_env(
        os.environ.get("GITHUB_ENV", ""),
        result.get("github_env_updates") or {},
    )
    if result.get("message"):
        print(result["message"])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
