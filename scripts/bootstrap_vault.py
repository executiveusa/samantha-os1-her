#!/usr/bin/env python3
"""Zero-Touch Key Generator & Infisical Vault Bootstrapper for Samantha OS¹.

Generates all internal cryptographic secrets, Infisical master secrets, self-hosted
LiveKit credentials, OpenCode server password, and Samantha's Ed25519 SSH keypair
for Hostinger VPS & Maus Bots control.

Writes ONLY to a gitignored staging directory (default: `.vault-staging/`).
Never prints secret values to stdout.

Usage:
    python scripts/bootstrap_vault.py
    python scripts/bootstrap_vault.py --rotate
    python scripts/bootstrap_vault.py --push-infisical
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

INTERNAL_GENERATORS = {
    "OS1_CLIENT_TOKEN": lambda: secrets.token_urlsafe(32),
    "OS1_BRAIN_TOKEN": lambda: secrets.token_urlsafe(32),
    "HERMES_API_KEY": lambda: secrets.token_urlsafe(32),
    "COMPOSIO_WEBHOOK_SECRET": lambda: secrets.token_urlsafe(32),
    "OPENCODE_SERVER_PASSWORD": lambda: secrets.token_urlsafe(24),
    "LIVEKIT_API_KEY": lambda: f"APIos1{secrets.token_hex(8)}",
    "LIVEKIT_API_SECRET": lambda: secrets.token_urlsafe(32),
    "INFISICAL_ENCRYPTION_KEY": lambda: secrets.token_hex(16),  # 32 hex chars
    "INFISICAL_AUTH_SECRET": lambda: base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
    "INFISICAL_DB_PASSWORD": lambda: secrets.token_urlsafe(24),
    "INFISICAL_REDIS_PASSWORD": lambda: secrets.token_urlsafe(24),
}

EXTERNAL_PLACEHOLDERS = {
    "OPENROUTER_API_KEYS": "# Comma-separated OpenRouter keys (free models work with $0 balance)",
    "NVIDIA_API_KEYS": "# NVIDIA NIM free tier key from build.nvidia.com",
    "GROQ_API_KEYS": "# Optional ultra-fast free tier key from console.groq.com",
    "CEREBRAS_API_KEYS": "# Optional ultra-fast free tier key from cloud.cerebras.ai",
    "GOOGLE_API_KEYS": "# Optional Gemini free tier key from aistudio.google.com",
    "FISH_API_KEY": "# Fish Audio Drama 3 / Live 3 API key",
    "FISH_OPERATOR_VOICE_ID": "# Fish Audio OS1 onboarding operator voice ID",
    "FISH_VOICE_1_ID": "# Fish Audio Samantha voice ID",
    "TS_AUTHKEY": "# Tailscale reusable/ephemeral auth key for 24/7 private HTTPS bridge",
    "HOSTINGER_API_TOKEN": "# Hostinger VPS API token for autonomous VM status/snapshots",
    "HOSTINGER_VM_ID": "# Hostinger VPS virtual machine ID",
    "HOSTINGER_SSH_HOST": "# Hostinger VPS IP or Tailscale hostname",
}


def _parse_existing_env(env_path: Path) -> dict[str, str]:
    existing: dict[str, str] = {}
    if not env_path.exists():
        return existing
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        existing[k.strip()] = v.strip()
    return existing


def _ensure_ssh_keypair(out_dir: Path, *, rotate: bool) -> dict[str, str]:
    priv = out_dir / "samantha_ed25519"
    pub = out_dir / "samantha_ed25519.pub"
    if rotate:
        for p in (priv, pub):
            if p.exists():
                p.unlink()
    if not priv.exists():
        ssh_keygen = shutil.which("ssh-keygen")
        if ssh_keygen:
            subprocess.run(
                [ssh_keygen, "-t", "ed25519", "-N", "", "-C", "samantha-os1@hostinger", "-f", str(priv)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                os.chmod(priv, 0o600)
            except OSError:
                pass
        else:
            return {"generated": "false", "reason": "ssh-keygen not found on PATH"}
    return {
        "generated": "true",
        "private_key_path": str(priv),
        "public_key_path": str(pub),
        "public_key": pub.read_text(encoding="utf-8").strip() if pub.exists() else "",
    }


def _push_to_infisical(secrets_map: dict[str, str]) -> dict[str, object]:
    url = os.environ.get("INFISICAL_URL", "").rstrip("/")
    cid = os.environ.get("INFISICAL_CLIENT_ID", "")
    csec = os.environ.get("INFISICAL_CLIENT_SECRET", "")
    pid = os.environ.get("INFISICAL_PROJECT_ID", "")
    env_slug = os.environ.get("INFISICAL_ENV", "prod")
    if not (url and cid and csec and pid):
        return {"pushed": False, "reason": "Set INFISICAL_URL, INFISICAL_CLIENT_ID, INFISICAL_CLIENT_SECRET, INFISICAL_PROJECT_ID"}

    login_req = urllib.request.Request(
        f"{url}/api/v1/auth/universal-auth/login",
        data=json.dumps({"clientId": cid, "clientSecret": csec}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(login_req, timeout=15) as resp:
        token = json.load(resp)["accessToken"]

    pushed_keys: list[str] = []
    for k, v in secrets_map.items():
        if not v:
            continue
        payload = json.dumps(
            {
                "workspaceId": pid,
                "environment": env_slug,
                "secretPath": "/",
                "secretValue": v,
                "type": "shared",
                "secretComment": "Bootstrapped by scripts/bootstrap_vault.py",
            }
        ).encode("utf-8")
        for method in ("POST", "PATCH"):
            req = urllib.request.Request(
                f"{url}/api/v3/secrets/raw/{k}",
                data=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method=method,
            )
            try:
                with urllib.request.urlopen(req, timeout=15):
                    pushed_keys.append(k)
                    break
            except urllib.error.HTTPError as exc:
                if method == "POST" and exc.code in (400, 409):
                    continue
                raise
    return {"pushed": True, "count": len(pushed_keys), "keys": pushed_keys}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Samantha OS1 self-managing Infisical vault & keys.")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / ".vault-staging"),
        help="Gitignored staging directory for generated secrets",
    )
    parser.add_argument("--rotate", action="store_true", help="Regenerate all internal keys and SSH keypair")
    parser.add_argument("--push-infisical", action="store_true", help="Push generated secrets to live Infisical instance")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    env_path = out_dir / "generated-secrets.env"
    manifest_path = out_dir / "vault-manifest.json"

    existing = {} if args.rotate else _parse_existing_env(env_path)
    generated: dict[str, str] = {}
    for key, gen in INTERNAL_GENERATORS.items():
        generated[key] = existing.get(key) or gen()

    ssh_info = _ensure_ssh_keypair(out_dir, rotate=args.rotate)

    lines = [
        "# Samantha OS1 — Auto-Generated Internal Secrets (GITIGNORED — NEVER COMMIT)",
        f"# Generated at: {datetime.now(UTC).isoformat()}",
        "",
        "# --- Auto-Generated Internal & Self-Hosted Infrastructure Secrets ---",
    ]
    for key, val in generated.items():
        lines.append(f"{key}={val}")

    lines.extend(
        [
            "",
            "# --- Local Defaults for 24/7 VPS Stack ---",
            "OS1_LLM_MODE=free",
            "OS1_ENABLE_DEV_RESET=0",
            "OPENCODE_BASE_URL=http://opencode:4096",
            "INFISICAL_URL=http://infisical:8080",
            "LIVEKIT_URL=ws://livekit:7880",
            f"SAMANTHA_SSH_KEY_PATH={ssh_info.get('private_key_path', '/run/secrets/samantha_ed25519')}",
            "",
            "# --- External Provider Keys (fill in Infisical or below before starting VPS stack) ---",
        ]
    )
    for key, comment in EXTERNAL_PLACEHOLDERS.items():
        lines.append(f"{key}={existing.get(key, '')}  {comment}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass

    push_result: dict[str, object] | None = None
    if args.push_infisical:
        push_result = _push_to_infisical(generated)

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "staging_dir": str(out_dir),
        "env_file": str(env_path),
        "internal_keys_generated": sorted(generated.keys()),
        "external_keys_schema": sorted(EXTERNAL_PLACEHOLDERS.keys()),
        "ssh_keypair": {
            "generated": ssh_info.get("generated") == "true",
            "public_key_path": ssh_info.get("public_key_path", ""),
            "public_key": ssh_info.get("public_key", ""),
        },
        "infisical_push": push_result,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Never print secret values — only safe metadata + public SSH key
    print(f"[OK] Bootstrapped {len(generated)} internal keys into {env_path}")
    print(f"[OK] Manifest written to {manifest_path}")
    if ssh_info.get("public_key"):
        print(f"[OK] Samantha SSH Public Key (add to Hostinger VPS ~/.ssh/authorized_keys):\n{ssh_info['public_key']}")
    if push_result:
        print(f"[OK] Infisical push result: {json.dumps(push_result)}")


if __name__ == "__main__":
    main()
