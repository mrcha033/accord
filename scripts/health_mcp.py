"""Check health of configured MCP endpoints."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List
from urllib import error, parse, request


DEFAULT_ENDPOINTS = {
    "file": os.getenv("ACCORD_MCP_FILE_URL"),
    "search": os.getenv("ACCORD_MCP_SEARCH_URL"),
}


@dataclass
class Endpoint:
    name: str
    url: str


def _normalize(url: str | None) -> str | None:
    if not url:
        return None
    return url.rstrip("/")


def parse_endpoints(values: Iterable[str]) -> Dict[str, Endpoint]:
    endpoints: Dict[str, Endpoint] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid endpoint specification '{item}'. Use name=url")
        name, url = item.split("=", 1)
        norm = _normalize(url)
        if not norm:
            raise ValueError(f"Empty URL for endpoint '{name}'")
        endpoints[name] = Endpoint(name=name, url=norm)
    if not endpoints:
        for key, value in DEFAULT_ENDPOINTS.items():
            norm = _normalize(value)
            if norm:
                endpoints[key] = Endpoint(name=key, url=norm)
    return endpoints


def _health_request(url: str, timeout: float, method: str) -> tuple[int, bytes] | None:
    req = request.Request(url, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:  # type: ignore[assignment]
            status = getattr(resp, "status", 200)
            data = b"" if method == "HEAD" else resp.read()
            return status, data
    except error.URLError:
        return None


def check_endpoint(endpoint: Endpoint, timeout: float) -> str | None:
    health_url = endpoint.url + "/health"
    result = _health_request(health_url, timeout, "HEAD")
    if result is None:
        result = _health_request(health_url, timeout, "GET")
    if result is None:
        return f"{endpoint.name}: unreachable"
    status, data = result
    if status >= 400:
        return f"{endpoint.name}: HTTP {status}"
    if data:
        try:
            json.loads(data.decode("utf-8"))
        except Exception:
            pass
    return None


def check_endpoints(endpoints: Dict[str, Endpoint], timeout: float) -> List[str]:
    issues: List[str] = []
    for endpoint in endpoints.values():
        problem = check_endpoint(endpoint, timeout)
        if problem:
            issues.append(problem)
    return issues


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="Endpoint definition name=url. Defaults to ACCORD_MCP_* env vars.",
    )
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout per request in seconds")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args(argv)

    try:
        endpoints = parse_endpoints(args.endpoint)
    except ValueError as exc:
        print(str(exc))
        return 2

    if not endpoints:
        message = "No endpoints supplied."
        if args.json:
            print(json.dumps({"ok": False, "issues": [message]}, ensure_ascii=False))
        else:
            print(message)
        return 1

    issues = check_endpoints(endpoints, args.timeout)
    if issues:
        if args.json:
            print(json.dumps({"ok": False, "issues": issues}, ensure_ascii=False))
        else:
            for issue in issues:
                print(issue)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "issues": []}, ensure_ascii=False))
    else:
        print("All MCP endpoints healthy.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
