import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _prepare_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        repo_root,
        ignore=shutil.ignore_patterns(".git", "venv", "__pycache__", "*.pyc", "*.pyo"),
    )
    return repo_root


def _ensure_keys(repo_root: Path) -> None:
    priv = repo_root / "keys/ed25519.key"
    pub = repo_root / "keys/ed25519.pub"
    if priv.exists() and pub.exists():
        return
    subprocess.run(
        [sys.executable, "-m", "scripts.provtools", "keygen", "--out", "keys"],
        cwd=repo_root,
        check=True,
    )


def _run_experiment(repo_root: Path, spec_path: Path):
    env = os.environ.copy()
    env.setdefault("ACCORD_LLM_PROVIDER", "mock")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator.run_experiment",
            "--spec",
            str(spec_path),
            "--attest",
        ],
        cwd=repo_root,
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


def _create_temp_spec(repo_root: Path) -> Path:
    base_spec = yaml.safe_load((repo_root / "experiments/run.yaml").read_text(encoding="utf-8"))
    run_root = "experiments/results/test-sidecar"
    Path(repo_root / run_root).mkdir(parents=True, exist_ok=True)
    base_spec.setdefault("outputs", {})["root"] = run_root
    spec_path = repo_root / "experiments/run-sidecar-test.yaml"
    spec_path.write_text(yaml.safe_dump(base_spec, sort_keys=False), encoding="utf-8")
    return spec_path


def test_metadata_sidecar_and_dsse_end_to_end(tmp_path):
    repo_root = _prepare_repo(tmp_path)
    _ensure_keys(repo_root)
    spec = _create_temp_spec(repo_root)
    rc, stdout, stderr = _run_experiment(repo_root, spec)
    assert rc == 0, f"run_experiment failed:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"

    metadata_path = _extract_metadata_path(stdout)
    sidecar = metadata_path.with_suffix(".prov.md")
    dsse = metadata_path.with_suffix(".json.dsse")

    assert sidecar.exists(), f"missing sidecar: {sidecar}"
    assert dsse.exists(), f"missing dsse: {dsse}"

    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.provtools",
            "verify",
            str(dsse),
            "--pub",
            "keys/ed25519.pub",
            "--base",
            ".",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )
    assert verify.returncode == 0, f"verify failed:\nSTDOUT:\n{verify.stdout}\nSTDERR:\n{verify.stderr}"
