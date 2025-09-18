<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: org/ops/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/ops-log@v1
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
    signature_ref: attestations/AGENT-OPS01/ops-readme.dsse
-->

# Operations Ledger

Use this directory for runbooks, incident logs, and operational retrospectives. All Markdown entries must include provenance headers and DSSE envelopes. Organize incident reports under `incident-reports/` (create directory as needed) with filenames `YYYY-MM-DD-incident-<slug>.md`.
