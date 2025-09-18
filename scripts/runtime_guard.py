"""Runtime scope enforcement for agents.

Usage:
    guard = RuntimeGuard.from_alou("org/_registry/AGENT-PO01.alou.md", base_dir=".")
    tool_call = guard.wrap_tool_call(raw_call)
    guard.fs.write_text(Path("org/policy/new.md"), "# draft")
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Callable, Iterable
import re

import yaml

FRONT_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _load_alou_frontmatter(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    match = FRONT_RE.match(text)
    if not match:
        raise ValueError(f"Front-matter not found in {path}")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("ALOU front-matter must be a mapping")
    return data


class ScopeError(PermissionError):
    """Raised when runtime scope enforcement denies an operation."""


class FileScope:
    def __init__(self, base_dir: Path, write_scopes: Iterable[str]) -> None:
        self.base_dir = base_dir.resolve()
        self.write_scopes = list(write_scopes)
        if not self.write_scopes:
            raise ScopeError("No write scopes configured")

    def _normalize_target(self, path: Path) -> Path:
        string_path = str(path)
        if string_path.startswith("~"):
            raise ScopeError(f"tilde paths not allowed: {string_path}")
        if Path(string_path).is_absolute():
            raise ScopeError(f"absolute paths not allowed: {string_path}")
        candidate = self.base_dir / string_path
        if candidate.is_symlink():
            raise ScopeError(f"symlink not allowed in path: {string_path}")
        candidate = candidate.resolve()
        if candidate.is_symlink():
            raise ScopeError(f"symlink not allowed in path: {string_path}")
        try:
            candidate.relative_to(self.base_dir)
        except ValueError:
            raise ScopeError(f"path escapes base_dir: {string_path}")
        current = candidate
        while True:
            if current.is_symlink():
                raise ScopeError(f"symlink not allowed in path: {string_path}")
            if current == self.base_dir:
                break
            current = current.parent
        return candidate

    def _match_scopes(self, target: Path) -> bool:
        relative = str(target.relative_to(self.base_dir)).replace("\\", "/")
        return any(fnmatch.fnmatch(relative, pattern) for pattern in self.write_scopes)

    def assert_write_allowed(self, path: Path) -> Path:
        target = self._normalize_target(path)
        if not self._match_scopes(target):
            raise ScopeError(f"write not allowed by fs_write_scopes: {path}")
        return target

    def open_write(
        self,
        path: Path,
        *,
        binary: bool = False,
        create_parents: bool = True,
    ):
        target = self.assert_write_allowed(path)
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
        mode = "wb" if binary else "w"
        handle = open(tmp, mode)

        class _Atomic:
            def __enter__(self):
                return handle

            def __exit__(self, exc_type, exc, tb):
                handle.close()
                if exc is None:
                    if target.exists() and target.is_symlink():
                        raise ScopeError(f"symlink not allowed in path: {path}")
                    tmp.replace(target)
                else:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass

        return _Atomic()

    def write_text(self, path: Path, text: str) -> Path:
        with self.open_write(path, binary=False) as handle:
            handle.write(text)
        return (self.base_dir / path).resolve()

    def write_bytes(self, path: Path, data: bytes) -> Path:
        with self.open_write(path, binary=True) as handle:
            handle.write(data)
        return (self.base_dir / path).resolve()


class MCPGuard:
    def __init__(self, allowed: Iterable[str]) -> None:
        allowed_set = set(allowed)
        if not allowed_set:
            raise ScopeError("No MCP endpoints allowed")
        self.allowed = allowed_set

    def assert_allowed(self, endpoint: str) -> None:
        if endpoint not in self.allowed:
            raise ScopeError(f"MCP endpoint not allowed: {endpoint}")

    def wrap(self, call: Callable[..., object]) -> Callable[..., object]:
        def _wrapped(endpoint: str, action: str, *args, **kwargs):
            self.assert_allowed(endpoint)
            return call(endpoint, action, *args, **kwargs)

        return _wrapped


class RuntimeGuard:
    def __init__(self, file_scope: FileScope, mcp_guard: MCPGuard) -> None:
        self.fs = file_scope
        self._mcp = mcp_guard

    @classmethod
    def from_alou(
        cls,
        alou_path: str | Path,
        *,
        base_dir: str | Path = ".",
    ) -> "RuntimeGuard":
        frontmatter = _load_alou_frontmatter(Path(alou_path))
        mcp_allow = frontmatter.get("mcp_allow", [])
        write_scopes = frontmatter.get("fs_write_scopes", [])
        if not mcp_allow or not write_scopes:
            raise ValueError("ALOU missing mcp_allow or fs_write_scopes")
        file_scope = FileScope(Path(base_dir), write_scopes)
        mcp_guard = MCPGuard(mcp_allow)
        return cls(file_scope, mcp_guard)

    def wrap_tool_call(self, raw_call: Callable[..., object]) -> Callable[..., object]:
        return self._mcp.wrap(raw_call)
