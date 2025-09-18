import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ensure_keys():
    priv = ROOT / "keys/ed25519.key"
    pub = ROOT / "keys/ed25519.pub"
    if not priv.exists() or not pub.exists():
        subprocess.run(
            [sys.executable, "-m", "scripts.provtools", "keygen", "--out", "keys"],
            cwd=ROOT,
            check=True,
        )
    return priv, pub


def _run_experiment():
    env = os.environ.copy()
    env.setdefault("ACCORD_LLM_PROVIDER", "mock")
    proc = subprocess.run(
        [sys.executable, "-m", "orchestrator.run_experiment", "--spec", "experiments/run.yaml", "--attest"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _extract_metadata_path(stdout: str) -> Path:
    text = stdout.strip()
    last_brace = text.rfind("{")
    if last_brace == -1:
        raise AssertionError(f"metadata path not found in output:\n{stdout}")

    candidate = text[last_brace:]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:  # pragma: no cover - fallback for formatting changes
        raise AssertionError(f"failed to parse metadata JSON from output:\n{stdout}") from exc

    if "metadata" not in payload:
        raise AssertionError(f"metadata key missing in output payload:\n{payload}")
    return Path(payload["metadata"])


def test_metadata_sidecar_and_dsse_end_to_end(tmp_path):
    _ensure_keys()
    rc, stdout, stderr = _run_experiment()
    assert rc == 0, f"run_experiment failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    metadata_path = _extract_metadata_path(stdout)
    sidecar = metadata_path.with_suffix(".prov.md")
    dsse = metadata_path.with_suffix(".json.dsse")

    assert sidecar.exists(), f"missing sidecar: {sidecar}"
    assert dsse.exists(), f"missing dsse: {dsse}"

    verify = subprocess.run(
        [sys.executable, "-m", "scripts.provtools", "verify", str(dsse), "--pub", "keys/ed25519.pub", "--base", "."],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert verify.returncode == 0, f"verify failed:\nSTDOUT:\n{verify.stdout}\nSTDERR:\n{verify.stderr}"
