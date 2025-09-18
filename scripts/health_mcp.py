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


def check_endpoint(endpoint: Endpoint, timeout: float) -> str | None:
    health_url = endpoint.url + "/health"
    try:
        with request.urlopen(health_url, timeout=timeout) as resp:  # type: ignore[assignment]
            if getattr(resp, "status", 200) >= 400:
                return f"{endpoint.name}: HTTP {getattr(resp, 'status', 'unknown')}"
            try:
                body = resp.read().decode("utf-8")
                if body:
                    json.loads(body)
            except Exception:
                # Non-JSON bodies are tolerated as long as status is OK
                pass
            return None
    except error.URLError as exc:
        return f"{endpoint.name}: unreachable ({exc.reason})"
    except Exception as exc:  # pragma: no cover
        return f"{endpoint.name}: error ({exc})"


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
    args = parser.parse_args(argv)

    try:
        endpoints = parse_endpoints(args.endpoint)
    except ValueError as exc:
        print(str(exc))
        return 2

    if not endpoints:
        print("No endpoints supplied.")
        return 1

    issues = check_endpoints(endpoints, args.timeout)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print("All MCP endpoints healthy.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
