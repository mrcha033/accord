import json
import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PY = pathlib.Path(sys.executable)
VENV = os.environ.get("VIRTUAL_ENV")
if VENV:
    candidate = pathlib.Path(VENV) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    PYTHON = candidate if candidate.exists() else DEFAULT_PY
else:
    PYTHON = DEFAULT_PY

VALID = textwrap.dedent(
    """\
---
agent_id: AGENT-PO01
role_title: "Policy Orchestrator"
version: "1.1"
idempotency_key: "018fea7a-8f4a-7e1e-b1a1-0c0ffee0c0de"
cluster_path:
  chapter: "Governance"
  squad: "Foundational Constitution"
  guilds: ["Risk & Compliance"]
revision: "2025-09-17"
coach_agent: AGENT-COACH01
status: active
effective_from: "2025-09-17"
expires: "2026-09-17"
capabilities: ["policy_draft","vote_routing"]
mcp_allow: ["file","git","search"]
fs_write_scopes: ["org/policy/**","bus/gedi/**"]
data_classification: internal
gedi:
  roles: ["proposer","voter"]
  vote_weight: 1.0
  quorum: 0.6
  recusal_rules: ["if_proposer==reviewer"]
provenance:
  attestation_path: "attestations/policy-orchestrator/latest.dsse"
  hash_algo: "sha256"
  key_id: "k-001"
security:
  threat_model: "prompt-injection / privilege escalation"
  forbidden_ops: ["net.outbound"]
rotation_policy: "coach:6mo, key:90d"
---
body omitted
"""
)

INVALID = VALID.replace('version: "1.1"', 'version: "2.0"').replace(
    'mcp_allow: ["file","git","search"]',
    'mcp_allow: ["foo","git"]',
)





def run_validate(md: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "example.alou.md"
        path.write_text(md, encoding="utf-8")
        proc = subprocess.run(
            [str(PYTHON), str(ROOT / "scripts/validate_alou.py"), str(path)],
            capture_output=True,
            text=True,
        )
        return proc.returncode, (proc.stdout + proc.stderr)


def test_valid_passes():
    code, output = run_validate(VALID)
    assert code == 0, output
    payload = json.loads(output.strip())
    assert payload["ok"] is True
    assert payload["agent_id"] == "AGENT-PO01"


def test_invalid_fails():
    code, output = run_validate(INVALID)
    assert code == 1, output
    payload = json.loads(output.strip())
    assert payload["ok"] is False
    assert any("version" in err or "mcp_allow" in err for err in payload["errors"])
