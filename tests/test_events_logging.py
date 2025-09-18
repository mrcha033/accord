import json
import shutil
from pathlib import Path

from orchestrator.runtime import run_all
from scripts import provtools


def _copy_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    shutil.copytree(Path(__file__).resolve().parents[1], repo_root)
    return repo_root


def _ensure_keys(repo_root: Path) -> None:
    priv = repo_root / "keys/ed25519.key"
    pub = repo_root / "keys/ed25519.pub"
    if priv.exists():
        return
    provtools.keygen_ed25519(priv, pub)


def test_events_logging(tmp_path: Path) -> None:
    repo_root = _copy_repo(tmp_path)
    _ensure_keys(repo_root)

    events_path = repo_root / "experiments/results/test/events.jsonl"
    results = run_all(base_dir=repo_root, events_path=events_path)
    assert results

    data = events_path.read_text(encoding="utf-8").splitlines()
    assert len(data) >= len(results)
    event = json.loads(data[0])
    for field in ["t", "agent", "act", "targets", "dsse_ref"]:
        assert field in event
