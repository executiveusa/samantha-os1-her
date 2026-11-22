# Fish Audio — Realtime Voice, Custom Models & Hermes Integration Reference

Official documentation: [`docs.fish.audio`](https://docs.fish.audio)  
Official Hermes plugin: [`fishaudio/fish-audio-hermes`](https://github.com/fishaudio/fish-audio-hermes) ([Hermes Marketplace](https://hermes-agent.nousresearch.com/marketplace/fish-audio))

---

## 1. Speech Models & Expressive Direction

References: [Text to Speech](https://docs.fish.audio/features/text-to-speech), [Drama 3](https://docs.fish.audio/features/text-to-speech/drama-3), [Emotion Control](https://docs.fish.audio/developer-guide/core-features/emotions), [Pricing & Rate Limits](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits)

| Model | `model` Header / Config | Pricing | Expressive Control | Notes for Samantha / OS1 |
|---|---|---|---|---|
| **S2.1 Pro** | `s2.1-pro` | **$15.00 / 1M UTF-8 bytes** (~12 hrs speech) | `[bracket]` cues with free-form natural language (`[warm and happy]`, `[whispering]`, `[laughing]`) | **Recommended production default** — best latency/cost balance, full `reference_id` fidelity, production TTFA & DPA guarantees |
| **Drama 3** | `drama-3` | **$50.00 / 1M UTF-8 bytes** *(launch promo $10.00/M through Nov 30, 2026)* | Plain-language voice direction (`[softly, holding back a laugh]`), inline sounds & pauses (`[small laugh]`, `[shaky breath]`), word-level paired tags | **Highest emotional realism for *Her*** — TTFA comparable to S2.1 Pro |
| **S2.1 Pro Free** | `s2.1-pro-free` | **$0.00** *(through Nov 30, 2026)* | Same as `s2.1-pro` | Prototyping/dev only; no TTFA/DPA SLA; Fish may use requests for model improvement |
| **Live 3** | *(Agents platform only: `voice.engine: "live3"`)* | **$0.07/min** *(promo $0.035/min through Dec 31, 2026)* | Full-duplex listening, natural backchannels (`"mm-hmm"`), interruption & correction handling | English-only; recreates custom `voice_id` from a sample (close, not exact match to S2.1 Pro / Drama 3); `live3_prompt` currently targets `P2`, `DT`, `AIR` |
| **Transcribe 1 Pro** | `transcribe-1-pro` | Per audio duration | Batch STT (1.8% EN WER in Fish benchmarks) | Replaces deprecated `transcribe-1` |
| **Transcribe Stream 1** | `transcribe-stream-1` | **$0.36/hr** of open WS session (billed per second) | Word-by-word realtime streaming STT (`wss://api.fish.audio/v1/asr/realtime`) | Preview; used for live dictation |

> **Important Deprecation Dates**
> - **Nov 30, 2026**: `s2.1-pro-free` free tier and `drama-3` $10/M launch promo end (Dec 1, 00:00 PT / 08:00 UTC).
> - **Dec 31, 2026**: `s1` (legacy `(parenthesis)` syntax) and `transcribe-1` retire and auto-route to `s2.1-pro` and `transcribe-1-pro`.

### Expressive Syntax Examples (S2.1 Pro & Drama 3)
- **Emotion / tone cues** (zero extra latency):
  ```text
  [warm and curious] Wait — did you actually write that whole letter last night?
  [softly, amused] Okay, [small laugh] I have to hear how that ended.
  ```
- **Placement rules**: Sentence-level emotion cues work best at sentence start; tone controls and sounds (`[sigh]`, `[laughing]`, `[whispering]`) work anywhere.
- **Custom voice model**: Pass your saved/cloned model ID via `reference_id` (or `voice.voice_id` on Fish Agents).

### Rate & Concurrency Limits
- Concurrency scales by lifetime API credit top-ups:
  - **5 concurrent requests** (< $100 lifetime)
  - **15 concurrent requests** (≥ $100 lifetime)
  - **50 concurrent requests** (≥ $1,000 lifetime)
- Remember that Hermes's streaming speaker prefetches up to **3 sentences concurrently** per active turn.

---

## 2. Direct Realtime WebSocket TTS (`wss://api.fish.audio/v1/tts/live`)

Reference: [WebSocket TTS Streaming](https://docs.fish.audio/api-reference/endpoint/websocket/tts-live), [Real-time Voice Streaming](https://docs.fish.audio/developer-guide/best-practices/real-time-streaming)

- **Endpoint**: `wss://api.fish.audio/v1/tts/live`
- **Headers**:
  - `Authorization: Bearer <FISH_API_KEY>`
  - `model: s2.1-pro` (or `drama-3`)
- **Wire Serialization**: Binary **MessagePack** (`application/msgpack`).
- **Event Sequence**:
  1. **StartEvent** (once on connect; `request.text` empty):
     ```json
     {
       "event": "start",
       "request": {
         "text": "",
         "reference_id": "YOUR_FISH_MODEL_ID",
         "format": "pcm",
         "sample_rate": 24000,
         "latency": "balanced",
         "temperature": 0.7,
         "top_p": 0.7
       }
     }
     ```
  2. **TextEvent** (stream LLM text chunks as they arrive):
     ```json
     {"event": "text", "text": "Hey, I was just thinking about that."}
     ```
  3. **FlushEvent** (optional — force synthesis of buffered text):
     ```json
     {"event": "flush"}
     ```
  4. **CloseEvent**:
     ```json
     {"event": "stop"}
     ```
- **Latency**: `latency: "balanced"` targets ~240–300 ms TTFA (`"normal"` ~500 ms).
- **Python SDK**:
  ```python
  from fishaudio import FishAudio

  client = FishAudio(api_key=os.environ["FISH_API_KEY"])
  audio_stream = client.tts.stream_websocket(
      text_chunk_generator(),
      reference_id="YOUR_FISH_MODEL_ID",
      latency="balanced",
  )
  ```

---

## 3. First-Party Realtime Framework Integrations

### LiveKit Agents (`livekit-agents[fishaudio]`)
Reference: [Fish Audio LiveKit Integration](https://docs.fish.audio/developer-guide/integrations/livekit)

```bash
pip install "livekit-agents[fishaudio]"
export FISH_API_KEY=your_api_key_here
```
```python
from livekit.plugins.fishaudio import TTS

tts = TTS(
    reference_id="YOUR_FISH_MODEL_ID",
    model="s2.1-pro",        # or "drama-3"
    output_format="pcm",
    sample_rate=24000,
    latency_mode="balanced", # ~300ms TTFA ("normal" ~500ms)
)
# Supports both tts.synthesize(...) and real-time WebSocket tts.stream()
```

### Pipecat (`pipecat-ai[fish]`)
Reference: [Fish Audio Pipecat Integration](https://docs.fish.audio/developer-guide/integrations/pipecat)

```bash
pip install "pipecat-ai[fish]"
export FISH_API_KEY=your_api_key_here
```
```python
from pipecat.services.fish import FishAudioTTSService

tts = FishAudioTTSService(
    api_key=os.getenv("FISH_API_KEY"),
    reference_id="YOUR_FISH_MODEL_ID",
    model_id="s2.1-pro",     # or "drama-3"
    output_format="pcm",
    params=FishAudioTTSService.InputParams(
        latency="balanced",
        prosody_speed=1.0,
        prosody_volume=0,
        normalize=True,
    ),
)
```

---

## 4. Official Hermes Agent Plugin (`fishaudio/fish-audio-hermes`)

Maintained by Electric Sheep with the Fish Audio team (Apache-2.0). Requires **Hermes `>= 0.21.6`** for streaming voice & live dictation.

### Installation
Use the repository path directly (workaround for Hermes 0.23.0 catalog pin issue `NousResearch/hermes-agent#151856`):
```bash
hermes -p samantha plugins install 100yenadmin/fish-audio-hermes --enable --yes-deps
hermes -p samantha fish login
hermes -p samantha fish doctor --no-synth
```

### Configuration (`config.yaml`)
```yaml
tts:
  provider: fish-audio
  fish-audio:
    voice: YOUR_FISH_MODEL_ID
    model: s2.1-pro
    latency: balanced          # normal | balanced | low
    temperature: 0.7
stt:
  provider: fish-audio
  streaming: true              # live dictation via transcribe-stream-1
  fish-audio:
    model: transcribe-1-pro
plugins:
  entries:
    fish-audio:
      settings:
        streaming: auto        # auto (24 kHz PCM sentence streaming) | "off"
        live_transcription: realtime
        allow_free_model: false
```

### Capabilities & Measured Performance
- **Streaming TTS**: Streams 24 kHz PCM from `POST /v1/tts` into CLI/TUI voice mode, Desktop speak-stream, and any gateway adapter implementing `StreamingTTSConsumer` (including `kortexa-ai/hermes-realtime`). Set `transport: ws` to test WebSocket transport.
- **Measured TTFA**: Fish HTTP p50 **243 ms** (238–356 ms), Desktop speak-stream **310 ms**, CLI voice mode **373–381 ms** (excluding LLM TTFT).
- **Agent Tools (`fish_audio` toolset)**: `fish_speak`, `fish_voices`, `fish_transcribe`, `fish_settings`, `fish_account`, `fish_pronunciations`.
- **Slash Commands**: `/fish setup`, `/fish status`, `/fish voices`, `/fish use`, `/fish model`, `/fish preview`, `/fish alias`, `/fish balance`.
- **Known Limitations**:
  - Under `plugins.isolation: host`, streaming falls back to whole-file synthesis.
  - Hermes core's text normalizer can alter `<|speaker:N|>` and Drama 3 closing tags on the standard `text_to_speech`/streaming path (`upstream #133131`).
  - Does **not** expose Fish Live 3 agents (tracked in [`fishaudio/fish-audio-hermes#102`](https://github.com/fishaudio/fish-audio-hermes/issues/102)).
  - Note: Fish also offers a remote OAuth MCP server (`https://api.fish.audio/mcp`), but MCP is for Story Studio / video / image generation — it cannot act as Hermes's speech provider.

---

## 5. Fish Audio Agents Platform (Managed WebRTC + Custom LLM)

References: [Core Concepts](https://docs.fish.audio/agents/concepts), [Voice & Language](https://docs.fish.audio/agents/build/voice-language), [Custom LLM](https://docs.fish.audio/agents/build/custom-llm), [Web SDK](https://docs.fish.audio/agents/deploy/web-sdk), [React SDK](https://docs.fish.audio/agents/deploy/react-sdk), [Webhooks](https://docs.fish.audio/agents/monitor/webhooks)

Fish hosts a LiveKit-backed WebRTC voice platform with ready-made React (`@fishaudio/agent-react`), Web (`@fishaudio/agent-client`), React Native, and telephony deployments.

### Engine Options
- **Full Duplex (`voice.engine: "live3"`)**: One speech model listens while speaking, backchannels naturally, handles interruptions/corrections. Accepts your custom `voice_id` (recreated from a sample — approximate match). English-only.
- **Cascade (`voice.engine: "fish_tts"`)**: Pairs Fish ASR + your LLM + `voice.tts_model: "drama-3"` or `"s2.1-pro"`. Exact fidelity to your cloned `voice_id`, 52 languages, speaking speed, expressive mode, and pronunciation dictionaries.

### Wiring Hermes via Custom LLM (`llm.custom`)
```bash
curl --request PATCH "https://api.fish.audio/v1/agent/agents/$AGENT_ID/config" \
  --header "Authorization: Bearer $FISH_API_KEY" \
  --header "Content-Type: application/json" \
  --data '{
    "llm": {
      "custom": {
        "base_url": "https://your-public-hermes-shim.example.com/v1",
        "model": "samantha",
        "api_key": "YOUR_SHIM_OR_HERMES_KEY"
      }
    }
  }'
```
- Requirements & behavior:
  - `base_url` must be publicly reachable **`https://`** (no localhost/private IPs).
  - Fish sends `POST {base_url}/chat/completions` with `stream: true`, plus extra top-level JSON fields: `session_id`, `user_id`, and `fishaudio_extra_body`.
  - A thin reverse-proxy shim should map `session_id` → `X-Hermes-Session-Id`, `user_id` → `X-Hermes-Session-Key`, strip unrecognized top-level keys, and ensure Hermes has `tool_progress_events: false`.
  - Post-call webhooks (`call.ended`, `call.analyzed`) can push call transcripts back into Hermes / Honcho if needed.
