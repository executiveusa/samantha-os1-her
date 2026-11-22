"""Hermes plugin for Hostinger VPS, Tailscale, Infisical Vault, and Maus Bots control."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def _orch_call(path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    base = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("OS1_CLIENT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def ops_status() -> dict[str, Any]:
    """Inspect Tailscale, Hostinger VPS, and Maus Bots fleet status."""
    return _orch_call("/os1/ops/status")


def vault_status() -> dict[str, Any]:
    """Check Infisical self-managing vault health and configured key names (never returns secrets)."""
    return _orch_call("/os1/vault/status")


def control_maus_bot(
    bot_name: str,
    action: str = "status",
    *,
    dry_run: bool = False,
    approval_id: str | None = None,
) -> dict[str, Any]:
    """Run status/logs/restart/start/stop on a Maus Bot (mutations require approval_id)."""
    return _orch_call(
        f"/os1/ops/bots/{bot_name}",
        method="POST",
        body={"action": action, "dry_run": dry_run, "approval_id": approval_id},
    )


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="os1_ops_status",
        description="Get Hostinger VPS, Tailscale bridge, and Maus Bots fleet status.",
        handler=ops_status,
    )
    ctx.register_tool(
        name="os1_vault_status",
        description="Check Infisical self-managing vault status and missing external keys.",
        handler=vault_status,
    )
    ctx.register_tool(
        name="os1_control_maus_bot",
        description="Inspect or control a Maus Bot over Hostinger SSH/Tailscale (mutations require confirmation).",
        handler=control_maus_bot,
    )
