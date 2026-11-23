"""Contract tests for browser-session authentication across both Vercel services."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def auth_modules(monkeypatch):
    monkeypatch.setenv("OS1_WEB_LOGIN_PASSWORD", "test-only-passphrase-not-production")
    monkeypatch.setenv("OS1_WEB_SESSION_SECRET", "test-only-secret-key-strong-enough-for-ci-" * 3)
    orch = load(ROOT / "services/orchestrator/os1_orchestrator/web_auth.py", "test_orch_web_auth")
    voice = load(ROOT / "services/voice/os1_voice/web_auth.py", "test_voice_web_auth")
    return orch, voice


def test_signed_cookie_works_across_services(auth_modules):
    orch, voice = auth_modules
    assert orch.check_password("test-only-passphrase-not-production")
    assert not orch.check_password("wrong")
    cookie = orch.make_cookie()
    assert orch.verify_cookie(cookie)
    assert voice.verify_cookie(cookie)
    assert not voice.verify_cookie(cookie + "tampered")


def test_signature_does_not_survive_key_rotation(auth_modules, monkeypatch):
    orch, voice = auth_modules
    cookie = orch.make_cookie()
    monkeypatch.setenv("OS1_WEB_SESSION_SECRET", "rotated-test-secret" * 8)
    assert not orch.verify_cookie(cookie)
    assert not voice.verify_cookie(cookie)


def test_auth_fails_closed_without_config(auth_modules, monkeypatch):
    orch, voice = auth_modules
    cookie = orch.make_cookie()
    monkeypatch.delenv("OS1_WEB_LOGIN_PASSWORD")
    assert not orch.check_password("test-only-passphrase-not-production")
    assert not voice.verify_cookie(cookie)
    monkeypatch.delenv("OS1_WEB_SESSION_SECRET")
    assert not orch.verify_cookie(cookie)


def test_cookie_expiry(auth_modules, monkeypatch):
    orch, voice = auth_modules
    start = 1800000000
    monkeypatch.setattr(orch.time, "time", lambda: start)
    cookie = orch.make_cookie()
    monkeypatch.setattr(orch.time, "time", lambda: start + orch.TTL_SECONDS + 1)
    assert not orch.verify_cookie(cookie)
    assert not voice.verify_cookie(cookie)
