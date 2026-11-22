# OS1 / Samantha — Research Index & Executive Summary

*Research snapshot: November 22, 2026*

This directory captures the full technical research for building an **OS1 / Samantha (*Her*)** realtime voice AI companion on top of **Nous Research's Hermes Agent** harness and a custom **Fish Audio** voice model.

## Documents in This Folder

| File | Contents |
|---|---|
| [`hermes-harness-primitives.md`](./hermes-harness-primitives.md) | Complete map of Hermes Agent's architecture, `SOUL.md`, profiles/Bot Mode, Honcho & memory providers, cron/heartbeats/subagents, Voice Mode, Streaming TTS internals, all 4 programmatic protocols (API Server, Gateway WebSocket JSON-RPC, Python `AIAgent`/Plugin SDK, ACP), and hooks |
| [`fish-audio-realtime.md`](./fish-audio-realtime.md) | Fish Audio models (`s2.1-pro`, `drama-3`, `live3`), expressive `[bracket]` direction syntax, WebSocket TTS (`wss://api.fish.audio/v1/tts/live`), realtime STT (`wss://api.fish.audio/v1/asr/realtime`), the official `fish-audio-hermes` plugin, LiveKit & Pipecat plugins, Fish Agents (`@fishaudio/agent-react` + `llm.custom`), pricing, limits, and deprecations |
| [`architectures-and-ecosystem.md`](./architectures-and-ecosystem.md) | The 4 concrete realtime voice architectures for `os1-her`, comparison matrix, catalog of open-source reference repos/PRs, and critical technical gotchas |
| [`cua-driver-mcp-computer-use.md`](./cua-driver-mcp-computer-use.md) | Cua AI (`cua.ai` / `trycua/cua`) & Cua Driver (`cua-driver`) MCP computer use for users' own computers — background-first action ladder, Hermes built-in `computer_use` integration, `EmbeddedCuaDriverHost` desktop embedding, cloud-to-local bridge, capability manifests, policies, and platform limits |

Starter Hermes profile templates live in [`../../config/hermes-profile-example/`](../../config/hermes-profile-example/):
- [`config.yaml`](../../config/hermes-profile-example/config.yaml) — Profile configuration for `samantha` (API Server, Fish Audio plugin, Honcho memory, fast `voice_chat` auxiliary slot)
- [`SOUL.md`](../../config/hermes-profile-example/SOUL.md) — Starter spoken-first identity file (slot #1 in Hermes's system prompt)

---

## Executive Summary

Both ecosystems already provide strong native building blocks for a Samantha-class realtime voice agent:

1. **Hermes Agent (`NousResearch/hermes-agent`)** already supplies the cognitive harness:
   - `SOUL.md` (slot #1 durable persona), **Honcho** dialectic user modeling (evolves a model of the user across sessions), `MEMORY.md` / `USER.md` + SQLite FTS5 cross-session recall, self-improving skills, proactive `cron` / `/heartbeat` / `/loop` triggers, background subagents (`delegate_tool`), fast `auxiliary.voice_chat` model routing (reasoning disabled for spoken turns), barge-in with interruption awareness, and a full **OpenAI-compatible API Server + Runs API + Gateway WebSocket JSON-RPC**.
2. **Fish Audio has an official Hermes Agent plugin** ([`fishaudio/fish-audio-hermes`](https://github.com/fishaudio/fish-audio-hermes)) on the [Hermes Marketplace](https://hermes-agent.nousresearch.com/marketplace/fish-audio) that integrates directly with Hermes's `StreamingTTSProvider` (24 kHz PCM sentence-by-sentence streaming, ~243–381 ms TTFA) and realtime STT (`transcribe-stream-1`).
3. **Fish Audio's direct WebSocket TTS** (`wss://api.fish.audio/v1/tts/live`) has official **LiveKit** (`livekit-agents[fishaudio]`) and **Pipecat** (`pipecat-ai[fish]`) plugins, supports **S2.1 Pro** and **Drama 3** (plain-language performance direction like `[softly, smiling]` and `[small laugh]`), and powers Fish's **Voice Agent Platform** (**Live 3** full-duplex or **Drama 3 / S2.1 Pro** cascade + **Custom LLM**).
4. **Open-source Hermes + OS1 / Realtime blueprints already exist**:
   - [`nickvasilescu/hermes-desktop-os1`](https://github.com/nickvasilescu/hermes-desktop-os1) (*Her*-inspired native macOS OS1 client for Hermes)
   - [`nickvasilescu/hermes-voice-ios`](https://github.com/nickvasilescu/hermes-voice-ios) (iPhone-first dual-brain voice UI delegating durable work to Hermes)
   - [`kortexa-ai/hermes-realtime`](https://github.com/kortexa-ai/hermes-realtime) (native Hermes gateway plugin adding Direct WebRTC + LiveKit Conference)
   - [`rahulsethi/hermes-voice`](https://github.com/rahulsethi/hermes-voice) (self-hosted LiveKit worker backed by Hermes's OpenAI bridge)
   - [`NousResearch/hermes-agent#27040`](https://github.com/NousResearch/hermes-agent/pull/27040) + `tmylk/hermes-plugin-voice-pipecat` (generic `voice_server` WebSocket gateway + Pipecat)

---

## Architecture Comparison at a Glance

| Dimension | Arch 1: Native Plugins (`hermes-realtime` + `fish-audio-hermes`) | Arch 2: LiveKit / Pipecat + Fish WS + Hermes API | Arch 3: Dual-Brain OS1 (Voice Shell + Hermes Runs) | Arch 4: Fish Agent (`live3` / `fish_tts`) + Custom LLM |
|---|---|---|---|---|
| **Setup Effort** | Lowest (minutes) | Moderate (1 Python worker) | Higher (bridge + 2 prompts) | Low–Moderate (HTTPS shim) |
| **Custom Fish Model Fidelity** | Exact (`s2.1-pro` / `drama-3`) | **Exact + raw `[emotion]` tags** | **Exact + raw `[emotion]` tags** | Exact on `fish_tts`; approx on `live3` |
| **Turn-Taking / Barge-In** | Silero VAD + silence timeout | **Semantic EOT + instant barge-in** | **Instant + talks while tools run** | **True full-duplex (`live3`)** |
| **Long Tool-Call UX** | Pauses while tools run | Pauses (or filler via SSE) | **Seamless (chats while working)** | Pauses (needs keepalive/shim) |
| **Full Hermes Power** | 100% native | 100% via API Server | 100% via `/v1/runs` + `/steer` | 100% via `/v1/chat/completions` |

---

## Recommended Staged Buildout Plan

1. **Stage 1 — Samantha's Brain (Hermes Profile)**
   - Create a dedicated `samantha` Hermes profile using [`config/hermes-profile-example/SOUL.md`](../../config/hermes-profile-example/SOUL.md) and [`config/hermes-profile-example/config.yaml`](../../config/hermes-profile-example/config.yaml).
   - Enable Honcho memory (`hermes plugins install honcho && hermes memory setup`), configure `auxiliary.voice_chat` (fast model, `reasoning_effort: none`), enable `API_SERVER_ENABLED=true`, and attach personal MCP servers (calendar, email, notes, browser).
   - Optionally install `100yenadmin/fish-audio-hermes` + `kortexa-ai/hermes-realtime` to validate `SOUL.md`, Honcho recall, and your Fish `reference_id` immediately in CLI/WebRTC.
2. **Stage 2 — Realtime Voice Core (Arch 2 → Arch 3)**
   - Build a Python **LiveKit Agents** (or **Pipecat**) voice worker with `livekit-agents[fishaudio]` (`wss://api.fish.audio/v1/tts/live`, `drama-3` or `s2.1-pro`, your `reference_id`) + semantic turn detection + instant barge-in.
   - Route conversational turns to Hermes API Server (`POST /v1/chat/completions` with `X-Hermes-Session-Id` and stable `X-Hermes-Session-Key`).
   - Evolve to **Arch 3 (Dual-Brain)**: keep a sub-400 ms voice shell for immediate conversation and delegate long/multi-step work to Hermes via `POST /v1/runs` + `GET /v1/runs/{id}/events` (SSE) + `/steer` + `/approval` + `/clarify`.
3. **Stage 3 — OS1 Client Surface**
   - Build a minimal *Her*-inspired client (web, macOS, or iOS) with warm coral-on-cream styling, voice-reactive orb/ribbon visualizer, tap-to-interrupt, voice approval prompts, and an ambient activity rail showing background Hermes runs.
