#!/usr/bin/env bash
# Idempotent Hostinger Ubuntu VPS deployment pipeline for Samantha OS¹ (24/7/365)
# Usage:
#   ./infra/hostinger/deploy-hostinger.sh          # dry-run preflight
#   ./infra/hostinger/deploy-hostinger.sh --apply  # live deploy on Hostinger VPS
set -euo pipefail

APPLY="${1:-}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_DIR}/.vault-staging/generated-secrets.env"

echo "[OS1 Hostinger Pipeline] Repo: ${REPO_DIR}"

if [[ "${APPLY}" != "--apply" ]]; then
  echo "[DRY-RUN] Would verify Docker, bootstrap Infisical vault keys, sync free LLMs, and launch docker-compose.vps.yml."
  echo "[DRY-RUN] Re-run with --apply on the Hostinger VPS to execute."
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[OS1] Installing Docker Engine..."
  curl -fsSL https://get.docker.com | sh
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[OS1] Installing Python 3..."
  apt-get update && apt-get install -y python3
fi

cd "${REPO_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[OS1] Bootstrapping internal vault secrets & SSH keypair..."
  python3 scripts/bootstrap_vault.py --out "${REPO_DIR}/.vault-staging"
fi

echo "[OS1] Refreshing free LLM router catalog..."
python3 scripts/sync_free_llms.py || python3 scripts/sync_free_llms.py --offline

echo "[OS1] Starting 24/7/365 Samantha OS1 stack..."
docker compose -f docker-compose.vps.yml --env-file "${ENV_FILE}" up -d --build

echo "[OS1] Waiting for orchestrator /health..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8787/health >/dev/null 2>&1; then
    echo "[OS1] Orchestrator healthy!"
    curl -fsS http://127.0.0.1:8787/health
    echo ""
    exit 0
  fi
  sleep 2
done

echo "[ERROR] Orchestrator did not become healthy within 60s." >&2
docker compose -f docker-compose.vps.yml logs --tail 60 orchestrator >&2
exit 1
