"""Thin Jev (TypeSafe System One) wrapper with a hard latency budget.

Jev answers typed questions about a state in ~100 ms. It never generates speech and
never acts. Every caller must work when this returns ``None`` (no key, timeout,
rate limit, network error): the voice loop never waits on Jev.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, SystemOneResponse

from .config import Settings

log = logging.getLogger("os1.jev")


class Jev:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncTypeSafeClient | None = None
        if settings.jev_enabled:
            self._client = AsyncTypeSafeClient(
                api_key=settings.typesafe_api_key,
                model=settings.jev_model,
                timeout=settings.jev_budget_s + 0.5,
            )
        self._warned = False

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def ask(
        self,
        state: Mapping[str, Any],
        questions: Mapping[str, Any],
        *,
        budget_s: float | None = None,
    ) -> SystemOneResponse | None:
        if self._client is None or not questions:
            return None
        budget = budget_s if budget_s is not None else self._settings.jev_budget_s
        started = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                self._client.system_one(state=dict(state), questions=dict(questions)),
                timeout=budget,
            )
        except Exception as exc:  # noqa: BLE001 - any failure falls back
            if not self._warned:
                log.warning("jev unavailable, falling back (%s: %s)", type(exc).__name__, exc)
                self._warned = True
            return None
        log.debug("jev %s answered in %.0f ms", list(questions), (time.perf_counter() - started) * 1000)
        return resp

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
