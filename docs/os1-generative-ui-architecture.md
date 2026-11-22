# OS1 / Samantha — Realtime Generative UI Architecture with Jev

This document translates TypeSafe AI's **Jev** System One capabilities into a concrete architecture for building an **OS1 / Samantha** (*Her*-inspired) realtime generative interface.

See [`docs/jev-reference.md`](./jev-reference.md) for API specs, limits, primitives, and ecosystem notes.

---

## 1. Design Philosophy: Calm Presence Over Chatbot Chrome

What makes OS1 in *Her* feel fundamentally different from modern chat apps is **visual restraint paired with instantaneous contextual emergence**:

1. **Voice-first, presence-first:** Most of the time the screen should be an uncluttered, warm, breathing presence—not a wall of chat bubbles or widgets.
2. **Materialize only when helpful:** Visual artifacts (emails, letters, memories, music sketches, spatial camera highlights, confirmation cards) should glide in only when seeing or touching something genuinely helps—and dissolve cleanly when the conversation returns to pure dialogue.
3. **Sub-second choreography, zero flicker:** Waiting 3–4 seconds for an LLM to stream a UI JSON tree breaks the illusion of a living OS. UI transitions should begin *before* Samantha finishes her first spoken syllable, while deterministic code prevents jitter and accidental side effects.

---

## 2. Dual-System Architecture: System 1 (Jev) + System 2 (Voice LLM)

Split responsibilities cleanly between two specialized intelligence layers orchestrated by deterministic application code:

```text
Mic Audio / Text / Camera Frame / UI Events
        │
        ├──► Streaming STT + Acoustic/Telemetry Banding (in code)
        │           │
        │           ▼
        │    ┌─────────────────────────────────────────────────┐
        │    │  SYSTEM 1: OS1 Realtime Director (Jev 1.14.0)   │  ~100 ms
        │    │  Single speculative fan-out per tick:           │
        │    │   • needs_surface (Noul) + surface (Choice)     │
        │    │   • warmth, overwhelm, pace (Scores)            │
        │    │   • requests_irreversible_action (Noul)         │
        │    │   • worth_remembering (Noul) + memory_kind      │
        │    │   • visual_target_present (Noul) + Box (Vision) │
        │    └──────────────────────┬──────────────────────────┘
        │                           │
        │                           ▼
        │    ┌─────────────────────────────────────────────────┐
        │    │  Deterministic UI Choreographer (Code-Owned)    │
        │    │   • Hysteresis & dwell guards (anti-flicker)    │
        │    │   • Stakes-based probability thresholds         │
        │    │   • Spring interpolation for presence shader    │
        │    │   • Optional @json-render/core Spec composer    │
        │    └──────────────────────┬──────────────────────────┘
        │                           │
        └──► ┌──────────────────────┴──────────────────────────┐
             │  SYSTEM 2: Samantha Voice / Conversational LLM  │  streaming
             │   • Spoken dialogue, empathy, humor             │
             │   • Drafting letters, poems, email replies      │
             │   • Deep visual description (on cropped ROI)    │
             └─────────────────────────────────────────────────┘
```

### Ownership Boundaries

| Layer | Owns | Never Owns |
| --- | --- | --- |
| **Jev (System 1)** | Fast parallel judgments (`Choice`, `Score`, `Noul`, `Box`), surface selection, item relevance ranking, affective visual tone, memory/vision gating | Generating prose/speech, executing side effects, arithmetic/timers |
| **Voice LLM (System 2)** | Natural spoken dialogue, creative writing, open-ended reasoning, explaining cropped camera regions | Fast per-tick layout routing or high-frequency UI gating |
| **App Code (Director)** | Control flow, `AbortSignal` cancellation, latency budgets, hysteresis, semantic telemetry banding, confirmed side effects, component catalog & Zod validation | Guessing semantic intent with brittle regexes |

---

## 3. Five Signature OS1 UX Loops Powered by Jev

### Loop A — Pure Presence vs. Materializing Surfaces (`Companion Noul` + `Choice`)
A plain `Choice` always forces a winner even during pure conversation. Pair it with a **Companion Noul**:
- `needs_surface` (**Noul**): Should a visual surface be shown/updated right now, or is calm voice-only presence better?
- `surface` (**Choice**): `inbox_triage` | `writing_canvas` | `memory_constellation` | `music_sketch` | `confirm_action`.

**Deterministic UI state rules (hysteresis):**
- `needs_surface > 0.72` **and** `surface.probabilities[choice] > 0.70` → smoothly materialize the winning surface.
- `0.35 <= needs_surface <= 0.72` → stay in ambient presence, optionally displaying a quiet peripheral "Pull up `<surface>`" affordance chip (`jev-ui` `<Gate>` principle: add gentle affordances, never hijack focus).
- While a surface is already open, require `needs_surface < 0.35` across **2 consecutive ticks** (or an explicit dismiss) before dissolving back to pure presence so the screen never flickers mid-sentence.

### Loop B — Living Emotional Presence Shader (`Score` + Rolling Transcript)
Modeled on TypeSafe's **Intelliprompter** rolling-transcript loop:
- On each STT chunk (debounced ~400–600 ms, cancelling stale in-flight calls via `AbortSignal`), evaluate 2–3 ordered `Score` questions:
  - `warmth` (`0..3`: `"Task-focused and brisk"` → `"Deeply personal or vulnerable"`)
  - `pace` (`0..3`: `"Slow and reflective"` → `"Energetic and rapid"`)
  - `overwhelm` (`0..2`: `"Calm and clear"` → `"Visibly stressed or seeking calm structure"`)
- Check `confidence` first; when confident, smoothly spring-interpolate the normalized `0..1` scores into visual parameters:
  - Breathing cadence & organic waveform amplitude
  - Palette temperature (cool cream/coral ↔ deeper warm vermilion)
  - Information density (when `overwhelm` rises, automatically simplify active surfaces and hide secondary chrome)

### Loop C — "Pocket Camera" Live Vision & Spatial Reticle (`Images` + `Box`)
Using Jev 1.14's multimodal `Images` and `Box` primitive (`TypeSafe-Danger-Zone-Images: true`):
- Capture upright baseline JPEGs (`280..1568` px) from the camera at a low cadence (e.g., 1 fps or on voice trigger) and pass a short 3-frame rolling buffer (`"two seconds ago"`, `"one second ago"`, `"now"`) in `state`.
- Ask in the **same batched request** as the transcript:
  - `scene_changed` (**Noul**): Did something notable enter, move, or change across `camera_frames`?
  - `visual_target_present` (**Noul**): Is the person or object referenced in `latest` visible in `camera_frames[2].image`?
  - `visual_target_box` (**Box**): Locate the referenced person or object in `camera_frames[2].image`.
- **In code:**
  - Only render a subtle spatial focus reticle when `visual_target_present.noul > 0.7`.
  - If `visual_target_box.confidence < 0.6`, pad the edges by `0.05` before cropping.
  - Use `scene_changed` as a **Noul screen** to avoid sending redundant camera frames to an expensive System Two vision model.

### Loop D — Ambient Triage & Dynamic Workspace Composition (`Score` Fan-Out + `@json-render/core`)
When a user asks Samantha to organize emails, notes, or memories:
- **Item ranking:** Use **grade-mode `Score` fan-out** (one `Score` per candidate item) or **Composite Scoring** (e.g., `0.45 * personal_significance + 0.35 * urgency + 0.20 * emotional_relevance`). Unlike `Choice`, per-item scores stay comparable across batches, support dropping clutter below `minScore`, and allow `pinTop` so visible cards don't jump under the cursor.
- **Ad-hoc multi-card layouts:** When a request calls for combining multiple UI blocks (e.g., a letter draft alongside referenced photos and a music mood strip), delegate composition to `@json-render/core`'s `experimental_composeSpec` backed by Jev (`typesafe-ai/jev`) over your strict OS1 design-system catalog, capped with `maxElements` and `maxDepth` and validated with Zod before render.

### Loop E — Selective Memory & Safe Action Gating (`Simple Memory` + `Routing by Probability`)
- **Selective memory:** Ask `worth_remembering` (**Noul**) + `memory_kind` (**Choice**: `personal_fact`, `relationship`, `taste_preference`, `unfinished_intention`, `emotional_milestone`). Persist only when `worth_remembering.noul >= 0.7`, emit a brief tactile "remembered" shimmer in the UI, and pre-filter memories in code/vector search before putting a small shortlist back into `state`.
- **Action safety:** Jev never mutates external state directly. Even if `requests_irreversible_action.noul > 0.9`, Jev can only transition the UI into `confirm_action` with structured preview props owned by your app. Irreversible side effects (sending email, deleting drafts, booking) require explicit user confirmation.

---

## 4. Reference Director Tick Contract (`@typesafe-ai/sdk`)

All per-tick judgments execute in **one server-side `systemOne` call** with speculative fan-out:

```typescript
// Server-only module (e.g., src/server/os1-director.ts)
import { TypeSafeClient, choice, score, noul, box, image } from "@typesafe-ai/sdk";

export const OS1_JEV_MODEL = "jev-1.14.0";

const client = new TypeSafeClient({
  apiKey: process.env.TYPESAFE_API_KEY,
  defaultHeaders: { "TypeSafe-Danger-Zone-Images": "true" },
});

export interface Os1TickInput {
  rollingTranscript: string;
  lastUserUtterance: string;
  activeSurface:
    | "ambient_presence"
    | "inbox_triage"
    | "writing_canvas"
    | "memory_constellation"
    | "music_sketch"
    | "confirm_action";
  dwellBand: "just_opened" | "short" | "medium" | "lingering"; // semantic band, never raw ms
  voiceEnergyBand?: "quiet" | "conversational" | "animated";   // computed from audio RMS in code
  recentActions: string[];                                     // last 8-12 human-readable labels
  relevantMemories: string[];                                  // pre-filtered shortlist (anti-context-rot)
  cameraFrameJpeg?: Uint8Array;                                // upright baseline JPEG, 280..1568px
  signal?: AbortSignal;
}

export async function evaluateOs1Tick(input: Os1TickInput) {
  const camera = input.cameraFrameJpeg ? image(input.cameraFrameJpeg) : undefined;

  const state = {
    transcript: input.rollingTranscript,
    latest: input.lastUserUtterance,
    ui: {
      active_surface: input.activeSurface,
      dwell: input.dwellBand,
      recent_actions: input.recentActions,
    },
    ...(input.voiceEnergyBand ? { voice_energy: input.voiceEnergyBand } : {}),
    memories: input.relevantMemories,
    ...(camera ? { camera } : {}),
  };

  const questions = {
    needs_surface: noul(
      "Would showing or updating a visual UI surface genuinely help `latest` right now, " +
        "rather than staying in calm voice-only presence?",
      {
        true: "User refers to visual artifacts, lists, writing, media, schedules, or asks to see/organize something.",
        false: "Pure conversation, emotional reflection, casual banter, or simple spoken Q&A.",
      },
    ),
    surface: choice("Which OS1 surface best fits `latest` given `ui.active_surface`?", {
      inbox_triage: {
        what: "Reading, sorting, or curating emails and messages",
        not_for: "Drafting a long personal letter",
      },
      writing_canvas: {
        what: "Composing or editing a letter, note, or poem together",
        not_for: "Triage of multiple inbox items",
      },
      memory_constellation: {
        what: "Recalling shared memories, photos, or past moments in `memories`",
      },
      music_sketch: {
        what: "Listening to, composing, or curating music or audio moods",
      },
      confirm_action: {
        what: "Confirming an irreversible side effect (send, delete, book, pay)",
      },
    }),
    warmth: score("How emotionally intimate or warm is the tone in `transcript`?", [
      "Task-focused and brisk",
      "Friendly and casual",
      "Open and reflective",
      "Deeply personal or vulnerable",
    ]),
    overwhelm: score("How overloaded or stuck does the user sound in `latest`?", [
      "Calm and clear",
      "Mildly scattered",
      "Visibly stressed or seeking calm structure",
    ]),
    requests_irreversible_action: noul(
      "Does `latest` ask to send, delete, purchase, or permanently modify something?",
    ),
    worth_remembering: noul(
      "Does `latest` reveal a lasting personal preference, feeling, relationship, or life detail worth remembering?",
    ),
    ...(camera
      ? {
          visual_target_present: noul(
            "Is the person or object mentioned in `latest` visible in `camera`?",
          ),
          visual_target_box: box(
            "The person or object mentioned in `latest` inside `camera`",
          ),
        }
      : {}),
  };

  return client.systemOne({ model: OS1_JEV_MODEL, state, questions }, { signal: input.signal });
}
```

---

## 5. Realtime Engineering Guardrails

1. **Strict latency budget & fallback:** Wrap every tick in an `AbortSignal.timeout(1500)` (plus abort on new speech chunk). On timeout, rate limit (`429`/`529`), or missing API key, keep the current UI surface stable and log one concise warning—never block voice playback.
2. **Semantic telemetry banding:** Project continuous metrics into words before sending to Jev (`dwellBand`: `"just_opened" | "short" | "medium" | "lingering"`, `voiceEnergyBand`: `"quiet" | "conversational" | "animated"`). This avoids model jaggedness on raw numbers and prevents needless re-evaluations.
3. **Transport modes for dev & CI (inspired by `jev-ui`):** Support `JEV_TRANSPORT=live | record | replay | mock | auto` so the entire OS1 UI can be demoed and E2E-tested deterministically offline without a live API key—including fixture-mutation tests that verify UI surfaces actually respond to changed Jev answers.
4. **Server-side boundary:** Keep `TYPESAFE_API_KEY` (and `AI_GATEWAY_API_KEY` if using `@json-render/core`) strictly on the server; stream only validated UI state updates and inspector telemetry to the client.

---

## 6. Suggested Implementation Roadmap

1. **Milestone 1 — Ambient Presence + Director Loop:**
   - Warm *Her*-inspired full-bleed breathing presence canvas (canvas/WebGL/SVG) driven by spring-interpolated `warmth` and `overwhelm` scores.
   - Server-side `evaluateOs1Tick` endpoint with `live` / `record` / `replay` / `mock` transports.
   - Toggleable **Jev Inspector** drawer showing raw probabilities, confidence, active hysteresis state, latency (ms), and input token cost per tick.
2. **Milestone 2 — Core Tactile Surfaces & Hysteresis:**
   - Implement `inbox_triage` (grade-mode `Score` ranking + `pinTop`), `writing_canvas`, `memory_constellation` (powered by the `worth_remembering` memory loop), and `confirm_action` (stakes-gated).
   - Add voice input (Web Speech / streaming STT) + System 2 conversational/voice LLM running in parallel with Jev.
3. **Milestone 3 — Pocket Camera Mode & Dynamic Composition:**
   - Add webcam frame capture (upright JPEG resize to `280..1568` px) feeding `visual_target_present` + `visual_target_box` with a subtle warm reticle overlay.
   - Optionally integrate `@json-render/core` (`experimental_composeSpec`) for ad-hoc multi-card layouts within the OS1 design system.
