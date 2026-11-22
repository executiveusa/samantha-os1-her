# Composio Project Setup Checklist (`os1-her`)

Follow this checklist to provision and configure the Composio project(s) for **OS1-HER**.

---

## 1. Create Composio Projects

- [ ] Sign in to the [Composio Dashboard](https://app.composio.dev).
- [ ] Create two isolated projects under your organization:
  - `os1-her-dev` (local development & staging)
  - `os1-her-prod` (production)
- [ ] *(Optional)* For automated provisioning, save your Organization API Key (`Settings → Organization`) as `COMPOSIO_ORG_API_KEY` and create projects via `POST /api/v3.1/org/owner/project/new` with `should_create_api_key: true`.

---

## 2. Configure White-Label Branding (OS1 Onboarding)

In each project under **Project Settings → White Labeling**:

- [ ] Set **App Title** to `OS1`.
- [ ] Export `assets/icon.svg` to a square PNG (256×256 to 1024×1024 px) and upload as the project **Logo**.
- [ ] Configure the Connect Link theme colors (warm coral/cream *Her* palette).

---

## 3. Generate Scoped Project API Keys

In **Project Settings → API Keys**:

- [ ] Create a **Scoped Project API Key** for the OS1 runtime with:
  - **Session management**: `Write` (or `Read/Write` if reading saved session configs)
  - **Session tool execution**: `Write`
  - **Triggers / Webhooks**: `Read/Write` (if creating user triggers dynamically from the backend)
- [ ] Copy the key into `.env` as `COMPOSIO_API_KEY` (copied from `.env.example`).
- [ ] *(Note)* Scoped API key permissions cannot be edited after creation—rotate to a new key if permissions change.

---

## 4. Configure Auth Configs

### Phase 1 (Composio-Managed OAuth — Zero Setup)
These work out of the box with Composio's managed OAuth apps:
- [ ] `GMAIL` (also includes Google People contact lookup tools)
- [ ] `GOOGLECALENDAR`
- [ ] `GOOGLEDRIVE`
- [ ] `GOOGLEDOCS`
- [ ] `GOOGLETASKS` / `TODOIST`
- [ ] `NOTION`
- [ ] `SLACK` / `WHATSAPP`
- [ ] `GOOGLE_MAPS`

> **Production note**: Composio-managed OAuth apps share provider rate limits across customers and display Composio's app identity on the provider consent screen. Before public launch, register your own Google OAuth app and attach it as a Custom Auth Config.

### Phase 2 (Bring-Your-Own Auth Configs)
Create Auth Configs in the Dashboard and copy their `ac_*` IDs into `.env`:
- [ ] **Spotify (`SPOTIFY`)**: Create an app in the Spotify Developer Dashboard, set Composio's callback URI, create a Custom Auth Config, and save `COMPOSIO_SPOTIFY_AUTH_CONFIG_ID`.
- [ ] **Twilio (`TWILIO`)**: Configure with your Twilio API Key / Account credentials and save `COMPOSIO_TWILIO_AUTH_CONFIG_ID`.
- [ ] **Exa (`EXA`)**: Configure API Key auth and save `COMPOSIO_EXA_AUTH_CONFIG_ID`.

---

## 5. (Optional) Create Saved Session Configs

Under **Sessions → Configs** in the Dashboard (if Session Configs are enabled on your project):

- [ ] Create `os1-voice-core`: allowlist only the low-latency everyday toolkits/tools (e.g., Gmail read/draft, Calendar read/create, Spotify playback, Tasks). Save ID as `COMPOSIO_VOICE_SESSION_CONFIG_ID`.
- [ ] Create `os1-background-worker`: broader toolkit set for async Tool Router + Remote Sandbox tasks. Save ID as `COMPOSIO_WORKER_SESSION_CONFIG_ID`.

---

## 6. Wire Up Realtime Triggers & Webhooks

### Local Development
- [ ] Install the Composio CLI and authenticate.
- [ ] Stream signed trigger events straight to your local webhook endpoint (no ngrok/tunnel required):
  ```bash
  composio dev triggers listen --forward "http://localhost:8000/api/webhooks/composio"
  ```
- [ ] Copy the signing secret printed by the CLI (or set `COMPOSIO_WEBHOOK_SECRET` in `.env` beforehand so the CLI signs with it).

### Production
- [ ] Register your public HTTPS endpoint once per project:
  ```typescript
  const sub = await composio.triggers.setWebhookSubscription({
    webhookUrl: `${process.env.APP_URL}/api/webhooks/composio`,
  });
  ```
- [ ] Store `sub.secret` in your secret manager as `COMPOSIO_WEBHOOK_SECRET`.
- [ ] Create per-user trigger instances once they connect accounts:
  - `GMAIL_NEW_GMAIL_MESSAGE` (`type: "webhook"`)
  - `GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_CREATED_TRIGGER` (`type: "webhook"`)
  - `GOOGLECALENDAR_GOOGLE_CALENDAR_EVENT_UPDATED_TRIGGER` (`type: "webhook"`)
  - `GOOGLECALENDAR_EVENT_CANCELED_DELETED_TRIGGER` (`type: "webhook"`)
  - `GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER` (polling)

---

## 7. Install the Composio Coding-Agent Skill (Optional)

When ready to implement the integration inside this repo, install Composio's official agent skill:

```bash
npx skills add ComposioHQ/composio --skill composio -y
```
