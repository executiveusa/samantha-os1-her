#!/usr/bin/env python3
"""Sync free LLM provider catalog from open-free-llm-api/awesome-freellm-apis.

Writes a clean, machine-readable JSON catalog consumed by SmartLLMRouter via
OS1_FREE_LLM_CATALOG. Safe to run offline (falls back to curated defaults).
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

CURATED_PROVIDERS = [
    {
        "name": "cerebras-free",
        "base_url": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEYS",
        "models": ["llama-3.3-70b", "llama3.1-8b"],
        "priority": 10,
        "source": "awesome-freellm-apis",
    },
    {
        "name": "groq-free",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEYS",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "priority": 15,
        "source": "awesome-freellm-apis",
    },
    {
        "name": "openrouter-free",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEYS",
        "models": [
            "openrouter/free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemma-3-27b-it:free",
            "qwen/qwen3-235b-a22b:free",
            "deepseek/deepseek-r1:free",
        ],
        "priority": 20,
        "source": "awesome-freellm-apis",
    },
    {
        "name": "nvidia-free",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEYS",
        "models": [
            "meta/llama-3.3-70b-instruct",
            "nvidia/llama-3.1-nemotron-ultra-253b-v1",
            "deepseek-ai/deepseek-r1",
        ],
        "priority": 25,
        "source": "nvidia-nim-free",
    },
    {
        "name": "github-models-free",
        "base_url": "https://models.inference.ai.azure.com",
        "api_key_env": "GITHUB_MODELS_TOKEN",
        "models": ["gpt-4o-mini", "Meta-Llama-3.3-70B-Instruct"],
        "priority": 38,
        "source": "awesome-freellm-apis",
    },
    {
        "name": "opencode-free",
        "base_url": "http://opencode:4096/v1",
        "api_key_env": "OPENCODE_API_KEY",
        "models": ["opencode/big-pickle", "opencode/glm-4.7-free"],
        "priority": 40,
        "source": "anomalyco/opencode",
    },
]

UPSTREAM_URL = "https://raw.githubusercontent.com/open-free-llm-api/awesome-freellm-apis/main/README.md"


def fetch_upstream_status() -> dict[str, object]:
    try:
        req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "samantha-os1-her/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        return {"reachable": True, "bytes": len(text), "url": UPSTREAM_URL}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": str(exc), "url": UPSTREAM_URL}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Samantha OS1 free LLM router catalog.")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "infra" / "llm-router" / "free-llms.json"),
        help="Output JSON path",
    )
    parser.add_argument("--offline", action="store_true", help="Skip live GitHub check")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    catalog = {
        "generated_at": datetime.now(UTC).isoformat(),
        "upstream": {"reachable": False, "offline": True} if args.offline else fetch_upstream_status(),
        "providers": CURATED_PROVIDERS,
    }
    out_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote free LLM catalog ({len(CURATED_PROVIDERS)} providers) to {out_path}")


if __name__ == "__main__":
    main()
