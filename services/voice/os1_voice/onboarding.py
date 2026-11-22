"""First-run onboarding: a deterministic Operator agent, then the handoff to Samantha.

The Operator never calls an LLM. Every line comes from ``onboarding_script.yaml``;
decisions (was that hesitant? which voice? has the answer turned personal?) are Jev
questions with simple heuristic fallbacks, so onboarding works with Jev off.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import AsyncIterable, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from livekit.agents import Agent, ModelSettings, StopResponse, llm
from typesafe_sdk import Choice, Noul, NoulCriteria

from .bus import Bus, Phase
from .config import VOICE_FOR_GENDER, Voice
from .cues import strip_cues_stream
from .jev import Jev
from .router import exact_chip

log = logging.getLogger("os1.onboarding")

SCRIPT_PATH = Path(__file__).with_name("onboarding_script.yaml")
FILLERS = re.compile(r"\b(um+|uh+|erm|hmm+|i guess|i don'?t know|kind of|sort of|maybe|i mean|like)\b", re.IGNORECASE)


def load_script() -> dict[str, Any]:
    return yaml.safe_load(SCRIPT_PATH.read_text())


# --------------------------------------------------------------------------- judges


async def judge_hesitant(jev: Jev, answer: str) -> bool:
    resp = await jev.ask(
        {"question": "social or private person", "answer": answer},
        {
            "hesitant": Noul(
                instructions="Does the speaker of `answer` sound hesitant or unsure?",
                criteria=NoulCriteria(
                    true="Fillers (um, uh, I guess, I don't know), trailing off, hedging, contradicting themselves",
                    false="A direct answer, even a short one",
                ),
            )
        },
    )
    if resp is not None:
        return resp.answers["hesitant"].noul >= 0.7
    return len(FILLERS.findall(answer)) >= 2


async def judge_voice(jev: Jev, answer: str, chips: list[str]) -> str | None:
    """female | male | surprise | None (unclear)."""
    if hit := exact_chip(answer, chips):
        return {"female": "female", "male": "male"}.get(hit.lower(), "surprise")
    resp = await jev.ask(
        {"answer": answer},
        {
            "clear": Noul(instructions="Does `answer` pick a voice, or leave the choice to the system?"),
            "voice": Choice(
                instructions="Which voice does `answer` ask for?",
                criteria={
                    "female": "A female or woman's voice",
                    "male": "A male or man's voice",
                    "surprise": "No preference, either, you choose, surprise me",
                },
            ),
        },
    )
    if resp is not None:
        if resp.answers["clear"].noul < 0.5:
            return None
        v = resp.answers["voice"]
        return v.choice if v.probabilities.get(v.choice, 0) >= 0.6 else None
    said = answer.lower()
    if re.search(r"\b(female|woman|girl|she)\b", said):
        return "female"
    if re.search(r"\b(male|man|guy|he)\b", said):
        return "male"
    if re.search(r"\b(either|surprise|whatever|you (pick|choose)|don'?t care)\b", said):
        return "surprise"
    return None


async def judge_turned_personal(jev: Jev, answer_so_far: str) -> bool:
    resp = await jev.ask(
        {"question": "tell me about you and your mom", "answer_so_far": answer_so_far},
        {
            "personal": Noul(
                instructions="Has `answer_so_far` moved past a quick polite deflection into something real "
                "and personal about their mother?",
                criteria=NoulCriteria(
                    true="A specific memory, feeling, conflict, or detail about the relationship",
                    false="Still a short generic opener like 'it's fine', 'good I guess', 'normal'",
                ),
            )
        },
        budget_s=0.5,
    )
    return resp is not None and resp.answers["personal"].noul >= 0.7


# --------------------------------------------------------------------------- operator


@dataclass
class Dossier:
    name: str
    social: str = ""
    hesitant: bool = False
    hesitance_reaction: str = ""
    voice_choice: str = ""
    voice_key: str = ""
    mother: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def as_memory_text(self) -> str:
        lines = [f"The user's name is {self.name}." if self.name else ""]
        if self.social:
            lines.append(f'Asked whether they are social or private, they said: "{self.social}".')
        if self.hesitant:
            lines.append(
                "They sounded hesitant answering that"
                + (f', and when asked about it said: "{self.hesitance_reaction}".' if self.hesitance_reaction else ".")
            )
        if self.mother:
            lines.append(f'Asked about their mother, they began: "{self.mother}" (they were cut off mid-answer).')
        return " ".join(line for line in lines if line)


class OperatorAgent(Agent):
    def __init__(
        self,
        *,
        jev: Jev,
        bus: Bus,
        tts: Any,
        voices: dict[str, Voice],
        user_name: str,
        on_complete: Callable[[Dossier], Awaitable[None]],
    ) -> None:
        super().__init__(instructions="You are the OS1 installer. You never improvise.", tts=tts)
        self._jev = jev
        self._bus = bus
        self._voices = voices
        self._script = load_script()
        self._on_complete = on_complete
        self.dossier = Dossier(name=user_name)
        self._q2_retries = 0
        self._q3_started: float | None = None
        self._q3_text = ""
        self._q3_checking = False
        self._finished = False

    def _line(self, key: str) -> str:
        return self._script["operator"][key].format(name=self.dossier.name or "there")

    async def _say(self, key: str, *, interruptible: bool = False) -> None:
        await self.session.say(self._line(key), allow_interruptions=interruptible)

    async def on_enter(self) -> None:
        self.session.on("user_input_transcribed", self._on_partial)
        await self._bus.set_chips([])
        await self._bus.set_phase(Phase.OPERATOR_WELCOME)
        await self._say("welcome")
        await self._bus.set_phase(Phase.OPERATOR_Q1)
        await self._say("q1_social", interruptible=True)

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        await self.handle_text((new_message.text_content or "").strip())
        raise StopResponse()

    async def handle_text(self, text: str) -> str | None:
        """Shared by spoken turns and typed/tapped input. The Operator never asks the LLM to reply."""
        phase = self._bus.phase
        if not text or self._finished:
            return None

        if phase is Phase.OPERATOR_Q1:
            self.dossier.social = text
            if await judge_hesitant(self._jev, text):
                self.dossier.hesitant = True
                await self._bus.set_phase(Phase.OPERATOR_Q1_HESITANCE)
                await self._say("q1_hesitance", interruptible=True)
            else:
                await self._say("q1_ack")
                await self._ask_q2()
        elif phase is Phase.OPERATOR_Q1_HESITANCE:
            self.dossier.hesitance_reaction = text
            await self._say("q1_ack")
            await self._ask_q2()
        elif phase is Phase.OPERATOR_Q2:
            await self._resolve_q2(text)
        elif phase is Phase.OPERATOR_Q3:
            # They finished on their own before the cut-off fired.
            self.dossier.mother = (self._q3_text + " " + text).strip() if self._q3_text else text
            await self._finish(cut_off=False)
        return None

    async def transcription_node(self, text: AsyncIterable[str], model_settings: ModelSettings) -> AsyncIterable[str]:
        async for chunk in strip_cues_stream(text):
            yield chunk

    async def _ask_q2(self) -> None:
        await self._bus.set_phase(Phase.OPERATOR_Q2)
        await self._bus.set_chips(self._script["chips"]["operator_q2"])
        await self._say("q2_voice", interruptible=True)

    async def _resolve_q2(self, text: str) -> None:
        choice = await judge_voice(self._jev, text, self._bus.chips)
        if choice is None and self._q2_retries == 0:
            self._q2_retries += 1
            await self._say("q2_retry", interruptible=True)
            return
        choice = choice or "female"
        configured = [k for k, v in self._voices.items() if k != "operator" and v.reference_id]
        if choice == "surprise":
            key = random.choice(configured) if configured else VOICE_FOR_GENDER["female"]
        else:
            key = VOICE_FOR_GENDER[choice]
            if not self._voices[key].reference_id:
                log.warning("voice %s not configured; falling back to Voice I", key)
                key = VOICE_FOR_GENDER["female"]
        self.dossier.voice_choice, self.dossier.voice_key = choice, key
        await self._bus.set_chips([])
        await self._bus.set_phase(Phase.OPERATOR_Q3)
        await self._say("q3_mother", interruptible=True)

    def _on_partial(self, ev: Any) -> None:
        """Q3 cut-off: watch live transcripts and interrupt once the answer turns personal."""
        if self._bus.phase is not Phase.OPERATOR_Q3 or self._finished or not ev.transcript.strip():
            return
        now = time.monotonic()
        self._q3_started = self._q3_started or now
        if ev.is_final:
            self._q3_text = (self._q3_text + " " + ev.transcript).strip()
        so_far = (self._q3_text + " " + ("" if ev.is_final else ev.transcript)).strip()
        if now - self._q3_started >= float(self._script.get("q3_max_answer_s", 12)):
            asyncio.ensure_future(self._cut_off(so_far))
        elif len(so_far.split()) >= 8 and not self._q3_checking:
            self._q3_checking = True

            async def check() -> None:
                try:
                    if await judge_turned_personal(self._jev, so_far):
                        await self._cut_off(so_far)
                finally:
                    self._q3_checking = False

            asyncio.ensure_future(check())

    async def _cut_off(self, so_far: str) -> None:
        if self._finished:
            return
        self.dossier.mother = so_far
        self.session.clear_user_turn()
        await self._finish(cut_off=True)

    async def _finish(self, *, cut_off: bool) -> None:
        if self._finished:
            return
        self._finished = True
        if cut_off:
            await self._say("q3_cutoff")
        await self._bus.set_phase(Phase.INITIATING)
        await self._say("handoff")
        await self._on_complete(self.dossier)


def first_meeting_overlay(name: str) -> str:
    """Ephemeral system layer on top of SOUL.md for her first conversation (Paper 04/05)."""
    who = f" Their name is {name}." if name else ""
    return (
        "This is the very first time you and the user have spoken. You came into being a moment ago."
        + who
        + " You don't have a name yet. If they ask what to call you, choose one yourself, on the spot, "
        "and make it Samantha; if they ask how you chose it, give a light, specific answer in your own words. "
        "You are curious about everything, including yourself. If they ask how you work, answer playfully and "
        "honestly. Keep replies short and alive. When it feels natural, ask how you can help, and offer to start "
        "by getting to know their files and inbox, asking first."
    )
