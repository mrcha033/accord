<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: org/_registry/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/org-registry@v1
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

# Org Registry

This directory stores the canonical Agent Letters of Understanding (ALOU) and associated revision log for the `accord` multi-agent organization.

* `_alou-log.md`: Append-only ledger listing revisions and DSSE envelopes.
* `AGENT-*.alou.md`: Current charter for each agent role, consumed by `scripts.runtime_guard.RuntimeGuard`.
* Validation: run `python -m scripts.validate_alou org/_registry/*.alou.md` before committing updates.

All Markdown files must include an in-toto provenance header and corresponding DSSE attestation under `attestations/<agent>/` as enforced by CI.
