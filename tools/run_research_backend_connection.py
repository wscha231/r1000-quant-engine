#!/usr/bin/env python3
"""One-shot supplied-byte research connection. No collection or economic writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "research-backend-bundle-v1"
MAX_FILE = 4 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_OUTPUT = 16 * 1024 * 1024
RESEARCH_KEYS = ("identities", "events", "registry", "er", "cohort", "delta_previous", "delta_current", "a3_packet")
REQUIRED_CODE = (
    "tools/run_research_backend_connection.py",
    "research/research_path_connection_v1.py",
    "tools/research_risk_connection.py",
)
DEPENDENCY_SOURCES = (
    "research/a2_research_intake_v1.py", "research/a3_candidate_packet_v1.py",
    "research/candidate_registry_v1.py", "tools/chameleon_market_context_v2.py",
    "tools/candidate_reassessment_bridge.py", "tools/free_market_context.py",
    "tools/run287_hold_exit_policy.py", "tools/run_alphaops_vnext_policy_replay.py",
    "tools/security_lifecycle.py",
)
AUTHORITY_KEYS = (
    "selector", "er", "target", "portfolio", "paper", "broker", "orders",
    "promotion", "execute", "production", "dispatch", "admission", "ledger",
    "canonical_write", "learning", "reuse", "current", "fullrun", "live",
)


class BundleError(ValueError):
    """A bounded public reason code, without upstream exception text."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value) -> bytes:
    try:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise BundleError("OUTPUT_JSON_REFUSED") from None
    if len(raw) > MAX_OUTPUT:
        raise BundleError("OUTPUT_BUDGET")
    return raw


def strict_json(raw: bytes):
    if not isinstance(raw, bytes) or len(raw) > MAX_FILE:
        raise BundleError("INPUT_BYTE_BUDGET")
    depth = tokens = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
            tokens += 1
        elif char in (91, 123):
            depth += 1
            tokens += 1
            if depth > 32:
                raise BundleError("JSON_DEPTH_BUDGET")
        elif char in (93, 125):
            depth -= 1
        elif char in (44, 58):
            tokens += 1
        if tokens > 100000:
            raise BundleError("JSON_TOKEN_BUDGET")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BundleError("JSON_DUPLICATE_KEY")
            result[key] = value
        return result

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise BundleError("JSON_NONFINITE")
        return value

    def constant(_):
        raise BundleError("JSON_NONFINITE")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                           parse_float=number, parse_constant=constant)
    except BundleError:
        raise
    except (UnicodeError, ValueError, RecursionError, OverflowError):
        raise BundleError("JSON_INVALID") from None
    todo = [value]
    nodes = 0
    while todo:
        current = todo.pop()
        nodes += 1
        if nodes > 50000:
            raise BundleError("JSON_NODE_BUDGET")
        if isinstance(current, dict):
            todo.extend(current.values())
        elif isinstance(current, list):
            todo.extend(current)
    return value


def clock(value) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise BundleError("CLOCK_INVALID")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        return instant.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise BundleError("CLOCK_INVALID") from None


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BundleError("SHA256_INVALID")
    return value


def _no_links(path: Path):
    # Windows junctions are reparse points even where is_symlink() is false.
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BundleError("PATH_LINK_REFUSED")


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _absolute(value, *, exists=False) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise BundleError("ABSOLUTE_PATH_REQUIRED")
    path = Path(value)
    _no_links(path)
    try:
        return path.resolve(strict=exists)
    except (OSError, RuntimeError):
        raise BundleError("PATH_UNAVAILABLE") from None


def _relative(root: Path, value) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise BundleError("RELATIVE_PATH_INVALID")
    if any(part in ("", ".", "..") for part in value.split("/")) or Path(value).is_absolute():
        raise BundleError("PATH_TRAVERSAL_REFUSED")
    path = root / value
    _no_links(path)
    if root not in path.resolve().parents:
        raise BundleError("PATH_TRAVERSAL_REFUSED")
    return path


def _read(path: Path, limit: int) -> bytes:
    _no_links(path)
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise BundleError("INPUT_BYTE_BUDGET")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
        current = path.stat(follow_symlinks=False)
    except BundleError:
        raise
    except OSError:
        raise BundleError("INPUT_UNAVAILABLE") from None
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if len(raw) > limit:
        raise BundleError("INPUT_BYTE_BUDGET")
    if stamp(before) != stamp(after) or stamp(after) != stamp(current):
        raise BundleError("INPUT_CHANGED_DURING_READ")
    return raw


def _descriptor(root, descriptor, cutoff, budget, *, parse=True):
    expected = {"path", "expected_sha256", "available_at", "collected_at", "valid_through"}
    if not isinstance(descriptor, dict) or set(descriptor) != expected:
        raise BundleError("DESCRIPTOR_INVALID")
    available = clock(descriptor["available_at"])
    collected = clock(descriptor["collected_at"])
    expires = clock(descriptor["valid_through"])
    if not available <= collected <= cutoff:
        raise BundleError("INPUT_FUTURE_OR_TIME_ORDER")
    if expires <= cutoff or expires <= collected:
        raise BundleError("INPUT_STALE")
    expected_sha = _sha(descriptor["expected_sha256"])
    raw = _read(_relative(root, descriptor["path"]), MAX_FILE)
    budget[0] += len(raw)
    if budget[0] > MAX_TOTAL:
        raise BundleError("TOTAL_BYTE_BUDGET")
    if digest(raw) != expected_sha:
        raise BundleError("INPUT_HASH_MISMATCH")
    if parse:
        strict_json(raw)
    return raw


def _closed():
    return {key: False for key in AUTHORITY_KEYS}


def _not_run(reason):
    return {"status": "NOT_RUN", "reason": reason, "result": None, "result_sha256": None}


def _base_result():
    return {"schema": "research-backend-connection-v1", "status": "BLOCKED",
            "case_id": None, "cutoff": None, "input_sha256": {}, "dependency_sha256": {},
            "code_sha": None, "code_file_sha256": {}, "config_sha256": None,
            "runtime_dependency_file_sha256": {}, "runtime_dependency_status": "NOT_VERIFIED",
            "manifest_sha256": None, "evidence_level": "SUPPLIED_BYTES_ONLY",
            "synthetic_fixture": None, "research_only": True, "validated_er": None,
            "A5_eligible_input": False, "authority": _closed(), "calls": [],
            "stages": {"research_path": _not_run("INPUT_GATE_PENDING"),
                       "risk_connection": _not_run("INPUT_GATE_PENDING")},
            "reasons": [], "publication": None}


def _verify_pins(pins):
    if not isinstance(pins, dict) or not set(REQUIRED_CODE) <= set(pins) or len(pins) > 256:
        raise BundleError("REQUIRED_CODE_PINS_MISSING")
    checked = {}
    total = 0
    for name, sha in pins.items():
        raw = _read(_relative(ROOT, name), MAX_FILE)
        total += len(raw)
        if total > MAX_TOTAL:
            raise BundleError("CODE_BYTE_BUDGET")
        if digest(raw) != _sha(sha):
            raise BundleError("CODE_HASH_MISMATCH")
        checked[name] = digest(raw)
    return checked


def _dependency_snapshots():
    # A fixed, bounded inventory of the original consumers, not module discovery
    # or an assertion of complete interpreter/import closure authentication.
    found = {}
    for name in DEPENDENCY_SOURCES:
        try:
            found[name] = digest(_read(_relative(ROOT, name), MAX_FILE))
        except BundleError:
            found[name] = None
    status = "SOURCE_BYTES_HASHED_NOT_COMPLETE_CLOSURE" if all(found.values()) else "NOT_VERIFIED"
    return found, status


def _stage(callable_, result, name):
    result["calls"].append(name)
    try:
        value = callable_()
        raw = canonical(value)
    except Exception:
        return {"status": "BLOCKED", "reason": "CONNECTION_REFUSED", "result": None,
                "result_sha256": None}
    blocked = value.get("status") == "BLOCKED"
    return {"status": "BLOCKED" if blocked else "DONE", "reason": "SUPPLIED_RESEARCH_ONLY",
            "result": value, "result_sha256": digest(raw)}


def _publish(output: Path, result):
    # A new directory is one atomic batch; no mutable latest/CURRENT alias exists.
    if output.exists():
        raise BundleError("OUTPUT_ALREADY_EXISTS")
    _no_links(output)
    if not output.parent.is_dir():
        raise BundleError("OUTPUT_PARENT_MISSING")
    temporary = output.parent / ("." + output.name + ".tmp-" + uuid.uuid4().hex)
    temporary.mkdir()
    published = False
    try:
        payload = canonical(result)
        evidence = canonical({"input_sha256": result["input_sha256"],
                              "dependency_sha256": result["dependency_sha256"],
                              "code_file_sha256": result["code_file_sha256"],
                              "runtime_dependency_file_sha256": result["runtime_dependency_file_sha256"],
                              "runtime_dependency_status": result["runtime_dependency_status"],
                              "config_sha256": result["config_sha256"],
                              "manifest_sha256": result["manifest_sha256"]})
        receipt = canonical({"schema": "research-backend-publication-v1", "case_id": result["case_id"],
                             "status": result["status"], "cutoff": result["cutoff"],
                             "authority": _closed(), "files": {
                                 "result.json": digest(payload), "inputs.json": digest(evidence)}})
        files = {"result.json": payload, "inputs.json": evidence, "receipt.json": receipt}
        for name, raw in files.items():
            with (temporary / name).open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if digest(_read(temporary / name, MAX_OUTPUT)) != digest(raw):
                raise BundleError("OUTPUT_READBACK_MISMATCH")
        _no_links(output)
        if output.exists():
            raise BundleError("OUTPUT_ALREADY_EXISTS")
        temporary.rename(output)
        published = True
        for name, raw in files.items():
            if digest(_read(output / name, MAX_OUTPUT)) != digest(raw):
                raise BundleError("OUTPUT_READBACK_MISMATCH")
        return {"directory": str(output), "files": {name: digest(raw) for name, raw in files.items()},
                "readback_verified": True, "atomic_batch": True}
    except Exception:
        # This invocation owns this newly created namespace. Do not leave a
        # success-looking receipt after a post-rename physical-read failure.
        if published:
            _no_links(output)
            shutil.rmtree(output)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def run_bundle(manifest_path: Path, output_dir: Path) -> dict:
    """Consume one explicit manifest; publish only a new supplied-research namespace.

    Existing output directories are refused; every invocation rechecks clocks and bytes.
    Runtime exceptions expose fixed reason codes and never return an earlier result.
    """
    result = _base_result()
    output = None
    publication_safe = False
    try:
        manifest_file = _absolute(str(manifest_path), exists=True)
        output = _absolute(str(output_dir))
        if _overlap(output, manifest_file):
            raise BundleError("INPUT_OUTPUT_ALIAS")
        if output.exists():
            raise BundleError("OUTPUT_ALREADY_EXISTS")
        if not output.name.startswith("research-"):
            raise BundleError("RESEARCH_NAMESPACE_REQUIRED")
        raw_manifest = _read(manifest_file, MAX_MANIFEST)
        result["manifest_sha256"] = digest(raw_manifest)
        manifest = strict_json(raw_manifest)
        required = {"schema", "case_id", "cutoff", "input_root", "identifiers", "inputs",
                    "artifacts", "code_sha", "code_pins", "config"}
        if not isinstance(manifest, dict) or set(manifest) != required or manifest["schema"] != SCHEMA:
            raise BundleError("MANIFEST_INVALID")
        case_id = manifest["case_id"]
        if not isinstance(case_id, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", case_id) is None:
            raise BundleError("CASE_ID_INVALID")
        cutoff = clock(manifest["cutoff"])
        result.update(case_id=case_id, cutoff=manifest["cutoff"])
        input_root = _absolute(manifest["input_root"], exists=True)
        if not input_root.is_dir():
            raise BundleError("INPUT_ROOT_INVALID")
        if _overlap(output, input_root) or _overlap(output, ROOT):
            raise BundleError("INPUT_OUTPUT_ALIAS")
        publication_safe = True
        if not isinstance(manifest["config"], dict) or set(manifest["config"]) != {"synthetic_fixture"}:
            raise BundleError("CONFIG_INVALID")
        if type(manifest["config"]["synthetic_fixture"]) is not bool:
            raise BundleError("CONFIG_INVALID")
        result["synthetic_fixture"] = manifest["config"]["synthetic_fixture"]
        result["config_sha256"] = digest(canonical(manifest["config"]))
        if not isinstance(manifest["code_sha"], str) or re.fullmatch(r"[0-9a-f]{40}", manifest["code_sha"]) is None:
            raise BundleError("CODE_SHA_INVALID")
        result["code_sha"] = manifest["code_sha"]
        result["code_file_sha256"] = _verify_pins(manifest["code_pins"])
        identifiers = manifest["identifiers"]
        if not isinstance(identifiers, dict) or set(identifiers) != {"security_id", "issuer_id", "benchmark_id"}:
            raise BundleError("IDENTIFIERS_INVALID")
        if any(not isinstance(value, str) or not value or len(value) > 256 for value in identifiers.values()):
            raise BundleError("IDENTIFIERS_INVALID")
        supplied = manifest["inputs"]
        artifacts = manifest["artifacts"]
        if not isinstance(supplied, dict) or not set(supplied) <= set(RESEARCH_KEYS) | {"risk_request"}:
            raise BundleError("INPUT_KEYS_INVALID")
        if not isinstance(artifacts, dict) or len(artifacts) > 128:
            raise BundleError("ARTIFACT_BUDGET")
        budget = [0]
        loaded = {}
        for name, descriptor in supplied.items():
            if descriptor is None:
                continue
            loaded[name] = _descriptor(input_root, descriptor, cutoff, budget)
            result["input_sha256"][name] = digest(loaded[name])
        memory = {}
        for artifact_id, descriptor in artifacts.items():
            if not isinstance(artifact_id, str) or not artifact_id or len(artifact_id) > 256:
                raise BundleError("ARTIFACT_ID_INVALID")
            # Raw source evidence can be arbitrary bytes; schema/module validators own its meaning.
            raw = _descriptor(input_root, descriptor, cutoff, budget, parse=artifact_id.startswith("SCHEMA:"))
            memory[artifact_id] = raw
            result["dependency_sha256"][artifact_id] = digest(raw)
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from research.research_path_connection_v1 import MemoryArtifacts, build_research_path
        from tools.research_risk_connection import build_risk_connection
        request = {key: loaded.get(key) for key in RESEARCH_KEYS}
        request.update(identifiers, case_id=case_id)
        result["stages"]["research_path"] = _stage(
            lambda: build_research_path(request, cutoff=manifest["cutoff"],
                                        artifact_resolver=MemoryArtifacts(memory)), result, "build_research_path")
        risk_request = strict_json(loaded["risk_request"]) if "risk_request" in loaded else {}
        if not isinstance(risk_request, dict) or "company_research" in risk_request:
            raise BundleError("RISK_REQUEST_INVALID")
        risk_request["company_research"] = result["stages"]["research_path"]["result"]
        result["stages"]["risk_connection"] = _stage(
            lambda: build_risk_connection(risk_request, cutoff=manifest["cutoff"]), result, "build_risk_connection")
        result["status"] = "BLOCKED" if any(stage["status"] == "BLOCKED" for stage in result["stages"].values()) else "DONE"
    except BundleError as error:
        result["status"] = "BLOCKED"
        result["reasons"].append(str(error))
    except Exception:
        result["status"] = "BLOCKED"
        result["reasons"].append("BUNDLE_REFUSED")
    if result["calls"]:
        result["runtime_dependency_file_sha256"], result["runtime_dependency_status"] = _dependency_snapshots()
    if result["reasons"]:
        for stage in result["stages"].values():
            if stage["status"] == "NOT_RUN":
                stage["reason"] = "INPUT_GATE_BLOCKED"
    try:
        # Leave room for the returned physical-publication receipt as well.
        if len(canonical(result)) > MAX_OUTPUT - 65536:
            raise BundleError("OUTPUT_BUDGET")
    except BundleError:
        result["status"] = "BLOCKED"
        result["reasons"].append("OUTPUT_BUDGET")
        for stage in result["stages"].values():
            stage.update(status="BLOCKED", reason="OUTPUT_BUDGET", result=None, result_sha256=None)
    if publication_safe and output is not None:
        try:
            result["publication"] = _publish(output, result)
        except BundleError as error:
            result["status"] = "BLOCKED"
            result["reasons"].append(str(error))
            result["publication"] = None
        except Exception:
            result["status"] = "BLOCKED"
            result["reasons"].append("PUBLICATION_REFUSED")
            result["publication"] = None
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Explicit bounded input manifest; no latest/glob discovery")
    parser.add_argument("--output-dir", type=Path, required=True, help="New research-* directory outside input and code roots")
    args = parser.parse_args(argv)
    result = run_bundle(args.manifest, args.output_dir)
    print(canonical(result).decode("utf-8"), end="")
    return 0 if result["status"] == "DONE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
