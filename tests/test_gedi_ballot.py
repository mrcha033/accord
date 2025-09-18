import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _copy_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    ignore = shutil.ignore_patterns(
        ".git",
        "venv",
        "__pycache__",
        "*.pyc",
        "*.pyo",
    )
    shutil.copytree(ROOT, repo_root, ignore=ignore)
    return repo_root


def _run(cmd: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"command failed: {cmd}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _ensure_keys(repo_root: Path) -> None:
    key_path = repo_root / "keys/ed25519.key"
    if key_path.exists():
        return
    _run([sys.executable, "-m", "scripts.provtools", "keygen", "--out", "keys"], cwd=repo_root)


def test_ballot_cycle_condorcet(tmp_path: Path) -> None:
    repo_root = _copy_repo(tmp_path)
    tmp_dir = repo_root / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    env = {**os.environ, "ACCORD_LLM_PROVIDER": "mock", "TMPDIR": str(tmp_dir)}
    _ensure_keys(repo_root)

    draft_root = repo_root / "org/policy/norms/draft"
    draft_root.mkdir(parents=True, exist_ok=True)
    (draft_root / "journal-protocol.md").write_text("# Draft A\n", encoding="utf-8")
    (draft_root / "journal-protocol-alt.md").write_text("# Draft B\n", encoding="utf-8")

    ballot_path = repo_root / "org/policy/_ballots/GEDI-2025-09-20.yaml"
    ballot_path.parent.mkdir(parents=True, exist_ok=True)
    ballot_path.write_text(
        "id: \"GEDI-2025-09-20\"\n"
        "title: \"Journal Protocol v1\"\n"
        "rule: \"condorcet\"\n"
        "quorum: 0.6\n"
        "electorate:\n"
        "  - \"AGENT-OPS01\"\n"
        "  - \"AGENT-PM01\"\n"
        "  - \"AGENT-ENG01\"\n"
        "options:\n"
        "  A: \"org/policy/norms/draft/journal-protocol.md\"\n"
        "  B: \"org/policy/norms/draft/journal-protocol-alt.md\"\n",
        encoding="utf-8",
    )

    _run(
        [sys.executable, "-m", "scripts.gedi_ballot", "propose", str(ballot_path)],
        cwd=repo_root,
        env=env,
    )
    _run(
        [
            sys.executable,
            "-m",
            "scripts.gedi_ballot",
            "vote",
            "GEDI-2025-09-20",
            "--agent",
            "AGENT-OPS01",
            "--ranking",
            "A>B",
        ],
        cwd=repo_root,
        env=env,
    )
    _run(
        [
            sys.executable,
            "-m",
            "scripts.gedi_ballot",
            "vote",
            "GEDI-2025-09-20",
            "--agent",
            "AGENT-PM01",
            "--ranking",
            "A>B",
        ],
        cwd=repo_root,
        env=env,
    )
    _run(
        [
            sys.executable,
            "-m",
            "scripts.gedi_ballot",
            "vote",
            "GEDI-2025-09-20",
            "--agent",
            "AGENT-ENG01",
            "--ranking",
            "B>A",
        ],
        cwd=repo_root,
        env=env,
    )
    _run(
        [sys.executable, "-m", "scripts.gedi_ballot", "tally", "GEDI-2025-09-20"],
        cwd=repo_root,
        env=env,
    )

    tally_data = json.loads((repo_root / "logs/gedi/GEDI-2025-09-20-tally.json").read_text(encoding="utf-8"))
    assert tally_data["winner"] in {"A", "B"}

    _run(
        [sys.executable, "-m", "scripts.gedi_ballot", "adopt", "GEDI-2025-09-20"],
        cwd=repo_root,
        env=env,
    )

    dsse_paths = [
        repo_root / "attestations/gedi/GEDI-2025-09-20-announce.dsse",
        repo_root / "attestations/gedi/GEDI-2025-09-20-result.dsse",
        repo_root / "attestations/gedi/GEDI-2025-09-20-adopted.dsse",
        repo_root / "attestations/gedi/GEDI-2025-09-20-adopted-summary.dsse",
    ]
    for dsse in dsse_paths:
        _run(
            [
                sys.executable,
                "-m",
                "scripts.provtools",
                "verify",
                str(dsse.relative_to(repo_root)),
                "--pub",
                "keys/ed25519.pub",
                "--base",
                ".",
            ],
            cwd=repo_root,
            env=env,
        )
