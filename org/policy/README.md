<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: org/policy/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/policy-index@v1
  predicate:
    produced_by:
      agent_id: AGENT-PM01
      agent_role: Policy Mediator
      coach_id: AGENT-OPS01
    process:
      toolchain:
      - name: manual-prep
        version: '0.1'
      mcp_sessions: []
    governance:
      gedi_ballot_uri: org/policy/gedi-ballots/2025-01-15-bootstrap.json
      decision_rule: condorcet
    quality_checks:
      review_status: pending
      tests: []
    security:
      isolation_level: sandbox
      provenance_level: slsa-lvl1
    materials: []
  signers:
  - id: AGENT-PM01
    signature_ref: attestations/AGENT-PM01/policy-index.dsse
-->

# Policy Library

This folder stores GEDI governance artifacts and derived policy documents.

- `GEDI-governance.md`: Canonical charter for democratic decision making.
- `gedi-ballots/`: Machine-readable ballot ledgers (`*.json`) with embedded provenance headers.
- `gedi-minutes/`: (Optional) Meeting notes created when amendments or retrospectives occur.
- `backlog.md`: Tracking of pending policy work (create as needed).

Agents must use `scripts.policy_synth_pipeline.run_pipeline` to attach DSSE attestations for every Markdown or JSON artifact produced here. CI enforces verification before merge.
