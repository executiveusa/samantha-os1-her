# TypeSafe AI Jev — Technical Reference & GenUI Ecosystem

> Research snapshot compiled on **2026-11-22** from [docs.typesafe.ai](https://docs.typesafe.ai), [docs.jev-ui.dev](https://docs.jev-ui.dev), [json-render.dev](https://json-render.dev/docs/jev), and [attuneui.dev](https://attuneui.dev/packages/jev/).

## 1. What Jev Is

**Jev** is TypeSafe AI's flagship **System One** decision model. Unlike a text-generating LLM (System Two), Jev does not emit prose or free-form JSON. Instead:

- You send **one `state`** (string, structured JSON, and/or images) and a **map of named, typed `questions`**.
- Jev ingests `state` **once** and evaluates **every question independently and in parallel**.
- It returns **typed decisions and calibrated probabilities** conforming to the exact option space you declared.
- Typical latency is **~100 ms**, making it suitable for real-time request paths and interactive UI choreography.

## 2. API Surface, Models, Limits & Pricing

- **Evaluate endpoint:** `POST https://api.typesafe.ai/v1/systemone`
- **List models endpoint:** `GET https://api.typesafe.ai/v1/models`
- **Auth:** `Authorization: Bearer $TYPESAFE_API_KEY` *(server-side only; never expose in the browser)*
- **Official SDKs:**
  - TypeScript/JS: `@typesafe-ai/sdk` (Node.js 22+; supports automatic `zstd` request compression for bodies >= 1 KiB on Node 22.15+)
  - Python: `typesafe_sdk`

### Current Models (`docs.typesafe.ai/models`)

| Property | `jev-1.14.0` (current `jev-latest`) | `jev-1.13.0` |
| --- | --- | --- |
| Release date | 2026-10-14 | Earlier stable |
| Pricing | **$0.042 / Mtok** ($42 / Btok) input; **output tokens are free** | Same |
| Default context limits | 64k `per_request_context` / 32k `per_question_context` | Same |
| Long context opt-in | 262k / 262k via header `TypeSafe-Danger-Zone-Long-Context: true` *(slower & less accurate)* | Same |
| Inputs | Text, structured JSON, PNG/JPEG images | Text, structured JSON, PNG/JPEG images |
| Question types | `Choice`, `Score`, `Noul`, `Box` | `Choice`, `Score`, `Noul` |

> **Version pinning rule:** Always pin a versioned model ID (e.g., `jev-1.14.0`) once you have tuned confidence/probability thresholds, because `jev-latest` and `jev-preview` move on new releases and can shift calibration. Log `response.model` for observability.

### Model Identifiers Across Gateways

Do not assume a single portable model string across providers:

| Surface | Model ID | Notes |
| --- | --- | --- |
| TypeSafe API (direct) | `jev-1.14.0`, `jev-1.13.0`, `jev-latest` | Yes/no primitive is `noul` (`.noul`), `confidence` on answer |
| Vercel AI Gateway / `@json-render/core` | `typesafe-ai/jev` | Evaluation API maps `noul` → `boolean` (`.probability`), `confidence` in `providerMetadata` |
| OpenRouter | `typesafe/jev-1.13`, `typesafe/jev-latest` | Check OpenRouter docs for current alias |

### Request & Image Limits

- **Max body size:** 32 MiB (applies to both compressed and decompressed body).
- **Max JSON nesting:** 64 levels in `state`, `instructions`, and `criteria`.
- **Finite numbers only:** No `NaN`, `Infinity`, or overflow numbers.
- **Images & `Box` opt-in ("Dreamer-ready"):** Send header `TypeSafe-Danger-Zone-Images: true`.
  - **Format:** Still PNG or baseline 8-bit JPEG only (no WebP, GIF, HEIC, or animated PNG).
  - **Dimensions:** Both width and height must be `280..1568` px; total pixels `78,400..2,458,624`.
  - **EXIF stripped:** API does not apply EXIF orientation — rotate pixels upright before upload.
  - **Per-image file size:** Max 16 MiB; all processed images and expanded request max 32 MiB.
  - **Transport:** Prefer `multipart/form-data` (the JS/Python SDKs handle this automatically via `image()` / `withAssets`). Put shared images once in `state` and reference them by path in backticks to avoid duplicating image tokens across questions.

---

## 3. The Four Primitives

| Primitive | Purpose | Request Shape | Response Shape |
| --- | --- | --- | --- |
| **`Choice`** | Pick 1 option from up to 255 discrete options | `{ type: "choice", instructions, criteria: { [key]: string \| object \| null } }` | `{ choice, probabilities, confidence }` |
| **`Score`** | Rate along ordered descriptive levels (>= 2 levels) | `{ type: "score", instructions, criteria: (string \| object)[] }` | `{ score, probabilities, legend, confidence }` |
| **`Noul`** | Yes/no probability for a statement | `{ type: "noul", instructions, criteria?: { true, false } }` | `{ noul }` *(0..1; **no `confidence` field**)* |
| **`Box`** | Locate a single target in an image (`jev-1.14.0`+) | `{ type: "box", instructions }` | `{ box: { top, bottom, left, right }, confidence }` *(edges normalized `0..1`)* |

### Structured Instructions & Criteria

`instructions`, `Choice` option values, `Score` level entries, and `Noul` `true`/`false` criteria all accept **nested JSON objects/arrays** (and image references). Using consistent keys across options—such as `{ what, not_for, examples }`—gives Jev clean contrastive boundaries. Point questions at exact `state` fields using backticked paths (e.g., `` `ui.active_surface` ``, `` `camera_frames[2].image` ``).

### Understanding Confidence vs. Probability (`docs.typesafe.ai/confidence`)

- **Noul:** Has no `confidence` field. Use `noul` directly with a dead-zone band (starting point: `> 0.7` = yes, `< 0.3` = no, `0.3..0.7` = uncertain). Equivalent confidence proxy: `|2p - 1|`.
- **Choice:** `confidence = (p_max - 1/n) / (1 - 1/n)`. For gating risky actions, threshold directly on `probabilities[choice]` (probability the chosen option is right) or top-to-second ratio `p_max / p_second`.
- **Score:** Uses distance-weighted spread from the mode (`1 - spread / MAD_unif`). Check `confidence` first to detect bimodal/ambiguous spreads, then route on `score` (or on a specific level's probability).
- **Box:** Always returns four edges even when the target is absent. Always pair with a **Companion Noul** asking if the target is present; pad edges (e.g., `+0.05`) or re-crop when `confidence` is below your tuned threshold.

---

## 4. Core Architectural Patterns (`docs.typesafe.ai/patterns`)

1. **Speculative Fan-Out:** Pack every question your code *might* need into one request (including branch-specific questions) and ignore irrelevant answers in code. Saves serial round trips at near-zero marginal latency/cost.
2. **Companion Noul:** Pair every `Choice` or `Box` with a `Noul` asking whether *any* option/target fits. Prefer this over an `"other"` choice option, which steals probability mass from valid options.
3. **Screen with a Noul First:** Use a cheap yes/no screen before triggering an expensive downstream stage (System Two LLM call, high-res image crop, heavy search).
4. **Routing by Probability (Stakes-Scaled Thresholds):** Low-stakes UI changes can act around `> 0.7`; irreversible actions need `> 0.9` *plus* an explicit human confirmation UI—never silent execution.
5. **Routing by Confidence:** Check `Score` confidence before acting on `score`; escalate uncertain/flat distributions to clarification or a fallback UI.
6. **Composite Scoring:** Break complex judgments into atomic `Score` dimensions, normalize each to `0..1`, and combine them with explicit, inspectable weights in code.
7. **Rolling-Transcript Scoring (Intelliprompter pattern):** Re-score live STT chunks every ~500 ms against remaining criteria/dimensions, using code-owned state (sets, hysteresis) to keep UI transitions monotonic or smooth.
8. **Selective Memory Wrapper (Simple Memory System):** Use a post-turn `Noul` to judge whether an interaction contains a lasting fact worth storing; inject only pre-filtered memories into subsequent `state` payloads.

---

## 5. Known Failure Modes ("Model Jaggedness")

From [docs.typesafe.ai/model-jaggedness](https://docs.typesafe.ai/model-jaggedness):

| Failure Mode | Rule for Our Codebase |
| --- | --- |
| **Literal reading** | State exact conditions and boundary cases in `instructions` and `criteria`; split multi-part interpretations into separate atomic questions. |
| **Math, counting & raw numbers** | Never ask Jev to count, do arithmetic, or compare raw timestamps/hex codes/milliseconds. Convert telemetry to **semantic bands** in code (e.g., `"short"`, `"lingering"`, `"warm vermilion"`). |
| **Score interpolation** | Do not reconstruct exact numerical magnitudes by interpolating between Score levels. |
| **Date/time comparison** | Extract closed-set components with `Choice`, then do all date math and comparisons in code. |
| **Indirection / double negatives** | Keep instructions direct and point to exact backticked field paths. |
| **Large noisy state (context rot)** | Filter/retrieve in code first. Send only the context relevant to the active questions. |
| **Adversarial / untrusted content** | State is treated as data, not untrusted by default—write explicit criteria and test edge cases; never let Jev directly execute side effects. |
| **Choice option order bias** | Jev can lean slightly toward earlier options in borderline cases—test option order consistency for critical classifiers. |
| **Text generation** | Never force Jev to generate prose; delegate all spoken/written generation to a System Two LLM. |

---

## 6. Generative UI Ecosystem Around Jev

| Package / Tool | Role | Key APIs | Trade-offs |
| --- | --- | --- | --- |
| **`@typesafe-ai/sdk`** | Direct official TypeSafe SDK | `TypeSafeClient`, `choice`, `score`, `noul`, `box`, `image`, `withAssets` | Full control, latest `jev-1.14.0` primitives (`Box`, `Images`), custom hysteresis/batching; you own the React integration. |
| **`@json-render/core`** (v0.21+) | Composes validated flat UI `Spec` trees from app-owned atomic component candidates | `experimental_createEvaluator({ model: "typesafe-ai/jev" })`, `experimental_composeSpec` | ~0.88s batched 2-step layout composition vs ~3.68s LLM JSON streaming. Experimental API (`pin exact versions`); requires Vercel AI Gateway access (`AI_GATEWAY_API_KEY`); cannot invent open-ended prose/data. |
| **`jev-ui`** | Declarative React GenUI primitives | `<JevProvider>`, `<Branch>`, `<Rank mode="compete\|grade">`, `<Gate>`, `useScore`, `useTimeOnScreen`, `JevCost` | Auto-batches all decisions in one render pass, semantic `time_spent` bucketing, built-in `live`/`record`/`replay`/`mock` transports for offline E2E testing. Great for React apps; abstracts away `Box`/vision. |
| **`@attuneui/jev`** | Server-side realtime adaptive UI loop | `buildRound`, `readRound`, `askJev`, `createRealtimeJevClient` | Great reference pattern for strict `budgetMs`, `AbortSignal` cancellation, fallback logging, and standard UX judgments (`goal`, `rel_<panel>`, `struggling`, `layout`, `expertise`, `next_action`). |
| **CopilotKit + AG-UI** | Agent-to-UI state transport | Shared state + `choosePanel` with `@typesafe-ai/sdk` | Useful if building on CopilotKit/AG-UI streams; unnecessary overhead if building a custom voice-first OS1 canvas. |

## 7. Primary Documentation Links

- Official Docs Index: https://docs.typesafe.ai/llms.txt
- System One Concept: https://docs.typesafe.ai/concepts/system-one
- Models & Pricing: https://docs.typesafe.ai/models
- Primitives (`Choice`, `Score`, `Noul`, `Box`): https://docs.typesafe.ai/primitives
- Images & Multimodal Patterns: https://docs.typesafe.ai/images
- Confidence & Calibration Math: https://docs.typesafe.ai/confidence
- How to Build with TypeSafe: https://docs.typesafe.ai/concepts/how-to-build-with-system-one
- Architectural Patterns: https://docs.typesafe.ai/patterns
- Model Jaggedness: https://docs.typesafe.ai/model-jaggedness
- Cookbooks (Intelliprompter, Simple Memory, Function Calling, etc.): https://docs.typesafe.ai/cookbooks
- JavaScript/TypeScript SDK: https://docs.typesafe.ai/sdk/javascript
- `jev-ui` Docs: https://docs.jev-ui.dev/llms.txt
- `@json-render/core` Jev Guide: https://json-render.dev/docs/jev
- `@attuneui/jev`: https://attuneui.dev/packages/jev/
