"""Hermes plugin for full GitHub access & cross-project graph reasoning."""

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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def github_sync_and_connect() -> dict[str, Any]:
    return _orch("/os1/github/sync-wiki", method="POST", body={})


def github_connections() -> dict[str, Any]:
    return _orch("/os1/github/connections")


def register(ctx: Any) -> None:
    ctx.register_tool(name="os1_github_sync_wiki", description="Index all Bambu GitHub repos into the SQLite LLM Wiki and link shared stacks.", handler=github_sync_and_connect)
    ctx.register_tool(name="os1_github_connections", description="Scan Bambu's GitHub + Second Brain graph for the best cross-project node connections.", handler=github_connections)
