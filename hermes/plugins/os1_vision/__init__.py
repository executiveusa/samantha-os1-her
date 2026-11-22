"""Hermes plugin for VisionClaw AX-022 glasses, laptop camera, and holo-gestures."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def _orch(path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    base = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("OS1_CLIENT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def vision_status() -> dict[str, Any]:
    return _orch("/os1/vision/status")


def trigger_holo_gesture(gesture: str, source: str = "holo_command") -> dict[str, Any]:
    return _orch("/os1/vision/gesture", method="POST", body={"gesture": gesture, "source": source})


def register(ctx: Any) -> None:
    ctx.register_tool(name="os1_vision_status", description="Inspect VisionClaw glasses & laptop camera status and recent holo-gestures.", handler=vision_status)
    ctx.register_tool(name="os1_holo_gesture", description="Execute a VisionClaw holo-gesture command (open_palm, pinch, peace, point, fist, stretch, flick_left, flick_right).", handler=trigger_holo_gesture)
