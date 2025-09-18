"""ALOU v1.1 validator.

Parses Markdown front-matter, validates against JSON Schema, and enforces
additional guardrails for MCP endpoints and filesystem scopes.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml
from jsonschema import Draft202012Validator

FRONT_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "agent_id",
        "role_title",
        "cluster_path",
        "revision",
        "status",
        "version",
        "effective_from",
        "capabilities",
        "mcp_allow",
        "fs_write_scopes",
        "gedi",
        "runtime",
        "provenance",
        "security",
    ],
    "properties": {
        "version": {"type": "string", "const": "1.1"},
        "idempotency_key": {"type": "string", "minLength": 1},
        "agent_id": {"type": "string", "pattern": r"^AGENT-[A-Za-z0-9_-]+$"},
        "role_title": {"type": "string", "minLength": 1},
        "cluster_path": {
            "type": "object",
            "required": ["chapter", "squad"],
            "properties": {
                "chapter": {"type": "string", "minLength": 1},
                "squad": {"type": "string", "minLength": 1},
                "guilds": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                },
            },
        },
        "revision": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "coach_agent": {
            "anyOf": [
                {"type": "string", "pattern": r"^AGENT-[A-Za-z0-9_-]+$"},
                {"type": "string", "const": "NONE"},
                {"type": "null"},
            ]
        },
        "status": {"enum": ["active", "standby", "retired"]},
        "effective_from": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "expires": {
            "anyOf": [
                {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                {"type": "string", "const": "NONE"},
                {"type": "null"},
            ]
        },
        "capabilities": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "mcp_allow": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "fs_write_scopes": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
        "data_classification": {
            "enum": ["public", "internal", "restricted", "secret"],
            "default": "internal",
        },
        "gedi": {
            "type": "object",
            "required": ["roles", "vote_weight", "quorum"],
            "properties": {
                "roles": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "vote_weight": {
                    "type": "number",
                    "minimum": 0.0,
                },
                "quorum": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "recusal_rules": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                },
            },
        },
        "provenance": {
            "type": "object",
            "required": ["attestation_path", "hash_algo", "key_id"],
            "properties": {
                "attestation_path": {"type": "string", "minLength": 1},
                "hash_algo": {"enum": ["sha256", "sha384", "sha512"]},
                "key_id": {"type": "string", "minLength": 1},
            },
        },
        "security": {
            "type": "object",
            "required": ["threat_model", "forbidden_ops"],
            "properties": {
                "threat_model": {"type": "string", "minLength": 1},
                "forbidden_ops": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
        },
        "rotation_policy": {"type": "string", "minLength": 1},
        "runtime": {
            "type": "object",
            "required": ["prompt_path", "output_path", "summary_path"],
            "properties": {
                "prompt_path": {"type": "string", "minLength": 1},
                "output_path": {"type": "string", "minLength": 1},
                "summary_path": {"type": "string", "minLength": 1},
                "context_roots": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                },
                "prompt_template": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": True,
}

ALLOWED_MCP = {"file", "git", "search", "browser", "db", "knowledge"}
FORBIDDEN_FS = {
    "**/.git/**",
    "**/secrets/**",
    "**/.env",
    "**/keys/**",
}


def extract_frontmatter(md_text: str) -> Dict[str, Any]:
    match = FRONT_RE.match(md_text)
    if not match:
        raise ValueError("Front-matter not found")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("Front-matter is not a mapping")
    return data


def extra_checks(doc: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    # MCP endpoints must be from the allow-list.
    bad_mcp = [item for item in doc.get("mcp_allow", []) if item not in ALLOWED_MCP]
    if bad_mcp:
        errors.append(f"mcp_allow contains unknown endpoints: {bad_mcp}")

    # Forbidden filesystem patterns must never be included.
    for scope in doc.get("fs_write_scopes", []):
        for forbidden in FORBIDDEN_FS:
            if fnmatch.fnmatch(scope, forbidden) or fnmatch.fnmatch(forbidden, scope):
                errors.append(
                    f"fs_write_scopes overlaps with forbidden path: {scope} ~ {forbidden}"
                )

    runtime = doc.get("runtime", {})
    if isinstance(runtime, dict):
        for key in ("prompt_path", "output_path", "summary_path"):
            value = runtime.get(key)
            if isinstance(value, str) and Path(value).is_absolute():
                errors.append(f"runtime.{key} must be a relative path: {value}")
        for root in runtime.get("context_roots", []) or []:
            if isinstance(root, str) and Path(root).is_absolute():
                errors.append(f"runtime.context_roots entries must be relative paths: {root}")

    return errors


def validate_file(path: Path) -> int:
    md_text = path.read_text(encoding="utf-8")
    frontmatter = extract_frontmatter(md_text)

    validator = Draft202012Validator(SCHEMA)
    schema_errors = [
        f"{error.message} @ {'/'.join(map(str, error.path))}"
        for error in validator.iter_errors(frontmatter)
    ]
    guardrail_errors = extra_checks(frontmatter)
    errors = schema_errors + guardrail_errors

    if errors:
        print(
            json.dumps(
                {"file": str(path), "ok": False, "errors": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps({"file": str(path), "ok": True, "agent_id": frontmatter["agent_id"]}, ensure_ascii=False))
    return 0


def main(argv: List[str]) -> int:
    if len(argv) <= 1:
        print(
            "Usage: python validate_alou.py path/to/file.alou.md [more.alou.md]",
            file=sys.stderr,
        )
        return 2

    exit_code = 0
    for name in argv[1:]:
        path = Path(name)
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            exit_code = max(exit_code, 2)
            continue
        result = validate_file(path)
        exit_code = max(exit_code, result)

    return exit_code


def cli() -> int:
    """Entry-point wrapper for setuptools."""

    return main(sys.argv)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(cli())
