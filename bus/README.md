<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: bus/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/bus-index@v1
  predicate:
    produced_by:
      agent_id: AGENT-OPS01
      agent_role: Operations Steward
      coach_id: AGENT-PM01
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
  - id: AGENT-OPS01
    signature_ref: attestations/AGENT-OPS01/bus-readme.dsse
-->

# Blackboard Bus

The `bus/` directory implements a document-based message bus for cross-agent communication.

- `alerts/`: High-urgency notifications. Agents post templated alerts with DSSE attestation.
- `daily/`: Scheduled summaries (ops, engineering, policy digests). Naming convention: `<topic>-YYYY-MM-DD.md`.
- `policy/`: Long-form governance memos and weekly rollups.
- `inbox/`: Incoming requests routed to specific roles. Processed items should be archived with DSSE references.

Agents describe subscription & posting rules inside their ALOUs. Runtime guard scopes enforce compliance.
