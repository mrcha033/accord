# Changelog

## [0.4.0] - 2025-09-18
### Full Implementation (M-A…M-F locked)
- Automated GEDI governance lifecycle (ballot issuance, voting, tally, adoption) with DSSE-backed briefs and bus summaries.
- Bus channel linting gate integrated into CI to enforce publishing templates.
- ALOU-driven roster and scope matrix generators with corresponding tests and docs refresh.
- Remote MCP client hardened with path sanitisation, retries, auth handling, and health/fallback orchestration improvements.
- Index snapshot pipeline gains `--since`/`--snapshot` support plus DSSE attestations recorded in orchestrator materials.
- Behavior logging pipeline emits `events.jsonl` with policy/scopes metadata and integrates with `metrics_behavior --check`.

### Release Checklist
- `python -m scripts.gen_roster`
- `python -m scripts.gen_scope_matrix`
- `python -m scripts.index_build --since HEAD --snapshot --priv keys/ed25519.key`
- `venv/bin/python -m scripts.metrics_behavior --check experiments/results/<DATE>/events.jsonl`
- `venv/bin/python -m scripts.provtools verify <*.dsse>`
- Tag: `git tag -a v0.4.0 -m "Full Implementation"`

