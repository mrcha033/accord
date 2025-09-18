import logging
import os

import pytest

from mcp.client import MCPClient
from scripts.runtime_guard import RuntimeGuard


@pytest.fixture()
def guard() -> RuntimeGuard:
    return RuntimeGuard.from_alou("org/_registry/AGENT-OPS01.alou.md", base_dir=".")


def test_remote_fallback_to_stub(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, guard: RuntimeGuard) -> None:
    monkeypatch.setenv("ACCORD_MCP_MODE", "remote")
    monkeypatch.setenv("ACCORD_MCP_FILE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ACCORD_MCP_SEARCH_URL", "http://127.0.0.1:9")
    caplog.set_level(logging.WARNING)

    client = MCPClient(guard)
    response = client.call("file", "read_text", path="scripts/validate_alou.py")
    assert "ALOU" in response.data
    assert any("Remote MCP call failed" in record.message for record in caplog.records)
    # second call uses stub immediately
    response2 = client.call("file", "read_text", path="scripts/validate_alou.py")
    assert "ALOU" in response2.data
