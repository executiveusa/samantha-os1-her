"""Async Composio v3 Tool Router client for OS1 Orchestrator.

Uses Composio v3 Tool Router sessions (`POST /api/v3/tool_router/session`), which support:
- Zero-setup Managed OAuth Connect Links (`POST /session/{sid}/link`)
- Connected account status sync (`GET /api/v3/connected_accounts`)
- Direct tool execution (`POST /session/{sid}/execute`) for Gmail fetch / trash / untrash
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("os1.composio")

BASE_URL = "https://backend.composio.dev"


class ComposioClient:
    def __init__(self, *, api_key: str | None = None, user_id: str | None = None) -> None:
        self._api_key = api_key
        self._user_id = user_id
        self._session_id: str | None = None

    @property
    def api_key(self) -> str:
        return self._api_key if self._api_key is not None else os.environ.get("COMPOSIO_API_KEY", "").strip()

    @property
    def user_id(self) -> str:
        return self._user_id if self._user_id is not None else os.environ.get("OS1_SESSION_KEY", "os1-primary")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "Content-Type": "application/json"}

    async def ensure_session(self, *, force_new: bool = False) -> str:
        if self._session_id and not force_new:
            return self._session_id
        async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers(), timeout=15.0) as client:
            r = await client.post("/api/v3/tool_router/session", json={"user_id": self.user_id})
            r.raise_for_status()
            self._session_id = str(r.json()["session_id"])
            return self._session_id

    async def create_connect_link(self, toolkit: str) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "configured": False, "message": "COMPOSIO_API_KEY is not configured."}
        try:
            sid = await self.ensure_session()
            async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers(), timeout=15.0) as client:
                r = await client.post(
                    f"/api/v3/tool_router/session/{sid}/link",
                    json={"toolkit": toolkit.lower()},
                )
                data = r.json()
                if r.is_success:
                    return {
                        "ok": True,
                        "configured": True,
                        "toolkit": toolkit.lower(),
                        "redirect_url": data.get("redirect_url"),
                        "connected_account_id": data.get("connected_account_id"),
                        "link_token": data.get("link_token"),
                    }
                return {"ok": False, "configured": True, "error": data}
        except Exception as exc:  # noqa: BLE001
            log.warning("create_connect_link(%s) failed: %s", toolkit, exc)
            return {"ok": False, "configured": True, "error": str(exc)}

    async def list_active_toolkits(self) -> dict[str, dict[str, Any]]:
        """Return `{toolkit_slug: {id, status, account_label}}` for active connected accounts."""
        if not self.configured:
            return {}
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers(), timeout=15.0) as client:
                r = await client.get("/api/v3/connected_accounts", params={"user_ids": self.user_id, "limit": 50})
                if not r.is_success:
                    return {}
                out: dict[str, dict[str, Any]] = {}
                for item in r.json().get("items") or []:
                    status = str(item.get("status") or "").upper()
                    if status != "ACTIVE":
                        continue
                    tk = item.get("toolkit")
                    slug = (tk.get("slug") if isinstance(tk, dict) else str(tk or "")).lower()
                    if slug:
                        out[slug] = {
                            "id": item.get("id"),
                            "status": status,
                            "account_label": str(item.get("label") or item.get("user_id") or "Connected"),
                        }
                return out
        except Exception as exc:  # noqa: BLE001
            log.debug("list_active_toolkits failed: %s", exc)
            return {}

    async def execute_tool(self, tool_slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "COMPOSIO_API_KEY is not configured."}
        try:
            sid = await self.ensure_session()
            async with httpx.AsyncClient(base_url=BASE_URL, headers=self._headers(), timeout=25.0) as client:
                r = await client.post(
                    f"/api/v3/tool_router/session/{sid}/execute",
                    json={"tool_slug": tool_slug, "arguments": arguments},
                )
                data = r.json()
                if r.is_success:
                    return {"ok": True, "data": data}
                # If a newly connected account wasn't visible in a cached session, retry once with a fresh session.
                if r.status_code == 400 and "No active connection" in str(data):
                    sid = await self.ensure_session(force_new=True)
                    r2 = await client.post(
                        f"/api/v3/tool_router/session/{sid}/execute",
                        json={"tool_slug": tool_slug, "arguments": arguments},
                    )
                    if r2.is_success:
                        return {"ok": True, "data": r2.json()}
                    return {"ok": False, "status": r2.status_code, "error": r2.json()}
                return {"ok": False, "status": r.status_code, "error": data}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def fetch_gmail_inbox(self, limit: int = 12) -> dict[str, Any]:
        """Fetch recent Gmail inbox messages and normalize them into OS1 Spatial Inbox tiles."""
        res = await self.execute_tool("GMAIL_FETCH_EMAILS", {"max_results": limit, "query": "in:inbox"})
        if not res.get("ok"):
            return res
        payload = res.get("data") or {}
        inner = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        raw_msgs = inner.get("messages") or inner.get("emails") or []
        items: list[dict[str, Any]] = []
        for idx, m in enumerate(raw_msgs[:limit], start=1):
            if not isinstance(m, dict):
                continue
            preview = m.get("preview")
            snippet = (
                preview.get("body")
                if isinstance(preview, dict)
                else (m.get("snippet") or m.get("messageText") or "")
            )
            sender = str(m.get("sender") or m.get("from") or "Unknown").strip()
            # Clean display name from "Name <email@domain>"
            if "<" in sender:
                name_part = sender.split("<", 1)[0].strip().strip('"')
                sender = name_part or sender.split("<", 1)[1].rstrip(">")
            items.append(
                {
                    "id": str(m.get("messageId") or m.get("id") or f"gmail_{idx}"),
                    "number": idx,
                    "sender": sender,
                    "subject": str(m.get("subject") or "(No subject)").strip(),
                    "snippet": str(snippet or "").strip()[:240],
                    "received_at": str(m.get("messageTimestamp") or m.get("date") or ""),
                }
            )
        return {"ok": True, "items": items}

    async def trash_gmail(self, message_ids: list[str]) -> list[dict[str, Any]]:
        results = []
        for mid in message_ids:
            results.append(await self.execute_tool("GMAIL_MOVE_TO_TRASH", {"message_id": mid}))
        return results

    async def untrash_gmail(self, message_ids: list[str]) -> list[dict[str, Any]]:
        results = []
        for mid in message_ids:
            results.append(await self.execute_tool("GMAIL_UNTRASH", {"message_id": mid}))
        return results
