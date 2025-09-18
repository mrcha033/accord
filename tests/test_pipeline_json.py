import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _env_with_path() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [env.get("PYTHONPATH"), str(ROOT)]))
    return env


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def write_bundle(tmp_path: Path) -> Path:
    artifact = tmp_path / "policy.md"
    artifact.write_text("POLICY", encoding="utf-8")
    header = textwrap.dedent(
        f"""<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "policy.md"
      digest:
        sha256: "{sha256(artifact)}"
  predicateType: "https://example.org/schemas/policy@v1"
  predicate: {{}}
-->
"""
    )
    bundle = tmp_path / "bundle.md"
    bundle.write_text(header + "\n# body\n", encoding="utf-8")
    return bundle


def ensure_keys(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.provtools", "keygen", "--out", "keys"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env=_env_with_path(),
    )
    assert proc.returncode == 0


def read_last_json(stdout: str) -> dict:
    lines = [line for line in stdout.strip().splitlines() if line]
    assert lines, "expected JSON output"
    return json.loads(lines[-1])


def test_pipeline_cli_success(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    ensure_keys(tmp_path)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.policy_synth_pipeline",
            str(bundle),
            "keys/ed25519.key",
            "att.dsse",
            "--base-dir",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_env_with_path(),
    )
    assert proc.returncode == 0, proc.stderr
    payload = read_last_json(proc.stdout)
    assert payload["ok"] is True
    assert payload["attestation"] == "att.dsse"
    assert payload["verify"]["signature_ok"] is True
    assert payload["verify"]["schema_ok"] is True
    assert payload["verify"]["digest_ok"] is True
    assert payload["verify_exit_code"] == 0


def test_pipeline_cli_failure_json(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.policy_synth_pipeline",
            str(bundle),
            "keys/ed25519.key",
            "att.dsse",
            "--synth-cmd",
            sys.executable,
            "-c",
            "import sys; sys.exit(1)",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_env_with_path(),
    )
    assert proc.returncode == 1
    payload = read_last_json(proc.stdout)
    assert payload["ok"] is False
    assert "error" in payload
