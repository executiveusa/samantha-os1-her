"""Tests for SmartLLMRouter: OpenRouter token rotation, NVIDIA/OpenCode failover, and Brain integration."""

from __future__ import annotations

import asyncio
import json

import httpx

from os1_voice.brain import Brain, BrainSettings
from os1_voice.llm_router import ProviderRoute, SmartLLMRouter, TokenSlot


def _sse_body(*chunks: str) -> bytes:
    lines = []
    for c in chunks:
        lines.append(f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n")
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


def test_openrouter_token_rotation_on_429_and_failover_to_nvidia():
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization", ""))
        if "openrouter.ai" in str(request.url) and request.headers.get("authorization") == "Bearer or-key-1":
            return httpx.Response(429, headers={"retry-after": "30"}, text="rate limited")
        if "openrouter.ai" in str(request.url) and request.headers.get("authorization") == "Bearer or-key-2":
            return httpx.Response(503, text="upstream busy")
        if "integrate.api.nvidia.com" in str(request.url):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse_body("Hello ", "from ", "NVIDIA free tier."),
            )
        return httpx.Response(500, text="unexpected")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    router = SmartLLMRouter(
        routes=[
            ProviderRoute(
                name="openrouter-free",
                base_url="https://openrouter.ai/api/v1",
                models=["openrouter/free", "meta-llama/llama-3.3-70b-instruct:free"],
                tokens=[TokenSlot("or-key-1", "key-1"), TokenSlot("or-key-2", "key-2")],
                priority=10,
            ),
            ProviderRoute(
                name="nvidia-free",
                base_url="https://integrate.api.nvidia.com/v1",
                models=["meta/llama-3.3-70b-instruct"],
                tokens=[TokenSlot("nv-key-1", "key-1")],
                priority=20,
            ),
        ],
        client=client,
    )

    async def _run() -> str:
        out: list[str] = []
        async for tok in router.stream_chat(system="You are Samantha.", messages=[{"role": "user", "content": "Hi"}]):
            out.append(tok)
        await router.aclose()
        return "".join(out)

    text = asyncio.run(_run())
    assert text == "Hello from NVIDIA free tier."
    assert seen_auth == ["Bearer or-key-1", "Bearer or-key-2", "Bearer nv-key-1"]
    assert router.last_used["provider"] == "nvidia-free"

    # Status must never expose raw API keys
    status_str = json.dumps(router.status())
    assert "or-key-1" not in status_str
    assert "nv-key-1" not in status_str


def test_brain_uses_smart_free_router_without_anthropic_key():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_body("I'm right here."),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    router = SmartLLMRouter(
        routes=[
            ProviderRoute(
                name="opencode-free",
                base_url="http://opencode:4096/v1",
                models=["opencode/big-pickle"],
                tokens=[],
                requires_auth=False,
                priority=10,
            )
        ],
        client=client,
    )
    brain = Brain(
        "drama3",
        settings=BrainSettings(model="claude-sonnet-5-5", effort="low", fallbacks=False, llm_mode="free"),
        router=router,
    )

    async def _run() -> str:
        chunks = [c async for c in brain.stream([{"role": "user", "content": "Hey Samantha"}])]
        await router.aclose()
        return "".join(chunks)

    assert asyncio.run(_run()) == "I'm right here."
