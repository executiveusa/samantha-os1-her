"""What the client sees: phase, say-chips, background work, active voice.

Slice 1 publishes these as LiveKit participant attributes on the agent (the client
reads them from the room). Slice 2 moves them to the orchestrator's /os1/events bus;
callers only use this interface, so that swap is local to this file.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum

from livekit import rtc

log = logging.getLogger("os1.bus")


class Phase(StrEnum):
    PREFLIGHT = "preflight"
    OPERATOR_WELCOME = "operator_welcome"
    OPERATOR_Q1 = "operator_q1"
    OPERATOR_Q1_HESITANCE = "operator_q1_hesitance"
    OPERATOR_Q2 = "operator_q2"
    OPERATOR_Q3 = "operator_q3"
    INITIATING = "initiating"
    SAMANTHA_FIRST_MEETING = "samantha_first_meeting"
    ACTIVE = "active"
    ASLEEP = "asleep"


class Bus:
    def __init__(self, room: rtc.Room) -> None:
        self._room = room
        self._attrs: dict[str, str] = {}
        self.phase: Phase = Phase.PREFLIGHT

    async def _publish(self, **attrs: str) -> None:
        changed = {k: v for k, v in attrs.items() if self._attrs.get(k) != v}
        if not changed:
            return
        self._attrs.update(changed)
        try:
            await self._room.local_participant.set_attributes(changed)
        except Exception as exc:  # noqa: BLE001 - UI state must never break the voice loop
            log.warning("could not publish %s: %s", list(changed), exc)

    async def set_phase(self, phase: Phase) -> None:
        self.phase = phase
        log.info("phase -> %s", phase)
        await self._publish(**{"os1.phase": phase.value})

    async def set_chips(self, chips: list[str]) -> None:
        await self._publish(**{"os1.chips": json.dumps(chips)})

    async def set_work(self, items: list[dict]) -> None:
        await self._publish(**{"os1.work": json.dumps(items)})

    async def set_handoff(self, engine: str) -> None:
        """Tell the app to switch voice engines (e.g. to a Fish Live 3 session after onboarding)."""
        await self._publish(**{"os1.handoff": engine})

    async def set_voice(self, voice_key: str) -> None:
        await self._publish(**{"os1.voice": voice_key})

    @property
    def chips(self) -> list[str]:
        return json.loads(self._attrs.get("os1.chips", "[]"))
