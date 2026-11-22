# Samantha OS¹ (`samantha-os1-her`) — Bug Audit & Top 20 Improvements

Audit conducted on `executiveusa/samantha-os1-her` (base commit `a3a7bc4`), combining static code inspection, test execution, and runtime failure analysis from the original demo.

---

## Bugs Found & Fixed in This Release

| # | Bug | Root Cause | Fix Shipped |
|---|---|---|---|
| **B1** | **Voice-to-Screen Desync** ("take me to the cloud" → unauthorized error; "take me to memory" → "heading to canvas") | `pills.py` lacked common natural navigation phrases (`take me to...`, `cloud`, `my mac`, `canvas`, `memory`, `talk`) and `TurnEngine` did not inject `activeSurface` into the brain's system note, so Samantha hallucinated screen state. | Expanded `FILLER_PREFIX` and `GLOBAL_PHRASES` in `pills.py` for zero-LLM deterministic routing + injected live `active_surface` into `TurnEngine` notes. |
| **B2** | **LiveKit `<audio>` DOM Element Leak** | `packages/ui/src/useOs1.ts` appended `track.attach()` to `document.body` on `TrackSubscribed` without detaching on `TrackUnsubscribed` or `Disconnected`. | Added `TrackUnsubscribed` cleanup and unmount/disconnect detachment of all attached audio elements. |
| **B3** | **`OS1_ENABLE_DEV_RESET` Unsafe Default** | `app.py` defaulted `OS1_ENABLE_DEV_RESET` to `"1"` while `.env.example` documented `"0"`, leaving profile/dossier wipe enabled in production if unset. | Changed default to `"0"` in `services/orchestrator/os1_orchestrator/app.py`. |
| **B4** | **CORS Blocks Tailscale & Remote PWA Clients** | `CORSMiddleware` only allowed `localhost:5173` / `127.0.0.1`, breaking 24/7 VPS Web/PWA access over Tailscale MagicDNS (`*.ts.net`) or `100.x.y.z`. | Added dynamic `OS1_ALLOWED_ORIGINS` + regex support for `*.ts.net` and Tailscale CGNAT `100.64.0.0/10`. |
| **B5** | **Fire-and-Forget `asyncio.ensure_future` GC Hazard** | `app.py` and `turns.py` spawned unreferenced tasks with `asyncio.ensure_future(...)`, risking silent GC cancellation and swallowed exceptions in Python 3.12+. | Added tracked background task sets with `add_done_callback` exception logging. |
| **B6** | **Single-Provider Paid LLM Lock-In** | `services/voice/os1_voice/brain.py` hardcoded `AsyncAnthropic` (`claude-sonnet-5-5`) with no fallback, failing immediately on missing key or 429 rate limits. | Replaced direct single-provider call with `SmartLLMRouter` supporting OpenRouter `:free`, NVIDIA NIM free tier, Groq/Cerebras/Gemini/Mistral (`awesome-freellm-apis`), OpenCode, and Anthropic fallback. |

---

## Top 20 Ways to Make Samantha OS¹ Better & More Capable

### Tier 1 — Shipped in This Upgrade (`ZTE-20261122-0001`)
1. **Smart Free-LLM & Multi-Token Switcher (`SmartLLMRouter`)** — Automatic health-scored, EWMA-latency-aware routing across OpenRouter `:free` models, NVIDIA NIM free tier, `awesome-freellm-apis` ultra-fast free providers (Groq, Cerebras, Gemini, Mistral), and OpenCode, with multi-key rotation and automatic 429 cooldown backoff.
2. **OpenCode (`anomalyco/opencode`) Headless Integration** — Always-on `opencode serve` sidecar wired as both a free-model LLM provider and Samantha's self-coding execution backend.
3. **Self-Hosted Infisical Vault + Auto-Key Bootstrap** — Self-managing open-source Infisical stack (Postgres + Redis + Infisical) with zero-touch cryptographic generation of internal tokens, LiveKit keys, OpenCode credentials, and Ed25519 SSH keypairs (`scripts/bootstrap_vault.py`) plus Machine Identity API sync.
4. **Lauren Tan's `pstack` Self-Evolution Framework** — Embeds `.pstack/` playbooks (`poteto-mode`, `architect`, `tdd`, `unslop`, `blast-radius`, `reflect`) and 24 core engineering principles so Samantha plans, verifies, and updates her own codebase without shipping slop.
5. **Tailscale Zero-Trust Mesh Bridge** — Tailscale Docker sidecar + `serve.json` HTTPS reverse proxy exposing Samantha privately across all user devices (`https://samantha.<tailnet>.ts.net`) with zero exposed public ports.
6. **Hostinger VPS Pipeline & Self-Management** — Idempotent `infra/hostinger/deploy-hostinger.sh` + Hostinger VPS REST API + hardened Ed25519 SSH bridge for 24/7/365 autonomous server ops.
7. **Maus Bots Fleet Controller** — Unified SSH/Docker/systemd control plane (`/os1/ops/bots/*` + `hermes/plugins/os1_ops`) allowing Samantha to inspect logs, check health, restart, and deploy Maus Bots under risk-tiered confirmation gates.
8. **24/7/365 Web/PWA Client** — Responsive installable PWA build (`npm run build:web` + `manifest.webmanifest` + `sw.js`) served directly from the VPS over Tailscale alongside the native Electron desktop app.
9. **Deterministic Voice-to-Surface Synchronization** — Zero-LLM natural phrase navigation (`take me to cloud/memory/canvas/swarm/talk/vault/ops`) + active surface awareness injected into every spoken turn.
10. **Free-LLM Catalog Auto-Sync (`scripts/sync_free_llms.py`)** — Pulls fresh provider/model availability from `open-free-llm-api/awesome-freellm-apis` into the router registry.

### Tier 2 — High-Leverage Next Milestones (Roadmap)
11. **Local Whisper / Faster-Whisper + Kokoro / Piper Offline Voice Fallback** — Add local CPU/GPU STT + TTS fallback on the VPS so Samantha stays 100% free and operational even if Fish Audio quota is exhausted.
12. **Streaming Speculative Audio Pre-Roll** — Begin TTS synthesis on the first complete clause (`.`, `?`, `!`, `—`) while the LLM streams the rest, cutting perceived voice latency below 350 ms.
13. **Semantic Vector Memory + Knowledge Graph (SQLite-vec)** — Upgrade `Os1Store` SQLite memories with local embeddings + hybrid BM25/vector retrieval so Samantha recalls long-horizon context accurately across months.
14. **Proactive Ambient Heartbeat & Scheduled Briefings** — Cron-driven morning briefings, inbox digest, and Maus Bots anomaly alerts pushed through the orchestrator attention triage queue.
15. **Multi-Agent Swarm Live Visualizer** — Stream live tool-call traces and sub-agent progress from Hermes + OpenCode + Maus Bots into the OS¹ `Swarm` surface with per-agent kill/steer pills.
16. **Voice Biometric Speaker Verification** — Require voiceprint match (or Tailscale device identity + PIN) before approving `money` or `forget` or `destructive_ops` risk-tier actions.
17. **Cross-Platform Bounded CUA Host (Windows + Linux + macOS)** — Extend `apps/desktop/src/main/cuaHost.ts` beyond macOS allowlists to support bounded Windows and Linux desktop automation.
18. **Automatic PR Creation & Canary Self-Updates** — Wire `os1_pstack` to run `pstack` verification in a sandbox container, open a GitHub PR on `executiveusa/samantha-os1-her`, and auto-roll back if `/health` fails after deploy.
19. **OpenTelemetry + Prometheus Cost/Latency Telemetry** — Track TTFT, free-tier vs paid-tier token savings, 429 rate-limit events, and Maus Bots uptime in a lightweight dashboard.
20. **End-to-End Playwright + Voice Replay CI Suite** — Automated GitHub Actions workflow running pytest, TypeScript checks, Electron/PWA builds, and mocked voice-turn golden transcripts on every push.
