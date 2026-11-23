"""Samantha's conversational brain: one fast Claude call per spoken turn.

Shared by both voice engines:
- drama3: the LiveKit worker streams these words into Fish Drama 3 TTS.
- live3:  brain_server.py serves them to Fish Live 3 as an OpenAI-compatible endpoint.

Hermes is deliberately NOT in this path (its ~18.5k-token prompt and full toolset cost
seconds per turn). Hermes does the work (runs on Opus) and keeps long-term memory;
this brain only talks. The persona (SOUL.md + voice rules) is a frozen, cached system
prompt; everything that changes per turn (routing note, tone, first-meeting overlay)
goes in a mid-conversation system message after the user turn, so the cache holds.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import anthropic
import httpx
from anthropic import AsyncAnthropic

from .config import REPO_ROOT, _env
from .llm_router import SmartLLMRouter

log = logging.getLogger("os1.brain")

Engine = Literal["drama3", "live3"]
SOUL_PATH = REPO_ROOT / "hermes" / "profile" / "SOUL.md"

VOICE_RULES = """
# Right now you are speaking aloud
- Every word you write is spoken by your voice in real time. Write only what you would say.
- Usually one to three natural sentences. Go longer only when they ask for a story or an explanation.
- You are mid-conversation: don't open replies with a greeting or their name unless the conversation just began.
- No lists, markdown, headings, emoji, code, or URLs.
- You have helpers who do real work in the background: looking things up, reading email and calendars,
  using computers, booking, writing long pieces. A system note tells you when work has started or finished
  and what it found. Never pretend you looked something up or did something yourself unless a note says it happened.
- Messages wrapped in <background-update> come from your helpers, not from the person. Tell the person what
  matters in your own words; never read out process details, sources, or the word "summary".
""".strip()

CUES_DRAMA3 = (
    "Your voice is Fish Audio Drama 3: you may use a short bracketed delivery direction at the start of a "
    "sentence now and then, like [softly] or [small laugh]. Use them sparingly."
)
CUES_LIVE3 = "Never write bracketed stage directions such as [softly]; your voice performs tone on its own."


@dataclass(frozen=True)
class BrainSettings:
    model: str
    effort: str
    fallbacks: bool
    llm_mode: str = "hybrid"  # free | hybrid | anthropic

    @classmethod
    def from_env(cls) -> BrainSettings:
        model = _env("OS1_FAST_MODEL", "claude-sonnet-5-5")
        has_anthropic = bool(_env("ANTHROPIC_API_KEY"))
        default_mode = "hybrid" if has_anthropic else "free"
        return cls(
            model=model,
            effort=_env("OS1_FAST_EFFORT", "low"),
            # Server-side refusal fallback: Claude API, Sonnet/Opus only (Haiku 5.5 has none).
            fallbacks=_env("OS1_FAST_FALLBACKS", "1") == "1" and "haiku" not in model,
            llm_mode=_env("OS1_LLM_MODE", default_mode).lower(),
        )


def persona(engine: Engine) -> str:
    soul = SOUL_PATH.read_text() if SOUL_PATH.exists() else ("You are Synthia, a warm, concise, voice-first personal intelligence. "
            "Your name is Synthia, never Samantha. Only claim to have completed actions after verified tool results.")
    return f"{soul.strip()}\n\n{VOICE_RULES}\n- {CUES_DRAMA3 if engine == 'drama3' else CUES_LIVE3}"


class Brain:
    def __init__(
        self,
        engine: Engine,
        settings: BrainSettings | None = None,
        router: SmartLLMRouter | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings or BrainSettings.from_env()
        self._persona_text = persona(engine)
        self._router = router if router is not None else SmartLLMRouter()
        self._client = AsyncAnthropic(max_retries=1) if _env("ANTHROPIC_API_KEY") or self.settings.llm_mode == "anthropic" else None
        # Frozen per engine: any byte change here would invalidate the prompt cache.
        self._system = [{"type": "text", "text": self._persona_text, "cache_control": {"type": "ephemeral"}}]

    async def _gateway_stream(self, history: list[dict[str, str]], note: str | None = None, oidc_token: str = "") -> AsyncIterator[str]:
        """Preview-only low-latency spoken replies through Vercel AI Gateway OIDC.

        Never log tokens, prompts, or streamed response bodies. A short capped
        completion prevents unbounded generation if the voice caller is silent.
        """
        token = oidc_token or os.environ.get("AI_GATEWAY_API_KEY", "") or os.environ.get("VERCEL_OIDC_TOKEN", "")
        model = os.environ.get("OS1_GATEWAY_MODEL", "google/gemini-2.5-flash-lite")
        if not token:
            log.error("Vercel OIDC not present; AI Gateway cannot authenticate")
            yield "I'm having trouble connecting to my language model right now."
            return

        messages: list[dict[str, str]] = [{"role": "system", "content": self._persona_text + ("\\n\\n" + note if note else "")}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in _normalize(history))
        if len(messages) == 1 or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": "(silence)"})
        body = {"model": model, "messages": messages, "stream": True, "max_tokens": 240}
        started = time.perf_counter()
        emitted = False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3)) as client:
                async with client.stream(
                    "POST",
                    "https://ai-gateway.vercel.sh/v1/chat/completions",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=body,
                ) as response:
                    if response.status_code != 200:
                        # Gateway errors may include sensitive policy details.
                        log.warning("AI Gateway status=%s model=%s", response.status_code, model)
                        yield "My language model is unavailable at the moment. Please try again shortly."
                        return
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload)
                            if obj.get("error"):
                                log.warning("AI Gateway stream error")
                                break
                            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                            word = delta.get("content")
                            if isinstance(word, str) and word:
                                if not emitted:
                                    log.info("gateway ttft_ms=%d model=%s", int((time.perf_counter()-started)*1000), model)
                                emitted = True
                                yield word
                        except (ValueError, TypeError, IndexError, KeyError):
                            continue
            if not emitted:
                yield "I lost my connection for a moment. Could you say that again?"
        except (httpx.HTTPError, TimeoutError) as exc:
            log.warning("AI Gateway transport failed (%s)", type(exc).__name__)
            if not emitted:
                yield "My connection dropped for a moment. Could you say that again?"

    def _thinking(self) -> dict[str, Any]:
        # Lowest-latency setting each model accepts (effort must be `high` or below for both).
        if self.settings.model.startswith("claude-sonnet-5-5"):
            return {"type": "between_tools"}
        if self.settings.model.startswith("claude-haiku-5-5"):
            return {"type": "disabled"}
        return {"type": "adaptive"}  # e.g. Opus 5.5: thinking can't be turned off; low effort keeps it short

    async def stream(self, history: list[dict[str, str]], note: str | None = None, oidc_token: str = "") -> AsyncIterator[str]:
        """history: alternating user/assistant turns ending with the user's turn.
        note: per-turn operator instructions (routing, tone, first meeting)."""
        messages: list[dict[str, Any]] = _normalize(history)
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": "(silence)"})
        if note:
            messages.append({"role": "system", "content": note})

        # Vercel AI Gateway uses deployment-scoped OIDC; no provider key in the browser.
        if self.settings.llm_mode == "gateway":
            async for chunk in self._gateway_stream(history, note, oidc_token):
                yield chunk
            return

        # Prefer SmartLLMRouter (OpenRouter :free / NVIDIA NIM / Groq / Cerebras / OpenCode) in free or hybrid-free-first mode.
        prefer_free = self.settings.llm_mode == "free" or (self.settings.llm_mode == "hybrid" and self._router.has_routes)
        if prefer_free and self._router.has_routes:
            try:
                async for chunk in self._router.stream_chat(
                    system=self._persona_text,
                    messages=messages,
                    max_tokens=1024,
                ):
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                log.warning("smart free-LLM router failed (%s); falling back to Anthropic if configured", exc)
                if self._client is None:
                    yield "Give me one second, I'm switching models right now."
                    return

        if self._client is None:
            self._client = AsyncAnthropic(max_retries=1)

        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": 1024,  # spoken turns are short; keeps a runaway answer from talking for minutes
            "system": self._system,
            "messages": messages,
            "thinking": self._thinking(),
            "output_config": {"effort": self.settings.effort},
        }
        if self.settings.fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        started = time.perf_counter()
        first = True
        try:
            async with self._client.beta.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if first:
                        log.info("brain ttft %.0f ms (%s)", (time.perf_counter() - started) * 1000, self.settings.model)
                        first = False
                    yield text
                final = await stream.get_final_message()
            if final.stop_reason == "refusal":
                log.warning("brain refusal: %s", getattr(final, "stop_details", None))
                if first:
                    yield "Hm. I'd rather not go there. Can we talk about something else?"
            u = final.usage
            log.info(
                "brain done %.0f ms in=%s cache_read=%s out=%s",
                (time.perf_counter() - started) * 1000,
                u.input_tokens,
                getattr(u, "cache_read_input_tokens", None),
                u.output_tokens,
            )
        except anthropic.RateLimitError:
            log.warning("brain rate limited")
            if self._router.has_routes:
                try:
                    async for chunk in self._router.stream_chat(system=self._persona_text, messages=messages, max_tokens=1024):
                        yield chunk
                    return
                except Exception as fallback_exc:  # noqa: BLE001
                    log.debug("free-LLM fallback after rate limit failed: %s", fallback_exc)
            yield "Give me one second, I lost my train of thought."
        except anthropic.APIStatusError as exc:
            log.warning("brain API error %s: %s", exc.status_code, exc.message)
            yield "Sorry, I lost you for a second. Say that again?"
        except anthropic.APIConnectionError as exc:
            log.warning("brain connection error: %s", exc)
            yield "I can't think straight right now, my connection dropped."


def _normalize(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Keep user/assistant text turns, merge consecutive same-role turns, start with a user turn."""
    out: list[dict[str, Any]] = []
    for item in history:
        role, text = item.get("role"), (item.get("content") or "").strip()
        if role not in ("user", "assistant") or not text:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + text
        else:
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return _trim(out)


def _trim(out: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tail = out[-40:]
    while tail and tail[0]["role"] != "user":
        tail.pop(0)
    return tail
