from pathlib import Path

from orchestrator.experiment_loop import AutoBallotConfig, ExperimentLoop, ExperimentState


def _write_alou(path: Path, agent_id: str, extra_scopes: str = "") -> None:
    scopes = "bus/daily/risk.md" if not extra_scopes else extra_scopes
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            f"---\n"
            f"agent_id: {agent_id}\n"
            "role_title: \"Role\"\n"
            "version: \"1.1\"\n"
            "revision: \"2025-01-01\"\n"
            "status: active\n"
            "effective_from: \"2025-01-01\"\n"
            "capabilities: [\"test\"]\n"
            "mcp_allow: [\"file\"]\n"
            "fs_write_scopes: [\"org/test/**\",\"bus/test/**\",\"bus/daily/risk.md\"]\n"
            "runtime:\n"
            f"  prompt_path: \"agents/{agent_id}/prompt.md\"\n"
            f"  output_path: \"org/test/{agent_id}.md\"\n"
            "  summary_path: \"bus/daily/risk.md\"\n"
            "gedi:\n"
            "  roles: [\"voter\"]\n"
            "  vote_weight: 1.0\n"
            "  quorum: 0.5\n"
            "provenance:\n"
            f"  attestation_path: \"attestations/{agent_id}/latest.dsse\"\n"
            "  hash_algo: \"sha256\"\n"
            f"  key_id: \"k-{agent_id.lower()}\"\n"
            "security:\n"
            "  threat_model: \"test\"\n"
            "  forbidden_ops: [\"net.outbound\"]\n"
            "rotation_policy: \"coach:6mo, key:90d\"\n"
            "---\n"
        ),
        encoding="utf-8",
    )


def test_auto_ballot_discovers_proposals(tmp_path: Path) -> None:
    proposals = tmp_path / "org/policy/proposals"
    _write_alou(proposals / "AGENT-NEW01.alou.md", "AGENT-NEW01")

    loop = ExperimentLoop.__new__(ExperimentLoop)
    loop.base_dir = tmp_path
    loop.auto_ballot = AutoBallotConfig(
        enabled=True,
        cadence_rounds=1,
        electorate=[],
        options={"NONE": "retain-current-roster"},
        proposal_materials=[],
        vote_rankings={},
        discover_proposals=True,
    )
    loop.state = ExperimentState()
    loop.state.roster = []

    options = loop._compose_auto_ballot_options()
    assert any(key.startswith("ADD-AGENT-NEW01") for key in options.keys())
    payload = next(value for key, value in options.items() if key.startswith("ADD-AGENT-NEW01"))
    assert payload["artifact"].endswith("AGENT-NEW01.alou.md")


def test_auto_ballot_dynamic_electorate(tmp_path: Path) -> None:
    registry = tmp_path / "org/_registry"
    _write_alou(registry / "AGENT-NEW01.alou.md", "AGENT-NEW01")

    loop = ExperimentLoop.__new__(ExperimentLoop)
    loop.base_dir = tmp_path
    loop.auto_ballot = AutoBallotConfig(
        enabled=True,
        cadence_rounds=1,
        electorate=["AGENT-OPS01"],
        options={"NONE": "retain-current-roster"},
        proposal_materials=[],
        vote_rankings={},
        discover_proposals=False,
    )
    loop.state = ExperimentState()
    loop.state.roster = ["AGENT-NEW01"]

    electorate = loop._compose_auto_ballot_electorate()
    assert "AGENT-OPS01" in electorate
    assert "AGENT-NEW01" in electorate
