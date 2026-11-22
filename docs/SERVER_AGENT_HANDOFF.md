# Samantha OS¹ — Server Agent Handoff (Hostinger VPS 24/7/365)

Everything on the codebase, vault key generation, free-LLM routing, OpenCode sidecar, `pstack` self-update engine, Tailscale bridge, Hostinger pipeline, and Web/PWA build is wired and verified.

All that remains for the **Server Agent** on your Hostinger Ubuntu VPS is connecting the VPS and starting the stack.

---

## Pre-Generated Local Staging (Gitignored — Never Committed)

On this machine, `scripts/bootstrap_vault.py` has already generated Samantha's internal cryptographic keys & SSH keypair into `.vault-staging/`:
- `.vault-staging/generated-secrets.env` — all internal service tokens (`OS1_CLIENT_TOKEN`, `OS1_BRAIN_TOKEN`, `HERMES_API_KEY`, `COMPOSIO_WEBHOOK_SECRET`, `OPENCODE_SERVER_PASSWORD`), Infisical master secrets (`INFISICAL_ENCRYPTION_KEY`, `INFISICAL_AUTH_SECRET`, `INFISICAL_DB_PASSWORD`, `INFISICAL_REDIS_PASSWORD`), and self-hosted LiveKit keys (`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`).
- `.vault-staging/samantha_ed25519` + `.vault-staging/samantha_ed25519.pub` — Samantha's dedicated Ed25519 SSH keypair for Hostinger & Maus Bots control.
- `.vault-staging/vault-manifest.json` — machine-readable manifest (key names & public SSH key only).

---

## Server Agent 5-Step Cutover Checklist

1. **Clone the fork on the Hostinger VPS:**
   ```bash
   git clone https://github.com/executiveusa/samantha-os1-her.git /opt/samantha-os1-her
   cd /opt/samantha-os1-her
   git checkout zte/ZTE-20261122-0001/samantha-os1-upgrade  # or main once PR is merged
   ```

2. **Transfer or bootstrap `.vault-staging/`:**
   - Option A (recommended): SCP `.vault-staging/` from this workstation to `/opt/samantha-os1-her/.vault-staging/` (and `chmod 600` on `generated-secrets.env` and `samantha_ed25519`).
   - Option B: Run `python3 scripts/bootstrap_vault.py` directly on the Hostinger VPS to generate fresh keys on-box.
   - Add `.vault-staging/samantha_ed25519.pub` to `~/.ssh/authorized_keys` on the Hostinger VPS (and any Maus Bots host).

3. **Populate external provider keys in `.vault-staging/generated-secrets.env` (or in Infisical UI at `http://127.0.0.1:8080`):**
   - **Free LLMs (pick 1+):** `OPENROUTER_API_KEYS` (comma-separated for multi-token rotation), `NVIDIA_API_KEYS`, `GROQ_API_KEYS`, `CEREBRAS_API_KEYS`, `GOOGLE_API_KEYS`. (OpenCode free models also run automatically via the `opencode` sidecar.)
   - **Voice:** `FISH_API_KEY`, `FISH_OPERATOR_VOICE_ID`, `FISH_VOICE_1_ID`.
   - **Networking & Ops:** `TS_AUTHKEY` (Tailscale auth key), `HOSTINGER_API_TOKEN`, `HOSTINGER_VM_ID`, `HOSTINGER_SSH_HOST`.
   - **Maus Bots:** Edit `infra/hostinger/maus-bots.json` with your exact Docker container names or systemd unit names.

4. **Launch the 24/7/365 stack with one idempotent command:**
   ```bash
   ./infra/hostinger/deploy-hostinger.sh --apply
   ```

5. **Connect Infisical Machine Identity (optional auto-sync):**
   - Open Infisical at `https://samantha.<your-tailnet>.ts.net/vault` (or `http://127.0.0.1:8080` via SSH tunnel).
   - Create a Machine Identity (Universal Auth), set `INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`, `INFISICAL_PROJECT_ID`, and run:
     ```bash
     python3 scripts/bootstrap_vault.py --push-infisical
     ```
   - Open Samantha's 24/7 Web/PWA UI at `https://samantha.<your-tailnet>.ts.net/#token=<OS1_CLIENT_TOKEN>` from any phone, tablet, or desktop!
