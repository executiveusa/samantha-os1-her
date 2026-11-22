"""The user's OS1 profile (name, onboarding state, chosen voice, onboarding dossier).

The orchestrator owns it (GET/PATCH /os1/profile). If the orchestrator is not
reachable, a local JSON file keeps development working.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("os1.profile")

LOCAL = Path(os.environ.get("OS1_STATE_DIR", Path.home() / ".os1")) / "profile.json"
DEFAULT: dict[str, Any] = {"name": "", "onboarded": False, "voice_key": "voice_1_warm", "dossier": {}}


class ProfileStore:
    def __init__(self, orchestrator_url: str, token: str) -> None:
        self._url = orchestrator_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def get(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                resp = await http.get(f"{self._url}/os1/profile", headers=self._headers)
                resp.raise_for_status()
                return {**DEFAULT, **resp.json()}
        except Exception as exc:  # noqa: BLE001
            log.info("orchestrator unavailable (%s); using %s", type(exc).__name__, LOCAL)
            return {**DEFAULT, **(json.loads(LOCAL.read_text()) if LOCAL.exists() else {})}

    async def patch(self, **fields: Any) -> None:
        try:
            async with httpx.AsyncClient(timeout=2.0) as http:
                resp = await http.patch(f"{self._url}/os1/profile", json=fields, headers=self._headers)
                resp.raise_for_status()
                return
        except Exception:  # noqa: BLE001
            current = json.loads(LOCAL.read_text()) if LOCAL.exists() else {}
            LOCAL.parent.mkdir(parents=True, exist_ok=True)
            LOCAL.write_text(json.dumps({**DEFAULT, **current, **fields}, indent=2))
