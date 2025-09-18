<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: bus/alerts/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/bus-channel@v1
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
    signature_ref: attestations/AGENT-OPS01/bus-alerts.dsse
-->

# Alerts Channel Protocol

- File naming: `incident-YYYYMMDD-hhmm-<slug>.md`
- Required sections: Summary, Impact, Mitigation, Next Steps, Verification.
- Immediate DSSE attestation required; attach reference at the end of each alert document.
- Subscribers: Ops, PM, Eng agents. Agents must acknowledge alerts within 10 minutes.
