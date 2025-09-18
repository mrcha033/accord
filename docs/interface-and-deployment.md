# MCP Interface & Deployment Guide

## Ownership & Tracking
- **Owner**: AGENT-OPS01 (Operations Steward)
- **Escalation**: ops@accord.ai
- **Issue Tracker**: org/policy/ops-runbook.md#FLEET-MCP-001
- **Acceptance Criteria**:
  1. File endpoint responds to `/health` with HTTP 200.
  2. Search endpoint responds to `/health` with HTTP 200.
  3. `scripts.health_mcp` exits `0` when run against the deployment.
  4. Orchestrator reads via remote MCP clients when reachable and logs a fallback message when not.

## Local Deployment (Docker)

```bash
docker compose -f deploy/mcp-file.yaml up -d
docker compose -f deploy/mcp-search.yaml up -d

export ACCORD_MCP_MODE=remote
export ACCORD_MCP_FILE_URL=http://localhost:8082
export ACCORD_MCP_SEARCH_URL=http://localhost:8083
```

## Health Checks

```bash
python -m scripts.health_mcp --endpoint file=$ACCORD_MCP_FILE_URL --endpoint search=$ACCORD_MCP_SEARCH_URL
```

Expect `All MCP endpoints healthy.` or a diagnostic message.

## Notes
- Search container reads indexes from `indexes/`; rebuild snapshots before deployment.
- Guarded MCP calls fall back to local stubs if servers become unreachable (logged at `WARNING`).
