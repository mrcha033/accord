from urllib import error

from scripts import health_mcp


class DummyResponse:
    def __init__(self, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self) -> "DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - nothing to clean up
        return None

    def read(self) -> bytes:
        return self._body


def test_health_mcp_success(monkeypatch) -> None:
    def fake_urlopen(url, timeout=5):
        return DummyResponse()

    monkeypatch.setattr(health_mcp.request, "urlopen", fake_urlopen)
    endpoints = health_mcp.parse_endpoints(["file=http://localhost:8080"])
    issues = health_mcp.check_endpoints(endpoints, timeout=1)
    assert issues == []


def test_health_mcp_failure(monkeypatch) -> None:
    def fake_fail(url, timeout=5):
        raise error.URLError("fail")

    monkeypatch.setattr(health_mcp.request, "urlopen", fake_fail)
    endpoints = health_mcp.parse_endpoints(["file=http://localhost:8080"])
    issues = health_mcp.check_endpoints(endpoints, timeout=1)
    assert issues and "unreachable" in issues[0]
