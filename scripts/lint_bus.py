"""Lint bus documents to enforce channel-specific templates.

Channels:
- alerts: require `# ALERT` header plus `Impact:`, `Actions:`, `Owner:` fields.
- daily: require `# Draft generated` header and bullet lines for generated/agent plus `_DSSE` note.
- inbox: require `# Request` header and requester/owner fields.
- policy: require top-level heading and adoption/summary context.

Usage: `python -m scripts.lint_bus [--base PATH]`
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, List


class LintError(Exception):
    """Raised when lint validation fails."""


def _strip_provenance(lines: Iterable[str]) -> List[str]:
    out: List[str] = []
    skip = False
    for line in lines:
        if line.lstrip().startswith("<!--"):
            skip = True
            continue
        if skip and line.rstrip().endswith("-->"):
            skip = False
            continue
        if not skip:
            out.append(line.rstrip("\n"))
    return out


def _require(condition: bool, message: str, errors: List[str]) -> None:
    if not condition:
        errors.append(message)


def lint_alert(path: Path) -> List[str]:
    lines = _strip_provenance(path.read_text(encoding="utf-8").splitlines())
    errors: List[str] = []
    content = [line.strip() for line in lines if line.strip()]
    _require(bool(content), "no content", errors)
    if content:
        _require(
            content[0].startswith("# ALERT"),
            "first heading must start with '# ALERT'",
            errors,
        )
    joined = "\n".join(content)
    for required in ("Impact:", "Actions:", "Owner:"):
        _require(required in joined, f"missing '{required}' field", errors)
    return errors


def lint_daily(path: Path) -> List[str]:
    lines = _strip_provenance(path.read_text(encoding="utf-8").splitlines())
    errors: List[str] = []
    content = [line.strip() for line in lines if line.strip()]
    _require(bool(content), "no content", errors)
    if content:
        _require(
            content[0].startswith("# Draft generated"),
            "first heading must start with '# Draft generated'",
            errors,
        )
    joined = "\n".join(content)
    for required in ("- Generated:", "- Agent:"):
        _require(required in joined, f"missing '{required}' bullet", errors)
    _require("DSSE" in joined, "missing DSSE note", errors)
    return errors


def lint_inbox(path: Path) -> List[str]:
    lines = _strip_provenance(path.read_text(encoding="utf-8").splitlines())
    errors: List[str] = []
    content = [line.strip() for line in lines if line.strip()]
    _require(bool(content), "no content", errors)
    if content:
        _require(
            content[0].startswith("# Request"),
            "first heading must start with '# Request'",
            errors,
        )
    joined = "\n".join(content)
    for required in ("**Raised by**", "**Owner**", "**Status**"):
        _require(required in joined, f"missing '{required}' field", errors)
    return errors


def lint_policy(path: Path) -> List[str]:
    lines = _strip_provenance(path.read_text(encoding="utf-8").splitlines())
    errors: List[str] = []
    content = [line.strip() for line in lines if line.strip()]
    _require(bool(content), "no content", errors)
    if content:
        _require(
            content[0].startswith("#"),
            "policy summaries must begin with a heading",
            errors,
        )
    return errors


CHANNEL_RULES = {
    "alerts": lint_alert,
    "daily": lint_daily,
    "inbox": lint_inbox,
    "policy": lint_policy,
}


def lint_bus(base_dir: Path) -> List[str]:
    errors: List[str] = []
    bus_dir = base_dir / "bus"
    if not bus_dir.exists():
        return ["bus directory not found"]
    for channel, checker in CHANNEL_RULES.items():
        folder = bus_dir / channel
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            issues = checker(path)
            if issues:
                for issue in issues:
                    errors.append(f"{path.relative_to(base_dir)}: {issue}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=".", help="Base directory of repository")
    args = parser.parse_args(argv)
    base_dir = Path(args.base).resolve()
    issues = lint_bus(base_dir)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    print("bus lint: ok")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
