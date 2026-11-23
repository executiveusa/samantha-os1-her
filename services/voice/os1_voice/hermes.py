"""Hermes API Server client for the voice worker: chat LLM wiring + Runs API."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("os1.hermes")


def new_session_id(prefix: str) -> str:
    return f"os1-{prefix}-{uuid.uuid4().hex[:12]}"


def voice_llm(settings: Settings, session_id: str) -> lk_openai.LLM:
    """LiveKit LLM that talks to Hermes's OpenAI-compatible endpoint.

    With ``X-Hermes-Session-Id`` set, Hermes loads history from its own state.db and
    only uses the last user message from the body; system messages become an
    ephemeral layer on top of SOUL.md (our per-turn instructions).
    """
    import openai
    from livekit.plugins import openai as lk_openai

    client = openai.AsyncClient(
        base_url=f"{settings.hermes_api_url.rstrip('/')}/v1",
        api_key=settings.hermes_api_key or "unset",
        default_headers={
            "X-Hermes-Session-Id": session_id,
            "X-Hermes-Session-Key": settings.session_key,
        },
        max_retries=0,
    )
    return lk_openai.LLM(
        model=settings.hermes_voice_model,
        client=client,
        extra_body={"model_options": {"reasoning": {"enabled": False}}},
    )


@dataclass
class RunEvent:
    event: str
    data: dict[str, Any]


class HermesRuns:
    """Background work on the main brain (Opus) via /v1/runs."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._http = httpx.AsyncClient(
            base_url=settings.hermes_api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.hermes_api_key}",
                "X-Hermes-Session-Key": settings.session_key,
            },
            timeout=httpx.Timeout(15.0, read=None),
        )

    async def start(self, task: str, *, instructions: str | None = None) -> str:
        body: dict[str, Any] = {
            "input": task,
            "model": self._s.hermes_work_model,
            # One Hermes session per independent task; memory scope is shared via the key.
            "session_id": new_session_id("work"),
        }
        if instructions:
            body["instructions"] = instructions
        resp = await self._http.post("/v1/runs", json=body, headers={"Idempotency-Key": uuid.uuid4().hex})
        resp.raise_for_status()
        return resp.json()["run_id"]

    async def events(self, run_id: str) -> AsyncIterator[RunEvent]:
        """SSE stream. Lines starting with ':' are keepalives and are skipped."""
        async with self._http.stream("GET", f"/v1/runs/{run_id}/events") as resp:
            resp.raise_for_status()
            event, data_lines = "message", []
            async for line in resp.aiter_lines():
                if not line:
                    if data_lines:
                        raw = "\n".join(data_lines)
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            data = {"text": raw}
                        # Hermes puts the name inside the JSON ("event": "run.completed"); accept
                        # "type" or an SSE `event:` line too.
                        name = (data.get("event") or data.get("type") or event) if isinstance(data, dict) else event
                        yield RunEvent(event=name, data=data)
                    event, data_lines = "message", []
                elif line.startswith(":"):
                    continue
                elif line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())

    async def status(self, run_id: str) -> dict[str, Any]:
        resp = await self._http.get(f"/v1/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()

    async def steer(self, run_id: str, text: str) -> None:
        (await self._http.post(f"/v1/runs/{run_id}/steer", json={"input": text})).raise_for_status()

    async def stop(self, run_id: str) -> None:
        (await self._http.post(f"/v1/runs/{run_id}/stop", json={})).raise_for_status()

    async def approve(self, run_id: str, request_id: str, generation: Any, choice: str) -> None:
        (
            await self._http.post(
                f"/v1/runs/{run_id}/approval",
                json={"request_id": request_id, "execution_generation": generation, "choice": choice},
            )
        ).raise_for_status()

    async def aclose(self) -> None:
        await self._http.aclose()
