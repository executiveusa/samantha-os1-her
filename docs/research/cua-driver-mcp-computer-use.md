# Cua AI & Cua Driver (MCP) — Computer Use on Users' Own Computers

*Research snapshot: November 22, 2026*

> **Naming note ("Kua" vs. "Cua"):** The computer-use platform and driver commonly heard as *"Kua AI"* / *"Kua driver"* is spelled **Cua** (short for **C**omputer **U**se **A**gent, pronounced *"kua"*), built by **Cua AI, Inc.** at [`cua.ai`](https://cua.ai) and [`github.com/trycua/cua`](https://github.com/trycua/cua). Unrelated products with the literal spelling *Kua* (`kua.ai`, an e-commerce seller SEO platform, and `KuaDashboard`, an AWS/GCP/Kubernetes dashboard) are not desktop computer-use drivers.

---

## 1. Executive Summary (TL;DR for `os1-her`)

1. **Cua Driver (`cua-driver`) is the right primitive for letting OS1/Samantha operate apps on a user's own computer — *without* taking over their mouse or keyboard.** Built in Rust and licensed under **MIT**, Cua Driver exposes an MCP server (`cua-driver mcp`), CLI (`cua-driver call`), and Python/TypeScript SDKs (`cua-driver` / `@trycua/cua-driver`) across **macOS, Windows, and Linux**. Its defining feature is **background-first delivery**: it reads OS accessibility trees and routes actions to specific windows behind the user's active window with its own tinted overlay cursor, so the user and Samantha can co-work on the same machine simultaneously.
2. **Avoid deprecated Cua packages from 2025 tutorials.** On **October 18, 2026**, Cua retired Cua Cloud & Fleets and deprecated `cuabot`, `cua-computer`, `cua-computer-server`, `cua-agent`, and `cua-mcp-server`. (`cuabot` also has known unpatched security issues and must not be run.) For driving a user's own machine today, **Cua Driver** is the sole active, maintained component.
3. **Massive integration advantage for `os1-her`: Hermes Agent already ships Cua Driver natively.** Nous Research's Hermes Agent includes a built-in `computer_use` toolset that bundles and pins `cua-driver` (updated to **`0.52.0`** on Nov 19, 2026 via [`NousResearch/hermes-agent#157538`](https://github.com/NousResearch/hermes-agent/pull/157538)) and speaks MCP over stdio to it. Hermes adds Set-of-Marks (SOM) capture formatting, 4-layer screenshot token eviction (~30K vs. ~600K tokens over a 20-action session), voice/gateway approval gates, hard-blocked dangerous shortcuts/shell payloads, `hermes computer-use doctor`, and automatic telemetry suppression (`CUA_DRIVER_RS_TELEMETRY_ENABLED=0`).
4. **How it fits `os1-her`'s existing architecture:**
   - **Composio (`docs/composio-architecture.md`)** owns **cloud APIs, OAuth custody, and proactive webhooks** (Gmail, Google Calendar, Drive, Spotify, Notion, Slack).
   - **Browser CDP (`browser_*` / Hermes `browser`)** owns **web apps** cleanly via DOM/CDP without pixel fragility.
   - **Cua Driver (`computer_use` / `cua-driver mcp`)** fills **Tier 3 — Local & OS-Native Surfaces** on the user's own computer (Apple Mail, Notes, Messages, Finder, spreadsheets, native desktop apps, and local Electron apps that have no cloud API).
5. **For a shipping OS1 desktop product, embed the driver in the signed OS1 app.** Cua Driver's `EmbeddedCuaDriverHost` lets a signed OS1 desktop client own macOS Accessibility/Screen Recording TCC grants under its own bundle ID, expose a private MCP socket to the agent, intercept residual permission prompts via `DriverAuthorizationHost` (so Samantha can ask for voice confirmation), and stream content-free activity events via `DriverActivityObserver` into OS1's ambient UI.

---

## 2. What Is Cua AI? (Company, Ecosystem & Licensing)

### Company & Traction
- **Cua AI, Inc.** (San Francisco; founded March 2025 by Francesco Bonacci and Dillon DuPont, formerly Microsoft / co-authors of *Windows Agent Arena*; Y Combinator Spring/X25 batch).
- Flagship open-source monorepo: [`github.com/trycua/cua`](https://github.com/trycua/cua) (~32.7k GitHub stars as of Nov 2026).

### Active Cua Product Stack (Late 2026)

| Component | Purpose | License | Relevance to `os1-her` |
| --- | --- | --- | --- |
| **Cua Driver (`cua-driver`)** | Background-first desktop & browser automation runtime on a real host OS (macOS, Windows, Linux) via MCP, CLI, or SDK | **MIT** | **Primary target** — lets OS1 drive apps on the user's own computer |
| **Cua SDK (`cua-sandbox`) & `cua` CLI** | Create and manage isolated local/cloud VM sandboxes (macOS via Lume, Linux, Windows via `ghcr.io/trycua/*`) | **MIT** | Useful only if OS1 needs *isolated* disposable desktops instead of the user's own desktop |
| **Lume** | Lightweight macOS/Linux VM manager using Apple `Virtualization.Framework` (~97% native CPU on Apple Silicon) | **MIT** | Optional local sandbox backend for unsafe/untrusted agent work |
| **Cua Spaces** | Desktop app (macOS 26+) managing local/remote VM "Spaces" and bundling Cua Driver with menu-bar health/repair UI | **FSL-1.1-MIT** *(source-available; converts to MIT 2 yrs post-release; free personal, $18/mo Pro, $30/seat Teams)* | Optional convenience wrapper on macOS 26+; **not required** to use Cua Driver |
| **Cua Bench / Cua Driver Bench** | Evaluation benchmarks for computer-use agents and driver harnesses | `cua-bench` MIT; `cua-driver-bench` FSL-1.1-MIT | Useful for regression testing OS1 computer-use reliability |
| **`cua-perception` (Optional Extension)** | Local CPU screenshot parser (OmniParser icon detector + PP-OCR + ONNX Runtime) for canvas/game UIs lacking accessibility trees | **Mixed: OmniParser is AGPL-3.0-only**, PP-OCR Apache-2.0 | **Legal caution** — skip if distributing OS1 commercially without AGPL compliance; Cua Driver works fully without it |

### Deprecated Packages (Do Not Use)
Following the **October 18, 2026** shutdown of Cua Cloud and Fleets ([migration guide](https://cua.ai/docs/cua-sdk/guides/cua-cloud-ended)), the following packages are **unmaintained**:

| Deprecated Package | Last Release | Replacement |
| --- | --- | --- |
| `cuabot` (npm) | `1.0.14` | **Do not run** — has known security vulnerabilities. Use **Cua Driver** over MCP or a sandbox. |
| `cua-mcp-server` (PyPI) | `0.1.16` | **`cua-driver mcp`** (native Rust stdio MCP server). |
| `cua-computer-server` (PyPI) | `0.3.46` | **`cua-driver`** on a host desktop, or `cua-spacesd` inside sandboxes. |
| `cua-computer` (PyPI) | `0.5.19` | **`cua-driver`** SDK for the host machine, or `cua-sandbox` for VMs. |
| `cua-agent` (PyPI) | `0.9.1` | Bring your own harness (Hermes Agent, Claude Code, Codex, custom orchestrator) over MCP. |

---

## 3. How Cua Driver Works Under the Hood

Cua Driver is strictly the **UI observation and actuation layer**. It never calls an LLM API or owns the agent loop—your harness (Hermes Agent / OS1 runtime) owns reasoning, voice, memory, and planning:

```text
User Voice / Intent
   │
   ▼
OS1 / Hermes Agent Harness (LLM + Loop + Approvals + Memory)
   │  MCP (stdio / Unix socket / Named Pipe / optional Bearer HTTP)
   │  or UniFFI SDK (Python / TypeScript)
   ▼
Cua Driver Rust Runtime (7-layer AuthZ + Sessions + Element Cache + Browser CDP)
   │
   ├── macOS:   Accessibility (AX) + SkyLight (`SLPSPostEventRecordTo`) + ScreenCaptureKit
   ├── Windows: UI Automation (UIA) + HWND `PostMessage` / `SendInput`
   └── Linux:   AT-SPI 2 + X11/XTest (or Wayland compositor/portal + XWayland)
```

### 3.1 Observe: Accessibility Tree + Pixels Together
- **`get_window_state(pid, window_id)`** returns both the window's structured **accessibility tree** (roles, labels, bounds, opaque `element_token` handles) and a **window screenshot** in a single call.
- Pass `include_screenshot: false` when only re-indexing elements (saves vision tokens and latency).
- **`get_desktop_state`** captures the full primary display (used for screen-level orientation or desktop shell elements; desktop-targeted input is foreground-only).
- Every `get_window_state` call invalidates the previous snapshot of that window (`invalidated_snapshot_ids`); acting on an old handle returns `stale_element_token` rather than silently misclicking.

### 3.2 The Background-First Action Ladder
Every input tool (`click`, `double_click`, `right_click`, `drag`, `scroll`, `type_text`, `press_key`, `hotkey`) requires an explicit per-call `target` (`{kind: "window", pid, window_id}` or `{kind: "desktop", display_id: "primary"}`) and defaults to **`delivery_mode: "background"`**—meaning the driver does **not** raise the target window, warp the real OS pointer, or steal keyboard focus from the user.

Cua Driver enforces an explicit 4-rung **action ladder**:

1. **Rung 1 — Element, Background (`element_token`):** Invokes semantic OS accessibility actions (`AXPerformAction` on macOS, UIA Invoke on Windows, AT-SPI on Linux). **This is the only rung the driver can verify itself** (`verified: true`, `effect: "confirmed"`).
2. **Rung 2 — Pixel, Background (`x, y` in window-local screenshot coordinates):** Synthesizes window-scoped input without fronting the window. For keyboard actions into Chromium/Electron inputs, passing `x, y` first clicks to give the renderer field focus.
3. **Rung 3 — Page (`browser_*` over CDP):** For Chrome, Edge, Chromium, and Electron windows, switches to typed Chrome DevTools Protocol tools bound to the exact window/tab—operating on occluded or inactive tabs without focus steal.
4. **Rung 4 — Foreground (`delivery_mode: "foreground"`):** Last resort for games, canvas apps (Blender, Unity), and focus-polling apps. Briefly raises the target window, delivers the single action, and restores the user's previous frontmost app.

### 3.3 Honest Verification & Structured Refusals
A core design strength of Cua Driver is **anti-hallucination feedback**:
- Every action returns structured metadata:
  - `path`: actual delivery mechanism (`ax`, `cgevent`, `cgevent_fg`, `key_events`, `x11_atspi`, `x11_pixel`, `msaa`, etc.)
  - `effect`: `confirmed` | `unverifiable` | `suspected_noop` | `partial` | `refused`
  - `verified`: `true` only when confirmed via accessibility readback
  - `escalation`: `{ recommended: "px" | "page" | "foreground", reason }` when a higher rung is needed
- Electron, Catalyst, and web views often echo writes they didn't apply; Cua Driver flags them `unverifiable` instead of faking success.
- Ambiguous targets (e.g., a `pid` with multiple windows when `window_id` is omitted) refuse before sending input (`ambiguous_window_target`) and return the candidate window list.

### 3.4 Latency & Token Multipliers: `run_steps`, `run_script`, and `agent_display`
For a realtime voice companion like OS1, multi-turn round-trips kill conversational flow. Cua Driver includes three standout tools:
- **`run_steps` (default recommended action tool):** Executes 1–64 ordered actions in **one MCP tool call**, stops on first failure, supports targeting by `{role, name, app, window}` without a prior snapshot, automatically retries stale tokens once on a unique role+label match, and with `observe: {}` returns a compact `since: "latest"` accessibility diff in the same response.
- **`run_script`:** Executes a sandboxed **QuickJS** JavaScript program (no filesystem, network, process, timers, or env; 32 MiB heap; 64 KiB script; 30s default / 120s max timeout; 100 default / 500 max calls) that loops, branches, and reads/verifies state locally inside the driver, returning only the final result to the LLM. Every inner call still passes full permission & policy checks. *(Can be disabled via `CUA_DRIVER_DISABLE_RUN_SCRIPT=1`.)*
- **`agent_display` (macOS):** Creates a **virtual display** for the agent so OS1 can move app windows completely off the user's physical monitor via `set_window_frame` while working on them cleanly (1:1 non-Retina coordinates).

### 3.5 Optional Local Vision Parsing (`cua-perception`)
For apps with empty accessibility trees (custom canvas, remote desktops, games), the optional `cua-perception` extension runs **OmniParser + PP-OCR via ONNX Runtime on CPU** locally (no cloud upload, ~2–2.5s on macOS, ~3.5–4s on Linux, ~8–9s on Windows). Every perception click is bound to a single-use `capture_id` (60s TTL) to prevent stale-screen clicks. **License caveat:** OmniParser is **AGPL-3.0-only**; omit this extension if AGPL is unacceptable for your distribution model.

---

## 4. MCP Tool Catalog, Transports & Process Model

### 4.1 Complete MCP Tool Groups (`cua-driver mcp`)

| Category | Key Tools | Notes |
| --- | --- | --- |
| **App & Window** | `list_apps`, `list_windows`, `launch_app`, `kill_app`, `bring_to_front`, `set_window_frame`, `invoke_menu` | `launch_app` launches in the background; `kill_app` only kills driver-launched processes in `standard` mode |
| **Window State** | `get_window_state`, `verify_state`, `parse_visual_regions` | `get_accessibility_tree` is deprecated (removed after Nov 26, 2026) |
| **Screen** | `get_desktop_state`, `get_screen_size`, `get_cursor_position`, `zoom`, `agent_display` *(macOS)* | `zoom` crops a window region with 20% padding |
| **Pointer & Click** | `click`, `double_click`, `right_click`, `drag`, `scroll`, `move_cursor` *(+ Linux low-level `mouse_*` / `parallel_mouse_drag`)* | Per-call `target` + `delivery_mode` (`background` default) |
| **Keyboard & Values** | `type_text`, `press_key`, `hotkey`, `set_value`, `clipboard_read`, `clipboard_write` | `set_value` writes accessible field values directly (works even on minimized macOS windows) |
| **Batch & Script** | `run_steps`, `run_script` | Cuts LLM round-trips dramatically; passes identical AuthZ checks |
| **Browser (CDP)** | `browser_prepare`, `get_browser_state`, `browser_navigate`, `browser_click`, `browser_type`, `browser_select`, `browser_pointer`, `browser_dialog`, `browser_set_input_files`, `browser_download`, `browser_motion_policy`, `page` *(legacy read-only)* | Chrome/Edge/Electron over CDP; `semantic_v2` snapshot ranks visible content + typed refs; `page` remains read-only fallback for Safari/Firefox |
| **Sessions** | `start_session`, `get_session`, `list_sessions`, `end_session` | 5-minute idle TTL; transport-owned leases (`session_owned_by_other_transport`) |
| **Agent Cursor** | `set_agent_cursor_enabled`, `set_agent_cursor_motion`, `set_agent_cursor_theme`, `get_agent_cursor_state` | Customizable dotLottie/SVG cursor themes & reduced motion |
| **Recording** | `start_recording`, `stop_recording`, `get_recording_state` | Trajectory capture (`replay_trajectory` & `install_ffmpeg` deprecated after Nov 26, 2026) |
| **Ops & Diagnostics** | `check_permissions`, `health_report`, `get_config`, `set_config`, `check_for_update`, `install_extension`, `get_guide` | `health_report` powers `hermes computer-use doctor`; `get_guide` serves bundled agent guidance without needing an external skill install |

### 4.2 Process Model & Transports

Where the runtime lives determines **who owns OS permissions (TCC on macOS, interactive desktop session on Windows/Linux)**:

| Entry Point | Runtime Owner | Lifecycle & Transport |
| --- | --- | --- |
| `cua-driver mcp` (Windows / Linux) | The MCP child process itself | Stdio; exits cleanly on stdin EOF |
| `cua-driver mcp` (macOS) | Proxies to **`CuaDriver.app`** daemon (`com.trycua.driver`) | Stdio proxy → daemon socket so macOS Accessibility & Screen Recording grants persist across terminal/agent restarts (`--direct` overrides) |
| `cua-driver serve --socket <path>` + `cua-driver mcp --socket <path>` | Dedicated long-lived daemon (LaunchAgent / Scheduled Task / systemd user unit) | Shared Unix socket (macOS/Linux) or owner-restricted Named Pipe (Windows); lets multiple MCP clients share one desktop (native input serialized 1-at-a-time) |
| `EmbeddedCuaDriverHost` (TS / Python SDK) | **Your signed desktop app process** | Spawns a private embedded daemon (`CUA_DRIVER_EMBEDDED=1`) inheriting the parent app's TCC identity and returns `{ socketPath, mcp: { command, args, environment } }` |
| Optional HTTP MCP listener | Same runtime when `CUA_DRIVER_RS_MCP_HTTP_PORT` is set | Disabled by default; requires `CUA_DRIVER_RS_MCP_HTTP_TOKEN` (32–4096 chars, Bearer auth). **Local/tunneled use only—never bind raw to public internet.** |

---

## 5. How `os1-her` Can Use Cua Driver for Users' Own Computers

Depending on how we deploy `os1-her` (local personal Hermes companion vs. packaged OS1 desktop app vs. cloud-hosted OS1), there are **four concrete integration patterns**.

### Pattern A: Hermes Agent Built-In `computer_use` Toolset *(Recommended Immediate Path for Local `os1-her`)*

Because `os1-her` is built on **Nous Research's Hermes Agent**, you **do not need to wire up a second raw MCP server** for local single-user setups. Hermes already bundles, pins, and wraps `cua-driver` (pinned at `0.52.0` as of Nov 2026) as its native `computer_use` toolset over stdio MCP.

**Why use Hermes's built-in wrapper instead of raw `cua-driver mcp` on Hermes:**
- **Pinned & self-healing binary management:** Managed via `hermes pm` (`pm/lock.json`), verified via SHA-256, inspected via `hermes computer-use status` and `hermes computer-use doctor`.
- **4-layer screenshot token optimization:** Automatic batch screenshot eviction (respecting Anthropic's 100-image `<=2000px` and 24 MB budgets while preserving prompt-cache prefixes), context-compressor pruning, image-aware token estimation (~1500 tokens/image), and Anthropic server-side `clear_tool_uses_20250919`. Reduces a 20-action session from **~600K tokens to ~30K tokens**.
- **Hermes-native safety & approvals:** Maps clicks/typing/drags/keys into Hermes's approval flow (CLI dialog, messaging buttons, or API Server `POST /v1/runs/{id}/approval` for OS1 voice confirmation), keyed separately as `cua::background` vs. `cua::foreground`, plus hard-blocked dangerous key combos (empty trash, force delete, lock/logout) and shell-injection typing filters (`curl | bash`, `sudo rm -rf /`).
- **Privacy by default:** Hermes automatically injects `CUA_DRIVER_RS_TELEMETRY_ENABLED=0` on every `cua-driver` invocation, disabling upstream PostHog telemetry.
- **Platform stability fixes out of the box:** Automatically disables the overlay cursor where it causes known issues (macOS idle CPU burn, Linux X11 fullscreen-window wedging).

> **Important:** Both Cua's docs and Hermes's docs explicitly recommend **not** adding a duplicate raw `cua-driver` MCP entry when Hermes's `computer_use` toolset is enabled.

**Setup for the `samantha` Hermes profile (`~/.hermes/profiles/samantha/config.yaml`):**

```yaml
# Add to config/hermes-profile-example/config.yaml
computer_use:
  permission_mode: bounded                       # "standard" for interactive dev; "bounded" for hardened daily use
  capability_manifest: ~/.hermes/profiles/samantha/cua-manifest.yaml
  cua_telemetry: false                           # default false; keeps PostHog telemetry disabled
  # no_overlay: false                            # uncomment only if you explicitly want the cursor overlay on macOS/X11
  # native_wayland: true                         # Linux Wayland opt-in (requires WAYLAND_DISPLAY)
  # autostart: true                              # Windows only, if driving via SSH from Session 0
```

Enable and verify:
```bash
hermes -p samantha computer-use install
hermes -p samantha tools enable computer_use --platform cli
hermes -p samantha computer-use doctor           # verifies binary, TCC grants, AX/UIA/AT-SPI, ScreenCaptureKit
```

---

### Pattern B: Signed OS1 Desktop App Hosting Cua Driver (`EmbeddedCuaDriverHost`) *(Recommended Product Path)*

If `os1-her` ships a dedicated desktop app (e.g., an evolution of `nickvasilescu/hermes-desktop-os1`, or an Electron/Tauri/Swift OS1 client on the user's Mac/Windows/Linux laptop), asking end users to separately install `CuaDriver.app` and grant permissions to a third-party app breaks the seamless OS1 onboarding experience.

Cua Driver natively solves this via **`EmbeddedCuaDriverHost`**:

1. Bundle the signed `cua-driver` binary inside your app (e.g., `OS1.app/Contents/Resources/cua-driver`, **outside** Electron's ASAR archive, with the executable bit set).
2. The **permission-owning OS1 desktop app process** calls `EmbeddedCuaDriverHost.start()` (never via `open(1)` or `NSWorkspace`, which breaks macOS TCC responsibility attribution).
3. macOS attributes Accessibility & Screen Recording grants directly to **`OS1.app`** (`com.os1.samantha`), and `check_permissions` reports `source.attribution: "host"` without spawning confusing third-party permission popups.
4. Your OS1 app passes `connection.mcp` (`{ command, args, environment }`) to the local agent / MCP client—and can also connect directly via `CuaDriver.connect(connection.socketPath)` using the TypeScript/Python SDK.
5. Attach two native host callbacks:
   - **`DriverAuthorizationHost`**: Intercepts residual `standard`-mode boundaries (e.g., attaching to a user's logged-in Chrome profile) so **Samantha asks verbally** (*"Want me to check your open Chrome tab?"*) and renders a Jev `confirm_action` card before approving.
   - **`DriverActivityObserver`**: Emits content-free events (`tool`, `risk_class`, `refusal_code`—never screenshots or typed text) to gently animate the OS1 breathing presence shader / ambient activity rail.

```typescript
// Inside the signed OS1 desktop main process (Node / Electron / Bun)
import { CuaDriver, EmbeddedCuaDriverHost } from "@trycua/cua-driver";

const host = EmbeddedCuaDriverHost.withOptions(
  "/Applications/OS1.app/Contents/Resources/cua-driver",
  "com.os1.samantha",
  {
    noOverlay: false,
    captureStderr: true,
    environment: {
      CUA_DRIVER_RS_TELEMETRY_ENABLED: "0",
      CUA_DRIVER_PERMISSION_MODE: "bounded",
      CUA_DRIVER_CAPABILITY_MANIFEST_FILE: "/Users/me/.os1/cua-manifest.yaml",
      CUA_DRIVER_CAPABILITY_MANIFEST_APPROVED: "1",
      // Optional snappier post-action window-change wait (default 1000ms on macOS)
      CUA_DRIVER_WINDOW_CHANGE_TIMEOUT_MS: "350",
    },
  },
);

const connection = await host.start();
const driver = CuaDriver.connect(connection.socketPath);

// Hand `connection.mcp` ({ command, args, environment }) to your MCP client or Hermes backend.
// On app exit (strict order):
// await driver.shutdown(); driver.uniffiDestroy();
// await host.stop(); host.uniffiDestroy();
```

---

### Pattern C: Direct Raw `cua-driver mcp` (Non-Hermes / Custom MCP Orchestrator)

If you build a standalone TypeScript/Python OS1 orchestrator (e.g., Vercel AI SDK + Composio + LiveKit without Hermes), or want to connect Claude Code / Codex / Cursor directly during development:

1. Install standalone Cua Driver:
   ```bash
   # macOS & Linux
   /bin/bash -c "$(curl -fsSL https://cua.ai/driver/install.sh)"
   # Windows (PowerShell)
   irm https://cua.ai/driver/install.ps1 | iex
   ```
2. Register the stdio MCP server (or point at a policy-hardened daemon with `--socket`):
   ```json
   {
     "mcpServers": {
       "cua-driver": {
         "command": "cua-driver",
         "args": ["mcp", "--socket", "/tmp/os1-cua-driver.sock"],
         "env": {
           "CUA_DRIVER_RS_TELEMETRY_ENABLED": "0",
           "CUA_DRIVER_PERMISSION_MODE": "bounded",
           "CUA_DRIVER_CAPABILITY_MANIFEST_FILE": "/Users/you/.os1/cua-manifest.yaml",
           "CUA_DRIVER_CAPABILITY_MANIFEST_APPROVED": "1"
         }
       }
     }
   }
   ```
   *(Note: on macOS, bare `cua-driver mcp` proxies to `CuaDriver.app`, whose own LaunchAgent/launch flags govern the permission mode—env vars in the MCP client block apply directly on Windows/Linux or when passing `--direct` / spawning your own daemon.)*
3. **Engineering requirements if bypassing Hermes:** You must implement your own screenshot eviction/token cap (otherwise raw screenshots will blow through LLM context windows in ~10 turns), a human-in-the-loop approval gate on mutating tools, and prompt-injection defenses.

---

### Pattern D: Cloud/Remote OS1 Brain Driving the User's Local Computer (Companion Bridge)

A critical architectural constraint: **`cua-driver` must always execute locally inside the user's interactive desktop session.** A cloud-hosted OS1 server cannot reach into a user's laptop by itself (and per Hermes docs, Hermes's `computer_use` drives whichever machine hosts the gateway/sandbox display, not a thin remote client).

If `os1-her` evolves into a multi-user cloud-hosted service where users want Samantha to control *their own personal computer*, use an **outbound local companion bridge**:

```text
User's Laptop (Interactive Desktop Session)                       OS1 Cloud Backend
┌──────────────────────────────────────────────┐                  ┌───────────────────────────────┐
│ OS1 Local Companion App (signed, TCC owner)  │                  │ OS1 Voice Shell (LiveKit/Fish)│
│  ├── EmbeddedCuaDriverHost (bounded mode +   │                  │  + System 2 Agent / Hermes    │
│  │   user-editable app/folder manifest)      │   Outbound TLS   │  + Composio (Cloud OAuth)     │
│  ├── Local Kill Switch (hotkey + menu bar)   │ ◀══ WebSocket / ▶│  + Remote MCP Client Proxy    │
│  └── Local MCP-over-WS / Tunnel Relay        │   mTLS / OAuth   │    (forwards tool calls to    │
└──────────────────────────────────────────────┘                  │     user's connected laptop)  │
                                                                  └───────────────────────────────┘
```

**Non-negotiable rules for Pattern D:**
- **Never expose `CUA_DRIVER_RS_MCP_HTTP_PORT` directly to the public internet.** Keep the driver bound to a local Unix socket / Named Pipe (or loopback HTTP with a 32–4096 char bearer token) behind an outbound authenticated tunnel (mTLS WebSocket, Tailscale/WireGuard, or authenticated user-scoped relay).
- **Enforce `bounded` mode + local policy *on the user's laptop***, not just in the cloud prompt—even if the cloud LLM is prompt-injected by a malicious email or webpage, the user's local Cua Driver runtime refuses out-of-scope apps, folders, and security dialogs.
- **Provide a hardware/menu-bar emergency stop** wired directly to `cua-driver revoke --all` (immediately suspends all calls with `authorization_suspended` until the user explicitly re-enables).

---

### 5.1 How Cua Driver Fits `os1-her`'s Dual-Brain Voice UX, Composio & Jev

| Capability / User Request | Best Tooling Layer in `os1-her` | Why |
| --- | --- | --- |
| *"Check my Gmail for Catherine's note and schedule dinner Thursday"* | **Composio** (`GMAIL`, `GOOGLECALENDAR`) | Faster, zero UI fragility, OAuth-scoped, realtime webhook triggers |
| *"Research flights on Google Flights and fill out this web form"* | **Browser CDP** (Hermes `browser` / Cua `browser_*`) | Structured DOM/accessibility refs, works in occluded tabs, origin-restricted |
| *"Clean up my Desktop screenshots, open Apple Notes, grab that paragraph from my Pages doc, or tweak a chart in Excel/Keynote"* | **Cua Driver** (`computer_use` / `cua-driver mcp`) | Native local apps with no cloud API; runs in background while user keeps working |

**Pairing with Dual-Brain Voice (`docs/research/architectures-and-ecosystem.md` — Arch 3) & Jev (`docs/os1-generative-ui-architecture.md`):**
1. **Zero dead air while Samantha drives the desktop:** The sub-400 ms Voice Shell delegates desktop tasks to Hermes via `POST /v1/runs` (*"Let me pull that up in Notes in the background—keep going with what you were saying"*). Because Cua Driver works in the background (or on a macOS `agent_display`), the user's active window and cursor are undisturbed while they chat.
2. **Voice-native approvals:** When Hermes pauses for a `cua::background` / `cua::foreground` approval (or `DriverAuthorizationHost` fires), the SSE `approval.request` event prompts Samantha to confirm aloud while Jev transitions the UI into `confirm_action`.
3. **Calm ambient visibility:** Feed `DriverActivityObserver` events (or `tool.started` SSE events) into the OS1 breathing presence canvas / ambient rail so the user always knows *which* app Samantha is touching without intrusive chat chrome.

---

## 6. Security, Permissions & Prompt-Injection Defense

Giving an AI agent GUI control over a user's personal computer is the highest-privilege surface in `os1-her` (any malicious text in an email, Slack message, or webpage screenshot can attempt prompt injection). Cua Driver is unusually strong here because **authorization is enforced inside the Rust runtime below every transport (MCP, CLI, SDK, `run_script`) and is immutable after launch**—the agent cannot widen its own permissions via tool calls.

### 6.1 The 7-Layer Fail-Closed Authorization Stack
Every tool call must pass all 7 narrowing layers:
1. Hard invariants (e.g., self-targeting protection, protected hosts)
2. Built-in tool & risk map
3. Administrator policy (`CUA_DRIVER_MANAGED_POLICY_FILE`)
4. User policy (`CUA_DRIVER_POLICY_FILE`)
5. Permission mode (`standard` | `bounded` | `unrestricted`)
6. Capability manifest (when configured; required in `bounded`)
7. Launch grant (`--grant existing-profile`) or `DriverAuthorizationHost` callback

### 6.2 Permission Modes

| Mode | Behavior | Recommendation for `os1-her` |
| --- | --- | --- |
| **`standard`** *(default)* | Allows observe/click/type/scroll/drag, isolated browser, validated file transfer, killing driver-launched processes. Denies killing foreign processes, OS permission prompts, and requires explicit grant for logged-in browser profiles. Refuses input onto macOS security/password/Gatekeeper prompts (`security_prompt_protected`). | Good for local developer testing paired with Hermes `approvals.mode: manual`. |
| **`bounded`** | **Deny-by-default.** Requires a v3 capability manifest with mandatory `expires_after` and `idle_timeout`. Out-of-scope apps, origins, or paths return `bounded_resource_outside_manifest`. | **Strongly recommended for daily OS1 use and any unattended/background runs.** |
| **`unrestricted`** | Bypasses Cua approval checks and allows clicking OS security prompts (`--dangerously-bypass-approvals`). Zero prompt-injection protection. | **NEVER use on a user's personal computer.** Only for disposable VMs/sandboxes. |

### 6.3 Recommended Starter Capability Manifest for OS1 (`cua-manifest.yaml`)

> **Critical Cua Rule:** A manifest that specifies `resources.browser.origins` may **only** allow typed `browser_*` tools (combining browser origin restrictions with generic `click`/`get_window_state` is refused at startup, because generic desktop input could target another browser tab). Keep native-app desktop work and origin-scoped browser work in **separate runtimes/manifests**, and set `desktop.display: false` on the desktop manifest.

```yaml
# ~/.hermes/profiles/samantha/cua-manifest.yaml (Native Desktop Apps — macOS example)
version: 3
expires_after: 8h
idle_timeout: 30m

allow:
  tools:
    - start_session
    - end_session
    - list_apps
    - list_windows
    - launch_app
    - get_window_state
    - run_steps
    - click
    - double_click
    - type_text
    - set_value
    - press_key
    - scroll
    - verify_state

resources:
  apps:
    - bundle_id: com.apple.Notes
      launch: true
      windows: all
      terminate: driver_launched
    - bundle_id: com.apple.iCal
      launch: true
      windows: all
      terminate: driver_launched
    - bundle_id: com.apple.calculator
      launch: true
      windows: all
      terminate: driver_launched
    # Explicitly omit Terminal, iTerm2, System Settings, Keychain, Password Managers, and Browsers here

  files:
    read:
      - dir: /Users/you/Documents/OS1-Shared
        recursive: true
    write:
      - dir: /Users/you/Documents/OS1-Shared
        recursive: true

  desktop:
    display: false
```

### 6.4 Extra Hardening Controls
- **YAML / OPA Rego Policy (`CUA_DRIVER_POLICY_FILE`):** Restrict `click` to `delivery_mode: [background]` and `scope: [window]` (preventing unexpected focus-stealing foreground clicks), cap `type_text` length (`max_length: 500`), and explicitly deny sensitive tools (`kill_app`, `clipboard_read`, `run_script` if unwanted).
- **Disable `run_script` if you want strict per-step visibility:** Set `CUA_DRIVER_DISABLE_RUN_SCRIPT=1` so every individual action passes through Hermes's per-tool logging/approval loop.
- **No password typing:** Never feed user passwords into `type_text`; rely on OS autofill (Keychain / Credential Manager / GNOME Keyring) or OAuth via Composio.
- **Instant user kill switch:** Bind a global shortcut or OS1 UI button to `cua-driver revoke --all` (or `cua-driver revoke --session <label>`).
- **Telemetry off:** Always set `CUA_DRIVER_RS_TELEMETRY_ENABLED=0` (or `DO_NOT_TRACK=1` / `cua-driver telemetry disable`) when running standalone outside Hermes.

---

## 7. Platform Support Matrix & Known Limitations

Cua Driver validates every supported capability cell against real fixture apps in a Rust test harness and returns explicit structured refusals rather than silent false positives. Still, real-world OS constraints matter when targeting users' personal computers:

| Platform | Mechanisms | Status | Key Limits & Gotchas for OS1 Users |
| --- | --- | --- | --- |
| **macOS** (14+; 26+ for Spaces) | AX API, SkyLight (`SLPSPostEventRecordTo`), CoreGraphics, ScreenCaptureKit | **Supported** (AppKit, SwiftUI, Electron, Tauri, WKWebView) | • Requires user-granted **Accessibility + Screen Recording** TCC permissions.<br>• Uses private SkyLight SPIs (Apple OS updates can break older driver builds—keep pinned driver updated).<br>• **Stale TCC rows after updates:** System Settings may show ON while `doctor` fails; fix with `tccutil reset Accessibility com.trycua.driver` & `tccutil reset ScreenCapture com.trycua.driver`.<br>• **Off-Space SwiftUI windows** lose their AX tree (`off_space: true`; AppKit unaffected).<br>• **Minimized windows** drop Return/Space/Tab commits (use `set_value` or element click).<br>• **Chromium pixel `right_click`** fires left-click on macOS (use `element_token` or foreground).<br>• Agent cursor overlay causes idle CPU burn on macOS (Hermes disables it by default). |
| **Windows** (10 / 11) | Win32, UI Automation (UIA), HWND `PostMessage` / `SendInput` | **Supported** (Electron, Tauri, WPF, WinUI 3, WebView2) | • **UIPI elevation wall:** A normal (Medium-integrity) agent cannot read UIA or click inside Administrator (High-integrity) windows.<br>• **SSH / Session 0:** On-demand MCP over SSH has no interactive desktop; requires opt-in interactive Scheduled Task (`cua-driver-serve`).<br>• **`WindowsApps` install trap:** A binary under `C:\Program Files\WindowsApps` can trigger WinError 5 from Python venvs; install to user profile instead. |
| **Linux (X11)** | AT-SPI 2, X11/EWMH, XTest | **Supported with toolkit limits** | • glibc x86_64/ARM64 only (no musl/Android builds).<br>• Some toolkits reject synthetic background events (driver returns explicit refusal).<br>• Overlay cursor is a fullscreen always-on-top window that can wedge X11 desktop input after unclean exit (Hermes disables it by default).<br>• Cinnamon leaves AT-SPI off by default. |
| **Linux (Wayland)** | AT-SPI 2 + compositor/portal input + XWayland capture | **Supported with compositor limits** | • **Raw background keyboard input is focus-bound** (`background_unavailable`)—must use AT-SPI-editable fields, `element_token`, XWayland (`GDK_BACKEND=x11`, `QT_QPA_PLATFORM=xcb`), or `foreground` mode.<br>• Screen capture requires an XWayland bridge; Hermes requires `computer_use.native_wayland: true` opt-in. |
| **Cross-Platform App Limits** | — | — | • **Canvas apps, games, Blender, Unity, Logic/Final Cut, Electron < 28:** sparse/empty AX tree; background pixel clicks no-op. Require `delivery_mode: "foreground"` (when user isn't typing) or `cua-perception`.<br>• **Browser CDP (`browser_*`):** Supports Chrome, Edge, Chromium, Electron; **Safari, Firefox, WKWebView, Tauri** return `browser_route_unavailable` (use native AX/pixel or read-only `page`). On Linux, `browser_click` needs `input_route: "dom_event"` to avoid activating the window. |

---

## 8. Recommended Staged Rollout for `os1-her`

1. **Stage 1 — Local Prototype via Hermes `computer_use` (Day 1)**
   - Keep `os1-her` running locally on the developer's machine with the `samantha` Hermes profile.
   - Enable Hermes's built-in `computer_use` toolset (`hermes -p samantha computer-use install && hermes -p samantha tools enable computer_use`), grant OS permissions, and verify with `hermes computer-use doctor`.
   - Test co-working: have Samantha read/edit Apple Notes or Calculator in the background while you keep typing in your active editor, routed via Arch 3 (`/v1/runs` + voice approval).
2. **Stage 2 — Harden for Daily Personal Use (`bounded` Mode + Policy)**
   - Author a narrow v3 `cua-manifest.yaml` allowlisting only benign personal productivity apps (Notes, Calendar, Music, spreadsheets—explicitly excluding Terminal, System Settings, Password Managers, and browsers) with `desktop.display: false`.
   - Attach a `CUA_DRIVER_POLICY_FILE` restricting `click` to `background` + `window` scope and capping `type_text` length.
   - Keep web workflows on Composio (API/OAuth) and Hermes `browser` (CDP) so Cua Driver is strictly reserved for native desktop apps.
3. **Stage 3 — End-User Distribution (Signed OS1 Desktop App / Companion)**
   - Package `cua-driver` inside a signed `OS1.app` using `EmbeddedCuaDriverHost` so users grant permissions once to **OS1** (never a separate daemon install).
   - Wire `DriverAuthorizationHost` into Samantha's spoken confirmation + Jev `confirm_action` card, wire `DriverActivityObserver` into the OS1 presence shader, and add a one-tap menu-bar / voice kill switch (`cua-driver revoke --all`).
   - If moving OS1's brain to the cloud later, keep the `EmbeddedCuaDriverHost` inside the local OS1 Companion App connected over an outbound authenticated tunnel—never expose raw Cua Driver HTTP directly.

---

## 9. Sources & References

- **Cua AI & Repository:** [`cua.ai`](https://cua.ai) · [`cua.ai/cua-driver`](https://cua.ai/cua-driver) · [`github.com/trycua/cua`](https://github.com/trycua/cua) · [`libs/cua-driver/README.md`](https://github.com/trycua/cua/blob/main/libs/cua-driver/README.md)
- **Cua Driver Official Docs:**
  - [How Cua Driver works](https://cua.ai/docs/cua-driver/concepts/how-cua-driver-works)
  - [Platform support](https://cua.ai/docs/cua-driver/concepts/platform-support)
  - [Quickstart](https://cua.ai/docs/cua-driver/quickstart) · [Connect your agent](https://cua.ai/docs/cua-driver/guides/connect-your-agent) · [Hermes guide](https://cua.ai/docs/cua-driver/guides/hermes)
  - [All MCP tools](https://cua.ai/docs/cua-driver/reference/mcp-tools) · [Batch, recording and settings (`run_steps` / `run_script`)](https://cua.ai/docs/cua-driver/reference/mcp-tools/batch-recording-and-settings) · [Drive a browser (CDP)](https://cua.ai/docs/cua-driver/guides/browsers)
  - [Set permissions (modes, manifests, YAML/Rego policies)](https://cua.ai/docs/cua-driver/guides/permissions)
  - [Use the SDK & Expose MCP from a desktop app (`EmbeddedCuaDriverHost`)](https://cua.ai/docs/cua-driver/guides/use-the-sdk)
  - [Serve, configure and update CLI reference](https://cua.ai/docs/cua-driver/reference/cli/serve-and-configure) · [Operate Cua Driver](https://cua.ai/docs/cua-driver/guides/operate) · [Troubleshoot & Known limits](https://cua.ai/docs/cua-driver/guides/troubleshoot)
  - [Migrate from Cua Cloud and deprecated packages (Oct 18, 2026)](https://cua.ai/docs/cua-sdk/guides/cua-cloud-ended)
- **Nous Research Hermes Agent Computer Use Integration:**
  - [Hermes Agent — Computer Use Feature Docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/computer-use)
  - [`NousResearch/hermes-agent#157538`](https://github.com/NousResearch/hermes-agent/pull/157538) (Bumping pinned `cua-driver` `0.21.0 → 0.52.0` with `element_token` & AX/SOM fixes, merged Nov 19, 2026)
