"""Hermes plugin for Bambu's Second Brain SQLite LLM Wiki & Knowledge Graph."""

from __future__ import annotations

import json
import os
import urllib.parse
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
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def wiki_search(query: str) -> dict[str, Any]:
    return _orch(f"/os1/wiki/search?q={urllib.parse.quote(query)}")


def wiki_ingest_second_brain(directory: str | None = None) -> dict[str, Any]:
    return _orch("/os1/wiki/ingest", method="POST", body={"directory": directory})


def wiki_recommend_connections() -> dict[str, Any]:
    return _orch("/os1/wiki/connections")


def register(ctx: Any) -> None:
    ctx.register_tool(name="os1_wiki_search", description="Search Bambu's SQLite LLM Wiki & Second Brain.", handler=wiki_search)
    ctx.register_tool(name="os1_wiki_ingest", description="Ingest Bambu's Second Brain / ICM folder into SQLite LLM Wiki.", handler=wiki_ingest_second_brain)
    ctx.register_tool(name="os1_wiki_connections", description="Find recommended cross-node connections across Bambu's wiki & projects.", handler=wiki_recommend_connections)
