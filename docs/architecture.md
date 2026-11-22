# OS1 / Samantha — System Architecture

*Version 2 · 2026-11-22 · merges the Claude and Gemini planning proposals*

This is the working architecture for `os1-her`. It sits on top of the research in [`docs/research/`](research/), [`os1-generative-ui-architecture.md`](os1-generative-ui-architecture.md), [`jev-reference.md`](jev-reference.md) and [`composio-architecture.md`](composio-architecture.md). Where this doc and those disagree, this doc wins (see §15).

**Design source:** OS1 — Her design tokens: coral `#CD4F33`, studio cream `#EDD7BD`, paper `#FFFDF9`, ink `#38281E`; DM Sans, DM Mono, Mrs Saint Delafield.

---

## 1. Principles

1. **Three loops at three speeds.** *Presence* (100–400 ms: listening, speaking, what the screen shows), *Work* (seconds to minutes: tools, connectors, computer use), *Ambient* (async: triggers, cron, memory). Presence never waits on Work.
2. **One brain.** Hermes is the only agent that acts. The voice front end is a thin, fast shell over it.
3. **The screen only shows what you're talking about.** Calm horizon by default. Surfaces appear when they help and leave when the conversation moves on.
4. **Voice-native, no buttons.** Every action on screen is a phrase you can say (a "say" chip). Everything visible can be named ("open number twelve", "the 1:45", "forget the beach").
5. **Confirmation scales with risk.** Low stakes: she just does it ("undo that" reverses). Things other people see: she asks once. Money and forgetting: read back, two-word answer, voice check.

---

## 2. System Diagram

```
 OS1 client (desktop app + Pocket; Paper design)
  ├─ mic / speaker ────────────── LiveKit room (WebRTC audio) ──────────┐
  ├─ renders UI state ◀── WS /os1/events ──┐                            │
  ├─ sends taps/pills ─── POST /os1/actions┤                            │
  └─ Cua Driver (embedded, bounded) ───────┼── outbound tunnel ──┐      │
                                           │                     │      │
 ┌─ OS1 ORCHESTRATOR (state bus) ──────────┴───────┐             │      │
 │  UI state patches · speakable-pill resolver     │◀─ transcript/voice state ─┐
 │  Jev director tick + hysteresis choreographer   │             │      │     │
 │  PendingAction bus + 60 s undo queue            │             │      │     │
 │  Composio webhook receiver + attention triage   │             │      │     │
 │  Memory ledger API · Orgo VNC token minting     │             │      │     │
 └──────────────┬──────────────────────────────────┘             │      ▼     │
                │ /v1/runs SSE (observes)          ┌─ VOICE WORKER (LiveKit Agents) ─┐
                │                                  │  VAD · semantic EOT · barge-in  │
                │                                  │  STT (Fish transcribe-stream-1) │
                │                                  │  Shell LLM (fast, no reasoning) │
                │                                  │   5 tools → Hermes /v1/runs     │
                │                                  │  Fish TTS WS (Voice I / II)     │
                │                                  └───────────────┬─────────────────┘
                ▼                                                  │ /v1/runs · /steer · /approval
 ┌─ ORGO VM "Samantha's computer" (always on) ─────────────────────▼──────────────┐
 │  HERMES — profile `samantha`                                                    │
 │   SOUL.md · MEMORY.md/USER.md · skills · cron/heartbeat · delegate_tool         │
 │   native: computer_use + browser + terminal  → this VM's own desktop            │
 │   plugins: os1_ui · os1_memory · os1_composio · fish-audio (voice notes)        │
 │   MCP: user_computer  ◀──────────────────────── tunnel from the client ─────────┘
 └─────────────────────────────────────────────────────────────────────────────────┘
        ▲ webhooks
  Composio triggers ──▶ orchestrator triage ──▶ speak now / at next greeting / silently log
```

---

## 3. Ownership

| Component | Owns | Never owns |
|---|---|---|
| **Client** | Rendering surfaces, audio I/O, embedded Cua Driver + kill switch, noVNC view | Keys, decisions, tool calls |
| **Voice worker** | Turn-taking, barge-in, STT, shell LLM, Fish TTS, voice parameters | Real tools, memory writes, UI decisions |
| **Orchestrator** | All UI state, Jev ticks, pill resolution, approvals bus, undo, triggers, memory ledger, VNC tokens | Agent reasoning |
| **Hermes** | All actions: tools, Composio, both computers, subagents, cron, writing memory text | Audio, UI timing |
| **Jev** | Fast judgments: which surface, when, mood, attention urgency, "worth remembering" | Prose, side effects, storage |

The orchestrator can start as one FastAPI (or Node) process. It is separate from the voice worker so the UI keeps working with voice off and so non-voice sources (triggers, Cua, Orgo, Hermes runs) have one place to land.

---

## 4. Realtime Voice + Fish Audio

**Worker:** Python LiveKit Agents (`livekit-agents[fishaudio]`). Silero VAD + LiveKit turn detector for semantic end-of-turn; playback stops instantly on barge-in. When interrupted, the next shell turn is told what was cut off.

**STT:** Fish `transcribe-stream-1` (fallback: Deepgram). Partials stream to the orchestrator for Jev and captions.

**Shell LLM:** fast, non-reasoning model, seeded with `SOUL.md`, a small memory shortlist (§9), the list of visible say-chips, and active run summaries. It has **no tools**: Jev routes each turn (§5b) and the worker performs these Hermes calls itself:

| Tool | Hermes call |
|---|---|
| `delegate(task, label)` | `POST /v1/runs` (stable `session_id` + `X-Hermes-Session-Key`) |
| `status(run_id?)` | `GET /v1/runs/{id}` |
| `steer(run_id, instruction)` | `POST /v1/runs/{id}/steer` |
| `cancel(run_id \| "all")` | `POST /v1/runs/{id}/stop` |
| `respond_approval(request_id, choice)` | `POST /v1/runs/{id}/approval` via the orchestrator's PendingAction bus |

Run events (`message.interim`, `tool.started`, `approval.request`, `run.completed`) are injected as quiet context so she talks about progress naturally ("Found one — the 10:30 or the 1:45?").

**Fish TTS:** direct WebSocket (`wss://api.fish.audio/v1/tts/live`), PCM 24 kHz, `latency: balanced`. Not through Hermes's TTS path, because Hermes's normalizer mangles Drama 3 tags (upstream #133131). `[bracket]` cues go to Fish and are stripped from captions. The `fish-audio-hermes` plugin stays installed only for CLI testing and `fish_speak` voice notes from cron.

**Two voices (Paper 14):** a voice registry in config:

```yaml
voices:
  voice_1_warm:   { reference_id: "<id>", model: drama-3,  speed: 0.96, temperature: 0.72 }
  voice_2_bright: { reference_id: "<id>", model: s2.1-pro, speed: 1.05, temperature: 0.65 }
```

Spoken tweaks ("a little warmer", "slow down") adjust speed/temperature plus a short style line in the shell prompt, applied on the next turn.

**Model choice (decided): `drama-3`** for both voices, over the worker's direct WebSocket. Cost after the Nov 30, 2026 promo: $50 / 1M UTF-8 bytes ≈ $4 per hour of continuous speech from her. `s2.1-pro` stays a config-only fallback. Watch Fish concurrency (5 / 15 / 50 by lifetime top-up).

**Privacy:** "stop listening" cuts the mic stream at the client, not just in software, until the wake word.

---

## 4b. Option: Fish Live 3 as Samantha's Voice (tested 2026-11-22)

**Verified:** a Fish Agent with `voice.engine: "live3"` and `llm.custom` calls our own OpenAI-compatible endpoint for every reply and speaks our exact words. Live 3 owns listening, turn-taking, backchannels ("mm-hmm") and voice; our endpoint owns the words. Test: greeting + one text turn both hit the probe endpoint (`model: "samantha"`, `session_id`, full message history, built-in `_end_call` tool); about 0.5 s from message to speech through a tunnel.

| | Our cascade (current) | Fish Live 3 + our brain |
|---|---|---|
| Turn-taking | Our LiveKit worker (VAD + turn detector) | Live 3 full duplex: backchannels, natural interruptions |
| Voice | Exact Drama 3 clone + `[bracket]` cues | Close recreation of the clone; no bracket cues (expressive is Drama 3 / S2.1 only) |
| Languages | 52 | English only (falls back to TTS otherwise) |
| Who writes words | Worker → model | Fish → **our** `/v1/chat/completions` (public HTTPS, 800 ms TTFT target, 10 s cap, 1 retry) |
| Push into a live call | Worker speaks any time | No server push: the client relays updates as `user.message` |
| Cost | Fish TTS per byte | $0.07/min ($0.035 promo to 2026-12-31) + our model |

**How it would fit:**
- **Orchestrator** creates the Fish session server-side (`POST /v1/agent/sessions`) and returns `livekit_url` + `token`. The desktop app already speaks LiveKit, and Fish uses the same `lk.transcription` streams and `lk.agent.state` attribute, so the UI barely changes. Say-chips become `user.message` on the `client-event` topic.
- **Brain endpoint** (new, public): Jev route → fast model called directly with a lean prompt (chat), or start a Hermes run on Opus + one-line ack (work). Hermes stays the worker, never in the per-turn path (its 18.5k-token prompt can't meet 800 ms).
- **Run results:** orchestrator → desktop app → `user.message` carrying a `<background-update>` marker → the brain narrates it.
- **Generative UI:** `show_surface` / `present_canvas` declared as Fish **client tools** (`expects_response: false`), executed in Electron.
- **Onboarding** stays on our own LiveKit worker (exact operator voice; the Q3 cut-off needs live partial transcripts on the server). At `initiating` the app leaves that room and joins the Fish Live 3 session; the waking screen covers the switch.
- **Blocker to clear:** the brain endpoint must be public HTTPS. The Orgo public URL is gated by an Orgo sign-in page; use a named Cloudflare tunnel or lift the gate.

---

## 4c. The Brain and the Two Voice Engines (built 2026-11-22)

Hermes is no longer in the per-turn path. Every spoken turn is answered by **the brain** (`services/voice/os1_voice/brain.py`): one streaming Claude call (`OS1_FAST_MODEL`, default `claude-sonnet-5-5`, thinking `between_tools`, effort `low`, server-side refusal fallback) with SOUL.md + voice rules as a frozen, cached system prompt and the per-turn routing note as a mid-conversation system message. Measured: first token ~0.56–0.7 s with a warm cache (vs ~12 s through Hermes). Hermes runs the work on Opus and receives each conversation's transcript at the end for long-term memory.

Turn decisions live in `turns.py` (`TurnEngine` + `WorkManager`), shared by both engines. `OS1_VOICE_ENGINE` picks the engine:

| | `drama3` | `live3` |
|---|---|---|
| Runs in | `os1_voice.worker` (LiveKit Agents) | `os1_voice.brain_server` (Fish Live 3 custom LLM, public HTTPS) |
| Voice | Exact Drama 3 clone, bracket cues | Live 3 recreation, full duplex + backchannels |
| UI state | LiveKit participant attributes | app polls the brain server: `GET /os1/sessions/{id}/poll` (1 s; Cloudflare quick tunnels hold long-lived SSE bodies, so the SSE endpoint is for direct connections only) |
| Run results | worker speaks them | app relays them as `user.message` |
| Onboarding | worker (Operator → Samantha in one room) | worker, then `os1.handoff=live3` → app joins the Fish session |

**Deployed on Orgo VM (2026-11-22):** supervisor programs `os1-brain` (:8788) plus Cloudflare quick tunnels `os1-tunnel-orchestrator` / `os1-tunnel-brain`; `scripts/deploy_orgo.py` records the URLs and re-points the Fish agent when the brain URL changes. Both engines verified end to end there, including a background run on Opus narrated back. Quick-tunnel URLs change when a tunnel restarts; a named Cloudflare tunnel (or lifting the Orgo public-URL sign-in gate) makes them permanent.

Setup for `live3`: run the brain server behind public HTTPS, then `python3 scripts/fish_live3_agent.py https://<brain-url>` (creates/updates and publishes the Fish agent, writes `FISH_AGENT_ID`).

---

## 5. Speakable Pills (voice-native UI)

Every interactive element in every surface carries a `speakablePhrase` (and optional aliases). The orchestrator keeps the set of currently visible phrases.

On each final STT utterance:
1. **Orchestrator matches first** (normalized exact + fuzzy match against visible phrases). A confident match dispatches the action directly, with no LLM call: lowest latency, fully deterministic.
2. Otherwise the utterance goes to the shell LLM, which also sees the visible phrases so it can resolve near-misses ("the later one").

Taps on the same pills go through `POST /os1/actions` and take the identical path.

---

## 5b. Jev in the Voice Loop

Jev (~100 ms, typed answers, never acts) handles fast decisions so no LLM round trip is spent on them. Every call has a hard budget and a fallback; the voice never waits on Jev.

| Decision | Where | Fallback |
|---|---|---|
| **Turn routing**: `chat` / `work` / `control` / `chip` / `ignore`, plus run target, control action (status, change, stop, approve, deny) and warmth, in one speculative fan-out | `services/voice/os1_voice/router.py` | `chat` |
| **Addressed to her?** (always-on mic: ignore speech to someone else in the room) | router | treat as addressed |
| **Onboarding**: Q1 hesitance, Q2 voice choice, Q3 "answer turned personal" cut-off | `onboarding.py` | filler/keyword heuristics, 12 s timer |
| Tone hint from `warmth` → softer delivery cues for Drama 3 | `samantha.py` | none |
| *Later:* surface timing + mood (§6), attention triage (§10), memory gating (§9), email keeper scoring (day one), "worth interrupting now?" for run results, approval stakes cross-check (§8), Opus vs. faster model for a delegated task | orchestrator / worker | — |

Routing replaces the voice shell's 5 tools: the fast model only talks. `work` starts a Hermes run on Opus (`samantha-work` route) and she acknowledges in one line; results return as a `<background-update>` turn she narrates. Exact say-chip matches skip Jev entirely.

## 5c. First Run (Operator → Samantha)

Phases (published as `os1.phase`): `preflight → operator_welcome → operator_q1 (→ operator_q1_hesitance) → operator_q2 → operator_q3 → initiating → samantha_first_meeting → active`.

- The Operator is a deterministic LiveKit agent with its own Fish voice (`FISH_OPERATOR_VOICE_ID`); it never calls an LLM. Lines live in `services/voice/os1_voice/onboarding_script.yaml` (original OS1 wording following the film's beats).
- Q2 picks Samantha's Drama 3 voice. The handoff is a LiveKit agent swap, so the room stays up while the TTS voice changes.
- During `initiating` (Paper 03, ~6 s): the profile is marked onboarded, and the interview dossier is written to Hermes memory via a background run.
- Samantha wakes with "Hello, I'm here." and a first-meeting overlay on top of SOUL.md; when she names herself, the naming surface (Paper 05) appears.
- Dev: Develop → Replay Onboarding resets the profile (`POST /os1/dev/reset-onboarding`).

**Day one (slices 3–4):** permission gate, bulk email audit with Jev keeper scoring and the inbox surfaces (07/08), contact sorting and VIP seeding, Drive/local folder plan with reversible moves only. Bulk delete goes to Gmail Trash behind one read-back confirmation plus the undo queue.

---

## 6. Generative UI

Three layers.

**Layer 1 — Timing and mood (Jev, in the orchestrator).** One batched `systemOne` call per debounced STT chunk (~500 ms, `AbortSignal.timeout(1500)`, stale ticks aborted, failures hold current UI). Questions: `needs_surface` (Noul) + `surface` (Choice), `warmth` / `pace` / `overwhelm` (Score), `requests_irreversible_action` (Noul), `worth_remembering` (Noul) + `memory_kind` (Choice), and camera `visual_target_present` + `visual_target_box` in Pocket camera mode. Hysteresis in code: show at `needs_surface > 0.72` and choice prob `> 0.70`; dismiss after `< 0.35` for 2 ticks. High `overwhelm` collapses a surface to its two biggest options. Pin `jev-1.14.0`. Support `live | record | replay | mock` transports from day one.

**Layer 2 — Hand-built surfaces (from Paper).** Purpose-built components with live props from Hermes / Composio / Cua / Orgo:

| Surface key | Paper screen | Fed by |
|---|---|---|
| `home` | 06 Desktop — Home (horizon + floating shapes) | Active runs → one shape each |
| `voice_flow` | ★ Voice flow | Shell + runs + PendingAction |
| `inbox_cascade` | Spatial inbox (numbered tiles) | Composio Gmail via Hermes |
| `computer_use_yours` | 09 Computer use — on your machine | Cua activity events |
| `her_computer` | 10 Her own computer — cloud | Orgo VM + noVNC + "while you were away" log |
| `swarm` | 11 Swarm — many of her | `/v1/runs` + subagent events |
| `made_just_now` | 12 Generative UI | Layer 3 cards |
| `connectors` | 13 Connectors | Connector policy table |
| `voice_picker` | 14 Voice | Voice registry |
| `memory` | 15 Memory | Memory ledger |
| `camera` | P3 Show me — camera | Jev Box + vision model |
| `modal_*` | S2 Modals (asking, interrupting, forgetting) | PendingAction + triage |

**Layer 3 — "Made just now" cards (Paper 12).** A small, strict card catalog (`ComparisonCard`, `ChoicePairCard`, `QuickDecisionCard`, `AudioSketchCard`, `ReadbackConfirmCard`, `TimelineCard`, `DraftPreviewCard`), each with a schema and required `speakablePhrase` on every control. Hermes emits a card spec directly through the `os1_ui` plugin tool `present_canvas(cards[])`. The plugin validates it against the catalog schema; the orchestrator reads it from the run's `tool.completed` event and holds it as a *pending surface* until Jev / an explicit request shows it. `@json-render/core` is an optional later optimization (experimental, needs Vercel AI Gateway), not a dependency.

---

## 7. Tool Calling

| Tier | Who | Tools |
|---|---|---|
| 0 | Orchestrator | Pill resolution (no LLM) |
| 1 | Voice shell | The 5 delegation tools only |
| 2 | Hermes | Native tools, `computer_use`, `browser`, `terminal`, `delegate_tool`, cron, `os1_ui`, `os1_memory`, `os1_composio`, `user_computer` MCP, `fish_audio` |

**Routing ladder** (in `SOUL.md` or a Hermes skill): Composio API → browser on her computer → her desktop → **your computer (last resort, only for things that exist only there).**

---

## 8. Approvals & Undo

Hermes, Composio, Cua and Jev can each want a confirmation. All of them become one `PendingAction` on the orchestrator bus. **Each action is gated exactly once:** Composio write tools and Cua mutations are gated by Hermes approvals (Composio `requireApproval` stays off, so the user is never asked twice). Jev's `requests_irreversible_action` is only a cross-check that forces the confirm surface.

```ts
PendingAction {
  id, source: "hermes" | "cua" | "triage" | "memory",
  runId?, requestId?, title, summaryLines[],
  stakes: "low" | "shared" | "money" | "forget" | "computer",
  options: { phrase, choice }[],          // speakable
  allowRememberRule?: boolean             // "don't ask me for Erin again"
}
```

| Stakes | Behavior (from Paper) |
|---|---|
| `low` | Just do it; push to 60 s **undo queue** ("Booked · 10:30 · *undo that*") |
| `shared` (others will see) | Ask once |
| `money`, `forget` | Read back, two-word answer ("Book it", "Yes, forget it"), voice check |
| `computer` | Per-action approval on your machine; none on hers |

---

## 9. Memory

Two stores of record, one optional model:

| Store | Role | Delete ("Yes, forget it") |
|---|---|---|
| **OS1 memory ledger** (Postgres/SQLite, orchestrator) | What the user sees and controls. Dated moments in 5 categories: People, Places, Things you love, Things that hurt, Promises | Hard delete by id; cascade below |
| **Hermes memory** (`MEMORY.md`, `USER.md`, session FTS) | Working facts and transcripts the agent uses | `os1_memory.forget` purges matching entries and redacts session records |
| **Honcho** (optional) | Dialectic user model across sessions | **Gate:** enable only if its API can delete messages *and* derived conclusions. Otherwise leave off; a model you can't forget breaks screen 15's promise |

**Writing:** Jev's `worth_remembering` (≥ 0.7) + `memory_kind` decide *whether* and *which category*; Hermes writes the 1–2 sentence text through `os1_memory.remember` (Jev cannot write prose). The UI shows the "remembered" shimmer.

**Reading:** before each shell turn and Jev tick, the orchestrator sends a small pre-filtered shortlist (~300–500 tokens).

**One relationship:** every shell turn is mirrored into the Hermes session so Hermes memory sees the whole conversation, not just delegated tasks.

---

## 10. Connectors (Composio)

**Integration:** an `os1_composio` Hermes plugin wrapping the Composio Python SDK (one Tool Router session per user, sandbox on for bulk jobs). The plugin path is needed because Paper 13's per-app policy changes at runtime. The hosted MCP endpoint is fine for the first day of prototyping only.

**Connector policy table** (orchestrator, per user), matching Paper 13:

| Policy | Effect in the plugin |
|---|---|
| `full_access` | All tools allowed |
| `ask_before_write` | Read tools free; write tools → Hermes approval (`shared` stakes) |
| `read_only` | Write tools not exposed at all |
| `ask_every_time` | Every call → approval (`money` stakes for payments) |

Spoken changes ("stop reading my messages", "always ask before paying") update the table; "connect my bank" opens a white-labeled Connect Link. Show policy as a spoken status ("Mail: asks before sending"), not toggles.

**Firewall:** Composio Firewall on, to filter prompt injection from email/doc content.

**Triggers:** one project webhook → orchestrator → Jev attention tick (`urgency` Score + is the user mid-conversation / focused):
- **Low** (newsletters, receipts) → background Hermes run to log/archive.
- **Medium** (schedule change) → queue for the next natural greeting.
- **High** (family, VIP, meeting in 10 min) → "Sorry — can I interrupt?" modal with "Go ahead" / "In ten".

---

## 11. Computer Use — Two Computers

### Her computer (Orgo)
- Hermes runs **on** her primary Orgo VM. Its native `computer_use` + `browser` drive that VM's desktop with no extra wiring. Cron, heartbeats and triggers keep running while your laptop is closed.
- She works there autonomously (research, files, long jobs, overnight "while you were away" work). Extra Orgo VMs can be cloned for parallel or untrusted work via the Orgo API.
- **"Show me" (Paper 10):** the orchestrator mints a VNC password server-side and the client mounts a noVNC view, read-only by default. The VNC password is root on that VM: mint only for the owner, never cache or ship it to the client bundle.
- Keep your personal secrets off her desktop session; a prompt-injected page could read anything there.

### Your computer (Cua Driver)
- The OS1 desktop app embeds `cua-driver` via `EmbeddedCuaDriverHost`, so macOS permissions belong to OS1.
- `bounded` mode with a v3 capability manifest (allowlisted apps/folders, `desktop.display: false`, no Terminal / Keychain / System Settings / password managers). `CUA_DRIVER_RS_TELEMETRY_ENABLED=0`.
- The app opens an **outbound** authenticated tunnel; Hermes sees it as a separately named `user_computer` MCP server. The driver's HTTP port is never exposed.
- **Paper 09:** activity events fill "What I'm doing"; "let me drive" (voice or hotkey) runs `cua-driver revoke --all`.

---

## 12. Deployment Topology

- **Orgo VM (always on):** Hermes gateway (`samantha`), optionally the orchestrator and voice worker too.
- **LiveKit:** LiveKit Cloud to start.
- **Client:** desktop app on your machine (holds Cua + tunnel) and Pocket on the phone.
- **Secrets** (`TYPESAFE_API_KEY`, `FISH_API_KEY`, `COMPOSIO_API_KEY`, `ORGO_API_KEY`, `API_SERVER_KEY`) live server-side only.

Hermes goes on Orgo from day one: running it locally first would let `computer_use` drive your real machine without the bounded manifest, and sessions/memory would need migrating later.

---

## 13. Build Order (vertical slices)

1. **Voice + presence core.** `samantha` profile on Orgo; LiveKit worker with Fish TTS (both voices), STT, turn detection, LLM = Hermes chat completions for now; client shell with Paper tokens, `home` horizon, voice line, say chips.
2. **Dual brain + state bus.** Orchestrator; 5-tool shell over `/v1/runs`; swarm shapes from run events; PendingAction + undo; pill resolver.
3. **Generative UI + memory.** Jev director (mock → live); `made_just_now` via `present_canvas`; `memory` surface + ledger + forget cascade.
4. **Connectors + proactivity.** `os1_composio` plugin with policy table; Gmail / Calendar / Drive / Spotify; triggers → triage → interrupt modal; inbox cascade.
5. **Two computers.** Her computer surface + noVNC; then Cua embedded in the desktop app + tunnel + "let me drive".

---

## 14. Open Decisions & Things to Verify

**Decided**
- **Client: fresh Electron + React + TypeScript app.** UI lives in its own package (`packages/ui`) so the shell could later move to Tauri without touching surfaces. LiveKit JS SDK for audio, WebSocket for `/os1/events`, noVNC for "Show me". Cua embeds via the documented `@trycua/cua-driver` `EmbeddedCuaDriverHost` in the Electron main process (binary outside ASAR). iPhone Pocket app comes later (small SwiftUI or React Native app).
- **Backend: Python** for the voice worker, orchestrator and Hermes plugins.
- **Voice: Fish `drama-3`.**
- **Models: hosted only, no local model.** Hermes main brain: Claude Opus 5.5 (`claude-opus-5-5`). Voice shell: whichever of Gemini Neon 4 / a fast Claude model has the lowest time-to-first-token with reasoning off (measure in slice 1). Thinking Machines Inkling was evaluated and dropped.
- **Repo layout:** `apps/desktop` · `packages/ui` · `services/voice` · `services/orchestrator` · `hermes/` (profile + plugins).

**Open**
- **Single user (you) or multi-user product?** Changes Composio user ids, one Orgo VM per user, auth.

**Verify before relying on**
- `tool.completed` run events include tool arguments (needed for `present_canvas`).
- How to mirror shell turns into a Hermes session (`/api/sessions/{id}/messages` append?).
- Honcho deletion of messages and derived conclusions.
- Voice check for money/forget (speaker verification) — no provider chosen yet.
- Orgo details from the Gemini proposal: Hermes VM template, VNC endpoint/password API, Composio `orgo` toolkit.

**Design gaps (from the Paper thread)**
- Eyes-free state: what the screen does when you're across the room.
- Connectors as spoken status instead of switches.

---

## 15. Supersedes

- [`composio-architecture.md`](composio-architecture.md): no Composio tools on the voice model; no two-tier sessions; runtime is Hermes + LiveKit/Fish, not OpenAI Realtime / Gemini Live; plugin over hosted MCP; Hermes approvals instead of `requireApproval`.
- [`os1-generative-ui-architecture.md`](os1-generative-ui-architecture.md): surface catalog replaced by §6 (from Paper); Jev memory feeds the ledger rather than being its own store; `json-render` optional.
- [`research/cua-driver-mcp-computer-use.md`](research/cua-driver-mcp-computer-use.md): with Hermes on Orgo, its native `computer_use` drives *her* VM; your machine is always reached via Pattern D (embedded host + outbound tunnel).
- [`research/README.md`](research/README.md) staged plan: replaced by §13.
