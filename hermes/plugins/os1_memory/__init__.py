"""Hermes plugin: os1_memory — Memory Ledger remember/forget cascade."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _orch(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("OS1_CLIENT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode()[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _purge_hermes_markdown(terms: list[str]) -> list[str]:
    """Remove matching lines from Hermes MEMORY.md / USER.md so 'really gone' holds everywhere."""
    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    touched: list[str] = []
    lowered = [t.strip().lower() for t in terms if t.strip()]
    if not lowered:
        return touched
    for name in ("MEMORY.md", "USER.md"):
        p = hermes_home / name
        if not p.exists():
            continue
        lines = p.read_text().splitlines()
        kept = [ln for ln in lines if not any(term in ln.lower() for term in lowered)]
        if len(kept) != len(lines):
            p.write_text("\n".join(kept) + ("\n" if kept else ""))
            touched.append(str(p))
    return touched


def handle_remember(args: dict[str, Any], **_kwargs: Any) -> str:
    res = _orch(
        "POST",
        "/os1/memories",
        {
            "category": args.get("category", "things_you_love"),
            "summary": args.get("summary", ""),
            "detail": args.get("detail", ""),
            "source": "hermes",
        },
    )
    return json.dumps(res)


def handle_forget(args: dict[str, Any], **_kwargs: Any) -> str:
    query = str(args.get("query") or "")
    memory_id = args.get("memory_id")
    confirmed = bool(args.get("confirmed", False))
    res = _orch("POST", "/os1/memories/forget", {"memory_id": memory_id, "query": query, "confirmed": confirmed})
    if confirmed and res.get("ok"):
        terms = [query] + [d.get("summary", "") for d in res.get("deleted", [])]
        res["hermes_purged"] = _purge_hermes_markdown(terms)
    return json.dumps(res)


def handle_list_memories(args: dict[str, Any], **_kwargs: Any) -> str:
    q = str(args.get("query") or "")
    cat = str(args.get("category") or "")
    qs = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in (("category", cat), ("query", q)) if v)
    path = f"/os1/memories?{qs}" if qs else "/os1/memories"
    return json.dumps(_orch("GET", path))


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="os1_remember",
        toolset="os1",
        description="Save a meaningful dated moment to the OS1 Memory Ledger (People, Places, Things you love, Things that hurt, Promises).",
        schema={
            "name": "os1_remember",
            "description": "Persist a 1-2 sentence personal memory into the OS1 Memory Ledger.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["people", "places", "things_you_love", "things_that_hurt", "promises"],
                    },
                    "summary": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["category", "summary"],
            },
        },
        handler=handle_remember,
    )
    ctx.register_tool(
        name="os1_forget",
        toolset="os1",
        description="Forget a memory permanently. Always call with confirmed=false first to open the read-back modal unless the user just confirmed 'Yes, forget it'.",
        schema={
            "name": "os1_forget",
            "description": "Request or execute permanent deletion from both OS1 Memory Ledger and Hermes memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                    "query": {"type": "string"},
                    "confirmed": {"type": "boolean", "default": False},
                },
            },
        },
        handler=handle_forget,
    )
    ctx.register_tool(
        name="os1_list_memories",
        toolset="os1",
        description="Search or list saved moments in the OS1 Memory Ledger.",
        schema={
            "name": "os1_list_memories",
            "description": "Read entries from the OS1 Memory Ledger.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
        handler=handle_list_memories,
    )
