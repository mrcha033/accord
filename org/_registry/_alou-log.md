<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: org/_registry/_alou-log.md
    digest: {}
  predicateType: https://accord.ai/schemas/registry-log@v1
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
    signature_ref: attestations/AGENT-PM01/bootstrap.dsse
-->

# ALOU Revision Log

| Date       | Agent        | Change Summary                          | DSSE Envelope                                |
|------------|--------------|-----------------------------------------|-----------------------------------------------|
| 2025-01-15 | AGENT-OPS01  | Initial charter for Operations Steward  | `attestations/AGENT-OPS01/bootstrap.dsse`     |
| 2025-01-15 | AGENT-PM01   | Initial charter for Policy Mediator     | `attestations/AGENT-PM01/bootstrap.dsse`      |
| 2025-01-15 | AGENT-ENG01  | Initial charter for Engineering Synth   | `attestations/AGENT-ENG01/bootstrap.dsse`     |
