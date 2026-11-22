from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OS1_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "devsecret-devsecret-devsecret-devsecret")
    monkeypatch.setenv("OS1_CLIENT_TOKEN", "test-token")
    monkeypatch.setenv("JEV_TRANSPORT", "mock")
    monkeypatch.setenv("HERMES_API_URL", "")
    import os1_orchestrator.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app, headers={"Authorization": "Bearer test-token"})


def test_memory_ledger_and_two_step_forget(client):
    created = client.post(
        "/os1/memories",
        json={"category": "places", "summary": "Watched the sunset at Ocean Beach", "detail": "Cold wind, warm coffee"},
    ).json()
    assert created["id"].startswith("mem_")
    assert len(client.get("/os1/memories").json()["items"]) == 1

    # Unconfirmed forget opens a high-stakes read-back PendingAction
    step1 = client.post("/os1/memories/forget", json={"query": "Ocean Beach"}).json()
    assert step1["requires_confirmation"] is True
    pa = step1["pending_action"]
    assert pa["stakes"] == "forget"

    # Speaking "Yes, forget it" resolves the PendingAction via zero-LLM pill matcher and truly deletes it
    res = client.post("/os1/actions", json={"phrase": "Yes, forget it", "source": "voice"}).json()
    assert res["matched"] is True
    assert client.get("/os1/memories").json()["items"] == []


def test_generative_ui_canvas_validation_and_pill_match(client):
    resp = client.post(
        "/os1/canvas",
        json={
            "title": "Two ferries to Sausalito",
            "cards": [
                {
                    "kind": "ChoicePairCard",
                    "id": "ferry",
                    "prompt": "Which boat works better?",
                    "left": {"title": "10:30 AM", "detail": "Sunny deck", "speakablePhrase": "The 10:30"},
                    "right": {"title": "1:45 PM", "detail": "After lunch", "speakablePhrase": "The 1:45"},
                }
            ],
        },
    )
    assert resp.status_code == 200
    state = client.get("/os1/state").json()
    assert state["activeSurface"] == "made_just_now"
    assert "The 1:45" in state["visiblePhrases"]

    hit = client.post("/os1/actions", json={"phrase": "yeah, the 1:45", "source": "voice"}).json()
    assert hit["matched"] is True
    assert hit["target"] == "canvas"
    assert hit["phrase"] == "The 1:45"


def test_director_hysteresis_and_mood(client):
    # High-need turn opens surface immediately
    t1 = client.post("/os1/director/tick", json={"latest": "Can you show me my inbox?"}).json()
    assert t1["activeSurface"] == "inbox_cascade"
    assert t1["surfaceChanged"] is True

    # First low-need turn holds surface (anti-flicker hysteresis needs 2 consecutive low ticks)
    t2 = client.post("/os1/director/tick", json={"latest": "Hmm yeah I like rainy days"}).json()
    assert t2["activeSurface"] == "inbox_cascade"

    # Second consecutive low-need turn dismisses cleanly back to calm conversation
    t3 = client.post("/os1/director/tick", json={"latest": "Tell me a joke"}).json()
    assert t3["activeSurface"] == "conversation"


def test_inbox_scoring_trash_and_60s_undo(client):
    synced = client.post(
        "/os1/inbox/sync",
        json={
            "items": [
                {"sender": "Mom", "subject": "Dinner this Sunday?", "snippet": "Love to see you"},
                {"sender": "Deals Newsletter", "subject": "50% off sale — unsubscribe", "snippet": "Promo"},
            ]
        },
    ).json()
    assert synced["count"] == 2
    items = synced["items"]
    assert items[0]["keeper_score"] > items[1]["keeper_score"]

    # Switch to inbox and voice-archive #2
    client.post("/os1/actions", json={"target": "surface", "action": "inbox_cascade"})
    r = client.post("/os1/actions", json={"phrase": "archive number two", "source": "voice"}).json()
    assert r["matched"] is True
    assert len(client.get("/os1/inbox").json()["items"]) == 1

    # Say "undo that" within 60 seconds → restores #2
    u = client.post("/os1/actions", json={"phrase": "undo that", "source": "voice"}).json()
    assert u["matched"] is True
    assert len(client.get("/os1/inbox").json()["items"]) == 2


def test_connectors_policies_and_webhook_triage(client, monkeypatch):
    import hashlib
    import hmac

    updated = client.patch("/os1/connectors/gmail", json={"connected": True, "policy": "read_only"}).json()
    assert updated["connected"] is True
    assert updated["spoken_status"] == "Mail · read only"

    body = json.dumps({"title": "Urgent message from Mom", "summary": "Flight moved up 2 hours"}).encode()

    # Without COMPOSIO_WEBHOOK_SECRET, webhook MUST fail closed (503).
    monkeypatch.delenv("COMPOSIO_WEBHOOK_SECRET", raising=False)
    assert client.post("/os1/webhooks/composio", content=body, headers={"Content-Type": "application/json"}).status_code == 503

    # With secret + valid HMAC signature, high-urgency webhook triggers "Sorry — can I interrupt?" modal.
    monkeypatch.setenv("COMPOSIO_WEBHOOK_SECRET", "whsec_test_123")
    sig = hmac.new(b"whsec_test_123", body, hashlib.sha256).hexdigest()
    wh = client.post(
        "/os1/webhooks/composio",
        content=body,
        headers={"Content-Type": "application/json", "x-composio-signature": f"sha256={sig}"},
    ).json()
    assert wh["urgency"] == "high"
    pa = client.get("/os1/state").json()["pendingAction"]
    assert pa is not None and "interrupt" in pa["title"].lower()


def test_ws_events_and_cua_tunnel_revoke(client):
    with client.websocket_connect("/os1/events?token=test-token") as ws:
        snap = json.loads(ws.receive_text())
        assert snap["type"] == "snapshot"
        assert "connectors" in snap

    with client.websocket_connect("/os1/your-computer/tunnel?token=test-token") as cua_ws:
        assert client.get("/os1/your-computer/status").json()["connected"] is True
        rev = client.post("/os1/actions", json={"phrase": "let me drive", "source": "voice"}).json()
        assert rev["matched"] is True
        msg = json.loads(cua_ws.receive_text())
        assert msg["type"] == "revoke"
