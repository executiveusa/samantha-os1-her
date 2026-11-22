"""Tailscale Bridge + Hostinger VPS API + Maus Bots Fleet Controller for Samantha OS¹.

Safety invariants:
- Read-only operations (status, logs, metrics, tailscale peer list) execute directly.
- Mutating operations (restart, deploy, stop, vps_reboot) require explicit `apply=True`
  AND a valid one-time approval_id when `require_approval=True` (enforced by app.py).
- SSH commands use strict argument lists (never shell=True injection) and an explicit
  allowlist of safe Docker / systemd / status actions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("os1.ops_bridge")

SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


@dataclass(frozen=True)
class MausBotSpec:
    name: str
    kind: str  # "docker" | "systemd"
    target: str  # container name or systemd unit name
    host: str = ""  # optional Tailscale/SSH host override
    repo_path: str = ""
    description: str = ""


def _validate_identifier(val: str, label: str) -> str:
    if not SAFE_NAME_RE.match(val):
        raise ValueError(f"Invalid {label}: {val!r}")
    return val


def load_maus_bots() -> dict[str, MausBotSpec]:
    """Load Maus Bots registry from MAUS_BOTS_CONFIG (JSON string or path to JSON file)."""
    raw = os.environ.get("MAUS_BOTS_CONFIG", "").strip()
    entries: list[dict[str, Any]] = []
    if raw:
        path = Path(raw)
        if path.exists() and path.is_file():
            entries = json.loads(path.read_text(encoding="utf-8"))
        else:
            try:
                entries = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("MAUS_BOTS_CONFIG is neither a valid file nor JSON")
    if not entries:
        # Sensible default fleet template so status/discovery works out of the box
        entries = [
            {
                "name": "maus-core",
                "kind": "docker",
                "target": "maus-core",
                "description": "Primary Maus Bot worker container",
            },
            {
                "name": "maus-scheduler",
                "kind": "docker",
                "target": "maus-scheduler",
                "description": "Maus Bot cron & job scheduler",
            },
        ]

    fleet: dict[str, MausBotSpec] = {}
    for item in entries:
        name = _validate_identifier(str(item["name"]), "bot name")
        kind = str(item.get("kind", "docker")).lower()
        if kind not in ("docker", "systemd"):
            raise ValueError(f"Unsupported bot kind for {name}: {kind}")
        target = _validate_identifier(str(item.get("target") or name), "bot target")
        fleet[name] = MausBotSpec(
            name=name,
            kind=kind,
            target=target,
            host=str(item.get("host") or ""),
            repo_path=str(item.get("repo_path") or ""),
            description=str(item.get("description") or ""),
        )
    return fleet


class OpsBridge:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self.hostinger_token = os.environ.get("HOSTINGER_API_TOKEN", "").strip()
        self.hostinger_vm_id = os.environ.get("HOSTINGER_VM_ID", "").strip()
        self.ssh_host = os.environ.get("HOSTINGER_SSH_HOST", "").strip()
        self.ssh_user = os.environ.get("HOSTINGER_SSH_USER", "root").strip()
        self.ssh_port = int(os.environ.get("HOSTINGER_SSH_PORT", "22"))
        self.ssh_key_path = os.environ.get("SAMANTHA_SSH_KEY_PATH", "").strip()
        self.tailscale_host = os.environ.get("TAILSCALE_HOSTNAME", "samantha").strip()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def status(self) -> dict[str, Any]:
        fleet = load_maus_bots()
        return {
            "tailscale_hostname": self.tailscale_host,
            "hostinger_api_configured": bool(self.hostinger_token),
            "hostinger_vm_id": self.hostinger_vm_id or None,
            "ssh_configured": bool(self.ssh_host and self.ssh_key_path),
            "ssh_target": f"{self.ssh_user}@{self.ssh_host}:{self.ssh_port}" if self.ssh_host else None,
            "maus_bots": [
                {
                    "name": b.name,
                    "kind": b.kind,
                    "target": b.target,
                    "host": b.host or self.ssh_host or "local-vps",
                    "description": b.description,
                }
                for b in fleet.values()
            ],
        }

    def build_bot_command(self, bot: MausBotSpec, action: str, *, tail_lines: int = 80) -> list[str]:
        """Build a strict, injection-safe command list for a Maus Bot action."""
        lines = max(10, min(int(tail_lines), 500))
        if bot.kind == "docker":
            match action:
                case "status":
                    return ["docker", "inspect", "--format", "{{.State.Status}} (started {{.State.StartedAt}})", bot.target]
                case "logs":
                    return ["docker", "logs", "--tail", str(lines), bot.target]
                case "restart":
                    return ["docker", "restart", bot.target]
                case "stop":
                    return ["docker", "stop", bot.target]
                case "start":
                    return ["docker", "start", bot.target]
                case _:
                    raise ValueError(f"Unsupported docker bot action: {action}")
        else:
            match action:
                case "status":
                    return ["systemctl", "is-active", bot.target]
                case "logs":
                    return ["journalctl", "-u", bot.target, "-n", str(lines), "--no-pager"]
                case "restart":
                    return ["systemctl", "restart", bot.target]
                case "stop":
                    return ["systemctl", "stop", bot.target]
                case "start":
                    return ["systemctl", "start", bot.target]
                case _:
                    raise ValueError(f"Unsupported systemd bot action: {action}")

    async def run_ssh_command(self, remote_argv: list[str], *, host_override: str = "", dry_run: bool = False) -> dict[str, Any]:
        host = host_override or self.ssh_host
        if not host:
            return {"ok": False, "dry_run": dry_run, "error": "HOSTINGER_SSH_HOST is not configured", "command": remote_argv}

        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
            "-p", str(self.ssh_port),
        ]
        if self.ssh_key_path:
            ssh_cmd.extend(["-i", self.ssh_key_path])
        ssh_cmd.append(f"{self.ssh_user}@{host}")
        ssh_cmd.extend(remote_argv)

        if dry_run:
            return {"ok": True, "dry_run": True, "command": ssh_cmd}

        proc = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25.0)
        except TimeoutError:
            proc.kill()
            return {"ok": False, "error": "SSH command timed out after 25s", "command": remote_argv}

        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="ignore")[-4000:],
            "stderr": stderr.decode("utf-8", errors="ignore")[-1500:],
        }

    async def control_bot(self, bot_name: str, action: str, *, dry_run: bool = False, tail_lines: int = 80) -> dict[str, Any]:
        fleet = load_maus_bots()
        bot = fleet.get(bot_name)
        if bot is None:
            raise KeyError(f"Unknown Maus Bot: {bot_name}")
        cmd = self.build_bot_command(bot, action, tail_lines=tail_lines)
        result = await self.run_ssh_command(cmd, host_override=bot.host, dry_run=dry_run)
        return {"bot": bot.name, "action": action, "kind": bot.kind, **result}

    async def hostinger_vps_info(self) -> dict[str, Any]:
        """Query Hostinger VPS REST API for VM status and IP/metrics."""
        if not self.hostinger_token:
            return {"ok": False, "configured": False, "error": "HOSTINGER_API_TOKEN is not configured"}
        url = (
            f"https://developers.hostinger.com/api/vps/v1/virtual-machines/{self.hostinger_vm_id}"
            if self.hostinger_vm_id
            else "https://developers.hostinger.com/api/vps/v1/virtual-machines"
        )
        resp = await self._http().get(url, headers={"Authorization": f"Bearer {self.hostinger_token}"})
        if resp.status_code >= 400:
            return {"ok": False, "status_code": resp.status_code, "error": resp.text[:300]}
        return {"ok": True, "configured": True, "data": resp.json()}
