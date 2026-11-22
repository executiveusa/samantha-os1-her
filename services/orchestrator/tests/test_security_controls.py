"""Security tests for fail-closed auth, one-time approval verification, payment caps, and allowlists."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient


def _load_composio_plugin():
    p = Path(__file__).resolve().parents[3] / "hermes" / "plugins" / "os1_composio" / "__init__.py"
    spec = importlib.util.spec_from_file_location("os1_composio_test", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_auth_fails_closed_when_token_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("OS1_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OS1_CLIENT_TOKEN", "")
    monkeypatch.setenv("OS1_DEV_NO_AUTH", "0")
    monkeypatch.setenv("JEV_TRANSPORT", "mock")
    import os1_orchestrator.app as app_module

    importlib.reload(app_module)
    c = TestClient(app_module.app)
    assert c.get("/health").status_code == 200
    assert c.get("/os1/state").status_code == 503


def test_one_time_approval_token_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("OS1_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("OS1_CLIENT_TOKEN", "tok-sec")
    monkeypatch.setenv("JEV_TRANSPORT", "mock")
    import os1_orchestrator.app as app_module

    importlib.reload(app_module)
    c = TestClient(app_module.app, headers={"Authorization": "Bearer tok-sec"})

    pa = c.post("/os1/approvals", json={"source": "composio", "title": "Send email", "stakes": "shared"}).json()
    aid = pa["id"]

    # Before human approval, verify fails (403)
    assert c.post(f"/os1/approvals/{aid}/verify", json={"expected_source": "composio"}).status_code == 403

    # Human approves
    assert c.post(f"/os1/approvals/{aid}/respond", json={"choice": "allow"}).status_code == 200

    # First verify succeeds and consumes the one-time token
    assert c.post(f"/os1/approvals/{aid}/verify", json={"expected_source": "composio"}).status_code == 200
    # Replay fails (403)
    assert c.post(f"/os1/approvals/{aid}/verify", json={"expected_source": "composio"}).status_code == 403


def test_composio_payment_cap_units_and_recipient_allowlist(monkeypatch):
    mod = _load_composio_plugin()
    monkeypatch.setenv("OS1_MAX_PAYMENT_USD", "25.00")
    monkeypatch.setenv("OS1_ALLOWED_RECIPIENTS", "mom@example.com,erin@example.com")

    # Ambiguous bare `amount` rejected
    r1 = json.loads(mod.handle_composio_action({"toolkit": "stripe", "action_slug": "STRIPE_CHARGE", "arguments": {"amount": 10}}))
    assert r1["blocked_by_cap"] is True

    # Over-cap payment rejected
    r2 = json.loads(
        mod.handle_composio_action(
            {"toolkit": "stripe", "action_slug": "STRIPE_CHARGE", "arguments": {"currency": "USD", "amount_usd": 40.0}}
        )
    )
    assert r2["blocked_by_cap"] is True

    # Unlisted recipient rejected
    r3 = json.loads(
        mod.handle_composio_action(
            {"toolkit": "gmail", "action_slug": "GMAIL_SEND_EMAIL", "arguments": {"to": "stranger@evil.test"}}
        )
    )
    assert r3["blocked_by_allowlist"] is True
