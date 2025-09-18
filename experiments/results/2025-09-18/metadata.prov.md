<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "experiments/results/2025-09-18/metadata.json"
      digest: {}
  predicateType: "https://accord.ai/schemas/artifact@v1"
  predicate:
    produced_by:
      agent_id: "AGENT-EXPRUNNER"
      agent_role: "Experiment Runner"
    process:
      toolchain:
        - name: "orchestrator"
          version: "0.4.0-dev0"
        - name: "llm"
          provider: "mock"
          model: "mock"
          temperature: "0"
    materials:
      - name: "docs/index.jsonl"
        digest: {}
      - name: "experiments/run.yaml"
        digest: {}
-->
