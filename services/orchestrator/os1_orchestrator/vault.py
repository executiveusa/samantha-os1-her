"""Infisical Self-Managing Vault Client & Internal Key Rotator for Samantha OS¹.

Supports:
- Self-hosted Infisical Universal Auth (Machine Identity) via REST API
- Programmatic creation/rotation of internal OS1 service tokens (never exposes raw values over HTTP)
- Safe offline/local fallback so dev & tests work cleanly without a live Infisical server
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

log = logging.getLogger("os1.vault")

INTERNAL_KEY_SPECS: dict[str, int] = {
    "OS1_CLIENT_TOKEN": 32,
    "OS1_BRAIN_TOKEN": 32,
    "HERMES_API_KEY": 32,
    "COMPOSIO_WEBHOOK_SECRET": 32,
    "OPENCODE_SERVER_PASSWORD": 24,
    "LIVEKIT_API_SECRET": 32,
}

EXTERNAL_KEY_NAMES: tuple[str, ...] = (
    "OPENROUTER_API_KEYS",
    "NVIDIA_API_KEYS",
    "GROQ_API_KEYS",
    "CEREBRAS_API_KEYS",
    "FISH_API_KEY",
    "TS_AUTHKEY",
    "HOSTINGER_API_TOKEN",
    "ANTHROPIC_API_KEY",
)


@dataclass
class VaultConfig:
    url: str
    client_id: str
    client_secret: str
    project_id: str
    environment: str = "prod"
    secret_path: str = "/"

    @classmethod
    def from_env(cls) -> VaultConfig:
        return cls(
            url=os.environ.get("INFISICAL_URL", "http://infisical:8080").rstrip("/"),
            client_id=os.environ.get("INFISICAL_CLIENT_ID", "").strip(),
            client_secret=os.environ.get("INFISICAL_CLIENT_SECRET", "").strip(),
            project_id=os.environ.get("INFISICAL_PROJECT_ID", "").strip(),
            environment=os.environ.get("INFISICAL_ENV", "prod").strip() or "prod",
            secret_path=os.environ.get("INFISICAL_SECRET_PATH", "/").strip() or "/",
        )

    @property
    def configured(self) -> bool:
        return bool(self.url and self.client_id and self.client_secret and self.project_id)


class InfisicalVault:
    def __init__(self, config: VaultConfig | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        self.config = config or VaultConfig.from_env()
        self._client = client
        self._access_token: str | None = None
        self._last_rotation: str | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=12.0)
        return self._client

    async def authenticate(self) -> str:
        if not self.config.configured:
            raise RuntimeError("Infisical Universal Auth is not configured")
        resp = await self._http().post(
            f"{self.config.url}/api/v1/auth/universal-auth/login",
            json={
                "clientId": self.config.client_id,
                "clientSecret": self.config.client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = str(data.get("accessToken") or "")
        if not token:
            raise RuntimeError("Infisical login response missing accessToken")
        self._access_token = token
        return token

    async def _auth_headers(self) -> dict[str, str]:
        if not self._access_token:
            await self.authenticate()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def set_secret(self, key: str, value: str, *, comment: str = "Managed by Samantha OS1") -> dict[str, Any]:
        """Create or update a secret in Infisical (idempotent upsert)."""
        if not self.config.configured:
            os.environ[key] = value
            return {"key": key, "stored": "env-fallback"}

        headers = await self._auth_headers()
        payload = {
            "workspaceId": self.config.project_id,
            "environment": self.config.environment,
            "secretPath": self.config.secret_path,
            "secretValue": value,
            "type": "shared",
            "secretComment": comment,
        }
        url = f"{self.config.url}/api/v3/secrets/raw/{key}"
        resp = await self._http().post(url, headers=headers, json=payload)
        if resp.status_code in (400, 409):
            resp = await self._http().patch(url, headers=headers, json=payload)
        resp.raise_for_status()
        return {"key": key, "stored": "infisical"}

    async def list_secret_names(self) -> list[str]:
        if not self.config.configured:
            return sorted(k for k in (*INTERNAL_KEY_SPECS, *EXTERNAL_KEY_NAMES) if os.environ.get(k))
        headers = await self._auth_headers()
        resp = await self._http().get(
            f"{self.config.url}/api/v3/secrets/raw",
            headers=headers,
            params={
                "workspaceId": self.config.project_id,
                "environment": self.config.environment,
                "secretPath": self.config.secret_path,
            },
        )
        resp.raise_for_status()
        items = resp.json().get("secrets") or []
        return sorted(str(item.get("secretKey")) for item in items if item.get("secretKey"))

    async def rotate_internal_keys(self, keys: list[str] | None = None) -> dict[str, Any]:
        """Generate fresh cryptographic keys for allowed internal services and persist to Infisical."""
        target_keys = keys or list(INTERNAL_KEY_SPECS.keys())
        invalid = [k for k in target_keys if k not in INTERNAL_KEY_SPECS]
        if invalid:
            raise ValueError(f"Unsupported internal key(s): {', '.join(invalid)}")

        rotated: list[dict[str, Any]] = []
        for k in target_keys:
            nbytes = INTERNAL_KEY_SPECS[k]
            new_val = secrets.token_urlsafe(nbytes)
            res = await self.set_secret(k, new_val, comment="Auto-rotated by Samantha OS1 vault")
            rotated.append({"key": k, "stored": res["stored"]})

        self._last_rotation = datetime.now(UTC).isoformat()
        return {
            "ok": True,
            "rotated_at": self._last_rotation,
            "rotated": rotated,
        }

    def status(self) -> dict[str, Any]:
        """Safe status report — NEVER exposes secret values."""
        internal_present = {k: bool(os.environ.get(k)) for k in INTERNAL_KEY_SPECS}
        external_present = {
            k: bool(os.environ.get(k) or os.environ.get(k.removesuffix("S")))
            for k in EXTERNAL_KEY_NAMES
        }
        return {
            "infisical_configured": self.config.configured,
            "infisical_url": self.config.url,
            "environment": self.config.environment,
            "last_rotation": self._last_rotation,
            "internal_keys": internal_present,
            "external_keys": external_present,
            "missing_external_keys": [k for k, ok in external_present.items() if not ok],
        }
