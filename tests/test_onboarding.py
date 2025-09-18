import textwrap
from pathlib import Path

import pytest

from orchestrator.onboarding import AgentOnboardingError, materialize_agent
from orchestrator.runtime import load_registered_agent_configs


def _candidate_alou(prompt_template: str | None = "# Prompt body\n") -> str:
    runtime_lines = [
        "runtime:",
        "  prompt_path: \"agents/AGENT-RISK01/prompt.md\"",
        "  output_path: \"org/risk/reports/daily.md\"",
        "  summary_path: \"bus/daily/risk.md\"",
        "  context_roots: [\"org/risk\",\"bus/risk\"]",
    ]
    if prompt_template is not None:
        runtime_lines.append("  prompt_template: |-")
        runtime_lines.extend(textwrap.indent(prompt_template.rstrip("\n") + "\n", "    ").splitlines())
    runtime_block = "\n".join(runtime_lines) + "\n"

    return textwrap.dedent(
        f"""\
---
agent_id: AGENT-RISK01
role_title: "Risk Analyst"
version: "1.1"
idempotency_key: "018fea9a-c5ba-7117-8a21-6b8f3600risk"
cluster_path:
  chapter: "Risk"
  squad: "RiskOps"
  guilds: ["Compliance"]
revision: "2025-09-01"
coach_agent: AGENT-OPS01
status: active
effective_from: "2025-09-01"
expires: "NONE"
capabilities: ["risk_review"]
mcp_allow: ["file","search"]
fs_write_scopes: ["org/risk/**","bus/risk/**"]
{runtime_block}
data_classification: internal
gedi:
  roles: ["observer"]
  vote_weight: 0.5
  quorum: 0.3
provenance:
  attestation_path: "attestations/AGENT-RISK01/latest.dsse"
  hash_algo: "sha256"
  key_id: "k-risk01"
security:
  threat_model: "prompt injection"
  forbidden_ops: ["net.outbound"]
rotation_policy: "coach:6mo, key:90d"
---

Body content is ignored for onboarding tests.
"""
    )


def test_materialize_agent_creates_assets(tmp_path: Path) -> None:
    base = tmp_path
    candidate_path = base / "org/policy/proposals/AGENT-RISK01.alou.md"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(_candidate_alou(), encoding="utf-8")

    result = materialize_agent(base, candidate_path)

    assert result.agent_id == "AGENT-RISK01"
    assert result.prompt_created is True
    assert result.output_created is True
    assert result.summary_created is True
    assert result.context_roots == (Path("org/risk"), Path("bus/risk"))

    prompt_text = (base / result.prompt_path).read_text(encoding="utf-8")
    assert "# Prompt body" in prompt_text

    output_text = (base / result.output_path).read_text(encoding="utf-8")
    assert "Auto-generated placeholder" in output_text

    registry_doc = (base / result.alou_path).read_text(encoding="utf-8")
    original_doc = candidate_path.read_text(encoding="utf-8")
    assert registry_doc == original_doc

    registry = load_registered_agent_configs(base)
    assert "AGENT-RISK01" in registry
    cfg = registry["AGENT-RISK01"]
    assert cfg.prompt_path == result.prompt_path
    assert cfg.output_path == result.output_path
    assert cfg.summary_path == result.summary_path


def test_materialize_agent_requires_prompt_template_when_missing_file(tmp_path: Path) -> None:
    base = tmp_path
    candidate_path = base / "org/policy/proposals/AGENT-RISK01.alou.md"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(_candidate_alou(prompt_template=None), encoding="utf-8")

    with pytest.raises(AgentOnboardingError):
        materialize_agent(base, candidate_path)

    prompt_path = base / "agents/AGENT-RISK01/prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Existing prompt\n", encoding="utf-8")

    result = materialize_agent(base, candidate_path)
    assert result.prompt_created is False
