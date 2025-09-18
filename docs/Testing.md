<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: docs/Testing.md
    digest: {}
  predicateType: https://accord.ai/schemas/testing-playbook@v1
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
    materials:
    - name: tests/test_runtime_guard.py
      digest:
        sha256: f3be3adeb7b53230aa98700735385e1db45c4740865d5d1423f0f6f9bf1b3cbf
      role: unit_test
  signers:
  - id: AGENT-ENG01
    signature_ref: attestations/AGENT-ENG01/testing-playbook.dsse
-->

# Testing Playbook

## Automated
- `pytest` — covers runtime guard, provenance tooling, and policy pipeline.
- Future: add orchestrator smoke tests that stub the LLM call and assert scoped writes.

## Manual
1. **Guard enforcement**: run `python - <<'PY'` scripts to attempt unauthorized writes and expect `ScopeError`.
2. **Orchestrator dry run**: `python -m orchestrator.runtime --json` (requires `keys/` or expects warning).
3. **Experiment harness**: `python -m orchestrator.run_experiment --spec experiments/run.yaml --attest` (attestation optional if keys absent).
4. **Provenance verification**: `python -m scripts.provtools verify --dsse <file> --pub keys/ed25519.pub` once DSSE generated.

## Edge Cases to Simulate
- Concurrent agent launches (increase worker count).
- Symlink injection attempt within `org/` (should raise `ScopeError`).
- DSSE pipeline with missing provenance header (expect failure).
- Experiment output root override outside allowed scope (guard should prevent).

Document pass/fail outcomes under `experiments/results/<run>/` along with DSSE envelopes.

## Smoke Checklist
1. `venv/bin/python -m scripts.provtools keygen --out keys`
2. `ACCORD_LLM_PROVIDER=mock venv/bin/python -m orchestrator.run_experiment --spec experiments/run.yaml --attest`
3. `for dsse in attestations/AGENT-*/*.dsse; do venv/bin/python -m scripts.provtools verify --dsse "$dsse" --pub keys/ed25519.pub; done`
