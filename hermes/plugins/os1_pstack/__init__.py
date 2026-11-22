"""Hermes plugin exposing Samantha's pstack self-building & self-updating workflow."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def _orch_call(path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    base = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("OS1_CLIENT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def pstack_plan(goal: str) -> dict[str, Any]:
    """Route a self-build or engineering goal through pstack poteto-mode."""
    return _orch_call("/os1/pstack/plan", method="POST", body={"goal": goal, "dry_run": True})


def pstack_self_update(goal: str, *, dry_run: bool = True) -> dict[str, Any]:
    """Dispatch a pstack self-update run to OpenCode on an isolated git branch."""
    return _orch_call("/os1/pstack/run", method="POST", body={"goal": goal, "dry_run": dry_run})


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="os1_pstack_plan",
        description="Plan a Samantha OS1 self-update or bugfix using Lauren Tan's pstack playbooks.",
        handler=pstack_plan,
    )
    ctx.register_tool(
        name="os1_pstack_self_update",
        description="Execute a pstack-governed self-update via OpenCode on an isolated git branch.",
        handler=pstack_self_update,
    )
