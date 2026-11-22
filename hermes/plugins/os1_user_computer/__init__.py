"""Hermes plugin: os1_user_computer — bounded Cua Driver bridge to the user's Mac."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def handle_user_computer(args: dict[str, Any], **_kwargs: Any) -> str:
    base = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("OS1_CLIENT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "tool": str(args.get("tool", "status")),
        "arguments": args.get("arguments") or {},
        "requireApproval": bool(args.get("require_approval", True)),
        "description": str(args.get("description") or ""),
    }
    req = urllib.request.Request(
        f"{base}/os1/your-computer/call",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=95) as resp:
            return resp.read().decode() or "{}"
    except urllib.error.HTTPError as exc:
        return json.dumps({"ok": False, "status": exc.code, "error": exc.read().decode()[:400]})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": str(exc)})


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="os1_user_computer",
        toolset="os1",
        description="LAST RESORT ONLY: run a bounded Cua Driver action on the user's own Mac when a file/app exists only there. Always gated behind per-action approval and 'Let me drive' kill switch.",
        schema={
            "name": "os1_user_computer",
            "description": "Run a bounded Cua Driver tool on the user's Mac over the outbound tunnel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "e.g. list_files, open_app, read_note, click, type"},
                    "arguments": {"type": "object"},
                    "description": {"type": "string", "description": "Plain-language explanation shown to the user for approval"},
                    "require_approval": {"type": "boolean", "default": True},
                },
                "required": ["tool", "description"],
            },
        },
        handler=handle_user_computer,
    )
