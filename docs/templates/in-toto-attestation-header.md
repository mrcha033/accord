# In-toto Style Metadata Header

How to use: embed this HTML comment block at the top of a document, code file, or summary so that both humans and parsers can read it. Pair it with a DSSE signature file (`.dsse`) to verify hashes.

---

## Header Structure
- **_type**: in-toto Statement version (URL), e.g. `https://in-toto.io/Statement/v0.1`.
- **subject**: Array of artifacts. Each entry includes `name` (path/ID) and `digest` (sha256, etc.).
- **predicateType**: URI describing the process type (policy, summary, code, etc.).
- **predicate**: Execution metadata. Include tooling, runtime, GEDI decisions, validation status, and `materials`.
- **signers**: Participants and signature references. Final signatures live in the DSSE envelope.

> **Differences from legacy format**
> - `statement_type` → `_type`, `predicate_type` → `predicateType`, `subject[].uri` → `subject[].name`
> - `materials` move from the top level to `predicate.materials`
> - DSSE `payloadType` must be `application/vnd.in-toto+json` for compatibility

---

## Markdown Header Template

```markdown
<!--
provenance:
  _type: https://in-toto.io/Statement/v0.1
  subject:
  - name: <relative path or document id>
    digest: {}
  predicateType: https://accord.ai/schemas/policy@v1
  predicate:
    produced_by:
      agent_id: AGENT-<ID>
      agent_role: <role title>
      coach_id: AGENT-<ID | NONE>
    process:
      toolchain:
      - name: <tool or script>
        version: <version>
      mcp_sessions:
      - server: <mcp endpoint>
        session_id: <UUID>
    governance:
      gedi_ballot_uri: <ballot log path | NONE>
      decision_rule: <e.g. condorcet>
    quality_checks:
      review_status: <pending|approved>
      tests:
      - name: <test name>
        result: <pass|fail|n/a>
    security:
      isolation_level: <sandbox|trusted>
      provenance_level: slsa-lvl1
    materials:
    - name: <input document or dataset>
      digest:
        sha256: <input hash>
      role: input
  signers:
  - id: AGENT-<ID>
    signature_ref: attestations/<filename>.dsse
-->
```

---

## Example (Policy Update Header)

```markdown
<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "org/policy/2024-07-05-gedi-rollout.md"
      digest:
        sha256: "f1bfc4f86f8d4e5cf3a9e14d047c9e5f0f1733b59dcb5eeeaf37b193f3b6abfe"
  predicateType: "https://accord.ai/schemas/policy@v1"
  predicate:
    produced_by:
      agent_id: "AGENT-PO01"
      agent_role: "Policy Orchestrator"
      coach_id: "AGENT-COACH01"
    process:
      toolchain:
        - name: "policy-synth"
          version: "0.3.2"
      mcp_sessions:
        - server: "mcp://file-system@v1"
          session_id: "98d1a876-1f40-4a54-8ac3-d75e80c6d3be"
    governance:
      gedi_ballot_uri: "logs/gedi/2024-07-04-rollout.json"
      decision_rule: "condorcet"
    quality_checks:
      review_status: "approved"
      tests:
        - name: "policy-lint"
          result: "pass"
    security:
      isolation_level: "sandbox"
      provenance_level: "slsa-lvl1"
    materials:
      - name: "org/_registry/AGENT-PO01.alou.md"
        digest:
          sha256: "d4e0851dc58af53bba1ce1ea2c5afbbf8923a8d2d2fa31b88d93707aa0e1f9f7"
        role: "reference"
      - name: "bus/gedi/2024-07-04-vote.log"
        digest:
          sha256: "b31bd6a039b11b3688e02f651e2b44531b314ae52f78c87a9b1d4c6172bbf44c"
        role: "ballot_log"
  signers:
    - id: "AGENT-PO01"
      signature_ref: "attestations/2024-07-05-gedi-rollout.dsse"
    - id: "AGENT-COACH01"
      signature_ref: "attestations/2024-07-05-gedi-rollout.dsse"
-->
```

---

## DSSE Quick Reference
- **payloadType**: Always `application/vnd.in-toto+json`.
- **payload**: Base64-encode the JSON serialization of the Statement above.
- **Signature algorithm**: Ed25519 (or similar). Follow PAE (Pre-Authentication Encoding) when combining `payloadType` and `payload`.

```
length(type) = len(payloadType)
length(payload) = len(payload)
PAE = "DSSEv1 {length(type)} {payloadType} {length(payload)} {payload}"
```

Use `scripts/provtools.py` to validate the Statement, confirm hashes, and produce DSSE signatures end-to-end.
