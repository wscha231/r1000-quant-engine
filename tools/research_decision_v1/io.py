"""Bounded JSON inputs and immutable research-only output paths."""
import json
import os
import tempfile
import stat
import uuid
from pathlib import Path
from tools.research_decision_v1.data import canonical, digest
from tools.research_decision_v1.platform_io import (input_descriptor, is_redirect, publish_staged,
    sync_directory, output_parent, output_existing_descriptor)


def descriptor_bytes(descriptor, maximum):
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
        raise ValueError("unsafe_or_oversized_input")
    chunks, size = [], 0
    while True:
        chunk = os.read(descriptor, min(1_048_576, maximum + 1 - size))
        if not chunk: break
        size += len(chunk)
        if size > maximum: raise ValueError("unsafe_or_oversized_input")
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("input_changed_during_read")
    return b"".join(chunks)


def read_bytes(path, maximum=32_000_000):
    path = Path(path)
    if ".." in path.parts: raise ValueError("unsafe_or_oversized_input")
    path = path.absolute()
    try:
        with input_descriptor(path) as descriptor:
            return descriptor_bytes(descriptor, maximum)
    except OSError as exc:
        raise ValueError("unsafe_or_oversized_input") from exc


def read_json(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out: raise ValueError("duplicate_json_key")
            out[key] = value
        return out
    def constant(value): raise ValueError("nonfinite_json")
    return json.loads(read_bytes(path).decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)


def research_root(repo_root):
    root = Path(repo_root).resolve()
    out = root / "outputs" / "research_decision_v1"
    for p in (root / "outputs", out):
        if is_redirect(p): raise ValueError("output_symlink")
    with output_parent(out): pass
    return out


def immutable_bytes(path, data):
    path = Path(path).absolute()
    if ".." in path.parts: raise ValueError("output_symlink")
    if any(is_redirect(p) for p in (path, *path.parents)): raise ValueError("output_symlink")
    with output_parent(path.parent) as parent_descriptor:
        temporary = None
        try:
            if parent_descriptor is None:
                handle = tempfile.NamedTemporaryFile(dir=path.parent, prefix=".research-stage-", delete=False)
                temporary = Path(handle.name)
            else:
                temporary = path.parent / (".research-stage-" + uuid.uuid4().hex)
                descriptor = os.open(temporary.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=parent_descriptor)
                handle = os.fdopen(descriptor, "wb")
            with handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
            try:
                publish_staged(temporary, path, parent_descriptor=parent_descriptor)
            except FileExistsError:
                try:
                    with output_existing_descriptor(path, parent_descriptor) as descriptor:
                        if descriptor_bytes(descriptor, len(data)) != data: raise ValueError("immutable_history_conflict")
                except (ValueError, OSError) as exc: raise ValueError("immutable_history_conflict") from exc
            sync_directory(path.parent, descriptor=parent_descriptor)
        finally:
            if temporary is not None:
                if parent_descriptor is None: temporary.unlink(missing_ok=True)
                else: os.unlink(temporary.name, dir_fd=parent_descriptor)
    return path


def immutable_json(path, payload):
    return immutable_bytes(path, (canonical(payload) + "\n").encode())


def source_material(repo_root):
    root = Path(repo_root).resolve()
    package = root / "tools" / "research_decision_v1"
    files = sorted(package.rglob("*.py"))
    parent_init = root / "tools" / "__init__.py"
    if parent_init.exists(): files.append(parent_init)
    if not files or any(is_redirect(p) for p in (package, *package.parents, *files)):
        raise ValueError("engine_package_missing_or_unsafe")
    if any(p.suffix in {".so", ".pyd"} for p in package.rglob("*")):
        raise ValueError("unmanifested_executable")
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in files}


def source_code_hash(repo_root):
    return digest(source_material(repo_root))
