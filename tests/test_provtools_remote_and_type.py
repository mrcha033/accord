import base64
import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import textwrap
import hashlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import provtools


def _env_with_path() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [env.get("PYTHONPATH"), str(ROOT)])
    )
    return env


def run_tool(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "scripts.provtools", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env_with_path(),
    )


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_bundle(tmp_path: pathlib.Path, extra_predicate: str) -> pathlib.Path:
    doc = tmp_path / "doc.md"
    doc.write_text("DOC", encoding="utf-8")
    header = textwrap.dedent(
        f"""<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "doc.md"
      digest:
        sha256: "{sha256(doc)}"
  predicateType: "https://example.org/schemas/policy@v1"
  predicate:
{textwrap.indent(extra_predicate.strip(), '    ')}
-->
"""
    )
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header + "\n# body\n", encoding="utf-8")
    return bundle


def ensure_keys(tmp_path: pathlib.Path) -> None:
    proc = run_tool(tmp_path, "keygen", "--out", "keys")
    assert proc.returncode == 0, proc.stderr


def test_remote_material_requires_digest(tmp_path: pathlib.Path) -> None:
    extra = textwrap.dedent(
        """
materials:
  - name: "https://example.org/spec"
    digest:
      sha256: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
"""
    ).strip()
    bundle = build_bundle(tmp_path, extra)
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_remote_material_missing_digest_fails(tmp_path: pathlib.Path) -> None:
    extra = textwrap.dedent(
        """
materials:
  - name: "https://example.org/spec"
"""
    ).strip()
    bundle = build_bundle(tmp_path, extra)
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 1
    assert "remote material requires digest" in proc.stdout


def test_verify_rejects_unexpected_payload_type(tmp_path: pathlib.Path) -> None:
    extra = "predicate_field: 1"
    bundle = build_bundle(tmp_path, extra)
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    attestation = tmp_path / "att.dsse"
    envelope = json.loads(attestation.read_text(encoding="utf-8"))
    envelope["payloadType"] = "text/plain"
    attestation.write_text(json.dumps(envelope), encoding="utf-8")

    proc = run_tool(
        tmp_path,
        "verify",
        str(attestation),
        "--pub",
        str(tmp_path / "keys/ed25519.pub"),
    )
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["signature_ok"] is False
    assert any("unsupported payloadType" in err for err in payload["errors"])


def test_subject_path_escape(tmp_path: pathlib.Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("DOC", encoding="utf-8")
    header = textwrap.dedent(
        """<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "../outside"
      digest:
        sha256: "{digest}"
  predicateType: "https://example.org/schemas/policy@v1"
  predicate: {{}}
-->
"""
    ).format(digest=sha256(doc))
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header, encoding="utf-8")
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 1
    assert "path escapes base_dir" in proc.stdout


def test_multiple_comments_selects_provenance(tmp_path: pathlib.Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text("DOC", encoding="utf-8")
    banner = "<!-- banner -->\n"
    provenance = textwrap.dedent(
        f"""\
        <!--
        provenance:
          _type: "https://in-toto.io/Statement/v0.1"
          subject:
            - name: "doc.md"
              digest:
                sha256: "{sha256(doc)}"
          predicateType: "https://example.org/schemas/policy@v1"
          predicate: {{}}
        -->
        """
    )
    footer = "<!-- footer -->\n"
    bundle = tmp_path / "bundle.md"
    bundle.write_text(banner + provenance + footer, encoding="utf-8")
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_subject_absolute_path_rejected(tmp_path: pathlib.Path) -> None:
    zeros = "0" * 64
    header = textwrap.dedent(
        f"""<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "/etc/passwd"
      digest:
        sha256: "{zeros}"
  predicateType: "https://example.org/schemas/policy@v1"
  predicate: {{}}
-->
"""
    )
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header, encoding="utf-8")
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 1
    assert "absolute or home path not allowed" in proc.stdout


def test_subject_symlink_rejected(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "doc.md"
    target.write_text("DOC", encoding="utf-8")
    link = tmp_path / "alias.md"
    link.symlink_to(target)
    header = textwrap.dedent(
        f"""<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "alias.md"
      digest:
        sha256: "{sha256(target)}"
  predicateType: "https://example.org/schemas/policy@v1"
  predicate: {{}}
-->
"""
    )
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header, encoding="utf-8")
    ensure_keys(tmp_path)

    proc = run_tool(
        tmp_path,
        "build",
        str(bundle),
        "--priv",
        str(tmp_path / "keys/ed25519.key"),
        "--out",
        str(tmp_path / "att.dsse"),
    )
    assert proc.returncode == 1
    assert "symlink not allowed" in proc.stdout


def test_subject_material_order_canonical(tmp_path: pathlib.Path) -> None:
    ensure_keys(tmp_path)
    priv = tmp_path / "keys/ed25519.key"
    statement = {
        "_type": "https://in-toto.io/Statement/v0.1",
        "predicateType": "https://example.org/schemas/policy@v1",
        "subject": [
            {"name": "b.txt", "digest": {"sha256": "0" * 64}},
            {"name": "a.txt", "digest": {"sha256": "0" * 64}},
        ],
        "predicate": {
            "materials": [
                {"name": "y.txt", "digest": {"sha256": "0" * 64}},
                {"name": "x.txt", "digest": {"sha256": "0" * 64}},
            ]
        },
    }
    envelope = provtools.dsse_sign(statement, priv)
    payload = json.loads(base64.b64decode(envelope["payload"]))
    subjects = [item["name"] for item in payload["subject"]]
    materials = [item["name"] for item in payload["predicate"]["materials"]]
    assert subjects == sorted(subjects)
    assert materials == sorted(materials)


def test_concurrent_build_same_output(tmp_path: pathlib.Path) -> None:
    extra = textwrap.dedent(
        """
materials: []
"""
    ).strip()
    bundle = build_bundle(tmp_path, extra)
    ensure_keys(tmp_path)

    def _build() -> subprocess.CompletedProcess:
        return run_tool(
            tmp_path,
            "build",
            str(bundle),
            "--priv",
            str(tmp_path / "keys/ed25519.key"),
            "--out",
            str(tmp_path / "att.dsse"),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_build) for _ in range(6)]
        results = [future.result() for future in futures]

    assert all(proc.returncode == 0 for proc in results)

    verify = run_tool(
        tmp_path,
        "verify",
        str(tmp_path / "att.dsse"),
        "--pub",
        str(tmp_path / "keys/ed25519.pub"),
        "--base",
        str(tmp_path),
    )
    assert verify.returncode == 0
