"""Bounded JSON inputs and immutable research-only output paths."""
import json
import os
import tempfile
from pathlib import Path
from tools.research_decision_v1.data import canonical, digest


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_000_000:
        raise ValueError("unsafe_or_oversized_input")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out: raise ValueError("duplicate_json_key")
            out[key] = value
        return out
    def constant(value): raise ValueError("nonfinite_json")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=constant)


def research_root(repo_root):
    root = Path(repo_root).resolve()
    out = root / "outputs" / "research_decision_v1"
    for p in (root / "outputs", out):
        if p.is_symlink(): raise ValueError("output_symlink")
    out.mkdir(parents=True, exist_ok=True)
    return out


def immutable_bytes(path, data):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError("output_symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".research-stage-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(temporary, path)  # Atomic publication with no replacement.
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data: raise ValueError("immutable_history_conflict")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
    return path


def immutable_json(path, payload):
    return immutable_bytes(path, (canonical(payload) + "\n").encode())


def source_material(repo_root):
    root = Path(repo_root).resolve()
    package = root / "tools" / "research_decision_v1"
    files = sorted(package.rglob("*.py"))
    parent_init = root / "tools" / "__init__.py"
    if parent_init.exists(): files.append(parent_init)
    if not files or any(p.is_symlink() for p in (package, *package.parents, *files)):
        raise ValueError("engine_package_missing_or_unsafe")
    if any(p.suffix in {".so", ".pyd"} for p in package.rglob("*")):
        raise ValueError("unmanifested_executable")
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in files}


def source_code_hash(repo_root):
    return digest(source_material(repo_root))
