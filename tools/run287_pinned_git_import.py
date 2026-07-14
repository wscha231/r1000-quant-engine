"""Import Python modules directly from a pinned Git tree without checkout.

The loader is intentionally small and read-only.  It maps tracked ``.py``
files at one commit to Python module names, removes already-loaded collisions,
and compiles the pinned bytes while retaining repository-like ``__file__``
paths.  This allows research audits to use an exact historical policy source
without changing the current worktree or creating another worktree.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Iterator


def _module_name(relative_path: str) -> tuple[str, bool]:
    if relative_path.endswith("/__init__.py"):
        return relative_path[: -len("/__init__.py")].replace("/", "."), True
    return relative_path[:-3].replace("/", "."), False


def _python_tree(commit: str, repo_root: Path) -> tuple[dict[str, str], set[str]]:
    listing = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit],
        cwd=repo_root,
        text=True,
        stderr=subprocess.DEVNULL,
    ).splitlines()
    modules: dict[str, str] = {}
    packages: set[str] = set()
    for relative_path in listing:
        if not relative_path.endswith(".py"):
            continue
        module_name, is_package = _module_name(relative_path)
        modules[module_name] = relative_path
        if is_package:
            packages.add(module_name)
    return modules, packages


class PinnedGitLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Meta-path loader that serves repository modules from one Git commit."""

    def __init__(self, commit: str, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.commit = subprocess.check_output(
            ["git", "rev-parse", f"{commit}^{{commit}}"],
            cwd=self.repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        self.modules, self.packages = _python_tree(self.commit, self.repo_root)
        self.loaded: list[dict[str, Any]] = []
        self._blob_cache: dict[str, bytes] = {}

    def blob(self, relative_path: str) -> bytes:
        if relative_path not in self._blob_cache:
            self._blob_cache[relative_path] = subprocess.check_output(
                ["git", "show", f"{self.commit}:{relative_path}"],
                cwd=self.repo_root,
                stderr=subprocess.DEVNULL,
            )
        return self._blob_cache[relative_path]

    def find_spec(
        self,
        fullname: str,
        path: Any = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        del path, target
        if fullname not in self.modules:
            return None
        return importlib.util.spec_from_loader(
            fullname,
            self,
            is_package=fullname in self.packages,
        )

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        del spec
        return None

    def exec_module(self, module: ModuleType) -> None:
        relative_path = self.modules[module.__name__]
        source = self.blob(relative_path)
        virtual_path = self.repo_root / relative_path
        module.__file__ = str(virtual_path)
        module.__loader__ = self
        if module.__name__ in self.packages:
            module.__path__ = [str(virtual_path.parent)]  # type: ignore[attr-defined]
        self.loaded.append(
            {
                "module": module.__name__,
                "relative_path": relative_path,
                "bytes": int(len(source)),
                "sha256": hashlib.sha256(source).hexdigest(),
                "source_commit": self.commit,
                "source_mode": "pinned_git_object",
            }
        )
        exec(compile(source, str(virtual_path), "exec"), module.__dict__)

    def remove_loaded_collisions(self) -> dict[str, ModuleType]:
        removed: dict[str, ModuleType] = {}
        for module_name in self.modules:
            existing = sys.modules.pop(module_name, None)
            if existing is not None:
                removed[module_name] = existing
        return removed

    @staticmethod
    def unload(module_names: list[str]) -> None:
        for module_name in reversed(module_names):
            sys.modules.pop(module_name, None)


@contextmanager
def pinned_import_context(
    commit: str,
    repo_root: Path,
) -> Iterator[PinnedGitLoader]:
    loader = PinnedGitLoader(commit, repo_root)
    removed = loader.remove_loaded_collisions()
    sys.meta_path.insert(0, loader)
    try:
        yield loader
    finally:
        if loader in sys.meta_path:
            sys.meta_path.remove(loader)
        loader.unload([row["module"] for row in loader.loaded])
        sys.modules.update(removed)
