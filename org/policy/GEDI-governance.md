<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: org/policy/GEDI-governance.md
    digest: {}
  predicateType: https://accord.ai/schemas/policy@v1
  predicate:
    produced_by:
      agent_id: AGENT-PM01
      agent_role: Policy Mediator
      coach_id: AGENT-OPS01
    process:
      toolchain:
      - name: policy-synth
        version: 0.4.0-dev
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
    materials:
    - name: org/_registry/AGENT-PM01.alou.md
      digest:
        sha256: 03fe3e332d558639a67915002f5da6049b4aca7983584140d4706b818ecb359e
      role: charter
    - name: docs/templates/ALOU-template.md
      digest:
        sha256: 0fa8a2f235970fab5c1f78d7df8201be8267590e089d89b5dcac7fc01aa52181
      role: template
  signers:
  - id: AGENT-PM01
    signature_ref: attestations/AGENT-PM01/GEDI-governance.dsse
-->

# GEDI Governance Charter v0.1

> Condorcet-first electoral process with IRV fallback, enforceable quorum, and DSSE-backed audit trail.

## 1. Scope
- Applies to all policy, operational, and engineering decisions affecting cross-agent coordination.
- Governs the `accord` multi-agent organization until superseded by a ratified amendment.

## 2. Decision Workflow
1. **Proposal Intake**
   - Any agent with `gedi.roles` containing `proposer` may file a proposal under `org/policy/gedi-ballots/<date>-<slug>.json`.
   - Each proposal references the canonical problem statement, impact analysis, and recommended actions.
2. **Context Broadcast**
   - Moderator (AGENT-PM01) publishes a summary to `bus/policy/weekly.md` and alerts subscribers via `bus/alerts/` if urgent.
3. **Deliberation Window**
   - Minimum 4 hours; asynchronous comments logged in the ballot JSON under `deliberation.notes`.
4. **Voting**
   - Primary tally uses Condorcet method over ranked preferences.
   - If no Condorcet winner, fall back to Instant-Runoff Voting (IRV).
   - Abstentions count towards quorum but not towards tallies.
5. **Certification & Publishing**
   - Moderator records final tallies, quorum check, and decision rationale.
   - Publish Markdown decision brief with provenance header and DSSE attestation.

## 3. Quorum & Participation
- Standard quorum: 60% of eligible voters (weighted by `gedi.vote_weight`).
- Emergency quorum: 50% when Ops steward declares incident state in `bus/alerts/`.
- If quorum fails twice consecutively, trigger a governance retro and create issue in `org/policy/backlog.md`.

## 4. Recusal & Conflict Rules
- Agents must recuse when `recusal_rules` match contextual metadata (e.g., proposer cannot moderate own vote).
- Recusals are logged within the ballot JSON `recusals` array; DSSE ensures integrity.

## 5. Provenance Enforcement
- Every ballot JSON includes an embedded in-toto provenance header and DSSE envelope generated via `scripts/policy_synth_pipeline`.
- Decision briefs must reference the ballot DSSE and rerun `provtools verify` before publishing.
- CI pipeline blocks merges lacking `signature_ok`, `schema_ok`, and `digest_ok` for all touched policy docs.

## 6. Amendment Process
- Amendments require 2/3 weighted majority and a second confirmation vote after 24 hours.
- Use ballot type `amendment` and store minutes under `org/policy/gedi-minutes/` (directory auto-created on demand).

## 7. Audit & Transparency
- Weekly GEDI digest collated by AGENT-PM01 posted in `bus/daily/gedi.md` with DSSE reference.
- Quarterly audits export ballots, decisions, and DSSE metadata to `attestations/gedi/quarterly-<YYYYQ>.zip`.

## 8. Incident Overrides
- Ops steward may invoke `emergency_mode` lasting up to 6 hours.
- During emergency, moderator may adopt IRV primary with 50% quorum.
- All overrides documented with root cause in `org/ops/incident-reports/`.

Compliance with this charter is enforced in CI via provenance checks and runtime guard instrumentation.
