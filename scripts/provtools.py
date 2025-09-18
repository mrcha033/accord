"""Provenance tooling for in-toto Statements + DSSE signatures."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, cast

import yaml
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from jsonschema import Draft202012Validator

COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)
PAYLOAD_TYPE = "application/vnd.in-toto+json"

STATEMENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["_type", "subject", "predicateType", "predicate"],
    "properties": {
        "_type": {
            "type": "string",
            "pattern": r"^https://in-toto\.io/Statement/v(0\.1|1)$",
        },
        "subject": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "digest": {"type": "object"},
                },
            },
        },
        "predicateType": {
            "type": "string",
            "pattern": r"^https://.+",
        },
        "predicate": {"type": "object"},
    },
    "additionalProperties": True,
}


try:  # local execution vs package
    from scripts.provtools_cache import HashRaceError, sha256_cached
except ModuleNotFoundError:  # pragma: no cover - fallback when run as script
    from provtools_cache import HashRaceError, sha256_cached  # type: ignore


def _sha256(path: Path) -> str:
    return sha256_cached(path)


def extract_header(md_text: str) -> Dict[str, Any]:
    """Return the provenance mapping extracted from a Markdown comment.

    Iterates over HTML comments that include ``provenance:`` (case-insensitive)
    and returns the first valid mapping, supporting both wrapped and legacy
    layouts for backward compatibility.
    """

    for match in COMMENT_RE.finditer(md_text):
        body = match.group(1).strip()
        if "provenance:" not in body.lower():
            continue
        raw = yaml.safe_load(body)
        if not isinstance(raw, dict):
            continue
        provenance = raw.get("provenance", raw) or {}
        if isinstance(provenance, dict):
            return provenance
        raise ValueError("provenance block is not a mapping")

    raise ValueError("provenance header not found")


def normalize_to_statement(header: Dict[str, Any]) -> Dict[str, Any]:
    statement_type = header.get("_type") or header.get("statement_type")
    predicate_type = header.get("predicateType") or header.get("predicate_type")
    subjects = header.get("subject", [])

    normalized_subjects: List[Dict[str, Any]] = []
    for subject in subjects:
        subject = dict(subject)
        if "uri" in subject and "name" not in subject:
            subject["name"] = subject.pop("uri")
        subject.setdefault("digest", {})
        normalized_subjects.append(subject)

    predicate = dict(header.get("predicate", {}))
    if "materials" in header and "materials" not in predicate:
        predicate["materials"] = header["materials"]

    return {
        "_type": statement_type,
        "subject": normalized_subjects,
        "predicateType": predicate_type,
        "predicate": predicate,
    }


def validate_statement(statement: Dict[str, Any]) -> List[str]:
    validator = Draft202012Validator(STATEMENT_SCHEMA)
    return [
        f"{error.message} @ {'/'.join(map(str, error.path))}"
        for error in validator.iter_errors(statement)
    ]


def fill_and_check_digests(base_dir: Path, statement: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    for subject in statement.get("subject", []):
        name = subject.get("name")
        if not name:
            errors.append("subject missing name")
            continue
        if Path(name).is_absolute() or name.startswith(("~", "/", "\\")):
            errors.append(f"absolute or home path not allowed: {name}")
            continue
        digest = subject.setdefault("digest", {})
        candidate = (base_dir / name)
        if candidate.is_symlink():
            errors.append(f"symlink not allowed: {name}")
            continue
        target = candidate.resolve()
        try:
            target.relative_to(base_dir)
        except ValueError:
            errors.append(f"path escapes base_dir: {name}")
            continue
        if not target.exists():
            errors.append(f"subject path not found: {name}")
            continue
        try:
            actual = _sha256(target)
        except HashRaceError:
            errors.append(f"file changed during hashing: {name}")
            continue
        except FileNotFoundError:
            errors.append(f"subject path not found: {name}")
            continue
        if "sha256" in digest:
            if digest["sha256"].lower() != actual:
                errors.append(f"subject digest mismatch for {name}")
        else:
            digest["sha256"] = actual

    materials = statement.get("predicate", {}).get("materials", []) or []
    for material in materials:
        name = material.get("name") or material.get("uri")
        if not name:
            errors.append("material missing name")
            continue

        material["name"] = name
        material.pop("uri", None)
        digest = material.setdefault("digest", {})

        if re.match(r"^[a-z]+://", name):
            if "sha256" not in digest:
                errors.append(f"remote material requires digest: {name}")
            continue

        if Path(name).is_absolute() or name.startswith(("~", "/", "\\")):
            errors.append(f"absolute or home path not allowed: {name}")
            continue

        candidate = (base_dir / name)
        if candidate.is_symlink():
            errors.append(f"symlink not allowed: {name}")
            continue
        target = candidate.resolve()
        try:
            target.relative_to(base_dir)
        except ValueError:
            errors.append(f"path escapes base_dir: {name}")
            continue
        if not target.exists():
            errors.append(f"material path not found: {name}")
            continue

        try:
            actual = _sha256(target)
        except HashRaceError:
            errors.append(f"file changed during hashing: {name}")
            continue
        except FileNotFoundError:
            errors.append(f"material path not found: {name}")
            continue
        if "sha256" in digest:
            if digest["sha256"].lower() != actual:
                errors.append(f"materials digest mismatch for {name}")
        else:
            digest["sha256"] = actual

    return errors


def pae(payload_type: str, payload: bytes) -> bytes:
    return b" ".join(
        [
            b"DSSEv1",
            str(len(payload_type)).encode(),
            payload_type.encode(),
            str(len(payload)).encode(),
            payload,
        ]
    )


def keygen_ed25519(priv_path: Path, pub_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path.write_bytes(priv_bytes)
    pub_path.write_bytes(pub_bytes)


def load_priv(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):  # defensive type check
        raise TypeError("Expected Ed25519 private key")
    return cast(Ed25519PrivateKey, key)


def load_pub(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):  # defensive type check
        raise TypeError("Expected Ed25519 public key")
    return cast(Ed25519PublicKey, key)


def key_fingerprint(public_key: Ed25519PublicKey) -> str:
    """Return a stable identifier for the provided Ed25519 public key."""

    raw = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashes.Hash(hashes.SHA256())
    digest.update(raw)
    return digest.finalize().hex()[:16]


def dsse_sign(statement: Dict[str, Any], priv_pem: Path, key_id: str = "") -> Dict[str, Any]:
    subjects = statement.get("subject")
    if isinstance(subjects, list):
        statement["subject"] = sorted(
            subjects,
            key=lambda item: (item.get("name") or ""),
        )

    predicate = statement.get("predicate")
    if isinstance(predicate, dict):
        materials = predicate.get("materials")
        if isinstance(materials, list):
            predicate["materials"] = sorted(
                materials,
                key=lambda item: (item.get("name") or ""),
            )

    payload = json.dumps(
        statement,
        separators=(",", ":"),
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    private_key = load_priv(priv_pem)
    if not key_id:
        key_id = key_fingerprint(private_key.public_key())
    signature = private_key.sign(pae(PAYLOAD_TYPE, payload))
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode(),
        "signatures": [
            {
                "keyid": key_id,
                "sig": base64.b64encode(signature).decode(),
            }
        ],
    }


def dsse_verify(envelope: Dict[str, Any], pub_pem: Path) -> bool:
    payload_type = envelope["payloadType"]
    if payload_type != PAYLOAD_TYPE:
        raise ValueError(f"unsupported payloadType: {payload_type}")

    payload = base64.b64decode(envelope["payload"])
    signature = base64.b64decode(envelope["signatures"][0]["sig"])
    public_key = load_pub(pub_pem)
    public_key.verify(signature, pae(payload_type, payload))
    return True


def cmd_keygen(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    priv = out_dir / "ed25519.key"
    pub = out_dir / "ed25519.pub"
    keygen_ed25519(priv, pub)
    print(f"keys written to {out_dir}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    trace_id = uuid.uuid4().hex
    target = Path(args.file)
    md_text = target.read_text(encoding="utf-8")
    header = extract_header(md_text)
    statement = normalize_to_statement(header)
    errors = validate_statement(statement)
    base_dir = Path(args.base).resolve()
    errors.extend(fill_and_check_digests(base_dir, statement))

    if errors:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        print(
            json.dumps(
                {
                    "event": "build",
                    "ok": False,
                    "file": str(target),
                    "dsse": str(args.out),
                    "errors": errors,
                    "trace_id": trace_id,
                    "duration_ms": duration_ms,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    envelope = dsse_sign(statement, Path(args.priv), key_id=args.keyid or "")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(
        f"{out_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    tmp_path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    print(
        json.dumps(
            {
                "event": "build",
                "ok": True,
                "file": str(target),
                "dsse": str(out_path),
                "trace_id": trace_id,
                "duration_ms": duration_ms,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    trace_id = uuid.uuid4().hex
    dsse_path = Path(args.dsse)
    envelope = json.loads(dsse_path.read_text(encoding="utf-8"))
    schema_errors: List[str] = []
    digest_errors: List[str] = []
    errors: List[str] = []
    signature_ok = False

    try:
        dsse_verify(envelope, Path(args.pub))
        signature_ok = True
    except Exception as exc:  # surface signature failures explicitly
        errors.append(str(exc))

    if signature_ok:
        statement = json.loads(base64.b64decode(envelope["payload"]).decode())
        schema_errors = validate_statement(statement)
        if not schema_errors:
            digest_errors = fill_and_check_digests(Path(args.base).resolve(), statement)
        errors.extend(schema_errors)
        errors.extend(digest_errors)

    schema_ok = signature_ok and not schema_errors
    digest_ok = signature_ok and not digest_errors

    if signature_ok and schema_ok and digest_ok:
        error_code = "OK"
    elif not signature_ok:
        error_code = "SIG_INVALID"
    elif schema_errors:
        error_code = "SCHEMA_INVALID"
    elif digest_errors:
        if any("file changed during hashing" in e for e in digest_errors):
            error_code = "HASH_RACE"
        elif any("path" in e and "allowed" in e for e in digest_errors):
            error_code = "PATH_FORBIDDEN"
        elif any("digest mismatch" in e for e in digest_errors):
            error_code = "DIGEST_MISMATCH"
        else:
            error_code = "DIGEST_INVALID"
    elif errors:
        error_code = "UNKNOWN_ERROR"
    else:
        error_code = "UNKNOWN_ERROR"

    payload = {
        "event": "verify",
        "signature_ok": signature_ok,
        "schema_ok": schema_ok,
        "digest_ok": digest_ok,
        "statement_ok": signature_ok and not errors,
        "errors": errors,
        "dsse": str(dsse_path),
        "trace_id": trace_id,
        "duration_ms": int((time.perf_counter() - t0) * 1000),
        "error_code": error_code,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if signature_ok and schema_ok and digest_ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    keygen = sub.add_parser("keygen", help="generate Ed25519 keypair")
    keygen.add_argument("--out", default="keys", help="output directory for keypair")
    keygen.set_defaults(func=cmd_keygen)

    build_cmd = sub.add_parser("build", help="normalize, validate, and sign a Statement")
    build_cmd.add_argument("file", help="Markdown artifact with provenance header")
    build_cmd.add_argument("--priv", required=True, help="PEM private key path")
    build_cmd.add_argument("--out", default="attestations/out.dsse", help="DSSE output path")
    build_cmd.add_argument("--base", default=".", help="base directory for digest resolution")
    build_cmd.add_argument("--keyid", default="", help="key identifier to embed in DSSE")
    build_cmd.set_defaults(func=cmd_build)

    verify_cmd = sub.add_parser("verify", help="verify DSSE signature and digests")
    verify_cmd.add_argument("dsse", help="path to DSSE envelope")
    verify_cmd.add_argument("--pub", required=True, help="PEM public key path")
    verify_cmd.add_argument("--base", default=".", help="base directory for digest resolution")
    verify_cmd.set_defaults(func=cmd_verify)

    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main(sys.argv))
