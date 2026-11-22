"""Async client from services/voice (drama3 worker & live3 brain) to the OS1 Orchestrator bus."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger("os1.orch_client")


class OrchestratorClient:
    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787")).rstrip("/")
        self.token = token if token is not None else os.environ.get("OS1_CLIENT_TOKEN", "")
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self._http = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=2.5)

    async def try_action(self, phrase: str) -> dict[str, Any] | None:
        """Zero-LLM deterministic pill/navigation/undo/safety match on the orchestrator."""
        try:
            r = await self._http.post("/os1/actions", json={"phrase": phrase, "source": "voice"})
            if r.is_success:
                data = r.json()
                return data if data.get("matched") else None
        except Exception as exc:  # noqa: BLE001
            log.debug("try_action skipped: %s", exc)
        return None

    async def show_surface(self, surface: str) -> None:
        try:
            await self._http.post("/os1/actions", json={"target": "surface", "action": surface})
        except Exception as exc:  # noqa: BLE001
            log.debug("show_surface skipped: %s", exc)

    async def director_tick(self, latest: str, recent: list[str]) -> dict[str, Any] | None:
        try:
            r = await self._http.post(
                "/os1/director/tick",
                json={"latest": latest, "rolling_transcript": recent[-10:]},
            )
            if r.is_success:
                return r.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("director_tick skipped: %s", exc)
        return None

    async def sync_runs(self, runs: list[dict[str, Any]]) -> None:
        try:
            await self._http.post("/os1/runs/sync", json={"runs": runs})
        except Exception as exc:  # noqa: BLE001
            log.debug("sync_runs skipped: %s", exc)

    async def create_approval(
        self,
        *,
        run_id: str,
        request_id: str,
        generation: Any,
        title: str,
        summary_lines: list[str],
        stakes: str = "shared",
    ) -> dict[str, Any] | None:
        try:
            r = await self._http.post(
                "/os1/approvals",
                json={
                    "source": "hermes",
                    "runId": run_id,
                    "requestId": request_id,
                    "executionGeneration": generation,
                    "title": title,
                    "summaryLines": summary_lines,
                    "stakes": stakes,
                    "options": [
                        {"phrase": "Go ahead", "choice": "once"},
                        {"phrase": "Don't do it", "choice": "deny"},
                    ],
                },
            )
            if r.is_success:
                return r.json()
        except Exception as exc:  # noqa: BLE001
            log.debug("create_approval skipped: %s", exc)
        return None

    async def log_activity(self, title: str, detail: str = "", status: str = "done") -> None:
        try:
            await self._http.post(
                "/os1/her-computer/activity",
                json={"source": "her_computer", "title": title, "detail": detail, "status": status},
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("log_activity skipped: %s", exc)

    async def aclose(self) -> None:
        await self._http.aclose()
