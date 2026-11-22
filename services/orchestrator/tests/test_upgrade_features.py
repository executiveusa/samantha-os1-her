"""Behavioral tests for Samantha OS1 upgrade: pills fix, Infisical vault, Ops Bridge, and pstack."""

from __future__ import annotations

from fastapi.testclient import TestClient

from os1_orchestrator import app as mod
from os1_orchestrator.pills import match_pill


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {mod.CLIENT_TOKEN}"}


def test_voice_navigation_pills_fix_video_desync_phrases():
    cases = {
        "please take me to the cloud": ("surface", "her_computer"),
        "open cloud": ("surface", "her_computer"),
        "take me to my mac": ("surface", "your_computer"),
        "take me to swarm": ("surface", "swarm"),
        "take me to canvas": ("surface", "made_just_now"),
        "take me to memory": ("surface", "memory"),
        "go to talk": ("surface", "conversation"),
        "back to talking": ("surface", "conversation"),
        "pull up the emails": ("inbox", "open_inbox"),
    }
    for phrase, expected in cases.items():
        hit = match_pill(phrase, [])
        assert hit is not None, f"Expected match for {phrase!r}"
        assert (hit.target, hit.action) == expected, f"Mismatch for {phrase!r}: got {(hit.target, hit.action)}"


def test_vault_status_and_internal_rotation_never_expose_secrets():
    client = TestClient(mod.app)
    r = client.get("/os1/vault/status", headers=_headers())
    assert r.status_code == 200
    body = r.json()
    assert "internal_keys" in body
    assert "external_keys" in body
    # Ensure booleans only — never raw secret strings
    assert all(isinstance(v, bool) for v in body["internal_keys"].values())

    rot = client.post("/os1/vault/rotate-internal", headers=_headers(), json={"keys": ["OPENCODE_SERVER_PASSWORD"]})
    assert rot.status_code == 200
    rdata = rot.json()
    assert rdata["ok"] is True
    assert rdata["rotated"][0]["key"] == "OPENCODE_SERVER_PASSWORD"
    assert "secretValue" not in str(rdata)

    bad = client.post("/os1/vault/rotate-internal", headers=_headers(), json={"keys": ["NOT_A_REAL_KEY"]})
    assert bad.status_code == 400


def test_ops_bridge_maus_bots_status_dry_run_and_approval_gate():
    client = TestClient(mod.app)
    st = client.get("/os1/ops/status", headers=_headers())
    assert st.status_code == 200
    bots = [b["name"] for b in st.json()["maus_bots"]]
    assert "maus-core" in bots

    # Dry-run restart returns command preview without executing SSH
    dry = client.post(
        "/os1/ops/bots/maus-core",
        headers=_headers(),
        json={"action": "restart", "dry_run": True},
    )
    assert dry.status_code == 200
    assert dry.json()["dry_run"] is True

    # Live mutation without approval_id must gate behind PendingAction
    gated = client.post(
        "/os1/ops/bots/maus-core",
        headers=_headers(),
        json={"action": "restart", "dry_run": False},
    )
    assert gated.status_code == 200
    gdata = gated.json()
    assert gdata["ok"] is False
    assert gdata["approval_required"] is True
    assert gdata["pending_action"]["source"] == "ops"

    # Unknown bot returns 404
    missing = client.post(
        "/os1/ops/bots/nonexistent-bot",
        headers=_headers(),
        json={"action": "status", "dry_run": True},
    )
    assert missing.status_code == 404


def test_pstack_status_plan_and_dry_run():
    client = TestClient(mod.app)
    st = client.get("/os1/pstack/status", headers=_headers())
    assert st.status_code == 200
    assert st.json()["installed"] is True
    assert "poteto-mode" in st.json()["playbooks"]

    plan = client.post(
        "/os1/pstack/plan",
        headers=_headers(),
        json={"goal": "fix voice surface desync bug"},
    )
    assert plan.status_code == 200
    assert plan.json()["playbook"] == "bugfix"
    assert plan.json()["branch"].startswith("self-update/")

    run = client.post(
        "/os1/pstack/run",
        headers=_headers(),
        json={"goal": "upgrade free llm router", "dry_run": True},
    )
    assert run.status_code == 200
    assert run.json()["ok"] is True
    assert run.json()["dry_run"] is True
