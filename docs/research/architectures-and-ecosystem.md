# OS1 / Samantha — Realtime Architectures, Open-Source Ecosystem & Gotchas

---

## 1. Four Concrete Architectures for `os1-her`

### Architecture 1: Pure Native Hermes Plugins (Fastest Prototype)
Zero custom voice server code — install both plugins directly into a `samantha` Hermes profile.

```text
OS1 Web / Mobile / Desktop Client (WebRTC or LiveKit SDK)
        │  RTP audio + oai-events / conference.events data channel
        ▼
Hermes Gateway + kortexa-ai/hermes-realtime
  ├── Bundled Silero VAD v6.2 + speculative ASR prefetch + leading-silence trim
  ├── Full in-process AIAgent (SOUL.md + Honcho + 70+ tools + MCP + Skills)
  └── StreamingTTSConsumer ──▶ fish-audio-hermes (24 kHz PCM, YOUR reference_id)
```

- **Install**:
  ```bash
  hermes -p samantha plugins install 100yenadmin/fish-audio-hermes --enable --yes-deps
  hermes -p samantha plugins install kortexa-ai/hermes-realtime/hermes_realtime --enable --yes-deps
  hermes -p samantha config set streaming.enabled true
  hermes -p samantha config set display.platforms.realtime.streaming true
  hermes -p samantha config set display.platforms.livekit.streaming true
  ```
- **Pros**: Fastest path to a working WebRTC/LiveKit Samantha with zero glue services; 100% native Hermes sessions, tools, Honcho memory, and `response.cancel` barge-in.
- **Cons**: Silence-timeout VAD (not semantic end-of-turn); Hermes's core text normalizer can mangle Drama 3 word tags (`upstream #133131`); direct WebRTC advertises host ICE candidates (use its LiveKit Conference transport or TURN for internet reachability).

---

### Architecture 2: LiveKit Agents or Pipecat Worker → Hermes API Server (Recommended Starting Point)
A dedicated realtime voice runtime owns audio transport, **semantic turn detection**, crisp barge-in, and direct **Fish Audio WebSocket TTS (`wss://api.fish.audio/v1/tts/live`)**, while routing the LLM leg to Hermes's OpenAI-compatible API Server (`:8642`).

```text
OS1 Client (Web / macOS / iOS over WebRTC)
        │
        ▼
LiveKit Agents (or Pipecat) Python Voice Worker
  ├── Silero VAD + Semantic Turn Detection + Instant Barge-In
  ├── Streaming STT (Deepgram / Fish transcribe-stream-1 / Whisper)
  ├── LLM ──▶ Hermes API Server (POST http://127.0.0.1:8642/v1/chat/completions)
  │           Headers: X-Hermes-Session-Id + X-Hermes-Session-Key (Honcho!)
  └── TTS ──▶ Fish Audio WebSocket (wss://api.fish.audio/v1/tts/live)
              model: drama-3 or s2.1-pro · reference_id: YOUR_MODEL_ID
```

- **Pros**:
  - **Maximum voice expressiveness & fidelity**: Streams raw LLM tokens straight to Fish WebSocket so Samantha can use `[warmly]`, `[soft laugh]`, `[whispering]` Drama 3 / S2.1 Pro cues untouched by Hermes's core text normalizer (while stripping tags from the visual transcript).
  - **Semantic turn-taking**: LiveKit's Turn Detector / Pipecat's Smart Turn avoids interrupting mid-thought while cutting playback instantaneously on barge-in.
  - **Full Hermes capabilities**: Tools, MCP, Honcho memory, `SOUL.md`, skills, cron.
- **Cons**: One lightweight Python worker process alongside `hermes gateway`; long multi-step tool calls still pause the spoken turn unless bridged with Arch 3.

---

### Architecture 3: Dual-Brain "True OS1 / Samantha" (Voice Shell + Durable Hermes Worker)
Modeled directly on [`nickvasilescu/hermes-voice-ios`](https://github.com/nickvasilescu/hermes-voice-ios) and Hermes Desktop's built-in `gpt-live` delegation design — but keeping **your Fish Audio custom voice**.

In *Her*, Samantha never freezes in silence while scanning thousands of emails or executing code. She talks naturally *while* work runs asynchronously in the background.

```text
                      ┌──────────────────────────────────────────────────┐
                      │  Fast Voice Shell (<400 ms TTFA)                 │
User ◀── WebRTC ────▶ │  LiveKit / Pipecat + Fast LLM (no reasoning)     │
                      │  + Fish Audio WebSocket (YOUR reference_id)      │
                      │  5 Narrow Tools:                                 │
                      │   delegate · status · steer · cancel · approve   │
                      └───────────────────────┬──────────────────────────┘
                                              │ REST + SSE (/v1/runs)
                                              ▼
                      ┌──────────────────────────────────────────────────┐
                      │  Durable Hermes Agent (Profile: samantha)        │
                      │  POST /v1/runs · GET /v1/runs/{id}/events (SSE)  │
                      │  POST /v1/runs/{id}/steer · /approval · /clarify │
                      │  70+ tools · MCP · Sandbox · Cron · Honcho       │
                      └──────────────────────────────────────────────────┘
```

- **How it works**:
  1. Casual conversation, emotional banter, and follow-ups stay in the fast Voice Shell (backed by shared Honcho user context).
  2. When real work is needed (research, email triage, coding, calendar edits), the Voice Shell calls `delegate(task)` → `POST /v1/runs` with `session_id` + `X-Hermes-Session-Key` and immediately replies verbally (*"On it — give me a second while I look through that..."*).
  3. The bridge subscribes to `GET /v1/runs/{id}/events` (SSE) and injects quiet context updates (`tool.started`, `message.interim`, `approval.request`, `subagent.complete`, `run.completed`) back into the Voice Shell so she can speak naturally about progress, ask for verbal tool approval (`POST /v1/runs/{id}/approval`), or adjust mid-flight (`POST /v1/runs/{id}/steer`).
- **Pros**: True *Her* conversational fluidity + zero dead air during long tool calls + exact Fish voice fidelity + voice-native approval & steering.
- **Cons**: Requires careful prompt/context synchronization so both layers feel like one unified consciousness.

---

### Architecture 4: Managed Fish Audio Agent (`Live 3` or `Drama 3`) + Custom LLM → Hermes
Offload WebRTC, phone numbers, VAD, and full-duplex turn-taking to Fish Audio's Agents platform (`@fishaudio/agent-react`), pointing `llm.custom.base_url` at a thin HTTPS shim in front of Hermes API Server (`:8642`).

- **Pros**: Drop-in React/Web/React Native/Phone SDKs; fastest path to **Live 3 full-duplex backchannels** (`"mm-hmm"` while you speak).
- **Cons**: Requires publicly reachable HTTPS endpoint; `live3` approximates custom voices from a sample (use `voice.engine: "fish_tts"` + `drama-3` / `s2.1-pro` for exact fidelity); per-minute platform billing ($0.07/min; $0.035/min promo through Dec 31, 2026) plus LLM cost.

---

## 2. Open-Source Reference Repos & PRs

| Repository / PR | Purpose | Key Patterns to Study / Reuse |
|---|---|---|
| [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent) | Core Hermes harness | `gateway/streaming_tts_consumer.py`, `gateway/platforms/api_server.py`, `voice.voice_chat_mode: gpt-live` |
| [`fishaudio/fish-audio-hermes`](https://github.com/fishaudio/fish-audio-hermes) | Official Fish Audio plugin for Hermes | `StreamingTTSProvider` PCM streaming, `transcribe-stream-1` live STT, latency benchmarks, retry/error handling |
| [`nickvasilescu/hermes-desktop-os1`](https://github.com/nickvasilescu/hermes-desktop-os1) | **OS1 by Element Software** — *Her*-styled macOS app for Hermes | Warm coral-on-cream design language, thin typography, calm motion, minimal single-toggle voice UX |
| [`nickvasilescu/hermes-voice-ios`](https://github.com/nickvasilescu/hermes-voice-ios) | iPhone-first WebRTC voice UI + TypeScript bridge for Hermes | **Gold-standard dual-brain blueprint**: 5 narrow voice tools (`delegate`, `status`, `follow-up`, `cancel`, `approve`), optimistic activity rail, pause/resume voice without killing background Hermes runs, 1 Hermes thread per independent task |
| [`kortexa-ai/hermes-realtime`](https://github.com/kortexa-ai/hermes-realtime) | Native Hermes gateway plugin (Direct WebRTC + LiveKit Conference) | `BasePlatformAdapter` + `StreamingTTSConsumer` integration, bundled Silero VAD v6.2, `asr_prefetch_silence`, `tts_trim_leading_silence`, OpenAI `oai-events` contract, `hermes.input_audio.state` mute extension |
| [`rahulsethi/hermes-voice`](https://github.com/rahulsethi/hermes-voice) | Self-hosted LiveKit worker backed by Hermes OpenAI bridge | Clean Python template for LiveKit Agents → Hermes `/v1/chat/completions`, plus fail-closed `private` vs `public` privacy lanes |
| [`NousResearch/hermes-agent#27040`](https://github.com/NousResearch/hermes-agent/pull/27040) (`tmylk/hermes-plugin-voice-pipecat`) | Proposed generic `voice_server` WebSocket gateway platform + Pipecat runtime | Bidirectional WebSocket protocol for streaming assistant deltas, barge-in playback reconciliation, and room events |
| `jesuscopado/samantha-os1-openai-realtime` | Classic Samantha OS1 Realtime assistant | Prompting/persona inspiration for spoken warmth and conversational cadence |

---

## 3. Critical Gotchas & Engineering Checklist

1. **Disable `tool_progress_events` for strict OpenAI SSE clients**:
   - Hermes `/v1/chat/completions` emits custom `event: hermes.tool.progress` SSE frames by default. Set `gateway.platforms.api_server.tool_progress_events: false` for stock LiveKit/Pipecat/Fish Custom LLM clients (or parse them explicitly to animate the OS1 UI).
2. **Always send `X-Hermes-Session-Key` alongside `X-Hermes-Session-Id`**:
   - Keeps Honcho's dialectic user model continuous across individual call sessions.
   - Do not try to pass a CLI/Desktop session ID to the API Server (`409 permission_denied`); use `/api/ws` if voice and desktop text must share the same live transcript.
3. **Preserve Fish `[emotion]` tags without leaking them to UI text**:
   - In Arch 2/3, stream LLM output directly to `wss://api.fish.audio/v1/tts/live` with a lightweight voice sanitizer that strips markdown/code blocks/URLs while preserving `[bracket]` delivery cues for Fish, and strip `[bracket]` cues from the visual caption stream.
   - In Arch 1 (`fish-audio-hermes` via Hermes core), note `upstream #133131` where core's `tts_text_normalize` can alter Drama 3 closing tags and `<|speaker:N|>` markup.
4. **Kill reasoning tokens on spoken turns**:
   - Always configure `auxiliary.voice_chat.reasoning_effort: none` (native voice) or pass `model_options: {"reasoning": {"enabled": false}}` on API Server voice requests to avoid multi-second silence before first audio.
5. **Shim Fish Custom LLM extra keys (Arch 4)**:
   - Fish sends `session_id`, `user_id`, and `fishaudio_extra_body` as top-level JSON fields on `/chat/completions`. Translate them into `X-Hermes-Session-Id` / `X-Hermes-Session-Key` and strip them before forwarding.
6. **Handle `: keepalive` SSE comments**:
   - Hermes sends `: keepalive` every 10s during long tool calls; any custom SSE parser must ignore lines starting with `:`.
7. **Watch Fish concurrency & plugin isolation**:
   - Concurrency is capped at 5 (<$100 lifetime top-up), 15 (≥$100), or 50 (≥$1,000).
   - Avoid `plugins.isolation: host` if relying on `fish-audio-hermes` streaming PCM (falls back to whole-file synthesis).
8. **Respect `fish-audio-hermes` install path on Hermes 0.23.0**:
   - Install via `hermes plugins install 100yenadmin/fish-audio-hermes --enable --yes-deps` rather than the catalog name `fish-audio` until `NousResearch/hermes-agent#151856` is resolved.
