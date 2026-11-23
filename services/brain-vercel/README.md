# Synthia voice API on Vercel

The `voice` service in the root `vercel.json` uses **`services/`** as the
root, with entrypoint `brain-vercel/app.py`. This preserves access to the
shared `services/voice/os1_voice` modules and `onboarding_script.yaml`,
while the lean `services/pyproject.toml` excludes the LiveKit native worker.

The persistent voice worker continues to use `services/voice/pyproject.toml`
on the VPS; do not install it in Vercel's Python function.

## Smoke checks on a preview deployment

- `GET /voice/health` returns HTTP 200 and JSON `ok: true`.
- `GET /os1/sessions/<id>/poll` without a valid bearer token returns 401.
- `POST /v1/chat/completions` without a valid bearer token returns 401.
- With authorized preview credentials, verify a real streaming turn and session events.
- Independently validate the browser, Vercel-to-orchestrator connection, and VPS
  worker before promotion to production.

**Known constraint:** `brain_server.py` currently stores sessions in process
memory. Vercel functions do not guarantee sticky sessions or durable memory;
this change fixes module packaging but does not solve persistence. A durable
session/event backend or routing to an always-on voice service is required for
production-grade multi-turn continuity.

**Rollback:** revert this PR and redeploy the previous Vercel commit.
