# Agent Context — `executiveusa/samantha-os1-her`

- **Purpose:** Voice-first, *Her*-inspired personal OS (OS¹ / Samantha) running 24/7/365 on a Hostinger VPS over Tailscale, with Electron desktop + Web/PWA clients, Infisical self-managing vault, free-LLM multi-token router, OpenCode sidecar, `pstack` self-update framework, and Maus Bots fleet control.
- **Stack:** Electron + React + Three.js + Vite (`apps/desktop`, `packages/ui`), Python 3.12+ FastAPI + SQLite (`services/orchestrator`), LiveKit Agents + Fish Audio + SmartLLMRouter (`services/voice`), Hermes plugins (`hermes/plugins/*`), Docker Compose + Infisical + OpenCode + Tailscale (`docker-compose.vps.yml`, `infra/`).
- **Branch:** `zte/ZTE-20261122-0001/samantha-os1-upgrade` (fork of `nickvasilescu/os1-her`).

## Key Additions & Changes
- **Bug Fixes:** Voice navigation desync (`services/orchestrator/os1_orchestrator/pills.py`), LiveKit audio DOM leak (`packages/ui/src/useOs1.ts`), unsafe `OS1_ENABLE_DEV_RESET` default & Tailscale CORS & tracked bg tasks (`services/orchestrator/os1_orchestrator/app.py`, `services/voice/os1_voice/turns.py`).
- **Smart Free-LLM Router & OpenCode:** `services/voice/os1_voice/llm_router.py`, integrated into `services/voice/os1_voice/brain.py`, catalog sync in `scripts/sync_free_llms.py`, OpenCode config in `infra/opencode/opencode.json`.
- **Infisical Self-Managing Vault:** `services/orchestrator/os1_orchestrator/vault.py`, zero-touch key/SSH bootstrapper in `scripts/bootstrap_vault.py`, self-hosted Postgres+Redis+Infisical in `docker-compose.vps.yml`.
- **Lauren Tan's `pstack` Framework:** `.pstack/principles.md`, `.pstack/playbooks.yaml`, `services/orchestrator/os1_orchestrator/pstack_engine.py`, `hermes/plugins/os1_pstack/`.
- **Tailscale + Hostinger + Maus Bots Bridge:** `services/orchestrator/os1_orchestrator/ops_bridge.py`, `hermes/plugins/os1_ops/`, `infra/tailscale/`, `infra/hostinger/deploy-hostinger.sh`, `infra/hostinger/maus-bots.json`.
- **Web/PWA 24/7 Client:** `apps/desktop/vite.web.config.ts`, `manifest.webmanifest`, `sw.js`, served from orchestrator when `apps/desktop/dist-web` exists.

## Validation Commands
- `(cd services/orchestrator && uv run pytest -q)`
- `(cd services/voice && uv run pytest -q)`
- `npm run typecheck && npm run build && npm run build:web`
- `python scripts/bootstrap_vault.py` & `python scripts/sync_free_llms.py --offline`

## Next Recommended Steps
- Run the Server Agent handoff checklist in `docs/SERVER_AGENT_HANDOFF.md` on the Hostinger VPS.
- Merge PR from `zte/ZTE-20261122-0001/samantha-os1-upgrade` into `main` on `executiveusa/samantha-os1-her`.
