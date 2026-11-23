"""Short-lived, signed browser login cookie; never contains an API key.

Keep this module byte-identical in orchestrator and voice packages so a session
created by orchestrator can authorize session poll/event endpoints on voice.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

COOKIE_NAME = "os1_web_session"
TTL_SECONDS = 12 * 3600


def configured() -> bool:
    return bool(os.environ.get("OS1_WEB_LOGIN_PASSWORD") and os.environ.get("OS1_WEB_SESSION_SECRET"))


def _key() -> bytes:
    return os.environ.get("OS1_WEB_SESSION_SECRET", "").encode("utf-8")


def check_password(password: str) -> bool:
    expected = os.environ.get("OS1_WEB_LOGIN_PASSWORD", "")
    return configured() and secrets.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def make_cookie() -> str:
    if not configured():
        raise RuntimeError("web login not configured")
    nonce = secrets.token_urlsafe(18)
    issued = str(int(time.time()))
    message = f"v1.{issued}.{nonce}"
    mac = hmac.new(_key(), message.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
    return f"{message}.{signature}"


def verify_cookie(value: str) -> bool:
    if not configured() or not value or len(value) > 512:
        return False
    try:
        version, issued, nonce, signature = value.split(".")
        if version != "v1" or len(nonce) < 18:
            return False
        timestamp = int(issued)
        now = int(time.time())
        if timestamp > now + 30 or now - timestamp > TTL_SECONDS:
            return False
        message = f"{version}.{issued}.{nonce}"
        mac = hmac.new(_key(), message.encode("utf-8"), hashlib.sha256).digest()
        expected = base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")
        return secrets.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False
