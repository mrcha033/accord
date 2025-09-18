# Accord Provenance Tooling

Accord provides a reproducible "proof chain" for policy artifacts. It bundles
in-toto provenance statements, DSSE signing/verification, runtime permission
guards, and CI automation so that every Markdown policy change is backed by a
cryptographically verifiable attestation.

## Key Components

- **`scripts/provtools.py`** – Normalize, validate, sign, and verify provenance
  statements embedded in Markdown front matter.
- **`scripts/policy_synth_pipeline.py`** – CLI pipeline that optionaly runs a
  synthesis command, rebuilds the attestation, and surfaces verification
  results.
- **`scripts/runtime_guard.py`** – Runtime enforcement of `mcp_allow` endpoints
  and `fs_write_scopes` derived from an agent's ALOU definition.
- **`.github/workflows/provenance.yml`** – GitHub Actions gate that rebuilds and
  verifies every touched Markdown document on pull requests.
- **`tests/`** – Pytest suite covering provenance handling, runtime guard rules,
  and pipeline behaviour.

## Installing

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt  # install pytest, jsonschema, etc.
```

## Environment Configuration

Sensitive settings (LLM provider, API keys, provenance key overrides) live in
`.env` files that never leave your machine.

1. Copy the template and customise values:

   ```bash
   cp .env.template .env
   # edit .env and set ACCORD_LLM_PROVIDER, OPENAI_API_KEY, etc.
   ```

2. Run orchestration commands through the helper so variables load automatically:

   ```bash
   scripts/with-env.sh python -m orchestrator.run_experiment --spec experiments/run.yaml --attest
   ```

Set `ACCORD_ENV_FILE=/path/to/profile.env` when you want an alternate config.


## Embedding Provenance in Markdown

Front matter must follow the in-toto statement schema. See
`docs/templates/in-toto-attestation-header.md` for a complete template.

## CLI Usage

### Build

```bash
source venv/bin/activate
python -m scripts.provtools build docs/policy.md \
  --priv keys/ed25519.key \
  --out attestations/policy.dsse \
  --base .
```

Outputs structured JSON:

```
{
  "event": "build",
  "ok": true,
  "file": "docs/policy.md",
  "dsse": "attestations/policy.dsse",
  "trace_id": "…",
  "duration_ms": 12
}
```

### Verify

```bash
python -m scripts.provtools verify attestations/policy.dsse \
  --pub keys/ed25519.pub --base .
```

```
{
  "event": "verify",
  "signature_ok": true,
  "schema_ok": true,
  "digest_ok": true,
  "statement_ok": true,
  "error_code": "OK",
  "errors": [],
  "dsse": "attestations/policy.dsse",
  "duration_ms": 9
}
```

### Policy Pipeline

```bash
python -m scripts.policy_synth_pipeline docs/policy.md \
  keys/ed25519.key attestations/policy.dsse --base-dir .
```

The CLI wraps build + verify and returns a JSON payload with `verify` results
and exit codes suitable for automation.

## Runtime Guard

```python
from pathlib import Path
from scripts.runtime_guard import RuntimeGuard, ScopeError

guard = RuntimeGuard.from_alou("org/_registry/AGENT-PO01.alou.md", base_dir=".")
wrapped_tool = guard.wrap_tool_call(raw_tool_call)

try:
    guard.fs.write_text(Path("org/policy/new-policy.md"), "# Draft\n")
except ScopeError as exc:
    log.error("Write denied", extra={"error": str(exc)})
```

The guard enforces:

- MCP endpoints listed in `mcp_allow`
- Filesystem write scopes listed in `fs_write_scopes`
- No tilde, absolute, symlink, or base-escape paths.

## CI Workflow

`.github/workflows/provenance.yml` runs on every pull request:

1. Determines changed Markdown files using the PR base SHA.
2. Rebuilds and verifies attestation envelopes.
3. Fails the PR if any `signature_ok`, `schema_ok`, or `digest_ok` flag is
   false.
4. Uploads `attestations/ci/summary.json` (and DSSE envelopes on failure).

Make the workflow required in branch protection to enforce provenance.

## Testing & Stress

```bash
source venv/bin/activate
python -m pytest -q                        # unit / integration tests
PYTHONPATH=. python -m pytest -q -n auto -k "provtools and (build or verify)"
```

Recommended stress for race-proof hashing and atomic writes:

```bash
PYTHONPATH=. bash -c 'seq 1 1000 | xargs -I{} -P 16 \
  python -m scripts.provtools build samples/bundle.md \
    --priv keys/ed25519.key --out attestations/race.dsse >/dev/null'
python -m scripts.provtools verify attestations/race.dsse \
  --pub keys/ed25519.pub --base .
```

## Release Checklist (v0.3+)

- CI provenance workflow marked "required".
- Keys generated/rotated outside the repository; CI uses ephemeral keys.
- DSSE + `summary.json` retention configured (e.g. 30–90 days).
- Runbook mapping `error_code` to response: `SIG_INVALID`, `SCHEMA_INVALID`,
  `DIGEST_MISMATCH`, `PATH_FORBIDDEN`, `HASH_RACE`, etc.
- All orchestrator paths use the runtime guard wrappers exclusively.

## License

MIT
