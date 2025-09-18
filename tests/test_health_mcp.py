from urllib import error

from scripts import health_mcp


def test_health_mcp_success(monkeypatch) -> None:
    monkeypatch.setattr(
        health_mcp,
        "_health_request",
        lambda url, timeout, method: (200, b"{}"),
    )
    endpoints = health_mcp.parse_endpoints(["file=http://localhost:8080"])
    issues = health_mcp.check_endpoints(endpoints, timeout=1)
    assert issues == []


def test_health_mcp_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        health_mcp,
        "_health_request",
        lambda url, timeout, method: None,
    )
    endpoints = health_mcp.parse_endpoints(["file=http://localhost:8080"])
    issues = health_mcp.check_endpoints(endpoints, timeout=1)
    assert issues and "unreachable" in issues[0]
