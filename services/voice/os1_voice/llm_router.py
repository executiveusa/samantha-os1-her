"""Smart Free-LLM & Multi-Token Switcher for Samantha OS¹.

Routes real-time voice and background turns across free-tier OpenAI-compatible LLM
providers with:
- Multi-token rotation per provider (comma-separated keys, e.g. OPENROUTER_API_KEYS)
- Automatic 429 / 5xx cooldown and zero-downtime failover across providers
- EWMA TTFT latency scoring so the fastest healthy free model wins for voice
- Native support for:
    * OpenRouter free models (`:free` + `openrouter/free`)
    * NVIDIA NIM free tier (`https://integrate.api.nvidia.com/v1`)
    * OpenCode (`anomalyco/opencode`) headless server (`OPENCODE_BASE_URL`)
    * `open-free-llm-api/awesome-freellm-apis` providers (Cerebras, Groq, Gemini, Mistral, GitHub Models)
- Persistent HTTPX connection pooling to eliminate per-turn TLS handshake overhead.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("os1.llm_router")


@dataclass
class TokenSlot:
    key: str
    label: str
    cooldown_until: float = 0.0
    consecutive_errors: int = 0
    total_requests: int = 0

    def is_available(self, now: float) -> bool:
        return now >= self.cooldown_until

    def mark_error(self, now: float, *, status_code: int = 429, retry_after: float | None = None) -> None:
        self.consecutive_errors += 1
        if retry_after is not None and retry_after > 0:
            delay = min(retry_after, 300.0)
        elif status_code == 429:
            delay = min(15.0 * (2 ** min(self.consecutive_errors - 1, 4)), 240.0)
        else:
            delay = min(5.0 * (2 ** min(self.consecutive_errors - 1, 3)), 60.0)
        self.cooldown_until = now + delay

    def mark_success(self) -> None:
        self.consecutive_errors = 0
        self.cooldown_until = 0.0
        self.total_requests += 1


@dataclass
class ProviderRoute:
    name: str
    base_url: str
    models: list[str]
    tokens: list[TokenSlot] = field(default_factory=list)
    priority: int = 50  # lower = preferred
    requires_auth: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)
    ewma_ttft_ms: float = 450.0
    _token_cursor: int = 0
    _model_cursor: int = 0

    def next_token(self, now: float) -> TokenSlot | None:
        if not self.requires_auth and not self.tokens:
            return TokenSlot(key="", label="no-auth")
        if not self.tokens:
            return None
        n = len(self.tokens)
        for offset in range(n):
            idx = (self._token_cursor + offset) % n
            slot = self.tokens[idx]
            if slot.is_available(now):
                self._token_cursor = (idx + 1) % n
                return slot
        return None

    def current_model(self) -> str:
        if not self.models:
            return "openrouter/free"
        return self.models[self._model_cursor % len(self.models)]

    def rotate_model(self) -> None:
        if len(self.models) > 1:
            self._model_cursor = (self._model_cursor + 1) % len(self.models)

    def record_ttft(self, ttft_ms: float) -> None:
        alpha = 0.3
        self.ewma_ttft_ms = round((1 - alpha) * self.ewma_ttft_ms + alpha * ttft_ms, 1)

    def score(self, now: float) -> tuple[int, float]:
        available = 0 if self.next_token_peek(now) is not None else 1
        # Combine static priority tier with measured TTFT latency
        return (available, self.priority * 10.0 + self.ewma_ttft_ms)

    def next_token_peek(self, now: float) -> TokenSlot | None:
        if not self.requires_auth and not self.tokens:
            return TokenSlot(key="", label="no-auth")
        for slot in self.tokens:
            if slot.is_available(now):
                return slot
        return None


def _split_keys(*env_names: str) -> list[TokenSlot]:
    keys: list[str] = []
    for name in env_names:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)
    return [TokenSlot(key=k, label=f"key-{i + 1}") for i, k in enumerate(keys)]


def _split_models(env_name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return list(default)
    parsed = [m.strip() for m in raw.split(",") if m.strip()]
    return parsed or list(default)


def build_default_routes() -> list[ProviderRoute]:
    """Assemble free-tier LLM routes from environment + optional synced awesome-freellm-apis catalog."""
    routes: list[ProviderRoute] = []

    # 1. Cerebras free tier — fastest TTFT (~100ms) for voice presence
    cerebras_keys = _split_keys("CEREBRAS_API_KEYS", "CEREBRAS_API_KEY")
    if cerebras_keys:
        routes.append(
            ProviderRoute(
                name="cerebras-free",
                base_url=os.environ.get("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1").rstrip("/"),
                models=_split_models("CEREBRAS_MODELS", ["llama-3.3-70b", "llama3.1-8b"]),
                tokens=cerebras_keys,
                priority=10,
                ewma_ttft_ms=140.0,
            )
        )

    # 2. Groq free tier — ultra-fast LPU (~150ms TTFT)
    groq_keys = _split_keys("GROQ_API_KEYS", "GROQ_API_KEY")
    if groq_keys:
        routes.append(
            ProviderRoute(
                name="groq-free",
                base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
                models=_split_models("GROQ_MODELS", ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]),
                tokens=groq_keys,
                priority=15,
                ewma_ttft_ms=180.0,
            )
        )

    # 3. OpenRouter free models + multi-token switcher
    or_keys = _split_keys("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY")
    if or_keys:
        routes.append(
            ProviderRoute(
                name="openrouter-free",
                base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
                models=_split_models(
                    "OPENROUTER_FREE_MODELS",
                    [
                        "openrouter/free",
                        "meta-llama/llama-3.3-70b-instruct:free",
                        "google/gemma-3-27b-it:free",
                        "qwen/qwen3-235b-a22b:free",
                        "deepseek/deepseek-r1:free",
                    ],
                ),
                tokens=or_keys,
                priority=20,
                extra_headers={
                    "HTTP-Referer": os.environ.get("APP_URL", "https://github.com/executiveusa/samantha-os1-her"),
                    "X-Title": "Samantha OS1",
                },
                ewma_ttft_ms=320.0,
            )
        )

    # 4. NVIDIA NIM free tier (build.nvidia.com)
    nv_keys = _split_keys("NVIDIA_API_KEYS", "NVIDIA_API_KEY")
    if nv_keys:
        routes.append(
            ProviderRoute(
                name="nvidia-free",
                base_url=os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
                models=_split_models(
                    "NVIDIA_FREE_MODELS",
                    [
                        "meta/llama-3.3-70b-instruct",
                        "nvidia/llama-3.1-nemotron-ultra-253b-v1",
                        "deepseek-ai/deepseek-r1",
                    ],
                ),
                tokens=nv_keys,
                priority=25,
                ewma_ttft_ms=360.0,
            )
        )

    # 5. Google AI Studio (Gemini free tier OpenAI-compatible endpoint)
    google_keys = _split_keys("GOOGLE_API_KEYS", "GOOGLE_API_KEY")
    if google_keys:
        routes.append(
            ProviderRoute(
                name="google-free",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                models=_split_models("GOOGLE_FREE_MODELS", ["gemini-2.5-flash", "gemini-2.0-flash"]),
                tokens=google_keys,
                priority=30,
                ewma_ttft_ms=340.0,
            )
        )

    # 6. Mistral free tier (La Plateforme Experiment plan)
    mistral_keys = _split_keys("MISTRAL_API_KEYS", "MISTRAL_API_KEY")
    if mistral_keys:
        routes.append(
            ProviderRoute(
                name="mistral-free",
                base_url="https://api.mistral.ai/v1",
                models=_split_models("MISTRAL_FREE_MODELS", ["mistral-small-latest", "open-mistral-nemo"]),
                tokens=mistral_keys,
                priority=35,
                ewma_ttft_ms=390.0,
            )
        )

    # 7. OpenCode (anomalyco/opencode) headless server — always-available free models (OpenCode Zen)
    opencode_url = os.environ.get("OPENCODE_BASE_URL", "").strip().rstrip("/")
    if opencode_url:
        oc_keys = _split_keys("OPENCODE_API_KEY", "OPENCODE_SERVER_PASSWORD")
        routes.append(
            ProviderRoute(
                name="opencode-free",
                base_url=opencode_url if opencode_url.endswith("/v1") else f"{opencode_url}/v1",
                models=_split_models("OPENCODE_FREE_MODELS", ["opencode/big-pickle", "opencode/glm-4.7-free"]),
                tokens=oc_keys,
                priority=40,
                requires_auth=bool(oc_keys),
                ewma_ttft_ms=420.0,
            )
        )

    # 8. Optional dynamic overlay from scripts/sync_free_llms.py (awesome-freellm-apis)
    catalog_path = os.environ.get("OS1_FREE_LLM_CATALOG", "")
    if catalog_path and Path(catalog_path).exists():
        try:
            extra = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
            for item in extra.get("providers", []):
                env_var = str(item.get("api_key_env") or "")
                keys = _split_keys(env_var) if env_var else []
                if keys and item.get("base_url") and item.get("models") and not any(r.name == item["name"] for r in routes):
                    routes.append(
                        ProviderRoute(
                            name=str(item["name"]),
                            base_url=str(item["base_url"]).rstrip("/"),
                            models=[str(m) for m in item["models"]],
                            tokens=keys,
                            priority=int(item.get("priority", 45)),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("could not load OS1_FREE_LLM_CATALOG %s: %s", catalog_path, exc)

    return routes


class SmartLLMRouter:
    """Latency-aware, multi-token, multi-provider free LLM streamer with automatic failover."""

    def __init__(
        self,
        routes: list[ProviderRoute] | None = None,
        *,
        timeout_s: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.routes: list[ProviderRoute] = routes if routes is not None else build_default_routes()
        self.timeout_s = timeout_s
        self._client = client
        self._preferred_provider: str | None = None
        self.last_used: dict[str, Any] = {}

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def has_routes(self) -> bool:
        return bool(self.routes)

    def set_preferred(self, provider_name: str | None) -> bool:
        if provider_name is None:
            self._preferred_provider = None
            return True
        if any(r.name == provider_name for r in self.routes):
            self._preferred_provider = provider_name
            return True
        return False

    def ordered_routes(self, now: float | None = None) -> list[ProviderRoute]:
        ts = time.monotonic() if now is None else now
        ranked = sorted(self.routes, key=lambda r: r.score(ts))
        if self._preferred_provider:
            ranked.sort(key=lambda r: (0 if r.name == self._preferred_provider else 1, r.score(ts)))
        return ranked

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "preferred": self._preferred_provider,
            "last_used": self.last_used,
            "routes": [
                {
                    "name": r.name,
                    "base_url": r.base_url,
                    "active_model": r.current_model(),
                    "models": r.models,
                    "token_count": len(r.tokens),
                    "healthy_tokens": sum(1 for t in r.tokens if t.is_available(now)) if r.tokens else (0 if r.requires_auth else 1),
                    "ewma_ttft_ms": r.ewma_ttft_ms,
                    "priority": r.priority,
                }
                for r in self.ordered_routes(now)
            ],
        }

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream assistant text from the best healthy free-LLM route, rotating tokens/models on 429/5xx."""
        now = time.monotonic()
        candidates = self.ordered_routes(now)
        if not candidates:
            raise RuntimeError("No free LLM routes configured")

        payload_messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for m in messages:
            role = m.get("role", "user")
            content = str(m.get("content", ""))
            if content:
                payload_messages.append({"role": role, "content": content})

        errors: list[str] = []
        client = self._http()

        for route in candidates:
            # Try up to len(tokens) or 1 slot per route before failing over to next provider
            attempts = max(1, len(route.tokens))
            for _ in range(attempts):
                now = time.monotonic()
                slot = route.next_token(now)
                if slot is None:
                    break
                model = route.current_model()
                headers = {"Content-Type": "application/json", **route.extra_headers}
                if slot.key:
                    headers["Authorization"] = f"Bearer {slot.key}"

                body = {
                    "model": model,
                    "messages": payload_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": True,
                }
                started = time.perf_counter()
                emitted_any = False
                try:
                    async with client.stream("POST", f"{route.base_url}/chat/completions", headers=headers, json=body) as resp:
                        if resp.status_code >= 400:
                            retry_after_hdr = resp.headers.get("retry-after")
                            retry_after = float(retry_after_hdr) if retry_after_hdr and retry_after_hdr.isdigit() else None
                            slot.mark_error(time.monotonic(), status_code=resp.status_code, retry_after=retry_after)
                            if resp.status_code in (400, 404, 429, 502, 503):
                                route.rotate_model()
                            err_text = (await resp.aread()).decode("utf-8", errors="ignore")[:180]
                            errors.append(f"{route.name}/{model} ({slot.label}): HTTP {resp.status_code} {err_text}")
                            log.warning("llm_router failover %s/%s HTTP %s", route.name, model, resp.status_code)
                            continue

                        async for raw_line in resp.aiter_lines():
                            line = raw_line.strip()
                            if not line or not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = (choices[0].get("delta") or {}).get("content") or ""
                            if delta:
                                if not emitted_any:
                                    ttft_ms = (time.perf_counter() - started) * 1000
                                    route.record_ttft(ttft_ms)
                                    slot.mark_success()
                                    self.last_used = {
                                        "provider": route.name,
                                        "model": model,
                                        "token_label": slot.label,
                                        "ttft_ms": round(ttft_ms, 1),
                                    }
                                    log.info("llm_router ttft %.0f ms (%s / %s)", ttft_ms, route.name, model)
                                    emitted_any = True
                                yield delta

                        if emitted_any:
                            return
                        errors.append(f"{route.name}/{model}: empty stream")
                        route.rotate_model()
                except httpx.HTTPError as exc:
                    slot.mark_error(time.monotonic(), status_code=503)
                    errors.append(f"{route.name}/{model}: {type(exc).__name__}: {exc}")
                    log.warning("llm_router network failover %s/%s: %s", route.name, model, exc)
                    if emitted_any:
                        return

        raise RuntimeError(f"All free LLM routes failed: {'; '.join(errors[-4:])}")
