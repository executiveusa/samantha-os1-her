from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OS1_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "devkey")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "devsecret-devsecret-devsecret-devsecret")
    monkeypatch.setenv("OS1_CLIENT_TOKEN", "test-token")
    import os1_orchestrator.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app, headers={"Authorization": "Bearer test-token"})


def test_profile_roundtrip_and_reset(client):
    assert client.get("/os1/profile").json()["onboarded"] is False
    client.patch("/os1/profile", json={"name": "Theo", "onboarded": True, "voice_key": "voice_male"})
    assert client.get("/os1/profile").json()["voice_key"] == "voice_male"
    reset = client.post("/os1/dev/reset-onboarding").json()
    assert reset["name"] == "Theo" and reset["onboarded"] is False and reset["voice_key"] == "voice_1_warm"


def test_token_dispatches_agent_and_saves_name(client):
    resp = client.post("/os1/token", json={"name": "Theo"}).json()
    assert resp["engine"] == "drama3"
    assert resp["url"].startswith("wss://") and resp["token"].count(".") == 2
    assert client.get("/os1/profile").json()["name"] == "Theo"


def test_requires_token(client):
    assert client.get("/health").status_code == 200
    assert client.get("/os1/profile", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/os1/token", json={}, headers={"Authorization": ""}).status_code == 401
