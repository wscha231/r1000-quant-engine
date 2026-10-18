#!/usr/bin/env python3
"""Bounded local run_bundle queue; no persisted acceptance rehydration."""
from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
from datetime import datetime, timezone
import os
import importlib
import inspect
import marshal
import math
from pathlib import Path
import re
import sys
import threading
import time
from types import CodeType, FunctionType, MappingProxyType
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import run_research_backend_connection as backend

SCHEMA = "research-local-queue-v1"
MAX_CASES = 16
MAX_ATTEMPTS = 16
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 60
MAX_PROGRESS = 32
CASE_KEYS = {"case_id", "bundle_path", "bundle_sha256", "as_of", "identifiers",
             "valid_through", "review_due_at", "correction", "source_failure", "outcome_due"}
LIMITS = {"max_cases": MAX_CASES, "max_attempts": MAX_ATTEMPTS,
          "max_input_bytes": MAX_INPUT_BYTES, "max_seconds": MAX_SECONDS,
          "max_progress": MAX_PROGRESS}
Error = backend.BundleError


def require(condition, reason):
    if not condition:
        raise Error(reason)


def closed(value):
    require(isinstance(value, dict) and value == backend._closed()
            and all(v is False for v in value.values()), "QUEUE_AUTHORITY_REFUSED")


def _due(case, bundle=None):
    now = datetime.now(timezone.utc)
    if any(case[k] for k in ("correction", "source_failure", "outcome_due")) \
            or backend.clock(case["valid_through"]) <= now \
            or (case["review_due_at"] is not None and backend.clock(case["review_due_at"]) <= now):
        return True
    return bundle is not None and any(
        backend.clock(d["valid_through"]) <= now for kind in ("inputs", "artifacts")
        for d in bundle[kind].values() if d is not None)


def _publish(parent, name, value):
    """Unique bounded JSON directory; failures retain unaccepted staging bytes."""
    identity = backend._directory_identity(parent)
    target = parent / name
    require(not target.exists(), "QUEUE_PUBLICATION_EXISTS")
    temporary = parent / (".queue-" + uuid.uuid4().hex)
    temporary.mkdir()
    own = backend._directory_identity(temporary)
    raw = backend.canonical(value)
    require(len(raw) <= backend.MAX_FILE, "QUEUE_PROGRESS_BYTE_BUDGET")
    with (temporary / "record.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    require(backend._read(temporary / "record.json", backend.MAX_FILE) == raw,
            "QUEUE_STAGE_READBACK_FAILED")
    require(backend._directory_identity(temporary) == own
            and backend._directory_identity(parent) == identity, "QUEUE_DIRECTORY_CHANGED")
    backend._rename_noreplace(temporary, target)
    require(backend._directory_identity(target) == own
            and backend._directory_identity(parent) == identity
            and backend._read(target / "record.json", backend.MAX_FILE) == raw,
            "QUEUE_FINAL_READBACK_FAILED")
    return {"directory": str(target), "identity": own,
            "sha256": backend.digest(raw), "readback_verified": True}


def _read_publication(publication):
    require(isinstance(publication, dict), "RETURNED_ACCEPTANCE_MISSING")
    acceptance = publication.get("acceptance")
    require(isinstance(acceptance, dict)
            and acceptance.get("state") == "LOCAL_READBACK_ACCEPTED"
            and publication.get("readback_verified") is True
            and publication.get("atomic_batch") is True
            and backend.digest(backend.canonical(acceptance)) == publication.get("acceptance_sha256")
            and acceptance.get("files") == publication.get("files"), "RETURNED_ACCEPTANCE_INVALID")
    directory = backend._absolute(publication.get("directory"), exists=True)
    require(backend._directory_identity(directory) == acceptance.get("directory_identity"),
            "ACCEPTED_DIRECTORY_CHANGED")
    files = publication["files"]
    require(set(files) == {"result.json", "inputs.json", "receipt.json"}, "ACCEPTED_FILES_INVALID")
    for name, expected in files.items():
        require(backend.digest(backend._read(directory / name, backend.MAX_OUTPUT)) == expected,
                "ACCEPTED_BYTES_CHANGED")


def _code_snapshot():
    """Conservative repository Python/config inventory, not interpreter closure."""
    hashes = {}
    size = count = walked = 0
    for parent, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__", ".pytest_cache"})
        walked += len(dirs) + len(files)
        require(walked <= 32768, "CODE_TRAVERSAL_BUDGET")
        for directory in dirs:
            backend._no_links(Path(parent) / directory)
        for name in sorted(files):
            path = Path(parent) / name
            if path.suffix.lower() not in {".py", ".json", ".yaml", ".yml", ".toml"}:
                continue
            count += 1
            require(count <= 8192, "CODE_INVENTORY_BUDGET")
            raw = backend._read(path, backend.MAX_FILE)
            size += len(raw)
            require(size <= MAX_INPUT_BYTES, "CODE_BYTE_BUDGET")
            hashes[path.relative_to(ROOT).as_posix()] = backend.digest(raw)
    return {"files_sha256": backend.digest(backend.canonical(hashes)),
            "dependency_scope": "REPOSITORY_SOURCE_CONFIG_NOT_INTERPRETER_CLOSURE"}


def _module_stamp():
    """Bind consumer callables to compiled source, then their live code/defaults.

    Controller instrumentation is outside this consumer stamp. This is not an
    interpreter/native-library closure or a hostile-process sandbox.
    """
    for name in ("research.research_path_connection_v1", "tools.research_risk_connection"):
        importlib.import_module(name)
    modules = {}
    total = 0
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not isinstance(filename, str) or name == __name__ or name.startswith("tests."):
            continue
        path = Path(filename).resolve()
        if ROOT not in path.parents or path.suffix != ".py" or "tests" in path.relative_to(ROOT).parts:
            continue
        require(len(modules) < 256, "RUNTIME_MODULE_BUDGET")
        raw = backend._read(path, backend.MAX_FILE)
        total += len(raw)
        require(total <= backend.MAX_TOTAL, "RUNTIME_SOURCE_BYTE_BUDGET")
        compiled = compile(raw, filename, "exec", dont_inherit=True, optimize=sys.flags.optimize)
        syntax = ast.parse(raw)
        aliases = {}
        for node in ast.walk(syntax):
            if isinstance(node, ast.ImportFrom):
                imported = node.module
                if node.level:
                    imported = importlib.util.resolve_name("." * node.level + (imported or ""),
                                                           module.__package__)
                for alias in node.names:
                    aliases.setdefault(alias.asname or alias.name, []).append((imported, alias.name))
        expected = {}
        pending = [compiled]
        while pending:
            code = pending.pop()
            pending.extend(c for c in code.co_consts if isinstance(c, CodeType))
            if code.co_flags & inspect.CO_NEWLOCALS and "<" not in code.co_qualname:
                expected.setdefault(code.co_qualname, []).append(code)
        bindings = {}
        for qualified, alternatives in expected.items():
            owner = module
            value = None
            for part in qualified.split("."):
                value = vars(owner).get(part)
                owner = value
                if value is None:
                    break
            if isinstance(value, (staticmethod, classmethod)):
                value = value.__func__
            functions = [value.fget, value.fset, value.fdel] if isinstance(value, property) else [value]
            for position, function in enumerate(functions):
                if function is None:
                    continue
                wrapper = function
                # A source-declared import can legitimately replace a compiled
                # fallback definition. Its owning repository module is checked
                # independently below; bind the actual alias, never silently
                # accept an arbitrary foreign replacement.
                imported_alias = next(((origin, symbol) for origin, symbol in aliases.get(qualified, [])
                    if origin in sys.modules and vars(sys.modules[origin]).get(symbol) is function), None)
                if imported_alias is not None:
                    bindings[qualified + ":" + str(position)] = {
                        "import_alias": list(imported_alias), "callable_id": id(function),
                        "code": _runtime_value(function)}
                    continue
                wrappers = []
                while hasattr(function, "__wrapped__"):
                    require(len(wrappers) < 8, "RUNTIME_WRAPPER_BUDGET")
                    if isinstance(function, FunctionType):
                        actual_globals = function.__globals__
                        actual_path = backend._absolute(actual_globals.get("__file__"), exists=True)
                        require(ROOT in actual_path.parents, "RUNTIME_WRAPPER_OUTSIDE_SCOPE")
                        wrapper_raw = backend._read(actual_path, backend.MAX_FILE)
                        total += len(wrapper_raw)
                        require(total <= backend.MAX_TOTAL, "RUNTIME_SOURCE_BYTE_BUDGET")
                        codes = [compile(wrapper_raw, str(actual_path), "exec", dont_inherit=True,
                                         optimize=sys.flags.optimize)]
                        matches = False
                        while codes:
                            code = codes.pop()
                            matches |= function.__code__ == code
                            codes.extend(c for c in code.co_consts if isinstance(c, CodeType))
                        require(matches, "LOADED_WRAPPER_CODE_MISMATCH")
                        wrappers.append({"id": id(function),
                            "code_sha256": backend.digest(marshal.dumps(function.__code__)),
                            "closure": [_runtime_value(c.cell_contents) for c in function.__closure__ or ()]})
                    else:
                        require(type(function).__module__ == "functools", "RUNTIME_WRAPPER_REFUSED")
                        wrappers.append({"id": id(function), "type": type(function).__qualname__})
                    function = function.__wrapped__
                require(isinstance(function, FunctionType) and function.__globals__ is vars(module)
                        and any(function.__code__ == code for code in alternatives),
                        "LOADED_SOURCE_CODE_MISMATCH")
                bindings[qualified + ":" + str(position)] = {
                    "callable_id": id(wrapper), "code_id": id(function.__code__),
                    "executed_code_sha256": backend.digest(marshal.dumps(function.__code__)),
                    "wrappers": wrappers,
                    "defaults": _runtime_value(function.__defaults__),
                    "kwdefaults": _runtime_value(function.__kwdefaults__)}
        # Literal module constants and class field defaults also expose stale
        # cached configuration when only data, rather than a function, changed.
        for scope, namespace in [(syntax, vars(module))] + [
                (node, vars(vars(module)[node.name])) for node in syntax.body
                if isinstance(node, ast.ClassDef) and isinstance(vars(module).get(node.name), type)]:
            for node in scope.body:
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if isinstance(node, ast.AnnAssign) else [])
                for target in targets:
                    if not isinstance(target, ast.Name) or (not isinstance(scope, ast.ClassDef)
                            and (not target.id.isupper() or re.search("SECRET|PASSWORD|TOKEN|API_KEY", target.id))):
                        continue
                    try:
                        literal = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError):
                        continue
                    require(target.id in namespace and namespace[target.id] == literal,
                            "LOADED_SOURCE_CONSTANT_MISMATCH")
        modules[name] = {"module_id": id(module), "source_sha256": backend.digest(raw),
                         "bindings_sha256": backend.digest(backend.canonical(bindings))}
    return modules


def _runtime_value(value, depth=0):
    require(depth <= 8, "RUNTIME_DEFAULT_DEPTH_BUDGET")
    if type(value) is float and not math.isfinite(value):
        return {"nonfinite_float": value.hex()}
    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, FunctionType):
        return {"function_id": id(value), "code_sha256": backend.digest(marshal.dumps(value.__code__))}
    if isinstance(value, (bytes, bytearray)):
        require(len(value) <= backend.MAX_FILE, "RUNTIME_DEFAULT_BUDGET")
        return {"bytes_sha256": backend.digest(bytes(value))}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"dataclass": type(value).__module__ + "." + type(value).__qualname__,
                "fields": {field.name: _runtime_value(getattr(value, field.name), depth + 1)
                           for field in dataclasses.fields(value)}}
    if isinstance(value, (list, tuple, dict)):
        require(len(value) <= 512, "RUNTIME_DEFAULT_BUDGET")
        if isinstance(value, dict):
            return {"dict_pairs": [[_runtime_value(k, depth + 1), _runtime_value(v, depth + 1)]
                                   for k, v in value.items()]}
        return {type(value).__name__: [_runtime_value(v, depth + 1) for v in value]}
    if isinstance(value, (set, frozenset)):
        require(len(value) <= 512, "RUNTIME_DEFAULT_BUDGET")
        return {type(value).__name__: sorted(backend.digest(backend.canonical(_runtime_value(v, depth + 1)))
                                           for v in value)}
    return {"type": type(value).__module__ + "." + type(value).__qualname__, "identity": id(value)}


def _security(bundle, trusted_root, output):
    require(isinstance(bundle, dict), "BUNDLE_SHAPE_INVALID")
    root = backend._absolute(bundle.get("input_root"))
    require(root == trusted_root or trusted_root in root.parents, "BUNDLE_ROOT_OUTSIDE_TRUST")
    require(not backend._overlap(root, output) and not backend._overlap(root, ROOT),
            "BUNDLE_ROOT_OVERLAP")
    for key in ("inputs", "artifacts"):
        require(isinstance(bundle.get(key), dict), "BUNDLE_DESCRIPTORS_INVALID")
        require(len(bundle[key]) <= 128, "BUNDLE_DESCRIPTOR_BUDGET")
        for descriptor in bundle[key].values():
            if descriptor is not None:
                require(isinstance(descriptor, dict) and set(descriptor) ==
                        {"path", "expected_sha256", "available_at", "collected_at", "valid_through"},
                        "BUNDLE_DESCRIPTOR_INVALID")
                backend._relative(root, descriptor.get("path"))
    pins = bundle.get("code_pins")
    require(isinstance(pins, dict) and len(pins) <= 256, "BUNDLE_PINS_INVALID")
    for path in pins:
        backend._relative(ROOT, path)
    return root


class QueueSession:
    """One owner process, new output root, bounded lifetime and live return proofs.

    No JSON/pickle restoration API. Existing roots need explicit owner recovery.
    """

    def __init__(self, input_root: Path, output_dir: Path, queue_id: str, limits: dict):
        require(isinstance(queue_id, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", queue_id),
                "QUEUE_ID_INVALID")
        require(isinstance(limits, dict) and set(limits) == set(LIMITS), "QUEUE_LIMITS_INVALID")
        require(all(type(v) is int and 0 < v <= LIMITS[k] for k, v in limits.items()),
                "QUEUE_LIMITS_EXCEEDED")
        self.input_root = backend._absolute(str(input_root), exists=True)
        self.output = backend._absolute(str(output_dir))
        require(self.input_root.is_dir() and self.output.name.startswith("research-queue-"),
                "QUEUE_ROOT_INVALID")
        require(not backend._overlap(self.input_root, self.output)
                and not backend._overlap(ROOT, self.output)
                and not backend._overlap(ROOT, self.input_root), "QUEUE_ROOT_OVERLAP")
        require(self.output.parent.is_dir() and not self.output.exists(),
                "OWNER_RECOVERY_REQUIRED_EXISTING_ROOT")
        self.limits = MappingProxyType(dict(limits))
        self.queue_id = queue_id
        self.pid = os.getpid()
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.proofs = {}
        self.reservations = {}
        self.used_bytes = self.progress_count = 0
        self.poisoned = False
        self.output.mkdir()  # Atomic exclusive namespace creation, never an overwrite.
        self.identity = backend._directory_identity(self.output)
        self.binding = _publish(self.output, "owner", {
            "schema": SCHEMA, "queue_id": queue_id, "limits": dict(self.limits),
            "input_root": str(self.input_root), "pid": self.pid,
            "authority": backend._closed(), "acceptance_restorable_from_disk": False})

    def __reduce__(self):
        raise TypeError("QueueSession acceptance cannot be serialized")

    def _guard(self):
        require(not self.poisoned and os.getpid() == self.pid, "QUEUE_SESSION_NOT_LIVE")
        require(backend._directory_identity(self.output) == self.identity, "QUEUE_ROOT_CHANGED")
        require(backend._directory_identity(Path(self.binding["directory"])) == self.binding["identity"]
                and backend.digest(backend._read(Path(self.binding["directory"]) / "record.json",
                                                backend.MAX_FILE)) == self.binding["sha256"],
                "QUEUE_BINDING_CHANGED")
        require(time.monotonic() - self.started < self.limits["max_seconds"], "QUEUE_TIME_BUDGET")

    def _prepare(self, raw):
        manifest = backend.strict_json(raw)
        require(isinstance(manifest, dict) and set(manifest) ==
                {"schema", "queue_id", "as_of", "cases", "authority"}, "QUEUE_MANIFEST_INVALID")
        require(manifest["schema"] == SCHEMA and manifest["queue_id"] == self.queue_id,
                "QUEUE_IDENTITY_MISMATCH")
        closed(manifest["authority"])
        now = datetime.now(timezone.utc)
        asof = backend.clock(manifest["as_of"])
        require(asof <= now, "QUEUE_FUTURE")
        cases = manifest["cases"]
        require(isinstance(cases, list) and 0 < len(cases) <= self.limits["max_cases"],
                "QUEUE_CASE_BUDGET")
        seen = set()
        prepared = []
        # Security scan covers every present bundle before any invocation/write.
        for case in cases:
            require(isinstance(case, dict) and set(case) == CASE_KEYS, "QUEUE_CASE_INVALID")
            ident = case["case_id"]
            require(isinstance(ident, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", ident)
                    and ident not in seen, "QUEUE_CASE_ID_INVALID")
            seen.add(ident)
            require(all(type(case[k]) is bool for k in ("correction", "source_failure", "outcome_due")),
                    "QUEUE_REVIEW_FLAGS_INVALID")
            backend._sha(case["bundle_sha256"])
            require(isinstance(case["identifiers"], dict) and set(case["identifiers"]) ==
                    {"security_id", "issuer_id", "benchmark_id"}
                    and all(isinstance(v, str) and 0 < len(v) <= 256
                            for v in case["identifiers"].values()), "QUEUE_IDENTIFIERS_INVALID")
            path = backend._relative(self.input_root, case["bundle_path"])
            require(backend.clock(case["as_of"]) <= asof, "QUEUE_CASE_FUTURE")
            backend.clock(case["valid_through"])
            if case["review_due_at"] is not None:
                backend.clock(case["review_due_at"])
            body = bundle = root = None
            reason = None
            try:
                body = backend._read(path, backend.MAX_MANIFEST)
                bundle = backend.strict_json(body)
            except Error as error:
                reason = str(error)
            if bundle is not None:
                root = _security(bundle, self.input_root, self.output)
            prepared.append((case, path, body, bundle, root, reason))
        return manifest, prepared

    def run(self, manifest_path: Path):
        require(self.lock.acquire(blocking=False), "QUEUE_OWNER_BUSY")
        try:
            return self._run(manifest_path)
        except (Error, OSError):
            # An ambiguous publication cannot be retried by this controller.
            self.poisoned = True
            raise
        finally:
            self.lock.release()

    def _run(self, manifest_path):
        self._guard()
        path = backend._absolute(str(manifest_path), exists=True)
        require(self.input_root in path.parents, "QUEUE_MANIFEST_OUTSIDE_TRUST")
        manifest_raw = backend._read(path, backend.MAX_MANIFEST)
        manifest, prepared = self._prepare(manifest_raw)
        require(self.progress_count < self.limits["max_progress"], "QUEUE_PROGRESS_BUDGET")
        rows = []
        candidates = {}
        for case, bundle_path, body, bundle, root, reason in prepared:
            self._guard()
            row = {"case_id": case["case_id"], "status": "INPUT_BLOCKED", "reason": reason,
                   "bundle_sha256": case["bundle_sha256"], "publication": None}
            rows.append(row)
            now = datetime.now(timezone.utc)
            if _due(case):
                row.update(status="REVIEW_DUE", reason="EXPIRY_CORRECTION_SOURCE_OR_OUTCOME_DUE")
                continue
            if reason:
                continue
            if not root.is_dir():
                row["reason"] = "BUNDLE_INPUT_ROOT_MISSING"
                continue
            if backend.digest(body) != case["bundle_sha256"]:
                row["reason"] = "BUNDLE_HASH_MISMATCH"
                continue
            if bundle.get("case_id") != case["case_id"] or bundle.get("cutoff") != case["as_of"] \
                    or bundle.get("identifiers") != case["identifiers"]:
                row["reason"] = "BUNDLE_IDENTITY_OR_CLOCK_MISMATCH"
                continue
            inputs = {}
            size = len(body)
            try:
                backend._verify_pins(bundle["code_pins"])
                for kind in ("inputs", "artifacts"):
                    for key, descriptor in bundle[kind].items():
                        if descriptor is None:
                            continue
                        if backend.clock(descriptor["valid_through"]) <= now:
                            raise Error("DESCRIPTOR_REVIEW_DUE")
                        data = backend._descriptor(root, descriptor, backend.clock(case["as_of"]),
                                                   [0], parse=False)
                        size += len(data)
                        require(size <= backend.MAX_TOTAL, "CASE_BYTE_BUDGET")
                        inputs[kind + ":" + key] = backend.digest(data)
                snapshot = _code_snapshot()
            except Error as error:
                row.update(reason=str(error))
                if str(error) == "DESCRIPTOR_REVIEW_DUE":
                    row["status"] = "REVIEW_DUE"
                continue
            self._guard()
            if _due(case, bundle):
                row.update(status="REVIEW_DUE", reason="CLOCK_EXPIRED_DURING_PREFLIGHT")
                continue
            try:
                runtime_before = _module_stamp()
            except Error as error:
                row.update(status="REVIEW_DUE", reason=str(error))
                continue
            self._guard()
            fingerprint = backend.digest(backend.canonical({"bundle": backend.digest(body),
                "inputs": inputs, "code": snapshot}))
            key = backend.digest(backend.canonical([case["case_id"], fingerprint]))
            row["fingerprint"] = fingerprint
            proof = self.proofs.get(key)
            if proof is not None:
                try:
                    require(proof["modules"] == runtime_before, "LOADED_MODULES_CHANGED")
                    _read_publication(proof["publication"])
                    require(not _due(case, bundle), "CLOCK_EXPIRED_DURING_READBACK")
                except Error as error:
                    row.update(status="REVIEW_DUE", reason=str(error))
                else:
                    row.update(status="SKIP_UNCHANGED", reason="LIVE_RETURN_AND_FRESH_READBACK",
                               publication=copy.deepcopy(proof["publication"]))
                continue
            if key in self.reservations or (self.output / ("intent-" + key)).exists() \
                    or (self.output / ("research-" + key)).exists():
                row.update(status="REVIEW_DUE", reason="UNRESOLVED_PRIOR_INTENT")
                continue
            if len(self.reservations) >= self.limits["max_attempts"] \
                    or self.used_bytes + size > self.limits["max_input_bytes"]:
                row["reason"] = "QUEUE_CUMULATIVE_BUDGET"
                continue
            self.reservations[key] = size
            self.used_bytes += size  # No refund/reset, including failed attempts.
            _publish(self.output, "intent-" + key, {"case_id": case["case_id"],
                "fingerprint": fingerprint, "reserved_input_bytes": size,
                "state": "UNACCEPTED_INTENT", "authority": backend._closed()})
            self._guard()
            if _due(case, bundle):
                row.update(status="REVIEW_DUE", reason="CLOCK_EXPIRED_DURING_INTENT")
                continue
            output = self.output / ("research-" + key)
            result = backend.run_bundle(bundle_path, output)
            self._guard()
            # Reject races between preflight and the actual downstream read.
            require(backend.digest(backend._read(bundle_path, backend.MAX_MANIFEST)) == backend.digest(body)
                    and result.get("manifest_sha256") == backend.digest(body), "BUNDLE_CHANGED_AT_CALL")
            require(_code_snapshot() == snapshot, "CODE_CHANGED_AT_CALL")
            closed(result.get("authority"))
            require(result.get("A5_eligible_input") is False and result.get("validated_er") is None,
                    "DOWNSTREAM_AUTHORITY_REFUSED")
            publication = result.get("publication")
            try:
                _read_publication(publication)
                require(publication["directory"] == str(output), "WRONG_RETURN_DIRECTORY")
                require(result.get("calls") == ["build_research_path", "build_risk_connection"],
                        "LOCAL_STAGES_NOT_RUN")
                actual = {"inputs:" + k: v for k, v in result["input_sha256"].items()}
                actual.update({"artifacts:" + k: v for k, v in result["dependency_sha256"].items()})
                require(actual == inputs, "DOWNSTREAM_INPUT_HASH_MISMATCH")
                require(not _due(case, bundle), "CLOCK_EXPIRED_DURING_EXECUTION_OR_READBACK")
            except Error as error:
                row.update(status="REVIEW_DUE", reason=str(error))
                continue
            row.update(status="RAN_LOCAL_RESEARCH", reason="ACTUAL_C_D_CALLS_LOCAL_READBACK",
                       result_status=result["status"], publication=publication,
                       runtime_dependency_status=result["runtime_dependency_status"])
            candidates[key] = {"publication": copy.deepcopy(publication), "modules": _module_stamp()}
        report = {"schema": SCHEMA, "queue_id": self.queue_id,
                  "manifest_sha256": backend.digest(manifest_raw), "as_of": manifest["as_of"],
                  "rows": rows, "attempts_reserved": len(self.reservations),
                  "input_bytes_reserved": self.used_bytes,
                  "acceptance_restorable_from_disk": False, "authority": backend._closed(),
                  "validated_er": None, "A5_eligible_input": False,
                  "progress_state": "PREPARED_ONLY"}
        cases = {case["case_id"]: (case, bundle) for case, _, _, bundle, _, _ in prepared}
        def revalidate_all():
            changed = False
            for row in rows:
                if row["status"] not in {"RAN_LOCAL_RESEARCH", "SKIP_UNCHANGED"}:
                    continue
                case, bundle = cases[row["case_id"]]
                if _due(case, bundle):
                    row.update(status="REVIEW_DUE", reason="CLOCK_EXPIRED_AT_BATCH_BOUNDARY",
                               publication=None)
                    key = backend.digest(backend.canonical([row["case_id"], row["fingerprint"]]))
                    candidates.pop(key, None)
                    self.proofs.pop(key, None)
                    changed = True
            return changed
        revalidate_all()  # Later cases may have crossed an earlier case's clock.
        self._guard()
        self.progress_count += 1
        progress = _publish(self.output, "progress-" + str(self.progress_count), report)
        self._guard()
        if revalidate_all():
            # Stored progress was only preparation. Do not accept it, reconstruct
            # it, retry publication, or mint any new batch proof after late expiry.
            report.update(progress_state="UNACCEPTED_DUE_AFTER_PUBLICATION",
                          local_progress_acceptance=None)
            return report
        self.proofs.update(candidates)  # Only after actual progress return/readback.
        report["progress_state"] = "LOCAL_READBACK_ACCEPTED"
        report["local_progress_acceptance"] = progress
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--queue-id", required=True)
    args = parser.parse_args()
    try:
        session = QueueSession(args.input_root, args.output_dir, args.queue_id, LIMITS)
        result = session.run(args.manifest)
    except (Error, OSError):
        print(backend.canonical({"status": "BLOCKED", "reason": "QUEUE_REFUSED_OWNER_INSPECTION_REQUIRED",
                                 "authority": backend._closed()}).decode(), end="")
        return 2
    print(backend.canonical(result).decode(), end="")
    return 0 if all(r["status"] in {"RAN_LOCAL_RESEARCH", "SKIP_UNCHANGED"}
                    for r in result["rows"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
