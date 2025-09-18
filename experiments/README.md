<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: experiments/README.md
    digest: {}
  predicateType: https://accord.ai/schemas/experiment-index@v1
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
    signature_ref: attestations/AGENT-ENG01/experiments-readme.dsse
-->

# Experiment Harness

- `run.yaml`: Declarative specification for orchestrated experiments.
- `results/`: DSSE-backed artifacts emitted by `orchestrator/run_experiment.py` (per run timestamp).
- `metrics/`: (Planned) Aggregated accuracy, cost, latency, provenance completeness tables.

Execute an experiment via:

```bash
python -m orchestrator.run_experiment --spec experiments/run.yaml --attest
```

The runner enforces filesystem scope through the Engineering Synth ALOU.
