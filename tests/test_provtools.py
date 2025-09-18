import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import hashlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PY = pathlib.Path(sys.executable)
VENV = os.environ.get("VIRTUAL_ENV")
if VENV:
    candidate = pathlib.Path(VENV) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    PYTHON = candidate if candidate.exists() else DEFAULT_PY
else:
    PYTHON = DEFAULT_PY

HEADER_TEMPLATE = textwrap.dedent(
    """
<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "doc.md"
      digest:
        sha256: "{doc_hash}"
  predicateType: "https://accord.ai/schemas/policy@v1"
  predicate:
    produced_by:
      agent_id: "AGENT-PO01"
    materials:
      - name: "ref.txt"
        digest:
          sha256: "{ref_hash}"
-->
"""
)


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def run_tool(tmp: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(PYTHON), str(ROOT / "scripts/provtools.py"), *args],
        cwd=tmp,
        capture_output=True,
        text=True,
    )


def test_build_and_verify_roundtrip(tmp_path: pathlib.Path):
    ref = tmp_path / "ref.txt"
    ref.write_text("hello", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text("POLICY", encoding="utf-8")

    header = HEADER_TEMPLATE.format(doc_hash=sha256(doc), ref_hash=sha256(ref))
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header + "\n# Body\n", encoding="utf-8")

    proc = run_tool(tmp_path, "keygen", "--out", "keys")
    assert proc.returncode == 0, proc.stderr

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
        "--base",
        str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout.strip())
    assert result["ok"] is True

    proc = run_tool(
        tmp_path,
        "verify",
        str(tmp_path / "att.dsse"),
        "--pub",
        str(tmp_path / "keys/ed25519.pub"),
        "--base",
        str(tmp_path),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["signature_ok"] is True
    assert payload["schema_ok"] is True
    assert payload["digest_ok"] is True
    assert payload["error_code"] == "OK"


def test_digest_mismatch_fails(tmp_path: pathlib.Path):
    ref = tmp_path / "ref.txt"
    ref.write_text("hello", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text("POLICY", encoding="utf-8")

    header = HEADER_TEMPLATE.format(doc_hash="0" * 64, ref_hash="0" * 64)
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header + "\n# Body\n", encoding="utf-8")

    run_tool(tmp_path, "keygen", "--out", "keys")

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
        "--base",
        str(tmp_path),
    )
    assert proc.returncode == 1
    assert "digest mismatch" in proc.stdout
