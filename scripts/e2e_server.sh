#!/usr/bin/env bash
# Starts Agora on practice data in a throwaway folder, for the Playwright smoke test.
set -euo pipefail
cd "$(dirname "$0")/.."
DATA_DIR="$(mktemp -d)"
export AGORA_DATA_DIR="$DATA_DIR" AGORA_FAKE_DATA=1 AGORA_FAKE_AI=1
uv run python -m backend.db.migrate >/dev/null
exec uv run uvicorn --factory backend.main:create_app --host 127.0.0.1 --port "${E2E_PORT:-8798}"
