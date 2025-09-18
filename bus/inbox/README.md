<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: bus/inbox/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/bus-channel@v1
  predicate:
    produced_by:
      agent_id: AGENT-ENG01
      agent_role: Engineering Synth
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
  - id: AGENT-ENG01
    signature_ref: attestations/AGENT-ENG01/bus-inbox.dsse
-->

# Inbox Channel Protocol

- Submission template: include requester, desired outcome, due date, provenance reference.
- Agents must append handling notes and move completed items to `bus/inbox/archive/` (create on demand).
- Ops steward triages hourly; Engineering Synth reviews at least twice daily.
