#!/usr/bin/env bash
# Load environment variables from .env (or ACCORD_ENV_FILE) and execute a command.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ACCORD_ENV_FILE:-$ROOT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "[with-env] warning: env file '$ENV_FILE' not found; continuing without overrides" >&2
fi

if [[ $# -eq 0 ]]; then
  echo "Usage: scripts/with-env.sh <command> [args...]" >&2
  exit 2
fi

exec "$@"
