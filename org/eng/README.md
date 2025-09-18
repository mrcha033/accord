<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: org/eng/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/eng-notebook@v1
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
    signature_ref: attestations/AGENT-ENG01/eng-readme.dsse
-->

# Engineering Notes

Store design memos, architecture decision records, and runtime diagnostics here. Each document should link back to relevant experiments and MCP adapters. Subdirectories to create as work progresses:

- `adr/` for decision records
- `orchestrator-notes/` for runtime changes
- `metrics/` for exported charts or CSVs
