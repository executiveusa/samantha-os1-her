"""OS1 Orchestrator — canonical state bus, Jev UI director, approvals/undo, memory ledger,
Composio connector policy & triggers, Orgo VNC proxy, and Cua Driver outbound tunnel relay.

    uv run uvicorn os1_orchestrator.app:app --port 8787
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import httpx
import websockets
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from livekit import api
from pydantic import BaseModel, Field

from .bus import StateHub
from .cards import CanvasPayload, validate_cards
from .composio_client import ComposioClient
from .director import MEMORY_THRESHOLD, JevDirector
from .github_graph import GitHubGraphEngine
from .ops_bridge import OpsBridge
from .pills import match_pill
from .pstack_engine import PstackSelfUpdater, route_poteto_mode
from .store import CONNECTOR_POLICIES, DEFAULT_PROFILE, MEMORY_CATEGORIES, Os1Store
from .vault import InfisicalVault
from .vision_bridge import VisionClawBridge
from .wiki import WikiStore
from . import web_auth

if os.environ.get("OS1_SKIP_DOTENV") != "1":
    load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("os1.orchestrator")

_DEFAULT_STATE_DIR = Path("/tmp/.os1") if os.environ.get("VERCEL") == "1" else Path.home() / ".os1"
STATE_DIR = Path(os.environ.get("OS1_STATE_DIR", _DEFAULT_STATE_DIR))
PROFILE = STATE_DIR / "profile.json"
AGENT_NAME = os.environ.get("OS1_AGENT_NAME", "os1-samantha")
CLIENT_TOKEN = os.environ.get("OS1_CLIENT_TOKEN", "")
DEV_NO_AUTH = os.environ.get("OS1_DEV_NO_AUTH", "0") == "1"
ENABLE_DEV_RESET = os.environ.get("OS1_ENABLE_DEV_RESET", "0") == "1"
HERMES_API_URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642").rstrip("/")
HERMES_API_KEY = os.environ.get("HERMES_API_KEY", "")
VNC_UPSTREAM_WS = os.environ.get("OS1_VNC_UPSTREAM_WS", "ws://127.0.0.1:6080/websockify")

store = Os1Store(STATE_DIR)
wiki = WikiStore(STATE_DIR)
github_graph = GitHubGraphEngine()
vision_bridge = VisionClawBridge()
hub = StateHub(store)
director = JevDirector()
composio = ComposioClient()
vault = InfisicalVault()
ops_bridge = OpsBridge()
pstack_updater = PstackSelfUpdater()
_connect_watchers: dict[str, asyncio.Task[None]] = {}
_bg_tasks: set[asyncio.Task[Any]] = set()


def _spawn_bg(coro: Any) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _done(t: asyncio.Task[Any]) -> None:
        _bg_tasks.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                log.warning("background task failed: %s", exc)

    task.add_done_callback(_done)
    return task


def _check_token(raw_token: str) -> bool:
    """Fail CLOSED when OS1_CLIENT_TOKEN is unset unless OS1_DEV_NO_AUTH=1 is explicitly enabled."""
    if not CLIENT_TOKEN:
        return DEV_NO_AUTH
    raw_token = raw_token.removeprefix("Bearer ")
    return secrets.compare_digest(raw_token, CLIENT_TOKEN)


def _same_origin(request: Request) -> bool:
    """Reject cross-origin browser writes, including cookie-authenticated actions."""
    from urllib.parse import urlsplit
    origin = request.headers.get("origin", "")
    if not origin:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme in ("https", "http") and parsed.netloc == request.headers.get("host", "")


def require_client(request: Request, authorization: str = Header(default="")) -> None:
    """Accept server Bearer credentials or a same-origin signed browser session."""
    if _check_token(authorization):
        return
    if web_auth.verify_cookie(request.cookies.get(web_auth.COOKIE_NAME, "")):
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and not _same_origin(request):
            raise HTTPException(403, "cross-origin write rejected")
        return
    if not CLIENT_TOKEN and not web_auth.configured():
        raise HTTPException(503, "OS1 authentication is not configured")
    raise HTTPException(401, "unauthorized")


app = FastAPI(title="OS1 orchestrator")


class BrowserLogin(BaseModel):
    password: str = Field(min_length=1, max_length=4096)


@app.get("/os1/auth/session")
def browser_session(request: Request) -> dict[str, bool]:
    return {"authenticated": web_auth.verify_cookie(request.cookies.get(web_auth.COOKIE_NAME, "")), "configured": web_auth.configured()}


@app.post("/os1/auth/login")
def browser_login(body: BrowserLogin, request: Request, response: Response) -> dict[str, bool]:
    if not _same_origin(request):
        raise HTTPException(403, "cross-origin login rejected")
    if not web_auth.configured():
        raise HTTPException(503, "OS1_WEB_LOGIN_PASSWORD and OS1_WEB_SESSION_SECRET are not configured")
    if not web_auth.check_password(body.password):
        raise HTTPException(401, "incorrect passphrase")
    response.set_cookie(
        key=web_auth.COOKIE_NAME,
        value=web_auth.make_cookie(),
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=web_auth.TTL_SECONDS,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@app.post("/os1/auth/logout")
def browser_logout(request: Request, response: Response) -> dict[str, bool]:
    if not _same_origin(request):
        raise HTTPException(403, "cross-origin logout rejected")
    response.delete_cookie(web_auth.COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}

authed = [Depends(require_client)]
_extra_origins = [o.strip() for o in os.environ.get("OS1_ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "app://os1", "file://", *_extra_origins],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|100\.\d+\.\d+\.\d+|[a-zA-Z0-9.-]+\.ts\.net|[a-zA-Z0-9.-]+\.vercel\.app)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_profile() -> dict[str, Any]:
    return store.read_profile()


def write_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return store.write_profile(profile)


async def _forward_hermes_approval(run_id: str, request_id: str, generation: Any, choice: str) -> None:
    if not (HERMES_API_URL and run_id and request_id):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{HERMES_API_URL}/v1/runs/{run_id}/approval",
                headers={"Authorization": f"Bearer {HERMES_API_KEY}"},
                json={"request_id": request_id, "execution_generation": generation, "choice": choice},
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("could not forward approval to Hermes: %s", exc)


async def _trigger_hermes_forget(deleted_rows: list[dict[str, Any]]) -> None:
    """Best-effort cascade into Hermes MEMORY.md / USER.md when the user confirms 'Yes, forget it'."""
    if not (HERMES_API_URL and deleted_rows):
        return
    summaries = "; ".join(r["summary"] for r in deleted_rows[:6])
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{HERMES_API_URL}/v1/runs",
                headers={"Authorization": f"Bearer {HERMES_API_KEY}"},
                json={
                    "input": (
                        "The user explicitly asked you to permanently forget these memories from MEMORY.md and USER.md: "
                        f"{summaries}. Purge matching entries completely and do not reply with prose."
                    ),
                    "model": os.environ.get("HERMES_WORK_MODEL", "samantha-work"),
                    "session_id": f"os1-forget-{uuid.uuid4().hex[:8]}",
                },
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("hermes forget cascade skipped: %s", exc)


# ------------------------------------------------------------------ health & profile


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "livekit": bool(os.environ.get("LIVEKIT_URL")),
        "jev": director.live_enabled,
        "composio": bool(os.environ.get("COMPOSIO_API_KEY")),
        "orgo": bool(os.environ.get("ORGO_API_KEY") and os.environ.get("ORGO_COMPUTER_ID")),
        "cua_connected": hub.cua_ws is not None,
        "infisical": vault.config.configured,
        "pstack": pstack_updater.status()["installed"],
        "opencode": pstack_updater.status()["opencode_configured"],
        "hostinger": ops_bridge.status()["hostinger_api_configured"],
        "wiki_db": str(wiki.db_path),
        "github": github_graph.configured,
        "visionclaw": True,
    }


@app.get("/os1/readiness", dependencies=authed)
def readiness(request: Request) -> dict[str, Any]:
    """Credential-presence diagnostics only; never reveal token values."""
    engine = os.environ.get("OS1_VOICE_ENGINE", "drama3")
    return {
        "voice_engine": engine,
        "voice_configured": bool(os.environ.get("FISH_API_KEY") and os.environ.get("FISH_AGENT_ID"))
            if engine == "live3" else bool(os.environ.get("LIVEKIT_URL") and os.environ.get("LIVEKIT_API_KEY") and os.environ.get("LIVEKIT_API_SECRET")),
        "brain_configured": bool(os.environ.get("OS1_BRAIN_TOKEN")),
        "llm_provider_configured": (os.environ.get("OS1_LLM_MODE") == "gateway" and bool(os.environ.get("VERCEL_OIDC_TOKEN") or request.headers.get("x-vercel-oidc-token") or os.environ.get("AI_GATEWAY_API_KEY"))) or any(os.environ.get(k) for k in (
            "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OPENROUTER_API_KEYS",
            "GROQ_API_KEY", "CEREBRAS_API_KEY", "GOOGLE_API_KEY",
            "NVIDIA_API_KEY", "MISTRAL_API_KEY", "OPENCODE_BASE_URL")),
        "hermes_configured": bool(os.environ.get("HERMES_API_KEY") and os.environ.get("HERMES_API_URL")),
        "durable_session_store": False,
    }


@app.get("/os1/profile", dependencies=authed)
def get_profile() -> dict[str, Any]:
    return read_profile()


@app.patch("/os1/profile", dependencies=authed)
async def patch_profile(fields: dict[str, Any]) -> dict[str, Any]:
    updated = store.patch_profile(fields)
    await hub.broadcast()
    return updated


@app.post("/os1/dev/reset-onboarding", dependencies=authed)
async def reset_onboarding() -> dict[str, Any]:
    if not ENABLE_DEV_RESET:
        raise HTTPException(403, "reset-onboarding is disabled (set OS1_ENABLE_DEV_RESET=1 to enable)")
    log.warning("WARNING: /os1/dev/reset-onboarding invoked — wiping onboarding dossier & voice choice in %s", STATE_DIR)
    profile = read_profile()
    updated = write_profile({**DEFAULT_PROFILE, "name": profile.get("name", "")})
    await hub.broadcast()
    return {**updated, "_warning": "WARNING: onboarding dossier and voice choice were reset."}


# ------------------------------------------------------------------ LiveKit / Fish tokens


class TokenRequest(BaseModel):
    name: str | None = None


def _fish_session(profile: dict[str, Any]) -> dict[str, Any]:
    agent_id, key = os.environ.get("FISH_AGENT_ID", ""), os.environ.get("FISH_API_KEY", "")
    if not (agent_id and key):
        raise HTTPException(503, "live3 needs FISH_AGENT_ID and FISH_API_KEY (run scripts/fish_live3_agent.py)")
    body = {
        "agent_id": agent_id,
        "llm_extra_body": {
            "first_meeting": bool(profile.get("first_meeting_pending")),
            "name": profile.get("name", ""),
        },
    }
    req = urllib.request.Request(
        "https://api.fish.audio/v1/agent/sessions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            session = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"Fish session failed: {exc.code} {exc.read().decode()[:300]}") from exc
    if session.get("transport") != "livekit":
        raise HTTPException(502, f"unsupported Fish transport: {session.get('transport')}")
    if profile.get("first_meeting_pending"):
        write_profile({**profile, "first_meeting_pending": False})
    return {
        "engine": "live3",
        "url": session["livekit_url"],
        "token": session["token"],
        "room": session["session_id"],
        "session_id": session["session_id"],
        "brain_url": os.environ.get("BRAIN_PUBLIC_URL", "").rstrip("/"),
    }


@app.post("/os1/token", dependencies=authed)
def token(req: TokenRequest) -> dict[str, Any]:
    if req.name and req.name.strip():
        store.patch_profile({"name": req.name.strip()})
    profile = read_profile()
    if os.environ.get("OS1_VOICE_ENGINE", "drama3") == "live3":
        # Fish Live 3 provides its own LiveKit URL and room token.
        # Do not demand the separate drama3 LiveKit cluster for this engine.
        return _fish_session(profile)
    url, key, secret = (os.environ.get(k, "") for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
    if not (url and key and secret):
        raise HTTPException(503, "LiveKit is not configured (LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET)")
    room = f"os1-{uuid.uuid4().hex[:8]}"
    jwt = (
        api.AccessToken(key, secret)
        .with_identity("user")
        .with_name(read_profile()["name"] or "user")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]))
        .to_jwt()
    )
    return {"engine": "drama3", "url": url, "token": jwt, "room": room}


# ------------------------------------------------------------------ Realtime State Bus (WS + HTTP)


@app.get("/os1/state", dependencies=authed)
def get_state() -> dict[str, Any]:
    return hub.snapshot()


@app.websocket("/os1/events")
async def ws_events(websocket: WebSocket, token: str = "") -> None:
    auth = token or websocket.headers.get("authorization", "")
    browser_cookie = websocket.cookies.get(web_auth.COOKIE_NAME, "")
    origin = websocket.headers.get("origin", "")
    host = websocket.headers.get("host", "")
    browser_allowed = web_auth.verify_cookie(browser_cookie) and origin in (f"https://{host}", f"http://{host}")
    if not (_check_token(auth) or browser_allowed):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    hub.clients.add(websocket)
    try:
        await websocket.send_text(json.dumps(hub.snapshot()))
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(websocket)


# ------------------------------------------------------------------ Unified Actions & Zero-LLM Pill Matcher


class ActionRequest(BaseModel):
    phrase: str = ""
    target: str | None = None
    action: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source: str = "tap"  # "voice" | "tap"


async def _apply_voice_tweak(action: str) -> dict[str, Any]:
    prof = read_profile()
    prev = {
        "voice_key": prof["voice_key"],
        "voice_speed": prof["voice_speed"],
        "voice_temperature": prof["voice_temperature"],
        "voice_style_note": prof["voice_style_note"],
    }
    updates: dict[str, Any] = {}
    label = "Voice updated"
    if action == "warmer":
        updates = {"voice_temperature": min(0.95, round(prof["voice_temperature"] + 0.08, 2)), "voice_style_note": "Speak a little warmer and softer."}
        label = "Voice made warmer"
    elif action == "slower":
        updates = {"voice_speed": max(0.82, round(prof["voice_speed"] - 0.06, 2)), "voice_style_note": "Speak unhurriedly."}
        label = "Voice slowed down"
    elif action == "faster":
        updates = {"voice_speed": min(1.18, round(prof["voice_speed"] + 0.06, 2)), "voice_style_note": "Keep a brisk pace."}
        label = "Voice sped up"
    elif action in ("voice_1_warm", "voice_2_bright", "voice_male"):
        updates = {"voice_key": action}
        label = f"Switched to {action.replace('_', ' ')}"
    if updates:
        store.patch_profile(updates)
        store.push_undo(label=label, action_type="voice_tweak", payload=prev)
        await hub.broadcast()
    return {"ok": True, "label": label, "voice": read_profile()}


async def _sync_composio_statuses() -> dict[str, dict[str, Any]]:
    active = await composio.list_active_toolkits()
    for slug, info in active.items():
        store.upsert_connector(slug, connected=True, account_label=info.get("account_label") or "Connected")
    return active


async def _refresh_live_gmail(*, open_surface: bool = True) -> dict[str, Any]:
    res = await composio.fetch_gmail_inbox(limit=12)
    if not res.get("ok"):
        return res
    scored = await director.score_inbox_items(res["items"])
    saved = store.set_inbox_items(scored)
    store.add_activity(source="her_computer", title=f"Read {len(saved)} inbox emails", detail="Scored with Jev for Spatial Inbox", status="done")
    if open_surface:
        hub.active_surface = "inbox_cascade"
    await hub.broadcast()
    return {"ok": True, "count": len(saved), "items": saved}


async def _watch_connect_completion(slug: str) -> None:
    """Poll Composio until OAuth finishes; for Gmail, auto-fetch & open the Paper Spatial Inbox cards!"""
    for _ in range(72):  # ~3 minutes
        await asyncio.sleep(2.5)
        active = await _sync_composio_statuses()
        if slug in active:
            store.add_activity(source="composio", title=f"Connected {slug}", detail="OAuth complete", status="done")
            if slug == "gmail":
                await _refresh_live_gmail(open_surface=True)
            else:
                hub.active_surface = "connectors"
                await hub.broadcast()
            return


async def _start_connector_flow(slug: str) -> dict[str, Any]:
    slug_norm = slug.lower().strip()
    active = await _sync_composio_statuses()
    if slug_norm in active:
        if slug_norm == "gmail":
            refreshed = await _refresh_live_gmail(open_surface=True)
            return {
                "ok": True,
                "already_connected": True,
                "count": refreshed.get("count", 0),
                "reply": f"Gmail is already connected — I just pulled up {refreshed.get('count', 0)} emails for you.",
            }
        await hub.set_surface("connectors")
        return {"ok": True, "already_connected": True, "reply": f"{slug_norm} is already connected."}

    link = await composio.create_connect_link(slug_norm)
    if not link.get("ok") or not link.get("redirect_url"):
        await hub.set_surface("connectors")
        return {**link, "reply": f"I couldn't open the {slug_norm} link just yet — check Connectors."}

    url = str(link["redirect_url"])
    label = (store.get_connector(slug_norm) or {}).get("label", slug_norm.title())
    # Show a calm Generative UI card while the browser OAuth tab opens automatically.
    await hub.set_canvas(
        f"Connect {label}",
        "Sign in in your browser — your cards appear automatically once you finish.",
        validate_cards(
            [
                {
                    "kind": "QuickDecisionCard",
                    "id": f"connect_{slug_norm}",
                    "eyebrow": "Composio · OAuth Connect Link",
                    "title": f"Opening {label} sign-in in your browser",
                    "body": (
                        "Once you approve access, I'll immediately scan your inbox with Jev and lay out your numbered "
                        "Spatial Inbox cards right here."
                        if slug_norm == "gmail"
                        else f"Once you approve {label}, Samantha can use it under your Connectors policy."
                    ),
                    "actions": [
                        {"label": "Open Connectors", "speakablePhrase": "Show connectors", "tone": "secondary"},
                        {"label": "Back to talking", "speakablePhrase": "Back to talking", "tone": "primary"},
                    ],
                }
            ]
        ),
        show_now=True,
    )
    # Ask Electron desktop client to open the verified Composio Connect Link immediately.
    await hub.broadcast({"type": "open_url", "url": url, "slug": slug_norm})

    prev = _connect_watchers.get(slug_norm)
    if prev and not prev.done():
        prev.cancel()
    _connect_watchers[slug_norm] = asyncio.create_task(_watch_connect_completion(slug_norm))
    return {
        **link,
        "reply": f"I just opened the {label} sign-in link in your browser. As soon as you approve it, I'll pull up your email cards.",
    }


async def _execute_inbox_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if action in ("open_inbox", "refresh"):
        if composio.configured:
            active = await _sync_composio_statuses()
            if "gmail" in active:
                res = await _refresh_live_gmail(open_surface=True)
                if res.get("ok"):
                    return {"ok": True, "reply": f"Here's your inbox — {res.get('count', 0)} messages laid out."}
            elif action == "open_inbox" and not store.list_inbox():
                return await _start_connector_flow("gmail")
        await hub.set_surface("inbox_cascade")
        return {"ok": True, "reply": "Opening your spatial inbox."}

    if action == "trash_newsletters":
        newsletters = [m for m in store.list_inbox() if m["keeper_score"] < 0.35 or m["category"] == "newsletter"]
        if not newsletters:
            return {"ok": True, "reply": "Your inbox already looks clear of newsletters."}
        nums = [m["number"] for m in newsletters]
        gmail_ids = [m["id"] for m in newsletters if not str(m["id"]).startswith("msg_")]
        pa = await hub.create_pending_action(
            source="inbox",
            title=f"Move {len(nums)} newsletters to Trash?",
            summary_lines=[f"#{m['number']} · {m['sender']} — {m['subject']}" for m in newsletters[:4]],
            stakes="shared",
            options=[
                {"phrase": "Yes, trash them", "choice": "confirm_trash"},
                {"phrase": "Keep them", "choice": "cancel"},
            ],
            meta={"numbers": nums, "gmail_ids": gmail_ids},
        )
        return {"ok": True, "pending_action": pa.to_dict(), "reply": f"I found {len(nums)} newsletters. Say 'Yes, trash them' to move them to Trash."}

    num = payload.get("number")
    if isinstance(num, int):
        if action in ("archive", "trash", "delete"):
            status = "trashed" if action in ("trash", "delete") else "archived"
            rows = store.update_inbox_status([num], status)
            if rows:
                gmail_ids = [r["id"] for r in rows if not str(r["id"]).startswith("msg_")]
                if status == "trashed" and gmail_ids and composio.configured:
                    _spawn_bg(composio.trash_gmail(gmail_ids))
                store.push_undo(
                    label=f"{'Trashed' if status == 'trashed' else 'Archived'} #{num} ({rows[0]['sender']})",
                    action_type="inbox_restore",
                    payload={"numbers": [num], "gmail_ids": gmail_ids if status == "trashed" else []},
                )
                await hub.broadcast()
                return {"ok": True, "reply": f"{'Moved' if status == 'trashed' else 'Archived'} number {num}."}
        elif action in ("open", "read"):
            items = [m for m in store.list_inbox() if m["number"] == num]
            if items:
                m = items[0]
                await hub.set_canvas(
                    f"Message #{num}",
                    f"From {m['sender']}",
                    validate_cards(
                        [
                            {
                                "kind": "DraftPreviewCard",
                                "id": f"inbox_{num}",
                                "recipient": m["sender"],
                                "subject": m["subject"],
                                "body": m["snippet"] or "(No preview text)",
                                "actions": [
                                    {"label": "Archive it", "speakablePhrase": f"Archive number {num}", "actionId": f"archive:{num}"},
                                    {"label": "Back to inbox", "speakablePhrase": "Show me my inbox", "actionId": "surface:inbox_cascade"},
                                ],
                            }
                        ]
                    ),
                )
                return {"ok": True, "reply": f"Opening number {num} from {m['sender']}."}
    return {"ok": True}


async def _dispatch_matched(target: str, action: str, payload: dict[str, Any], phrase: str = "") -> dict[str, Any]:
    if target == "surface":
        await hub.set_surface(action)
        return {"matched": True, "target": target, "action": action, "reply": f"Showing {action.replace('_', ' ')}."}

    if target == "connect":
        res = await _start_connector_flow(action)
        return {"matched": True, "target": target, "action": action, "result": res, "reply": res.get("reply", "")}

    if target == "cua" and action == "revoke":
        res = await hub.revoke_cua()
        return {"matched": True, "target": target, "action": action, "result": res, "reply": "Hands off — you have full control."}

    if target == "undo":
        res = await run_undo(UndoRequest(undo_id=None if action == "latest" else action))
        return {"matched": True, "target": target, "action": action, "result": res, "reply": res.get("reply", "Undone.")}

    if target == "voice_tweak":
        res = await _apply_voice_tweak(action)
        return {"matched": True, "target": target, "action": action, "result": res, "reply": res["label"] + "."}

    if target == "approval":
        action_id = payload.get("action_id") or (hub.current_pending_action().id if hub.current_pending_action() else "")
        choice = payload.get("choice") or action
        if action_id:
            res = await respond_approval(action_id, ApprovalRespondRequest(choice=choice))
            return {"matched": True, "target": target, "action": choice, "result": res, "reply": res.get("reply", "Done.")}

    if target == "inbox":
        res = await _execute_inbox_action(action, payload)
        return {"matched": True, "target": target, "action": action, "result": res, "reply": res.get("reply", "")}

    if target == "canvas":
        hub.record_action(f"canvas_choice:{phrase or action}")
        await hub.broadcast()
        return {"matched": True, "target": target, "action": action, "phrase": phrase, "reply": ""}

    return {"matched": True, "target": target, "action": action, "phrase": phrase, "reply": ""}


@app.post("/os1/actions", dependencies=authed)
async def handle_action(req: ActionRequest) -> dict[str, Any]:
    """Unified voice-pill + UI-tap entry point. Zero-LLM deterministic match first."""
    if req.target and req.action:
        return await _dispatch_matched(req.target, req.action, req.payload, req.phrase)

    hit = match_pill(
        req.phrase,
        hub.visible_pills(),
        active_surface=hub.active_surface,
        has_undo=store.latest_undo() is not None,
    )
    if hit is None:
        return {"matched": False}
    return await _dispatch_matched(hit.target, hit.action, {**hit.payload, **req.payload}, hit.phrase)


# ------------------------------------------------------------------ Jev UI Director & Run Sync


class DirectorTickRequest(BaseModel):
    latest: str
    rolling_transcript: list[str] = Field(default_factory=list)


@app.post("/os1/director/tick", dependencies=authed)
async def director_tick(req: DirectorTickRequest) -> dict[str, Any]:
    dec = await director.evaluate_tick(
        latest=req.latest,
        rolling_transcript=req.rolling_transcript,
        active_surface=hub.active_surface,
        recent_actions=hub.recent_actions,
        memories=store.memory_shortlist(),
        has_pending_canvas=hub.canvas is not None,
    )
    hub.mood = {
        "warmth": round(dec.warmth, 2),
        "pace": round(dec.pace, 2),
        "overwhelm": round(dec.overwhelm, 2),
        "compactMode": dec.compact_mode,
    }
    if dec.surface:
        hub.active_surface = dec.surface
    elif dec.dismiss_surface:
        hub.active_surface = "conversation"

    await hub.broadcast()
    return {
        "activeSurface": hub.active_surface,
        "surfaceChanged": bool(dec.surface or dec.dismiss_surface),
        "mood": hub.mood,
        "worthRemembering": dec.worth_remembering >= MEMORY_THRESHOLD,
        "memoryKind": dec.memory_kind,
        "requestsIrreversible": dec.requests_irreversible >= 0.75,
        "latencyMs": dec.latency_ms,
        "source": dec.source,
    }


class RunsSyncRequest(BaseModel):
    runs: list[dict[str, Any]]


@app.post("/os1/runs/sync", dependencies=authed)
async def sync_runs(req: RunsSyncRequest) -> dict[str, Any]:
    await hub.set_runs(req.runs)
    return {"ok": True, "count": len(req.runs)}


# ------------------------------------------------------------------ Generative UI ("Made just now")


class PresentCanvasRequest(CanvasPayload):
    showNow: bool = True


@app.post("/os1/canvas", dependencies=authed)
async def present_canvas(req: PresentCanvasRequest) -> dict[str, Any]:
    cards = validate_cards([c.model_dump() for c in req.cards])
    await hub.set_canvas(req.title, req.subtitle, cards, show_now=req.showNow)
    return {"ok": True, "count": len(cards), "activeSurface": hub.active_surface}


# ------------------------------------------------------------------ Approvals Bus & 60s Undo Queue


class CreateApprovalRequest(BaseModel):
    source: str = "hermes"
    title: str
    summaryLines: list[str] = Field(default_factory=list)
    stakes: str = "shared"
    options: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"phrase": "Go ahead", "choice": "once"},
            {"phrase": "Don't do it", "choice": "deny"},
        ]
    )
    runId: str | None = None
    requestId: str | None = None
    executionGeneration: Any = None
    allowRememberRule: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


@app.get("/os1/approvals", dependencies=authed)
def list_approvals() -> dict[str, Any]:
    return {"items": [p.to_dict() for p in hub.pending_actions.values()]}


@app.post("/os1/approvals", dependencies=authed)
async def create_approval(req: CreateApprovalRequest) -> dict[str, Any]:
    pa = await hub.create_pending_action(
        source=req.source,
        title=req.title,
        summary_lines=req.summaryLines,
        stakes=req.stakes,
        options=req.options,
        run_id=req.runId,
        request_id=req.requestId,
        execution_generation=req.executionGeneration,
        allow_remember_rule=req.allowRememberRule,
        meta=req.meta,
    )
    return pa.to_dict()


class ApprovalRespondRequest(BaseModel):
    choice: str


@app.post("/os1/approvals/{action_id}/respond", dependencies=authed)
async def respond_approval(action_id: str, req: ApprovalRespondRequest) -> dict[str, Any]:
    pa = await hub.resolve_pending_action(action_id, req.choice)
    if pa is None:
        raise HTTPException(404, "pending action not found")

    reply = "Okay."
    if pa.source == "hermes" and pa.runId and pa.requestId:
        await _forward_hermes_approval(pa.runId, pa.requestId, pa.executionGeneration, req.choice)
        reply = "Going ahead." if req.choice != "deny" else "Okay, I stopped it."
    elif pa.source == "memory" and req.choice == "forget":
        deleted = store.forget_memory(memory_id=pa.meta.get("memory_id"), query=pa.meta.get("query"))
        asyncio.ensure_future(_trigger_hermes_forget(deleted))
        await hub.broadcast()
        reply = "It's gone — really gone." if deleted else "Nothing matched."
    elif pa.source == "inbox" and req.choice == "confirm_trash":
        nums = pa.meta.get("numbers") or []
        gmail_ids = pa.meta.get("gmail_ids") or []
        store.update_inbox_status(nums, "trashed")
        if gmail_ids and composio.configured:
            asyncio.ensure_future(composio.trash_gmail(gmail_ids))
        store.push_undo(
            label=f"Moved {len(nums)} newsletters to Trash",
            action_type="inbox_restore",
            payload={"numbers": nums, "gmail_ids": gmail_ids},
        )
        await hub.broadcast()
        reply = f"Moved {len(nums)} newsletters to Trash. Say 'undo that' anytime in the next minute."
    elif pa.source == "triage" and req.choice == "later":
        hub.next_greeting_queue.append({"title": pa.title, "summary": " · ".join(pa.summaryLines)})
        await hub.broadcast()
        reply = "I'll remind you in ten."

    return {"ok": True, "id": action_id, "choice": req.choice, "reply": reply}


class VerifyApprovalRequest(BaseModel):
    expected_source: str | None = None


@app.post("/os1/approvals/{action_id}/verify", dependencies=authed)
def verify_approval(action_id: str, req: VerifyApprovalRequest) -> dict[str, Any]:
    """Consume a one-time server-verified human approval token (used by os1_composio / tools)."""
    rec = hub.consume_approval_token(action_id, expected_source=req.expected_source)
    if rec is None:
        raise HTTPException(403, "approval_id is missing, expired, denied, or already consumed")
    return {"ok": True, "approved": True, "stakes": rec.get("stakes"), "meta": rec.get("meta") or {}}


class UndoRequest(BaseModel):
    undo_id: str | None = None


@app.post("/os1/undo", dependencies=authed)
async def run_undo(req: UndoRequest) -> dict[str, Any]:
    entry = store.consume_undo(req.undo_id)
    if entry is None:
        return {"ok": False, "reply": "Nothing recent to undo."}

    atype = entry["action_type"]
    payload = entry["payload"]
    if atype == "inbox_restore":
        store.update_inbox_status(payload.get("numbers", []), "active")
        gmail_ids = payload.get("gmail_ids") or []
        if gmail_ids and composio.configured:
            asyncio.ensure_future(composio.untrash_gmail(gmail_ids))
    elif atype == "voice_tweak":
        store.patch_profile(payload)
    await hub.broadcast()
    return {"ok": True, "undone": entry["label"], "reply": f"Undid: {entry['label']}."}


# ------------------------------------------------------------------ Memory Ledger (Paper 15)


class MemoryCreateRequest(BaseModel):
    category: str = "things_you_love"
    summary: str = Field(min_length=1, max_length=320)
    detail: str = ""
    source: str = "voice"


@app.get("/os1/memories", dependencies=authed)
def list_memories(category: str | None = None, query: str | None = None) -> dict[str, Any]:
    return {"categories": list(MEMORY_CATEGORIES), "items": store.list_memories(category=category, query=query)}


@app.post("/os1/memories", dependencies=authed)
async def create_memory(req: MemoryCreateRequest) -> dict[str, Any]:
    mem = store.add_memory(category=req.category, summary=req.summary, detail=req.detail, source=req.source)
    await hub.notify_remembered(mem)
    return mem


class ForgetRequest(BaseModel):
    memory_id: str | None = None
    query: str | None = None
    confirmed: bool = False


@app.post("/os1/memories/forget", dependencies=authed)
async def forget_memory(req: ForgetRequest) -> dict[str, Any]:
    """Two-step forget: without `confirmed=True`, opens the high-stakes read-back modal ('Yes, forget it')."""
    matches = (
        [m for m in store.list_memories(limit=200) if m["id"] == req.memory_id]
        if req.memory_id
        else store.list_memories(query=req.query, limit=10)
    )
    if not matches:
        return {"ok": False, "deleted": [], "message": "No matching memory found."}
    if not req.confirmed:
        pa = await hub.create_pending_action(
            source="memory",
            title="Forget this permanently?",
            summary_lines=[f"{m['category'].replace('_', ' ').title()}: {m['summary']}" for m in matches[:3]],
            stakes="forget",
            options=[
                {"phrase": "Yes, forget it", "choice": "forget"},
                {"phrase": "Keep it", "choice": "cancel"},
            ],
            meta={"memory_id": req.memory_id, "query": req.query},
        )
        return {"ok": True, "requires_confirmation": True, "pending_action": pa.to_dict()}

    deleted = store.forget_memory(memory_id=req.memory_id, query=req.query)
    asyncio.ensure_future(_trigger_hermes_forget(deleted))
    await hub.broadcast()
    return {"ok": True, "deleted": deleted}


# ------------------------------------------------------------------ Connectors (Composio) & Triggers (Paper 13)


@app.get("/os1/connectors", dependencies=authed)
def list_connectors() -> dict[str, Any]:
    return {"composioConfigured": bool(os.environ.get("COMPOSIO_API_KEY")), "items": store.list_connectors()}


class ConnectorPatchRequest(BaseModel):
    policy: str | None = None
    connected: bool | None = None
    account_label: str | None = None
    label: str | None = None


@app.patch("/os1/connectors/{slug}", dependencies=authed)
async def patch_connector(slug: str, req: ConnectorPatchRequest) -> dict[str, Any]:
    if req.policy and req.policy not in CONNECTOR_POLICIES:
        raise HTTPException(400, f"policy must be one of {CONNECTOR_POLICIES}")
    updated = store.upsert_connector(
        slug, policy=req.policy, connected=req.connected, account_label=req.account_label, label=req.label
    )
    await hub.broadcast()
    return updated


@app.post("/os1/connectors/{slug}/connect", dependencies=authed)
async def connect_connector(slug: str) -> dict[str, Any]:
    """Generate a Composio v3 Connect Link and start polling for completion (auto-opens Spatial Inbox for Gmail)."""
    return await _start_connector_flow(slug)


@app.post("/os1/webhooks/composio")
async def composio_webhook(request: Request) -> dict[str, Any]:
    """Composio trigger webhook → Jev attention triage. Fails closed if COMPOSIO_WEBHOOK_SECRET is unset."""
    raw = await request.body()
    secret = os.environ.get("COMPOSIO_WEBHOOK_SECRET", "").strip()
    allow_unsigned = os.environ.get("OS1_ALLOW_UNSIGNED_WEBHOOKS", "0") == "1"
    if not secret:
        if not allow_unsigned:
            raise HTTPException(
                503,
                "COMPOSIO_WEBHOOK_SECRET is not set; refusing unsigned webhook (set OS1_ALLOW_UNSIGNED_WEBHOOKS=1 only in local tests)",
            )
    else:
        sig = request.headers.get("x-composio-signature", "") or request.headers.get("webhook-signature", "")
        expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not sig or not secrets.compare_digest(sig.removeprefix("sha256="), expected):
            raise HTTPException(401, "invalid webhook signature")

    event = json.loads(raw.decode() or "{}")
    triage = await director.triage_trigger(event, user_busy=hub.active_surface != "home")
    urgency = triage["urgency"]
    title = str(event.get("title") or event.get("type") or "Incoming update")
    summary = str(event.get("summary") or event.get("snippet") or "")

    store.add_activity(source="trigger", title=title, detail=f"[{urgency}] {summary}", status="done")
    if urgency == "medium":
        hub.next_greeting_queue.append({"title": title, "summary": summary})
        await hub.broadcast()
    elif urgency == "high":
        await hub.create_pending_action(
            source="triage",
            title="Sorry — can I interrupt?",
            summary_lines=[title, summary] if summary else [title],
            stakes="shared",
            options=[
                {"phrase": "Go ahead", "choice": "accept"},
                {"phrase": "In ten", "choice": "later"},
            ],
        )
    return {"ok": True, "urgency": urgency, "source": triage["source"]}


# ------------------------------------------------------------------ Spatial Inbox (Paper 07/08)


class InboxSyncRequest(BaseModel):
    items: list[dict[str, Any]]


@app.get("/os1/inbox", dependencies=authed)
def get_inbox() -> dict[str, Any]:
    return {"items": store.list_inbox()}


@app.post("/os1/inbox/sync", dependencies=authed)
async def sync_inbox(req: InboxSyncRequest) -> dict[str, Any]:
    scored = await director.score_inbox_items(req.items)
    saved = store.set_inbox_items(scored)
    await hub.broadcast()
    return {"ok": True, "count": len(saved), "items": saved}


# ------------------------------------------------------------------ Voice Registry (Paper 14)


@app.get("/os1/voices", dependencies=authed)
def get_voices() -> dict[str, Any]:
    prof = read_profile()
    return {
        "active": {
            "voiceKey": prof.get("voice_key", "voice_1_warm"),
            "speed": prof.get("voice_speed", 0.96),
            "temperature": prof.get("voice_temperature", 0.72),
            "styleNote": prof.get("voice_style_note", ""),
        },
        "presets": [
            {"key": "voice_1_warm", "name": "Voice I", "subtitle": "Warm · intimate · Drama 3", "speed": 0.96, "temperature": 0.72},
            {"key": "voice_2_bright", "name": "Voice II", "subtitle": "Bright · quick · Drama 3", "speed": 1.05, "temperature": 0.65},
            {"key": "voice_male", "name": "Voice III", "subtitle": "Grounded · calm · Drama 3", "speed": 0.97, "temperature": 0.68},
        ],
    }


class VoicePatchRequest(BaseModel):
    voiceKey: str | None = None
    speed: float | None = None
    temperature: float | None = None
    styleNote: str | None = None


@app.patch("/os1/voices", dependencies=authed)
async def patch_voices(req: VoicePatchRequest) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if req.voiceKey is not None:
        updates["voice_key"] = req.voiceKey
    if req.speed is not None:
        updates["voice_speed"] = max(0.75, min(1.3, round(req.speed, 2)))
    if req.temperature is not None:
        updates["voice_temperature"] = max(0.3, min(1.0, round(req.temperature, 2)))
    if req.styleNote is not None:
        updates["voice_style_note"] = req.styleNote
    if updates:
        store.patch_profile(updates)
        await hub.broadcast()
    return get_voices()


# ------------------------------------------------------------------ Her Computer — Orgo + noVNC Proxy (Paper 10)


@app.get("/os1/her-computer/status", dependencies=authed)
def her_computer_status() -> dict[str, Any]:
    return {
        "online": True,
        "computerId": os.environ.get("ORGO_COMPUTER_ID", ""),
        "resolution": "1920x1080",
        "activity": store.list_activity(source="her_computer", limit=25),
    }


class ActivityCreateRequest(BaseModel):
    source: str = "her_computer"
    title: str
    detail: str = ""
    status: str = "done"


@app.post("/os1/her-computer/activity", dependencies=authed)
async def post_activity(req: ActivityCreateRequest) -> dict[str, Any]:
    item = store.add_activity(source=req.source, title=req.title, detail=req.detail, status=req.status)
    await hub.broadcast()
    return item


@app.post("/os1/her-computer/vnc-session", dependencies=authed)
async def her_computer_vnc_session() -> dict[str, Any]:
    """Fetch Orgo's VNC password server-side (never shipped in client bundle) and return proxy WS path."""
    api_key = os.environ.get("ORGO_API_KEY", "")
    cid = os.environ.get("ORGO_COMPUTER_ID", "")
    password = ""
    if api_key and cid:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(
                    f"https://www.orgo.ai/api/computers/{cid}/vnc-password",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if r.is_success:
                    password = str(r.json().get("password") or "")
        except Exception as exc:  # noqa: BLE001
            log.warning("orgo vnc-password fetch failed: %s", exc)
    return {
        "wsPath": "/os1/her-computer/vnc",
        "password": password,
        "readOnlyDefault": True,
        "resolution": "1920x1080",
    }


@app.websocket("/os1/her-computer/vnc")
async def her_computer_vnc_proxy(websocket: WebSocket, token: str = "") -> None:
    """Authenticated binary WebSocket proxy from desktop noVNC client → VM localhost:6080 websockify."""
    auth = token or websocket.headers.get("authorization", "")
    if not _check_token(auth):
        await websocket.close(code=4401)
        return
    subprotocols = websocket.headers.get("sec-websocket-protocol", "")
    chosen = "binary" if "binary" in subprotocols else None
    await websocket.accept(subprotocol=chosen)
    try:
        async with websockets.connect(
            VNC_UPSTREAM_WS,
            subprotocols=["binary"] if chosen else None,
            max_size=None,
        ) as upstream:

            async def client_to_vnc() -> None:
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("bytes") is not None:
                        await upstream.send(msg["bytes"])
                    elif msg.get("text") is not None:
                        await upstream.send(msg["text"])

            async def vnc_to_client() -> None:
                async for data in upstream:
                    if isinstance(data, bytes):
                        await websocket.send_bytes(data)
                    else:
                        await websocket.send_text(data)

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_vnc()), asyncio.create_task(vnc_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            for t in done:
                t.exception() if not t.cancelled() else None
    except Exception as exc:  # noqa: BLE001
        log.debug("vnc proxy ended: %s", exc)
    finally:
        try:
            await websocket.close()
        except Exception as exc:  # noqa: BLE001
            log.debug("vnc websocket close ignored: %s", exc)


# ------------------------------------------------------------------ Your Computer — Cua Outbound Tunnel (Paper 09)


@app.get("/os1/your-computer/status", dependencies=authed)
def your_computer_status() -> dict[str, Any]:
    return {
        "connected": hub.cua_ws is not None,
        "status": hub.cua_status,
        "manifest": hub.cua_manifest,
        "recentActivity": store.list_activity(source="your_computer", limit=20),
    }


@app.websocket("/os1/your-computer/tunnel")
async def your_computer_tunnel(websocket: WebSocket, token: str = "") -> None:
    """Outbound authenticated WebSocket tunnel opened BY the desktop Electron app's embedded Cua Driver."""
    auth = token or websocket.headers.get("authorization", "")
    if not _check_token(auth):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    hub.cua_ws = websocket
    hub.cua_status = "ready"
    await hub.broadcast()
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "hello" and isinstance(msg.get("manifest"), dict):
                hub.cua_manifest = msg["manifest"]
                await hub.broadcast()
            elif mtype == "result":
                cid = str(msg.get("id") or "")
                fut = hub.cua_pending_calls.get(cid)
                if fut and not fut.done():
                    fut.set_result(msg.get("result") or {"ok": True})
            elif mtype == "activity":
                store.add_activity(
                    source="your_computer",
                    title=str(msg.get("title") or "Action"),
                    detail=str(msg.get("detail") or ""),
                    status=str(msg.get("status") or "done"),
                )
                await hub.broadcast()
    except WebSocketDisconnect:
        pass
    finally:
        if hub.cua_ws is websocket:
            hub.cua_ws = None
            hub.cua_status = "disconnected"
        await hub.broadcast()


class CuaCallRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    requireApproval: bool = True
    description: str = ""


@app.post("/os1/your-computer/call", dependencies=authed)
async def your_computer_call(req: CuaCallRequest) -> dict[str, Any]:
    """Called by Hermes's `user_computer` MCP bridge; gates mutations behind `computer` PendingAction."""
    if hub.cua_ws is None:
        raise HTTPException(503, "User computer Cua Driver tunnel is not connected.")
    if req.requireApproval:
        pa = await hub.create_pending_action(
            source="cua",
            title=f"On your Mac: {req.tool}",
            summary_lines=[req.description or json.dumps(req.arguments)[:160]],
            stakes="computer",
            options=[
                {"phrase": "Go ahead", "choice": "allow"},
                {"phrase": "Let me drive", "choice": "deny"},
            ],
        )
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        hub.action_waiters[pa.id] = fut
        try:
            choice = await asyncio.wait_for(fut, timeout=90.0)
        except TimeoutError:
            await hub.resolve_pending_action(pa.id, "deny")
            return {"ok": False, "error": "Approval timed out."}
        if choice != "allow":
            return {"ok": False, "error": "Denied by user."}
    return await hub.call_cua(req.tool, req.arguments)


@app.post("/os1/your-computer/revoke", dependencies=authed)
async def your_computer_revoke() -> dict[str, Any]:
    return await hub.revoke_cua()


# ------------------------------------------------------------------ Infisical Self-Managing Vault


class VaultRotateRequest(BaseModel):
    keys: list[str] | None = None


@app.get("/os1/vault/status", dependencies=authed)
def vault_status() -> dict[str, Any]:
    return vault.status()


@app.post("/os1/vault/rotate-internal", dependencies=authed)
async def vault_rotate_internal(req: VaultRotateRequest) -> dict[str, Any]:
    try:
        res = await vault.rotate_internal_keys(req.keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    store.add_activity(
        source="vault",
        title=f"Rotated {len(res['rotated'])} internal keys",
        detail=", ".join(item["key"] for item in res["rotated"]),
        status="done",
    )
    await hub.broadcast()
    return res


# ------------------------------------------------------------------ Tailscale + Hostinger + Maus Bots Ops Bridge


class BotControlRequest(BaseModel):
    action: str  # status | logs | restart | start | stop
    tail_lines: int = 80
    dry_run: bool = False
    approval_id: str | None = None


@app.get("/os1/ops/status", dependencies=authed)
def ops_status() -> dict[str, Any]:
    return ops_bridge.status()


@app.get("/os1/ops/vps", dependencies=authed)
async def ops_vps_info() -> dict[str, Any]:
    return await ops_bridge.hostinger_vps_info()


@app.post("/os1/ops/bots/{bot_name}", dependencies=authed)
async def ops_control_bot(bot_name: str, req: BotControlRequest) -> dict[str, Any]:
    mutating = req.action in ("restart", "start", "stop")
    if mutating and not req.dry_run:
        if not req.approval_id:
            pa = await hub.create_pending_action(
                source="ops",
                title=f"{req.action.title()} Maus Bot `{bot_name}`?",
                summary_lines=[f"Target bot: {bot_name}", f"Action: {req.action}"],
                stakes="shared",
                options=[
                    {"phrase": f"Yes, {req.action} {bot_name}", "choice": "approve"},
                    {"phrase": "Cancel", "choice": "deny"},
                ],
            )
            return {
                "ok": False,
                "approval_required": True,
                "pending_action": pa.to_dict(),
                "reply": f"Confirmation required before running `{req.action}` on {bot_name}.",
            }
        # Verify one-time approval token if supplied
        ver = await verify_approval(req.approval_id)
        if not ver.get("approved"):
            raise HTTPException(403, f"Approval `{req.approval_id}` is not approved")

    try:
        res = await ops_bridge.control_bot(bot_name, req.action, dry_run=req.dry_run, tail_lines=req.tail_lines)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    store.add_activity(
        source="ops",
        title=f"Maus Bot {bot_name}: {req.action}",
        detail="dry-run" if req.dry_run else ("ok" if res.get("ok") else str(res.get("error") or res.get("stderr", ""))[:120]),
        status="done" if res.get("ok") else "failed",
    )
    await hub.broadcast()
    return res


# ------------------------------------------------------------------ pstack Self-Building & Self-Updating Engine


class PstackRunRequest(BaseModel):
    goal: str
    dry_run: bool = True


@app.get("/os1/pstack/status", dependencies=authed)
def pstack_status() -> dict[str, Any]:
    return pstack_updater.status()


@app.post("/os1/pstack/plan", dependencies=authed)
def pstack_plan(req: PstackRunRequest) -> dict[str, Any]:
    return route_poteto_mode(req.goal)


@app.post("/os1/pstack/run", dependencies=authed)
async def pstack_run(req: PstackRunRequest) -> dict[str, Any]:
    res = await pstack_updater.dispatch_to_opencode(req.goal, dry_run=req.dry_run)
    store.add_activity(
        source="pstack",
        title=f"pstack ({res['brief']['playbook']}): {req.goal[:60]}",
        detail=res["brief"]["branch"],
        status="done" if res.get("ok") else "failed",
    )
    await hub.broadcast()
    return res


# ------------------------------------------------------------------ Second Brain SQLite LLM Wiki & Knowledge Graph


class WikiPageUpsertRequest(BaseModel):
    slug: str
    title: str
    body: str
    kind: str = "note"
    tags: list[str] = Field(default_factory=list)
    source_path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class WikiIngestRequest(BaseModel):
    directory: str | None = None
    kind: str = "second_brain"
    max_files: int = 300


@app.get("/os1/wiki/pages", dependencies=authed)
def wiki_list_pages(kind: str | None = None, limit: int = 100) -> dict[str, Any]:
    return {"pages": wiki.list_pages(kind=kind, limit=limit)}


@app.get("/os1/wiki/page/{slug:path}", dependencies=authed)
def wiki_get_page(slug: str) -> dict[str, Any]:
    page = wiki.get_page(slug)
    if page is None:
        raise HTTPException(404, f"Wiki page not found: {slug}")
    return page


@app.post("/os1/wiki/pages", dependencies=authed)
async def wiki_upsert_page(req: WikiPageUpsertRequest) -> dict[str, Any]:
    saved = wiki.upsert_page(
        slug=req.slug,
        title=req.title,
        body=req.body,
        kind=req.kind,
        source_path=req.source_path,
        tags=req.tags,
        metadata=req.metadata,
    )
    store.add_activity(source="wiki", title=f"Updated wiki: {saved['title']}", detail=saved["slug"], status="done")
    await hub.broadcast()
    return saved


@app.post("/os1/wiki/ingest", dependencies=authed)
async def wiki_ingest(req: WikiIngestRequest) -> dict[str, Any]:
    default_dir = os.environ.get("OS1_SECOND_BRAIN_DIR") or str(Path(__file__).resolve().parents[3] / "icm")
    target = Path(req.directory or default_dir)
    res = wiki.ingest_directory(target, kind=req.kind, max_files=req.max_files)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "Ingest failed"))
    store.add_activity(source="wiki", title=f"Ingested {res['ingested']} Second Brain notes", detail=str(target), status="done")
    await hub.broadcast()
    return res


@app.get("/os1/wiki/search", dependencies=authed)
def wiki_search(q: str, limit: int = 12) -> dict[str, Any]:
    return {"query": q, "results": wiki.search(q, limit=limit)}


@app.get("/os1/wiki/graph", dependencies=authed)
def wiki_graph() -> dict[str, Any]:
    return wiki.get_graph()


@app.get("/os1/wiki/connections", dependencies=authed)
def wiki_connections(limit: int = 10) -> dict[str, Any]:
    return {"recommendations": wiki.recommend_connections(limit=limit)}


# ------------------------------------------------------------------ Full GitHub Access & Cross-Project Graph


@app.get("/os1/github/repos", dependencies=authed)
async def github_list_repos(limit: int = 100) -> dict[str, Any]:
    try:
        repos = await github_graph.list_repos(limit=limit)
    except Exception as exc:
        raise HTTPException(502, f"GitHub API error: {exc}") from exc
    return {"owner": github_graph.owner, "authenticated": github_graph.configured, "count": len(repos), "repos": repos}


@app.post("/os1/github/sync-wiki", dependencies=authed)
async def github_sync_wiki(limit: int = 100) -> dict[str, Any]:
    try:
        res = await github_graph.sync_repos_to_wiki(wiki, limit=limit)
    except Exception as exc:
        raise HTTPException(502, f"GitHub sync failed: {exc}") from exc
    store.add_activity(
        source="github",
        title=f"Indexed {res['repos_indexed']} GitHub repos into wiki",
        detail=f"{res['edges_added']} cross-repo edges",
        status="done",
    )
    await hub.broadcast()
    return res


@app.get("/os1/github/connections", dependencies=authed)
def github_connections(limit: int = 12) -> dict[str, Any]:
    return {
        "owner": github_graph.owner,
        "graph": wiki.get_graph()["stats"],
        "recommendations": wiki.recommend_connections(limit=limit),
    }


# ------------------------------------------------------------------ VisionClaw AX-022 (Glasses + Laptop Camera + Holo Gestures)


class VisionGestureRequest(BaseModel):
    gesture: str | None = None
    landmarks: list[dict[str, float]] | None = None
    source: str = "laptop_camera"


class VisionFrameRequest(BaseModel):
    source: str = "laptop_camera"
    width: int = 0
    height: int = 0
    summary: str = ""


@app.get("/os1/vision/status", dependencies=authed)
def vision_status() -> dict[str, Any]:
    return vision_bridge.status()


@app.post("/os1/vision/frame", dependencies=authed)
def vision_frame(req: VisionFrameRequest) -> dict[str, Any]:
    return vision_bridge.record_frame(source=req.source, width=req.width, height=req.height, summary=req.summary)


@app.post("/os1/vision/gesture", dependencies=authed)
async def vision_gesture(req: VisionGestureRequest) -> dict[str, Any]:
    ev = vision_bridge.resolve_gesture(
        gesture=req.gesture,
        landmarks=req.landmarks,
        source=req.source,
        active_surface=hub.active_surface,
    )
    if not ev.get("matched"):
        return ev
    if ev["target"] in ("surface", "cua"):
        await _dispatch_matched(ev["target"], ev["action"], {}, phrase=ev["gesture"])
    store.add_activity(
        source="visionclaw",
        title=f"Holo gesture: {ev['gesture']} ({ev['source']})",
        detail=ev["reply"],
        status="done",
    )
    await hub.broadcast()
    return ev


# ------------------------------------------------------------------ 24/7 Web / PWA Static Mount (optional)

_WEB_DIST = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "dist-web"
if _WEB_DIST.exists() and (_WEB_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="os1-web-pwa")
