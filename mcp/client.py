"""MCP client with runtime-guard integration and remote fallback.

The default implementation uses local stubs for file/search interactions. When
environment variable ``ACCORD_MCP_MODE`` is set to ``remote`` the client will
attempt to call HTTP endpoints defined by ``ACCORD_MCP_FILE_URL`` and
``ACCORD_MCP_SEARCH_URL``. If the remote calls fail, the client logs a warning
and falls back to the stub behaviour.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List
from urllib import error, parse, request

from scripts.runtime_guard import RuntimeGuard, ScopeError

LOGGER = logging.getLogger(__name__)

from .index import SimpleIndex


class MCPError(RuntimeError):
    """Raised when an MCP call fails or an unsupported endpoint is used."""


@dataclass
class MCPResponse:
    endpoint: str
    action: str
    data: Any


class MCPClient:
    """Tiny MCP client that dispatches to local adapters under guard control."""

    def __init__(self, guard: RuntimeGuard, *, base_dir: Path | None = None) -> None:
        self._guard = guard
        self._base_dir = (base_dir or Path(".")).resolve()
        self._wrapped = guard.wrap_tool_call(self._dispatch)
        self._remote = None
        self._remote_active = False
        mode = os.getenv("ACCORD_MCP_MODE", "stub").lower()
        if mode == "remote":
            file_url = os.getenv("ACCORD_MCP_FILE_URL")
            search_url = os.getenv("ACCORD_MCP_SEARCH_URL")
            try:
                self._remote = _RemoteAdapter(file_url=file_url, search_url=search_url)
                self._remote_active = True
                LOGGER.info(
                    "Using remote MCP endpoints (file=%s, search=%s)",
                    file_url,
                    search_url,
                )
            except Exception as exc:
                LOGGER.warning(
                    "Remote MCP setup failed (%s). Falling back to stub implementation.",
                    exc,
                )
                self._remote = None
                self._remote_active = False
        self._index = SimpleIndex(self._base_dir)

    # Public API ---------------------------------------------------------
    def call(self, endpoint: str, action: str, **kwargs: Any) -> MCPResponse:
        """Invoke a tool endpoint, returning an ``MCPResponse`` envelope."""

        result = self._wrapped(endpoint, action, **kwargs)
        return MCPResponse(endpoint=endpoint, action=action, data=result)

    # Dispatch -----------------------------------------------------------
    def _dispatch(self, endpoint: str, action: str, *args: Any, **kwargs: Any) -> Any:
        handler_name = f"_handle_{endpoint}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            raise MCPError(f"unsupported endpoint: {endpoint}")
        if self._remote_active and endpoint in {"file", "search"} and self._remote:
            try:
                return self._remote.handle(endpoint, action, *args, **kwargs)
            except RemoteError as exc:
                LOGGER.warning(
                    "Remote MCP call failed (%s). Reverting to stub for remainder of session.",
                    exc,
                )
                self._remote_active = False
        return handler(action, *args, **kwargs)

    # Endpoint handlers --------------------------------------------------
    def _handle_file(self, action: str, *, path: str) -> Any:
        candidate = self._resolve_path(path)
        if action in {"read", "read_text"}:
            return candidate.read_text(encoding="utf-8")
        if action == "read_bytes":
            return candidate.read_bytes()
        if action == "list" and candidate.is_dir():
            return sorted(str(p.relative_to(self._base_dir)) for p in candidate.rglob("*"))
        raise MCPError(f"unsupported file action: {action}")

    def _handle_search(
        self,
        action: str,
        *,
        pattern: str,
        paths: Iterable[str] | None = None,
        limit: int = 20,
    ) -> List[dict[str, Any]]:
        if action != "grep":
            raise MCPError(f"unsupported search action: {action}")
        roots = [self._resolve_path(p) for p in (paths or ["."])]
        findings: List[dict[str, Any]] = []

        indexed = self._index.search(pattern, limit)
        findings.extend(indexed)
        seen = {item["file"] for item in findings}
        for root in roots:
            files = [root] if root.is_file() else list(root.rglob("*.md"))
            for file_path in files:
                try:
                    text = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                rel = str(file_path.relative_to(self._base_dir))
                if rel in seen:
                    continue
                if pattern in text:
                    findings.append(
                        {
                            "file": rel,
                            "snippet": _first_line_with(text, pattern),
                        }
                    )
                    seen.add(rel)
                if len(findings) >= limit:
                    return findings
        return findings

    def _handle_knowledge(
        self,
        action: str,
        *,
        topic: str,
        notes_dir: str = "docs",
        limit: int = 5,
    ) -> List[str]:
        if action != "retrieve":
            raise MCPError(f"unsupported knowledge action: {action}")
        root = self._resolve_path(notes_dir)
        indexed = self._index.knowledge(topic, limit)
        matches: List[str] = list(indexed)
        if len(matches) >= limit:
            return matches[:limit]

        if not root.exists():
            return matches
        for path in sorted(root.glob("**/*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = str(path.relative_to(self._base_dir))
            if rel in matches:
                continue
            if topic.lower() in text.lower():
                matches.append(rel)
            if len(matches) >= limit:
                break
        return matches

    # Helpers ------------------------------------------------------------
    def _resolve_path(self, raw: str) -> Path:
        path = Path(raw)
        if path.is_absolute() or str(path).startswith("~"):
            raise ScopeError(f"absolute or tilde path not allowed in MCP call: {raw}")
        candidate = (self._base_dir / path).resolve()
        try:
            candidate.relative_to(self._base_dir)
        except ValueError as exc:
            raise ScopeError(f"MCP path escapes base dir: {raw}") from exc
        if candidate.is_symlink():
            raise ScopeError(f"symlink targets not allowed: {raw}")
        return candidate


def _first_line_with(text: str, pattern: str) -> str:
    lower = pattern.lower()
    for line in text.splitlines():
        if lower in line.lower():
            return line.strip()
    return ""


class RemoteError(RuntimeError):
    """Raised when remote MCP operations fail."""


class _RemoteAdapter:
    def __init__(self, *, file_url: str | None, search_url: str | None) -> None:
        if not file_url or not search_url:
            raise ValueError("ACCORD_MCP_FILE_URL and ACCORD_MCP_SEARCH_URL must be set")
        self._file_url = file_url.rstrip("/")
        self._search_url = search_url.rstrip("/")

    def handle(self, endpoint: str, action: str, *args: Any, **kwargs: Any) -> Any:
        if endpoint == "file":
            return self._handle_file(action, **kwargs)
        if endpoint == "search":
            return self._handle_search(action, **kwargs)
        raise RemoteError(f"remote endpoint not supported: {endpoint}")

    def _handle_file(self, action: str, *, path: str) -> Any:
        if action in {"read", "read_text"}:
            data = self._http_get(self._file_url + "/file", {"path": path})
            return data.decode("utf-8") if action == "read_text" else data
        if action == "read_bytes":
            return self._http_get(self._file_url + "/file", {"path": path})
        if action == "list":
            payload = self._http_get(self._file_url + "/list", {"path": path})
            return json.loads(payload.decode("utf-8"))
        raise RemoteError(f"unsupported file action: {action}")

    def _handle_search(self, action: str, *, pattern: str, limit: int = 20, paths: Iterable[str] | None = None) -> List[dict[str, Any]]:
        if action != "grep":
            raise RemoteError(f"unsupported search action: {action}")
        params = {"pattern": pattern, "limit": str(limit)}
        payload = self._http_get(self._search_url + "/search", params)
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, list):
            raise RemoteError("search response malformed")
        return data

    def _http_get(self, base: str, params: dict[str, str]) -> bytes:
        query = parse.urlencode(params)
        url = f"{base}?{query}" if params else base
        try:
            with request.urlopen(url, timeout=5) as response:  # type: ignore[assignment]
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise RemoteError(f"HTTP {status} for {url}")
                return response.read()
        except error.URLError as exc:
            raise RemoteError(exc.reason)
