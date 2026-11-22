# Nous Research Hermes Agent — Harness & API Primitives Reference

Official repository: [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent)  
Official documentation: [`hermes-agent.nousresearch.com/docs`](https://hermes-agent.nousresearch.com/docs)

---

## 1. Core Architecture Overview

All Hermes surfaces (CLI, TUI, Desktop, Messaging Gateway, API Server, ACP, Cron, Python Library) drive a single platform-agnostic core class: **`AIAgent`** (`run_agent.py`, loop in `agent/conversation_loop.py` and `agent/turn_*.py`).

```text
Entry Points: CLI · TUI · Desktop · Gateway (25+ platforms) · API Server · ACP · Cron · Python
                                         │
                                         ▼
                               AIAgent (run_agent.py)
        ┌───────────────────┬────────────────────────┬────────────────────┐
        │ Prompt Builder    │ Provider Resolution    │ Tool Registry      │
        │ (stable → context │ (chat_completions /     │ (70+ tools across  │
        │  → volatile)      │  codex_responses /     │  ~28 toolsets +    │
        │  + Compression)   │  anthropic_messages)   │  dynamic MCP)      │
        └─────────┬─────────┴────────────────────────┴─────────┬──────────┘
                  ▼                                            ▼
     SQLite + FTS5 Sessions                     Terminal (6+ backends: local,
     MEMORY.md / USER.md                        Docker, SSH, Modal, Daytona,
     External Memory (Honcho, etc.)             Vercel Sandbox) · Browser CDP
```

### Design Principles Relevant to OS1
- **Prompt stability**: System prompt tiers (`stable` → `context` → `volatile`) avoid cache-breaking mutations mid-conversation.
- **Interruptible**: API calls and tool execution can be cancelled mid-flight (`_interruptible_api_call`).
- **Profile isolation**: Every profile (`hermes -p <name>`) gets an isolated `HERMES_HOME` (`~/.hermes/profiles/<name>/`) with its own `config.yaml`, `.env`, `SOUL.md`, `MEMORY.md`, `USER.md`, skills, SQLite sessions, and TTS settings. Multiple profiles can be served by one multiplexed gateway.

---

## 2. Persona, Profiles & Memory Primitives

### `SOUL.md` (Primary Identity — Slot #1)
- Docs: [Personality & SOUL.md](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality), [Use SOUL.md with Hermes](https://hermes-agent.nousresearch.com/docs/guides/use-soul-with-hermes)
- Location: `$HERMES_HOME/SOUL.md` (loaded **only** from `HERMES_HOME`, never from the working directory).
- Occupies **slot #1 in the system prompt**, completely replacing the built-in default Hermes identity verbatim with no wrapper text.
- Use `SOUL.md` for durable voice, warmth, cadence, conversational style, and emotional posture; keep repo/project instructions in `AGENTS.md`.
- Session-level overlays remain available via `/personality` presets.

### Profiles & Bot Mode
- Docs: [Bot Mode](https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode)
- A "Bot" in Hermes Desktop is simply a Hermes profile (`~/.hermes/profiles/<name>/`).
- Each profile can pin its own LLM provider/model, `SOUL.md`, skills, MCP servers, routines (`hermes cron`), and **per-profile TTS voice** (`tts.*` in that profile's `config.yaml`).

### Layered Memory & Honcho Dialectic User Modeling
- Docs: [Memory Providers](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory-providers), [Honcho Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/honcho)
- **Built-in memory** (always active): `MEMORY.md`, `USER.md` (curated with periodic agent nudges), and SQLite FTS5 cross-session search with LLM summarization.
- **External memory providers** (1 active at a time, additive to built-in):
  - **`honcho`** (catalog plugin: `hermes plugins install honcho && hermes memory setup`) — maintained by Plastic Labs. Runs **non-blocking background memory prefetch** before each turn, injects session summary + user representation + peer card into the system prompt, syncs turns after each response, and runs **multi-pass server-side dialectic reasoning** (`dialecticCadence`) to derive implicit conclusions about user preferences, patterns, and goals. Ideal for Samantha's deepening relationship model.
  - Other supported providers: `mem0`, `hindsight` (catalog), `openviking`, `supermemory`, `holographic`, `retaindb`, `byterover`.
- **Long-term memory scoping over HTTP**:
  - Pass `X-Hermes-Session-Id` for the active transcript and **`X-Hermes-Session-Key`** (max 256 chars, e.g. `agent:samantha:voice:dm:primary`) for the durable user/channel scope so Honcho maintains one continuous model across rotating call sessions.

---

## 3. Proactive Agency & Background Delegation

### Cron & Jobs API
- Docs: [Cron Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/cron-internals), [CLI Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)
- Supports relative delays (`30m`, `2h`), intervals (`every 2h`), 5-field cron (`0 8 * * *`), and ISO timestamps.
- Each cron run executes in a fresh isolated `AIAgent` session (with `MEMORY.md`/`USER.md` loaded and optional attached skills), can deliver to any platform (including voice notes via `fish_speak`), and is controllable over REST (`/api/jobs/*`) or via the agent's `cronjob_manage` tool.
- Pluggable trigger via `cron.provider` (built-in 60s ticker, `chronos` for scale-to-zero gateways, or custom plugin).

### In-Session Heartbeats & Loops
- Docs: [Slash Commands](https://hermes-agent.nousresearch.com/docs/reference/slash-commands)
- `/heartbeat every <interval>` (`/hb`): re-enters an idle session as a turn (min 60s; coalesces missed ticks).
- `/loop [interval] [--times N] [--until <cond>]` (`/proactive`): recurring in-session execution with optional auxiliary LLM stop condition.

### Background Subagents (`delegate_tool`)
- Spawns isolated child agents for long/parallel workstreams.
- On the API Server, when a request uses explicit server-side session continuation (`X-Hermes-Session-Id`, `/api/sessions/{id}/chat`, or `/v1/runs` with `session_id`), detached completions persist into session history and emit `subagent.start` / `subagent.complete` events on `/v1/runs/{id}/events`.

---

## 4. Native Voice & Streaming TTS Primitives

Docs: [Voice Mode](https://hermes-agent.nousresearch.com/docs/user-guide/features/voice-mode), [Use Voice Mode with Hermes](https://hermes-agent.nousresearch.com/docs/guides/use-voice-mode-with-hermes), [Streaming TTS Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/streaming-tts)

### Voice Surfaces
- **CLI & TUI Voice Mode** (`/voice on`, push-to-talk `Ctrl+B`, continuous silence-detected loop, strict stop phrases like `"stop"`).
- **Wake Word** (`/wake on`): built-in on-device hotword listener for CLI, TUI, and Desktop.
- **Messaging Auto Voice Reply**: Telegram & Discord inline Opus/OGG voice bubbles (`/voice on` for voice-only, `/voice tts` for all).
- **Discord Voice Channels**: `/voice join` listens per-user, transcribes, runs full agent loop, speaks back in VC.
- **Desktop Client-Direct Voice**: Remote Desktop fetches `GET /api/audio/voice-config` and calls supported STT/TTS providers directly (plugin providers fall back to gateway relay).
- **Desktop GPT-Live Mode (Full Duplex + Delegation)**:
  - Config: `voice.voice_chat_mode: gpt-live` (uses OpenAI `gpt-live-1` over WebRTC, session minted by gateway `POST /api/audio/voice-live/session`).
  - **Key architectural blueprint**: The voice model has *no tools of its own*; it handles full-duplex listening, backchannels, and interruptions, emits `session.delegation.created` for real work (which executes a normal Hermes turn), receives quiet tool progress (`"Hermes is working: terminal"`), and paraphrases the streamed answer aloud.

### Fast Voice Chat Auxiliary Model
```yaml
auxiliary:
  voice_chat:
    provider: openrouter
    model: google/gemini-3-flash-preview
    reasoning_effort: none   # default on voice turns — avoids thinking dead-air
```
- Runs spoken turns on a fast, non-reasoning model while preserving the full toolset; typed turns, memory curation, and skill reflection stay on the main session model.

### Streaming TTS Pipeline Internals
1. **Producer**: LLM emits text deltas.
2. **Sentence Chunker** (`tools.tts_streaming.SentenceChunker`): strips thinking blocks, buffers clauses (configurable `tts.streaming.min_len`, default 20 chars), cleans via `tools.tts_text_normalize.prepare_spoken_text`, and **prefetches up to 3 sentences concurrently**.
3. **Provider**: Built-in streamers (`elevenlabs`, `openai`, `gemini`, `xai`) or any **plugin `TTSProvider`** registered with `ctx.register_tts_provider()` that sets `streams_pcm = True` and `stream_sample_rate` and implements `stream(text, format="pcm", voice=..., model=..., speed=...)` (must tolerate concurrent calls!).
4. **Audio Sink**: `sounddevice.OutputStream` locally, Desktop speak-stream WebSocket, or gateway `StreamingTTSConsumer` (`gateway/streaming_tts_consumer.py`) for any `BasePlatformAdapter` implementing:
   - `supports_streaming_tts(chat_id, audio_format) -> bool`
   - `begin_streaming_tts` / `write_streaming_tts` / `finish_streaming_tts` / `abort_streaming_tts`

### Full-Duplex Barge-In & Interruption Awareness
- Mic remains live through LLM thinking and TTS playback.
- Noise floor calibrates against the quiet room at turn start (never against playback bleed). Configurable via `voice.barge_in`, `voice.barge_in_threshold_multiplier` (default `3.0`), and `voice.barge_in_grace_seconds` (default `0.5`).
- **Crucial detail**: When interrupted, Hermes appends a short note to the next turn informing the LLM that its previous spoken reply was cut off so it reacts naturally.

### Live Streaming STT
- `stt.streaming: true` enables real-time mid-utterance transcription (built-in: `openai`, `xai`, `elevenlabs`; plugins opt in via `TranscriptionProvider.streaming_capable` + `open_stream_session()`). Falls back cleanly to file transcription on error.

---

## 5. Programmatic & Wire Protocols

Docs: [Programmatic Integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration), [API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server), [Gateway over SSH](https://hermes-agent.nousresearch.com/docs/developer-guide/gateway-ssh-clients), [Agent Loop Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)

### Protocol 1: OpenAI-Compatible API Server (`gateway/platforms/api_server.py`)
Enable in `~/.hermes/.env` (or `gateway.api_server` in `config.yaml`):
```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_KEY=your-secret-key
# API_SERVER_CORS_ORIGINS=http://localhost:3000
```
Multi-profile multiplexing mounts each profile at `/p/<profile>/v1/...` using that profile's own `API_SERVER_KEY`.

**Endpoints**:
- **Chat & Responses**:
  - `POST /v1/chat/completions` — OpenAI format (`stream: true` SSE). Emits `event: hermes.tool.progress` by default; disable for strict OpenAI clients via `gateway.platforms.api_server.tool_progress_events: false`. Supports `X-Hermes-Session-Id`, `X-Hermes-Session-Key`, `Idempotency-Key`, inline images (`image_url`), and per-request `model` / `provider` / `model_options` (`{"reasoning": {"enabled": false}}`).
  - `POST /v1/responses`, `GET/DELETE /v1/responses/{id}` — Stateful OpenAI Responses API (`previous_response_id` or named `conversation`), streaming `response.output_text.delta`, `function_call`, `function_call_output`, and `phase: "commentary"` interim items.
- **Runs API (ideal for async delegation from a realtime voice shell)**:
  - `POST /v1/runs` → `202 {run_id, status}` (supports `Idempotency-Key`, `session_id`, `instructions`)
  - `GET /v1/runs/{id}` → status, `output`, `usage`, `runtime`, `pending_controls`
  - `GET /v1/runs/{id}/events` → SSE stream of `message.delta`, `message.interim`, `tool.started`, `tool.completed`, `subagent.start`, `subagent.complete`, `approval.request`, `run.steered`, and terminal `run.completed` / `run.cancelled` / `run.failed` / `run.interrupted`
  - `POST /v1/runs/{id}/steer` → inject mid-run guidance at the next tool boundary (undelivered text returns as `pending_steer` on terminal event)
  - `POST /v1/runs/{id}/approval` → resolve pending tool/MCP approval (`{request_id, execution_generation, choice}`)
  - `POST /v1/runs/{id}/clarify` → answer a clarification prompt (`{request_id, execution_generation, answer}`)
  - `POST /v1/runs/{id}/stop` → interrupt active run
  - `POST /v1/runs/{id}/resolve-unknown` → recover after gateway restart
- **Sessions, Jobs & Discovery**:
  - `GET/POST/PATCH/DELETE /api/sessions`, `/api/sessions/{id}/messages`, `/fork`, `/chat`, `/chat/stream`
  - `GET/POST/PATCH/DELETE /api/jobs`, `/pause`, `/resume`, `/run`
  - `GET /v1/capabilities`, `GET /v1/models`, `GET /api/model/options`, `GET /v1/skills`, `GET /v1/toolsets`, `GET /health`, `GET /health/detailed`
- **SSE Keepalive**: All SSE streams emit `: keepalive` comments every 10 seconds during long tool calls.
- **Session Isolation Caveat**: API Server sessions cannot bind sessions owned by CLI/Desktop/messaging (`409 permission_denied`). To share live sessions with Desktop/TUI, use Protocol 2.

### Protocol 2: Gateway WebSocket JSON-RPC (`/api/ws`, `hermes-gateway-v1`)
- Powers Ink TUI, Hermes Desktop, and Dashboard.
- Mint single-use connection tickets via `hermes gateway attach --json` (or long-lived `hermes gateway tickets --serve --json` over SSH).
- Reusable Node/TS client: `@hermes/shared/gateway-client` (`GatewayClient`).
- 112 gateway-served RPC methods: `session.create/resume/detach/interrupt/steer/history/transcript/list`, `prompt.submit/cancel/steer_queued`, `subagent.list/steer/interrupt`, `approval.respond`, `clarify.respond`, `command.dispatch`, `config.get/set`, `cron.submit/status/cancel`, `plugin.<id>.*`.
- Supports multi-client session attachment (e.g., voice client + desktop UI viewing the exact same live session) and server→client JSON-RPC requests (`approval`, `clarify`, `sudo`, `secret`) after advertising `client.capabilities({server_requests: true})`.

### Protocol 3: Python In-Process & Plugin SDK
- Docs: [Build a Hermes Plugin](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins), [Adding a Platform Adapter](https://hermes-agent.nousresearch.com/docs/developer-guide/adding-platform-adapters)
- Direct Python embed:
  ```python
  result = agent.run_conversation(
      user_message="...",
      stream_delta_callback=lambda delta: ...,
  )
  ```
- Plugin entry point (`~/.hermes/plugins/<name>/` or pip entry point `hermes_agent.plugins`):
  - `ctx.register_tool(...)`, `ctx.register_hook(...)`, `ctx.register_command(...)`, `ctx.register_cli_command(...)`
  - `ctx.register_platform(...)` (subclass `BasePlatformAdapter` + optional `StreamingTTSConsumer` hooks)
  - `ctx.register_tts_provider(...)` / `ctx.register_stt_provider(...)`
  - `ctx.register_rpc(...)` / `ctx.emit_to_session(...)`
  - `ctx.dispatch_tool(name, arguments)` (invokes any tool through normal approval/redaction/budget pipelines)

### Protocol 4: Event Hooks (4 Systems)
Docs: [Event Hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks)
1. **Plugin hooks** (`ctx.register_hook`): `pre_llm_call`, `post_tool_call`, `on_stream_delta` (bounded async queues — never blocks tokens), `on_session_start`.
2. **Gateway hooks** (`~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py`): `gateway:startup`, `session:start/end/reset/compress`, `agent:start/step/end`.
3. **Shell hooks** (`config.yaml` `hooks:`): drop-in scripts across CLI/Gateway/Desktop.
4. **Outbound webhooks** (`hooks.outbound:`): signed HTTP lifecycle pushes — useful for updating external OS1 ambient UI state.
