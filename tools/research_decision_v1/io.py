"""Bounded JSON inputs and immutable research-only output paths."""
import json
import os
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


def immutable_json(path, payload):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)): raise ValueError("output_symlink")
    data = (canonical(payload) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_bytes() != data: raise ValueError("immutable_history_conflict")
    return path


def source_code_hash(repo_root):
    root = Path(repo_root)
    return digest({p.name: p.read_text(encoding="utf-8") for p in sorted((root / "tools" / "research_decision_v1").glob("*.py"))})
